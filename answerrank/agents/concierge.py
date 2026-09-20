"""Concierge — handles the moment a prospect replies.

This was the largest unmanaged gap in the business. Everything upstream
exists to produce a reply, and until now a reply landed in an inbox and sat
there. The reply is worth more than every audit that preceded it.

Two modes:

* **Connected** (IMAP configured): polls the sending mailbox, matches replies
  to prospects, classifies intent and drafts a response.
* **Manual**: the operator logs a reply from the console, and the same
  classification and drafting runs.

It drafts, it never sends. A prospect who has just engaged is the last place
to risk an automated misfire, and the reply that closes a $997/mo deal
deserves ten seconds of human attention.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import datetime, timezone

from .. import knowledge, playbook
from ..models import OutreachMessage, Prospect, now_iso
from .base import Agent

#: Ordered most-specific first: an unsubscribe request must win over the word
#: "yes" appearing elsewhere in the same message.
INTENT_PATTERNS: list[tuple[str, str]] = [
    ("unsubscribe", r"\b(unsubscribe|remove me|stop emailing|take me off|do not contact)\b"),
    ("not_interested", r"\b(not interested|no thanks|no thank you|pass|we're good|"
                       r"all set|not right now|already have)\b"),
    ("hostile", r"\b(spam|scam|stop|harassment|report you|lawyer)\b"),
    ("question", r"\?|(\bhow much\b|\bwhat does\b|\bwho are you\b|\bwhat is this\b|"
                 r"\bcost\b|\bprice\b|\bpricing\b)"),
    ("interested", r"\b(yes|sure|send it|interested|sounds good|go ahead|"
                   r"please do|let's|lets talk|call me|tell me more)\b"),
    ("referral", r"\b(talk to|speak with|forward|my (marketing|web) (guy|person|team))\b"),
]


def classify(text: str) -> str:
    """What the prospect actually wants. Conservative by design.

    Ambiguity resolves to ``question``, which routes to a human rather than
    to an automated assumption about intent.
    """
    low = (text or "").lower()
    for intent, pattern in INTENT_PATTERNS:
        if re.search(pattern, low):
            return intent
    return "question" if low.strip() else "unclear"


#: One body builder for the whole system, so a reply and an opener can never
#: wrap differently.
_body = playbook.email_body


def draft_response(intent: str, prospect: Prospect, settings,
                   text: str = "") -> tuple[str, str]:
    """A reply the operator can send as-is or edit in ten seconds."""
    biz = prospect.business
    brand = settings.brand
    price = settings.pricing.growth_monthly
    payback = knowledge.payback_line(biz.vertical, price)

    if intent == "interested":
        return ("send_report", _body(
            "Hi,",
            f"Great \u2014 running the full check on {biz.name} now. You'll have the "
            f"report within a day.",
            "It covers every question we tested, the actual AI answers, who's being "
            "named instead of you, and the three fixes that move it fastest.",
            "No call needed to read it. If it's useful afterwards, we can talk then.",
            brand))

    if intent == "question":
        # If the question is really an objection in disguise \u2014 and most are \u2014
        # answer that first. A generic explanation aimed past the actual
        # concern reads as a brochure and gets no second reply.
        answer = playbook.rebuttal(text, biz.vertical, price)
        if answer:
            return ("answer_objection", _body(
                "Hi,",
                answer,
                f"To be concrete about {biz.name}: we measure how often you get named "
                f"when someone asks an assistant for {knowledge.a_label(biz.vertical)} "
                f"in {biz.market}. The first report is free and there's no call "
                f"attached.",
                payback,
                "Want it?",
                brand))

        return ("answer_question", _body(
            "Hi,",
            "Happy to explain.",
            f"We check how often {biz.name} gets named when someone asks an AI "
            f"assistant for {knowledge.a_label(biz.vertical)} in {biz.market} \u2014 "
            f"ChatGPT, Google's AI Overviews, Perplexity and Claude. Right now "
            f"you're named in very few of them.",
            f"The first report is free and there's no call required. After that it's "
            f"${price:,.0f}/month to track it and do the work that moves it, cancel "
            f"any time.",
            payback,
            "Want the report?",
            brand))

    if intent == "referral":
        return ("forward_to_contact", _body(
            "Hi,",
            "Of course \u2014 happy to send it to them directly. What's the best address?",
            "Worth saying: this usually isn't something their existing work covers. A "
            "site can rank first in local search and still be absent from the AI "
            "answer, because assistants build answers from structured data rather "
            "than the results page.",
            brand))

    if intent == "not_interested":
        # A "no thanks" that names a reason is not a no yet \u2014 it is an
        # objection. One answer, then the door closes either way; the
        # suppression already happened before this was drafted.
        answer = playbook.rebuttal(text, biz.vertical, price)
        if answer:
            return ("answer_objection", _body(
                "Hi,",
                "Fair enough, and I'll leave it there after this.",
                answer,
                "If that changes how it looks, the report is still free and still "
                "yours for a one-word reply. If not, no hard feelings \u2014 good luck "
                "this season.",
                brand))

    if intent in {"not_interested", "unsubscribe", "hostile"}:
        return ("close_politely", _body(
            "Hi,",
            "Understood \u2014 I'll leave it there and you won't hear from me again.",
            "Good luck this season.",
            brand))

    return ("needs_human", _body("Hi,", "Thanks for getting back to me.", brand))


class ConciergeAgent(Agent):
    name = "concierge"
    description = "Handles inbound replies and drafts the response."
    interval = 1800  # replies are time-sensitive; half an hour is the ceiling

    # ---------------- inbox ----------------

    def _imap_config(self) -> dict[str, str] | None:
        host = os.environ.get("IMAP_HOST", "")
        user = os.environ.get("IMAP_USERNAME") or os.environ.get("SMTP_USERNAME", "")
        pwd = os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD", "")
        if not (host and user and pwd):
            return None
        return {"host": host, "user": user, "password": pwd,
                "folder": os.environ.get("IMAP_FOLDER", "INBOX")}

    def _fetch_replies(self) -> list[tuple[str, str]]:
        """(from_address, body) for unread mail. Empty when not configured."""
        cfg = self._imap_config()
        if not cfg:
            return []
        out: list[tuple[str, str]] = []
        try:
            with imaplib.IMAP4_SSL(cfg["host"]) as box:
                box.login(cfg["user"], cfg["password"])
                box.select(cfg["folder"])
                _typ, data = box.search(None, "UNSEEN")
                for num in (data[0].split() if data and data[0] else [])[:40]:
                    _typ, raw = box.fetch(num, "(RFC822)")
                    if not raw or not raw[0]:
                        continue
                    msg = email.message_from_bytes(raw[0][1])
                    sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode(
                                    "utf-8", "replace")
                                break
                    else:
                        body = (msg.get_payload(decode=True) or b"").decode(
                            "utf-8", "replace")
                    if sender:
                        out.append((sender, body[:4000]))
        except (imaplib.IMAP4.error, OSError) as exc:
            self.log.warning("could not read the mailbox: %s", exc)
        return out

    # ---------------- handling ----------------

    def handle_reply(self, prospect: Prospect, text: str) -> dict[str, str]:
        """Classify, record, advance, and draft. Returns what it decided."""
        intent = classify(text)
        action, body = draft_response(intent, prospect, self.settings, text)

        self.store.record_outcome(
            prospect_id=prospect.id, vertical=prospect.business.vertical,
            step=prospect.touches, kind="replied", sentiment=intent,
            note=text[:300])

        if intent in {"unsubscribe", "hostile"}:
            # Honour it immediately and permanently, whatever else it said.
            self.store.suppress(prospect.business.email, f"reply: {intent}")
            prospect.stage = "suppressed"
        elif intent == "not_interested":
            self.store.suppress(prospect.business.email, "declined")
            prospect.stage = "lost"
            self.store.record_outcome(
                prospect_id=prospect.id, vertical=prospect.business.vertical,
                kind="lost", sentiment=intent)
        else:
            prospect.stage = "replied"

        prospect.notes = (prospect.notes or "") + f" | replied: {intent}"
        prospect.last_touch_at = now_iso()
        self.store.upsert_prospect(prospect)

        # A drafted response, never a sent one. The id comes back with the
        # decision so the caller shows the reply it just wrote rather than
        # whichever draft happens to be first in the queue.
        message_id = ""
        if intent not in {"unsubscribe", "hostile"}:
            message = OutreachMessage(
                prospect_id=prospect.id,
                subject=f"Re: {prospect.business.name}",
                body=body, sequence_step=prospect.touches + 1,
                status="drafted",
                scheduled_for=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            self.store.save_message(message)
            message_id = message.id

        return {"intent": intent, "action": action, "message_id": message_id}

    def execute(self) -> tuple[int, str]:
        replies = self._fetch_replies()
        if not replies:
            cfg = self._imap_config()
            return 0, ("no new replies" if cfg else
                       "mailbox not connected — log replies from the console "
                       "(set IMAP_HOST to poll automatically)")

        by_email = {p.business.email.lower(): p
                    for p in self.store.get_prospects(limit=5000)
                    if p.business.email}
        handled = 0
        intents: list[str] = []
        for sender, body in replies:
            prospect = by_email.get(sender)
            if not prospect:
                continue
            intents.append(self.handle_reply(prospect, body)["intent"])
            handled += 1

        if not handled:
            return 0, f"{len(replies)} replies, none matched a known prospect"
        summary = ", ".join(f"{intents.count(i)} {i}" for i in sorted(set(intents)))
        return handled, f"handled {handled} replies: {summary}"
