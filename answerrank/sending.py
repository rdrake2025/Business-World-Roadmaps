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

import time
from typing import Any, Callable

from .mailer import Mailer
from .models import now_iso


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

    pol = settings.outreach
    remaining = pol.max_emails_total_per_day - store.sends_today()
    if remaining <= 0:
        return {"sent": 0, "failed": 0, "blocked": True,
                "reasons": [f"Daily cap reached ({pol.max_emails_total_per_day}). "
                            f"Try tomorrow."],
                "errors": [], "dry_run": dry_run}

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
            "sends_today": store.sends_today(),
            "daily_cap": pol.max_emails_total_per_day}
