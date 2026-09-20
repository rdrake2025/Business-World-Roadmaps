"""The delivery method: what actually moves the score, and in what order.

``playbook.py`` trained the agents to sell. This trains them to deliver, and
it exists for a specific commercial reason. A client paying a retainer for
twelve months was receiving roughly the same six files every month. That is
the churn mechanism the Retention agent names in as many words — *they are
paying for movement they cannot see* — and it arrives on a 60-to-90 day
delay, long before anyone asks to cancel.

So the work is sequenced into an arc. Each month does something the previous
month did not, in an order chosen by what moves an answer engine soonest for
the least client effort, and each phase states how to verify it landed.

Two honesty rules are load-bearing here:

**Time-to-effect is stated and never shortened.** Structured data shows up
when an engine next crawls, which is days to weeks. Review velocity compounds
over months. A client told to expect results in thirty days and shown none is
a client who cancels in month three — the overpromise causes the churn it was
meant to prevent.

**We say who does the work.** A plan full of tasks the owner has to do is a
plan that does not get done, and then the retainer looks worthless. Where the
owner is the only one who can act — they hold the Google login, they are the
one who can ask a customer for a review — that is marked, and it is kept
small on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import knowledge

#: Who can actually perform the work.
US, CLIENT, BOTH = "us", "client", "both"


@dataclass(frozen=True)
class Lever:
    """One piece of work, with the mechanism that makes it matter."""

    key: str
    name: str
    #: *Why* an answer engine cares. Not the benefit — the mechanism.
    why: str
    owner: str
    #: Client minutes. Ours is not their problem and is deliberately not shown.
    client_minutes: int
    #: (earliest, typical) days before it can show in a re-audit.
    effect_days: tuple[int, int]
    #: How to confirm it actually landed, rather than assuming.
    verify: str

    def timing(self) -> str:
        earliest, typical = self.effect_days
        if typical <= 21:
            return f"shows up in {earliest}-{typical} days"
        return f"builds over {earliest // 7}-{typical // 7} weeks"


@dataclass(frozen=True)
class Phase:
    month: int
    title: str
    #: The one sentence that goes at the top of the client's report.
    thesis: str
    levers: list[Lever] = field(default_factory=list)

    def client_minutes(self) -> int:
        return sum(l.client_minutes for l in self.levers if l.owner != US)


# ---------------------------------------------------------------------------
# The arc
# ---------------------------------------------------------------------------

PHASES: list[Phase] = [
    Phase(
        month=1,
        title="Make the site readable",
        thesis=("Nothing else matters while an engine cannot read the page or "
                "cannot tell what the business is. This month is the cheapest "
                "and fastest work in the whole engagement."),
        levers=[
            Lever("unblock_crawlers", "Allow the answer engines in robots.txt",
                  "A site that disallows OAI-SearchBot or PerplexityBot cannot "
                  "appear in their answers at all, however good the content is. "
                  "This is a gate, not a ranking factor.",
                  BOTH, 15, (2, 14),
                  "Re-read /robots.txt and confirm the names are allowed."),
            Lever("localbusiness_schema", "Publish LocalBusiness JSON-LD",
                  "Retrieval-based engines quote what they can parse. Structured "
                  "data states the trade, the service area, the hours and the "
                  "phone as machine-readable facts rather than as prose an "
                  "engine has to infer from.",
                  BOTH, 20, (7, 21),
                  "Google's Rich Results Test returns the type with no errors."),
            Lever("gbp_core", "Complete the Google Business Profile",
                  "The local pack is a direct input to AI Overviews for local "
                  "service intent. Categories and services are the fields that "
                  "decide which queries the profile is eligible for.",
                  CLIENT, 45, (7, 21),
                  "Every field populated; primary category is the most specific "
                  "one offered."),
        ],
    ),
    Phase(
        month=2,
        title="Answer the questions being lost",
        thesis=("The audit named the exact questions where a competitor is "
                "chosen instead. This month publishes an answer to each one, "
                "in the form an engine can lift."),
        levers=[
            Lever("faq_content", "Publish answer-shaped copy for the lost prompts",
                  "An engine assembling an answer prefers a passage that already "
                  "answers the question in the first forty words. Copy written to "
                  "be skimmed by a person buries the answer under a preamble, so "
                  "there is nothing to lift.",
                  US, 10, (14, 35),
                  "Search the exact question and confirm the page is returned."),
            Lever("faqpage_schema", "Publish FAQPage JSON-LD for those answers",
                  "Marks each question and answer as a discrete pair rather than "
                  "as a wall of text, so a model can take one without the rest.",
                  BOTH, 15, (7, 21),
                  "Rich Results Test lists every pair."),
            Lever("service_pages", "One page per high-value job, naming the city",
                  "A single services page competes for everything and wins "
                  "nothing. The job with the largest ticket deserves a page that "
                  "is about that job in that market and nothing else.",
                  US, 20, (21, 56),
                  "Each page is reachable in two clicks from the homepage."),
        ],
    ),
    Phase(
        month=3,
        title="Make the business resolvable as one entity",
        thesis=("An engine will not name a business it cannot confidently "
                "resolve. Disagreeing records across directories look like "
                "several businesses, or like none."),
        levers=[
            Lever("nap_consistency", "Make name, address and phone byte-identical",
                  "Entity resolution is a matching problem. “St” against "
                  "“Street”, or two phone numbers, splits one business into "
                  "several weak records instead of one strong one.",
                  US, 10, (21, 56),
                  "Search the phone number in quotes; every result shows the "
                  "same name and address."),
            Lever("core_citations", "Claim the nine listings every engine checks",
                  "Corroboration from sources that are not the business's own "
                  "site is what moves a claim from asserted to verified.",
                  # Only the verification steps need the owner: Google and
                  # Apple want a code sent to them. The form-filling is ours.
                  BOTH, 25, (21, 56),
                  "Each listing is claimed, not merely present."),
            Lever("trade_authority", "Get listed in the trade's own directories",
                  "A trade association or licensing directory carries far more "
                  "weight per listing than a general one, because membership is "
                  "gated on something.",
                  BOTH, 15, (28, 84),
                  "The business is findable by name in each directory's search."),
        ],
    ),
    Phase(
        month=4,
        title="Give the engines proof to quote",
        thesis=("Reviews are the corroboration engines quote most often, and "
                "recency counts as much as volume. This is the month the "
                "compounding starts."),
        levers=[
            Lever("review_velocity", "A repeatable review ask after every job",
                  "Recency is weighted: forty reviews from three years ago read "
                  "as a business that used to be good. A steady trickle reads as "
                  "one that still is.",
                  CLIENT, 20, (28, 90),
                  "New reviews appear every week, not in bursts."),
            Lever("review_responses", "Reply to every review, naming the job and city",
                  "A reply is indexable text that pairs the business with a "
                  "service and a place, written by the business, attached to a "
                  "third-party record.",
                  US, 10, (21, 60),
                  "No review older than a week sits unanswered."),
        ],
    ),
    Phase(
        month=5,
        title="Widen the surface",
        thesis=("With the foundation holding, the work becomes covering more "
                "of the questions being asked rather than defending the ones "
                "already won."),
        levers=[
            Lever("location_pages", "Genuinely distinct pages for each service area",
                  "A model can tell the difference between a page about a place "
                  "and a template with the place name swapped in. The second "
                  "kind is ignored at best.",
                  US, 25, (28, 84),
                  "Each page names local detail a template could not produce."),
            Lever("job_gallery", "Real jobs, described, with image structured data",
                  "Specific completed work is the most quotable evidence a "
                  "service business has, and almost nobody publishes it in a "
                  "form an engine can read.",
                  BOTH, 30, (28, 84),
                  "Each entry has a description, not only a photo."),
        ],
    ),
    Phase(
        month=6,
        title="Build authority off your own site",
        thesis=("Everything so far is what the business says about itself, or "
                "what customers say. This is what independent sources say, "
                "which is the hardest to get and the slowest to decay."),
        levers=[
            Lever("supplier_locators", "Get into manufacturer and supplier locators",
                  "A dealer locator is a strong third-party signal and is usually "
                  "free to a business already buying the product.",
                  BOTH, 30, (28, 90),
                  "The business appears in each locator's own search."),
            Lever("local_presence", "Local press, sponsorship, community listings",
                  "An independent mention on a local domain ties the business to "
                  "a place in a way no amount of its own copy can.",
                  CLIENT, 45, (56, 180),
                  "At least one new independent mention per quarter."),
        ],
    ),
]

#: What happens every month regardless of phase.
STANDING = [
    Lever("re_audit", "Re-run the full audit",
          "The score is the deliverable. Measuring monthly is what makes the "
          "work visible and catches a regression before the client finds it.",
          US, 0, (0, 0),
          "The report shows this month against the start."),
    Lever("regressions", "Fix anything that has slipped",
          "Directories silently drop records, site rebuilds remove schema, and "
          "a plugin update can restore a robots.txt block. Nothing stays fixed "
          "on its own.",
          US, 0, (0, 0),
          "Every previously completed item still verifies."),
]


# ---------------------------------------------------------------------------

def phase_for(month: int) -> Phase:
    """The phase for a given month of the engagement. Month 1 is the first."""
    index = max(1, month)
    if index <= len(PHASES):
        return PHASES[index - 1]
    # Past the arc the work is maintenance and widening, which is phases 5-6
    # alternating. Saying so is more honest than inventing a seventh month of
    # novelty that does not exist.
    return PHASES[4 + (index % 2)]


def plan(month: int, vertical: str = "", audit=None) -> dict[str, object]:
    """This month's work, adjusted for what the audit actually found.

    The arc is the default, not a script. A blocked robots.txt outranks
    everything and moves to the front whatever month it is found in, because
    every other lever is worthless while it holds.
    """
    current = phase_for(month)
    levers = list(current.levers)
    overrides: list[str] = []

    access = (getattr(audit, "crawler_access", None) or {}) if audit else {}
    if access.get("critical") and month > 1:
        blocker = next(l for l in PHASES[0].levers if l.key == "unblock_crawlers")
        levers.insert(0, blocker)
        overrides.append(
            "The site is blocking answer engines in robots.txt, so that moves "
            "to the front of this month regardless of the plan — nothing else "
            "can work while it holds.")

    trade = knowledge.get(vertical) if vertical else None
    notes: list[str] = []
    if trade and current.month == 3:
        notes.append("Trade directories for this business: "
                     + ", ".join(trade.directories) + ".")
    if trade and current.month == 2:
        notes.append(f"Highest-value job to give its own page: {trade.jobs[0]}.")

    return {
        "month": month,
        "title": current.title,
        "thesis": current.thesis,
        "levers": levers,
        "standing": list(STANDING),
        "client_minutes": sum(l.client_minutes for l in levers if l.owner != US),
        "overrides": overrides,
        "notes": notes,
    }


def summarise(month: int, vertical: str = "", audit=None) -> str:
    """The plan as plain text, for a report or the console."""
    p = plan(month, vertical, audit)
    lines = [f"Month {p['month']}: {p['title']}", "", str(p["thesis"]), ""]
    for note in p["overrides"]:
        lines += [f"! {note}", ""]
    for lever in p["levers"]:
        who = {US: "we do this", CLIENT: "needs you",
               BOTH: "we prepare it, you approve"}[lever.owner]
        lines.append(f"- {lever.name} ({who}; {lever.timing()})")
        lines.append(f"    Why: {lever.why}")
        lines.append(f"    Done when: {lever.verify}")
    for note in p["notes"]:
        lines += ["", note]
    minutes = p["client_minutes"]
    lines += ["", f"Your time this month: about {minutes} minutes."
              if minutes else "", ]
    return "\n".join(l for l in lines if l is not None)
