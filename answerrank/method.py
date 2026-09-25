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
    #: Keys into ``evidence.LIBRARY``: the research this lever rests on.
    evidence: tuple[str, ...] = ()

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
        title="Make the business readable and specific",
        thesis=("Nothing else matters while an engine cannot read the site or "
                "cannot tell exactly what the business does. This month is the "
                "fastest work in the engagement: a page per job, the Google "
                "profile set up properly, and nothing blocking the engines."),
        levers=[
            Lever("unblock_crawlers", "Allow the answer engines in robots.txt",
                  "A site that disallows OAI-SearchBot or PerplexityBot cannot "
                  "appear in their answers at all, however good the content is. "
                  "This is a gate, not a ranking factor.",
                  BOTH, 15, (2, 14),
                  "Re-read /robots.txt and confirm the names are allowed."),
            Lever("service_pages", "One page per high-value job, naming the city",
                  "A dedicated page for each service is the second-strongest "
                  "AI-visibility factor in Whitespark's 2026 survey, and for home "
                  "services most engines cite the contractor's own site more than "
                  "anything else. A single services page competes for everything "
                  "and wins nothing.",
                  US, 10, (14, 56),
                  "Each page is reachable in two clicks from the homepage and "
                  "names the job and the city in its title.",
                  ("ai_visibility_factors", "home_services_sources")),
            Lever("gbp_core", "Set up the Google Business Profile properly",
                  "The primary category is the single strongest local-pack factor "
                  "(Whitespark 2026), and 'open at the time of search' is in the "
                  "top five, so the category and the hours come first. Services "
                  "decide which questions the profile is eligible for.",
                  CLIENT, 45, (7, 21),
                  "Primary category is the most specific one offered; hours and "
                  "services are complete.",
                  ("local_pack_factors",)),
            Lever("localbusiness_schema", "Publish LocalBusiness JSON-LD",
                  "Structured data states the trade, area, hours and phone as "
                  "machine-readable facts. It is quick and helps Google's own "
                  "features, but practitioners rank it only 44th for AI "
                  "visibility (Whitespark 2026), so it is done in twenty minutes "
                  "and not sold as the thing that moves the answers.",
                  BOTH, 15, (7, 21),
                  "Google's Rich Results Test returns the type with no errors.",
                  ("ai_visibility_factors",)),
        ],
    ),
    Phase(
        month=2,
        title="Get onto the lists the engines quote",
        thesis=("The strongest AI-visibility factor is being on the expert "
                "'best of' lists for the trade and town, and those are the "
                "directories ChatGPT cites most for local questions. This month "
                "puts the business in front of them, and answers the questions "
                "the audit showed being lost."),
        levers=[
            Lever("curated_lists", "Get onto the expert 'best of' lists",
                  "Presence on expert-curated best-of lists is the #1 AI-visibility "
                  "factor in Whitespark's 2026 survey, and curated sites such as "
                  "Three Best Rated and Expertise are the directories ChatGPT "
                  "cites most for local searches (BrightLocal). These sites choose "
                  "who they list, which is exactly why a listing counts.",
                  BOTH, 20, (28, 90),
                  "The business appears on each list's page for its trade and "
                  "city, or a nomination is on record with a date to re-apply.",
                  ("ai_visibility_factors", "chatgpt_search_sources")),
            Lever("faq_content", "Publish answer-shaped copy for the lost questions",
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
        ],
    ),
    Phase(
        month=3,
        title="Make the business resolvable as one entity",
        thesis=("An engine will not name a business it cannot confidently "
                "resolve. Disagreeing records across directories look like "
                "several businesses, or like none. Most of what the engines "
                "quote is the business's own site and its listings."),
        levers=[
            Lever("nap_consistency", "Make name, address and phone byte-identical",
                  "Entity resolution is a matching problem. “St” against "
                  "“Street”, or two phone numbers, splits one business into "
                  "several weak records instead of one strong one.",
                  US, 10, (21, 56),
                  "Search the phone number in quotes; every result shows the "
                  "same name and address."),
            Lever("core_citations", "Claim the listings the engines check, Bing first",
                  "86% of AI citations come from a business's own site and its "
                  "listings (Yext). ChatGPT Search runs on Bing (BrightLocal), so "
                  "Bing Places matters as much as Google; Apple Business Connect "
                  "feeds Siri and Apple Maps.",
                  # Only the verification steps need the owner: Google, Bing and
                  # Apple want a code sent to them. The form-filling is ours.
                  BOTH, 25, (21, 56),
                  "Each listing is claimed, not merely present.",
                  ("brand_managed_citations", "chatgpt_search_sources")),
            Lever("trade_authority", "Get listed in the trade's own directories",
                  "Prominence on industry-relevant sites is the #3 AI-visibility "
                  "factor (Whitespark 2026). A trade association or licensing "
                  "directory carries far more weight per listing than a general "
                  "one, because membership is gated on something.",
                  BOTH, 15, (28, 84),
                  "The business is findable by name in each directory's search.",
                  ("ai_visibility_factors",)),
        ],
    ),
    Phase(
        month=4,
        title="Give the engines proof to quote",
        thesis=("Reviews are the corroboration engines quote most, and recency "
                "counts: three in four customers look at the last three months "
                "only. This is the month the compounding starts."),
        levers=[
            Lever("review_velocity", "A new review at least every two weeks",
                  "74% of consumers prioritise reviews from the last three months "
                  "and 32% want one from the last two weeks; 68% will not consider "
                  "a business under 4 stars (BrightLocal 2026). Forty reviews from "
                  "three years ago read as a business that used to be good.",
                  CLIENT, 20, (28, 90),
                  "A new review appears at least every two weeks, not in bursts, "
                  "and the average stays at 4.0 or above.",
                  ("consumer_reviews_2026", "local_pack_factors")),
            Lever("third_party_reviews", "Reviews on the trade's respected sites too",
                  "The authority of the sites holding a business's reviews is the "
                  "#5 AI-visibility factor (Whitespark 2026), and for home "
                  "services nearly half of ChatGPT's citations are directories and "
                  "review platforms. Reviews only on Google are invisible to an "
                  "engine reading the BBB or Angi.",
                  BOTH, 15, (28, 90),
                  "New reviews land on at least one site besides Google each month.",
                  ("ai_visibility_factors", "home_services_sources")),
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
                  "A dealer locator is a prominent listing on an industry site, "
                  "the #3 AI-visibility factor (Whitespark 2026), and is usually "
                  "free to a business already buying the product.",
                  BOTH, 30, (28, 90),
                  "The business appears in each locator's own search.",
                  ("ai_visibility_factors",)),
            Lever("local_presence", "Local press, sponsorship, community listings",
                  "Unstructured citations — mentions on other sites — are the #4 "
                  "AI-visibility factor (Whitespark 2026): 'mentions are the new "
                  "link'. An independent local mention ties the business to a "
                  "place in a way no amount of its own copy can.",
                  CLIENT, 45, (56, 180),
                  "At least one new independent mention per quarter.",
                  ("ai_visibility_factors",)),
        ],
    ),
]

#: What happens every month regardless of phase.
STANDING = [
    Lever("re_audit", "Re-run the full audit",
          "The score is the deliverable. AI answers change almost every run "
          "(SparkToro 2026), so each question is asked three times and the "
          "result is a share with a margin, measured the same way each month.",
          US, 0, (0, 0),
          "The report shows this month against the start, with its margin.",
          ("ai_answers_vary",)),
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


def already_done(lever: Lever, audit=None) -> bool:
    """Whether the audit has already verified this lever needs no work.

    Only claims what was measured. Robots.txt is the one lever the audit
    checks directly: when it was read and lets every answer engine in, telling
    the owner to "allow the answer engines" asks them to fix something that
    is not broken — which they can check in ten seconds, and which costs the
    credibility of everything else on the page. The month-1 plan and the
    prospect's report both said it regardless.
    """
    if lever.key != "unblock_crawlers" or audit is None:
        return False
    access = getattr(audit, "crawler_access", None) or {}
    # ``ok`` is False both when something critical is blocked and when the
    # file could not be read — and an unread file verifies nothing.
    return bool(access) and bool(access.get("ok"))


def first_fixes(vertical: str = "", audit=None, n: int = 3) -> list[Lever]:
    """The fixes that move the score fastest, in the order the arc does them,
    leaving out anything the audit shows is already right."""
    out: list[Lever] = []
    for phase in PHASES:
        for lever in plan(phase.month, vertical, audit)["levers"]:
            if lever.key not in {l.key for l in out}:
                out.append(lever)
            if len(out) >= n:
                return out
    return out


def plan(month: int, vertical: str = "", audit=None) -> dict[str, object]:
    """This month's work, adjusted for what the audit actually found.

    The arc is the default, not a script. A blocked robots.txt outranks
    everything and moves to the front whatever month it is found in, because
    every other lever is worthless while it holds.
    """
    current = phase_for(month)
    levers = [l for l in current.levers if not already_done(l, audit)]
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
    if trade and current.month == 1:
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
