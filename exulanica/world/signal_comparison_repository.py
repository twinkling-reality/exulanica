"""The records of a signal comparison: its definition, its runs, their receipts and outcomes.

A signal comparison is defined over one saved world version's roads as they are: the repository
reads the roads the version's snapshot states (:func:`~exulanica.world.traffic_host.
saved_world_roads`), never a caller's copy, and records a definition naming the roads by version
and digest, the group of signals the arms decide for, the arms, the seeds it committed to by
digest, the protocol and catalogs it is run and judged under, and the junction signal role's
contract (migration 0132). Runs are reserved before anything is asked, their receipts are appended
as they are paid for, and each run ends in one outcome.

Nothing here plays an episode or asks a model. :meth:`SignalComparisonRepository.plan` gives the
runner the :class:`~exulanica.world.signal_comparison.SignalRunPlan` it plays, over the roads the
version states now, refused as ``roads_changed`` when they no longer digest to the roads the
comparison recorded. Every statement names the workspace and the world; a run's seed is read here,
for a runner and a replay, and no read of runs returns it.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.db.session import set_workspace
from exulanica.world.decision_roles import DecisionRole
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.signal_comparison import SignalRunPlan
from exulanica.world.society import seed_digest
from exulanica.world.traffic_episodes import TrafficInput
from exulanica.world.traffic_host import saved_world_roads

__all__ = [
    "DEFINITION_PROFILE",
    "FAILURE_PROFILE",
    "RUN_PROFILE",
    "SignalComparisonConflict",
    "SignalComparisonRefused",
    "SignalComparisonRepository",
    "UnknownSignalComparison",
    "run_id_for",
]

DEFINITION_PROFILE: Final = "exulanica.signal-comparison/v1"
RUN_PROFILE: Final = "exulanica.signal-comparison-run/v1"
FAILURE_PROFILE: Final = "exulanica.signal-comparison-failure/v1"
_RUN_NAMESPACE: Final = uuid.UUID("0b2f6a9e-3c51-4d7e-9a4b-6e1f2d8c5a37")


class UnknownSignalComparison(UnknownWorldResource, LookupError):
    """A signal comparison or run is unavailable in this workspace and world: answered as an
    unknown reference, so no reader learns whether another workspace holds the id."""


class SignalComparisonConflict(ValueError):
    """A caller's comparison id already names a different definition."""


class SignalComparisonRefused(ValueError):
    """A signal comparison these records cannot hold or play, refused by name."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def run_id_for(comparison_id: uuid.UUID, arm: str, digest: str) -> uuid.UUID:
    """One run per arm and seed of a comparison, so reserving it again finds the same run."""
    return uuid.uuid5(_RUN_NAMESPACE, f"{comparison_id}:{arm}:{digest}")


def sealed(document: Mapping[str, Any]) -> dict[str, Any]:
    """``document`` with its own digest, over everything else it states."""
    body = {key: value for key, value in document.items() if key != "document_sha256"}
    return {**body, "document_sha256": hashlib.sha256(canonical_json(body)).hexdigest()}


class SignalComparisonRepository:
    """Append and read signal comparison records in one workspace and world."""

    def __init__(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str
    ) -> None:
        self.connection, self.workspace_id, self.world_id = connection, workspace_id, world_id
        connection.row_factory = dict_row
        set_workspace(connection, workspace_id)

    # -- the roads -------------------------------------------------------------------------------

    def snapshot_of(self, version_id: uuid.UUID) -> uuid.UUID:
        """The source snapshot of one of the world's versions, or unavailable."""
        row = self.connection.execute(
            "select source_snapshot_id from world_alternate_version where workspace_id=%s "
            "and world_id=%s and version_id=%s",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()
        if row is None:
            raise UnknownSignalComparison("version is unavailable")
        return row["source_snapshot_id"]

    def roads(self, version_id: uuid.UUID) -> TrafficInput:
        """The roads the version's snapshot states now, as traffic reads them."""
        return saved_world_roads(
            self.connection, self.workspace_id, self.world_id, self.snapshot_of(version_id)
        )

    # -- definitions -----------------------------------------------------------------------------

    def define(
        self, comparison_id: uuid.UUID, document: Mapping[str, Any], *, created_by: uuid.UUID
    ) -> dict[str, Any]:
        """Record ``document`` (sealed here) as a comparison of this world; the same id with the
        same document returns the stored definition, with another it is a conflict."""
        stored = sealed(document)
        if stored["profile"] != DEFINITION_PROFILE or stored["world_id"] != self.world_id:
            raise SignalComparisonRefused("definition_profile", "not a signal comparison here")
        existing = self._definition(comparison_id, missing_ok=True)
        if existing is not None:
            if existing["document"] != stored:
                raise SignalComparisonConflict("the comparison id names another definition")
            return existing["document"]
        try:
            with self.connection.transaction():
                self.connection.execute(
                    "insert into signal_comparison(workspace_id,world_id,comparison_id,version_id,"
                    "roads_version,roads_sha256,document,document_sha256,created_by) "
                    "values(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.workspace_id,
                        self.world_id,
                        comparison_id,
                        uuid.UUID(stored["version_id"]),
                        stored["roads"]["roads_version"],
                        stored["roads"]["input_sha256"],
                        Jsonb(stored),
                        stored["document_sha256"],
                        created_by,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name != "signal_comparison_pkey":
                raise
            raise SignalComparisonConflict("the comparison id names another definition") from exc
        return stored

    def _definition(self, comparison_id: uuid.UUID, *, missing_ok: bool = False) -> dict | None:
        row = self.connection.execute(
            "select * from signal_comparison where workspace_id=%s and world_id=%s "
            "and comparison_id=%s",
            (self.workspace_id, self.world_id, comparison_id),
        ).fetchone()
        if row is None and not missing_ok:
            raise UnknownSignalComparison("comparison is unavailable")
        return row

    def definition(self, version_id: uuid.UUID, comparison_id: uuid.UUID) -> dict[str, Any]:
        """One comparison of this version, or unavailable."""
        row = self._definition(comparison_id)
        if row is None or row["version_id"] != version_id:
            raise UnknownSignalComparison("comparison is unavailable")
        return row

    def definitions(self, version_id: uuid.UUID) -> list[dict[str, Any]]:
        """This version's signal comparisons, newest first."""
        return self.connection.execute(
            "select * from signal_comparison where workspace_id=%s and world_id=%s "
            "and version_id=%s order by created_at desc, comparison_id",
            (self.workspace_id, self.world_id, version_id),
        ).fetchall()

    # -- runs ------------------------------------------------------------------------------------

    def reserve(
        self, comparison_id: uuid.UUID, *, arm: str, seed: str, created_by: uuid.UUID
    ) -> uuid.UUID:
        """The run of ``arm`` on ``seed``, reserved now or found reserved before."""
        digest = seed_digest(seed)
        run_id = run_id_for(comparison_id, arm, digest)
        self.connection.execute(
            "insert into signal_comparison_run(workspace_id,world_id,comparison_id,run_id,arm,"
            "seed,seed_digest,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (workspace_id,run_id) do nothing",
            (
                self.workspace_id,
                self.world_id,
                comparison_id,
                run_id,
                arm,
                seed,
                digest,
                created_by,
            ),
        )
        found = self._run(run_id)
        if (found["comparison_id"], found["arm"], found["seed_digest"]) != (
            comparison_id,
            arm,
            digest,
        ):
            raise SignalComparisonConflict("the run id already names another run")
        return run_id

    def _run(self, run_id: uuid.UUID) -> dict[str, Any]:
        row = self.connection.execute(
            "select * from signal_comparison_run where workspace_id=%s and world_id=%s "
            "and run_id=%s",
            (self.workspace_id, self.world_id, run_id),
        ).fetchone()
        if row is None:
            raise UnknownSignalComparison("run is unavailable")
        return row

    def runs(self, comparison_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every run of a comparison with its outcome, or None while it has none; no seed."""
        return self.connection.execute(
            "select r.comparison_id,r.run_id,r.arm,r.seed_digest,r.created_at,"
            "o.status,o.document as outcome from signal_comparison_run r "
            "left join signal_comparison_outcome o "
            "on o.workspace_id=r.workspace_id and o.world_id=r.world_id and o.run_id=r.run_id "
            "where r.workspace_id=%s and r.world_id=%s and r.comparison_id=%s "
            "order by r.seed_digest, r.arm",
            (self.workspace_id, self.world_id, comparison_id),
        ).fetchall()

    def run_counts(
        self, comparison_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, int, int]]:
        """How many runs each comparison reserved, completed and finished."""
        rows = self.connection.execute(
            "select r.comparison_id,count(*) as runs,"
            "count(o.run_id) filter (where o.status='completed') as completed,"
            "count(o.run_id) as finished "
            "from signal_comparison_run r left join signal_comparison_outcome o "
            "on o.workspace_id=r.workspace_id and o.world_id=r.world_id and o.run_id=r.run_id "
            "where r.workspace_id=%s and r.world_id=%s and r.comparison_id=any(%s) "
            "group by r.comparison_id",
            (self.workspace_id, self.world_id, list(comparison_ids)),
        ).fetchall()
        return {
            row["comparison_id"]: (int(row["runs"]), int(row["completed"]), int(row["finished"]))
            for row in rows
        }

    def open_runs(self, comparison_id: uuid.UUID) -> list[dict[str, Any]]:
        """A comparison's runs with no outcome yet, each saying whether it asked anything."""
        return self.connection.execute(
            "select r.run_id,r.arm,r.seed_digest,exists(select 1 from signal_comparison_decision "
            "d where d.workspace_id=r.workspace_id and d.world_id=r.world_id "
            "and d.run_id=r.run_id) as asked from signal_comparison_run r "
            "where r.workspace_id=%s and r.world_id=%s and r.comparison_id=%s "
            "and not exists(select 1 from signal_comparison_outcome o where "
            "o.workspace_id=r.workspace_id and o.world_id=r.world_id and o.run_id=r.run_id) "
            "order by r.seed_digest, r.arm",
            (self.workspace_id, self.world_id, comparison_id),
        ).fetchall()

    def spending(self, comparison_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
        """What each comparison's asks cost, as its receipts recorded each call."""
        rows = self.connection.execute(
            "select comparison_id,sum((receipt->'provider'->>'cost_usd')::numeric) as spent "
            "from signal_comparison_decision where workspace_id=%s and world_id=%s "
            "and comparison_id=any(%s) and receipt->'provider' <> 'null'::jsonb "
            "group by comparison_id",
            (self.workspace_id, self.world_id, list(comparison_ids)),
        ).fetchall()
        return {row["comparison_id"]: Decimal(row["spent"]) for row in rows}

    def append(
        self,
        comparison_id: uuid.UUID,
        run_id: uuid.UUID,
        request: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> None:
        """Append one choice point's request and receipt, in decision order."""
        self.connection.execute(
            "insert into signal_comparison_decision(workspace_id,world_id,comparison_id,run_id,"
            "decision_seq,request_id,signal_id,choice_second,request,request_sha256,receipt,"
            "receipt_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                self.world_id,
                comparison_id,
                run_id,
                receipt["decision_seq"],
                request["request_id"],
                request["subject_id"],
                request["context"]["choice_second"],
                Jsonb(dict(request)),
                request["document_sha256"],
                Jsonb(dict(receipt)),
                receipt["document_sha256"],
            ),
        )

    def stored(self, run_id: uuid.UUID) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """A run's stored requests and receipts, in decision order."""
        rows = self.connection.execute(
            "select request,receipt from signal_comparison_decision where workspace_id=%s "
            "and world_id=%s and run_id=%s order by decision_seq",
            (self.workspace_id, self.world_id, run_id),
        ).fetchall()
        return [(row["request"], row["receipt"]) for row in rows]

    def outcome(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        row = self.connection.execute(
            "select document from signal_comparison_outcome where workspace_id=%s "
            "and world_id=%s and run_id=%s",
            (self.workspace_id, self.world_id, run_id),
        ).fetchone()
        return None if row is None else row["document"]

    def finish(
        self, comparison_id: uuid.UUID, run_id: uuid.UUID, document: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Record a run's one outcome, sealed."""
        stored = sealed({**document, "run_id": str(run_id)})
        self.connection.execute(
            "insert into signal_comparison_outcome(workspace_id,world_id,comparison_id,run_id,"
            "status,document,document_sha256) values(%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                self.world_id,
                comparison_id,
                run_id,
                stored["status"],
                Jsonb(stored),
                stored["document_sha256"],
            ),
        )
        return stored

    # -- what a runner and a replay play ---------------------------------------------------------

    def plan(
        self, comparison_id: uuid.UUID, run_id: uuid.UUID, role: DecisionRole
    ) -> tuple[SignalRunPlan, dict[str, Any]]:
        """The run's plan over the roads its version states now, refused as ``roads_changed``
        where they no longer digest to the roads the comparison recorded."""
        definition = self._definition(comparison_id)["document"]  # type: ignore[index]
        run = self._run(run_id)
        if run["comparison_id"] != comparison_id:
            raise UnknownSignalComparison("run is unavailable")
        roads = self.roads(uuid.UUID(definition["version_id"]))
        if (roads.version_id, roads.sha256) != (
            definition["roads"]["roads_version"],
            definition["roads"]["input_sha256"],
        ):
            raise SignalComparisonRefused(
                "roads_changed", "the version's roads are not the roads the comparison recorded"
            )
        contract = role.contract(definition["contract"]["catalog_versions"])
        if contract.binding() != definition["contract"]:
            raise SignalComparisonRefused("contract_changed", "the role's contract changed")
        arm = definition["arms"][run["arm"]]
        return (
            SignalRunPlan(
                run_id=run_id,
                roads=roads,
                seed=run["seed"],
                group=tuple(definition["group"]),
                decider=arm["decider"],
                provider_config=arm["provider_config"],
                role=role,
                contract=contract,
            ),
            definition,
        )
