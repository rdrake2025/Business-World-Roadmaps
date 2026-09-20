"""Whether the answer engines are allowed to read the site at all.

Every other measurement in this system assumes the engines can see the page.
Often they cannot, because the site's own ``robots.txt`` tells them not to —
usually added by a theme, a plugin, or an agency that pasted in a
"block AI scrapers" snippet without knowing that the same rule removes the
business from the answers its customers are reading.

That makes this the first thing to check and the most valuable thing to find.
It is binary, it is verifiable by the owner in ten seconds, and fixing it is
free. "You are invisible to ChatGPT because your own site tells it to leave"
is a different conversation from "your visibility could be better".

The distinctions below matter and are easy to get wrong, so they are encoded
rather than assumed:

* Blocking ``Google-Extended`` does **not** remove a site from AI Overviews.
  That surface is served from the normal Googlebot index. Google-Extended
  governs Gemini training and grounding only.
* Blocking ``GPTBot`` does **not** remove a site from ChatGPT's search
  results. GPTBot is the training crawler; ``OAI-SearchBot`` is the one that
  builds the search index, and ``ChatGPT-User`` fetches a page when a user's
  question calls for it.
* Blocking ``Googlebot`` removes a site from ordinary Google *and* from AI
  Overviews, which is a far larger problem than the one being audited.

Telling an owner they are blocked from a surface they are not blocked from
would be caught the moment they checked, and would cost the account.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

USER_AGENT = ("AnswerRankBot/1.0 (+https://answerrank.io/about; "
              "robots.txt audit)")


@dataclass(frozen=True)
class Crawler:
    token: str            #: the user-agent string used in robots.txt
    operator: str
    surface: str          #: what a block actually costs
    critical: bool        #: whether a block removes the business from answers


#: Ordered by how much a block costs the business.
CRAWLERS: tuple[Crawler, ...] = (
    Crawler("Googlebot", "Google",
            "Google Search and AI Overviews", True),
    Crawler("OAI-SearchBot", "OpenAI",
            "ChatGPT search results", True),
    Crawler("ChatGPT-User", "OpenAI",
            "ChatGPT fetching the page to answer a live question", True),
    Crawler("PerplexityBot", "Perplexity",
            "Perplexity answers and citations", True),
    Crawler("Claude-SearchBot", "Anthropic",
            "Claude search results", True),
    Crawler("Claude-User", "Anthropic",
            "Claude fetching the page to answer a live question", True),
    Crawler("bingbot", "Microsoft",
            "Bing and Microsoft Copilot", True),
    Crawler("Applebot", "Apple",
            "Siri and Spotlight suggestions", True),
    Crawler("GPTBot", "OpenAI",
            "OpenAI model training — not ChatGPT search", False),
    Crawler("ClaudeBot", "Anthropic",
            "Anthropic model training — not Claude search", False),
    Crawler("Google-Extended", "Google",
            "Gemini grounding and training — not AI Overviews", False),
    Crawler("CCBot", "Common Crawl",
            "Common Crawl, which feeds many models indirectly", False),
)


@dataclass
class Access:
    domain: str
    blocked: list[Crawler] = field(default_factory=list)
    allowed: list[Crawler] = field(default_factory=list)
    robots_found: bool = False
    error: str = ""

    @property
    def critical_blocks(self) -> list[Crawler]:
        return [c for c in self.blocked if c.critical]

    @property
    def ok(self) -> bool:
        return not self.critical_blocks and not self.error

    def headline(self) -> str:
        """The sentence that goes in the audit, or an honest nothing."""
        if self.error:
            return (f"Could not read robots.txt for {self.domain} "
                    f"({self.error}), so whether the answer engines are "
                    f"allowed in is unknown. Worth checking by hand.")
        if not self.robots_found:
            return (f"{self.domain} publishes no robots.txt, so every answer "
                    f"engine is free to read it. Nothing to fix here.")
        critical = self.critical_blocks
        if not critical:
            blocked = [c.token for c in self.blocked]
            if blocked:
                return (f"{self.domain} blocks {', '.join(blocked)}, which "
                        f"affects model training but not the answers customers "
                        f"see. Not costing you visibility.")
            return (f"{self.domain} allows every answer engine to read it. "
                    f"Nothing to fix here.")
        names = ", ".join(c.token for c in critical)
        surfaces = "; ".join(sorted({c.surface for c in critical}))
        return (f"{self.domain} blocks {names} in its own robots.txt. That "
                f"removes it from {surfaces} — not because of competition, "
                f"but because the site asks them to leave.")

    def fix(self) -> str:
        if not self.critical_blocks:
            return ""
        lines = "\n".join(f"User-agent: {c.token}\nAllow: /\n"
                          for c in self.critical_blocks)
        return (f"Edit https://{self.domain}/robots.txt and allow these:\n\n"
                f"{lines}\nThe change takes effect the next time each engine "
                f"crawls, usually within a few days.")


# ---------------------------------------------------------------------------

def _groups(text: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    """Parse robots.txt into (user-agents, [(directive, path)]) groups.

    Written by hand rather than with ``urllib.robotparser`` because that
    module answers "may I fetch this URL" for one agent at a time and hides
    which rule decided it. The audit has to report the rule, not the verdict —
    an owner who is told they are blocked will ask where it says that.
    """
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    starting_group = False

    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name = field_name.strip().lower()
        value = value.strip()

        if field_name == "user-agent":
            if rules and not starting_group:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
            starting_group = True
        elif field_name in {"allow", "disallow"}:
            starting_group = False
            rules.append((field_name, value))
    if agents:
        groups.append((agents, rules))
    return groups


def _blocks(groups, token: str) -> bool:
    """Whether the root path is disallowed for this crawler.

    Follows the specificity rule every major crawler implements: a group
    naming the agent wins outright over the wildcard group, so a site that
    disallows ``*`` while allowing ``GPTBot`` is not blocking GPTBot.
    """
    token = token.lower()
    specific = [rules for agents, rules in groups if token in agents]
    wildcard = [rules for agents, rules in groups if "*" in agents]
    applicable = specific or wildcard
    if not applicable:
        return False

    blocked = False
    for rules in applicable:
        for directive, path in rules:
            if directive == "disallow" and path in {"/", "/*"}:
                blocked = True
            elif directive == "allow" and path in {"/", "/*"}:
                blocked = False
            elif directive == "disallow" and path == "":
                blocked = False  # "Disallow:" with no path means allow all
    return blocked


def check_access(website: str, timeout: int = 12, session=None) -> Access:
    """Read the site's robots.txt and report which engines it turns away."""
    if not website:
        return Access(domain="", error="no website on file")
    if not website.startswith(("http://", "https://")):
        website = "https://" + website
    domain = urlparse(website).netloc.lower().removeprefix("www.")
    result = Access(domain=domain)

    try:
        import requests
    except ImportError:
        result.error = "requests is not installed"
        return result

    own = session is None
    session = session or requests.Session()
    try:
        resp = session.get(urljoin(website, "/robots.txt"), timeout=timeout,
                           headers={"User-Agent": USER_AGENT})
        # Only a genuine absence means "no rules". A 403 or a 500 means the
        # file could not be read, which is not the same thing at all —
        # reporting it as all-clear would tell an owner they are fine when
        # the truth is unknown, which is the one direction this check must
        # never be wrong in.
        if resp.status_code in {404, 410}:
            result.allowed = list(CRAWLERS)
            return result
        if resp.status_code >= 400:
            result.error = f"robots.txt returned HTTP {resp.status_code}"
            return result
        text = resp.text[:200_000]
    except Exception as exc:  # noqa: BLE001 - an unreachable file is not a block
        result.error = type(exc).__name__
        return result
    finally:
        if own:
            session.close()

    result.robots_found = True
    groups = _groups(text)
    for crawler in CRAWLERS:
        (result.blocked if _blocks(groups, crawler.token)
         else result.allowed).append(crawler)
    return result
