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
        """One tap from the phone. Same guard rails as the CLI, by construction."""
        from answerrank.sending import send_batch

        return send_batch(self.store, self.settings, limit=limit, dry_run=dry_run)

    def clients(self) -> dict[str, Any]:
        """Client health, worst first — the order to work them in."""
        from answerrank.agents.retention import RetentionAgent

        rows = RetentionAgent(self.store, self.settings).portfolio()
        return {
            "count": len(rows),
            "mrr": round(sum(h.mrr for h in rows), 2),
            "at_risk_mrr": round(sum(h.mrr for h in rows if h.band == "act_now"), 2),
            "clients": [{"id": h.client_id, "name": h.name, "mrr": h.mrr,
                         "score": h.score, "band": h.band, "action": h.action,
                         "signals": h.signals, "tenure_days": h.tenure_days}
                        for h in rows],
        }

    def intelligence(self) -> dict[str, Any]:
        """What the fleet has worked out: findings, volume, the next move."""
        from answerrank.agents.analyst import AnalystAgent
        from answerrank.agents.strategist import StrategistAgent

        analyst = AnalystAgent(self.store, self.settings)
        try:
            move = StrategistAgent(self.store, self.settings).recommend()
        except Exception:  # noqa: BLE001 - a panel must never fail to render
            move = None

        return {
            "learnings": analyst.learnings(),
            "funnel": analyst.funnel().__dict__,
            "by_vertical": [r for r in analyst.by_vertical() if r["sent"]],
            "by_step": [r for r in analyst.by_step() if r["sent"]],
            "volume": analyst.required_volume(
                self.settings.profit_target_monthly, None,
                self.settings.pricing.delivery_cost_monthly),
            "next_move": move,
            "pricing": [
                {"vertical": r["vertical"],
                 "label": _knowledge().get(str(r["vertical"])).label,
                 "price": r["price"], "basis": r["basis"]}
                for r in _knowledge().priced_verticals()],
        }

    def brief(self, prospect_id: str) -> dict[str, Any]:
        """The full qualification read for one prospect."""
        from answerrank import qualify

        prospect = next((p for p in self.store.get_prospects(limit=10_000)
                         if p.id == prospect_id), None)
        if not prospect:
            return {"error": "no such prospect"}
        out = qualify.brief(prospect.business, prospect.score, prospect.competitor_gap,
                            self.settings.quote_for(prospect.business.vertical))
        out["prospect_id"] = prospect.id
        out["stage"] = prospect.stage
        out["market"] = prospect.business.market
        out["email"] = prospect.business.email
        return out

    def log_reply(self, prospect_id: str, text: str) -> dict[str, Any]:
        """Record an inbound reply from the phone and draft the response.

        The most valuable thing the operator can do in a spare minute is paste
        in a reply that arrived on their phone, so this is one tap from the
        pipeline rather than a CLI command on a laptop they may not have.
        """
        from answerrank.agents.concierge import ConciergeAgent

        prospect = next((p for p in self.store.get_prospects(limit=10_000)
                         if p.id == prospect_id), None)
        if not prospect:
            return {"error": "no such prospect"}
        if not (text or "").strip():
            return {"error": "nothing to record"}

        result = ConciergeAgent(self.store, self.settings).handle_reply(prospect, text)
        draft = next((m for m in self.store.get_messages("drafted", 200)
                      if m.id == result.get("message_id")), None)
        return {
            "intent": result["intent"],
            "action": result["action"],
            "stage": prospect.stage,
            "draft": ({"id": draft.id, "subject": draft.subject, "body": draft.body}
                      if draft else None),
        }

    # ------------------------------------------------------------------
    # Everything below was reachable only from a terminal. Closing a sale in
    # particular — the single most important moment in this business — needed
    # a command line, on a machine whose owner has said plainly that they
    # cannot use one. A capability the operator cannot reach is a capability
    # the business does not have.
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """What is stopping you from operating right now."""
        from answerrank import doctor as doctor_mod

        checks = doctor_mod.run_all(self.settings, probe=False)
        passed, warned, failed, blockers = doctor_mod.summarise(checks)
        return {
            "passed": passed, "warned": warned, "failed": failed,
            "can_send": not blockers,
            "blockers": [{"name": c.name, "detail": c.detail, "fix": c.fix}
                         for c in blockers],
            "checks": [{"name": c.name, "status": c.status.lower(),
                        "detail": c.detail, "fix": c.fix, "blocking": c.blocking}
                       for c in checks],
        }

    def money(self) -> dict[str, Any]:
        """Runway, the path to the target, and what the next milestone is."""
        from answerrank.budget import (
            cumulative_monthly, load_personal, milestones, quit_threshold,
            reinvestment_split, runway_months,
        )

        personal = load_personal()
        pnl = self.store.pnl(30)
        profit = pnl.get("profit", 0.0)
        mrr = self.store.mrr()
        clients = len(self.store.get_clients("active"))
        burn = cumulative_monthly("1_first_client")
        disposable = getattr(personal, "disposable", 0.0)
        savings = getattr(personal, "savings", 0.0)

        target = self.settings.profit_target_monthly

        # Two different true answers, and showing only one of them is why the
        # panel read as broken: five clients at $5,985 MRR sat beside a headline
        # of -$138 and "0% of target".
        #
        #   booked   — what actually hit the ledger in the last 30 days. Honest,
        #              and lags badly: a client signed yesterday shows nothing.
        #   run rate — what the current client base earns in a month once
        #              billed. This is what "am I at $5,000/month?" actually
        #              asks, so it drives the meter — labelled as a run rate,
        #              never presented as money already received.
        delivery = self.settings.pricing.delivery_cost_monthly * clients
        run_rate = mrr - delivery - burn
        gauge = milestones(getattr(personal, "job_take_home", 0.0))
        upcoming = [m for m in gauge if run_rate < m["profit"]]

        return {
            "mrr": round(mrr, 2),
            "clients": clients,
            "profit_30d": round(profit, 2),
            "run_rate_profit": round(run_rate, 2),
            "revenue_30d": round(pnl.get("revenue", 0.0), 2),
            "costs_30d": round(pnl.get("costs", 0.0), 2),
            "target": target,
            "pct_to_target": round(min(100.0, max(0.0, run_rate / target * 100)), 1),
            "monthly_burn": round(burn, 2),
            "runway_months": round(runway_months(savings, burn, disposable), 1),
            "split": reinvestment_split(profit),
            "quit": quit_threshold(getattr(personal, "job_take_home", 0.0)),
            "next_milestone": upcoming[0] if upcoming else None,
            "milestones_hit": len(gauge) - len(upcoming),
            "cost_breakdown": self.store.cost_breakdown(30),
        }

    def forecast(self, adds_per_month: float = 2.0,
                 churn: float = 0.05) -> dict[str, Any]:
        """Month-by-month path to the profit target at a given close rate."""
        from answerrank.budget import cumulative_monthly

        price = self.settings.pricing.growth_monthly
        delivery = self.settings.pricing.delivery_cost_monthly
        overhead = cumulative_monthly("1_first_client")
        target = self.settings.profit_target_monthly

        rows, clients = [], float(len(self.store.get_clients("active")))
        hit_month = None
        for month in range(1, 13):
            clients = clients * (1 - churn) + adds_per_month
            revenue = clients * price
            costs = overhead + clients * delivery
            profit = revenue - costs
            if profit >= target and hit_month is None:
                hit_month = month
            rows.append({"month": month, "clients": round(clients, 1),
                         "mrr": round(revenue), "costs": round(costs),
                         "profit": round(profit), "at_target": profit >= target})
        return {"rows": rows, "target": target, "target_month": hit_month,
                "adds_per_month": adds_per_month, "churn": churn,
                "price": price}

    def win(self, prospect_id: str, plan: str = "growth") -> dict[str, Any]:
        """Convert a prospect into a paying client. The moment that matters."""
        from answerrank.models import Client, LedgerEntry

        prospect = next((p for p in self.store.get_prospects(limit=10_000)
                         if p.id == prospect_id), None)
        if not prospect:
            return {"error": "no such prospect"}
        if prospect.stage == "won":
            return {"error": f"{prospect.business.name} is already a client"}

        price = self.settings.pricing.plan_price(plan)
        if not price:
            return {"error": f"unknown plan {plan!r}"}

        client = Client(business=prospect.business, plan=plan, mrr=price,
                        status="active")
        self.store.upsert_client(client)

        prospect.stage = "won"
        prospect.notes = (prospect.notes or "") + f" | won on {plan} at ${price:,.0f}"
        self.store.upsert_prospect(prospect)
        self.store.record_outcome(
            prospect_id=prospect.id, vertical=prospect.business.vertical,
            step=prospect.touches, kind="won", note=f"{plan} ${price:,.0f}")

        return {
            "client_id": client.id,
            "name": prospect.business.name,
            "plan": plan,
            "mrr": price,
            "total_mrr": round(self.store.mrr(), 2),
            "clients": len(self.store.get_clients("active")),
            "next": ("The Auditor will run their first full audit on the next "
                     "cycle, and the Fixer will build month 1 of their plan."),
        }

    def log_expense(self, category: str, amount: float, description: str = "",
                    revenue: bool = False) -> dict[str, Any]:
        """Record money in or out without opening a terminal."""
        from answerrank.models import LedgerEntry

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return {"error": "amount must be a number"}
        if amount <= 0:
            return {"error": "amount must be positive"}
        if not category.strip():
            return {"error": "a category is required"}

        self.store.add_ledger(LedgerEntry(
            kind="revenue" if revenue else "cost",
            category=category.strip(), amount=amount,
            description=description.strip()))
        return {"ok": True, "kind": "revenue" if revenue else "cost",
                "amount": amount, "pnl": self.store.pnl(30)}

    def research(self, refresh: bool = False) -> dict[str, Any]:
        """What each agent's researcher found about that agent's own work."""
        from answerrank import research as research_mod
        from answerrank.agents.researcher import ResearcherAgent

        if refresh:
            ResearcherAgent(self.store, self.settings).execute()
        findings = self.store.research_findings()
        return {
            "findings": findings,
            "blocking": sum(1 for f in findings if f["severity"] == "blocking"),
            "researchers": [{"subject": c.subject, "question": c.question}
                            for c in research_mod.RESEARCHERS],
        }

    def markets(self) -> dict[str, Any]:
        """Candidate trades we do not serve yet, and what has been measured."""
        from answerrank import markets as markets_mod

        price = self.settings.pricing.growth_monthly
        findings = {f["market"]: f for f in self.store.latest_findings()}
        rows = []
        for c in markets_mod.ranked(price):
            found = findings.get(c.key)
            rows.append({
                "key": c.key, "label": c.label,
                "score": c.score(price), "verdict": c.verdict(price),
                "avg_ticket": c.avg_ticket, "basis": c.basis,
                "needs_research": c.needs_research,
                "measured": bool(found),
                "invisible_share": (found or {}).get("invisible_share"),
                "sampled": (found or {}).get("sampled"),
            })
        return {"candidates": rows, "price": price}

    def tick(self) -> dict[str, Any]:
        from answerrank.orchestrator import Orchestrator

        lines = Orchestrator(self.store, self.settings).tick(force=True)
        return {"ran": len(lines), "lines": lines}


def _knowledge():
    from answerrank import knowledge
    return knowledge


def _finite(value: Any) -> Any:
    """Replace values JSON cannot express with ones a browser can parse.

    Python happily writes `Infinity` and `NaN`; `JSON.parse` rejects both, so
    one infinite runway figure takes down the whole panel with a parse error
    and no visible cause. Runway legitimately is infinite when income already
    covers the burn, so this is not a rounding edge case — it is the healthy
    path. Infinity becomes null and the caller renders it as such.
    """
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


def to_json(payload: Any) -> bytes:
    """The one JSON writer for the whole web layer.

    There were two — this one, which nothing called, and a copy inside the
    WSGI app that every endpoint actually used. The dead one is gone rather
    than left to drift, which is how the last four bugs of this shape started.
    """
    return json.dumps(_finite(payload), default=str).encode("utf-8")
