"""Onboarder — the first hour after someone pays.

The gap between paying and hearing from you is where buyer's remorse lives,
and until now that gap was unbounded: a sale closed in the dashboard and the
client heard nothing at all. The welcome sequence existed, as a markdown file
the operator would have to find, open, copy, personalise by hand and send —
which means on a busy evening it does not get sent.

That matters more than it sounds. The Retention agent's own research is that
the first ninety days decide the relationship. Day one being silence is the
worst possible opening, and it is the one day the client is paying most
attention.

So this drafts the welcome the moment a client exists, personalised with
their real audit, and asks for exactly the two things month one needs. It
drafts; the operator still reads it before it goes. But it is written, it is
waiting, and it takes ten seconds instead of twenty minutes.
"""

from __future__ import annotations

from .. import knowledge, method, playbook
from ..models import OutreachMessage, now_iso
from .base import Agent

#: Recorded against the client so a welcome is written exactly once.
ONBOARDED = "onboarded"


def welcome_email(client, audit, settings) -> tuple[str, str]:
    """The first email, with this client's own numbers in it.

    Deliberately states the honest timeline. A client told to expect movement
    in thirty days and shown none cancels in month three — the overpromise
    causes the churn it was meant to prevent, so month one is described as
    what it is: the baseline.
    """
    biz = client.business
    trade = knowledge.get(biz.vertical)
    plan = method.plan(1, biz.vertical, audit)

    if audit and audit.results:
        shown = sum(1 for r in audit.results if r.mentioned)
        total = len(audit.results)
        standing = (f"Your baseline: you were named in {shown} of {total} AI answers "
                    f"for {knowledge.plural(trade.label)} in {biz.market}.")
    else:
        standing = (f"I'm running your full audit now — ten buyer-intent questions "
                    f"across ChatGPT, Google's AI Overviews, Perplexity and Claude.")

    work = "\n".join(f"  - {lever.name}" for lever in plan["levers"])
    minutes = plan["client_minutes"]

    body = playbook.email_body(
        f"Hi,",
        f"Thanks for signing up. Here is exactly what happens now, so there are "
        f"no surprises.",
        standing,
        f"This month: {plan['title']}. {plan['thesis']}",
        f"Three things:",
    ) + "\n\n" + work + "\n\n" + playbook.email_body(
        f"I need two things from you, and then very little after that.",
        f"1. Confirm your exact business name, address and phone as they appear "
        f"on your Google Business Profile. Those three have to match "
        f"byte-for-byte everywhere, and a mismatch is the most common thing "
        f"that is quietly wrong.",
        f"2. Either add me to your Google Business Profile, or tell me who can "
        f"make changes to it and your website.",
        f"That is about {minutes} minutes of your time this month. The rest is "
        f"mine.",
        f"Being straight with you about timing: month one is the baseline. "
        f"Structured data shows up when the engines next crawl, which is days "
        f"to weeks, and reviews compound over months. You should expect to see "
        f"the number move in month two, not next week. I will show you the "
        f"same measurement every month either way — including the months it "
        f"does not move.",
        f"Any questions, just reply. I read everything.",
        f"{settings.brand}\n{settings.website}")

    return f"You're in — here's what happens next", body


class OnboarderAgent(Agent):
    name = "onboarder"
    description = "Writes the welcome the hour a client signs, not the week after."
    interval = 1800  # the gap between paying and hearing from you is the risk

    def _pending(self) -> list:
        """Active clients who have never been welcomed."""
        out = []
        for client in self.store.get_clients("active"):
            if self.store.has_outcome(client.id, ONBOARDED):
                continue
            out.append(client)
        return out

    def _latest_audit(self, business_id: str):
        history = self.store.audit_history(business_id, limit=1)
        return history[0] if history else None

    def _prospect_for(self, client):
        """The original prospect, so the draft lands in the normal inbox."""
        domain = client.business.domain
        if not domain:
            return None
        return next((p for p in self.store.get_prospects(limit=10_000)
                     if p.business.domain == domain), None)

    def execute(self) -> tuple[int, str]:
        pending = self._pending()
        if not pending:
            return 0, "every client has been welcomed"

        written = []
        for client in pending:
            audit = self._latest_audit(client.business.id)
            subject, body = welcome_email(client, audit, self.settings)
            prospect = self._prospect_for(client)

            self.store.save_message(OutreachMessage(
                prospect_id=prospect.id if prospect else client.id,
                subject=subject, body=body, sequence_step=0, kind="welcome",
                status="drafted", scheduled_for=now_iso()))
            self.store.record_outcome(
                prospect_id=client.id, vertical=client.business.vertical,
                kind=ONBOARDED, note=f"welcome drafted for {client.business.name}")
            written.append(client.business.name)

        return len(written), (
            f"welcome drafted for {', '.join(written[:3])}"
            + (f" and {len(written) - 3} more" if len(written) > 3 else "")
            + " — approve it today, the first hour is the one that counts")
