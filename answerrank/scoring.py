"""The AnswerRank Visibility Score.

A single 0-100 number the client can watch move month over month. It has to
be (a) honest, (b) hard to game, and (c) explainable to an HVAC owner in one
sentence. Four components:

==============  ======  ====================================================
Component       Weight  What it measures
==============  ======  ====================================================
Presence          40%   How often you are named at all, weighted by how much
                        buyer traffic each engine carries.
Prominence        25%   Where you land when named. Being #1 in a three-name
                        list is worth far more than being #5.
Citation          20%   Whether your own domain is used as a *source*. This
                        is the durable signal — it survives model updates
                        because it is grounded in retrieval, not memory.
Sentiment         15%   The quality of the context you appear in.
==============  ======  ====================================================

Share of voice is reported separately rather than folded in, because clients
need to see the competitor gap as its own number — it is what makes them buy.
"""

from __future__ import annotations

from collections import Counter

from . import knowledge
from .engines.base import (
    cites_domain,
    detect_sentiment,
    extract_businesses,
    name_matches,
)
from .models import Audit, ProbeResult

WEIGHTS = {"presence": 0.40, "prominence": 0.25, "citation": 0.20, "sentiment": 0.15}

SENTIMENT_VALUE = {"positive": 1.0, "neutral": 0.7, "negative": 0.0, "absent": 0.0}

# Relative buyer traffic per engine. Used to weight presence so that being
# invisible on Google AI Overviews costs more than being invisible on a
# smaller assistant.
ENGINE_LABELS = {
    "google_aio": "Google AI Overviews",
    "openai": "ChatGPT",
    "perplexity": "Perplexity",
    "anthropic": "Claude",
    "mock": "Simulated engine",
}

ENGINE_WEIGHTS = {
    "google_aio": 1.8,
    "openai": 1.6,
    "perplexity": 1.3,
    "anthropic": 1.2,
    "mock": 1.0,
}


def prominence_value(position: int | None, total_named: int) -> float:
    """1.0 for the top slot, decaying with rank. Unnamed scores 0."""
    if not position or position < 1:
        return 0.0
    # Harmonic decay: #1 -> 1.00, #2 -> 0.67, #3 -> 0.50, #4 -> 0.40
    return 1.0 / (1.0 + 0.5 * (position - 1))


def interpret(answer_text: str, sources: list[str], business_name: str,
              business_domain: str) -> dict[str, object]:
    """Turn one raw answer into the structured signals the score needs."""
    named = extract_businesses(answer_text)
    mentioned = name_matches(business_name, answer_text)

    position: int | None = None
    if mentioned:
        for idx, candidate in enumerate(named, 1):
            if name_matches(business_name, candidate) or name_matches(candidate, business_name):
                position = idx
                break
        if position is None:
            # Named in prose but not in the list structure: real, but weak.
            position = len(named) + 1 if named else 1

    cited = cites_domain(business_domain, sources)

    competitors = [
        n for n in named
        if not (name_matches(business_name, n) or name_matches(n, business_name))
    ]

    return {
        "mentioned": mentioned,
        "position": position,
        "cited": cited,
        "competitors": competitors,
        "named_count": len(named),
        "sentiment": detect_sentiment(answer_text, business_name),
    }


def score_audit(audit: Audit) -> Audit:
    """Compute the composite score and every subscore, in place."""
    results = [r for r in audit.results if not r.error]
    if not results:
        audit.score = 0.0
        audit.subscores = {k: 0.0 for k in WEIGHTS}
        audit.findings = ["No answer engines responded; audit could not be completed."]
        return audit

    presence_num = presence_den = 0.0
    prom_total = cite_total = sent_total = 0.0
    competitor_counter: Counter[str] = Counter()
    engine_hits: dict[str, list[int]] = {}

    for r in results:
        w = ENGINE_WEIGHTS.get(r.engine, 1.0)
        presence_den += w
        if r.mentioned:
            presence_num += w
        prom_total += prominence_value(r.position, len(r.competitors) + 1)
        cite_total += 1.0 if r.cited else 0.0
        sent_total += SENTIMENT_VALUE.get(r.sentiment, 0.0)
        competitor_counter.update(r.competitors)
        engine_hits.setdefault(r.engine, []).append(1 if r.mentioned else 0)

    n = len(results)
    subs = {
        "presence": presence_num / presence_den if presence_den else 0.0,
        "prominence": prom_total / n,
        "citation": cite_total / n,
        "sentiment": sent_total / n,
    }

    audit.subscores = {k: round(v * 100, 1) for k, v in subs.items()}
    audit.margin = presence_margin(sum(1 for r in results if r.mentioned), n)
    audit.score = round(sum(subs[k] * WEIGHTS[k] for k in WEIGHTS) * 100, 1)
    audit.competitors = dict(competitor_counter.most_common(10))
    audit.competitor_mentions_total = sum(competitor_counter.values())
    audit.engine_breakdown = {
        eng: round(100 * sum(hits) / len(hits), 1) for eng, hits in engine_hits.items()
    }
    audit.findings = generate_findings(audit)
    return audit


def presence_margin(named: int, asked: int, z: float = 1.96) -> float:
    """± points on the share of answers naming the business (Wilson, 95%).

    One sweep is a sample of answers that change run to run; this says how
    far the true share could be from the one measured. Wilson rather than
    the textbook interval because it stays honest at 0 of 4 and 4 of 4.
    """
    if asked <= 0:
        return 0.0
    p = named / asked
    denom = 1 + z * z / asked
    half = z * ((p * (1 - p) / asked + z * z / (4 * asked * asked)) ** 0.5) / denom
    return round(100 * half, 1)


def share_of_voice(audit: Audit) -> dict[str, float]:
    """Percent of all business mentions that went to each player, us included.

    The denominator counts every competitor mention in the sweep, not just
    the named ones. ``audit.competitors`` keeps the ten strongest so the
    report has something to list; dividing by those ten alone quietly
    deleted the long tail and inflated everyone still on the chart.
    """
    mentions = sum(1 for r in audit.results if r.mentioned)
    totals = Counter(audit.competitors)
    totals[audit.business_name] = mentions
    # Audits written before this field existed fall back to what is charted.
    competitor_total = max(audit.competitor_mentions_total,
                           sum(audit.competitors.values()))
    grand = competitor_total + mentions or 1

    # The client is always on their own chart. ``most_common`` breaks ties by
    # insertion order and the client is inserted last, so a business level
    # with its rivals dropped off the bottom of the share-of-voice table in
    # its own report — which reads as a bug to the person paying for it.
    rows = [(name, c) for name, c in totals.most_common(8)
            if name != audit.business_name][:7]
    rows.insert(0, (audit.business_name, mentions))
    return {name: round(100 * c / grand, 1) for name, c in rows}


def competitor_gap(audit: Audit) -> float:
    """How many more answers the leading competitor wins, as a 0-100 figure."""
    mentions = sum(1 for r in audit.results if r.mentioned)
    top = audit.top_competitor
    if not top:
        return 0.0
    n = len(audit.results) or 1
    return round(100 * (top[1] - mentions) / n, 1)


def generate_findings(audit: Audit) -> list[str]:
    """Plain-English findings. These become the report body and the sales email."""
    findings: list[str] = []
    n = len(audit.results) or 1
    mentions = sum(1 for r in audit.results if r.mentioned)
    subs = audit.subscores

    if mentions == 0:
        findings.append(
            f"{audit.business_name} was not named in any of the {n} AI answers tested. "
            "Customers asking an assistant for this service are not being shown this business at all."
        )
    else:
        findings.append(
            f"{audit.business_name} appeared in {mentions} of {n} AI answers "
            f"({round(100 * mentions / n)}% of buyer-intent questions tested)."
        )

    top = audit.top_competitor
    if top and top[1] > mentions:
        findings.append(
            f"{top[0]} was named in {top[1]} of {n} answers — {top[1] - mentions} more than "
            f"{audit.business_name}. Those are booked jobs going to a competitor."
        )

    # The gap in money terms. Stated as an estimate with its assumption
    # attached, because a number a client cannot interrogate is a number they
    # will not believe — and should not.
    risk = knowledge.revenue_at_risk(audit.vertical, n - mentions, n)
    v = knowledge.get(audit.vertical)
    if float(risk["annual_revenue"]) >= 2000:
        findings.append(
            f"At an average ticket of ${v.economics.avg_ticket:,.0f}, that gap is worth "
            f"an estimated ${float(risk['annual_revenue']):,.0f} a year in first-job "
            f"revenue — about {risk['lost_jobs_per_month']} jobs a month. "
            f"{risk['assumption']}"
        )

    if subs.get("citation", 0) < 20:
        findings.append(
            "The business's own website is almost never used as a source by AI engines. "
            "For home services most engines cite the contractor's own site more than "
            "anything else, and a dedicated page per service is the second-strongest "
            "AI-visibility factor (Whitespark 2026): that is the fix."
        )

    weak = [e for e, v in audit.engine_breakdown.items() if v < 25]
    if weak:
        pretty = ", ".join(sorted(ENGINE_LABELS.get(e, e) for e in weak))
        findings.append(f"Visibility is weakest on: {pretty}. These surfaces need dedicated work.")

    if any(r.sentiment == "negative" for r in audit.results):
        findings.append(
            "At least one AI answer described this business in a negative context. "
            "Review-profile remediation should be prioritised."
        )

    if subs.get("prominence", 0) < 30 and mentions:
        # The order of names in an AI answer changes almost every run
        # (SparkToro, 2026), so this is stated as a tendency, never a rank.
        findings.append(
            "When the business is named, it tends to come after its competitors in "
            "the list. The order changes from one answer to the next, so how often it "
            "is named matters more; being named first more often follows from that."
        )
    return findings


def grade(score: float) -> str:
    for threshold, letter in ((80, "A"), (65, "B"), (50, "C"), (35, "D")):
        if score >= threshold:
            return letter
    return "F"
