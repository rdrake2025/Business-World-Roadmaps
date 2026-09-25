"""Sender — sends what you approved, at sensible hours, so you never tap Send.

Approving an email was only half the job: it then sat until someone opened
the console and tapped Send, and a batch paced ninety seconds apart kept the
phone busy for half an hour. Now approving is the whole job. Answers to
people who wrote in go out between 7am and 9pm your time; cold emails on
weekdays between 8am and 5pm, when owners read them.

Nothing about what may be sent changes. The same send path runs, with the
warm-up cap, the bounce brake, the suppression list and the sending
blockers, plus the DNS check the doctor applies, which a phone send skipped.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone

from .. import automation, calls
from .base import Agent

log = logging.getLogger("answerrank.sender")

WARM_HOURS = (7, 21)
COLD_HOURS = (8, 17)


class SenderAgent(Agent):
    name = "sender"
    description = "Sends what you approved, at the right hours, so you never tap Send."
    interval = 15 * 60

    def __init__(self, store, settings, background: bool = True):
        super().__init__(store, settings)
        self.background = background

    def _dns_blockers(self) -> list[str]:
        """The doctor's DNS check, cached for six hours: it is a network call."""
        from ..mailer import check_dns_readiness

        raw = self.store.kv_get("sender.dns")
        now = datetime.now(timezone.utc)
        if raw:
            try:
                cached = json.loads(raw)
                if now - datetime.fromisoformat(cached["at"]) < timedelta(hours=6):
                    return cached["blockers"]
            except (ValueError, KeyError, TypeError):
                pass
        domain = (self.settings.from_email or "").split("@")[-1]
        blockers = check_dns_readiness(domain, self.settings.email_provider) if domain else []
        self.store.kv_set("sender.dns", json.dumps(
            {"at": now.isoformat(timespec="seconds"), "blockers": blockers}))
        return blockers

    def execute(self) -> tuple[int, str]:
        from ..mailer import SMTPConfig
        from ..sending import send_batch

        if getattr(self.settings, "demo_mode", False):
            return 0, "demo mode: sending stays manual"
        if not automation.enabled(self.store, "auto_send"):
            return 0, "automatic sending is off; approved emails wait for you to tap Send"
        queue = self.store.send_queue(500)
        if not queue:
            return 0, "nothing approved to send"
        if not SMTPConfig.from_env().configured():
            return 0, "no mailbox saved yet (Keys and settings), so nothing can send"

        local = calls.local_in(calls.operator_tz(self.settings))
        warm_ok = WARM_HOURS[0] <= local.hour < WARM_HOURS[1]
        cold_ok = local.weekday() < 5 and COLD_HOURS[0] <= local.hour < COLD_HOURS[1]
        warm = sum(1 for m in queue if (m.kind or "cold") != "cold")
        cold = len(queue) - warm
        want = (warm if warm_ok else 0) + (cold if cold_ok else 0)
        if not want:
            return 0, f"{len(queue)} approved, waiting for sending hours"

        blockers = self._dns_blockers()
        if blockers:
            return 0, f"not sending yet: {blockers[0]}"

        only = None if (warm_ok and cold_ok) else ("warm" if warm_ok else "cold")
        limit = min(want, 25)

        def run() -> None:
            try:
                result = send_batch(self.store, self.settings, limit=limit, only=only)
                log.info("sender: %s sent, %s failed", result.get("sent"), result.get("failed"))
            except Exception:  # noqa: BLE001 - never take the fleet down
                log.exception("sender: batch failed")

        if self.background:
            threading.Thread(target=run, daemon=True, name="answerrank-sender").start()
        else:
            run()
        what = {"warm": "answers", "cold": "cold emails", None: "emails"}[only]
        return limit, f"sending {limit} approved {what}"
