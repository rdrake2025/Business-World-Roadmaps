"""Where the engines look, and whether the business is there.

The research is consistent about what AI answers are built from. For local
questions ChatGPT's leading directory sources are curated "best of" sites
(Three Best Rated and Expertise, BrightLocal), and for home services nearly
half of its citations are directories and review platforms (Cheers, 2026).
Whitespark's 2026 survey ranks presence on expert-curated lists as the
single strongest AI-visibility factor, with prominence on industry sites
and the authority of the sites holding a business's reviews close behind.

None of that was checked. The Fixer handed every client the same generic
directory list, whatever the engines in their town actually quote. This
checks two things instead:

* **Which sites the engines cite** for this trade in this town, read from
  the sources the grounded answers came with, and
* **whether the business, and the competitor the engines named instead,
  are on them**, by a site-restricted search for each.

The gap between the two is the most useful sentence in a sales call and the
first line of a client's month-two plan.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

#: Curated "best of" sites: they choose who is listed, which is why listing
#: counts. Named in BrightLocal's ChatGPT source study.
CURATED = {"expertise.com": "Expertise.com", "threebestrated.com": "Three Best Rated"}

#: Directories and review platforms the engines cite for home services.
DIRECTORIES = {"bbb.org": "Better Business Bureau", "angi.com": "Angi",
               "yelp.com": "Yelp", "thumbtack.com": "Thumbtack",
               "homeadvisor.com": "HomeAdvisor", "nextdoor.com": "Nextdoor"}

#: Never a "listing": search engines, social networks, the engines themselves.
_NOT_LISTINGS = {"google.com", "bing.com", "facebook.com", "instagram.com",
                 "youtube.com", "wikipedia.org", "reddit.com", "maps.google.com",
                 "chatgpt.com", "openai.com", "perplexity.ai", "x.com", "twitter.com",
                 "linkedin.com", "tiktok.com"}

HOW_TO_GET_ON = {
    "curated": ("They choose who is listed. Use the site's 'nominate' or 'contact' "
                "page and send the licence number, insurance, years trading and the "
                "review count and rating. Ask again each review cycle if declined."),
    "directory": ("Claim or create the free listing with the exact name, address "
                  "and phone used everywhere else, choose the most specific "
                  "category, and ask a recent customer to review it there."),
    "cited": ("The engines quote this site for this trade here. Find how "
              "businesses are listed on it and get on it the same way."),
}


def domain_of(url: str) -> str:
    host = urlparse(url if "//" in url else f"https://{url}").netloc.lower()
    host = host.split(":")[0]
    for prefix in ("www.", "m.", "local."):
        host = host.removeprefix(prefix)
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 and len(parts[-1]) > 2 else host


def cited_domains(audits, own_domain: str = "") -> Counter:
    """How often each third-party site was cited in live-search answers."""
    counts: Counter = Counter()
    own = domain_of(own_domain) if own_domain else ""
    for audit in audits:
        for r in getattr(audit, "results", []):
            if r.error or not getattr(r, "grounded", False):
                continue
            for d in {domain_of(u) for u in r.sources or [] if u}:
                if d and d != own and d not in _NOT_LISTINGS:
                    counts[d] += 1
    return counts


def targets(cited: Counter, limit: int = 8) -> list[tuple[str, str, str]]:
    """(domain, label, kind): the curated lists always, then the directories
    the engines here actually cite most, then the standard ones."""
    out: list[tuple[str, str, str]] = [(d, label, "curated") for d, label in CURATED.items()]
    seen = set(CURATED)
    for d, _n in cited.most_common():
        if d in seen or len(out) >= limit:
            continue
        kind = "directory" if d in DIRECTORIES else "cited"
        out.append((d, DIRECTORIES.get(d, d), kind))
        seen.add(d)
    for d, label in DIRECTORIES.items():
        if len(out) >= limit:
            break
        if d not in seen:
            out.append((d, label, "directory"))
            seen.add(d)
    return out


def serper_search(query: str, key: str = "", timeout: int = 20) -> list[dict[str, Any]]:
    """Organic results for one query, or [] on any failure."""
    import requests

    key = key or os.environ.get("SERPER_API_KEY", "")
    if not key:
        return []
    try:
        resp = requests.post("https://google.serper.dev/search",
                             headers={"X-API-KEY": key, "Content-Type": "application/json"},
                             json={"q": query, "gl": "us", "num": 5}, timeout=timeout)
        if resp.status_code >= 400:
            return []
        return list(resp.json().get("organic") or [])
    except Exception:  # noqa: BLE001 - a failed check is "unknown", never a crash
        return []


def serper_places(query: str, key: str = "", timeout: int = 20) -> list[dict[str, Any]]:
    """Google Maps results for one query, or [] on any failure."""
    import requests

    key = key or os.environ.get("SERPER_API_KEY", "")
    if not key:
        return []
    try:
        resp = requests.post("https://google.serper.dev/places",
                             headers={"X-API-KEY": key, "Content-Type": "application/json"},
                             json={"q": query, "gl": "us"}, timeout=timeout)
        if resp.status_code >= 400:
            return []
        return list(resp.json().get("places") or [])
    except Exception:  # noqa: BLE001
        return []


def google_reviews(name: str, city: str,
                   places: Callable[[str], list[dict[str, Any]]]) -> dict[str, Any]:
    """The business's Google rating and review count, or {} if not found.

    Tracked monthly so Retention can see a client going quiet on reviews:
    74% of consumers look only at the last three months (BrightLocal 2026).
    """
    needle = name.lower().split(" llc")[0].strip()
    for place in places(f"{name} {city}".strip()):
        if needle and needle in str(place.get("title", "")).lower():
            return {"rating": place.get("rating"),
                    "count": place.get("ratingCount") or place.get("reviews")}
    return {}


def listed(name: str, city: str, domain: str,
           search: Callable[[str], list[dict[str, Any]]]) -> bool:
    """Whether a site-restricted search finds the business on that site."""
    if not name:
        return False
    results = search(f'site:{domain} "{name}" {city}'.strip())
    needle = name.lower().split(" llc")[0].strip()
    return any(needle in f"{r.get('title', '')} {r.get('snippet', '')}".lower()
               for r in results)


def check(business, competitor: str, cited: Counter,
          search: Callable[[str], list[dict[str, Any]]],
          only: tuple[str, ...] = ()) -> dict[str, Any]:
    """Look the business, and the competitor named instead, up on each site."""
    rows = []
    for domain, label, kind in targets(cited):
        if only and kind not in only:
            continue
        rows.append({
            "domain": domain, "label": label, "kind": kind,
            "cited": cited.get(domain, 0),
            "business": listed(business.name, business.city, domain, search),
            "competitor": listed(competitor, business.city, domain, search)
            if competitor else None,
        })
    return {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "competitor": competitor, "rows": rows}


def gaps(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Sites the competitor is on and the business is not, curated lists first."""
    order = {"curated": 0, "directory": 1, "cited": 2}
    rows = [r for r in result.get("rows", []) if r.get("competitor") and not r.get("business")]
    return sorted(rows, key=lambda r: (order.get(r["kind"], 3), -r.get("cited", 0)))


def report(business, result: dict[str, Any]) -> str:
    """The deliverable: where the engines look, and what to do about each."""
    competitor = result.get("competitor") or "the business named instead"
    lines = [f"# Where the AI engines look — {business.name}", "",
             "The engines build local answers from the business's own site and "
             "from third-party sites. Curated 'best of' lists are the strongest "
             "single factor (Whitespark 2026 Local Search Ranking Factors), and "
             "for home services nearly half of ChatGPT's citations are directories "
             "and review sites. This is where you stand on the ones that matter "
             f"here, next to {competitor}.", "",
             f"| Site | Cited in answers here | {business.name[:24]} | {competitor[:24]} |",
             "| --- | --- | --- | --- |"]
    for r in result.get("rows", []):
        comp = "—" if r.get("competitor") is None else ("yes" if r["competitor"] else "no")
        lines.append(f"| {r['label']} | {r.get('cited', 0) or '—'} | "
                     f"{'yes' if r['business'] else '**no**'} | {comp} |")
    todo = [r for r in result.get("rows", []) if not r["business"]]
    if todo:
        lines += ["", "## What to do", ""]
        for r in sorted(todo, key=lambda r: (not r.get("competitor"), r["kind"] != "curated")):
            why = f" {competitor} is on it." if r.get("competitor") else ""
            lines.append(f"- **{r['label']}** ({r['domain']}).{why} "
                         f"{HOW_TO_GET_ON[r['kind']]}")
    lines += ["", "Checked by searching each site for the business by name and "
                  "town. A 'no' can mean the listing exists under a different name, "
                  "which is itself worth fixing: the name must match everywhere."]
    return "\n".join(lines)


def one_liner(business, result: dict[str, Any]) -> str:
    """The sentence for a sales call, or ''."""
    missing = [r for r in gaps(result) if r["kind"] == "curated"]
    if not missing:
        return ""
    return (f"{result['competitor']} is on {missing[0]['label']}'s list for "
            f"{business.city}; {business.name} isn't.")
