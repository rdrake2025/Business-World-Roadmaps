"""Guardian — the part of Autopilot that knows when to stop.

A business that sends email on its own needs something watching that isn't
the thing sending. Every other agent is judged on getting its job done; the
Guardian is judged only on whether it noticed, in time, that something was
going wrong, and whether it stopped the right part and told you.

What it watches, and what it does:

* **Complaints.** Mailbox providers act on spam reports (Gmail's line is
  0.3% of mail reported, and the aim is under 0.1%). You can't see the
  reports, but you can see the replies that say it: "this is spam",
  "reporting you". Three of those in a week pauses prospecting until you
  look. So does more than 5% of a week's first emails answered "remove
  me", which says the targeting is off. An unsubscribe on its own is
  healthy: it's what you want people to do instead of reporting you.
  It does not resume by itself: the copy or the targeting is wrong, and
  only a person can say which.
* **Bounces.** The send path already refuses cold email over the bounce
  ceiling. The Guardian makes that visible as a pause, and lifts it by
  itself once the rate is back under the line.
* **Things waiting for you.** Answers it wasn't sure of, held for more than
  a day. A person who asked a question and heard nothing is a lost sale.
* **Agents failing.** Any agent whose last three runs failed.
* **The mailbox failing.** A send that errored (not a bounce) in the last
  day: usually a changed password.
* **Mail from strangers** that matched nobody: often a referral or a
  client writing from a new address.
* **API spend** over the month's budget.

Everything it finds is emailed to you once a day at most, per problem, and
shown on the phone.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .. import automation
from .base import Agent

OPT_OUT_LIMIT = 0.05
OPT_OUT_SAMPLE = 50
HOSTILE_LIMIT = 3
WAITING_HOURS = 24
#: After you resume prospecting, the week that caused the pause is still in
#: the numbers; this long before the same week can pause it again.
GRACE_DAYS = 3


class GuardianAgent(Agent):
    name = "guardian"
    description = "Watches Autopilot and pauses any part that starts going wrong."
    interval = 30 * 60

    def __init__(self, store, settings, mailer=None):
        super().__init__(store, settings)
        self._mailer = mailer

    # ------------------------------------------------------------------ checks
    def _since(self, days: float) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")

    def opt_outs(self) -> tuple[int, int, int]:
        """(first emails sent, asked to stop, angry) over the last seven days."""
        since = self._since(7)
        sent = sum(1 for r in self.store.outcomes_with_prefix("sent", days=8)
                   if r["kind"] == "sent" and r["occurred_at"] >= since)
        replies = [r for r in self.store.outcomes_with_prefix("replied", days=8)
                   if r["occurred_at"] >= since]
        stop = sum(1 for r in replies if r.get("sentiment") in {"unsubscribe", "hostile"})
        angry = sum(1 for r in replies if r.get("sentiment") == "hostile")
        return sent, stop, angry

    def check_prospecting(self) -> list[tuple[str, str]]:
        """Pause or resume first emails. Returns alerts (key, text)."""
        from ..sending import bounce_blocker

        out = []
        stage = "prospecting"
        kind = self.store.kv_get("guardian.kind.prospecting") or ""
        bounced = bounce_blocker(self.store, self.settings)
        if bounced and not automation.paused(self.store, stage):
            automation.pause(self.store, stage, f"Too many emails bouncing. {bounced}")
            self.store.kv_set("guardian.kind.prospecting", "bounces")
            out.append(("pause.bounces", f"First emails are paused: too many are "
                                         f"bouncing. {bounced}"))
        elif not bounced and kind == "bounces" and automation.paused(self.store, stage):
            automation.resume(self.store, stage)
            self.store.kv_set("guardian.kind.prospecting", "")
            out.append(("resume.bounces", "Bounces are back under the line, so first "
                                          "emails have started again by themselves."))

        grace = self.store.kv_get("guardian.grace.prospecting") or ""
        if grace and grace > datetime.now(timezone.utc).isoformat(timespec="seconds"):
            return out
        sent, stop, angry = self.opt_outs()
        rate = stop / sent if sent else 0.0
        too_many = sent >= OPT_OUT_SAMPLE and rate > OPT_OUT_LIMIT
        if (too_many or angry >= HOSTILE_LIMIT) and not automation.paused(self.store, stage):
            why = (f"{stop} of the {sent} businesses emailed this week asked to stop "
                   f"({rate:.1%}, over the 5% line)" if too_many else
                   f"{angry} replies this week called it spam or worse")
            automation.pause(self.store, stage, f"Paused: {why}.")
            self.store.kv_set("guardian.kind.prospecting", "opt_outs")
            out.append(("pause.opt_outs",
                        f"First emails are paused: {why}. Mailbox providers treat "
                        f"that as complaints, and complaints decide whether any of "
                        f"your email is delivered. Check the trade and cities you "
                        f"picked (Keys and settings) and read a few of the latest "
                        f"first emails, then tap Resume on the phone."))
        return out

    def check_waiting(self) -> list[tuple[str, str]]:
        cutoff = self._since(WAITING_HOURS / 24)
        warm = [m for m in self.store.get_messages("drafted", 1000)
                if (m.kind or "cold") != "cold" and (m.created_at or "") < cutoff]
        if not warm or not automation.enabled(self.store, "autopilot"):
            return []
        return [("waiting", f"{len(warm)} answer{'s' if len(warm) != 1 else ''} "
                            f"Autopilot wasn't sure of {'have' if len(warm) != 1 else 'has'} "
                            f"waited over a day for you. Someone who asked a question "
                            f"and heard nothing is a lost sale: open the inbox.")]

    def check_agents(self) -> list[tuple[str, str]]:
        from ..orchestrator import AGENT_ORDER

        runs = self.store.recent_runs(400)
        out = []
        for name in AGENT_ORDER:
            last = [r for r in runs if r["agent"] == name][:3]
            if len(last) == 3 and all(r["status"] == "error" for r in last):
                out.append((f"agent.{name}", f"The {name} agent has failed three runs in "
                                             f"a row: {last[0].get('error') or 'no detail'}"))
        return out

    def check_mailbox(self) -> list[tuple[str, str]]:
        raw = self.store.kv_get("sending.last_error") or ""
        at, _, detail = raw.partition("|")
        if raw and at >= self._since(1):
            return [("mailbox", f"An email failed to send (not a bounce): {detail}. "
                                f"Usually the mailbox password changed: run Keys and "
                                f"settings on the desktop button.")]
        return []

    def check_strangers(self) -> list[tuple[str, str]]:
        since = self._since(1)
        with self.store.conn() as cx:
            rows = cx.execute("SELECT sender, snippet FROM inbound WHERE kind='unmatched' "
                              "AND handled_at >= ?", (since,)).fetchall()
        if not rows:
            return []
        lines = "\n".join(f"- {r['sender']}: {(r['snippet'] or '')[:120]}" for r in rows[:5])
        return [("strangers", f"{len(rows)} email(s) came from addresses that match no "
                              f"business or client. Often a referral or a client writing "
                              f"from a new address; they're in your inbox:\n{lines}")]

    def check_spend(self) -> list[tuple[str, str]]:
        budget = float(getattr(self.settings, "api_budget_monthly", 0) or 0)
        if not budget:
            return []
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self.store.conn() as cx:
            row = cx.execute("SELECT COALESCE(SUM(amount), 0) s FROM ledger WHERE kind='cost' "
                             "AND category='api' AND occurred_at LIKE ?", (f"{month}%",)).fetchone()
        spent = float(row["s"])
        if spent > budget:
            return [("spend", f"AI API spend this month is ${spent:,.2f}, over the "
                              f"${budget:,.0f} budget. Lower teaser_audits_per_day in "
                              f"answerrank.yml, or raise api_budget_monthly if the sales "
                              f"justify it.")]
        return []

    # ------------------------------------------------------------------ alerts
    def _alert(self, items: list[tuple[str, str]]) -> int:
        """Email what's new today. Each problem at most once a day."""
        if not items:
            return 0
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            seen = json.loads(self.store.kv_get("guardian.alerted") or "{}")
        except ValueError:
            seen = {}
        fresh = [(k, t) for k, t in items if seen.get(k) != today]
        if not fresh:
            return 0
        from ..mailer import SMTPConfig
        from .briefing import BriefingAgent
        brief = BriefingAgent(self.store, self.settings, mailer=self._mailer)
        if self._mailer is None and (getattr(self.settings, "demo_mode", False)
                                     or not SMTPConfig.from_env().configured()):
            return 0
        subject = ("Autopilot: " + fresh[0][1].split(".")[0])[:120]
        body = "\n\n".join(t for _k, t in fresh) + f"\n\nYour console: {brief.console()}"
        if brief._send(subject, body):
            for k, _t in fresh:
                seen[k] = today
            self.store.kv_set("guardian.alerted", json.dumps(seen))
            return 1
        return 0

    def findings(self) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        for check in (self.check_prospecting, self.check_waiting, self.check_agents,
                      self.check_mailbox, self.check_strangers, self.check_spend):
            try:
                items += check()
            except Exception as exc:  # noqa: BLE001 - one broken check must not hide the rest
                self.log.warning("guardian check %s failed: %s", check.__name__, exc)
        return items

    def execute(self) -> tuple[int, str]:
        items = self.findings()
        self.store.kv_set("guardian.last", json.dumps(
            {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "items": [t for _k, t in items]}))
        emailed = self._alert(items)
        if not items:
            return 0, "all clear"
        return len(items), (f"{len(items)} thing(s) to know" +
                            (", emailed to you" if emailed else "") + ": "
                            + items[0][1][:120])
