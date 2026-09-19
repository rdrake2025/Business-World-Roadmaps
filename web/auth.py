"""Access control for the local operator console.

The console can approve outreach and trigger sends, so it is not something
to leave open on a network. It binds to the LAN so a phone can reach the
laptop, which means anything else on that Wi-Fi can reach it too — a cafe,
an office, a shared flat.

The model is deliberately simple, because complexity in auth is how auth
breaks: one long random token, generated once and kept in the database.
It arrives the first time in the URL (scanned or typed from the laptop
terminal), is exchanged for a cookie, and never appears in a URL again.

This is not a substitute for TLS. Over a trusted home network it is
proportionate; exposed to the internet through a tunnel it is the minimum,
and the tunnel must supply HTTPS.
"""

from __future__ import annotations

import hmac
import secrets
from http.cookies import SimpleCookie
from typing import Any

TOKEN_KEY = "console_token"
COOKIE = "ar_session"
#: Paths anyone may reach — the public site and the legally-required opt-out.
PUBLIC = {"/", "/unsubscribe", "/audit-request", "/privacy", "/terms", "/health",
          "/manifest.webmanifest", "/sw.js", "/icon.svg"}


def get_or_create_token(store) -> str:
    """The console token, minted on first use and stable thereafter."""
    token = store.kv_get(TOKEN_KEY)
    if not token:
        token = secrets.token_urlsafe(24)
        store.kv_set(TOKEN_KEY, token)
    return token


def rotate_token(store) -> str:
    token = secrets.token_urlsafe(24)
    store.kv_set(TOKEN_KEY, token)
    return token


def _cookies(environ: dict[str, Any]) -> dict[str, str]:
    raw = environ.get("HTTP_COOKIE", "")
    if not raw:
        return {}
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:  # noqa: BLE001 - a malformed cookie is simply no cookie
        return {}
    return {k: v.value for k, v in jar.items()}


def presented_token(environ: dict[str, Any], query: dict[str, str]) -> str:
    """Token from the cookie, the header, or the first-visit query string."""
    return (
        _cookies(environ).get(COOKIE)
        or environ.get("HTTP_X_AUTH_TOKEN", "")
        or query.get("t", "")
    ).strip()


def is_authorised(presented: str, expected: str) -> bool:
    if not presented or not expected:
        return False
    # Constant-time: a timing side channel on a 24-byte token is unlikely to
    # be practical, but comparing secrets this way costs nothing.
    return hmac.compare_digest(presented, expected)


def requires_auth(path: str) -> bool:
    return path not in PUBLIC


def session_cookie(token: str, secure: bool = False) -> str:
    """A long-lived cookie so the phone is asked only once.

    HttpOnly keeps it away from page scripts; SameSite=Lax is enough for a
    console with no cross-site posts and keeps normal navigation working.
    """
    parts = [
        f"{COOKIE}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=31536000",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie() -> str:
    return f"{COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
