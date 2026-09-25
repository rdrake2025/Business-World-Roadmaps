"""Editing a draft on the phone without breaking it.

Every email is plain text wrapped at 74 columns and, for anything cold or
carrying a report, ends in the legal footer: your company, your postal
address and the unsubscribe line. Editing used to mean skipping the draft,
because the phone had no way to change it. Now it does, with two rules:

* The footer is not yours to edit here. It is split off before you see the
  text and put back exactly as it was, so no edit can drop the address or the
  opt-out the law requires.
* A cold email is checked again after the edit, with the same checks the
  Outreach agent applies to its own drafts (length, no empty nudges).

The text is shown with its line wrapping undone, so it reads naturally in a
phone's text box, and wrapped again on save.
"""

from __future__ import annotations

import re

from . import playbook

_FOOTER = "\n\n---\n"
_LIST = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
#: A line at least this long was probably broken by the wrapper, so the
#: next line continues it. Short lines (a sign-off, a web address) end
#: where the author ended them.
_WRAPPED = playbook.WRAP - 24


def split(body: str) -> tuple[str, str]:
    """(the part you may edit, the legal footer kept as is)."""
    at = body.rfind(_FOOTER)
    if at >= 0 and "unsubscribe" in body[at:].lower():
        return body[:at], body[at:]
    return body, ""


def unwrap(text: str) -> str:
    """Undo the 74-column wrapping, paragraph by paragraph."""
    paragraphs = []
    for para in text.strip().split("\n\n"):
        lines: list[str] = []
        for line in para.split("\n"):
            continues = (lines and line.strip() and not _LIST.match(line)
                         and (line.startswith(" ") or len(lines[-1]) >= _WRAPPED))
            if continues:
                lines[-1] = lines[-1].rstrip() + " " + line.strip()
            else:
                lines.append(line.rstrip())
        paragraphs.append("\n".join(lines))
    return "\n\n".join(paragraphs)


def editable(body: str) -> str:
    return unwrap(split(body)[0])


def rebuild(edited: str, original_body: str) -> str:
    """The edited text, wrapped again, with the original footer back on."""
    _core, footer = split(original_body)
    text = (edited or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    return playbook.email_body(*paragraphs) + footer


def problems(message, body: str) -> list[str]:
    """What would stop this edit going out. Empty means fine."""
    if not split(body)[0].strip():
        return ["The email is empty."]
    if (message.kind or "cold") == "cold":
        return playbook.sequence_check(message.sequence_step, body)
    return []
