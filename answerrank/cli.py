"""Operator command line — the human's control surface over the agent fleet.

Design rule: the fleet does the work, the operator makes the decisions that
carry legal, financial, or reputational risk. Everything that sends mail,
charges money, or commits to a client is an explicit command here.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .agents.fixer import FixerAgent
from . import doctor as doctor_mod
from . import knowledge
from . import markets
from . import wizard
from .budget import (
    PHASES, cumulative_monthly, load_personal, milestones, phase_cost,
    quit_threshold, reinvestment_split, runway_months, write_template,
)
from .agents.reporter import render_report
from .audit import estimate_cost, run_audit
from .config import SETTINGS, Settings, load_settings
from .mailer import Mailer, check_dns_readiness, throttle
from .models import Business, Client, LedgerEntry, Prospect, now_iso
from .orchestrator import Orchestrator, build_fleet, setup_logging
from .schedule import build_calendar
from .scoring import grade
from .store import Store

BAR = "─" * 68


def _store(settings: Settings) -> Store:
    return Store(settings.database_path)


def _hr(title: str) -> None:
    print(f"\n{title}\n{BAR}")


# ---------------------------------------------------------------- commands

def cmd_init(args, settings: Settings) -> int:
    path = Path(args.path or "answerrank.yml")
    if path.exists() and not args.force:
        print(f"{path} already exists. Use --force to overwrite.")
        return 1
    path.write_text(f"""# AnswerRank configuration
brand: {settings.brand}
company_legal_name: "YOUR LEGAL ENTITY, LLC"
from_email: "hello@yourdomain.com"
website: "https://yourdomain.com"

# REQUIRED before any email is sent (CAN-SPAM). A registered agent address
# A registered agent, a USPS-registered PO Box, or a CMRA mailbox all
# qualify under the FTC's CAN-SPAM guide. It need not be your home.
physical_address: "123 Main St, Suite 100, Austin, TX 78701"

engines: [openai, anthropic, perplexity, google_aio]
prompts_per_audit: 10
tick_seconds: 300
profit_target_monthly: 5000

pricing:
  audit_one_time: 297
  starter_monthly: 499
  growth_monthly: 997
  managed_monthly: 1997

outreach:
  max_emails_total_per_day: 120
  max_emails_per_domain_per_day: 30
  min_seconds_between_sends: 90
  max_followups: 3
  followup_gap_days: 4
""", encoding="utf-8")
    print(f"Wrote {path}")
    print("\nNext:")
    print("  1. Edit physical_address, from_email and website — sending is blocked until you do.")
    print("  2. Export provider keys: OPENAI_API_KEY, ANTHROPIC_API_KEY, PERPLEXITY_API_KEY, SERPER_API_KEY")
    print("  3. Run: python3 run.py tick")
    return 0


def cmd_agents(args, settings: Settings) -> int:
    store = _store(settings)
    _hr("AGENT FLEET")
    for agent in build_fleet(store, settings):
        hours = agent.interval / 3600
        print(f"  {agent.name:<12} every {hours:>5.1f}h   {agent.description}")
    _hr("RECENT RUNS")
    runs = store.recent_runs(12)
    if not runs:
        print("  (none yet — run `tick`)")
    for r in runs:
        mark = "ok " if r["status"] == "ok" else "ERR"
        print(f"  [{mark}] {r['started_at'][11:19]} {r['agent']:<12} {(r['summary'] or r['error'])[:80]}")
    return 0


def cmd_tick(args, settings: Settings) -> int:
    setup_logging(args.verbose)
    orch = Orchestrator(_store(settings), settings)
    lines = orch.tick(force=args.force)
    _hr("TICK")
    for line in lines or ["  (nothing due — use --force)"]:
        print("  " + line)
    return 0


def cmd_run(args, settings: Settings) -> int:
    setup_logging(args.verbose)
    Orchestrator(_store(settings), settings).run_forever()
    return 0


def cmd_audit(args, settings: Settings) -> int:
    store = _store(settings)
    biz = Business(
        name=args.name, city=args.city, state=args.state or "",
        vertical=args.vertical, website=args.website or "", email=args.email or "",
        phone=args.phone or "",
    )
    engines = settings.available_engines()
    print(f"Auditing {biz.name} ({biz.market}) across {len(engines)} engine(s): {', '.join(engines)}")
    print(f"Estimated cost: ${estimate_cost(args.depth, len(engines)):.4f}\n")

    audit = run_audit(biz, settings, depth=args.depth)
    store.save_audit(audit)

    _hr(f"VISIBILITY SCORE: {audit.score}/100  (grade {grade(audit.score)})")
    for k, v in audit.subscores.items():
        print(f"  {k:<12} {v:>6.1f}")
    _hr("FINDINGS")
    for f in audit.findings:
        print(f"  • {f}")
    if audit.competitors:
        _hr("COMPETITORS NAMED INSTEAD")
        for name, count in list(audit.competitors.items())[:6]:
            print(f"  {count:>3}x  {name}")

    if args.report:
        deliverables = FixerAgent(store, settings).build_for(biz, audit)
        for d in deliverables:
            store.save_deliverable(d)
        out_dir = Path(settings.output_dir) / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = (biz.domain or biz.id).replace(".", "_")
        path = out_dir / f"{slug}_{datetime.now(timezone.utc):%Y-%m-%d}.html"
        path.write_text(render_report(audit, settings, store.audit_history(biz.id), deliverables),
                        encoding="utf-8")
        print(f"\n  Report:       {path}")

        asset_dir = Path(settings.output_dir) / "deliverables" / slug
        asset_dir.mkdir(parents=True, exist_ok=True)
        for d in deliverables:
            (asset_dir / d.filename).write_text(d.body, encoding="utf-8")
        print(f"  Deliverables: {asset_dir}  ({len(deliverables)} files)")
    return 0


def cmd_prospects(args, settings: Settings) -> int:
    store = _store(settings)
    _hr("PIPELINE")
    counts = store.count_prospects_by_stage()
    if not counts:
        print("  (empty — run `tick --force`)")
        return 0
    for stage, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {stage:<14} {n:>4}")

    rows = store.get_prospects(args.stage, args.limit)
    if rows:
        _hr(f"{'BUSINESS':<28}{'MARKET':<18}{'SCORE':>6}{'GAP':>6}  STAGE")
        for p in rows:
            score = f"{p.score:.0f}" if p.score is not None else "—"
            gap = f"{p.competitor_gap:.0f}" if p.competitor_gap is not None else "—"
            flag = " HOT" if p.is_hot else ""
            print(f"  {p.business.name[:26]:<28}{p.business.market[:16]:<18}{score:>6}{gap:>6}  {p.stage}{flag}")
    return 0


def cmd_inbox(args, settings: Settings) -> int:
    store = _store(settings)
    msgs = store.get_messages(args.status, args.limit)
    _hr(f"OUTREACH INBOX — {args.status} ({len(msgs)})")
    if not msgs:
        print("  (empty)")
        return 0
    for m in msgs:
        print(f"\n  [{m.id}]  step {m.sequence_step}")
        print(f"  SUBJECT: {m.subject}")
        if args.full:
            print("  " + "\n  ".join(m.body.splitlines()))
        else:
            preview = " ".join(m.body.split())[:150]
            print(f"  {preview}...")
    return 0


def cmd_approve(args, settings: Settings) -> int:
    store = _store(settings)
    msgs = store.get_messages("drafted", args.limit)
    if args.ids:
        msgs = [m for m in msgs if m.id in set(args.ids)]
    for m in msgs:
        m.status = "approved"
        store.save_message(m)
    print(f"Approved {len(msgs)} message(s) for sending.")
    print("Run `send` to deliver them (SMTP required).")
    return 0


def cmd_send(args, settings: Settings) -> int:
    from .agents.outreach import OutreachAgent

    store = _store(settings)
    agent = OutreachAgent(store, settings)

    problems = agent.preflight()
    domain = settings.from_email.split("@")[-1]
    if not args.skip_dns:
        problems += check_dns_readiness(domain)
    if problems:
        _hr("SENDING BLOCKED")
        for p in problems:
            print(f"  ✗ {p}")
        print("\n  Fix these first. Sending from an unauthenticated domain gets it")
        print("  filtered permanently, and a burned domain cannot be recovered.")
        return 1

    mailer = Mailer(settings)
    pol = settings.outreach
    remaining = pol.max_emails_total_per_day - store.sends_today()
    if remaining <= 0:
        print(f"Daily cap reached ({pol.max_emails_total_per_day}). Try tomorrow.")
        return 0

    approved = store.get_messages("approved", min(args.limit, remaining))
    if not approved:
        print("No approved messages. Run `approve` first.")
        return 0

    by_id = {p.id: p for p in store.get_prospects(limit=10_000)}
    sent = failed = 0
    for m in approved:
        prospect = by_id.get(m.prospect_id)
        if not prospect or not prospect.business.email:
            continue
        if store.is_suppressed(prospect.business.email):
            m.status = "suppressed"
            store.save_message(m)
            continue

        if args.dry_run:
            print(f"  [dry-run] would send to {prospect.business.email}: {m.subject}")
            sent += 1
            continue

        ok, detail = mailer.send(prospect.business.email, m.subject, m.body)
        if ok:
            m.status, m.sent_at = "sent", now_iso()
            prospect.touches += 1
            prospect.last_touch_at = now_iso()
            prospect.stage = "contacted" if m.sequence_step == 1 else "following_up"
            store.upsert_prospect(prospect)
            sent += 1
        else:
            m.status = "bounced" if "bounce" in detail else "drafted"
            if "bounce" in detail:
                store.suppress(prospect.business.email, detail)
            failed += 1
            print(f"  ✗ {prospect.business.email}: {detail}")
        store.save_message(m)
        throttle(pol.min_seconds_between_sends if not args.fast else 1)

    print(f"\nSent {sent}, failed {failed}. Daily total now {store.sends_today()}/{pol.max_emails_total_per_day}.")
    return 0


def cmd_win(args, settings: Settings) -> int:
    """Convert a prospect into a paying client."""
    store = _store(settings)
    matches = [p for p in store.get_prospects(limit=10_000)
               if args.prospect.lower() in p.business.name.lower() or p.id == args.prospect]
    if not matches:
        print(f"No prospect matching '{args.prospect}'.")
        return 1
    if len(matches) > 1 and not args.force:
        print("Multiple matches — be more specific or pass --force:")
        for p in matches[:10]:
            print(f"  {p.id}  {p.business.name} ({p.business.market})")
        return 1

    prospect = matches[0]
    mrr = args.mrr if args.mrr is not None else settings.pricing.plan_price(args.plan)
    client = Client(business=prospect.business, plan=args.plan, mrr=mrr, status="active")
    store.upsert_client(client)

    prospect.stage = "won"
    store.upsert_prospect(prospect)

    print(f"✓ {client.business.name} is now a {args.plan} client at ${mrr:,.0f}/mo.")
    print(f"  MRR is now ${store.mrr():,.0f}.")
    return 0


def cmd_dashboard(args, settings: Settings) -> int:
    from .agents.bookkeeper import BookkeeperAgent

    store = _store(settings)
    k = BookkeeperAgent(store, settings).kpis()

    _hr("BUSINESS DASHBOARD")
    print(f"  MRR                    ${k['mrr']:>10,.0f}      ARR  ${k['arr']:,.0f}")
    print(f"  Active clients          {k['active_clients']:>10,.0f}      ARPU ${k['arpu']:,.0f}")
    print(f"  Revenue (30d)          ${k['revenue_30d']:>10,.0f}")
    print(f"  Costs (30d)            ${k['cost_30d']:>10,.0f}")
    print(f"  Profit (30d)           ${k['profit']:>10,.0f}      margin {k['margin']*100:.0f}%")

    pct = k["pct_to_target"]
    filled = max(0, min(30, int(pct * 30 / 100)))
    print(f"\n  Target ${k['target']:,.0f}/mo  [{'█'*filled}{'░'*(30-filled)}] {pct:.0f}%")
    if k["profit_gap"] > 0:
        print(f"  Gap: ${k['profit_gap']:,.0f}/mo  ≈ {k['more_clients_needed']:.0f} more "
              f"client(s) at ${settings.pricing.growth_monthly:,.0f}/mo")
    else:
        print("  TARGET MET.")

    _hr("PIPELINE")
    for stage, n in sorted(store.count_prospects_by_stage().items(), key=lambda kv: -kv[1]):
        print(f"  {stage:<14} {n:>4}")

    costs = store.cost_breakdown(30)
    if costs:
        _hr("COST BREAKDOWN (30d)")
        for cat, amt in costs.items():
            print(f"  {cat:<14} ${amt:>8,.2f}")
    return 0


def cmd_forecast(args, settings: Settings) -> int:
    """Model the path from where we are to the profit target."""
    from .agents.bookkeeper import FIXED_COSTS, PROCESSOR_FLAT, PROCESSOR_PCT

    p = settings.pricing
    fixed = sum(FIXED_COSTS.values())
    _hr("UNIT ECONOMICS")
    print(f"  {'Plan':<10}{'Price':>10}{'Delivery':>10}{'Fees':>9}{'Margin':>10}{'To target':>11}")
    for plan in ("starter", "growth", "managed"):
        price = p.plan_price(plan)
        fees = price * PROCESSOR_PCT + PROCESSOR_FLAT
        margin = price - p.delivery_cost_monthly - fees
        need = int(-(-(settings.profit_target_monthly + fixed) // margin))
        print(f"  {plan:<10}{f'${price:,.0f}':>10}{f'${p.delivery_cost_monthly:,.0f}':>10}"
              f"{f'${fees:,.2f}':>9}{f'${margin:,.0f}':>10}{need:>11,}")

    _hr(f"PATH TO ${settings.profit_target_monthly:,.0f}/MO PROFIT")
    print(f"  Fixed overhead: ${fixed:,.0f}/mo\n")
    print(f"  {'Month':<7}{'Clients':>9}{'MRR':>11}{'Costs':>10}{'Profit':>11}")

    clients = float(args.start_clients)
    adds, churn = args.adds_per_month, args.churn
    blended = (p.starter_monthly + p.growth_monthly) / 2
    for month in range(1, args.months + 1):
        clients = clients * (1 - churn) + adds
        mrr = clients * blended
        costs = fixed + clients * (p.delivery_cost_monthly + blended * PROCESSOR_PCT + PROCESSOR_FLAT)
        profit = mrr - costs
        flag = "   ← target" if profit >= settings.profit_target_monthly else ""
        print(f"  {month:<7}{clients:>9.1f}{f'${mrr:,.0f}':>11}{f'${costs:,.0f}':>10}"
              f"{f'${profit:,.0f}':>11}{flag}")

    print(f"\n  Assumes {adds} new client(s)/month, {churn*100:.0f}% monthly churn,")
    print(f"  blended price ${blended:,.0f}. Change with --adds-per-month / --churn.")
    return 0


def cmd_export(args, settings: Settings) -> int:
    store = _store(settings)
    audit = store.get_audit(args.audit_id)
    if not audit:
        print(f"No audit {args.audit_id}")
        return 1
    out = Path(args.out or settings.output_dir) / "export" / audit.id
    out.mkdir(parents=True, exist_ok=True)
    for d in store.get_deliverables(audit.id):
        (out / (d.filename or f"{d.kind}.txt")).write_text(d.body, encoding="utf-8")
    (out / "audit.json").write_text(json.dumps(
        {"score": audit.score, "subscores": audit.subscores,
         "findings": audit.findings, "competitors": audit.competitors},
        indent=2), encoding="utf-8")
    print(f"Exported to {out}")
    return 0


def cmd_budget_init(args, settings: Settings) -> int:
    path = Path(args.path or "budget.yml")
    if path.exists() and not args.force:
        print(f"{path} already exists. Use --force to overwrite.")
        return 1
    write_template(path)
    print(f"Wrote {path}")
    print("\nEdit every line with your real numbers, then run: python3 run.py budget")
    print("This file is gitignored — it never leaves your machine.")
    return 0


def cmd_budget(args, settings: Settings) -> int:
    from .agents.bookkeeper import BookkeeperAgent

    store = _store(settings)
    me = load_personal(args.path or "budget.yml")
    kpis = BookkeeperAgent(store, settings).kpis()
    profit = args.profit if args.profit is not None else kpis["profit"]

    _hr("PERSONAL")
    print(f"  Take-home income        ${me.net_income:>10,.0f}")
    for name, amount in sorted(me.expenses.items(), key=lambda kv: -kv[1]):
        print(f"    {name.replace('_',' '):<22}${amount:>8,.0f}")
    print(f"  {'Total expenses':<24}${me.total_expenses:>10,.0f}")
    print(f"  {'Disposable':<24}${me.disposable:>10,.0f} / month")

    _hr("BUSINESS COST BY PHASE")
    print(f"  {'Phase':<34}{'One-time':>11}{'Monthly':>10}")
    for key, ph in PHASES.items():
        one, month = phase_cost(key)
        print(f"  {ph['label']:<34}{f'${one:,.0f}':>11}{f'${month:,.2f}':>10}")
    current = cumulative_monthly(args.phase)
    print(f"\n  At {PHASES[args.phase]['label']}: ${current:,.2f}/mo recurring")
    for note in PHASES[args.phase]["notes"]:
        print(f"    • {note}")

    _hr("RUNWAY")
    surplus = max(0.0, me.disposable)
    months = runway_months(me.savings, current, surplus)
    print(f"  Monthly disposable      ${surplus:>10,.0f}")
    print(f"  Savings                 ${me.savings:>10,.0f}")
    print(f"  Monthly business burn   ${current:>10,.2f}")
    if months == float("inf"):
        covered = surplus / current if current else 0
        print(f"  Runway                     indefinite")
        print(f"\n  Your disposable income covers the burn {covered:,.0f}x over, so this")
        print("  never touches savings. Spend nothing beyond the current phase.")
    else:
        print(f"  Shortfall               ${current - surplus:>10,.2f} / month")
        print(f"  Runway                  {months:>11,.1f} months on savings")
        if months < 3:
            print("\n  Tight. Do Phase 0 only — about $12/mo. Do not form the LLC")
            print("  or buy tools until a client has actually paid you.")

    _hr("PROFIT SPLIT")
    if profit <= 0:
        print("  No profit yet. Nothing to split — this is expected before month 2.")
    else:
        split = reinvestment_split(profit)
        note = split.pop("_note", "")
        print(f"  On ${profit:,.0f}/mo profit:")
        for k, v in split.items():
            print(f"    {k.replace('_',' '):<22}${v:>8,.0f}")
        print(f"\n  {note}")

    _hr("MILESTONES")
    print(f"  {'Profit':>9}{'Clients':>9}   What it means")
    for m in milestones(me.net_income):
        here = " ←" if profit >= m["profit"] and profit > 0 else ""
        profit_col = f"${m['profit']:,.0f}"
        print(f"  {profit_col:>9}{m['clients']:>9}   {m['meaning']}{here}")

    q = quit_threshold(me.net_income)
    _hr("LEAVING THE JOB")
    print(f"  Your take-home                  ${q['job_take_home']:>9,.0f}/mo")
    print(f"  Profit that truly matches it    ${q['profit_to_match_pay']:>9,.0f}/mo  (profit is pre-tax)")
    print(f"  Safe to quit at                 ${q['safe_quit_profit']:>9,.0f}/mo")
    print(f"  ...sustained for                {q['sustained_months']:>10,.0f} months")
    print(f"  ...with cash banked             ${q['cash_buffer_needed']:>9,.0f}")
    print("\n  Do not quit early. Business profit is variable and pre-tax;")
    print("  a wage is neither. Matching them dollar for dollar is a pay cut.")
    return 0


def cmd_expense(args, settings: Settings) -> int:
    store = _store(settings)
    entry = LedgerEntry(
        kind="cost" if not args.revenue else "revenue",
        category=args.category, amount=args.amount, description=args.note or "",
    )
    store.add_ledger(entry)
    kind = "revenue" if args.revenue else "expense"
    print(f"Logged {kind}: ${args.amount:,.2f} — {args.category}"
          + (f" ({args.note})" if args.note else ""))
    pnl = store.pnl(30)
    print(f"Last 30 days: revenue ${pnl['revenue']:,.2f}, "
          f"costs ${pnl['cost']:,.2f}, profit ${pnl['profit']:,.2f}")
    return 0


def cmd_schedule(args, settings: Settings) -> int:
    start = (datetime.strptime(args.start, "%Y-%m-%d").date()
             if args.start else datetime.now(timezone.utc).date())
    ics = build_calendar(start, include_launch=not args.no_launch,
                         brand=settings.brand)

    out = Path(args.out or Path(settings.output_dir) / "answerrank-schedule.ics")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ics, encoding="utf-8", newline="")

    count = ics.count("BEGIN:VEVENT")
    print(f"Wrote {out}  ({count} events)")
    _hr("WHAT IS IN IT")
    print("  Daily    06:30  Morning ops (20 min) — approve, send, check replies")
    print("  Daily    12:15  Reply check (10 min)")
    print("  Tue/Thu  17:30  Sales calls (90 min) — when owners are reachable")
    print("  Sat      09:00  Deep work (2h) — dashboard, pipeline, fix the funnel")
    print("  Sun             Rest day. Deliberately empty.")
    print("  1st Sat  11:15  Monthly close — bill, reconcile, move tax reserve")
    if not args.no_launch:
        print("  Plus 14 dated launch tasks over your first 30 days.")
    _hr("PUT IT ON YOUR PHONE")
    print("  iPhone:   email the .ics to yourself, open it, tap Add All")
    print("  Android:  Google Calendar (web) → Settings → Import & export → Import")
    print("\n  Every event's notes hold the exact commands for that block,")
    print("  so the calendar entry alone tells you what to do.")
    return 0


def cmd_doctor(args, settings: Settings) -> int:
    checks = doctor_mod.run_all(settings, probe=args.probe)
    _hr("PREFLIGHT CHECK")
    colour = {"PASS": "\033[32m", "WARN": "\033[33m", "FAIL": "\033[31m"}
    for c in checks:
        tag = f"{colour[c.status]}{c.icon}\033[0m"
        block = " \033[31m[BLOCKING]\033[0m" if c.blocking and c.status != "PASS" else ""
        print(f"  [{tag}] {c.name:<28} {c.detail[:52]}{block}")

    passed, warned, failed, blockers = doctor_mod.summarise(checks)
    print(f"\n  {passed} passing, {warned} warnings, {failed} failing")

    fixes = [c for c in checks if c.status != "PASS" and c.fix]
    if fixes:
        _hr("HOW TO FIX")
        for c in fixes:
            print(f"\n  {c.name}")
            for line in c.fix.split(". "):
                if line.strip():
                    print(f"    → {line.strip().rstrip('.')}.")

    _hr("CAN YOU SEND EMAIL?")
    if blockers:
        print(f"  NO — {len(blockers)} blocking issue(s) above must be resolved first.")
        print("  This is enforced in code: `send` will refuse until they are clear.")
        print("  Sending from an unauthenticated domain burns it permanently.")
    else:
        print("  YES — all blocking checks pass. Warm the domain, then start small.")
    return 1 if blockers else 0


def cmd_setup(args, settings: Settings) -> int:
    return wizard.run(settings, args.path or "answerrank.yml")


def cmd_web(args, settings: Settings) -> int:
    import logging

    from web.app import create_app, lan_ip, qr_or_url, serve

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")

    app = create_app(settings)
    ip = lan_ip()
    phone_url = f"http://{ip}:{args.port}/app?t={app.token}"

    _hr("ON THIS LAPTOP")
    print(f"  Console        http://localhost:{args.port}/app?t={app.token}")
    print(f"  Landing page   http://localhost:{args.port}/")
    print(f"  Unsubscribe    http://localhost:{args.port}/unsubscribe")

    _hr("ON YOUR PHONE")
    print("  Same Wi-Fi as this laptop, then open:\n")
    print(f"    {phone_url}\n")
    qr = qr_or_url(phone_url)
    if qr:
        print(qr)
    else:
        print("  (install `qrencode` to get a scannable code here)")
    print("  Open it once — it stays signed in, and you can add it to your")
    print("  home screen so it opens like an app.")

    _hr("NOTE")
    print("  Anyone on this network who has that link can approve outreach,")
    print("  so treat it like a password. Restart to issue a new one.")
    print("\n  Ctrl-C to stop.\n")

    serve(args.host, args.port, settings)
    return 0


def _plural(label: str) -> str:
    """"agency" -> "agencies", not "agencys"."""
    if label.endswith("y") and label[-2:-1] not in "aeiou":
        return label[:-1] + "ies"
    if label.endswith(("s", "x", "ch", "sh")):
        return label + "es"
    return label + "s"


def _wrap(text: str, width: int = 66, indent: str = "  ") -> str:
    import textwrap
    return "\n".join(textwrap.wrap(text, width=width,
                                   initial_indent=indent, subsequent_indent=indent))


def cmd_verticals(args, settings: Settings) -> int:
    """Which trades justify which price, and on what argument."""
    price = args.price or settings.pricing.growth_monthly
    rows = knowledge.best_verticals(price)

    _hr(f"WHICH TRADES JUSTIFY ${price:,.0f}/MO")
    print(f"  {'Trade':<24}{'Ticket':>9}{'1st-job':>9}{'Lifetime':>10}  Verdict")
    for r in rows:
        v = knowledge.get(str(r["vertical"]))
        ticket = f"${v.economics.avg_ticket:,.0f}"
        first = f"{r['first_job_ratio']}x"
        life = f"{r['lifetime_ratio']}x"
        print(f"  {v.label:<24}{ticket:>9}{first:>9}{life:>10}  {r['verdict']}")
    strong = [r for r in rows if r["verdict"] == "strong"]
    _hr("WHAT THIS MEANS")
    if strong:
        names = ", ".join(_plural(knowledge.get(str(r["vertical"])).label) for r in strong)
        print(_wrap(f"Sell {names} on first-job revenue. The arithmetic stands alone."))
    workable = [r for r in rows if r["verdict"] == "workable"]
    if workable:
        names = ", ".join(_plural(knowledge.get(str(r["vertical"])).label) for r in workable)
        print(_wrap(f"{names.capitalize()} need the lifetime-value argument — "
                    f"claiming first-job payback there would not survive scrutiny."))
    weak = [r for r in rows if r["verdict"] == "weak"]
    if weak:
        names = ", ".join(_plural(knowledge.get(str(r["vertical"])).label) for r in weak)
        print(_wrap(f"Avoid at this price: {names}. Price lower, or spend the "
                    f"outreach where the maths works."))

    top = rows[0]
    v = knowledge.get(str(top["vertical"]))
    _hr(f"RECOMMENDED STARTING VERTICAL: {v.label.upper()}")
    risk = knowledge.revenue_at_risk(v.key, 10, 10)
    print(f"  Average ticket     ${v.economics.avg_ticket:>10,.0f}")
    print(f"  Lifetime value     ${v.economics.lifetime_value:>10,.0f}")
    print(f"  They already pay   ${v.economics.typical_cac:>10,.0f}  to win one customer")
    print(f"  Invisibility costs ${float(risk['annual_revenue']):>10,.0f}  a year, estimated")
    print(f"\n  {knowledge.payback_line(v.key, price)}")
    print(f"  Peak season: {v.peak_label()}")
    print()
    print(_wrap(knowledge.seasonal_note(v.key, datetime.now(timezone.utc).month)))

    _hr("WHAT THEY WILL SAY")
    for o in v.objections:
        print(f"  \u2022 \u201c{o}\u201d")
    return 0


def cmd_markets(args, settings: Settings) -> int:
    """Candidate markets, measured where the Explorer has been."""
    from .agents.strategist import StrategistAgent

    store = _store(settings)
    price = args.price or settings.pricing.growth_monthly
    findings = {f["market"]: f for f in store.latest_findings()}

    _hr(f"CANDIDATE MARKETS AT ${price:,.0f}/MO")
    print(f"  {'Market':<30}{'Prior':>7}{'Measured':>10}{'Invisible':>11}  Verdict")
    for c in markets.ranked(price):
        f = findings.get(c.key)
        measured = f"{f['opportunity']}" if f else "\u2014"
        invisible = f"{f['invisible_share']:.0f}%" if f else "\u2014"
        verdict = f["verdict"] if f else c.verdict(price)
        flag = " ?" if c.needs_research else ""
        print(f"  {c.label + flag:<30}{c.score(price):>7}{measured:>10}"
              f"{invisible:>11}  {verdict}")
    print("\n  ? = economics estimated, not sourced.  Measured = sampled by the")
    print("  Explorer; blank means nobody has audited a business there yet.")

    top = markets.ranked(price)[0]
    _hr(f"BEST CANDIDATE: {top.label.upper()}")
    print(f"  Average ticket        ${top.avg_ticket:>9,.0f}")
    print(f"  Their marketing spend ${top.monthly_marketing_spend:>9,.0f} / month")
    share = price / top.monthly_marketing_spend * 100 if top.monthly_marketing_spend else 0
    print(f"  This retainer is      {share:>10.0f}% of that budget")
    print(f"\n  Basis: {top.basis}")
    for n in top.notes:
        print(_wrap(f"\u2022 {n}"))

    rec = StrategistAgent(store, settings).recommend()
    _hr("WHAT TO DO NEXT")
    print(f"  {rec['move']}")
    print()
    print(_wrap(rec["why"]))
    print(f"\n  Confidence: {rec['confidence']}")
    return 0


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="answerrank",
        description=f"{SETTINGS.brand} — AI search visibility, run by an agent fleet.",
    )
    ap.add_argument("--config", help="path to answerrank.yml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="write a starter config file")
    s.add_argument("--path"); s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("agents", help="list the fleet and recent runs")
    s.set_defaults(func=cmd_agents)

    s = sub.add_parser("tick", help="run one cycle of all due agents")
    s.add_argument("--force", action="store_true", help="run every agent regardless of schedule")
    s.set_defaults(func=cmd_tick)

    s = sub.add_parser("run", help="run the fleet continuously (24/7)")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("audit", help="audit one business now")
    s.add_argument("name"); s.add_argument("city")
    s.add_argument("--state", default=""); s.add_argument("--vertical", default="hvac")
    s.add_argument("--website", default=""); s.add_argument("--email", default="")
    s.add_argument("--phone", default="")
    s.add_argument("--depth", choices=["teaser", "full", "deep"], default="full")
    s.add_argument("--report", action="store_true", help="also render HTML report + deliverables")
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("prospects", help="show the pipeline")
    s.add_argument("--stage"); s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_prospects)

    s = sub.add_parser("inbox", help="review drafted outreach")
    s.add_argument("--status", default="drafted"); s.add_argument("--limit", type=int, default=10)
    s.add_argument("--full", action="store_true")
    s.set_defaults(func=cmd_inbox)

    s = sub.add_parser("approve", help="approve drafts for sending")
    s.add_argument("ids", nargs="*"); s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_approve)

    s = sub.add_parser("send", help="send approved messages")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--fast", action="store_true", help="skip pacing (testing only)")
    s.add_argument("--skip-dns", action="store_true")
    s.set_defaults(func=cmd_send)

    s = sub.add_parser("win", help="convert a prospect to a paying client")
    s.add_argument("prospect"); s.add_argument("--plan", default="growth",
                                               choices=["starter", "growth", "managed"])
    s.add_argument("--mrr", type=float); s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_win)

    s = sub.add_parser("dashboard", help="KPIs and progress to target")
    s.set_defaults(func=cmd_dashboard)

    s = sub.add_parser("forecast", help="model the path to the profit target")
    s.add_argument("--months", type=int, default=12)
    s.add_argument("--start-clients", type=float, default=0)
    s.add_argument("--adds-per-month", type=float, default=2)
    s.add_argument("--churn", type=float, default=0.05)
    s.set_defaults(func=cmd_forecast)

    s = sub.add_parser("export", help="export an audit's deliverables")
    s.add_argument("audit_id"); s.add_argument("--out")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("budget-init", help="write a personal budget template")
    s.add_argument("--path"); s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_budget_init)

    s = sub.add_parser("budget", help="personal + business budget, runway, milestones")
    s.add_argument("--path", help="path to budget.yml")
    s.add_argument("--profit", type=float, help="override monthly profit")
    s.add_argument("--phase", default="0_test", choices=list(PHASES.keys()))
    s.set_defaults(func=cmd_budget)

    s = sub.add_parser("expense", help="log a business expense (or --revenue)")
    s.add_argument("category"); s.add_argument("amount", type=float)
    s.add_argument("--note"); s.add_argument("--revenue", action="store_true")
    s.set_defaults(func=cmd_expense)

    s = sub.add_parser("schedule", help="generate an .ics calendar for your phone")
    s.add_argument("--start", help="launch start date YYYY-MM-DD (default: today)")
    s.add_argument("--out", help="output path")
    s.add_argument("--no-launch", action="store_true",
                   help="recurring rhythm only, skip the 30-day launch tasks")
    s.set_defaults(func=cmd_schedule)

    s = sub.add_parser("setup", help="interactive first-run setup")
    s.add_argument("--path")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("doctor", help="check what is blocking you from operating")
    s.add_argument("--probe", action="store_true",
                   help="also probe the live unsubscribe endpoint over the network")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("verticals", help="which trades justify which price")
    s.add_argument("--price", type=float, help="monthly retainer to test")
    s.set_defaults(func=cmd_verticals)

    s = sub.add_parser("markets", help="candidate markets and the next move")
    s.add_argument("--price", type=float)
    s.set_defaults(func=cmd_markets)

    s = sub.add_parser("web", help="serve the site and the phone console")
    s.add_argument("--host", default="0.0.0.0"); s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_web)

    return ap




def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.config) if args.config else SETTINGS
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())
