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


def state(store) -> list[dict]:
    return [{"key": s.key, "label": s.label, "explain": s.explain,
             "on": enabled(store, s.key)} for s in SWITCHES.values()]
