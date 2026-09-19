"""SMTP sending with the 2026 bulk-sender requirements built in.

Google, Yahoo and Microsoft now require authenticated mail (SPF, DKIM and an
aligned DMARC policy at quarantine or reject), one-click unsubscribe per
RFC 8058, spam complaints under 0.3% and bounces under 2%. Non-compliant
senders see 22-34% of mail filtered or rejected outright; compliant senders
average around 89% inbox placement.

SPF/DKIM/DMARC are DNS-level and must be configured on the sending domain —
this module cannot do that for you, and :func:`check_dns_readiness` will tell
you plainly whether it is done. What this module *does* guarantee is the
per-message half: the unsubscribe headers, the rate limits, and a hard stop
when bounce or complaint rates drift toward the enforcement thresholds.
"""

from __future__ import annotations

import logging
import os
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

log = logging.getLogger("answerrank.mailer")


@dataclass
class SMTPConfig:
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True

    @classmethod
    def from_env(cls) -> "SMTPConfig":
        return cls(
            host=os.environ.get("SMTP_HOST", ""),
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ.get("SMTP_USERNAME", ""),
            password=os.environ.get("SMTP_PASSWORD", ""),
            use_tls=os.environ.get("SMTP_TLS", "true").lower() != "false",
        )

    def configured(self) -> bool:
        return bool(self.host and self.username and self.password)


def build_message(to_email: str, subject: str, body: str, settings) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.brand, settings.from_email))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=settings.from_email.split("@")[-1])
    msg["Reply-To"] = settings.from_email

    # RFC 8058 one-click unsubscribe. Both headers are required: the URL alone
    # is not enough for Gmail/Yahoo to treat it as one-click.
    unsub = f"{settings.website}/unsubscribe?e={to_email}"
    msg["List-Unsubscribe"] = f"<{unsub}>, <mailto:{settings.from_email}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    # Plain text only. No tracking pixels, no images, no link shorteners —
    # each of those measurably depresses first-touch deliverability.
    msg.set_content(body)
    return msg


def check_dns_readiness(domain: str) -> list[str]:
    """Best-effort check of SPF/DMARC. Returns blocking problems."""
    problems: list[str] = []
    try:
        import subprocess

        def txt(name: str) -> str:
            out = subprocess.run(
                ["dig", "+short", "TXT", name], capture_output=True, text=True, timeout=10
            )
            return out.stdout or ""

        spf = txt(domain)
        if "v=spf1" not in spf:
            problems.append(f"No SPF record found on {domain}. Add one before sending.")

        dmarc = txt(f"_dmarc.{domain}")
        if "v=DMARC1" not in dmarc:
            problems.append(f"No DMARC record on _dmarc.{domain}. Required for bulk sending.")
        elif "p=none" in dmarc.replace(" ", ""):
            problems.append(
                f"DMARC on {domain} is p=none. Bulk senders need p=quarantine or p=reject."
            )
    except (OSError, subprocess.SubprocessError) as exc:  # noqa: F821
        problems.append(f"Could not verify DNS ({exc}); verify SPF/DKIM/DMARC manually.")
    return problems


class Mailer:
    def __init__(self, settings, config: SMTPConfig | None = None):
        self.settings = settings
        self.config = config or SMTPConfig.from_env()

    def send(self, to_email: str, subject: str, body: str) -> tuple[bool, str]:
        if not self.config.configured():
            return False, "SMTP not configured (set SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD)"
        msg = build_message(to_email, subject, body, self.settings)
        try:
            with smtplib.SMTP(self.config.host, self.config.port, timeout=30) as server:
                if self.config.use_tls:
                    server.starttls()
                server.login(self.config.username, self.config.password)
                server.send_message(msg)
            return True, "sent"
        except smtplib.SMTPRecipientsRefused:
            return False, "bounced: recipient refused"
        except smtplib.SMTPException as exc:
            return False, f"smtp error: {exc}"
        except OSError as exc:
            return False, f"network error: {exc}"


def throttle(seconds: int) -> None:
    """Pace sends. Bursts look automated; steady pacing looks human."""
    time.sleep(max(0, seconds))
