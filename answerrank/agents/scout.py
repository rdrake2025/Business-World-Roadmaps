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

def parse_markets(values) -> list[tuple[str, str]]:
    """["Waco, TX", "Temple TX"] -> [("Waco", "TX"), ("Temple", "TX")]."""
    out = []
    for raw in values or []:
        text = str(raw).strip().rstrip(".")
        if "," in text:
            city, _, state = text.rpartition(",")
        else:
            city, _, state = text.rpartition(" ")
        city, state = city.strip(), state.strip().upper()
        if city and len(state) == 2 and state.isalpha():
            out.append((city, state))
    return out


#: Fallback if nothing is defensible at the configured price.
FALLBACK_VERTICALS = ["hvac", "plumbing"]


def defensible_verticals(monthly_price: float,
                         ladder: list[float] | None = None) -> list[str]:
    """Trades worth prospecting, highest-value tier first.

    The Strategist flagged the first version of this: the Scout was adding
    roofing prospects at a price roofing cannot justify, so Outreach filtered
    them out afterwards — API spend and pipeline noise generated for nothing.
    Selecting at discovery is cheaper than rejecting at the point of sale.

    The correction to that correction is the pricing ladder. "Cannot justify
    $997" is not the same as "not worth serving": a garage door company
    defends $297 comfortably. Filtering on one price threw away half the
    library for a reason that was never about the market. Every trade with a
    defensible tier is prospected, best-paying first, and each one is later
    quoted the price its own economics support.
    """
    tiers = ladder or [monthly_price]
    priced = [
        (float(r["price"]), str(r["vertical"]))
        for r in (knowledge.recommended_price(k, tiers) for k in knowledge.VERTICALS)
        if r["price"]
    ]
    priced.sort(key=lambda row: -row[0])
    return [vertical for _price, vertical in priced] or FALLBACK_VERTICALS


#: Stamped on the notes of any prospect the Scout invented. The send path
#: refuses these outright: their domains do not resolve, so every one is a
#: hard bounce, and bounces are capped at 2% before the sending domain is
#: throttled wholesale.
SIMULATED_MARKER = "SIMULATED — fixture data, never contact"


class ScoutAgent(Agent):
    name = "scout"
    description = "Discovers local service businesses and adds them to the prospect pool."
    interval = 6 * 3600

    def __init__(self, store, settings, target_per_run: int = 25,
                 seed_file: str | None = None):
        super().__init__(store, settings)
        self.target = target_per_run
        self.seed_file = seed_file or os.environ.get("ANSWERRANK_SEED_FILE", "")
        # The operator's chosen trade and cities win. Until this, the trade
        # asked for at setup was never saved, and every trade the price
        # supports was searched across twelve fixed cities, so a first call
        # list was spread across the country instead of the operator's patch.
        chosen = [t for t in (getattr(settings, "trades", None) or [])
                  if t in knowledge.VERTICALS]
        self.verticals = chosen or defensible_verticals(
            settings.pricing.growth_monthly, settings.pricing.ladder())
        self.markets = parse_markets(getattr(settings, "markets", None)) or DEFAULT_MARKETS

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
        """Fixtures so the fleet is observable end-to-end with no credentials.

        These are invented. The domains do not resolve and the addresses do
        not exist, so anything built from them is marked at the point it
        enters the database and refused by the send path — see
        :data:`SIMULATED_MARKER`.
        """
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
            city, state = self.markets[(n // len(self.verticals)) % len(self.markets)]
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
        seeded = self.from_seed_file()
        # Count only what the seed file still has to offer. A CSV of fifty
        # businesses that are all already prospects used to keep ``found``
        # above target on every run, so live search was never reached and
        # discovery stopped for good the day the file was imported.
        fresh_seeds = [b for b in seeded
                       if b.domain and not self.store.prospect_exists(b.domain)]
        found: list[Business] = list(fresh_seeds)

        has_live_source = bool(self.settings.api_key("serper"))
        searched = False
        if len(found) < self.target and has_live_source:
            searched = True
            for vertical in self.verticals:
                if len(found) >= self.target:
                    break
                for city, state in self.markets:
                    if len(found) >= self.target:
                        break
                    found.extend(self.from_serper(vertical, city, state))

        simulated = False
        if not found:
            # Inventing businesses is for watching the pipeline move with no
            # credentials. With a live source configured, an empty result is
            # an outage or an exhausted quota, and filling the database with
            # fabricated addresses turns that into hard bounces against a
            # 2% ceiling — on a real sending domain, from a real outage.
            if has_live_source and not self.settings.demo_mode:
                return 0, ("no businesses found this run — the search API "
                           "returned nothing. Nothing invented to cover it.")
            if seeded and not searched:
                return 0, (f"seed file has {len(seeded)} businesses, all already "
                           f"in the pipeline; nothing new to add")
            simulated = True
            found = self.simulated(self.target)

        added = skipped = 0
        for biz in found[: self.target * 3]:
            if not biz.domain:
                skipped += 1  # no website: nothing to optimise, nothing to sell
                continue
            if self.store.prospect_exists(biz.domain):
                skipped += 1
                continue
            self.store.upsert_prospect(Prospect(
                business=biz, stage="discovered",
                notes=SIMULATED_MARKER if simulated else ""))
            added += 1

        source = "simulated" if simulated else ("search" if searched else "seed file")
        return added, (f"added {added} new prospects from {source} across "
                       f"{'/'.join(self.verticals)}, skipped {skipped}")
