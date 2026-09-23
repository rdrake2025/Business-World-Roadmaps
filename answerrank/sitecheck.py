"""Is the work actually live on the client's website?

The service's fixes only count once they are on the client's site. Ten of
the fifteen levers in the six-month arc need the client — or someone they
forward it to — to paste code into their website or edit their Google
profile. Until now nothing checked whether that ever happened, so a client
could pay for three months while the files sat unopened in an inbox, the
score stayed flat, and the first sign of it was the cancellation.

This reads the client's homepage the way an engine does and answers four
questions: which website platform it runs on (so the install steps can be
the right ones), whether the business's structured data is on the page,
whether the FAQ markup is, and whether anything went live with a blank still
in it. It records the answer, so the monthly report can say what is live and
Retention can see a client stuck at the install step.

It reads what is in the page as served. Markup injected later by JavaScript
(a tag manager, say) is invisible here even though Google may still see it,
so "not found" is reported as "not found in the page", never as "missing",
and the Rich Results Test is named as the tie-breaker.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from . import knowledge
from .engines.base import normalize
from .models import Business, now_iso

USER_AGENT = ("AnswerRankBot/1.0 (+https://answerrank.io/about; "
              "checking a client's own site at their request)")
_MAX_BYTES = 2_000_000

#: Signatures in the served page, most specific first. Every one of these is
#: a fingerprint the platform puts in every page it serves.
PLATFORMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("wix", "Wix", (r"static\.wixstatic\.com", r"wix-bolt", r"_wixCIDX",
                    r'content="Wix\.com Website Builder')),
    ("squarespace", "Squarespace", (r"static1\.squarespace\.com",
                                    r"<!-- This is Squarespace\. -->",
                                    r"Static\.SQUARESPACE_CONTEXT")),
    ("godaddy", "GoDaddy Website Builder", (r"img1\.wsimg\.com",
                                            r"Starfield Technologies; Go Daddy Website Builder",
                                            r"godaddysites\.com")),
    ("shopify", "Shopify", (r"cdn\.shopify\.com", r"Shopify\.theme")),
    ("webflow", "Webflow", (r"data-wf-site=", r'content="Webflow"')),
    ("duda", "Duda", (r"irp\.cdn-website\.com", r"dudaone", r"multiscreensite\.com")),
    ("weebly", "Square Online / Weebly", (r"editmysite\.com", r"weebly\.com")),
    ("wordpress", "WordPress", (r"/wp-content/", r"/wp-includes/",
                                r'content="WordPress')),
)

PLATFORM_LABEL = {key: label for key, label, _ in PLATFORMS}
PLATFORM_LABEL["unknown"] = "your website"

_JSONLD = re.compile(
    r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.I | re.S)

#: Types that say "this is a local business". Every trade's own type is in
#: KNOWN_SCHEMA_TYPES, and those are all LocalBusiness subtypes.
LOCAL_TYPES = set(knowledge.KNOWN_SCHEMA_TYPES) | {"LocalBusiness"}


@dataclass
class SiteCheck:
    url: str
    reached: bool = False
    status: int | None = None
    platform: str = "unknown"
    types: list[str] = field(default_factory=list)
    local_business: bool = False
    faq: bool = False
    name_matches: bool | None = None
    phone_matches: bool | None = None
    placeholders: list[str] = field(default_factory=list)
    invalid_blocks: int = 0
    problems: list[str] = field(default_factory=list)
    checked_at: str = field(default_factory=now_iso)

    @property
    def platform_label(self) -> str:
        return PLATFORM_LABEL.get(self.platform, "your website")

    def live(self, kind: str) -> bool:
        """Whether a deliverable of this kind is verifiably on the page."""
        if kind == "schema_jsonld":
            return self.local_business and not self.placeholders
        if kind == "faq_schema":
            return self.faq
        return False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SiteCheck":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def lines(self) -> list[str]:
        """What a client should hear about it, in plain words."""
        if not self.reached:
            return [f"We could not load {self.url} to check it"
                    + (f" (HTTP {self.status})." if self.status else ".")]
        out = []
        out.append("✓ Business details (LocalBusiness markup) are live on your homepage."
                   if self.live("schema_jsonld") else
                   "✗ Business details markup is not in your homepage yet."
                   if not self.local_business else
                   "! Business details markup is live but still has a blank in it: "
                   + ", ".join(self.placeholders[:3]) + ".")
        out.append("✓ FAQ markup is live." if self.faq
                   else "✗ FAQ markup is not in your homepage yet.")
        if self.local_business and self.name_matches is False:
            out.append("! The business name in the markup does not match your "
                       "Google listing name. They need to be identical.")
        if self.local_business and self.phone_matches is False:
            out.append("! The phone number in the markup does not match the one "
                       "on file. They need to be identical everywhere.")
        return out


# ---------------------------------------------------------------------------
# Reading the page
# ---------------------------------------------------------------------------

def fetch(url: str, timeout: int = 12) -> tuple[int | None, dict[str, str], str]:
    """(status, headers, html) — capped, never raises."""
    try:
        import requests
        resp = requests.get(url, timeout=timeout, allow_redirects=True, stream=True,
                            headers={"User-Agent": USER_AGENT,
                                     "Accept": "text/html,application/xhtml+xml"})
    except Exception:  # noqa: BLE001 - an unreachable site is a result, not a crash
        return None, {}, ""
    try:
        chunks, size = [], 0
        for chunk in resp.iter_content(64 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if size >= _MAX_BYTES:
                break
        html = b"".join(chunks).decode(resp.encoding or "utf-8", "replace")
        return resp.status_code, dict(resp.headers), html
    except Exception:  # noqa: BLE001
        return resp.status_code, dict(resp.headers), ""
    finally:
        resp.close()


def detect_platform(html: str, headers: dict[str, str] | None = None) -> str:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if any(k.startswith("x-wix") for k in headers):
        return "wix"
    for key, _label, patterns in PLATFORMS:
        if any(re.search(p, html or "", re.I) for p in patterns):
            return key
    return "unknown"


def extract_jsonld(html: str) -> tuple[list[dict[str, Any]], int]:
    """Every JSON-LD node in the page, flattened, plus how many blocks were
    not valid JSON — a broken block is ignored by every engine that reads it."""
    nodes: list[dict[str, Any]] = []
    invalid = 0
    for raw in _JSONLD.findall(html or ""):
        text = raw.strip().removeprefix("<!--").removesuffix("-->").strip()
        try:
            data = json.loads(text)
        except ValueError:
            invalid += 1
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if "@graph" in item and isinstance(item["@graph"], list):
                    stack.extend(item["@graph"])
                nodes.append(item)
    return nodes, invalid


def _types(node: dict[str, Any]) -> set[str]:
    t = node.get("@type")
    if isinstance(t, str):
        return {t.split("/")[-1]}
    if isinstance(t, list):
        return {str(x).split("/")[-1] for x in t}
    return set()


def _digits(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    return d[-10:] if len(d) >= 10 else d


def check(business: Business, url: str = "",
          fetcher: Callable[[str], tuple[int | None, dict[str, str], str]] | None = None
          ) -> SiteCheck:
    url = url or business.website or (f"https://{business.domain}" if business.domain else "")
    result = SiteCheck(url=url)
    if not url:
        result.problems.append("No website on file.")
        return result
    status, headers, html = (fetcher or fetch)(url)
    result.status = status
    if not status or status >= 400 or not html:
        result.problems.append("Could not load the homepage.")
        return result
    result.reached = True
    result.platform = detect_platform(html, headers)

    nodes, result.invalid_blocks = extract_jsonld(html)
    seen: set[str] = set()
    for node in nodes:
        seen |= _types(node)
    result.types = sorted(seen)
    local = [n for n in nodes if _types(n) & LOCAL_TYPES]
    result.local_business = bool(local)
    result.faq = any("FAQPage" in _types(n) for n in nodes)

    if local:
        node = local[0]
        name = str(node.get("name", ""))
        result.name_matches = bool(name) and normalize(name) == normalize(business.name)
        if business.phone and node.get("telephone"):
            result.phone_matches = _digits(str(node["telephone"])) == _digits(business.phone)
        blob = json.dumps(local)
        result.placeholders = sorted(set(re.findall(r"REPLACE_WITH_[A-Z_]+", blob)))

    if result.invalid_blocks:
        result.problems.append(f"{result.invalid_blocks} structured-data block(s) on the "
                               f"page are not valid JSON, so every engine ignores them.")
    if result.placeholders:
        result.problems.append("Markup went live with blanks still in it: "
                               + ", ".join(result.placeholders) + ".")
    return result


# ---------------------------------------------------------------------------
# Install steps, per platform
# ---------------------------------------------------------------------------

#: Wix rejects a structured-data markup of 7,000 characters or more, and
#: allows five per page (Wix Help Center, "Adding Structured Data Markup to
#: Your Site's Pages").
WIX_MARKUP_LIMIT = 7000

INSTALL_STEPS: dict[str, str] = {
    "wordpress": (
        "WordPress, about 5 minutes:\n"
        "1. In your WordPress dashboard go to Plugins > Add New, search for "
        "\"WPCode\", then Install and Activate.\n"
        "2. Go to Code Snippets > Header & Footer.\n"
        "3. In the Header box, paste each file below wrapped like this:\n"
        "   <script type=\"application/ld+json\"> ...the file... </script>\n"
        "4. Save. That puts it on every page, which is what you want for the "
        "business details."),
    "wix": (
        "Wix, about 5 minutes:\n"
        "1. In the Wix editor, open Pages & Menu and click the three dots next "
        "to your Home page.\n"
        "2. Click SEO basics, then the Advanced SEO tab, then Structured Data "
        "Markup.\n"
        "3. Click + Add New Markup and paste one file. Do it again for the "
        "second file.\n"
        "4. Click Apply, then Publish the site.\n"
        f"Wix only accepts markups under {WIX_MARKUP_LIMIT:,} characters and "
        "five per page; the files below are already sized to fit."),
    "squarespace": (
        "Squarespace, about 5 minutes (needs the Core plan or above — the "
        "Basic plan has no code injection):\n"
        "1. Go to Settings > Advanced (or Website Tools) > Code Injection.\n"
        "2. In the Header box, paste each file below wrapped like this:\n"
        "   <script type=\"application/ld+json\"> ...the file... </script>\n"
        "3. Save."),
    "godaddy": (
        "GoDaddy Website Builder, about 10 minutes:\n"
        "1. Open your site in the GoDaddy editor. Check the page's Settings > "
        "SEO for a structured data or schema field first, and paste there if "
        "it exists.\n"
        "2. If it doesn't, add an HTML section to the homepage and paste each "
        "file wrapped like this:\n"
        "   <script type=\"application/ld+json\"> ...the file... </script>\n"
        "GoDaddy sometimes places HTML sections in a frame that search engines "
        "don't read as part of the page. We check your homepage after you do "
        "this and will tell you if it isn't being seen."),
    "shopify": (
        "Shopify, about 10 minutes:\n"
        "1. Online Store > Themes > the three dots > Edit code.\n"
        "2. Open layout/theme.liquid and paste each file just before </head>, "
        "wrapped like this:\n"
        "   <script type=\"application/ld+json\"> ...the file... </script>\n"
        "3. Save."),
    "webflow": (
        "Webflow, about 5 minutes (needs a paid site plan for custom code):\n"
        "1. Site settings > Custom code > Head code.\n"
        "2. Paste each file wrapped like this:\n"
        "   <script type=\"application/ld+json\"> ...the file... </script>\n"
        "3. Save and Publish."),
    "duda": (
        "Duda: Site settings > Head HTML, paste each file wrapped in "
        "<script type=\"application/ld+json\"> ... </script>, then Republish."),
    "weebly": (
        "Square Online / Weebly: Settings > SEO > Header Code, paste each file "
        "wrapped in <script type=\"application/ld+json\"> ... </script>, then "
        "Publish."),
    "unknown": (
        "Forward this to whoever looks after your website:\n"
        "\"Please add the two JSON files below to the site as JSON-LD, each "
        "inside <script type=\"application/ld+json\"> tags in the <head> of "
        "the homepage, exactly as they are.\""),
}


def install_steps(platform: str) -> str:
    return INSTALL_STEPS.get(platform, INSTALL_STEPS["unknown"])


def fit_for_platform(json_text: str, platform: str) -> str:
    """Compact the JSON, and for Wix make sure it fits the per-markup limit.

    A FAQPage file can run past Wix's limit; Wix then refuses it outright,
    and an owner who has just been told "paste this" stops there. Dropping
    the last questions until it fits keeps the file valid and installable.
    """
    try:
        doc = json.loads(json_text)
    except ValueError:
        return json_text
    compact = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
    if platform != "wix":
        return json.dumps(doc, indent=2, ensure_ascii=False)
    items = doc.get("mainEntity") if isinstance(doc, dict) else None
    while len(compact) >= WIX_MARKUP_LIMIT and isinstance(items, list) and len(items) > 1:
        items.pop()
        compact = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
    return compact
