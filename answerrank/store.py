"""SQLite persistence.

One file, no migrations framework, no server. The whole business state is a
single portable ``.db`` file that can be backed up with ``cp``. Tables store
their rich fields as JSON blobs so the schema never blocks a product change.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import (
    Audit,
    AgentRun,
    Business,
    Client,
    Deliverable,
    LedgerEntry,
    OutreachMessage,
    ProbeResult,
    Prospect,
)

log = logging.getLogger("answerrank.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS prospects (
    id TEXT PRIMARY KEY, business_id TEXT, name TEXT, city TEXT, state TEXT,
    vertical TEXT, website TEXT, domain TEXT, email TEXT, phone TEXT,
    stage TEXT, score REAL, competitor_gap REAL, last_audit_id TEXT,
    touches INTEGER, last_touch_at TEXT, next_action_at TEXT, notes TEXT,
    created_at TEXT, raw TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prospect_domain ON prospects(domain)
    WHERE domain IS NOT NULL AND domain != '';
CREATE INDEX IF NOT EXISTS idx_prospect_stage ON prospects(stage);

CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY, business_id TEXT, name TEXT, city TEXT, state TEXT,
    vertical TEXT, website TEXT, email TEXT, plan TEXT, mrr REAL, status TEXT,
    started_at TEXT, churned_at TEXT, last_report_at TEXT, raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_client_status ON clients(status);

CREATE TABLE IF NOT EXISTS audits (
    id TEXT PRIMARY KEY, business_id TEXT, business_name TEXT, market TEXT,
    vertical TEXT, score REAL, is_free_teaser INTEGER, created_at TEXT, raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_business ON audits(business_id, created_at);

CREATE TABLE IF NOT EXISTS deliverables (
    id TEXT PRIMARY KEY, audit_id TEXT, business_id TEXT, kind TEXT,
    title TEXT, body TEXT, filename TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, prospect_id TEXT, subject TEXT, body TEXT,
    sequence_step INTEGER, status TEXT, scheduled_for TEXT, sent_at TEXT,
    created_at TEXT, kind TEXT DEFAULT 'cold', approved_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_message_status ON messages(status);

CREATE TABLE IF NOT EXISTS ledger (
    id TEXT PRIMARY KEY, kind TEXT, category TEXT, amount REAL,
    description TEXT, client_id TEXT, occurred_at TEXT,
    -- Names what a recurring charge is and which month it belongs to, so
    -- "bill each client once a month" is enforced by the database rather
    -- than by a caller remembering to look first.
    dedupe_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_ledger_time ON ledger(occurred_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_dedupe ON ledger(dedupe_key)
    WHERE dedupe_key IS NOT NULL AND dedupe_key != '';

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY, agent TEXT, status TEXT, started_at TEXT,
    finished_at TEXT, items_processed INTEGER, summary TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS idx_run_agent ON agent_runs(agent, started_at);

CREATE TABLE IF NOT EXISTS outcomes (
    id TEXT PRIMARY KEY, prospect_id TEXT, message_id TEXT, vertical TEXT,
    step INTEGER, kind TEXT, sentiment TEXT, note TEXT, occurred_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outcome_kind ON outcomes(kind, occurred_at);
CREATE INDEX IF NOT EXISTS idx_outcome_vertical ON outcomes(vertical, kind);

CREATE TABLE IF NOT EXISTS market_findings (
    id TEXT PRIMARY KEY, market TEXT, label TEXT, sampled INTEGER,
    mean_score REAL, invisible_share REAL, opportunity REAL, verdict TEXT,
    notes TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_market_time ON market_findings(market, created_at);

CREATE TABLE IF NOT EXISTS research_findings (
    id TEXT PRIMARY KEY, subject TEXT, claim TEXT, evidence TEXT,
    proposal TEXT, severity TEXT, confidence TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_research_subject
    ON research_findings(subject, created_at);

CREATE TABLE IF NOT EXISTS inbound (
    message_id TEXT PRIMARY KEY, sender TEXT, kind TEXT, prospect_id TEXT,
    received_at TEXT, handled_at TEXT, snippet TEXT
);

CREATE TABLE IF NOT EXISTS site_checks (
    id TEXT PRIMARY KEY, business_id TEXT, checked_at TEXT, raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_site_checks ON site_checks(business_id, checked_at);

CREATE TABLE IF NOT EXISTS appointments (
    id TEXT PRIMARY KEY, prospect_id TEXT, kind TEXT, starts_at TEXT,
    note TEXT, status TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_appointments ON appointments(status, starts_at);

CREATE TABLE IF NOT EXISTS citation_checks (
    id TEXT PRIMARY KEY, business_id TEXT, checked_at TEXT, raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_citation_checks ON citation_checks(business_id, checked_at);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS suppression (
    email TEXT PRIMARY KEY, reason TEXT, created_at TEXT
);
"""


def _message(row) -> OutreachMessage:
    data = {k: row[k] for k in row.keys()}
    data["approved_at"] = data.get("approved_at") or ""
    return OutreachMessage(**data)


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._migrate()
        with self.conn() as cx:
            cx.executescript(SCHEMA)

    def _migrate(self) -> None:
        """Add columns that later versions introduced.

        ``CREATE TABLE IF NOT EXISTS`` does nothing to a table that already
        exists, so a new column is invisible to anyone with a database from
        an earlier build — which is everyone already running this. The
        indexes in SCHEMA reference those columns, so without this the whole
        schema script fails on an existing file and the app will not start.
        """
        if not Path(self.path).exists():
            return
        wanted = {"ledger": [("dedupe_key", "TEXT")],
                  "messages": [("kind", "TEXT DEFAULT 'cold'"),
                               ("approved_at", "TEXT DEFAULT ''")]}
        with self.conn() as cx:
            for table, columns in wanted.items():
                exists = cx.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if not exists:
                    continue
                have = {r["name"] for r in cx.execute(f"PRAGMA table_info({table})")}
                for name, decl in columns:
                    if name not in have:
                        cx.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        cx = sqlite3.connect(self.path, timeout=30)
        cx.row_factory = sqlite3.Row
        cx.execute("PRAGMA journal_mode=WAL")
        cx.execute("PRAGMA foreign_keys=ON")
        try:
            yield cx
            cx.commit()
        finally:
            cx.close()

    @contextmanager
    def writer(self) -> Iterator[sqlite3.Connection]:
        """A connection that holds the write lock for the whole block.

        ``conn`` is correct for a single statement. Several methods here read
        a row, decide something from it, and then write based on that
        decision. Under SQLite's default deferred transaction the read runs
        outside the lock, so two threads can both read "not there yet" and
        both go on to write.

        That stopped being theoretical when the fleet started running in a
        thread beside the web server: both write prospects, clients and the
        ledger against the same file. The observed consequences are a
        duplicate-domain IntegrityError that kills a Scout run, and a client
        billed twice in one month.

        ``BEGIN IMMEDIATE`` takes the write lock before the first read, so
        check-then-act becomes atomic and a second writer waits its turn
        instead of racing.
        """
        cx = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        cx.row_factory = sqlite3.Row
        cx.execute("PRAGMA journal_mode=WAL")
        cx.execute("PRAGMA foreign_keys=ON")
        try:
            cx.execute("BEGIN IMMEDIATE")
            try:
                yield cx
            except BaseException:
                # Never let a failed rollback replace the real exception: the
                # caller needs to see what actually went wrong, and closing
                # the connection below discards the transaction regardless.
                try:
                    cx.execute("ROLLBACK")
                except sqlite3.Error:
                    log.warning("rollback failed; closing the connection instead",
                                exc_info=True)
                raise
            cx.execute("COMMIT")
        finally:
            cx.close()

    # ---------------- prospects ----------------

    def upsert_prospect(self, p: Prospect) -> str:
        b = p.business
        # ``writer`` and not ``conn``: the SELECT below decides what the
        # INSERT does, and there is a unique index on domain. Two threads
        # reading "no such domain" at the same time both insert, and the
        # second one raises IntegrityError — which, before this, killed the
        # Scout run that hit it.
        with self.writer() as cx:
            # Domain is the natural key: never pitch the same business twice.
            if b.domain:
                row = cx.execute(
                    "SELECT id FROM prospects WHERE domain = ?", (b.domain,)
                ).fetchone()
                if row:
                    p.id = row["id"]
            cx.execute(
                """INSERT INTO prospects (id,business_id,name,city,state,vertical,website,domain,
                   email,phone,stage,score,competitor_gap,last_audit_id,touches,last_touch_at,
                   next_action_at,notes,created_at,raw)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     stage=excluded.stage, score=excluded.score,
                     competitor_gap=excluded.competitor_gap,
                     last_audit_id=excluded.last_audit_id, touches=excluded.touches,
                     last_touch_at=excluded.last_touch_at,
                     next_action_at=excluded.next_action_at, notes=excluded.notes,
                     email=excluded.email, raw=excluded.raw""",
                (p.id, b.id, b.name, b.city, b.state, b.vertical, b.website, b.domain,
                 b.email, b.phone, p.stage, p.score, p.competitor_gap, p.last_audit_id,
                 p.touches, p.last_touch_at, p.next_action_at, p.notes, p.created_at,
                 json.dumps(asdict(p), default=str)),
            )
        return p.id

    def prospect_exists(self, domain: str) -> bool:
        if not domain:
            return False
        with self.conn() as cx:
            return cx.execute(
                "SELECT 1 FROM prospects WHERE domain = ?", (domain,)
            ).fetchone() is not None

    def get_prospects(self, stage: str | None = None, limit: int = 100) -> list[Prospect]:
        q = "SELECT raw FROM prospects"
        args: tuple = ()
        if stage:
            q += " WHERE stage = ?"
            args = (stage,)
        q += " ORDER BY created_at ASC LIMIT ?"
        with self.conn() as cx:
            rows = cx.execute(q, args + (limit,)).fetchall()
        return [_prospect_from_raw(r["raw"]) for r in rows]

    def due_prospects(self, stage: str, limit: int = 50) -> list[Prospect]:
        """Prospects in a stage whose next_action_at has arrived."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.conn() as cx:
            rows = cx.execute(
                """SELECT raw FROM prospects WHERE stage = ?
                   AND (next_action_at = '' OR next_action_at <= ?)
                   ORDER BY score ASC LIMIT ?""",
                (stage, now, limit),
            ).fetchall()
        return [_prospect_from_raw(r["raw"]) for r in rows]

    def count_prospects_by_stage(self) -> dict[str, int]:
        with self.conn() as cx:
            rows = cx.execute(
                "SELECT stage, COUNT(*) c FROM prospects GROUP BY stage"
            ).fetchall()
        return {r["stage"]: r["c"] for r in rows}

    # ---------------- clients ----------------

    def upsert_client(self, c: Client) -> str:
        b = c.business
        with self.conn() as cx:
            cx.execute(
                """INSERT INTO clients (id,business_id,name,city,state,vertical,website,email,
                   plan,mrr,status,started_at,churned_at,last_report_at,raw)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET plan=excluded.plan, mrr=excluded.mrr,
                     status=excluded.status, churned_at=excluded.churned_at,
                     last_report_at=excluded.last_report_at, raw=excluded.raw""",
                (c.id, b.id, b.name, b.city, b.state, b.vertical, b.website, b.email,
                 c.plan, c.mrr, c.status, c.started_at, c.churned_at, c.last_report_at,
                 json.dumps(asdict(c), default=str)),
            )
        return c.id

    def start_client(self, c: Client) -> tuple[str, bool]:
        """Put a business on the books, once.

        Returns ``(client_id, created)``. If this business already has a
        live client record, that one is returned untouched and ``created``
        is False.

        Winning a deal is a button on a phone. A laggy tap gets tapped
        twice, and ``upsert_client`` keys on the client id — which is freshly
        generated each time — so the second tap used to create a second
        active client for the same business. MRR is the number this whole
        operation is steered by, and it was the number that doubled.
        """
        b = c.business
        with self.writer() as cx:
            row = cx.execute(
                """SELECT id FROM clients
                   WHERE business_id = ?
                   AND status IN ('active','trialing','awaiting_payment','past_due')
                   ORDER BY started_at ASC LIMIT 1""",
                (b.id,),
            ).fetchone()
            if row:
                return str(row["id"]), False
            cx.execute(
                """INSERT INTO clients (id,business_id,name,city,state,vertical,website,email,
                   plan,mrr,status,started_at,churned_at,last_report_at,raw)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET plan=excluded.plan, mrr=excluded.mrr,
                     status=excluded.status, raw=excluded.raw""",
                (c.id, b.id, b.name, b.city, b.state, b.vertical, b.website, b.email,
                 c.plan, c.mrr, c.status, c.started_at, c.churned_at, c.last_report_at,
                 json.dumps(asdict(c), default=str)),
            )
        return c.id, True

    def get_clients(self, status: str | None = "active") -> list[Client]:
        q = "SELECT raw FROM clients"
        args: tuple = ()
        if status:
            q += " WHERE status = ?"
            args = (status,)
        with self.conn() as cx:
            rows = cx.execute(q + " ORDER BY started_at ASC", args).fetchall()
        out = []
        for r in rows:
            d = json.loads(r["raw"])
            d["business"] = Business(**d["business"])
            out.append(Client(**d))
        return out

    def get_client(self, client_id: str) -> Client | None:
        with self.conn() as cx:
            row = cx.execute("SELECT raw FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not row:
            return None
        d = json.loads(row["raw"])
        d["business"] = Business(**d["business"])
        return Client(**d)

    def prospect_for_business(self, business: Business) -> Prospect | None:
        """The prospect record a client was won from — which is where their
        email address and the conversation with them live."""
        with self.conn() as cx:
            row = cx.execute(
                "SELECT raw FROM prospects WHERE business_id = ? LIMIT 1",
                (business.id,)).fetchone()
            if not row and business.domain:
                row = cx.execute(
                    "SELECT raw FROM prospects WHERE domain = ? LIMIT 1",
                    (business.domain,)).fetchone()
        return _prospect_from_raw(row["raw"]) if row else None

    def mrr(self) -> float:
        with self.conn() as cx:
            row = cx.execute(
                "SELECT COALESCE(SUM(mrr),0) m FROM clients WHERE status IN ('active','trialing')"
            ).fetchone()
        return float(row["m"])

    # ---------------- audits & deliverables ----------------

    def save_audit(self, a: Audit) -> str:
        with self.conn() as cx:
            cx.execute(
                """INSERT OR REPLACE INTO audits
                   (id,business_id,business_name,market,vertical,score,is_free_teaser,created_at,raw)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (a.id, a.business_id, a.business_name, a.market, a.vertical, a.score,
                 int(a.is_free_teaser), a.created_at, json.dumps(asdict(a), default=str)),
            )
        return a.id

    def teasers_since(self, stamp: str) -> int:
        """Free teaser audits run since an ISO timestamp."""
        with self.conn() as cx:
            return cx.execute(
                "SELECT COUNT(*) FROM audits WHERE is_free_teaser = 1 AND created_at >= ?",
                (stamp,)).fetchone()[0]

    def get_audit(self, audit_id: str) -> Audit | None:
        with self.conn() as cx:
            row = cx.execute("SELECT raw FROM audits WHERE id = ?", (audit_id,)).fetchone()
        return _audit_from_raw(row["raw"]) if row else None

    def audit_history(self, business_id: str, limit: int = 12,
                      comparable: bool = False) -> list[Audit]:
        """Audits for one business, newest first.

        ``comparable=True`` leaves out the free teaser. The teaser asks four
        questions and the monthly audit asks ten, so their scores measure
        different things — and every trend built on the mix compared them
        anyway. A client's first paid report showed their score falling by
        twenty-odd points in red since the day they were pitched, with
        nothing having changed but the question count. Anything drawing a
        line between two audits must ask for this.
        """
        with self.conn() as cx:
            rows = cx.execute(
                "SELECT raw FROM audits WHERE business_id = ? ORDER BY created_at DESC",
                (business_id,),
            ).fetchall()
        out = []
        for r in rows:
            audit = _audit_from_raw(r["raw"])
            if comparable and audit.is_free_teaser:
                continue
            out.append(audit)
            if len(out) >= limit:
                break
        return out

    def save_deliverable(self, d: Deliverable) -> str:
        with self.conn() as cx:
            cx.execute(
                """INSERT OR REPLACE INTO deliverables
                   (id,audit_id,business_id,kind,title,body,filename,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (d.id, d.audit_id, d.business_id, d.kind, d.title, d.body, d.filename, d.created_at),
            )
        return d.id

    def get_deliverable(self, deliverable_id: str) -> Deliverable | None:
        with self.conn() as cx:
            row = cx.execute("SELECT * FROM deliverables WHERE id = ?",
                             (deliverable_id,)).fetchone()
        if not row:
            return None
        return Deliverable(**{k: row[k] for k in row.keys()
                              if k in Deliverable.__dataclass_fields__})

    def get_deliverables(self, audit_id: str) -> list[Deliverable]:
        with self.conn() as cx:
            rows = cx.execute(
                "SELECT * FROM deliverables WHERE audit_id = ?", (audit_id,)
            ).fetchall()
        return [Deliverable(**{k: r[k] for k in r.keys()}) for r in rows]

    # ---------------- messages & suppression ----------------

    def save_message(self, m: OutreachMessage) -> str:
        with self.conn() as cx:
            cx.execute(
                """INSERT OR REPLACE INTO messages
                   (id,prospect_id,subject,body,sequence_step,status,scheduled_for,
                    sent_at,created_at,kind,approved_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (m.id, m.prospect_id, m.subject, m.body, m.sequence_step, m.status,
                 m.scheduled_for, m.sent_at, m.created_at, m.kind or "cold",
                 m.approved_at or ""),
            )
        return m.id

    def get_message(self, message_id: str) -> OutreachMessage | None:
        with self.conn() as cx:
            r = cx.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        return _message(r) if r else None

    def send_queue(self, limit: int = 100) -> list[OutreachMessage]:
        """Approved messages in the order they should leave.

        Anything answering a person goes before anything cold. By creation
        date alone, a reply to "yes, send it" drafted this morning queued
        behind every cold email approved earlier in the week — and while the
        warm-up cap is binding, that is days. In the 30-sale simulation the
        median wait for an answer was seven days. An interested buyer does
        not wait seven days.
        """
        with self.conn() as cx:
            rows = cx.execute(
                """SELECT * FROM messages WHERE status = 'approved'
                   ORDER BY CASE COALESCE(kind, 'cold') WHEN 'cold' THEN 1 ELSE 0 END,
                            created_at ASC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [_message(r) for r in rows]

    def messages_for(self, prospect_id: str) -> list[OutreachMessage]:
        with self.conn() as cx:
            rows = cx.execute(
                "SELECT * FROM messages WHERE prospect_id = ? ORDER BY created_at ASC",
                (prospect_id,),
            ).fetchall()
        return [_message(r) for r in rows]

    def withdraw_cold(self, prospect_id: str) -> int:
        """Pull any not-yet-sent cold message to someone who has left the
        sequence — they replied, bought, or asked us to stop."""
        with self.conn() as cx:
            cur = cx.execute(
                """UPDATE messages SET status = 'superseded'
                   WHERE prospect_id = ? AND status IN ('drafted', 'approved')
                   AND COALESCE(kind, 'cold') = 'cold'""",
                (prospect_id,),
            )
            return cur.rowcount

    def cold_sends_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with self.conn() as cx:
            row = cx.execute(
                """SELECT COUNT(*) c FROM messages WHERE status='sent' AND sent_at LIKE ?
                   AND COALESCE(kind, 'cold') = 'cold'""",
                (f"{today}%",),
            ).fetchone()
        return int(row["c"])

    def get_messages(self, status: str | None = None, limit: int = 200) -> list[OutreachMessage]:
        q = "SELECT * FROM messages"
        args: tuple = ()
        if status:
            q += " WHERE status = ?"
            args = (status,)
        with self.conn() as cx:
            rows = cx.execute(q + " ORDER BY created_at ASC LIMIT ?", args + (limit,)).fetchall()
        return [_message(r) for r in rows]

    def sends_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with self.conn() as cx:
            row = cx.execute(
                "SELECT COUNT(*) c FROM messages WHERE status='sent' AND sent_at LIKE ?",
                (f"{today}%",),
            ).fetchone()
        return int(row["c"])

    def suppress(self, email: str, reason: str) -> None:
        if not email:
            return
        with self.conn() as cx:
            cx.execute(
                "INSERT OR REPLACE INTO suppression (email,reason,created_at) VALUES (?,?,?)",
                (email.lower().strip(), reason,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )

    def is_suppressed(self, email: str) -> bool:
        if not email:
            return False
        with self.conn() as cx:
            return cx.execute(
                "SELECT 1 FROM suppression WHERE email = ?", (email.lower().strip(),)
            ).fetchone() is not None

    # ---------------- outcomes ----------------

    def record_outcome(self, *, prospect_id: str = "", message_id: str = "",
                       vertical: str = "", step: int = 0, kind: str = "",
                       sentiment: str = "", note: str = "") -> str:
        """Log what actually happened. Nothing learns without this.

        ``kind`` is one of: sent, replied, call_booked, won, lost, churned.
        """
        oid = f"out_{uuid.uuid4().hex[:12]}"
        with self.conn() as cx:
            cx.execute(
                """INSERT INTO outcomes
                   (id,prospect_id,message_id,vertical,step,kind,sentiment,note,occurred_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (oid, prospect_id, message_id, vertical, step, kind, sentiment, note,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
        return oid

    def outcome_counts(self, days: int = 90) -> dict[str, int]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self.conn() as cx:
            rows = cx.execute(
                "SELECT kind, COUNT(*) c FROM outcomes WHERE occurred_at >= ? GROUP BY kind",
                (since,),
            ).fetchall()
        return {r["kind"]: r["c"] for r in rows}

    def outcomes_by(self, field: str, days: int = 90) -> dict[str, dict[str, int]]:
        """Counts of each outcome kind, grouped by vertical or sequence step."""
        if field not in {"vertical", "step"}:
            raise ValueError("group by vertical or step only")
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self.conn() as cx:
            rows = cx.execute(
                f"""SELECT {field} g, kind, COUNT(*) c FROM outcomes
                    WHERE occurred_at >= ? AND {field} != '' GROUP BY g, kind""",
                (since,),
            ).fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(str(r["g"]), {})[r["kind"]] = r["c"]
        return out

    def prospects_awaiting_reply(self, limit: int = 200) -> list[Prospect]:
        return self.get_prospects("replied", limit)

    def outcomes_for(self, subject_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Everything recorded against one prospect or client, newest first."""
        with self.conn() as cx:
            rows = cx.execute(
                """SELECT * FROM outcomes WHERE prospect_id = ?
                   ORDER BY occurred_at DESC LIMIT ?""",
                (subject_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def outcomes_with_prefix(self, prefix: str, days: int = 365) -> list[dict[str, Any]]:
        """Every outcome whose kind starts with ``prefix``, newest first —
        one query for all prospects rather than one per prospect."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        pattern = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self.conn() as cx:
            rows = cx.execute(
                """SELECT * FROM outcomes WHERE kind LIKE ? ESCAPE '\\'
                   AND occurred_at >= ? ORDER BY occurred_at DESC""",
                (pattern, since)).fetchall()
        return [dict(r) for r in rows]

    def has_outcome(self, subject_id: str, kind: str) -> bool:
        """Whether this has *ever* happened to this subject.

        Asked directly rather than by scanning the latest N outcomes. The
        Onboarder used to look for its "welcomed" record among a client's 50
        most recent outcomes; Retention logged one at-risk record a day, and
        on day 51 the welcome fell out of view — so the client was welcomed
        again, three months in, with "You're in — here's what happens next".
        """
        with self.conn() as cx:
            return cx.execute(
                "SELECT 1 FROM outcomes WHERE prospect_id = ? AND kind = ? LIMIT 1",
                (subject_id, kind),
            ).fetchone() is not None

    def last_outcome_at(self, subject_id: str, kinds: tuple[str, ...] = ()) -> str | None:
        """When this prospect or client last did something. Silence is a signal."""
        sql = "SELECT MAX(occurred_at) t FROM outcomes WHERE prospect_id = ?"
        args: list[Any] = [subject_id]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        with self.conn() as cx:
            row = cx.execute(sql, args).fetchone()
        return row["t"] if row and row["t"] else None

    # ---------------- research ----------------

    def save_research(self, findings: list[dict[str, Any]]) -> int:
        """Replace this cycle's findings. A finding is a current observation,
        not a log — keeping every past one would bury today's."""
        if findings is None:
            return 0
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.conn() as cx:
            cx.execute("DELETE FROM research_findings")
            for f in findings:
                cx.execute(
                    """INSERT INTO research_findings
                       (id,subject,claim,evidence,proposal,severity,confidence,created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (f"res_{uuid.uuid4().hex[:12]}", f.get("subject", ""),
                     f.get("claim", ""), f.get("evidence", ""),
                     f.get("proposal", ""), f.get("severity", "improve"),
                     f.get("confidence", "provisional"), stamp))
        return len(findings)

    def research_findings(self, subject: str = "") -> list[dict[str, Any]]:
        """Current findings, most serious first."""
        order = ("CASE severity WHEN 'blocking' THEN 0 WHEN 'improve' THEN 1 "
                 "ELSE 2 END, subject")
        with self.conn() as cx:
            if subject:
                rows = cx.execute(
                    f"SELECT * FROM research_findings WHERE subject = ? ORDER BY {order}",
                    (subject,)).fetchall()
            else:
                rows = cx.execute(
                    f"SELECT * FROM research_findings ORDER BY {order}").fetchall()
        return [dict(r) for r in rows]

    # ---------------- market findings ----------------

    def save_finding(self, f: dict[str, Any]) -> None:
        with self.conn() as cx:
            cx.execute(
                """INSERT OR REPLACE INTO market_findings
                   (id,market,label,sampled,mean_score,invisible_share,opportunity,
                    verdict,notes,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (f["id"], f["market"], f["label"], f["sampled"], f["mean_score"],
                 f["invisible_share"], f["opportunity"], f["verdict"],
                 json.dumps(f.get("notes", [])), f["created_at"]),
            )

    def latest_findings(self, limit: int = 40) -> list[dict[str, Any]]:
        """Most recent finding per market, newest first."""
        with self.conn() as cx:
            rows = cx.execute(
                """SELECT * FROM market_findings WHERE id IN (
                       SELECT id FROM market_findings m1
                       WHERE created_at = (
                           SELECT MAX(created_at) FROM market_findings m2
                           WHERE m2.market = m1.market)
                   ) ORDER BY opportunity DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["notes"] = json.loads(d.get("notes") or "[]")
            except ValueError:
                d["notes"] = []
            out.append(d)
        return out

    def explored_markets(self) -> set[str]:
        with self.conn() as cx:
            rows = cx.execute("SELECT DISTINCT market FROM market_findings").fetchall()
        return {r["market"] for r in rows}

    # ---------------- key/value ----------------

    def inbound_seen(self, message_id: str) -> bool:
        with self.conn() as cx:
            return cx.execute("SELECT 1 FROM inbound WHERE message_id = ?",
                              (message_id,)).fetchone() is not None

    def record_inbound(self, message_id: str, sender: str, kind: str,
                       prospect_id: str = "", snippet: str = "") -> None:
        """Remember a message was read, so it is handled exactly once — by
        its id, not by the mailbox's read flag, which the operator's phone
        changes every time they open their email."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.conn() as cx:
            cx.execute(
                """INSERT OR IGNORE INTO inbound
                   (message_id, sender, kind, prospect_id, received_at, handled_at, snippet)
                   VALUES (?,?,?,?,?,?,?)""",
                (message_id, sender, kind, prospect_id, now, now, snippet[:300]))

    def unmatched_inbound(self, days: int = 14) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self.conn() as cx:
            rows = cx.execute(
                """SELECT * FROM inbound WHERE kind = 'unmatched' AND handled_at >= ?
                   ORDER BY handled_at DESC""", (since,)).fetchall()
        return [dict(r) for r in rows]

    def save_site_check(self, business_id: str, check: dict[str, Any]) -> None:
        with self.conn() as cx:
            cx.execute(
                "INSERT INTO site_checks (id, business_id, checked_at, raw) VALUES (?,?,?,?)",
                (f"chk_{uuid.uuid4().hex[:12]}", business_id,
                 check.get("checked_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 json.dumps(check, default=str)))

    def site_checks(self, business_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """What the client's site showed, newest first."""
        with self.conn() as cx:
            rows = cx.execute(
                """SELECT raw FROM site_checks WHERE business_id = ?
                   ORDER BY checked_at DESC LIMIT ?""", (business_id, limit)).fetchall()
        return [json.loads(r["raw"]) for r in rows]

    # ---------------- appointments ----------------

    def add_appointment(self, prospect_id: str, kind: str, starts_at: str,
                        note: str = "") -> str:
        """A booked walkthrough ("meeting") or a promised call back ("callback")."""
        aid = f"apt_{uuid.uuid4().hex[:12]}"
        with self.conn() as cx:
            cx.execute(
                """INSERT INTO appointments (id, prospect_id, kind, starts_at, note,
                   status, created_at) VALUES (?,?,?,?,?,?,?)""",
                (aid, prospect_id, kind, starts_at, note, "open",
                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
        return aid

    def appointments(self, kind: str | None = None, status: str = "open",
                     prospect_id: str | None = None) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM appointments WHERE status = ?", [status]
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        if prospect_id:
            q += " AND prospect_id = ?"
            args.append(prospect_id)
        with self.conn() as cx:
            rows = cx.execute(q + " ORDER BY starts_at ASC", tuple(args)).fetchall()
        return [dict(r) for r in rows]

    def close_appointments(self, prospect_id: str, kind: str | None = None,
                           status: str = "done") -> int:
        q, args = "UPDATE appointments SET status = ? WHERE prospect_id = ? AND status = 'open'", \
            [status, prospect_id]
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        with self.conn() as cx:
            return cx.execute(q, tuple(args)).rowcount

    def save_citation_check(self, business_id: str, check: dict[str, Any]) -> None:
        with self.conn() as cx:
            cx.execute(
                "INSERT INTO citation_checks (id, business_id, checked_at, raw) "
                "VALUES (?,?,?,?)",
                (f"cit_{uuid.uuid4().hex[:12]}", business_id,
                 check.get("checked_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 json.dumps(check, default=str)))

    def citation_checks(self, business_id: str, limit: int = 3) -> list[dict[str, Any]]:
        """Where the business was found on the sites engines quote, newest first."""
        with self.conn() as cx:
            rows = cx.execute(
                """SELECT raw FROM citation_checks WHERE business_id = ?
                   ORDER BY checked_at DESC LIMIT ?""", (business_id, limit)).fetchall()
        return [json.loads(r["raw"]) for r in rows]

    def instance_id(self) -> str:
        """A stable id for this database — which is to say, this business
        copy. Used to tell a laptop from the server running the same business."""
        existing = self.kv_get("instance_id")
        if existing:
            return existing
        new = f"inst_{uuid.uuid4().hex[:16]}"
        self.kv_set("instance_id", new)
        return new

    def fleet_active(self, minutes: int = 30) -> bool:
        """Whether agents have been running against this database recently."""
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(
            timespec="seconds")
        with self.conn() as cx:
            return cx.execute("SELECT 1 FROM agent_runs WHERE started_at >= ? LIMIT 1",
                              (since,)).fetchone() is not None

    def kv_get(self, key: str) -> str | None:
        with self.conn() as cx:
            row = cx.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str) -> None:
        with self.conn() as cx:
            cx.execute(
                "INSERT OR REPLACE INTO kv (key,value,created_at) VALUES (?,?,?)",
                (key, value, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )

    # ---------------- ledger ----------------

    #: Restates the partial index's predicate. SQLite matches an upsert to a
    #: partial unique index only when the conflict target repeats its WHERE
    #: clause verbatim; without it the statement is rejected outright.
    _DEDUPE_TARGET = "ON CONFLICT(dedupe_key) WHERE dedupe_key IS NOT NULL AND dedupe_key != ''"

    def add_ledger(self, e: LedgerEntry) -> str:
        """Record one entry of money in or out."""
        with self.conn() as cx:
            cx.execute(
                """INSERT INTO ledger
                   (id,kind,category,amount,description,client_id,occurred_at,dedupe_key)
                   VALUES (?,?,?,?,?,?,?,NULL)
                   ON CONFLICT(id) DO UPDATE SET
                     kind=excluded.kind, category=excluded.category,
                     amount=excluded.amount, description=excluded.description,
                     client_id=excluded.client_id, occurred_at=excluded.occurred_at""",
                (e.id, e.kind, e.category, e.amount, e.description, e.client_id,
                 e.occurred_at),
            )
        return e.id

    def add_ledger_once(self, e: LedgerEntry, dedupe_key: str) -> bool:
        """Record an entry unless one carrying this key already exists.

        Returns True when the entry was written. Uniqueness is enforced by an
        index, so two callers racing cannot both win — which is the point.
        The check-then-insert this replaced ran as two separate connections,
        and a console action landing during the Bookkeeper's tick could bill
        the same client twice in one month.
        """
        if not dedupe_key:
            raise ValueError("add_ledger_once needs a dedupe key")
        with self.conn() as cx:
            cur = cx.execute(
                f"""INSERT INTO ledger
                    (id,kind,category,amount,description,client_id,occurred_at,dedupe_key)
                    VALUES (?,?,?,?,?,?,?,?)
                    {self._DEDUPE_TARGET} DO NOTHING""",
                (e.id, e.kind, e.category, e.amount, e.description, e.client_id,
                 e.occurred_at, dedupe_key),
            )
            return cur.rowcount > 0

    def has_billed(self, client_id: str, month: str) -> bool:
        """Idempotency guard: has this client already been billed this month?"""
        with self.conn() as cx:
            return cx.execute(
                """SELECT 1 FROM ledger WHERE kind='revenue' AND category='subscription'
                   AND client_id = ? AND occurred_at LIKE ?""",
                (client_id, f"{month}%"),
            ).fetchone() is not None

    def has_cost(self, category: str, month: str) -> bool:
        """Idempotency guard for recurring fixed costs."""
        with self.conn() as cx:
            return cx.execute(
                """SELECT 1 FROM ledger WHERE kind='cost' AND category = ?
                   AND occurred_at LIKE ?""",
                (category, f"{month}%"),
            ).fetchone() is not None

    def pnl(self, days: int = 30) -> dict[str, float]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self.conn() as cx:
            rows = cx.execute(
                "SELECT kind, COALESCE(SUM(amount),0) t FROM ledger WHERE occurred_at >= ? GROUP BY kind",
                (since,),
            ).fetchall()
        totals = {r["kind"]: float(r["t"]) for r in rows}
        revenue = totals.get("revenue", 0.0)
        cost = totals.get("cost", 0.0)
        return {
            "revenue": round(revenue, 2),
            "cost": round(cost, 2),
            "profit": round(revenue - cost, 2),
            "margin": round((revenue - cost) / revenue, 4) if revenue else 0.0,
        }

    def cost_breakdown(self, days: int = 30) -> dict[str, float]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self.conn() as cx:
            rows = cx.execute(
                """SELECT category, COALESCE(SUM(amount),0) t FROM ledger
                   WHERE kind='cost' AND occurred_at >= ? GROUP BY category ORDER BY t DESC""",
                (since,),
            ).fetchall()
        return {r["category"]: round(float(r["t"]), 2) for r in rows}

    # ---------------- agent runs ----------------

    def start_run(self, run: AgentRun) -> str:
        with self.conn() as cx:
            cx.execute(
                """INSERT INTO agent_runs
                   (id,agent,status,started_at,finished_at,items_processed,summary,error)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (run.id, run.agent, run.status, run.started_at, "", 0, "", ""),
            )
        return run.id

    def finish_run(self, run: AgentRun) -> None:
        with self.conn() as cx:
            cx.execute(
                """UPDATE agent_runs SET status=?, finished_at=?, items_processed=?,
                   summary=?, error=? WHERE id=?""",
                (run.status, run.finished_at, run.items_processed, run.summary,
                 run.error, run.id),
            )

    def last_success_at(self, agent: str) -> str | None:
        """When this agent last finished cleanly, or None if it never has.

        The orchestrator used to answer this by scanning the most recent 200
        runs. The fleet records roughly that many in a day, so any agent on a
        daily interval fell out of the window, looked as though it had never
        run, and was therefore due on every single tick — the opposite of the
        budget the intervals exist to enforce.
        """
        with self.conn() as cx:
            row = cx.execute(
                """SELECT MAX(finished_at) t FROM agent_runs
                   WHERE agent = ? AND status = 'ok' AND finished_at != ''""",
                (agent,),
            ).fetchone()
        return row["t"] if row and row["t"] else None

    def prune_agent_runs(self, keep_days: int = 30) -> int:
        """Drop run history past its usefulness.

        Left alone this table is the only one that grows without bound: about
        200 rows a day, forever, on a file the operator is told they can back
        up by copying it.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat(
            timespec="seconds")
        with self.conn() as cx:
            cur = cx.execute("DELETE FROM agent_runs WHERE started_at < ?", (cutoff,))
            return cur.rowcount

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.conn() as cx:
            rows = cx.execute(
                "SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def _prospect_from_raw(raw: str) -> Prospect:
    d = json.loads(raw)
    d["business"] = Business(**d["business"])
    return Prospect(**d)


def _audit_from_raw(raw: str) -> Audit:
    d = json.loads(raw)
    d["results"] = [ProbeResult(**r) for r in d.get("results", [])]
    return Audit(**d)
