"""Preflight diagnostics.

Answers one question: *what is stopping me from operating right now?*

Every check returns a status and, when it fails, the exact command or action
that fixes it. Checks marked BLOCKING are things that make sending unlawful
or guarantee it lands in spam — the system refuses to send while any of them
fail, so this is where you find out why.
"""

from __future__ import annotations

import os
import shutil
import subprocess
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


def _dig_txt(name: str) -> str:
    if not shutil.which("dig"):
        return ""
    try:
        out = subprocess.run(["dig", "+short", "TXT", name],
                             capture_output=True, text=True, timeout=10)
        return out.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


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
    path = Path("answerrank.yml")
    if path.exists():
        return Check("Config file", PASS, str(path))
    return Check("Config file", WARN, "using built-in defaults",
                 "python3 run.py init   (then edit answerrank.yml)")


def check_address(settings: Settings) -> Check:
    addr = settings.physical_address or ""
    if addr and "SET_YOUR" not in addr and len(addr) > 12:
        return Check("CAN-SPAM postal address", PASS, addr[:46], blocking=True)
    return Check(
        "CAN-SPAM postal address", FAIL, "not configured",
        "Set `physical_address` in answerrank.yml. Legally required in every "
        "commercial email. A registered agent address works.",
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
    domain = settings.from_email.split("@")[-1] if "@" in settings.from_email else ""
    if not domain or "yourdomain" in domain:
        return [Check("DNS (SPF/DKIM/DMARC)", FAIL, "no real sending domain configured",
                      "Set from_email to your sending domain first.", blocking=True)]
    if not shutil.which("dig"):
        return [Check("DNS (SPF/DKIM/DMARC)", WARN, "`dig` not available here",
                      f"Verify manually: dig +short TXT {domain} and "
                      f"dig +short TXT _dmarc.{domain}", blocking=True)]

    out = []
    spf = _dig_txt(domain)
    if "v=spf1" in spf:
        out.append(Check("SPF record", PASS, domain, blocking=True))
    else:
        out.append(Check("SPF record", FAIL, f"none on {domain}",
                         f'Add TXT @ → "v=spf1 include:_spf.google.com ~all"', blocking=True))

    dmarc = _dig_txt(f"_dmarc.{domain}").replace(" ", "")
    if "v=DMARC1" not in dmarc:
        out.append(Check("DMARC record", FAIL, f"none on _dmarc.{domain}",
                         'Add TXT _dmarc → "v=DMARC1; p=quarantine; rua=mailto:you@domain"',
                         blocking=True))
    elif "p=none" in dmarc:
        out.append(Check("DMARC policy", FAIL, "p=none is not sufficient in 2026",
                         "Change the DMARC policy to p=quarantine or p=reject.", blocking=True))
    else:
        policy = "reject" if "p=reject" in dmarc else "quarantine"
        out.append(Check("DMARC record", PASS, f"p={policy}", blocking=True))
    return out


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
                     f"Deploy the web app so {url} is publicly reachable.", blocking=True)


def check_smtp() -> Check:
    from .mailer import SMTPConfig
    cfg = SMTPConfig.from_env()
    if cfg.configured():
        return Check("SMTP", PASS, f"{cfg.host}:{cfg.port} as {cfg.username}")
    return Check("SMTP", WARN, "not configured — drafting only",
                 "Export SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD when ready to send.")


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
    return checks


def summarise(checks: list[Check]) -> tuple[int, int, int, list[Check]]:
    passed = sum(1 for c in checks if c.status == PASS)
    warned = sum(1 for c in checks if c.status == WARN)
    failed = sum(1 for c in checks if c.status == FAIL)
    blockers = [c for c in checks if c.blocking and c.status != PASS]
    return passed, warned, failed, blockers
