"""Retention — keeps the clients the business has already won.

The arithmetic is not close. At a $997 retainer and roughly 35 sends per
client, replacing a churned client costs weeks of outreach; keeping one costs
a report and a question. A business reaching $5,000/month profit on five
clients cannot absorb losing one.

What the churn research says, and what this implements:

* **Health deteriorates 60 to 90 days before the cancellation.** By the time
  someone asks to cancel, the decision is months old. So this scores health
  continuously rather than reacting to notice.
* **Silence is the leading indicator.** Not complaints — complaints mean the
  client still expects something to change. The account that has said nothing
  at all is the one in danger.
* **The first 90 days decide the relationship.** A client who has not seen a
  result by day 90 will not wait for one at day 180.

Scores are deliberately unflattering. A health score that reads 85 for an
account nobody has spoken to in two months is worse than no score at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .base import Agent

#: Days of silence before an account is treated as at risk. Chosen to sit
#: inside the 60-90 day deterioration window rather than at the end of it.
SILENCE_WARNING = 30
SILENCE_CRITICAL = 60

#: How often a client must see evidence the retainer is doing something.
REPORT_DUE_DAYS = 32
REPORT_LATE_DAYS = 45


def _days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - when).days)


@dataclass
class Health:
    client_id: str
    name: str
    mrr: float
    score: float
    band: str                      #: healthy | monitor | act_now
    signals: list[str] = field(default_factory=list)
    action: str = ""
    tenure_days: int = 0

    def line(self) -> str:
        return f"{self.name}: {self.score:.0f}/100 ({self.band}) — {self.action}"


class RetentionAgent(Agent):
    name = "retention"
    description = "Scores client health and names the one action that saves each account."
    interval = 24 * 3600

    # ---------------- scoring ----------------

    def score_client(self, client) -> Health:
        """Four signals, weighted by how well each predicts a cancellation."""
        signals: list[str] = []
        points = 0.0
        biz = client.business
        tenure = _days_since(client.started_at) or 0

        # --- 1. Silence (40%) — the leading indicator -----------------------
        last_contact = self.store.last_outcome_at(
            client.id, ("replied", "call_booked", "client_message"))
        quiet = _days_since(last_contact)
        if quiet is None:
            if tenure <= 14:
                points += 28
                signals.append("New account — no contact history yet, which is normal.")
            else:
                points += 4
                signals.append(
                    f"No contact on record in {tenure} days of being a client. "
                    f"A silent account is the most dangerous kind.")
        elif quiet <= SILENCE_WARNING:
            points += 40
            signals.append(f"Spoke {quiet} days ago.")
        elif quiet <= SILENCE_CRITICAL:
            points += 20
            signals.append(f"{quiet} days since they last said anything. "
                           f"This is where the deterioration window opens.")
        else:
            points += 6
            signals.append(f"{quiet} days of silence. Treat this as notice already given.")

        # --- 2. Are we delivering? (25%) ------------------------------------
        since_report = _days_since(client.last_report_at)
        if since_report is None:
            if tenure <= REPORT_DUE_DAYS:
                points += 18
                signals.append("First report not due yet.")
            else:
                points += 2
                signals.append(
                    f"No report delivered in {tenure} days. They are paying and "
                    f"have seen nothing — this one is our fault, not theirs.")
        elif since_report <= REPORT_DUE_DAYS:
            points += 25
            signals.append(f"Last report {since_report} days ago — on cadence.")
        elif since_report <= REPORT_LATE_DAYS:
            points += 12
            signals.append(f"Report is {since_report - REPORT_DUE_DAYS} days late.")
        else:
            points += 2
            signals.append(f"{since_report} days since the last report. Overdue enough "
                           f"to be noticed.")

        # --- 3. Is it working? (25%) ----------------------------------------
        history = self.store.audit_history(biz.id, limit=6)
        scores = [a.score for a in reversed(history) if a.score is not None]
        if len(scores) < 2:
            points += 15
            signals.append("Not enough audits yet to show a trend.")
        else:
            delta = scores[-1] - scores[0]
            if delta >= 10:
                points += 25
                signals.append(f"Visibility up {delta:.0f} points since they started. "
                               f"Say this in the next report — it is the renewal argument.")
            elif delta >= 3:
                points += 19
                signals.append(f"Visibility up {delta:.0f} points. Real but modest.")
            elif delta > -3:
                points += 8
                signals.append(f"Visibility flat ({delta:+.0f}). They are paying for "
                               f"movement they cannot see.")
            else:
                points += 2
                signals.append(f"Visibility down {abs(delta):.0f} points. Get ahead of "
                               f"this before they notice it themselves.")

        # --- 4. Tenure (10%) — the first 90 days decide it ------------------
        if tenure <= 30:
            points += 7
            signals.append(f"Day {tenure}. Onboarding window — the habits set now hold.")
        elif tenure <= 90:
            points += 6
            signals.append(f"Day {tenure}. Still inside the window where a client "
                           f"decides whether this was worth buying.")
        else:
            points += 10
            signals.append(f"{tenure // 30} months in — past the highest-risk period.")

        score = round(min(100.0, points), 1)
        band = "healthy" if score >= 80 else "monitor" if score >= 60 else "act_now"

        # --- the single action ---------------------------------------------
        if since_report is not None and since_report > REPORT_LATE_DAYS:
            action = "Send this month's report today. Nothing else matters until they see one."
        elif since_report is None and tenure > REPORT_DUE_DAYS:
            action = "They have never received a report. Send one before anything else."
        elif quiet is not None and quiet > SILENCE_CRITICAL:
            action = (f"Call them, do not email. {quiet} days of silence at "
                      f"${client.mrr:,.0f}/mo is a cancellation forming.")
        elif quiet is None and tenure > 14:
            action = "Open a conversation — ask one question they would enjoy answering."
        elif len(scores) >= 2 and scores[-1] - scores[0] <= -3:
            action = ("Their score has fallen. Name it first, with what you are changing, "
                      "before they raise it.")
        elif len(scores) >= 2 and scores[-1] - scores[0] >= 10:
            action = ("Ask for a referral or a testimonial. A client watching their own "
                      "number rise is as willing as they will ever be.")
        else:
            action = "On track. Keep the report cadence."

        return Health(client_id=client.id, name=biz.name, mrr=client.mrr,
                      score=score, band=band, signals=signals, action=action,
                      tenure_days=tenure)

    def portfolio(self) -> list[Health]:
        """Every active client, worst first — that is the order to work them in."""
        rows = [self.score_client(c) for c in self.store.get_clients("active")]
        return sorted(rows, key=lambda h: (h.score, -h.mrr))

    def revenue_at_risk(self) -> float:
        return round(sum(h.mrr for h in self.portfolio() if h.band == "act_now"), 2)

    # ---------------- run ----------------

    def execute(self) -> tuple[int, str]:
        rows = self.portfolio()
        if not rows:
            return 0, "no active clients yet — nothing to retain"

        import json
        self.store.kv_set("retention.portfolio", json.dumps([
            {"client_id": h.client_id, "name": h.name, "mrr": h.mrr,
             "score": h.score, "band": h.band, "action": h.action,
             "signals": h.signals, "tenure_days": h.tenure_days}
            for h in rows]))

        for h in rows:
            if h.band == "act_now":
                self.store.record_outcome(
                    prospect_id=h.client_id, kind="at_risk", sentiment=h.band,
                    note=h.action[:300])

        at_risk = [h for h in rows if h.band == "act_now"]
        monitor = [h for h in rows if h.band == "monitor"]
        risk_mrr = sum(h.mrr for h in at_risk)
        summary = (f"{len(rows)} clients: {len(rows) - len(at_risk) - len(monitor)} healthy, "
                   f"{len(monitor)} monitor, {len(at_risk)} need action")
        if at_risk:
            summary += (f" | ${risk_mrr:,.0f}/mo at risk — worst: {at_risk[0].line()}")
        return len(rows), summary
