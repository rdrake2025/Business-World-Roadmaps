"""Strategist — decides what the business should do next.

The Explorer produces evidence. This agent reads it alongside what is
actually happening commercially — which verticals are winning clients, where
outreach is being wasted, what the pricing can carry — and turns it into one
recommendation.

It deliberately produces *one* recommendation at a time. A list of twelve
opportunities is a way of avoiding a decision, and an operator working five
hours a week can act on exactly one thing.
"""

from __future__ import annotations

from collections import Counter

from .. import knowledge, markets
from ..models import now_iso
from .base import Agent

#: Below this, the current vertical mix is not the thing to fix.
THIN_PIPELINE = 20


class StrategistAgent(Agent):
    name = "strategist"
    description = "Reads market evidence and recommends the single next move."
    interval = 24 * 3600

    # ---------------- analysis ----------------

    def assess(self) -> dict[str, object]:
        price = self.settings.pricing.growth_monthly
        clients = self.store.get_clients("active")
        prospects = self.store.get_prospects(limit=3000)
        findings = self.store.latest_findings()

        client_mix = Counter(c.business.vertical for c in clients)
        prospect_mix = Counter(p.business.vertical for p in prospects)
        won = Counter(p.business.vertical for p in prospects if p.stage == "won")
        lost = Counter(p.business.vertical for p in prospects
                       if p.stage in {"lost", "suppressed"})

        # Which served verticals actually justify the price.
        served = [
            {
                "vertical": key,
                "label": knowledge.get(key).label,
                "fit": knowledge.plan_fit(key, price),
                "prospects": prospect_mix.get(key, 0),
                "clients": client_mix.get(key, 0),
                "won": won.get(key, 0),
                "lost": lost.get(key, 0),
            }
            for key in knowledge.VERTICALS
            if prospect_mix.get(key) or client_mix.get(key)
        ]

        # Candidate markets, measured where the Explorer has been.
        measured = {f["market"]: f for f in findings}
        candidates = []
        for c in markets.CANDIDATES:
            f = measured.get(c.key)
            candidates.append({
                "market": c.key,
                "label": c.label,
                "prior": c.score(price),
                "measured": f["opportunity"] if f else None,
                "invisible": f["invisible_share"] if f else None,
                "verdict": f["verdict"] if f else c.verdict(price),
                "explored": bool(f),
                "needs_research": c.needs_research,
                "notes": (f["notes"] if f else c.notes)[:2],
            })
        candidates.sort(key=lambda r: -(r["measured"] or r["prior"]))

        return {
            "price": price,
            "clients": len(clients),
            "prospects": len(prospects),
            "served": served,
            "candidates": candidates,
            "explored_count": len(findings),
            "unexplored": [c.key for c in markets.CANDIDATES
                           if c.key not in measured],
        }

    def recommend(self, state: dict[str, object] | None = None) -> dict[str, str]:
        """One move, with the reasoning that produced it."""
        s = state or self.assess()
        price = float(s["price"])  # type: ignore[arg-type]
        candidates: list = s["candidates"]  # type: ignore[assignment]
        served: list = s["served"]  # type: ignore[assignment]

        # 1. Nothing works until there is a pipeline.
        if int(s["prospects"]) < THIN_PIPELINE:  # type: ignore[arg-type]
            return {
                "move": "Fill the pipeline before changing anything else",
                "why": (f"Only {s['prospects']} prospects exist. Market selection is "
                        f"premature while there is nothing to sell to — run the fleet "
                        f"until there are a few hundred."),
                "confidence": "high",
            }

        # 2. Outreach spent on verticals the price cannot serve is pure waste.
        misfit = [v for v in served
                  if v["fit"]["verdict"] == "weak" and v["prospects"] >= 5]
        if misfit:
            worst = max(misfit, key=lambda v: v["prospects"])
            return {
                "move": f"Stop prospecting {worst['label']}s, or price them lower",
                "why": (f"{worst['prospects']} prospects sit in a vertical where "
                        f"${price:,.0f}/mo cannot be defended "
                        f"({worst['fit']['first_job_ratio']}x first-job payback). "
                        f"Every email there spends complaint-rate budget on a "
                        f"business that will not buy."),
                "confidence": "high",
            }

        # 3. Prefer a market we have actually measured.
        proven = [c for c in candidates
                  if c["explored"] and c["verdict"] in {"pursue", "test"}
                  and not c["needs_research"]]
        if proven:
            best = proven[0]
            return {
                "move": f"Expand into {best['label']}",
                "why": (f"{best['invisible']:.0f}% of the businesses sampled were "
                        f"effectively invisible in AI answers, giving a measured "
                        f"opportunity of {best['measured']} against a prior of "
                        f"{best['prior']}. That is a real problem to sell, not an "
                        f"assumed one."),
                "confidence": "medium",
            }

        # 4. Otherwise, go and measure the most promising unexplored market.
        unmeasured = [c for c in candidates if not c["explored"]]
        if unmeasured:
            nxt = unmeasured[0]
            return {
                "move": f"Measure {nxt['label']} before committing to it",
                "why": (f"It scores {nxt['prior']} on priors, the best of the "
                        f"unexplored markets, but nobody has audited a single "
                        f"business in it. The Explorer will settle that for a few "
                        f"cents."),
                "confidence": "medium",
            }

        # 5. Everything measured, nothing compelling: deepen instead of widen.
        strong = [v for v in served if v["fit"]["verdict"] == "strong"]
        focus = strong[0]["label"] if strong else "your best vertical"
        return {
            "move": f"Go deeper in {focus} rather than wider",
            "why": ("Every candidate market has been measured and none beats what "
                    "you already serve. More markets would dilute the expertise "
                    "that makes the pitch credible."),
            "confidence": "medium",
        }

    # ---------------- run ----------------

    def execute(self) -> tuple[int, str]:
        state = self.assess()
        rec = self.recommend(state)
        self.store.kv_set("strategy_recommendation",
                          f"{rec['move']} || {rec['why']} || {rec['confidence']}")
        self.store.kv_set("strategy_updated", now_iso())
        return 1, f"{rec['move']} ({rec['confidence']} confidence)"
