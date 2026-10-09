"""The Companion's action planner without a database: its form, its validation and its digest.

Everything here is a rule the planner holds by construction: the model is offered only options the
reads listed, objects only by opaque label, an unavailable operation is refused by the capability
read's own code, ambiguity is asked about before anything is prepared, and a plan's digest names
its content and nothing about how it was paid for.
"""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest
from exulanica.models.manifest import Role
from exulanica.selection import action_outcome
from exulanica.selection import action_plan as plan
from exulanica.selection.action_plan import WorldEditOperation as Op
from exulanica.selection.calls import CallLog
from exulanica.selection.request_names import RequestNames
from exulanica.selection.validation import Session

VERSION = uuid.UUID(int=7)


def _descriptor(operation: str, *, state="available", code=None, permitted=True) -> dict:
    return {
        "operation": operation,
        "bind": {"version_id": str(VERSION)},
        "requires": ["world.write"],
        "permitted": permitted,
        "state": state,
        "code": code,
        "effects": [],
    }


def _world(*, objects: bool = True, descriptors: dict | None = None) -> plan._World:
    matrix = {row.commit: _descriptor(row.commit) for row in plan._MATRIX.values()}
    return plan._World(
        world_id="world:authored:test",
        version_id=VERSION,
        state_sha256="a" * 64,
        edit_seq=3,
        assets=(
            plan._Choice("cc0.bench", "cc0.bench", "Bench", "A wooden bench."),
            plan._Choice("cc0.seating-planter", "cc0.seating-planter", "Planter seat", "A seat."),
        ),
        objects=(
            (plan._Choice("object-1", "object:bench-for-ada", "Bench", selected=True),)
            if objects
            else ()
        ),
        arrangements=(plan._Choice("small_square", "small_square", "Small square", "Seats."),),
        arrangement_versions={"small_square": 1},
        descriptors={**matrix, **(descriptors or {})},
        object_ids=frozenset({"object:bench-for-ada"}) if objects else frozenset(),
    )


def _context(**overrides) -> plan._Context:
    values = {
        "version_id": str(VERSION),
        "base_state_sha256": "a" * 64,
        "origin_role": "fictional",
        "context": {
            "placement": {
                "region_id": "region:starter",
                "transform": {
                    "x_mm": 0,
                    "y_mm": 0,
                    "z_mm": 0,
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


def _values(schema: dict) -> list:
    """The values a schema admits: an ``enum``, or the one value a single-member ``Literal``
    renders as ``const``."""
    return schema["enum"] if "enum" in schema else [schema["const"]]


def test_the_form_offers_exactly_the_options_the_reads_listed():
    schema = plan._world_edit_form(_world()).model_json_schema()
    step = schema["$defs"]["WorldEditStep"]["properties"]
    assert _values(step["operation"]) == list(plan.DRAFT_OPERATIONS)
    assert _values(step["options"]["items"]) == [
        "cc0.bench",
        "cc0.seating-planter",
        "object-1",
        "small_square",
    ]
    assert step["options"]["maxItems"] == plan.MAX_CANDIDATES
    # No field could carry a position, an identifier, a permission or a route.
    assert set(step) == {"operation", "options"}


def test_an_option_list_with_nothing_listed_is_left_off_the_form():
    world = dataclasses.replace(_world(objects=False), assets=(), arrangements=())
    schema = plan._world_edit_form(world).model_json_schema()
    assert set(schema["$defs"]["WorldEditStep"]["properties"]) == {"operation"}
    without_objects = plan._world_edit_form(_world(objects=False)).model_json_schema()
    items = without_objects["$defs"]["WorldEditStep"]["properties"]["options"]["items"]
    assert "object-1" not in _values(items)


def test_objects_reach_the_model_by_label_and_title_only():
    rendered = plan._render_options(_world())
    assert "object-1: Bench (selected)" in rendered
    assert "ada" not in rendered


def test_a_drafted_label_resolves_to_the_value_its_read_listed():
    verdict = plan._typed_from_draft(
        [{"operation": "remove_object", "options": ["object-1"]}],
        _world(),
    )
    assert verdict.refusal is None and verdict.clarification is None
    assert verdict.actions == [plan._Action(Op.REMOVE_OBJECT, object_id="object:bench-for-ada")]


def test_two_options_for_one_slot_are_asked_about():
    verdict = plan._typed_from_draft(
        [{"operation": "place_object", "options": ["cc0.bench", "cc0.seating-planter"]}],
        _world(),
    )
    assert verdict.clarification is not None
    assert verdict.clarification["code"] == "asset_ambiguous"
    assert verdict.clarification["actions"][0]["asset_key"] is None
    assert [c["value"] for c in verdict.clarification["candidates"]] == [
        "cc0.bench",
        "cc0.seating-planter",
    ]


def test_a_change_the_operations_cannot_express_is_refused_by_name():
    verdict = plan._typed_from_draft([{"operation": "other", "options": []}], _world())
    assert verdict.refusal is not None
    assert verdict.refusal["code"] == "action_not_offered"


def test_a_placement_naming_nothing_listed_is_not_in_the_catalogue():
    verdict = plan._typed_from_draft([{"operation": "place_object", "options": []}], _world())
    assert verdict.refusal is not None
    assert verdict.refusal["code"] == "not_in_catalogue"


@pytest.mark.parametrize(
    ("state", "code", "permitted", "expected"),
    [
        ("unsupported", "arrangement_needs_authored_ground", True, "action_unsupported"),
        ("unavailable", "source_invalidated", True, "action_unavailable"),
        ("unknown", None, False, "action_unavailable"),
        ("available", None, False, "action_not_permitted"),
    ],
)
def test_the_capability_read_decides_and_its_code_travels_with_the_refusal(
    state, code, permitted, expected
):
    world = _world(
        descriptors={
            plan.ARRANGE: _descriptor(plan.ARRANGE, state=state, code=code, permitted=permitted)
        }
    )
    refused = plan._availability(
        [plan._Action(Op.PLACE_ARRANGEMENT, arrangement_key="small_square")], world
    )
    assert refused is not None
    assert refused["code"] == expected
    assert refused["operation"] == plan.ARRANGE
    assert refused["capability"]["code"] == code
    assert refused["capability"]["permitted"] is permitted


def test_an_operation_no_descriptor_states_is_refused_not_assumed():
    world = _world()
    descriptors = dict(world.descriptors)
    del descriptors[plan.UNDO]
    stripped = plan._World(
        world_id=world.world_id,
        version_id=world.version_id,
        state_sha256=world.state_sha256,
        edit_seq=world.edit_seq,
        assets=world.assets,
        objects=world.objects,
        arrangements=world.arrangements,
        arrangement_versions=world.arrangement_versions,
        descriptors=descriptors,
        object_ids=world.object_ids,
    )
    refused = plan._availability([plan._Action(Op.UNDO_LAST_EDIT)], stripped)
    assert refused is not None and refused["code"] == "action_not_offered"


@pytest.mark.parametrize(
    ("action", "overrides", "code"),
    [
        (
            plan._Action(Op.PLACE_OBJECT, asset_key="cc0.bench"),
            {"origin_role": None},
            "origin_role_required",
        ),
        (
            plan._Action(Op.PLACE_OBJECT, asset_key="cc0.bench"),
            {"context": {"placement": None, "viewer": None, "selected_object_id": None}},
            "placement_required",
        ),
        (
            plan._Action(
                Op.PLACE_ARRANGEMENT, arrangement_key="small_square", arrangement_version=1
            ),
            {"context": {"placement": None, "viewer": None, "selected_object_id": None}},
            "viewer_required",
        ),
        (plan._Action(Op.MOVE_OBJECT), {}, "object_required"),
    ],
)
def test_what_a_step_needs_and_nobody_supplied_is_asked_for(action, overrides, code):
    asked = plan._requirements([action], _context(**overrides), _world())
    assert asked is not None
    assert asked["code"] == code


def test_a_plan_is_named_by_its_content_and_not_by_what_it_cost():
    document = {"profile": plan.PLAN_PROFILE, "steps": [{"value": 0.8}], "outcome": "plan"}
    digest = plan.plan_document_sha256(document)
    assert digest == plan.plan_document_sha256(
        {**document, "execution": {"calls": [1]}, "names": {"[person A]": "x"}}
    )
    assert digest == plan.plan_document_sha256(dict(reversed(list(document.items()))))
    assert digest != plan.plan_document_sha256({**document, "steps": [{"value": 0.81}]})
    # A float enters the digest tagged, never as a bare number.
    assert plan._digest_input(0.8) == {"float": "0.8"}


def test_the_action_path_states_every_call_it_can_make():
    assert plan.ACTION_PATH_CALLS == ((Role.STRUCTURED_EXTRACTION, 3),)


def test_every_code_a_plan_can_carry_is_declared():
    assert "stale_version" in plan.ACTION_REFUSALS
    assert {
        "asset_ambiguous",
        "object_ambiguous",
        "object_required",
        "arrangement_ambiguous",
        "origin_role_required",
        "placement_required",
        "viewer_required",
        "speed_required",
        "minutes_required",
        "region_required",
        "kind_ambiguous",
        "anchor_ambiguous",
        "being_required",
        "being_ambiguous",
        "place_required",
        "place_ambiguous",
        "thing_ambiguous",
    } == plan.CLARIFICATIONS
    assert "no_change" in plan.ACTION_REFUSALS
    json.dumps(sorted(plan.ACTION_REFUSALS))


def test_the_outcome_route_takes_exactly_the_operations_a_plan_names():
    from typing import get_args

    from exulanica.api.routes.selection_actions import OutcomeOperation

    named = {row.commit for row in plan._MATRIX.values()} | {plan.STYLE_PREVIEW, plan.STYLE_APPLY}
    named |= {plan.CONTROL, plan.CONTROL_STEP, plan.BRING_PEOPLE}
    assert set(get_args(OutcomeOperation)) == named


# -- simulation: the playback controls, pinned to one clock read ------------------------------

SIM = plan.SimulationAction
SOCIETY = uuid.UUID(int=9)


def _clock(*, society: bool = True, mode="paused", speed=1, control_revision=4, tick=12):
    """A version's clock read as ``GET .../clock`` answers it for a legacy town, in the fields a
    plan reads: development data of the read's own shape."""
    return {
        "profile": "exulanica.world-clock/v1",
        "clock_profile": "exulanica.world-clock/legacy-v1",
        "revision": 0,
        "state": mode,
        "presented_through_tick": None,
        "traffic": None,
        "society": (
            {
                "control_revision": control_revision,
                "engine": "exulanica-society/v5",
                "mode": mode,
                "society_id": str(SOCIETY),
                "speed": speed,
                "state_sha256": "b" * 64,
                "tick": tick,
                "tick_interval_ms": 8000 if mode == "playing" else None,
            }
            if society
            else None
        ),
    }


def _simulation_world(*, held: bool = True, regions=("region:town",), **descriptors) -> plan._World:
    """A world whose capability read offers the three simulation operations, or overrides."""
    world = _world()
    offered = {
        operation: _descriptor(operation)
        for operation in (plan.CONTROL, plan.CONTROL_STEP, plan.BRING_PEOPLE)
    }
    return plan._World(
        world_id=world.world_id,
        version_id=world.version_id,
        state_sha256=world.state_sha256,
        edit_seq=world.edit_seq,
        assets=world.assets,
        objects=world.objects,
        arrangements=world.arrangements,
        arrangement_versions=world.arrangement_versions,
        descriptors={**world.descriptors, **offered, **descriptors},
        object_ids=world.object_ids,
        region_ids=tuple(regions),
        society_held=held,
        society_engine="exulanica-society/v5",
    )


def _simulate(action, *, clock=None, world=None, spending=None, **context):
    return plan.simulation_document(
        action,
        _context(**context),
        world or _simulation_world(),
        clock or _clock(),
        spending or plan.TimeSpending(),
    )


def test_the_simulation_form_offers_an_action_a_listed_speed_and_one_to_ten_minutes():
    schema = plan._SimulationDraft.model_json_schema()
    properties = schema["properties"]
    assert set(properties) == {"action", "speed", "minutes"}
    assert schema["$defs"]["SimulationAction"]["enum"] == [action.value for action in SIM]
    speed, _null = properties["speed"]["anyOf"]
    assert speed["enum"] == [1, 2, 4]
    minutes, _null = properties["minutes"]["anyOf"]
    assert (minutes["minimum"], minutes["maximum"]) == (1, plan.MAX_MINUTES)


def test_a_paused_world_moves_forward_by_a_chain_of_steps_each_pinned_to_the_one_before():
    document = _simulate(plan._Simulation(SIM.ADVANCE, minutes=3))
    assert document["outcome"] == "plan" and document["kind"] == "simulation"
    assert document["clock"] == _clock()
    steps = document["steps"]
    assert [step["operation"] for step in steps] == [plan.CONTROL_STEP] * 3
    assert [step["confirmation"] for step in steps] == ["required", "chained", "chained"]
    first = steps[0]
    assert first["body"] == {
        "base_revision": 4,
        "base_tick": 12,
        "base_state_sha256": "b" * 64,
        "base_clock_revision": 0,
    }
    assert first["pins"] == {
        "clock_revision": 0,
        "control_revision": 4,
        "tick": 12,
        "society_state_sha256": "b" * 64,
    }
    assert "body_from" not in first
    for index, step in enumerate(steps[1:], start=1):
        assert step["state"] == "pending" and step["pins"] is None
        # Only the bases are taken from the response before; the clock pin is the plan's own.
        assert step["body"] == {
            "base_revision": None,
            "base_tick": None,
            "base_state_sha256": None,
            "base_clock_revision": 0,
        }
        assert step["body_from"] == {
            "base_revision": {"step": index - 1, "field": "control.revision"},
            "base_tick": {"step": index - 1, "field": "society.current_tick"},
            "base_state_sha256": {"step": index - 1, "field": "society.state_sha256"},
        }
    assert [step["action"]["minute"] for step in steps] == [1, 2, 3]
    assert [step["receipt"] for step in steps] == ["control_manual_step"] * 3


def test_a_playing_world_is_paused_first_and_played_again_at_its_speed_last():
    document = _simulate(
        plan._Simulation(SIM.ADVANCE, minutes=2), clock=_clock(mode="playing", speed=2)
    )
    steps = document["steps"]
    assert [step["operation"] for step in steps] == [
        plan.CONTROL,
        plan.CONTROL_STEP,
        plan.CONTROL_STEP,
        plan.CONTROL,
    ]
    pause, first, _second, play = steps
    assert pause["body"] == {
        "base_revision": 4,
        "mode": "paused",
        "speed": 2,
        "base_clock_revision": 0,
    }
    assert pause["confirmation"] == "required"
    # The first minute takes its bases from the control read the pause answers.
    assert first["body_from"]["base_revision"] == {"step": 0, "field": "revision"}
    assert first["body_from"]["base_tick"] == {"step": 0, "field": "current_tick"}
    assert play["body"]["mode"] == "playing" and play["body"]["speed"] == 2
    assert play["body_from"] == {"base_revision": {"step": 2, "field": "control.revision"}}
    assert play["confirmation"] == "chained"


@pytest.mark.parametrize(("minutes", "steps"), [(0, None), (1, 1), (10, 10), (11, None)])
def test_time_moves_forward_one_to_ten_minutes_at_once(minutes, steps):
    document = _simulate(plan._Simulation(SIM.ADVANCE, minutes=minutes))
    if steps is None:
        assert document["outcome"] == "refused"
        assert document["refusal"]["code"] == "action_not_offered"
        assert document["steps"] == []
    else:
        assert document["outcome"] == "plan"
        assert len(document["steps"]) == steps


def test_the_longest_chain_fits_what_the_outcome_read_takes():
    document = _simulate(
        plan._Simulation(SIM.ADVANCE, minutes=plan.MAX_MINUTES), clock=_clock(mode="playing")
    )
    assert len(document["steps"]) == plan.MAX_PLAN_STEPS


@pytest.mark.parametrize(
    ("action", "clock"),
    [
        (plan._Simulation(SIM.PAUSE), _clock(mode="paused")),
        (plan._Simulation(SIM.PLAY), _clock(mode="playing")),
        (plan._Simulation(SIM.PLAY, speed=2), _clock(mode="playing", speed=2)),
        (plan._Simulation(SIM.SET_SPEED, speed=4), _clock(speed=4)),
    ],
)
def test_asking_for_what_the_controls_already_hold_changes_nothing(action, clock):
    document = _simulate(action, clock=clock)
    assert document["outcome"] == "refused"
    assert document["refusal"]["code"] == "no_change"
    assert document["steps"] == []


def test_play_at_another_speed_is_one_configuration():
    document = _simulate(plan._Simulation(SIM.PLAY, speed=4), clock=_clock(mode="playing"))
    (step,) = document["steps"]
    assert step["operation"] == plan.CONTROL
    assert step["body"] == {
        "base_revision": 4,
        "mode": "playing",
        "speed": 4,
        "base_clock_revision": 0,
    }
    assert step["compensation"] == {"operation": plan.CONTROL}


@pytest.mark.parametrize(
    ("action", "code", "slot"),
    [
        (plan._Simulation(SIM.SET_SPEED), "speed_required", "speed"),
        (plan._Simulation(SIM.ADVANCE), "minutes_required", "minutes"),
    ],
)
def test_a_slot_the_request_left_empty_is_asked_about(action, code, slot):
    document = _simulate(action)
    assert document["outcome"] == "clarify"
    clarification = document["clarification"]
    assert (clarification["code"], clarification["slot"]) == (code, slot)
    assert clarification["actions"] == [{**action.document(), slot: None}]


def test_the_speeds_offered_are_the_controls_own_with_the_current_one_marked():
    clarification = _simulate(plan._Simulation(SIM.SET_SPEED), clock=_clock(speed=2))[
        "clarification"
    ]
    assert clarification["candidates"] == [
        {"value": "1", "title": "", "selected": False},
        {"value": "2", "title": "", "selected": True},
        {"value": "4", "title": "", "selected": False},
    ]


def test_with_nobody_here_a_control_is_refused_and_bringing_people_offered():
    world = _simulation_world(
        held=False,
        **{
            plan.CONTROL: _descriptor(
                plan.CONTROL, state="unavailable", code="society_unavailable"
            ),
            plan.CONTROL_STEP: _descriptor(
                plan.CONTROL_STEP, state="unavailable", code="society_unavailable"
            ),
        },
    )
    document = _simulate(plan._Simulation(SIM.PAUSE), clock=_clock(society=False), world=world)
    refusal = document["refusal"]
    assert refusal["code"] == "action_unavailable"
    assert refusal["capability"]["code"] == "society_unavailable"
    assert refusal["alternatives"] == ["bring_people"]


def test_a_society_its_engine_cannot_play_is_refused_by_the_descriptors_own_code():
    world = _simulation_world(
        **{
            plan.CONTROL_STEP: _descriptor(
                plan.CONTROL_STEP, state="unsupported", code="legacy_society_not_playable"
            )
        }
    )
    document = _simulate(plan._Simulation(SIM.ADVANCE, minutes=1), world=world)
    assert document["refusal"]["code"] == "action_unsupported"
    assert document["refusal"]["capability"]["code"] == "legacy_society_not_playable"
    assert document["refusal"]["alternatives"] == []


def test_a_grant_without_the_control_is_refused_before_anything_is_prepared():
    world = _simulation_world(**{plan.CONTROL: _descriptor(plan.CONTROL, permitted=False)})
    document = _simulate(plan._Simulation(SIM.PAUSE), clock=_clock(mode="playing"), world=world)
    assert document["refusal"]["code"] == "action_not_permitted"
    assert document["steps"] == []


def test_spending_is_said_before_the_one_confirmation_for_each_step_that_can_ask_a_model():
    people = plan.TimeSpending(playing=("society_decision",))
    playing = _clock(mode="playing")
    chain = _simulate(plan._Simulation(SIM.ADVANCE, minutes=2), clock=playing, spending=people)
    # Only the playback worker asks a person's chosen model: a control step never does, and
    # playing the world again last does.
    assert [step["spends"] for step in chain["steps"]] == [False, False, False, True]
    assert chain["spends"] is True and chain["spends_by"] == ["society_decision"]
    paused = _simulate(plan._Simulation(SIM.ADVANCE, minutes=2), spending=people)
    assert paused["spends"] is False and paused["spends_by"] == []
    pause = _simulate(plan._Simulation(SIM.PAUSE), clock=playing, spending=people)
    assert pause["spends"] is False and pause["spends_by"] == []
    play = _simulate(plan._Simulation(SIM.PLAY), spending=people)
    assert play["spends"] is True and play["spends_by"] == ["society_decision"]
    # A coupled world's traffic asks a light's chosen model for every minute it seals.
    lights = plan.TimeSpending(playing=("junction_signal",), stepping=("junction_signal",))
    stepped = _simulate(plan._Simulation(SIM.ADVANCE, minutes=2), spending=lights)
    assert [step["spends"] for step in stepped["steps"]] == [True, True]
    assert stepped["spends_by"] == ["junction_signal"]
    assert _simulate(plan._Simulation(SIM.ADVANCE, minutes=2))["spends"] is False


def test_a_descriptor_that_spends_is_shown_on_its_step():
    world = _simulation_world(**{plan.CONTROL: {**_descriptor(plan.CONTROL), "spends": True}})
    document = _simulate(plan._Simulation(SIM.PLAY), world=world)
    assert document["steps"][0]["spends"] is True and document["spends"] is True


def test_people_are_brought_into_the_one_region_with_the_engine_the_read_names():
    world = _simulation_world(held=False)
    document = _simulate(
        plan._Simulation(SIM.BRING_PEOPLE), clock=_clock(society=False), world=world
    )
    (step,) = document["steps"]
    assert step["operation"] == plan.BRING_PEOPLE
    assert step["body"] == {"region_id": "region:town", "profile": "exulanica-society/v5"}
    assert step["receipt"] == "society_created" and step["replay"] == "held_society_returned"


def test_with_several_regions_the_page_region_is_taken_or_asked_for():
    world = _simulation_world(held=False, regions=("region:a", "region:starter"))
    pointed = _simulate(
        plan._Simulation(SIM.BRING_PEOPLE), clock=_clock(society=False), world=world
    )
    assert pointed["steps"][0]["body"]["region_id"] == "region:starter"
    asked = _simulate(
        plan._Simulation(SIM.BRING_PEOPLE),
        clock=_clock(society=False),
        world=world,
        context={"placement": None, "viewer": None, "selected_object_id": None},
    )
    assert asked["clarification"]["code"] == "region_required"
    assert [c["value"] for c in asked["clarification"]["candidates"]] == [
        "region:a",
        "region:starter",
    ]


def test_bringing_people_where_they_already_are_changes_nothing():
    document = _simulate(plan._Simulation(SIM.BRING_PEOPLE))
    assert document["refusal"]["code"] == "no_change"


def test_a_request_the_controls_cannot_express_is_refused_by_name():
    document = _simulate(plan._Simulation(SIM.OTHER))
    assert document["refusal"]["code"] == "action_not_offered"
    assert document["clock"] == _clock()


def test_the_drafter_is_told_the_state_and_the_speeds_and_nothing_else():
    rendered = plan._render_simulation(_clock(mode="playing", speed=2))
    assert "Time is running at speed 2." in rendered
    assert "4 (4 times the normal pace)" in rendered
    assert str(SOCIETY) not in rendered and "b" * 64 not in rendered


def test_simulation_controls_no_server_states_or_no_grant_holds_are_refused_before_a_draft():
    def refused(world):
        return plan._simulation_plan(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            RequestNames(()),
            "pause everyone",
            None,  # type: ignore[arg-type]
            _context(),
            world,
            _clock,
            log=CallLog(),
        )["refusal"]["code"]

    assert refused(_world()) == "action_not_offered"
    held_by_none = {
        operation: _descriptor(operation, permitted=False)
        for operation in (plan.CONTROL, plan.CONTROL_STEP, plan.BRING_PEOPLE)
    }
    assert refused(_simulation_world(**held_by_none)) == "action_not_permitted"


def _choosing(people, lights, *, travellers=False):
    """Stand-ins for the two choice reads: whether a person and a light have a chosen model, and
    whether a gate's travellers do, which only a read of who decides as the host asks sees."""
    model = {"provider": "nebius", "model_id": "a-chosen-model"}

    class People:
        def __init__(self, connection, workspace_id, *, world_id):
            pass

        def current(self, version_id, role):
            return {"person-1": {"model": model if people else None}}

        def deciding(self, version_id, role, contract):
            found = {"person-1": {"model": model if people else None, "from": "choice"}}
            if travellers:
                found["visitor-1"] = {"model": model, "from": "travellers"}
            return found

    class Lights:
        def __init__(self, connection, workspace_id, world_id, version_id):
            pass

        def current_choices(self):
            return {"light-1": {"model": model if lights else None}}

    return People, Lights


@pytest.mark.parametrize(
    ("people", "lights", "traffic", "expected"),
    [
        # Only playing asks a person's chosen model: the playback worker's decision phase.
        (True, False, None, plan.TimeSpending(playing=("society_decision",))),
        # A coupled world's traffic asks a light's chosen model for each minute it seals.
        (
            False,
            True,
            {"state": "following"},
            plan.TimeSpending(playing=("junction_signal",), stepping=("junction_signal",)),
        ),
        # A legacy world's lights run on the wall clock, whatever its people do.
        (False, True, None, plan.TimeSpending()),
        (False, True, {"state": "unavailable"}, plan.TimeSpending()),
        (False, False, {"state": "following"}, plan.TimeSpending()),
    ],
)
def test_time_spends_where_the_owner_chose_a_model_that_moving_time_asks(
    monkeypatch, people, lights, traffic, expected
):
    chooser, signals = _choosing(people, lights)
    monkeypatch.setattr(plan, "SocietyModelChoiceRepository", chooser)
    monkeypatch.setattr(plan, "TrafficSignalRepository", signals)
    session = Session(workspace_id=uuid.UUID(int=1), actor=uuid.UUID(int=2))
    clock = {**_clock(), "traffic": traffic}
    assert plan.time_spends(None, session, _simulation_world(), clock) == expected  # type: ignore[arg-type]
    assert plan.time_spends(None, session, _simulation_world(), _clock(society=False)) == (  # type: ignore[arg-type]
        plan.TimeSpending()
    )


class _OneRow:
    """A connection whose every statement answers ``row``: the version's society, as stored."""

    def __init__(self, row):
        self.row = row

    def execute(self, *_args):
        return self

    def fetchone(self):
        return self.row


#: The answer a step's own request got when it brought in society 9.
_BROUGHT = {"status": 200, "society_id": str(uuid.UUID(int=9))}


@pytest.mark.parametrize(
    ("stored", "body", "answer", "state"),
    [
        (None, {"region_id": "region:town"}, None, "not_applied"),
        (
            {"region_id": "region:town", "engine_version": "v5"},
            {"region_id": "region:town"},
            _BROUGHT,
            "applied",
        ),
        (
            {"region_id": "region:town", "engine_version": "v5"},
            {"region_id": "region:town", "profile": "v5"},
            _BROUGHT,
            "applied",
        ),
        # The same society, but the step came back without its own answer naming it: not the
        # step's, and its request would now meet a version that already holds one.
        (
            {"region_id": "region:town", "engine_version": "v5"},
            {"region_id": "region:town"},
            None,
            "superseded",
        ),
        (
            {"region_id": "region:town", "engine_version": "v5"},
            {"region_id": "region:town"},
            {"status": 409, "code": "society_exists"},
            "superseded",
        ),
        # Brought in first by another client, with another engine or into another region: the
        # step's own request is refused, so it did not happen.
        (
            {"region_id": "region:town", "engine_version": "v2"},
            {"region_id": "region:town", "profile": "v5"},
            _BROUGHT,
            "superseded",
        ),
        (
            {"region_id": "region:a", "engine_version": "v5"},
            {"region_id": "region:town"},
            _BROUGHT,
            "superseded",
        ),
    ],
)
def test_people_brought_in_read_back_by_the_region_and_the_engine_the_step_named(
    stored, body, answer, state
):
    row = None if stored is None else {"society_id": uuid.UUID(int=9), **stored}
    step = {"index": 0, "operation": plan.BRING_PEOPLE, "body": body, "answer": answer}
    session = Session(workspace_id=uuid.UUID(int=1), actor=uuid.UUID(int=2))
    read = action_outcome._bring_people_step(_OneRow(row), session, "world:test", VERSION, step)
    assert read["state"] == state


def test_time_spends_where_only_a_gate_s_travellers_are_run_by_a_model(monkeypatch):
    # No person's own choice names a model; the gate's mind runs its visitor, which the host asks.
    chooser, signals = _choosing(False, False, travellers=True)
    monkeypatch.setattr(plan, "SocietyModelChoiceRepository", chooser)
    monkeypatch.setattr(plan, "TrafficSignalRepository", signals)
    session = Session(workspace_id=uuid.UUID(int=1), actor=uuid.UUID(int=2))
    assert plan.time_spends(None, session, _simulation_world(), _clock()) == (  # type: ignore[arg-type]
        plan.TimeSpending(playing=("society_decision",))
    )
