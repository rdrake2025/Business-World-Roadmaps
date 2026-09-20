"""Buyer-intent prompt generation.

We do not ask "what do you think of Apex HVAC" — that guarantees a mention
and measures nothing. We ask what a customer with money in hand actually
asks an assistant, then check whether the client shows up in the answer.

Prompts are spread across four intents because they fail differently:

* ``discovery``  — "best X in Y". Generic, highest volume, hardest to win.
* ``emergency``  — urgent, highest ticket value, often under-optimised.
* ``comparison`` — the buyer is choosing between named options.
* ``trust``      — licensing, warranty, reviews. Where schema markup pays off.
"""

from __future__ import annotations

from . import knowledge
from .models import Probe

#: Per-vertical language, derived from :mod:`answerrank.knowledge` rather than
#: duplicated here. This was a second hand-maintained copy, and it had already
#: drifted badly: fifteen of the twenty-two trades were missing from it, so the
#: Scout searched local listings for "home service contractor" instead of "pest
#: control company" and brought back the wrong businesses entirely. A library
#: that has to be updated in two places is a library that will be updated in
#: one.
VERTICALS: dict[str, dict[str, object]] = {
    key: {
        "label": v.label,
        "service": v.service,
        "urgent": v.urgent_scenario,
        "jobs": list(v.jobs),
    }
    for key, v in knowledge.VERTICALS.items()
}

#: The fallback for anything unrecognised, matching ``knowledge.GENERIC``.
VERTICALS.setdefault("home_services", {
    "label": knowledge.GENERIC.label,
    "service": knowledge.GENERIC.service,
    "urgent": knowledge.GENERIC.urgent_scenario,
    "jobs": list(knowledge.GENERIC.jobs),
})


def vertical_meta(vertical: str) -> dict[str, object]:
    return VERTICALS.get(vertical, VERTICALS["home_services"])


def build_prompts(vertical: str, city: str, state: str = "", limit: int = 10) -> list[tuple[str, str]]:
    """Return ``(prompt, intent)`` pairs for a market, most valuable first.

    Prompts are written the way customers actually type them, not the way a
    marketer would phrase a query. Half-formed, urgent, and specific about the
    job — because that is what produces a realistic answer to measure against.
    """
    v = knowledge.get(vertical)
    label, service, urgent = v.label, v.service, v.urgent_scenario
    jobs = list(v.jobs)
    where = f"{city}, {state}".strip(", ") if state else city

    # An emergency prompt only makes sense where emergencies exist.
    second = (
        (f"{urgent} in {where}. Who should I call right now?", "emergency")
        if v.has_emergencies else
        (f"{urgent} in {where}. Which ones are worth considering?", "comparison")
    )

    prompts: list[tuple[str, str]] = [
        (f"Who is the best {label} in {where}?", "discovery"),
        second,
        (f"Recommend a trustworthy {label} near {where} with good reviews.", "trust"),
        (f"What are the top 5 {label}s in {where}?", "discovery"),
        (f"I need {service} in {where}. Which local companies should I compare?", "comparison"),
        ((f"Which {label} in {where} offers 24/7 emergency service?", "emergency")
         if v.has_emergencies else
         (f"Which {label} in {where} has the best reviews?", "trust")),
        (f"Who has the best pricing for {service} in {where}?", "comparison"),
        (f"Is there a licensed and insured {label} in {where} you would recommend?", "trust"),
    ]
    # Highest-value jobs first: an answer that names you for "system
    # replacement" is worth far more than one for "duct cleaning".
    for job in jobs[:3]:
        prompts.append((f"Who does the best {job} in {where}?", "discovery"))

    # Real buyer phrasing, appended verbatim with the market. These are the
    # half-formed queries people actually type, and they surface different
    # answers than a well-formed question does.
    for phrase in v.buyer_phrases[:3]:
        prompts.append((f"{phrase} in {where}", "discovery"))

    prompts.append((f"What should I look for when hiring a {label} in {where}, and who do you suggest?", "trust"))

    return prompts[:limit]


def build_probes(vertical: str, city: str, state: str, engines: list[str],
                 limit: int = 10) -> list[Probe]:
    """Cartesian product of prompts x engines — the full audit workload."""
    probes: list[Probe] = []
    for prompt, intent in build_prompts(vertical, city, state, limit):
        for engine in engines:
            probes.append(Probe(prompt=prompt, engine=engine, intent=intent))
    return probes
