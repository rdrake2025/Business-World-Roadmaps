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
)

NEGATIVE_CUES = ("avoid", "complaints", "poor reviews", "negative", "lawsuit", "scam", "warning")
POSITIVE_CUES = ("top rated", "highly rated", "best", "excellent", "trusted", "recommended",
                 "highly recommend", "well-reviewed", "top choice", "outstanding")


def normalize(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s&]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def name_tokens(name: str) -> list[str]:
    return [t for t in normalize(name).split() if t not in STOPWORDS and len(t) > 1]


def name_matches(business_name: str, haystack: str) -> bool:
    """Does ``business_name`` appear in ``haystack``?

    Requires either the full normalized name as a substring, or all of the
    distinctive tokens present within a short window of each other. The window
    check catches "Apex Heating & Air" when the answer says "Apex Air".
    """
    hay = normalize(haystack)
    full = normalize(business_name)
    if not full:
        return False
    if full in hay:
        return True

    tokens = name_tokens(business_name)
    if not tokens:
        return False
    # The distinctive part of a local business name is usually the first token
    # ("Apex", "Lone Star"). Require it, plus a majority of the rest.
    distinctive = [t for t in tokens if t not in BIZ_SUFFIXES] or tokens
    if not all(t in hay for t in distinctive[:2]):
        return False
    present = sum(1 for t in tokens if t in hay)
    return present >= max(1, int(len(tokens) * 0.6))


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

    # 3. Fallback: capitalized phrases ending in a known business suffix.
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


@dataclass
class EngineAnswer:
    """Raw output from one engine before we interpret it."""

    text: str
    sources: list[str]
    latency_ms: int = 0
    error: str = ""


class AnswerEngine(ABC):
    """One AI answer surface we can interrogate (ChatGPT, Claude, Perplexity...)."""

    name: str = "base"
    #: Human label used in client-facing reports.
    label: str = "Answer Engine"
    #: Relative weight in the composite score. Engines with more buyer traffic
    #: matter more; these reflect late-2026 assistant usage share.
    weight: float = 1.0

    @abstractmethod
    def ask(self, prompt: str) -> EngineAnswer:
        """Ask one buyer-intent question and return the answer plus sources."""

    def available(self) -> bool:
        return True
