"""Deterministic mock engine.

Lets the entire platform run — audits, scoring, reports, outreach drafts —
with no API keys and no network. Used for demos, tests, and for dry-running
a prospect list before spending a cent on tokens.

Output is seeded off the business name so the same business always produces
the same visibility profile, which makes report diffs meaningful in demos.
"""

from __future__ import annotations

import hashlib
import random

from .base import AnswerEngine, EngineAnswer

FIXTURE_COMPETITORS = {
    "hvac": ["Cool Breeze Air", "Lone Star Heating & Air", "Summit Climate Co", "AirPro Systems"],
    "plumbing": ["RapidFlow Plumbing", "Anchor Plumbing Co", "BlueLine Plumbers", "Pipeworks LLC"],
    "dental": ["Bright Smile Dental", "Cedar Park Family Dentistry", "Lakeside Dental Group"],
    "legal": ["Harper & Associates", "Stonebridge Law Group", "Vance Injury Law"],
    "roofing": ["Ironclad Roofing", "Summit Roof Co", "TopGuard Roofing"],
    "default": ["Premier Services Group", "Cornerstone Co", "Meridian Partners"],
}


class MockEngine(AnswerEngine):
    name = "mock"
    label = "Simulated Answer Engine"
    weight = 1.0

    def __init__(self, business_name: str = "", vertical: str = "default", visibility: float | None = None):
        self.business_name = business_name
        self.vertical = vertical
        # Seeded so results are stable per business.
        seed = int(hashlib.sha256(business_name.encode()).hexdigest()[:8], 16)
        self._rng = random.Random(seed)
        # Most local businesses genuinely are near-invisible in AI answers;
        # skew the simulation to match that reality (0-45% mention rate).
        self.visibility = visibility if visibility is not None else self._rng.uniform(0.0, 0.45)

    def ask(self, prompt: str) -> EngineAnswer:
        pool = FIXTURE_COMPETITORS.get(self.vertical, FIXTURE_COMPETITORS["default"])
        rng = random.Random(f"{self.business_name}|{prompt}")
        names = list(pool)
        rng.shuffle(names)
        names = names[:3]

        included = rng.random() < self.visibility
        if included and self.business_name:
            names.insert(rng.randint(0, len(names)), self.business_name)

        lines = [f"Here are well-regarded options based on reviews and availability:", ""]
        for i, n in enumerate(names, 1):
            blurb = rng.choice([
                "highly rated for responsiveness",
                "trusted local provider, 24/7 availability",
                "strong reviews for pricing transparency",
                "recommended for emergency work",
            ])
            lines.append(f"{i}. **{n}** - {blurb}")
        lines += ["", "Availability and pricing vary; confirm directly before booking."]

        sources = [f"https://{n.lower().replace(' ', '').replace('&','')}.com" for n in names[:2]]
        sources.append("https://www.yelp.com/search")
        return EngineAnswer(text="\n".join(lines), sources=sources, latency_ms=rng.randint(400, 1800))
