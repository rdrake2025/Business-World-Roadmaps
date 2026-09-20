"""Prospect qualification.

The outreach agent previously pitched anyone with a visibility gap. That is
half the question. A gap says there is a *problem*; it says nothing about
whether the business can pay to fix it, or whether the retainer arithmetic
survives contact with their economics.

Pitching badly-fitting prospects is not merely wasted effort — it spends the
one resource that cannot be bought back. Every ignored email pushes the
complaint rate toward the 0.3% threshold at which Google, Yahoo and Microsoft
begin filtering a domain wholesale. So qualification is a deliverability
control as much as a sales one.

Four factors, weighted by how much each actually predicts a close.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import knowledge

# Metros large enough to sustain the query volume the revenue model assumes,
# without the competitive density of a top-5 city.
STRONG_MARKETS = {
    "austin", "charlotte", "phoenix", "tampa", "nashville", "columbus",
    "raleigh", "denver", "kansas city", "boise", "greenville", "tucson",
    "jacksonville", "oklahoma city", "omaha", "richmond", "louisville",
    "birmingham", "tulsa", "wichita", "spokane", "fresno", "mesa", "reno",
}

# Free mail hosts on a business address suggest a business that has not
# invested in its own infrastructure — and generally does not buy retainers.
CONSUMER_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
                 "aol.com", "icloud.com", "live.com", "msn.com"}


@dataclass
class Fit:
    score: float              #: 0-100
    tier: str                 #: A | B | C | D
    reasons: list[str]
    blockers: list[str]

    @property
    def worth_pitching(self) -> bool:
        """C and above. D means the maths does not work at any effort."""
        return self.tier in {"A", "B", "C"} and not self.blockers


def score_fit(business, visibility_score: float | None = None,
              monthly_price: float = 997.0) -> Fit:
    """How good a client this business would actually be."""
    reasons: list[str] = []
    blockers: list[str] = []
    points = 0.0

    # --- 1. Does the retainer maths work for this trade? (40%) ---
    fit = knowledge.plan_fit(business.vertical, monthly_price)
    v = knowledge.get(business.vertical)
    if fit["verdict"] == "strong":
        points += 40
        reasons.append(
            f"${v.economics.avg_ticket:,.0f} average ticket — the retainer pays for "
            f"itself on first-job revenue alone")
    elif fit["verdict"] == "workable":
        points += 24
        reasons.append(
            f"Lifetime value of ${v.economics.lifetime_value:,.0f} carries the case, "
            f"but first-job revenue alone does not")
    else:
        points += 8
        blockers.append(
            f"At ${monthly_price:,.0f}/mo the economics are hard to defend for "
            f"{v.label}s. Price lower or skip.")

    # --- 2. Do they look like they already spend on marketing? (25%) ---
    domain = business.domain
    if not domain:
        blockers.append("No website — nothing to optimise and nothing to sell.")
    elif domain in CONSUMER_MAIL:
        blockers.append("Consumer email domain — unlikely to buy a retainer.")
    else:
        points += 15
        reasons.append("Owns a real domain")
        email_domain = (business.email or "").split("@")[-1].lower()
        if email_domain and email_domain == domain:
            points += 10
            reasons.append("Uses email on their own domain — a sign of real investment")
        elif email_domain in CONSUMER_MAIL:
            reasons.append("Uses a free email host despite owning a domain")

    # --- 3. Is the market big enough to matter? (20%) ---
    if business.city.strip().lower() in STRONG_MARKETS:
        points += 20
        reasons.append(f"{business.city} has the search volume to support the model")
    elif business.city:
        points += 11
        reasons.append(f"{business.city} is unverified for volume — worth checking")

    # --- 4. Is the problem severe enough to feel? (15%) ---
    if visibility_score is None:
        points += 7
    elif visibility_score < 25:
        points += 15
        reasons.append("Almost entirely absent from AI answers — the gap is undeniable")
    elif visibility_score < 50:
        points += 11
        reasons.append("Clear, demonstrable gap")
    elif visibility_score < 70:
        points += 5
        reasons.append("Moderate gap — a harder sell")
    else:
        blockers.append("Already visible. There is no honest problem to sell them.")

    score = round(min(100.0, points), 1)
    tier = "A" if score >= 75 else "B" if score >= 58 else "C" if score >= 42 else "D"
    return Fit(score=score, tier=tier, reasons=reasons, blockers=blockers)


def priority(business, visibility_score: float | None, competitor_gap: float | None,
             monthly_price: float = 997.0) -> float:
    """Ordering key for the outreach queue: fit first, then pain.

    A perfect-fit business with a moderate gap beats a poor-fit business with
    a catastrophic one, because the second will not buy at any level of pain.
    """
    fit = score_fit(business, visibility_score, monthly_price)
    if not fit.worth_pitching:
        return 0.0
    pain = min(100.0, (competitor_gap or 0.0))
    return round(fit.score * 0.7 + pain * 0.3, 1)
