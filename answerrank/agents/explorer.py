"""Explorer — finds out whether a new market is actually worth entering.

The market scoring model is a set of priors. This agent tests them. It picks
the least-examined candidate trade, samples real businesses in it, runs the
same audit the paying product runs, and reports what it measured rather than
what was assumed.

That distinction matters. A trade can look ideal on paper — high ticket,
fragmented, big marketing budgets — and turn out to be perfectly visible in
AI answers already, in which case there is nothing to sell. The only way to
know is to measure, and measuring costs fractions of a cent.

One market per run, deliberately. Exploration should never crowd out the
work that pays.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import knowledge, markets
from ..audit import estimate_cost, run_audit
from ..models import Business, LedgerEntry, new_id, now_iso
from .base import Agent

#: Businesses sampled per market. Enough to see a pattern, few enough that a
#: full sweep of the candidate list costs pennies.
SAMPLE_SIZE = 5

#: A market is only interesting if a real share of it is genuinely invisible.
INVISIBLE_THRESHOLD = 35.0


class ExplorerAgent(Agent):
    name = "explorer"
    description = "Samples candidate markets to find the next vertical worth entering."
    interval = 12 * 3600

    def __init__(self, store, settings, sample_size: int = SAMPLE_SIZE):
        super().__init__(store, settings)
        self.sample_size = sample_size

    # ---------------- sampling ----------------

    def _sample_businesses(self, candidate: markets.Candidate) -> list[Business]:
        """Real businesses where we can find them, plausible ones otherwise.

        With a SERP key this reads actual local operators. Without one it
        generates representative names so the measurement pipeline is
        exercised end to end — and the finding is flagged as simulated so
        nobody mistakes it for evidence.
        """
        cities = [("Austin", "TX"), ("Charlotte", "NC"), ("Tampa", "FL"),
                  ("Denver", "CO"), ("Columbus", "OH")]

        if self.settings.api_key("serper"):
            from .scout import ScoutAgent
            scout = ScoutAgent(self.store, self.settings)
            found: list[Business] = []
            for city, state in cities:
                if len(found) >= self.sample_size:
                    break
                found.extend(scout.from_serper(candidate.key, city, state)[:2])
            if found:
                for b in found:
                    b.vertical = candidate.key
                return found[: self.sample_size]

        stems = ["Apex", "Summit", "Cornerstone", "Ironclad", "Beacon", "Redwood"]
        return [
            Business(
                name=f"{stems[i % len(stems)]} {candidate.label.title()}",
                city=cities[i % len(cities)][0],
                state=cities[i % len(cities)][1],
                vertical=candidate.key,
                website=f"https://{stems[i % len(stems)].lower()}{candidate.key}.com",
            )
            for i in range(self.sample_size)
        ]

    # ---------------- run ----------------

    def execute(self) -> tuple[int, str]:
        explored = self.store.explored_markets()
        # Least-examined first, then by prior score — so the whole candidate
        # list gets covered rather than the top of it being re-tested forever.
        queue = sorted(
            markets.CANDIDATES,
            key=lambda c: (c.key in explored, -c.score(self.settings.pricing.growth_monthly)),
        )
        if not queue:
            return 0, "no candidate markets defined"

        candidate = queue[0]
        # Registered provisionally: auditable, but invisible to every pricing
        # and targeting decision until the market is actually adopted.
        knowledge.register_provisional(knowledge.from_candidate(candidate))

        businesses = self._sample_businesses(candidate)
        simulated = not self.settings.api_key("serper")

        scores: list[float] = []
        engine_count = len(self.settings.available_engines())
        spend = 0.0
        for biz in businesses:
            audit = run_audit(biz, self.settings, depth="teaser")
            scores.append(audit.score)
            spend += estimate_cost("teaser", engine_count)

        if not scores:
            return 0, f"{candidate.label}: no businesses sampled"

        mean_score = round(sum(scores) / len(scores), 1)
        invisible = round(100 * sum(1 for s in scores if s < INVISIBLE_THRESHOLD)
                          / len(scores), 1)

        # Measured invisibility replaces the assumed digital gap, weighted
        # toward what we actually observed.
        prior = candidate.score(self.settings.pricing.growth_monthly)
        measured = round(prior * 0.6 + invisible * 0.4, 1)

        notes = list(candidate.notes)
        if simulated:
            notes.insert(0, "SIMULATED SAMPLE — no SERP key, so these businesses "
                            "are representative rather than real. Re-run with a key "
                            "before acting on this.")
        if invisible >= 70:
            notes.append(f"{invisible:.0f}% of the sample was effectively invisible — "
                         f"there is a real problem to sell here.")
        elif invisible <= 30:
            notes.append(f"Only {invisible:.0f}% of the sample was invisible. This "
                         f"market may already be well served; the pitch would be weak.")
        if candidate.needs_research:
            notes.append("Economics are estimated, not sourced. Verify ticket size "
                         "and marketing spend before committing outreach to this.")

        verdict = ("pursue" if measured >= 70 and not simulated
                   else "test" if measured >= 55
                   else "watch" if measured >= 42
                   else "skip")

        self.store.save_finding({
            "id": new_id("mkt"),
            "market": candidate.key,
            "label": candidate.label,
            "sampled": len(scores),
            "mean_score": mean_score,
            "invisible_share": invisible,
            "opportunity": measured,
            "verdict": verdict,
            "notes": notes,
            "created_at": now_iso(),
        })

        if spend > 0:
            self.store.add_ledger(LedgerEntry(
                kind="cost", category="api", amount=round(spend, 4),
                description=f"market exploration: {candidate.label}",
            ))

        return 1, (
            f"explored {candidate.label}: {invisible:.0f}% invisible across "
            f"{len(scores)} sampled, opportunity {measured} — {verdict}"
            + (" (simulated)" if simulated else "")
        )
