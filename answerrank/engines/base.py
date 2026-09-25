"""Answer-engine abstraction plus the answer-parsing logic.

The parsing here is the core IP of the product. Given the free-text answer an
AI engine produced for a buyer-intent question, we have to decide:

* Was the client named at all?
* If so, how prominently (a #1 recommendation beats a footnote)?
* Was the client's own domain used as a *source* (citation), which is the
  stronger signal and the one that survives model retraining?
* Which competitors took the slots the client didn't?

Everything downstream — the score, the report, the sales email — is derived
from these four answers, so this module is deliberately conservative: it
would rather miss a fuzzy mention than invent one.
"""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse

# Words that appear inside business names but must not be used to match on
# their own, or every "Air" would match every other "Air".
STOPWORDS = {
    "the", "and", "of", "for", "inc", "llc", "co", "company", "corp", "group",
    "services", "service", "solutions", "systems", "a", "an",
}

# Suffixes that strongly indicate a phrase is a business name.
BIZ_SUFFIXES = (
    "hvac", "air", "heating", "cooling", "plumbing", "plumbers", "electric",
    "electrical", "roofing", "dental", "dentistry", "orthodontics", "law",
    "legal", "clinic", "medical", "health", "insurance", "realty", "homes",
    "landscaping", "pest", "cleaning", "movers", "moving", "auto", "repair",
    "construction", "contractors", "remodeling", "inc", "llc", "co",
    "company", "group", "associates", "partners", "services", "solutions",
    "& sons", "and sons",
    # The list above was written for the original seven trades. A competitor
    # named "Summit Roofs" or "Peak Exteriors" went unrecognised, which
    # undercounts the competitor gap — and that gap is the entire sales
    # argument, so undercounting it argues the client's case for them.
    "roofs", "roofers", "exteriors", "restoration", "spa", "aesthetics",
    "wellness", "veterinary", "vet", "animal", "hospital", "chiropractic",
    "chiropractors", "septic", "flooring", "floors", "tile", "carpet",
    "appliance", "appliances", "garage", "doors", "door", "tree", "arbor",
    "arborists", "lawn", "landscape", "pools", "collision", "tire", "tires",
    "transmission", "automotive", "motors", "kitchen", "bath", "renovations",
    "builders", "exterminators", "termite", "storage", "van", "lines",
)

NEGATIVE_CUES = ("avoid", "complaints", "poor reviews", "negative", "lawsuit", "scam", "warning")
POSITIVE_CUES = ("top rated", "highly rated", "best", "excellent", "trusted", "recommended",
                 "highly recommend", "well-reviewed", "top choice", "outstanding")


def normalize(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace.

    Apostrophes are deleted rather than replaced with a space, so "Joe's
    Plumbing" becomes "joes plumbing" and matches an answer that writes it
    without the apostrophe — which answers routinely do. Replacing it with a
    space split the name into "joe" and "s", and "joe" then failed to match
    "joes", so a real mention of a real client was recorded as an absence.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[\u2018\u2019']", "", text.lower())
    text = re.sub(r"[^\w\s&]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def name_tokens(name: str) -> list[str]:
    return [t for t in normalize(name).split() if t not in STOPWORDS and len(t) > 1]


#: How far apart the words of a name may sit and still be the same name.
#: "Apex Heating and Air" spreads four tokens; a whole paragraph mentioning
#: "Apex" in one sentence and "Air" in another is not a mention of the
#: business, and treating it as one is what this window exists to prevent.
NAME_WINDOW_SLACK = 3


def _word_in(needle: str, hay: str) -> bool:
    """Substring match on whole words only.

    Without this, a business called "Ace" matches the "ace" inside "place",
    and a one-word trade name scores visibility it does not have.
    """
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", hay) is not None


def name_matches(business_name: str, haystack: str) -> bool:
    """Does ``business_name`` appear in ``haystack``?

    Either the full name appears as whole words, or enough of its tokens
    appear *close together* — which is the part that matters and the part the
    first version of this function only claimed to do. It checked whether each
    token appeared anywhere in the answer, so "Austin Plumbing" matched an
    answer that merely mentioned Austin and then recommended a competitor
    whose name ended in Plumbing.

    Every failure of that kind inflates a client's score: it reports them as
    visible when they are not. That is the direction this must never be wrong
    in, because the client can check it in ten seconds and the whole
    engagement rests on the number being true. So the bar is deliberately set
    where a fuzzy mention is missed rather than invented.
    """
    hay = normalize(haystack)
    full = normalize(business_name)
    if not full or not hay:
        return False
    if _word_in(full, hay):
        return True

    tokens = name_tokens(business_name)
    if not tokens:
        return False

    # The distinctive part of a local business name is usually the first token
    # ("Apex", "Lone Star") rather than the trade word every competitor shares.
    distinctive = [t for t in tokens if t not in BIZ_SUFFIXES] or tokens
    anchors = distinctive[:2]

    hay_tokens = hay.split()
    span = len(tokens) + NAME_WINDOW_SLACK
    # Enough of the name, close together. A two-token name needs both; a
    # four-token name needs three, so "Lone Star Plumbing" is not read as a
    # mention of "Lone Star Heating & Air".
    needed = max(2, -(-len(tokens) * 6 // 10))
    if len(tokens) < needed:
        return False

    # A two-word name has no redundancy: both words must sit together or it is
    # not that name. "Denver Roofing" is not mentioned by "roofing in Denver:
    # Peak Roofing" — the trade word there belongs to a competitor. Longer
    # names can lose one word and still be recognisable, so they keep the
    # window.
    if len(tokens) == 2:
        for i in range(len(hay_tokens) - 1):
            if hay_tokens[i] == tokens[0] and hay_tokens[i + 1] == tokens[1]:
                return True
        return False

    for i, word in enumerate(hay_tokens):
        if word != anchors[0]:
            continue
        window = hay_tokens[i:i + span]
        if not all(a in window for a in anchors):
            continue
        if sum(1 for t in tokens if t in window) >= needed:
            return True
    return False


def extract_businesses(answer: str) -> list[str]:
    """Pull candidate business names out of an AI answer, in order of appearance.

    AI answers about local services are overwhelmingly formatted as numbered
    or bulleted lists with the name bolded or leading the line, so we mine
    those structures first and fall back to a capitalized-phrase heuristic.
    """
    found: list[str] = []

    def add(candidate: str) -> None:
        cand = candidate.strip(" *_:—-–\t")
        cand = re.sub(r"\s+", " ", cand)
        # Trim trailing descriptive clauses: "Apex HVAC - open 24/7" -> "Apex HVAC"
        cand = re.split(r"\s+[-–—]\s+|\s*\(|,\s", cand)[0].strip()
        if not (2 < len(cand) < 60):
            return
        if normalize(cand) in {normalize(f) for f in found}:
            return
        if not re.search(r"[A-Za-z]", cand):
            return
        found.append(cand)

    for raw_line in (answer or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # 1. **Bolded** names anywhere on the line.
        bold = re.findall(r"\*\*(.+?)\*\*", line)
        if bold:
            for b in bold:
                add(b)
            continue
        # 2. "1. Name" / "- Name" / "* Name" list items.
        m = re.match(r"^(?:\d+[\.\)]|[-*•])\s+(.+)$", line)
        if m:
            add(m.group(1))
            continue

    # 3. Prose lists. Not every answer is bulleted: "Here are some options:
    #    Apex Roofing, Summit Roofs, and Peak Exteriors." Splitting on the
    #    separators a person would read as a list recovers the names the
    #    line-based passes above cannot see.
    if len(found) < 2:
        for run in re.findall(
                r"(?:such as|including|options?(?:\s+are)?|recommend|try|consider)\s*:?\s+"
                r"([^.!?\n]{6,220})", answer or "", re.I):
            parts = re.split(r",\s*(?:and\s+)?|\s+and\s+|;\s*", run)
            for part in parts:
                part = part.strip()
                # Only capitalised phrases; a trailing clause is not a name.
                if re.match(r"^[A-Z][\w'&.\-]*(?:\s+[A-Z0-9][\w'&.\-]*){0,3}$", part):
                    add(part)

    # 4. Fallback: capitalized phrases ending in a known business suffix.
    if len(found) < 2:
        for m in re.finditer(
            r"\b((?:[A-Z][\w'&.-]*\s+){0,3}[A-Z][\w'&.-]*)\b", answer or ""
        ):
            phrase = m.group(1).strip()
            low = phrase.lower()
            if any(low.endswith(s) or f" {s}" in low for s in BIZ_SUFFIXES):
                add(phrase)

    return found


def detect_sentiment(answer: str, business_name: str) -> str:
    """Sentiment of the *context the business appears in*, not the whole answer."""
    if not name_matches(business_name, answer):
        return "absent"
    hay = normalize(answer)
    idx = hay.find(normalize(business_name).split()[0])
    window = hay[max(0, idx - 200): idx + 300] if idx >= 0 else hay
    neg = sum(1 for c in NEGATIVE_CUES if c in window)
    pos = sum(1 for c in POSITIVE_CUES if c in window)
    if neg > pos:
        return "negative"
    if pos > 0:
        return "positive"
    return "neutral"


def source_host(source: str) -> str:
    """The hostname a cited source points at, lowercased and de-www'd.

    Sources arrive as full URLs from Perplexity and Serper, and occasionally
    as a bare hostname. Both have to reduce to the same thing.
    """
    raw = (source or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        host = urlparse(raw).netloc
    except ValueError:
        return ""
    host = host.split("@")[-1].split(":")[0]
    return host.removeprefix("www.").strip(".")


def cites_domain(domain: str, sources: list[str]) -> bool:
    """Whether any source is genuinely the business's own site.

    This is a host comparison and not a substring search, which is what it
    used to be. ``"joesac.com" in source`` counts ``notjoesac.com``,
    ``joesac.com.example.ru`` and a Yelp page whose URL happens to spell the
    domain out. Citation is a fifth of the score and the component sold as
    the durable one, so every false positive here is a client paying to
    watch a number they did not earn — and a number that drops the moment
    anyone checks it by hand.
    """
    domain = (domain or "").strip().lower().removeprefix("www.").strip(".")
    if not domain or "." not in domain:
        return False
    for source in sources or []:
        host = source_host(source)
        if host and (host == domain or host.endswith("." + domain)):
            return True
    return False


@dataclass
class EngineAnswer:
    """Raw output from one engine before we interpret it."""

    text: str
    sources: list[str]
    latency_ms: int = 0
    error: str = ""
    #: Answered from a live web search, as the consumer product does, rather
    #: than from a model's memory. Only grounded answers are quoted to anyone.
    grounded: bool = False


class AnswerEngine(ABC):
    """One AI answer surface we can interrogate (ChatGPT, Claude, Perplexity...)."""

    name: str = "base"
    #: Human label used in client-facing reports.
    label: str = "Answer Engine"
    #: Relative weight in the composite score. Engines with more buyer traffic
    #: matter more; these reflect late-2026 assistant usage share.
    weight: float = 1.0

    #: Where the question is asked from, for engines that can localise.
    city: str = ""
    state: str = ""

    def locate(self, city: str, state: str) -> "AnswerEngine":
        self.city, self.state = city or "", state or ""
        return self

    @abstractmethod
    def ask(self, prompt: str) -> EngineAnswer:
        """Ask one buyer-intent question and return the answer plus sources."""

    def available(self) -> bool:
        return True
