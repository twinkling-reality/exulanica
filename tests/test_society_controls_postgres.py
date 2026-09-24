"""PG18 controls/worker evidence on admitted Flatiron inputs, using isolated owner fixtures."""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.world.society import StaleSocietyState, UnavailableSocietyInput, UnknownSociety
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_controls import BASE_TICK_INTERVAL_MIN_MS, LeaseLost
from psycopg.errors import CheckViolation

import test_society_runtime as helpers
from test_society_local_affordances_postgres import add_far, opt_in
from tests_support_api import scratch_database

runtime_world = helpers.runtime_world
pytestmark = pytest.mark.postgres


#: The base every control here is saved under: the fastest a host may state, so that a control
#: made a few seconds overdue owes more minutes than one batch may run.
BASE_MS = BASE_TICK_INTERVAL_MIN_MS


def authorizer(w, connection):
    return lambda actor, doc: w["runtime"].authorize(
        connection, replace(w["session"], actor=actor), doc
    )


def controls(w, connection=None):
    connection = connection or w["connection"]
    return SocietyControlRepository(
        connection,
        w["workspace"],
        world_id=w["version"].world_id,
        base_tick_interval_ms=BASE_MS,
        input_authorizer=authorizer(w, connection),
    )


def take_claim(w, connection=None):
    """The workspace's next due claim, whichever world holds it, with ``controls``' authority."""
    connection = connection or w["connection"]
    return SocietyControlRepository.claim_in_workspace(
        connection,
        w["workspace"],
        input_authorizer=authorizer(w, connection),
        base_tick_interval_ms=BASE_MS,
    )


def create(w, engine="exulanica-society/v3"):
    b = w["binding"]
    return helpers.society(w).create(
        b.version_id,
        place_id=b.place_id,
        region_id=b.region_id,
        seed="7a" * 32,
        actor=w["session"].actor,
        profile=engine,
        initial_input=None if engine.endswith("/v1") else helpers.initial(w),
    )


def save(w, *, revision=0, mode="playing", speed=1):
    return controls(w).configure(
        w["binding"].version_id,
        actor=w["session"].actor,
        base_revision=revision,
        mode=mode,
        speed=speed,
    )


def overdue(w, seconds=5):
    w["connection"].execute(
        "update world_society_control set next_due_at=clock_timestamp()"
        "-make_interval(secs=>%s) where workspace_id=%s",
        (seconds, w["workspace"]),
    )
    w["connection"].commit()


def expire(w):
    w["connection"].execute(
        "update world_society_control set lease_expires_at="
        "clock_timestamp()-interval '1 second' where workspace_id=%s",
        (w["workspace"],),
    )
    w["connection"].commit()


@pytest.mark.parametrize(
    "engine", ["exulanica-society/v2", "exulanica-society/v3", "exulanica-society/v4"]
)
def test_saved_controls_bounded_worker_local_failure_and_replay(
    runtime_world, spine_schema, engine
):
    w = runtime_world
    opt_in(w)
    initial = create(w, engine)
    vid = w["binding"].version_id
    repo = controls(w)
    default = repo.read(vid)
    assert default["revision"] == 0 and not default["persisted"] and default["mode"] == "paused"
    assert take_claim(w) is None
    settings = save(w, speed=4)
    assert settings["tick_interval_ms"] == BASE_MS // 4
    assert settings["simulated_seconds_per_tick"] == 60
    add_far(w)  # One unsupported destination must not pause a healthy district.
    overdue(w)
    worker = SocietyControlWorker(
        scratch_database(spine_schema[1]),
        runtime=w["runtime"],
        workspaces=[w["workspace"]],
        base_tick_interval_ms=BASE_MS,
    )
    result = worker.run_once(w["workspace"])
    receipt = result["receipt"]
    assert receipt["executed_ticks"] == 3 and receipt["skipped_due_ticks"] >= 17
    assert len(receipt["transitions"]) == 3 and receipt["tick_to"] == 3
    assert receipt["execution_duration_ms"] > 0
    assert result["control"]["interval_semantics"] == "minimum_wait_after_batch_completion"
    observed = result["control"]["last_batch_execution"]
    assert observed["executed_ticks"] == 3
    assert observed["execution_duration_ms"] == receipt["execution_duration_ms"]
    assert observed["receipt_sha256"] == receipt["document_sha256"]
    assert result["control"]["mode"] == "playing"
    assert helpers.society(w).replay(vid)["replay_verified"]
    held = helpers.society(w).snapshot(vid)
    assert len(held["state"]["inhabitants"]) == held["population_size"]
    # V4 sizes its population to the published walkable patch; earlier profiles keep 128.
    assert held["population_size"] == (46 if engine.endswith("/v4") else 128)
    with worker.database.session(w["workspace"]) as connection:
        assert controls(w, connection).read(vid) == result["control"]
    with pytest.raises(StaleSocietyState):
        save(w, revision=0, mode="paused")
    paused = save(w, revision=1, mode="paused")
    assert paused["revision"] == 2 and take_claim(w) is None
    with pytest.raises(StaleSocietyState):
        repo.manual_step(
            vid,
            actor=w["session"].actor,
            base_revision=2,
            base_tick=0,
            base_state_sha256=initial["state_sha256"],
        )
    step = repo.manual_step(
        vid,
        actor=w["session"].actor,
        base_revision=2,
        base_tick=3,
        base_state_sha256=paused["state_sha256"],
    )
    assert step["society"]["current_tick"] == 4
    assert step["receipt"]["kind"] == "manual_step"
    assert helpers.society(w).replay(vid)["state_sha256"] == step["society"]["state_sha256"]
    events = repo.events(vid)
    assert [e["event_seq"] for e in events] == list(range(len(events), 0, -1))
    with pytest.raises(CheckViolation), w["connection"].transaction():
        w["connection"].execute("update world_society_control_event set document=document")


def test_committed_claim_exclusion_pause_fence_and_workspace_scope(runtime_world, spine_schema):
    w = runtime_world
    initial = create(w)
    save(w)
    overdue(w)
    database = scratch_database(spine_schema[1])

    def claim_once():
        with database.session(w["workspace"]) as connection:
            return take_claim(w, connection)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim_once(), range(2)))
    claim = next(c for c in claims if c is not None)
    assert sum(c is not None for c in claims) == 1
    save(w, revision=1, mode="paused")
    with pytest.raises(LeaseLost):
        controls(w).execute(claim)
    assert helpers.society(w).snapshot(w["binding"].version_id) == initial
    stranger = uuid.uuid4()
    with database.session(stranger) as connection:
        foreign = SocietyControlRepository(connection, stranger, world_id=w["version"].world_id)
        assert SocietyControlRepository.claim_in_workspace(connection, stranger) is None
        with pytest.raises(UnknownSociety):
            foreign.read(w["binding"].version_id)
        with pytest.raises(LeaseLost):
            foreign.execute(claim)


def test_crash_reclaim_stale_token_and_recovery_limit(runtime_world):
    w = runtime_world
    create(w)
    save(w)
    overdue(w)
    repo = controls(w)
    # Deliberately abandon a committed lease, equivalent durable crash state.
    original = take_claim(w)
    assert take_claim(w) is None
    expire(w)
    recovered = take_claim(w)
    assert recovered.token != original.token
    with pytest.raises(LeaseLost):
        repo.execute(original)
    assert repo.execute(recovered)["receipt"]["executed_ticks"] == 3
    overdue(w)
    for _ in range(3):
        assert take_claim(w) is not None
        expire(w)
    assert take_claim(w) is None
    state = repo.read(w["binding"].version_id)
    assert state["mode"] == "paused" and state["reason"] == "lease_recovery_limit"
    assert state["current_tick"] == 3 and state["revision"] == 2
    assert repo.events(w["binding"].version_id)[0]["kind"] == "lease_recovery_exhausted"
    assert save(w, revision=2)["mode"] == "playing"


def test_failure_rolls_back_batch_and_source_withdrawal_pauses(runtime_world, monkeypatch):
    w = runtime_world
    before = create(w)
    save(w)
    overdue(w)
    repo = controls(w)
    claim = take_claim(w)
    original_ready = repo._ready

    def crash_after_first_tick(society, actor):
        original_ready(society, actor)
        helpers.society(w).advance(
            w["binding"].version_id, base_tick=0, base_state_sha256=before["state_sha256"]
        )
        raise RuntimeError("injected process failure")

    monkeypatch.setattr(repo, "_ready", crash_after_first_tick)
    with pytest.raises(RuntimeError):
        repo.execute(claim)
    assert helpers.society(w).snapshot(w["binding"].version_id) == before
    assert take_claim(w) is None  # Failure did not erase committed lease.
    expire(w)
    claim = take_claim(w)
    monkeypatch.setattr(repo, "_ready", original_ready)
    w["admissions"].withdraw("source", w["binding"].sources[0].admission_id)
    result = repo.execute(claim)
    assert (
        result["control"]["mode"] == "paused"
        and result["control"]["reason"] == "source_unavailable"
    )
    assert result["receipt"]["executed_ticks"] == 0 and result["control"]["current_tick"] == 0
    with pytest.raises(UnavailableSocietyInput):
        helpers.society(w).replay(w["binding"].version_id)


def test_expiry_during_execution_rolls_back_ticks(runtime_world, monkeypatch):
    w = runtime_world
    before = create(w)
    save(w)
    overdue(w)
    repo = controls(w)
    claim = take_claim(w)
    # Shorten the persisted deadline in this isolated fixture, then really cross DB clock time.
    w["connection"].execute(
        "update world_society_control set lease_expires_at="
        "clock_timestamp()+interval '200 milliseconds' where workspace_id=%s",
        (w["workspace"],),
    )
    w["connection"].commit()
    original = repo._ready

    def slow_ready(society, actor):
        original(society, actor)
        time.sleep(0.25)

    monkeypatch.setattr(repo, "_ready", slow_ready)
    with pytest.raises(LeaseLost):
        repo.execute(claim)
    assert helpers.society(w).snapshot(w["binding"].version_id) == before
    assert take_claim(w).token != claim.token


def test_legacy_is_manually_steppable_but_not_playable(runtime_world):
    w = runtime_world
    before = create(w, "exulanica-society/v1")
    repo = controls(w)
    vid = w["binding"].version_id
    assert not repo.read(vid)["play_eligible"]
    with pytest.raises(ValueError, match="legacy_society_not_playable"):
        save(w)
    assert not repo.read(vid)["persisted"]
    after = repo.manual_step(
        vid,
        actor=w["session"].actor,
        base_revision=0,
        base_tick=0,
        base_state_sha256=before["state_sha256"],
    )
    assert after["society"]["current_tick"] == 1
    assert helpers.society(w).replay(vid)["replay_verified"]


def test_other_authored_branch_keeps_independent_controls(runtime_world):
    w = runtime_world
    create(w)
    other = w["objects"].create_version(
        source_snapshot_id=w["binding"].source_snapshot_id,
        title="Independent simulation",
        created_by=w["session"].actor,
    )
    helpers.society(w).create(
        other.version_id,
        place_id=w["binding"].place_id,
        region_id="region-a",
        seed="8b" * 32,
        actor=w["session"].actor,
    )
    save(w)
    overdue(w)
    repo = controls(w)
    claim = take_claim(w)
    assert claim.version_id == w["binding"].version_id
    repo.execute(claim)
    untouched = repo.read(other.version_id)
    assert (
        untouched["current_tick"] == 0 and untouched["revision"] == 0 and not untouched["persisted"]
    )
    assert untouched["society_id"] != str(claim.society_id)


def test_recorded_control_cadence_measurement(runtime_world, spine_schema):
    """Small reproducible throughput sample, not a hardware-independent latency assertion."""
    import json
    import platform
    import statistics

    w = runtime_world
    create(w)
    save(w)
    worker = SocietyControlWorker(
        scratch_database(spine_schema[1]),
        runtime=w["runtime"],
        workspaces=[w["workspace"]],
        base_tick_interval_ms=BASE_MS,
    )
    samples = []
    for _ in range(12):
        overdue(w, seconds=0)
        start = time.perf_counter()
        result = worker.run_once(w["workspace"])
        samples.append((time.perf_counter() - start) * 1000)
        assert result["receipt"]["executed_ticks"] == 1
    sample = {
        "label": "isolated PG18 admitted Flatiron v3, 128 inhabitants; no model calls",
        "platform": platform.platform(),
        "processor": platform.processor(),
        "samples_ms": samples,
        "median_ms": statistics.median(samples),
        "p95_nearest_rank_ms": sorted(samples)[-1],
        "scope": "claim commit, new connection, input authority, one tick, receipt commit",
        "limitations": "single branch, local database/store, short history, no concurrent UI/load",
    }
    print("PLAYBACK_CADENCE " + json.dumps(sample, sort_keys=True))


def test_source_failure_after_one_tick_rolls_back_whole_batch(runtime_world, monkeypatch):
    from exulanica.world.society_repository import SocietyRepository

    w = runtime_world
    before = create(w)
    save(w)
    overdue(w)
    repo = controls(w)
    claim = take_claim(w)
    original = SocietyRepository.advance
    advances = []

    def fail_second(self, *args, **kwargs):
        if advances:
            raise UnavailableSocietyInput("injected authority failure after first tentative tick")
        result = original(self, *args, **kwargs)
        advances.append(result["current_tick"])
        return result

    monkeypatch.setattr(SocietyRepository, "advance", fail_second)
    result = repo.execute(claim)
    assert advances == [1]
    assert result["receipt"]["executed_ticks"] == 0
    assert result["control"]["reason"] == "source_unavailable"
    assert helpers.society(w).snapshot(w["binding"].version_id) == before
    assert helpers.society(w).replay(w["binding"].version_id)["replay_verified"]


def test_pause_acknowledgement_follows_running_batch(runtime_world, spine_schema):
    import threading

    w = runtime_world
    create(w)
    save(w)
    overdue(w)
    database = scratch_database(spine_schema[1])
    claim = take_claim(w)
    entered, release = threading.Event(), threading.Event()

    def execute():
        with database.session(w["workspace"]) as connection:
            repo = controls(w, connection)
            ready = repo._ready

            def wait_inside_lock(society, actor):
                ready(society, actor)
                entered.set()
                assert release.wait(5)

            repo._ready = wait_inside_lock
            return repo.execute(claim)

    def pause():
        with database.session(w["workspace"]) as connection:
            return controls(w, connection).configure(
                w["binding"].version_id,
                actor=w["session"].actor,
                base_revision=1,
                mode="paused",
                speed=1,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        advancing = pool.submit(execute)
        assert entered.wait(5)
        pausing = pool.submit(pause)
        time.sleep(0.05)
        assert not pausing.done()
        release.set()
        assert advancing.result(timeout=10)["receipt"]["executed_ticks"] == 3
        assert pausing.result(timeout=10)["mode"] == "paused"
    assert controls(w).read(w["binding"].version_id)["current_tick"] == 3
    assert take_claim(w) is None
    with pytest.raises(LeaseLost):
        controls(w).execute(claim)
