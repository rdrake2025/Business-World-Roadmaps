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
from datetime import datetime, timedelta, timezone

from .. import knowledge, playbook
from ..models import OutreachMessage, Prospect, now_iso
from .base import Agent

#: Ordered most-specific first. Every pattern here was checked against the
#: made-up replies in ``answerrank.simulate`` — and the first version failed
#: a quarter of them, in ways that each cost a sale:
#:
#: * "Still waiting on the report you mentioned" matched ``report you`` and
#:   was filed as **hostile** — the buyer was suppressed for chasing the
#:   report we promised them.
#: * "Is there a contract? I'd want my lawyer to look at it" matched
#:   ``lawyer`` and was filed as hostile too.
#: * "Let's hold off for now" matched ``let's`` and was filed as interested.
#: * "Yes. Is this really free?" and "Interested. What did you find?" hit
#:   the question mark first and got a sales explanation instead of a yes.
#: * "Alright, sign us up" and "Deal. Send me the invoice" had no pattern at
#:   all, and were answered with a pitch for the free report.
INTENT_PATTERNS: list[tuple[str, str]] = [
    ("unsubscribe", r"\b(unsubscribe|remove (me|us)|take (me|us) off|"
                    r"stop (emailing|contacting|sending|messaging)|"
                    r"do not (contact|email)|don'?t (contact|email) (me|us))\b|^\W*stop\W*$"),
    ("hostile", r"\b(spam(ming)?|scam(mer)?|harass(ment|ing)?|reporting you|"
                r"report(ed|ing)? (you|this) (to|as)|"
                r"how did you get (this|my|our) (address|email))\b"),
    ("not_interested", r"\b(not interested|no thanks|no thank you|we'?re good|all set(?! up)|"
                       r"not right now|hold off|not for us|(we|i)'?ll pass|"
                       r"pass on (this|it)|not at this time)\b"),
    ("ready_to_buy", r"\b(sign (me|us) up|let'?s do (it|this)|let'?s go (with|ahead)|"
                     r"count (me|us) in|where do (i|we) pay|how do (i|we) pay|"
                     r"send (me |us |over )?(the |an )?invoice|go ahead and start|"
                     r"get (us |me )?started|let'?s (try|start) it|"
                     r"you'?ve convinced me|it'?s a deal|ready to (start|sign|go))\b"
                     r"|^\W*(deal|start|let'?s start)\b|\b(we'?re|i'?m) in(?=\s*[.!,]|\s*$)"),
    ("interested", r"^\W*(yes|yeah|yep|yup|sure|ok(ay)?|please do|sounds good|"
                   r"go ahead|interested|absolutely|definitely)\b|"
                   r"\b(send (it|the report|that|it over)|i'?d like to see|"
                   r"would like to see|please send|tell me more|let'?s talk|call me|"
                   r"waiting (on|for) (the|that|your) report|"
                   r"update on (the|that|my) report|where'?s (the|that|my) report)\b"),
    ("referral", r"\b(talk to|speak (to|with)|forward (it|this)|"
                 r"my (marketing|web|office|it) (guy|person|team|manager|company)|"
                 r"office manager)\b"),
    ("question", r"\?|(\bhow much\b|\bwhat does\b|\bwho are you\b|\bwhat is this\b|"
                 r"\bcost\b|\bprice\b|\bpricing\b)"),
]


def classify(text: str, is_client: bool = False) -> str:
    """What the person actually wants. Conservative by design.

    Ambiguity resolves to ``question``, which routes to a human rather than
    to an automated assumption about intent.

    ``is_client`` changes everything: a paying client writing "who do I send
    the website login to?" is not a prospect asking what this costs, and
    answering them with the sales pitch — which is what happened, for every
    client, every time — tells a customer you do not know who they are. Only
    an explicit opt-out outranks being a client.
    """
    low = (text or "").lower().strip()
    if is_client:
        for intent in ("unsubscribe", "hostile"):
            pattern = dict(INTENT_PATTERNS)[intent]
            if re.search(pattern, low):
                return intent
        return "client_message" if low else "unclear"
    for intent, pattern in INTENT_PATTERNS:
        if re.search(pattern, low):
            return intent
    return "question" if low else "unclear"


#: One body builder for the whole system, so a reply and an opener can never
#: wrap differently.
_body = playbook.email_body


def report_email(prospect: Prospect, audit, settings) -> tuple[str, str]:
    """The free report the first email promised, as the email itself.

    Every cold opener ends 'Want it? Reply "yes" and it's yours', and every
    "yes" was answered with "you'll have the report within a day" — after
    which nothing in the system produced a report, and nothing in the console
    could. In the 30-sale simulation all thirty buyers said yes to it, and
    all thirty went cold waiting. This is that report.

    Plain text, like everything else sent: no attachment, no link to click
    through, nothing a spam filter or a busy owner has to take on trust. It
    delivers exactly what the opener listed — which questions they miss, who
    is named instead, and the three fixes that move it fastest.
    """
    from .. import method
    from ..scoring import ENGINE_LABELS, grade
    from .outreach import _compliance_block

    biz = prospect.business
    v = knowledge.get(biz.vertical)
    results = [r for r in audit.results if not r.error]
    n = len(results) or 1
    shown = sum(1 for r in results if r.mentioned)
    engines = sorted({ENGINE_LABELS.get(r.engine, r.engine) for r in results})
    missed = []
    for r in results:
        if not r.mentioned and r.prompt not in missed:
            missed.append(r.prompt)
    rivals = sorted(audit.competitors.items(), key=lambda kv: -kv[1])[:3]
    risk = knowledge.revenue_at_risk(biz.vertical, n - shown, n)
    price = settings.quote_for(biz.vertical)
    levers = method.first_fixes(biz.vertical, audit, 3)

    paragraphs = [
        "Hi,",
        f"Here's the full check on {biz.name}. I asked {n} questions a customer "
        f"in {biz.market} would ask an AI assistant, on "
        f"{', '.join(engines)}.",
        f"Score: {audit.score:.0f}/100 ({grade(audit.score)}). {biz.name} was "
        f"named in {shown} of those {n} answers.",
    ]
    if missed:
        paragraphs.append("Questions where you weren't named:\n"
                          + "\n".join(f"- {q}" for q in missed[:4]))
    if rivals:
        paragraphs.append("Named instead:\n" + "\n".join(
            f"- {name} ({count} of {n})" for name, count in rivals))
    blocked = (getattr(audit, "crawler_access", None) or {}).get("critical")
    if blocked:
        paragraphs.append(str(audit.crawler_access.get("headline", "")))
    if float(risk["annual_revenue"]) >= 2000:
        paragraphs.append(
            f"On a ${v.economics.avg_ticket:,.0f} average ticket, that gap is worth "
            f"roughly ${float(risk['annual_revenue']):,.0f} a year in first-job "
            f"revenue. {risk['assumption']}")
    if levers:
        paragraphs.append("The three fixes that move it fastest:\n" + "\n".join(
            f"{i}. {lever.name} — {lever.why}" for i, lever in enumerate(levers, 1)))
    paragraphs += [
        f"You can take that list and do it yourself; it's yours either way. If "
        f"you'd rather I did it, it's ${price:,.0f}/month, no long contract, "
        f"cancel any time. Reply \"start\" and I'll send the invoice.",
        f"{settings.brand}\n{settings.website}",
    ]
    subject = f"Your AI visibility report — {biz.name[:30]}"
    return subject, _body(*paragraphs) + _compliance_block(settings)


def draft_response(intent: str, prospect: Prospect, settings,
                   text: str = "", report_sent: bool = False) -> tuple[str, str]:
    """A reply the operator can send as-is or edit in ten seconds.

    ``report_sent`` matters because the right answer to most messages
    changes once they have the report: offering "the free report" to someone
    holding it reads as a mail merge, and the next step is the price.

    Returns ``("", "")`` where nothing should be sent at all.
    """
    biz = prospect.business
    brand = settings.brand
    price = settings.quote_for(biz.vertical)
    payback = knowledge.payback_line(biz.vertical, price)
    next_step = (f"If you'd like me to do the work, it's ${price:,.0f}/month, no long "
                 f"contract, cancel any time. Reply \"start\" and I'll send the "
                 f"invoice." if report_sent else "The first report is free and "
                 f"there's no call attached. Want it?")

    if intent == "ready_to_buy":
        return ("close_sale", _body(
            "Hi,",
            f"Great — glad to have {biz.name} on board.",
            f"It's ${price:,.0f}/month, billed monthly, no long contract, cancel "
            f"any time. I'll send the invoice over today.",
            "As soon as that's settled you'll get a short welcome note with the two "
            "things I need from you — about ten minutes of your time — and "
            "I start on the fixes from the report straight away.",
            brand))

    if intent == "client_message":
        return ("client_reply", _body(
            "Hi,",
            "Thanks — got it. I'll take it from here, and I'll come back to you "
            "if I need anything else.",
            brand))

    if intent == "interested" and report_sent:
        return ("propose_start", _body(
            "Hi,",
            "Glad it was useful.",
            next_step,
            "If you'd rather do it yourself, the list in the report is yours to "
            "keep either way.",
            brand))

    if intent == "question":
        # If the question is really an objection in disguise — and most are —
        # answer that first. A generic explanation aimed past the actual
        # concern reads as a brochure and gets no second reply.
        answer = playbook.rebuttal(text, biz.vertical, price)
        if answer:
            return ("answer_objection", _body(
                "Hi,",
                answer,
                f"To be concrete about {biz.name}: we measure how often you get named "
                f"when someone asks an assistant for {knowledge.a_label(biz.vertical)} "
                f"in {biz.market}, and do the work that moves it.",
                payback,
                next_step,
                brand))

        return ("answer_question", _body(
            "Hi,",
            "Happy to explain.",
            f"We check how often {biz.name} gets named when someone asks an AI "
            f"assistant for {knowledge.a_label(biz.vertical)} in {biz.market} — "
            f"ChatGPT, Google's AI Overviews, Perplexity and Claude — and then "
            f"do the work that moves it."
            + ("" if report_sent else f" That part is ${price:,.0f}/month, cancel "
                                      f"any time."),
            payback,
            next_step,
            brand))

    if intent == "referral":
        return ("forward_to_contact", _body(
            "Hi,",
            "Of course — happy to send it to them directly. What's the best address?",
            "Worth saying: this usually isn't something their existing work covers. A "
            "site can rank first in local search and still be absent from the AI "
            "answer, because assistants build answers from structured data rather "
            "than the results page.",
            brand))

    # A plain no, an opt-out, or hostility: they have been suppressed before
    # this is reached, so anything drafted here could never be delivered.
    # It used to draft a rebuttal anyway, which sat in the operator's inbox,
    # was approved, and silently became "suppressed" at the moment of sending.
    if intent in {"not_interested", "unsubscribe", "hostile"}:
        return ("", "")

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

    def _client_for(self, prospect: Prospect):
        """The live client record for this business, if it is one."""
        for client in self.store.get_clients("active"):
            if client.business.id == prospect.business.id or (
                    prospect.business.domain
                    and client.business.domain == prospect.business.domain):
                return client
        return None

    def _report_sent(self, prospect: Prospect) -> bool:
        return any(m.kind == "report" and m.status in {"drafted", "approved", "sent"}
                   for m in self.store.messages_for(prospect.id))

    def _report_for(self, prospect: Prospect):
        """A full audit for the report: a recent one if it exists, else run it."""
        from ..audit import estimate_cost, run_audit
        from ..models import LedgerEntry

        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat(
            timespec="seconds")
        for audit in self.store.audit_history(prospect.business.id, limit=5):
            if not audit.is_free_teaser and audit.created_at >= cutoff:
                return audit
        audit = run_audit(prospect.business, self.settings, depth="full",
                          check_crawlers=True)
        self.store.save_audit(audit)
        engines = len(self.settings.available_engines())
        self.store.add_ledger(LedgerEntry(
            kind="cost", category="api", amount=estimate_cost("full", engines),
            description=f"report audit for {prospect.business.name}"))
        return audit

    def handle_reply(self, prospect: Prospect, text: str) -> dict[str, str]:
        """Classify, record, advance, and draft. Returns what it decided."""
        client = self._client_for(prospect)
        intent = classify(text, is_client=client is not None)
        report_sent = self._report_sent(prospect)

        # Whoever wrote back has left the cold sequence, whatever they said.
        # Any follow-up already drafted or approved is withdrawn now, rather
        # than going out tomorrow as "last note from me" to someone who
        # replied "yes" yesterday.
        self.store.withdraw_cold(prospect.id)

        if client is not None:
            # Recorded against the client, which is what Retention reads.
            # Recorded against the prospect id, as it was, a client talking to
            # you every week looked like a client who had gone silent.
            self.store.record_outcome(
                prospect_id=client.id, vertical=prospect.business.vertical,
                kind="client_message", sentiment=intent, note=text[:300])
        else:
            self.store.record_outcome(
                prospect_id=prospect.id, vertical=prospect.business.vertical,
                step=prospect.touches, kind="replied", sentiment=intent,
                note=text[:300])

        if intent in {"unsubscribe", "hostile"}:
            # Honour it immediately and permanently, whatever else it said.
            self.store.suppress(prospect.business.email, f"reply: {intent}")
            if client is None:
                prospect.stage = "suppressed"
        elif intent == "not_interested":
            self.store.suppress(prospect.business.email, "declined")
            prospect.stage = "lost"
            self.store.record_outcome(
                prospect_id=prospect.id, vertical=prospect.business.vertical,
                kind="lost", sentiment=intent)
        elif client is None:
            prospect.stage = "replied"
        # A client stays a client. Their stage is not a reply to be worked.

        prospect.notes = (prospect.notes or "") + f" | replied: {intent}"
        prospect.last_touch_at = now_iso()
        self.store.upsert_prospect(prospect)

        # A drafted response, never a sent one. The id comes back with the
        # decision so the caller shows the reply it just wrote rather than
        # whichever draft happens to be first in the queue.
        if intent == "interested" and not report_sent and client is None:
            audit = self._report_for(prospect)
            subject, body = report_email(prospect, audit, self.settings)
            action, kind = "send_report", "report"
        else:
            action, body = draft_response(intent, prospect, self.settings, text,
                                          report_sent=report_sent)
            subject, kind = f"Re: {prospect.business.name}", "reply"

        message_id = ""
        if body:
            message = OutreachMessage(
                prospect_id=prospect.id, subject=subject, body=body,
                sequence_step=prospect.touches + 1, status="drafted", kind=kind,
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
