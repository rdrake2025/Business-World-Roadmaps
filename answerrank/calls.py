"""Cold calls: who to ring, what to say, and what happened.

Email was the only channel, so a prospect whose email went unanswered, or who
had no public address at all, was simply lost. Owners of trades businesses
answer the phone; that is how their customers reach them. This gives the
operator a call list built from the same audits the emails use, a script that
opens with the one true, specific thing the audit found, and one tap to record
what happened, which the rest of the system acts on.

The system never dials. Calls are placed by hand from the operator's own
phone, to the business numbers the businesses publish. That keeps them within
the business-to-business exemption of the FTC's Telemarketing Sales Rule,
which does not cover misleading anyone and does not survive continuing to
pitch someone who has said they have no need. So the script only quotes what
an audit actually recorded, never claims to be from an AI company, never
promises a placement, and "not interested" or "don't call" stops calls and
email to that business at once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from . import knowledge
from .models import Prospect, now_iso

#: Prospects in these stages have been audited and not yet talked to.
CALLABLE_STAGES = ("audited", "queued", "contacted", "following_up")
#: Attempts before a business is left alone. Four rings over about a week and
#: a half is persistent; more is a nuisance.
MAX_ATTEMPTS = 4

#: Weekday hours in the business's own time zone. Owners of trades
#: businesses are easiest to reach before the first job and after the last.
OPEN_HOURS = (8, 18)
GOOD_WINDOWS = ((8.0, 9.5), (16.0, 18.0))


@dataclass(frozen=True)
class Outcome:
    key: str
    label: str
    #: Nothing more to call about: the conversation happened or was refused.
    final: bool
    #: Days before calling again (non-final outcomes only).
    retry_days: int = 0


OUTCOMES: dict[str, Outcome] = {o.key: o for o in (
    Outcome("no_answer", "No answer", final=False, retry_days=1),
    Outcome("voicemail", "Left a voicemail", final=False, retry_days=2),
    Outcome("callback", "Call back later", final=False, retry_days=1),
    Outcome("send_report", "Send them the report", final=True),
    Outcome("booked", "Booked a call", final=True),
    Outcome("not_interested", "Not interested", final=True),
    Outcome("do_not_call", "Don't call again", final=True),
    Outcome("wrong_number", "Wrong number", final=True),
)}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


# ---------------------------------------------------------------------------
# Their local time
# ---------------------------------------------------------------------------

#: Each state's main time zone. A handful of states span two; the call list
#: says "about" for those rather than pretending to precision.
STATE_TZ = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix",
    "AR": "America/Chicago", "CA": "America/Los_Angeles", "CO": "America/Denver",
    "CT": "America/New_York", "DE": "America/New_York", "DC": "America/New_York",
    "FL": "America/New_York", "GA": "America/New_York", "HI": "Pacific/Honolulu",
    "ID": "America/Boise", "IL": "America/Chicago", "IN": "America/Indiana/Indianapolis",
    "IA": "America/Chicago", "KS": "America/Chicago", "KY": "America/New_York",
    "LA": "America/Chicago", "ME": "America/New_York", "MD": "America/New_York",
    "MA": "America/New_York", "MI": "America/Detroit", "MN": "America/Chicago",
    "MS": "America/Chicago", "MO": "America/Chicago", "MT": "America/Denver",
    "NE": "America/Chicago", "NV": "America/Los_Angeles", "NH": "America/New_York",
    "NJ": "America/New_York", "NM": "America/Denver", "NY": "America/New_York",
    "NC": "America/New_York", "ND": "America/Chicago", "OH": "America/New_York",
    "OK": "America/Chicago", "OR": "America/Los_Angeles", "PA": "America/New_York",
    "RI": "America/New_York", "SC": "America/New_York", "SD": "America/Chicago",
    "TN": "America/Chicago", "TX": "America/Chicago", "UT": "America/Denver",
    "VT": "America/New_York", "VA": "America/New_York", "WA": "America/Los_Angeles",
    "WV": "America/New_York", "WI": "America/Chicago", "WY": "America/Denver",
}
SPLIT_STATES = {"FL", "ID", "IN", "KS", "KY", "MI", "NE", "ND", "OR", "SD", "TN", "TX"}

#: Standard-time offsets, for a machine with no time zone database (Windows
#: without the tzdata package). Arizona and Hawaii never change their clocks.
_STANDARD = {"America/New_York": -5, "America/Detroit": -5,
             "America/Indiana/Indianapolis": -5, "America/Chicago": -6,
             "America/Denver": -7, "America/Boise": -7, "America/Phoenix": -7,
             "America/Los_Angeles": -8, "America/Anchorage": -9,
             "Pacific/Honolulu": -10}
_NO_DST = {"America/Phoenix", "Pacific/Honolulu"}


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    first = datetime(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def _fallback_local(tz_name: str, now: datetime) -> datetime:
    """US rule: summer time from 2am on the second Sunday of March to 2am on
    the first Sunday of November."""
    offset = _STANDARD.get(tz_name, -6)
    local = (now + timedelta(hours=offset)).replace(tzinfo=None)
    if tz_name not in _NO_DST:
        start = _nth_sunday(local.year, 3, 2).replace(hour=2)
        end = _nth_sunday(local.year, 11, 1).replace(hour=1)
        if start <= local < end:
            local += timedelta(hours=1)
    return local


def local_time(state: str, now: datetime | None = None) -> datetime | None:
    """The wall-clock time where the business is, or None if the state is unknown."""
    tz_name = STATE_TZ.get((state or "").strip().upper())
    if not tz_name:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)
    except Exception:  # noqa: BLE001 - no tz database on this machine
        return _fallback_local(tz_name, now)


def window(local: datetime | None) -> str:
    """good | open | closed | unknown"""
    if local is None:
        return "unknown"
    if local.weekday() >= 5:
        return "closed"
    hour = local.hour + local.minute / 60
    if not OPEN_HOURS[0] <= hour < OPEN_HOURS[1]:
        return "closed"
    return "good" if any(a <= hour < b for a, b in GOOD_WINDOWS) else "open"


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------

def dial_number(phone: str) -> str:
    """+15125550100 for a US number, or the digits as given."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return ("+" + digits) if digits else ""


def pretty_number(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return (phone or "").strip()


# ---------------------------------------------------------------------------
# What to say
# ---------------------------------------------------------------------------

def evidence(audit) -> dict[str, Any]:
    """The one specific, true thing to open with, taken from a real answer.

    Only answers from a live search count. A simulated audit produces
    plausible competitor names that do not exist, and a model answering from
    memory is not what ChatGPT tells a customer (it searches the web for
    local questions). Quoting either to a business owner would be exactly
    the misrepresentation the FTC's business-call rules forbid.
    """
    if audit is None:
        return {"real": False}
    real = [r for r in audit.results
            if not r.error and r.engine != "mock" and getattr(r, "grounded", False)]
    out: dict[str, Any] = {"real": bool(real), "score": round(audit.score),
                           "asked": len(real),
                           "named": sum(1 for r in real if r.mentioned)}
    hit = next((r for r in real if not r.mentioned and r.competitors), None)
    if hit:
        out.update(engine=SPOKEN.get(hit.engine, hit.engine), engine_key=hit.engine,
                   question=hit.prompt, competitor=hit.competitors[0],
                   also=hit.competitors[1:3])
    out["margin"] = getattr(audit, "margin", 0.0)
    return out


#: How each engine is named out loud. The Google check reads the AI Overview
#: together with the map and web results, so it is "Google", not "Google's AI".
SPOKEN = {"openai": "ChatGPT", "anthropic": "Claude", "perplexity": "Perplexity",
          "google_aio": "Google"}


def _a(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def script(prospect: Prospect, ev: dict[str, Any], settings) -> dict[str, Any]:
    biz = prospect.business
    trade = knowledge.get(biz.vertical).label
    a_trade = _a(trade)
    me = (getattr(settings, "your_name", "") or "").strip() or "[your name]"
    number = pretty_number(getattr(settings, "callback_phone", "")) or "[your number]"
    brand = settings.brand
    city = biz.city or "your area"
    emailed = prospect.touches > 0

    if ev.get("competitor"):
        named = _names([ev["competitor"], *ev.get("also", [])])
        if ev.get("engine_key") == "google_aio":
            found = (f"when I searched Google for “{ev['question']}”, it showed "
                     f"{named}. {biz.name} didn't come up.")
        else:
            found = (f"when I asked {ev['engine']} “{ev['question']}”, it "
                     f"recommended {named}. {biz.name} didn't come up.")
        short = (f"I asked {ev['engine']} for {a_trade} in {city}, and it "
                 f"recommended {ev['competitor']} instead of you.")
    elif ev.get("real") and ev.get("asked"):
        found = (f"when I asked AI assistants for {a_trade} in {city}, {biz.name} "
                 f"came up in {ev['named']} of {ev['asked']} answers.")
        short = f"I checked what AI assistants say about {trade}s in {city}."
    else:
        found = (f"I check what AI assistants tell people looking for {a_trade} in "
                 f"{city}, and I'd like to show you what they say about {biz.name}.")
        short = f"I check what AI assistants recommend for {trade}s in {city}."

    return {
        # Gong: stating the reason for the call early doubles success; asking
        # whether it's a bad time costs 40%. So: who, then why, in one breath.
        "opener": (f"Hi, is this the owner? This is {me} with {brand}. The reason "
                   f"I'm calling: {found} Did you know that was happening?"),
        "if_listening": ("More people are asking ChatGPT and Google's AI for a "
                         "recommendation instead of scrolling through results. It names "
                         "two or three businesses, and right now you're not one of them. "
                         "I've put together a free report: the questions you're missing, "
                         "who gets named instead, and the three fixes that change it."
                         + (f" One thing in it: {ev['listing']}" if ev.get("listing") else "")
                         + (" I emailed you about it too." if emailed else "")),
        "ask": "Can I email it over? What's the best address for you?",
        "then": ("If they want to talk: “I can walk you through it in 15 minutes. "
                 "Would Tuesday or Wednesday be better?”"),
        "voicemail": (f"Hi, this is {me} with {brand}, for the owner of {biz.name}. "
                      f"{short} I've put together a free report on why, and how to "
                      f"fix it. Call me back at {number}"
                      + (", or reply to my email" if biz.email else "")
                      + f". Again, {me}, {number}. Thanks."),
        "objections": [
            ("Not interested",
             "“No problem, I won't call again. Have a good day.” Then tap "
             "Not interested. Don't keep pitching; that is the rule for calling "
             "businesses."),
            ("How much is it?",
             f"“The report's free. If you want me to do the work, it's "
             f"${settings.quote_for(biz.vertical):,.0f} a month, cancel any time. "
             f"Let me send the report first so you can see if it's worth it.”"),
            ("We already have someone for SEO",
             "“Good, keep them. They work on where you rank in the list. This is "
             "whether you're named in the AI answer above the list. Ask them what "
             "they're doing about that; if they have a real answer, you don't need "
             "me.”"),
            ("Are you with Google?",
             "“No, I'm independent. I just check what these assistants say.” "
             "Never suggest you're with Google, OpenAI or any AI company."),
        ],
        "never": "Only say what the report shows. Never promise a ranking or placement.",
    }


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------

def _history(store) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in store.outcomes_with_prefix("call_"):
        out.setdefault(row["prospect_id"], []).append(row)
    return out


def _parse(stamp: str) -> datetime:
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def callable_now(prospect: Prospect, history: list[dict[str, Any]],
                 now: datetime) -> tuple[bool, int]:
    """(whether to put them on today's list, attempts so far)."""
    attempts = len(history)
    if attempts >= MAX_ATTEMPTS:
        return False, attempts
    if any(OUTCOMES.get(h["kind"][5:], OUTCOMES["no_answer"]).final for h in history):
        return False, attempts
    if history:
        last = history[0]
        outcome = OUTCOMES.get(last["kind"][5:], OUTCOMES["no_answer"])
        if now < _parse(last["occurred_at"]) + timedelta(days=outcome.retry_days) \
                - timedelta(hours=2):
            return False, attempts
    return True, attempts


def call_list(store, settings, now: datetime | None = None,
              limit: int = 40) -> dict[str, Any]:
    """Who to call, best first: those it's a good time to reach, then by fit."""
    from . import qualify
    from .agents.outreach import worth_pitching
    from .agents.scout import SIMULATED_MARKER

    now = now or datetime.now(timezone.utc)
    history = _history(store)
    rows = []
    for stage in CALLABLE_STAGES:
        for p in store.get_prospects(stage, 10_000):
            if not p.business.phone or SIMULATED_MARKER in (p.notes or ""):
                continue
            if p.business.email and store.is_suppressed(p.business.email):
                continue
            if not worth_pitching(p, settings):
                continue
            ok, attempts = callable_now(p, history.get(p.id, []), now)
            if not ok:
                continue
            local = local_time(p.business.state, now)
            rows.append((p, attempts, local, window(local)))

    order = {"good": 0, "open": 1, "unknown": 2, "closed": 3}
    rows.sort(key=lambda r: (order[r[3]], -qualify.priority(
        r[0].business, r[0].score, r[0].competitor_gap,
        settings.quote_for(r[0].business.vertical))))

    items = []
    for p, attempts, local, when in rows[:limit]:
        items.append({
            "id": p.id, "name": p.business.name, "market": p.business.market,
            "trade": knowledge.get(p.business.vertical).label,
            "phone": pretty_number(p.business.phone),
            "dial": dial_number(p.business.phone),
            "local": local.strftime("%I:%M %p").lstrip("0").lower() if local else "",
            "about": (p.business.state or "").upper() in SPLIT_STATES,
            "window": when, "attempts": attempts, "score": p.score,
        })
    return {"items": items, "count": len(rows), "today": today(store, now)}


def today(store, now: datetime | None = None) -> dict[str, int]:
    """Calls logged in the last 24 hours, by what happened."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    counts: dict[str, int] = {"calls": 0, "spoke": 0, "reports": 0, "booked": 0}
    for row in store.outcomes_with_prefix("call_", days=2):
        if row["occurred_at"] < since:
            continue
        kind = row["kind"][5:]
        counts["calls"] += 1
        if kind in {"send_report", "booked", "not_interested", "callback", "do_not_call"}:
            counts["spoke"] += 1
        if kind == "send_report":
            counts["reports"] += 1
        if kind == "booked":
            counts["booked"] += 1
    return counts


# ---------------------------------------------------------------------------
# What happened
# ---------------------------------------------------------------------------

def log_call(store, settings, prospect: Prospect, outcome: str,
             email: str = "", note: str = "") -> dict[str, Any]:
    """Record a call and act on it. Returns what was done, in words."""
    from .agents.concierge import ConciergeAgent, report_email
    from .models import OutreachMessage

    result = OUTCOMES.get(outcome)
    if result is None:
        return {"error": f"unknown outcome {outcome!r}"}
    biz = prospect.business
    email = (email or "").strip()
    if email and not _EMAIL.match(email):
        return {"error": f"{email!r} doesn't look like an email address"}
    if email and store.is_suppressed(email):
        return {"error": "That address asked not to be emailed. Talk to them first."}
    if outcome == "send_report" and not (email or biz.email):
        return {"error": "Ask for their email address first, then tap Send them the report."}
    if email and email.lower() != (biz.email or "").lower():
        biz.email = email

    store.record_outcome(prospect_id=prospect.id, vertical=biz.vertical,
                         step=prospect.touches, kind=f"call_{outcome}",
                         note=(note or "")[:300])
    prospect.last_touch_at = now_iso()
    next_step = ""
    message_id = ""

    if outcome == "send_report":
        store.withdraw_cold(prospect.id)
        prospect.stage = "replied"
        concierge = ConciergeAgent(store, settings)
        audit = concierge._report_for(prospect)
        subject, body = report_email(
            prospect, audit, settings,
            opening="Thanks for taking my call. Here's the report I mentioned.")
        message = OutreachMessage(prospect_id=prospect.id, subject=subject, body=body,
                                  sequence_step=prospect.touches + 1, status="drafted",
                                  kind="report", scheduled_for=now_iso())
        store.save_message(message)
        message_id = message.id
        next_step = "The report is drafted. Approve it in the inbox and send it today."
    elif outcome == "booked":
        store.withdraw_cold(prospect.id)
        prospect.stage = "replied"
        next_step = ("Booked. Put it in your calendar. The report and the sales "
                     "playbook are what you walk them through.")
    elif outcome == "not_interested":
        store.withdraw_cold(prospect.id)
        store.suppress(biz.email, "declined on a call")
        prospect.stage = "lost"
        store.record_outcome(prospect_id=prospect.id, vertical=biz.vertical,
                             kind="lost", sentiment="not_interested", note="on a call")
        next_step = "They won't be called or emailed again."
    elif outcome == "do_not_call":
        store.withdraw_cold(prospect.id)
        store.suppress(biz.email, "asked not to be contacted, on a call")
        prospect.stage = "suppressed"
        next_step = "Done. No more calls or emails to them."
    elif outcome == "wrong_number":
        biz.phone = ""
        next_step = "Number removed. Their email sequence carries on."
    else:
        next_step = f"On the list again in {result.retry_days} day" \
                    f"{'' if result.retry_days == 1 else 's'}."

    prospect.notes = (prospect.notes or "") + f" | call: {outcome}" \
        + (f" ({note[:80]})" if note else "")
    store.upsert_prospect(prospect)
    if outcome == "wrong_number" or email:
        _save_contact(store, prospect)
    return {"ok": True, "outcome": outcome, "label": result.label,
            "next": next_step, "message_id": message_id}


def _save_contact(store, prospect: Prospect) -> None:
    """Keep the phone and email columns in step with the record itself:
    ``upsert_prospect`` refreshes the email column on conflict, not the phone."""
    with store.writer() as cx:
        cx.execute("UPDATE prospects SET phone = ?, email = ? WHERE id = ?",
                   (prospect.business.phone, prospect.business.email, prospect.id))
