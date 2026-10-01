"""AnswerRank as an Obsidian vault: notes written from the code itself.

A wiki kept by hand drifts from the thing it describes within a week. These
notes are generated from the same places the agents read: the fleet and its
schedules, each researcher's question, the evidence library, the trade
library and its questions, and the cost model. Regenerate after any change:

    python run.py vault

and copy ``vault/AnswerRank`` into your own vault (or open ``vault`` in
Obsidian as a vault of its own). Links are Obsidian ``[[wikilinks]]``; every
one resolves to a note in the folder, which a test checks.

Only two notes are written by hand, in this file: the decisions and the
plan, because no code knows why a choice was made or what comes next.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

ROOT = "AnswerRank"

#: The published pages, so the vault links to what's already been made.
PAGES = {
    "Launch plan": "https://claude.ai/artifact/LrJFr4ocTkmRpGSRRhqwQG",
    "Pilot Kit": "https://claude.ai/artifact/G34kyvqUQLjshCXjxoBXhm",
    "Calendar (Shifts & Plans)": "https://claude.ai/artifact/A6R7TJvcuz75PAPvoSgEnZ",
    "Film: The Day It Hits 100%": "https://claude.ai/artifact/REcj3ziVKhc4zqT1ppUo1T",
    "Code (GitHub)": "https://github.com/rdrake2025/Business-World-Roadmaps",
}

#: What was decided, and why. Newest last. (When, what, why.)
DECISIONS = [
    ("2026-09", "Sell three plans: Starter $499, Growth $997, Managed $1,997 a month.",
     "Each trade is quoted the price its jobs can carry: a roofer's or tree "
     "service's numbers support Starter, a plumber's support more. See [[Trades]]."),
    ("2026-09", "Autopilot sells up to Growth, never Managed.",
     "Managed means hands-on work on the client's website; nobody does that "
     "while Autopilot runs alone."),
    ("2026-09", "You read the first 20 cold emails before Autopilot sends on its own.",
     "The first emails decide the domain's reputation, and a reputation can't "
     "be bought back."),
    ("2026-09", "The Guardian pauses only the part that's going wrong.",
     "Too many bounces stop first emails; replies, clients and reports carry "
     "on. See [[Guardian]]."),
    ("2026-09", "Start on the Lean budget: 5 businesses checked a day.",
     "The cheapest real start, about $21 a month on Google's free server. "
     "Move up once the first client pays. See [[Costs]]."),
    ("2026-09", "Not Oracle's free server.",
     "Its free tier was halved in June 2026. Google Cloud's e2-micro is the free option."),
    ("2026-10", "Real mode never makes anything up.",
     "With a key missing, AnswerRank used to invent businesses and scores. It "
     "now stops and says which key is missing."),
    ("2026-10", "Market research re-checks each trade once a month.",
     "Twice a day cost about $19 a month that no estimate counted. Once a "
     "month costs about $1.50. See [[Explorer]]."),
    ("2026-10", "Prove it with pilots first: three free months, measured.",
     "The only thing not yet proven is that the changes get a business named "
     "more often. Pilots on your own computer cost about $5 of OpenAI credit. "
     "See [[Pilots]]."),
    ("2026-10", "A before-and-after is published only if it beats the noise.",
     "AI answers change from day to day. The case study says \"don't publish\" "
     "when the change is within the margin of error."),
    ("2026-10", "Book only the costs actually being paid.",
     "The books used to include $138 a month of tools the plan never buys."),
]

#: The path from today to the goal. (Done?, step, roughly where it puts you.)
PLAN = [
    (False, "Check 5 businesses you know in ChatGPT, with the [[Pilot Kit]] (free)", ""),
    (False, "2 or 3 of them say yes to a free three-month pilot", ""),
    (False, "Measure them for about $5 of OpenAI credit: [[Pilots]]", ""),
    (False, "Full setup on the Lean budget, about $21 a month: [[Costs]]", "about 60%"),
    (False, "The live test passes with your real accounts", "about 72%"),
    (False, "You read the first 20 emails, switch Autopilot on, replies start", "about 77%"),
    (False, "45 days in: the pilots' before-and-after", ""),
    (False, "The first paying client, and a lawyer reviews the contract", "85-90%"),
    (False, "Six clients and $5,000 a month", "100%"),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _title(name: str) -> str:
    """A note name Obsidian and Windows both accept."""
    name = re.sub(r'[\\/:*?"<>|#^\[\]]', " -", name)
    return re.sub(r"\s+", " ", name).strip(" -.")[:120]


def _front(tags: list[str], **fields: str) -> str:
    lines = ["---", "tags: [" + ", ".join(tags) + "]"]
    lines += [f"{k}: {v}" for k, v in fields.items() if v != ""]
    return "\n".join(lines + ["---", ""])


def _every(seconds: int) -> str:
    if seconds % 86400 == 0:
        days = seconds // 86400
        return "once a day" if days == 1 else f"every {days} days"
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return "every hour" if hours == 1 else f"every {hours} hours"
    return f"every {seconds // 60} minutes"


def _prose(text: str) -> str:
    """Docstring text as one readable paragraph of Markdown."""
    text = text.replace("``", "`")
    return re.sub(r"\s*\n\s*", " ", text).strip()


def _doc_markdown(doc: str) -> str:
    """A docstring's body (after its title line) as Markdown: paragraphs
    unwrapped, list items kept as list items, ``code`` as `code`."""
    out = []
    for para in [p for p in doc.split("\n\n") if p.strip()][1:]:
        lines = [ln.strip() for ln in para.strip().splitlines()]
        if re.match(r"^([*-]|\d+\.)\s", lines[0]):
            items: list[str] = []
            for ln in lines:
                if re.match(r"^([*-]|\d+\.)\s", ln):
                    items.append(re.sub(r"^\*\s", "- ", ln))
                elif items:
                    items[-1] += " " + ln
            out.append("\n".join(items))
        else:
            out.append(" ".join(lines))
    return "\n\n".join(out).replace("``", "`")


def _purpose(cls) -> str:
    """How an agent works, from its module's own docstring."""
    return _doc_markdown(inspect.getdoc(inspect.getmodule(cls)) or "")


def _agents():
    from .orchestrator import AGENT_ORDER
    return list(AGENT_ORDER)


def _agent_note_name(name: str) -> str:
    return name.capitalize()


def _evidence_names() -> dict[str, str]:
    from . import evidence
    names, seen = {}, set()
    for key, e in evidence.LIBRARY.items():
        n = _title(e.source)
        if n in seen:
            n = _title(f"{e.source} ({key})")
        seen.add(n)
        names[key] = n
    return names


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------

def _home(n_agents: int, n_trades: int, n_sources: int) -> str:
    return _front(["answerrank", "moc"], aliases="[AnswerRank home]") + f"""# AnswerRank

AnswerRank gets local businesses named when their customers ask AI assistants
like ChatGPT who to call. It measures how often a business is named, writes
the changes for its website, and measures again every month. {n_agents} agents
run it, around the clock.

> [!tip] Where things stand
> The software is built and tested. The business starts with two or three
> pilots, measured for about $5: [[Pilots]].

## Map
- [[Dashboard]]: your live numbers
- [[Clients]]: a note for each client and pilot
- [[Plan]]: the steps from today to $5,000 a month
- [[Pilots]]: prove it works for about $5
- [[Costs]]: what each budget costs a month
- [[Agents]]: the {n_agents} agents and what each one does
- [[Trades]]: the {n_trades} trades, their prices and what their customers ask
- [[Research]]: the {n_sources} sources the agents work from
- [[Decisions]]: what was decided, and why
- [[Links]]: the pages made so far

*Generated from the code by `python run.py vault`. Notes you add yourself are
never touched; the generated ones are rewritten each time.*
"""


def _links() -> str:
    lines = [f"- [{k}]({v})" for k, v in PAGES.items()]
    return _front(["answerrank"]) + "# Links\n\nThe pages made for AnswerRank so far.\n\n" \
        + "\n".join(lines) + "\n\nBack to [[AnswerRank]].\n"


def _decisions() -> str:
    rows = "\n".join(f"### {when}: {what}\n{why}\n" for when, what, why in DECISIONS)
    return _front(["answerrank", "decisions"]) + \
        "# Decisions\n\nWhat was decided and why, oldest first. Add your own at the end.\n\n" \
        + rows + "\nBack to [[AnswerRank]].\n"


def _plan() -> str:
    steps = "\n".join(f"- [{'x' if done else ' '}] {step}" + (f" *({where})*" if where else "")
                      for done, step, where in PLAN)
    return _front(["answerrank", "plan"]) + f"""# Plan

Tick each step off as it's done. The percentages are how finished the
business is once that step is behind you.

{steps}

The [[Pilot Kit]] and the [[Links|calendar]] have these steps on dates.

Back to [[AnswerRank]].
"""


def _pilot_kit() -> str:
    return _front(["answerrank", "pilots"]) + f"""# Pilot Kit

A page for the free first step: it lists the questions to ask ChatGPT for
any trade and town, scores the businesses you know, and writes each one a
free-pilot offer. [Open the Pilot Kit]({PAGES['Pilot Kit']})

When some say yes, **Copy for AnswerRank** at the bottom of the Kit copies
them in the form AnswerRank's Pipeline → **Add several at once** reads.

Next: [[Pilots]]. Back to [[AnswerRank]].
"""


def _pilots() -> str:
    from .costs import client_audit_cost
    from .config import Settings
    s = Settings()
    s.engines = ["openai"]
    each = client_audit_cost(s)
    return _front(["answerrank", "pilots"]) + f"""# Pilots

Prove the service on two or three businesses you know, before any monthly
cost. All it takes is your own computer and **$5 of OpenAI credit**.

- One measurement of one pilot: about **{each * 100:.0f} cents** (10 questions,
  each asked 3 times on ChatGPT with web search)
- Three pilots, measured three times over two months: about
  **${each * 9:.0f}**

## Steps
1. Find 2 or 3 businesses that say yes ([[Pilot Kit]]). Offer three free
   months in return for honest feedback and, if it works, permission to
   share the before-and-after.
2. Buy $5 of OpenAI credit. It suggests $10: change it to 5, and leave
   automatic recharge off.
3. AnswerRank button → **2 Keys and settings** → paste only the OpenAI key.
4. **1 Open AnswerRank** → Pipeline → **Add several at once** → paste what
   **Copy for AnswerRank** in the [[Pilot Kit]] gave you. (Or **Add a
   business you know** → choose **Free pilot**, one at a time.)
5. Inbox: **Copy text** on the welcome, send it yourself with their report
   and files, then **I sent it myself**.
6. Open AnswerRank about once a month so it measures again. The **Pilots**
   card on Today shows each pilot's scores and the next measurement date,
   and **add these dates to your calendar** puts every date on your phone
   with a reminder. The [[Dashboard]] lists them too.
7. After 45 days the Pilots card links to the **before-and-after**, a page
   you can show other businesses.
8. A week before the three months end, the offer is written for you: their
   numbers and the price. If they say yes: **They said yes: start paid plan**.

Keep a note per pilot with the **Pilot log** template.

The full guide is `PILOTS.md` in the AnswerRank folder. Back to [[AnswerRank]].
"""


def _costs() -> str:
    from . import costs
    from .config import Settings
    s = Settings()
    free = {r["key"]: r for r in costs.table(s, server="gcp_free")}
    paid = {r["key"]: r for r in costs.table(s, server="digitalocean")}
    rows = "\n".join(
        f"| {free[k]['label']} | {free[k]['per_day']} | ${free[k]['total']:,.2f} | "
        f"${paid[k]['total']:,.2f} |" for k in free)
    lean = costs.estimate(s, server="gcp_free", checks_per_day=free["lean"]["per_day"])
    lines = "\n".join(f"| {line['label']} | ${line['monthly']:,.2f} | {line['note']} |"
                      for line in lean["lines"])
    return _front(["answerrank", "costs"]) + f"""# Costs

The one choice is how many new businesses are checked a day (Keys and settings
asks). Pilots on your own computer cost nothing a month: see [[Pilots]].

| Budget | Checked a day | Google's free server | $6 server |
| --- | --- | --- | --- |
{rows}

## Lean, line by line (free server)

| What | A month | Note |
| --- | --- | --- |
{lines}

On top: Stripe takes about 3.6% of each payment, and each client's monthly
audit costs about ${costs.client_audit_cost(s):.2f}.

`python run.py costs` prints your own numbers. Back to [[AnswerRank]].
"""


def _agents_moc(agents) -> str:
    rows = "\n".join(
        f"| [[{_agent_note_name(a.name)}]] | {_every(a.interval)} | {a.description} |"
        for a in agents)
    return _front(["answerrank", "agents", "moc"]) + f"""# Agents

{len(agents)} agents run the business, in this order each cycle. Each one has a
researcher that checks its work and asks one question.

| Agent | Runs | Job |
| --- | --- | --- |
{rows}

Back to [[AnswerRank]].
"""


def _agent_note(a, question: str, sources: list[tuple[str, str]]) -> str:
    purpose = _purpose(a)
    cites = "\n".join(f"- [[{name}]]: {why}" for name, why in sources) or "- None yet."
    q = f"\n## Its researcher asks\n{question}\n" if question else ""
    return _front(["answerrank", "agent"], runs=_every(a.interval)) + \
        f"# {_agent_note_name(a.name)}\n\n**{a.description}** Runs {_every(a.interval)}.\n\n" \
        + (f"## How it works\n{purpose}\n" if purpose else "") + q + \
        f"\n## Works from\n{cites}\n\nPart of [[Agents]].\n"


def _trades_moc(trades, prices) -> str:
    rows = "\n".join(
        f"| [[{_title(v.label.capitalize())}]] | ${prices[v.key]:,.0f} | "
        f"${v.economics.avg_ticket:,.0f} | ${v.economics.lifetime_value:,.0f} |"
        for v in trades)
    return _front(["answerrank", "trades", "moc"]) + f"""# Trades

What each trade is quoted a month, against what one of its jobs and one of its
customers is worth. On Autopilot the top plan is Growth ($997).

| Trade | Quoted a month | Average job | A customer's lifetime value |
| --- | --- | --- | --- |
{rows}

Back to [[AnswerRank]].
"""


def _trade_note(v, price: float) -> str:
    from .prompts import build_prompts
    qs = "\n".join(f"{i}. {q}" for i, (q, _) in enumerate(
        build_prompts(v.key, "your town", limit=6), 1))
    bullets = lambda xs: "\n".join(f"- {x}" for x in xs) or "- (none recorded)"  # noqa: E731
    e = v.economics
    from .config import Pricing
    growth = Pricing().growth_monthly
    cap = (f" (on Autopilot, Growth at ${growth:,.0f}: Managed needs hands-on work)"
           if price > growth else "")
    return _front(["answerrank", "trade"], quoted=f"{price:.0f}") + f"""# {v.label.capitalize()}

Quoted **${price:,.0f} a month**{cap}. An average job is worth about
${e.avg_ticket:,.0f}, and a customer over time about ${e.lifetime_value:,.0f}.
The person who decides is usually the {v.decision_maker}. Busiest:
{v.peak_label() or 'all year'}.

## Ask ChatGPT
{qs}

## What their customers type
{bullets(v.buyer_phrases)}

## What they'll say
{bullets(v.objections)}

## Signs they spend on marketing
{bullets(v.spend_signals)}

## Lists that recommend them
{bullets(v.directories)}

Part of [[Trades]].
"""


def _research_moc(names) -> str:
    from . import evidence
    agent_names = {a.name for a in _agents()}
    rows = []
    for key, e in evidence.LIBRARY.items():
        users = ", ".join(f"[[{_agent_note_name(u)}]]" if u in agent_names else u
                          for u in e.used_by)
        rows.append(f"| [[{names[key]}]] | {e.published} | {users} |")
    return _front(["answerrank", "research", "moc"]) + f"""# Research

The {len(evidence.LIBRARY)} sources the agents work from. Each note says what
the source found and what AnswerRank does because of it.

| Source | Published | Used by |
| --- | --- | --- |
""" + "\n".join(rows) + "\n\nBack to [[AnswerRank]].\n"


def _research_note(e) -> str:
    agent_names = {a.name for a in _agents()}
    users = ", ".join(f"[[{_agent_note_name(u)}]]" if u in agent_names else f"`{u}`"
                      for u in e.used_by)
    return _front(["answerrank", "research"], published=e.published, checked=e.checked) + \
        f"# {e.source}\n\n[Read the source]({e.url})\n\n## What it found\n{e.finding}\n\n" \
        f"## So AnswerRank\n{e.so_we}\n\nUsed by: {users}. Read again every " \
        f"{e.review_months} months.\n\nPart of [[Research]].\n"


TEMPLATES = {
    "Pilot log": _front(["answerrank", "pilot"], business="", trade="", town="",
                        status="asked") + """# {{title}}

Started {{date}}. Status: asked → yes → measuring → case study.

## Before (from AnswerRank)
- Score:
- Named in: __ of 10 questions
- Recommended instead:

## Changes made
- [ ] Welcome, report and files sent (then **I sent it myself**)
- [ ] Website files installed

## After (45 days or more)
- Score:
- Verdict:

## Notes
""",
    "Weekly review": _front(["answerrank", "weekly"]) + """# Week of {{date}}

- [ ] AnswerRank hour done
- Pilots asked / said yes:
- Emails sent / replies:
- Clients / money in each month:

## What worked

## One thing to do next week
""",
}


def _placeholder(title: str, text: str) -> str:
    return _front(["answerrank"]) + f"# {title}\n\n{text}\n\nBack to [[AnswerRank]].\n"


def _named(audit) -> tuple[int, int]:
    """(questions that named them, questions asked) in one audit."""
    asked: dict[str, bool] = {}
    for r in audit.results:
        key = r.prompt or r.probe_id     # each question is asked several times
        asked[key] = asked.get(key, False) or bool(r.mentioned)
    return sum(asked.values()), len(asked)


def _day(iso: str, plus: int = 0) -> str:
    from datetime import datetime, timedelta
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(days=plus)
    except ValueError:
        return iso[:10]
    return d.strftime("%Y-%m-%d")


#: Notes written only from your own data, never committed: what they hold is
#: yours. The committed vault has placeholders at the same paths.
LIVE_STATUSES = ("active", "awaiting_payment", "past_due", "churned")


def _week_fix(store, r, clients) -> str:
    """The week's advice. Before any cold email it's about the pilots: "send
    150 more cold emails" means nothing to someone with no mailbox yet."""
    from datetime import datetime, timezone

    from .casestudy import MIN_DAYS

    pilots = [c for c in clients if c.plan == "pilot" and c.status == "active"]
    if r["week"]["sent"] or store.sends_today() or not pilots:
        return r["fix"]
    ready, waiting = [], []
    for c in pilots:
        audits = store.audit_history(c.business.id, limit=24, comparable=True)
        if not audits:
            waiting.append(c.business.name)
            continue
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(audits[-1].created_at.replace("Z", "+00:00"))).days
        if age >= MIN_DAYS and len(audits) >= 2:
            ready.append(f"[[{_title(c.business.name)}]]")
    if ready:
        return ("The before-and-after is ready for " + ", ".join(ready) + ". Read it, "
                "and if it says it's worth publishing, ask them for a sentence in their own "
                "words: that's what sells the service to the next business.")
    if waiting:
        return ("Open AnswerRank for ten minutes so " + ", ".join(waiting)
                + " get their first measurement.")
    return ("You're in the pilot stage. Make sure each pilot has their report and "
            "files, and that the changes are going onto their website: the result "
            "depends on it. Open AnswerRank once a month for the next measurement.")


def _coming_up(store, c, now) -> list[tuple[str, str]]:
    """One client's dated steps ahead (see dates.py), worded for the vault."""
    from .dates import SAYS, ahead

    link = f"[[{_title(c.business.name) or c.id}]]"
    return [(d, SAYS[kind].format(who=link)) for d, kind in ahead(store, c, now)]


def _dated(rows: list[tuple[str, str]]) -> list[str]:
    from datetime import date
    out = []
    for d, text in rows:
        try:
            label = f"**{d}** ({date.fromisoformat(d).strftime('%a')})"
        except ValueError:
            label = f"**{d}**"
        out.append(f"- {label}: {text}")
    return out


#: More than this and the rest are counted, not listed: the note is a glance.
TODAY_MAX = 8


def _today(store, settings, now) -> list[str]:
    """The console's Today list, most urgent first, for reading in Obsidian
    (on your phone too, if your vault syncs) without opening AnswerRank."""
    from . import today

    items = [i for i in today.next_actions(store, settings, now)["items"]
             # The console shows sending problems in its own banner, and for
             # pilots with no mailbox they are beside the point.
             if i["key"] != "blocked"]
    out = ["## Today", "", "As of the time above. The Today tab in AnswerRank is "
           "always current.", ""]
    out += [f"- **{i['title']}**: {i['detail']}" for i in items[:TODAY_MAX]]
    if len(items) > TODAY_MAX:
        out.append(f"- …and {len(items) - TODAY_MAX} more on the Today tab.")
    if not items:
        out.append("- Nothing needs you right now.")
    return out + [""]


def _week_note(store, settings, now, clients) -> tuple[str, str]:
    """This week's review as a note of its own. It's rewritten until the week
    ends and then left as it was, so the folder becomes the business's diary."""
    from datetime import timedelta

    from . import weekly

    year, week, _ = now.isocalendar()
    name = f"Week {year}-W{week:02d}"
    monday = (now - timedelta(days=now.weekday())).date()
    r = weekly.review(store, settings, now)
    w, k = r["week"], r["kpis"]
    measured = sorted({c.business.name for c in clients
                       for a in store.audit_history(c.business.id, limit=3, comparable=True)
                       if _day(a.created_at) >= monday.isoformat()})
    funnel = [f"- {st['label']}: {st['value']:.0%} (healthy {st['healthy']})"
              + ("" if st["ok"] else " **fix this**") if st["judged"]
              else f"- {st['label']}: too early to judge" for st in r["steps"]]
    lines = [f"# {name}", "",
             f"Monday {monday.isoformat()} to Sunday {(monday + timedelta(days=6)).isoformat()}. "
             f"Rewritten each hour until the week ends, then kept as it was.", "",
             "## This week",
             f"- {w['sent']} cold emails sent, {w['replied']} replies",
             f"- {w['calls']} calls, {w['booked']} walkthroughs booked, "
             f"{w['won']} signed up, {w['paid']} paid",
             "- Measured: " + (", ".join(f"[[{_title(n)}]]" for n in measured) or "nobody"),
             f"- Now: {int(k['active_clients'])} client(s), "
             f"${store.mrr():,.0f} a month coming in", ""]
    sunday = (monday + timedelta(days=6)).isoformat()
    due = sorted((d, t) for c in clients for d, t in _coming_up(store, c, now) if d <= sunday)
    if due:
        lines += ["## Dates this week", *_dated(due), ""]
    lines += ["## The funnel (last 30 days)", *funnel, "",
             "## The one thing to change", _week_fix(store, r, clients), ""]
    if r["upcoming"]:
        lines += ["## Booked for next week",
                  *[f"- {u['when']}: {u['kind']}, {u['name']}" for u in r["upcoming"]], ""]
    lines += ["Your own thoughts on the week go in a note from the Weekly review "
              "template. Back to [[Dashboard]]."]
    return name, _front(["answerrank", "week"], week=f"{year}-W{week:02d}") + "\n".join(lines) + "\n"


def live_notes(store, settings) -> dict[str, str]:
    """A dashboard, and a note per client and pilot, from your database."""
    from datetime import datetime, timezone

    from . import casestudy, knowledge
    from .casestudy import MIN_DAYS

    now = datetime.now(timezone.utc)
    clients = [c for status in LIVE_STATUSES for c in store.get_clients(status)]
    notes: dict[str, str] = {}
    index, pilots, ahead = [], [], []
    for c in clients:
        audits = store.audit_history(c.business.id, limit=24, comparable=True)
        name = _title(c.business.name) or c.id
        known = c.business.vertical in knowledge.VERTICALS
        trade = knowledge.get(c.business.vertical).label.capitalize()
        trade_link = f"[[{_title(trade)}]]" if known else trade
        plan = "free pilot" if c.plan == "pilot" else f"{c.plan}, ${c.mrr:,.0f} a month"
        rows = "\n".join(f"| {_day(a.created_at)} | {a.score:.0f} | {n} of {t} |"
                         for a in reversed(audits) for n, t in [_named(a)])
        from .sales import pilot_ends
        until = f" Free until {pilot_ends(c)}." if c.plan == "pilot" else ""
        body = [f"# {c.business.name}", "",
                f"{trade_link} in {c.business.market}. {plan.capitalize()}, "
                f"{c.status.replace('_', ' ')}, since {_day(c.started_at)}.{until}", ""]
        if audits:
            first, last = audits[-1], audits[0]
            age = (now - datetime.fromisoformat(first.created_at.replace("Z", "+00:00"))).days
            body += ["## Measurements", "", "| Date | Score (out of 100) | Named in |",
                     "| --- | --- | --- |", rows, "",
                     f"Next measurement from {_day(last.created_at, 28)}, while "
                     f"AnswerRank is running.", ""]
            if age >= MIN_DAYS and len(audits) >= 2:
                _ev, text = casestudy.write_up(store, c)
                text = "\n".join(text.splitlines()[1:]).replace("\n## ", "\n### ")
                body += ["## Before and after", text.strip(), ""]
            else:
                body += [f"Before-and-after from {_day(first.created_at, MIN_DAYS)}.", ""]
            score = f"{first.score:.0f} → {last.score:.0f}" if len(audits) > 1 else f"{first.score:.0f}"
        else:
            body += ["Not measured yet: the first measurement runs within the hour "
                     "while AnswerRank is open.", ""]
            score = "not yet"
        theirs = _coming_up(store, c, now)
        ahead += theirs
        if theirs:
            body += ["## Coming up", *_dated(theirs), ""]
        body += ["*Rewritten by AnswerRank each hour. Keep your own notes about them "
                 "in a separate note (the Pilot log template) that links here.*", "",
                 "Part of [[Clients]]." + (" See [[Pilots]]." if c.plan == "pilot" else "")]
        notes[f"{ROOT}/Clients/{name}.md"] = _front(
            ["answerrank", "client"] + (["pilot"] if c.plan == "pilot" else []),
            plan=c.plan, status=c.status) + "\n".join(body) + "\n"
        index.append(f"| [[{name}]] | {plan} | {c.status.replace('_', ' ')} | {score} |")
        if c.plan == "pilot" and c.status == "active":
            pilots.append(f"- [[{name}]]: score {score}")

    notes[f"{ROOT}/Clients.md"] = _front(["answerrank", "clients"]) + "# Clients\n\n" + (
        "| Client | Plan | Status | Score |\n| --- | --- | --- | --- |\n" + "\n".join(index)
        if index else "No clients or pilots yet. See [[Pilots]].") + "\n\nBack to [[AnswerRank]].\n"

    week_name, week_note = _week_note(store, settings, now, clients)
    notes[f"{ROOT}/Weeks/{week_name}.md"] = week_note

    paying = store.get_clients("active")
    stages = store.count_prospects_by_stage()
    drafts = len(store.get_messages("drafted", 500))
    lines = [f"# Dashboard", "", f"Updated {now.strftime('%Y-%m-%d %H:%M')} UTC by AnswerRank.", "",
             *_today(store, settings, now),
             "## Money",
             f"- Coming in each month: **${store.mrr():,.0f}** from "
             f"{sum(1 for c in paying if c.mrr > 0)} paying client(s)",
             f"- Signed, waiting to pay: {len(store.get_clients('awaiting_payment'))}",
             f"- Goal: ${settings.profit_target_monthly:,.0f} a month. See [[Plan]].", "",
             f"This week so far: [[{week_name}]]", "",
             "## Pilots", *(pilots or ["- None yet. See [[Pilots]]."]), "",
             *(["## Coming up", *_dated(sorted(ahead)), ""] if ahead else []),
             "## Waiting for you",
             f"- {drafts} email(s) in the Inbox" if drafts else "- Nothing in the Inbox", ""]
    if stages:
        lines += ["## Businesses found", "", "| Stage | How many |", "| --- | --- |"]
        lines += [f"| {k.replace('_', ' ')} | {v} |" for k, v in sorted(stages.items())] + [""]
    lines += ["Back to [[AnswerRank]]."]
    notes[f"{ROOT}/Dashboard.md"] = _front(["answerrank", "dashboard"]) + "\n".join(lines) + "\n"
    return notes


def build() -> dict[str, str]:
    """Every note, as {path inside the vault: Markdown}."""
    from . import evidence, knowledge, research
    from .config import Settings

    agents = _agents()
    questions = {r.subject: r.question for r in research.RESEARCHERS}
    names = _evidence_names()
    trades = sorted(knowledge.VERTICALS.values(), key=lambda v: v.label)
    settings = Settings()
    prices = {v.key: settings.quote_for(v.key) for v in trades}

    notes = {
        f"{ROOT}/AnswerRank.md": _home(len(agents), len(trades), len(evidence.LIBRARY)),
        f"{ROOT}/Plan.md": _plan(),
        f"{ROOT}/Pilots.md": _pilots(),
        f"{ROOT}/Pilot Kit.md": _pilot_kit(),
        f"{ROOT}/Costs.md": _costs(),
        f"{ROOT}/Decisions.md": _decisions(),
        f"{ROOT}/Links.md": _links(),
        f"{ROOT}/Agents.md": _agents_moc(agents),
        f"{ROOT}/Trades.md": _trades_moc(trades, prices),
        f"{ROOT}/Research.md": _research_moc(names),
        f"{ROOT}/Dashboard.md": _placeholder(
            "Dashboard", "Your live numbers appear here once AnswerRank writes to your "
            "own vault: in Keys and settings, give it your vault's folder. It's "
            "refreshed every hour while AnswerRank runs: what needs you today (the "
            "same list as the Today tab), the money coming in, and the dates coming "
            "up for each pilot: the next measurement, the before-and-after, the "
            "offer and the end of the free months."),
        f"{ROOT}/Clients.md": _placeholder(
            "Clients", "A note for each client and pilot appears here once AnswerRank "
            "writes to your own vault: their scores over time, the next measurement "
            "and, after 45 days, the before-and-after. See [[Pilots]]."),
    }
    for a in agents:
        sources = [(names[e.key], _prose(e.so_we).split(". ")[0].rstrip(".") + ".")
                   for e in evidence.for_agent(a.name)]
        notes[f"{ROOT}/Agents/{_agent_note_name(a.name)}.md"] = _agent_note(
            a, questions.get(a.name, ""), sources)
    for v in trades:
        notes[f"{ROOT}/Trades/{_title(v.label.capitalize())}.md"] = _trade_note(v, prices[v.key])
    for key, e in evidence.LIBRARY.items():
        notes[f"{ROOT}/Research/{names[key]}.md"] = _research_note(e)
    for name, body in TEMPLATES.items():
        notes[f"{ROOT}/Templates/{name}.md"] = body
    return notes


def links_in(text: str) -> list[str]:
    """The note names a page links to (``[[Name]]`` or ``[[Name|label]]``)."""
    return [m.split("|")[0].strip() for m in re.findall(r"\[\[([^\]]+)\]\]", text)]


def write(out_dir: str | Path = "vault", store=None, settings=None) -> list[Path]:
    """Write every note under ``out_dir``/AnswerRank, plus the live ones when
    given a store. Generated notes are replaced; any note you added yourself
    is left alone, and nothing is written outside the AnswerRank folder."""
    out = Path(out_dir)
    if store is not None and not out.is_dir():
        raise FileNotFoundError(f"no folder at {out}")
    notes = build()
    if store is not None:
        notes.update(live_notes(store, settings))
    written = []
    for rel, body in notes.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written
