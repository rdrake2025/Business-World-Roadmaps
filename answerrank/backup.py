"""A copy of the business that lives somewhere other than the server.

The server backs its database up every night, to its own disk. That covers
a bad update or a mistake; it doesn't cover the server itself dying, being
deleted, or its disk failing, because the backups die with it. So once a
week the Briefing agent emails you a compressed copy. Your mailbox is
somewhere else entirely, and you already pay for it.

How it's made (see evidence.py: sqlite_online_backup, gmail_attachment_limit):

* SQLite's online backup API, never a file copy: a copy taken while the
  fleet is writing can capture a half-written state.
* Compressed with gzip. Gmail sends attachments up to 25 MB and encodes them
  first, which adds about a third, so anything over 15 MB compressed isn't
  attached; the email says so and how to fetch it from the server instead.

What's in it: businesses, their public contact details, clients, messages
and the books. No keys or passwords: those live in keys.env, never in the
database. It goes only to your own address.
"""

from __future__ import annotations

import gzip
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

#: Compressed size above which the copy isn't attached (Gmail's 25 MB limit,
#: less base64's third, less headroom).
MAX_ATTACH_MB = 15

RESTORE = """To restore it on a new server:
1. Make the new server with the setup file (deploy/SERVER.md), as the first time.
2. Unzip this file (7-Zip on Windows, or double-click on a Mac) to get
   answerrank.db.
3. Upload it to the server as /opt/answerrank/data/answerrank.db, replacing
   the empty one, then restart the server from its control panel.
Everything carries on from the moment this copy was taken."""


def snapshot(db_path: str | Path, out_dir: str | Path | None = None) -> Path:
    """A consistent, compressed copy of the database. Returns the .gz path."""
    out_dir = Path(out_dir or tempfile.mkdtemp(prefix="answerrank-backup-"))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = out_dir / f"answerrank-{stamp}.db"
    src = sqlite3.connect(str(db_path))
    try:
        dest = sqlite3.connect(str(raw))
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()
    gz = raw.with_suffix(".db.gz")
    with raw.open("rb") as fin, gzip.open(gz, "wb", compresslevel=9) as fout:
        while chunk := fin.read(1 << 20):
            fout.write(chunk)
    raw.unlink()
    return gz


def email_backup(store, settings, mailer, to: str) -> tuple[bool, str]:
    """Email the compressed copy to ``to``. Returns (sent, what happened)."""
    gz = snapshot(store.path)
    try:
        size_mb = gz.stat().st_size / (1024 * 1024)
        stamp = datetime.now(timezone.utc).strftime("%d %B %Y")
        if size_mb > MAX_ATTACH_MB:
            body = (f"This week's copy of the business is {size_mb:.0f} MB compressed, too "
                    f"big to attach. The server still keeps a copy every night in "
                    f"/opt/answerrank/backups. If this keeps happening, ask for the "
                    f"backups to go to cloud storage instead.")
            ok, detail = mailer.send(to, f"AnswerRank backup, {stamp} (too big to attach)",
                                     body)
            return ok, "too big to attach; told you instead" if ok else detail
        body = (f"Attached: a copy of the whole business as of {stamp} "
                f"({size_mb:.1f} MB). Keep this email. If the server is ever lost, "
                f"this is how you get everything back.\n\n{RESTORE}\n\n"
                f"No keys or passwords are in it.")
        ok, detail = mailer.send_file(to, f"AnswerRank backup, {stamp}", body,
                                      gz.name, gz.read_bytes(), "application/gzip")
        return ok, f"{size_mb:.1f} MB sent to {to}" if ok else detail
    finally:
        gz.unlink(missing_ok=True)
        try:
            gz.parent.rmdir()
        except OSError:
            pass
