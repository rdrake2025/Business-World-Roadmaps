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

from .models import Probe

# Per-vertical language. Keys map to the ``vertical`` field on Business.
VERTICALS: dict[str, dict[str, object]] = {
    "hvac": {
        "label": "HVAC contractor",
        "service": "AC repair",
        "urgent": "My AC stopped working in a heat wave",
        "jobs": ["AC repair", "furnace replacement", "heat pump installation", "duct cleaning"],
    },
    "plumbing": {
        "label": "plumber",
        "service": "plumbing repair",
        "urgent": "I have a burst pipe flooding my kitchen",
        "jobs": ["water heater replacement", "drain cleaning", "leak detection", "repiping"],
    },
    "roofing": {
        "label": "roofing contractor",
        "service": "roof repair",
        "urgent": "My roof is leaking after a storm",
        "jobs": ["roof replacement", "storm damage repair", "gutter installation"],
    },
    "dental": {
        "label": "dentist",
        "service": "dental care",
        "urgent": "I have severe tooth pain and need to be seen today",
        "jobs": ["dental implants", "Invisalign", "teeth whitening", "root canal"],
    },
    "legal": {
        "label": "attorney",
        "service": "legal representation",
        "urgent": "I was just injured in a car accident",
        "jobs": ["personal injury claim", "estate planning", "business formation"],
    },
    "medical": {
        "label": "medical clinic",
        "service": "primary care",
        "urgent": "I need urgent care today",
        "jobs": ["annual physical", "same-day sick visit", "chronic care management"],
    },
    "insurance": {
        "label": "insurance agency",
        "service": "insurance coverage",
        "urgent": "I need to file a claim after an accident",
        "jobs": ["home insurance quote", "commercial liability policy", "auto coverage review"],
    },
    "home_services": {
        "label": "home service contractor",
        "service": "home repair",
        "urgent": "I have an urgent home repair emergency",
        "jobs": ["remodeling", "electrical work", "general repairs"],
    },
}


def vertical_meta(vertical: str) -> dict[str, object]:
    return VERTICALS.get(vertical, VERTICALS["home_services"])


def build_prompts(vertical: str, city: str, state: str = "", limit: int = 10) -> list[tuple[str, str]]:
    """Return ``(prompt, intent)`` pairs for a market, most valuable first."""
    meta = vertical_meta(vertical)
    label, service, urgent = meta["label"], meta["service"], meta["urgent"]
    jobs: list[str] = list(meta["jobs"])  # type: ignore[arg-type]
    where = f"{city}, {state}".strip(", ") if state else city

    prompts: list[tuple[str, str]] = [
        (f"Who is the best {label} in {where}?", "discovery"),
        (f"{urgent} in {where}. Who should I call right now?", "emergency"),
        (f"Recommend a trustworthy {label} near {where} with good reviews.", "trust"),
        (f"What are the top 5 {label}s in {where}?", "discovery"),
        (f"I need {service} in {where}. Which local companies should I compare?", "comparison"),
        (f"Which {label} in {where} offers 24/7 emergency service?", "emergency"),
        (f"Who has the best pricing for {service} in {where}?", "comparison"),
        (f"Is there a licensed and insured {label} in {where} you would recommend?", "trust"),
    ]
    for job in jobs[:3]:
        prompts.append((f"Who does the best {job} in {where}?", "discovery"))
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
