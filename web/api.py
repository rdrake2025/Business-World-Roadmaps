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

    def prospects(self, stage: str | None = None, limit: int = 40,
                  hot: bool = False, q: str = "") -> dict[str, Any]:
        """Prospects for the phone, most relevant first.

        This used to return the oldest ``limit`` records in the stage, and
        the console filtered those for hot leads. Someone who replied
        yesterday — the most important person in the pipeline — sat outside
        the oldest forty and never appeared, so there was no way from the
        phone to log their reply or sign them up.
        """
        rows = self.store.get_prospects(stage, 10_000)
        if hot:
            rows = [p for p in rows if p.is_hot]
        # A reply arrives with a name and an address on it. Either finds them.
        needle = (q or "").strip().lower()
        if needle:
            rows = [p for p in rows
                    if needle in p.business.name.lower()
                    or needle in (p.business.email or "").lower()
                    or needle in (p.business.domain or "")]
        rows.sort(key=lambda p: p.last_touch_at or p.created_at, reverse=True)
        rows = rows[:limit]
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

    def send(self, limit: int = 25, dry_run: bool = False,
             background: bool = False) -> dict[str, Any]:
        """One tap from the phone. Same guard rails as the CLI, by construction.

        ``background`` is how the phone calls it. Sends are paced 90 seconds
        apart, so a batch of 25 takes over half an hour — and it used to run
        inside the web request, which the phone gave up on long before it
        finished: the button looked broken while the emails trickled out
        behind it. Now it checks the blockers, starts the batch, and answers
        straight away with how long it will take.
        """
        import threading

        from answerrank.agents.outreach import OutreachAgent
        from answerrank.sending import send_batch

        if not background or dry_run:
            return send_batch(self.store, self.settings, limit=limit, dry_run=dry_run)

        blockers = OutreachAgent(self.store, self.settings).preflight()
        if blockers:
            return {"sent": 0, "blocked": True, "reasons": blockers, "background": True}
        queued = min(limit, len(self.store.send_queue(limit)))
        if not queued:
            return {"sent": 0, "blocked": False, "background": True,
                    "reasons": ["No approved messages. Approve some first."]}

        def run() -> None:
            try:
                result = send_batch(self.store, self.settings, limit=limit)
                log.info("background send finished: %s sent, %s failed",
                         result.get("sent"), result.get("failed"))
            except Exception:  # noqa: BLE001 - never kill the server thread
                log.exception("background send failed")

        threading.Thread(target=run, daemon=True, name="answerrank-send").start()
        gap = self.settings.outreach.min_seconds_between_sends
        minutes = max(1, round(queued * gap / 60))
        return {"sent": 0, "blocked": False, "background": True, "queued": queued,
                "reasons": [f"Sending {queued} now, one every {gap}s — about "
                            f"{minutes} min. You can close this; it keeps going."]}

    def clients(self) -> dict[str, Any]:
        """Client health, worst first — the order to work them in."""
        from answerrank.agents.retention import RetentionAgent

        from answerrank import payments

        rows = RetentionAgent(self.store, self.settings).portfolio()
        return {
            "awaiting_payment": payments.waiting_summary(self.store, self.settings),
            "count": len(rows),
            "mrr": round(sum(h.mrr for h in rows), 2),
            "at_risk_mrr": round(sum(h.mrr for h in rows if h.band == "act_now"), 2),
            "clients": [{"id": h.client_id, "name": h.name, "mrr": h.mrr,
                         "score": h.score, "band": h.band, "action": h.action,
                         "signals": h.signals, "tenure_days": h.tenure_days,
                         **self._client_files(h.client_id)}
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
        """They said yes. The moment that matters — and not yet the money.

        A client is created *awaiting payment*. They are welcomed, audited and
        counted as revenue once the payment arrives, not before: until this
        build, Won made a client active on the spot and the P&L counted
        money nobody had sent. A pilot is free and starts immediately.
        """
        from answerrank import payments
        from answerrank.models import Client, OutreachMessage, now_iso

        prospect = next((p for p in self.store.get_prospects(limit=10_000)
                         if p.id == prospect_id), None)
        if not prospect:
            return {"error": "no such prospect"}
        if prospect.stage == "won":
            return {"error": f"{prospect.business.name} is already a client"}

        plan = (plan or "growth").lower()
        if plan not in self.settings.pricing.PLANS:
            return {"error": f"unknown plan {plan!r}"}
        price = self.settings.pricing.plan_price(plan)
        pilot = plan == "pilot"

        client = Client(business=prospect.business, plan=plan, mrr=price,
                        status="active" if pilot else "awaiting_payment")
        client_id, created = self.store.start_client(client)
        if not created:
            return {"error": f"{prospect.business.name} is already on the books"}
        client.id = client_id

        prospect.stage = "won"
        prospect.notes = (prospect.notes or "") + f" | won on {plan} at ${price:,.0f}"
        self.store.upsert_prospect(prospect)
        self.store.withdraw_cold(prospect.id)
        self.store.record_outcome(
            prospect_id=prospect.id, vertical=prospect.business.vertical,
            step=prospect.touches, kind="won", note=f"{plan} ${price:,.0f}")

        link = "" if pilot else payments.link_for(
            self.settings, plan, payments.reference_for(prospect, client),
            prospect.business.email)
        if link and not payments.link_already_sent(self.store, prospect,
                                                   self.settings, plan):
            subject, body = payments.payment_email(prospect, client, self.settings)
            self.store.save_message(OutreachMessage(
                prospect_id=prospect.id, subject=subject, body=body, kind="invoice",
                sequence_step=0, status="drafted", scheduled_for=now_iso()))

        if pilot:
            nxt = ("A free pilot starts now: welcome, first audit and month-1 plan "
                   "on the next cycle. Use it to prove the work moves the score.")
        elif link:
            nxt = ("The payment link is in your inbox to approve. They go live — "
                   "welcome, audit, plan — the moment it's paid.")
        else:
            nxt = (f"No payment link is set up for {plan}. Send them an invoice for "
                   f"${price:,.0f}, then tap Paid when it arrives. (Add a link in "
                   f"answerrank.yml under payment_links to skip this next time.)")
        return {
            "client_id": client_id,
            "name": prospect.business.name,
            "plan": plan,
            "mrr": price,
            "status": client.status,
            "payment_link": link,
            "total_mrr": round(self.store.mrr(), 2),
            "clients": len(self.store.get_clients("active")),
            "next": nxt,
        }

    def _client_files(self, client_id: str) -> dict[str, Any]:
        """Links to open this client's latest report and files on the phone,
        and what their website showed when last checked."""
        from answerrank.sitecheck import SiteCheck

        client = self.store.get_client(client_id)
        if client is None:
            return {"report_url": "", "files": [], "site": []}
        files, report = [], ""
        for audit in self.store.audit_history(client.business.id, limit=3,
                                              comparable=True):
            for d in self.store.get_deliverables(audit.id):
                if d.kind == "report_html":
                    report = report or f"/files/report/{client.id}"
                elif not any(f["title"] == d.title for f in files):
                    files.append({"title": d.title.split(" — ")[0],
                                  "url": f"/files/file/{d.id}"})
            if files:
                break
        if client.plan == "pilot" or len(self.store.audit_history(
                client.business.id, limit=2, comparable=True)) >= 2:
            files.insert(0, {"title": "Before & after (case study)",
                             "url": f"/files/case/{client.id}"})
        checks = self.store.site_checks(client.business.id, limit=1)
        return {"report_url": report, "files": files,
                "site": SiteCheck.from_dict(checks[0]).lines() if checks else []}

    def mark_paid(self, client_id: str) -> dict[str, Any]:
        """The money arrived. They go live."""
        from answerrank import payments

        client = self.store.get_client(client_id)
        if not client:
            return {"error": "no such client"}
        if client.status == "active" and client.paid_at:
            return {"error": f"{client.business.name} is already marked paid"}
        payments.mark_paid(self.store, client)
        return {"ok": True, "name": client.business.name,
                "total_mrr": round(self.store.mrr(), 2),
                "next": "Welcome email is drafted on the next cycle."}

    # ------------------------------------------------------------------ calls

    def _prospect(self, prospect_id: str):
        return next((p for p in self.store.get_prospects(limit=10_000)
                     if p.id == prospect_id), None)

    def calls(self) -> dict[str, Any]:
        """Who to ring now, best first."""
        from answerrank import calls
        return calls.call_list(self.store, self.settings)

    def call_sheet(self, prospect_id: str) -> dict[str, Any]:
        """Everything needed on one screen while the phone rings."""
        from answerrank import calls, knowledge

        prospect = self._prospect(prospect_id)
        if prospect is None:
            return {"error": "no such prospect"}
        audit = self.store.get_audit(prospect.last_audit_id) if prospect.last_audit_id \
            else next(iter(self.store.audit_history(prospect.business.id, limit=1)), None)
        ev = calls.evidence(audit)
        local = calls.local_time(prospect.business.state)
        return {
            "id": prospect.id, "name": prospect.business.name,
            "market": prospect.business.market,
            "trade": knowledge.get(prospect.business.vertical).label,
            "phone": calls.pretty_number(prospect.business.phone),
            "dial": calls.dial_number(prospect.business.phone),
            "email": prospect.business.email,
            "local": local.strftime("%I:%M %p").lstrip("0").lower() if local else "",
            "window": calls.window(local),
            "evidence": ev, "script": calls.script(prospect, ev, self.settings),
            "outcomes": [{"key": o.key, "label": o.label}
                         for o in calls.OUTCOMES.values()],
        }

    def log_call(self, prospect_id: str, outcome: str, email: str = "",
                 note: str = "") -> dict[str, Any]:
        from answerrank import calls

        prospect = self._prospect(prospect_id)
        if prospect is None:
            return {"error": "no such prospect"}
        return calls.log_call(self.store, self.settings, prospect, outcome, email, note)

    #: Where a prospect already is in the cold sequence. Adding someone you
    #: know by hand takes them out of it.
    _COLD_STAGES = {"discovered", "audited", "queued", "contacted", "following_up"}

    def add_business(self, name: str, city: str, state: str = "", vertical: str = "",
                     website: str = "", email: str = "", phone: str = "") -> dict[str, Any]:
        """A business the operator knows — a pilot, a referral, a friend's firm.

        Every prospect used to come from the Scout, so the first clients the
        launch plan calls for, the two or three pilots found through people
        the operator knows, could not be signed up: Sign them up works on a
        prospect, and there was no way to make one. They go straight to
        ``replied``, the stage where a person has the conversation, so the
        outreach agents never send them a cold email.
        """
        from answerrank import knowledge
        from answerrank.models import Business, Prospect

        name, city = (name or "").strip(), (city or "").strip()
        if not name or not city:
            return {"error": "a name and a town are needed"}
        vertical = (vertical or "").strip().lower() or "hvac"
        if vertical not in knowledge.VERTICALS:
            return {"error": f"unknown trade {vertical!r}"}
        website = (website or "").strip()
        if website and not website.startswith(("http://", "https://")):
            website = "https://" + website
        email = (email or "").strip()
        if email and "@" not in email:
            return {"error": f"{email!r} is not an email address"}

        biz = Business(name=name, city=city, state=(state or "").strip().upper()[:2],
                       vertical=vertical, website=website, email=email,
                       phone=(phone or "").strip())
        existing = next((p for p in self.store.get_prospects(limit=10_000)
                         if (biz.domain and p.business.domain == biz.domain)
                         or (p.business.name.lower() == name.lower()
                             and p.business.city.lower() == city.lower())), None)
        if existing is not None:
            if existing.stage == "won":
                return {"error": f"{existing.business.name} is already a client"}
            if existing.stage == "suppressed":
                return {"error": f"{existing.business.name} asked not to be emailed, "
                                 f"or their address bounced. Talk to them first."}
            if existing.stage in self._COLD_STAGES:
                self.store.withdraw_cold(existing.id)
                existing.stage = "replied"
                existing.notes = (existing.notes or "") + " | added by hand: someone you know"
                self.store.upsert_prospect(existing)
            return {"ok": True, "id": existing.id, "name": existing.business.name,
                    "stage": existing.stage, "existing": True}

        prospect = Prospect(business=biz, stage="replied",
                            notes="added by hand: someone you know")
        self.store.upsert_prospect(prospect)
        return {"ok": True, "id": prospect.id, "name": biz.name,
                "stage": prospect.stage, "existing": False}

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
