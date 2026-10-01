"""The live test: every outside service, once, with your real keys.

Every test and simulation in this project fakes the outside world: the
mailbox, Stripe, OpenAI, Serper, DNS, the internet. That proves the logic,
not the connections, and the connections are where a first day goes wrong:
a mistyped app password, a Stripe key without the right permission, a DNS
record at the wrong name. This runs each one for real, once, before any
prospect could be affected by it, and says in plain words what to fix.

What it touches, and what it costs:

* Sends one email to **you**, and reads it back from your inbox. The reply
  reader ignores mail from your own address, so it is never treated as a
  customer.
* One real ChatGPT check with web search: about 1.5 cents.
* One Serper search: one of your 2,500 free credits.
* Reads (never writes) Stripe: the restricted key can't move money anyway.
* Opens your payment links, portal link and your server's public pages.

Nothing is sent to anyone but you.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable


@dataclass
class Result:
    key: str
    name: str
    ok: bool | None          #: None: not set up yet, so not tested
    detail: str
    fix: str = ""


def _get(url: str, timeout: int = 15):
    import requests
    return requests.get(url, timeout=timeout, allow_redirects=True,
                        headers={"User-Agent": "AnswerRank self-test"})


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def check_mail_round_trip(settings, wait_seconds: int = 90,
                          sleep: Callable[[float], None] = time.sleep) -> list[Result]:
    """Send yourself a message and find it in the inbox."""
    import email
    import imaplib
    import os

    from .mailer import Mailer, SMTPConfig

    cfg = SMTPConfig.from_env()
    if not cfg.configured():
        return [Result("send", "Sending email", None, "no mailbox saved",
                       "Keys and settings: your mailbox address and app password.")]
    token = uuid.uuid4().hex[:10]
    to = cfg.username
    ok, detail = Mailer(settings).send(
        to, f"AnswerRank self-test {token}",
        "This is AnswerRank checking that it can send and read your email.\n"
        "You can delete it. Nothing was sent to anyone else.")
    out = [Result("send", "Sending email", ok,
                  f"sent to {to}" if ok else detail,
                  "" if ok else "Usually the app password: make a new one at "
                  "myaccount.google.com/apppasswords and paste it in Keys and settings.")]
    if not ok:
        return out
    host = os.environ.get("IMAP_HOST", "")
    user = os.environ.get("IMAP_USERNAME") or cfg.username
    pwd = os.environ.get("IMAP_PASSWORD") or cfg.password
    if not host:
        out.append(Result("read", "Reading replies", None, "not switched on",
                          "Keys and settings: answer yes to reading replies automatically."))
        return out
    found, problem, waited = False, "", 0
    while waited <= wait_seconds and not found:
        try:
            with imaplib.IMAP4_SSL(host) as box:
                box.login(user, pwd)
                box.select("INBOX", readonly=True)
                _t, data = box.search(None, f'(SUBJECT "self-test {token}")')
                found = bool(data and data[0])
        except (imaplib.IMAP4.error, OSError) as exc:
            problem = f"{type(exc).__name__}: {exc}"
            break
        if not found:
            sleep(5)
            waited += 5
    if problem:
        out.append(Result("read", "Reading replies", False, problem[:160],
                          "The same app password works for reading; check IMAP is on in "
                          "Gmail settings (Forwarding and POP/IMAP)."))
    else:
        out.append(Result("read", "Reading replies", found,
                          f"the test email arrived in your inbox" if found else
                          f"the test email hadn't arrived after {wait_seconds} seconds",
                          "" if found else "Look for it in Spam. If it's there, your "
                          "email domain records aren't passing yet (desktop button, 3)."))
    return out


def check_ai(settings) -> Result:
    from .engines.live import build_engines

    if not settings.api_key("openai"):
        return Result("ai", "Real AI check (ChatGPT with web search)", None,
                      "no OpenAI key", "Keys and settings: an OpenAI API key.")
    try:
        engine = build_engines(["openai"], "", "plumbing", settings.request_timeout,
                               city="Austin", state="TX")[0]
        answer = engine.ask("Who is the best emergency plumber in Austin, TX?")
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return Result("ai", "Real AI check (ChatGPT with web search)", False,
                      f"{type(exc).__name__}: {exc}"[:160],
                      "Check the key at platform.openai.com and that the account has credit.")
    if answer.error:
        from .audit import fix_for
        return Result("ai", "Real AI check (ChatGPT with web search)", False,
                      answer.error[:160], fix_for([answer.error]))
    if not answer.grounded:
        return Result("ai", "Real AI check (ChatGPT with web search)", False,
                      "answered from memory, not a live web search",
                      "The key works but web search was refused: the account may need "
                      "credit added, or the model name is not available to it.")
    return Result("ai", "Real AI check (ChatGPT with web search)", True,
                  f"answered from a live search, {len(answer.sources)} sources")


def check_finder(store, settings) -> Result:
    from .agents.scout import ScoutAgent

    if not settings.api_key("serper"):
        return Result("finder", "Business finder (Serper)", None, "no Serper key",
                      "Keys and settings: a free key from serper.dev.")
    found = ScoutAgent(store, settings).from_serper("plumbing", "Austin", "TX")
    if not found:
        return Result("finder", "Business finder (Serper)", False,
                      "the search came back empty",
                      "Check the key at serper.dev and that it has credits left.")
    with_site = sum(1 for b in found if b.website)
    return Result("finder", "Business finder (Serper)", True,
                  f"found {len(found)} businesses, {with_site} with a website")


def check_stripe(settings) -> list[Result]:
    import os

    from . import payments

    key = os.environ.get("STRIPE_API_KEY", "")
    out: list[Result] = []
    if not key:
        out.append(Result("stripe", "Payments confirmed automatically", None, "no Stripe key",
                          "Stripe > Developers > API keys > Create restricted key: Read "
                          "on Checkout Sessions and Subscriptions."))
    elif key.startswith("sk_"):
        out.append(Result("stripe", "Payments confirmed automatically", False,
                          "this is a full secret key, which can move money",
                          "Make a restricted key (rk_...) with Read only, and paste that."))
    else:
        try:
            payments._stripe_get(key, "checkout/sessions", {"limit": 1})
            payments._stripe_get(key, "subscriptions", {"limit": 1})
            live = "_live_" in key
            out.append(Result("stripe", "Payments confirmed automatically", True,
                              "the key can read checkouts and subscriptions"
                              + ("" if live else " (this is a TEST key: real payments "
                                 "need the live one)")))
        except PermissionError as exc:
            out.append(Result("stripe", "Payments confirmed automatically", False, str(exc),
                              "Edit the restricted key: Read on Checkout Sessions and "
                              "Subscriptions."))
        except Exception as exc:  # noqa: BLE001
            out.append(Result("stripe", "Payments confirmed automatically", False,
                              f"{type(exc).__name__}: {exc}"[:160], "Check the key in Stripe."))
    for plan in ("starter", "growth"):
        link = payments.base_link(settings, plan)
        if not link:
            out.append(Result(f"link_{plan}", f"{plan.title()} payment link", None,
                              "not saved", "Stripe > Payment Links, then Keys and settings."))
            continue
        try:
            r = _get(link)
            out.append(Result(f"link_{plan}", f"{plan.title()} payment link",
                              r.status_code == 200, f"opens ({r.status_code})"
                              if r.status_code == 200 else f"returns {r.status_code}",
                              "" if r.status_code == 200 else
                              "Copy the link again from Stripe > Payment Links."))
        except Exception as exc:  # noqa: BLE001
            out.append(Result(f"link_{plan}", f"{plan.title()} payment link", False,
                              type(exc).__name__, "Copy the link again from Stripe."))
    portal = (getattr(settings, "billing_portal_link", "") or "").strip()
    if portal:
        try:
            r = _get(portal)
            out.append(Result("portal", "Customer portal link", r.status_code == 200,
                              f"opens ({r.status_code})",
                              "" if r.status_code == 200 else
                              "Stripe > Settings > Billing > Customer portal: copy the "
                              "login link again."))
        except Exception as exc:  # noqa: BLE001
            out.append(Result("portal", "Customer portal link", False, type(exc).__name__,
                              "Copy the portal login link again."))
    return out


def check_domain(settings) -> Result:
    from .mailer import check_dns_readiness

    domain = (settings.from_email or "").split("@")[-1]
    if not domain or "example" in domain:
        return Result("dns", "Email domain (SPF, DKIM, DMARC)", None, "no sending address set",
                      "Keys and settings, or answerrank.yml: from_email.")
    blockers = check_dns_readiness(domain, getattr(settings, "email_provider", ""))
    return Result("dns", "Email domain (SPF, DKIM, DMARC)", not blockers,
                  "passes" if not blockers else blockers[0],
                  "" if not blockers else "Desktop button > 3 Email domain: add what it "
                  "lists, then run this again. DKIM can take 1-3 days.")


def check_server(settings) -> list[Result]:
    site = (settings.website or "").rstrip("/")
    if not site or "example" in site or "localhost" in site:
        return [Result("server", "Your server", None, "no website address set",
                       "deploy/SERVER.md, then the setup file from the desktop button.")]
    out = []
    try:
        r = _get(f"{site}/unsubscribe")
        out.append(Result("unsubscribe", "Unsubscribe link (the law needs it working)",
                          r.status_code == 200, f"{site}/unsubscribe answers ({r.status_code})",
                          "" if r.status_code == 200 else "The server isn't serving the "
                          "site yet: check the A record and give it up to an hour."))
    except Exception as exc:  # noqa: BLE001
        out.append(Result("unsubscribe", "Unsubscribe link (the law needs it working)", False,
                          f"{site} isn't reachable ({type(exc).__name__})",
                          "Point your domain's A record at the server (deploy/SERVER.md)."))
        return out
    try:
        data = _get(f"{site}/health").json()
        out.append(Result("server", "Your server's agents", bool(data.get("fleet_active")),
                          "running" if data.get("fleet_active") else "the site answers but "
                          "the agents aren't running",
                          "" if data.get("fleet_active") else "Restart the server from its "
                          "control panel."))
    except Exception as exc:  # noqa: BLE001
        out.append(Result("server", "Your server's agents", False, type(exc).__name__,
                          "The site answered but /health didn't: restart the server."))
    return out


def check_heartbeat(settings) -> Result | None:
    url = (getattr(settings, "heartbeat_url", "") or "").strip()
    if not url:
        return Result("heartbeat", "Warning if the server stops", None, "not set up",
                      "Optional: a free check at healthchecks.io, then paste its ping "
                      "URL in Keys and settings.")
    try:
        r = _get(url, timeout=10)
        return Result("heartbeat", "Warning if the server stops", r.status_code == 200,
                      "pinged" if r.status_code == 200 else f"returns {r.status_code}",
                      "" if r.status_code == 200 else "Copy the ping URL again from "
                      "healthchecks.io.")
    except Exception as exc:  # noqa: BLE001
        return Result("heartbeat", "Warning if the server stops", False, type(exc).__name__,
                      "Copy the ping URL again from healthchecks.io.")


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------

def run(store, settings, say: Callable[[str], None] | None = None,
        wait_seconds: int = 90) -> dict:
    """Every check, in the order a day-one problem would appear. Results are
    remembered so the Autopilot checklist can show them."""
    say = say or (lambda _line: None)
    results: list[Result] = []
    steps = [
        ("your mailbox", lambda: check_mail_round_trip(settings, wait_seconds)),
        ("your email domain", lambda: [check_domain(settings)]),
        ("your server", lambda: check_server(settings)),
        ("a real AI check", lambda: [check_ai(settings)]),
        ("the business finder", lambda: [check_finder(store, settings)]),
        ("Stripe", lambda: check_stripe(settings)),
        ("the downtime warning", lambda: [check_heartbeat(settings)]),
    ]
    for label, step in steps:
        say(f"  Testing {label}…")
        try:
            got = [r for r in step() if r is not None]
        except Exception as exc:  # noqa: BLE001 - one broken check must not hide the rest
            got = [Result(label, label.capitalize(), False, f"{type(exc).__name__}: {exc}"[:160])]
        results += got
    failed = [r for r in results if r.ok is False]
    missing = [r for r in results if r.ok is None]
    summary = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "passed": not failed and not [r for r in missing if r.key not in {"heartbeat", "portal"}],
        "results": [asdict(r) for r in results],
        "failed": [r.name for r in failed],
        "missing": [r.name for r in missing],
    }
    if store is not None:
        store.kv_set("selftest.last", json.dumps(summary))
    return summary


def last(store) -> dict:
    try:
        return json.loads(store.kv_get("selftest.last") or "{}")
    except ValueError:
        return {}
