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
from datetime import datetime, timedelta, timezone
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
        # The web server and the fleet can be separate processes on the
        # server; each carries the Autopilot switch into what it offers.
        from answerrank import automation
        try:
            automation.sync(store, settings)
        except Exception:  # noqa: BLE001 - a fresh database has no kv table yet
            pass

    # ------------------------------------------------------------ reads

    def state(self) -> dict[str, Any]:
        from answerrank.agents.bookkeeper import BookkeeperAgent
        from answerrank.agents.outreach import OutreachAgent
        from answerrank.mailer import SMTPConfig

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
            "mailbox": SMTPConfig.from_env().configured(),
            "pilots": self.pilots(),
            "pilot_calendar": "/files/dates/answerrank-pilots.ics",
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def pilots(self) -> list[dict[str, Any]]:
        """Each pilot's measurements so far, and when the next things happen.

        On the $5 path (PILOTS.md) the pilots are the whole business, and
        nothing said how they were doing: not the first score, not when the
        next measurement runs, not when the before-and-after can be read.
        """
        from answerrank.casestudy import MIN_DAYS

        def day(iso: str, plus: int = 0) -> str:
            try:
                d = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(days=plus)
            except ValueError:
                return ""
            return d.strftime("%d %b").lstrip("0")

        out = []
        for c in self.store.get_clients("active"):
            if c.plan != "pilot":
                continue
            audits = self.store.audit_history(c.business.id, limit=24, comparable=True)
            from answerrank import sales
            ends = sales.pilot_ends(c)
            plan = sales.offer_plan(self.settings, c.business.vertical)
            item: dict[str, Any] = {"id": c.id, "name": c.business.name,
                                    "measured": len(audits), "ends_on": day(ends + "T00:00:00+00:00"),
                                    "offer": f"{plan.capitalize()}, ${self.settings.pricing.plan_price(plan):,.0f}/mo"}
            if audits:
                first, last = audits[-1], audits[0]
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(first.created_at.replace("Z", "+00:00"))).days
                item.update(
                    first_score=round(first.score), first_on=day(first.created_at),
                    latest_score=round(last.score), latest_on=day(last.created_at),
                    # The Auditor measures a client again once their last full
                    # audit is 28 days old, while AnswerRank is open.
                    next_on=day(last.created_at, 28),
                    case_on=day(first.created_at, MIN_DAYS),
                    case_ready=age >= MIN_DAYS and len(audits) >= 2,
                    case_url=f"/files/case/{c.id}")
            out.append(item)
        return out

    #: What each kind of draft is, in the words on its badge.
    KIND_LABEL = {"pilot_offer": "end of their free pilot",
                  "reply": "answer to their reply", "report": "report they asked for",
                  "welcome": "welcome", "invoice": "payment link",
                  "client_report": "monthly report", "client_care": "check-in"}

    def inbox(self, status: str = "drafted", limit: int = 25) -> dict[str, Any]:
        """Drafts in the order to read them: answers to people who wrote in,
        then first emails, then follow-ups."""
        msgs = self.store.get_messages(status, 1000)
        msgs.sort(key=lambda m: (0 if (m.kind or "cold") != "cold" else
                                 1 if m.sequence_step <= 1 else 2, m.created_at))
        total = len(msgs)
        followups = sum(1 for m in msgs if (m.kind or "cold") == "cold" and m.sequence_step > 1)
        msgs = msgs[:limit]
        by_id = {p.id: p for p in self.store.get_prospects(limit=5000)}
        from answerrank import drafts

        items = []
        for m in msgs:
            p = by_id.get(m.prospect_id)
            core, footer = drafts.split(m.body)
            asked = ""
            if (m.kind or "cold") != "cold":
                row = next((r for r in self.store.outcomes_for(m.prospect_id, 20)
                            if r.get("kind") == "escalated"
                            and (r.get("note") or "").startswith("Needs your answer")), None)
                asked = (row.get("note") or "")[len("Needs your answer: "):] if row else ""
            items.append({
                "id": m.id,
                "step": m.sequence_step,
                "subject": m.subject,
                "body": m.body,
                "text": drafts.unwrap(core),
                "footer": footer.strip(),
                "asked": asked,
                "business": p.business.name if p else "(unknown)",
                "market": p.business.market if p else "",
                "email": p.business.email if p else "",
                "score": p.score if p else None,
                "gap": p.competitor_gap if p else None,
                "evidence": (p.notes or "").split(" | ")[0] if p else "",
                "kind": m.kind or "cold",
                "kind_label": self.KIND_LABEL.get(m.kind or "cold",
                                                  "first email" if m.sequence_step <= 1
                                                  else f"follow-up {m.sequence_step}"),
            })
        return {"items": items, "count": len(items), "total": total,
                "followups": followups, "status": status}

    def approve_followups(self) -> dict[str, Any]:
        """Every drafted follow-up at once: same template, same checks."""
        ids = [m.id for m in self.store.get_messages("drafted", 1000)
               if (m.kind or "cold") == "cold" and m.sequence_step > 1]
        return self.approve(ids)

    # ------------------------------------------------------------------ today

    def autopilot(self, action: str = "", stage: str = "") -> dict[str, Any]:
        """Readiness, what's paused, and the switch. Resume is one tap."""
        from answerrank import automation, autopilot
        if action == "resume" and stage in automation.STAGES:
            automation.resume(self.store, stage)
            from datetime import datetime, timedelta, timezone
            from answerrank.agents.guardian import GRACE_DAYS
            self.store.kv_set("guardian.kind." + stage, "")
            self.store.kv_set("guardian.grace." + stage, (
                datetime.now(timezone.utc) + timedelta(days=GRACE_DAYS)).isoformat(
                    timespec="seconds"))
        elif action in {"on", "off"}:
            automation.set_switch(self.store, "autopilot", action == "on")
            automation.sync(self.store, self.settings)
        return autopilot.cached(self.store, self.settings)

    def answers(self, action: str = "", message_id: str = "", triggers: str = "",
                answer_id: str = "") -> dict[str, Any]:
        """Answers you wrote, saved for next time: list, save, delete."""
        import re

        from answerrank import drafts
        if action == "save":
            m = self.store.get_message(message_id)
            words = [w.strip() for w in re.split(r"[,\n]", triggers or "") if len(w.strip()) >= 3]
            if m is None:
                return {"error": "That email isn't here any more."}
            if not words:
                return {"error": "Give at least one word or phrase that should trigger it."}
            paragraphs = [p for p in drafts.editable(m.body).split("\n\n") if p.strip()]
            brand = (self.settings.brand or "").lower()
            site = (self.settings.website or "").lower()
            keep = [p for p in paragraphs
                    if not re.match(r"^\s*(hi|hello|hey|dear)\b[^\n]{0,30}$", p, re.I)
                    and not (brand and p.strip().lower().startswith(brand))
                    and not (site and site in p.lower())
                    and "buy.stripe.com" not in p
                    and "pick 15 minutes" not in p.lower()]
            if not keep:
                return {"error": "There's no answer in that email to save."}
            asked = next((r.get("note", "")[len("Needs your answer: "):]
                          for r in self.store.outcomes_for(m.prospect_id, 20)
                          if r.get("kind") == "escalated"), "")
            aid = self.store.save_answer(words, "\n\n".join(keep), asked)
            return {"ok": True, "id": aid, "triggers": words}
        if action == "delete":
            return {"ok": self.store.delete_answer(answer_id)}
        return {"items": [{"id": a["id"], "triggers": a["triggers"], "text": a["text"],
                           "asked": a.get("asked") or "", "uses": a.get("uses") or 0}
                          for a in self.store.saved_answers()]}

    _SELFTEST = {"running": False}

    def selftest(self, run: bool = False) -> dict[str, Any]:
        """Start the live test on the server, or say how the last one went.
        It takes a minute or two (it waits for its own email), so it runs in
        the background and the phone asks again."""
        import threading

        from answerrank import selftest
        if run and not Api._SELFTEST["running"]:
            Api._SELFTEST["running"] = True

            def go() -> None:
                try:
                    selftest.run(self.store, self.settings)
                finally:
                    Api._SELFTEST["running"] = False
            threading.Thread(target=go, daemon=True, name="answerrank-selftest").start()
        return {"running": Api._SELFTEST["running"], "last": selftest.last(self.store)}

    def week(self) -> dict[str, Any]:
        from answerrank import weekly
        return weekly.review(self.store, self.settings)

    def next_up(self) -> dict[str, Any]:
        from answerrank import today
        return today.next_actions(self.store, self.settings)

    def automation(self, key: str = "", on: bool | None = None) -> dict[str, Any]:
        from answerrank import automation
        from answerrank.agents import sender
        if key:
            if key not in automation.SWITCHES:
                return {"error": f"unknown switch {key!r}"}
            automation.set_switch(self.store, key, bool(on))
            automation.sync(self.store, self.settings)
        return {"switches": automation.state(self.store),
                "status": sender.status(self.store, self.settings)}

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
        """Approve drafts. Answers to people go out about a minute later
        (after the Undo window) rather than at the next quarter hour."""
        from answerrank import sending
        from answerrank.models import now_iso

        from answerrank import automation

        wanted, n, warm, first = set(ids), 0, False, 0
        for m in self.store.get_messages("drafted", 1000):
            if m.id in wanted:
                m.status, m.approved_at = "approved", now_iso()
                self.store.save_message(m)
                n += 1
                warm = warm or (m.kind or "cold") != "cold"
                first += (m.kind or "cold") == "cold" and m.sequence_step <= 1
        # Each first email you read yourself counts toward Autopilot's start.
        automation.note_supervised(self.store, first)
        soon = sending.kick(self.store, self.settings) if warm else False
        return {"approved": n, "sending_soon": soon}

    def edit(self, message_id: str, subject: str, text: str) -> dict[str, Any]:
        """Change a draft's words. The legal footer is kept as it was, and a
        cold email is checked again exactly as the Outreach agent checks it."""
        from answerrank import drafts
        from answerrank.models import now_iso

        m = self.store.get_message(message_id)
        if m is None:
            return {"error": "That email isn't here any more."}
        if m.status not in {"drafted", "approved"}:
            return {"error": "That one has already gone, so it can't be changed."}
        body = drafts.rebuild(text, m.body)
        problems = drafts.problems(m, body)
        if problems:
            return {"error": problems[0]}
        m.subject = " ".join((subject or m.subject).split())[:150] or m.subject
        m.body = body
        if m.status == "approved":
            m.approved_at = now_iso()
        self.store.save_message(m)
        return {"ok": True, "id": m.id, "subject": m.subject, "body": m.body,
                "text": drafts.editable(m.body)}

    def undo(self, message_id: str) -> dict[str, Any]:
        """Take back the last decision on an email: an approval, while it
        hasn't gone yet, or a skip, including the business it stopped."""
        import json

        m = self.store.get_message(message_id)
        if m is None:
            return {"error": "That email isn't here any more."}
        if m.status == "approved":
            m.status, m.approved_at = "drafted", ""
            self.store.save_message(m)
            return {"ok": True, "status": "drafted",
                    "label": "Pulled back. It's in your drafts again."}
        if m.status == "sent" and self.store.kv_get(f"byhand.{m.id}"):
            m.status, m.sent_at = "drafted", ""
            self.store.save_message(m)
            self.store.kv_set(f"byhand.{m.id}", "")
            return {"ok": True, "status": "drafted", "label": "Back in your drafts."}
        if m.status == "sent":
            return {"error": "That one has already gone."}
        raw = self.store.kv_get(f"undo.{m.id}") or ""
        if m.status in {"suppressed", "superseded"} and raw:
            snap = json.loads(raw)
            m.status = "drafted"
            self.store.save_message(m)
            p = self._prospect(m.prospect_id)
            if p and snap.get("stage"):
                p.stage, p.notes = snap["stage"], snap.get("notes") or ""
                self.store.upsert_prospect(p)
            self.store.kv_set(f"undo.{m.id}", "")
            return {"ok": True, "status": "drafted", "label": "Back in your drafts."}
        return {"error": "Nothing to undo for that one."}

    def convert_pilot(self, client_id: str, plan: str = "") -> dict[str, Any]:
        """A pilot said yes to a paid plan."""
        from answerrank import sales

        client = self.store.get_client(client_id)
        if client is None:
            return {"error": "That client isn't here any more."}
        done = sales.convert_pilot(self.store, self.settings, client, plan)
        if done.get("error"):
            return done
        price = f"${done['mrr']:,.0f}"
        if done["payment_link"] and done["email"]:
            nxt = f"The payment link for {price}/month goes to {done['email']} shortly."
        elif done["payment_link"]:
            nxt = ("The payment link is in the Inbox: Copy text, send it to them, then "
                   "I sent it myself. They go live the moment it's paid.")
        else:
            nxt = (f"No payment link is set up yet. Send them an invoice for {price}, "
                   f"then tap Paid on the Clients tab when it arrives.")
        return {**done, "next": nxt}

    def sent_by_hand(self, message_id: str) -> dict[str, Any]:
        """You sent it yourself: from your own email, by text, in person.

        On the $5 pilot path there is no mailbox, so a pilot's welcome sat in
        the drafts for good and was reported as blocking every day. "I'll
        handle it" cleared it but recorded it as never sent, so a report you
        had sent by hand could be sent again. First emails to strangers can't
        be marked this way: only the send path adds the unsubscribe link and
        keeps to the warm-up.
        """
        from answerrank.models import now_iso

        m = self.store.get_message(message_id)
        if m is None:
            return {"error": "That email isn't here any more."}
        if (m.kind or "cold") == "cold":
            return {"error": "First emails go out through AnswerRank, so the "
                             "unsubscribe link and the daily limit apply."}
        if m.status not in {"drafted", "approved"}:
            return {"error": "That one has already gone."}
        m.status, m.sent_at, m.approved_at = "sent", now_iso(), ""
        self.store.save_message(m)
        self.store.kv_set(f"byhand.{m.id}", m.sent_at)
        p = self._prospect(m.prospect_id)
        if p is not None:
            p.last_touch_at = m.sent_at
            self.store.upsert_prospect(p)
        return {"ok": True, "status": "sent", "label": "Marked as sent by you."}

    def reject(self, ids: list[str]) -> dict[str, Any]:
        """Skip a draft.

        Skipping a cold email is a judgement that this business should not
        be contacted, so it suppresses the prospect too — otherwise the next
        cycle drafts the same message again. Skipping an answer to someone
        who wrote in only means you'll answer them yourself: it must never
        stop a hot lead.
        """
        import json

        wanted, n = set(ids), 0
        by_id = {p.id: p for p in self.store.get_prospects(limit=5000)}
        for m in self.store.get_messages("drafted", 1000):
            if m.id not in wanted:
                continue
            p = by_id.get(m.prospect_id)
            warm = (m.kind or "cold") != "cold"
            self.store.kv_set(f"undo.{m.id}", json.dumps(
                {"stage": "" if warm or not p else p.stage,
                 "notes": "" if warm or not p else p.notes}))
            if warm:
                m.status = "superseded"
                self.store.save_message(m)
                n += 1
                continue
            m.status = "suppressed"
            self.store.save_message(m)
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

        # The same world checks the automatic sender makes. The phone's Send
        # used to skip them, so a tap could send from a domain Gmail and
        # Outlook didn't trust yet, or with an unsubscribe link that led
        # nowhere.
        live: list[str] = []
        if not dry_run and not getattr(self.settings, "demo_mode", False):
            from answerrank.agents.sender import SenderAgent
            live = SenderAgent(self.store, self.settings).live_blockers()
            if live:
                return {"sent": 0, "blocked": True, "reasons": live,
                        "background": background}

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
        from answerrank import sales

        prospect = self._prospect(prospect_id)
        if not prospect:
            return {"error": "no such prospect"}
        done = sales.sign_up(self.store, self.settings, prospect, plan)
        if done.get("error"):
            return done
        client, client_id, plan, price = done["client"], done["client_id"], done["plan"], \
            done["mrr"]
        link, email, pilot = done["payment_link"], done["email"], done["pilot"]

        from answerrank import automation
        if pilot:
            nxt = ("A free pilot starts now: welcome, first audit and month-1 plan "
                   "on the next cycle. Use it to prove the work moves the score.")
        elif link and not email:
            nxt = ("There's no email for them yet: copy the payment link from "
                   "Clients and text it. They go live the moment it's paid.")
        elif link and automation.sending_on(self.store):
            nxt = (f"The payment link goes to {email} in a minute (answers go out "
                   f"7am-9pm). They go live the moment it's paid.")
        elif link:
            nxt = ("The payment link is approved: tap Send approved on Today. They "
                   "go live the moment it's paid.")
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
        checks = self.store.citation_checks(prospect.business.id, limit=1)
        if checks and ev.get("real"):
            from answerrank import citations
            ev["listing"] = citations.one_liner(prospect.business, checks[0])
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
            "report_url": f"/files/audit/{audit.id}" if audit else "",
            "meeting": next((calls.their_time(prospect.business.state,
                                              calls.parse_when(a["starts_at"]))
                             for a in self.store.appointments(
                                 kind="meeting", prospect_id=prospect.id)
                             if calls.parse_when(a["starts_at"])), ""),
            "outcomes": [{"key": o.key, "label": o.label}
                         for o in calls.OUTCOMES.values()],
        }

    def debrief(self, prospect_id: str, result: str, plan: str = "growth",
                when: str = "", note: str = "") -> dict[str, Any]:
        """How a walkthrough went. A yes signs them up and sends the link."""
        from answerrank import calls

        prospect = self._prospect(prospect_id)
        if prospect is None:
            return {"error": "no such prospect"}
        if result == "signed":
            out = self.win(prospect_id, plan)
            if out.get("error"):
                return out
            self.store.close_appointments(prospect_id)
            self.store.record_outcome(prospect_id=prospect_id,
                                      vertical=prospect.business.vertical,
                                      kind="walkthrough", sentiment="signed", note=plan)
            return {**out, "ok": True, "result": "signed", "label": "Signed up"}
        return calls.debrief(self.store, self.settings, prospect, result, when, note)

    def log_call(self, prospect_id: str, outcome: str, email: str = "",
                 note: str = "", when: str = "") -> dict[str, Any]:
        from answerrank import calls

        prospect = self._prospect(prospect_id)
        if prospect is None:
            return {"error": "no such prospect"}
        return calls.log_call(self.store, self.settings, prospect, outcome, email,
                              note, when)

    #: Where a prospect already is in the cold sequence. Adding someone you
    #: know by hand takes them out of it.
    _COLD_STAGES = {"discovered", "audited", "queued", "contacted", "following_up"}

    def add_many(self, text: str, pilots: bool = False) -> dict[str, Any]:
        """Several businesses you know at once, one per line:
        ``Name | trade | Town, ST`` and anything after (the Pilot Kit's status,
        an email) optional. The Pilot Kit's "Copy for AnswerRank" writes
        exactly this, so the businesses scored there don't get typed twice.
        With ``pilots``, each one is signed up as a free pilot as well."""
        from answerrank import knowledge

        by_label = {v.label.lower(): k for k, v in knowledge.VERTICALS.items()}
        added, signed, skipped = [], [], []
        for raw in (text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3 or not parts[0] or not parts[2]:
                skipped.append({"line": line, "why": "needs a name, a trade and a town"})
                continue
            name, trade, town = parts[0], parts[1].lower(), parts[2]
            vertical = trade if trade in knowledge.VERTICALS else by_label.get(trade, "")
            if not vertical:
                skipped.append({"line": line, "why": f"unknown trade {parts[1]!r}"})
                continue
            city, state = town, ""
            if "," in town:
                head, tail = town.rsplit(",", 1)
                if len(tail.strip()) == 2:
                    city, state = head.strip(), tail.strip()
            email = next((p for p in parts[3:] if "@" in p), "")
            r = self.add_business(name, city, state, vertical, "", email, "")
            if r.get("error"):
                skipped.append({"line": line, "why": r["error"]})
                continue
            added.append(r["name"])
            if pilots:
                w = self.win(r["id"], "pilot")
                if w.get("error"):
                    skipped.append({"line": line, "why": w["error"]})
                else:
                    signed.append(r["name"])
        return {"added": added, "signed": signed, "skipped": skipped}

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
