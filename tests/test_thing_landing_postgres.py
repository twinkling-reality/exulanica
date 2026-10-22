"""A placed thing is moved or placed only where the world's ground takes it, and a move's preview
says so first.

On a farm made from the fixture kind under a fixed identity, with a duck pond and a barn read from
the farm's own records, through the routes as a deployment serves them:

*   a well moved into the pond, inside the barn, past the farm's edge or into the air is refused by
    name (422, one code per refusal, ``where`` naming what refused it, a sentence to read), and
    nothing is written: the version's state and its edit log are as they were;
*   the same well moved onto open ground is moved, and the people of the farm's society of things
    take the move as their next input;
*   the move's preview gives the verdict the move then gives: a ready preview's ``after`` is what
    the move records, a refused one's reason and ``where`` are the move's; the removal preview is
    the removal; the undo preview on the things' path names the move it would undo;
*   while the kind worker is still making the farm's place, a move is answered 503 with
    Retry-After and writes nothing, and asked again once the place is made, it is moved; after the
    worker lost the place, a move is made in one ask;
*   a well placed in the pond, inside the barn, past the edge or in the air is refused as a move
    there is, and nothing is written; a creature made from words (a kind its workspace keeps) is
    placed where its maker puts it, unchecked.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.grammars.site.records import SiteAreaRecord, SiteStructureRecord
from exulanica.world import saved_entries
from exulanica.world.composers import composer_module
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.worker import JobOutcome, Kept, kind_worker
from exulanica.world.thing_store import ThingStore

from test_society_made_kinds import canary_creature
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
SITE = composer_module("site-plan", 1)
V7 = "exulanica-society/v7"
FARM = "world:generated:00000000-0000-4000-8000-00000000f0a1"
WELL = {"kind": "well", "version": 2}


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _the_same_farm_on_every_run(monkeypatch):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: FARM)


def _uploaded() -> dict[str, Any]:
    document = json.loads((FIXTURES / "fixture-farm.json").read_text(encoding="utf-8"))
    document["origin"] = "uploaded"
    document["provenance"] = {"by": "a test creator"}
    return document


def _farm(api) -> tuple[dict[str, Any], tuple[object, ...]]:
    """The farm's saved entry and the records the same kind composes for its identity."""
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, societies_of_things=True
    )
    kept = api.post("/worlds/kinds", {"document": _uploaded()})
    assert kept.status_code == 201, kept.text
    made_world = api.post(
        "/worlds/kinds/fixture_farm/worlds", {"preset": "small_farm", "title": "A farm"}
    )
    assert made_world.status_code == 201, made_world.text
    entry = made_world.json()
    assert entry["world_id"] == FARM
    read = read_kind(_uploaded())
    return entry, SITE.compose_kind(read, read.values("small_farm"), FARM).records


def _root(entry: dict) -> str:
    return f"/world/versions/{entry['authored_version_id']}"


def _scope(entry: dict) -> str:
    return f"?world_id={entry['world_id']}"


def _version(api, entry: dict) -> dict:
    read = api.get(_root(entry) + _scope(entry))
    assert read.status_code == 200, read.text
    return read.json()


def _recorded_after(api, edit: dict) -> dict:
    """The document the move or removal stored as its ``after``, read from the edit log itself."""
    with api.database.session(api.repository.workspace_id) as connection:
        row = connection.execute(
            "select after_document from world_alternate_version_edit "
            "where workspace_id=%s and edit_id=%s",
            (api.repository.workspace_id, uuid.UUID(edit["edit_id"])),
        ).fetchone()
    assert row is not None
    return dict(row["after_document"])


def _pose(x_mm: int, z_mm: int, y_mm: int = 0) -> dict[str, int]:
    return {"x_mm": x_mm, "y_mm": y_mm, "z_mm": z_mm, "yaw_microradians": 0}


def _open_ground(entry: dict) -> tuple[int, int]:
    """Three metres east of where a person arrives, which the farm keeps clear to walk."""
    east, _height, south = entry["generated_site"]["arrival_mm"]
    return east + 3_000, south


def _middle(record: Any) -> tuple[int, int]:
    """A record's middle in the region's frame (east, south) from its site box (east, north)."""
    return (record.min_x_mm + record.max_x_mm) // 2, -((record.min_y_mm + record.max_y_mm) // 2)


def _pond(records) -> tuple[int, int]:
    return _middle(next(r for r in records if isinstance(r, SiteAreaRecord) and "water" in r.roles))


def _barn(records) -> tuple[int, int]:
    return _middle(next(r for r in records if isinstance(r, SiteStructureRecord)))


def _placed_well(api, entry: dict) -> dict:
    x, z = _open_ground(entry)
    base = _version(api, entry)["state_sha256"]
    placed = api.post(
        _root(entry) + "/things" + _scope(entry),
        {
            "base_state_sha256": base,
            "thing_id": "well",
            "kind": WELL,
            "region_id": "region:generated",
            "pose": _pose(x, z),
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text
    return placed.json()


def _move(api, entry: dict, version: dict, pose: dict, *, preview: bool = False):
    tail = "/things/well/move" + ("/preview" if preview else "")
    return api.post(
        _root(entry) + tail + _scope(entry),
        {"base_state_sha256": version["state_sha256"], "pose": pose},
    )


def _refused_cases(entry: dict, records) -> dict[str, tuple[dict[str, int], dict[str, Any]]]:
    pond_x, pond_z = _pond(records)
    barn_x, barn_z = _barn(records)
    x, z = _open_ground(entry)
    return {
        "into the duck pond": (
            _pose(pond_x, pond_z),
            {"code": "thing_landing_blocked", "where": {"part": "water", "label": "duck pond"}},
        ),
        "inside the barn": (
            _pose(barn_x, barn_z),
            {"code": "thing_landing_blocked", "where": {"part": "structure"}},
        ),
        "past the farm's edge": (
            _pose(x + 500_000, z),
            {"code": "thing_landing_outside", "where": {"part": None}},
        ),
        "a metre into the air": (
            _pose(x, z, 1_000),
            {"code": "thing_landing_off_ground", "where": {"height_above_mm": 1_000}},
        ),
    }


@pytest.mark.parametrize(
    "case",
    ["into the duck pond", "inside the barn", "past the farm's edge", "a metre into the air"],
)
def test_a_well_moved_where_the_farm_does_not_take_it_is_refused_and_nothing_is_written(made, case):
    api = made
    entry, records = _farm(api)
    version = _placed_well(api, entry)
    pose, expected = _refused_cases(entry, records)[case]

    moved = _move(api, entry, version, pose)

    assert moved.status_code == 422, moved.text
    problem = moved.json()
    assert problem["code"] == expected["code"]
    for key, value in expected["where"].items():
        assert problem["where"][key] == value, problem
    assert problem["detail"] and "_" not in problem["detail"]
    after = _version(api, entry)
    assert (after["state_sha256"], after["edit_seq"]) == (
        version["state_sha256"],
        version["edit_seq"],
    )
    assert after["edits"] == version["edits"]


@pytest.mark.parametrize(
    "case",
    ["into the duck pond", "inside the barn", "past the farm's edge", "a metre into the air"],
)
def test_a_refused_move_s_preview_names_the_same_refusal_first(made, case):
    api = made
    entry, records = _farm(api)
    version = _placed_well(api, entry)
    pose, _expected = _refused_cases(entry, records)[case]

    preview = _move(api, entry, version, pose, preview=True)
    moved = _move(api, entry, version, pose)

    assert preview.status_code == 200, preview.text
    verdict = preview.json()
    assert verdict["availability"] == "blocked"
    assert verdict["blocked_reason"] == moved.json()["code"]
    assert verdict["blocked_detail"] == moved.json()["detail"]
    assert verdict["landing"] == {"checked": True, "where": moved.json()["where"]}
    assert verdict["would_change"]["after"] is None


def test_a_well_moved_onto_open_ground_is_moved_as_its_preview_said(made):
    api = made
    entry, _records = _farm(api)
    version = _placed_well(api, entry)
    x, z = _open_ground(entry)
    pose = {**_pose(x + 2_000, z), "yaw_microradians": 785_398}

    preview = _move(api, entry, version, pose, preview=True)
    assert preview.status_code == 200, preview.text
    verdict = preview.json()
    assert (verdict["availability"], verdict["landing"]) == (
        "ready",
        {"checked": True, "rest_y_mm": 0},
    )
    assert _version(api, entry) == version

    moved = _move(api, entry, version, pose)
    assert moved.status_code == 200, moved.text
    [well] = [thing for thing in moved.json()["things"] if thing["thing_id"] == "well"]
    assert well["transform"]["x_mm"] == x + 2_000
    assert moved.json()["edits"][-1]["kind"] == "move_thing"
    assert verdict["would_change"]["after"] == _recorded_after(api, moved.json()["edits"][-1])


def test_the_farm_s_people_take_the_move_as_their_next_input(made):
    api = made
    entry, _records = _farm(api)
    _placed_well(api, entry)
    created = api.post(
        _root(entry) + "/society" + _scope(entry), {"region_id": "region:generated", "profile": V7}
    )
    assert created.status_code in (200, 201), created.text
    version = _version(api, entry)
    x, z = _open_ground(entry)
    moved = _move(api, entry, version, _pose(x + 4_000, z))
    assert moved.status_code == 200, moved.text


def test_the_removal_and_undo_previews_are_the_removal_and_the_undo(made):
    api = made
    entry, _records = _farm(api)
    version = _placed_well(api, entry)
    x, z = _open_ground(entry)
    moved = _move(api, entry, version, _pose(x + 2_000, z)).json()

    undo = api.post(
        _root(entry) + "/things/undo/preview" + _scope(entry),
        {"base_state_sha256": moved["state_sha256"]},
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["would_change"]["undoes"]["kind"] == "move_thing"
    assert undo.json()["would_change"]["subject_id"] == "well"

    removal = api.post(
        _root(entry) + "/things/well/remove/preview" + _scope(entry),
        {"base_state_sha256": moved["state_sha256"]},
    )
    assert removal.status_code == 200, removal.text
    removed = api.post(
        _root(entry) + "/things/well/remove" + _scope(entry),
        {"base_state_sha256": moved["state_sha256"]},
    )
    assert removed.status_code == 200, removed.text
    assert removal.json()["would_change"]["after"] == _recorded_after(
        api, removed.json()["edits"][-1]
    )
    again = api.post(
        _root(entry) + "/things/well/remove/preview" + _scope(entry),
        {"base_state_sha256": removed.json()["state_sha256"]},
    )
    assert again.json()["blocked_reason"] == "invalid_object_state"


def test_a_stale_base_is_answered_as_stale_whatever_the_thing(made):
    api = made
    entry, _records = _farm(api)
    version = _placed_well(api, entry)
    stale = {**version, "state_sha256": "0" * 64}
    for thing in ("well", "nobody-placed-this"):
        moved = api.post(
            _root(entry) + f"/things/{thing}/move" + _scope(entry),
            {"base_state_sha256": stale["state_sha256"], "pose": _pose(*_open_ground(entry))},
        )
        assert (moved.status_code, moved.json()["code"]) == (409, "stale_object_base"), moved.text


def _place_runs(monkeypatch, answer):
    """The kind worker's place asks answered by ``answer``, every other job as it would be."""
    worker = kind_worker()
    monkeypatch.setattr(worker, "places", Kept(16, copies=True))
    run = worker.run

    def asked(key: str, seconds: float, *args: Any, **kwargs: Any) -> JobOutcome:
        if key.startswith("place:"):
            return answer(run, key, seconds, *args, **kwargs)
        return run(key, seconds, *args, **kwargs)

    monkeypatch.setattr(worker, "run", asked)


def test_a_move_while_the_place_is_being_made_asks_to_come_back_and_writes_nothing(
    made, monkeypatch
):
    api = made
    entry, _records = _farm(api)
    version = _placed_well(api, entry)
    x, z = _open_ground(entry)
    with monkeypatch.context() as busy:
        _place_runs(busy, lambda *_args, **_kwargs: JobOutcome("busy"))
        moved = _move(api, entry, version, _pose(x + 2_000, z))
        assert moved.status_code == 503, moved.text
        assert moved.headers["Retry-After"] == "2"
        assert _version(api, entry) == version
    moved = _move(api, entry, version, _pose(x + 2_000, z))
    assert moved.status_code == 200, moved.text


def test_a_move_after_the_worker_lost_the_place_is_made_in_one_ask(made, monkeypatch):
    """A place takes time to make, so only an ask that waits for it gets one: a move made in one
    ask here is one that waited, never one that happened to find it finished."""
    api = made
    entry, _records = _farm(api)
    version = _placed_well(api, entry)
    x, z = _open_ground(entry)

    def only_when_waited_for(run, key, seconds, *args, **kwargs):
        return JobOutcome("overran") if seconds == 0 else run(key, seconds, *args, **kwargs)

    _place_runs(monkeypatch, only_when_waited_for)
    moved = _move(api, entry, version, _pose(x + 2_000, z))
    assert moved.status_code == 200, moved.text


def test_another_world_s_version_is_answered_as_the_move_answers_it(made):
    api = made
    entry, _records = _farm(api)
    version = _placed_well(api, entry)
    other = f"/world/versions/{uuid.uuid4()}"
    for tail in ("/things/well/move/preview", "/things/well/move"):
        answer = api.post(
            other + tail + _scope(entry),
            {"base_state_sha256": version["state_sha256"], "pose": _pose(*_open_ground(entry))},
        )
        assert answer.status_code == 404, answer.text


def _place(api, entry: dict, thing_id: str, kind: dict, pose: dict):
    return api.post(
        _root(entry) + "/things" + _scope(entry),
        {
            "base_state_sha256": _version(api, entry)["state_sha256"],
            "thing_id": thing_id,
            "kind": kind,
            "region_id": "region:generated",
            "pose": pose,
            "origin_role": "fictional",
        },
    )


@pytest.mark.parametrize(
    "case",
    ["into the duck pond", "inside the barn", "past the farm's edge", "a metre into the air"],
)
def test_a_well_placed_where_the_farm_does_not_take_it_is_refused_and_nothing_is_written(
    made, case
):
    api = made
    entry, records = _farm(api)
    before = _version(api, entry)
    pose, expected = _refused_cases(entry, records)[case]

    placed = _place(api, entry, "well", WELL, pose)

    assert placed.status_code == 422, placed.text
    problem = placed.json()
    assert problem["code"] == expected["code"]
    for key, value in expected["where"].items():
        assert problem["where"][key] == value, problem
    assert problem["detail"] and "_" not in problem["detail"]
    assert _version(api, entry) == before


def test_a_well_placed_on_a_well_already_there_is_refused_by_its_name(made):
    api = made
    entry, _records = _farm(api)
    first = _placed_well(api, entry)

    placed = _place(api, entry, "second-well", WELL, _pose(*_open_ground(entry)))

    assert placed.status_code == 422, placed.text
    assert placed.json()["code"] == "thing_landing_blocked"
    assert placed.json()["where"]["part"] == "thing"
    assert _version(api, entry) == first


def test_a_creature_made_from_words_is_placed_where_its_maker_puts_it_unchecked(made):
    """The creature maker stands what it made in front of the person, wherever that is; a kind its
    workspace keeps is not held to the ground's rule when placed."""
    api = made
    entry, records = _farm(api)
    creature = canary_creature("crocodile", hands=True)
    with api.database.session(api.repository.workspace_id) as session:
        ThingStore(session, api.repository.workspace_id, api.store).keep_creature(
            creature, created_by=api.actor
        )

    placed = _place(
        api,
        entry,
        "creature:0000aaaa",
        {"source": "workspace", "sha256": creature.kind.sha256},
        _pose(*_pond(records)),
    )

    assert placed.status_code == 201, placed.text


def test_a_placing_while_the_place_is_being_made_asks_to_come_back_and_writes_nothing(
    made, monkeypatch
):
    api = made
    entry, _records = _farm(api)
    before = _version(api, entry)
    with monkeypatch.context() as busy:
        _place_runs(busy, lambda *_args, **_kwargs: JobOutcome("busy"))
        placed = _place(api, entry, "well", WELL, _pose(*_open_ground(entry)))
        assert placed.status_code == 503, placed.text
        assert placed.headers["Retry-After"] == "2"
        assert _version(api, entry) == before
    placed = _place(api, entry, "well", WELL, _pose(*_open_ground(entry)))
    assert placed.status_code == 201, placed.text
