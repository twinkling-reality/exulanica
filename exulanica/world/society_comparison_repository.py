"""The records of a comparison: its definition, its runs, their receipts and their outcomes.

A comparison is defined over one world's purposeful society as it stands: the repository reads the
society and the inputs it holds, never a caller's copy of either, freezes the newest input, or an
earlier stored one the caller names, by sequence and digest, and records a definition naming the
window, the arms, the phase, the seeds it committed to by digest, the group its arms decide for,
who decides for everybody else, and everything it is scored and judged under. The group and
everybody else are checked against the world's own records: every person is one of the society's,
named as its state names them, a group taken from an owner's choice is exactly the people that
choice named, and each other person keeps exactly the model or routine the owner's latest choice
for them names. Runs are reserved before anything is asked, their receipts are appended as they are
paid for, and each run ends in one outcome.

Nothing here runs a minute or asks a model. :meth:`SocietyComparisonRepository.plan` gives the
runner the :class:`~exulanica.world.society_comparison.RunPlan` it plays, with the stored inputs
authorised afresh before anything is asked; the replay reads the same plan
(:meth:`~SocietyComparisonRepository.read_plan`) and authorises its inputs after replaying and
before it answers (:meth:`~SocietyComparisonRepository.authorize_inputs`), so a run whose inputs
lost their rights before or while it was replayed is unavailable rather than drawn from stale
geometry. What the records say, as the routes serve them, is
:mod:`exulanica.world.society_comparison_result`. Every statement names the world. A definition
is keyed by the caller's id within its workspace, and a run, a receipt and an outcome by ids
derived from it. A run's seed is read here, for a runner
and a replay, and :meth:`SocietyComparisonRepository.runs` leaves it out.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.world.decision_roles import DecisionContract, DecisionRole
from exulanica.world.society import (
    UnavailableSocietyInput,
    UnknownSociety,
    inputs_ahead,
    seed_digest,
    society_state_sha256,
)
from exulanica.world.society_catalogs import (
    COMPARISON_SCORE_BY_FAMILY,
    DAY_SCORE_BY_FAMILY,
    PERSON_SCORE_CATALOG,
    ComparisonCatalogs,
    load_comparison_catalogs,
)
from exulanica.world.society_comparison import RunPlan
from exulanica.world.society_comparison_drawing import StoredDrawing
from exulanica.world.society_comparison_reading import WINDOW_NOT_OFFERED, reading_refusal
from exulanica.world.society_comparison_result import (
    DEFINITION_PROFILES,
    ComparisonRefused,
    check_definition_body,
    definition_role,
    definition_version,
    scoring_binding,
)
from exulanica.world.society_engines import society_engine
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_person_label import person_label
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

#: The profile a comparison is defined under: the second, which scores a group.
COMPARISON_PROFILE: Final = DEFINITION_PROFILES[2]
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


def _sealed(document: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in document.items() if key != "document_sha256"}
    return {**body, "document_sha256": society_state_sha256(body)}


def _held_asking(
    body: Mapping[str, Any],
    others: Sequence[Mapping[str, Any]],
    contract: DecisionContract,
    role: DecisionRole,
) -> None:
    """Every model a definition asks, an arm's or a person's outside the group, is asked under the
    terms the definition records: the contract it is defined under with that contract's deadline,
    the prompt the role asks with, one manifest digest across them all, and one mechanism for each
    model, one the contract accepts. A person outside the group asks as the owner's choice it
    names, which :meth:`SocietyComparisonRepository._people` holds; an arm's model is no owner's
    choice."""
    configs = [
        (f"arm {key}", arm["provider_config"], None)
        for key, arm in sorted(body["arms"].items())
        if arm["provider_config"] is not None
    ] + [
        (other["id"], other["provider_config"], other["choice"])
        for other in others
        if other["provider_config"] is not None
    ]
    accepted = {mechanism.value for mechanism in contract.mechanism_order}
    manifests = {config["manifest_sha256"] for _who, config, _choice in configs}
    mechanisms: dict[str, set[str]] = {}
    for who, config, choice in configs:
        mechanisms.setdefault(config["model_id"], set()).add(config["mechanism"])
        if (
            config["contract"] != contract.binding()
            or config["deadline_ms"] != contract.value("decision_deadline_ms")
            or config["prompt_version"] != role.prompt_version
            or config["mechanism"] not in accepted
            or (choice is None) != (config["choice_seq"] is None)
        ):
            raise ComparisonRefused(
                "asking_not_the_definitions", f"{who} is not asked under the definition's terms"
            )
    if len(manifests) > 1 or any(len(found) > 1 for found in mechanisms.values()):
        raise ComparisonRefused(
            "asking_not_the_definitions", "every model is asked under one manifest, one way"
        )
    # One answering per model too: the order it is asked in is part of what the model is here.
    answerings: dict[str, set[str]] = {}
    for held in [*body["arms"].values(), *others]:
        if held["provider_config"] is not None:
            answerings.setdefault(held["provider_config"]["model_id"], set()).add(
                canonical_json(held.get("answering")).decode()
            )
    if any(len(found) > 1 for found in answerings.values()):
        raise ComparisonRefused(
            "asking_not_the_definitions", "every model is asked in one order, wherever it decides"
        )


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
        role: DecisionRole,
        catalogs: ComparisonCatalogs | None = None,
        input_seq: int | None = None,
    ) -> dict[str, Any]:
        """Record a comparison over this version's society, frozen at its newest input or at the
        earlier stored input ``input_seq`` names, asking ``role``, whose contract the definition
        records and so names it by. Every run of it starts at the society's genesis and consumes
        the inputs up to the frozen one; it is not a branch of the live society at any tick.

        ``body`` is everything the definition states that the society does not: ``window_ticks``,
        ``phase``, ``seeds`` (digests), ``group`` (the people the arms decide for, or None for
        everybody, and where they came from), ``others`` (who decides for everybody else, each by
        the owner's choice it keeps), ``arms``, ``claim`` and ``preregistration``. The society, its
        population and people's names, its newest input and what the comparison is scored under
        are read here, and the group and everybody else are held to the world's records
        (:meth:`_people`). The same id with the same body returns the stored definition; with
        another body it is a conflict.
        """
        row = self.society._row(version_id)
        if row is None:
            raise UnknownSociety("society is unavailable")
        catalogs = load_comparison_catalogs() if catalogs is None else catalogs
        family = society_engine(row["engine_version"]).state_family
        required_score = COMPARISON_SCORE_BY_FAMILY.get(family)
        if required_score == 4 and catalogs.versions[PERSON_SCORE_CATALOG] == 3:
            scored = load_comparison_catalogs(
                versions={**catalogs.versions, PERSON_SCORE_CATALOG: required_score}
            )
            catalogs = replace(
                catalogs, score=scored.score, versions=scored.versions, sha256=scored.sha256
            )
        day_score = DAY_SCORE_BY_FAMILY.get(family)
        if int(catalogs.versions[PERSON_SCORE_CATALOG]) in DAY_SCORE_BY_FAMILY.values() and (
            day_score != int(catalogs.versions[PERSON_SCORE_CATALOG])
        ):
            raise ComparisonRefused(
                WINDOW_NOT_OFFERED, f"a {family} society keeps no day to compare over"
            )
        check_definition_body(body, catalogs)
        if not society_engine(row["engine_version"]).comparisons:
            raise ComparisonRefused(
                "engine_takes_no_comparison",
                f"{row['engine_version']} cannot be run by a comparison's arms",
            )
        if not role.hosted_by(row["engine_version"]):
            raise ComparisonRefused(
                "role_not_hosted", f"{row['engine_version']} hosts no {role.key} decisions"
            )
        refused = reading_refusal(catalogs, int(row["population_size"]), body)
        if refused is not None:
            raise ComparisonRefused(*refused)
        latest = self.society._chain(row)
        chosen = latest if input_seq is None else input_seq
        if not 1 <= chosen <= latest:
            raise ComparisonRefused(
                "input_not_in_society", f"this society holds inputs 1 to {latest}"
            )
        frozen = self.society._inputs(row, [chosen])[chosen]
        # One input alone: its own stored bytes are read before the lock its authorization takes.
        self.society._authorize(frozen)
        contract = role.contract()
        group, others = self._people(version_id, row, body, role)
        _held_asking(body, others, contract, role)
        document = _sealed(
            {
                "profile": COMPARISON_PROFILE,
                "world_id": self.world_id,
                "version_id": str(version_id),
                "society_id": str(row["society_id"]),
                "population": int(row["population_size"]),
                "input": {"input_seq": chosen, "document_sha256": frozen["document_sha256"]},
                "window_ticks": body["window_ticks"],
                "phase": body["phase"],
                "seeds": list(body["seeds"]),
                "group": group,
                "others": others,
                "arms": {key: dict(arm) for key, arm in sorted(body["arms"].items())},
                "claim": body["claim"],
                "preregistration": body["preregistration"],
                "contract": contract.binding(),
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
                        chosen,
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

    def _people(
        self,
        version_id: uuid.UUID,
        row: Mapping[str, Any],
        body: Mapping[str, Any],
        role: DecisionRole,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The group and everybody else as a definition records them, held to the world's
        records: each person one of the society's, named as its state names them; a group from an
        owner's choice exactly that choice's people; and each other person's decider exactly what
        the owner's latest choice for them names, or their routine where none does."""
        names = {person["id"]: person_label(person) for person in row["state"]["inhabitants"]}
        group, source = body["group"]["people"], dict(body["group"]["source"])
        people = sorted(names) if group is None else list(group)
        if not set(people) <= set(names):
            raise ComparisonRefused("group_person_unknown", "the group names somebody not here")
        choices = SocietyModelChoiceRepository(
            self.connection, self.workspace_id, world_id=self.world_id
        ).history(version_id, role)
        if source["kind"] == "owner_choice":
            named = next(
                (choice for choice in choices if choice["choice_seq"] == source["choice_seq"]),
                None,
            )
            if (
                named is None
                or named["document_sha256"] != source["document_sha256"]
                or sorted(named["people"]) != people
            ):
                raise ComparisonRefused(
                    "group_not_the_choice", "the group is exactly the people the choice named"
                )
        latest: dict[str, Mapping[str, Any]] = {}
        for recorded in choices:
            for subject in recorded["people"]:
                latest[subject] = recorded
        outside = sorted(set(names) - set(people))
        stated = {other["id"]: other for other in body["others"]}
        if sorted(stated) != outside:
            raise ComparisonRefused("others", "everybody outside the group is named, and only they")
        others = []
        for subject in outside:
            other = stated[subject]
            choice = latest.get(subject)
            model = None if choice is None else choice["model"]
            kept = (
                None
                if choice is None
                else {
                    "choice_seq": choice["choice_seq"],
                    "document_sha256": choice["document_sha256"],
                }
            )
            decider = other["decider"]
            config = other["provider_config"]
            if (
                other["choice"] != kept
                or (
                    {"kind": "routine"}
                    if model is None
                    else {
                        "kind": "model",
                        "provider": model["provider"],
                        "model_id": model["model_id"],
                    }
                )
                != dict(decider)
                or (config is not None and config["choice_seq"] != kept["choice_seq"])  # type: ignore[index]
            ):
                raise ComparisonRefused(
                    "others_not_the_owners_choice",
                    f"{subject} keeps what the owner's latest choice for them names",
                )
            others.append({"name": names[subject], **dict(other)})
        return {
            "people": [{"id": subject, "name": names[subject]} for subject in people],
            "source": source,
        }, others

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

    def run_counts(
        self, comparison_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, int, int]]:
        """How many runs each comparison reserved, how many of them completed, and how many
        finished, completed or failed."""
        rows = self.connection.execute(
            "select r.comparison_id,count(*) as runs,"
            "count(o.run_id) filter (where o.status='completed') as completed,"
            "count(o.run_id) as finished "
            "from society_comparison_run r left join society_comparison_outcome o "
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
        """A comparison's runs with no outcome yet, by seed digest and arm, each saying whether it
        asked anything: one that did was stopped part way, and cannot be played again."""
        return self.connection.execute(
            "select r.run_id,r.arm,r.seed_digest,exists(select 1 from society_comparison_decision "
            "d where d.workspace_id=r.workspace_id and d.world_id=r.world_id "
            "and d.run_id=r.run_id) as asked from society_comparison_run r "
            "where r.workspace_id=%s and r.world_id=%s and r.comparison_id=%s "
            "and not exists(select 1 from society_comparison_outcome o where "
            "o.workspace_id=r.workspace_id and o.world_id=r.world_id and o.run_id=r.run_id) "
            "order by r.seed_digest, r.arm",
            (self.workspace_id, self.world_id, comparison_id),
        ).fetchall()

    def spending(self, comparison_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
        """What each comparison's asks cost, as its receipts recorded each call: a comparison that
        asked nothing is absent."""
        rows = self.connection.execute(
            "select comparison_id,sum((receipt->'provider'->>'cost_usd')::numeric) as spent "
            "from society_comparison_decision where workspace_id=%s and world_id=%s "
            "and comparison_id=any(%s) and receipt->'provider' <> 'null'::jsonb "
            "group by comparison_id",
            (self.workspace_id, self.world_id, list(comparison_ids)),
        ).fetchall()
        return {row["comparison_id"]: Decimal(row["spent"]) for row in rows}

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

    # -- a day's run, hour by hour ------------------------------------------------------------

    def seal_hour(
        self,
        comparison_id: uuid.UUID,
        run_id: uuid.UUID,
        document: Mapping[str, Any],
        end_state: bytes,
    ) -> None:
        """Append one sealed hour of a day's run (``exulanica.society-comparison-hour/v1``), with
        the canonical bytes of the state it ended in. Migration 0136 holds it to its run, its order
        and the receipts recorded since the hour before it, and computes the state's digest."""
        receipts = document["receipts"]
        self.connection.execute(
            "insert into society_comparison_hour(workspace_id,world_id,comparison_id,run_id,hour,"
            "decision_seq_end,document,document_sha256,end_state,end_state_sha256) "
            "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                self.world_id,
                comparison_id,
                run_id,
                document["hour"],
                int(receipts["first_sequence"]) + int(receipts["count"]),
                Jsonb(dict(document)),
                document["document_sha256"],
                end_state,
                document["minutes"]["state_sha256"][-1],
            ),
        )

    def hours(self, run_id: uuid.UUID) -> list[dict[str, Any]]:
        """A run's sealed hours in order, each its hour, the decision sequence it ends at and its
        document; the states they ended in are read one at a time (:meth:`hour_state`)."""
        return self.connection.execute(
            "select hour,decision_seq_end,document from society_comparison_hour "
            "where workspace_id=%s and world_id=%s and run_id=%s order by hour",
            (self.workspace_id, self.world_id, run_id),
        ).fetchall()

    def hour_state(self, run_id: uuid.UUID, hour: int) -> tuple[bytes, str] | None:
        """The canonical bytes of the state a run's sealed ``hour`` ended in, with their digest, or
        None where it has not sealed that hour."""
        row = self.connection.execute(
            "select end_state,end_state_sha256 from society_comparison_hour "
            "where workspace_id=%s and world_id=%s and run_id=%s and hour=%s",
            (self.workspace_id, self.world_id, run_id, hour),
        ).fetchone()
        return None if row is None else (bytes(row["end_state"]), str(row["end_state_sha256"]))

    def stored_between(
        self, run_id: uuid.UUID, after: int, through: int | None = None
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """A run's stored requests and receipts after decision sequence ``after``, through
        ``through`` where it is named, in decision order."""
        rows = self.connection.execute(
            "select request,receipt from society_comparison_decision where workspace_id=%s "
            "and world_id=%s and run_id=%s and decision_seq>%s "
            "and (%s::bigint is null or decision_seq<=%s) order by decision_seq",
            (self.workspace_id, self.world_id, run_id, after, through, through),
        ).fetchall()
        return [(row["request"], row["receipt"]) for row in rows]

    def receipt_digests(self, run_id: uuid.UUID) -> list[str]:
        """Every receipt a run recorded, by digest, in decision order."""
        rows = self.connection.execute(
            "select receipt_sha256 from society_comparison_decision where workspace_id=%s "
            "and world_id=%s and run_id=%s order by decision_seq",
            (self.workspace_id, self.world_id, run_id),
        ).fetchall()
        return [str(row["receipt_sha256"]) for row in rows]

    def comparison_hours_sealed(self, comparison_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        """How many hours the runs of each of ``comparison_ids`` sealed together, by comparison
        id: a comparison none of whose runs sealed an hour is absent."""
        rows = self.connection.execute(
            "select comparison_id,count(*) as hours from society_comparison_hour "
            "where workspace_id=%s and world_id=%s and comparison_id=any(%s) "
            "group by comparison_id",
            (self.workspace_id, self.world_id, list(comparison_ids)),
        ).fetchall()
        return {row["comparison_id"]: int(row["hours"]) for row in rows}

    def hours_sealed(self, comparison_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        """How many hours each run of ``comparison_ids`` sealed, by run id: a run that sealed none
        is absent."""
        rows = self.connection.execute(
            "select run_id,count(*) as hours from society_comparison_hour where workspace_id=%s "
            "and world_id=%s and comparison_id=any(%s) group by run_id",
            (self.workspace_id, self.world_id, list(comparison_ids)),
        ).fetchall()
        return {row["run_id"]: int(row["hours"]) for row in rows}

    # -- a completed run's stored drawing ------------------------------------------------------

    def store_drawing(
        self, comparison_id: uuid.UUID, run_id: uuid.UUID, drawing: str, stored: StoredDrawing
    ) -> None:
        """Append a completed run's verified drawing under the digest of the code that drew it; a
        drawing already stored under that digest is kept as it is."""
        self.connection.execute(
            "insert into society_comparison_replay(workspace_id,world_id,comparison_id,run_id,"
            "drawing_sha256,document_sha256,document_bytes,document_gzip) "
            "values(%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (workspace_id,run_id,drawing_sha256) do nothing",
            (
                self.workspace_id,
                self.world_id,
                comparison_id,
                run_id,
                drawing,
                stored.document_sha256,
                stored.document_bytes,
                stored.document_gzip,
            ),
        )

    def drawing(self, run_id: uuid.UUID, drawing: str) -> StoredDrawing | None:
        """The run's drawing stored under the digest ``drawing``, or None where there is none."""
        row = self.connection.execute(
            "select document_gzip,document_sha256,document_bytes from society_comparison_replay "
            "where workspace_id=%s and world_id=%s and run_id=%s and drawing_sha256=%s",
            (self.workspace_id, self.world_id, run_id, drawing),
        ).fetchone()
        if row is None:
            return None
        return StoredDrawing(
            bytes(row["document_gzip"]), row["document_sha256"], row["document_bytes"]
        )

    # -- what a runner and a replay play ------------------------------------------------------

    def plan(self, comparison_id: uuid.UUID, run_id: uuid.UUID) -> tuple[RunPlan, dict[str, Any]]:
        """The run's plan from its definition and the society's stored inputs, authorised now,
        before anything is played or asked, and before anything the definition records is
        refused, so a run whose inputs lost their rights is unavailable whatever else it meets."""
        definition, run, inputs = self._frozen_inputs(comparison_id, run_id)
        self.authorize_inputs(inputs)
        return self._run_plan(run_id, definition, run, inputs), definition

    def read_plan(
        self, comparison_id: uuid.UUID, run_id: uuid.UUID
    ) -> tuple[RunPlan, dict[str, Any]]:
        """The run's plan from its definition and the society's stored inputs, not yet authorised:
        for a reader that authorises them with :meth:`authorize_inputs` after its own work and
        before it answers anything drawn from them, as the run route does after a replay. A plan
        the definition's records refuse (:class:`ComparisonRefused`) is refused only after the
        inputs' rights are asked, as :meth:`plan` orders them, so a withdrawn right is answered
        first."""
        definition, run, inputs = self._frozen_inputs(comparison_id, run_id)
        try:
            return self._run_plan(run_id, definition, run, inputs), definition
        except ComparisonRefused:
            self.authorize_inputs(inputs)
            raise

    def navigation_profile(self, row: Mapping[str, Any]) -> str | None:
        """The kind of ground a society stands on: the navigation profile of its newest input, or
        None for a society whose engine takes no inputs, which stands on no ground a measurement
        names. Read, never authorised: only the profile is used, which the input's composition
        profile fixes whether or not the input is available."""
        if not society_engine(str(row["engine_version"])).takes_inputs:
            return None
        latest = self.society._chain(dict(row))
        document = self.society._inputs(dict(row), [latest])[latest]
        return str(document["navigation"]["profile"])

    def _frozen_inputs(
        self, comparison_id: uuid.UUID, run_id: uuid.UUID
    ) -> tuple[dict[str, Any], dict[str, Any], tuple[dict[str, Any], ...]]:
        """The run's definition, its row and the society's inputs its definition froze, read and
        held to the frozen input's digest, not authorised."""
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
        return definition, run, inputs

    def _run_plan(
        self,
        run_id: uuid.UUID,
        definition: dict[str, Any],
        run: dict[str, Any],
        inputs: tuple[dict[str, Any], ...],
    ) -> RunPlan:
        """The plan the definition records for the run over ``inputs``, or the refusal of what it
        records (its role, its contract's catalogs), by name."""
        role = definition_role(definition)
        contract = role.contract(definition["contract"]["catalog_versions"])
        if contract.binding() != definition["contract"]:
            raise ComparisonRefused("contract_changed", "the contract's catalogs are not the same")
        arm = definition["arms"][run["arm"]]
        group, others = None, {}
        if definition_version(definition) == 2:
            # A group of everybody is everybody the run holds, as a first-version run's is.
            if definition["group"]["source"]["kind"] != "everyone":
                group = frozenset(person["id"] for person in definition["group"]["people"])
            others = {
                other["id"]: {
                    "decider": other["decider"],
                    "provider_config": other["provider_config"],
                }
                for other in definition["others"]
            }
        return RunPlan(
            run_id=run_id,
            society_id=uuid.UUID(definition["society_id"]),
            seed=run["seed"],
            population=int(definition["population"]),
            inputs=inputs,
            ticks=int(definition["window_ticks"]),
            decider=arm["decider"],
            provider_config=arm["provider_config"],
            contract=contract,
            group=group,
            others=others,
            # A definition is bound to this society by society_id and version_id. The engine is
            # read from that stored society, so historical v2 definitions keep v2 semantics.
            engine_profile=str(
                self.society._row(uuid.UUID(definition["version_id"]))["engine_version"]
            ),
        )

    def authorize_inputs(self, inputs: Sequence[dict[str, Any]]) -> None:
        """Authorise a run's inputs now, each through the society's authorizer
        (:class:`~exulanica.world.society.UnavailableSocietyInput` when one has lost its rights).
        Every input is announced before the first is authorized, which takes the asset read lock,
        so their stored bytes are all read before it."""
        with inputs_ahead(self.connection, inputs):
            for document in inputs:
                self.society._authorize(document)
