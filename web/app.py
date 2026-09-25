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
import socketserver
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Iterable
from wsgiref.simple_server import WSGIServer, make_server

from jinja2 import Environment, FileSystemLoader, select_autoescape

from answerrank.config import SETTINGS, Settings
from answerrank.models import Business, Prospect
from answerrank.store import Store

from . import auth
from .api import Api, to_json

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


def _int(raw: Any, default: int, lo: int = 1, hi: int = 1000) -> int:
    """A bounded integer from untrusted input.

    Two problems this closes. ``int("twenty")`` raised straight out of the
    handler, and a negative limit reaches SQLite as ``LIMIT -1``, which
    means no limit at all — the exact opposite of what the caller asked for.
    """
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


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
        """Public. Also answers "is a fleet already running this business?" —
        see ``cli._fleet_elsewhere`` — so it says which copy it is and whether
        agents are active, and nothing else."""
        body = json.dumps({"status": "ok", "brand": self.settings.brand,
                           "app": "answerrank",
                           "instance": self.store.instance_id(),
                           "fleet_active": self.store.fleet_active()}).encode()
        start("200 OK", [("Content-Type", "application/json"),
                         ("Content-Length", str(len(body))),
                         ("Cache-Control", "no-store")])
        return [body]

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
        from answerrank import knowledge
        body = render("console.html", trades=[(key, knowledge.get(key).label)
                                              for key in knowledge.VERTICALS])
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
        body = to_json(payload)
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
            q.get("status", "drafted"), _int(q.get("limit"), 25, 1, 100)))

    def api_prospects(self, environ, start):
        q = _query(environ)
        return self._json(start, self.api.prospects(
            q.get("stage") or None, _int(q.get("limit"), 40, 1, 200),
            hot=q.get("hot") in {"1", "true", "yes"}, q=q.get("q", "")[:120]))

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
            _int(d.get("limit"), 25, 1, 100), bool(d.get("dry_run")), background=True))

    def api_health(self, environ, start):
        return self._json(start, self.api.health())

    def api_money(self, environ, start):
        return self._json(start, self.api.money())

    def api_forecast(self, environ, start):
        q = _query(environ)
        try:
            adds = float(q.get("adds", 2) or 2)
            churn = float(q.get("churn", 0.05) or 0.05)
        except ValueError:
            adds, churn = 2.0, 0.05
        return self._json(start, self.api.forecast(max(0.1, min(20.0, adds)),
                                                   max(0.0, min(0.5, churn))))

    def api_win(self, environ, start):
        d = self._body_json(environ)
        return self._json(start, self.api.win(str(d.get("id", "")),
                                              str(d.get("plan", "growth"))))

    def api_paid(self, environ, start):
        d = self._body_json(environ)
        return self._json(start, self.api.mark_paid(str(d.get("id", ""))))

    def api_add(self, environ, start):
        d = self._body_json(environ)
        return self._json(start, self.api.add_business(
            **{k: str(d.get(k, "")) for k in ("name", "city", "state", "vertical",
                                               "website", "email", "phone")}))

    def api_expense(self, environ, start):
        d = self._body_json(environ)
        return self._json(start, self.api.log_expense(
            str(d.get("category", "")), d.get("amount", 0),
            str(d.get("description", "")), bool(d.get("revenue"))))

    def api_research(self, environ, start):
        refresh = _query(environ).get("refresh") in {"1", "true", "yes"}
        return self._json(start, self.api.research(refresh))

    def api_markets(self, environ, start):
        return self._json(start, self.api.markets())

    def dashboard(self, environ, start):
        """The desktop control room: everything on one screen."""
        body = render("dashboard.html")
        headers = [("Content-Type", "text/html; charset=utf-8"),
                   ("Content-Length", str(len(body))),
                   ("Cache-Control", "no-store")]
        if _query(environ).get("t"):
            headers.append(("Set-Cookie", auth.session_cookie(self.token)))
        start("200 OK", headers)
        return [body]

    def api_clients(self, environ, start):
        return self._json(start, self.api.clients())

    def api_intelligence(self, environ, start):
        return self._json(start, self.api.intelligence())

    def api_brief(self, environ, start):
        return self._json(start, self.api.brief(_query(environ).get("id", "")))

    def api_reply(self, environ, start):
        d = self._body_json(environ)
        return self._json(start, self.api.log_reply(
            str(d.get("id", "")), str(d.get("text", ""))))

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
            "/api/clients": self.api_clients,
            "/api/intelligence": self.api_intelligence,
            "/api/brief": self.api_brief,
            "/api/reply": self.api_reply,
            "/dashboard": self.dashboard,
            "/api/health": self.api_health,
            "/api/money": self.api_money,
            "/api/forecast": self.api_forecast,
            "/api/win": self.api_win,
            "/api/paid": self.api_paid,
            "/api/add": self.api_add,
            "/api/expense": self.api_expense,
            "/api/markets": self.api_markets,
            "/api/research": self.api_research,
        }

    def files(self, environ, start):
        """Open a client's report or one of their files from the phone.

        These were written to the laptop's disk and nothing could open them
        from anywhere else, so a report could not even be forwarded by hand.
        Behind the console login like everything else here; a file is only
        served from the output directory, whatever the database says.
        """
        parts = environ.get("PATH_INFO", "").strip("/").split("/")
        if len(parts) != 3 or parts[1] not in {"report", "file", "case"}:
            return self._ok(start, render("notfound.html"), status="404 Not Found")
        _, kind, ident = parts
        root = Path(self.settings.output_dir).resolve()
        if kind == "case":
            from answerrank import casestudy
            client = self.store.get_client(ident)
            if not client:
                return self._ok(start, render("notfound.html"), status="404 Not Found")
            _ev, text = casestudy.write_up(self.store, client)
            body = text.encode("utf-8")
            start("200 OK", [("Content-Type", "text/plain; charset=utf-8"),
                             ("Content-Length", str(len(body))),
                             ("Cache-Control", "no-store")])
            return [body]
        if kind == "report":
            reports = [d for c in [self.store.get_client(ident)] if c
                       for a in self.store.audit_history(c.business.id, limit=12)
                       for d in self.store.get_deliverables(a.id) if d.kind == "report_html"]
            target = Path(reports[0].body).resolve() if reports else None
            if not target or root not in target.parents or not target.exists():
                return self._ok(start, render("notfound.html"), status="404 Not Found")
            body = target.read_bytes()
            ctype, name = "text/html; charset=utf-8", target.name
        else:
            d = self.store.get_deliverable(ident)
            if not d or d.kind == "report_html":
                return self._ok(start, render("notfound.html"), status="404 Not Found")
            body = d.body.encode("utf-8")
            ctype = ("application/json" if d.filename.endswith(".json")
                     else "text/plain") + "; charset=utf-8"
            name = d.filename or f"{d.kind}.txt"
        start("200 OK", [("Content-Type", ctype), ("Content-Length", str(len(body))),
                         ("Content-Disposition", f'inline; filename="{name}"'),
                         ("Cache-Control", "no-store"),
                         ("X-Content-Type-Options", "nosniff")])
        return [body]

    def __call__(self, environ, start_response) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "/").rstrip("/") or "/"
        handler = self.routes.get(path)
        if handler is None and path.startswith("/files/"):
            handler = self.files

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
        except Exception as exc:  # noqa: BLE001
            log.exception("unhandled error on %s", path)
            # An API route answers in JSON even when it fails. The console
            # calls res.json() on everything, so an HTML error page did not
            # read as an error — the panel simply went blank and stayed that
            # way, which is the hardest kind of failure to diagnose from a
            # phone.
            if path.startswith("/api/"):
                return self._json(start_response,
                                  {"error": f"{type(exc).__name__}: {exc}"[:300]},
                                  "500 Internal Server Error")
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


class _ThreadedWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    """One thread per request.

    ``make_server`` is single-threaded, so any slow request froze the whole
    console — and one of them is genuinely slow: the doctor resolves SPF, DKIM
    and DMARC over the network, which takes seconds. While that was in flight
    the phone console would not load, the dashboard sat on stale numbers after
    closing a sale, and it looked like the app had hung. It had: one blocking
    call was holding the only thread.
    """

    daemon_threads = True
    #: A stuck client should not hold a thread forever.
    request_queue_size = 32


def serve(host: str = "0.0.0.0", port: int = 8000, settings: Settings | None = None) -> None:
    app = create_app(settings)
    server = make_server(host, port, app, server_class=_ThreadedWSGIServer)
    log.info("serving on http://%s:%s", host, port)
    server.serve_forever()
