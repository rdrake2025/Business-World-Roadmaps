"""Sending-domain setup: the exact records, and whether they are live yet.

This is the last thing standing between a working system and a business that
can actually earn, and it is the step most likely to be done wrong — not
because it is hard, but because the three records that matter are invisible
until mail is already in a spam folder.

Three things must be true before a single email goes out:

* **SPF** says which servers may send as your domain.
* **DKIM** cryptographically signs each message so it cannot be forged.
* **DMARC** tells receivers what to do when the first two fail, and since
  2026 a policy of ``p=none`` no longer satisfies Google, Yahoo or Microsoft.

Miss any one and 22-34% of mail is filtered or rejected outright. Get all
three right and compliant senders average around 89% inbox placement. There
is no partial credit and no way to recover a domain's reputation once it is
lost, which is why :func:`readiness` refuses rather than warns.

Lookups go over DNS-over-HTTPS rather than shelling out to ``dig``. The older
approach could not work on Windows at all — ``dig`` does not ship with it —
which silently blocked sending on the exact machine this system is run from.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field

DOH_ENDPOINTS = [
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
]


@dataclass(frozen=True)
class Record:
    """One row to paste into the registrar's DNS panel."""

    kind: str          #: TXT | MX | CNAME
    host: str          #: "@" for the domain itself
    value: str
    why: str
    priority: int | None = None   #: MX only

    def line(self) -> str:
        pri = f"  priority {self.priority}" if self.priority is not None else ""
        return f"{self.kind:<6} {self.host:<26} {self.value}{pri}"


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    monthly_cost: str
    spf_include: str
    #: DKIM selectors to check. Generated in the provider's admin console —
    #: we can verify one exists, we cannot invent the key for you.
    dkim_selectors: tuple[str, ...]
    mx: tuple[tuple[int, str], ...]
    smtp_host: str
    smtp_port: int
    imap_host: str
    daily_limit: int
    dkim_where: str
    app_password_where: str
    notes: tuple[str, ...] = ()


PROVIDERS: dict[str, Provider] = {
    "google": Provider(
        key="google", label="Google Workspace", monthly_cost="about $7/user/month",
        spf_include="include:_spf.google.com",
        dkim_selectors=("google",),
        mx=((1, "smtp.google.com"),),
        smtp_host="smtp.gmail.com", smtp_port=587, imap_host="imap.gmail.com",
        daily_limit=2000,
        dkim_where="Admin console → Apps → Google Workspace → Gmail → "
                   "Authenticate email → Generate new record (choose 2048-bit)",
        app_password_where="myaccount.google.com/apppasswords "
                           "(2-step verification must be on first)",
        notes=("The most forgiving option for a new sender: Gmail-to-Gmail "
               "delivery starts from a position of trust.",
               "You also get the inbox itself, which the Concierge can poll "
               "for replies."),
    ),
    "zoho": Provider(
        key="zoho", label="Zoho Mail", monthly_cost="about $1/user/month",
        spf_include="include:zoho.com",
        dkim_selectors=("zoho", "zmail"),
        mx=((10, "mx.zoho.com"), (20, "mx2.zoho.com"), (50, "mx3.zoho.com")),
        smtp_host="smtp.zoho.com", smtp_port=587, imap_host="imap.zoho.com",
        daily_limit=500,
        dkim_where="Zoho Mail admin → Domains → your domain → Email "
                   "Configuration → DKIM → Add selector",
        app_password_where="Zoho account → Security → App Passwords",
        notes=("The cheapest option that still gives real SMTP and IMAP.",
               "The free tier does NOT allow SMTP access — you need Mail Lite "
               "or above, or nothing will send.",
               "Pick your own DKIM selector; 'zoho' is the convention."),
    ),
    "microsoft": Provider(
        key="microsoft", label="Microsoft 365", monthly_cost="about $6/user/month",
        spf_include="include:spf.protection.outlook.com",
        dkim_selectors=("selector1", "selector2"),
        mx=((0, "<your-domain-key>.mail.protection.outlook.com"),),
        smtp_host="smtp.office365.com", smtp_port=587,
        imap_host="outlook.office365.com", daily_limit=2000,
        dkim_where="Microsoft 365 Defender → Policies → Email authentication "
                   "→ DKIM → enable for your domain (it gives you two CNAMEs)",
        app_password_where="Microsoft account → Security → App passwords "
                           "(requires MFA)",
        notes=("DKIM here is two CNAME records, not TXT.",
               "The MX hostname is specific to your tenant — Microsoft shows "
               "it during domain setup."),
    ),
    "fastmail": Provider(
        key="fastmail", label="Fastmail", monthly_cost="about $5/user/month",
        spf_include="include:spf.messagingengine.com",
        dkim_selectors=("fm1", "fm2", "fm3"),
        mx=((10, "in1-smtp.messagingengine.com"),
            (20, "in2-smtp.messagingengine.com")),
        smtp_host="smtp.fastmail.com", smtp_port=587, imap_host="imap.fastmail.com",
        daily_limit=2000,
        dkim_where="Fastmail → Settings → Domains → your domain "
                   "(it publishes three CNAMEs for you)",
        app_password_where="Fastmail → Settings → Privacy & Security → "
                           "App passwords",
        notes=("DKIM here is three CNAME records.",),
    ),
}

#: What we tell someone who has chosen something not on the list.
GENERIC_GUIDANCE = (
    "Your provider will give you an SPF include, a DKIM record and MX rows in "
    "its setup documentation. Add all three, then run this command again and "
    "it will verify them for you."
)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def _doh(name: str, rrtype: str, timeout: int = 12) -> list[str]:
    """Resolve over DNS-over-HTTPS. Works identically on every platform."""
    try:
        import requests
    except ImportError:
        return []
    for endpoint in DOH_ENDPOINTS:
        try:
            resp = requests.get(
                endpoint, params={"name": name, "type": rrtype},
                headers={"Accept": "application/dns-json"}, timeout=timeout)
            if resp.status_code != 200:
                continue
            answers = resp.json().get("Answer") or []
            out = []
            for a in answers:
                value = str(a.get("data", ""))
                # TXT answers arrive quoted, and long ones arrive in chunks.
                if rrtype == "TXT":
                    value = "".join(re.findall(r'"([^"]*)"', value)) or value
                out.append(value.strip())
            if out:
                return out
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return []


def _cli(name: str, rrtype: str) -> list[str]:
    """Fall back to whichever resolver the machine happens to have."""
    tool = next((t for t in ("dig", "nslookup") if shutil.which(t)), None)
    if not tool:
        return []
    cmd = ([tool, "+short", rrtype, name] if tool == "dig"
           else [tool, f"-type={rrtype}", name])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    if tool == "dig":
        return [line.strip().strip('"') for line in out.splitlines() if line.strip()]
    # nslookup prints  name  text = "value"
    found = re.findall(r'(?:text\s*=\s*)?"([^"]+)"', out)
    if not found and rrtype == "MX":
        found = re.findall(r"mail exchanger\s*=\s*(.+)", out)
    return [f.strip() for f in found]


def lookup(name: str, rrtype: str = "TXT") -> list[str]:
    """Every record of one type. DoH first, local resolver as a fallback."""
    return _doh(name, rrtype) or _cli(name, rrtype)


def dkim_key_is_real(record: str) -> bool:
    """Whether a DKIM TXT record carries an actual signing key.

    ``v=DKIM1; p=`` with nothing after it is not a configured key — under
    RFC 6376 an empty ``p`` means the key is *revoked*, and it is published
    deliberately, sometimes on a wildcard, to say "we sign nothing here".
    Accepting it would report a domain as authenticated while it sends
    unsigned mail, which is the single worst thing this check could do.
    """
    if "DKIM1" not in record:
        return False
    match = re.search(r"\bp\s*=\s*([A-Za-z0-9+/=]*)", record)
    if not match:
        return False
    # A 1024-bit RSA key is ~216 base64 characters; anything under 80 is not
    # a key, it is a placeholder.
    return len(match.group(1)) >= 80


# ---------------------------------------------------------------------------
# What to add
# ---------------------------------------------------------------------------

def records_for(domain: str, provider_key: str, reply_to: str = "") -> list[Record]:
    """The rows to paste into the registrar, in the order to paste them."""
    provider = PROVIDERS.get(provider_key)
    rua = reply_to or f"postmaster@{domain}"
    rows: list[Record] = []

    if provider:
        for priority, host in provider.mx:
            rows.append(Record("MX", "@", host, priority=priority,
                               why="Lets the domain receive mail, which is how "
                                   "replies reach you at all."))
        rows.append(Record(
            "TXT", "@", f"v=spf1 {provider.spf_include} ~all",
            why="SPF — says which servers may send as you. Exactly one SPF "
                "record per domain; if one already exists, merge the includes "
                "rather than adding a second."))
    else:
        rows.append(Record("TXT", "@", "v=spf1 include:<your provider> ~all",
                           why="SPF — your provider's documentation gives the "
                               "include to use."))

    selector = provider.dkim_selectors[0] if provider else "<selector>"
    rows.append(Record(
        "TXT", f"{selector}._domainkey",
        "<the long key your provider generates — paste it exactly>",
        why="DKIM — signs each message so it cannot be forged. This is the "
            "one record nobody can generate for you."))

    rows.append(Record(
        "TXT", "_dmarc",
        f"v=DMARC1; p=quarantine; rua=mailto:{rua}; adkim=s; aspf=s; pct=100",
        why="DMARC — tells receivers what to do when SPF or DKIM fail. "
            "p=none is no longer accepted for bulk sending; start at "
            "quarantine."))
    return rows


# ---------------------------------------------------------------------------
# Whether it is done
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    blocking: bool = True


@dataclass
class Readiness:
    domain: str
    provider: str
    signals: list[Signal] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return all(s.ok for s in self.signals if s.blocking)

    def blockers(self) -> list[str]:
        return [f"{s.name}: {s.detail}" + (f" — {s.fix}" if s.fix else "")
                for s in self.signals if s.blocking and not s.ok]


def readiness(domain: str, provider_key: str = "") -> Readiness:
    """Check the live DNS. Honest about what it could not determine."""
    result = Readiness(domain=domain, provider=provider_key)
    provider = PROVIDERS.get(provider_key)

    if not domain or "." not in domain or "yourdomain" in domain:
        result.signals.append(Signal(
            "Sending domain", False, "not configured",
            "Set from_email in answerrank.yml to an address on your own domain."))
        return result

    txt = lookup(domain, "TXT")
    reachable = bool(txt) or bool(lookup(domain, "A")) or bool(lookup(domain, "MX"))
    if not reachable:
        result.signals.append(Signal(
            "DNS lookup", False, f"could not resolve anything for {domain}",
            "Either the domain's nameservers are not live yet (allow an hour "
            "after purchase) or this machine has no outbound DNS."))
        return result

    # --- SPF ---
    spf = [t for t in txt if t.lower().startswith("v=spf1")]
    if not spf:
        result.signals.append(Signal(
            "SPF", False, f"no SPF record on {domain}",
            f'Add TXT @ = "v=spf1 '
            f'{provider.spf_include if provider else "include:<provider>"} ~all"'))
    elif len(spf) > 1:
        result.signals.append(Signal(
            "SPF", False, f"{len(spf)} SPF records — more than one is invalid",
            "Merge them into a single record. Receivers treat multiple SPF "
            "records as a permanent error and fail the check outright."))
    else:
        record = spf[0]
        if provider and provider.spf_include not in record:
            result.signals.append(Signal(
                "SPF", False,
                f"SPF exists but does not authorise {provider.label}",
                f"Add {provider.spf_include} to the existing record."))
        elif record.rstrip().endswith("+all"):
            result.signals.append(Signal(
                "SPF", False, "record ends in +all, which authorises anyone",
                "Change the ending to ~all or -all."))
        else:
            result.signals.append(Signal("SPF", True, record[:64]))

    # --- DKIM ---
    selectors = provider.dkim_selectors if provider else ("google", "zoho", "default",
                                                          "selector1", "fm1", "k1",
                                                          "mail", "s1")
    found_selector = ""
    revoked = False
    for selector in selectors:
        records = lookup(f"{selector}._domainkey.{domain}", "TXT")
        if any(dkim_key_is_real(r) for r in records):
            found_selector = selector
            break
        if any("DKIM1" in r for r in records):
            revoked = True
    if found_selector:
        result.signals.append(Signal("DKIM", True, f"published at {found_selector}._domainkey"))
    elif revoked:
        result.signals.append(Signal(
            "DKIM", False, "a DKIM record exists but carries no key",
            "An empty p= value means the key is revoked, so mail signed with "
            "it fails. Generate a real key and republish. "
            + (provider.dkim_where if provider else "")))
    else:
        result.signals.append(Signal(
            "DKIM", False, f"no key found (checked {', '.join(selectors)})",
            (provider.dkim_where if provider else
             "Generate the key in your provider's admin console, then publish "
             "it as the TXT record they give you.")))

    # --- DMARC ---
    dmarc = [t for t in lookup(f"_dmarc.{domain}", "TXT") if "v=DMARC1" in t]
    if not dmarc:
        result.signals.append(Signal(
            "DMARC", False, f"no record on _dmarc.{domain}",
            f'Add TXT _dmarc = "v=DMARC1; p=quarantine; '
            f'rua=mailto:postmaster@{domain}"'))
    else:
        policy = re.search(r"p\s*=\s*(\w+)", dmarc[0])
        value = (policy.group(1) if policy else "none").lower()
        if value == "none":
            result.signals.append(Signal(
                "DMARC", False, "policy is p=none, which no longer qualifies",
                "Change it to p=quarantine. Since 2026 Google, Yahoo and "
                "Microsoft treat p=none as unauthenticated for bulk senders."))
        else:
            result.signals.append(Signal("DMARC", True, f"p={value}"))

    # --- MX: not blocking to send, but without it no reply ever arrives ---
    mx = [m for m in lookup(domain, "MX") if m.strip().split()[-1] not in {".", ""}]
    if mx:
        result.signals.append(Signal("MX (receiving)", True, mx[0][:56], blocking=False))
    else:
        result.signals.append(Signal(
            "MX (receiving)", False, "no MX record — replies will bounce",
            "Add your provider's MX rows. Sending works without this; the "
            "replies you are sending *for* do not.", blocking=False))
    return result
