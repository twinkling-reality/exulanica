"""Durable authority boundary for controlled living-v4 society experiments.

The repository never accepts a caller's input digest as authority. It resolves the exact
workspace-scoped society and immutable input rows, asks the configured runtime authorizer to
check their current dependencies, and then validates the complete documents. Simulation and
replay happen outside database transactions; transactions only append already-validated records.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from copy import deepcopy
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.world import society_experiments as experiments
from exulanica.world.society import UnavailableSocietyInput, society_state_sha256
from exulanica.world.society_engines import EXPERIMENT_ENGINES, society_engine

__all__ = [
    "ExperimentConflict",
    "ExperimentResourceLimit",
    "SocietyExperimentRepository",
    "UnknownExperiment",
]

FAILURE_PROFILE: Final = "exulanica.society-experiment-failure/v1"
MAX_DEFINITION_BYTES: Final = 256 * 1024
MAX_CHECKPOINT_BYTES: Final = 16 * 1024 * 1024
MAX_EVIDENCE_BYTES: Final = 256 * 1024 * 1024
MAX_RESULT_BYTES: Final = 2 * 1024 * 1024
MAX_FAILURE_BYTES: Final = 16 * 1024
MAX_POPULATION: Final = 256
MAX_WARMUP_TICKS: Final = 1_440
MAX_FOLLOWUP_TICKS: Final = 1_440
MAX_PERSON_TICKS: Final = 500_000
_ATTEMPT_LOCK_SALT: Final = 880_084
_FAILURE_CODES: Final = frozenset(
    {"checkpoint_refused", "execution_refused", "validation_refused", "operator_aborted"}
)


class UnknownExperiment(LookupError):
    """An experiment or attempt is unavailable in the current workspace."""


class ExperimentConflict(ValueError):
    """An idempotency identity already names different immutable content."""


class ExperimentResourceLimit(ValueError):
    """A request exceeds the bounded experiment workload or record size."""


def _size(value: dict[str, Any], name: str, limit: int) -> int:
    size = len(canonical_json(value))
    if size > limit:
        raise ExperimentResourceLimit(f"{name} exceeds the {limit}-byte limit")
    return size


def _sealed(document: dict[str, Any]) -> bool:
    digest = document.get("document_sha256")
    return isinstance(digest, str) and digest == society_state_sha256(
        {key: value for key, value in document.items() if key != "document_sha256"}
    )


class SocietyExperimentRepository:
    """Append and verify experiment records for one already-scoped workspace."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        input_authorizer: Callable[[dict[str, Any]], None] | None = None,
        execution_authorizer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.input_authorizer = input_authorizer
        self.execution_authorizer = execution_authorizer

    def _authorize(self, *documents: dict[str, Any]) -> None:
        if self.input_authorizer is None:
            raise UnavailableSocietyInput("current society input authorization is not configured")
        seen: set[str] = set()
        for document in documents:
            digest = document["document_sha256"]
            if digest not in seen:
                self.input_authorizer(document)
                seen.add(digest)

    @staticmethod
    def _reservation(attempt: dict[str, Any]) -> dict[str, Any]:
        return {
            "workspace_id": attempt["workspace_id"],
            "attempt_id": attempt["attempt_id"],
            "experiment_id": attempt["experiment_id"],
            "phase": attempt["phase"],
            "seed_sha256": attempt["seed_sha256"],
            "created_by": attempt["created_by"],
            "created_at": attempt["created_at"],
        }

    def _authorize_execution(self, attempt: dict[str, Any], *, required: bool = False) -> None:
        if self.execution_authorizer is None:
            if required:
                raise UnavailableSocietyInput(
                    "current experiment execution authorization is not configured"
                )
            return
        self.execution_authorizer(deepcopy(self._reservation(attempt)))

    def _require_idle_replay_connection(self) -> None:
        if self.connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            raise ValueError("society experiment replay requires an idle connection")

    def _lock_attempt(self, attempt_id: uuid.UUID) -> None:
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s,%s))",
            (f"{self.workspace_id}:{attempt_id}", _ATTEMPT_LOCK_SALT),
        )

    def _definition_row(self, experiment_id: uuid.UUID) -> dict[str, Any]:
        row = self.connection.execute(
            "select * from society_experiment_definition where workspace_id=%s "
            "and experiment_id=%s",
            (self.workspace_id, experiment_id),
        ).fetchone()
        if row is None:
            raise UnknownExperiment("experiment is unavailable")
        return dict(row)

    def _attempt_row(self, attempt_id: uuid.UUID) -> dict[str, Any]:
        row = self.connection.execute(
            "select * from society_experiment_attempt where workspace_id=%s and attempt_id=%s",
            (self.workspace_id, attempt_id),
        ).fetchone()
        if row is None:
            raise UnknownExperiment("experiment attempt is unavailable")
        return dict(row)

    def _source(
        self, source_society_id: uuid.UUID, baseline_seq: int, treatment_seq: int
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        source = self.connection.execute(
            "select s.*,v.state_sha256 as authored_state_sha256,v.edit_seq as authored_edit_seq "
            "from world_society s join world_alternate_version v "
            "on v.workspace_id=s.workspace_id and v.world_id=s.world_id "
            "and v.version_id=s.version_id where s.workspace_id=%s and s.society_id=%s",
            (self.workspace_id, source_society_id),
        ).fetchone()
        if source is None or not society_engine(source["engine_version"]).experiments:
            raise UnknownExperiment("experiment source is unavailable")
        rows = self.connection.execute(
            "select input_seq,document,document_sha256 from world_society_input "
            "where workspace_id=%s and society_id=%s and input_seq=any(%s) order by input_seq",
            (self.workspace_id, source_society_id, [baseline_seq, treatment_seq]),
        ).fetchall()
        by_seq = {row["input_seq"]: dict(row) for row in rows}
        if baseline_seq not in by_seq or treatment_seq not in by_seq:
            raise UnknownExperiment("experiment source is unavailable")
        baseline, treatment = by_seq[baseline_seq], by_seq[treatment_seq]
        for stored in (baseline, treatment):
            document = stored["document"]
            if (
                document.get("input_seq") != stored["input_seq"]
                or document.get("document_sha256") != stored["document_sha256"]
            ):
                raise experiments.ExperimentIntegrityError("stored society input binding mismatch")
        self._authorize(baseline["document"], treatment["document"])
        version = {
            "world_id": source["world_id"],
            "version_id": source["version_id"],
            "authored_state_sha256": source["authored_state_sha256"],
            "authored_edit_seq": source["authored_edit_seq"],
        }
        return dict(source), baseline, treatment, version

    def _source_society_for_version(self, version_id: uuid.UUID, world_id: str) -> uuid.UUID:
        rows = self.connection.execute(
            "select society_id from world_society where workspace_id=%s and world_id=%s "
            "and version_id=%s and engine_version=any(%s) order by society_id limit 2",
            (self.workspace_id, world_id, version_id, list(EXPERIMENT_ENGINES)),
        ).fetchall()
        if len(rows) != 1:
            raise UnknownExperiment("experiment source is unavailable")
        return rows[0]["society_id"]

    def _validated_definition_source(
        self, row: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        document = row["document"]
        if not _sealed(document) or document["document_sha256"] != row["document_sha256"]:
            raise experiments.ExperimentIntegrityError(
                "stored experiment definition digest mismatch"
            )
        self._bounded_work(document)
        source, baseline, treatment, _version = self._source(
            row["source_society_id"], row["baseline_input_seq"], row["treatment_input_seq"]
        )
        if (
            baseline["document_sha256"] != row["baseline_input_sha256"]
            or treatment["document_sha256"] != row["treatment_input_sha256"]
            or row["world_id"] != source["world_id"]
            or row["authored_version_id"] != source["version_id"]
            or treatment["document"]["authored_state"]
            != {
                "edit_seq": row["authored_edit_seq"],
                "delta_sha256": row["authored_state_sha256"],
            }
        ):
            raise experiments.ExperimentIntegrityError(
                "stored experiment authority binding mismatch"
            )
        experiments.validate_experiment_definition(
            document, baseline["document"], treatment["document"]
        )
        return source, baseline["document"], treatment["document"]

    @staticmethod
    def _bounded_work(definition: dict[str, Any]) -> None:
        warmup = definition.get("warmup_ticks")
        followup = definition.get("followup_ticks")
        declared = definition.get("population")
        if declared is None:
            raise ExperimentResourceLimit(
                "a durable experiment requires an explicit bounded population"
            )
        if type(warmup) is not int or warmup < 1 or warmup > MAX_WARMUP_TICKS:
            raise ExperimentResourceLimit("warmup ticks exceed the controlled experiment limit")
        if type(followup) is not int or followup < 1 or followup > MAX_FOLLOWUP_TICKS:
            raise ExperimentResourceLimit("follow-up ticks exceed the controlled experiment limit")
        if type(declared) is not int or declared < 1 or declared > MAX_POPULATION:
            raise ExperimentResourceLimit("population exceeds the controlled experiment limit")
        person_ticks = declared * (warmup + 2 * followup)
        if person_ticks > MAX_PERSON_TICKS:
            raise ExperimentResourceLimit("experiment person-ticks exceed the controlled limit")

    def create_definition(
        self,
        experiment_id: uuid.UUID,
        source_society_id: uuid.UUID,
        definition: dict[str, Any],
        *,
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        """Resolve authority and append one immutable definition, idempotently."""
        _size(definition, "experiment definition", MAX_DEFINITION_BYTES)
        baseline_binding = definition.get("baseline_input", {})
        treatment_binding = definition.get("treatment_input", {})
        baseline_seq = baseline_binding.get("input_seq")
        treatment_seq = treatment_binding.get("input_seq")
        if type(baseline_seq) is not int or type(treatment_seq) is not int:
            raise experiments.ExperimentIntegrityError("definition input sequences are invalid")
        source, baseline, treatment, _version = self._source(
            source_society_id, baseline_seq, treatment_seq
        )
        self._bounded_work(definition)
        experiments.validate_experiment_definition(
            definition, baseline["document"], treatment["document"]
        )
        authored = treatment["document"]["authored_state"]
        values = {
            "workspace_id": self.workspace_id,
            "experiment_id": experiment_id,
            "source_society_id": source_society_id,
            "world_id": source["world_id"],
            "authored_version_id": source["version_id"],
            "authored_state_sha256": authored["delta_sha256"],
            "authored_edit_seq": authored["edit_seq"],
            "baseline_input_seq": baseline_seq,
            "baseline_input_sha256": baseline["document_sha256"],
            "treatment_input_seq": treatment_seq,
            "treatment_input_sha256": treatment["document_sha256"],
            "document": deepcopy(definition),
            "document_sha256": definition["document_sha256"],
            "created_by": actor,
        }
        with self.connection.transaction():
            # Re-resolve and re-authorize after validation, immediately before the append.
            self._source(source_society_id, baseline_seq, treatment_seq)
            self.connection.execute(
                "insert into society_experiment_definition(workspace_id,experiment_id,"
                "source_society_id,world_id,authored_version_id,authored_state_sha256,"
                "authored_edit_seq,baseline_input_seq,baseline_input_sha256,treatment_input_seq,"
                "treatment_input_sha256,document,document_sha256,created_by) values("
                + ",".join(["%s"] * 14)
                + ") on conflict(workspace_id,experiment_id) do nothing",
                (
                    values["workspace_id"],
                    values["experiment_id"],
                    values["source_society_id"],
                    values["world_id"],
                    values["authored_version_id"],
                    values["authored_state_sha256"],
                    values["authored_edit_seq"],
                    values["baseline_input_seq"],
                    values["baseline_input_sha256"],
                    values["treatment_input_seq"],
                    values["treatment_input_sha256"],
                    Jsonb(values["document"]),
                    values["document_sha256"],
                    values["created_by"],
                ),
            )
            held = self._definition_row(experiment_id)
            if any(held[key] != value for key, value in values.items()):
                raise ExperimentConflict("experiment identity already names another definition")
        return self.definition(experiment_id)

    def prepare_definition(
        self,
        version_id: uuid.UUID,
        experiment_id: uuid.UUID,
        *,
        world_id: str,
        baseline_input_seq: int,
        treatment_input_seq: int,
        intervention: str,
        target_id: str | None,
        population: int,
        warmup_ticks: int,
        followup_ticks: int,
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        """Freeze a supported definition from immutable server-resolved input rows."""
        self._bounded_work(
            {
                "population": population,
                "warmup_ticks": warmup_ticks,
                "followup_ticks": followup_ticks,
            }
        )
        if intervention == "noop":
            if target_id is not None or baseline_input_seq != treatment_input_seq:
                raise experiments.ExperimentIntegrityError(
                    "a no-op definition must bind one exact input sequence"
                )
        elif intervention == "add_rest_amenity":
            if target_id is None:
                raise experiments.ExperimentIntegrityError(
                    "a rest-amenity definition requires a target identity"
                )
        else:
            raise experiments.ExperimentIntegrityError("unsupported experiment intervention")
        source_society_id = self._source_society_for_version(version_id, world_id)
        _source, baseline, treatment, _version = self._source(
            source_society_id, baseline_input_seq, treatment_input_seq
        )
        if intervention == "noop":
            definition = experiments.freeze_noop_control_definition(
                baseline["document"],
                population=population,
                warmup_ticks=warmup_ticks,
                followup_ticks=followup_ticks,
            )
        elif intervention == "add_rest_amenity":
            assert target_id is not None
            definition = experiments.freeze_rest_amenity_definition(
                baseline["document"],
                treatment["document"],
                target_id=target_id,
                population=population,
                warmup_ticks=warmup_ticks,
                followup_ticks=followup_ticks,
            )
        return self.create_definition(experiment_id, source_society_id, definition, actor=actor)

    def definition(self, experiment_id: uuid.UUID) -> dict[str, Any]:
        row = self._definition_row(experiment_id)
        self._validated_definition_source(row)
        return deepcopy(row)

    def _definition_in(
        self, world_id: str, version_id: uuid.UUID, experiment_id: uuid.UUID, refusal: str
    ) -> dict[str, Any]:
        """The definition, only when it belongs to the exact world and version its caller named."""
        row = self._definition_row(experiment_id)
        if (row["world_id"], row["authored_version_id"]) != (world_id, version_id):
            raise UnknownExperiment(refusal)
        return row

    def definition_for_version(
        self, version_id: uuid.UUID, experiment_id: uuid.UUID, *, world_id: str
    ) -> dict[str, Any]:
        """Read only when the definition belongs to the exact world and version in the route."""
        row = self._definition_in(world_id, version_id, experiment_id, "experiment is unavailable")
        self._validated_definition_source(row)
        return deepcopy(row)

    def start_attempt(
        self,
        experiment_id: uuid.UUID,
        attempt_id: uuid.UUID,
        seed_sha256: str,
        *,
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        """Reserve a development attempt before checkpoint or arm computation begins."""
        if seed_sha256 not in experiments.DEVELOPMENT_SEEDS:
            raise experiments.ExperimentIntegrityError(
                "only a seed committed to the development split can be started"
            )
        definition = self._definition_row(experiment_id)
        self._validated_definition_source(definition)
        values = {
            "workspace_id": self.workspace_id,
            "attempt_id": attempt_id,
            "experiment_id": experiment_id,
            "phase": "development",
            "seed_sha256": seed_sha256,
            "created_by": actor,
        }
        with self.connection.transaction():
            self._validated_definition_source(self._definition_row(experiment_id))
            self.connection.execute(
                "insert into society_experiment_attempt(workspace_id,attempt_id,experiment_id,"
                "phase,seed_sha256,created_by) values(%s,%s,%s,%s,%s,%s) "
                "on conflict(workspace_id,attempt_id) do nothing",
                tuple(values.values()),
            )
            held = self._attempt_row(attempt_id)
            if any(held[key] != value for key, value in values.items()):
                raise ExperimentConflict("attempt identity already names another request")
        return self.attempt(attempt_id)

    def start_attempt_for_version(
        self,
        version_id: uuid.UUID,
        experiment_id: uuid.UUID,
        attempt_id: uuid.UUID,
        seed_sha256: str,
        *,
        world_id: str,
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        """Reserve only beneath the exact world, version and experiment named by the route."""
        if seed_sha256 not in experiments.DEVELOPMENT_SEEDS:
            raise experiments.ExperimentIntegrityError(
                "only a seed committed to the development split can be started"
            )
        self.definition_for_version(version_id, experiment_id, world_id=world_id)
        return self.start_attempt(experiment_id, attempt_id, seed_sha256, actor=actor)

    def save_checkpoint(self, attempt_id: uuid.UUID, checkpoint: dict[str, Any]) -> dict[str, Any]:
        """Replay and seal one checkpoint; no replay occurs while a transaction is open."""
        self._require_idle_replay_connection()
        _size(checkpoint, "experiment checkpoint", MAX_CHECKPOINT_BYTES)
        attempt = self._attempt_row(attempt_id)
        terminal = self.connection.execute(
            "select 1 from society_experiment_outcome where workspace_id=%s and attempt_id=%s",
            (self.workspace_id, attempt_id),
        ).fetchone()
        if terminal is not None:
            raise ExperimentConflict("a terminal attempt cannot accept a checkpoint")
        definition = self._definition_row(attempt["experiment_id"])
        _source, baseline, _treatment = self._validated_definition_source(definition)
        if (
            checkpoint.get("phase") != attempt["phase"]
            or checkpoint.get("seed_sha256") != attempt["seed_sha256"]
        ):
            raise experiments.ExperimentIntegrityError("checkpoint attempt binding mismatch")
        self._require_idle_replay_connection()
        experiments.validate_experiment_checkpoint(definition["document"], checkpoint, baseline)
        values = {
            "workspace_id": self.workspace_id,
            "experiment_id": attempt["experiment_id"],
            "attempt_id": attempt_id,
            "document": deepcopy(checkpoint),
            "document_sha256": checkpoint["document_sha256"],
        }
        with self.connection.transaction():
            self._lock_attempt(attempt_id)
            terminal = self.connection.execute(
                "select 1 from society_experiment_outcome where workspace_id=%s and attempt_id=%s",
                (self.workspace_id, attempt_id),
            ).fetchone()
            if terminal is not None:
                raise ExperimentConflict("a terminal attempt cannot accept a checkpoint")
            self._authorize_execution(self._attempt_row(attempt_id))
            self._validated_definition_source(self._definition_row(attempt["experiment_id"]))
            self.connection.execute(
                "insert into society_experiment_checkpoint(workspace_id,experiment_id,attempt_id,"
                "document,document_sha256) values(%s,%s,%s,%s,%s) "
                "on conflict(workspace_id,attempt_id) do nothing",
                (
                    values["workspace_id"],
                    values["experiment_id"],
                    values["attempt_id"],
                    Jsonb(values["document"]),
                    values["document_sha256"],
                ),
            )
            held = self.connection.execute(
                "select * from society_experiment_checkpoint where workspace_id=%s "
                "and attempt_id=%s",
                (self.workspace_id, attempt_id),
            ).fetchone()
            if held is None or any(held[key] != value for key, value in values.items()):
                raise ExperimentConflict("attempt already has another checkpoint")
        return self.attempt(attempt_id)

    def complete_attempt(
        self,
        attempt_id: uuid.UUID,
        evidence: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Replay evidence outside the transaction, then append one terminal completion."""
        self._require_idle_replay_connection()
        _size(evidence, "experiment evidence", MAX_EVIDENCE_BYTES)
        _size(result, "experiment result", MAX_RESULT_BYTES)
        attempt = self._attempt_row(attempt_id)
        definition = self._definition_row(attempt["experiment_id"])
        self._validated_definition_source(definition)
        checkpoint_row = self.connection.execute(
            "select * from society_experiment_checkpoint where workspace_id=%s and attempt_id=%s",
            (self.workspace_id, attempt_id),
        ).fetchone()
        if checkpoint_row is None:
            raise ExperimentConflict("an incomplete attempt has no sealed checkpoint")
        checkpoint = checkpoint_row["document"]
        self._require_idle_replay_connection()
        experiments.verify_pair_result(result, definition["document"], checkpoint, evidence)
        values = {
            "workspace_id": self.workspace_id,
            "experiment_id": attempt["experiment_id"],
            "attempt_id": attempt_id,
            "status": "completed",
            "checkpoint_sha256": checkpoint["document_sha256"],
            "evidence": deepcopy(evidence),
            "evidence_sha256": evidence["document_sha256"],
            "result": deepcopy(result),
            "result_sha256": result["document_sha256"],
            "failure": None,
            "failure_sha256": None,
        }
        with self.connection.transaction():
            self._lock_attempt(attempt_id)
            self._authorize_execution(self._attempt_row(attempt_id))
            self._validated_definition_source(self._definition_row(attempt["experiment_id"]))
            current_checkpoint = self.connection.execute(
                "select document_sha256 from society_experiment_checkpoint "
                "where workspace_id=%s and attempt_id=%s",
                (self.workspace_id, attempt_id),
            ).fetchone()
            if (
                current_checkpoint is None
                or current_checkpoint["document_sha256"] != values["checkpoint_sha256"]
            ):
                raise ExperimentConflict("attempt checkpoint changed before completion")
            self.connection.execute(
                "insert into society_experiment_outcome(workspace_id,experiment_id,attempt_id,"
                "status,checkpoint_sha256,evidence,evidence_sha256,result,result_sha256,failure,"
                "failure_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "on conflict(workspace_id,attempt_id) do nothing",
                (
                    values["workspace_id"],
                    values["experiment_id"],
                    values["attempt_id"],
                    values["status"],
                    values["checkpoint_sha256"],
                    Jsonb(values["evidence"]),
                    values["evidence_sha256"],
                    Jsonb(values["result"]),
                    values["result_sha256"],
                    None,
                    None,
                ),
            )
            self._compare_outcome(attempt_id, values)
        return self.attempt(attempt_id)

    def fail_attempt(
        self,
        attempt_id: uuid.UUID,
        *,
        code: str,
        detail: str,
    ) -> dict[str, Any]:
        """Append a bounded server-shaped failure, including before a checkpoint exists."""
        if code not in _FAILURE_CODES:
            raise ValueError("unsupported experiment failure code")
        if not isinstance(detail, str) or not 1 <= len(detail) <= 2_000:
            raise ValueError("experiment failure detail must contain 1 to 2000 characters")
        attempt = self._attempt_row(attempt_id)
        definition = self._definition_row(attempt["experiment_id"])
        self._validated_definition_source(definition)
        checkpoint = self.connection.execute(
            "select document_sha256 from society_experiment_checkpoint "
            "where workspace_id=%s and attempt_id=%s",
            (self.workspace_id, attempt_id),
        ).fetchone()
        failure = {
            "profile": FAILURE_PROFILE,
            "attempt_id": str(attempt_id),
            "definition_sha256": definition["document_sha256"],
            "checkpoint_sha256": "" if checkpoint is None else checkpoint["document_sha256"],
            "code": code,
            "detail": detail,
        }
        failure["document_sha256"] = society_state_sha256(failure)
        _size(failure, "experiment failure", MAX_FAILURE_BYTES)
        values = {
            "workspace_id": self.workspace_id,
            "experiment_id": attempt["experiment_id"],
            "attempt_id": attempt_id,
            "status": "failed",
            "checkpoint_sha256": None if checkpoint is None else checkpoint["document_sha256"],
            "evidence": None,
            "evidence_sha256": None,
            "result": None,
            "result_sha256": None,
            "failure": failure,
            "failure_sha256": failure["document_sha256"],
        }
        with self.connection.transaction():
            self._lock_attempt(attempt_id)
            self._authorize_execution(self._attempt_row(attempt_id))
            self._validated_definition_source(self._definition_row(attempt["experiment_id"]))
            current_checkpoint = self.connection.execute(
                "select document_sha256 from society_experiment_checkpoint "
                "where workspace_id=%s and attempt_id=%s",
                (self.workspace_id, attempt_id),
            ).fetchone()
            current_checkpoint_sha256 = (
                None if current_checkpoint is None else current_checkpoint["document_sha256"]
            )
            if current_checkpoint_sha256 != values["checkpoint_sha256"]:
                raise ExperimentConflict("attempt checkpoint changed before failure was sealed")
            self.connection.execute(
                "insert into society_experiment_outcome(workspace_id,experiment_id,attempt_id,"
                "status,checkpoint_sha256,evidence,evidence_sha256,result,result_sha256,failure,"
                "failure_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "on conflict(workspace_id,attempt_id) do nothing",
                (
                    values["workspace_id"],
                    values["experiment_id"],
                    values["attempt_id"],
                    values["status"],
                    values["checkpoint_sha256"],
                    None,
                    None,
                    None,
                    None,
                    Jsonb(failure),
                    values["failure_sha256"],
                ),
            )
            self._compare_outcome(attempt_id, values)
        return self.attempt(attempt_id)

    def _compare_outcome(self, attempt_id: uuid.UUID, values: dict[str, Any]) -> None:
        held = self.connection.execute(
            "select * from society_experiment_outcome where workspace_id=%s and attempt_id=%s",
            (self.workspace_id, attempt_id),
        ).fetchone()
        if held is None or any(held[key] != value for key, value in values.items()):
            raise ExperimentConflict("attempt already has another terminal outcome")

    def attempt(self, attempt_id: uuid.UUID) -> dict[str, Any]:
        """Return one authorized record with non-disclosing workspace isolation."""
        attempt = self._attempt_row(attempt_id)
        definition = self._definition_row(attempt["experiment_id"])
        self._validated_definition_source(definition)
        checkpoint = self.connection.execute(
            "select * from society_experiment_checkpoint where workspace_id=%s and attempt_id=%s",
            (self.workspace_id, attempt_id),
        ).fetchone()
        outcome = self.connection.execute(
            "select * from society_experiment_outcome where workspace_id=%s and attempt_id=%s",
            (self.workspace_id, attempt_id),
        ).fetchone()
        if checkpoint is not None:
            document = checkpoint["document"]
            if (
                not _sealed(document)
                or document["document_sha256"] != checkpoint["document_sha256"]
            ):
                raise experiments.ExperimentIntegrityError("stored checkpoint digest mismatch")
        if outcome is not None:
            self._validate_outcome_shape(dict(outcome), definition, checkpoint)
        return {
            **deepcopy(attempt),
            "status": "incomplete" if outcome is None else outcome["status"],
            "checkpoint": None if checkpoint is None else deepcopy(dict(checkpoint)),
            "outcome": None if outcome is None else deepcopy(dict(outcome)),
        }

    def attempt_summary(
        self,
        version_id: uuid.UUID,
        experiment_id: uuid.UUID,
        attempt_id: uuid.UUID,
        *,
        world_id: str,
    ) -> dict[str, Any]:
        """Return a compact authorized record without loading stored execution evidence."""
        attempt = self._attempt_row(attempt_id)
        if attempt["experiment_id"] != experiment_id:
            raise UnknownExperiment("experiment attempt is unavailable")
        definition = self._definition_in(
            world_id, version_id, experiment_id, "experiment attempt is unavailable"
        )
        self._validated_definition_source(definition)
        checkpoint = self.connection.execute(
            "select document_sha256,recorded_at from society_experiment_checkpoint "
            "where workspace_id=%s and experiment_id=%s and attempt_id=%s",
            (self.workspace_id, experiment_id, attempt_id),
        ).fetchone()
        outcome = self.connection.execute(
            "select status,checkpoint_sha256,evidence_sha256,result,result_sha256,failure,"
            "failure_sha256,recorded_at from society_experiment_outcome where workspace_id=%s "
            "and experiment_id=%s and attempt_id=%s",
            (self.workspace_id, experiment_id, attempt_id),
        ).fetchone()
        if outcome is not None:
            self._validate_summary_outcome(
                dict(outcome), definition, checkpoint, attempt["seed_sha256"], attempt_id
            )
        return {
            **deepcopy(attempt),
            "definition_sha256": definition["document_sha256"],
            "status": "incomplete" if outcome is None else outcome["status"],
            "checkpoint_sha256": (None if checkpoint is None else checkpoint["document_sha256"]),
            "checkpoint_recorded_at": (None if checkpoint is None else checkpoint["recorded_at"]),
            "outcome": None if outcome is None else deepcopy(dict(outcome)),
        }

    def execution_material(self, attempt_id: uuid.UUID) -> dict[str, Any]:
        """Resolve one reserved attempt for trusted out-of-request execution.

        The caller must install a current execution authorizer. The stored creator is returned
        as attribution only and never grants execution. Source documents are resolved from their
        immutable rows and pass the ordinary current-input authorizer before leaving this method.
        Full evidence is deliberately not loaded for a terminal attempt.
        """
        self._require_idle_replay_connection()
        attempt = self._attempt_row(attempt_id)
        if (
            attempt["phase"] != "development"
            or attempt["seed_sha256"] not in experiments.DEVELOPMENT_SEEDS
        ):
            raise experiments.ExperimentIntegrityError(
                "local execution supports committed development attempts only"
            )
        reservation = self._reservation(attempt)
        self._authorize_execution(attempt, required=True)
        self._require_idle_replay_connection()
        definition = self._definition_row(attempt["experiment_id"])
        _source, baseline, treatment = self._validated_definition_source(definition)
        self._require_idle_replay_connection()
        checkpoint = self.connection.execute(
            "select document,document_sha256,recorded_at from society_experiment_checkpoint "
            "where workspace_id=%s and experiment_id=%s and attempt_id=%s",
            (self.workspace_id, attempt["experiment_id"], attempt_id),
        ).fetchone()
        outcome = self.connection.execute(
            "select status,checkpoint_sha256,evidence_sha256,result,result_sha256,failure,"
            "failure_sha256,recorded_at from society_experiment_outcome where workspace_id=%s "
            "and experiment_id=%s and attempt_id=%s",
            (self.workspace_id, attempt["experiment_id"], attempt_id),
        ).fetchone()
        if checkpoint is not None:
            document = checkpoint["document"]
            if (
                not _sealed(document)
                or document["document_sha256"] != checkpoint["document_sha256"]
                or document.get("definition_sha256") != definition["document_sha256"]
                or document.get("phase") != attempt["phase"]
                or document.get("seed_sha256") != attempt["seed_sha256"]
            ):
                raise experiments.ExperimentIntegrityError(
                    "stored experiment checkpoint execution binding mismatch"
                )
        if outcome is not None:
            self._validate_summary_outcome(
                dict(outcome), definition, checkpoint, attempt["seed_sha256"], attempt_id
            )
        return {
            "reservation": deepcopy(reservation),
            "definition": deepcopy(definition["document"]),
            "baseline_input": deepcopy(baseline),
            "treatment_input": deepcopy(treatment),
            "checkpoint": None if checkpoint is None else deepcopy(dict(checkpoint)),
            "terminal": None if outcome is None else deepcopy(dict(outcome)),
        }

    @staticmethod
    def _validate_summary_outcome(
        outcome: dict[str, Any],
        definition: dict[str, Any],
        checkpoint: Any,
        seed_sha256: str,
        attempt_id: uuid.UUID,
    ) -> None:
        if outcome["status"] == "completed":
            result = outcome["result"]
            if (
                checkpoint is None
                or not _sealed(result)
                or outcome["checkpoint_sha256"] != checkpoint["document_sha256"]
                or outcome["result_sha256"] != result["document_sha256"]
                or result.get("definition_sha256") != definition["document_sha256"]
                or result.get("checkpoint_sha256") != checkpoint["document_sha256"]
                or result.get("seed_sha256") != seed_sha256
            ):
                raise experiments.ExperimentIntegrityError(
                    "stored completion summary binding mismatch"
                )
        elif outcome["status"] == "failed":
            failure = outcome["failure"]
            if (
                not _sealed(failure)
                or failure.get("profile") != FAILURE_PROFILE
                or failure.get("attempt_id") != str(attempt_id)
                or failure.get("definition_sha256") != definition["document_sha256"]
                or failure.get("checkpoint_sha256")
                != ("" if checkpoint is None else checkpoint["document_sha256"])
                or outcome["failure_sha256"] != failure["document_sha256"]
            ):
                raise experiments.ExperimentIntegrityError(
                    "stored failure summary binding mismatch"
                )
        else:
            raise experiments.ExperimentIntegrityError(
                "stored experiment outcome status is invalid"
            )

    @staticmethod
    def _validate_outcome_shape(
        outcome: dict[str, Any], definition: dict[str, Any], checkpoint: Any
    ) -> None:
        if outcome["status"] == "completed":
            if (
                checkpoint is None
                or not _sealed(outcome["evidence"])
                or not _sealed(outcome["result"])
            ):
                raise experiments.ExperimentIntegrityError("stored completion digest mismatch")
            if (
                outcome["checkpoint_sha256"] != checkpoint["document_sha256"]
                or outcome["evidence_sha256"] != outcome["evidence"]["document_sha256"]
                or outcome["result_sha256"] != outcome["result"]["document_sha256"]
            ):
                raise experiments.ExperimentIntegrityError("stored completion binding mismatch")
        elif outcome["status"] == "failed":
            failure = outcome["failure"]
            if (
                not _sealed(failure)
                or failure["profile"] != FAILURE_PROFILE
                or failure["definition_sha256"] != definition["document_sha256"]
                or outcome["failure_sha256"] != failure["document_sha256"]
            ):
                raise experiments.ExperimentIntegrityError("stored failure binding mismatch")
        else:
            raise experiments.ExperimentIntegrityError(
                "stored experiment outcome status is invalid"
            )

    def verify_attempt(self, attempt_id: uuid.UUID) -> dict[str, Any]:
        """Reopen and replay every sealed artifact without changing the live society."""
        self._require_idle_replay_connection()
        record = self.attempt(attempt_id)
        definition = self._definition_row(record["experiment_id"])
        _source, baseline, _treatment = self._validated_definition_source(definition)
        if record["checkpoint"] is not None:
            self._require_idle_replay_connection()
            experiments.validate_experiment_checkpoint(
                definition["document"], record["checkpoint"]["document"], baseline
            )
        if record["status"] == "completed":
            outcome = record["outcome"]
            self._require_idle_replay_connection()
            experiments.verify_pair_result(
                outcome["result"],
                definition["document"],
                record["checkpoint"]["document"],
                outcome["evidence"],
            )
        return record
