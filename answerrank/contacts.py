"""Finding the address a business publishes for people to contact them on.

Everything upstream of this works and produces nothing, because the local
search results the Scout reads give a name, a website and a phone number —
never an email. The outreach agent requires one, so in production every
single real prospect was filtered out as uncontactable while the simulation,
which fabricates addresses, ran perfectly. The pipeline looked healthy and
could not send a single message.

What this does is what a person does when they want to contact a business:
open the site, click Contact, read the address printed there. Nothing more.
It reads the pages a business publishes for exactly this purpose, obeys
robots.txt, identifies itself honestly, and goes no further.

**It never guesses.** ``info@theirdomain.com`` is right often enough to be
tempting and wrong often enough to be fatal: every wrong guess is a bounce,
bounces are capped at 2% before the sending domain is throttled wholesale,
and a guessed address cannot be distinguished from a real one until the
damage is done. A business whose address cannot be found is recorded as not
found, which is a fact the operator can act on — by calling the phone number
the Scout already has.
"""

from __future__ import annotations

import re
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

#: Pages a business publishes its contact details on, in the order worth trying.
CONTACT_PATHS = ("/contact", "/contact-us", "/contact.html", "/contact-us.html",
                 "", "/about", "/about-us")

#: Local parts that reach a person who can say yes, best first.
ROLE_PREFERENCE = ("owner", "hello", "info", "office", "contact", "admin",
                   "service", "sales", "team", "mail")

#: Local parts that reach nobody worth writing to.
DEAD_LOCALS = {"noreply", "no-reply", "donotreply", "do-not-reply", "bounce",
               "mailer-daemon", "postmaster", "abuse", "dmca"}

#: Placeholder addresses left in themes and templates. Writing to one is a
#: guaranteed bounce and tells you nothing about the business.
PLACEHOLDER_LOCALS = {"youremail", "your-email", "your_email", "email", "name",
                      "firstname", "yourname", "user", "username", "someone",
                      "example", "test", "demo", "sample"}

PLACEHOLDER_DOMAINS = {
    "example.com", "example.org", "example.net", "domain.com", "yourdomain.com",
    "mysite.com", "company.com", "email.com", "sentry.io", "wixpress.com",
    "sentry-next.wixpress.com", "schema.org", "w3.org", "godaddy.com",
    "squarespace.com", "wordpress.com", "wix.com", "shopify.com", "site.com",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
#: Retina image filenames such as logo@2x.png parse as an address otherwise.
IMAGE_TAIL_RE = re.compile(r"\.(png|jpe?g|gif|webp|svg|ico|bmp|css|js)$", re.I)

USER_AGENT = ("AnswerRankBot/1.0 (+https://answerrank.io/about; "
              "contact discovery for a one-time outreach)")

#: Hard ceilings on what one page may cost us. A contact page is a few tens
#: of kilobytes; anything past this is a misconfigured server, an export, or
#: a file that happens to answer on that URL. The agent runs unattended, so
#: "download it all and slice afterwards" is a memory leak with a schedule.
_MAX_PAGE_BYTES = 2_000_000
_MAX_ROBOTS_BYTES = 200_000


@dataclass
class Contact:
    email: str = ""
    source_url: str = ""
    confidence: str = ""      #: own-domain-role | own-domain | third-party
    considered: tuple[str, ...] = ()
    note: str = ""

    @property
    def found(self) -> bool:
        return bool(self.email)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def is_usable(email: str) -> bool:
    """Whether this is a real address a person reads."""
    email = email.strip().strip(".").lower()
    if email.count("@") != 1 or len(email) > 254:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain or ".." in email:
        return False
    if IMAGE_TAIL_RE.search(domain):
        return False
    if re.fullmatch(r"\d+x", local) or re.fullmatch(r"\d+x", domain.split(".")[0]):
        return False
    if local in DEAD_LOCALS or local in PLACEHOLDER_LOCALS:
        return False
    if domain in PLACEHOLDER_DOMAINS:
        return False
    if any(domain.endswith("." + d) for d in PLACEHOLDER_DOMAINS):
        return False
    return True


def extract_emails(html: str) -> list[str]:
    """Every plausible address on a page, mailto links first.

    A ``mailto:`` is the address the business chose to publish for contact;
    a bare string in the body might be a vendor, a photo credit or a careers
    inbox. The ordering is preserved so the ranker can prefer the deliberate
    one.
    """
    if not html:
        return []
    found: list[str] = []
    for raw in re.findall(r'mailto:([^"\'>\s?]+)', html, re.I):
        candidate = raw.strip().lower()
        if is_usable(candidate) and candidate not in found:
            found.append(candidate)
    for raw in EMAIL_RE.findall(html):
        candidate = raw.strip().lower()
        if is_usable(candidate) and candidate not in found:
            found.append(candidate)
    return found


def rank(emails: list[str], domain: str) -> list[str]:
    """Best contact first: their own domain beats a free inbox, and a role
    address beats a named individual who may have left the company."""
    domain = (domain or "").lower().removeprefix("www.")

    def key(email: str) -> tuple[int, int, int]:
        local, _, host = email.partition("@")
        host = host.removeprefix("www.")
        own = host == domain or host.endswith("." + domain) if domain else False
        try:
            role = ROLE_PREFERENCE.index(local)
        except ValueError:
            role = len(ROLE_PREFERENCE)
        return (0 if own else 1, role, len(email))

    return sorted(emails, key=key)


def classify(email: str, domain: str) -> str:
    local, _, host = (email or "").partition("@")
    domain = (domain or "").lower().removeprefix("www.")
    host = host.removeprefix("www.")
    own = bool(domain) and (host == domain or host.endswith("." + domain))
    if own and local in ROLE_PREFERENCE:
        return "own-domain-role"
    if own:
        return "own-domain"
    return "third-party"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _robots(session, base: str) -> "urllib.robotparser.RobotFileParser | None":
    """Fetch and parse robots.txt once. None means "no rules we could read"."""
    parser = urllib.robotparser.RobotFileParser()
    try:
        resp = session.get(urljoin(base, "/robots.txt"), timeout=10)
        if resp.status_code >= 400:
            return None  # no robots file is permission by convention
        parser.parse(resp.text[:_MAX_ROBOTS_BYTES].splitlines())
    except Exception:  # noqa: BLE001 - an unreadable robots file is not a refusal
        return None
    return parser


def _allowed(parser, base: str, path: str) -> bool:
    """Honour robots.txt. A business that asks not to be crawled is not
    crawled, and we are asking for a favour here, not exercising a right.

    The parser is fetched once per site and passed in. It used to be
    refetched for every candidate path, which meant up to seven requests for
    the same file per prospect — a lot of noise in someone's access log from
    a crawler asking them for a favour.
    """
    if parser is None:
        return True
    try:
        return parser.can_fetch(USER_AGENT, urljoin(base, path or "/"))
    except Exception:  # noqa: BLE001
        return True


def _fetch_html(session, url: str, timeout: int) -> str | None:
    """One page of HTML, capped, or None if it is not worth reading.

    Streams and stops at the cap rather than letting ``resp.text`` pull an
    arbitrarily large body into memory first.
    """
    resp = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
    try:
        if resp.status_code >= 400:
            return None
        ctype = resp.headers.get("Content-Type", "text/html").lower()
        if "html" not in ctype:
            return None
        chunks: list[bytes] = []
        size = 0
        for chunk in resp.iter_content(64 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if size >= _MAX_PAGE_BYTES:
                break
        encoding = resp.encoding or "utf-8"
        return b"".join(chunks).decode(encoding, "replace")
    finally:
        resp.close()


def find_contact(website: str, timeout: int = 12, max_pages: int = 4,
                 session=None) -> Contact:
    """Read the pages a business publishes to be contacted on. Never guesses."""
    if not website:
        return Contact(note="no website on file")
    if not website.startswith(("http://", "https://")):
        website = "https://" + website
    domain = urlparse(website).netloc.lower().removeprefix("www.")
    if not domain:
        return Contact(note="website is not a usable URL")

    try:
        import requests
    except ImportError:
        return Contact(note="requests is not installed")

    own = session is None
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT,
                            "Accept": "text/html,application/xhtml+xml"})

    seen: list[str] = []
    checked = 0
    try:
        robots = _robots(session, website)
        for path in CONTACT_PATHS:
            if checked >= max_pages:
                break
            if not _allowed(robots, website, path):
                return Contact(note="robots.txt asks us not to read this site",
                               considered=tuple(seen))
            url = urljoin(website, path) if path else website
            try:
                html = _fetch_html(session, url, timeout)
            except Exception:  # noqa: BLE001 - one dead page is not a dead site
                continue
            checked += 1
            if html is None:
                continue
            for email in extract_emails(html):
                if email not in seen:
                    seen.append(email)
            best = rank(seen, domain)
            # Stop as soon as an address on their own domain turns up; more
            # pages will only add vendors and photo credits.
            if best and classify(best[0], domain).startswith("own-domain"):
                return Contact(email=best[0], source_url=url,
                               confidence=classify(best[0], domain),
                               considered=tuple(seen))
    finally:
        if own:
            session.close()

    best = rank(seen, domain)
    if not best:
        return Contact(note=f"no address published on {domain}",
                       considered=tuple(seen))
    return Contact(email=best[0], source_url=website,
                   confidence=classify(best[0], domain), considered=tuple(seen))
