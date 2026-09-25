"""Where the passwords and API keys live.

Every outside service this business uses — the mailbox it sends from and
reads replies in, the AI engines, Stripe — is reached with a key. Until now
the only way to supply one was ``export SMTP_PASSWORD=...``, which is shell
syntax that does nothing in a Windows command window and is forgotten the
moment the window closes. On the machine this actually runs on, nothing
could be sent, no real audit could run, and no reply could be read.

So the keys live in one small file, ``keys.env``, next to ``answerrank.yml``.
It is never committed (see ``.gitignore``), it is read at startup, and it is
written by ``run.py keys`` (or KEYS.bat), which asks for each one in plain
language and tests the mailbox before saving. A real environment variable
still wins over the file, so a server can be configured the usual way.
"""

from __future__ import annotations

import getpass
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT

KEYS_FILE = ROOT / "keys.env"


@dataclass(frozen=True)
class Key:
    name: str
    label: str
    why: str
    secret: bool = True
    optional: bool = True


#: Every key the system reads, in the order the setup asks for them.
KEYS: tuple[Key, ...] = (
    Key("SMTP_HOST", "Mail server", "Filled in from your email provider.",
        secret=False, optional=False),
    Key("SMTP_PORT", "Mail server port", "Filled in from your email provider.",
        secret=False, optional=False),
    Key("SMTP_USERNAME", "Mailbox address", "The address you send from.",
        secret=False, optional=False),
    Key("SMTP_PASSWORD", "Mailbox app password",
        "A 16-character app password, not your normal password. Google: "
        "myaccount.google.com > Security > 2-Step Verification must be on, "
        "then App passwords.", optional=False),
    Key("IMAP_HOST", "Inbox server",
        "Lets the system read replies for you instead of you pasting them in. "
        "Uses the same mailbox and app password.", secret=False),
    Key("OPENAI_API_KEY", "OpenAI key", "Runs real ChatGPT checks. "
        "platform.openai.com > API keys."),
    Key("ANTHROPIC_API_KEY", "Anthropic key", "Runs real Claude checks. "
        "console.anthropic.com > API keys."),
    Key("PERPLEXITY_API_KEY", "Perplexity key", "Runs real Perplexity checks."),
    Key("SERPER_API_KEY", "Serper key", "Finds local businesses and reads "
        "Google's AI Overviews. serper.dev."),
    Key("STRIPE_API_KEY", "Stripe read-only key",
        "Lets the system see who has paid, so you don't have to tell it. "
        "Stripe > Developers > API keys > Create restricted key: Checkout "
        "Sessions = Read, Subscriptions = Read, everything else None. "
        "Starts with rk_."),
)

_LINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$")


def read(path: Path | str = KEYS_FILE) -> dict[str, str]:
    """The keys in the file, or nothing if there is no file."""
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        value = m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[m.group(1)] = value
    return out


def apply(path: Path | str = KEYS_FILE) -> list[str]:
    """Put the file's keys into the environment. A real environment variable
    is left alone — it was set on purpose, and it wins."""
    applied = []
    for name, value in read(path).items():
        if value and not os.environ.get(name):
            os.environ[name] = value
            applied.append(name)
    return applied


def write(values: dict[str, str], path: Path | str = KEYS_FILE) -> Path:
    """Save the keys, keeping any the file already had that were not given."""
    p = Path(path)
    merged = read(p)
    merged.update({k: v for k, v in values.items() if v is not None})
    lines = ["# AnswerRank keys. Private: never share this file or commit it.",
             "# Edit with `run.py keys` (or KEYS.bat) rather than by hand.", ""]
    known = [k.name for k in KEYS]
    for name in known + sorted(set(merged) - set(known)):
        if merged.get(name):
            lines.append(f"{name}={merged[name]}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        p.chmod(0o600)   # meaningful on a server; harmless on Windows
    except OSError:
        pass
    return p


def set_payment_links(links: dict[str, str], config_path: Path | str) -> Path:
    """Write the ``payment_links`` block of answerrank.yml, keeping every
    other line — and every comment — exactly as it was.

    Line-based on purpose: a YAML round-trip would strip the comments that
    explain the file, and hand-editing nested YAML is what broke the config
    the first time.
    """
    path = Path(config_path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    block = ["payment_links:"] + [f'  {plan}: "{url}"' for plan, url in links.items()]
    start = next((i for i, line in enumerate(lines)
                  if line.startswith("payment_links:")), None)
    if start is None:
        lines += [""] + block
    else:
        end = start + 1
        while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
            if not lines[end].strip() and end + 1 < len(lines) \
                    and not lines[end + 1].startswith((" ", "\t")):
                break
            end += 1
        lines[start:end] = block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_setting(name: str, value: str | list[str], config_path: Path | str) -> Path:
    """Set one top-level ``name: "value"`` (or ``name: ["a", "b"]``) line in
    answerrank.yml, keeping every other line exactly as it was (same
    reasoning as above)."""
    path = Path(config_path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if isinstance(value, list):
        line = f"{name}: [{', '.join(_quote(v) for v in value)}]"
    else:
        line = f"{name}: {_quote(value)}"
    at = next((i for i, existing in enumerate(lines)
               if re.match(rf"{re.escape(name)}\s*:", existing)), None)
    if at is None:
        lines += ["", line]
    else:
        lines[at] = line
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def address_is_real(address: str) -> bool:
    """The doctor's test, in one place: not the template, and long enough."""
    return bool(address) and "SET_YOUR" not in address and len(address) > 12


def masked(value: str) -> str:
    if not value:
        return "not set"
    return value[:3] + "…" + value[-2:] if len(value) > 8 else "set"


def test_smtp(host: str, port: int, user: str, password: str) -> str:
    """"" if the mailbox accepts the login, otherwise the reason in words."""
    import smtplib
    try:
        with smtplib.SMTP(host, int(port), timeout=20) as server:
            server.starttls()
            server.login(user, password)
        return ""
    except smtplib.SMTPAuthenticationError:
        return ("the mailbox refused the password. It must be an app password "
                "(with 2-Step Verification on), not your normal one.")
    except (smtplib.SMTPException, OSError) as exc:
        return f"could not reach {host}: {exc}"


def test_imap(host: str, user: str, password: str) -> str:
    import imaplib
    try:
        with imaplib.IMAP4_SSL(host, timeout=20) as box:
            box.login(user, password)
        return ""
    except imaplib.IMAP4.error:
        return ("the inbox refused the login. In Google Workspace an admin may "
                "need to allow IMAP: Admin console > Apps > Google Workspace > "
                "Gmail > End User Access > POP and IMAP access.")
    except OSError as exc:
        return f"could not reach {host}: {exc}"


def _ask_targets(settings, config_path: Path, ask, say) -> None:
    """The trade and cities the finder searches, and so the call list."""
    from . import knowledge
    from .agents.scout import parse_markets

    say("\n  What you sell and where. The system finds businesses there for your "
        "call list and emails.")
    now = list(getattr(settings, "trades", None) or [])
    while True:
        entered = ask(f"  Trade (e.g. hvac, plumbing, roofing; 'list' for all 22) "
                      f"[{', '.join(now) or 'all that fit your price'}]: ").strip().lower()
        if entered == "list":
            say("    " + ", ".join(knowledge.VERTICALS))
            continue
        break
    if entered:
        trades = [t.strip() for t in entered.replace(";", ",").split(",") if t.strip()]
        unknown = [t for t in trades if t not in knowledge.VERTICALS]
        if unknown:
            say(f"    Not a trade the system knows: {', '.join(unknown)}. Skipped. "
                f"Type 'list' to see them.")
        elif trades != now:
            set_setting("trades", trades, config_path)
            settings.trades = trades
    now = list(getattr(settings, "markets", None) or [])
    entered = ask(f"  Cities, up to 3, like: Waco, TX; Temple, TX "
                  f"[{'; '.join(now) or 'the default 12'}]: ").strip()
    if entered:
        markets = [f"{c}, {s}" for c, s in parse_markets(entered.split(";"))][:3]
        if not markets:
            say("    Couldn't read that. Use City, ST and separate cities with ;")
        elif markets != now:
            set_setting("markets", markets, config_path)
            settings.markets = markets


def interactive(settings, path: Path | str = KEYS_FILE,
                ask=input, ask_secret=getpass.getpass, say=print) -> int:
    """Ask for each key in plain language, test the mailbox, save.

    Pressing Enter keeps whatever is already saved, so this can be run again
    at any time to add one key without retyping the rest.
    """
    from .dns_setup import PROVIDERS

    have = read(path)
    say("\n  KEYS — saved privately in keys.env on this computer.")
    say("  Press Enter to keep what is already saved.\n")

    provider_key = (settings.email_provider or "").lower()
    if provider_key not in PROVIDERS:
        options = "/".join(PROVIDERS)
        answer = ask(f"  Which email provider is your mailbox with? ({options}) [google]: ")
        provider_key = (answer.strip().lower() or "google")
    provider = PROVIDERS.get(provider_key) or PROVIDERS["google"]

    values: dict[str, str] = {
        "SMTP_HOST": have.get("SMTP_HOST") or provider.smtp_host,
        "SMTP_PORT": have.get("SMTP_PORT") or str(provider.smtp_port),
    }
    default_user = have.get("SMTP_USERNAME") or settings.from_email
    user = ask(f"  Mailbox address [{default_user}]: ").strip() or default_user
    values["SMTP_USERNAME"] = user

    say(f"\n  App password: {provider.app_password_where}")
    pwd = ask_secret(f"  App password [{masked(have.get('SMTP_PASSWORD', ''))}]: ").strip()
    values["SMTP_PASSWORD"] = pwd.replace(" ", "") or have.get("SMTP_PASSWORD", "")

    read_inbox = ask("\n  Read replies automatically, so you never paste them in? "
                     "[Y/n]: ").strip().lower()
    values["IMAP_HOST"] = "" if read_inbox.startswith("n") else provider.imap_host

    for key in KEYS:
        if key.name.startswith(("SMTP_", "IMAP_")):
            continue
        say(f"\n  {key.label}: {key.why}")
        current = have.get(key.name, "")
        entered = (ask_secret if key.secret else ask)(
            f"  {key.label} [{masked(current)}] (Enter to skip): ").strip()
        values[key.name] = entered or current

    # Payment links and the postal address are not secret — every client sees
    # them — so they live in answerrank.yml, but they are asked for here so
    # that getting ready to send never means editing YAML by hand.
    from .config import DEFAULT_CONFIG_PATH
    config_path = Path(os.environ.get("ANSWERRANK_CONFIG") or DEFAULT_CONFIG_PATH)

    current_address = getattr(settings, "physical_address", "") or ""
    shown = current_address if address_is_real(current_address) else "not set"
    say("\n  Postal address: printed at the foot of every email — the law requires "
        "one. It does not have to be your home: a USPS PO Box or a virtual "
        "mailbox address works.")
    address = ask(f"  Postal address [{shown}]: ").strip()
    if address and not address_is_real(address):
        say("    That looks too short for a full address — street, city, state, "
            "ZIP. Skipped.")
    elif address and address != current_address:
        set_setting("physical_address", address, config_path)
        settings.physical_address = address
        say(f"  Address saved to {config_path.name}.")

    say("\n  For the call script: your first name, and the number a voicemail asks "
        "them to call back (a free Google Voice number keeps your own private).")
    for name, label in (("your_name", "Your first name"),
                        ("callback_phone", "Callback number")):
        now = getattr(settings, name, "") or ""
        entered = ask(f"  {label} [{now or 'not set'}]: ").strip()
        if entered and entered != now:
            set_setting(name, entered, config_path)
            setattr(settings, name, entered)

    _ask_targets(settings, config_path, ask, say)

    current_links = dict(getattr(settings, "payment_links", None) or {})
    say("\n  Stripe payment links (Stripe > Payment Links > New, with a recurring "
        "monthly price). Paste each one, or press Enter to skip.")
    links: dict[str, str] = {}
    for plan in ("starter", "growth", "managed"):
        price = settings.pricing.plan_price(plan)
        now = current_links.get(plan, "")
        entered = ask(f"  {plan.title()} (${price:,.0f}/mo) [{now or 'none'}]: ").strip()
        if entered and not entered.startswith("https://"):
            say("    That isn't a link — it should start with https://. Skipped.")
            entered = ""
        links[plan] = entered or now
    if any(links.values()) and links != current_links:
        set_payment_links(links, config_path)
        say(f"  Payment links saved to {config_path.name}.")

    if values.get("STRIPE_API_KEY", "").startswith("sk_"):
        say("\n  That is a full secret key. It can move money. Make a restricted "
            "read-only key instead (rk_...) — this system only needs to look.")
        values["STRIPE_API_KEY"] = have.get("STRIPE_API_KEY", "")

    say("\n  Testing the mailbox…")
    problem = ""
    if values["SMTP_PASSWORD"]:
        problem = test_smtp(values["SMTP_HOST"], int(values["SMTP_PORT"]),
                            values["SMTP_USERNAME"], values["SMTP_PASSWORD"])
        say("  ✓ Sending works." if not problem else f"  ✗ Sending: {problem}")
        if values["IMAP_HOST"]:
            imap_problem = test_imap(values["IMAP_HOST"], values["SMTP_USERNAME"],
                                     values["SMTP_PASSWORD"])
            say("  ✓ Reading replies works." if not imap_problem
                else f"  ✗ Reading replies: {imap_problem}")
    else:
        say("  No app password yet — nothing to test. Run this again once you have one.")

    saved = write(values, path)
    say(f"\n  Saved to {saved}. Keep this file private.")
    return 0 if not problem else 1
