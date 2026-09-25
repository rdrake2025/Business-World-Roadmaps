"""The Friday review, done for you.

The sales playbook asks for 45 minutes every Friday: open the dashboard,
walk the funnel, find the one step that isn't converting, fix that. Nobody
does that reliably at the end of a week of calls. This does the walk and
sends the answer:

* the week in numbers: emails, replies, calls, walkthroughs, sign-ups, money;
* each funnel step against the healthy range from the playbook, judged only
  when there is enough data to mean something (a 0% reply rate on 20 emails
  is noise, and acting on noise is how good sequences get thrown away);
* the one thing to change: the earliest broken step, because fixing a later
  one while an earlier one leaks is wasted work;
* what is already booked for next week.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

SPOKE = {"send_report", "booked", "not_interested", "callback", "do_not_call"}


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    healthy: str
    #: The rate below which the step counts as broken, and the sample it
    #: needs before it is judged at all.
    floor: float
    sample: int
    fix: str


#: In funnel order: the earliest broken one is the one to fix. Ranges are the
#: playbook's (02_SALES_PLAYBOOK.md, "The numbers that matter").
STEPS = (
    Step("delivered", "Emails delivered", "over 95%", 0.95, 50,
         "Deliverability. Cold emails are bouncing: check the email domain "
         "(desktop button > 3 Email domain) and pause cold sending until it's green."),
    Step("reply", "Reply rate", "1-3%", 0.01, 150,
         "The offer or the targeting. Look at reply rate by trade on the Brain tab "
         "and move toward the trade that answers; lean on calls meanwhile, which "
         "don't depend on anyone opening an email."),
    Step("booked", "Replies and calls to walkthroughs", "over 40%", 0.40, 5,
         "Getting to the walkthrough. When someone replies, call them the same day "
         "rather than emailing back, and add a booking link (Keys and settings) so "
         "they can pick a time themselves."),
    Step("close", "Walkthroughs to sign-ups", "over 30%", 0.30, 3,
         "The walkthrough itself. Talk less: show the test log, stop at the "
         "competitor row, then ask for the card on the call (sales playbook, "
         "'The call')."),
)


def _counts(store, days: int, now: datetime) -> dict[str, int]:
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    c: dict[str, int] = {}
    for kind in ("sent", "bounced", "replied", "won", "paid", "lost", "churned"):
        c[kind] = sum(1 for r in store.outcomes_with_prefix(kind, days=days + 1)
                      if r["kind"] == kind and r["occurred_at"] >= since)
    calls = [r for r in store.outcomes_with_prefix("call_", days=days + 1)
             if r["occurred_at"] >= since]
    c["calls"] = len(calls)
    c["spoke"] = sum(1 for r in calls if r["kind"][5:] in SPOKE)
    c["booked"] = sum(1 for r in calls if r["kind"] == "call_booked")
    c["reports"] = sum(1 for r in calls if r["kind"] == "call_send_report")
    held = [r for r in store.outcomes_with_prefix("walkthrough", days=days + 1)
            if r["occurred_at"] >= since and r.get("sentiment") != "rebook"]
    c["walkthroughs"] = len(held)
    c["signed_after"] = sum(1 for r in held if r.get("sentiment") == "signed")
    return c


def _rates(c: dict[str, int]) -> dict[str, tuple[float | None, int]]:
    """Each step's rate and the sample it rests on."""
    def rate(num: int, den: int) -> tuple[float | None, int]:
        return (num / den if den else None, den)
    return {
        "delivered": rate(c["sent"] - c["bounced"], c["sent"]),
        "reply": rate(c["replied"], c["sent"]),
        "booked": rate(c["booked"], c["replied"] + c["spoke"]),
        "close": rate(c["signed_after"], c["walkthroughs"]),
    }


def review(store, settings, now: datetime | None = None) -> dict[str, Any]:
    from . import calls
    from .agents.bookkeeper import BookkeeperAgent

    now = now or datetime.now(timezone.utc)
    week = _counts(store, 7, now)
    # Rates are judged over 30 days: a week of a new business is too few.
    month = _counts(store, 30, now)
    rates = _rates(month)

    steps, broken = [], None
    for s in STEPS:
        value, sample = rates[s.key]
        judged = value is not None and sample >= s.sample
        ok = judged and value >= s.floor
        steps.append({"key": s.key, "label": s.label, "healthy": s.healthy,
                      "value": value, "sample": sample, "judged": judged,
                      "ok": ok, "fix": s.fix})
        if judged and not ok and broken is None:
            broken = steps[-1]

    if broken:
        fix = broken["fix"]
    elif not any(st["judged"] for st in steps):
        need = max(0, STEPS[1].sample - month["sent"])
        fix = ("Too early to judge anything, and that's normal. Keep the volume up: "
               + (f"about {need} more cold emails before the reply rate means "
                  f"something, and " if need else "")
               + "calls every weekday morning and late afternoon.")
    else:
        fix = ("Nothing measurable is broken. The lever now is volume: more calls "
               "and more first emails approved each day.")

    upcoming = []
    prospects = {p.id: p for p in store.get_prospects(limit=10_000)}
    for apt in store.appointments():
        start = calls.parse_when(apt["starts_at"])
        if start and now <= start <= now + timedelta(days=7):
            p = prospects.get(apt["prospect_id"])
            if p:
                upcoming.append({
                    "kind": "Walkthrough" if apt["kind"] == "meeting" else "Call back",
                    "name": p.business.name,
                    "when": calls.local_in(calls.operator_tz(settings), start)
                    .strftime("%a %I:%M %p").replace(" 0", " ")})

    kpis = BookkeeperAgent(store, settings).kpis()
    return {"week": week, "steps": steps, "fix": fix,
            "broken": broken["label"] if broken else "",
            "upcoming": upcoming, "kpis": kpis}


def email(r: dict[str, Any], console: str = "") -> tuple[str, str]:
    w, k = r["week"], r["kpis"]
    subject = (f"Your week: {w['won']} signed, {w['calls']} calls, "
               f"{w['sent']} emails. " + ("Fix: " + r["broken"] if r["broken"]
                                          else "Nothing broken"))
    lines = [
        "Here's the week, and the one thing to change.",
        "",
        "THIS WEEK",
        f"- {w['sent']} cold emails sent, {w['replied']} replies",
        f"- {w['calls']} calls: {w['spoke']} conversations, {w['reports']} reports "
        f"sent, {w['booked']} walkthroughs booked",
        f"- {w['walkthroughs']} walkthroughs held, {w['won']} signed up, "
        f"{w['paid']} paid",
        f"- Now: {int(k['active_clients'])} paying clients, ${k['profit']:,.0f} profit "
        f"a month of ${k['target']:,.0f} ({k['pct_to_target']:.0f}%)",
        "",
        "THE FUNNEL (last 30 days, against healthy)",
    ]
    for s in r["steps"]:
        if s["judged"]:
            mark = "ok" if s["ok"] else "FIX"
            lines.append(f"- {s['label']}: {s['value']:.0%} (healthy {s['healthy']}) {mark}")
        else:
            lines.append(f"- {s['label']}: too early (from {s['sample']} so far)")
    lines += ["", "THE ONE THING TO CHANGE", r["fix"]]
    if r["upcoming"]:
        lines += ["", "ALREADY BOOKED FOR NEXT WEEK"]
        lines += [f"- {u['when']}: {u['kind']}, {u['name']}" for u in r["upcoming"]]
    if console:
        lines += ["", f"Open your console: {console}"]
    return subject[:140], "\n".join(lines)
