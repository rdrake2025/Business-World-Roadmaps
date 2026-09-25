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
from .config import SETTINGS, Pricing, Settings, load_settings
from .mailer import check_dns_readiness
from .models import Business, LedgerEntry
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

# Stripe payment links, one per plan. In Stripe: Payment Links > New, with a
# RECURRING monthly price, so Stripe charges every month by itself. Paste the
# https://buy.stripe.com/... address for each plan you sell. Leave blank and
# you send invoices by hand and tap Paid when the money arrives.
payment_links:
  starter: ""
  growth: ""
  managed: ""

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
    print("  2. Save your keys: AnswerRank button -> Keys and settings")
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


def _fleet_elsewhere(settings: Settings, store) -> str:
    """The address of another copy of this business already running its
    agents, or "".

    Two fleets for one business send every email twice, from two databases
    that each think they are the only one. That is the natural result of
    moving to a server and then double-clicking start.bat on the laptop out
    of habit, so it is checked rather than documented.
    """
    url = (settings.website or "").rstrip("/")
    if not url.startswith("https://") or getattr(settings, "demo_mode", False):
        return ""
    try:
        import requests
        data = requests.get(f"{url}/health", timeout=6).json()
    except Exception:  # noqa: BLE001 - unreachable means nothing is there
        return ""
    if (isinstance(data, dict) and data.get("app") == "answerrank"
            and data.get("fleet_active") and data.get("instance")
            and data.get("instance") != store.instance_id()):
        return url
    return ""


def cmd_run(args, settings: Settings) -> int:
    setup_logging(args.verbose)
    store = _store(settings)
    elsewhere = _fleet_elsewhere(settings, store)
    if elsewhere and not getattr(args, "force", False):
        print(f"Your agents are already running on {elsewhere}. Starting them here too "
              f"would send every email twice. Use {elsewhere}/app instead.")
        return 1
    Orchestrator(store, settings).run_forever()
    return 0


def cmd_case_study(args, settings: Settings) -> int:
    """Before and after for one client, written up — or told it's too early."""
    from . import casestudy

    store = _store(settings)
    matches = [c for status in ("active", "past_due", "churned")
               for c in store.get_clients(status)
               if args.client.lower() in c.business.name.lower() or c.id == args.client]
    if len(matches) != 1:
        print("No single client matches that." if not matches else
              "More than one matches: " + ", ".join(c.business.name for c in matches))
        return 1
    ev, text = casestudy.write_up(store, matches[0])
    out = Path(settings.output_dir) / "case-studies"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{(matches[0].business.domain or matches[0].id).replace('.', '_')}.md"
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n  Saved to {path}  (verdict: {ev.verdict.replace('_', ' ')})")
    return 0


def cmd_server_script(args, settings: Settings) -> int:
    """Write the one file that sets up the always-on server."""
    from . import server

    args.domain = args.domain or _my_domain(settings)
    if not args.domain:
        print("  Which domain? Example: run.py server-script --domain getanswerrank.com")
        return 1
    try:
        path, link, warnings = server.write(args.domain)
    except ValueError as exc:
        print(f"  {exc}")
        return 1
    _hr("SERVER SETUP FILE")
    print(f"  Written: {path}")
    print("  It contains your keys. Keep it private and delete it once the")
    print("  server is running.\n")
    for w in warnings:
        print(f"  ! {w}")
    print("  Then follow deploy/SERVER.md. In short:")
    print("   1. Create an Ubuntu 24.04 server (DigitalOcean or Hetzner, ~$6/mo).")
    print("   2. On the creation page, open the user data / cloud config box and")
    print("      paste the whole contents of that file.")
    print(f"   3. At your domain registrar, point an A record for {args.domain}")
    print("      at the server's IP address.")
    print("   4. Wait about 10 minutes, then run the doctor on this laptop.\n")
    print("  Your console, once it's up (save this — it's your login):")
    print(f"    {link}\n")
    _save_console_link(settings, link)
    print("  It's also saved on this computer: the AnswerRank button's")
    print("  \"Open AnswerRank\" opens it once the server is running.")
    return 0


def _my_domain(settings: Settings) -> str:
    """The domain in the address you send from, unless it's still the template's."""
    email = settings.from_email or ""
    domain = email.split("@")[-1].lower() if "@" in email else ""
    return "" if domain in {"", "answerrank.io", "yourdomain.com"} else domain


def _link_file(settings: Settings) -> Path:
    """Private, next to the database, which git never sees."""
    return Path(settings.database_path).parent / "console-link.txt"


def _save_console_link(settings: Settings, link: str) -> None:
    path = _link_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(link + "\n", encoding="utf-8")


def cmd_evidence(args, settings: Settings) -> int:
    """The professional research behind the agents' rules, with sources."""
    from . import evidence
    print(evidence.as_markdown())
    stale = evidence.overdue()
    if stale:
        print("Due a re-check: " + ", ".join(e.source for e in stale))
    return 0


def cmd_open(args, settings: Settings) -> int:
    """What the AnswerRank button's "Open" does.

    Once a server runs the business, starting a second copy on the laptop
    is refused (it would send every email twice) — which left the button
    doing nothing useful. So when the server is up, this opens its console
    instead. Exit code 3 tells start.bat not to start a local copy.
    """
    import webbrowser

    store = _store(settings)
    elsewhere = _fleet_elsewhere(settings, store)
    if not elsewhere:
        return 0
    path = _link_file(settings)
    link = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if link:
        webbrowser.open(link)
        print(f"  Your business runs on your server. Opened: {link}")
    else:
        print(f"  Your business runs on your server at {elsewhere}.")
        print("  Open your console link on your phone (it was printed when the")
        print("  server setup file was made).")
    return 3


def cmd_console_link(args, settings: Settings) -> int:
    """Print the console address, or install a known token first."""
    from web import auth

    store = _store(settings)
    token = auth.set_token(store, args.set) if args.set else auth.get_or_create_token(store)
    base = (args.base or settings.website or "http://localhost:8000").rstrip("/")
    print(f"{base}/app?t={token}")
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
        # Like for like: a teaser and a full audit ask different numbers of
        # questions, so a trend between them is noise drawn as a result.
        history = [a for a in store.audit_history(biz.id)
                   if a.is_free_teaser == audit.is_free_teaser]
        path.write_text(render_report(audit, settings, history, deliverables),
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
    """Deliver approved messages. All the guard rails live in `sending`."""
    from .sending import send_batch

    store = _store(settings)
    extra = []
    if not args.skip_dns:
        extra = check_dns_readiness(settings.from_email.split("@")[-1])

    result = send_batch(
        store, settings, limit=args.limit, dry_run=args.dry_run,
        throttle_seconds=1 if args.fast else None,
        extra_checks=extra, on_event=print,
    )

    if result["blocked"]:
        _hr("SENDING BLOCKED")
        for reason in result["reasons"]:
            print(f"  \u2717 {reason}")
        print("\n  Fix these first. Sending from an unauthenticated domain gets it")
        print("  filtered permanently, and a burned domain cannot be recovered.")
        return 1

    if result["reasons"]:
        print(result["reasons"][0])
        return 0

    for err in result["errors"]:
        print(f"  \u2717 {err}")
    print(f"\nSent {result['sent']}, failed {result['failed']}. "
          f"Daily total now {result['sends_today']}/{result['daily_cap']}.")
    return 0


def cmd_win(args, settings: Settings) -> int:
    """They said yes. Same code path as the Won button on the phone."""
    from web.api import Api

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

    result = Api(store, settings).win(matches[0].id, args.plan)
    if "error" in result:
        print(result["error"])
        return 1
    if args.mrr is not None:
        client = store.get_client(result["client_id"])
        client.mrr = args.mrr
        store.upsert_client(client)
        result["mrr"] = args.mrr
    print(f"\u2713 {result['name']} signed on {result['plan']} at ${result['mrr']:,.0f}/mo "
          f"({result['status'].replace('_', ' ')}).")
    if result.get("payment_link"):
        print(f"  Payment link: {result['payment_link']}")
    print(f"  {result['next']}")
    return 0


def cmd_paid(args, settings: Settings) -> int:
    """The money arrived — they go live."""
    from web.api import Api

    store = _store(settings)
    waiting = [c for c in store.get_clients("awaiting_payment")
               if args.client.lower() in c.business.name.lower() or c.id == args.client]
    if len(waiting) != 1:
        print("No single unpaid client matches that." if not waiting else
              "More than one matches: " + ", ".join(c.business.name for c in waiting))
        return 1
    result = Api(store, settings).mark_paid(waiting[0].id)
    if "error" in result:
        print(result["error"])
        return 1
    print(f"\u2713 {result['name']} is paid and live. MRR is now ${result['total_mrr']:,.0f}.")
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

    # The fleet runs beside the console, in this same window.
    #
    # It did not, and that was the whole automation claim failing silently:
    # `web` served the pages and nothing ticked, so the agents only moved when
    # somebody pressed a button. A system that needs a human to press a button
    # every few hours is not running 24/7, whatever the documentation says.
    fleet_thread = None
    elsewhere = "" if args.no_fleet else _fleet_elsewhere(settings, _store(settings))
    if elsewhere:
        _hr("ALREADY RUNNING ELSEWHERE")
        print(f"  Your agents run on {elsewhere}. Starting a second copy here")
        print(f"  would send every email twice, so this window will not.")
        print(f"  Open {elsewhere}/app on your phone instead.\n")
        return 1
    if not args.no_fleet:
        import threading

        from .orchestrator import Orchestrator

        store = _store(settings)
        orchestrator = Orchestrator(store, settings)
        fleet_thread = threading.Thread(
            target=orchestrator.run_forever, kwargs={"install_signals": False},
            daemon=True, name="answerrank-fleet")
        fleet_thread.start()

    _hr("RUNNING")
    if fleet_thread:
        print(f"  {len(build_fleet(_store(settings), settings))} agents are running "
              f"in this window, on their own schedules.")
        print(f"  They keep working while you do nothing. Leave it open.")
    else:
        print("  Fleet disabled (--no-fleet). The agents will not run.")

    _hr("NOTE")
    print("  Anyone on this network who has that link can approve outreach,")
    print("  so treat it like a password. Restart to issue a new one.")
    print("\n  Ctrl-C to stop.\n")

    serve(args.host, args.port, settings)
    return 0


#: One pluraliser for the whole system, so the CLI and the outreach copy
#: can never disagree about what a garage door company is called in the plural.
_plural = knowledge.plural


def _wrap(text: str, width: int = 66, indent: str = "  ", hang: bool = False) -> str:
    """Wrap for a terminal. ``hang`` aligns continuations under a bullet."""
    import textwrap
    following = indent + ("  " if hang else "")
    return "\n".join(textwrap.wrap(text, width=width,
                                   initial_indent=indent, subsequent_indent=following))


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
        print(_wrap(f"Not defensible at ${price:,.0f}: {names}. That is a pricing "
                    f"problem, not a market problem \u2014 see the tier below."))

    _hr("WHERE EACH TRADE SHOULD BE PRICED")
    print(_wrap("A trade that fails at one tier is not a trade to drop. It is a "
                "trade to quote differently, and this is the highest tier each "
                "one's own economics defend."))
    print()
    print(f"  {'Trade':<26}{'Sell at':>10}  Basis")
    for r in knowledge.priced_verticals():
        label = knowledge.get(str(r["vertical"])).label
        tier = f"${float(r['price']):,.0f}" if r["price"] else "none"
        print(f"  {label[:25]:<26}{tier:>10}  {r['basis']}")

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

def _find_prospect(store, needle: str):
    matches = [p for p in store.get_prospects(limit=10_000)
               if needle.lower() in p.business.name.lower() or p.id == needle]
    if not matches:
        print(f"No prospect matching {needle!r}. Try `prospects` to see the pipeline.")
        return None
    if len(matches) > 1:
        print(f"{len(matches)} prospects match {needle!r}:")
        for p in matches[:8]:
            print(f"  {p.id}  {p.business.name} ({p.business.city})")
        print("\nUse the id.")
        return None
    return matches[0]


def cmd_brief(args, settings: Settings) -> int:
    """Everything known about one prospect, in the order a seller needs it."""
    from . import qualify

    store = _store(settings)
    prospect = _find_prospect(store, args.prospect)
    if not prospect:
        return 1

    price = args.price or settings.quote_for(prospect.business.vertical)
    b = qualify.brief(prospect.business, prospect.score, prospect.competitor_gap, price)

    _hr(f"{str(b['business']).upper()} \u2014 {b['trade']}")
    print(f"  Priority            {b['priority']}/100")
    print(f"  ICP fit             {b['fit_score']}/100  (tier {b['tier']})")
    print(f"  BANT                {b['bant_score']}/100  ({b['bant_verdict']})")
    bant = b["bant"]
    print(f"    budget {bant['budget']:.0%}   authority {bant['authority']:.0%}   "
          f"need {bant['need']:.0%}   timeline {bant['timeline']:.0%}")
    print(f"  Decision maker      {b['decision_maker']}")
    quoted, rec = float(b["quoted_price"]), b["recommended_price"]
    if rec and float(rec) != quoted:
        print(f"  Price               quoting ${quoted:,.0f} \u2014 this trade supports "
              f"${float(rec):,.0f}")
    else:
        print(f"  Price               ${quoted:,.0f}")

    _hr("THE EVIDENCE")
    for key in ("budget", "authority", "need", "timeline"):
        print(_wrap(f"{key.title()}: {b['bant_evidence'][key]}"))

    if b["blockers"]:
        _hr("BLOCKERS")
        for x in b["blockers"]:
            print(_wrap(f"\u2717 {x}"))

    _hr("TIMING")
    print(_wrap(str(b["seasonality"])))

    _hr("WHAT THEY WILL SAY, AND THE ANSWER")
    for row in b["objections"]:
        print(f'\n  \u201c{row["objection"]}\u201d')
        print(_wrap(str(row["answer"]), indent="    "))

    _hr("ASK THESE")
    for q in b["discovery"]:
        print(_wrap(f"\u2022 {q}", hang=True))

    _hr("NEXT")
    print(_wrap(str(b["next_question"])))
    return 0


def cmd_reply(args, settings: Settings) -> int:
    """Log an inbound reply. The Concierge classifies it and drafts the answer."""
    from .agents.concierge import ConciergeAgent

    store = _store(settings)
    prospect = _find_prospect(store, args.prospect)
    if not prospect:
        return 1

    text = " ".join(args.text)
    result = ConciergeAgent(store, settings).handle_reply(prospect, text)

    _hr(f"REPLY FROM {prospect.business.name.upper()}")
    print(_wrap(f"\u201c{text}\u201d"))
    print(f"\n  Read as       {result['intent']}")
    print(f"  Action        {result['action']}")
    print(f"  Stage now     {prospect.stage}")

    if result["intent"] in {"unsubscribe", "hostile"}:
        print(_wrap("\nSuppressed permanently. Nothing further will be sent to them, "
                    "and no draft was written."))
        return 0

    draft = next((m for m in store.get_messages("drafted", 200)
                  if m.id == result.get("message_id")), None)
    if draft:
        _hr("DRAFTED RESPONSE \u2014 read it before you send it")
        print(draft.body)
        print(f"\n  Approve with:  answerrank approve --id {draft.id}")
    return 0


def cmd_clients(args, settings: Settings) -> int:
    """Client health, worst first. That is the order to work them in."""
    from .agents.retention import RetentionAgent

    store = _store(settings)
    rows = RetentionAgent(store, settings).portfolio()
    if not rows:
        _hr("CLIENTS")
        print(_wrap("No active clients yet. Convert one with `win` once a prospect "
                    "says yes."))
        return 0

    mrr = sum(h.mrr for h in rows)
    at_risk = [h for h in rows if h.band == "act_now"]
    _hr(f"{len(rows)} CLIENTS \u2014 ${mrr:,.0f}/MO")
    print(f"  {'Client':<26}{'MRR':>9}{'Health':>9}  Band")
    for h in rows:
        print(f"  {h.name[:25]:<26}${h.mrr:>8,.0f}{h.score:>9.0f}  {h.band}")
    if at_risk:
        print(f"\n  ${sum(h.mrr for h in at_risk):,.0f}/mo sits in accounts that need "
              f"action now.")

    for h in rows:
        _hr(f"{h.name.upper()} \u2014 {h.score:.0f}/100 ({h.band})")
        for s in h.signals:
            print(_wrap(f"\u2022 {s}", hang=True))
        print(_wrap(f"\u2192 {h.action}", hang=True))
    return 0


def cmd_learn(args, settings: Settings) -> int:
    """What the outcomes actually say. Refuses to conclude on thin data."""
    from .agents.analyst import AnalystAgent

    store = _store(settings)
    analyst = AnalystAgent(store, settings)
    days = args.days

    _hr(f"WHAT THE LAST {days} DAYS SHOW")
    for line in analyst.learnings(days):
        print(_wrap(f"\u2022 {line}", hang=True))

    rows = [r for r in analyst.by_vertical(days) if r["sent"]]
    if rows:
        _hr("BY TRADE")
        print(f"  {'Trade':<26}{'Sent':>7}{'Replied':>9}{'Rate':>8}  Confidence")
        for r in rows:
            rate = f"{r['reply_rate']:.1%}" if r["reply_rate"] is not None else "\u2014"
            print(f"  {str(r['label'])[:25]:<26}{r['sent']:>7}{r['replied']:>9}"
                  f"{rate:>8}  {r['confidence']}")

    steps = [r for r in analyst.by_step(days) if r["sent"]]
    if steps:
        _hr("BY SEQUENCE STEP")
        for r in steps:
            rate = f"{r['reply_rate']:.1%}" if r["reply_rate"] is not None else "\u2014"
            print(f"  step {r['step']}: {r['sent']:>5} sent, {r['replied']:>4} replied "
                  f"({rate})")

    vol = analyst.required_volume(settings.profit_target_monthly, None,
                                  settings.pricing.delivery_cost_monthly, days)
    _hr("WHAT THE TARGET REQUIRES")
    print(_wrap(str(vol["line"])))
    print(_wrap(f"Deal value: {vol['price_basis']}."))
    print(f"\n  About {vol['sends_per_day']} emails a working day, every day, "
          f"for {vol['ramp_months']} months.")
    return 0


def cmd_playbook(args, settings: Settings) -> int:
    """The sales method for one trade: positioning, objections, questions."""
    from . import playbook

    vertical = args.vertical
    if vertical not in knowledge.VERTICALS:
        print(f"Unknown trade {vertical!r}. Known: "
              f"{', '.join(sorted(knowledge.VERTICALS))}")
        return 1
    price = args.price or float(knowledge.recommended_price(vertical)["price"] or
                                settings.pricing.growth_monthly)
    v = knowledge.get(vertical)

    _hr(f"PLAYBOOK \u2014 {v.label.upper()} AT ${price:,.0f}/MO")
    print(_wrap(playbook.value_proposition(vertical, price, settings.brand)))
    print(f"\n  Decision maker   {v.decision_maker}")
    print(f"  Peak season      {v.peak_label()}")
    print(_wrap(knowledge.seasonal_note(vertical, datetime.now(timezone.utc).month)))

    _hr("OBJECTIONS AND ANSWERS")
    for row in playbook.objection_brief(vertical, price):
        print(f'\n  \u201c{row["objection"]}\u201d')
        print(_wrap(str(row["answer"]), indent="    "))

    _hr("DISCOVERY QUESTIONS")
    for q in playbook.discovery_questions(vertical):
        print(_wrap(f"\u2022 {q.replace('{city}', 'their city')}", hang=True))

    _hr("THE SEQUENCE")
    for step, intent in sorted(playbook.SEQUENCE_INTENT.items()):
        print(_wrap(f"{step}. {intent}"))
    return 0


def _write_config_values(path: Path, values: dict[str, str]) -> list[str]:
    """Update top-level keys in answerrank.yml, creating it if absent.

    Deliberately line-based rather than a YAML round-trip: the config file is
    meant to be read and edited by a human, and a serialiser would strip every
    comment explaining what the values are for.
    """
    changed = []
    if not path.exists():
        path.write_text("# AnswerRank configuration\n", encoding="utf-8")
    lines = path.read_text(encoding="utf-8").splitlines()
    for key, value in values.items():
        rendered = f'{key}: "{value}"'
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}:") and not line.startswith(" "):
                if line.strip() != rendered:
                    lines[i] = rendered
                    changed.append(key)
                break
        else:
            lines.append(rendered)
            changed.append(key)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def cmd_domain(args, settings: Settings) -> int:
    """Set up the sending domain: the records to add, then whether they are live.

    This is the last step between a working system and one that can earn, and
    the one most likely to be done wrong — the three records that matter are
    invisible until mail is already in a spam folder.
    """
    from . import dns_setup

    if not (args.domain or _my_domain(settings)):
        print("Which domain? Type the one you bought, e.g. getanswerrank.com")
        return 1
    domain = (args.domain or _my_domain(settings)).strip().lower().removeprefix("http://")
    domain = domain.removeprefix("https://").split("/")[0].removeprefix("www.")
    if "." not in domain:
        print(f"{domain!r} does not look like a domain. Example: answerrank.io")
        return 1

    provider_key = (args.provider or settings.email_provider or "").lower()
    provider = dns_setup.PROVIDERS.get(provider_key)
    mailbox = args.mailbox or "hello"

    # ---------------- write it down ----------------
    if not args.check_only:
        changed = _write_config_values(Path(args.config or "answerrank.yml"), {
            "from_email": f"{mailbox}@{domain}",
            "website": f"https://{domain}",
            "email_provider": provider_key,
        })
        if changed:
            print(f"Updated answerrank.yml: {', '.join(changed)}")

    _hr(f"SENDING DOMAIN: {domain.upper()}")
    if provider:
        print(f"  Mailbox provider   {provider.label} ({provider.monthly_cost})")
        print(f"  Send limit         {provider.daily_limit:,} a day on their side")
    elif provider_key:
        print(f"  Mailbox provider   {provider_key} (not one I have records for)")
        print(_wrap(dns_setup.GENERIC_GUIDANCE))
    else:
        print("  Mailbox provider   not chosen yet")
        print(_wrap("Pass --provider with one of: "
                    + ", ".join(sorted(dns_setup.PROVIDERS)) + ". Without it I "
                    "can still check what is published, but I cannot tell you "
                    "the exact values to add."))

    # ---------------- what to add ----------------
    _hr("ADD THESE AT YOUR REGISTRAR")
    print(_wrap("Wherever you bought the domain, find DNS settings. Add each "
                "row below. The Host column is sometimes called Name; @ means "
                "the domain itself."))
    for record in dns_setup.records_for(domain, provider_key):
        print(f"\n  {record.kind}")
        print(f"    Host   {record.host}")
        print(f"    Value  {record.value}")
        if record.priority is not None:
            print(f"    Priority {record.priority}")
        print(_wrap(record.why, indent="    "))

    if provider:
        _hr("THE ONE RECORD NOBODY CAN GENERATE FOR YOU")
        print(_wrap(f"DKIM. Get it here, then paste it as the TXT record above:"))
        print(_wrap(provider.dkim_where, indent="    "))

    # ---------------- is it live ----------------
    _hr("CHECKING WHAT IS ACTUALLY PUBLISHED")
    print("  (DNS changes take anywhere from a minute to an hour to appear)\n")
    result = dns_setup.readiness(domain, provider_key)
    for signal in result.signals:
        mark = "\u2713" if signal.ok else ("\u2717" if signal.blocking else "!")
        print(f"  {mark} {signal.name:<16} {signal.detail[:44]}")
        if not signal.ok and signal.fix:
            print(_wrap(signal.fix, indent="      "))

    # ---------------- then what ----------------
    if result.ready:
        _hr("THE DOMAIN IS READY")
        if provider:
            print("  Set these so the system can send as you:\n")
            print(f"    SMTP_HOST      {provider.smtp_host}")
            print(f"    SMTP_PORT      {provider.smtp_port}")
            print(f"    SMTP_USERNAME  {mailbox}@{domain}")
            print(f"    SMTP_PASSWORD  an app password, not your login password")
            print(_wrap(f"Get the app password here: {provider.app_password_where}",
                        indent="    "))
            print(f"\n    IMAP_HOST      {provider.imap_host}")
            print(_wrap("Optional, and worth it: with IMAP set the Concierge "
                        "polls for replies on its own instead of waiting for "
                        "you to paste them in.", indent="    "))
        pol = settings.outreach
        _hr("WARM-UP — THIS IS NOT OPTIONAL")
        print(_wrap(f"A domain with no sending history that opens at "
                    f"{pol.max_emails_total_per_day} a day is read as a "
                    f"compromised account, and that reputation does not come "
                    f"back. The system ramps you automatically and will not "
                    f"let you exceed it:"))
        print()
        for from_day, cap in pol.warmup_steps:
            shown = cap or pol.max_emails_total_per_day
            print(f"    from day {from_day:<3} {shown:>4} emails a day")
        print()
        print(_wrap("Day one starts on your first real send, recorded in the "
                    "database rather than the config so it cannot be quietly "
                    "reset when the cap feels slow."))
        _hr("NEXT")
        print("  python3 run.py doctor --probe     # everything else that gates sending")
        print("  python3 run.py inbox              # read what the agents drafted")
    else:
        _hr("NOT READY YET")
        print(_wrap("Add the records above, wait a few minutes, then run this "
                    "again. Nothing will send until every blocking row passes "
                    "\u2014 that refusal is the feature. A domain burned by "
                    "sending unauthenticated mail cannot be recovered, and you "
                    "would be buying a new one."))
        print(f"\n  python3 run.py domain {domain}"
              + (f" --provider {provider_key}" if provider_key else ""))
    return 0 if result.ready else 1


def cmd_research(args, settings: Settings) -> int:
    """What each agent's researcher found about that agent's own work."""
    from . import research
    from .agents.researcher import ResearcherAgent

    store = _store(settings)
    agent = ResearcherAgent(store, settings)

    if args.refresh:
        agent.execute()
    findings = store.research_findings(args.subject or "")

    if args.subject:
        _hr(f"RESEARCH ON {args.subject.upper()}")
    else:
        _hr(f"{len(research.RESEARCHERS)} RESEARCHERS, ONE PER AGENT")
        print(f"  {'Agent':<13}Question")
        for cls in research.RESEARCHERS:
            print(f"  {cls.subject:<13}{cls.question}")
        _hr("WHAT THEY FOUND")

    if not findings:
        print(_wrap("Nothing the evidence supports saying. That is the common "
                    "and correct answer \u2014 a researcher that invented a finding "
                    "every cycle would be one more thing you stop reading."))
        print("\n  Refresh with:  python3 run.py research --refresh")
        return 0

    for f in findings:
        mark = {"blocking": "\u2717", "improve": "!", "note": "\u00b7"}.get(
            f["severity"], "\u00b7")
        print(f"\n  {mark} [{f['subject']}] {f['claim']}")
        print(_wrap(f"Evidence: {f['evidence']}", indent="      "))
        print(_wrap(f"\u2192 {f['proposal']}", indent="      "))
        print(f"      ({f['confidence']})")
    return 0


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
    s.add_argument("--force", action="store_true",
                   help="start even if another copy of this business is running")
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

    s = sub.add_parser("win", help="they said yes: sign them up (awaiting payment)")
    s.add_argument("prospect"); s.add_argument("--plan", default="growth",
                                               choices=list(Pricing.PLANS))
    s.add_argument("--mrr", type=float); s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_win)

    s = sub.add_parser("paid", help="their payment arrived: make them live")
    s.add_argument("client")
    s.set_defaults(func=cmd_paid)

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

    s = sub.add_parser("domain", help="set up the sending domain and check its DNS")
    s.add_argument("domain", nargs="?", default="",
                   help="the domain you bought (default: the one you send from)")
    s.add_argument("--provider", help="google | zoho | microsoft | fastmail")
    s.add_argument("--mailbox", default="hello", help="the part before the @")
    s.add_argument("--check-only", action="store_true",
                   help="check DNS without writing to answerrank.yml")
    s.set_defaults(func=cmd_domain)

    s = sub.add_parser("brief", help="full qualification brief for one prospect")
    s.add_argument("prospect", help="name fragment or id")
    s.add_argument("--price", type=float)
    s.set_defaults(func=cmd_brief)

    s = sub.add_parser("reply", help="log an inbound reply and draft the answer")
    s.add_argument("prospect", help="name fragment or id")
    s.add_argument("text", nargs="+", help="what they wrote")
    s.set_defaults(func=cmd_reply)

    s = sub.add_parser("clients", help="client health scores and the action for each")
    s.set_defaults(func=cmd_clients)

    s = sub.add_parser("learn", help="what the recorded outcomes actually show")
    s.add_argument("--days", type=int, default=90)
    s.set_defaults(func=cmd_learn)

    s = sub.add_parser("research", help="what each agent's researcher found")
    s.add_argument("--subject", help="one agent name, e.g. outreach")
    s.add_argument("--refresh", action="store_true", help="re-run the researchers now")
    s.set_defaults(func=cmd_research)

    s = sub.add_parser("playbook", help="how to sell one trade")
    s.add_argument("vertical")
    s.add_argument("--price", type=float)
    s.set_defaults(func=cmd_playbook)

    s = sub.add_parser("verticals", help="which trades justify which price")
    s.add_argument("--price", type=float, help="monthly retainer to test")
    s.set_defaults(func=cmd_verticals)

    s = sub.add_parser("markets", help="candidate markets and the next move")
    s.add_argument("--price", type=float)
    s.set_defaults(func=cmd_markets)

    s = sub.add_parser("keys", help="save your mailbox password and API keys")
    s.set_defaults(func=cmd_keys)

    s = sub.add_parser("simulate", help="run made-up sales through the real agents")
    s.add_argument("--sales", type=int, default=30, help="buyers to simulate (default 30)")
    s.add_argument("--days", type=int, default=100, help="days to run (default 100)")
    s.add_argument("--seed", type=int, default=7, help="change for a different market")
    s.add_argument("--keep", action="store_true", help="keep the scratch database")
    s.set_defaults(func=cmd_simulate)

    s = sub.add_parser("case-study", help="before/after write-up for a client (pilots)")
    s.add_argument("client")
    s.set_defaults(func=cmd_case_study)

    s = sub.add_parser("server-script", help="write the file that sets up your server")
    s.add_argument("--domain", default="",
                   help="e.g. getanswerrank.com (default: the one you send from)")
    s.set_defaults(func=cmd_server_script)

    s = sub.add_parser("evidence", help="print the research the agents work from")
    s.set_defaults(func=cmd_evidence)

    s = sub.add_parser("open", help="open the console: the server's, or start one here")
    s.set_defaults(func=cmd_open)

    s = sub.add_parser("console-link", help="print the console address with its login")
    s.add_argument("--set", help="use this token (the server setup does this)")
    s.add_argument("--base", help="address to print, e.g. https://yourdomain.com")
    s.set_defaults(func=cmd_console_link)

    s = sub.add_parser("web", help="serve the console and run the fleet")
    s.add_argument("--no-fleet", action="store_true",
                   help="serve the pages without running the agents")
    s.add_argument("--host", default="0.0.0.0"); s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_web)

    return ap




def cmd_keys(args, settings: Settings) -> int:
    """Ask for each key, test the mailbox, save to keys.env."""
    from . import keys
    return keys.interactive(settings)


def cmd_simulate(args, settings: Settings) -> int:
    """Made-up buyers, real agents, nothing real touched."""
    import logging

    from . import simulate

    # The fleet logs every agent run; across a hundred simulated days that
    # buries the scorecard. Only warnings and worse get through.
    logging.getLogger("answerrank").setLevel(logging.WARNING)
    print(f"\nSimulating {args.sales} buyers over {args.days} days. Nothing real is "
          f"touched: no email is sent, no AI service is called, and your own "
          f"database is not opened.\nThis takes a few minutes.\n")
    card = simulate.run(sales=args.sales, days=args.days, seed=args.seed,
                        say=print, keep=args.keep)
    print(simulate.render(card))
    return 0 if simulate.passed(card) else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.config) if args.config else SETTINGS
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())
