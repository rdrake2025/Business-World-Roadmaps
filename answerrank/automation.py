"""The switches that decide how much runs without you.

Kept in the database rather than answerrank.yml: they are flipped from the
phone, take effect on the next cycle, and the server has its own copy of the
config file that the phone cannot edit.

Every switch only ever skips a step *you* would have taken; none of them
lifts a guard rail. The warm-up cap, the bounce brake, the suppression list,
the playbook checker and the sending blockers apply exactly as they do when
you tap the buttons yourself.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Switch:
    key: str
    label: str
    explain: str
    default: bool


SWITCHES: dict[str, Switch] = {s.key: s for s in (
    Switch("autopilot", "Autopilot: run the whole business for me",
           "Every email the fleet writes goes out without waiting for you: first "
           "emails (once you have read the first 20), follow-ups, answers to "
           "replies, reports, payment links, welcomes and monthly reports. Anything "
           "it cannot answer properly is held and emailed to you at once, and the "
           "Guardian pauses any part that starts going wrong.",
           False),
    Switch("auto_send", "Send approved emails for me",
           "Anything you approve goes out on its own: answers to people who wrote "
           "to you from 7am to 9pm, cold emails on weekday business hours. Caps and "
           "brakes still apply. Off means you tap Send yourself.",
           True),
    Switch("approve_followups", "Approve follow-ups automatically",
           "Follow-ups 2 to 4 of a sequence you already approved the start of. They "
           "are written from the same template and pass the same checks. First "
           "emails always wait for you.",
           False),
    Switch("approve_reports", "Approve reports people asked for",
           "When someone replies yes or asks on a call, their report goes without "
           "waiting for you. It is the same report every time, built from their "
           "audit.",
           False),
)}


def enabled(store, key: str) -> bool:
    raw = store.kv_get(f"auto.{key}")
    if raw in (None, ""):
        return SWITCHES[key].default
    return raw == "1"


def set_switch(store, key: str, on: bool) -> None:
    if key not in SWITCHES:
        raise KeyError(key)
    store.kv_set(f"auto.{key}", "1" if on else "0")
    if key == "autopilot" and on:
        # Autopilot approves; nothing reaches anyone unless something sends.
        store.kv_set("auto.auto_send", "1")


# ---------------------------------------------------------------------------
# Autopilot
# ---------------------------------------------------------------------------

#: First emails you read yourself before Autopilot writes them alone. They
#: are the one message that goes to a stranger, so the drafts are checked
#: by a person on real businesses before any go out unread: about two days
#: of sending during warm-up.
SUPERVISED_FIRST_EMAILS = 20

#: The parts of the business the Guardian can pause on its own. Each email
#: kind belongs to one of them.
STAGES = {
    "prospecting": "First emails and follow-ups to businesses that haven't replied",
    "answers": "Answers, reports and payment links to people who wrote in",
    "clients": "Welcomes and monthly reports to paying clients",
}
STAGE_OF = {"cold": "prospecting", "reply": "answers", "report": "answers",
            "invoice": "answers", "welcome": "clients", "client_report": "clients",
            "client_care": "clients"}


def supervised(store) -> int:
    """First emails you have approved yourself, towards Autopilot's start."""
    try:
        return int(store.kv_get("autopilot.supervised") or 0)
    except ValueError:
        return 0


def note_supervised(store, n: int) -> None:
    if n > 0:
        store.kv_set("autopilot.supervised", str(supervised(store) + n))


def paused(store, stage: str) -> str:
    """Why the Guardian paused this part, or "" if it is running."""
    return store.kv_get(f"guardian.pause.{stage}") or ""


def pause(store, stage: str, reason: str) -> None:
    store.kv_set(f"guardian.pause.{stage}", reason)


def resume(store, stage: str) -> None:
    store.kv_set(f"guardian.pause.{stage}", "")


def auto_approve(store, kind: str, step: int = 1) -> bool:
    """Whether an email of this kind goes out without you reading it first.

    One answer for every agent that writes email, so the Outreach agent, the
    Concierge, the Onboarder, the Reporter and the Bookkeeper cannot
    disagree about what runs by itself. A paused stage always waits.
    """
    kind = kind or "cold"
    if paused(store, STAGE_OF.get(kind, "answers")):
        return False
    if enabled(store, "autopilot"):
        if kind == "cold" and step <= 1:
            return supervised(store) >= SUPERVISED_FIRST_EMAILS
        return True
    if kind == "cold":
        return step > 1 and enabled(store, "approve_followups")
    if kind == "report":
        return enabled(store, "approve_reports")
    return False


def sync(store, settings) -> None:
    """Carry the switch into what's offered: no done-for-you plan on
    Autopilot, since nobody is there to do it."""
    settings.sell_managed = not enabled(store, "autopilot")


def sending_on(store) -> bool:
    return enabled(store, "auto_send") or enabled(store, "autopilot")


def state(store) -> list[dict]:
    return [{"key": s.key, "label": s.label, "explain": s.explain,
             "on": enabled(store, s.key)} for s in SWITCHES.values()]
