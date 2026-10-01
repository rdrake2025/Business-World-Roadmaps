"""The audit runner — the single code path that produces every audit.

Used in two modes, and this reuse is the economic engine of the business:

* **Free teaser** (``depth="teaser"``): 4 prompts, run against cold prospects
  to generate the personalised hook in the outreach email. Costs fractions of
  a cent per prospect.
* **Full audit** (``depth="full"``): the paid deliverable.

The same code sells the deal and delivers the service, so every improvement
to the audit improves both conversion and retention simultaneously.
"""

from __future__ import annotations

import concurrent.futures
import logging

from . import crawlers
from .config import Settings
from .engines.base import AnswerEngine
from .engines.live import build_engines
from .models import Audit, Business, ProbeResult, new_id
from .prompts import build_prompts
from .scoring import interpret, score_audit

log = logging.getLogger("answerrank.audit")

DEPTHS = {"teaser": 4, "full": 10, "deep": 16}

#: What every caller says when real mode has no answer engine to ask.
NO_ENGINE = ("No AI engine key is saved, so nothing was checked. Add your OpenAI "
             "key in Keys and settings (desktop menu).")


class NoAnswerEngine(RuntimeError):
    """Real mode, and no engine key: refusing beats inventing a score."""


class MeasurementFailed(RuntimeError):
    """Too few questions came back answered to count as a measurement."""


#: Below this share of questions answered, nothing is kept. An audit of an
#: outage reads as a business nobody names: saved, it was a 0 in a pilot's
#: history, the before-and-after said "it went the wrong way", and the next
#: re-measure waited 28 days because one had just been done. Running out of
#: OpenAI credit, which a $5 start will do, failed every question at once.
MIN_ANSWERED = 0.8

#: Where the last failed measurement is noted for the Today list. Cleared by
#: the next one that works.
OUTAGE_KEY = "measure.outage"


def why_failed(errors: list[str], asked: int) -> str:
    """What went wrong, in words, and what to do about it."""
    return (f"{len(errors)} of {asked} questions asked got no answer, so nothing was "
            f"measured and nothing was saved. {fix_for(errors)}")


def fix_for(errors: list[str]) -> str:
    """What to do about failed answers, from what the engines said."""
    text = " ".join(errors).lower()
    if "insufficient_quota" in text or "exceeded your current quota" in text:
        fix = ("OpenAI says the account is out of credit. Add some at "
               "platform.openai.com, Settings, Billing ($5 covers about ten "
               "measurements), then leave AnswerRank open: it tries again within "
               "the hour.")
    elif "http 401" in text or "invalid_api_key" in text or "incorrect api key" in text:
        fix = ("An answer engine turned the key down. Check it in Keys and settings "
               "(desktop menu, option 2).")
    elif "http 429" in text:
        fix = ("An answer engine is limiting how fast it answers. AnswerRank tries "
               "again within the hour.")
    elif any(w in text for w in ("connectionerror", "timeout", "max retries", "name resolution")):
        fix = ("The answer engines couldn't be reached. Is the internet connection "
               "up? AnswerRank tries again within the hour.")
    else:
        fix = (f"The first error was: {errors[0][:160]}. AnswerRank tries again "
               f"within the hour.")
    return fix


def note_outage(store, why: str) -> None:
    import json
    from datetime import datetime, timezone
    store.kv_set(OUTAGE_KEY, json.dumps(
        {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "why": why}))


def clear_outage(store) -> None:
    if store.kv_get(OUTAGE_KEY):
        store.kv_set(OUTAGE_KEY, "")


def outage(store) -> dict | None:
    """The last failed measurement, if nothing has worked since."""
    import json
    raw = store.kv_get(OUTAGE_KEY)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None

#: Estimated USD per probe, with web search: OpenAI $10/1k searches plus
#: tokens on gpt-5-mini; Anthropic $10/1k searches (up to two) plus the
#: tokens results add; Perplexity Sonar's request fee plus tokens; one
#: Serper query. Checked against the providers' pricing pages, Sept 2026.
ENGINE_COST = {"openai": 0.015, "anthropic": 0.03, "perplexity": 0.007,
               "google_aio": 0.001, "mock": 0.0}


def run_audit(business: Business, settings: Settings, depth: str = "full",
              engines: list[AnswerEngine] | None = None,
              max_workers: int = 6, check_crawlers: bool = False) -> Audit:
    """Probe every (prompt x engine) pair and score the result.

    ``check_crawlers`` additionally reads the site's robots.txt. It is off by
    default so this function stays a pure measurement of the engines; the
    Auditor agent turns it on, which is where the other budget decisions live.
    """
    if engines is None and not settings.can_measure():
        raise NoAnswerEngine(NO_ENGINE)
    limit = DEPTHS.get(depth, DEPTHS["full"])
    engine_names = settings.available_engines()
    if depth == "teaser":
        chosen = [n for n in (getattr(settings, "teaser_engines", None) or [])
                  if n in engine_names]
        engine_names = chosen or engine_names
    engines = engines or build_engines(
        engine_names, business.name, business.vertical, settings.request_timeout,
        city=business.city, state=business.state,
    )
    repeats = 1 if depth == "teaser" else max(1, int(getattr(settings, "probe_repeats", 1)))

    prompts = build_prompts(business.vertical, business.city, business.state, limit)
    audit = Audit(
        business_id=business.id,
        business_name=business.name,
        market=business.market,
        vertical=business.vertical,
        is_free_teaser=(depth == "teaser"),
    )

    jobs = [(engine, prompt, intent) for prompt, intent in prompts
            for engine in engines for _ in range(repeats)]

    def probe(job) -> ProbeResult:
        engine, prompt, _intent = job
        answer = engine.ask(prompt)
        if answer.error:
            log.warning("probe failed on %s: %s", engine.name, answer.error)
            return ProbeResult(
                probe_id=new_id("prb"), engine=engine.name, prompt=prompt,
                answer_text="", mentioned=False, cited=False, position=None,
                error=answer.error,
            )
        signals = interpret(answer.text, answer.sources, business.name, business.domain)
        return ProbeResult(
            probe_id=new_id("prb"),
            engine=engine.name,
            prompt=prompt,
            # Truncated: we keep enough to quote in the report without
            # bloating the database with full answers.
            answer_text=answer.text[:1500],
            mentioned=bool(signals["mentioned"]),
            cited=bool(signals["cited"]),
            position=signals["position"],  # type: ignore[arg-type]
            competitors=list(signals["competitors"]),  # type: ignore[arg-type]
            sources=answer.sources[:8],
            sentiment=str(signals["sentiment"]),
            latency_ms=answer.latency_ms,
            grounded=bool(getattr(answer, "grounded", False)),
        )

    # Probes are independent network calls; run them concurrently so a
    # 40-probe audit finishes in seconds rather than minutes.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        audit.results = list(pool.map(probe, jobs))

    failed = [r.error for r in audit.results if r.error]
    if audit.results and len(failed) > (1 - MIN_ANSWERED) * len(audit.results):
        raise MeasurementFailed(why_failed(failed, len(audit.results)))

    audit = score_audit(audit)
    audit.cost = round(sum(ENGINE_COST.get(r.engine, 0.01)
                           for r in audit.results if not r.error), 4)

    if check_crawlers and business.website:
        access = crawlers.check_access(business.website, settings.request_timeout)
        audit.crawler_access = {
            "ok": access.ok,
            "robots_found": access.robots_found,
            "blocked": [c.token for c in access.blocked],
            "critical": [c.token for c in access.critical_blocks],
            "headline": access.headline(),
            "fix": access.fix(),
        }
        # Goes first when it bites. Everything else in the audit measures how
        # well the business competes for a place in the answer; this one says
        # it removed itself from the running, which explains the rest of the
        # page and is the cheapest thing on it to fix.
        if access.critical_blocks:
            audit.findings.insert(0, access.headline())

    return audit


def estimate_cost(depth: str, engines, repeats: int = 3) -> float:
    """Rough USD cost of one audit, before it runs.

    ``engines`` is a list of engine names, or a count (then priced at a
    typical engine). After an audit has run, ``audit.cost`` is the figure to
    book: it counts the probes that actually happened.
    """
    per = (sum(ENGINE_COST.get(n, 0.01) for n in engines)
           if isinstance(engines, (list, tuple)) else float(engines) * 0.012)
    reps = 1 if depth == "teaser" else max(1, repeats)
    return round(DEPTHS.get(depth, 10) * per * reps, 4)
