"""Scout — finds local businesses worth pitching.

Two sources, in priority order:

1. **Serper Places** (live): searches "<vertical> in <city>" and reads the
   local pack. Real businesses, with websites and phone numbers.
2. **Seed file / simulation** (offline): a CSV the operator drops in, or
   generated fixtures so the pipeline is demonstrable without keys.

The Scout enforces one hard rule: never add a business we have already seen.
Duplicate outreach is the fastest way to a spam complaint, and complaint rate
is the constraint that governs the whole acquisition channel.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import requests

from .. import knowledge
from ..models import Business, Prospect
from ..prompts import VERTICALS
from .base import Agent

# Markets chosen for population and service density: enough businesses to
# prospect for months, high enough ticket values to support a retainer.
DEFAULT_MARKETS = [
    ("Austin", "TX"), ("Charlotte", "NC"), ("Phoenix", "AZ"), ("Tampa", "FL"),
    ("Nashville", "TN"), ("Columbus", "OH"), ("Raleigh", "NC"), ("Denver", "CO"),
    ("Kansas City", "MO"), ("Boise", "ID"), ("Greenville", "SC"), ("Tucson", "AZ"),
]

#: Fallback if nothing is defensible at the configured price.
FALLBACK_VERTICALS = ["hvac", "plumbing"]


def defensible_verticals(monthly_price: float) -> list[str]:
    """Only prospect trades the retainer can honestly be sold to.

    The Strategist flagged this: the Scout was adding roofing prospects at a
    price roofing cannot justify, so the Outreach agent then filtered them
    out. That is API spend and pipeline noise generated for nothing. Selecting
    at the point of discovery is cheaper than rejecting at the point of sale.
    """
    ranked = knowledge.best_verticals(monthly_price)
    good = [str(r["vertical"]) for r in ranked
            if r["verdict"] in {"strong", "workable"}]
    return good or FALLBACK_VERTICALS


class ScoutAgent(Agent):
    name = "scout"
    description = "Discovers local service businesses and adds them to the prospect pool."
    interval = 6 * 3600

    def __init__(self, store, settings, target_per_run: int = 25,
                 seed_file: str | None = None):
        super().__init__(store, settings)
        self.target = target_per_run
        self.seed_file = seed_file or os.environ.get("ANSWERRANK_SEED_FILE", "")
        self.verticals = defensible_verticals(settings.pricing.growth_monthly)

    # ---------------- sources ----------------

    def from_serper(self, vertical: str, city: str, state: str) -> list[Business]:
        key = self.settings.api_key("serper")
        if not key:
            return []
        label = VERTICALS.get(vertical, VERTICALS["home_services"])["label"]
        try:
            resp = requests.post(
                "https://google.serper.dev/places",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json={"q": f"{label} in {city}, {state}", "gl": "us"},
                timeout=self.settings.request_timeout,
            )
            resp.raise_for_status()
            places = resp.json().get("places", [])
        except (requests.RequestException, ValueError) as exc:
            self.log.warning("serper places failed for %s/%s: %s", vertical, city, exc)
            return []

        out = []
        for p in places:
            if not p.get("title"):
                continue
            out.append(Business(
                name=p["title"],
                city=city,
                state=state,
                vertical=vertical,
                website=p.get("website", "") or "",
                phone=p.get("phoneNumber", "") or "",
            ))
        return out

    def from_seed_file(self) -> list[Business]:
        """CSV columns: name, city, state, vertical, website, email, phone."""
        if not self.seed_file or not Path(self.seed_file).exists():
            return []
        out = []
        with open(self.seed_file, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if not row.get("name"):
                    continue
                out.append(Business(
                    name=row["name"].strip(),
                    city=row.get("city", "").strip(),
                    state=row.get("state", "").strip(),
                    vertical=row.get("vertical", "home_services").strip() or "home_services",
                    website=row.get("website", "").strip(),
                    email=row.get("email", "").strip(),
                    phone=row.get("phone", "").strip(),
                ))
        return out

    def simulated(self, count: int) -> list[Business]:
        """Fixtures so the fleet is observable end-to-end with no credentials."""
        import hashlib
        stems = ["Apex", "Summit", "Ironclad", "BlueRidge", "Cornerstone", "Vanguard",
                 "Beacon", "Redwood", "Northgate", "Sterling", "Copperfield", "Harbor"]
        suffix = {"hvac": "Heating & Air", "plumbing": "Plumbing Co", "roofing": "Roofing",
                  "dental": "Family Dental", "legal": "Law Group",
                  "medical": "Medical Clinic", "insurance": "Insurance"}
        out = []
        existing = len(self.store.get_prospects(limit=10_000))
        for i in range(count):
            n = existing + i
            vert = self.verticals[n % len(self.verticals)]
            city, state = DEFAULT_MARKETS[(n // len(self.verticals)) % len(DEFAULT_MARKETS)]
            stem = stems[n % len(stems)]
            tag = hashlib.sha1(f"{stem}{vert}{city}{n}".encode()).hexdigest()[:4]
            name = f"{stem} {suffix.get(vert, 'Services')}"
            slug = f"{stem.lower()}{vert}{tag}"
            out.append(Business(
                name=name, city=city, state=state, vertical=vert,
                website=f"https://{slug}.com",
                email=f"office@{slug}.com",
            ))
        return out

    # ---------------- run ----------------

    def execute(self) -> tuple[int, str]:
        found: list[Business] = self.from_seed_file()

        if len(found) < self.target and self.settings.api_key("serper"):
            for vertical in self.verticals:
                if len(found) >= self.target:
                    break
                for city, state in DEFAULT_MARKETS:
                    if len(found) >= self.target:
                        break
                    found.extend(self.from_serper(vertical, city, state))

        if not found:
            found = self.simulated(self.target)

        added = skipped = 0
        for biz in found[: self.target * 3]:
            if not biz.domain:
                skipped += 1  # no website: nothing to optimise, nothing to sell
                continue
            if self.store.prospect_exists(biz.domain):
                skipped += 1
                continue
            self.store.upsert_prospect(Prospect(business=biz, stage="discovered"))
            added += 1

        return added, (f"added {added} new prospects across "
                       f"{'/'.join(self.verticals)}, skipped {skipped}")
