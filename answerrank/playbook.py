"""The sales playbook the agents are trained on.

Until now the agents knew their *market* (``knowledge.py``) and their *ICP*
(``qualify.py``) but not how to sell. The outreach copy was written by hand
and the reply handling improvised. This module encodes the method, so the
same discipline applies on the four-hundredth prospect as on the fourth.

It is drawn from two places, deliberately:

* **This repository's own roadmaps.** ``Sales_Business_Development_README.md``
  specifies BANT (Budget, Authority, Need, Timeline) as the qualification
  framework and names the pitfalls — broad targeting and weak follow-ups —
  that this implementation is built to avoid.
* **Published 2026 benchmarks**, already sourced per trade in
  ``knowledge.py``, which is what lets a BANT score cite a number rather
  than assert a judgement.

Nothing here is a template with blanks. Every output carries a figure the
owner can check against their own books, because a claim they can disprove
costs more than no claim at all.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field

from . import knowledge

# ---------------------------------------------------------------------------
# BANT — the qualification framework
# ---------------------------------------------------------------------------

#: Decision-maker shapes, and how many people have to say yes. A single
#: owner-operator can buy on the call; a practice manager cannot.
AUTHORITY_SHAPE = {
    "owner": (1.0, "Owner decides alone — one conversation closes it."),
    "owner, usually also running jobs": (
        0.92, "Owner decides, but is on a truck all day. Reach them early or late."),
    "owner or office manager": (
        0.80, "Office manager screens; the owner signs. Expect one hand-off."),
    "owner or service manager": (
        0.80, "Service manager screens; the owner signs. Expect one hand-off."),
    "owner or branch manager": (
        0.78, "Branch manager may need corporate sign-off on spend."),
    "practice owner": (0.95, "Practice owner decides — clinical owners move fast on ROI."),
    "practice owner or hospital manager": (
        0.75, "Two-step: the manager gathers, the owner decides."),
    "practice manager": (
        0.62, "Practice manager rarely holds budget. Ask who signs before pitching."),
    "owner or practice manager": (0.72, "Ask early which of the two holds the budget."),
    "managing partner": (0.70, "Partnership decisions need consensus — slower, but sticky."),
    "agency principal": (0.85, "Principal holds the budget outright."),
    "medical director or owner": (
        0.70, "Clinical director may defer spend decisions to an owner."),
}

#: Timeline urgency by how close the trade's peak season is.
TIMELINE_BANDS = [
    (0, 0.70, "Peak season now — they feel the loss, but cannot take a meeting."),
    (1, 1.00, "One month to peak. The single best moment to close this trade."),
    (2, 0.95, "Two months to peak. Enough runway for the work to land in time."),
    (3, 0.85, "Three months to peak. Good window."),
    (5, 0.55, "Mid-cycle. No deadline pressure to lean on."),
    (12, 0.40, "Far from peak. Lead with the run-up, not with urgency."),
]


@dataclass
class BANT:
    """A qualification read with the evidence attached to each dimension."""

    budget: float       #: 0-1
    authority: float
    need: float
    timeline: float
    evidence: dict[str, str] = field(default_factory=dict)
    #: The one question that would most improve this read.
    next_question: str = ""

    @property
    def score(self) -> float:
        """Weighted. Need and Budget predict a close; Timeline mostly predicts *when*."""
        return round(100 * (self.budget * 0.35 + self.need * 0.30
                            + self.authority * 0.20 + self.timeline * 0.15), 1)

    @property
    def verdict(self) -> str:
        s = self.score
        if s >= 72:
            return "qualified"
        if s >= 55:
            return "nurture"
        return "disqualified"

    def summary(self) -> str:
        return (f"BANT {self.score:.0f}/100 ({self.verdict}) — "
                f"B {self.budget:.0%} A {self.authority:.0%} "
                f"N {self.need:.0%} T {self.timeline:.0%}")


def _months_to_peak(vertical: str, month: int) -> int:
    v = knowledge.get(vertical)
    return min((p - month) % 12 for p in v.peak_months)


def bant(business, visibility_score: float | None, competitor_gap: float | None,
         monthly_price: float, month: int = 6) -> BANT:
    """Score a prospect on Budget, Authority, Need and Timeline.

    Each dimension answers a question that can actually kill a deal, and each
    is derived from something measured rather than assumed:

    ``Budget``     does this trade's economics defend this price?
    ``Authority``  how many people have to agree?
    ``Need``       did we measure a gap, and is a competitor in it?
    ``Timeline``   is there a season that makes this urgent?
    """
    v = knowledge.get(business.vertical)
    ev: dict[str, str] = {}

    # --- Budget -----------------------------------------------------------
    fit = knowledge.plan_fit(business.vertical, monthly_price)
    if fit["verdict"] == "strong":
        budget = 0.95
        ev["budget"] = (f"${v.economics.avg_ticket:,.0f} average ticket covers "
                        f"${monthly_price:,.0f}/mo on first-job revenue alone.")
    elif fit["verdict"] == "workable":
        budget = 0.70
        ev["budget"] = (f"Defensible on lifetime value (${v.economics.lifetime_value:,.0f}), "
                        f"not on the first job. Lead with the relationship.")
    else:
        rec = knowledge.recommended_price(business.vertical)
        budget = 0.25
        if rec["price"]:
            ev["budget"] = (f"${monthly_price:,.0f} is not defensible here. "
                            f"Offer ${float(rec['price']):,.0f} instead — {rec['basis']}.")
        else:
            ev["budget"] = "The economics do not support a retainer at any tier."

    # --- Authority --------------------------------------------------------
    authority, auth_note = AUTHORITY_SHAPE.get(
        v.decision_maker, (0.75, f"Decision sits with the {v.decision_maker}."))
    ev["authority"] = auth_note

    # --- Need -------------------------------------------------------------
    if visibility_score is None:
        need, ev["need"] = 0.45, "Not audited yet — run the teaser before pitching."
    elif visibility_score < 25:
        need, ev["need"] = 0.95, "Effectively absent from AI answers. The gap is undeniable."
    elif visibility_score < 50:
        need, ev["need"] = 0.75, "Measured gap, clear enough to show them."
    elif visibility_score < 70:
        need, ev["need"] = 0.40, "Partial visibility — a harder case to make."
    else:
        need, ev["need"] = 0.10, "Already visible. There is no honest problem to sell."

    gap = competitor_gap or 0.0
    if gap >= 30 and need >= 0.4:
        need = min(1.0, need + 0.05)
        ev["need"] += f" A local competitor leads them by {gap:.0f} points."

    # --- Timeline ---------------------------------------------------------
    away = _months_to_peak(business.vertical, month)
    timeline, t_note = next((w, n) for cutoff, w, n in TIMELINE_BANDS if away <= cutoff)
    ev["timeline"] = f"{t_note} Peak: {v.peak_label()}."

    # --- The gap in our own knowledge -------------------------------------
    if visibility_score is None:
        question = "Run the free audit first — everything else is guesswork without it."
    elif budget < 0.5:
        question = f"Ask what they spend on marketing now before quoting ${monthly_price:,.0f}."
    elif authority < 0.75:
        question = "Ask who signs off on marketing spend before building a proposal."
    else:
        question = "Ask what would have to be true for them to act this quarter."

    return BANT(budget=budget, authority=authority, need=need, timeline=timeline,
                evidence=ev, next_question=question)


# ---------------------------------------------------------------------------
# Objection handling
# ---------------------------------------------------------------------------

#: Matched in order. Each rebuttal concedes the owner's point first — an
#: objection argued with is an objection repeated, and these owners have heard
#: every marketing pitch already.
REBUTTALS: list[tuple[str, str, str]] = [
    ("regulated",
     r"bar rules|advertising rules|compliance|regulat|what we can say|"
     r"(medical|legal) (advertising|marketing) (rules|restrictions)",
     "That constraint is real, and this stays inside it. Nothing here makes a "
     "claim about outcomes or uses a testimonial. It is structured factual "
     "information — services, service area, credentials, hours, answers to "
     "questions you already answer on the phone — published where an assistant "
     "can verify it. The rules govern what you may claim, not whether you may "
     "be findable."),
    ("selective",
     r"not taking new (patients|clients)|not accepting new|"
     r"reimbursement|panel rates|wait ?list",
     "Then this is a question about which work, not more of it. Visibility is "
     "what lets you choose: when the assistant names you, the people who call "
     "are the ones who searched for what you actually want to do, rather than "
     "whoever happened to find the number. That is worth more to a full "
     "practice than to an empty one."),
    ("known_locally",
     r"everyone (around here|in town) (already )?knows us|been coming here|"
     r"twenty years|thirty years|our (injector|doctor|stylist)'?s? following|"
     r"established here|reputation speaks",
     "That reputation is real and it is doing its job with the people who "
     "already have it. This is about the person who does not — the one who "
     "moved here last month, has nobody to ask, and types the question into "
     "an assistant. They get three names. Your standing locally does not "
     "reach that conversation."),
    ("channel_dependency",
     r"insurance (panel|work|drives)|carrier leads|lead broker|buy leads|"
     r"already (buy|purchase) leads|(builders?|contractors?|warranty compan\w+|"
     r"the county inspector|designers?) (send|keep|sell)|angi|home ?advisor|thumbtack",
     "That works until it doesn't, and the part worth noticing is that you "
     "don't control it. A panel changes its list, a broker raises its price, a "
     "builder finds someone cheaper — and none of that is yours to decide. "
     "Being the name an assistant gives is demand you own outright. It is the "
     "one channel nobody can take off you."),
    ("seasonal",
     r"storms? (season|bring|give)|seasonal|summer fills|"
     r"winter is the problem|catch up in (spring|summer)|busy season|in season",
     "That's the argument for doing it now rather than against doing it. The "
     "businesses an assistant names during the rush were indexed and "
     "corroborated months earlier — the answer is already built by the time "
     "the phones start. The off-season is the only window where this work can "
     "land before it matters."),
    ("price_shopping",
     r"shop(s|ped)? us on price|price shootout|race to the bottom|"
     r"cheaper (mow|quote|price)|everyone wants (a )?cheap",
     "Being one of five quotes is a price fight. Being the business the "
     "assistant named is not — you arrive already recommended, and the "
     "conversation starts from trust instead of from the number. That is the "
     "difference this changes, and it is the one that protects your margin."),
    ("small_operation",
     r"one[- ]van|two trucks|one truck|small shop|two[- ]truck|just me and|"
     r"we'?re a (small|two)",
     "Then the goal is not more calls — it is better ones. A small crew that "
     "gets named for the high-value job instead of the $90 callout makes more "
     "money from the same week. Volume is not the point here; selection is."),
    ("no_residential",
     r"don'?t do residential|commercial only|we'?re commercial|no residential",
     "Commercial buyers search the same way. A facility manager comparing "
     "vendors asks an assistant exactly like a homeowner does, and gets the "
     "same short list. The trade changes; the mechanism doesn't."),
    ("already_pay_seo",
     r"seo|agency|marketing (guy|company|person)|already pay|"
     r"spend (heavily )?on ads|google ads|adwords|\bppc\b",
     "That's usually true, and it's why this is a separate problem. A site can "
     "rank first in local search and still be absent from the AI answer — "
     "assistants build answers from structured data and corroborating sources, "
     "not from the results page. Your SEO spend isn't failing; it's aimed "
     "somewhere else."),
    ("no_time",
     r"no time|too busy (to|in|for)|busy in season|swamped|don'?t have time",
     "Understood. The work is ours, not yours — the only thing we need from "
     "you is about ten minutes of answers in the first week, and nothing "
     "after that."),
    ("phone_rings",
     r"phone rings|stay busy|busy enough|booked|backlog|enough work|capacity|full",
     "Good — that means this isn't urgent, which is the right time to fix it. "
     "The question isn't whether the phone rings today, it's who gets named "
     "when it slows down. The businesses in the answer now set that for the "
     "next two years."),
    ("referrals",
     r"referral|word of mouth|repeat customers|past clients|"
     r"existing (patients|clients|customers)|neighbou?rs refer",
     "Referrals are the best channel you have, and nothing here touches them. "
     "This is about the customer who has nobody to ask. They type the question "
     "into an assistant, get three names, and you were never in the running."),
    ("tried_marketing",
     r"tried .*(marketing|advertis)|wasted money|didn'?t work|worthless|got nothing",
     "Fair, and most of it doesn't. That's why the first report is free and "
     "there's no call attached — you can read what we measured and decide "
     "whether it's real before any money changes hands."),
    ("price",
     r"too expensive|can'?t afford|cost too much|out of (our|my) budget|"
     r"margins are too thin|margins.{0,12}thin",
     None),  # filled per-vertical by rebuttal(), which knows the payback maths
    ("chains",
     r"chain|franchise|national|corporate|big box|dealer|"
     r"own the search|outspend|dominate the",
     "They outspend you on ads, but an AI answer isn't bought. It's assembled "
     "from what a model can verify about a business — hours, service area, "
     "specialisms, corroborating sources. That's a fight a good local operator "
     "can actually win."),
]


def rebuttal(objection: str, vertical: str = "", monthly_price: float = 997.0) -> str:
    """The answer to an objection, conceding the owner's point first.

    Returns an empty string when nothing matches, which routes the reply to a
    human rather than producing a confident non-answer.
    """
    low = (objection or "").lower()
    for key, pattern, text in REBUTTALS:
        if not re.search(pattern, low):
            continue
        if key == "price":
            pay = knowledge.payback_line(vertical or "hvac", monthly_price)
            rec = knowledge.recommended_price(vertical or "hvac")
            cheaper = ""
            if rec["price"] and float(rec["price"]) < monthly_price:
                cheaper = (f" If that's still too much, there's a "
                           f"${float(rec['price']):,.0f}/mo tier that covers the "
                           f"tracking and the highest-value fixes.")
            return (f"Reasonable question. {pay} If it doesn't return that, it "
                    f"isn't worth buying and you should cancel.{cheaper}")
        return text or ""
    return ""


def objection_brief(vertical: str, monthly_price: float = 997.0) -> list[dict[str, str]]:
    """What this trade will actually say, and the answer to each.

    Built from the objections recorded for the vertical, so the brief an agent
    reads before writing to a roofer is not the one it reads for a dentist.
    """
    v = knowledge.get(vertical)
    out = []
    for objection in v.objections:
        answer = rebuttal(objection, vertical, monthly_price)
        out.append({
            "objection": objection,
            "answer": answer or ("No scripted answer — handle this one personally."),
        })
    return out


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discovery_questions(vertical: str) -> list[str]:
    """Questions that make the prospect do the arithmetic themselves.

    A number the owner says out loud is worth more than the same number in our
    email, because it is theirs. Each of these is designed to surface one
    input to the ROI case rather than to build rapport.
    """
    v = knowledge.get(vertical)
    top_job = v.jobs[0] if v.jobs else v.service
    return [
        f"What's your average ticket on a {top_job} right now?",
        "Of the customers who called you last month, how many had never heard "
        "of you before they searched?",
        f"When someone asks an assistant for {knowledge.a_label(vertical)} in "
        f"{{city}}, who do you "
        f"think it names?",
        f"What does {v.peak_label()} usually do to your call volume?",
        "What are you spending a month to get a new customer today?",
        "If nothing changes here, what does that cost you over a year?",
    ]


def value_proposition(vertical: str, monthly_price: float, brand: str) -> str:
    """The positioning statement, stated in the trade's own economics."""
    v = knowledge.get(vertical)
    risk = knowledge.revenue_at_risk(vertical, 7, 10)
    return (
        f"For {knowledge.plural(v.label)} who are invisible when customers ask an "
        f"AI assistant "
        f"who to call, {brand} measures exactly which questions you're missing, "
        f"fixes what makes you unfindable, and tracks it every month. A typical "
        f"gap costs about ${float(risk['annual_revenue']):,.0f} a year in "
        f"first-job revenue. {knowledge.payback_line(vertical, monthly_price)}"
    )


# ---------------------------------------------------------------------------
# Follow-up discipline
# ---------------------------------------------------------------------------

#: Plain-text email wraps at a fixed width. Not every mail client soft-wraps
#: well, and a body with one 100-column line among a dozen short ones reads as
#: machine-generated before a word of it is read.
WRAP = 74


def email_body(*paragraphs: str) -> str:
    """Wrap and join paragraphs into a plain-text email body.

    Every message the system writes goes through here, so a long interpolated
    business name cannot produce a ragged line in one agent's copy and not
    another's.
    """
    out = []
    for para in paragraphs:
        if not para or not para.strip():
            continue
        # A paragraph carrying its own newlines is a block the author laid out
        # deliberately — a signature, an address — so each line wraps on its
        # own rather than being collapsed into one.
        out.append("\n".join(_wrap_line(line) if line.strip() else ""
                             for line in para.strip().split("\n")))
    return "\n\n".join(out)


_LIST_MARKER = re.compile(r"^(\s*(?:[-*•]|\d+[.)])\s+)")


def _wrap_line(line: str) -> str:
    """One line, wrapped. List items hang under their own text, and a name
    like OAI-SearchBot is never split at its hyphen."""
    marker = _LIST_MARKER.match(line)
    indent = " " * len(marker.group(1)) if marker else ""
    return textwrap.fill(line, WRAP, subsequent_indent=indent,
                         break_on_hyphens=False, break_long_words=False)


#: ``Sales_Business_Development_README.md`` names weak follow-ups as one of
#: the two pitfalls of the prospecting stage. This is the corrective: each
#: touch must carry a new idea, and a touch that only asks "any thoughts?"
#: is not a follow-up, it is attrition.
SEQUENCE_INTENT = {
    1: "Evidence. One measured fact about their business and the free report offer.",
    2: "Reframe. Why their existing SEO spend did not prevent this.",
    3: "Permission to close. Make saying no easy; a clean no beats silence.",
}


#: A first email over this many words (before the footer) is not sent.
FIRST_TOUCH_MAX_WORDS = 100


def sequence_check(step: int, body: str) -> list[str]:
    """Problems with a drafted message, before it costs a reputation point."""
    problems = []
    sentences = [s for s in re.split(r"[.!?]\s", body) if s.strip()]
    if len(sentences) > 12:
        problems.append(f"{len(sentences)} sentences — past about a dozen, replies halve.")
    if step in SEQUENCE_INTENT and not body.strip():
        problems.append("Empty body.")
    if step == 1:
        # The signature and the legal footer don't count: the reader skips them.
        core = body.split("\n---\n")[0]
        words = len(core.split())
        if words > FIRST_TOUCH_MAX_WORDS:
            problems.append(
                f"{words} words. The best first emails average under 80 "
                f"(Instantly, 2026); over {FIRST_TOUCH_MAX_WORDS} is rejected.")
    if re.search(r"\b(just checking in|any thoughts|bumping this|circling back)\b",
                 body, re.I):
        problems.append("Contains a content-free nudge. Every touch needs a new idea.")
    if "unsubscribe" not in body.lower():
        problems.append("No unsubscribe line — CAN-SPAM requires one on every send.")
    longest = max((len(line) for line in body.split("\n")), default=0)
    if longest > WRAP + 4:
        problems.append(f"A line runs to {longest} columns. Build the body with "
                        f"`email_body` so an interpolated name cannot break the wrap.")
    return problems
