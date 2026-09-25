"""Researcher — runs the sixteen researchers and files what they found.

One slot in the tick order rather than sixteen. The researchers are
subordinate by design: they read what their agent produced, report on it, and
never act. Putting them behind a single coordinator keeps the fleet legible —
twenty-six entries in the agent list would be a worse tool, not a better one —
while each researcher stays a separate, named, separately tested unit.

It runs last, after every agent has produced whatever it is going to produce
this cycle, for the same reason the Analyst does: studying a half-finished
tick tells you about the tick, not about the agent.
"""

from __future__ import annotations

from .. import research
from .base import Agent


class ResearcherAgent(Agent):
    name = "researcher"
    description = "Runs a researcher against every agent and reports what holds."
    interval = 6 * 3600

    def investigate(self) -> list[research.Finding]:
        from .. import evidence

        found: list[research.Finding] = []
        for r in research.build(self.store, self.settings):
            found.extend(r.run())
        # The professional research the rules rest on has a shelf life. AI
        # search changes by the quarter; a rule built on last year's study
        # is a guess with a citation.
        for e in evidence.overdue():
            found.append(research.Finding(
                subject=e.used_by[0],
                claim=f"Research due a re-check: {e.source}.",
                evidence=f"Last read {e.checked}; checked every {e.review_months} months.",
                proposal=(f"Re-read {e.url} and update what we do in "
                          f"answerrank/evidence.py, or remove it if it no longer holds."),
                severity=research.NOTE, confidence=research.CONFIDENT))
        order = {research.BLOCKING: 0, research.IMPROVE: 1, research.NOTE: 2}
        found.sort(key=lambda f: (order.get(f.severity, 3), f.subject))
        return found

    def execute(self) -> tuple[int, str]:
        findings = self.investigate()
        self.store.save_research([f.as_dict() for f in findings])

        total = len(research.RESEARCHERS)
        if not findings:
            # The common and correct outcome. Saying so plainly is the point:
            # sixteen researchers inventing something every cycle would be
            # sixteen things the operator stops reading.
            return 0, (f"{total} researchers ran, none found anything that the "
                       f"evidence supports saying")

        blocking = [f for f in findings if f.severity == research.BLOCKING]
        headline = findings[0].line()
        summary = f"{len(findings)} finding(s) across {total} researchers | {headline}"
        if blocking:
            summary = f"{len(blocking)} BLOCKING | " + summary
        return len(findings), summary
