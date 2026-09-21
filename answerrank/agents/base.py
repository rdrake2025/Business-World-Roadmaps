"""Agent base class.

Every agent is a small, single-purpose worker that the orchestrator can call
on a schedule. Agents never raise into the scheduler: a failure is recorded
as an ``AgentRun`` with status ``error`` and the fleet keeps running. That
property is what makes unattended 24/7 operation safe.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..config import Settings
from ..models import AgentRun, now_iso
from ..store import Store


class Agent(ABC):
    #: Stable identifier used in logs, run records and the CLI.
    name: str = "agent"
    #: One-line description shown by ``answerrank agents``.
    description: str = ""
    #: Default interval between runs, in seconds.
    interval: int = 3600
    #: Longest a single run may take before the fleet gives up on it and moves
    #: on. A crash is an exception and is caught; a hang is not an exception —
    #: it is simply never returning, and without this one stuck network call
    #: stops every agent behind it indefinitely, with nothing recorded.
    max_seconds: int = 900

    def __init__(self, store: Store, settings: Settings):
        self.store = store
        self.settings = settings
        self.log = logging.getLogger(f"answerrank.{self.name}")

    @abstractmethod
    def execute(self) -> tuple[int, str]:
        """Do the work. Return ``(items_processed, human_summary)``."""

    def run(self) -> AgentRun:
        run = AgentRun(agent=self.name)
        self.store.start_run(run)
        self.log.info("start")
        try:
            count, summary = self.execute()
            run.status, run.items_processed, run.summary = "ok", count, summary
            self.log.info("ok — %s", summary)
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all
            run.status = "error"
            run.error = f"{type(exc).__name__}: {exc}"
            self.log.exception("failed")
        run.finished_at = now_iso()
        self.store.finish_run(run)
        return run
