"""The orchestrator — what makes this a 24/7 business rather than a script.

A single long-lived process that wakes on a fixed tick, asks each agent
whether it is due, and runs the ones that are. Properties that matter for
unattended operation:

* **Crash-isolated.** An agent raising does not stop the fleet; the failure
  is written to ``agent_runs`` and the next agent proceeds.
* **Restart-safe.** "Due" is computed from the last run recorded in the
  database, not from in-memory state, so a restart resumes rather than
  re-runs everything.
* **Bounded.** Each agent has its own per-run budget, so a runaway loop
  cannot burn the month's API spend.
* **Signal-aware.** SIGINT/SIGTERM finish the current agent, then exit
  cleanly — safe for systemd, Docker, or a plain terminal.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from .agents.analyst import AnalystAgent
from .agents.auditor import AuditorAgent
from .agents.base import Agent
from .models import AgentRun, now_iso
from .agents.bookkeeper import BookkeeperAgent
from .agents.concierge import ConciergeAgent
from .agents.explorer import ExplorerAgent
from .agents.fixer import FixerAgent
from .agents.onboarder import OnboarderAgent
from .agents.outreach import OutreachAgent
from .agents.prospector import ProspectorAgent
from .agents.reporter import ReporterAgent
from .agents.researcher import ResearcherAgent
from .agents.citations import CitationAgent
from .agents.retention import RetentionAgent
from .agents.scout import ScoutAgent
from .agents.strategist import StrategistAgent
from .config import Settings
from .store import Store

log = logging.getLogger("answerrank.orchestrator")

# Order matters: each agent consumes what the previous one produced, so a
# single tick can carry a prospect from discovery all the way to a drafted
# email.
#
# The Prospector sits directly after the Scout so a business whose contact
# cannot be found never consumes an audit — rejecting at discovery is cheaper
# than rejecting at the point of sale.
#
# The Onboarder runs second for the same reason the Concierge runs first: the
# gap between a client paying and hearing from you is where buyer's remorse
# lives, and it outranks any amount of new prospecting.
#
# The Concierge runs first because an inbound reply outranks every piece of
# new work in the queue — it is the only event in the system that a human is
# waiting on. The Analyst runs late, after the tick has produced whatever it
# is going to produce, and the Strategist runs last so its single
# recommendation is made with the Analyst's findings already written. The
# Researcher runs last of all: studying a half-finished tick tells you about
# the tick, not about the agent.
AGENT_ORDER = [ConciergeAgent, OnboarderAgent, ScoutAgent, ProspectorAgent,
               AuditorAgent, CitationAgent,
               FixerAgent, ReporterAgent,
               OutreachAgent, BookkeeperAgent, RetentionAgent, ExplorerAgent,
               AnalystAgent, StrategistAgent, ResearcherAgent]


def build_fleet(store: Store, settings: Settings) -> list[Agent]:
    return [cls(store, settings) for cls in AGENT_ORDER]


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-28s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


class Orchestrator:
    def __init__(self, store: Store, settings: Settings, agents: list[Agent] | None = None):
        self.store = store
        self.settings = settings
        self.agents = agents or build_fleet(store, settings)
        self._stop = False
        #: Agents whose previous run never returned. A stuck thread cannot be
        #: killed in Python, so the next best thing is to refuse to start a
        #: second copy of it — otherwise a permanently hung agent accumulates
        #: one leaked thread per cycle, forever.
        self._stuck: dict[str, threading.Thread] = {}

    # ---------------- scheduling ----------------

    def _last_success(self, agent_name: str) -> datetime | None:
        """When this agent last finished cleanly.

        This used to scan the most recent 200 runs and take the first match.
        The fleet writes roughly 200 runs a day, so an agent on a daily
        interval — the Bookkeeper, Retention, the Strategist — was reliably
        pushed out of that window by the chattier agents, read as never
        having run, and therefore judged due on every tick. Intervals exist
        to bound what the fleet spends; a window that forgets makes the
        longest intervals the ones least honoured.
        """
        stamp = self.store.last_success_at(agent_name)
        if not stamp:
            return None
        try:
            return datetime.fromisoformat(stamp)
        except ValueError:
            return None

    def is_due(self, agent: Agent, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        last = self._last_success(agent.name)
        if last is None:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return now - last >= timedelta(seconds=agent.interval)

    # ---------------- execution ----------------

    def _run_guarded(self, agent: Agent) -> str:
        """Run one agent, and give up on it if it never comes back.

        ``Agent.run`` already turns any exception into a recorded failure. It
        cannot do anything about a run that simply does not return — a socket
        without a timeout, a DNS lookup against a resolver that accepts and
        never answers. Left alone that blocks every agent behind it for as
        long as the process lives, which is the opposite of running 24/7.
        """
        previous = self._stuck.get(agent.name)
        if previous is not None and previous.is_alive():
            return (f"[ERR] {agent.name:<12} still hung from a previous cycle; "
                    f"skipped rather than started twice")

        result: dict[str, AgentRun] = {}

        def work() -> None:
            result["run"] = agent.run()

        worker = threading.Thread(target=work, daemon=True,
                                  name=f"answerrank-{agent.name}")
        worker.start()
        worker.join(agent.max_seconds)

        if worker.is_alive():
            self._stuck[agent.name] = worker
            stuck = AgentRun(agent=agent.name, status="error")
            stuck.error = (f"no response after {agent.max_seconds}s — the fleet "
                           f"moved on without it")
            # finish_run is an UPDATE, so the row has to exist first or the
            # timeout is recorded nowhere and the operator never learns why an
            # agent went quiet.
            self.store.start_run(stuck)
            stuck.finished_at = now_iso()
            self.store.finish_run(stuck)
            log.error("%s exceeded its %ss budget; continuing without it",
                      agent.name, agent.max_seconds)
            return f"[ERR] {agent.name:<12} {stuck.error}"

        self._stuck.pop(agent.name, None)
        run = result.get("run")
        if run is None:  # pragma: no cover - the thread died without recording
            return f"[ERR] {agent.name:<12} finished without recording a result"
        marker = "ok " if run.status == "ok" else "ERR"
        return f"[{marker}] {agent.name:<12} {run.summary or run.error}"

    def tick(self, force: bool = False) -> list[str]:
        """Run every due agent once. Returns human-readable lines."""
        lines: list[str] = []
        for agent in self.agents:
            if self._stop:
                break
            if not force and not self.is_due(agent):
                continue
            lines.append(self._run_guarded(agent))
        return lines

    def stop(self) -> None:
        """Ask the loop to finish the current agent and exit."""
        self._stop = True

    def _housekeep(self) -> None:
        """Trim run history once a day.

        ``agent_runs`` is the only table that grows purely with uptime, and
        the operator is told they can back this database up by copying the
        file. Thirty days is more history than anything here reads.
        """
        today = datetime.now(timezone.utc).date().isoformat()
        if self.store.kv_get("last_prune") == today:
            return
        removed = self.store.prune_agent_runs(30)
        self.store.kv_set("last_prune", today)
        if removed:
            log.info("pruned %s agent runs older than 30 days", removed)

    def run_forever(self, install_signals: bool = True) -> None:
        """Tick until stopped.

        ``install_signals`` is False when the fleet runs inside a thread
        alongside the web server: `signal.signal` raises outright off the main
        thread, and that exception would have killed the fleet the moment it
        started.
        """
        def handle(signum, _frame):
            log.info("signal %s received — finishing current agent then exiting", signum)
            self._stop = True

        if install_signals:
            signal.signal(signal.SIGINT, handle)
            signal.signal(signal.SIGTERM, handle)

        log.info(
            "fleet online: %s | tick=%ss | engines=%s",
            ", ".join(a.name for a in self.agents),
            self.settings.tick_seconds,
            ",".join(self.settings.available_engines()),
        )

        while not self._stop:
            started = time.time()
            try:
                for line in self.tick():
                    log.info(line)
                self._housekeep()
            except Exception:  # noqa: BLE001 - the loop must never die
                log.exception("tick failed; continuing")

            elapsed = time.time() - started
            sleep_for = max(1.0, self.settings.tick_seconds - elapsed)
            # Sleep in short slices so a signal is honoured promptly.
            waited = 0.0
            while waited < sleep_for and not self._stop:
                time.sleep(min(1.0, sleep_for - waited))
                waited += 1.0

        log.info("fleet stopped cleanly")
