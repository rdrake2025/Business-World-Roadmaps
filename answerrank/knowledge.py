"""Domain knowledge the agents reason from.

Every agent previously worked off a handful of hardcoded strings, which made
the audits generic and the outreach abstract. This module is the difference
between "you're not visible in AI search" and "you're missing roughly
$18,000 of first-job revenue a year, and here is the arithmetic."

All figures are published 2026 benchmarks, cited per vertical. They are
industry averages, not claims about a specific business — everything derived
from them is presented as an estimate, and :func:`revenue_at_risk` states its
assumptions rather than hiding them.

Sources:
  HVAC ticket / LTV / CAC  — Housecall Pro, ServiceTitan, PipelineOn (2026)
  Plumbing CPL / per-tech  — Foundry CRO home-services benchmarks (2026)
  Roofing job value / CAC  — Foundry CRO; 99 Calls contractor CAC (2026)
  Dental production / LTV  — Dentx, Dental Intel, MeetDandy (2026)
  Legal case value         — CasePeer PI statistics; Nolo (2026)
  Seasonality              — SmartAC / BaaDigi HVAC search seasonality (2026)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Economics:
    """What one won customer is worth to this kind of business."""

    avg_ticket: float          #: typical first job, USD
    lifetime_value: float      #: full relationship value, USD
    typical_cac: float         #: what they already pay to win one customer
    #: Buyer-intent searches per month for this trade in a mid-size metro.
    #: Varies enormously by trade: an HVAC unit fails far more often than a
    #: roof needs replacing, and personal injury is rarer still.
    monthly_queries: int = 300
    #: Share of new customers who arrive via search rather than referral or
    #: repeat.
    search_share: float = 0.45
    #: Share of those searches that actually resolve into an AI answer naming
    #: businesses. AI answers are a growing minority of search, not all of it.
    ai_answer_share: float = 0.30
    #: "Named in the answer" to "booked the job". Inversely related to ticket
    #: size: nobody gets three quotes for a blocked drain, everybody does for
    #: a roof.
    booking_rate: float = 0.025

    def monthly_value(self, jobs_per_month: float) -> float:
        return round(self.avg_ticket * jobs_per_month, 2)


@dataclass(frozen=True)
class Vertical:
    key: str
    label: str                 #: how a customer would name this trade
    service: str               #: the service itself, lowercase
    urgent_scenario: str       #: a complete sentence a panicking customer types
    jobs: list[str]            #: real job types, highest value first
    economics: Economics
    #: Months (1-12) when demand peaks. Outreach lands best just before these.
    peak_months: list[int]
    #: What the owner will say to deflect. Used to pre-empt in copy.
    objections: list[str]
    #: Who actually decides. Rarely a marketing manager at this size.
    decision_maker: str
    #: Phrases real buyers use, which the prompt builder mirrors.
    buyer_phrases: list[str] = field(default_factory=list)
    #: Signals a business is a real prospect rather than a hobbyist.
    spend_signals: list[str] = field(default_factory=list)

    def peak_label(self) -> str:
        names = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May",
                 6: "June", 7: "July", 8: "August", 9: "September",
                 10: "October", 11: "November", 12: "December"}
        return " and ".join(names[m] for m in self.peak_months)


VERTICALS: dict[str, Vertical] = {
    "hvac": Vertical(
        key="hvac",
        label="HVAC contractor",
        service="AC repair",
        urgent_scenario="My AC stopped working in a heat wave",
        jobs=["system replacement", "furnace replacement", "heat pump installation",
              "AC repair", "duct cleaning"],
        # Blended residential ticket $1,400-1,800; LTV $15,340 over 7-10 years;
        # CAC $296-350 for well-run shops.
        economics=Economics(avg_ticket=1600, lifetime_value=15340, typical_cac=325,
                            monthly_queries=420, booking_rate=0.025),
        peak_months=[7, 12],  # AC in July, heating in December
        objections=[
            "I already pay an SEO guy",
            "My phone rings fine",
            "I get all my work from referrals",
            "I'm too busy in season to think about marketing",
        ],
        decision_maker="owner, usually also running jobs",
        buyer_phrases=["ac not cooling", "emergency ac repair", "hvac near me",
                       "how much to replace an ac unit", "who fixes furnaces"],
        spend_signals=["wrapped vehicles", "Google Ads presence", "review count above 50",
                       "financing offered", "maintenance plan advertised"],
    ),
    "plumbing": Vertical(
        key="plumbing",
        label="plumber",
        service="plumbing repair",
        urgent_scenario="I have a burst pipe flooding my kitchen",
        jobs=["repiping", "water heater replacement", "sewer line repair",
              "leak detection", "drain cleaning"],
        # CPL ~$129; $160-220k revenue per technician annually.
        economics=Economics(avg_ticket=750, lifetime_value=4200, typical_cac=260,
                            monthly_queries=480, booking_rate=0.030),
        peak_months=[1, 12],  # frozen and burst pipes
        objections=[
            "We're booked solid already",
            "Word of mouth is all we need",
            "Tried marketing before, wasted money",
        ],
        decision_maker="owner or office manager",
        buyer_phrases=["emergency plumber near me", "burst pipe who to call",
                       "water heater not working", "24 hour plumber"],
        spend_signals=["24/7 line advertised", "Google Ads presence", "branded vans",
                       "review count above 40"],
    ),
    "roofing": Vertical(
        key="roofing",
        label="roofing contractor",
        service="roof repair",
        urgent_scenario="My roof is leaking after a storm",
        jobs=["full roof replacement", "storm damage repair", "roof repair",
              "gutter installation"],
        # Average job ~$9,000; CAC $400-900; CPL ~$228.
        # Infrequent, high-consideration purchase: low volume, low conversion.
        economics=Economics(avg_ticket=9000, lifetime_value=11000, typical_cac=650,
                            monthly_queries=120, booking_rate=0.008),
        peak_months=[5, 9],  # post-storm seasons
        objections=[
            "Storm season brings us all the work we need",
            "We buy leads already",
            "Insurance work is most of our business",
        ],
        decision_maker="owner",
        buyer_phrases=["roof leaking who to call", "roof replacement cost",
                       "storm damage roofer", "best roofer near me"],
        spend_signals=["yard signs", "lead-gen spend", "manufacturer certification",
                       "financing offered"],
    ),
    "dental": Vertical(
        key="dental",
        label="dentist",
        service="dental care",
        urgent_scenario="I have severe tooth pain and need to be seen today",
        jobs=["dental implants", "Invisalign", "crowns", "root canal",
              "teeth whitening"],
        # Production per patient ~$259 (PPO $225-275, FFS $325-400);
        # patient LTV ~$6,700 (range $3,500-15,000).
        economics=Economics(avg_ticket=259, lifetime_value=6700, typical_cac=300,
                            monthly_queries=340, booking_rate=0.015),
        peak_months=[1, 9],  # benefits reset, back-to-school
        objections=[
            "We're not taking new patients",
            "Our patients come from referrals",
            "We already have a marketing company",
        ],
        decision_maker="practice owner or office manager",
        buyer_phrases=["emergency dentist near me", "dentist accepting new patients",
                       "how much are dental implants", "dentist open saturday"],
        spend_signals=["accepting new patients", "Google Ads presence",
                       "membership plan advertised", "review count above 100"],
    ),
    "legal": Vertical(
        key="legal",
        label="attorney",
        service="legal representation",
        urgent_scenario="I was just injured in a car accident",
        jobs=["personal injury claim", "car accident case", "estate planning",
              "business formation"],
        # PI settlements: most $3,000-25,000, median MVA settlement ~$40,000;
        # ~$17,000 average case value needed for a healthy LTV:CAC.
        # Rare event, heavily shopped: very low volume and conversion, but a
        # single case dwarfs a year of the retainer.
        economics=Economics(avg_ticket=17000, lifetime_value=17000, typical_cac=2200,
                            monthly_queries=90, search_share=0.60, booking_rate=0.005),
        peak_months=[1, 7],
        objections=[
            "We get cases from referrals and other attorneys",
            "We already spend heavily on ads",
            "Bar rules restrict what we can say",
        ],
        decision_maker="managing partner",
        buyer_phrases=["car accident lawyer near me", "do I need a lawyer for",
                       "best personal injury attorney", "free consultation lawyer"],
        spend_signals=["TV or billboard presence", "heavy Google Ads spend",
                       "multiple office locations", "case results published"],
    ),
    "medical": Vertical(
        key="medical",
        label="medical clinic",
        service="primary care",
        urgent_scenario="I need urgent care today",
        jobs=["annual physical", "same-day sick visit", "chronic care management"],
        economics=Economics(avg_ticket=180, lifetime_value=3400, typical_cac=210,
                            monthly_queries=400, booking_rate=0.020),
        peak_months=[1, 10],
        objections=["We're at capacity", "Insurance drives our patient flow"],
        decision_maker="practice manager",
        buyer_phrases=["urgent care near me open now", "doctor accepting new patients"],
        spend_signals=["accepting new patients", "extended hours", "walk-ins welcome"],
    ),
    "insurance": Vertical(
        key="insurance",
        label="insurance agency",
        service="insurance coverage",
        urgent_scenario="I need to file a claim after an accident",
        jobs=["commercial liability policy", "home insurance", "auto coverage"],
        economics=Economics(avg_ticket=900, lifetime_value=5600, typical_cac=280,
                            monthly_queries=210, booking_rate=0.012),
        peak_months=[1, 6],
        objections=["Carrier leads keep us busy", "We're a captive agency"],
        decision_maker="agency principal",
        buyer_phrases=["insurance agent near me", "cheapest home insurance quote"],
        spend_signals=["multiple carriers", "Google Ads presence", "local sponsorships"],
    ),
}

#: Fallback for anything unmapped. Deliberately conservative economics.
GENERIC = Vertical(
    key="home_services",
    label="home service contractor",
    service="home repair",
    urgent_scenario="I have an urgent home repair emergency",
    jobs=["remodeling", "electrical work", "general repairs"],
    economics=Economics(avg_ticket=600, lifetime_value=2800, typical_cac=240,
                        monthly_queries=250, booking_rate=0.018),
    peak_months=[5, 9],
    objections=["We're busy enough", "Referrals cover us"],
    decision_maker="owner",
    buyer_phrases=["contractor near me", "who to call for home repair"],
    spend_signals=["branded vehicle", "Google Ads presence"],
)


def get(vertical: str) -> Vertical:
    return VERTICALS.get(vertical, GENERIC)


# ---------------------------------------------------------------------------
# Derived arguments
# ---------------------------------------------------------------------------

def revenue_at_risk(vertical: str, missed_answers: int, total_answers: int,
                    market_queries_per_month: int | None = None) -> dict[str, float | str]:
    """Estimate the revenue a visibility gap plausibly costs, per year.

    This is the number that turns a marketing conversation into an ROI
    calculation, so it is built to be defensible rather than impressive:

    * It counts only the share of customers who arrive via search at all.
    * It assumes a deliberately low conversion from "saw the answer" to "booked".
    * It reports first-job revenue, not lifetime value, as the headline.

    ``market_queries_per_month`` is the weakest input — real volume varies
    hugely by metro — so it is surfaced in the output rather than buried, and
    the caller can override it.
    """
    v = get(vertical)
    econ = v.economics
    queries = market_queries_per_month or econ.monthly_queries
    total = max(1, total_answers)
    miss_rate = max(0.0, min(1.0, missed_answers / total))

    # Searches → arriving via search → resolving to an AI answer → the business
    # absent from it. Each step discounts the estimate rather than inflating it.
    exposed = queries * econ.search_share * econ.ai_answer_share * miss_rate
    lost_jobs_month = exposed * econ.booking_rate

    annual_first_job = lost_jobs_month * econ.avg_ticket * 12
    annual_lifetime = lost_jobs_month * econ.lifetime_value * 12

    return {
        "lost_jobs_per_month": round(lost_jobs_month, 1),
        "annual_revenue": round(annual_first_job, -2),
        "annual_lifetime_value": round(annual_lifetime, -2),
        "avg_ticket": econ.avg_ticket,
        "lifetime_value": econ.lifetime_value,
        "assumption": (
            f"Assumes ~{queries} buyer-intent searches a month for "
            f"{v.label}s in a market this size, {int(econ.search_share * 100)}% of "
            f"new customers arriving via search, {int(econ.ai_answer_share * 100)}% "
            f"of those resolving to an AI answer, and a "
            f"{econ.booking_rate * 100:.1f}% booking rate. Every step is set low on "
            f"purpose — the real figure is likely higher."
        ),
    }


def payback_line(vertical: str, monthly_price: float) -> str:
    """One sentence a trade owner can check against their own numbers."""
    v = get(vertical)
    jobs = monthly_price / v.economics.avg_ticket
    if jobs <= 1.05:
        return (f"One {v.service} job covers roughly a month of this "
                f"(average ticket about ${v.economics.avg_ticket:,.0f}).")
    if jobs <= 3:
        return (f"About {jobs:.1f} jobs a month covers this, against an average "
                f"ticket of ${v.economics.avg_ticket:,.0f}.")
    return (f"Roughly {jobs:.0f} jobs a month covers this. Worth checking against "
            f"your own average ticket.")


def seasonal_note(vertical: str, month: int) -> str:
    """Whether now is a good moment to be pitching this trade."""
    v = get(vertical)
    ahead = [(p - month) % 12 for p in v.peak_months]
    nearest = min(ahead)
    if nearest == 0:
        return (f"Peak season now. Owners are busy and hard to reach, but the cost "
                f"of being invisible is at its highest.")
    if 1 <= nearest <= 3:
        return (f"{nearest} month(s) before peak ({v.peak_label()}). The best window "
                f"to pitch — demand is coming and there is still time to act.")
    return (f"Off-season. Owners have time to talk, but less urgency. Lead with the "
            f"run-up to {v.peak_label()}.")


def plan_fit(vertical: str, monthly_price: float) -> dict[str, object]:
    """Whether this price is defensible for this trade, and on what basis.

    Not every vertical justifies the same retainer on the same argument. An
    HVAC contractor can be sold on first-job revenue alone. A dentist cannot —
    a single new patient is worth $259 on the first visit, so the honest case
    rests on lifetime value and has to be made that way. Selling a dentist on
    first-job maths would be a claim that falls apart the moment they check it.

    Returns the ratio, which argument holds, and a plain verdict.
    """
    r = revenue_at_risk(vertical, 10, 10)
    annual_price = monthly_price * 12
    first_job_ratio = float(r["annual_revenue"]) / annual_price
    lifetime_ratio = float(r["annual_lifetime_value"]) / annual_price

    if first_job_ratio >= 1.5:
        basis, verdict = "first-job revenue", "strong"
    elif lifetime_ratio >= 4.0:
        basis, verdict = "lifetime value", "workable"
    else:
        basis, verdict = "neither", "weak"

    return {
        "vertical": vertical,
        "monthly_price": monthly_price,
        "first_job_ratio": round(first_job_ratio, 2),
        "lifetime_ratio": round(lifetime_ratio, 1),
        "basis": basis,
        "verdict": verdict,
        "guidance": {
            "strong": "Sell on first-job revenue. The arithmetic stands on its own.",
            "workable": ("Lead with lifetime value — first-job revenue alone does not "
                         "cover the retainer here, and claiming it would not survive "
                         "scrutiny."),
            "weak": ("This price is hard to defend for this trade. Price lower, or "
                     "spend the outreach somewhere the maths works."),
        }[verdict],
    }


def best_verticals(monthly_price: float) -> list[dict[str, object]]:
    """Rank the trades by how well they justify a given retainer."""
    rows = [plan_fit(k, monthly_price) for k in VERTICALS]
    order = {"strong": 0, "workable": 1, "weak": 2}
    return sorted(rows, key=lambda r: (order[str(r["verdict"])],
                                       -float(r["first_job_ratio"])))
