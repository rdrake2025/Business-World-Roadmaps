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
  Restoration job / CLV    — PuroClean, Palm Build, PushLeads restoration (2026)
  Med spa visit / LTV      — Zenoti, DigitalMedSpa, ScaleHaven aesthetics (2026)
  Electrician pricing      — Housecall Pro electrician pricing; 99 Calls LSA (2026)
  Garage door pricing      — Housecall Pro garage door price guide (2026)
  Tree service CAC         — Financial Models Lab tree care benchmarks (2026)
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
    #: Whether this trade has genuine emergencies. A burst pipe does; a med
    #: spa does not, and framing one as urgent produces a prompt no real
    #: customer would type — which measures nothing.
    has_emergencies: bool = True
    #: The schema.org type a retrieval engine should see. This lived as a
    #: lookup table inside the Fixer and covered seven trades of twenty-two,
    #: so fifteen were published as a generic ``LocalBusiness`` — the one
    #: signal that tells an engine what the business actually *is*, discarded.
    #: It belongs on the trade, where adding a vertical forces choosing one.
    schema_type: str = "LocalBusiness"

    def peak_label(self) -> str:
        names = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May",
                 6: "June", 7: "July", 8: "August", 9: "September",
                 10: "October", 11: "November", 12: "December"}
        return " and ".join(names[m] for m in self.peak_months)


#: schema.org types we are confident exist and are recognised. A type that is
#: subtly wrong is worse than a generic one: the engine drops the whole block
#: rather than reading past it, so the markup that was supposed to help is
#: simply not read.
KNOWN_SCHEMA_TYPES = {
    "LocalBusiness", "ProfessionalService", "HomeAndConstructionBusiness",
    "HVACBusiness", "Plumber", "RoofingContractor", "Electrician",
    "GeneralContractor", "HousePainter", "Locksmith", "MovingCompany",
    "AutomotiveBusiness", "AutoRepair",
    "MedicalBusiness", "MedicalClinic", "Dentist", "Physician", "VeterinaryCare",
    "LegalService", "Attorney",
    "FinancialService", "InsuranceAgency",
    "HealthAndBeautyBusiness", "DaySpa",
}


VERTICALS: dict[str, Vertical] = {
    "hvac": Vertical(
        key="hvac",
        schema_type="HVACBusiness",
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
        schema_type="Plumber",
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
        schema_type="RoofingContractor",
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
        schema_type="Dentist",
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
        schema_type="Attorney",
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
    "restoration": Vertical(
        key="restoration",
        schema_type="GeneralContractor",
        label="restoration contractor",
        service="water damage restoration",
        urgent_scenario="My basement is flooding right now",
        jobs=["water damage restoration", "mold remediation", "fire damage repair",
              "storm damage cleanup", "sewage cleanup"],
        # National average job $3,860 (range $1,383-$6,370); CLV ~$5,000 with
        # repeat customers producing 60% of annual revenue; industry CAC ~$200,
        # though paid leads run $150-350. Volume is low because a flood is rare,
        # but intent is near-total when it happens.
        economics=Economics(avg_ticket=3860, lifetime_value=5000, typical_cac=200,
                            monthly_queries=140, search_share=0.55,
                            booking_rate=0.020),
        peak_months=[1, 8],  # winter pipe bursts, summer storm season
        objections=[
            "We're on insurance panels, that's where our work comes from",
            "Storms bring us all the work we can handle",
            "We already buy leads",
            "We're a franchise, marketing is handled corporately",
        ],
        decision_maker="owner or operations manager",
        buyer_phrases=["water damage restoration near me", "emergency flood cleanup",
                       "who to call for basement flooding", "mold removal company",
                       "24 hour water damage"],
        spend_signals=["24/7 emergency line", "IICRC certification displayed",
                       "Google Ads presence", "insurance panel membership",
                       "branded response vehicles"],
    ),
    "med_spa": Vertical(
        key="med_spa",
        schema_type="DaySpa",
        label="medical spa",
        service="aesthetic treatment",
        urgent_scenario="I am looking for a good med spa",
        has_emergencies=False,
        jobs=["body contouring", "laser treatment", "injectables", "chemical peel",
              "skin resurfacing"],
        # Average $536 per visit (range $450-700); lifetime value ~$7,800 over
        # three years at four visits a year; patient acquisition cost ~$285.
        # Single-location marketing budgets run $3,000-10,000/month, the highest
        # of any vertical here — the retainer is a rounding error to them.
        economics=Economics(avg_ticket=536, lifetime_value=7800, typical_cac=285,
                            monthly_queries=320, search_share=0.50,
                            booking_rate=0.015),
        peak_months=[4, 11],  # pre-summer and pre-holiday
        objections=[
            "We already work with a marketing agency",
            "Our injector's following brings the patients",
            "We're booked out for weeks already",
            "Medical advertising rules limit what we can say",
        ],
        decision_maker="owner, often the medical director",
        buyer_phrases=["best med spa near me", "botox near me",
                       "medical spa reviews", "laser hair removal near me",
                       "where to get filler"],
        spend_signals=["membership plan advertised", "heavy Instagram presence",
                       "Google Ads presence", "multiple injectors on staff",
                       "financing offered"],
    ),
    "electrical": Vertical(
        key="electrical",
        schema_type="Electrician",
        label="electrician",
        service="electrical work",
        urgent_scenario="My power keeps tripping and I need an electrician",
        jobs=["panel upgrade", "EV charger installation", "rewiring",
              "outlet and switch repair", "lighting installation"],
        # $40-100/hr with $100-200 service calls; panel upgrades and EV charger
        # installs carry the average well above a service call. Lead cost rose
        # 51% to $43.15 in 2026, which makes organic visibility more valuable.
        economics=Economics(avg_ticket=900, lifetime_value=3600, typical_cac=310,
                            monthly_queries=380, booking_rate=0.022),
        peak_months=[6, 11],
        objections=[
            "We're booked out for weeks",
            "Contractors send us all the work we need",
            "I don't do residential marketing",
        ],
        decision_maker="owner, often still on the tools",
        buyer_phrases=["electrician near me", "breaker keeps tripping who to call",
                       "ev charger installer", "cost to upgrade electrical panel"],
        spend_signals=["licensed and bonded displayed", "Google Ads presence",
                       "EV charger certification", "branded vans"],
    ),
    "tree_service": Vertical(
        key="tree_service",
        schema_type="HomeAndConstructionBusiness",
        label="tree service",
        service="tree removal",
        urgent_scenario="A tree came down on my property after a storm",
        jobs=["emergency tree removal", "tree removal", "stump grinding",
              "pruning and trimming", "storm cleanup"],
        # Emergency removal is the highest-value line by a wide margin;
        # published CAC around $300 with an industry goal of $220 by 2030.
        economics=Economics(avg_ticket=1400, lifetime_value=2800, typical_cac=300,
                            monthly_queries=260, booking_rate=0.020),
        peak_months=[3, 9],  # storm seasons
        objections=[
            "Storm season gives us more work than we can take",
            "We get everything from referrals and HOAs",
            "Marketing didn't work when we tried it",
        ],
        decision_maker="owner",
        buyer_phrases=["emergency tree removal near me", "tree fell on house who to call",
                       "tree removal cost", "arborist near me"],
        spend_signals=["ISA certified arborist", "24/7 storm response advertised",
                       "chipper and bucket truck fleet", "Google Ads presence"],
    ),
    "garage_door": Vertical(
        key="garage_door",
        schema_type="HomeAndConstructionBusiness",
        label="garage door company",
        service="garage door repair",
        urgent_scenario="My garage door is stuck and my car is trapped inside",
        jobs=["door installation", "opener replacement", "torsion spring replacement",
              "track and roller repair"],
        # Repairs $150-600, springs $200-600, openers $300-800, full install
        # $800-2,500+. High frequency, modest ticket — the case rests on volume.
        economics=Economics(avg_ticket=450, lifetime_value=1300, typical_cac=190,
                            monthly_queries=300, booking_rate=0.028),
        peak_months=[1, 7],  # cold snaps and heat both break springs
        objections=[
            "We're a two-truck shop, we stay busy",
            "Builders and property managers keep us full",
            "Our phone rings enough",
        ],
        decision_maker="owner",
        buyer_phrases=["garage door repair near me", "garage door spring broke",
                       "garage door won't open", "same day garage door repair"],
        spend_signals=["same-day service advertised", "Google Ads presence",
                       "branded trucks", "manufacturer dealer status"],
    ),
    "medical": Vertical(
        key="medical",
        schema_type="MedicalClinic",
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
        schema_type="InsuranceAgency",
        label="insurance agency",
        service="insurance coverage",
        urgent_scenario="I am shopping for an insurance agent",
        jobs=["commercial liability policy", "home insurance", "auto coverage"],
        has_emergencies=False,
        economics=Economics(avg_ticket=900, lifetime_value=5600, typical_cac=280,
                            monthly_queries=210, booking_rate=0.012),
        peak_months=[1, 6],
        objections=["Carrier leads keep us busy", "We're a captive agency"],
        decision_maker="agency principal",
        buyer_phrases=["insurance agent near me", "cheapest home insurance quote"],
        spend_signals=["multiple carriers", "Google Ads presence", "local sponsorships"],
    ),
    "pest_control": Vertical(
        key="pest_control",
        schema_type="HomeAndConstructionBusiness",
        label="pest control company",
        service="pest treatment",
        urgent_scenario="I found bed bugs in my bedroom",
        jobs=["bed bug treatment", "termite treatment", "rodent exclusion",
              "quarterly protection plan", "wasp nest removal"],
        # Initial service $300-550; the money is in the quarterly plan, which
        # runs ~$140 a visit and retains for 3-5 years.
        economics=Economics(avg_ticket=400, lifetime_value=2600, typical_cac=180,
                            monthly_queries=380, search_share=0.50, booking_rate=0.030),
        peak_months=[5, 6],  # spring emergence and summer swarms
        objections=[
            "We're seasonal, we catch up in spring anyway",
            "Terminix and Orkin own the search results",
            "Our route is full",
        ],
        decision_maker="owner or branch manager",
        buyer_phrases=["exterminator near me", "how to get rid of bed bugs fast",
                       "termite inspection cost", "same day pest control"],
        spend_signals=["quarterly plan advertised", "Google Ads presence",
                       "branded trucks", "free inspection offer"],
    ),
    "auto_repair": Vertical(
        key="auto_repair",
        schema_type="AutoRepair",
        label="auto repair shop",
        service="car repair",
        urgent_scenario="My car won't start and I need it fixed today",
        jobs=["engine diagnostics and repair", "transmission service", "brake job",
              "check engine light", "oil change"],
        # Average repair order sits around $500; a retained customer returns
        # two to three times a year for the life of the vehicle.
        economics=Economics(avg_ticket=500, lifetime_value=4200, typical_cac=250,
                            monthly_queries=550, search_share=0.40, booking_rate=0.028),
        peak_months=[1, 7],  # cold-start failures and summer road-trip season
        objections=[
            "We have a two-week backlog already",
            "Our customers have been coming here for twenty years",
            "Dealers get all the online business",
        ],
        decision_maker="owner or service manager",
        buyer_phrases=["mechanic near me", "why is my check engine light on",
                       "brake repair cost", "honest auto shop near me"],
        spend_signals=["ASE certified technicians", "loaner cars offered",
                       "Google Ads presence", "review count above 100"],
    ),
    "veterinary": Vertical(
        key="veterinary",
        schema_type="VeterinaryCare",
        label="veterinary clinic",
        service="veterinary care",
        urgent_scenario="My dog is sick and I need a vet who can see him today",
        jobs=["emergency visit", "surgery", "dental cleaning", "wellness plan",
              "vaccinations"],
        # Per-visit spend is modest but a pet is a decade-long relationship,
        # so the honest case here is lifetime value, not the first visit.
        economics=Economics(avg_ticket=320, lifetime_value=4800, typical_cac=220,
                            monthly_queries=420, search_share=0.45, booking_rate=0.030),
        peak_months=[5, 9],  # parasite season and back-to-school puppy intake
        objections=[
            "We're not taking new patients",
            "Corporate groups are buying up every practice around us",
            "Our schedule is booked three weeks out",
        ],
        decision_maker="practice owner or hospital manager",
        buyer_phrases=["emergency vet near me open now", "vet accepting new patients",
                       "how much does a dog dental cost", "24 hour animal hospital"],
        spend_signals=["accepting new patients", "wellness plan advertised",
                       "after-hours line", "AAHA accreditation"],
    ),
    "chiropractic": Vertical(
        key="chiropractic",
        schema_type="MedicalBusiness",
        label="chiropractor",
        service="chiropractic care",
        urgent_scenario="I threw my back out and I can barely move",
        jobs=["initial care plan", "spinal decompression", "auto injury rehab",
              "adjustment visit"],
        # A single adjustment is ~$65, but new patients arrive on a care plan
        # worth $800-1,100 and many return for years afterwards.
        economics=Economics(avg_ticket=850, lifetime_value=3600, typical_cac=190,
                            monthly_queries=260, search_share=0.55, booking_rate=0.025),
        peak_months=[1, 9],  # new-year resolutions and post-summer injuries
        objections=[
            "Referrals from our existing patients keep us full",
            "Insurance reimbursement is what limits us, not patients",
            "We tried a marketing company and got nothing",
        ],
        decision_maker="practice owner",
        buyer_phrases=["chiropractor near me", "chiropractor that takes my insurance",
                       "back pain who to see", "walk in chiropractor today"],
        spend_signals=["new patient special advertised", "online booking",
                       "Google Ads presence", "review count above 80"],
    ),
    "remodeling": Vertical(
        key="remodeling",
        schema_type="GeneralContractor",
        label="remodeling contractor",
        service="kitchen and bath remodeling",
        urgent_scenario="I am planning a kitchen remodel and comparing contractors",
        jobs=["full kitchen remodel", "bathroom remodel", "home addition",
              "basement finishing"],
        has_emergencies=False,
        # Very high ticket, very low volume, long consideration with three or
        # four bids — the booking rate is set correspondingly low.
        economics=Economics(avg_ticket=28000, lifetime_value=38000, typical_cac=1900,
                            monthly_queries=140, search_share=0.55, booking_rate=0.010),
        peak_months=[3, 9],  # spring planning and pre-holiday completion
        objections=[
            "We're booked through next year",
            "Our work comes from designers and past clients",
            "Leads from Angi were worthless",
        ],
        decision_maker="owner",
        buyer_phrases=["kitchen remodel cost", "best remodeling contractor near me",
                       "bathroom renovation contractors", "home addition builder"],
        spend_signals=["portfolio gallery on site", "design showroom",
                       "financing offered", "NARI or NKBA membership"],
    ),
    "flooring": Vertical(
        key="flooring",
        schema_type="HomeAndConstructionBusiness",
        label="flooring contractor",
        service="flooring installation",
        urgent_scenario="I am choosing a flooring installer and want quotes",
        jobs=["whole-home hardwood installation", "luxury vinyl plank",
              "tile installation", "carpet replacement", "refinishing"],
        has_emergencies=False,
        economics=Economics(avg_ticket=4200, lifetime_value=6400, typical_cac=620,
                            monthly_queries=190, search_share=0.50, booking_rate=0.012),
        peak_months=[4, 10],
        objections=[
            "Big box stores control the installs",
            "Builders keep our crews busy",
            "Everyone shops us on price anyway",
        ],
        decision_maker="owner",
        buyer_phrases=["flooring installers near me", "cost to install hardwood floors",
                       "lvp vs laminate", "who installs tile floors"],
        spend_signals=["showroom", "free in-home estimate", "Google Ads presence",
                       "manufacturer certified installer"],
    ),
    "appliance_repair": Vertical(
        key="appliance_repair",
        schema_type="HomeAndConstructionBusiness",
        label="appliance repair company",
        service="appliance repair",
        urgent_scenario="My refrigerator stopped cooling and the food is spoiling",
        jobs=["refrigerator repair", "washer and dryer repair", "oven repair",
              "dishwasher repair"],
        # Low ticket, high frequency, decided in minutes — this trade lives or
        # dies on being the name the assistant says first.
        economics=Economics(avg_ticket=280, lifetime_value=900, typical_cac=120,
                            monthly_queries=460, search_share=0.55, booking_rate=0.032),
        peak_months=[7, 11],  # summer fridge failures, holiday oven failures
        objections=[
            "We're a one-van operation",
            "Warranty companies send us all the work we need",
            "Margins are too thin for marketing",
        ],
        decision_maker="owner",
        buyer_phrases=["appliance repair near me", "fridge not cooling who to call",
                       "same day washer repair", "samsung repair technician near me"],
        spend_signals=["same-day service advertised", "factory authorized",
                       "Google Ads presence", "online booking"],
    ),
    "septic": Vertical(
        key="septic",
        schema_type="HomeAndConstructionBusiness",
        label="septic service company",
        service="septic service",
        urgent_scenario="My septic tank is backing up into the house",
        jobs=["septic system replacement", "drain field repair", "tank pumping",
              "inspection for a home sale"],
        # Routine pumping is ~$500; failures and replacements run into the
        # thousands, and the blended figure reflects both.
        economics=Economics(avg_ticket=1100, lifetime_value=3400, typical_cac=230,
                            monthly_queries=180, search_share=0.60, booking_rate=0.035),
        peak_months=[4, 11],  # spring saturation and holiday household load
        objections=[
            "Everyone around here already knows us",
            "The county inspector sends us work",
            "We only have two trucks",
        ],
        decision_maker="owner",
        buyer_phrases=["septic pumping near me", "septic backing up who to call",
                       "septic inspection for closing", "drain field repair cost"],
        spend_signals=["emergency service advertised", "county permitted installer",
                       "Google Ads presence", "real estate inspection service"],
    ),
    "moving": Vertical(
        key="moving",
        schema_type="MovingCompany",
        label="moving company",
        service="moving services",
        urgent_scenario="I need movers for a house move in two weeks",
        jobs=["long-distance move", "full-service local move", "packing services",
              "piano and specialty moving"],
        # Search-dominated: almost nobody has a mover they already use, which
        # makes the AI answer unusually decisive for this trade.
        economics=Economics(avg_ticket=1300, lifetime_value=2100, typical_cac=290,
                            monthly_queries=320, search_share=0.65, booking_rate=0.018),
        peak_months=[6, 7],  # the summer moving season
        objections=[
            "Summer fills itself, winter is the problem",
            "Lead brokers already sell us moves",
            "Every quote turns into a price shootout",
        ],
        decision_maker="owner",
        buyer_phrases=["movers near me", "how much do movers cost",
                       "best moving company reviews", "last minute movers"],
        spend_signals=["binding estimate offered", "DOT number displayed",
                       "Google Ads presence", "review count above 60"],
    ),
    "landscaping": Vertical(
        key="landscaping",
        schema_type="HomeAndConstructionBusiness",
        label="landscaping company",
        service="landscaping",
        urgent_scenario="I want my yard redone before summer",
        jobs=["hardscape and patio installation", "irrigation installation",
              "landscape design", "seasonal maintenance contract", "sod installation"],
        has_emergencies=False,
        # Maintenance contracts are what make the lifetime value work; the
        # blended ticket carries both a mow route and a $9,000 patio.
        economics=Economics(avg_ticket=650, lifetime_value=4800, typical_cac=210,
                            monthly_queries=400, search_share=0.45, booking_rate=0.022),
        peak_months=[4, 5],
        objections=[
            "Our route is full by April",
            "Neighbours refer us, we've never advertised",
            "Everyone wants a cheaper mow",
        ],
        decision_maker="owner",
        buyer_phrases=["landscaper near me", "patio installation cost",
                       "lawn care service near me", "landscape designer near me"],
        spend_signals=["design portfolio", "maintenance contracts advertised",
                       "Google Ads presence", "branded trailers"],
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


#: Markets under exploration. Readable by the audit machinery so a candidate
#: can be measured, but deliberately excluded from every decision function —
#: a market we have not adopted must not influence pricing or targeting.
PROVISIONAL: dict[str, "Vertical"] = {}


def get(vertical: str) -> Vertical:
    """Adopted verticals first, then anything under exploration."""
    return VERTICALS.get(vertical) or PROVISIONAL.get(vertical, GENERIC)


def register_provisional(v: "Vertical") -> None:
    """Make a candidate market auditable without adopting it."""
    if v.key not in VERTICALS:
        PROVISIONAL[v.key] = v


def is_adopted(vertical: str) -> bool:
    return vertical in VERTICALS


#: Letters whose *name* begins with a vowel sound. "HVAC" is spoken
#: "aych-vac", so it takes "an" despite starting with a consonant — the kind
#: of detail a trade owner notices in a cold email even if they cannot say why.
_ACRONYM_VOWEL_SOUND = set("AEFHILMNORSX")


def article(phrase: str) -> str:
    """"a" or "an" for a phrase, acronyms included."""
    words = (phrase or "").split()
    if not words:
        return "a"
    word = words[0]
    if word.isupper() and len(word) > 1:
        return "an" if word[0] in _ACRONYM_VOWEL_SOUND else "a"
    return "an" if word[0].lower() in "aeiou" else "a"


def plural(label: str) -> str:
    """Pluralise a trade label. "garage door company" -> "garage door companies"."""
    if not label:
        return label
    head, _, last = label.rpartition(" ")
    if last.endswith("y") and len(last) > 1 and last[-2].lower() not in "aeiou":
        last = last[:-1] + "ies"
    elif last.endswith(("s", "x", "z", "ch", "sh")):
        last += "es"
    else:
        last += "s"
    return f"{head} {last}".strip()


def sentence_case(text: str) -> str:
    """Capitalise the first letter and leave the rest alone.

    ``str.capitalize`` would turn "HVAC contractor" into "Hvac contractor",
    which reads as carelessness to the one audience that would notice.
    """
    return (text[:1].upper() + text[1:]) if text else text


def a_label(vertical: str) -> str:
    """"an HVAC contractor", "a plumber" — ready to drop into a sentence."""
    label = get(vertical).label
    return f"{article(label)} {label}"


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
            f"{plural(v.label)} in a market this size, "
            f"{int(econ.search_share * 100)}% of "
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


def from_candidate(candidate) -> Vertical:
    """A provisional Vertical for a market we have not adopted yet.

    The Explorer needs to run real audits in a candidate trade to find out
    whether the visibility gap it assumes is actually there. That requires a
    Vertical, and building one from the candidate's own figures keeps the
    measurement honest — it tests the market as described, not an idealised
    version of it.
    """
    label = candidate.label
    return Vertical(
        key=candidate.key,
        label=label,
        service=label.replace(" contractor", "").replace(" clinic", ""),
        urgent_scenario=f"I need {article(label)} {label} urgently",
        jobs=[f"{label} work"],
        economics=Economics(
            avg_ticket=candidate.avg_ticket,
            # Unknown until researched; a conservative multiple of ticket.
            lifetime_value=candidate.avg_ticket * 2.5,
            typical_cac=candidate.avg_ticket * 0.2,
            # Volume scales inversely with ticket size: nobody needs a $4,500
            # restoration job as often as a $400 pest treatment. Without this,
            # high-ticket candidates generate revenue claims no owner believes.
            monthly_queries=int(max(60, min(400, 240_000 / max(candidate.avg_ticket, 100)))),
            booking_rate=max(0.004, min(0.025, 0.025 * candidate.urgency)),
        ),
        peak_months=[6],
        objections=["We get enough work already"],
        decision_maker="owner",
        buyer_phrases=[f"{label} near me", f"best {label}", f"emergency {label}"],
        spend_signals=["Google Ads presence", "branded vehicle"],
    )


#: The standard pricing ladder, low to high. Kept here rather than imported
#: from config so the knowledge layer has no dependency on runtime settings.
PRICE_LADDER: list[float] = [297.0, 497.0, 997.0, 1997.0]


def recommended_price(vertical: str, ladder: list[float] | None = None) -> dict[str, object]:
    """The highest price this trade's economics actually defend.

    Previously a trade that failed at $997 was simply dropped. That threw away
    real markets for a reason that was never about the market: an appliance
    repair shop cannot justify $997 on a $280 ticket, but it justifies $297
    comfortably. The answer to weak economics is a lower tier, not silence.

    Returns the tier, the basis it rests on, and — when nothing on the ladder
    works — an honest ``None`` rather than a price we would have to defend
    with a number the owner could disprove.
    """
    rungs = sorted(ladder or PRICE_LADDER, reverse=True)
    for price in rungs:
        fit = plan_fit(vertical, price)
        if fit["verdict"] in {"strong", "workable"}:
            return {
                "vertical": vertical,
                "price": price,
                "verdict": fit["verdict"],
                "basis": fit["basis"],
                "line": (f"{sentence_case(plural(get(vertical).label))} support "
                         f"${price:,.0f}/mo on {fit['basis']}."),
            }
    return {
        "vertical": vertical,
        "price": None,
        "verdict": "weak",
        "basis": "neither",
        "line": (f"No tier on the ladder is defensible for {get(vertical).label}s. "
                 f"The ticket is too small and the relationship too short."),
    }


def priced_verticals(ladder: list[float] | None = None) -> list[dict[str, object]]:
    """Every adopted trade with the tier it should be sold at, best first."""
    rows = [recommended_price(k, ladder) for k in VERTICALS]
    sellable = [r for r in rows if r["price"] is not None]
    unsellable = [r for r in rows if r["price"] is None]
    sellable.sort(key=lambda r: (-float(r["price"] or 0),
                                 0 if r["verdict"] == "strong" else 1))
    return sellable + unsellable
