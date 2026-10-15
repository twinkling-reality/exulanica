"""Keep a project's history without a save button.

The watcher reads the selected checkpoint at a bounded interval and records an automatic
checkpoint once the selection has stayed the same for a settle period. Edits that cancel out
before then (a model switched away and back) leave nothing pending and record nothing. It writes
only the local project folder: never the world and never a remote. A checkpoint is recorded at the
watcher's own time, and the day's count is read back from the project's history, so a watcher
started again on the same day holds the same cap.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from exulanica.world_package.projects.capture import Capture
from exulanica.world_package.projects.checkpoint import (
    ProjectError,
    checkpoint_digest,
    document,
    evidence_digest,
)
from exulanica.world_package.projects.repository import (
    Project,
    Sessions,
    accumulate,
    session_file,
)
from exulanica.world_package.projects.summary import evidence_summary, summarize

MIN_POLL_SECONDS = 5.0
MAX_POLL_SECONDS = 300.0
#: A day, for the daily cap: midnight to midnight, UTC.
DAY_SECONDS = 86_400


@dataclass(frozen=True)
class Policy:
    poll_seconds: float = 15.0
    settle_seconds: float = 120.0
    # While models play, evidence grows every minute and the selection never settles; a change
    # pending this long is recorded anyway, so a long session still keeps history.
    max_pending_seconds: float = 1800.0
    daily_cap: int = 48

    def __post_init__(self) -> None:
        if not MIN_POLL_SECONDS <= self.poll_seconds <= MAX_POLL_SECONDS:
            raise ProjectError("poll interval must be between 5 and 300 seconds")
        if not self.poll_seconds <= self.settle_seconds <= 86_400:
            raise ProjectError("settle period must be at least one poll and at most a day")
        if not self.settle_seconds <= self.max_pending_seconds <= 86_400:
            raise ProjectError("maximum pending time must be between the settle period and a day")
        if not 1 <= self.daily_cap <= 1_000:
            raise ProjectError("daily cap must be between 1 and 1000 checkpoints")


@dataclass
class Watcher:
    project: Project
    read: Callable[[], Capture]
    policy: Policy = field(default_factory=Policy)
    clock: Callable[[], float] = time.time
    _seen: str | None = None
    _since: float | None = None
    _first: float | None = None

    def _recorded_today(self, now: float) -> int:
        """Checkpoints the project recorded in the UTC day holding `now`, from its history."""
        start = now // DAY_SECONDS * DAY_SECONDS
        return self.project.checkpoints_between(start, start + DAY_SECONDS)

    def _pending(self, captured: Capture) -> tuple[dict[str, Any], list[str], list[str]]:
        """The candidate, and what differs from the last record: world and evidence apart."""
        candidate = document(captured.checkpoint)
        committed = self.project.at("HEAD")
        saved = self.project.sessions_at("HEAD")
        # Pending files hold records a capture's window may no longer return.
        sessions = {**saved, **self._sessions(self.project.working_sessions(), captured)}
        world = [] if candidate == committed else summarize(committed, candidate)
        if candidate != committed and not world:
            world = ["changed selected details; see the field diff"]
        return candidate, world, evidence_summary(saved, sessions)

    @staticmethod
    def _files(saved: Sessions, captured: Capture) -> list[dict[str, Any]]:
        return [] if captured.evidence is None else accumulate(saved, captured.evidence)

    def _sessions(self, saved: Sessions, captured: Capture) -> Sessions:
        sessions = dict(saved)
        for evidence in self._files(saved, captured):
            sessions[session_file(evidence["session_id"])] = evidence
        return sessions

    def _session_closed(self, captured: Capture) -> bool:
        """A living session that closed since the last record: its end is the checkpoint."""
        held = (captured.evidence or {}).get("living_session")
        if held is None or held["state"] != "closed":
            return False
        saved = self.project.sessions_at("HEAD").get(session_file(captured.evidence["session_id"]))
        return saved is None or (saved.get("living_session") or {}).get("state") != "closed"

    def _digest(self, candidate: dict[str, Any], captured: Capture) -> str:
        files = self._files(self.project.working_sessions(), captured)
        return ":".join([checkpoint_digest(candidate), *(evidence_digest(f) for f in files)])

    def step(self) -> dict[str, Any]:
        """One poll: clean, settling, capped or checkpointed."""
        now = self.clock()
        captured = self.read()
        candidate, world, evidence = self._pending(captured)
        if not world and not evidence:
            self._seen = self._since = self._first = None
            committed = self.project.at("HEAD")
            if self.project.working() != committed:
                self.project.write_working(committed)
            return {"state": "clean"}
        state = self._digest(candidate, captured)
        if state != self._seen:
            self._seen, self._since = state, now
            self._first = self._first if self._first is not None else now
            # Pending changes are visible in the folder before they are recorded.
            files = self._files(self.project.working_sessions(), captured)
            self.project.write_working(candidate, files)
        pending = {"pending": world, "pending_evidence": evidence}
        settled = self._since is not None and now - self._since >= self.policy.settle_seconds
        overdue = self._first is not None and now - self._first >= self.policy.max_pending_seconds
        if not settled and not overdue and not self._session_closed(captured):
            return {"state": "settling", **pending}
        return self._record(captured, now, pending)

    def _record(self, captured: Capture, now: float, pending: dict[str, Any]) -> dict[str, Any]:
        if self._recorded_today(now) >= self.policy.daily_cap:
            return {"state": "capped", **pending}
        # Every pending session file, not only the one this capture read: a session the cap held
        # back stays pending in the folder while a later poll reads another session.
        sessions = self._sessions(self.project.working_sessions(), captured)
        result = self.project.save(
            captured.checkpoint,
            evidence=list(sessions.values()),
            dependencies=captured.dependencies,
            when=now,
        )
        self._seen = self._since = self._first = None
        return {"state": "checkpointed" if result["committed"] else "clean", **result}

    def finish(self) -> dict[str, Any]:
        """At the end of a session, record what is pending without waiting out the settle period."""
        captured = self.read()
        _, world, evidence = self._pending(captured)
        if not world and not evidence:
            return {"state": "clean"}
        return self._record(
            captured, self.clock(), {"pending": world, "pending_evidence": evidence}
        )

    def run(
        self,
        stop: threading.Event,
        report: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Poll until `stop` is set, then record any pending change once and return."""
        tell = report or (lambda _: None)
        while not stop.is_set():
            try:
                outcome = self.step()
            except ProjectError as exc:
                # The world may be paused or restarting; keep what is recorded and try again.
                outcome = {"state": "unreachable", "error": str(exc)}
            if outcome["state"] != "clean":
                tell(outcome)
            stop.wait(self.policy.poll_seconds)
        try:
            final = self.finish()
        except ProjectError as exc:
            final = {"state": "unreachable", "error": str(exc)}
        tell(final)
        return final
