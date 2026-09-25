"""Moving the business onto a small always-on server.

Every email carries an unsubscribe link, and that link has to work from the
public internet — the doctor refuses to send until it does. A laptop cannot
serve it: the app is only reachable on the home Wi-Fi, and a laptop sleeps.
So the business needs one small server (about $6 a month) with HTTPS.

This writes one file that sets that server up. The operator creates an
Ubuntu 24.04 server at DigitalOcean or Hetzner, pastes the file into the
"user data" box on the creation page, points their domain at the server's
address, and is done. No terminal, no SSH.

The file carries the operator's settings and keys, so it is written next to
the config, is ignored by git, and should be deleted once the server is up.
"""

from __future__ import annotations

import base64
import re
import secrets
import subprocess
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, ROOT
from .keys import KEYS_FILE

TEMPLATE = ROOT / "deploy" / "setup-server.sh"
DEFAULT_REPO = "https://github.com/rdrake2025/Business-World-Roadmaps.git"

#: DigitalOcean accepts 64 KiB of user data; Hetzner accepts 32 KiB.
USER_DATA_LIMIT = 32 * 1024

_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def repo_url() -> str:
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        url = ""
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.split(":", 1)[1]
    return url if url.startswith("https://") else DEFAULT_REPO


def _config_for(domain: str, config_path: Path) -> str:
    """The operator's config, pointed at the server's own address."""
    text = config_path.read_text(encoding="utf-8") if config_path.exists() \
        else "# AnswerRank configuration\n"
    line = f'website: "https://{domain}"'
    if re.search(r"(?m)^website:", text):
        text = re.sub(r"(?m)^website:.*$", line, text)
    else:
        text += "\n" + line + "\n"
    return text


def build(domain: str, config_path: Path = DEFAULT_CONFIG_PATH,
          keys_path: Path = KEYS_FILE, token: str = "",
          repo: str = "") -> tuple[str, str]:
    """(script, console_link) for this domain."""
    domain = domain.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    domain = domain.removeprefix("www.")
    if not _DOMAIN.match(domain):
        raise ValueError(f"{domain!r} is not a domain name. Use something like "
                         f"getanswerrank.com — no https://, no slashes.")
    token = token or secrets.token_urlsafe(24)
    keys_text = Path(keys_path).read_text(encoding="utf-8") if Path(keys_path).exists() else ""

    script = TEMPLATE.read_text(encoding="utf-8")
    for marker, value in (
        ("__DOMAIN__", domain),
        ("__REPO__", repo or repo_url()),
        ("__TOKEN__", token),
        ("__CONFIG_B64__", base64.b64encode(
            _config_for(domain, Path(config_path)).encode()).decode()),
        ("__KEYS_B64__", base64.b64encode(keys_text.encode()).decode()),
    ):
        script = script.replace(marker, value)
    return script, f"https://{domain}/app?t={token}"


def write(domain: str, out_dir: Path = ROOT, **kw) -> tuple[Path, str, list[str]]:
    """Write the file. Returns (path, console link, warnings)."""
    script, link = build(domain, **kw)
    name = domain.strip().lower().removeprefix("https://").strip("/").removeprefix("www.")
    path = Path(out_dir) / f"server-setup-{name}.sh"
    path.write_text(script, encoding="utf-8", newline="\n")
    warnings = []
    if len(script.encode()) > USER_DATA_LIMIT:
        warnings.append(f"The file is {len(script) // 1024} KB; Hetzner accepts 32 KB. "
                        f"DigitalOcean accepts it.")
    if not Path(kw.get("keys_path", KEYS_FILE)).exists():
        warnings.append("No keys.env yet, so the server will have no mailbox or API "
                        "keys. Do Keys and settings first (AnswerRank button), then make this file again.")
    return path, link, warnings
