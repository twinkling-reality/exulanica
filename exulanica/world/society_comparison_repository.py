"""The records of a comparison: its definition, its runs, their receipts and their outcomes.

A comparison is defined over one world's purposeful society as it stands: the repository reads the
society and the inputs it holds, never a caller's copy of either, freezes the newest input by
sequence and digest, and records a definition naming the window, the arms, the phase and the
seeds it committed to by digest, and everything it is scored and judged under. Runs are reserved
before anything is asked, their receipts are appended as they are paid for, and each run ends in
one outcome.

Nothing here runs a minute or asks a model. :meth:`SocietyComparisonRepository.plan` gives the
runner and the replay the same :class:`~exulanica.world.society_comparison.RunPlan`, with the
stored inputs authorised afresh, so a run whose inputs have since lost their rights is unavailable
rather than replayed from stale geometry. What the records say, as the routes serve them, is
:mod:`exulanica.world.society_comparison_result`. Every statement names the world. A definition
is keyed by the caller's id within its workspace, and a run, a receipt and an outcome by ids
derived from it. A run's seed is read here, for a runner
and a replay, and :meth:`SocietyComparisonRepository.runs` leaves it out.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.world.society import (
    UnavailableSocietyInput,
    UnknownSociety,
    inputs_ahead,
    society_state_sha256,
)
from exulanica.world.society_catalogs import ComparisonCatalogs, load_comparison_catalogs
from exulanica.world.society_comparison import RunPlan
from exulanica.world.society_comparison_result import (
    ComparisonRefused,
    check_definition_body,
    protocol_value,
    scoring_binding,
)
from exulanica.world.society_decision_contract import decision_contract
from exulanica.world.society_engines import society_engine
from exulanica.world.society_repository import SocietyRepository

__all__ = [
    "COMPARISON_PROFILE",
    "ComparisonConflict",
    "ComparisonRefused",
    "SocietyComparisonRepository",
    "UnknownComparison",
    "run_id_for",
    "seed_digest",
]

COMPARISON_PROFILE: Final = "exulanica.society-comparison/v1"
_RUN_NAMESPACE: Final = uuid.UUID("5c1b5d2e-6f0a-4c61-9b7e-2f4f3c8d1a90")


class UnknownComparison(UnknownSociety, LookupError):
    """A comparison or run is unavailable in this workspace and world: answered as an unknown
    society is, so no reader learns whether another workspace holds the id."""


class ComparisonConflict(ValueError):
    """A caller's comparison id already names a different definition, in this world or in another
    world of the workspace, whose rows this world's reads do not see."""


def run_id_for(comparison_id: uuid.UUID, arm: str, seed_digest: str) -> uuid.UUID:
    """One run per arm and seed of a comparison, so reserving it again finds the same run."""
    return uuid.uuid5(_RUN_NAMESPACE, f"{comparison_id}:{arm}:{seed_digest}")


def seed_digest(seed: str) -> str:
    """How a seed is committed: the SHA-256 of its text."""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _sealed(document: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in document.items() if key != "document_sha256"}
    return {**body, "document_sha256": society_state_sha256(body)}


class SocietyComparisonRepository:
    """Append and read comparison records in one workspace and world."""

    def __init__(self, society: SocietyRepository) -> None:
        self.society = society
        self.connection = society.connection
        self.workspace_id = society.workspace_id
        self.world_id = society.world_id

    # -- definitions -------------------------------------------------------------------------

    def define(
        self,
        version_id: uuid.UUID,
        *,
        comparison_id: uuid.UUID,
        body: Mapping[str, Any],
        created_by: uuid.UUID,
        catalogs: ComparisonCatalogs | None = None,
    ) -> dict[str, Any]:
        """Record a comparison over this version's society, frozen at its newest input.

        ``body`` is everything the definition states that the society does not: ``window_ticks``,
        ``phase``, ``seeds`` (digests), ``arms``, ``claim`` and ``preregistration``. The society,
        its population, its newest input and what the comparison is scored under are read here.
        The same id with the same body returns the stored definition; with another body it is a
        conflict.
        """
        catalogs = load_comparison_catalogs() if catalogs is None else catalogs
        check_definition_body(body, catalogs)
        row = self.society._row(version_id)
        if row is None:
            raise UnknownSociety("society is unavailable")
        if not society_engine(row["engine_version"]).comparisons:
            raise ComparisonRefused(
                "engine_takes_no_comparison",
                f"{row['engine_version']} cannot be run by a comparison's arms",
            )
        if row["population_size"] > protocol_value(catalogs, "population_maximum"):
            raise ComparisonRefused(
                "population_over_comparison_bound",
                f"{row['population_size']} people; a comparison runs at most "
                f"{protocol_value(catalogs, 'population_maximum')}",
            )
        latest = self.society._chain(row)
        frozen = self.society._inputs(row, [latest])[latest]
        self.society._authorize(frozen)
        document = _sealed(
            {
                "profile": COMPARISON_PROFILE,
                "world_id": self.world_id,
                "version_id": str(version_id),
                "society_id": str(row["society_id"]),
                "population": int(row["population_size"]),
                "input": {"input_seq": latest, "document_sha256": frozen["document_sha256"]},
                "window_ticks": body["window_ticks"],
                "phase": body["phase"],
                "seeds": list(body["seeds"]),
                "arms": {key: dict(arm) for key, arm in sorted(body["arms"].items())},
                "claim": body["claim"],
                "preregistration": body["preregistration"],
                "contract": decision_contract().binding(),
                "scoring": scoring_binding(catalogs),
            }
        )
        existing = self._definition(comparison_id, missing_ok=True)
        if existing is not None:
            stored = existing["document"]
            if {k: v for k, v in stored.items() if k != "document_sha256"} != {
                k: v for k, v in document.items() if k != "document_sha256"
            }:
                raise ComparisonConflict("the comparison id already names another definition")
            return stored
        try:
            with self.connection.transaction():
                self.connection.execute(
                    "insert into society_comparison(workspace_id,world_id,comparison_id,version_id,"
                    "society_id,input_seq,input_sha256,document,document_sha256,created_by) "
                    "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.workspace_id,
                        self.world_id,
                        comparison_id,
                        version_id,
                        row["society_id"],
                        latest,
                        frozen["document_sha256"],
                        Jsonb(document),
                        document["document_sha256"],
                        created_by,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            # The key is the workspace's, and a definition in another of its worlds is not read
            # above: the id is taken all the same.
            if exc.diag.constraint_name != "society_comparison_pkey":
                raise
            raise ComparisonConflict("the comparison id already names another definition") from exc
        return document

    def _definition(self, comparison_id: uuid.UUID, *, missing_ok: bool = False) -> dict | None:
        row = self.connection.execute(
            "select * from society_comparison where workspace_id=%s and world_id=%s "
            "and comparison_id=%s",
            (self.workspace_id, self.world_id, comparison_id),
        ).fetchone()
        if row is None and not missing_ok:
            raise UnknownComparison("comparison is unavailable")
        return row

    def definition(self, version_id: uuid.UUID, comparison_id: uuid.UUID) -> dict[str, Any]:
        """One comparison of this version, or unavailable."""
        row = self._definition(comparison_id)
        if row is None or row["version_id"] != version_id:
            raise UnknownComparison("comparison is unavailable")
        return row

    def definitions(self, version_id: uuid.UUID) -> list[dict[str, Any]]:
        """This version's comparisons, newest first."""
        return self.connection.execute(
            "select * from society_comparison where workspace_id=%s and world_id=%s "
            "and version_id=%s order by created_at desc, comparison_id",
            (self.workspace_id, self.world_id, version_id),
        ).fetchall()

    # -- runs -------------------------------------------------------------------------------

    def reserve(
        self, comparison_id: uuid.UUID, *, arm: str, seed: str, created_by: uuid.UUID
    ) -> uuid.UUID:
        """The run of ``arm`` on ``seed``, reserved now or found reserved before."""
        digest = seed_digest(seed)
        run_id = run_id_for(comparison_id, arm, digest)
        self.connection.execute(
            "insert into society_comparison_run(workspace_id,world_id,comparison_id,run_id,arm,"
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
            raise ComparisonConflict("the run id already names another run")
        return run_id

    def _run(self, run_id: uuid.UUID) -> dict[str, Any]:
        row = self.connection.execute(
            "select * from society_comparison_run where workspace_id=%s and world_id=%s "
            "and run_id=%s",
            (self.workspace_id, self.world_id, run_id),
        ).fetchone()
        if row is None:
            raise UnknownComparison("run is unavailable")
        return row

    def runs(self, comparison_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every run of a comparison with its outcome, or ``None`` while it has none. The seed
        itself is left out: a reader of runs names seeds by digest."""
        return self.connection.execute(
            "select r.comparison_id,r.run_id,r.arm,r.seed_digest,r.created_at,"
            "o.status,o.document as outcome from society_comparison_run r "
            "left join society_comparison_outcome o "
            "on o.workspace_id=r.workspace_id and o.world_id=r.world_id and o.run_id=r.run_id "
            "where r.workspace_id=%s and r.world_id=%s and r.comparison_id=%s "
            "order by r.seed_digest, r.arm",
            (self.workspace_id, self.world_id, comparison_id),
        ).fetchall()

    def run_counts(self, comparison_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
        """How many runs each comparison reserved, and how many of them completed."""
        rows = self.connection.execute(
            "select r.comparison_id,count(*) as runs,"
            "count(o.run_id) filter (where o.status='completed') as completed "
            "from society_comparison_run r left join society_comparison_outcome o "
            "on o.workspace_id=r.workspace_id and o.world_id=r.world_id and o.run_id=r.run_id "
            "where r.workspace_id=%s and r.world_id=%s and r.comparison_id=any(%s) "
            "group by r.comparison_id",
            (self.workspace_id, self.world_id, list(comparison_ids)),
        ).fetchall()
        return {row["comparison_id"]: (int(row["runs"]), int(row["completed"])) for row in rows}

    def append(
        self,
        comparison_id: uuid.UUID,
        run_id: uuid.UUID,
        requests: Sequence[Mapping[str, Any]],
        receipts: Sequence[Mapping[str, Any]],
    ) -> None:
        """Append one minute's receipts, each with the request it answers, in decision order."""
        for request, receipt in zip(requests, receipts, strict=True):
            self.connection.execute(
                "insert into society_comparison_decision(workspace_id,world_id,comparison_id,"
                "run_id,decision_seq,request_id,subject_id,base_tick,request,request_sha256,"
                "receipt,receipt_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    self.world_id,
                    comparison_id,
                    run_id,
                    receipt["decision_seq"],
                    request["request_id"],
                    request["subject_id"],
                    request["base_tick"],
                    Jsonb(dict(request)),
                    request["document_sha256"],
                    Jsonb(dict(receipt)),
                    receipt["document_sha256"],
                ),
            )

    def stored(self, run_id: uuid.UUID) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """A run's stored requests and receipts, in decision order."""
        rows = self.connection.execute(
            "select request,receipt from society_comparison_decision where workspace_id=%s "
            "and world_id=%s and run_id=%s order by decision_seq",
            (self.workspace_id, self.world_id, run_id),
        ).fetchall()
        return [(row["request"], row["receipt"]) for row in rows]

    def outcome(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        row = self.connection.execute(
            "select document from society_comparison_outcome where workspace_id=%s "
            "and world_id=%s and run_id=%s",
            (self.workspace_id, self.world_id, run_id),
        ).fetchone()
        return None if row is None else row["document"]

    def finish(
        self, comparison_id: uuid.UUID, run_id: uuid.UUID, document: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Record a run's one outcome, sealed."""
        sealed = _sealed({**document, "run_id": str(run_id)})
        self.connection.execute(
            "insert into society_comparison_outcome(workspace_id,world_id,comparison_id,run_id,"
            "status,document,document_sha256) values(%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                self.world_id,
                comparison_id,
                run_id,
                sealed["status"],
                Jsonb(sealed),
                sealed["document_sha256"],
            ),
        )
        return sealed

    # -- what a runner and a replay play ------------------------------------------------------

    def plan(self, comparison_id: uuid.UUID, run_id: uuid.UUID) -> tuple[RunPlan, dict[str, Any]]:
        """The run's plan from its definition and the society's stored inputs, authorised now."""
        definition = self._definition(comparison_id)["document"]  # type: ignore[index]
        run = self._run(run_id)
        if run["comparison_id"] != comparison_id:
            raise UnknownComparison("run is unavailable")
        row = self.society._row(uuid.UUID(definition["version_id"]))
        if row is None or str(row["society_id"]) != definition["society_id"]:
            raise UnknownComparison("the comparison's society is unavailable")
        frozen = int(definition["input"]["input_seq"])
        documents = self.society._inputs(row, range(1, frozen + 1))
        inputs = tuple(documents[sequence] for sequence in range(1, frozen + 1))
        if inputs[-1]["document_sha256"] != definition["input"]["document_sha256"]:
            raise UnavailableSocietyInput("the comparison's frozen input changed")
        # Every input is announced before the first is authorized, which takes the asset read
        # lock, so their stored bytes are all read before it.
        with inputs_ahead(self.connection, inputs):
            for document in inputs:
                self.society._authorize(document)
        contract = decision_contract(definition["contract"]["catalog_versions"])
        if contract.binding() != definition["contract"]:
            raise ComparisonRefused("contract_changed", "the contract's catalogs are not the same")
        arm = definition["arms"][run["arm"]]
        plan = RunPlan(
            run_id=run_id,
            society_id=uuid.UUID(definition["society_id"]),
            seed=run["seed"],
            population=int(definition["population"]),
            inputs=inputs,
            ticks=int(definition["window_ticks"]),
            decider=arm["decider"],
            provider_config=arm["provider_config"],
            contract=contract,
        )
        return plan, definition
