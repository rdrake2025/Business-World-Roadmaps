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

from datetime import datetime, timedelta, timezone

from ..models import OutreachMessage, Prospect, now_iso
from ..prompts import vertical_meta
from .base import Agent


def _compliance_block(settings) -> str:
    """CAN-SPAM + 2026 bulk-sender footer. Appended to every message."""
    return (
        f"\n\n---\n"
        f"{settings.company_legal_name}\n"
        f"{settings.physical_address}\n"
        f"Reply STOP or click here to unsubscribe and we will not contact you again: "
        f"{settings.website}/unsubscribe\n"
    )


def first_touch(prospect: Prospect, settings) -> tuple[str, str]:
    """The opener. Short, specific, one ask, no attachments, no images."""
    biz = prospect.business
    meta = vertical_meta(biz.vertical)
    score = prospect.score or 0.0
    gap = prospect.competitor_gap or 0.0
    label = str(meta["label"])

    subject = f"{biz.name} isn't showing up in AI search for {biz.city}"
    if score >= 40:
        subject = f"Quick note on {biz.name}'s AI search visibility"

    evidence = prospect.notes or (
        f"{biz.name} appears in very few AI answers for {label}s in {biz.market}."
    )

    body = f"""Hi,

I ran a quick check on how {biz.name} shows up when people ask AI assistants
(ChatGPT, Google's AI Overviews, Perplexity) for a {label} in {biz.market}.

{evidence}

That matters more than it used to: a growing share of "who should I call"
searches now end with an AI answer naming two or three businesses. If you're
not one of them, the customer never sees you — there's no page two to be on.

I put the full breakdown into a one-page report: which questions you're
missing, who's being named instead, and the three fixes that move it fastest.

Want me to send it over? Just reply "yes" and it's yours, no charge.

Best,
{settings.brand}
{settings.website}"""

    return subject, body + _compliance_block(settings)


def followup(prospect: Prospect, step: int, settings) -> tuple[str, str]:
    biz = prospect.business
    meta = vertical_meta(biz.vertical)
    label = str(meta["label"])
    top = ""
    if prospect.notes and "appears in" in prospect.notes:
        top = prospect.notes

    if step == 2:
        subject = f"Re: {biz.name} isn't showing up in AI search for {biz.city}"
        body = f"""Hi,

Following up on the AI visibility check for {biz.name}.

The part most owners find surprising: this isn't a Google ranking problem.
A business can sit at #1 in local search and still be absent from the AI
answer, because assistants build answers from structured data and
corroborating sources rather than from the results page.

{top}

Happy to send the one-page report — no charge, no call required. Reply "yes".

Best,
{settings.brand}"""
    elif step == 3:
        subject = f"Closing the loop — {biz.name}"
        body = f"""Hi,

Last note from me on this.

If AI search visibility isn't a priority for {biz.name} right now, that's a
completely reasonable call and I'll leave you alone.

If it becomes one later, the free report offer stands — just reply to this
email any time and I'll run a fresh check for {biz.market}.

Either way, good luck this season.

Best,
{settings.brand}
{settings.website}"""
    else:
        subject = f"Re: {biz.name} and {label}s in {biz.city}"
        body = f"Hi,\n\nJust checking whether the report would be useful.\n\nBest,\n{settings.brand}"

    return subject, body + _compliance_block(settings)


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
        email = prospect.business.email
        if not email or "@" not in email:
            return False
        if self.store.is_suppressed(email):
            return False
        # Only pitch where we proved a gap. No evidence, no email.
        return prospect.is_hot or (prospect.score is not None and prospect.score < 55)

    def execute(self) -> tuple[int, str]:
        pol = self.settings.outreach
        drafted = skipped = 0
        now = datetime.now(timezone.utc)

        # --- first touches ---
        for prospect in self.store.due_prospects("audited", self.draft_budget):
            if not self._eligible(prospect):
                prospect.stage = "suppressed"
                prospect.notes = (prospect.notes or "") + " | filtered: no evidence or no email"
                self.store.upsert_prospect(prospect)
                skipped += 1
                continue

            subject, body = first_touch(prospect, self.settings)
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
