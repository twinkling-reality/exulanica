"""PostgreSQL records for controlled living-v4 experiments and their failure boundaries."""

from __future__ import annotations

import uuid
from copy import deepcopy

import pytest
from exulanica.api.society_experiment_runner import SocietyExperimentRunner
from exulanica.db.roles import provision_runtime_role
from exulanica.selection.validation import Session
from exulanica.world import society_experiments as experiments
from exulanica.world.assets import reviewed_assets
from exulanica.world.society import UnavailableSocietyInput, society_state_sha256
from exulanica.world.society_experiment_repository import (
    ExperimentConflict,
    ExperimentResourceLimit,
    SocietyExperimentRepository,
    UnknownExperiment,
)
from exulanica.world.society_living import LivingPlace, current_routine, initial_living_society
from exulanica.world.society_place import place_from_society_input
from exulanica.world.society_planner import input_sha256
from exulanica.world.society_repository import SocietyRepository
from psycopg.types.json import Jsonb

import test_society_experiments as core_helpers
import test_world_objects_api as object_helpers
from conftest import scratch_role_database
from society_living_fixtures import grid_input

objects_api = object_helpers.objects_api
pytestmark = pytest.mark.postgres

TARGET_ID = "authored:rest-experiment:rest"
OBJECT_ID = "object:rest-experiment"
RLS_ROLE = "exulanica_experiment_suite"
RUNNER_ROLE = "exulanica_experiment_runner_suite"


def _seal_input(document):
    document["document_sha256"] = input_sha256(document)
    return document


def _reseal(document):
    document["document_sha256"] = society_state_sha256(
        {key: value for key, value in document.items() if key != "document_sha256"}
    )
    return document


def _treatment(baseline):
    document = deepcopy(baseline)
    document["input_seq"] += 1
    document["authored_state"] = {
        "edit_seq": baseline["authored_state"]["edit_seq"] + 1,
        "delta_sha256": "e" * 64,
    }
    target = {
        "target_id": TARGET_ID,
        "subject_id": "authored:rest-experiment",
        "node_id": "walk:03:02",
        "affordance": "rest",
        "duration_ticks": 3,
        "origin": "authored",
        "object_id": OBJECT_ID,
        "version_id": document["version_id"],
        "enabled": True,
    }
    document["targets"].append(target)
    document["targets"].sort(key=lambda row: row["target_id"])
    plate = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.marker-plate")
    document["dependency_refs"].extend(
        [
            {
                "kind": "authored_object",
                "identity": f"{document['version_id']}:{OBJECT_ID}",
                "sha256": society_state_sha256(target),
            },
            {
                "kind": "reviewed_asset",
                "identity": plate.asset_key,
                "sha256": plate.content_sha256,
            },
        ]
    )
    document["dependency_refs"].sort(
        key=lambda row: (row["kind"], row["identity"], row["sha256"])
    )
    return _seal_input(document)


@pytest.fixture
def experiment_case(objects_api, repository, ingest_spine):
    connection = repository.connection
    workspace = repository.workspace_id
    version = objects_api.version("Experiment authority fixture")
    version_id = uuid.UUID(version["version_id"])
    place_id = uuid.uuid4()
    connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)", (workspace, place_id)
    )
    baseline = grid_input(columns=4, rows=4, version_id=version_id)
    baseline["authored_state"] = {
        "edit_seq": version["edit_seq"],
        "delta_sha256": version["state_sha256"],
    }
    _seal_input(baseline)
    rights = {"available": True}

    def authorize(document):
        if not rights["available"] and document["availability"] == "available":
            raise UnavailableSocietyInput("fixture source authorization withdrawn")

    societies = SocietyRepository(
        connection, workspace, world_id=version["world_id"], input_authorizer=authorize
    )
    created = societies.create(
        version_id,
        place_id=place_id,
        region_id="region-a",
        seed="7a" * 32,
        actor=objects_api.actor,
        profile="exulanica-society/v4",
        initial_input=baseline,
    )
    treatment = _treatment(baseline)
    connection.execute(
        "update world_alternate_version set state_sha256=%s,edit_seq=%s "
        "where workspace_id=%s and version_id=%s",
        (
            treatment["authored_state"]["delta_sha256"],
            treatment["authored_state"]["edit_seq"],
            workspace,
            version_id,
        ),
    )
    societies.record_input(version_id, treatment)
    definition = experiments.freeze_rest_amenity_definition(
        baseline,
        treatment,
        target_id=TARGET_ID,
        warmup_ticks=2,
        followup_ticks=3,
        population=3,
    )
    repo = SocietyExperimentRepository(connection, workspace, input_authorizer=authorize)
    return {
        "connection": connection,
        "objects_api": objects_api,
        "workspace": workspace,
        "actor": objects_api.actor,
        "source_society_id": created["society_id"],
        "world_id": version["world_id"],
        "version_id": version_id,
        "baseline": baseline,
        "treatment": treatment,
        "definition": definition,
        "repo": repo,
        "rights": rights,
        "open_another": ingest_spine[1],
    }


def _prepare(case, *, definition=None):
    repo = case["repo"]
    definition = case["definition"] if definition is None else definition
    experiment_id, attempt_id = uuid.uuid4(), uuid.uuid4()
    repo.create_definition(
        experiment_id,
        case["source_society_id"],
        definition,
        actor=case["actor"],
    )
    repo.start_attempt(
        experiment_id, attempt_id, experiments.DEVELOPMENT_SEEDS[0], actor=case["actor"]
    )
    checkpoint = experiments.prepare_checkpoint(
        definition, experiments.DEVELOPMENT_SEEDS[0], case["baseline"]
    )
    repo.save_checkpoint(attempt_id, checkpoint)
    return experiment_id, attempt_id, checkpoint


class _FixtureRuntime:
    def __init__(self, case):
        self.case = case

    def authorize(self, _connection, session, document):
        assert session.workspace_id == self.case["workspace"]
        if not self.case["rights"]["available"] and document["availability"] == "available":
            raise UnavailableSocietyInput("fixture source authorization withdrawn")


def _runner(case, spine_schema, authorize_execution):
    provision_runtime_role(case["connection"], role=RUNNER_ROLE)
    database = scratch_role_database(spine_schema[1], RUNNER_ROLE)
    session = Session(workspace_id=case["workspace"], actor=case["actor"])
    return (
        SocietyExperimentRunner(
            database,
            runtime=_FixtureRuntime(case),
            authorize_execution=authorize_execution,
        ),
        session,
    )


def _reserve(case, seed_index=0):
    experiment_id, attempt_id = uuid.uuid4(), uuid.uuid4()
    case["repo"].create_definition(
        experiment_id,
        case["source_society_id"],
        case["definition"],
        actor=case["actor"],
    )
    case["repo"].start_attempt(
        experiment_id,
        attempt_id,
        experiments.DEVELOPMENT_SEEDS[seed_index],
        actor=case["actor"],
    )
    return experiment_id, attempt_id


def test_completed_record_reopens_replays_and_does_not_change_live_society(experiment_case):
    case = experiment_case
    before = case["connection"].execute(
        "select current_tick,state_sha256 from world_society where workspace_id=%s "
        "and society_id=%s",
        (case["workspace"], case["source_society_id"]),
    ).fetchone()
    experiment_id, attempt_id, checkpoint = _prepare(case)
    result, evidence = experiments.execute_pair(
        case["definition"],
        checkpoint,
        case["baseline"],
        case["treatment"],
    )
    assert evidence is not None
    completed = case["repo"].complete_attempt(attempt_id, evidence, result)
    assert completed["status"] == "completed"
    # Exact retry is idempotent; a different terminal fact is a conflict.
    assert case["repo"].complete_attempt(attempt_id, evidence, result)["status"] == "completed"
    with pytest.raises(ExperimentConflict):
        case["repo"].fail_attempt(
            attempt_id, code="operator_aborted", detail="conflicts with completion"
        )

    another = case["open_another"]()
    reopened = SocietyExperimentRepository(
        another.connection, case["workspace"], input_authorizer=lambda _document: None
    )
    verified = reopened.verify_attempt(attempt_id)
    assert verified["experiment_id"] == experiment_id
    assert verified["checkpoint"]["document_sha256"] == checkpoint["document_sha256"]
    assert verified["outcome"]["evidence_sha256"] == evidence["document_sha256"]
    assert verified["outcome"]["result_sha256"] == result["document_sha256"]
    after = case["connection"].execute(
        "select current_tick,state_sha256 from world_society where workspace_id=%s "
        "and society_id=%s",
        (case["workspace"], case["source_society_id"]),
    ).fetchone()
    assert after == before


def test_local_runner_completes_reserved_attempt_and_terminal_retry_is_observational(
    experiment_case, spine_schema
):
    case = experiment_case
    experiment_id, attempt_id = _reserve(case)
    calls = []

    def authorize_execution(connection, session, reservation):
        assert session == Session(workspace_id=case["workspace"], actor=case["actor"])
        assert reservation["created_by"] == case["actor"]  # attribution, not the grant
        calls.append((reservation["attempt_id"], connection.info.transaction_status.name))

    runner, session = _runner(case, spine_schema, authorize_execution)
    before = case["connection"].execute(
        "select current_tick,state_sha256 from world_society where workspace_id=%s "
        "and society_id=%s",
        (case["workspace"], case["source_society_id"]),
    ).fetchone()

    receipt = runner.run_reserved(session, attempt_id)
    assert receipt.status == "completed"
    assert receipt.experiment_id == experiment_id
    assert receipt.checkpoint_sha256 is not None
    assert receipt.result_sha256 is not None
    assert receipt.failure_sha256 is None
    assert runner.run_reserved(session, attempt_id) == receipt
    assert len(calls) >= 4
    assert {status for _attempt_id, status in calls} == {"IDLE", "INTRANS"}
    summary = case["repo"].attempt_summary(
        case["version_id"], experiment_id, attempt_id, world_id=case["world_id"]
    )
    assert summary["outcome"]["result_sha256"] == receipt.result_sha256
    after = case["connection"].execute(
        "select current_tick,state_sha256 from world_society where workspace_id=%s "
        "and society_id=%s",
        (case["workspace"], case["source_society_id"]),
    ).fetchone()
    assert after == before


def test_local_runner_rechecks_execution_authority_before_checkpoint_append(
    experiment_case, spine_schema, monkeypatch
):
    case = experiment_case
    _experiment_id, attempt_id = _reserve(case, seed_index=1)
    permission = {"allowed": True}

    def authorize_execution(_connection, _session, _reservation):
        if not permission["allowed"]:
            raise UnavailableSocietyInput("fixture execution permission withdrawn")

    runner, session = _runner(case, spine_schema, authorize_execution)
    prepare = experiments.prepare_checkpoint
    calls = 0

    def revoke_after_prepare(*args, **kwargs):
        nonlocal calls
        checkpoint = prepare(*args, **kwargs)
        calls += 1
        if calls == 1:
            permission["allowed"] = False
        return checkpoint

    monkeypatch.setattr(experiments, "prepare_checkpoint", revoke_after_prepare)
    with pytest.raises(UnavailableSocietyInput, match="execution permission withdrawn"):
        runner.run_reserved(session, attempt_id)
    counts = case["connection"].execute(
        "select (select count(*) from society_experiment_checkpoint where workspace_id=%s "
        "and attempt_id=%s) as checkpoints,(select count(*) from society_experiment_outcome "
        "where workspace_id=%s and attempt_id=%s) as outcomes",
        (case["workspace"], attempt_id, case["workspace"], attempt_id),
    ).fetchone()
    assert counts == {"checkpoints": 0, "outcomes": 0}

    permission["allowed"] = True
    assert runner.run_reserved(session, attempt_id).status == "completed"


def test_local_runner_refuses_held_out_reservation_before_computation_or_abort(
    experiment_case, spine_schema, monkeypatch
):
    case = experiment_case
    experiment_id = uuid.uuid4()
    case["repo"].create_definition(
        experiment_id,
        case["source_society_id"],
        case["definition"],
        actor=case["actor"],
    )
    attempt_id = uuid.uuid4()
    case["connection"].execute(
        "insert into society_experiment_attempt(workspace_id,attempt_id,experiment_id,phase,"
        "seed_sha256,created_by) values(%s,%s,%s,'held_out',%s,%s)",
        (
            case["workspace"],
            attempt_id,
            experiment_id,
            experiments.HELD_OUT_SEEDS[0],
            case["actor"],
        ),
    )
    runner, session = _runner(case, spine_schema, lambda *_args: None)
    monkeypatch.setattr(
        experiments,
        "prepare_checkpoint",
        lambda *_args, **_kwargs: pytest.fail("held-out checkpoint preparation started"),
    )
    monkeypatch.setattr(
        experiments,
        "execute_pair",
        lambda *_args, **_kwargs: pytest.fail("held-out arm execution started"),
    )

    with pytest.raises(experiments.ExperimentIntegrityError, match="development attempts only"):
        runner.run_reserved(session, attempt_id)
    with pytest.raises(experiments.ExperimentIntegrityError, match="development attempts only"):
        runner.abort_reserved(session, attempt_id, detail="must not terminalize held-out work")
    counts = (
        case["connection"]
        .execute(
            "select (select count(*) from society_experiment_checkpoint where workspace_id=%s "
            "and attempt_id=%s) as checkpoints,(select count(*) from society_experiment_outcome "
            "where workspace_id=%s and attempt_id=%s) as outcomes",
            (case["workspace"], attempt_id, case["workspace"], attempt_id),
        )
        .fetchone()
    )
    assert counts == {"checkpoints": 0, "outcomes": 0}


def test_local_runner_explicit_abort_is_terminal_and_idempotent(
    experiment_case, spine_schema
):
    case = experiment_case
    _experiment_id, attempt_id = _reserve(case, seed_index=5)
    runner, session = _runner(case, spine_schema, lambda *_args: None)

    receipt = runner.abort_reserved(
        session, attempt_id, detail="operator stopped the bounded local run"
    )
    assert receipt.status == "failed"
    assert receipt.checkpoint_sha256 is None
    assert runner.abort_reserved(
        session, attempt_id, detail="operator stopped the bounded local run"
    ) == receipt
    assert runner.run_reserved(session, attempt_id) == receipt


def test_local_runner_preserves_checkpoint_when_source_authority_revokes_before_completion(
    experiment_case, spine_schema, monkeypatch
):
    case = experiment_case
    _experiment_id, attempt_id = _reserve(case, seed_index=2)
    runner, session = _runner(case, spine_schema, lambda *_args: None)
    execute = experiments.execute_pair
    calls = 0

    def revoke_after_execution(*args, **kwargs):
        nonlocal calls
        result = execute(*args, **kwargs)
        calls += 1
        if calls == 1:
            case["rights"]["available"] = False
        return result

    monkeypatch.setattr(experiments, "execute_pair", revoke_after_execution)
    with pytest.raises(UnavailableSocietyInput, match="source authorization withdrawn"):
        runner.run_reserved(session, attempt_id)
    counts = case["connection"].execute(
        "select (select count(*) from society_experiment_checkpoint where workspace_id=%s "
        "and attempt_id=%s) as checkpoints,(select count(*) from society_experiment_outcome "
        "where workspace_id=%s and attempt_id=%s) as outcomes",
        (case["workspace"], attempt_id, case["workspace"], attempt_id),
    ).fetchone()
    assert counts == {"checkpoints": 1, "outcomes": 0}

    case["rights"]["available"] = True
    assert runner.run_reserved(session, attempt_id).status == "completed"
    assert calls == 2


def test_local_runner_rechecks_execution_authority_after_result_replay_before_append(
    experiment_case, spine_schema, monkeypatch
):
    case = experiment_case
    _experiment_id, attempt_id = _reserve(case, seed_index=6)
    permission = {"allowed": True}

    def authorize_execution(_connection, _session, _reservation):
        if not permission["allowed"]:
            raise UnavailableSocietyInput("fixture execution permission withdrawn")

    runner, session = _runner(case, spine_schema, authorize_execution)
    verify = experiments.verify_pair_result
    calls = 0

    def revoke_after_result_replay(*args, **kwargs):
        nonlocal calls
        verify(*args, **kwargs)
        calls += 1
        if calls == 1:
            permission["allowed"] = False

    monkeypatch.setattr(experiments, "verify_pair_result", revoke_after_result_replay)
    with pytest.raises(UnavailableSocietyInput, match="execution permission withdrawn"):
        runner.run_reserved(session, attempt_id)
    counts = (
        case["connection"]
        .execute(
            "select (select count(*) from society_experiment_checkpoint where workspace_id=%s "
            "and attempt_id=%s) as checkpoints,(select count(*) from society_experiment_outcome "
            "where workspace_id=%s and attempt_id=%s) as outcomes",
            (case["workspace"], attempt_id, case["workspace"], attempt_id),
        )
        .fetchone()
    )
    assert counts == {"checkpoints": 1, "outcomes": 0}

    permission["allowed"] = True
    assert runner.run_reserved(session, attempt_id).status == "completed"
    assert calls == 2


def test_local_runner_observes_concurrent_terminal_failure_after_duplicate_computation(
    experiment_case, spine_schema, monkeypatch
):
    case = experiment_case
    _experiment_id, attempt_id = _reserve(case, seed_index=3)
    runner, session = _runner(case, spine_schema, lambda *_args: None)
    execute = experiments.execute_pair

    def terminate_after_execution(*args, **kwargs):
        result = execute(*args, **kwargs)
        case["repo"].fail_attempt(
            attempt_id,
            code="operator_aborted",
            detail="concurrent terminal fixture",
        )
        return result

    monkeypatch.setattr(experiments, "execute_pair", terminate_after_execution)
    receipt = runner.run_reserved(session, attempt_id)
    assert receipt.status == "failed"
    assert receipt.result_sha256 is None
    assert receipt.failure_sha256 is not None
    assert (
        case["connection"].execute(
            "select count(*) as n from society_experiment_outcome where workspace_id=%s "
            "and attempt_id=%s",
            (case["workspace"], attempt_id),
        ).fetchone()["n"]
        == 1
    )


def test_local_runner_maps_actual_evidence_free_invalid_pair_to_terminal_failure(
    experiment_case, spine_schema, monkeypatch
):
    case = experiment_case
    experiment_id, attempt_id = _reserve(case, seed_index=4)
    runner, session = _runner(case, spine_schema, lambda *_args: None)

    def execute_invalid_pair(*_args, **_kwargs):
        baseline = grid_input(columns=6, rows=4)
        isolated = "walk:05:03"
        baseline["navigation"]["edges"] = [
            row
            for row in baseline["navigation"]["edges"]
            if isolated not in (row["from_node_id"], row["to_node_id"])
        ]
        _seal_input(baseline)
        treatment = core_helpers.treatment_input(baseline, node_id=isolated)
        definition = experiments.freeze_rest_amenity_definition(
            baseline,
            treatment,
            target_id=TARGET_ID,
            warmup_ticks=2,
            followup_ticks=4,
            population=2,
        )
        checkpoint = experiments.prepare_checkpoint(
            definition, experiments.DEVELOPMENT_SEEDS[2], baseline
        )
        result, evidence = core_helpers.execute_pair(
            definition, checkpoint, baseline, treatment
        )
        assert result["status"] == "invalid_pair" and evidence is None
        return result, evidence

    monkeypatch.setattr(experiments, "execute_pair", execute_invalid_pair)
    receipt = runner.run_reserved(session, attempt_id)
    assert receipt.status == "failed" and receipt.result_sha256 is None
    summary = case["repo"].attempt_summary(
        case["version_id"], experiment_id, attempt_id, world_id=case["world_id"]
    )
    assert summary["outcome"]["failure"]["code"] == "execution_refused"
    assert summary["outcome"]["failure"]["detail"].startswith("intervention_unreachable:")


def test_noop_control_is_stored_and_replayed_exactly(experiment_case):
    case = experiment_case
    definition = experiments.freeze_noop_control_definition(
        case["baseline"], warmup_ticks=2, followup_ticks=3, population=3
    )
    experiment_id, attempt_id = uuid.uuid4(), uuid.uuid4()
    case["repo"].create_definition(
        experiment_id,
        case["source_society_id"],
        definition,
        actor=case["actor"],
    )
    case["repo"].start_attempt(
        experiment_id, attempt_id, experiments.DEVELOPMENT_SEEDS[1], actor=case["actor"]
    )
    checkpoint = experiments.prepare_checkpoint(
        definition, experiments.DEVELOPMENT_SEEDS[1], case["baseline"]
    )
    case["repo"].save_checkpoint(attempt_id, checkpoint)
    result, evidence = experiments.execute_pair(
        definition, checkpoint, case["baseline"], case["baseline"]
    )
    assert evidence is not None
    assert result["comparison"]["high_fatigue_fraction"] == {
        "numerator": 0,
        "denominator": 1,
    }
    case["repo"].complete_attempt(attempt_id, evidence, result)
    assert case["repo"].verify_attempt(attempt_id)["outcome"]["result"] == result


def test_incomplete_failed_idempotent_and_conflicting_records_are_explicit(experiment_case):
    case = experiment_case
    experiment_id = uuid.uuid4()
    case["repo"].create_definition(
        experiment_id,
        case["source_society_id"],
        case["definition"],
        actor=case["actor"],
    )
    # Definition replay is exact; another document under the same identity conflicts.
    case["repo"].create_definition(
        experiment_id,
        case["source_society_id"],
        case["definition"],
        actor=case["actor"],
    )
    attempt_id = uuid.uuid4()
    case["repo"].start_attempt(
        experiment_id, attempt_id, experiments.DEVELOPMENT_SEEDS[2], actor=case["actor"]
    )
    assert case["repo"].attempt(attempt_id)["status"] == "incomplete"
    failed = case["repo"].fail_attempt(
        attempt_id, code="operator_aborted", detail="isolated fixture interruption"
    )
    assert failed["status"] == "failed"
    assert failed["outcome"]["failure"]["checkpoint_sha256"] == ""
    assert (
        case["repo"].fail_attempt(
            attempt_id, code="operator_aborted", detail="isolated fixture interruption"
        )["status"]
        == "failed"
    )
    late_checkpoint = experiments.prepare_checkpoint(
        case["definition"], experiments.DEVELOPMENT_SEEDS[2], case["baseline"]
    )
    with pytest.raises(ExperimentConflict, match="terminal"):
        case["repo"].save_checkpoint(attempt_id, late_checkpoint)
    with pytest.raises(ExperimentConflict):
        case["repo"].fail_attempt(
            attempt_id, code="validation_refused", detail="different terminal record"
        )


def test_workspace_nondisclosure_and_current_authorization_gate_every_read(
    experiment_case, monkeypatch
):
    case = experiment_case
    _experiment_id, attempt_id, checkpoint = _prepare(case)
    result, evidence = experiments.execute_pair(
        case["definition"], checkpoint, case["baseline"], case["treatment"]
    )
    assert evidence is not None
    foreign = SocietyExperimentRepository(
        case["connection"], uuid.uuid4(), input_authorizer=lambda _document: None
    )
    with pytest.raises(UnknownExperiment, match="unavailable"):
        foreign.attempt(attempt_id)

    verify = experiments.verify_pair_result

    def revoke_after_replay(*args, **kwargs):
        verify(*args, **kwargs)
        case["rights"]["available"] = False

    monkeypatch.setattr(experiments, "verify_pair_result", revoke_after_replay)
    with pytest.raises(UnavailableSocietyInput, match="withdrawn"):
        case["repo"].complete_attempt(attempt_id, evidence, result)
    with pytest.raises(UnavailableSocietyInput, match="withdrawn"):
        case["repo"].attempt(attempt_id)
    assert (
        case["connection"]
        .execute(
            "select count(*) as n from society_experiment_outcome where workspace_id=%s "
            "and attempt_id=%s",
            (case["workspace"], attempt_id),
        )
        .fetchone()["n"]
        == 0
    )


def test_resealed_noncanonical_checkpoint_and_oversized_work_refuse_before_storage(
    experiment_case, monkeypatch
):
    case = experiment_case
    experiment_id = uuid.uuid4()
    case["repo"].create_definition(
        experiment_id,
        case["source_society_id"],
        case["definition"],
        actor=case["actor"],
    )
    attempt_id = uuid.uuid4()
    case["repo"].start_attempt(
        experiment_id, attempt_id, experiments.DEVELOPMENT_SEEDS[3], actor=case["actor"]
    )
    checkpoint = experiments.prepare_checkpoint(
        case["definition"], experiments.DEVELOPMENT_SEEDS[3], case["baseline"]
    )
    corrupt = deepcopy(checkpoint)
    corrupt["state"]["tick"] = 0
    corrupt["state_sha256"] = society_state_sha256(corrupt["state"])
    _reseal(corrupt)
    with pytest.raises(experiments.ExperimentIntegrityError):
        case["repo"].save_checkpoint(attempt_id, corrupt)
    assert case["repo"].attempt(attempt_id)["status"] == "incomplete"

    too_large = deepcopy(case["definition"])
    too_large["warmup_ticks"] = 1_441
    _reseal(too_large)
    monkeypatch.setattr(
        experiments,
        "validate_experiment_definition",
        lambda *_args, **_kwargs: pytest.fail("heavy validation ran before the resource refusal"),
    )
    with pytest.raises(ExperimentResourceLimit, match="warmup"):
        case["repo"].create_definition(
            uuid.uuid4(),
            case["source_society_id"],
            too_large,
            actor=case["actor"],
        )


def test_checkpoint_replay_refuses_a_caller_transaction_before_heavy_work(
    experiment_case, monkeypatch
):
    case = experiment_case
    experiment_id = uuid.uuid4()
    case["repo"].create_definition(
        experiment_id,
        case["source_society_id"],
        case["definition"],
        actor=case["actor"],
    )
    attempt_id = uuid.uuid4()
    case["repo"].start_attempt(
        experiment_id, attempt_id, experiments.DEVELOPMENT_SEEDS[4], actor=case["actor"]
    )
    checkpoint = experiments.prepare_checkpoint(
        case["definition"], experiments.DEVELOPMENT_SEEDS[4], case["baseline"]
    )
    monkeypatch.setattr(
        experiments,
        "validate_experiment_checkpoint",
        lambda *_args, **_kwargs: pytest.fail("checkpoint replay entered an outer transaction"),
    )
    with case["connection"].transaction(), pytest.raises(ValueError, match="idle connection"):
        case["repo"].save_checkpoint(attempt_id, checkpoint)


def test_automatic_population_cannot_borrow_a_smaller_source_population_bound(
    experiment_case, monkeypatch
):
    case = experiment_case
    version = case["objects_api"].version("Automatic population bound fixture")
    version_id = uuid.UUID(version["version_id"])
    baseline = grid_input(columns=6, rows=4, version_id=version_id)
    baseline["authored_state"] = {
        "edit_seq": version["edit_seq"],
        "delta_sha256": version["state_sha256"],
    }
    _seal_input(baseline)
    routine = current_routine()
    place = LivingPlace(place_from_society_input(baseline, routine), routine)
    society_id = uuid.uuid5(version_id, "exulanica-society/v1")
    seed = "6a" * 32
    state = initial_living_society(
        society_id, seed, place, routine, branch_id=str(version_id), population=1
    )
    automatic = initial_living_society(
        society_id, seed, place, routine, branch_id=str(version_id)
    )
    assert len(state["inhabitants"]) == 1 < len(automatic["inhabitants"])
    place_id = uuid.uuid4()
    case["connection"].execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (case["workspace"], place_id),
    )
    case["connection"].execute(
        "insert into world_society(workspace_id,society_id,world_id,version_id,place_id,"
        "region_id,engine_version,seed,population_size,tick_seconds,current_tick,state,"
        "state_sha256,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            case["workspace"],
            society_id,
            baseline["world_id"],
            version_id,
            place_id,
            "region-a",
            "exulanica-society/v4",
            seed,
            1,
            60,
            0,
            Jsonb(state),
            society_state_sha256(state),
            case["actor"],
        ),
    )
    case["connection"].execute(
        "insert into world_society_input(workspace_id,society_id,input_seq,document,"
        "document_sha256) values(%s,%s,1,%s,%s)",
        (case["workspace"], society_id, Jsonb(baseline), baseline["document_sha256"]),
    )
    definition = experiments.freeze_noop_control_definition(
        baseline, warmup_ticks=1, followup_ticks=1, population=None
    )
    monkeypatch.setattr(
        experiments,
        "validate_experiment_definition",
        lambda *_args, **_kwargs: pytest.fail("heavy validation ran without a population bound"),
    )
    with pytest.raises(ExperimentResourceLimit, match="explicit bounded population"):
        case["repo"].create_definition(
            uuid.uuid4(), society_id, definition, actor=case["actor"]
        )


def test_database_records_are_append_only(experiment_case):
    case = experiment_case
    experiment_id = uuid.uuid4()
    case["repo"].create_definition(
        experiment_id,
        case["source_society_id"],
        case["definition"],
        actor=case["actor"],
    )
    with pytest.raises(Exception, match="not committed"):
        case["connection"].execute(
            "insert into society_experiment_attempt(workspace_id,attempt_id,experiment_id,"
            "phase,seed_sha256,created_by) values(%s,%s,%s,'development',%s,%s)",
            (
                case["workspace"],
                uuid.uuid4(),
                experiment_id,
                "f" * 64,
                case["actor"],
            ),
        )
    with pytest.raises(Exception, match="append-only"):
        case["connection"].execute(
            "update society_experiment_definition set created_by=%s "
            "where workspace_id=%s and experiment_id=%s",
            (uuid.uuid4(), case["workspace"], experiment_id),
        )


def test_nonowner_role_cannot_discover_another_workspaces_experiment(
    experiment_case, spine_schema
):
    case = experiment_case
    experiment_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    seed = experiments.DEVELOPMENT_SEEDS[5]
    checkpoint = experiments.prepare_checkpoint(case["definition"], seed, case["baseline"])
    result, evidence = experiments.execute_pair(
        case["definition"], checkpoint, case["baseline"], case["treatment"]
    )
    assert evidence is not None
    provision_runtime_role(case["connection"], role=RLS_ROLE)
    _psycopg, scratch = spine_schema
    database = scratch_role_database(scratch, RLS_ROLE)
    with database.session(case["workspace"]) as connection:
        privileges = connection.execute(
            "select has_table_privilege(current_user,'society_experiment_attempt','SELECT') "
            "as can_select,has_table_privilege(current_user,'society_experiment_attempt','INSERT') "
            "as can_insert,has_table_privilege(current_user,'society_experiment_attempt','UPDATE') "
            "as can_update"
        ).fetchone()
        assert privileges == {"can_select": True, "can_insert": True, "can_update": False}
        repo = SocietyExperimentRepository(
            connection, case["workspace"], input_authorizer=lambda _document: None
        )
        repo.create_definition(
            experiment_id,
            case["source_society_id"],
            case["definition"],
            actor=case["actor"],
        )
        repo.start_attempt(experiment_id, attempt_id, seed, actor=case["actor"])
        repo.save_checkpoint(attempt_id, checkpoint)
        repo.complete_attempt(attempt_id, evidence, result)
        assert repo.verify_attempt(attempt_id)["status"] == "completed"
        mine = connection.execute(
            "select count(*) as n from society_experiment_definition where experiment_id=%s",
            (experiment_id,),
        ).fetchone()["n"]
    with database.session(uuid.uuid4()) as connection:
        theirs = connection.execute(
            "select count(*) as n from society_experiment_definition where experiment_id=%s",
            (experiment_id,),
        ).fetchone()["n"]
    assert mine == 1 and theirs == 0


def test_an_experiment_is_read_only_in_the_world_its_definition_binds(experiment_case):
    """A version-addressed read in another world refuses exactly as a missing experiment does."""
    case = experiment_case
    repo, version_id = case["repo"], case["version_id"]
    experiment_id, attempt_id = _reserve(case)
    assert repo.definition_for_version(version_id, experiment_id, world_id=case["world_id"])
    assert repo.attempt_summary(version_id, experiment_id, attempt_id, world_id=case["world_id"])
    elsewhere = f"{case['world_id']}:elsewhere"
    for read in (
        lambda: repo.definition_for_version(version_id, experiment_id, world_id=elsewhere),
        lambda: repo.attempt_summary(version_id, experiment_id, attempt_id, world_id=elsewhere),
        lambda: repo.definition_for_version(version_id, uuid.uuid4(), world_id=case["world_id"]),
    ):
        with pytest.raises(UnknownExperiment, match="unavailable"):
            read()
    # Nor can a definition be prepared over the version's society from another world.
    with pytest.raises(UnknownExperiment, match="experiment source is unavailable"):
        repo.prepare_definition(
            version_id,
            uuid.uuid4(),
            world_id=elsewhere,
            baseline_input_seq=1,
            treatment_input_seq=1,
            intervention="noop",
            target_id=None,
            population=3,
            warmup_ticks=2,
            followup_ticks=3,
            actor=case["actor"],
        )
