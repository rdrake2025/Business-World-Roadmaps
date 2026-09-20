"""Market discovery: which *kinds* of business are worth serving at all.

The seven verticals the system knows were chosen by hand. That is a ceiling.
This module makes finding the eighth a systematic activity rather than a
hunch, because the choice of market determines more about whether this
business works than anything downstream of it does.

Six factors decide whether a trade is worth serving. They are deliberately
about the *market*, not about any one business in it:

============== ====== ====================================================
Factor         Weight What it asks
============== ====== ====================================================
Affordability    30%  Can a typical operator absorb the retainer without
                      thinking hard about it? Measured against what they
                      already spend on marketing, not against their revenue.
Urgency          20%  Do customers ask an assistant, or do they already
                      know who to call? No asking, no answer to be named in.
Fragmentation    18%  Many independent operators, or a few chains? Chains
                      have marketing departments and will not buy this.
Digital gap      15%  How badly served are they today? A trade that already
                      has good agencies is a harder sell.
Ticket value     12%  Bigger jobs make the ROI argument trivial.
Incumbent risk    5%  Is someone already selling this to them?
============== ====== ====================================================

Figures are 2026 published benchmarks where available and explicitly marked
estimates otherwise. Anything the Explorer agent cannot source is flagged
``needs_research`` rather than quietly guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field

WEIGHTS = {
    "affordability": 0.30,
    "urgency": 0.20,
    "fragmentation": 0.18,
    "digital_gap": 0.15,
    "ticket": 0.12,
    "incumbent_risk": 0.05,
}


@dataclass
class Candidate:
    """A trade we might serve, and what we currently believe about it."""

    key: str
    label: str
    #: Typical first job in USD. The single most load-bearing number.
    avg_ticket: float
    #: What a single-location operator spends on marketing monthly.
    monthly_marketing_spend: float
    #: 0-1. Do customers ask an assistant who to call, or already know?
    urgency: float
    #: 0-1. Share of the market that is independent rather than chain-owned.
    fragmentation: float
    #: 0-1. How poorly served they are by existing marketing providers.
    digital_gap: float
    #: 0-1. How crowded the market already is with people selling this.
    incumbent_risk: float
    #: Where the numbers came from, or why they are a guess.
    basis: str
    #: True when a figure is an informed estimate rather than a sourced one.
    needs_research: bool = False
    notes: list[str] = field(default_factory=list)

    # ---- derived ----

    def affordability(self, monthly_price: float) -> float:
        """Retainer as a share of what they already spend, inverted to 0-1.

        A business spending $5,000 a month on marketing barely notices $997.
        One spending $600 has to cut something else, and will say no.
        """
        if self.monthly_marketing_spend <= 0:
            return 0.0
        share = monthly_price / self.monthly_marketing_spend
        if share <= 0.10:
            return 1.0
        if share >= 1.0:
            return 0.0
        # Linear between a tenth of their budget and all of it.
        return round(1.0 - ((share - 0.10) / 0.90), 3)

    def ticket_strength(self) -> float:
        """Normalised to 0-1, saturating around $10k — past that the ROI
        argument is already trivial and more ticket adds nothing."""
        return round(min(1.0, self.avg_ticket / 10_000) ** 0.5, 3)

    def score(self, monthly_price: float = 997.0) -> float:
        parts = {
            "affordability": self.affordability(monthly_price),
            "urgency": self.urgency,
            "fragmentation": self.fragmentation,
            "digital_gap": self.digital_gap,
            "ticket": self.ticket_strength(),
            "incumbent_risk": 1.0 - self.incumbent_risk,
        }
        return round(100 * sum(parts[k] * WEIGHTS[k] for k in WEIGHTS), 1)

    def breakdown(self, monthly_price: float = 997.0) -> dict[str, float]:
        return {
            "affordability": round(self.affordability(monthly_price) * 100),
            "urgency": round(self.urgency * 100),
            "fragmentation": round(self.fragmentation * 100),
            "digital_gap": round(self.digital_gap * 100),
            "ticket": round(self.ticket_strength() * 100),
            "incumbent_risk": round((1 - self.incumbent_risk) * 100),
        }

    def verdict(self, monthly_price: float = 997.0) -> str:
        s = self.score(monthly_price)
        if s >= 72:
            return "pursue"
        if s >= 58:
            return "test"
        if s >= 45:
            return "watch"
        return "skip"


#: The candidate universe. Everything here is a real trade with a local,
#: searchable footprint. Trades already served are excluded — this is the
#: expansion list, not a catalogue.
#:
#: Promoted so far: restoration, med spa, tree service, electrician, garage
#: door, pest control and veterinary — each moved into knowledge.py once the
#: Explorer measured it and the economics were sourced properly. A promoted
#: trade leaves this list: keeping it here would have the Explorer spend real
#: audits re-measuring a market already being sold to.
CANDIDATES: list[Candidate] = [
    Candidate(
        key="concrete", label="concrete contractor",
        avg_ticket=5500, monthly_marketing_spend=1200,
        urgency=0.35, fragmentation=0.92, digital_gap=0.88, incumbent_risk=0.15,
        basis="Identified as a low-volume, high-ticket underserved niche (2026)",
        notes=["Very high ticket and almost no digital competition.",
               "Low urgency: a driveway is planned, not panicked over.",
               "Small marketing budgets make the retainer a real decision."],
    ),
    Candidate(
        key="junk_removal", label="junk removal",
        avg_ticket=350, monthly_marketing_spend=1100,
        urgency=0.70, fragmentation=0.80, digital_gap=0.68, incumbent_risk=0.50,
        basis="$52B market, cited as a growth niche for 2026",
        notes=["Large and growing market, but low ticket.",
               "Franchise brands (1-800-GOT-JUNK) dominate recall."],
    ),
    Candidate(
        key="aging_in_place", label="home accessibility contractor",
        avg_ticket=3800, monthly_marketing_spend=900,
        urgency=0.45, fragmentation=0.94, digital_gap=0.92, incumbent_risk=0.10,
        basis="Named a consistently underserved 2026 trend (aging in place)",
        needs_research=True,
        notes=["Almost nobody is serving this digitally — the largest gap on the list.",
               "Demographics guarantee demand growth for decades.",
               "Budgets are small today; the category is early."],
    ),
    Candidate(
        key="pool_service", label="pool service",
        avg_ticket=280, monthly_marketing_spend=900,
        urgency=0.40, fragmentation=0.90, digital_gap=0.75, incumbent_risk=0.25,
        basis="Named a 2026 recurring-revenue local category",
        notes=["Recurring contracts give strong lifetime value.",
               "Low ticket and small budgets make the retainer a stretch.",
               "Geographically limited to warm markets."],
    ),
    Candidate(
        key="smart_home", label="smart home installer",
        avg_ticket=2400, monthly_marketing_spend=1300,
        urgency=0.30, fragmentation=0.88, digital_gap=0.85, incumbent_risk=0.20,
        basis="Named among five 2026 growth sectors; ticket estimated",
        needs_research=True,
        notes=["Buyers research extensively before choosing — AI answers matter.",
               "Low urgency lengthens the sales cycle for the installer."],
    ),
]


def by_key(key: str) -> Candidate | None:
    return next((c for c in CANDIDATES if c.key == key), None)


def ranked(monthly_price: float = 997.0) -> list[Candidate]:
    return sorted(CANDIDATES, key=lambda c: -c.score(monthly_price))


def shortlist(monthly_price: float = 997.0, limit: int = 3) -> list[Candidate]:
    """The ones worth acting on, best first."""
    return [c for c in ranked(monthly_price)
            if c.verdict(monthly_price) in {"pursue", "test"}][:limit]
