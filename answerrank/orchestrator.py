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
import time
from datetime import datetime, timedelta, timezone

from .agents.auditor import AuditorAgent
from .agents.base import Agent
from .agents.bookkeeper import BookkeeperAgent
from .agents.explorer import ExplorerAgent
from .agents.fixer import FixerAgent
from .agents.outreach import OutreachAgent
from .agents.reporter import ReporterAgent
from .agents.scout import ScoutAgent
from .agents.strategist import StrategistAgent
from .config import Settings
from .store import Store

log = logging.getLogger("answerrank.orchestrator")

# Order matters: each agent consumes what the previous one produced, so a
# single tick can carry a prospect from discovery all the way to a drafted
# email.
AGENT_ORDER = [ScoutAgent, AuditorAgent, FixerAgent, ReporterAgent, OutreachAgent,
               BookkeeperAgent, ExplorerAgent, StrategistAgent]


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

    # ---------------- scheduling ----------------

    def _last_success(self, agent_name: str) -> datetime | None:
        for run in self.store.recent_runs(200):
            if run["agent"] == agent_name and run["status"] == "ok" and run["finished_at"]:
                try:
                    return datetime.fromisoformat(run["finished_at"])
                except ValueError:
                    return None
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

    def tick(self, force: bool = False) -> list[str]:
        """Run every due agent once. Returns human-readable lines."""
        lines: list[str] = []
        for agent in self.agents:
            if self._stop:
                break
            if not force and not self.is_due(agent):
                continue
            run = agent.run()
            marker = "ok " if run.status == "ok" else "ERR"
            lines.append(f"[{marker}] {agent.name:<12} {run.summary or run.error}")
        return lines

    def run_forever(self) -> None:
        def handle(signum, _frame):
            log.info("signal %s received — finishing current agent then exiting", signum)
            self._stop = True

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
