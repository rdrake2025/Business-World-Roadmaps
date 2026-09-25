"""The one place a message actually leaves the building.

The CLI and the phone console both sent mail, with separate copies of the
same loop. They had already drifted: one throttled between sends and the
other did not, one marked suppressed recipients and the other silently
skipped them. Two implementations of a compliance-critical path is a defect
waiting for a bad day, so there is now one.

Everything that protects the sending domain lives here — preflight, the daily
cap, suppression, throttling, bounce handling — and so does the outcome
record, which is what lets the Analyst measure anything at all.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .mailer import Mailer
from .models import now_iso

#: Only one batch may be in flight at a time.
#:
#: The daily cap is read once, before the loop, and then trusted for the
#: whole batch. That was safe while sending was a command someone typed. It
#: is not safe now that the fleet runs in a thread beside the web server: an
#: Outreach tick and a tap on the console's Send button read the same "12 of
#: 40 used" and both send 28. Overshooting a warm-up cap is the specific
#: thing the ramp exists to prevent, and the damage — a throttled sending
#: domain — takes weeks to undo.
_SEND_LOCK = threading.Lock()


#: Where the ramp's start date lives once the first real send has happened.
WARMUP_KEY = "sending.warmup_start"


def _days_warming(store, settings) -> int:
    """Days since this domain first sent anything.

    The date is recorded in the database on the first real send rather than
    configured by hand, because a warm-up that can be reset by editing a file
    is a warm-up that will be reset the first time the cap feels slow.
    """
    from datetime import date

    stamp = store.kv_get(WARMUP_KEY) or getattr(settings, "warmup_start", "") or ""
    if not stamp:
        return 0
    try:
        started = date.fromisoformat(stamp[:10])
    except ValueError:
        return 0
    return max(0, (date.today() - started).days)


def _begin_warmup(store) -> None:
    """Stamp day one, once, on the first message that actually goes out."""
    from datetime import date

    if not store.kv_get(WARMUP_KEY):
        store.kv_set(WARMUP_KEY, date.today().isoformat())


def send_batch(store, settings, limit: int = 25, dry_run: bool = False,
               throttle_seconds: float | None = None,
               extra_checks: list[str] | None = None,
               on_event: Callable[[str], None] | None = None,
               only: str | None = None) -> dict[str, Any]:
    """Deliver up to ``limit`` approved messages. Returns what happened.

    ``extra_checks`` lets the CLI add its DNS readiness check, which the
    console cannot run. Anything in it blocks the batch exactly like a
    preflight failure — a caller can add conditions, never remove them.
    """
    from .agents.outreach import OutreachAgent

    def say(line: str) -> None:
        if on_event:
            on_event(line)

    blockers = OutreachAgent(store, settings).preflight() + list(extra_checks or [])
    if blockers:
        return {"sent": 0, "failed": 0, "blocked": True, "reasons": blockers,
                "errors": [], "dry_run": dry_run}

    if not _SEND_LOCK.acquire(blocking=False):
        return {"sent": 0, "failed": 0, "blocked": True,
                "reasons": ["A send is already running. Wait for it to finish."],
                "errors": [], "dry_run": dry_run}
    try:
        return _send_batch_locked(store, settings, limit, dry_run,
                                  throttle_seconds, say, only)
    finally:
        _SEND_LOCK.release()


#: Stages in which a prospect is still in the cold sequence. A cold message
#: to anyone outside these is withdrawn at the moment of sending, whatever
#: was approved when: they replied, bought, or asked us to stop.
COLD_STAGES = {"discovered", "audited", "queued", "contacted", "following_up"}

#: Evidence needed before a bounce rate means anything. At 50 sends, one
#: unlucky bounce is already 2%: the first version of this brake tripped in
#: the simulation on 2 bounces out of 52 and paused prospecting for two weeks
#: over noise. A brake that fires on noise gets switched off, which is worse
#: than no brake.
BOUNCE_SAMPLE_MIN = 100
BOUNCE_COUNT_MIN = 3


def bounce_blocker(store, settings, days: int = 14) -> str:
    """Why cold sending must stop, or "" if it may continue.

    The mailer has always promised "a hard stop when bounce or complaint
    rates drift toward the enforcement thresholds", and the ceiling has
    always been in the config — but nothing read it. Bounces are the one
    rate this system can measure for itself, so this enforces that one.
    """
    counts = store.outcome_counts(days)
    sent, bounced = counts.get("sent", 0), counts.get("bounced", 0)
    attempts = sent + bounced
    if attempts < BOUNCE_SAMPLE_MIN or bounced < BOUNCE_COUNT_MIN:
        return ""
    rate = bounced / attempts
    ceiling = settings.outreach.bounce_rate_ceiling
    if rate >= ceiling:
        return (f"Cold sending paused: {bounced} of {attempts} messages bounced in "
                f"the last {days} days ({rate:.1%}), at or over the {ceiling:.0%} "
                f"ceiling mailbox providers throttle at. Replies to people who "
                f"wrote to you still go out. Check where these addresses came from "
                f"before sending more.")
    return ""


def _send_batch_locked(store, settings, limit: int, dry_run: bool,
                       throttle_seconds: float | None,
                       say: Callable[[str], None],
                       only: str | None = None) -> dict[str, Any]:
    pol = settings.outreach
    days_sending = _days_warming(store, settings)
    cap = pol.warmup_cap(days_sending)
    note = pol.warmup_note(days_sending)

    # The warm-up cap governs cold volume. A reply to someone who wrote to
    # us, a report they asked for, or a welcome to a paying client is not
    # what the ramp protects against — and holding a new client's welcome
    # until tomorrow because cold outreach spent today's budget is exactly
    # backwards.
    cold_room = cap - store.cold_sends_today()
    cold_block = bounce_blocker(store, settings)

    queue = store.send_queue(limit if not only else 500)
    if only == "warm":
        queue = [m for m in queue if (m.kind or "cold") != "cold"][:limit]
    elif only == "cold":
        queue = [m for m in queue if (m.kind or "cold") == "cold"][:limit]
    if not queue:
        return {"sent": 0, "failed": 0, "blocked": False,
                "reasons": ["No approved messages. Approve some first."],
                "errors": [], "dry_run": dry_run}
    if all(m.kind == "cold" for m in queue) and (cold_room <= 0 or cold_block):
        reason = cold_block or f"Today's cap of {cap} is used up. {note}"
        return {"sent": 0, "failed": 0, "blocked": True, "reasons": [reason],
                "errors": [], "dry_run": dry_run,
                "warmup_day": days_sending + 1, "daily_cap": cap}

    mailer = Mailer(settings)
    by_id = {p.id: p for p in store.get_prospects(limit=10_000)}
    gap = pol.min_seconds_between_sends if throttle_seconds is None else throttle_seconds

    sent = failed = skipped = withdrawn = cold_sent = 0
    errors: list[str] = []
    reasons: list[str] = []

    for m in queue:
        cold = (m.kind or "cold") == "cold"
        if cold:
            if cold_block:
                reasons.append(cold_block)
                break
            # Re-read rather than trusting the count taken before the loop. A
            # throttled batch can run for an hour, which is long enough to
            # cross midnight — and the cap is a per-day figure. A dry run
            # records nothing, so it counts for itself.
            used = (cap - cold_room + cold_sent) if dry_run else store.cold_sends_today()
            if used >= cap:
                say(f"  stopping: daily cap of {cap} reached mid-batch")
                reasons.append(f"Today's cap of {cap} is used up. {note}")
                break

        prospect = by_id.get(m.prospect_id)
        if not prospect or not prospect.business.email:
            skipped += 1
            continue
        email = prospect.business.email

        if store.is_suppressed(email):
            m.status = "suppressed"
            store.save_message(m)
            skipped += 1
            say(f"  skipped {email}: on the suppression list")
            continue

        if cold and prospect.stage not in COLD_STAGES:
            # Approved days ago, overtaken since. "Closing the loop — last
            # note from me" to someone who said yes yesterday, or who is now
            # paying, costs more than the sequence could ever earn.
            m.status = "superseded"
            store.save_message(m)
            withdrawn += 1
            say(f"  withdrew cold message to {email}: they are now '{prospect.stage}'")
            continue

        if dry_run:
            say(f"  [dry-run] would send to {email}: {m.subject}")
            sent += 1
            cold_sent += cold
            continue

        ok, detail = mailer.send(email, m.subject, m.body)
        if ok:
            m.status, m.sent_at = "sent", now_iso()
            prospect.last_touch_at = now_iso()
            if cold:
                prospect.touches += 1
                prospect.stage = "contacted" if m.sequence_step == 1 else "following_up"
                # Without this the system can act but never learn. Only cold
                # sends count: the funnel measures replies per cold email,
                # and counting our own answers would dilute it.
                store.record_outcome(
                    prospect_id=prospect.id, message_id=m.id,
                    vertical=prospect.business.vertical, step=m.sequence_step,
                    kind="sent", note=m.subject[:120])
            store.upsert_prospect(prospect)
            sent += 1
            cold_sent += cold
            _begin_warmup(store)
            say(f"  sent to {email}")
        else:
            bounced = "bounce" in detail.lower()
            m.status = "bounced" if bounced else "drafted"
            if bounced:
                store.suppress(email, detail)
                store.record_outcome(
                    prospect_id=prospect.id, message_id=m.id,
                    vertical=prospect.business.vertical, step=m.sequence_step,
                    kind="bounced", note=detail[:200])
                if cold:
                    prospect.stage = "suppressed"
                    prospect.notes = (prospect.notes or "") + " | bounced"
                    store.upsert_prospect(prospect)
            failed += 1
            errors.append(f"{email}: {detail}")
            say(f"  failed {email}: {detail}")

        store.save_message(m)
        if gap and not dry_run:
            time.sleep(gap)

    return {"sent": sent, "failed": failed, "skipped": skipped,
            "withdrawn": withdrawn, "blocked": False,
            "reasons": reasons[:1], "errors": errors[:5], "dry_run": dry_run,
            "sends_today": store.sends_today(), "daily_cap": cap,
            "warmup_day": days_sending + 1,
            "warmup_note": note}
