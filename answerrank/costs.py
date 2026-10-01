"""What the business costs to run each month, worked out from its settings.

Every figure the guides quote comes from here, so a price change in one
place ("ENGINE_COST" in audit.py, the plan prices, the settings) moves them
all. The inputs are the providers' own pricing pages (see evidence.py:
openai_search_pricing, serper_pricing, workspace_pricing, gcp_free_tier).

The one dial that matters is how many new businesses are checked a day.
Everything else is fixed or scales with clients, who pay for themselves
many times over.
"""

from __future__ import annotations

from dataclasses import dataclass

#: How many businesses to check a day, and when the Guardian speaks up
#: about AI spend. Chosen in Keys and settings.
PRESETS = {
    "lean": {"teaser_audits_per_day": 5, "api_budget_monthly": 20.0,
             "label": "Lean", "explain": "5 businesses checked a day, so a few "
             "first emails a day. Slower to find clients; the cheapest way to "
             "start, and one tap to change later."},
    "standard": {"teaser_audits_per_day": 20, "api_budget_monthly": 50.0,
                 "label": "Standard", "explain": "20 a day: keeps the warm-up's "
                 "sending and a morning of calls supplied."},
    "growth": {"teaser_audits_per_day": 40, "api_budget_monthly": 100.0,
               "label": "Growth", "explain": "40 a day: for full sending volume "
               "once the domain is warmed up and replies are coming in."},
}

WORKSPACE = 8.40      #: Business Starter, flexible plan, one mailbox
DOMAIN = 1.00         #: about $12 a year
SERVERS = {"digitalocean": 6.00, "gcp_free": 0.00}
#: Serper after the 2,500 free searches: $50 per 50,000.
SERPER_PER_QUERY = 0.001
SERPER_FREE = 2500
DAYS = 30


@dataclass
class Line:
    label: str
    monthly: float
    note: str = ""


def preset_for(settings) -> str:
    """Which preset these settings match, or "custom"."""
    per_day = int(getattr(settings, "teaser_audits_per_day", 20))
    for key, p in PRESETS.items():
        if p["teaser_audits_per_day"] == per_day:
            return key
    return "custom"


def fixed_monthly(settings, sending: bool | None = None) -> dict[str, float]:
    """What the business pays each month whether or not anyone signs.

    Only what is in use. With no mailbox nothing can be sent, so there is no
    mailbox to pay for and no server needed for unsubscribe links: the $5
    pilot path (PILOTS.md) costs nothing a month. The Bookkeeper used to book
    a flat $138 of "tooling" and "software" the plan never buys, so the
    dashboard showed a $139 monthly loss on a business that had spent 90
    cents. AI checks are booked as they happen, never here.
    """
    if sending is None:
        from .mailer import SMTPConfig
        sending = SMTPConfig.from_env().configured()
    if not sending:
        return {}
    server = getattr(settings, "server_host", "") or "digitalocean"
    return {k: v for k, v in (("mailbox", WORKSPACE), ("server", SERVERS.get(server, 6.0)),
                              ("domain", DOMAIN)) if v}


def check_costs(settings) -> tuple[float, int]:
    """(AI engine cost, Serper searches) for one free check of a prospect."""
    from .audit import DEPTHS, ENGINE_COST

    engines = [e for e in (getattr(settings, "teaser_engines", None) or ["openai"])]
    prompts = DEPTHS["teaser"]
    ai = sum(ENGINE_COST.get(e, 0.01) for e in engines if e != "google_aio") * prompts
    serper = prompts if "google_aio" in engines else 0
    return round(ai, 4), serper


def client_audit_cost(settings) -> float:
    """One client's monthly full audit, on every engine, asked several times."""
    from .audit import DEPTHS, ENGINE_COST

    engines = [e for e in getattr(settings, "engines", None) or ENGINE_COST if e != "mock"]
    repeats = max(1, int(getattr(settings, "probe_repeats", 1)))
    return round(sum(ENGINE_COST.get(e, 0.01) for e in engines) * DEPTHS["full"] * repeats, 2)


def estimate(settings, clients: int = 0, server: str | None = None,
             checks_per_day: int | None = None) -> dict:
    """The month, line by line, before and after clients."""
    server = server or getattr(settings, "server_host", "") or "digitalocean"
    per_day = int(checks_per_day if checks_per_day is not None
                  else getattr(settings, "teaser_audits_per_day", 20))
    ai_each, serper_each = check_costs(settings)
    checks = per_day * DAYS
    # The finder runs four times a day and stops after two or three searches
    # once it has enough new businesses.
    serper_queries = checks * serper_each + DAYS * 4 * 3
    # The Explorer re-measures each candidate trade once a month, a handful
    # of real businesses each, plus a local search to find them.
    from . import markets
    from .agents.explorer import REVISIT_DAYS, SAMPLE_SIZE
    explored = len(markets.CANDIDATES) * DAYS / REVISIT_DAYS
    serper_queries += round(explored * (SAMPLE_SIZE * serper_each + 3))
    lines = [
        Line("Mailbox (Google Workspace)", WORKSPACE, "one mailbox, month to month"),
        Line("Server", SERVERS.get(server, 6.0),
             "Google Cloud free tier" if server == "gcp_free" else "DigitalOcean"),
        Line("AI checks of new businesses", round(checks * ai_each, 2),
             f"{per_day} a day at about {ai_each * 100:.0f} cents each"),
        Line("Market research", round(explored * SAMPLE_SIZE * ai_each, 2),
             f"{len(markets.CANDIDATES)} possible new trades re-checked once a month, "
             f"{SAMPLE_SIZE} businesses each"),
        Line("Business finder (Serper)", round(serper_queries * SERPER_PER_QUERY, 2),
             f"about {serper_queries:,} searches a month; nothing until the first "
             f"{SERPER_FREE:,} free ones are used"),
        Line("Domain", DOMAIN, "you already have it"),
    ]
    if clients:
        lines.append(Line(f"Client audits ({clients})",
                          round(clients * client_audit_cost(settings), 2),
                          f"about ${client_audit_cost(settings):.2f} each a month"))
    total = round(sum(line.monthly for line in lines), 2)
    return {"lines": [line.__dict__ for line in lines], "total": total,
            "checks_per_day": per_day, "preset": preset_for(settings),
            "per_check": ai_each}


def table(settings, server: str | None = None) -> list[dict]:
    """Every preset side by side, for the budget question."""
    out = []
    for key, p in PRESETS.items():
        e = estimate(settings, server=server, checks_per_day=p["teaser_audits_per_day"])
        out.append({"key": key, "label": p["label"], "explain": p["explain"],
                    "per_day": p["teaser_audits_per_day"], "total": e["total"]})
    return out
