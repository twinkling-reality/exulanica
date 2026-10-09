"""The Companion's things without a database: adding a thing by its kind, asking a being to act.

What the planner holds by construction, read against independent sources: the kinds offered are
the shipped catalog's (its lock file), laid out by hand-worked geometry, and a direct step is the
request the actions route's own builder makes on a real society of things composed in memory.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import math
import uuid
from pathlib import Path

import pytest
from exulanica.selection import action_plan as plan
from exulanica.selection import action_things as things
from exulanica.selection.action_plan import WorldEditOperation as Op
from exulanica.world.authored_delta import delta_sha256
from exulanica.world.objects import Transform
from exulanica.world.society import society_state_sha256
from exulanica.world.society_things import initial_things_society

import living_square_support as square
import things_society_support as support

VERSION = uuid.UUID(int=7)
BASE = "a" * 64
ROOT = Path(__file__).resolve().parents[1]
KINDS = ROOT / "assets/catalogs/things/kinds"
LOOKS = ROOT / "assets/catalogs/things/looks"


def _lock() -> dict[tuple[str, int], str]:
    document = json.loads((ROOT / "assets/catalogs/things/kinds.lock.json").read_text())
    return {(row["kind"], row["version"]): row["sha256"] for row in document["kinds"]}


def _first_look_container(kind: str, version: int) -> str | None:
    document = json.loads((KINDS / f"{kind}.v{version}.json").read_text())
    if not document["looks"]:
        return None
    first = document["looks"][0]
    look = json.loads((LOOKS / f"{first['look']}.v{first['version']}.json").read_text())
    return (look.get("container") or {}).get("sha256")


# -- the kinds offered -----------------------------------------------------------------------------


def test_every_kind_an_author_may_place_is_offered_at_its_newest_version():
    lock = _lock()
    newest: dict[str, int] = {}
    for kind, version in lock:
        newest[kind] = max(version, newest.get(kind, 0))
    offered = {choice.key: choice for choice in things.offered_kinds(frozenset())}
    # A visitor is decided for only from outside, so an author never places one.
    assert set(offered) == set(newest) - {"visitor"}
    for key, choice in offered.items():
        assert choice.version == newest[key]
        assert choice.sha256 == lock[(key, newest[key])]


def test_a_kind_drawn_by_a_reviewed_object_s_own_container_is_offered_as_that_object():
    bench = _first_look_container("bench", 1)
    assert bench is not None
    offered = {choice.key for choice in things.offered_kinds(frozenset({bench}))}
    assert "bench" not in offered and "cafe_table" in offered
    furniture = ("bench", "cafe_table", "lamp_post", "market_stall", "planter_tree")
    containers = {_first_look_container(kind, 1) for kind in (*furniture, "seating_planter")}
    remaining = {choice.key for choice in things.offered_kinds(frozenset(containers - {None}))}
    assert remaining.isdisjoint({*furniture, "seating_planter"})
    assert {"knight", "traveller", "lantern_spirit", "villager", "sword", "lantern", "well"} <= (
        remaining
    )


# -- where a thing goes ----------------------------------------------------------------------------

#: A well 3.5 m ahead of a person standing at the origin and looking north (toward -z): its box
#: is 1,600 mm square, so its circle is isqrt(800^2 + 800^2) + 1 = 1,132 mm.
WELL = things.Footprint(0, -3_500, (800, 800))
#: A being's circle: isqrt(300^2 + 300^2) + 1 = 425 mm.
BEING = (300, 300)
VIEWER = (0, 0)


def test_a_thing_stands_at_the_pointed_spot_when_it_is_free():
    assert things.lay_out(BEING, anchor=None, spot=(0, -3_500), viewer=VIEWER, taken=[]) == (
        0,
        -3_500,
    )


def test_a_taken_spot_sends_a_thing_ahead_onto_the_nearest_ring():
    # Ahead along the line the person looks: 2,500 mm farther north, 2,500 mm from the well's
    # centre against the 425 + 1,132 + 300 = 1,857 it needs.
    assert things.lay_out(BEING, anchor=None, spot=(0, -3_500), viewer=VIEWER, taken=[WELL]) == (
        0,
        -6_000,
    )


def test_beside_something_is_its_side_toward_the_person_first_then_its_right():
    # 1,132 + 425 + 300 and a millimetre = 1,858 mm from the well's centre, toward the person.
    toward = things.lay_out(BEING, anchor=WELL, spot=None, viewer=VIEWER, taken=[WELL])
    assert toward == (0, -3_500 + 1_858)
    bench = things.Footprint(0, -1_642, (900, 230))
    turned = things.lay_out(BEING, anchor=WELL, spot=None, viewer=VIEWER, taken=[WELL, bench])
    # The toward side turned by a quarter, counterclockwise from above: (0, 1) becomes (-1, 0).
    assert turned == (-1_858, -3_500)


def test_beside_something_off_the_axes_is_never_inside_it_once_rounded():
    # Toward a person diagonally away, the rounded point stays a full 1,857 mm from the centre.
    anchor = things.Footprint(-4_000, 2_000, (800, 800))
    point = things.lay_out(BEING, anchor=anchor, spot=None, viewer=(0, 4_000), taken=[anchor])
    assert point is not None
    assert math.hypot(point[0] + 4_000, point[1] - 2_000) >= 1_857


def test_a_thing_is_never_laid_out_where_the_person_stands():
    # Pointing at their own feet: the spot is within 425 + 1,000 mm of the person, so the thing
    # takes the first ring slot ahead instead, 2,500 mm along the way they look (north, -z).
    assert things.lay_out(BEING, anchor=None, spot=(0, -400), viewer=VIEWER, taken=[]) == (
        0,
        -2_900,
    )


def test_with_nowhere_near_free_nothing_is_laid_out():
    crowd = [
        things.Footprint(x, z, (2_000, 2_000))
        for x in (-6_000, 0, 6_000)
        for z in (-9_000, -3_500, 2_000)
    ]
    assert things.lay_out(BEING, anchor=WELL, spot=None, viewer=VIEWER, taken=crowd) is None
    assert things.lay_out(BEING, anchor=None, spot=(0, -3_500), viewer=VIEWER, taken=crowd) is None


@pytest.mark.parametrize(
    ("point", "yaw"),
    [
        # South of the person: it turns half way round to face north, toward them.
        ((0, 3_500), round(math.pi * 1_000_000)),
        # North of the person, facing south toward them: no turn.
        ((0, -3_500), 0),
        # East of the person: a quarter turn clockwise from above, in whole microradians taken
        # modulo 6,283,186 as a scene's things are turned.
        ((3_500, 0), -round(math.pi / 2 * 1_000_000) % 6_283_186),
    ],
)
def test_a_thing_turns_to_face_the_person(point, yaw):
    assert things.facing_yaw(point, VIEWER, otherwise=7) == yaw


def test_with_no_person_known_a_thing_keeps_the_page_s_yaw():
    assert things.facing_yaw((0, 3_500), None, otherwise=1_234) == 1_234


# -- what the drafter names, read back -------------------------------------------------------------


def _kind(key: str) -> things.KindChoice:
    return next(choice for choice in things.offered_kinds(frozenset()) if choice.key == key)


def _being(being_id: str, name: str, *, crossed: bool = False) -> things.BeingRead:
    return things.BeingRead(
        id=being_id,
        display_name=name,
        kind_label="visitor" if crossed else "traveller",
        look_label=None if crossed else "blocky traveller",
        came_by="crossed" if crossed else "placed",
        footprint=things.Footprint(3_000, -3_000, BEING),
    )


def _read(**changes) -> things.ThingsRead:
    society = things.SocietyRead(
        society_id=str(uuid.UUID(int=9)),
        engine="exulanica-society/v7",
        region_id="region:starter",
        tick=4,
        state_sha256="b" * 64,
        state={"input_seq": 1},
        document={"targets": []},
        newest_input_seq=1,
        beings=(
            _being(str(uuid.UUID(int=1)), "Traveller"),
            _being(str(uuid.UUID(int=2)), "Traveller 2"),
            _being(str(uuid.UUID(int=3)), "Visitor", crossed=True),
        ),
        places=(
            things.PlaceRead("thing:well:visit", "well", "visit"),
            things.PlaceRead("authored:x:bench:rest", "bench", "rest"),
        ),
    )
    values = {
        "kinds": tuple(_kind(key) for key in ("knight", "lantern", "lantern_spirit", "well")),
        "placed": (
            things.PlacedRead(
                "well",
                "well",
                None,
                "region:starter",
                Transform(0, 0, -3_500, 0, 1000),
                WELL,
            ),
        ),
        "society": society,
        "elevation_mm": 0,
        "taken": (("well", WELL),),
        "placed_count": 1,
        "placed_ids": frozenset({"well"}),
        "anchors": {("thing", "well"): (WELL, "region:starter", 0)},
        "newest_objects": {},
    }
    values.update(changes)
    return things.ThingsRead(**values)


def _world(read: things.ThingsRead | None = None) -> plan._World:
    read = _read() if read is None else read
    matrix = {
        row.commit: {
            "operation": row.commit,
            "bind": {"version_id": str(VERSION)},
            "requires": ["world.write"],
            "permitted": True,
            "state": "available",
            "code": None,
            "effects": [],
        }
        for row in plan._MATRIX.values()
    }
    kinds, placed, beings, places = plan._thing_choices(read)
    return plan._World(
        world_id="world:authored:test",
        version_id=VERSION,
        state_sha256=BASE,
        edit_seq=3,
        assets=(plan._Choice("cc0.bench", "cc0.bench", "Bench", "A wooden bench."),),
        objects=(plan._Choice("object-1", "object:bench-for-ada", "Bench"),),
        arrangements=(),
        arrangement_versions={},
        descriptors=matrix,
        object_ids=frozenset({"object:bench-for-ada"}),
        region_ids=("region:starter",),
        things=read,
        actor=uuid.UUID(int=0xAC),
        kinds=kinds,
        placed=placed,
        beings=beings,
        places=places,
    )


def _context(**overrides) -> plan._Context:
    values = {
        "version_id": str(VERSION),
        "base_state_sha256": BASE,
        "origin_role": "fictional",
        "context": {
            "placement": {
                "region_id": "region:starter",
                "transform": {
                    "x_mm": 0,
                    "y_mm": 0,
                    "z_mm": -3_500,
                    "yaw_microradians": 0,
                    "scale_milli": 1000,
                },
            },
            "viewer": {"x_mm": 0, "z_mm": 0, "yaw_microradians": 0, "region_id": None},
            "selected_object_id": None,
        },
        "saved_entry": None,
    }
    values.update(overrides)
    return plan._Context.read(values)


def _draft(*steps):
    return plan._typed_from_draft(
        [{"operation": operation, "options": list(options)} for operation, *options in steps],
        _world(),
    )


def test_a_kind_named_alone_is_the_thing_added_with_an_id_minted_for_it():
    verdict = _draft(("place_thing", "knight"))
    assert verdict.refusal is None and verdict.clarification is None
    [action] = verdict.actions
    assert (action.operation, action.kind, action.kind_version, action.near) == (
        Op.PLACE_THING,
        "knight",
        _kind("knight").version,
        None,
    )
    assert things.valid_minted_id(action.thing_id, "knight")


def test_a_thing_goes_beside_what_the_step_names():
    [action] = _draft(("place_thing", "knight", "thing-1")).actions
    assert action.near == "thing:well"
    [beside] = _draft(("place_thing", "lantern", "being-1")).actions
    assert beside.near == f"being:{uuid.UUID(int=1)}"


def test_a_later_step_names_the_thing_an_earlier_step_adds_by_the_id_it_was_minted():
    verdict = _draft(("place_thing", "well"), ("place_thing", "knight", "well"))
    first, second = verdict.actions
    assert (second.kind, second.near) == ("knight", f"thing:{first.thing_id}")


def test_two_of_a_kind_are_two_things_neither_beside_the_other():
    first, second = _draft(("place_thing", "knight"), ("place_thing", "knight")).actions
    assert (first.kind, second.kind, second.near) == ("knight", "knight", None)
    assert first.thing_id != second.thing_id


def test_two_kinds_neither_added_before_are_asked_about():
    verdict = _draft(("place_thing", "knight", "lantern"))
    assert verdict.clarification["code"] == "kind_ambiguous"
    assert [c["value"] for c in verdict.clarification["candidates"]] == ["knight", "lantern"]
    assert verdict.clarification["actions"][0]["kind"] is None


def test_two_things_it_could_go_beside_are_asked_about_by_name():
    verdict = _draft(("place_thing", "lantern", "being-1", "being-2"))
    assert verdict.clarification["code"] == "anchor_ambiguous"
    assert [c["title"] for c in verdict.clarification["candidates"]] == [
        "Traveller (kind: traveller; looks like: blocky traveller)",
        "Traveller 2 (kind: traveller; looks like: blocky traveller)",
    ]


def test_the_list_a_label_came_from_says_whether_a_thing_or_an_object_is_added():
    [thing] = _draft(("place_object", "knight")).actions
    [bench] = _draft(("place_thing", "cc0.bench")).actions
    assert (thing.operation, thing.kind) == (Op.PLACE_THING, "knight")
    assert (bench.operation, bench.asset_key) == (Op.PLACE_OBJECT, "cc0.bench")
    two = _draft(("place_object", "cc0.bench"), ("place_object", "cc0.bench")).actions
    assert [action.asset_key for action in two] == ["cc0.bench", "cc0.bench"]


def test_a_being_is_asked_to_go_to_or_use_one_place():
    [go] = _draft(("send_to", "being-1", "place-1")).actions
    assert (go.operation, go.act, go.subject_id, go.target_id) == (
        Op.DIRECT_THING,
        "go_to",
        str(uuid.UUID(int=1)),
        "thing:well:visit",
    )
    verdict = _draft(("use", "being-1", "place-1", "place-2"))
    assert verdict.clarification["code"] == "place_ambiguous"


@pytest.mark.parametrize(
    ("action", "overrides", "code"),
    [
        (
            plan._Action(Op.PLACE_THING, kind="knight", kind_version=2),
            {"origin_role": None},
            "origin_role_required",
        ),
        (
            plan._Action(Op.PLACE_THING, kind="knight", kind_version=2),
            {"context": {"placement": None, "viewer": None, "selected_object_id": None}},
            "placement_required",
        ),
        (
            plan._Action(Op.DIRECT_THING, act="go_to", target_id="thing:well:visit"),
            {},
            "being_required",
        ),
        (plan._Action(Op.DIRECT_THING, act="go_to", subject_id="x"), {}, "place_required"),
    ],
)
def test_what_a_thing_step_needs_and_nobody_supplied_is_asked_for(action, overrides, code):
    asked = plan._requirements([action], _context(**overrides), _world())
    assert asked is not None and asked["code"] == code


def test_a_thing_step_beside_something_needs_no_pointed_spot():
    action = plan._Action(Op.PLACE_THING, kind="knight", kind_version=2, near="thing:well")
    none = {"context": {"placement": None, "viewer": None, "selected_object_id": None}}
    assert plan._requirements([action], _context(**none), _world()) is None


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ({"operation": "place_thing", "kind": "dragon"}, "not_in_catalogue"),
        ({"operation": "place_thing", "kind": "knight", "kind_version": 1}, "not_in_catalogue"),
        ({"operation": "place_thing", "kind": "knight", "thing_id": "mine"}, "not_understood"),
        ({"operation": "place_thing", "kind": "knight", "near": "somewhere"}, "not_understood"),
        ({"operation": "direct_thing", "act": "dance"}, "action_not_offered"),
    ],
)
def test_a_typed_thing_step_a_client_sends_back_is_checked_against_the_reads(raw, code):
    verdict = plan._typed_from_request([raw], _world())
    assert verdict.refusal is not None and verdict.refusal["code"] == code


def test_a_being_from_outside_reaches_the_drafter_by_kind_and_number_only():
    rendered = plan._render_options(_world())
    assert "being-3: Visitor (a visitor from outside)" in rendered
    assert "being-1: Traveller (kind: traveller; looks like: blocky traveller)" in rendered
    assert "THINGS THAT CAN BE ADDED" in rendered and "knight: knight." in rendered
    assert "place-1: the well, to visit" in rendered


def test_the_form_offers_every_option_the_reads_listed_and_no_other_field():
    schema = plan._world_edit_form(_world()).model_json_schema()
    step = schema["$defs"]["WorldEditStep"]["properties"]
    assert set(step) == {"operation", "options"}
    assert step["options"]["items"]["enum"] == list(plan.iter_labels(_world()))
    assert step["options"]["maxItems"] == plan.MAX_CANDIDATES
    assert schema["properties"]["steps"]["maxItems"] == plan.MAX_STEPS


# -- preparing a place step ------------------------------------------------------------------------


def _prepare(action, *, read=None, **context):
    return plan._prepared_things_step(0, action, _context(**context), _world(read))


def test_a_place_step_is_the_add_thing_request_beside_what_it_names():
    action = plan._Action(
        Op.PLACE_THING,
        kind="knight",
        kind_version=_kind("knight").version,
        thing_id="companion:knight:0123456789ab",
        near="thing:well",
    )
    step = _prepare(action)
    assert step["state"] == "prepared" and step["code"] is None
    assert step["operation"] == "POST /world/versions/{version_id}/things"
    assert step["preview"] is None
    assert step["pins"] == {"base_state_sha256": BASE, "edit_seq": 3}
    lock = _lock()
    assert step["body"] == {
        "base_state_sha256": BASE,
        "thing_id": "companion:knight:0123456789ab",
        "kind": {
            "kind": "knight",
            "version": _kind("knight").version,
            "sha256": lock[("knight", _kind("knight").version)],
        },
        "region_id": "region:starter",
        # Beside the well on its side toward the person; facing them, north of them: no turn.
        "pose": {"x_mm": 0, "y_mm": 0, "z_mm": -1_642, "yaw_microradians": 0},
        "origin_role": "fictional",
        "saved_entry": None,
    }


def test_a_thing_step_names_what_it_names_as_the_reads_label_it():
    place = plan._Action(Op.PLACE_THING, kind="lantern", kind_version=1, near="thing:well")
    beside = plan._Action(
        Op.PLACE_THING, kind="lantern", kind_version=1, near=f"being:{uuid.UUID(int=2)}"
    )
    ask = plan._Action(
        Op.DIRECT_THING, act="use", subject_id=str(uuid.UUID(int=1)), target_id="thing:well:visit"
    )
    world = _world()
    assert plan._titles(place, world) == {"kind": "lantern", "near": "well"}
    assert plan._titles(beside, world) == {"kind": "lantern", "near": "Traveller 2"}
    assert plan._titles(ask, world) == {
        "subject": "Traveller",
        "place": "well",
        "affordance": "visit",
        "act": "use",
    }


def test_a_place_step_the_route_would_refuse_is_blocked_by_the_route_s_code():
    action = plan._Action(
        Op.PLACE_THING, kind="knight", kind_version=_kind("knight").version, thing_id="well"
    )
    taken = _prepare(action)
    assert (taken["state"], taken["code"]) == ("blocked", "invalid_object_state")
    full = _prepare(dataclasses.replace(action, thing_id=None), read=_read(placed_count=256))
    assert (full["state"], full["code"]) == ("blocked", "thing_limit_reached")
    gone = _prepare(dataclasses.replace(action, thing_id=None, near="thing:lost"))
    assert (gone["state"], gone["code"]) == ("blocked", "anchor_not_here")
    crowd = tuple(
        (f"o{x}{z}", things.Footprint(x, z, (2_000, 2_000)))
        for x in (-6_000, 0, 6_000)
        for z in (-9_000, -3_500, 2_000)
    )
    nowhere = _prepare(dataclasses.replace(action, thing_id=None), read=_read(taken=crowd))
    assert (nowhere["state"], nowhere["code"]) == ("blocked", "no_free_place_near")


# -- preparing a direct step on a real society of things -------------------------------------------

WELL_THING = support.thing("well", "well", 2, -4_000, 2_000)
KNIGHT = support.thing("knight", "knight", 2, 3_000, 3_000)


def _society(*, queued: bool = False, crossed: bool = False):
    held = tuple(square.square_objects())
    placed = (WELL_THING, KNIGHT)
    version = dataclasses.replace(
        square.version(held),
        things=placed,
        state_sha256=delta_sha256(
            objects=held,
            element_overrides=(),
            environment_instances=(),
            point_map_instances=(),
            things=placed,
        ),
    )
    document = support.compose(placed)
    state = initial_things_society(support.SOCIETY, support.SEED, document, population=2)
    if crossed:
        state = copy.deepcopy(state)
        knight = next(p for p in state["inhabitants"] if p["came_by"] == "placed")
        knight.update(
            came_by="crossed",
            placed_id=None,
            placed_at_mm=None,
            crossing={"arrival_id": "a", "bridge": "b", "grant_id": str(uuid.UUID(int=1))},
        )
    row = {
        "society_id": support.SOCIETY,
        "engine_version": "exulanica-society/v7",
        "region_id": "region:starter",
        "current_tick": state["tick"],
        "state_sha256": society_state_sha256(state),
        "state": state,
    }
    newest = document["input_seq"] + (1 if queued else 0)
    return things.read_things(
        world_id=document["world_id"],
        version=version,
        reviewed={},
        looks={},
        society=(row, document, newest, frozenset()),
        elevation_mm=0,
        viewer=None,
    )


def _knight_id(read):
    return next(b.id for b in read.society.beings if b.display_name == "Knight")


def _well_place(read):
    return next(p.target_id for p in read.society.places if p.title == "well")


def test_a_direct_step_is_the_request_the_route_s_own_builder_makes_now():
    read = _society()
    knight, well = _knight_id(read), _well_place(read)
    body, code = things.direct_body(
        read.society,
        requested_by=uuid.UUID(int=0xAC),
        subject_id=knight,
        act="go_to",
        target_id=well,
    )
    assert code is None
    assert body["intent"] == {"kind": "go_to", "target_id": well}
    assert (body["base_tick"], body["base_state_sha256"]) == (
        read.society.tick,
        read.society.state_sha256,
    )
    again, _ = things.direct_body(
        read.society,
        requested_by=uuid.UUID(int=0xBD),
        subject_id=knight,
        act="go_to",
        target_id=well,
    )
    # The same request at the same minute is one request, whoever prepares it.
    assert again["idempotency_key"] == body["idempotency_key"]
    used, _ = things.direct_body(
        read.society, requested_by=uuid.UUID(int=0xAC), subject_id=knight, act="use", target_id=well
    )
    assert used["intent"] == {"kind": "perform", "target_id": well, "affordance": "visit"}
    assert used["idempotency_key"] != body["idempotency_key"]


def test_a_direct_step_waits_for_the_minute_that_takes_a_queued_input_in():
    read = _society(queued=True)
    body, code = things.direct_body(
        read.society,
        requested_by=uuid.UUID(int=0xAC),
        subject_id=_knight_id(read),
        act="go_to",
        target_id=_well_place(read),
    )
    assert (body, code) == (None, "society_input_queued")
    assert code in things.WAIT_CODES


def test_a_being_already_asked_at_this_minute_waits_for_the_minute_that_takes_it():
    read = _society()
    knight, well = _knight_id(read), _well_place(read)
    ask = {
        "requested_by": uuid.UUID(int=0xAC),
        "subject_id": knight,
        "act": "go_to",
        "target_id": well,
    }
    # The positive control: nobody asked yet, so the request is made.
    assert things.direct_body(read.society, **ask)[1] is None
    asked = dataclasses.replace(read.society, asked=frozenset({knight}))
    assert things.direct_body(asked, **ask) == (None, "inhabitant_action_in_progress")
    assert "inhabitant_action_in_progress" in things.WAIT_CODES


def test_a_full_destination_waits_for_a_free_place_rather_than_refusing():
    read = _society()
    knight, well = _knight_id(read), _well_place(read)
    ask = {
        "requested_by": uuid.UUID(int=0xAC),
        "subject_id": knight,
        "act": "go_to",
        "target_id": well,
    }
    # The positive control: the well has room, so the request is made.
    assert things.direct_body(read.society, **ask)[1] is None
    state = copy.deepcopy(dict(read.society.state))
    [target] = [t for t in read.society.document["targets"] if t["target_id"] == well]
    others = [p for p in state["inhabitants"] if p["id"] != knight]
    assert len(others) >= len(target["place_node_ids"])
    nodes = {n["node_id"]: n for n in read.society.document["navigation"]["nodes"]}
    for person, place in zip(others, target["place_node_ids"], strict=False):
        # Each of the well's places taken by somebody standing at it.
        person["location"] = {"node_id": place, "edge": None}
        person["position_mm"] = list(nodes[place]["position_mm"])
    full = dataclasses.replace(read.society, state=state, state_sha256=society_state_sha256(state))
    assert things.direct_body(full, **ask) == (None, "destination_full")
    assert "destination_full" in things.WAIT_CODES


def test_a_town_s_places_are_named_as_the_town_names_them():
    import test_walking_surfaces_v3 as town

    document = town._compose(*town._scene_things())
    destinations = {
        d["destination_id"].split(":", 1)[1]: d for d in town._town()[1]["destinations"]
    }
    state = initial_things_society(town.SOCIETY, town.SEED, document, population=2)
    row = {
        "society_id": town.SOCIETY,
        "engine_version": "exulanica-society/v7",
        "region_id": "region:starter",
        "current_tick": state["tick"],
        "state_sha256": society_state_sha256(state),
        "state": state,
    }
    read = things.read_things(
        world_id=document["world_id"],
        version=dataclasses.replace(square.version(()), things=()),
        reviewed={},
        looks={},
        society=(row, document, document["input_seq"], frozenset()),
        elevation_mm=0,
        viewer=None,
    )
    titles = {place.target_id: place.title for place in read.society.places}
    named = [
        t
        for t in document["targets"]
        if t.get("enabled") and t["origin"] in ("premises", "furniture")
    ]
    # The drafter is shown at most 24 places; among them, at least one premises with a number.
    listed = [t for t in named if t["target_id"] in titles]
    assert any(t["place"]["label"] and t["place"]["address_number"] is not None for t in listed)
    for target in listed:
        destination = destinations[target["object_id"]]
        label, number = destination["label"], destination["address_number"]
        expected = (
            "a place"
            if label is None
            else label
            if number is None
            else f"{label} at number {number}"
        )
        assert titles[target["target_id"]] == expected


def test_a_being_its_own_program_decides_for_is_refused_by_the_route_s_name():
    read = _society(crossed=True)
    visitor = next(b for b in read.society.beings if b.from_outside)
    body, code = things.direct_body(
        read.society,
        requested_by=uuid.UUID(int=0xAC),
        subject_id=visitor.id,
        act="go_to",
        target_id=_well_place(read),
    )
    assert (body, code) == (None, "decided_from_outside")
    assert visitor.look_label is None
