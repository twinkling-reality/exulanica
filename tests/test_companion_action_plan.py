"""The Companion's action planner without a database: its form, its validation and its digest.

Everything here is a rule the planner holds by construction: the model is offered only options the
reads listed, objects only by opaque label, an unavailable operation is refused by the capability
read's own code, ambiguity is asked about before anything is prepared, and a plan's digest names
its content and nothing about how it was paid for.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.models.manifest import Role
from exulanica.selection import action_plan as plan
from exulanica.selection.action_plan import WorldEditOperation as Op

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
    assert _values(step["operation"]) == [operation.value for operation in Op]
    assert _values(step["kinds"]["items"]) == ["cc0.bench", "cc0.seating-planter"]
    assert _values(step["objects"]["items"]) == ["object-1"]
    assert _values(step["arrangements"]["items"]) == ["small_square"]
    assert step["kinds"]["maxItems"] == plan.MAX_CANDIDATES
    # No field could carry a position, an identifier, a permission or a route.
    assert set(step) == {"operation", "kinds", "objects", "arrangements"}


def test_a_slot_with_no_options_is_left_off_the_form():
    schema = plan._world_edit_form(_world(objects=False)).model_json_schema()
    assert "objects" not in schema["$defs"]["WorldEditStep"]["properties"]


def test_objects_reach_the_model_by_label_and_title_only():
    rendered = plan._render_options(_world())
    assert "object-1: Bench (selected)" in rendered
    assert "ada" not in rendered


def test_a_drafted_label_resolves_to_the_value_its_read_listed():
    verdict = plan._typed_from_draft(
        [{"operation": "remove_object", "kinds": [], "objects": ["object-1"], "arrangements": []}],
        _world(),
    )
    assert verdict.refusal is None and verdict.clarification is None
    assert verdict.actions == [plan._Action(Op.REMOVE_OBJECT, object_id="object:bench-for-ada")]


def test_two_options_for_one_slot_are_asked_about():
    verdict = plan._typed_from_draft(
        [
            {
                "operation": "place_object",
                "kinds": ["cc0.bench", "cc0.seating-planter"],
                "objects": [],
                "arrangements": [],
            }
        ],
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
    verdict = plan._typed_from_draft(
        [{"operation": "other", "kinds": [], "objects": [], "arrangements": []}], _world()
    )
    assert verdict.refusal is not None
    assert verdict.refusal["code"] == "action_not_offered"


def test_a_placement_naming_nothing_listed_is_not_in_the_catalogue():
    verdict = plan._typed_from_draft(
        [{"operation": "place_object", "kinds": [], "objects": [], "arrangements": []}], _world()
    )
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
    } == plan.CLARIFICATIONS
    json.dumps(sorted(plan.ACTION_REFUSALS))


def test_the_outcome_route_takes_exactly_the_operations_a_plan_names():
    from typing import get_args

    from exulanica.api.routes.selection_actions import OutcomeOperation

    named = {row.commit for row in plan._MATRIX.values()} | {plan.STYLE_PREVIEW, plan.STYLE_APPLY}
    assert set(get_args(OutcomeOperation)) == named
