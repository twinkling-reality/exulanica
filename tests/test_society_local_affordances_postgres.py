"""PG18 evidence using actual admitted district bytes and scoped runtime/object hooks."""

from copy import deepcopy

import pytest
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world.society import StaleSocietyState, UnavailableSocietyInput
from exulanica.world.society_input_policy import LOCAL_COMPOSITION, LOCAL_INPUT, UNREACHABLE
from exulanica.world.society_planner import input_sha256
from psycopg.errors import CheckViolation
from psycopg.types.json import Jsonb

import test_society_runtime as helpers

runtime_world = helpers.runtime_world
pytestmark = pytest.mark.postgres


def opt_in(w):
    w["runtime"] = SocietyRuntime(
        store=w["store"],
        bindings=[w["binding"]],
        reviewed_affordances=w["registry"],
        composition_profile=LOCAL_COMPOSITION,
    )
    w["objects"] = WorldObjectRepository(
        w["connection"],
        w["workspace"],
        world_id=w["version"].world_id,
        store=w["store"],
        on_edit=lambda vid: w["runtime"].authored_edit(w["connection"], w["session"], vid),
    )


def add_far(w):
    v = w["objects"].version(w["binding"].version_id)
    return w["objects"].add_object(
        v.version_id,
        AuthoredObject(
            "object:far-reviewed",
            w["plate"].content_sha256,
            "region-a",
            Transform(1000000, 0, 1000000, 0, 1000),
            ObjectOrigin("authored", "fictional"),
        ),
        base_state_sha256=v.state_sha256,
        actor=w["session"].actor,
    )


def history(w):
    return [
        r["document"]
        for r in w["connection"].execute(
            "select document from world_society_input where workspace_id=%s order by input_seq",
            (w["workspace"],),
        )
    ]


def step(w, state):
    return helpers.society(w).advance(
        w["binding"].version_id,
        base_tick=state["current_tick"],
        base_state_sha256=state["state_sha256"],
    )


@pytest.mark.parametrize("engine", ["exulanica-society/v2", "exulanica-society/v3"])
def test_explicit_policy_upgrade_mixed_inputs_move_undo_reload_and_exact_replay(
    runtime_world, engine
):
    w = runtime_world
    b = w["binding"]
    legacy = helpers.initial(w)
    assert legacy["profile"] == "exulanica.society-input/v1"
    state = helpers.society(w).create(
        b.version_id,
        place_id=b.place_id,
        region_id=b.region_id,
        seed="7a" * 32,
        actor=w["session"].actor,
        profile=engine,
        initial_input=legacy,
    )
    state = step(w, state)
    original = deepcopy(state)
    old_binding = w["binding"].model_dump_json()
    opt_in(w)
    added = add_far(w)
    inputs = history(w)
    assert inputs[0] == legacy
    assert inputs[1]["profile"] == LOCAL_INPUT and inputs[1]["availability"] == "available"
    assert inputs[1]["unavailable_affordances"][0]["reason"] == UNREACHABLE
    assert inputs[1]["navigation"] == inputs[0]["navigation"]
    assert inputs[1]["targets"] == inputs[0]["targets"]
    assert w["binding"].model_dump_json() == old_binding
    state = step(w, state)
    assert any(p["action"]["status"] != "blocked" for p in state["state"]["inhabitants"])
    moved = w["objects"].move_object(
        b.version_id,
        "object:far-reviewed",
        Transform(40000, 0, 64000, 0, 1000),
        base_state_sha256=added.state_sha256,
        actor=w["session"].actor,
    )
    assert history(w)[-1]["unavailable_affordances"] == []
    assert any(t["object_id"] == "object:far-reviewed" for t in history(w)[-1]["targets"])
    state = step(w, state)
    w["objects"].undo(b.version_id, base_state_sha256=moved.state_sha256, actor=w["session"].actor)
    assert history(w)[-1]["unavailable_affordances"][0]["object_id"] == "object:far-reviewed"
    state = step(w, state)
    w["connection"].commit()
    opt_in(w)  # Fresh runtime configuration, no reconstruction of historical projection.
    assert helpers.society(w).snapshot(b.version_id) == state
    replay = helpers.society(w).replay(b.version_id)
    assert replay["replay_verified"] and replay["state_sha256"] == state["state_sha256"]
    with pytest.raises(StaleSocietyState):
        step(w, original)
    assert len(state["state"]["inhabitants"]) == 128


@pytest.mark.parametrize("engine", ["exulanica-society/v2", "exulanica-society/v3"])
def test_unreachable_activity_keeps_source_rights_and_historical_reads_gated(runtime_world, engine):
    w = runtime_world
    opt_in(w)
    b = w["binding"]
    initial = helpers.initial(w)
    state = helpers.society(w).create(
        b.version_id,
        place_id=b.place_id,
        region_id=b.region_id,
        seed="7a" * 32,
        actor=w["session"].actor,
        profile=engine,
        initial_input=initial,
    )
    add_far(w)
    state = step(w, state)
    w["admissions"].withdraw("source", b.sources[0].admission_id)
    with pytest.raises(UnavailableSocietyInput):
        helpers.society(w).snapshot(b.version_id)
    with pytest.raises(UnavailableSocietyInput):
        helpers.society(w).replay(b.version_id)
    w["runtime"].authored_edit(w["connection"], w["session"], b.version_id)
    unavailable = history(w)[-1]
    assert unavailable["profile"] == LOCAL_INPUT and unavailable["availability"] == "unavailable"
    assert (
        unavailable["targets"]
        == unavailable["unavailable_affordances"]
        == unavailable["navigation"]["nodes"]
        == []
    )
    state = step(w, state)
    assert all(p["action"]["status"] == "blocked" for p in state["state"]["inhabitants"])
    with pytest.raises(UnavailableSocietyInput):
        helpers.society(w).replay(b.version_id)


def test_migration_rejects_unknown_profiles_and_malformed_local_shape(runtime_world):
    w = runtime_world
    state = helpers.create(w)
    legacy = history(w)[0]
    for profile, local in [
        ("unknown", []),
        (LOCAL_INPUT, None),
        (LOCAL_INPUT, {}),
        ("exulanica.society-input/v1", []),
    ]:
        doc = deepcopy(legacy)
        doc.update(profile=profile, input_seq=2)
        if local is not None:
            doc["unavailable_affordances"] = local
        doc["document_sha256"] = input_sha256(doc)
        with pytest.raises(CheckViolation) as error, w["connection"].transaction():
            w["connection"].execute(
                "insert into world_society_input("
                "workspace_id,society_id,input_seq,document,document_sha256) "
                "values(%s,%s,2,%s,%s)",
                (w["workspace"], state["society_id"], Jsonb(doc), doc["document_sha256"]),
            )
        assert error.value.sqlstate == "23514"
    assert len(history(w)) == 1


def test_existing_legacy_global_pause_recovers_only_after_explicit_new_policy_input(runtime_world):
    w = runtime_world
    state = helpers.create(w)
    add_far(w)
    old = history(w)[-1]
    assert old["profile"] == "exulanica.society-input/v1" and old["availability"] == "unavailable"
    state = step(w, state)
    assert all(p["action"]["status"] == "blocked" for p in state["state"]["inhabitants"])
    opt_in(w)
    w["runtime"].authored_edit(w["connection"], w["session"], w["binding"].version_id)
    refreshed = history(w)[-1]
    assert refreshed["authored_state"] == old["authored_state"]
    assert refreshed["input_seq"] == old["input_seq"] + 1
    assert refreshed["profile"] == LOCAL_INPUT and refreshed["availability"] == "available"
    state = step(w, state)
    assert any(p["action"]["status"] != "blocked" for p in state["state"]["inhabitants"])
    assert history(w)[1] == old
    assert helpers.society(w).replay(w["binding"].version_id)["replay_verified"]


def test_locally_unreachable_asset_still_requires_reviewed_bytes(runtime_world):
    from exulanica.evidence.blob import BlobId
    from exulanica.store.base import PurgeAuthorization, privileged_purger

    w = runtime_world
    opt_in(w)
    state = helpers.create(w)
    add_far(w)
    state = step(w, state)
    doc = history(w)[-1]
    assert doc["unavailable_affordances"]
    assert any(
        r["kind"] == "reviewed_asset" and r["sha256"] == w["plate"].content_sha256
        for r in doc["dependency_refs"]
    )
    purger = privileged_purger(
        w["store"],
        PurgeAuthorization(
            tombstone_id="fixture", actor="test", reason="isolated missing asset bytes"
        ),
    )
    purger.purge(BlobId.from_hex(w["plate"].content_sha256))
    with pytest.raises(UnavailableSocietyInput):
        helpers.society(w).snapshot(w["binding"].version_id)
    w["runtime"].authored_edit(w["connection"], w["session"], w["binding"].version_id)
    assert history(w)[-1]["availability"] == "unavailable"
    assert history(w)[-1]["unavailable_affordances"] == []
    state = step(w, state)
    assert all(p["action"]["status"] == "blocked" for p in state["state"]["inhabitants"])
