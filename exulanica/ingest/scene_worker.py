"""A separate pose process that drains durable reconstruction-scene leases."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from exulanica.db.session import Database
from exulanica.ingest.reconstruction_scratch import cleanup_abandoned_scene_scratch
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.scene_reconstruction import (
    SceneBuildOutcome,
    SceneReconstructionProcessor,
)
from exulanica.ingest.spine.reconstruction_jobs import ClaimedSceneJob
from exulanica.store import ContentAddressedStore

__all__ = ["SceneReconstructionWorker"]


class _LeaseKeeper:
    def __init__(
        self,
        database: Database,
        workspace_id: uuid.UUID,
        claimed: ClaimedSceneJob,
        *,
        lease_seconds: float,
        heartbeat_seconds: float,
    ) -> None:
        self._database = database
        self._workspace_id = workspace_id
        self._claimed = claimed
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._stop = threading.Event()
        self.lost = threading.Event()
        self._thread = threading.Thread(target=self._run, name="scene-lease", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self._heartbeat_seconds + 1)

    def _run(self) -> None:
        while not self._stop.wait(self._heartbeat_seconds):
            try:
                with self._database.session(self._workspace_id) as connection:
                    repository = IngestRepository(connection, self._workspace_id)
                    held = repository.heartbeat_reconstruction_scene(
                        job_id=self._claimed.job_id,
                        claim_token=self._claimed.claim_token,
                        lease_seconds=self._lease_seconds,
                    )
            except Exception:
                self.lost.set()
                return
            if not held:
                self.lost.set()
                return


class SceneReconstructionWorker:
    """Claim exact scene sets and execute them with a renewable database lease."""

    def __init__(
        self,
        database: Database,
        store: ContentAddressedStore,
        scratch_root: Path,
        workspaces: frozenset[uuid.UUID],
        *,
        name: str,
        code_revision: str,
        execution_image: str,
        lease_seconds: float = 900.0,
        heartbeat_seconds: float = 30.0,
        abandoned_after_seconds: float = 3600.0,
        job_ids: frozenset[uuid.UUID] | None = None,
    ) -> None:
        if not workspaces:
            raise ValueError("a scene worker needs at least one configured workspace")
        if job_ids is not None and not job_ids:
            raise ValueError("a job-scoped scene worker needs at least one job id")
        if heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError("scene heartbeat must be positive and shorter than its lease")
        self._database = database
        self._store = store
        self._scratch_root = scratch_root
        self._workspaces = workspaces
        self._name = name
        self._code_revision = code_revision
        self._execution_image = execution_image
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._abandoned_after_seconds = abandoned_after_seconds
        self._job_ids = job_ids
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    @property
    def name(self) -> str:
        return self._name

    @property
    def workspace_count(self) -> int:
        return len(self._workspaces)

    @property
    def job_ids(self) -> frozenset[uuid.UUID] | None:
        """The explicit jobs this worker may claim; ``None`` drains its workspaces."""
        return self._job_ids

    def cleanup_abandoned(self) -> tuple[str, ...]:
        active: set[str] = set()
        for workspace_id in self._workspaces:
            with self._database.session(workspace_id) as connection:
                repository = IngestRepository(connection, workspace_id)
                repository.expire_exhausted_reconstruction_scenes()
                active.update(repository.active_reconstruction_scratch_keys())
        return cleanup_abandoned_scene_scratch(
            self._scratch_root,
            active_keys=frozenset(active),
            older_than_seconds=self._abandoned_after_seconds,
        )

    def drain_observed(self) -> list[SceneBuildOutcome]:
        """Drain all work currently eligible in the configured workspaces."""
        outcomes: list[SceneBuildOutcome] = []
        while not self._stop.is_set():
            claimed_any = False
            for workspace_id in sorted(self._workspaces, key=str):
                outcome = self._claim_one(workspace_id)
                if outcome is not None:
                    claimed_any = True
                    outcomes.append(outcome)
            if not claimed_any:
                return outcomes
        return outcomes

    def _claim_one(self, workspace_id: uuid.UUID) -> SceneBuildOutcome | None:
        with self._database.session(workspace_id) as connection:
            repository = IngestRepository(connection, workspace_id)
            claimed = repository.claim_reconstruction_scene(
                worker=self._name,
                lease_seconds=self._lease_seconds,
                job_ids=self._job_ids,
            )
            if claimed is None:
                return None
            with self._renewing_lease(workspace_id, claimed) as keeper:
                return SceneReconstructionProcessor(
                    repository,
                    self._store,
                    self._scratch_root,
                    code_revision=self._code_revision,
                    execution_image=self._execution_image,
                    external_cancellation=keeper.lost.is_set,
                    stop_requested=self._stop.is_set,
                ).process(claimed)

    @contextmanager
    def _renewing_lease(
        self, workspace_id: uuid.UUID, claimed: ClaimedSceneJob
    ) -> Iterator[_LeaseKeeper]:
        keeper = _LeaseKeeper(
            self._database,
            workspace_id,
            claimed,
            lease_seconds=self._lease_seconds,
            heartbeat_seconds=self._heartbeat_seconds,
        )
        keeper.start()
        try:
            yield keeper
        finally:
            keeper.close()
