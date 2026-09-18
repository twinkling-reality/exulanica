"""The v4 living society: routine catalogs, place sizing, occupancy, motion and replay.

Pure fixtures only. The grid is fictional; the Flatiron input is composed offline from the
committed district assets. Nothing here is persistence or rendered evidence.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections import Counter
from itertools import pairwise

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.world.society import society_state_sha256
from exulanica.world.society_catalogs import ROUTINE_DIRECTORY, load_routine_model
from exulanica.world.society_living import (
    LIVING_PROFILE,
    LivingPlace,
    advance_living_society,
    initial_living_society,
)
from exulanica.world.society_metrics import measure_run
from exulanica.world.society_place import (
    place_from_society_input,
    seal_place,
    validate_place,
)

from society_fixtures import edited, seal
from society_living_fixtures import (
    GRID_SOCIETY,
    SEEDS,
    flatiron_input,
    grid_input,
    grid_place,
    routine,
)


def run(place_document, seed, ticks, *, population=None, society=GRID_SOCIETY):
    model = routine()
    place = LivingPlace(place_document, model)
    state = initial_living_society(
        society, seed, place, model, branch_id="branch", population=population
    )
    states, events = [state], []
    for _ in range(ticks):
        state, produced = advance_living_society(state, seed, [place], model)
        states.append(state)
        events.extend(produced)
    return states, events


def test_routine_catalogs_load_with_a_reason_and_licence_on_every_entry():
    model = load_routine_model()
    assert set(model.needs) == {"fatigue", "leisure", "meal", "provisions", "sleep"}
    assert model.activities["stroll"].setting == "standing"
    assert model.activities["work"].mode == "shift"
    assert model.use_classes["bakery"].role_label == "baker"
    assert model.sha256 == load_routine_model().sha256
    for path in ROUTINE_DIRECTORY.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        for entry in document["entries"]:
            assert entry["reason"].strip()
            assert entry["licence"]["verdict"] == "SHIP"


def _drop_standing(entries):
    for entry in entries:
        if entry["setting"] == "standing":
            entry["setting"] = "destination"


@pytest.mark.parametrize(
    ("catalog", "mutate", "message"),
    [
        ("society-need", lambda e: e[0].pop("reason"), "missing"),
        ("society-activity", lambda e: e[0].update(need="appetite"), "unknown need"),
        ("society-activity", _drop_standing, "standing activity"),
        ("society-use-class", lambda e: e[0].update(visitor_affordances=["juggle"]), "affordance"),
        ("society-policy", lambda e: e.pop(0), "exactly"),
    ],
)
def test_routine_catalog_refuses_inconsistent_entries(tmp_path, catalog, mutate, message):
    directory = tmp_path / "society"
    shutil.copytree(ROUTINE_DIRECTORY, directory)
    path = directory / f"{catalog}.v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document["entries"])
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CatalogError, match=message):
        load_routine_model(directory)


def test_a_routine_catalog_the_model_does_not_read_is_refused(tmp_path):
    """A sixth catalog in the directory is refused rather than left out of the model.

    The model used to read exactly the five ids in ROUTINE_VERSIONS, so a catalog added to the
    directory would have been loaded by nobody and covered by no digest, while every test here
    still passed. The directory is now compared against the schemas both ways.
    """
    directory = tmp_path / "society"
    shutil.copytree(ROUTINE_DIRECTORY, directory)
    assert load_routine_model(directory).sha256 == load_routine_model().sha256
    (directory / "society-weather.v1.json").write_text(
        json.dumps({"schema_version": 1, "catalog_id": "society-weather"}), encoding="utf-8"
    )
    with pytest.raises(CatalogError, match="files with no schema"):
        load_routine_model(directory)
    (directory / "society-weather.v1.json").unlink()
    (directory / "society-policy.v1.json").unlink()
    with pytest.raises(CatalogError, match="schemas with no file"):
        load_routine_model(directory)


def test_flatiron_is_projected_as_published_and_sizes_its_population():
    model = routine()
    document = place_from_society_input(flatiron_input(), model)
    validate_place(document, model)
    assert len(document["nodes"]) == len(document["spots"]) == 93
    assert len(document["edges"]) == 151
    assert [d["visitor_capacity"] for d in document["destinations"]] == [1, 1, 1, 1]
    assert document["crossings"] == []
    assert any("32000 mm by 80000 mm" in line for line in document["unsupported"])
    assert any(line.startswith("homes") for line in document["unsupported"])
    place = LivingPlace(document, model)
    state = initial_living_society(uuid.uuid4(), SEEDS[0], place, model, branch_id="b")
    assert state["profile"] == LIVING_PROFILE
    assert state["population"] | {"reason": None} == {
        "size": 46,
        "requested": None,
        "limit": 83,
        "capacity": 93,
        "rule": "place_sized",
        "reason": None,
        "supported_needs": ["fatigue", "leisure"],
    }
    assert state["environment"]["weather"]["availability"] == "unavailable"
    assert state["environment"]["resources"]["availability"] == "unavailable"
    for person in state["inhabitants"]:
        assert person["role"] is None and person["home"] is None and person["work"] is None
        assert person["role_reason"] == "place_publishes_no_premises"
        assert "display_name" not in person
    assert len({tuple(p["position_mm"]) for p in state["inhabitants"]}) == 46
    with pytest.raises(ValueError, match="at most 83 inhabitants"):
        initial_living_society(uuid.uuid4(), SEEDS[0], place, model, branch_id="b", population=84)


def test_flatiron_population_stays_spread_and_moving_for_500_ticks():
    document = place_from_society_input(flatiron_input(), routine())
    states, events = run(document, SEEDS[0], 500)
    summary = measure_run(states[1:], document).summary()
    assert summary["population"] == 46
    assert summary["distinct_positions"]["min"] == 46
    assert summary["stationary_collisions"] == 0
    assert summary["over_capacity_ticks"] == 0
    assert summary["longest_outdoor_stay_ticks"] <= 5
    assert summary["moving_share_milli"] >= 250
    assert {"rest", "stroll", "visit"} <= set(summary["activity_share_milli"])
    assert all(v["peak"] == v["capacity"] == 1 for v in summary["destinations"].values())
    kinds = Counter(event.kind for event in events)
    assert kinds["action_completed"] > 4000 and kinds["goal_selected"] > 4000
    assert all(event.document["synthetic"] for event in events)


@pytest.mark.parametrize("seed", SEEDS)
def test_no_seed_lets_the_population_settle_on_one_spot(seed):
    document = grid_place()
    states, _ = run(document, seed, 150)
    summary = measure_run(states[1:], document).summary()
    population = summary["population"]
    assert population == 30
    assert summary["stationary_collisions"] == 0
    assert summary["over_capacity_ticks"] == 0
    assert summary["distinct_positions"]["min"] >= population - 2
    assert summary["longest_outdoor_stay_ticks"] <= 5
    last_moved = {p["id"]: 0 for p in states[0]["inhabitants"]}
    for tick, state in enumerate(states[1:], start=1):
        for person in state["inhabitants"]:
            if len(person["motion_path_mm"]) > 1:
                last_moved[person["id"]] = tick
            assert tick - last_moved[person["id"]] <= 6, "an inhabitant stopped moving"


def test_every_recorded_step_follows_the_graph_within_the_walking_speed():
    document = grid_place()
    states, _ = run(document, SEEDS[3], 60)
    for state in states[1:]:
        for person in state["inhabitants"]:
            path = person["motion_path_mm"]
            assert path[-1] == person["position_mm"]
            length = 0
            for (ax, az), (bx, bz) in pairwise(path):
                assert ax == bx or az == bz, "a step left the grid lines"
                assert ax % 4000 == 0 or az % 4000 == 0
                length += abs(ax - bx) + abs(az - bz)
            assert length <= person["walk_speed_mm_per_tick"]


def test_v4_transitions_are_byte_deterministic_and_pinned():
    first, first_events = run(grid_place(), SEEDS[0], 30)
    second, second_events = run(grid_place(), SEEDS[0], 30)
    assert first == second
    assert [e.document for e in first_events] == [e.document for e in second_events]
    assert society_state_sha256(first[0]) == INITIAL_GRID_DIGEST
    assert society_state_sha256(first[-1]) == TICK_30_GRID_DIGEST
    assert (
        society_state_sha256([[str(e.event_id), e.kind, e.document] for e in first_events])
        == EVENTS_30_GRID_DIGEST
    )
    other, _ = run(grid_place(), SEEDS[1], 30)
    assert society_state_sha256(other[-1]) != TICK_30_GRID_DIGEST


def test_v4_refuses_foreign_places_seeds_and_routines():
    model = routine()
    place = LivingPlace(grid_place(), model)
    state = initial_living_society(GRID_SOCIETY, SEEDS[0], place, model, branch_id="b")
    with pytest.raises(ValueError, match="seed lineage"):
        advance_living_society(state, SEEDS[1], [place], model)
    other = LivingPlace(grid_place(grid_input(columns=9)), model)
    with pytest.raises(ValueError, match="binding mismatch"):
        advance_living_society(state, SEEDS[0], [other], model)
    tampered = grid_place()
    tampered["destinations"][0]["visitor_capacity"] = 2
    with pytest.raises(ValueError, match=r"digest mismatch|exactly one visitor"):
        LivingPlace(tampered, model)
    resealed = seal_place(tampered)
    with pytest.raises(ValueError, match="exactly one visitor per spot"):
        validate_place(resealed, model)
    stale = dict(state, routine={**state["routine"], "sha256": "0" * 64})
    with pytest.raises(ValueError, match="another routine"):
        advance_living_society(stale, SEEDS[0], [place], model)


def _successor(document, change):
    result = edited(document)
    change(result)
    return seal(result)


def test_place_edits_replan_without_teleporting_and_restore_use():
    model = routine()
    base = grid_input()
    rest = next(t for t in base["targets"] if t["target_id"] == "district:pad-a:rest")

    def disable(doc):
        next(t for t in doc["targets"] if t["target_id"] == rest["target_id"])["enabled"] = False

    def restore(doc):
        next(t for t in doc["targets"] if t["target_id"] == rest["target_id"])["enabled"] = True

    first = LivingPlace(place_from_society_input(base, model), model)
    state = initial_living_society(GRID_SOCIETY, SEEDS[2], first, model, branch_id="b")
    for _ in range(40):
        state, _ = advance_living_society(state, SEEDS[2], [first], model)
        if any(
            (p["goal"] or {}).get("destination_id") == rest["target_id"]
            for p in state["inhabitants"]
        ):
            break
    users = {
        p["id"]
        for p in state["inhabitants"]
        if (p["goal"] or {}).get("destination_id") == rest["target_id"]
    }
    assert users
    before = {p["id"]: p["position_mm"] for p in state["inhabitants"]}
    disabled_doc = _successor(base, disable)
    second = LivingPlace(place_from_society_input(disabled_doc, model), model)
    state, events = advance_living_society(state, SEEDS[2], [first, second], model)
    replanned = [e for e in events if e.kind == "replanned"]
    assert {str(e.subject_id) for e in replanned} == users
    assert {e.document["reason"] for e in replanned} == {"destination_disabled_or_removed"}
    assert all(e.document["input_seq"] == 2 for e in replanned)
    for person in state["inhabitants"]:
        assert person["motion_path_mm"][0] == before[person["id"]]
    for _ in range(20):
        state, _ = advance_living_society(state, SEEDS[2], [second], model)
        assert all(
            (p["goal"] or {}).get("destination_id") != rest["target_id"]
            for p in state["inhabitants"]
        )
    restored_doc = _successor(disabled_doc, restore)
    third = LivingPlace(place_from_society_input(restored_doc, model), model)
    state, _ = advance_living_society(state, SEEDS[2], [second, third], model)
    used = False
    for _ in range(80):
        state, _ = advance_living_society(state, SEEDS[2], [third], model)
        used = used or any(
            p["action"]["kind"] == "rest" and p["action"]["destination_id"] == rest["target_id"]
            for p in state["inhabitants"]
        )
    assert used
    unavailable = _successor(
        restored_doc,
        lambda d: d.update(availability="unavailable", unavailable_reason="source_withdrawn"),
    )
    fourth = LivingPlace(place_from_society_input(unavailable, model), model)
    held = {p["id"]: p["position_mm"] for p in state["inhabitants"]}
    state, events = advance_living_society(state, SEEDS[2], [third, fourth], model)
    assert all(p["action"]["status"] == "blocked" for p in state["inhabitants"])
    assert all(p["position_mm"] == held[p["id"]] for p in state["inhabitants"])
    assert all(len(p["motion_path_mm"]) == 1 for p in state["inhabitants"])
    assert {e.document["reason"] for e in events if e.kind == "blocked"} == {"source_withdrawn"}


def test_legacy_tables_live_only_in_the_frozen_v1_module():
    import inspect

    import exulanica.world.society as core
    import exulanica.world.society_catalogs as catalogs
    import exulanica.world.society_city_place as city
    import exulanica.world.society_legacy as legacy
    import exulanica.world.society_living as living
    import exulanica.world.society_place as place

    for module in (core, catalogs, city, living, place):
        source = inspect.getsource(module)
        for fabrication in ("FIRST_NAMES", "LAST_NAMES", '"home:', '"work:', "300_000", '"baker"'):
            assert fabrication not in source, (module.__name__, fabrication)
    frozen = inspect.getsource(legacy)
    assert "exist only so stored histories replay" in " ".join(frozen.split())
    assert legacy.LEGACY_FIRST_NAMES[0] == "Ari"


# Pinned under three PYTHONHASHSEED values on 2026-09-16. A change here is a new profile.
INITIAL_GRID_DIGEST = "5c725d9c3b3d1bd52cd29bb2e0184ba27c40f6ffb2e9dba1c2e658796f068e13"
TICK_30_GRID_DIGEST = "5e5b6cd809d5c6d7b63b6625a9874f8ba63c0c3412cfd44c6b702bfa7187d6b3"
EVENTS_30_GRID_DIGEST = "a4f38101f40592157ce8664b6380d3e073eb9190703d8e1f0fe500dd5e6a2d6d"
