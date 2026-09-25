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
