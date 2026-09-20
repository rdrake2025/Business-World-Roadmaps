"""SQLite persistence.

One file, no migrations framework, no server. The whole business state is a
single portable ``.db`` file that can be backed up with ``cp``. Tables store
their rich fields as JSON blobs so the schema never blocks a product change.
"""

from __future__ import annotations

import json
import sqlite3
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
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_message_status ON messages(status);

CREATE TABLE IF NOT EXISTS ledger (
    id TEXT PRIMARY KEY, kind TEXT, category TEXT, amount REAL,
    description TEXT, client_id TEXT, occurred_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ledger_time ON ledger(occurred_at);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY, agent TEXT, status TEXT, started_at TEXT,
    finished_at TEXT, items_processed INTEGER, summary TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS idx_run_agent ON agent_runs(agent, started_at);

CREATE TABLE IF NOT EXISTS market_findings (
    id TEXT PRIMARY KEY, market TEXT, label TEXT, sampled INTEGER,
    mean_score REAL, invisible_share REAL, opportunity REAL, verdict TEXT,
    notes TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_market_time ON market_findings(market, created_at);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS suppression (
    email TEXT PRIMARY KEY, reason TEXT, created_at TEXT
);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as cx:
            cx.executescript(SCHEMA)

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

    # ---------------- prospects ----------------

    def upsert_prospect(self, p: Prospect) -> str:
        b = p.business
        with self.conn() as cx:
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

    def get_audit(self, audit_id: str) -> Audit | None:
        with self.conn() as cx:
            row = cx.execute("SELECT raw FROM audits WHERE id = ?", (audit_id,)).fetchone()
        return _audit_from_raw(row["raw"]) if row else None

    def audit_history(self, business_id: str, limit: int = 12) -> list[Audit]:
        with self.conn() as cx:
            rows = cx.execute(
                "SELECT raw FROM audits WHERE business_id = ? ORDER BY created_at DESC LIMIT ?",
                (business_id, limit),
            ).fetchall()
        return [_audit_from_raw(r["raw"]) for r in rows]

    def save_deliverable(self, d: Deliverable) -> str:
        with self.conn() as cx:
            cx.execute(
                """INSERT OR REPLACE INTO deliverables
                   (id,audit_id,business_id,kind,title,body,filename,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (d.id, d.audit_id, d.business_id, d.kind, d.title, d.body, d.filename, d.created_at),
            )
        return d.id

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
                   (id,prospect_id,subject,body,sequence_step,status,scheduled_for,sent_at,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (m.id, m.prospect_id, m.subject, m.body, m.sequence_step, m.status,
                 m.scheduled_for, m.sent_at, m.created_at),
            )
        return m.id

    def get_messages(self, status: str | None = None, limit: int = 200) -> list[OutreachMessage]:
        q = "SELECT * FROM messages"
        args: tuple = ()
        if status:
            q += " WHERE status = ?"
            args = (status,)
        with self.conn() as cx:
            rows = cx.execute(q + " ORDER BY created_at ASC LIMIT ?", args + (limit,)).fetchall()
        return [OutreachMessage(**{k: r[k] for k in r.keys()}) for r in rows]

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

    def add_ledger(self, e: LedgerEntry) -> str:
        with self.conn() as cx:
            cx.execute(
                """INSERT OR REPLACE INTO ledger
                   (id,kind,category,amount,description,client_id,occurred_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (e.id, e.kind, e.category, e.amount, e.description, e.client_id, e.occurred_at),
            )
        return e.id

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
