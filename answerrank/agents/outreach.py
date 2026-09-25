"""Outreach — drafts personalised, compliant first-touch and follow-up email.

Design decisions that are deliberate, not defaults:

**Drafts, never auto-sends.** The agent writes messages and queues them at
``status="drafted"``. Sending requires an explicit human approval step plus
configured SMTP. One misconfigured loop that blasts a bad list destroys the
sending domain permanently, and a domain reputation cannot be bought back.
A human approving a batch costs two minutes a day and removes that risk.

**Every message carries real evidence.** We only pitch businesses where the
teaser audit proved a gap. The opening line is a measured fact about *their*
business, not a template variable. That is what separates this from spam in
both the recipient's judgement and a regulator's.

**Compliance is enforced in code, not documented in a wiki.** CAN-SPAM
requires a physical postal address, a working opt-out, and a non-deceptive
subject line. The 2026 Google/Yahoo/Microsoft bulk rules add one-click
unsubscribe and complaint rates under 0.3%. ``_compliance_block`` and the
rate caps in :class:`~answerrank.config.OutreachPolicy` implement all of it,
and :meth:`preflight` refuses to send if anything is missing.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .. import knowledge, playbook, qualify
from ..models import OutreachMessage, Prospect, now_iso
from .base import Agent
from .scout import SIMULATED_MARKER


def _compliance_block(settings) -> str:
    """CAN-SPAM + 2026 bulk-sender footer. Appended to every message."""
    return (
        f"\n\n---\n"
        f"{settings.company_legal_name}\n"
        f"{settings.physical_address}\n"
        f"Reply STOP, or use this link, and we will not contact you again:\n"
        f"{settings.website}/unsubscribe\n"
    )


def subject_line(business: str, city: str, missed: int, total: int) -> str:
    """A subject in the 36-50 character band that reply-rate data favours.

    Long subjects get truncated in a mobile preview, which is where most of
    these are read. The business's own name goes first so the truncation, if
    any, never costs the one word that proves this is not a blast.
    """
    name = business if len(business) <= 22 else business[:21].rstrip() + "\u2026"
    candidates = [
        f"{name}: {missed} of {total} AI answers missed",
        f"{name} \u2014 missing from AI search",
        f"{name} and AI search in {city}",
        f"{name}: invisible to AI search",
    ]
    for c in candidates:
        if 34 <= len(c) <= 52:
            return c
    return min(candidates, key=lambda c: abs(len(c) - 43))


def first_touch(prospect: Prospect, settings) -> tuple[str, str]:
    """The opener.

    Held to six sentences. Reply-rate data is unambiguous that emails past
    roughly a dozen sentences lose about half their responses even when well
    personalised, and the earlier version of this ran to fifteen. Everything
    that survived the cut is either evidence about their business or the ask.
    """
    biz = prospect.business
    v = knowledge.get(biz.vertical)
    score = prospect.score or 0.0

    # Recover the measured counts from the audit headline where possible, so
    # the subject states a fact rather than an impression.
    missed, total = 4, 4
    note = prospect.notes or ""
    match = re.search(r"appears in (\d+) of (\d+)", note)
    if match:
        shown, total = int(match.group(1)), int(match.group(2))
        missed = max(0, total - shown)

    # A site that blocks the engines is a different conversation: not "you
    # are losing a competition" but "you withdrew from it", which is both a
    # stronger claim and one they can verify in ten seconds.
    blocks_engines = "in its own robots.txt" in note

    subject = subject_line(biz.name, biz.city, missed, total)
    if blocks_engines:
        subject = f"{biz.name[:26]}: your site blocks AI search"
    elif score >= 40:
        subject = f"{biz.name[:22]}: a gap in AI search"

    evidence = note.split(" | ")[0] if note else (
        f"{biz.name} appears in very few AI answers for "
        f"{knowledge.plural(v.label)} in {biz.market}.")

    risk = knowledge.revenue_at_risk(biz.vertical, missed, total)
    money = ""
    if float(risk["annual_revenue"]) >= 8000:
        money = (
            f"On a ${v.economics.avg_ticket:,.0f} average ticket that is roughly "
            f"${float(risk['annual_revenue']):,.0f} a year of first-job revenue going "
            f"elsewhere \u2014 and that estimate is set deliberately low.")

    if blocks_engines:
        return subject, playbook.email_body(
            "Hi,",
            evidence,
            "I check this for a living and it is almost always unintentional \u2014 a "
            "plugin or a previous agency adds the rule to block scrapers, and the "
            "same line removes the business from the answers its customers read.",
            f"You can confirm it yourself: open {biz.website.rstrip('/')}/robots.txt "
            f"and look for those names.",
            "It is a one-line fix and it costs nothing. Happy to send exactly what "
            "to change, plus the check I ran \u2014 no charge either way.",
            f"{settings.brand}\n{settings.website}") + _compliance_block(settings)

    body = playbook.email_body(
        "Hi,",
        evidence,
        "When someone asks an assistant who to call, the answer names two or three "
        "businesses and the rest are never seen.",
        money,
        "I put the full check into a one-page report \u2014 which questions you're "
        "missing, who's named instead, and the three fixes that move it fastest.",
        'Want it? Reply "yes" and it\'s yours, no charge.',
        f"{settings.brand}\n{settings.website}")

    return subject, body + _compliance_block(settings)


def followup(prospect: Prospect, step: int, settings) -> tuple[str, str]:
    """Follow-ups, each carrying one new idea rather than a nudge.

    Step 2 reframes: this is not an SEO problem, which is why their existing
    spend did not prevent it. Step 3 gives permission to say no, which
    reliably produces a share of the total replies. Past step 3 the sequence
    closes rather than degrading into pestering \u2014 a content-free nudge costs
    more in complaint rate than it can earn in replies.
    """
    biz = prospect.business
    v = knowledge.get(biz.vertical)
    evidence = (prospect.notes or "").split(" | ")[0]

    if step == 2:
        subject = f"Re: {subject_line(biz.name, biz.city, 0, 0).split(':')[0]}"
        body = playbook.email_body(
            "Hi,",
            f"Following up on the AI visibility check for {biz.name}.",
            "The part most owners find surprising: this isn't a Google ranking "
            "problem. You can sit at number one in local search and still be absent "
            "from the AI answer, because assistants build answers from structured "
            "data and corroborating sources rather than from the results page.",
            "That's why your existing SEO spend didn't stop it.",
            evidence,
            'Happy to send the one-page report \u2014 no charge, no call. Just reply "yes".',
            settings.brand)
    elif step == 3:
        subject = f"Closing the loop \u2014 {biz.name[:24]}"
        body = playbook.email_body(
            "Hi,",
            "Last note from me on this.",
            f"If AI search visibility isn't a priority for {biz.name} right now, "
            f"that's a fair call and I'll leave you alone.",
            f"If it becomes one \u2014 the run-up to {v.peak_label()} is when it costs "
            f"the most \u2014 reply any time and I'll run a fresh check for "
            f"{biz.market}.",
            "Either way, good luck this season.",
            f"{settings.brand}\n{settings.website}")
    else:
        subject = f"One last thing \u2014 {biz.name[:24]}"
        risk = knowledge.revenue_at_risk(biz.vertical, 7, 10)
        body = playbook.email_body(
            "Hi,",
            "I'll stop here, but I'll leave you the number rather than the pitch.",
            f"{knowledge.sentence_case(knowledge.a_label(biz.vertical))} missing from "
            f"roughly seven in ten AI answers loses on the order of "
            f"${float(risk['annual_revenue']):,.0f} a year in first-job revenue. That "
            f"is built on ${v.economics.avg_ticket:,.0f} tickets and a deliberately "
            f"low booking rate, so check it against your own books \u2014 it costs you "
            f"nothing to know the figure either way.",
            f"If you ever want the detail behind it for {biz.name}, reply any time.",
            settings.brand)

    return subject, body + _compliance_block(settings)


def worth_pitching(prospect: Prospect, settings, log=None) -> bool:
    """A real, demonstrable problem, at a business the retainer honestly
    makes sense for. The same bar for an email and for a call."""
    # The price this trade can actually defend, not one flat number.
    # Quoting every trade $997 discarded half the library for a reason
    # that was never about the market.
    price = settings.quote_for(prospect.business.vertical)
    fit = qualify.score_fit(prospect.business, prospect.score, price)
    if not fit.worth_pitching:
        if log is not None:
            log.debug("skipping %s: %s", prospect.business.name,
                      fit.blockers[0] if fit.blockers else f"tier {fit.tier}")
        return False
    return prospect.is_hot or (prospect.score is not None and prospect.score < 55)


class OutreachAgent(Agent):
    name = "outreach"
    description = "Drafts compliant, evidence-backed outreach for audited prospects."
    interval = 4 * 3600

    def __init__(self, store, settings, draft_budget: int = 40):
        super().__init__(store, settings)
        self.draft_budget = draft_budget

    def preflight(self) -> list[str]:
        """Blocking problems that must be fixed before a single send."""
        problems = []
        pol = self.settings.outreach
        if pol.require_physical_address and (
            not self.settings.physical_address
            or "SET_YOUR" in self.settings.physical_address
        ):
            problems.append(
                "CAN-SPAM: no physical postal address configured "
                "(set `physical_address` in answerrank.yml)."
            )
        if pol.require_unsubscribe and not self.settings.website:
            problems.append("CAN-SPAM: no unsubscribe URL host configured (`website`).")
        if "@" not in self.settings.from_email:
            problems.append("No valid from_email configured.")
        return problems

    def _eligible(self, prospect: Prospect) -> bool:
        """Two tests, both of which must pass.

        A demonstrable gap is necessary but not sufficient: the business also
        has to be one the retainer honestly makes sense for. Pitching poor-fit
        prospects spends complaint-rate budget that cannot be recovered, and
        the qualifier refuses outright where there is no real problem to sell.
        """
        email = prospect.business.email
        if not email or "@" not in email:
            return False
        if self.store.is_suppressed(email):
            return False
        # Fixture data must never reach a real mailbox. These domains do not
        # exist, so each one is a hard bounce against a 2% ceiling.
        if SIMULATED_MARKER in (prospect.notes or ""):
            self.log.debug("skipping %s: fixture data", prospect.business.name)
            return False

        return worth_pitching(prospect, self.settings, self.log)

    def _phone_only(self, prospect: Prospect) -> bool:
        """No address to email, but a number to call and a gap worth calling
        about. Suppressing these threw away exactly the businesses a call
        can still reach."""
        email = prospect.business.email
        return (not email or "@" not in email) and bool(prospect.business.phone) \
            and SIMULATED_MARKER not in (prospect.notes or "") \
            and worth_pitching(prospect, self.settings)

    def _passes_discipline(self, step: int, body: str, prospect: Prospect) -> bool:
        """The playbook's own check, run against our own drafts.

        A rule the agents are trained on but never measured against is a
        comment, not a rule. Anything the check rejects is not sent — a
        message that fails our own standard would cost more in reputation
        than it could earn in replies.
        """
        problems = playbook.sequence_check(step, body)
        if problems:
            self.log.warning("draft for %s rejected by the playbook: %s",
                             prospect.business.name, "; ".join(problems))
            return False
        return True

    def execute(self) -> tuple[int, str]:
        pol = self.settings.outreach
        drafted = skipped = 0
        now = datetime.now(timezone.utc)

        # --- first touches, best-fit first ---
        candidates = sorted(
            self.store.due_prospects("audited", self.draft_budget * 2),
            key=lambda p: -qualify.priority(
                p.business, p.score, p.competitor_gap,
                self.settings.quote_for(p.business.vertical)),
        )[: self.draft_budget]
        for prospect in candidates:
            if not self._eligible(prospect) and self._phone_only(prospect):
                # Kept for the call list; looked at again in a week in case
                # an address has turned up.
                prospect.next_action_at = (now + timedelta(days=7)).isoformat(timespec="seconds")
                if "phone only" not in (prospect.notes or ""):
                    prospect.notes = (prospect.notes or "") + " | phone only: no email found"
                self.store.upsert_prospect(prospect)
                skipped += 1
                continue
            if not self._eligible(prospect):
                prospect.stage = "suppressed"
                prospect.notes = (prospect.notes or "") + " | filtered: no evidence or no email"
                self.store.upsert_prospect(prospect)
                skipped += 1
                continue

            subject, body = first_touch(prospect, self.settings)
            if not self._passes_discipline(1, body, prospect):
                skipped += 1
                continue
            self.store.save_message(OutreachMessage(
                prospect_id=prospect.id, subject=subject, body=body,
                sequence_step=1, status="drafted",
                scheduled_for=now.isoformat(timespec="seconds"),
            ))
            prospect.stage = "queued"
            prospect.next_action_at = (
                now + timedelta(days=pol.followup_gap_days)
            ).isoformat(timespec="seconds")
            self.store.upsert_prospect(prospect)
            drafted += 1

        # --- follow-ups for anyone contacted and silent ---
        for prospect in self.store.due_prospects("contacted", self.draft_budget) + \
                        self.store.due_prospects("following_up", self.draft_budget):
            if prospect.touches >= pol.max_followups + 1:
                prospect.stage = "lost"
                prospect.notes = (prospect.notes or "") + " | sequence exhausted, no reply"
                self.store.upsert_prospect(prospect)
                continue
            if not self._eligible(prospect):
                continue

            step = prospect.touches + 1
            subject, body = followup(prospect, step, self.settings)
            if not self._passes_discipline(step, body, prospect):
                continue
            self.store.save_message(OutreachMessage(
                prospect_id=prospect.id, subject=subject, body=body,
                sequence_step=step, status="drafted",
                scheduled_for=now.isoformat(timespec="seconds"),
            ))
            prospect.stage = "following_up"
            prospect.next_action_at = (
                now + timedelta(days=pol.followup_gap_days)
            ).isoformat(timespec="seconds")
            self.store.upsert_prospect(prospect)
            drafted += 1

        problems = self.preflight()
        note = f" | BLOCKED FOR SEND: {'; '.join(problems)}" if problems else ""
        return drafted, f"drafted {drafted} messages, filtered {skipped} unqualified{note}"
