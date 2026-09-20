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

from . import auth
from .api import Api

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
        self.api = Api(self.store, self.settings)
        self.token = auth.get_or_create_token(self.store)

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

    # ------------------------------------------------------------ console

    def console(self, environ, start):
        body = render("console.html")
        headers = [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
        ]
        # First visit arrives with ?t=<token>; trade it for a cookie so the
        # token never sits in history, bookmarks or a shared screenshot.
        if _query(environ).get("t"):
            headers.append(("Set-Cookie", auth.session_cookie(self.token)))
        start("200 OK", headers)
        return [body]

    def manifest(self, environ, start):
        doc = {
            "name": f"{self.settings.brand} Console",
            "short_name": self.settings.brand,
            "start_url": "/app",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#0E1211",
            "theme_color": "#0E1211",
            "icons": [
                {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml",
                 "purpose": "any maskable"},
            ],
        }
        body = json.dumps(doc).encode()
        start("200 OK", [("Content-Type", "application/manifest+json"),
                         ("Content-Length", str(len(body)))])
        return [body]

    def icon(self, environ, start):
        letter = (self.settings.brand or "A")[0].upper()
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
            '<rect width="512" height="512" rx="108" fill="#0E1211"/>'
            '<circle cx="256" cy="256" r="150" fill="none" stroke="#1B93A8" stroke-width="26"/>'
            f'<text x="256" y="258" font-family="system-ui,sans-serif" font-size="176" '
            f'font-weight="700" fill="#EEF2F2" text-anchor="middle" '
            f'dominant-baseline="central">{letter}</text></svg>'
        ).encode()
        start("200 OK", [("Content-Type", "image/svg+xml"),
                         ("Content-Length", str(len(svg))),
                         ("Cache-Control", "max-age=86400")])
        return [svg]

    def service_worker(self, environ, start):
        # Deliberately minimal: the console must never show stale business
        # numbers, so nothing is cached except the shell for offline boot.
        js = (
            "self.addEventListener('install', function(e){ self.skipWaiting(); });\n"
            "self.addEventListener('activate', function(e){ e.waitUntil(clients.claim()); });\n"
            "self.addEventListener('fetch', function(e){});\n"
        ).encode()
        start("200 OK", [("Content-Type", "application/javascript"),
                         ("Content-Length", str(len(js))),
                         ("Cache-Control", "no-store")])
        return [js]

    # ------------------------------------------------------------ api

    def _json(self, start, payload, status="200 OK"):
        body = json.dumps(payload, default=str).encode()
        start(status, [("Content-Type", "application/json"),
                       ("Content-Length", str(len(body))),
                       ("Cache-Control", "no-store")])
        return [body]

    def _body_json(self, environ) -> dict:
        try:
            n = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            n = 0
        if not n:
            return {}
        try:
            return json.loads(environ["wsgi.input"].read(min(n, 256 * 1024)) or b"{}")
        except (ValueError, KeyError):
            return {}

    def api_state(self, environ, start):
        return self._json(start, self.api.state())

    def api_inbox(self, environ, start):
        q = _query(environ)
        return self._json(start, self.api.inbox(
            q.get("status", "drafted"), min(int(q.get("limit", 25) or 25), 100)))

    def api_prospects(self, environ, start):
        q = _query(environ)
        return self._json(start, self.api.prospects(
            q.get("stage") or None, min(int(q.get("limit", 40) or 40), 200)))

    def api_reports(self, environ, start):
        return self._json(start, self.api.reports())

    def api_telemetry(self, environ, start):
        return self._json(start, self.api.telemetry())

    def ops(self, environ, start):
        body = render("ops.html")
        headers = [("Content-Type", "text/html; charset=utf-8"),
                   ("Content-Length", str(len(body))),
                   ("Cache-Control", "no-store")]
        if _query(environ).get("t"):
            headers.append(("Set-Cookie", auth.session_cookie(self.token)))
        start("200 OK", headers)
        return [body]

    def api_approve(self, environ, start):
        ids = self._body_json(environ).get("ids") or []
        return self._json(start, self.api.approve([str(i) for i in ids]))

    def api_reject(self, environ, start):
        ids = self._body_json(environ).get("ids") or []
        return self._json(start, self.api.reject([str(i) for i in ids]))

    def api_send(self, environ, start):
        d = self._body_json(environ)
        return self._json(start, self.api.send(
            min(int(d.get("limit", 25)), 100), bool(d.get("dry_run"))))

    def api_tick(self, environ, start):
        return self._json(start, self.api.tick())

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
            "/app": self.console,
            "/manifest.webmanifest": self.manifest,
            "/icon.svg": self.icon,
            "/sw.js": self.service_worker,
            "/api/state": self.api_state,
            "/api/inbox": self.api_inbox,
            "/api/prospects": self.api_prospects,
            "/api/reports": self.api_reports,
            "/api/telemetry": self.api_telemetry,
            "/ops": self.ops,
            "/api/approve": self.api_approve,
            "/api/reject": self.api_reject,
            "/api/send": self.api_send,
            "/api/tick": self.api_tick,
        }

    def __call__(self, environ, start_response) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "/").rstrip("/") or "/"
        handler = self.routes.get(path)

        # Resolve first: an unknown path is a 404 regardless of credentials.
        if handler is None:
            body = render("notfound.html")
            return self._ok(start_response, body, status="404 Not Found")

        # Everything but the public site needs the console token. The console
        # can approve outreach and trigger sends, so an open port on a shared
        # network would be a real problem.
        if auth.requires_auth(path):
            presented = auth.presented_token(environ, _query(environ))
            if not auth.is_authorised(presented, self.token):
                if path.startswith("/api/"):
                    return self._json(start_response, {"error": "unauthorised"},
                                      "401 Unauthorized")
                body = render("locked.html")
                start_response("401 Unauthorized", [
                    ("Content-Type", "text/html; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                    ("Cache-Control", "no-store"),
                ])
                return [body]

        try:
            return handler(environ, start_response)
        except Exception:  # noqa: BLE001
            log.exception("unhandled error on %s", path)
            body = b"<h1>Something went wrong</h1>"
            start_response("500 Internal Server Error",
                           [("Content-Type", "text/html"), ("Content-Length", str(len(body)))])
            return [body]


def lan_ip() -> str:
    """The address the phone should use to reach this laptop.

    Opens a UDP socket toward a public address and reads back which local
    interface the routing table picked. No packets are sent — UDP connect is
    purely local — and it is far more reliable than parsing `ifconfig` or
    trusting the hostname, which often resolves to 127.0.0.1.
    """
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 8.8.8.8 is only a routing hint — UDP connect sends no packets and
        # needs no connectivity. (TEST-NET ranges are unsuitable: some hosts
        # sit on them, and then the socket returns that interface instead.)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        return ip if not ip.startswith("127.") else "127.0.0.1"
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def qr_or_url(url: str) -> str:
    """A scannable QR when the system can draw one, else the plain URL."""
    import shutil
    import subprocess

    if shutil.which("qrencode"):
        try:
            out = subprocess.run(["qrencode", "-t", "ANSIUTF8", "-m", "1", url],
                                 capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    return ""


def create_app(settings: Settings | None = None) -> Application:
    return Application(settings)


def serve(host: str = "0.0.0.0", port: int = 8000, settings: Settings | None = None) -> None:
    from wsgiref.simple_server import make_server

    app = create_app(settings)
    log.info("serving on http://%s:%s", host, port)
    make_server(host, port, app).serve_forever()
