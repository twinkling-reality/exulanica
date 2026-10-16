"""A world with a pond, as a society of things over it reads it, for the swimming tests.

The fixture farm (``tests/fixtures/world-kinds/fixture-farm.json``, its first preset) lays a pond in
the south-east corner of its site: an area whose roles name water, 35.1 m by 32.5 m, with the
walking lines of its zone along its south, west and north sides. :func:`compose_farm` composes a
things input over the farm's own surfaces as the runtime does, with the water the site composer
states (:func:`~exulanica.world.composers.site_plan.swim_nodes`) handed to the composition, and
:func:`finned_walker` is a body with four legs and a pair of fins drafted to walk and swim: under
the body grammar's second version, as a kind kept before the grammar named a pace in water, so it
swims at the swimming module's reference pace, or under a later version, stating its own. Nothing
here names an animal: the body is described by its shape.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from functools import cache
from typing import Any

from exulanica.environment.district_geometry import segment_blocked
from exulanica.grammar.grammars.site.records import SiteAreaRecord
from exulanica.selection.creature_drafting import assembled_form
from exulanica.things.bodies import load_body_grammar, read_body_recipe
from exulanica.things.creatures import assemble_creature
from exulanica.things.run_forms import run_form
from exulanica.world.authored_delta import version_delta_sha256
from exulanica.world.composers.site_plan import swim_nodes
from exulanica.world.kinds.worker import _placed
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import PlacedThing, WorkspaceKindReference
from exulanica.world.society_authored_ground import StandingPolicy, authored_ground_from_snapshot
from exulanica.world.society_planner import input_sha256
from exulanica.world.society_site_place import site_obstructions
from exulanica.world.society_walking_surfaces import build_walking_surfaces_input
from exulanica.world.society_water_sources import site_water
from exulanica.world.town_people import people_frame

import test_site_society_of_things as site
from creature_support import form_of
from living_town_support import version_of

SEED = "6" * 64
SOCIETY = uuid.uuid5(uuid.NAMESPACE_URL, "society-of-swimmers")
#: Who drafted the body: a model's provenance, as a drafted kind's origin names it.
BY = {
    "kind": "model",
    "provider": "example_provider",
    "model_id": "example/model",
    "prompt_version": "creature-drafting-1",
    "prompt_sha256": "cd" * 32,
    "words_sha256": "ab" * 32,
    "execution_sha256": None,
}


@dataclasses.dataclass(frozen=True)
class Farm:
    """The fixture farm as its society's composer reads it."""

    world_id: str
    receipt: dict[str, Any]
    records: tuple[object, ...]
    ground: Any
    answer: dict[str, Any]
    routine: Any
    pond: SiteAreaRecord


@cache
def farm() -> Farm:
    world_id, composed = site._composed("farm")
    receipt = json.loads(json.dumps(composed.receipt))
    snapshot_id = uuid.uuid5(uuid.NAMESPACE_URL, composed.receipt_sha256)
    ground = authored_ground_from_snapshot(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=composed.receipt_sha256,
        composer_key=composed.candidate.composer_key,
        composer_version=composed.candidate.composer_version,
        topology=composed.candidate.topology,
        placement=composed.candidate.placement,
    )
    records = tuple(composed.records)
    [pond] = [r for r in records if isinstance(r, SiteAreaRecord) and "water" in r.roles]
    return Farm(
        world_id,
        receipt,
        records,
        ground,
        _placed(ground.place_id, receipt, records),
        site.SITE.receipt_routine(receipt),
        pond,
    )


@cache
def finned_walker_creature(grammar_version: int = 2) -> Any:
    """A body with four legs and a pair of fins, drafted to walk and swim under the body grammar's
    ``grammar_version``."""
    grammar = load_body_grammar(version=grammar_version)
    form = form_of("three_heads", label="finned walker", moves=["walking", "swimming"])
    form["fins"], form["fin_segments"] = 2, 2
    return assemble_creature(assembled_form(form, grammar), by=BY, grammar=grammar)


@cache
def finned_walker(grammar_version: int = 2) -> tuple[str, dict[str, Any]]:
    """:func:`finned_walker_creature`'s kind's digest and its run form."""
    creature = finned_walker_creature(grammar_version)
    grammar = load_body_grammar(version=grammar_version)
    recipe = read_body_recipe(dict(creature.recipe), grammar=grammar)
    return creature.kind.sha256, run_form(creature.kind, creature.plan, recipe)


def placed(placed_id: str, sha256: str, east_mm: int, north_mm: int) -> PlacedThing:
    """A made thing placed at a point of the site's own frame (east and north), as the region
    states it (east and south)."""
    return PlacedThing(
        placed_id,
        WorkspaceKindReference(sha256),
        farm().ground.region_id,
        Transform(east_mm, 0, -north_mm, 0, 1000),
        ObjectOrigin("authored", "fictional"),
    )


def compose_farm(
    *things: PlacedThing,
    input_seq: int = 1,
    water: bool = True,
    made_kinds: dict[str, Any] | None = None,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    """A things input over the farm, with ``things`` placed and the site's water handed to its
    composition where ``water`` says so, as the runtime hands it (:func:`site_water`); unavailable
    for ``unavailable_reason`` where one is given."""
    made = farm()
    version = dataclasses.replace(
        version_of(made.world_id, made.ground.snapshot_id), things=tuple(things)
    )
    version = dataclasses.replace(version, state_sha256=version_delta_sha256(version))
    place = made.answer["place"]
    policy = made.routine.policy
    return build_walking_surfaces_input(
        ground=made.ground,
        version=version,
        place=place,
        input_seq=input_seq,
        dependency_refs=[],
        availability="available" if unavailable_reason is None else "unavailable",
        unavailable_reason=unavailable_reason,
        reviewed_affordances={},
        standing=StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"]),
        things=True,
        segment_blocked=segment_blocked,
        obstructions=site_obstructions(made.answer["blocked"]),
        people=people_frame(place, made.routine),
        made_kinds=made_kinds,
        water=site_water(made.answer) if water else None,
    )


def resealed(document: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """``document`` with ``changes`` (a value of None removes the field), sealed again."""
    sealed = {k: v for k, v in document.items() if k != "document_sha256"}
    for key, value in changes.items():
        if value is None:
            sealed.pop(key, None)
        else:
            sealed[key] = value
    sealed["document_sha256"] = input_sha256(sealed)
    return sealed


def pond_water_statement() -> list[dict[str, Any]]:
    """The water the site composer states for the farm."""
    made = farm()
    return swim_nodes(made.receipt, made.records)
