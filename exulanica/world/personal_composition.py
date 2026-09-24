"""Compose personal photographs into the personal-source world's protected topology.

The one writer of a personal-source world's topology. The protected route
(``GET`` and ``POST /worlds/personal-source``, :mod:`exulanica.api.routes.worlds`) and the operator
scripts (:func:`exulanica.orchestration.reference_world.compose_reference_sources`) both register
through :func:`register_composition`, which creates the world under the count policy when the
workspace holds none (:func:`exulanica.world.worlds.ensure_personal_source_world`) and registers
the topology through the style repository's protected seam. What each caller composes is its own:
the scripts name photographs from an intake manifest, and the route composes every photograph the
review rule admits (:mod:`exulanica.world.reviewed_sources`), grouped by the live scene groups
(:mod:`exulanica.graph.personal_sources`).

A composition is membership: which photograph is a source slot of which region. It asserts
nothing new about a photograph's time, position, geometry or meaning, and it writes no evidence.

**What the route may do next** is decided here, once, from world state the server holds
(:func:`personal_world_plan`):

- ``create_world``: the workspace holds no personal-source world, and composing makes it;
- ``update_world``: the world was composed but never made (it has no structural snapshot) and
  the composition differs from its current topology, so composing registers its next topology;
- ``save_entry``: there is nothing to compose, because the unmade world's topology is exactly this
  composition or the made world holds exactly these photographs, and no saved world names it yet;
- otherwise a named refusal (:class:`PersonalWorldRefused`).

**A made world is not changed.** Once the world has a structural snapshot, every saved world of it
opens that snapshot and nothing advances it, so composing again could only change a topology
nobody sees. The plan compares the photographs the snapshot was made with to the ones composing
now would use, and refuses a difference as ``personal_world_already_made``, in words that say what
the world holds and what changed, rather than offering a change with no visible effect.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg

from exulanica.canonical import sha256_of_canonical
from exulanica.world.errors import WorldNotConfigured
from exulanica.world.models import TopologyContract, TopologySourceSlot
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.structure_repository import WorldStructureRepository
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.worlds import (
    PERSONAL_SOURCE,
    ensure_personal_source_world,
    workspace_worlds,
)

__all__ = [
    "PERSONAL_COMPOSITION_PROFILE",
    "SOURCE_NAMESPACE",
    "ComposedSource",
    "PersonalComposition",
    "PersonalWorldPlan",
    "PersonalWorldRefused",
    "compose_personal_world",
    "personal_composition_record",
    "personal_world_plan",
    "register_composition",
    "source_slot",
]

#: Source ids are ``uuid5`` of the workspace and capture under this namespace, so a photograph
#: keeps one source id in every topology it is composed into.
SOURCE_NAMESPACE: Final = uuid.UUID("d3f0565b-c4b2-4d19-8ea9-a3f79bbb5649")

#: The record a route composition's topology digest covers.
PERSONAL_COMPOSITION_PROFILE: Final = "exulanica.personal-source-composition/v1"

#: The provenance reason a world created by the route is registered with.
_CREATED_BY_ROUTE: Final = "reviewed photographs composed into their scene groups"

Action = Literal["create_world", "update_world", "save_entry"]


@dataclass(frozen=True, slots=True)
class ComposedSource:
    """One photograph as a source slot of one region."""

    capture_id: uuid.UUID
    source_sha256: str
    evidence_span_id: uuid.UUID
    region_id: str


@dataclass(frozen=True, slots=True)
class PersonalComposition:
    """What the route would compose now, and how many reviewed photographs it leaves out."""

    #: Every photograph the review rule admits, including those left out below.
    reviewed: int
    #: Reviewed photographs no live scene group contains. They have no region to be a slot of.
    outside_scene_groups: int
    #: The composed photographs, region by region in scene-group order, capture id order inside.
    sources: tuple[ComposedSource, ...]
    #: The regions, in scene-group order; each holds at least one composed photograph.
    region_ids: tuple[str, ...]
    #: The original-image span of every reviewed photograph, composed or left out.
    reviewed_spans: frozenset[uuid.UUID] = frozenset()

    @property
    def composed(self) -> int:
        return len(self.sources)


class PersonalWorldRefused(Exception):
    """A named reason the personal-source world cannot be composed or saved now.

    ``detail`` is written for the person who asked; a client shows it as it is.
    """

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _no_reviewed_sources() -> PersonalWorldRefused:
    return PersonalWorldRefused(
        "no_reviewed_personal_sources",
        "None of your photographs has a current review from you, so there is nothing to make "
        "a world from yet. Review your photographs first.",
    )


def _no_grouped_sources(reviewed: int) -> PersonalWorldRefused:
    return PersonalWorldRefused(
        "no_grouped_personal_sources",
        f"You have reviewed {reviewed} photograph{'' if reviewed == 1 else 's'}, but none of "
        "them belongs to a place yet. Photographs become places when they are grouped by when "
        "and where they were taken.",
    )


def _world_current() -> PersonalWorldRefused:
    return PersonalWorldRefused(
        "personal_world_current",
        "Your world from your photographs already holds every photograph you have reviewed, "
        "and it is saved. Open it from your worlds.",
    )


def _world_already_made(
    *, held: int, added: int, not_allowed: int, ungrouped: int
) -> PersonalWorldRefused:
    """Refuse changing a made world, saying what it holds and what it shows of what changed.

    Each count says what the world does with those photographs, as its read path measures it: a
    photograph no longer allowed (deleted, withdrawn, or without a current review) is one its
    source media stops drawing (``lapsed_personal_captures`` in the style repository), and a
    reviewed photograph that is only no longer in a place is still drawn where it was made.
    """

    def photographs(count: int) -> str:
        return f"{count} photograph{'' if count == 1 else 's'}"

    def of_its(count: int) -> str:
        return f"{count} of its photographs"

    it = {True: "it", False: "them"}
    said = [f"Your world from your photographs was made with {photographs(held)}."]
    if added:
        said.append(
            f"{photographs(added)} you reviewed since {'is' if added == 1 else 'are'} not in it."
        )
    if not_allowed:
        said.append(
            f"{of_its(not_allowed)} {'is' if not_allowed == 1 else 'are'} no longer allowed in "
            f"it (deleted, withdrawn or without a current review from you), so the world no "
            f"longer shows {it[not_allowed == 1]}."
        )
    if ungrouped:
        said.append(
            f"{of_its(ungrouped)} {'is' if ungrouped == 1 else 'are'} no longer in any place, "
            f"and the world still shows {it[ungrouped == 1]} where {it[ungrouped == 1]} "
            f"{'was' if ungrouped == 1 else 'were'} placed."
        )
    said.append("This app does not add photographs to a world once it is made, or move them in it.")
    return PersonalWorldRefused("personal_world_already_made", " ".join(said))


def _sources_changed() -> PersonalWorldRefused:
    return PersonalWorldRefused(
        "personal_sources_changed",
        "Your reviewed photographs changed after this was checked, so nothing was made. "
        "Check again, then try again.",
    )


def source_slot(
    workspace_id: uuid.UUID, source: ComposedSource
) -> tuple[TopologySourceSlot, dict[str, str]]:
    """The protected source slot for one photograph, and its line in the composition record."""
    source_id = uuid.uuid5(SOURCE_NAMESPACE, f"{workspace_id}:{source.capture_id}")
    slot_key = f"source-{source.capture_id}"
    slot = TopologySourceSlot(source_id, slot_key, source.region_id, source.evidence_span_id, None)
    return slot, {
        "source_id": str(source_id),
        "capture_id": str(source.capture_id),
        "source_sha256": source.source_sha256,
        "evidence_span_id": str(source.evidence_span_id),
        "slot_key": slot_key,
    }


def personal_composition_record(
    workspace_id: uuid.UUID, composition: PersonalComposition
) -> dict[str, Any]:
    """The document a route composition's topology digest is the SHA-256 of."""
    regions: dict[str, list[dict[str, str]]] = {region: [] for region in composition.region_ids}
    for source in composition.sources:
        regions[source.region_id].append(source_slot(workspace_id, source)[1])
    return {
        "profile": PERSONAL_COMPOSITION_PROFILE,
        "workspace_id": str(workspace_id),
        "regions": [
            {"region_id": region, "source_slots": slots} for region, slots in regions.items()
        ],
        "interpretation": "membership of reviewed photographs in their scene groups; "
        "no new reconstruction or evidence",
    }


def register_composition(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    record: Mapping[str, Any],
    sources: Sequence[ComposedSource],
    region_ids: Sequence[str],
    actor: uuid.UUID,
    reason: str,
) -> dict[str, Any]:
    """Register ``record``'s digest as the personal-source world's current topology.

    Creates the world first, as ``actor`` with ``reason``, when the workspace holds none; the
    count policy refuses a creation past its limit there. Composing the same record again returns
    the same world, digest and style version.
    """
    if not sources or not region_ids or len({s.capture_id for s in sources}) != len(sources):
        raise ValueError("a composition needs regions and unique photographs")
    if {source.region_id for source in sources} - set(region_ids):
        raise ValueError("every composed photograph must be a slot of a composed region")
    digest = sha256_of_canonical(dict(record)).hex()
    world_id = ensure_personal_source_world(
        connection, workspace_id, created_by=actor, reason=reason
    )
    version = WorldStyleRepository(connection, workspace_id, world_id=world_id).register_topology(
        TopologyContract(
            digest,
            tuple(region_ids),
            tuple(source_slot(workspace_id, source)[0] for source in sources),
            world_id=world_id,
        )
    )
    return {
        "world_id": world_id,
        "topology_digest": digest,
        "style_version_id": str(version.version_id),
    }


@dataclass(frozen=True, slots=True)
class PersonalWorldPlan:
    """What composing now would do, or why it cannot, with the facts that decided it."""

    action: Action | None
    refusal: PersonalWorldRefused | None
    world_id: str | None
    saved_entry_id: uuid.UUID | None
    #: The digest composing now would register; ``None`` when there is nothing to compose.
    topology_digest: str | None
    current_topology_digest: str | None


def personal_world_plan(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    composition: PersonalComposition,
) -> PersonalWorldPlan:
    """Decide, from the registry, the world's topology and its saved entry, what may happen now."""
    personal = [
        world.world_id
        for world in workspace_worlds(connection, workspace_id)
        if world.kind == PERSONAL_SOURCE
    ]
    world_id = personal[0] if len(personal) == 1 else None
    current = None
    saved_entry_id = None
    if world_id is not None:
        try:
            current = WorldStyleRepository(
                connection, workspace_id, world_id=world_id
            ).current_topology_digest()
        except WorldNotConfigured:
            current = None
        row = connection.execute(
            "select entry_id from saved_world_entry where workspace_id=%s and world_id=%s",
            (workspace_id, world_id),
        ).fetchone()
        saved_entry_id = None if row is None else row["entry_id"]
    digest = (
        None
        if composition.composed == 0
        else sha256_of_canonical(personal_composition_record(workspace_id, composition)).hex()
    )

    def refused(refusal: PersonalWorldRefused) -> PersonalWorldPlan:
        return PersonalWorldPlan(None, refusal, world_id, saved_entry_id, digest, current)

    def plan(action: Action) -> PersonalWorldPlan:
        return PersonalWorldPlan(action, None, world_id, saved_entry_id, digest, current)

    if len(personal) > 1:
        return refused(
            PersonalWorldRefused(
                "several_personal_source_worlds",
                f"This account holds {len(personal)} worlds made from its photographs; "
                "choose the one to bring up to date.",
            )
        )
    if composition.reviewed == 0:
        return refused(_no_reviewed_sources())
    if composition.composed == 0:
        return refused(_no_grouped_sources(composition.reviewed))
    if world_id is None:
        return plan("create_world")
    snapshot = WorldStructureRepository(connection, workspace_id, world_id=world_id).current()
    if snapshot is None:
        # Composed but never made: a new topology is what making it will open.
        return plan("update_world") if digest != current else plan("save_entry")
    # Made: its structural snapshot is what every saved world of it opens, and nothing advances a
    # made world's snapshot. Composing again could only change a topology nobody sees.
    made_with = {
        uuid.UUID(element["evidence"]["span_id"])
        for element in snapshot.candidate.topology["elements"]
        if element["evidence"]["kind"] == "span"
    }
    composed_now = {source.evidence_span_id for source in composition.sources}
    if composed_now != made_with:
        return refused(
            _world_already_made(
                held=len(made_with),
                added=len(composed_now - made_with),
                not_allowed=len(made_with - composition.reviewed_spans),
                ungrouped=len((made_with & composition.reviewed_spans) - composed_now),
            )
        )
    if saved_entry_id is None:
        return plan("save_entry")
    return refused(_world_current())


def compose_personal_world(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    composition: PersonalComposition,
    *,
    expected_topology_digest: str,
    actor: uuid.UUID,
) -> tuple[PersonalWorldPlan, dict[str, Any]]:
    """Carry out the plan for exactly the composition the caller was shown.

    The caller reads ``composition`` holding the workspace lock, so nothing it read can change
    before this returns. ``expected_topology_digest`` is the digest the caller was shown; any other
    composition is refused as ``personal_sources_changed`` and nothing is written. ``save_entry``
    writes nothing and answers with the world and its current topology.
    """
    with connection.transaction():
        lock_workspace(connection, workspace_id)
        plan = personal_world_plan(connection, workspace_id, composition)
        # The refusal first: it says what is true now, which a digest mismatch alone would not.
        if plan.refusal is not None:
            raise plan.refusal
        if plan.topology_digest != expected_topology_digest:
            raise _sources_changed()
        if plan.action == "save_entry":
            assert plan.world_id is not None and plan.current_topology_digest is not None
            style = WorldStyleRepository(connection, workspace_id, world_id=plan.world_id).current()
            return plan, {
                "world_id": plan.world_id,
                "topology_digest": plan.current_topology_digest,
                "style_version_id": str(style.version_id),
            }
        return plan, register_composition(
            connection,
            workspace_id,
            record=personal_composition_record(workspace_id, composition),
            sources=composition.sources,
            region_ids=composition.region_ids,
            actor=actor,
            reason=_CREATED_BY_ROUTE,
        )
