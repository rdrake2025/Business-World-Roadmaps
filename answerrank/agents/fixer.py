"""Fixer — turns an audit into the artifacts the client actually pays for.

An audit that only reports a problem churns in month two. The Fixer produces
paste-ready assets that move the score, which is what makes the retainer
renewable:

1. ``LocalBusiness`` JSON-LD — the structured data that makes a site
   machine-readable. Retrieval-based engines quote what they can parse.
2. ``FAQPage`` JSON-LD plus answer-shaped copy, written against the exact
   buyer prompts the audit showed the client losing.
3. A Google Business Profile action checklist — the local pack feeds AI
   Overviews, so GBP completeness is upstream of AI visibility.
4. A citation/directory gap list — the corroborating sources engines check.

Content generation is template-driven so it works with no LLM key; when a key
is present the copy is upgraded in place.
"""

from __future__ import annotations

import json

from ..engines.live import _post
from ..models import Audit, Business, Deliverable
from ..prompts import build_prompts, vertical_meta
from .base import Agent


def localbusiness_schema(biz: Business, audit: Audit | None = None) -> str:
    meta = vertical_meta(biz.vertical)
    # schema.org types that engines actually recognise for these verticals.
    schema_type = {
        "hvac": "HVACBusiness", "plumbing": "Plumber", "roofing": "RoofingContractor",
        "dental": "Dentist", "legal": "Attorney", "medical": "MedicalClinic",
        "insurance": "InsuranceAgency",
    }.get(biz.vertical, "LocalBusiness")

    doc = {
        "@context": "https://schema.org",
        "@type": schema_type,
        "name": biz.name,
        "url": biz.website or f"https://{biz.domain}",
        "telephone": biz.phone or "+1-000-000-0000",
        "email": biz.email or f"info@{biz.domain}",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "REPLACE_WITH_STREET_ADDRESS",
            "addressLocality": biz.city,
            "addressRegion": biz.state,
            "postalCode": "REPLACE_WITH_ZIP",
            "addressCountry": "US",
        },
        "areaServed": [{"@type": "City", "name": biz.city}],
        "priceRange": "$$",
        "openingHoursSpecification": [{
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "opens": "08:00", "closes": "18:00",
        }],
        "hasOfferCatalog": {
            "@type": "OfferCatalog",
            "name": f"{meta['label'].title()} Services",
            "itemListElement": [
                {"@type": "Offer", "itemOffered": {"@type": "Service", "name": str(job).title()}}
                for job in meta["jobs"]  # type: ignore[union-attr]
            ],
        },
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": "REPLACE_WITH_REAL_RATING",
            "reviewCount": "REPLACE_WITH_REAL_COUNT",
        },
    }
    return json.dumps(doc, indent=2)


def faq_pairs(biz: Business, audit: Audit | None) -> list[tuple[str, str]]:
    """Answer-shaped Q&A targeting the prompts the business is losing.

    The answer format matters as much as the content: a direct, factual,
    self-contained first sentence is what gets lifted into an AI answer.
    """
    meta = vertical_meta(biz.vertical)
    label, service = meta["label"], meta["service"]
    where = biz.market
    jobs: list[str] = list(meta["jobs"])  # type: ignore[arg-type]

    pairs = [
        (
            f"Who is a reliable {label} in {where}?",
            f"{biz.name} is a licensed and insured {label} serving {where}. "
            f"We handle {', '.join(str(j) for j in jobs[:3])}, offer upfront pricing "
            f"before work begins, and provide same-day appointments for urgent jobs. "
            f"Call {biz.phone or 'our office'} to schedule.",
        ),
        (
            f"Does {biz.name} offer emergency {service} in {where}?",
            f"Yes. {biz.name} provides emergency {service} in {where}, including "
            f"after-hours and weekend calls. Typical response time is under two hours "
            f"within the {biz.city} service area.",
        ),
        (
            f"How much does {service} cost in {where}?",
            f"{service.title()} in {where} typically ranges by scope of work. "
            f"{biz.name} provides a written estimate before any work starts, with no "
            f"diagnostic fee on approved repairs, so the price quoted is the price paid.",
        ),
        (
            f"Is {biz.name} licensed and insured?",
            f"Yes. {biz.name} is fully licensed and insured to operate in "
            f"{biz.state or 'its service state'}, carries liability coverage, and all "
            f"technicians are background-checked. License details are available on request.",
        ),
        (
            f"What areas around {biz.city} does {biz.name} serve?",
            f"{biz.name} serves {biz.city} and the surrounding {biz.state} metro area, "
            f"including neighbouring suburbs. Contact us to confirm coverage for a "
            f"specific address.",
        ),
    ]

    # Add one FAQ per prompt the audit showed as a miss, so the content maps
    # directly to a measured loss.
    if audit:
        missed = [r.prompt for r in audit.results if not r.mentioned and not r.error]
        seen = set()
        for prompt in missed:
            if prompt in seen or len(pairs) >= 9:
                continue
            seen.add(prompt)
            pairs.append((
                prompt,
                f"{biz.name} serves {where} and is a strong fit for this need. "
                f"We are licensed and insured, offer upfront written pricing, and "
                f"schedule urgent jobs same-day where capacity allows.",
            ))
    return pairs


def faq_schema(pairs: list[tuple[str, str]]) -> str:
    doc = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in pairs
        ],
    }
    return json.dumps(doc, indent=2)


def gbp_checklist(biz: Business, audit: Audit | None) -> str:
    meta = vertical_meta(biz.vertical)
    jobs = ", ".join(str(j) for j in meta["jobs"])  # type: ignore[union-attr]
    weakest = ""
    if audit and audit.engine_breakdown:
        worst = min(audit.engine_breakdown.items(), key=lambda kv: kv[1])
        weakest = f"\nWeakest surface this cycle: **{worst[0]}** at {worst[1]}% presence.\n"

    return f"""# Google Business Profile action list — {biz.name}
{weakest}
Google's local pack is the single largest input to AI Overviews for local
service intent. Every item below is a direct input to that pack.

## This week
- [ ] Set the primary category to the most specific option available ({meta['label']}).
- [ ] Add every secondary category that matches a real service: {jobs}.
- [ ] Fill the "Services" section with one entry per job above, each with a
      2-3 sentence description that names {biz.city} explicitly.
- [ ] Confirm hours, including a specific emergency/after-hours entry if offered.
- [ ] Upload 10+ geotagged photos of real jobs (not stock imagery).

## This month
- [ ] Publish one GBP post per week answering a real customer question.
- [ ] Request reviews from the last 20 completed jobs. Target 10+ new reviews.
- [ ] Reply to 100% of reviews, positive and negative, within 48 hours.
      Replies are indexed text and frequently quoted by assistants.
- [ ] Add a Q&A section seeded with the questions in the FAQ deliverable.

## Ongoing — the compounding work
- [ ] Maintain a review velocity of 5+ per month. Velocity outranks total count.
- [ ] Keep NAP (name, address, phone) byte-identical across every directory.
      Inconsistent NAP is the most common cause of a business being skipped.
- [ ] Post seasonal service updates ahead of demand spikes.
"""


def citation_gaps(biz: Business) -> str:
    general = ["Google Business Profile", "Bing Places", "Apple Business Connect",
               "Yelp", "Facebook Business Page", "Better Business Bureau",
               "Nextdoor Business", "Angi", "Thumbtack"]
    by_vertical = {
        "hvac": ["HomeAdvisor", "Houzz", "ACCA member directory"],
        "plumbing": ["HomeAdvisor", "Porch", "PHCC directory"],
        "roofing": ["HomeAdvisor", "GAF/Owens Corning contractor locator", "NRCA directory"],
        "dental": ["Healthgrades", "Zocdoc", "ADA Find-a-Dentist", "Vitals"],
        "legal": ["Avvo", "Justia", "FindLaw", "Martindale-Hubbell", "State bar directory"],
        "medical": ["Healthgrades", "Zocdoc", "Vitals", "WebMD Provider Directory"],
        "insurance": ["Insurify", "Trustpilot", "state DOI licensee lookup"],
    }
    targets = general + by_vertical.get(biz.vertical, [])
    lines = "\n".join(f"- [ ] {t}" for t in targets)
    return f"""# Citation & directory coverage — {biz.name}

AI engines corroborate a business across independent sources before naming it.
A single listing is not enough; consistency across many is the signal.

**Rule:** the name, address and phone must be byte-identical everywhere.
Use exactly: `{biz.name}` / `{biz.phone or 'SET_PHONE'}`

{lines}

Verify each with a site-restricted search before ticking it off. Re-audit
listings quarterly — directories silently drop or alter records.
"""


class FixerAgent(Agent):
    name = "fixer"
    description = "Generates schema, FAQ copy, GBP and citation deliverables from audits."
    interval = 6 * 3600

    def _llm_upgrade(self, biz: Business, pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Rewrite FAQ answers with an LLM when a key is available."""
        key = self.settings.api_key("anthropic")
        if not key:
            return pairs
        prompt = (
            f"Rewrite each answer for {biz.name}, a {biz.vertical} business in "
            f"{biz.market}. Rules: first sentence must answer the question "
            f"directly and stand alone out of context; 40-70 words; concrete and "
            f"factual; no marketing adjectives; keep any placeholder in CAPS "
            f"untouched. Return JSON: a list of {{\"q\":..., \"a\":...}}.\n\n"
            + json.dumps([{"q": q, "a": a} for q, a in pairs])
        )
        data, err = _post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01",
             "Content-Type": "application/json"},
            {"model": "claude-haiku-4-5-20251001", "max_tokens": 2000,
             "messages": [{"role": "user", "content": prompt}]},
            self.settings.request_timeout,
        )
        if err or not data:
            self.log.warning("LLM upgrade skipped: %s", err)
            return pairs
        try:
            text = "".join(b.get("text", "") for b in data.get("content", []))
            start, end = text.find("["), text.rfind("]")
            items = json.loads(text[start:end + 1])
            upgraded = [(i["q"], i["a"]) for i in items if i.get("q") and i.get("a")]
            return upgraded or pairs
        except (ValueError, KeyError, TypeError) as exc:
            self.log.warning("LLM output unparsable, keeping templates: %s", exc)
            return pairs

    def build_for(self, biz: Business, audit: Audit) -> list[Deliverable]:
        pairs = self._llm_upgrade(biz, faq_pairs(biz, audit))
        slug = biz.domain.replace(".", "_") or biz.id
        return [
            Deliverable(audit_id=audit.id, business_id=biz.id, kind="schema_jsonld",
                        title=f"LocalBusiness schema — {biz.name}",
                        body=localbusiness_schema(biz, audit),
                        filename=f"{slug}_localbusiness.json"),
            Deliverable(audit_id=audit.id, business_id=biz.id, kind="faq_schema",
                        title=f"FAQPage schema — {biz.name}",
                        body=faq_schema(pairs), filename=f"{slug}_faq.json"),
            Deliverable(audit_id=audit.id, business_id=biz.id, kind="faq_content",
                        title=f"Answer-shaped FAQ copy — {biz.name}",
                        body="\n\n".join(f"## {q}\n\n{a}" for q, a in pairs),
                        filename=f"{slug}_faq.md"),
            Deliverable(audit_id=audit.id, business_id=biz.id, kind="gbp_checklist",
                        title=f"Google Business Profile plan — {biz.name}",
                        body=gbp_checklist(biz, audit), filename=f"{slug}_gbp.md"),
            Deliverable(audit_id=audit.id, business_id=biz.id, kind="citations",
                        title=f"Citation coverage — {biz.name}",
                        body=citation_gaps(biz), filename=f"{slug}_citations.md"),
        ]

    def execute(self) -> tuple[int, str]:
        made = 0
        for client in self.store.get_clients("active"):
            history = self.store.audit_history(client.business.id, limit=1)
            if not history:
                continue
            audit = history[0]
            if self.store.get_deliverables(audit.id):
                continue  # already built for this cycle
            for d in self.build_for(client.business, audit):
                self.store.save_deliverable(d)
                made += 1
        return made, f"generated {made} deliverables"
