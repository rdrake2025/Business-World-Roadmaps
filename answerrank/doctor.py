"""Preflight diagnostics.

Answers one question: *what is stopping me from operating right now?*

Every check returns a status and, when it fails, the exact command or action
that fixes it. Checks marked BLOCKING are things that make sending unlawful
or guarantee it lands in spam — the system refuses to send while any of them
fail, so this is where you find out why.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import PROVIDER_ENV, Settings

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""
    blocking: bool = False

    @property
    def icon(self) -> str:
        return {PASS: "✓", WARN: "!", FAIL: "✗"}[self.status]


def check_python() -> Check:
    v = sys.version_info
    if v >= (3, 11):
        return Check("Python version", PASS, f"{v.major}.{v.minor}.{v.micro}")
    return Check("Python version", FAIL, f"{v.major}.{v.minor}", "Python 3.11+ required.")


def check_dependencies() -> Check:
    missing = []
    for mod, pkg in (("requests", "requests"), ("jinja2", "Jinja2"), ("yaml", "PyYAML")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return Check("Dependencies", PASS, "requests, jinja2, PyYAML")
    return Check("Dependencies", FAIL, f"missing {', '.join(missing)}",
                 "pip install -r requirements.txt")


def check_config(settings: Settings) -> Check:
    from .config import CONFIG_PROBLEMS

    path = Path("answerrank.yml")
    # A file that exists but will not parse is worse than no file: every
    # setting silently reverts to a default, including the sender identity.
    # Loading no longer crashes over it, so this is where it has to be said.
    if CONFIG_PROBLEMS:
        return Check("Config file", FAIL, CONFIG_PROBLEMS[0][:120],
                     "Fix the YAML (check indentation and quotes), then rerun "
                     "the doctor. Deleting it and running `python3 run.py init` "
                     "starts from a clean template.")
    if path.exists():
        return Check("Config file", PASS, str(path))
    return Check("Config file", WARN, "using built-in defaults",
                 "python3 run.py init   (then edit answerrank.yml)")


def check_address(settings: Settings) -> Check:
    from .keys import address_is_real
    addr = settings.physical_address or ""
    if address_is_real(addr):
        return Check("CAN-SPAM postal address", PASS, addr[:46], blocking=True)
    return Check(
        "CAN-SPAM postal address", FAIL, "not configured",
        "AnswerRank button → Keys and settings asks for it. Legally required in every "
        "commercial email. A USPS PO Box or virtual mailbox address works.",
        blocking=True)


def check_identity(settings: Settings) -> Check:
    problems = []
    if "@" not in settings.from_email or "yourdomain" in settings.from_email:
        problems.append("from_email")
    if not settings.website or "answerrank.io" in settings.website:
        problems.append("website")
    if not problems:
        return Check("Sender identity", PASS,
                     f"{settings.from_email} · {settings.website}", blocking=True)
    return Check("Sender identity", FAIL, f"placeholder values: {', '.join(problems)}",
                 "Set from_email and website in answerrank.yml to your real domain.",
                 blocking=True)


def check_engines(settings: Settings) -> Check:
    live = [n for n in settings.engines
            if os.environ.get(PROVIDER_ENV.get("serper" if n == "google_aio" else n, ""), "").strip()]
    if len(live) >= 2:
        return Check("AI engine keys", PASS, f"{len(live)} live: {', '.join(live)}")
    if live:
        return Check("AI engine keys", WARN, f"only {live[0]} configured",
                     "Two or more engines give a far more defensible score. "
                     "Export OPENAI_API_KEY / ANTHROPIC_API_KEY / PERPLEXITY_API_KEY / SERPER_API_KEY.")
    return Check("AI engine keys", WARN, "none — running in simulation mode",
                 "Simulation is fine for learning the system, but audits are not "
                 "real until you export at least one provider key.")


def check_database(settings: Settings) -> Check:
    try:
        from .store import Store
        store = Store(settings.database_path)
        counts = store.count_prospects_by_stage()
        total = sum(counts.values())
        return Check("Database", PASS,
                     f"{settings.database_path} ({total} prospects, MRR ${store.mrr():,.0f})")
    except Exception as exc:  # noqa: BLE001
        return Check("Database", FAIL, str(exc)[:70],
                     "Check the path in answerrank.yml is writable.")


def check_dns(settings: Settings) -> list[Check]:
    """SPF, DKIM, DMARC and MX, checked live against the sending domain.

    This previously checked SPF and DMARC only. A domain can pass both and
    still land in spam, because DKIM is the one of the three that actually
    proves a message was not forged — and it was never looked at.
    """
    from .dns_setup import readiness

    domain = settings.from_email.split("@")[-1] if "@" in settings.from_email else ""
    provider = getattr(settings, "email_provider", "") or ""
    result = readiness(domain, provider)
    return [
        Check(f"DNS · {s.name}", PASS if s.ok else FAIL, s.detail, s.fix,
              blocking=s.blocking)
        for s in result.signals
    ]


def check_unsubscribe(settings: Settings, probe: bool = False) -> Check:
    """The endpoint must be live and reachable before any send."""
    url = f"{settings.website.rstrip('/')}/unsubscribe"
    if not probe:
        return Check("Unsubscribe endpoint", WARN, f"not probed — expected at {url}",
                     "Run `python3 run.py doctor --probe` once the site is deployed, "
                     "or `python3 run.py web` to serve it locally.", blocking=True)
    try:
        import requests
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return Check("Unsubscribe endpoint", PASS, f"{url} → 200", blocking=True)
        return Check("Unsubscribe endpoint", FAIL, f"{url} → {resp.status_code}",
                     "Must return 200. Deploy the web app before sending.", blocking=True)
    except Exception as exc:  # noqa: BLE001
        return Check("Unsubscribe endpoint", FAIL, f"unreachable: {type(exc).__name__}",
                     f"{url} must work from the internet before anything is sent. "
                     f"See deploy/SERVER.md for the $6/month server setup.", blocking=True)


def check_smtp() -> Check:
    from .mailer import SMTPConfig
    cfg = SMTPConfig.from_env()
    if cfg.configured():
        return Check("SMTP", PASS, f"{cfg.host}:{cfg.port} as {cfg.username}")
    return Check("SMTP", WARN, "not configured — drafting only",
                 "Keys and settings (AnswerRank button, option 2) saves your "
                 "mailbox and app password. It tests them before saving.")


def check_inbox(probe: bool = False) -> Check:
    """Whether replies are read automatically, and whether the login works."""
    import os

    host = os.environ.get("IMAP_HOST", "")
    user = os.environ.get("IMAP_USERNAME") or os.environ.get("SMTP_USERNAME", "")
    pwd = os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD", "")
    if not host:
        return Check("Reading replies", WARN, "off — replies are pasted in by hand",
                     "Run Keys and settings (AnswerRank button, option 2) and answer yes to reading replies automatically.")
    if not (user and pwd):
        return Check("Reading replies", WARN, f"{host} set, but no mailbox login",
                     "Run Keys and settings (AnswerRank button, option 2) to add the mailbox and app password.")
    if not probe:
        return Check("Reading replies", PASS, f"{host} as {user} (not tested)")
    from .keys import test_imap
    problem = test_imap(host, user, pwd)
    if problem:
        return Check("Reading replies", FAIL, problem[:90], problem)
    return Check("Reading replies", PASS, f"{host} as {user}")


def check_payments(settings: Settings) -> Check:
    """Whether a yes can turn into money without a manual invoice."""
    import os

    links = {k: v for k, v in (settings.payment_links or {}).items() if v}
    key = os.environ.get("STRIPE_API_KEY", "")
    if not links:
        return Check("Payments", WARN, "no payment links — every sale needs a manual invoice",
                     "In Stripe, make a Payment Link per plan with a recurring monthly "
                     "price, then add them to answerrank.yml under payment_links.")
    missing = [p for p in ("starter", "growth", "managed") if p not in links]
    detail = f"links for {', '.join(sorted(links))}"
    if key.startswith("sk_"):
        return Check("Payments", WARN, detail + "; Stripe key is a full secret key",
                     "Replace it with a restricted read-only key (rk_...) in Keys and settings (AnswerRank button, option 2).")
    if not key:
        return Check("Payments", PASS, detail + "; tap Paid when money arrives",
                     "Optional: add a read-only Stripe key in Keys and settings (AnswerRank button, option 2) and payments are "
                     "confirmed automatically.")
    return Check("Payments", PASS, detail + ("; missing " + ", ".join(missing) if missing else "")
                 + "; confirmed automatically")


def check_budget() -> Check:
    if Path("budget.yml").exists():
        return Check("Personal budget", PASS, "budget.yml present")
    return Check("Personal budget", WARN, "not set up",
                 "python3 run.py budget-init   (then edit with your real numbers)")


def run_all(settings: Settings, probe: bool = False) -> list[Check]:
    checks = [
        check_python(),
        check_dependencies(),
        check_config(settings),
        check_database(settings),
        check_engines(settings),
        check_budget(),
        check_address(settings),
        check_identity(settings),
    ]
    checks.extend(check_dns(settings))
    checks.append(check_unsubscribe(settings, probe))
    checks.append(check_smtp())
    checks.append(check_inbox(probe))
    checks.append(check_payments(settings))
    return checks


def summarise(checks: list[Check]) -> tuple[int, int, int, list[Check]]:
    passed = sum(1 for c in checks if c.status == PASS)
    warned = sum(1 for c in checks if c.status == WARN)
    failed = sum(1 for c in checks if c.status == FAIL)
    blockers = [c for c in checks if c.blocking and c.status != PASS]
    return passed, warned, failed, blockers
