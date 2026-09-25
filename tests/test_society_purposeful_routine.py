"""The purposeful society's routine is versioned data, and the input a society reads selects it.

``assets/catalogs/society/society-purposeful-activity.v<N>.json`` states what a purposeful
society's people do, how long each stay lasts and how it varies, what it relieves, how often it is
chosen, and how far standing and talking reach. Version 1 is the rules the society was released
with, which every input that records no routine is read under; a saved world's newest input records
the version it was composed under (``exulanica.society-input/authored-ground-v3``).
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from copy import deepcopy

import psycopg
import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.world import object_catalog, society_authored_ground, society_catalogs
from exulanica.world.object_catalog import world_object_catalog
from exulanica.world.society_catalogs import (
    ANY_KIND,
    NO_KIND,
    PURPOSEFUL_CATALOG,
    PURPOSEFUL_ROUTINE_VERSIONS,
    ROUTINE_DIRECTORY,
    UNRECORDED_ROUTINE_VERSIONS,
    check_object_kinds,
    load_purposeful_routine,
    purposeful_routine,
)
from exulanica.world.society_composition import MAX_REACH_MM
from exulanica.world.society_input_policy import AUTHORED_GROUND_INPUT_V3
from exulanica.world.society_planner import (
    DURATIONS,
    input_sha256,
    routine_of,
    validate_society_input,
)

import living_square_support as square
import test_society_authored_world_postgres as helpers
import test_society_saved_world_api as saved_api

saved_world = helpers.saved_world


def test_the_released_rules_are_the_first_version_and_nothing_else():
    """Version 1 states exactly what the planner used to state in code, and chooses the nearest."""
    released = purposeful_routine(UNRECORDED_ROUTINE_VERSIONS)
    assert DURATIONS == {"rest": 3, "visit": 1}
    assert {key: (a.relief, a.preferred_at_need) for key, a in released.activities.items()} == {
        "rest": (500, 750),
        "visit": (20, 0),
    }
    assert released.choice == "nearest"
    assert released.in_setting("open") is None and released.in_setting("pair") is None


def test_a_new_input_records_the_newest_routine_and_every_other_reads_the_first():
    document = square.compose(square.square_objects())
    assert document["profile"] == AUTHORED_GROUND_INPUT_V3
    assert document["routine"] == purposeful_routine().binding()
    assert document["routine"]["catalog_versions"] == PURPOSEFUL_ROUTINE_VERSIONS
    assert routine_of(document) == purposeful_routine()
    older = square.compose(square.square_objects(), v2=True)
    assert "routine" not in older
    assert routine_of(older) == purposeful_routine(UNRECORDED_ROUTINE_VERSIONS)


def test_each_activity_names_the_entry_for_its_kind_or_its_affordance_default():
    document = square.compose(square.square_objects())
    by_kind = {t["object_id"].split("-", 3)[3]: t["activity"] for t in document["targets"]}
    assert by_kind == {
        "bench": "rest_bench",
        "cafe_table": "rest_cafe_table",
        "market_stall": "visit_market_stall",
        "planter_tree": "visit_planter_tree",
        "seating_planter": "rest_seating_planter",
    }
    # A kind the routine states no stay for uses its affordance's default entry.
    routine = purposeful_routine()
    assert routine.at_object("visit", "marker_cube") == routine.default("visit")


def _rebound(document: dict, **routine) -> dict:
    changed = deepcopy(document)
    changed["routine"] = {**changed["routine"], **routine}
    changed["document_sha256"] = input_sha256(changed)
    return changed


def test_an_input_is_held_to_the_routine_it_records():
    document = square.compose(square.square_objects())
    validate_society_input(document)
    with pytest.raises(ValueError, match="purposeful routine digest mismatch"):
        validate_society_input(_rebound(document, sha256="0" * 64))
    with pytest.raises(ValueError, match="unknown purposeful routine"):
        validate_society_input(_rebound(document, catalog_versions={PURPOSEFUL_CATALOG: 99}))
    with pytest.raises(ValueError, match="invalid routine binding"):
        validate_society_input(_rebound(document, catalog_versions={PURPOSEFUL_CATALOG: "2"}))
    # An activity the recorded routine does not state for the target's affordance is refused.
    wrong = deepcopy(document)
    wrong["targets"][0]["activity"] = (
        "visit_market_stall" if wrong["targets"][0]["affordance"] == "rest" else "rest_bench"
    )
    wrong["document_sha256"] = input_sha256(wrong)
    with pytest.raises(ValueError, match="unreviewed affordance"):
        validate_society_input(wrong)
    # An input of a profile that records no routine cannot carry one.
    older = square.compose(square.square_objects(), v2=True)
    older["routine"] = document["routine"]
    older["document_sha256"] = input_sha256(older)
    with pytest.raises(ValueError, match="invalid society input fields"):
        validate_society_input(older)


def _edited(tmp_path, change) -> object:
    directory = tmp_path / "society"
    shutil.copytree(ROUTINE_DIRECTORY, directory)
    path = directory / f"{PURPOSEFUL_CATALOG}.v2.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document["entries"])
    path.write_text(json.dumps(document), encoding="utf-8")
    return directory


def _entry(entries, key):
    return next(entry for entry in entries if entry["key"] == key)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda e: _entry(e, "rest_bench").update(weight_milli=10), "weight 0"),
        (lambda e: _entry(e, "stand").update(reach_mm=0), "reaches"),
        (lambda e: _entry(e, "talk").update(spacing_mm=0), "reaches"),
        (lambda e: _entry(e, "talk").update(reach_mm=MAX_REACH_MM + 1), "reach_mm"),
        (lambda e: _entry(e, "visit").update(choice="nearest"), "fixed time"),
        (lambda e: _entry(e, "rest_bench").update(object_kind="any"), "exactly one entry"),
        (lambda e: e.remove(_entry(e, "rest")), "a kind entry offers"),
        (lambda e: _entry(e, "stand").pop("reason"), "missing"),
    ],
    ids=[
        "kind-entry-with-a-weight",
        "stand-with-no-reach",
        "talk-with-no-spacing",
        "reach-beyond-every-reach",
        "a-drawn-routine-with-a-nearest-entry",
        "two-defaults-for-one-affordance",
        "kind-entries-with-no-default",
        "an-entry-with-no-reason",
    ],
)
def test_the_loader_refuses_by_name(tmp_path, change, message):
    directory = _edited(tmp_path, change)
    with pytest.raises(CatalogError, match=message):
        load_purposeful_routine(directory, versions=PURPOSEFUL_ROUTINE_VERSIONS)


def test_the_loader_reads_the_published_files_through_the_path_the_refusals_take(tmp_path):
    """A positive control for the refusals above: an unchanged copy loads to the same digest."""
    directory = _edited(tmp_path, lambda entries: None)
    assert (
        load_purposeful_routine(directory, versions=PURPOSEFUL_ROUTINE_VERSIONS).sha256
        == purposeful_routine().sha256
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda e: _entry(e, "rest_bench").update(object_kind="park_bench"), "'park_bench'"),
        (lambda e: _entry(e, "rest_bench").update(object_kind="marker_cube"), "offers 'visit'"),
    ],
    ids=["kind-the-object-catalog-lacks", "kind-with-another-affordance"],
)
def test_a_routine_about_to_be_recorded_is_held_to_the_object_catalog(tmp_path, change, message):
    """Reading a version never asks the object catalog; recording one does, and refuses by name."""
    directory = _edited(tmp_path, change)
    routine = load_purposeful_routine(directory, versions=PURPOSEFUL_ROUTINE_VERSIONS)
    with pytest.raises(CatalogError, match=message):
        check_object_kinds(routine)


def test_the_routine_a_new_input_records_names_only_kinds_the_object_catalog_states():
    """Parity of the catalogs as they are: a changed object catalog fails here, not in a world."""
    routine = purposeful_routine()
    named = {activity.object_kind for activity in routine.activities.values()} - {ANY_KIND, NO_KIND}
    # A positive control: the routine names kinds of its own, so the check below asks something.
    assert named == {"bench", "cafe_table", "market_stall", "planter_tree", "seating_planter"}
    check_object_kinds(routine, world_object_catalog())


def _without_benches(monkeypatch) -> None:
    """The object catalog as a later version might publish it, with no bench in it."""
    reduced = dataclasses.replace(
        world_object_catalog(),
        kinds=tuple(kind for kind in world_object_catalog().kinds if kind.key != "bench"),
    )
    monkeypatch.setattr(object_catalog, "world_object_catalog", lambda: reduced)
    monkeypatch.setattr(society_authored_ground, "world_object_catalog", lambda: reduced)


def test_a_recorded_input_is_read_whatever_the_object_catalog_later_drops(monkeypatch):
    """A stored newest-profile input names a routine whose bench entry outlives the bench kind."""
    recorded = square.compose(square.square_objects())
    assert "rest_bench" in {target["activity"] for target in recorded["targets"]}
    society_catalogs._purposeful.cache_clear()
    _without_benches(monkeypatch)
    try:
        # The routine is read again from its files by version and digest, under the smaller
        # object catalog, and the input it binds is as valid as when it was recorded.
        validate_society_input(recorded)
        assert routine_of(recorded) == purposeful_routine()
        # Composing a new input under that catalog refuses by name, before anything records it.
        with pytest.raises(CatalogError, match="'bench'"):
            square.compose(square.square_objects())
    finally:
        society_catalogs._purposeful.cache_clear()


def test_an_input_recording_a_routine_that_states_no_stay_for_its_targets_is_refused():
    """A newest-profile input naming activities of the released rules, which read a stay from a
    fixed duration its targets do not carry, is refused by name before any minute is taken."""
    document = square.compose(square.square_objects())
    released = deepcopy(document)
    released["routine"] = purposeful_routine(UNRECORDED_ROUTINE_VERSIONS).binding()
    for target in released["targets"]:
        target["activity"] = target["affordance"]
    released["document_sha256"] = input_sha256(released)
    with pytest.raises(ValueError, match="does not state every target's stay"):
        validate_society_input(released)
    # A positive control: the same input under the routine it was composed with is valid.
    for target, original in zip(released["targets"], document["targets"], strict=True):
        target["activity"] = original["activity"]
    released["routine"] = document["routine"]
    released["document_sha256"] = input_sha256(released)
    validate_society_input(released)


def test_every_reach_is_bounded_as_a_saved_world_bounds_reach():
    schema = society_catalogs.SCHEMAS[(PURPOSEFUL_CATALOG, 2)]
    check = dict(schema.fields)["reach_mm"]
    assert check("reach", MAX_REACH_MM) == MAX_REACH_MM
    with pytest.raises(CatalogError):
        check("reach", MAX_REACH_MM + 1)


@pytest.mark.postgres
def test_the_database_holds_which_inputs_record_a_routine(saved_world):
    """0108: a newest-profile input always records its routine, and no earlier one ever does."""
    world = saved_world
    connection = world["connection"]
    created = saved_api_society(world)
    stored = connection.execute(
        "select society_id,document from world_society_input where workspace_id=%s",
        (world["workspace"],),
    ).fetchone()
    assert stored["document"]["profile"] == AUTHORED_GROUND_INPUT_V3
    assert created["input_seq"] == 1
    without = deepcopy(stored["document"])
    del without["routine"]
    older = deepcopy(stored["document"])
    older["profile"] = "exulanica.society-input/authored-ground-v2"
    # A check passes on null: a routine naming no catalog versions, and an input that omits its
    # unread placements, would each be admitted by one if the rule were not asked whether it holds.
    unversioned = deepcopy(stored["document"])
    del unversioned["routine"]["catalog_versions"]
    unlisted = deepcopy(stored["document"])
    del unlisted["unread_placements"]
    for document, constraint in (
        (without, "world_society_input_routine_check"),
        (older, "world_society_input_routine_check"),
        (unversioned, "world_society_input_routine_check"),
        (unlisted, "world_society_input_unread_placements_check"),
    ):
        document["input_seq"] = 2
        document["document_sha256"] = input_sha256(document)
        with pytest.raises(psycopg.errors.CheckViolation) as refused, connection.transaction():
            connection.execute(
                "insert into world_society_input(workspace_id,society_id,input_seq,document,"
                "document_sha256) values(%s,%s,%s,%s,%s)",
                (
                    world["workspace"],
                    stored["society_id"],
                    2,
                    psycopg.types.json.Jsonb(document),
                    input_sha256(document),
                ),
            )
        assert refused.value.diag.constraint_name == constraint


def saved_api_society(world) -> dict:
    """A society brought into the saved world with one usable object, as the route does."""
    runtime = world["runtime"]
    connection, session = world["connection"], world["session"]
    version_id, region = world["binding"].version_id, world["binding"].region_id
    helpers.place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    with connection.transaction():
        return helpers.society_repository(world, runtime).create(
            version_id,
            place_id=world["binding"].place_id,
            region_id=region,
            seed="7a" * 32,
            actor=session.actor,
            profile=saved_api.V2,
            initial_input=runtime.initial_input(
                connection, session, version_id, world["binding"].place_id, region
            ),
        )
