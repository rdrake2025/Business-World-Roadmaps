"""A researcher for every agent, studying whether that agent actually works.

The fleet acts. The Analyst measures the funnel. Nothing asked whether each
individual agent was doing its own job well — so a Scout that finds
unpitchable businesses, an Auditor asking questions nobody is ever named in,
or a Retention model that flags nothing before a client leaves would all keep
running, reporting success, for months.

Each doing-agent is now shadowed by a researcher that reads the evidence that
agent leaves in the database and answers one question about it. They are
subordinate: they investigate and report, they never act. Acting on a finding
is the operator's decision, or the Strategist's.

**The discipline that makes this useful rather than noise.** Thirteen
researchers emitting something every cycle would be thirteen things the
operator stops reading by the end of the first week, and the one real finding
would be lost among twelve pieces of filler. So a researcher that lacks the
evidence to conclude returns *nothing*. Silence is the correct and common
output. Every finding carries the numbers it rests on, so the operator can
check the reasoning rather than trust it.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# Severity, in the order the operator should read them.
BLOCKING, IMPROVE, NOTE = "blocking", "improve", "note"
#: Confidence in the finding, mirroring the Analyst's sample-size discipline.
CONFIDENT, PROVISIONAL = "confident", "provisional"


@dataclass
class Finding:
    """One observation about one agent, with the arithmetic behind it."""

    subject: str          #: the agent this is about
    claim: str            #: what was observed, in one sentence
    evidence: str         #: the numbers it rests on
    proposal: str         #: what to change
    severity: str = IMPROVE
    confidence: str = PROVISIONAL

    def line(self) -> str:
        return f"[{self.subject}] {self.claim}"

    def as_dict(self) -> dict[str, str]:
        return {"subject": self.subject, "claim": self.claim,
                "evidence": self.evidence, "proposal": self.proposal,
                "severity": self.severity, "confidence": self.confidence}


class Researcher(ABC):
    """Shadows one agent. Investigates, reports, never acts."""

    #: The agent whose work this studies.
    subject: str = ""
    #: The single question this researcher exists to answer.
    question: str = ""

    def __init__(self, store, settings):
        self.store = store
        self.settings = settings

    @abstractmethod
    def investigate(self) -> list[Finding]:
        """Findings, or an empty list when the evidence will not support one."""

    def run(self) -> list[Finding]:
        """Investigate without ever taking the fleet down with it."""
        try:
            return self.investigate() or []
        except Exception as exc:  # noqa: BLE001 - a researcher must not break a tick
            return [Finding(
                subject=self.subject,
                claim=f"This researcher could not run: {type(exc).__name__}",
                evidence=str(exc)[:160],
                proposal="A researcher failing is a bug in the researcher, not a "
                         "finding about the agent. Nothing is known either way.",
                severity=NOTE, confidence=PROVISIONAL)]

    # ---- shared helpers -------------------------------------------------

    def _kv_json(self, key: str, default):
        raw = self.store.kv_get(key)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _share(part: int, whole: int) -> float:
        return (part / whole) if whole else 0.0


# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------

class ScoutResearcher(Researcher):
    subject = "scout"
    question = "Is discovery finding businesses actually worth pitching?"
    #: Below this, a trade's rejection rate is noise rather than a pattern.
    MIN_PER_TRADE = 8

    def investigate(self) -> list[Finding]:
        prospects = self.store.get_prospects(limit=10_000)
        if len(prospects) < 20:
            return []

        by_trade: dict[str, list] = {}
        for p in prospects:
            by_trade.setdefault(p.business.vertical, []).append(p)

        out = []
        for trade, rows in by_trade.items():
            if len(rows) < self.MIN_PER_TRADE:
                continue
            rejected = sum(1 for p in rows if p.stage == "suppressed")
            share = self._share(rejected, len(rows))
            if share >= 0.5:
                out.append(Finding(
                    subject=self.subject,
                    claim=f"Half of what the Scout finds in {trade} is unpitchable.",
                    evidence=(f"{rejected} of {len(rows)} {trade} prospects were "
                              f"filtered out after discovery ({share:.0%})."),
                    proposal=("Every rejected prospect cost an audit. Either tighten "
                              "the search for this trade or stop prospecting it — "
                              "rejecting at discovery is cheaper than at the point "
                              "of sale."),
                    severity=IMPROVE,
                    confidence=CONFIDENT if len(rows) >= 25 else PROVISIONAL))
        return out


class ProspectorResearcher(Researcher):
    subject = "prospector"
    question = "Can the businesses we find actually be reached?"
    MIN_CHECKED = 12

    def investigate(self) -> list[Finding]:
        checked = [p for p in self.store.get_prospects(limit=10_000)
                   if p.contact_checked_at]
        if len(checked) < self.MIN_CHECKED:
            return []

        with_email = sum(1 for p in checked if "@" in (p.business.email or ""))
        share = self._share(with_email, len(checked))
        out = []
        if share < 0.4:
            out.append(Finding(
                subject=self.subject,
                claim="Most businesses we find publish no contact address.",
                evidence=(f"{with_email} of {len(checked)} checked sites had a "
                          f"usable address ({share:.0%})."),
                proposal=("Email may be the wrong channel for these trades. The "
                          "phone numbers are already on file — a finding worth "
                          "acting on before sending more."),
                severity=BLOCKING if share < 0.25 else IMPROVE,
                confidence=CONFIDENT if len(checked) >= 40 else PROVISIONAL))

        blocked = sum(1 for p in checked
                      if "asks not to be read" in (p.notes or ""))
        if blocked and self._share(blocked, len(checked)) >= 0.15:
            out.append(Finding(
                subject=self.subject,
                claim="A meaningful share of sites decline to be read.",
                evidence=f"{blocked} of {len(checked)} returned a robots.txt refusal.",
                proposal=("That refusal is honoured and should stay honoured. Note "
                          "it as a cost of the channel, not a problem to solve."),
                severity=NOTE, confidence=PROVISIONAL))
        return out


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

class AuditorResearcher(Researcher):
    subject = "auditor"
    question = "Do the questions we ask measure anything?"
    MIN_AUDITS = 6

    def investigate(self) -> list[Finding]:
        audits = []
        for p in self.store.get_prospects(limit=400):
            if p.last_audit_id:
                a = self.store.get_audit(p.last_audit_id)
                if a:
                    audits.append(a)
        if len(audits) < self.MIN_AUDITS:
            return []

        by_prompt: dict[str, list[bool]] = {}
        errors: dict[str, int] = {}
        total_by_engine: dict[str, int] = {}
        for a in audits:
            for r in a.results:
                by_prompt.setdefault(r.prompt, []).append(bool(r.mentioned))
                total_by_engine[r.engine] = total_by_engine.get(r.engine, 0) + 1
                if r.error:
                    errors[r.engine] = errors.get(r.engine, 0) + 1

        out = []
        dead = [q for q, hits in by_prompt.items()
                if len(hits) >= 5 and not any(hits)]
        if dead:
            out.append(Finding(
                subject=self.subject,
                claim=f"{len(dead)} question(s) have never named anyone we audit.",
                evidence=(f'Example: "{dead[0][:96]}" — {len(by_prompt[dead[0]])} '
                          f"asks, zero mentions."),
                proposal=("A question nobody is ever named in measures nothing and "
                          "costs an API call every audit. Either it is phrased in a "
                          "way engines answer generically, or it is the wrong "
                          "question for this trade."),
                severity=IMPROVE, confidence=PROVISIONAL))

        for engine, count in errors.items():
            share = self._share(count, total_by_engine.get(engine, 1))
            if share >= 0.2:
                out.append(Finding(
                    subject=self.subject,
                    claim=f"The {engine} engine is failing often.",
                    evidence=(f"{count} of {total_by_engine[engine]} probes errored "
                              f"({share:.0%})."),
                    proposal=("Scores computed with an engine mostly missing are "
                              "weaker than they look. Check the key and the rate "
                              "limit before quoting those numbers to a client."),
                    severity=BLOCKING, confidence=CONFIDENT))
        return out


class FixerResearcher(Researcher):
    subject = "fixer"
    question = "Does the work we deliver actually move the score?"
    MIN_CLIENTS = 2

    def investigate(self) -> list[Finding]:
        moved, flat, examined = 0, 0, 0
        for client in self.store.get_clients("active"):
            history = self.store.audit_history(client.business.id, limit=8,
                                               comparable=True)
            scores = [a.score for a in reversed(history) if a.score is not None]
            if len(scores) < 2:
                continue
            examined += 1
            if scores[-1] - scores[0] >= 3:
                moved += 1
            elif scores[-1] - scores[0] <= 0:
                flat += 1
        if examined < self.MIN_CLIENTS:
            return []

        if flat and flat >= moved:
            return [Finding(
                subject=self.subject,
                claim="The deliverables are not moving client scores.",
                evidence=(f"Of {examined} clients with a measurable trend, {flat} "
                          f"are flat or down and {moved} improved."),
                proposal=("Check the deliverables were actually installed before "
                          "concluding the work is wrong — an uninstalled file and "
                          "an ineffective one look identical from here."),
                severity=BLOCKING,
                confidence=CONFIDENT if examined >= 5 else PROVISIONAL)]
        return []


class ReporterResearcher(Researcher):
    subject = "reporter"
    question = "Do the monthly reports start a conversation?"

    def investigate(self) -> list[Finding]:
        clients = self.store.get_clients("active")
        reported = [c for c in clients if c.last_report_at]
        if len(reported) < 2:
            return []
        silent = [c for c in reported
                  if not self.store.last_outcome_at(
                      c.id, ("replied", "call_booked", "client_message"))]
        if len(silent) == len(reported):
            return [Finding(
                subject=self.subject,
                claim="Every client who received a report has said nothing back.",
                evidence=f"{len(reported)} reports delivered, {len(silent)} silent.",
                proposal=("A report that prompts no reply is a report being filed "
                          "unread. Ask one direct question in the covering note — "
                          "silence is the leading churn signal, not a neutral one."),
                severity=IMPROVE,
                confidence=CONFIDENT if len(reported) >= 4 else PROVISIONAL)]
        return []


# ---------------------------------------------------------------------------
# Selling
# ---------------------------------------------------------------------------

class OutreachResearcher(Researcher):
    subject = "outreach"
    question = "Which part of the sequence earns replies?"
    MIN_SENDS = 25

    def investigate(self) -> list[Finding]:
        by_step = self.store.outcomes_by("step")
        sent_total = sum(c.get("sent", 0) for c in by_step.values())
        if sent_total < self.MIN_SENDS:
            return []

        out = []
        for step, counts in sorted(by_step.items(), key=lambda kv: int(kv[0] or 0)):
            sent = counts.get("sent", 0)
            replied = counts.get("replied", 0)
            if sent >= self.MIN_SENDS and replied == 0:
                out.append(Finding(
                    subject=self.subject,
                    claim=f"Step {step} of the sequence has never earned a reply.",
                    evidence=f"{sent} sends at step {step}, zero replies.",
                    proposal=("Each touch is meant to carry a new idea. A step that "
                              "earns nothing is spending complaint-rate budget for "
                              "no return — rewrite it or cut it."),
                    severity=IMPROVE, confidence=CONFIDENT))

        bounced = sum(c.get("bounced", 0) for c in by_step.values())
        if bounced and self._share(bounced, sent_total) >= 0.02:
            out.append(Finding(
                subject=self.subject,
                claim="The bounce rate is at the threshold that gets a domain filtered.",
                evidence=(f"{bounced} bounces in {sent_total} sends "
                          f"({self._share(bounced, sent_total):.1%}); the ceiling is 2%."),
                proposal=("Stop sending and clean the list. A domain filtered "
                          "wholesale is not recoverable — you buy a new one."),
                severity=BLOCKING, confidence=CONFIDENT))
        return out


class ConciergeResearcher(Researcher):
    subject = "concierge"
    question = "Are inbound replies being read correctly?"
    MIN_REPLIES = 8

    def investigate(self) -> list[Finding]:
        replies = [o for o in self._all_outcomes() if o["kind"] == "replied"]
        if len(replies) < self.MIN_REPLIES:
            return []

        punted = sum(1 for o in replies
                     if o["sentiment"] in {"question", "unclear", ""})
        share = self._share(punted, len(replies))
        if share >= 0.5:
            return [Finding(
                subject=self.subject,
                claim="Half of replies are being handed to you unclassified.",
                evidence=(f"{punted} of {len(replies)} replies read as "
                          f"'question' or 'unclear' ({share:.0%})."),
                proposal=("Routing an ambiguous reply to a human is correct by "
                          "design, but at this rate the classifier is not earning "
                          "its place. Read the last ten and see which intent it "
                          "is missing."),
                severity=IMPROVE,
                confidence=CONFIDENT if len(replies) >= 20 else PROVISIONAL)]
        return []

    def _all_outcomes(self) -> list[dict]:
        with self.store.conn() as cx:
            rows = cx.execute(
                "SELECT kind, sentiment, note FROM outcomes "
                "ORDER BY occurred_at DESC LIMIT 500").fetchall()
        return [dict(r) for r in rows]


class OnboarderResearcher(Researcher):
    subject = "onboarder"
    question = "Do new clients actually hear from us?"

    def investigate(self) -> list[Finding]:
        clients = self.store.get_clients("active")
        if not clients:
            return []
        drafted_ids = {m.prospect_id for m in self.store.get_messages("drafted", 300)
                       if m.sequence_step == 0}
        if not drafted_ids:
            return []
        return [Finding(
            subject=self.subject,
            claim="A welcome email is written and still sitting unapproved.",
            evidence=f"{len(drafted_ids)} welcome message(s) drafted, none sent.",
            proposal=("This agent exists to close the gap between someone paying "
                      "and hearing from you. A draft nobody approves reopens the "
                      "exact gap it was built to close. Approve it today."),
            severity=BLOCKING, confidence=CONFIDENT)]


# ---------------------------------------------------------------------------
# Keeping and counting
# ---------------------------------------------------------------------------

class RetentionResearcher(Researcher):
    subject = "retention"
    question = "Does the health score see a churn coming?"

    def investigate(self) -> list[Finding]:
        churned = self.store.get_clients("churned")
        if not churned:
            return []
        warned = sum(1 for c in churned
                     if any(o["kind"] == "at_risk"
                            for o in self.store.outcomes_for(c.id, limit=50)))
        if warned < len(churned):
            return [Finding(
                subject=self.subject,
                claim="Clients have churned without the health score flagging them.",
                evidence=f"{len(churned) - warned} of {len(churned)} churned unwarned.",
                proposal=("The model weights silence heaviest. If these accounts "
                          "were talking and still left, the signal that predicts "
                          "churn here is a different one — look at what they had "
                          "in common."),
                severity=BLOCKING,
                confidence=CONFIDENT if len(churned) >= 3 else PROVISIONAL)]
        return []


class BookkeeperResearcher(Researcher):
    subject = "bookkeeper"
    question = "Is any cost growing faster than the business?"

    def investigate(self) -> list[Finding]:
        pnl = self.store.pnl(30)
        revenue = pnl.get("revenue", 0.0)
        costs = self.store.cost_breakdown(30)
        if not costs:
            return []

        out = []
        if revenue > 0:
            for category, amount in costs.items():
                share = self._share(int(amount * 100), int(revenue * 100))
                if share >= 0.25:
                    out.append(Finding(
                        subject=self.subject,
                        claim=f"{category.title()} is eating a quarter of revenue.",
                        evidence=(f"${amount:,.2f} against ${revenue:,.2f} of "
                                  f"revenue in 30 days ({share:.0%})."),
                        proposal=("At this margin the model stops working. Check "
                                  "whether this scales with clients or is fixed."),
                        severity=IMPROVE, confidence=CONFIDENT))

        unbilled = [c for c in self.store.get_clients("active")
                    if c.mrr > 0 and not self.store.outcomes_for(c.id, limit=1)
                    and not c.last_report_at]
        if revenue == 0 and self.store.mrr() > 0:
            out.append(Finding(
                subject=self.subject,
                claim="There are clients on the books but no revenue recorded.",
                evidence=(f"MRR is ${self.store.mrr():,.0f} and 30-day booked "
                          f"revenue is $0."),
                proposal=("Either billing has not run yet, which is normal in the "
                          "first month, or invoices are not going out. Worth "
                          "confirming which."),
                severity=IMPROVE, confidence=CONFIDENT))
        return out


# ---------------------------------------------------------------------------
# The thinking agents, checked by researchers of their own
# ---------------------------------------------------------------------------

class ExplorerResearcher(Researcher):
    subject = "explorer"
    question = "Were our guesses about a market right when we measured it?"

    def investigate(self) -> list[Finding]:
        from . import markets

        findings = self.store.latest_findings(limit=40)
        measured = [f for f in findings if f.get("sampled")]
        if len(measured) < 2:
            return []

        wrong = []
        for f in measured:
            candidate = markets.by_key(str(f.get("market", "")))
            if not candidate:
                continue
            prior = candidate.score(self.settings.pricing.growth_monthly)
            actual = float(f.get("opportunity") or 0)
            if abs(actual - prior) >= 20:
                wrong.append((candidate.label, prior, actual))
        if wrong:
            label, prior, actual = wrong[0]
            return [Finding(
                subject=self.subject,
                claim="Measured opportunity is diverging from the desk estimate.",
                evidence=(f"{len(wrong)} market(s) off by 20+ points. {label}: "
                          f"scored {prior:.0f} on priors, measured {actual:.0f}."),
                proposal=("The prior weights are miscalibrated for these trades. "
                          "Measurement wins — adjust the factor weights toward "
                          "what the sampling found."),
                severity=IMPROVE,
                confidence=CONFIDENT if len(wrong) >= 3 else PROVISIONAL)]
        return []


class AnalystResearcher(Researcher):
    subject = "analyst"
    question = "Is the Analyst concluding on enough evidence?"

    def investigate(self) -> list[Finding]:
        from .agents.analyst import MIN_SAMPLE

        learnings = self._kv_json("analyst.learnings", [])
        funnel = self._kv_json("analyst.funnel", {})
        sent = int(funnel.get("sent") or 0)
        if not learnings:
            return []

        # The Analyst is supposed to refuse below the floor. If it published
        # several conclusions on a thin sample, the guard is not holding.
        substantive = [l for l in learnings if "measurable yet" not in l]
        if sent < MIN_SAMPLE and len(substantive) > 0:
            return [Finding(
                subject=self.subject,
                claim="Conclusions are being drawn below the evidence floor.",
                evidence=(f"{len(substantive)} finding(s) published on {sent} "
                          f"sends; the floor is {MIN_SAMPLE}."),
                proposal=("Acting on noise is worse than acting on a benchmark, "
                          "because it feels like evidence. The refusal is the "
                          "feature — check why it did not fire."),
                severity=BLOCKING, confidence=CONFIDENT)]
        return []


class StrategistResearcher(Researcher):
    subject = "strategist"
    question = "Is the recommended move ever acted on?"
    #: How many times the same advice may repeat before it is being ignored.
    REPEAT_LIMIT = 3

    def investigate(self) -> list[Finding]:
        history = self._kv_json("research.strategy_history", [])
        current = self.store.kv_get("strategy_recommendation") or ""
        if not current:
            return []

        history = [h for h in history if isinstance(h, str)][-12:]
        repeats = sum(1 for h in history if h == current)
        history.append(current)
        self.store.kv_set("research.strategy_history", json.dumps(history[-12:]))

        if repeats >= self.REPEAT_LIMIT:
            return [Finding(
                subject=self.subject,
                claim="The same recommendation has stood unchanged for a while.",
                evidence=f'"{current[:96]}" — unchanged across {repeats + 1} checks.',
                proposal=("Either it is not being acted on, or it is not "
                          "actionable as written. Both are worth a minute: the "
                          "whole point of one recommendation is that it gets done."),
                severity=IMPROVE, confidence=PROVISIONAL)]
        return []


#: One researcher per doing-agent, in the order the fleet runs them.
RESEARCHERS: list[type[Researcher]] = [
    ConciergeResearcher, OnboarderResearcher, ScoutResearcher,
    ProspectorResearcher, AuditorResearcher, FixerResearcher,
    ReporterResearcher, OutreachResearcher, BookkeeperResearcher,
    RetentionResearcher, ExplorerResearcher, AnalystResearcher,
    StrategistResearcher,
]


def build(store, settings) -> list[Researcher]:
    return [cls(store, settings) for cls in RESEARCHERS]
