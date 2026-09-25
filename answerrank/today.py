"""Up next: everything that needs you, in the order to do it.

The console had the right information spread across five tabs: drafts in
one, replies in another, the call list, payments, client health. Running
the business meant visiting each, every time, and deciding for yourself
which mattered most. This decides for you, and every item carries the one
action that deals with it.

The order is how much money is at stake and how fast it goes cold:

1. Anything blocking sending, because nothing else reaches anyone.
2. A walkthrough starting soon, then one that has just happened and needs
   its result: a yes there is the payment link, one tap away.
3. Someone who wrote back and is ready to buy.
4. A call back you promised, now due.
5. Answers and reports drafted for people who asked.
6. Calls, while it's a good time to reach owners.
7. A client who said yes and hasn't paid.
8. First emails and follow-ups to read.
9. Approved emails, if nothing is sending them for you.
10. Clients whose account needs saving.

An empty list is the goal, and says so.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

WARM = {"reply", "report", "welcome", "invoice", "client_report"}
HOT_INTENTS = {"ready_to_buy", "interested"}


def _item(key: str, tone: str, title: str, detail: str, action: dict[str, Any],
          count: int = 1) -> dict[str, Any]:
    return {"key": key, "tone": tone, "title": title, "detail": detail,
            "action": action, "count": count}


def _latest_intent(store, prospect_id: str) -> str:
    for row in store.outcomes_for(prospect_id, 20):
        if row.get("kind") == "replied":
            return row.get("sentiment") or ""
    return ""


def next_actions(store, settings, now: datetime | None = None) -> dict[str, Any]:
    from . import automation, calls, payments
    from .agents.outreach import OutreachAgent
    from .agents.retention import RetentionAgent

    now = now or datetime.now(timezone.utc)
    items: list[dict[str, Any]] = []
    prospects = {p.id: p for p in store.get_prospects(limit=10_000)}

    # 1. Blocked sending
    blockers = OutreachAgent(store, settings).preflight()
    if blockers:
        items.append(_item("blocked", "warn", "Sending is blocked", blockers[0],
                           {"type": "none"}))

    # 2 and 11. Walkthroughs: about to start, just finished, later today
    later_today, finished = [], []
    for apt in store.appointments(kind="meeting"):
        start = calls.parse_when(apt["starts_at"])
        p = prospects.get(apt["prospect_id"])
        if not start or not p or start < now - timedelta(days=14):
            continue
        mine = calls.local_in(calls.operator_tz(settings), start)
        clock = mine.strftime("%I:%M %p").lstrip("0").lower()
        if start <= now - timedelta(minutes=30):
            finished.append(_item(f"debrief:{apt['id']}", "hot",
                                  f"How did the walkthrough with {p.business.name} go?",
                                  "One tap: signed up, call back, or not for them. A yes "
                                  "sends the payment link.",
                                  {"type": "debrief", "id": p.id}))
        elif start <= now + timedelta(hours=2):
            items.append(_item(f"meeting:{apt['id']}", "hot",
                               f"{clock}: walkthrough with {p.business.name}",
                               "Open their report and the call notes before you dial.",
                               {"type": "call", "id": p.id}))
        elif start <= now + timedelta(hours=18):
            later_today.append((clock, p))
    items.extend(finished)

    # 3 and 5. Drafts for people who wrote to us
    drafts = store.get_messages("drafted", 500)
    warm = [m for m in drafts if (m.kind or "cold") in WARM]
    hot = []
    for m in warm:
        if _latest_intent(store, m.prospect_id) in HOT_INTENTS:
            hot.append(m)
    for m in hot[:3]:
        p = prospects.get(m.prospect_id)
        name = p.business.name if p else "Someone"
        ready = _latest_intent(store, m.prospect_id) == "ready_to_buy"
        items.append(_item(f"hot:{m.id}", "hot",
                           f"{name} {'wants to start' if ready else 'wants the report'}",
                           "The answer is drafted"
                           + (" with the payment link" if ready else "")
                           + ". Read it and approve.",
                           {"type": "review", "id": m.id}))

    # 4. Call backs due, and 6. calls
    call_list = calls.call_list(store, settings, now=now, limit=200)
    due = [c for c in call_list["items"] if c["window"] == "callback"]
    if due:
        items.append(_item("callbacks", "now",
                           f"Call back {due[0]['name']}"
                           + (f" and {len(due) - 1} more" if len(due) > 1 else ""),
                           "They asked you to call about now.",
                           {"type": "calls"}, len(due)))

    rest = [m for m in warm if m not in hot]
    if rest:
        items.append(_item("warm", "now",
                           f"{len(rest)} answer{'s' if len(rest) != 1 else ''} to people "
                           f"who asked", "Replies, reports and welcomes. They go first.",
                           {"type": "review"}, len(rest)))

    good = [c for c in call_list["items"] if c["window"] == "good"]
    if good:
        items.append(_item("calls", "now",
                           f"Call {len(good)} business{'es' if len(good) != 1 else ''}",
                           "A good time to reach owners where they are. Tap to start "
                           "calling; the next one opens as you log each call.",
                           {"type": "calls"}, len(good)))

    # 7. Payments
    for w in payments.waiting_summary(store, settings):
        if w["overdue"] or w["days"] >= settings.payment_reminder_days:
            items.append(_item(f"pay:{w['id']}", "todo",
                               f"{w['name']} hasn't paid ({w['days']} days)",
                               "Call them. Copy the pay link from Clients if they've "
                               "lost it.", {"type": "pane", "pane": "clients"}))

    # 8. Cold drafts
    cold = [m for m in drafts if (m.kind or "cold") == "cold"]
    if cold:
        first = sum(1 for m in cold if m.sequence_step == 1)
        follow = len(cold) - first
        parts = []
        if first:
            parts.append(f"{first} first email{'s' if first != 1 else ''}")
        if follow:
            parts.append(f"{follow} follow-up{'s' if follow != 1 else ''}")
        items.append(_item("cold", "todo", "Read " + " and ".join(parts),
                           "About ten seconds each. They go out under your name.",
                           {"type": "review"}, len(cold)))

    # 9. Approved, and nothing sending them
    approved = len(store.send_queue(500))
    if approved and not blockers and not automation.enabled(store, "auto_send"):
        items.append(_item("send", "todo", f"Send {approved} approved",
                           "Or switch on 'Send approved emails for me' below.",
                           {"type": "send"}, approved))

    # 10. Clients at risk
    for h in RetentionAgent(store, settings).portfolio():
        if h.band == "act_now":
            items.append(_item(f"client:{h.client_id}", "todo",
                               f"Save {h.name}", h.action, {"type": "pane", "pane": "clients"}))

    for clock, p in later_today:
        items.append(_item(f"later:{p.id}", "info", f"{clock}: walkthrough with {p.business.name}",
                           "Coming up. Their report is ready when you are.",
                           {"type": "call", "id": p.id}))

    open_calls = [c for c in call_list["items"] if c["window"] == "open"]
    if open_calls and not good:
        items.append(_item("calls-open", "info",
                           f"{len(open_calls)} business{'es' if len(open_calls) != 1 else ''} "
                           f"to call", "Owners are usually easier to reach 8-9:30am and "
                           "4-6pm their time.", {"type": "calls"}, len(open_calls)))

    return {"items": items, "done": not any(i["tone"] in {"hot", "now", "todo", "warn"}
                                             for i in items),
            "calls_today": call_list["today"]}
