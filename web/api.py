"""JSON API behind the operator console.

Every handler returns plain data; the console renders it. Handlers that
change something (approving outreach, sending, running the fleet) are POST
only and go through exactly the same guard rails as the command line — in
particular, sending still refuses while any blocking preflight check fails.
Approving from a phone must never be a way around a compliance gate.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("answerrank.api")


def _iso_age(stamp: str) -> str:
    """'4m ago' — a phone screen has no room for a timestamp."""
    if not stamp:
        return "never"
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp[:16]
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - then).total_seconds()
    if secs < 90:
        return "just now"
    for limit, div, unit in ((3600, 60, "m"), (86400, 3600, "h"), (2592000, 86400, "d")):
        if secs < limit:
            return f"{int(secs // div)}{unit} ago"
    return f"{int(secs // 2592000)}mo ago"


class Api:
    def __init__(self, store, settings):
        self.store = store
        self.settings = settings

    # ------------------------------------------------------------ reads

    def state(self) -> dict[str, Any]:
        from answerrank.agents.bookkeeper import BookkeeperAgent
        from answerrank.agents.outreach import OutreachAgent

        kpis = BookkeeperAgent(self.store, self.settings).kpis()
        blockers = OutreachAgent(self.store, self.settings).preflight()
        stages = self.store.count_prospects_by_stage()
        runs = self.store.recent_runs(12)

        agents: list[dict[str, Any]] = []
        seen = set()
        for r in runs:
            if r["agent"] in seen:
                continue
            seen.add(r["agent"])
            agents.append({
                "name": r["agent"],
                "status": r["status"],
                "summary": (r["summary"] or r["error"] or "")[:120],
                "when": _iso_age(r["started_at"]),
            })

        drafted = len(self.store.get_messages("drafted", 500))
        approved = len(self.store.get_messages("approved", 500))
        hot = sum(1 for p in self.store.get_prospects(limit=2000) if p.is_hot)

        return {
            "brand": self.settings.brand,
            "money": {
                "mrr": kpis["mrr"],
                "profit": kpis["profit"],
                "target": kpis["target"],
                "pct": min(100.0, kpis["pct_to_target"]),
                "clients": int(kpis["active_clients"]),
                "arpu": kpis["arpu"],
                "more_needed": int(kpis["more_clients_needed"]),
                "margin": round(kpis["margin"] * 100),
            },
            "queue": {
                "drafted": drafted,
                "approved": approved,
                "sent_today": self.store.sends_today(),
                "daily_cap": self.settings.outreach.max_emails_total_per_day,
            },
            "pipeline": {"stages": stages, "hot": hot,
                         "total": sum(stages.values())},
            "agents": agents,
            "blockers": blockers,
            "can_send": not blockers,
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def inbox(self, status: str = "drafted", limit: int = 25) -> dict[str, Any]:
        msgs = self.store.get_messages(status, limit)
        by_id = {p.id: p for p in self.store.get_prospects(limit=5000)}
        items = []
        for m in msgs:
            p = by_id.get(m.prospect_id)
            items.append({
                "id": m.id,
                "step": m.sequence_step,
                "subject": m.subject,
                "body": m.body,
                "business": p.business.name if p else "(unknown)",
                "market": p.business.market if p else "",
                "email": p.business.email if p else "",
                "score": p.score if p else None,
                "gap": p.competitor_gap if p else None,
                "evidence": (p.notes or "").split(" | ")[0] if p else "",
            })
        return {"items": items, "count": len(items), "status": status}

    def prospects(self, stage: str | None = None, limit: int = 40) -> dict[str, Any]:
        rows = self.store.get_prospects(stage, limit)
        return {"items": [{
            "id": p.id, "name": p.business.name, "market": p.business.market,
            "vertical": p.business.vertical, "stage": p.stage,
            "score": p.score, "gap": p.competitor_gap, "hot": p.is_hot,
        } for p in rows], "count": len(rows)}

    def reports(self) -> dict[str, Any]:
        out = Path(self.settings.output_dir) / "reports"
        if not out.exists():
            return {"items": []}
        files = sorted(out.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
        return {"items": [{
            "name": f.name,
            "when": _iso_age(datetime.fromtimestamp(f.stat().st_mtime,
                                                    timezone.utc).isoformat()),
        } for f in files[:30]]}

    # ------------------------------------------------------------ telemetry

    def telemetry(self) -> dict[str, Any]:
        """Execution traces for the ops panel.

        The research on agent observability is consistent: what matters is not
        a prettier number but the ability to see what an agent actually did —
        its inputs, its duration, its decision, its failures — and to spot
        drift before it costs you. So this returns real traces, not a summary:
        every recorded run, with wall-clock duration and the agent's own
        account of what it processed.
        """
        from answerrank.orchestrator import AGENT_ORDER

        runs = self.store.recent_runs(80)
        now = datetime.now(timezone.utc)

        def dur(r) -> float | None:
            if not (r["started_at"] and r["finished_at"]):
                return None
            try:
                a = datetime.fromisoformat(r["started_at"])
                b = datetime.fromisoformat(r["finished_at"])
            except ValueError:
                return None
            return round(max(0.0, (b - a).total_seconds()), 2)

        # Per-agent rollup, in the order the fleet actually executes them.
        specs = {cls.name: cls for cls in AGENT_ORDER}
        agents: list[dict[str, Any]] = []
        for name, cls in specs.items():
            mine = [r for r in runs if r["agent"] == name]
            last = mine[0] if mine else None
            oks = sum(1 for r in mine if r["status"] == "ok")
            since = None
            if last and last["started_at"]:
                try:
                    started = datetime.fromisoformat(last["started_at"])
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    since = round((now - started).total_seconds())
                except ValueError:
                    since = None
            agents.append({
                "name": name,
                "role": cls.description,
                "interval": cls.interval,
                "status": last["status"] if last else "idle",
                "summary": (last["summary"] or last["error"] or "") if last else "never run",
                "items": last["items_processed"] if last else 0,
                "duration": dur(last) if last else None,
                "seconds_since": since,
                "due_in": (max(0, cls.interval - since) if since is not None else 0),
                "runs": len(mine),
                "reliability": round(100 * oks / len(mine)) if mine else None,
                # Sparkline of items processed, oldest to newest.
                "history": [r["items_processed"] or 0 for r in reversed(mine[:14])],
            })

        feed = [{
            "agent": r["agent"],
            "status": r["status"],
            "text": (r["summary"] or r["error"] or "")[:160],
            "at": r["started_at"][11:19] if r["started_at"] else "",
            "duration": dur(r),
            "items": r["items_processed"] or 0,
        } for r in runs[:40]]

        # Throughput and spend, straight off the ledger and the run records.
        today = now.date().isoformat()
        todays = [r for r in runs if (r["started_at"] or "").startswith(today)]
        costs = self.store.cost_breakdown(30)

        return {
            "agents": agents,
            "feed": feed,
            "throughput": {
                "runs_today": len(todays),
                "items_today": sum(r["items_processed"] or 0 for r in todays),
                "errors_today": sum(1 for r in todays if r["status"] == "error"),
                "avg_duration": round(
                    sum(d for d in (dur(r) for r in runs[:30]) if d is not None)
                    / max(1, sum(1 for r in runs[:30] if dur(r) is not None)), 2),
            },
            "spend": {
                "api_30d": costs.get("api", 0.0),
                "total_30d": round(sum(costs.values()), 2),
                "breakdown": costs,
            },
            "pipeline": self.store.count_prospects_by_stage(),
            "clock": now.isoformat(timespec="seconds"),
        }

    # ------------------------------------------------------------ writes

    def approve(self, ids: list[str]) -> dict[str, Any]:
        wanted, n = set(ids), 0
        for m in self.store.get_messages("drafted", 500):
            if m.id in wanted:
                m.status = "approved"
                self.store.save_message(m)
                n += 1
        return {"approved": n}

    def reject(self, ids: list[str]) -> dict[str, Any]:
        """Skip a draft and stop pitching that business.

        A rejection is a judgement that this prospect should not be
        contacted, so it suppresses the prospect too — otherwise the next
        cycle drafts the same message again.
        """
        wanted, n = set(ids), 0
        by_id = {p.id: p for p in self.store.get_prospects(limit=5000)}
        for m in self.store.get_messages("drafted", 500):
            if m.id not in wanted:
                continue
            m.status = "suppressed"
            self.store.save_message(m)
            p = by_id.get(m.prospect_id)
            if p:
                p.stage = "suppressed"
                p.notes = (p.notes or "") + " | skipped by operator"
                self.store.upsert_prospect(p)
            n += 1
        return {"rejected": n}

    def send(self, limit: int = 25, dry_run: bool = False) -> dict[str, Any]:
        from answerrank.agents.outreach import OutreachAgent
        from answerrank.mailer import Mailer
        from answerrank.models import now_iso

        agent = OutreachAgent(self.store, self.settings)
        blockers = agent.preflight()
        if blockers:
            # The console is a convenience, never an override.
            return {"sent": 0, "blocked": True, "reasons": blockers}

        cap = self.settings.outreach.max_emails_total_per_day - self.store.sends_today()
        if cap <= 0:
            return {"sent": 0, "blocked": True,
                    "reasons": ["Daily sending cap reached. Try tomorrow."]}

        mailer = Mailer(self.settings)
        by_id = {p.id: p for p in self.store.get_prospects(limit=5000)}
        sent = failed = 0
        errors: list[str] = []

        for m in self.store.get_messages("approved", min(limit, cap)):
            p = by_id.get(m.prospect_id)
            if not p or not p.business.email or self.store.is_suppressed(p.business.email):
                continue
            if dry_run:
                sent += 1
                continue
            ok, detail = mailer.send(p.business.email, m.subject, m.body)
            if ok:
                m.status, m.sent_at = "sent", now_iso()
                p.touches += 1
                p.last_touch_at = now_iso()
                p.stage = "contacted" if m.sequence_step == 1 else "following_up"
                self.store.upsert_prospect(p)
                sent += 1
            else:
                failed += 1
                errors.append(f"{p.business.email}: {detail}")
                if "bounce" in detail:
                    m.status = "bounced"
                    self.store.suppress(p.business.email, detail)
            self.store.save_message(m)

        return {"sent": sent, "failed": failed, "blocked": False,
                "errors": errors[:5], "dry_run": dry_run}

    def tick(self) -> dict[str, Any]:
        from answerrank.orchestrator import Orchestrator

        lines = Orchestrator(self.store, self.settings).tick(force=True)
        return {"ran": len(lines), "lines": lines}


def json_response(payload: Any, status: str = "200 OK") -> tuple[str, bytes]:
    return status, json.dumps(payload, default=str).encode("utf-8")
