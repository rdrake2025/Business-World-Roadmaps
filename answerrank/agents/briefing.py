"""Briefing — your day in one email, and a tap on the shoulder when it matters.

Knowing what needed doing meant opening the console. Now it comes to you:

* **Every morning** (Monday to Saturday, from 7am your time): the Up next
  list in order, yesterday's numbers, and the month against the target.
* **As it happens**: someone wrote back ready to buy or asking for their
  report, a client paid, or cold sending paused itself. Those can't wait
  for tomorrow's briefing.

It goes to the briefing address (Keys and settings), or the mailbox you
send from. The reply reader ignores mail from your own address, so a
briefing never looks like a customer reply.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import calls
from .base import Agent

ALERT_INTENTS = {"ready_to_buy": "is ready to start", "interested": "wants the report"}


class BriefingAgent(Agent):
    name = "briefing"
    description = "Emails you the day's list each morning, and alerts when it matters."
    interval = 15 * 60

    def __init__(self, store, settings, mailer=None):
        super().__init__(store, settings)
        self._mailer = mailer

    # ------------------------------------------------------------------
    def recipient(self) -> str:
        import os
        return ((getattr(self.settings, "briefing_email", "") or "").strip()
                or os.environ.get("SMTP_USERNAME", "") or self.settings.from_email)

    def mailer(self):
        if self._mailer is None:
            from ..mailer import Mailer
            self._mailer = Mailer(self.settings)
        return self._mailer

    def _send(self, subject: str, body: str) -> bool:
        ok, detail = self.mailer().send(self.recipient(), subject, body)
        self.store.kv_set("briefing.last_error", "" if ok else detail)
        return ok

    def console(self) -> str:
        return f"{(self.settings.website or '').rstrip('/')}/app"

    # ------------------------------------------------------------------
    def digest(self, now: datetime | None = None) -> tuple[str, str]:
        from .. import today
        from .bookkeeper import BookkeeperAgent

        now = now or datetime.now(timezone.utc)
        up = today.next_actions(self.store, self.settings, now=now)
        urgent = [i for i in up["items"] if i["tone"] != "info"]
        counts = self.store.outcome_counts(days=1)
        call_counts = up["calls_today"]
        kpis = BookkeeperAgent(self.store, self.settings).kpis()

        if urgent:
            subject = "Today: " + "; ".join(i["title"] for i in urgent[:2])
            if len(urgent) > 2:
                subject += f" (+{len(urgent) - 2} more)"
        else:
            subject = "Today: nothing needs you yet"
        lines = ["Good morning. Here's today, most urgent first:", ""]
        if up["items"]:
            for n, item in enumerate(up["items"], 1):
                lines.append(f"{n}. {item['title']}")
                lines.append(f"   {item['detail']}")
        else:
            lines.append("Nothing needs you. The fleet is finding and checking businesses.")
        lines += [
            "",
            "Yesterday: "
            f"{counts.get('sent', 0)} emails sent, {counts.get('replied', 0)} replies, "
            f"{call_counts['calls']} calls ({call_counts['spoke']} spoke, "
            f"{call_counts['reports']} reports, {call_counts['booked']} booked), "
            f"{counts.get('paid', 0)} paid.",
            f"This month: ${kpis['profit']:,.0f} profit of ${kpis['target']:,.0f} "
            f"({kpis['pct_to_target']:.0f}%), {int(kpis['active_clients'])} paying clients.",
            "",
            f"Open your console: {self.console()}",
        ]
        return subject[:140], "\n".join(lines)

    def alerts(self, since: str) -> list[tuple[str, str]]:
        """(subject, body) for everything worth interrupting you for since then.

        Each event is alerted once, remembered by id rather than by a time
        cut-off: a reply logged in the same second as the last check would
        otherwise fall through the gap.
        """
        import json

        try:
            done = set(json.loads(self.store.kv_get("briefing.alerted") or "[]"))
        except ValueError:
            done = set()
        fresh: list[str] = []
        out = []
        prospects = {p.id: p for p in self.store.get_prospects(limit=10_000)}
        clients = {c.id: c for s in ("active", "past_due", "awaiting_payment")
                   for c in self.store.get_clients(s)}
        for row in self.store.outcomes_with_prefix("replied", days=2):
            if row["occurred_at"] < since or row["id"] in done \
                    or row.get("sentiment") not in ALERT_INTENTS:
                continue
            fresh.append(row["id"])
            p = prospects.get(row["prospect_id"])
            name = p.business.name if p else "Someone"
            out.append((f"{name} {ALERT_INTENTS[row['sentiment']]}",
                        f"They wrote: \"{(row.get('note') or '')[:280]}\"\n\n"
                        f"The answer is drafted and waiting for you to approve:\n"
                        f"{self.console()}"))
        for row in self.store.outcomes_with_prefix("paid", days=2):
            if row["occurred_at"] < since or row["id"] in done:
                continue
            fresh.append(row["id"])
            c = clients.get(row["prospect_id"])
            name = c.business.name if c else "A client"
            out.append((f"{name} paid", f"{name} paid ({row.get('note') or ''}). The "
                        f"welcome email is being drafted; approve it today, the gap "
                        f"between paying and hearing from you is where second thoughts "
                        f"live.\n\n{self.console()}"))
        from ..sending import bounce_blocker
        blocked = bounce_blocker(self.store, self.settings)
        last = self.store.kv_get("briefing.bounce_alert") or ""
        today_iso = datetime.now(timezone.utc).date().isoformat()
        if blocked and last != today_iso:
            self.store.kv_set("briefing.bounce_alert", today_iso)
            out.append(("Cold sending paused itself", f"{blocked}\n\n{self.console()}"))
        if fresh:
            self.store.kv_set("briefing.alerted", json.dumps((list(done) + fresh)[-300:]))
        return out

    # ------------------------------------------------------------------
    def execute(self) -> tuple[int, str]:
        from ..mailer import SMTPConfig

        if getattr(self.settings, "demo_mode", False):
            return 0, "demo mode: no briefings"
        if self._mailer is None and not SMTPConfig.from_env().configured():
            return 0, "no mailbox saved yet, so no briefing"

        now = datetime.now(timezone.utc)
        sent = 0
        # Set once, on the first run, so nothing from before the briefing
        # existed is alerted; after that each event is alerted exactly once.
        since = self.store.kv_get("briefing.alerts_since")
        if not since:
            self.store.kv_set("briefing.alerts_since", now.isoformat(timespec="seconds"))
        else:
            for subject, body in self.alerts(since):
                sent += self._send(subject, body)

        local = calls.local_in(calls.operator_tz(self.settings), now)
        today_local = local.date().isoformat()
        if local.weekday() != 6 and local.hour >= 7 \
                and self.store.kv_get("briefing.digest_date") != today_local:
            subject, body = self.digest(now)
            if self._send(subject, body):
                self.store.kv_set("briefing.digest_date", today_local)
                sent += 1
        return sent, (f"sent {sent} briefing email(s) to {self.recipient()}"
                      if sent else "nothing new to tell you")
