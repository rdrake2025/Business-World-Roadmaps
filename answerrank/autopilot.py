"""Is the business ready to run by itself? The answer, item by item.

Autopilot can be switched on at any time, but a business missing a piece
doesn't run by itself, it stalls somewhere quietly: no reply reader means
every "yes, send it" sits in a mailbox; no payment key means every payment
waits for someone to notice it. This lists each piece, whether it's there,
and the one thing to do if it isn't, in the order to do them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class Item:
    key: str
    label: str
    ok: bool
    detail: str
    fix: str = ""
    #: Needed for the business to run unattended. The rest make it better.
    required: bool = True


def _server(store, settings, probe: bool) -> Item:
    site = (settings.website or "").rstrip("/")
    label = "Running 24/7 on your server"
    fix = ("Follow deploy/SERVER.md: a $6/month server, the setup file from the "
           "desktop button (option 5), and one DNS record at your registrar.")
    if not site or "example" in site or "localhost" in site or "127.0.0.1" in site:
        return Item("server", label, False, "no website address set yet", fix)
    if not probe:
        return Item("server", label, False, f"not checked yet ({site})", fix)
    try:
        import requests
        data = requests.get(f"{site}/health", timeout=8).json()
    except Exception as exc:  # noqa: BLE001 - any failure means not reachable
        return Item("server", label, False, f"{site} isn't answering ({type(exc).__name__})",
                    fix)
    if not data.get("fleet_active"):
        return Item("server", label, False, f"{site} answers, but its agents aren't running",
                    "On the server's console, check the Fleet card; restarting the "
                    "server usually fixes it.")
    return Item("server", label, True, f"{site} is up and its agents are running")


def _dns(store, settings, probe: bool) -> Item:
    label = "Email domain set up (SPF, DKIM, DMARC)"
    fix = "Desktop button > 3 Email domain, and follow what it says until it's green."
    raw = store.kv_get("sender.dns")
    blockers = None
    if raw:
        try:
            blockers = json.loads(raw).get("blockers")
        except ValueError:
            blockers = None
    if blockers is None and probe:
        from .agents.sender import SenderAgent
        blockers = SenderAgent(store, settings)._dns_blockers()
    if blockers is None:
        return Item("dns", label, False, "not checked yet", fix)
    if blockers:
        return Item("dns", label, False, blockers[0], fix)
    return Item("dns", label, True, "passes the checks Gmail and Outlook apply")


def _live(store) -> Item:
    from . import selftest
    r = selftest.last(store)
    fix = ("Desktop button > 7, or Run the live test on this card. It sends one email "
           "to you and runs one real AI check, about 2 cents.")
    if not r:
        return Item("live", "Tested with your real accounts", False, "not run yet", fix)
    when = r.get("at", "")[:10]
    if r.get("passed"):
        return Item("live", "Tested with your real accounts", True, f"all working ({when})")
    first = (r.get("failed") or r.get("missing") or ["something"])[0]
    return Item("live", "Tested with your real accounts", False,
                f"{first} didn't pass ({when})", fix)


def _backup(store) -> Item:
    try:
        last = json.loads(store.kv_get("briefing.backup_last") or "{}")
    except ValueError:
        last = {}
    if not last:
        return Item("backup", "Weekly backup emailed to you", False,
                    "the first one goes out Sunday night",
                    "Nothing to do: it needs the mailbox, and arrives each Sunday.",
                    required=False)
    return Item("backup", "Weekly backup emailed to you", bool(last.get("ok")),
                f"{last.get('detail', '')} ({last.get('at', '')[:10]})",
                "" if last.get("ok") else "Check the mailbox works (desktop button, 7).",
                required=False)


def _budget(settings) -> Item:
    from . import costs
    e = costs.estimate(settings)
    label = costs.PRESETS.get(e["preset"], {}).get("label", "Custom")
    return Item("budget", "Budget chosen", True,
                f"{label}: {e['checks_per_day']} businesses a day, about "
                f"${e['total']:,.0f} a month before clients",
                "Keys and settings asks: Lean, Standard or Growth.", required=False)


def readiness(store, settings, probe: bool = False) -> dict:
    """Every piece Autopilot needs, and whether it's in place."""
    import os

    from . import automation, payments
    from .agents.concierge import ConciergeAgent
    from .mailer import SMTPConfig

    keys = "Desktop button > 2 Keys and settings"
    smtp = SMTPConfig.from_env().configured()
    address = (settings.physical_address or "").strip()
    links = [p for p in ("starter", "growth") if payments.base_link(settings, p)]
    stripe = os.environ.get("STRIPE_API_KEY", "")
    engines = [p for p in ("openai", "perplexity", "anthropic") if settings.api_key(p)]
    supervised = automation.supervised(store)
    need = automation.SUPERVISED_FIRST_EMAILS

    items = [
        Item("demo", "Real mode (not the demo)", not getattr(settings, "demo_mode", False),
             "demo mode is on: nothing real is checked or sent"
             if getattr(settings, "demo_mode", False) else "real mode",
             "Real mode is the default; this is the practice-run setting. Take the "
             "line demo_mode: true out of answerrank.yml (and ANSWERRANK_DEMO out of "
             "keys.env if it's there)."),
        _server(store, settings, probe),
        Item("mailbox", "Mailbox connected (sends your email)", smtp,
             "saved and tested" if smtp else "no mailbox saved",
             f"{keys}: your Google Workspace address and an app password."),
        Item("replies", "Replies read automatically",
             ConciergeAgent(store, settings)._imap_config() is not None,
             "reading your inbox every half hour"
             if ConciergeAgent(store, settings)._imap_config() else "off",
             f"{keys}: answer yes to reading replies automatically."),
        _dns(store, settings, probe),
        Item("address", "Postal address in every email",
             bool(address) and "SET_YOUR" not in address,
             address or "missing", f"{keys}: a PO box or virtual mailbox is fine."),
        Item("engines", "AI answer engine key (real checks)", bool(engines),
             ", ".join(engines) if engines else "none saved",
             f"{keys}: an OpenAI key (platform.openai.com), about $30-60 a month."),
        Item("finder", "Business finder key (new prospects)", bool(settings.api_key("serper")),
             "Serper saved" if settings.api_key("serper") else "none saved",
             f"{keys}: a Serper key (serper.dev; 2,500 free searches, then $50 "
             f"for 50,000)."),
        Item("links", "Payment links (Starter and Growth)", len(links) == 2,
             ", ".join(links) if links else "none",
             "Stripe > Payment Links: one per plan, recurring monthly, then paste "
             "them in Keys and settings."),
        Item("stripe", "Payments confirmed automatically", stripe.startswith("rk_"),
             "read-only key saved" if stripe.startswith("rk_") else
             ("a full secret key: swap it for a restricted one" if stripe else "no key"),
             "Stripe > Developers > API keys > Create restricted key: Read on "
             "Checkout Sessions and Subscriptions. Paste it in Keys and settings."),
        Item("portal", "Clients manage billing themselves",
             bool((getattr(settings, "billing_portal_link", "") or "").strip()),
             "customer portal link saved"
             if getattr(settings, "billing_portal_link", "") else "no portal link",
             "Stripe > Settings > Billing > Customer portal > Activate; copy the "
             "link into Keys and settings.", required=False),
        Item("booking", "Booking link for people who want a call",
             bool((getattr(settings, "booking_link", "") or "").strip()),
             "saved" if getattr(settings, "booking_link", "") else "none",
             "Optional: Google Calendar > Create > Appointment schedule, then paste "
             "the link in Keys and settings.", required=False),
        _live(store),
        Item("heartbeat", "Warning if the server stops",
             bool((getattr(settings, "heartbeat_url", "") or "").strip()),
             "healthchecks.io is watching" if getattr(settings, "heartbeat_url", "")
             else "not set up",
             "Free: healthchecks.io > Add Check (period 30 min, grace 30 min), then "
             "paste its ping URL in Keys and settings.", required=False),
        _backup(store),
        _budget(settings),
        Item("supervised", f"You've read the first {need} first emails",
             supervised >= need, f"{min(supervised, need)} of {need}",
             "Approve first emails in the phone's review screen as they arrive; "
             "Autopilot writes them alone after that. About two days."),
    ]
    required = [i for i in items if i.required]
    paused = {stage: automation.paused(store, stage) for stage in automation.STAGES
              if automation.paused(store, stage)}
    return {
        "on": automation.enabled(store, "autopilot"),
        "ready": all(i.ok for i in required),
        "done": sum(1 for i in required if i.ok),
        "total": len(required),
        "items": [asdict(i) for i in items],
        "next": next((asdict(i) for i in items if i.required and not i.ok), None),
        "paused": paused,
        "stages": automation.STAGES,
        "guardian": json.loads(store.kv_get("guardian.last") or "{}"),
    }


def cached(store, settings) -> dict:
    """Readiness with the network checks, at most once every ten minutes."""
    raw = store.kv_get("autopilot.readiness") or ""
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    fresh = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
    if data.get("at", "") >= fresh:
        probed = {i["key"]: i for i in data.get("items", []) if i["key"] in {"server", "dns"}}
        now = readiness(store, settings, probe=False)
        now["items"] = [probed.get(i["key"], i) for i in now["items"]]
        required = [i for i in now["items"] if i["required"]]
        now.update(ready=all(i["ok"] for i in required),
                   done=sum(1 for i in required if i["ok"]),
                   next=next((i for i in required if not i["ok"]), None))
        return now
    out = readiness(store, settings, probe=True)
    store.kv_set("autopilot.readiness", json.dumps(
        {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **out}))
    return out
