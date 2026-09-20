"""Analyst — turns recorded outcomes into decisions.

Every other agent acts. This one is the only one that asks whether the acting
worked, which is the difference between a system that runs and a system that
improves. It reads the ``outcomes`` table and answers three questions:

1. **What is the funnel actually doing?** Sent to replied to won, measured,
   not assumed.
2. **Which trades and which sequence steps earn their place?** Reply rate by
   vertical and by step, so effort moves toward what converts.
3. **How much volume does the target require at the observed rates?** The
   $5,000/month goal expressed as emails per week, which is the only form of
   it the operator can act on.

The discipline that matters here is refusing to conclude. Below
:data:`MIN_SAMPLE` sends, a per-vertical reply rate is noise, and acting on
noise is worse than acting on the benchmark prior — it feels like evidence.
Every finding therefore carries the sample it rests on, and thin samples are
reported as "not yet known" rather than quietly rounded into a decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import knowledge
from .base import Agent

#: Sends to one vertical before its reply rate is worth acting on. At a ~4%
#: expected reply rate, 25 sends still only produces one reply on average, so
#: this is the floor for *noticing*, not for certainty — findings below
#: 60 sends are reported as provisional.
MIN_SAMPLE = 25
CONFIDENT_SAMPLE = 60

#: Cold-outreach priors for a well-targeted, evidence-carrying B2B sequence.
#: Used only while real data is thin, and always labelled as a prior.
PRIOR_REPLY_RATE = 0.04
PRIOR_REPLY_TO_WON = 0.15


@dataclass
class Funnel:
    sent: int
    replied: int
    interested: int
    won: int
    lost: int

    @property
    def reply_rate(self) -> float:
        return self.replied / self.sent if self.sent else 0.0

    @property
    def win_rate_of_replies(self) -> float:
        return self.won / self.replied if self.replied else 0.0

    @property
    def sends_per_win(self) -> float:
        return self.sent / self.won if self.won else 0.0

    def line(self) -> str:
        if not self.sent:
            return "No sends recorded yet — nothing to learn from."
        return (f"{self.sent} sent, {self.replied} replied "
                f"({self.reply_rate:.1%}), {self.won} won"
                + (f" — {self.sends_per_win:.0f} sends per client."
                   if self.won else "."))


class AnalystAgent(Agent):
    name = "analyst"
    description = "Reads outcomes and reports what is actually converting."
    interval = 12 * 3600

    # ---------------- measurement ----------------

    def funnel(self, days: int = 90) -> Funnel:
        c = self.store.outcome_counts(days)
        return Funnel(
            sent=c.get("sent", 0),
            replied=c.get("replied", 0),
            interested=c.get("interested", 0),
            won=c.get("won", 0),
            lost=c.get("lost", 0),
        )

    def by_vertical(self, days: int = 90) -> list[dict[str, object]]:
        """Reply and win rates per trade, with the sample size attached."""
        grouped = self.store.outcomes_by("vertical", days)
        rows = []
        for vertical, counts in grouped.items():
            sent = counts.get("sent", 0)
            replied = counts.get("replied", 0)
            won = counts.get("won", 0)
            rows.append({
                "vertical": vertical,
                "label": knowledge.get(vertical).label,
                "sent": sent,
                "replied": replied,
                "won": won,
                "reply_rate": round(replied / sent, 4) if sent else None,
                "confidence": ("confident" if sent >= CONFIDENT_SAMPLE
                               else "provisional" if sent >= MIN_SAMPLE
                               else "insufficient"),
            })
        return sorted(rows, key=lambda r: -(r["reply_rate"] or 0))

    def by_step(self, days: int = 90) -> list[dict[str, object]]:
        """Which touch in the sequence earns its place."""
        grouped = self.store.outcomes_by("step", days)
        rows = []
        for step, counts in sorted(grouped.items(), key=lambda kv: int(kv[0] or 0)):
            sent = counts.get("sent", 0)
            replied = counts.get("replied", 0)
            rows.append({
                "step": int(step or 0),
                "sent": sent,
                "replied": replied,
                "reply_rate": round(replied / sent, 4) if sent else None,
            })
        return rows

    # ---------------- what a client is actually worth ----------------

    def blended_price(self) -> tuple[float, str]:
        """The average retainer the current pipeline would actually produce.

        Trades are quoted between the lowest and highest tier the ladder
        offers, so assuming one flat price makes the most important number
        this system produces — how much work the target requires — wrong in
        an unknown direction. This weights each trade's own price by how many
        prospects are actually in it.
        """
        prospects = self.store.get_prospects(limit=5000)
        prices = [self.settings.quote_for(p.business.vertical) for p in prospects]
        if not prices:
            return self.settings.pricing.growth_monthly, "no pipeline yet, using the standard tier"
        blended = sum(prices) / len(prices)
        low, high = min(prices), max(prices)
        if low == high:
            return blended, f"every prospect quoted ${blended:,.0f}"
        return blended, (f"blended across {len(prices)} prospects quoted "
                         f"${low:,.0f}\u2013${high:,.0f}")

    # ---------------- the volume the goal requires ----------------

    def required_volume(self, target_monthly_profit: float,
                        monthly_price: float | None = None,
                        delivery_cost: float = 18.0,
                        days: int = 90) -> dict[str, object]:
        """Emails per week to reach the profit target at the observed rates.

        This is the single most useful number the system produces, because it
        converts an abstract goal into a quantity of work. When the sample is
        thin it falls back to published cold-outreach priors and says so —
        a stated prior is honest, a fabricated measurement is not.
        """
        f = self.funnel(days)
        if monthly_price is None:
            monthly_price, price_basis = self.blended_price()
        else:
            price_basis = f"${monthly_price:,.0f} as given"
        margin = max(1.0, monthly_price - delivery_cost)
        clients_needed = target_monthly_profit / margin

        if f.sent >= CONFIDENT_SAMPLE and f.won:
            sends_per_win = f.sends_per_win
            basis = f"measured: {f.won} wins from {f.sent} sends"
        elif f.sent >= MIN_SAMPLE and f.replied:
            sends_per_win = (1 / f.reply_rate) / PRIOR_REPLY_TO_WON
            basis = (f"half measured: your reply rate ({f.reply_rate:.1%}) with a "
                     f"{PRIOR_REPLY_TO_WON:.0%} benchmark reply-to-close")
        else:
            sends_per_win = (1 / PRIOR_REPLY_RATE) / PRIOR_REPLY_TO_WON
            basis = (f"benchmark prior only ({PRIOR_REPLY_RATE:.0%} reply, "
                     f"{PRIOR_REPLY_TO_WON:.0%} close) — not enough sends to measure")

        # Clients are cumulative: a retainer won in month one still pays in
        # month six. The build is therefore spread over a ramp rather than
        # demanded all at once.
        sends_total = clients_needed * sends_per_win
        for ramp in (6, 9, 12):
            per_week = sends_total / (ramp * 4.33)
            if per_week <= 120:  # the daily cap, weekly
                break
        return {
            "clients_needed": round(clients_needed, 1),
            "sends_per_win": round(sends_per_win),
            "sends_total": round(sends_total),
            "ramp_months": ramp,
            "sends_per_week": round(per_week),
            "sends_per_day": round(per_week / 5),
            "basis": basis,
            "monthly_price": round(monthly_price, 2),
            "price_basis": price_basis,
            "line": (f"{clients_needed:.0f} clients at an average of "
                     f"${monthly_price:,.0f} reaches "
                     f"${target_monthly_profit:,.0f}/mo profit. At {round(sends_per_win)} "
                     f"sends per client that is about {round(per_week)} emails a week "
                     f"over {ramp} months ({basis})."),
        }

    # ---------------- conclusions ----------------

    def learnings(self, days: int = 90) -> list[str]:
        """Findings worth acting on. Empty is a valid and honest answer."""
        out: list[str] = []
        f = self.funnel(days)

        if f.sent < MIN_SAMPLE:
            out.append(
                f"Only {f.sent} sends recorded. Nothing here is measurable yet — "
                f"{MIN_SAMPLE} is the floor before any rate means anything.")
            return out

        out.append(f.line())

        verticals = [r for r in self.by_vertical(days)
                     if r["confidence"] != "insufficient"]
        if len(verticals) >= 2:
            best, worst = verticals[0], verticals[-1]
            if (best["reply_rate"] or 0) >= 2 * (worst["reply_rate"] or 0) + 0.01:
                out.append(
                    f"{best['label']}s reply at {best['reply_rate']:.1%} "
                    f"({best['sent']} sends) against {worst['reply_rate']:.1%} for "
                    f"{worst['label']}s ({worst['sent']}). Move prospecting effort "
                    f"toward {best['label']}s.")
        thin = [r for r in self.by_vertical(days) if r["confidence"] == "insufficient"]
        if thin:
            out.append(
                f"{len(thin)} trade(s) have fewer than {MIN_SAMPLE} sends "
                f"({', '.join(str(r['vertical']) for r in thin[:4])}) — not yet known.")

        steps = [r for r in self.by_step(days) if (r["sent"] or 0) >= MIN_SAMPLE]
        if len(steps) >= 2:
            late = [r for r in steps if r["step"] >= 2]
            late_replies = sum(int(r["replied"] or 0) for r in late)
            if late_replies and f.replied:
                share = late_replies / f.replied
                out.append(
                    f"{share:.0%} of replies arrive after the first email. "
                    + ("The follow-up sequence is carrying the channel — keep it."
                       if share >= 0.4 else
                       "Most replies come from the opener; the follow-ups are "
                       "adding little."))

        if f.replied >= 10 and not f.won:
            out.append(
                f"{f.replied} replies and no wins. The problem is at the close, "
                f"not the top of the funnel — the reply handling is where to look.")
        return out

    def execute(self) -> tuple[int, str]:
        learnings = self.learnings()
        vol = self.required_volume(
            self.settings.profit_target_monthly,
            None,  # blend from the pipeline rather than assume one tier
            self.settings.pricing.delivery_cost_monthly)

        import json
        self.store.kv_set("analyst.learnings", json.dumps(learnings))
        self.store.kv_set("analyst.funnel", json.dumps(self.funnel().__dict__))
        self.store.kv_set("analyst.by_vertical", json.dumps(self.by_vertical()))
        self.store.kv_set("analyst.required_volume", json.dumps(vol))

        headline = learnings[0] if learnings else "no outcomes recorded yet"
        return len(learnings), f"{headline} | {vol['line']}"
