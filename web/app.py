"""The public web surface: landing page, lead capture, and unsubscribe.

Built as a plain WSGI app on the standard library so it runs anywhere — the
laptop during Phase 0, a $6 VPS later, or any free tier that speaks WSGI —
with no framework to keep current.

The unsubscribe endpoint is the reason this exists. Until it is live and
reachable, sending a single cold email is unlawful under CAN-SPAM and will
fail the 2026 one-click requirement from Google, Yahoo and Microsoft. It
writes to the same suppression table the outreach agent checks before every
send, so an opt-out takes effect immediately rather than within the ten
business days the law allows.
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Iterable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from answerrank.config import SETTINGS, Settings
from answerrank.models import Business, Prospect
from answerrank.store import Store

log = logging.getLogger("answerrank.web")

TEMPLATES = Path(__file__).resolve().parent / "templates"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)


def render(name: str, **ctx: Any) -> bytes:
    ctx.setdefault("brand", SETTINGS.brand)
    ctx.setdefault("website", SETTINGS.website)
    ctx.setdefault("company", SETTINGS.company_legal_name)
    ctx.setdefault("address", SETTINGS.physical_address)
    ctx.setdefault("contact_email", SETTINGS.from_email)
    ctx.setdefault("pricing", SETTINGS.pricing)
    return _env.get_template(name).render(**ctx).encode("utf-8")


def _form(environ: dict[str, Any]) -> dict[str, str]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    # Cap the body: an unbounded read is a trivial memory exhaustion vector.
    body = environ["wsgi.input"].read(min(length, 64 * 1024)).decode("utf-8", "replace")
    return {k: v[0] for k, v in urllib.parse.parse_qs(body).items() if v}


def _query(environ: dict[str, Any]) -> dict[str, str]:
    return {k: v[0] for k, v in
            urllib.parse.parse_qs(environ.get("QUERY_STRING", "")).items() if v}


class Application:
    def __init__(self, settings: Settings | None = None, store: Store | None = None):
        self.settings = settings or SETTINGS
        self.store = store or Store(self.settings.database_path)

    # ------------------------------------------------------------------ routes

    def landing(self, environ, start):
        return self._ok(start, render("landing.html"))

    def privacy(self, environ, start):
        return self._ok(start, render("privacy.html"))

    def terms(self, environ, start):
        return self._ok(start, render("terms.html"))

    def health(self, environ, start):
        start("200 OK", [("Content-Type", "application/json")])
        return [json.dumps({"status": "ok", "brand": self.settings.brand}).encode()]

    def unsubscribe(self, environ, start):
        """GET shows a confirmation page; POST performs the opt-out.

        Mail clients implementing RFC 8058 POST here with a
        ``List-Unsubscribe=One-Click`` body and expect a 2xx with no
        interaction. A human clicking the link gets the same result through
        the form. Both paths converge on the same suppression write.
        """
        method = environ.get("REQUEST_METHOD", "GET").upper()

        if method == "GET":
            email = _query(environ).get("e", "")
            return self._ok(start, render("unsubscribe.html", email=email, done=False))

        data = _form(environ)
        email = (data.get("email") or _query(environ).get("e") or "").strip().lower()
        one_click = data.get("List-Unsubscribe") == "One-Click"

        if email and EMAIL_RE.match(email):
            self.store.suppress(email, "unsubscribed via web")
            log.info("suppressed %s", email)
            # Also stop any sequence already queued for this address.
            self._halt_sequence(email)
        elif one_click:
            # A one-click POST without a usable address still must not error;
            # the sender is told to stop, and we have nothing to key on.
            log.warning("one-click unsubscribe with no resolvable address")

        if one_click:
            start("200 OK", [("Content-Type", "text/plain")])
            return [b"Unsubscribed."]
        return self._ok(start, render("unsubscribe.html", email=email, done=True))

    def audit_request(self, environ, start):
        """Inbound lead capture from the landing page."""
        if environ.get("REQUEST_METHOD", "GET").upper() != "POST":
            return self._redirect(start, "/")

        d = _form(environ)
        email = (d.get("email") or "").strip().lower()
        name = (d.get("business") or "").strip()
        city = (d.get("city") or "").strip()

        if not (name and city and EMAIL_RE.match(email)):
            return self._ok(start, render(
                "landing.html",
                error="Please provide a business name, city, and a valid email."), status="400 Bad Request")

        biz = Business(
            name=name, city=city, state=(d.get("state") or "").strip(),
            vertical=(d.get("vertical") or "home_services").strip(),
            website=(d.get("website") or "").strip(), email=email,
        )
        # Inbound leads jump the queue: they asked, so they are worth auditing
        # before any cold prospect.
        self.store.upsert_prospect(Prospect(
            business=biz, stage="discovered",
            notes="INBOUND — requested audit from website",
        ))
        log.info("inbound lead: %s (%s)", name, city)
        return self._ok(start, render("thanks.html", business=name))

    # ------------------------------------------------------------------ helpers

    def _halt_sequence(self, email: str) -> None:
        """Mark any queued message for this address as suppressed."""
        try:
            by_id = {p.id: p for p in self.store.get_prospects(limit=10_000)
                     if p.business.email.lower() == email}
            if not by_id:
                return
            for msg in self.store.get_messages(limit=10_000):
                if msg.prospect_id in by_id and msg.status in {"drafted", "approved"}:
                    msg.status = "suppressed"
                    self.store.save_message(msg)
            for prospect in by_id.values():
                prospect.stage = "suppressed"
                self.store.upsert_prospect(prospect)
        except Exception:  # noqa: BLE001 - opt-out must never fail
            log.exception("could not halt sequence for %s", email)

    def _ok(self, start, body: bytes, status: str = "200 OK"):
        start(status, [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ])
        return [body]

    def _redirect(self, start, location: str):
        start("302 Found", [("Location", location)])
        return [b""]

    # ------------------------------------------------------------------ wsgi

    @property
    def routes(self) -> dict[str, Callable]:
        return {
            "/": self.landing,
            "/unsubscribe": self.unsubscribe,
            "/audit-request": self.audit_request,
            "/privacy": self.privacy,
            "/terms": self.terms,
            "/health": self.health,
        }

    def __call__(self, environ, start_response) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "/").rstrip("/") or "/"
        handler = self.routes.get(path)
        if handler is None:
            body = render("notfound.html")
            return self._ok(start_response, body, status="404 Not Found")
        try:
            return handler(environ, start_response)
        except Exception:  # noqa: BLE001
            log.exception("unhandled error on %s", path)
            body = b"<h1>Something went wrong</h1>"
            start_response("500 Internal Server Error",
                           [("Content-Type", "text/html"), ("Content-Length", str(len(body)))])
            return [body]


def create_app(settings: Settings | None = None) -> Application:
    return Application(settings)


def serve(host: str = "0.0.0.0", port: int = 8000, settings: Settings | None = None) -> None:
    from wsgiref.simple_server import make_server

    app = create_app(settings)
    log.info("serving on http://%s:%s", host, port)
    make_server(host, port, app).serve_forever()
