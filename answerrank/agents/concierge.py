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


def report_email(prospect: Prospect, audit, settings,
                 opening: str = "") -> tuple[str, str]:
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
        *([opening] if opening else []),
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
                   text: str = "", report_sent: bool = False,
                   payment_link: str = "") -> tuple[str, str]:
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
        # With a payment link configured, the close carries it: the fewer
        # steps between "yes" and paid, the fewer yeses go cold.
        how = (f"Here's the link to set it up — ${price:,.0f}/month, renews "
               f"monthly, cancel any time:\n{payment_link}"
               if payment_link else
               f"It's ${price:,.0f}/month, billed monthly, no long contract, cancel "
               f"any time. I'll send the invoice over today.")
        return ("close_sale", _body(
            "Hi,",
            f"Great — glad to have {biz.name} on board.",
            how,
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


# ---------------------------------------------------------------------------
# Reading real mail
# ---------------------------------------------------------------------------

#: Where a reply stops being the reply and starts being what it replies to.
_QUOTE_MARKERS = re.compile(
    r"^\s*(On .{4,200}wrote:\s*$"                  # Gmail, Apple Mail
    r"|-{2,}\s*Original Message\s*-{2,}"             # Outlook, older clients
    r"|_{10,}"                                         # Outlook web separator
    r"|From:\s.+"                                      # forwarded/quoted header block
    r"|Sent from my (iPhone|iPad|Android|Galaxy)"      # phone signatures
    r")", re.I | re.M)


def strip_quoted(text: str) -> str:
    """Only what the person wrote, not the email they were replying to.

    Every mail client quotes the original by default, and ours carries an
    unsubscribe footer. Read whole, "Yes please" plus the quoted footer
    classifies as an unsubscribe — and would have, for every reply, the
    moment replies were read automatically. The same text arrives when an
    operator pastes a whole email thread into the console.
    """
    text = (text or "").replace("\r\n", "\n")
    m = _QUOTE_MARKERS.search(text)
    if m and m.start() > 0:
        text = text[:m.start()]
    kept = [line for line in text.split("\n") if not line.lstrip().startswith(">")]
    return "\n".join(kept).strip()


def html_to_text(html: str) -> str:
    import html as html_lib
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", html_lib.unescape(text)).strip()


def message_body(msg) -> str:
    """The plain-text part, or the HTML part flattened if that is all there is."""
    plain = html = ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ctype = part.get_content_type()
        if part.get_filename():
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        if ctype == "text/plain" and not plain:
            plain = text
        elif ctype == "text/html" and not html:
            html = text
    return plain or html_to_text(html)


def mail_kind(msg) -> str:
    """normal | bounce | auto. Only a normal message is a person talking."""
    sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
    subject = (msg.get("Subject") or "").lower()
    if sender.split("@")[0] in {"mailer-daemon", "postmaster"} \
            or msg.get("X-Failed-Recipients") \
            or msg.get_content_type() == "multipart/report":
        return "bounce"
    auto = (msg.get("Auto-Submitted", "no").lower() != "no"
            or msg.get("X-Autoreply") or msg.get("X-Autorespond")
            or (msg.get("Precedence", "").lower() in {"auto_reply", "bulk", "junk"})
            or subject.startswith(("automatic reply", "auto:", "out of office",
                                   "autoreply", "away:")))
    return "auto" if auto else "normal"


def failed_recipients(msg) -> list[str]:
    """Which of our addresses a bounce notice is about."""
    found = [a.strip().lower() for a in (msg.get("X-Failed-Recipients") or "").split(",")
             if "@" in a]
    if not found:
        # The machine-readable part is a message/delivery-status block, whose
        # payload the email package parses into a list of header groups.
        texts = [message_body(msg)]
        for part in msg.walk():
            if part.get_content_type() == "message/delivery-status":
                payload = part.get_payload()
                items = payload if isinstance(payload, list) else [payload]
                texts.extend(str(item) for item in items)
        body = "\n".join(texts)
        found = [m.lower() for m in re.findall(
            r"(?:Final|Original)-Recipient:\s*rfc822;\s*([^\s>]+@[^\s>]+)", body, re.I)]
    return sorted(set(found))


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

    def _fetch_replies(self, days: int = 4) -> list[dict[str, str]]:
        """New mail from the last few days, each exactly once. Empty when not
        configured.

        Three things this used to get wrong, each of which would have bitten
        the first week it ran for real:

        * It searched UNSEEN. The operator reads their email on their phone,
          which marks it seen, so any reply they had already glanced at was
          never handled. Mail is now found by date and remembered by its
          Message-ID.
        * Fetching with RFC822 marks every message read — including Stripe
          receipts and personal mail it then ignored. BODY.PEEK leaves the
          mailbox exactly as the operator left it.
        * It could not tell a person from a machine: out-of-office replies got
          a sales answer, and bounce notices were ignored — which, since Gmail
          accepts mail first and bounces it later, meant almost no bounce was
          ever counted.
        """
        cfg = self._imap_config()
        if not cfg:
            return []
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
        own = (self.settings.from_email or "").lower()
        out: list[dict[str, str]] = []
        try:
            with imaplib.IMAP4_SSL(cfg["host"]) as box:
                box.login(cfg["user"], cfg["password"])
                box.select(cfg["folder"], readonly=True)
                _typ, data = box.search(None, f"(SINCE {since})")
                for num in (data[0].split() if data and data[0] else [])[-300:]:
                    _typ, raw = box.fetch(num, "(BODY.PEEK[])")
                    if not raw or not isinstance(raw[0], tuple):
                        continue
                    msg = email.message_from_bytes(raw[0][1])
                    sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
                    mid = (msg.get("Message-ID") or "").strip() or \
                        f"{sender}|{msg.get('Date', '')}|{msg.get('Subject', '')}"
                    if not sender or sender == own or self.store.inbound_seen(mid):
                        continue
                    kind = mail_kind(msg)
                    out.append({
                        "id": mid, "sender": sender, "kind": kind,
                        "subject": msg.get("Subject", ""),
                        "body": strip_quoted(message_body(msg))[:4000],
                        "failed": ",".join(failed_recipients(msg)) if kind == "bounce" else "",
                    })
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
        from ..audit import run_audit
        from ..models import LedgerEntry

        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat(
            timespec="seconds")
        for audit in self.store.audit_history(prospect.business.id, limit=5):
            if not audit.is_free_teaser and audit.created_at >= cutoff:
                return audit
        audit = run_audit(prospect.business, self.settings, depth="full",
                          check_crawlers=True)
        self.store.save_audit(audit)
        self.store.add_ledger(LedgerEntry(
            kind="cost", category="api", amount=audit.cost,
            description=f"report audit for {prospect.business.name}"))
        return audit

    def handle_reply(self, prospect: Prospect, text: str) -> dict[str, str]:
        """Classify, record, advance, and draft. Returns what it decided."""
        text = strip_quoted(text) or (text or "").strip()
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
            link = ""
            if intent == "ready_to_buy":
                from .. import payments
                plan = self.settings.pricing.plan_for(
                    self.settings.quote_for(prospect.business.vertical)) or "growth"
                link = payments.link_for(self.settings, plan, prospect.id,
                                         prospect.business.email)
            action, body = draft_response(intent, prospect, self.settings, text,
                                          report_sent=report_sent, payment_link=link)
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

    def _match(self, sender: str, prospects: list[Prospect]) -> Prospect | None:
        """Exact address first; failing that, the one business on that domain.

        Cold email goes to info@ and the owner answers from their own address
        on the same domain. Matching the address alone dropped those replies,
        which are exactly the ones from the person who can say yes.
        """
        exact = [p for p in prospects if (p.business.email or "").lower() == sender]
        if exact:
            return exact[0]
        domain = sender.split("@")[-1]
        if domain in {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
                      "icloud.com", "aol.com"}:
            return None
        same = [p for p in prospects if p.business.domain == domain]
        return same[0] if len(same) == 1 else None

    def execute(self) -> tuple[int, str]:
        mail = self._fetch_replies()
        if not mail:
            cfg = self._imap_config()
            return 0, ("no new replies" if cfg else
                       "mailbox not connected — replies are pasted in from the "
                       "console (Keys and settings on the AnswerRank button reads them automatically)")

        prospects = [p for p in self.store.get_prospects(limit=10_000) if p.business.email]
        handled = bounced = skipped = unmatched = 0
        intents: list[str] = []
        for item in mail:
            if item["kind"] == "bounce":
                for address in item["failed"].split(","):
                    target = self._match(address, prospects) if address else None
                    if address:
                        self.store.suppress(address, "bounced (notice in mailbox)")
                    if target:
                        self.store.record_outcome(
                            prospect_id=target.id, vertical=target.business.vertical,
                            kind="bounced", note="bounce notice")
                        bounced += 1
                self.store.record_inbound(item["id"], item["sender"], "bounce",
                                          snippet=item["failed"])
                continue
            if item["kind"] == "auto":
                self.store.record_inbound(item["id"], item["sender"], "auto",
                                          snippet=item["subject"])
                skipped += 1
                continue
            prospect = self._match(item["sender"], prospects)
            if prospect is None:
                # Surfaced, not dropped: it may be a referral writing from a
                # new address, or a client's bookkeeper.
                self.store.record_inbound(item["id"], item["sender"], "unmatched",
                                          snippet=item["subject"] + " — " + item["body"][:200])
                unmatched += 1
                continue
            result = self.handle_reply(prospect, item["body"])
            self.store.record_inbound(item["id"], item["sender"], "reply",
                                      prospect.id, item["body"][:300])
            intents.append(result["intent"])
            handled += 1

        parts = []
        if handled:
            parts.append(f"handled {handled} replies: " + ", ".join(
                f"{intents.count(i)} {i}" for i in sorted(set(intents))))
        if bounced:
            parts.append(f"{bounced} bounce notice(s) — addresses suppressed")
        if skipped:
            parts.append(f"{skipped} auto-replies ignored")
        if unmatched:
            parts.append(f"{unmatched} from senders I don't recognise — check your inbox")
        return handled, "; ".join(parts) or "nothing new"
