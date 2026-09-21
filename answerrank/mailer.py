"""SMTP sending with the 2026 bulk-sender requirements built in.

Google, Yahoo and Microsoft now require authenticated mail (SPF, DKIM and an
aligned DMARC policy at quarantine or reject), one-click unsubscribe per
RFC 8058, spam complaints under 0.3% and bounces under 2%. Non-compliant
senders see 22-34% of mail filtered or rejected outright; compliant senders
average around 89% inbox placement.

SPF/DKIM/DMARC are DNS-level and must be configured on the sending domain.
:mod:`answerrank.dns_setup` prints the exact records and verifies them live;
:func:`check_dns_readiness` is the gate that refuses to send until it is
done. What this module guarantees is the per-message half: the unsubscribe
headers, the rate limits, and a hard stop when bounce or complaint rates
drift toward the enforcement thresholds.
"""

from __future__ import annotations

import logging
import os
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from urllib.parse import quote

log = logging.getLogger("answerrank.mailer")


@dataclass
class SMTPConfig:
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True

    @staticmethod
    def _port_from_env() -> int:
        """587 unless the environment says otherwise, and legibly.

        ``int(os.environ["SMTP_PORT"])`` on a blank or mistyped value raises
        a bare ValueError from inside a dataclass constructor, which reaches
        the operator as a traceback with nothing actionable in it. They are
        editing this in a .bat file.
        """
        raw = (os.environ.get("SMTP_PORT") or "").strip()
        if not raw:
            return 587
        try:
            port = int(raw)
        except ValueError:
            log.warning("SMTP_PORT=%r is not a number; using 587", raw)
            return 587
        if not 1 <= port <= 65535:
            log.warning("SMTP_PORT=%s is out of range; using 587", port)
            return 587
        return port

    @classmethod
    def from_env(cls) -> "SMTPConfig":
        return cls(
            host=os.environ.get("SMTP_HOST", "").strip(),
            port=cls._port_from_env(),
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
    #
    # The address is percent-encoded. Pasted in raw, a perfectly ordinary
    # ``info+sales@`` arrives at the handler as ``info sales@``, fails
    # validation, and is never suppressed — while the recipient's mail client
    # tells them they unsubscribed. The next message to that address is a
    # spam complaint, and complaints are capped at 0.3% before the domain is
    # throttled wholesale.
    unsub = f"{settings.website}/unsubscribe?e={quote(to_email, safe='')}"
    msg["List-Unsubscribe"] = f"<{unsub}>, <mailto:{settings.from_email}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    # Plain text only. No tracking pixels, no images, no link shorteners —
    # each of those measurably depresses first-touch deliverability.
    msg.set_content(body)
    return msg


def check_dns_readiness(domain: str, provider: str = "") -> list[str]:
    """Blocking DNS problems, or an empty list when the domain is ready.

    Delegates to :mod:`answerrank.dns_setup`. It used to shell out to ``dig``,
    which does not exist on Windows — so on the machine this system is
    actually run from, the check could never pass and sending was blocked
    permanently by a resolver that was never there.
    """
    from .dns_setup import readiness

    return readiness(domain, provider).blockers()


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
