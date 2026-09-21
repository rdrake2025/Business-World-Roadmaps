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
               on_event: Callable[[str], None] | None = None) -> dict[str, Any]:
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
                                  throttle_seconds, say)
    finally:
        _SEND_LOCK.release()


def _send_batch_locked(store, settings, limit: int, dry_run: bool,
                       throttle_seconds: float | None,
                       say: Callable[[str], None]) -> dict[str, Any]:
    pol = settings.outreach
    days_sending = _days_warming(store, settings)
    cap = pol.warmup_cap(days_sending)
    remaining = cap - store.sends_today()
    if remaining <= 0:
        note = pol.warmup_note(days_sending)
        return {"sent": 0, "failed": 0, "blocked": True,
                "reasons": [f"Today's cap of {cap} is used up. {note}"],
                "errors": [], "dry_run": dry_run,
                "warmup_day": days_sending + 1, "daily_cap": cap}

    approved = store.get_messages("approved", min(limit, remaining))
    if not approved:
        return {"sent": 0, "failed": 0, "blocked": False,
                "reasons": ["No approved messages. Approve some first."],
                "errors": [], "dry_run": dry_run}

    mailer = Mailer(settings)
    by_id = {p.id: p for p in store.get_prospects(limit=10_000)}
    gap = pol.min_seconds_between_sends if throttle_seconds is None else throttle_seconds

    sent = failed = skipped = 0
    errors: list[str] = []

    for m in approved:
        # Re-read rather than trusting the count taken before the loop. A
        # throttled batch can run for an hour, which is long enough to cross
        # midnight — and the cap is a per-day figure.
        if not dry_run and store.sends_today() >= cap:
            say(f"  stopping: daily cap of {cap} reached mid-batch")
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

        if dry_run:
            say(f"  [dry-run] would send to {email}: {m.subject}")
            sent += 1
            continue

        ok, detail = mailer.send(email, m.subject, m.body)
        if ok:
            m.status, m.sent_at = "sent", now_iso()
            prospect.touches += 1
            prospect.last_touch_at = now_iso()
            prospect.stage = "contacted" if m.sequence_step == 1 else "following_up"
            store.upsert_prospect(prospect)
            # Without this the system can act but never learn.
            store.record_outcome(
                prospect_id=prospect.id, message_id=m.id,
                vertical=prospect.business.vertical, step=m.sequence_step,
                kind="sent", note=m.subject[:120])
            sent += 1
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
            failed += 1
            errors.append(f"{email}: {detail}")
            say(f"  failed {email}: {detail}")

        store.save_message(m)
        if gap and not dry_run:
            time.sleep(gap)

    return {"sent": sent, "failed": failed, "skipped": skipped, "blocked": False,
            "reasons": [], "errors": errors[:5], "dry_run": dry_run,
            "sends_today": store.sends_today(), "daily_cap": cap,
            "warmup_day": days_sending + 1,
            "warmup_note": pol.warmup_note(days_sending)}
