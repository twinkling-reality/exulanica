"""Trusted local execution of one already-reserved development experiment attempt.

This is not an HTTP worker and it does not discover work. A trusted host supplies the current
session, an exact attempt identity, current execution authorization, and the configured society
runtime. Each durable phase reopens the workspace-scoped database and rechecks both execution
permission and source-input authority. Simulation runs outside transactions. Competing callers
may duplicate deterministic computation; append-only attempt locking permits only one terminal
record.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import psycopg

from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.session import Database
from exulanica.selection.validation import Session
from exulanica.world import society_experiments as experiments
from exulanica.world.society_experiment_repository import (
    ExperimentConflict,
    SocietyExperimentRepository,
)

__all__ = [
    "ExperimentExecutionAuthorizer",
    "ExperimentRunReceipt",
    "SocietyExperimentRunner",
]


class ExperimentExecutionAuthorizer(Protocol):
    """Current permission seam owned by trusted local composition, not reservation metadata."""

    def __call__(
        self,
        connection: psycopg.Connection,
        session: Session,
        reservation: dict[str, Any],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ExperimentRunReceipt:
    attempt_id: uuid.UUID
    experiment_id: uuid.UUID
    status: Literal["completed", "failed"]
    checkpoint_sha256: str | None
    result_sha256: str | None
    failure_sha256: str | None
    recorded_at: dt.datetime


class _InputRuntime(Protocol):
    def authorize(
        self, connection: psycopg.Connection, session: Session, document: dict[str, Any]
    ) -> None: ...


class SocietyExperimentRunner:
    """Run or explicitly abort an exact reserved attempt through existing durable records."""

    def __init__(
        self,
        database: Database,
        *,
        runtime: SocietyRuntime | _InputRuntime,
        authorize_execution: ExperimentExecutionAuthorizer,
    ) -> None:
        self.database = database
        self.runtime = runtime
        self.authorize_execution = authorize_execution

    def _repository(
        self, connection: psycopg.Connection, session: Session
    ) -> SocietyExperimentRepository:
        return SocietyExperimentRepository(
            connection,
            session.workspace_id,
            input_authorizer=lambda document: self.runtime.authorize(connection, session, document),
            execution_authorizer=lambda reservation: self.authorize_execution(
                connection, session, reservation
            ),
        )

    @staticmethod
    def _receipt(material: dict[str, Any]) -> ExperimentRunReceipt | None:
        terminal = material["terminal"]
        if terminal is None:
            return None
        reservation = material["reservation"]
        return ExperimentRunReceipt(
            attempt_id=reservation["attempt_id"],
            experiment_id=reservation["experiment_id"],
            status=terminal["status"],
            checkpoint_sha256=terminal["checkpoint_sha256"],
            result_sha256=terminal["result_sha256"],
            failure_sha256=terminal["failure_sha256"],
            recorded_at=terminal["recorded_at"],
        )

    def _material(self, session: Session, attempt_id: uuid.UUID) -> dict[str, Any]:
        with self.database.session(session.workspace_id) as connection:
            return self._repository(connection, session).execution_material(attempt_id)

    def _terminal_after_conflict(
        self,
        session: Session,
        attempt_id: uuid.UUID,
        conflict: ExperimentConflict,
    ) -> ExperimentRunReceipt:
        receipt = self._receipt(self._material(session, attempt_id))
        if receipt is None:
            raise conflict
        return receipt

    @staticmethod
    def _same_checkpoint(material: dict[str, Any], expected: dict[str, Any]) -> None:
        checkpoint = material["checkpoint"]
        if checkpoint is None or checkpoint["document_sha256"] != expected["document_sha256"]:
            raise ExperimentConflict("attempt checkpoint changed before local execution")

    @staticmethod
    def _invalid_pair_detail(result: dict[str, Any]) -> str:
        refusals = result.get("invalid_pairs")
        if not isinstance(refusals, list) or not refusals:
            return "invalid_pair: controlled pair produced no executable arm evidence"
        first = refusals[0]
        code = first.get("code", "invalid_pair") if isinstance(first, dict) else "invalid_pair"
        detail = first.get("detail", "pair refused") if isinstance(first, dict) else "pair refused"
        rendered = f"{code}: {detail}"
        return rendered[:2_000]

    def _fail(
        self,
        session: Session,
        attempt_id: uuid.UUID,
        *,
        code: Literal["execution_refused", "operator_aborted"],
        detail: str,
        checkpoint: dict[str, Any] | None = None,
    ) -> ExperimentRunReceipt:
        try:
            with self.database.session(session.workspace_id) as connection:
                repository = self._repository(connection, session)
                material = repository.execution_material(attempt_id)
                receipt = self._receipt(material)
                if receipt is not None:
                    return receipt
                if checkpoint is not None:
                    self._same_checkpoint(material, checkpoint)
                repository.fail_attempt(attempt_id, code=code, detail=detail)
        except ExperimentConflict as conflict:
            return self._terminal_after_conflict(session, attempt_id, conflict)
        receipt = self._receipt(self._material(session, attempt_id))
        if receipt is None:  # pragma: no cover - append and reload are one tested contract
            raise ExperimentConflict("experiment failure was not recorded")
        return receipt

    def abort_reserved(
        self, session: Session, attempt_id: uuid.UUID, *, detail: str
    ) -> ExperimentRunReceipt:
        """Record an explicit operator abort; other exceptions remain honestly retryable."""
        return self._fail(
            session, attempt_id, code="operator_aborted", detail=detail, checkpoint=None
        )

    def run_reserved(self, session: Session, attempt_id: uuid.UUID) -> ExperimentRunReceipt:
        """Run one exact reservation, resuming its checkpoint and observing terminal retries."""
        material = self._material(session, attempt_id)
        receipt = self._receipt(material)
        if receipt is not None:
            return receipt

        checkpoint_row = material["checkpoint"]
        checkpoint = None if checkpoint_row is None else checkpoint_row["document"]
        if checkpoint is None:
            checkpoint = experiments.prepare_checkpoint(
                material["definition"],
                material["reservation"]["seed_sha256"],
                material["baseline_input"],
                phase=material["reservation"]["phase"],
            )
            try:
                with self.database.session(session.workspace_id) as connection:
                    repository = self._repository(connection, session)
                    current = repository.execution_material(attempt_id)
                    receipt = self._receipt(current)
                    if receipt is not None:
                        return receipt
                    held = current["checkpoint"]
                    if held is None:
                        repository.save_checkpoint(attempt_id, checkpoint)
                    else:
                        self._same_checkpoint(current, checkpoint)
            except ExperimentConflict as conflict:
                return self._terminal_after_conflict(session, attempt_id, conflict)

        result, evidence = experiments.execute_pair(
            material["definition"],
            checkpoint,
            material["baseline_input"],
            material["treatment_input"],
        )
        if evidence is None:
            return self._fail(
                session,
                attempt_id,
                code="execution_refused",
                detail=self._invalid_pair_detail(result),
                checkpoint=checkpoint,
            )

        try:
            with self.database.session(session.workspace_id) as connection:
                repository = self._repository(connection, session)
                current = repository.execution_material(attempt_id)
                receipt = self._receipt(current)
                if receipt is not None:
                    return receipt
                self._same_checkpoint(current, checkpoint)
                repository.complete_attempt(attempt_id, evidence, result)
        except ExperimentConflict as conflict:
            return self._terminal_after_conflict(session, attempt_id, conflict)
        receipt = self._receipt(self._material(session, attempt_id))
        if receipt is None:  # pragma: no cover - append and reload are one tested contract
            raise ExperimentConflict("experiment completion was not recorded")
        return receipt
