"""The Companion's offer of new pieces for a world's look, without a database or a model.

A drafted ``request_pieces`` step is typed from the options it names (kinds, or things in the world,
or none for the world's things in general) and prepared as one request to POST /world/piece-requests
with the route's own estimate, so the sheet states the time and the cost before the person says
yes. The pieces object is the one the actions route hands the planner, over the committed library
and catalogs; the world is the things plan tests' (``test_companion_things_plan``).
"""

from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path

from exulanica.generation.offer import WorldPieces
from exulanica.generation.requests import LookReference
from exulanica.selection import action_plan as plan
from exulanica.selection.action_plan import PIECES
from exulanica.selection.action_plan import WorldEditOperation as Op
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.style_packs import load_context

from test_companion_things_plan import _context, _world

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = style_pack_library()
DEFAULT = LIBRARY.default_pack
LOOK = LookReference(DEFAULT.pack_id, DEFAULT.version, DEFAULT.manifest_sha256)


def _pieces(look: LookReference | None = LOOK) -> WorldPieces:
    return WorldPieces("world:authored:test", look, LIBRARY, load_context(ROOT))


def _granted(_operation: str) -> tuple[list[str], bool]:
    return ["model.invoke", "world.write"], True


def _offered(world: plan._World, pieces: WorldPieces | None = None) -> plan._World:
    return plan._with_pieces(world, _granted, _pieces() if pieces is None else pieces)


def _label(world: plan._World, key: str) -> str:
    return next(choice.label for choice in world.kinds if choice.value == key)


def test_a_named_kind_is_asked_for_and_none_named_asks_for_the_world_s_things():
    world = _offered(_world())
    named = plan._typed_from_draft(
        [{"operation": "request_pieces", "options": [_label(world, "well")]}], world
    )
    assert named.refusal is None and named.clarification is None
    [action] = named.actions
    assert (action.operation, action.kinds, action.named) == (Op.REQUEST_PIECES, ("well",), True)
    general = plan._typed_from_draft([{"operation": "request_pieces", "options": []}], world)
    [action] = general.actions
    read = world.things
    assert read is not None
    assert action.kinds == tuple(sorted({item.kind for item in read.placed if item.kind}))
    assert action.named is False


def test_new_pieces_are_asked_for_on_their_own():
    world = _offered(_world())
    verdict = plan._typed_from_draft(
        [
            {"operation": "place_thing", "options": [_label(world, "well")]},
            {"operation": "request_pieces", "options": [_label(world, "well")]},
        ],
        world,
    )
    assert verdict.refusal is not None
    assert (verdict.refusal["code"], verdict.refusal["step"]) == ("action_not_offered", 1)
    # And never as a later step a client sends back.
    sent_back = plan._typed_from_request([{"operation": "request_pieces"}], world)
    assert sent_back.refusal is not None and sent_back.refusal["code"] == "action_not_offered"


def test_the_step_states_the_request_and_what_it_will_cost_before_the_yes():
    world = _offered(_world())
    verdict = plan._typed_from_draft(
        [{"operation": "request_pieces", "options": [_label(world, "well")]}], world
    )
    document = plan._world_edit_document(verdict, _context(), world, previewer=None)
    assert document["outcome"] == "plan", document.get("refusal")
    [step] = document["steps"]
    assert (step["operation"], step["state"], step["bind"], step["query"]) == (
        PIECES,
        "prepared",
        {},
        {},
    )
    assert step["spends"] is True and step["permitted"] is True
    assert step["confirmation"] == "required"
    body = step["body"]
    assert body["world_id"] == "world:authored:test"
    assert body["look"] == {
        "pack_id": LOOK.pack_id,
        "version": LOOK.version,
        "manifest_sha256": LOOK.manifest_sha256,
    }
    assert [kind["key"] for kind in body["kinds"]] == ["well"]
    uuid.UUID(body["idempotency_key"])
    estimate = step["estimate"]
    assert estimate["provider_label"] == "Nebius AI Cloud"
    assert estimate["basis"]["kind"] == "measured_runs"
    assert estimate["items"] >= 1 and estimate["usd_worst_case"] >= estimate["usd_typical"]
    assert step["titles"] == {"kinds": next(c.title for c in world.kinds if c.value == "well")}
    assert document["spends"] is True
    # The same plan prepared again asks with the same key, so a replay answers the first ask.
    again = plan._world_edit_document(verdict, _context(), world, previewer=None)
    assert again["steps"][0]["body"]["idempotency_key"] == body["idempotency_key"]


def test_without_a_look_pieces_can_be_made_in_or_the_route_s_grant_the_step_is_refused():
    unlooked = _offered(_world(), _pieces(look=None))
    verdict = plan._typed_from_draft([{"operation": "request_pieces", "options": []}], unlooked)
    refused = plan._world_edit_document(verdict, _context(), unlooked, previewer=None)
    assert refused["outcome"] == "refused"
    assert refused["refusal"]["code"] == "action_unavailable"

    world = plan._with_pieces(
        _world(), lambda _op: (["model.invoke", "world.write"], False), _pieces()
    )
    verdict = plan._typed_from_draft([{"operation": "request_pieces", "options": []}], world)
    refused = plan._world_edit_document(verdict, _context(), world, previewer=None)
    assert refused["refusal"]["code"] == "action_not_permitted"

    # A route that hands no pieces object offers no such step at all.
    bare = _world()
    bare = dataclasses.replace(
        bare, descriptors={k: v for k, v in bare.descriptors.items() if k != PIECES}
    )
    verdict = plan._typed_from_draft([{"operation": "request_pieces", "options": []}], bare)
    refused = plan._world_edit_document(verdict, _context(), bare, previewer=None)
    assert refused["refusal"]["code"] == "action_not_offered"


def test_a_being_has_no_piece_and_nothing_asked_blocks_the_step_by_name():
    world = _offered(_world())
    beings = [
        choice
        for choice in world.kinds
        if world.things
        and any(kind.key == choice.value and kind.being for kind in world.things.kinds)
    ]
    assert beings
    verdict = plan._typed_from_draft(
        [{"operation": "request_pieces", "options": [beings[0].label]}], world
    )
    document = plan._world_edit_document(verdict, _context(), world, previewer=None)
    assert document["outcome"] == "refused"
    assert document["steps"][0]["code"] == "no_piece_needed"
