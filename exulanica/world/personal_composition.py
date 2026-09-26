"""Compose personal photographs into the personal-source world, and add later ones once it is made.

The one writer of a personal-source world's topology. The protected route
(``GET`` and ``POST /worlds/personal-source``, :mod:`exulanica.api.routes.worlds`) and the operator
scripts (:func:`exulanica.orchestration.reference_world.compose_reference_sources`) both register
through :func:`register_composition`, which creates the world under the count policy when the
workspace holds none (:func:`exulanica.world.worlds.ensure_personal_source_world`) and registers
the topology through the style repository's protected seam. What each caller composes is its own:
the scripts name photographs from an intake manifest, and the route composes every photograph the
review rule admits (:mod:`exulanica.world.reviewed_sources`), arranged by :func:`arrange` over the
live scene groups (:mod:`exulanica.graph.personal_sources` reads both facts).

A composition is membership: which photograph is a source slot of which region. It asserts
nothing new about a photograph's time, position, geometry or meaning, and it writes no evidence.

**Which region a photograph is a slot of** is one rule, :func:`arrange`. Scene grouping keeps
every earlier group live beside a later one (a place photographed again is several overlapping
groups, and their ordinals restart with every run), so a place is read as the photographs the
live groups connect: two photographs share a place when some live group holds both. A region the
world was made with keeps its id and every photograph it was made with, and takes in each newly
reviewed photograph of its place. A place holding no photograph of the made world becomes a new
region, named by its largest live group. A newly reviewed photograph whose place holds photographs
of several made regions is left out and counted, because joining it would join places, and so is
one no live group holds. For one grouping run over a world never made, every group is its own
place and the regions are exactly those groups, in the grouping's order.

**What the route may do next** is decided here, once, from world state the server holds
(:func:`personal_world_plan`):

- ``create_world``: the workspace holds no personal-source world, and composing makes it;
- ``update_world``: the world was composed but never made (it has no structural snapshot) and
  the composition differs from its current topology, so composing registers its next topology;
- ``save_entry``: there is nothing to compose, because the unmade world's topology is exactly this
  composition, or the world is made and no saved world names it yet, which opens it as it was made;
- ``add_photographs``: the world is made and saved, and newly reviewed photographs have a place in
  it. The read answers with a preview: what adding them does, in counts and in words, and the
  SHA-256 of exactly that preview, which the write must be given back;
- otherwise a named refusal (:class:`PersonalWorldRefused`).

**Adding photographs keeps everything.** It never removes or moves a photograph the world was
made with: one no longer allowed stays in its slot and the review rule keeps it from being drawn,
and one no longer in any place stays where it was placed. In one transaction, under the workspace
lock and only for the preview the person confirmed, it registers the composition, appends the next
structural snapshot with a placement migration for each place that grows, carries the saved
world's authored version onto that snapshot (every object, override, environment piece and depth
estimate the new version can hold, its change list when every one of them carries, and the
avatar's appearance), and moves the saved entry to it, each step comparing the base it read. What
cannot carry stays in the previous version, which is not changed, and the preview says so by kind,
reason and count. The one thing that refuses the addition is one the person can fix: inhabitants
who are here, who do not move to the new version, are sent away first.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

import psycopg

from exulanica.canonical import sha256_of_canonical
from exulanica.store.base import ContentAddressedStore
from exulanica.world.bootstrap import structural_input_digests
from exulanica.world.character_appearance_repository import CharacterAppearanceRepository
from exulanica.world.composed import composed_candidate
from exulanica.world.edit_kinds import EditSubject
from exulanica.world.errors import StaleObjectBase, StaleStructuralBase, WorldNotConfigured
from exulanica.world.models import TopologyContract, TopologySourceSlot
from exulanica.world.object_repository import (
    CarryOutcome,
    CarryPlan,
    StayReason,
    WorldObjectRepository,
)
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.reviewed_sources import lapsed_personal_captures
from exulanica.world.saved_entries import (
    SavedWorldEntry,
    SavedWorldEntryRepository,
    StaleSavedWorldEntry,
)
from exulanica.world.society_engines import society_engine
from exulanica.world.society_presence import AWAY, HERE, presence
from exulanica.world.structure import PlacementMigration, SpatialSnapshot
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
    "VERSION_TABLES",
    "AdditionPreview",
    "ComposedSource",
    "LiveSceneGroup",
    "MadeWorld",
    "PersonalComposition",
    "PersonalSources",
    "PersonalWorldPlan",
    "PersonalWorldRefused",
    "ReviewedPhotograph",
    "arrange",
    "compose_personal_world",
    "made_world",
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

#: The document an addition preview's digest covers, which the person confirms.
ADDITION_PREVIEW_PROFILE: Final = "exulanica.personal-world-addition-preview/v1"

#: Placement migration ids are ``uuid5`` of the world, the snapshot the addition extends and the
#: region under this namespace, so the read and the write name the same migration.
_MIGRATION_NAMESPACE: Final = uuid.UUID("6a0f3c1e-8d2b-4f57-a9c4-3e71b5d20c86")

#: The provenance reason a world created by the route is registered with.
_CREATED_BY_ROUTE: Final = "reviewed photographs composed into their scene groups"

Action = Literal["create_world", "update_world", "save_entry", "add_photographs"]

#: Every table whose rows belong to one authored version, and what adding photographs does with
#: them. ``tests/test_personal_world_addition.py`` holds the keys equal to the tables whose foreign
#: keys name ``world_alternate_version``, so a table added later fails until this says what an
#: addition does with it.
VERSION_TABLES: Final[Mapping[str, str]] = {
    "world_alternate_version": "a new version on the new snapshot whose parent is the old one",
    "world_alternate_object": "carried",
    "world_alternate_element_override": "carried",
    "world_alternate_environment_instance": "carried while its source can still be placed",
    "world_alternate_point_map_instance": "carried while its depth right and bytes allow it",
    "world_alternate_version_edit": "carried whole when every row carries, otherwise not at all",
    "world_character_appearance_revision": "the avatar's carried; an inhabitant's stay",
    "world_society": "stays in the previous version; inhabitants who are here refuse",
    "society_experiment_definition": "stays in the previous version with its society",
    "society_comparison": "stays in the previous version with its society",
    "saved_world_entry": "moved to the new version",
}


@dataclass(frozen=True, slots=True)
class ReviewedPhotograph:
    """One photograph the review rule admits now, with the viewer bytes it may be shown with."""

    capture_id: uuid.UUID
    source_sha256: str
    evidence_span_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class LiveSceneGroup:
    """One live scene group: the photographs grouping put together, and its run's ordinal."""

    group_id: str
    ordinal: int
    capture_ids: frozenset[uuid.UUID]


@dataclass(frozen=True, slots=True)
class PersonalSources:
    """The two facts :func:`arrange` reads, each from its one owner."""

    reviewed: tuple[ReviewedPhotograph, ...]
    groups: tuple[LiveSceneGroup, ...]


@dataclass(frozen=True, slots=True)
class ComposedSource:
    """One photograph as a source slot of one region."""

    capture_id: uuid.UUID
    source_sha256: str
    evidence_span_id: uuid.UUID
    region_id: str


@dataclass(frozen=True, slots=True)
class MadeWorld:
    """The structural snapshot a made world opens, and the photographs it was made with."""

    snapshot: SpatialSnapshot
    #: The snapshot's regions, in its order.
    region_ids: tuple[str, ...]
    #: Every photograph the snapshot holds as a slot, region by region.
    sources: tuple[ComposedSource, ...]


@dataclass(frozen=True, slots=True)
class PersonalComposition:
    """What the rule arranges: every slot, region by region, and what it leaves out."""

    #: Every photograph the review rule admits, including those left out below.
    reviewed: int
    #: Reviewed photographs no live scene group holds, left out.
    outside_scene_groups: int
    #: Every slot, region by region in region order, capture id order inside.
    sources: tuple[ComposedSource, ...]
    #: The regions: a made world's first, in its order, then new ones in grouping order.
    region_ids: tuple[str, ...]
    #: Of the reviewed photographs, the ones that are slots.
    reviewed_slots: int = 0
    #: Newly reviewed photographs whose place holds photographs of several made regions, left out.
    between_places: int = 0
    #: The slots a made world does not hold yet; every slot when nothing is made.
    added: tuple[ComposedSource, ...] = ()
    #: Photographs the made world holds that no live scene group holds now.
    made_outside_groups: frozenset[uuid.UUID] = frozenset()
    #: The snapshot the composition extends, when the world is made.
    made_snapshot_id: uuid.UUID | None = None

    @property
    def composed(self) -> int:
        return self.reviewed_slots

    @property
    def made_region_ids(self) -> frozenset[str]:
        added = {source.capture_id for source in self.added}
        return frozenset(
            source.region_id for source in self.sources if source.capture_id not in added
        )


class PersonalWorldRefused(Exception):
    """A named reason the personal-source world cannot be composed, saved or added to now.

    ``detail`` is written for the person who asked; a client shows it as it is.
    """

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _photographs(count: int) -> str:
    return f"{count} photograph{'' if count == 1 else 's'}"


def _it(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


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


def _left_out(composition: PersonalComposition) -> list[str]:
    """What happens to newly reviewed photographs that cannot be added, one sentence per reason."""
    said = []
    if composition.outside_scene_groups:
        count = composition.outside_scene_groups
        said.append(
            f"{_photographs(count)} you reviewed since {_it(count, 'is', 'are')} not in any "
            f"place, so {_it(count, 'it is', 'they are')} left out."
        )
    if composition.between_places:
        count = composition.between_places
        said.append(
            f"{_photographs(count)} you reviewed since {_it(count, 'belongs', 'belong')} with "
            f"more than one place of your world, so {_it(count, 'it is', 'they are')} left out: "
            "adding a photograph never joins places."
        )
    return said


def _kept(not_allowed: int, made_outside_groups: int) -> list[str]:
    """What the world does with photographs it was made with that changed, one sentence each."""
    said = []
    if not_allowed:
        count = not_allowed
        said.append(
            f"{count} of its photographs {_it(count, 'is', 'are')} no longer allowed in it "
            "(deleted, withdrawn or without a current review from you), so the world does not "
            f"show {_it(count, 'it', 'them')}; {_it(count, 'it stays', 'they stay')} in "
            f"{_it(count, 'its', 'their')} place and {_it(count, 'shows', 'show')} again after "
            "a new review."
        )
    if made_outside_groups:
        count = made_outside_groups
        said.append(
            f"{count} of its photographs {_it(count, 'is', 'are')} no longer in any place and "
            f"{_it(count, 'stays', 'stay')} where {_it(count, 'it was', 'they were')} placed."
        )
    return said


def _world_current(
    composition: PersonalComposition, not_allowed: int, made_outside_groups: int
) -> PersonalWorldRefused:
    left_out = _left_out(composition)
    said = (
        [
            "Your world from your photographs is saved, and none of the photographs you reviewed "
            "since can be added to it."
        ]
        if left_out
        else [
            "Your world from your photographs already holds every photograph you have reviewed, "
            "and it is saved. Open it from your worlds."
        ]
    )
    return PersonalWorldRefused(
        "personal_world_current",
        " ".join([*said, *left_out, *_kept(not_allowed, made_outside_groups)]),
    )


def _source_deleted() -> PersonalWorldRefused:
    return PersonalWorldRefused(
        "personal_world_source_deleted",
        "A photograph your world from your photographs was made with was deleted, so it cannot "
        "be opened or added to. This app does not rebuild a world from the photographs that "
        "remain.",
    )


def _changed_elsewhere() -> PersonalWorldRefused:
    return PersonalWorldRefused(
        "personal_world_changed_elsewhere",
        "Your world from your photographs was changed after it was last saved. Open it from your "
        "worlds and choose whether to use the latest changes, then add your photographs.",
    )


def _not_latest() -> PersonalWorldRefused:
    return PersonalWorldRefused(
        "personal_world_not_latest",
        "Your saved world opens an earlier version of your world from your photographs, and "
        "photographs are added only to its latest version. Move your saved world to the latest "
        "version, then add them.",
    )


def _inhabitants_here(adding: int) -> PersonalWorldRefused:
    return PersonalWorldRefused(
        "personal_world_edit_cannot_carry",
        f"{_photographs(adding)} you reviewed since can be added to your world, but its "
        "inhabitants are here, and inhabitants do not move to the world with the added "
        "photographs. Send the inhabitants away first, then add the photographs.",
    )


def _sources_changed() -> PersonalWorldRefused:
    return PersonalWorldRefused(
        "personal_sources_changed",
        "Your reviewed photographs changed after this was checked, so nothing was made. "
        "Check again, then try again.",
    )


def _preview_changed() -> PersonalWorldRefused:
    return PersonalWorldRefused(
        "personal_world_preview_changed",
        "Your world or your photographs changed after you looked, so nothing was added. "
        "Look again, then confirm.",
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
    """The document a route composition's topology digest is the SHA-256 of.

    A composition that adds photographs to a made world also names the snapshot it extends.
    """
    regions: dict[str, list[dict[str, str]]] = {region: [] for region in composition.region_ids}
    for source in composition.sources:
        regions[source.region_id].append(source_slot(workspace_id, source)[1])
    record: dict[str, Any] = {
        "profile": PERSONAL_COMPOSITION_PROFILE,
        "workspace_id": str(workspace_id),
        "regions": [
            {"region_id": region, "source_slots": slots} for region, slots in regions.items()
        ],
        "interpretation": "membership of reviewed photographs in their scene groups; "
        "no new reconstruction or evidence",
    }
    if composition.made_snapshot_id is not None:
        record["extends_snapshot_id"] = str(composition.made_snapshot_id)
    return record


def arrange(sources: PersonalSources, made: MadeWorld | None = None) -> PersonalComposition:
    """The one rule for which region each photograph is a slot of; see the module docstring."""
    made_sources = () if made is None else made.sources
    made_region_of = {source.capture_id: source.region_id for source in made_sources}
    made_regions = () if made is None else made.region_ids

    # Places: photographs connected through live groups (union-find over capture ids).
    parent: dict[uuid.UUID, uuid.UUID] = {}

    def root(capture: uuid.UUID) -> uuid.UUID:
        while parent[capture] != capture:
            parent[capture] = parent[parent[capture]]
            capture = parent[capture]
        return capture

    groups = [group for group in sources.groups if group.capture_ids]
    for group in groups:
        members = sorted(group.capture_ids)
        for capture in members:
            parent.setdefault(capture, capture)
        first = root(members[0])
        for capture in members[1:]:
            other = root(capture)
            if other != first:
                parent[max(first, other)] = min(first, other)
                first = min(first, other)
    rows_of: dict[uuid.UUID, list[LiveSceneGroup]] = {}
    for group in groups:
        rows_of.setdefault(root(next(iter(group.capture_ids))), []).append(group)
    # A place holds a made region when it holds one of its photographs, or when one of its rows
    # is the very group a made region is named by.
    made_ids = set(made_regions)
    touching: dict[uuid.UUID, set[str]] = {}
    for capture, region in made_region_of.items():
        if capture in parent:
            touching.setdefault(root(capture), set()).add(region)
    for place, rows in rows_of.items():
        touching.setdefault(place, set()).update(
            row.group_id for row in rows if row.group_id in made_ids
        )

    reviewed = sorted(sources.reviewed, key=lambda photograph: photograph.capture_id)
    added: list[ComposedSource] = []
    outside = between = 0
    new_region_of_place: dict[uuid.UUID, LiveSceneGroup] = {}
    for photograph in reviewed:
        if photograph.capture_id in made_region_of:
            continue
        if photograph.capture_id not in parent:
            outside += 1
            continue
        place = root(photograph.capture_id)
        regions = touching.get(place, set())
        if len(regions) > 1:
            between += 1
            continue
        if regions:
            (region,) = regions
        else:
            # The largest live row of the place names it; the smaller id breaks a tie.
            named = new_region_of_place.setdefault(
                place, min(rows_of[place], key=lambda row: (-len(row.capture_ids), row.group_id))
            )
            region = named.group_id
        added.append(
            ComposedSource(
                capture_id=photograph.capture_id,
                source_sha256=photograph.source_sha256,
                evidence_span_id=photograph.evidence_span_id,
                region_id=region,
            )
        )

    new_regions = sorted(new_region_of_place.values(), key=lambda row: (row.ordinal, row.group_id))
    region_ids = (*made_regions, *(row.group_id for row in new_regions))
    by_region: dict[str, list[ComposedSource]] = {region: [] for region in region_ids}
    for source in (*made_sources, *added):
        by_region[source.region_id].append(source)
    ordered = tuple(
        source
        for region in region_ids
        for source in sorted(by_region[region], key=lambda slot: slot.capture_id)
    )
    reviewed_captures = {photograph.capture_id for photograph in reviewed}
    return PersonalComposition(
        reviewed=len(reviewed),
        outside_scene_groups=outside,
        sources=ordered,
        region_ids=tuple(region for region in region_ids if by_region[region]),
        reviewed_slots=sum(1 for source in ordered if source.capture_id in reviewed_captures),
        between_places=between,
        added=tuple(sorted(added, key=lambda slot: slot.capture_id)),
        made_outside_groups=frozenset(set(made_region_of) - set(parent)),
        made_snapshot_id=None if made is None else made.snapshot.snapshot_id,
    )


def made_world(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot: SpatialSnapshot,
) -> MadeWorld:
    """The photographs ``snapshot`` holds, found by the source id :func:`source_slot` gives them.

    A slot's capture is the capture of the slot's photograph whose source id is the slot's own,
    computed forward from the capture, never parsed from a key. A slot no capture answers for is
    one this module never composed, and adding to such a world is refused by name.
    """
    rows = connection.execute(
        "select ws.source_id,ws.region_id,ws.evidence_span_id,c.capture_id,"
        "encode(s.blob_sha256,'hex') as source_sha256 "
        "from world_topology_source ws "
        "left join evidence_span s on s.workspace_id=ws.workspace_id "
        "and s.span_id=ws.evidence_span_id "
        "left join capture c on c.workspace_id=ws.workspace_id and c.blob_sha256=s.blob_sha256 "
        "where ws.workspace_id=%s and ws.world_id=%s and ws.topology_digest=%s",
        (workspace_id, world_id, snapshot.digests.topology_sha256),
    ).fetchall()
    found: dict[uuid.UUID, ComposedSource] = {}
    slots = {row["source_id"] for row in rows}
    for row in rows:
        capture = row["capture_id"]
        if capture is None or row["region_id"] is None:
            continue
        if uuid.uuid5(SOURCE_NAMESPACE, f"{workspace_id}:{capture}") == row["source_id"]:
            found[row["source_id"]] = ComposedSource(
                capture_id=capture,
                source_sha256=row["source_sha256"],
                evidence_span_id=row["evidence_span_id"],
                region_id=row["region_id"],
            )
    if not slots or set(found) != slots:
        raise PersonalWorldRefused(
            "personal_world_not_composed",
            "Your world from your photographs holds places this app did not compose from your "
            "reviewed photographs, so it cannot add photographs to it.",
        )
    regions = tuple(region["region_id"] for region in snapshot.candidate.topology["regions"])
    by_region: dict[str, list[ComposedSource]] = {region: [] for region in regions}
    for source in found.values():
        by_region[source.region_id].append(source)
    return MadeWorld(
        snapshot=snapshot,
        region_ids=regions,
        sources=tuple(
            source
            for region in regions
            for source in sorted(by_region[region], key=lambda slot: slot.capture_id)
        ),
    )


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
class AdditionPreview:
    """What adding photographs to a made world does, as the person is shown it before confirming.

    ``sha256`` is the SHA-256 of ``document``, which holds every base the addition compares, every
    count and every sentence; the write adds the photographs only when it is given back.
    """

    sha256: str
    sentences: tuple[str, ...]
    counts: Mapping[str, Any]
    document: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _AdditionBase:
    """The state an addition preview was read from, which the confirmed write compares."""

    entry: SavedWorldEntry
    made: MadeWorld
    carry: CarryPlan
    avatar_revisions: int


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
    composition: PersonalComposition
    #: What adding photographs does, for ``add_photographs`` only.
    preview: AdditionPreview | None = None
    _base: _AdditionBase | None = field(default=None, repr=False, compare=False)


#: The words each kind of carried row is counted in, singular and plural.
_KIND_WORDS: Final[Mapping[EditSubject, tuple[str, str]]] = {
    EditSubject.OBJECT: ("object you placed", "objects you placed"),
    EditSubject.ELEMENT: ("change to a place's structure", "changes to its places' structure"),
    EditSubject.ENVIRONMENT_INSTANCE: ("environment piece", "environment pieces"),
    EditSubject.POINT_MAP_INSTANCE: ("photograph depth estimate", "photograph depth estimates"),
}

#: Why a carried row stays in the previous version, as the object repository names it, in words
#: that complete "because ..." for one row and for several.
_STAYS_BECAUSE: Final[Mapping[StayReason, tuple[str, str]]] = {
    StayReason.SOURCE_WITHDRAWN: ("its source was withdrawn", "their sources were withdrawn"),
    StayReason.BINDING_DRIFT: (
        "the source it was placed from has changed",
        "the sources they were placed from have changed",
    ),
    StayReason.COMPOSITION_DENIED: (
        "its source may no longer be placed in a world",
        "their sources may no longer be placed in a world",
    ),
    StayReason.SOURCE_DELETED: ("its photograph was deleted", "their photographs were deleted"),
    StayReason.RIGHT_ENDED: ("its depth right has ended", "their depth rights have ended"),
    StayReason.NOT_READABLE: ("it can no longer be read", "they can no longer be read"),
}


@dataclass(frozen=True, slots=True)
class _Society:
    """A version's society, as far as adding photographs has to say anything about it."""

    held: bool
    inhabitants: int
    #: ``HERE`` or ``AWAY`` when the society's engine keeps presence; ``None`` when it does not,
    #: and then nothing is known about where its inhabitants are.
    presence: str | None

    @property
    def here(self) -> bool:
        return self.inhabitants > 0 and self.presence == HERE


def _society(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, version_id: uuid.UUID
) -> _Society:
    """The version's society: whether it holds one, how many inhabitants, and where they are.

    A personal-source world holds no society when it is made; this answers for the version as it
    is, so an addition never leaves inhabitants behind without saying so. Inhabitants an engine
    does not send away are not a cause the person can fix, so they do not refuse the addition.
    """
    row = connection.execute(
        "select engine_version,state from world_society "
        "where workspace_id=%s and world_id=%s and version_id=%s",
        (workspace_id, world_id, version_id),
    ).fetchone()
    if row is None:
        return _Society(held=False, inhabitants=0, presence=None)
    return _Society(
        held=True,
        inhabitants=len(row["state"].get("inhabitants") or ()),
        presence=presence(row["state"]) if society_engine(row["engine_version"]).presence else None,
    )


def _society_stays(society: _Society) -> str:
    """What the preview says of a society that stays in the previous version: only what is known."""
    if not society.inhabitants:
        return (
            "Its society, which has no inhabitants, and its history stay only in the previous "
            "version."
        )
    if society.presence is None:
        return "Its inhabitants and their history stay only in the previous version."
    if society.presence == AWAY:
        return "Its inhabitants, who are away, and their history stay only in the previous version."
    raise ValueError(
        f"inhabitants who are {society.presence} refuse an addition; none stays behind"
    )


def _addition_preview(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    composition: PersonalComposition,
    base: _AdditionBase,
    *,
    topology_digest: str,
    not_allowed: int,
    society: _Society,
) -> AdditionPreview:
    """The counts and sentences of an addition, and the digest of both with every base."""
    made_regions = composition.made_region_ids
    joining = Counter(
        source.region_id for source in composition.added if source.region_id in made_regions
    )
    new_places = Counter(
        source.region_id for source in composition.added if source.region_id not in made_regions
    )
    carried = Counter(
        part.subject
        for part in base.carry.parts
        if part.outcome is CarryOutcome.CARRIED and not part.removed
    )
    stays: Counter[tuple[EditSubject, StayReason]] = Counter(
        (part.subject, part.reason)
        for part in base.carry.parts
        if part.outcome is CarryOutcome.STAYS and part.reason is not None
    )
    region_styles = next(
        version.region_styles
        for version in WorldStyleRepository(connection, workspace_id, world_id=world_id).versions()
        if version.version_id == base.entry.style_version_id
    )
    adding = len(composition.added)
    said = [f"{_photographs(adding)} you reviewed since will be added to your world's places."]
    if joining:
        count, places = sum(joining.values()), len(joining)
        said.append(
            f"{count} {_it(count, 'joins', 'join')} {places} "
            f"{_it(places, 'place', 'places')} already in it."
        )
    if new_places:
        count, places = sum(new_places.values()), len(new_places)
        said.append(
            f"{count} {_it(count, 'makes', 'make')} {places} new {_it(places, 'place', 'places')}."
        )
    said.extend(_left_out(composition))
    said.extend(_kept(not_allowed, len(composition.made_outside_groups)))
    made: list[str] = [
        f"{carried[subject]} {_it(carried[subject], *_KIND_WORDS[subject])}"
        for subject in EditSubject
        if carried[subject]
    ]
    if region_styles:
        made.append(
            f"the appearance you gave {len(region_styles)} "
            f"{_it(len(region_styles), 'place', 'places')}"
        )
    if base.avatar_revisions:
        made.append("your avatar's appearance")
    said.append(
        "Its appearance and everything you made in it carry over"
        + (f": {', '.join(made)}." if made else ".")
    )
    for (subject, reason), count in sorted(
        stays.items(), key=lambda item: (item[0][0], item[0][1])
    ):
        kind = _it(count, *_KIND_WORDS[subject])
        said.append(
            f"{count} {kind} {_it(count, 'stays', 'stay')} only in the previous version, "
            f"because {_it(count, *_STAYS_BECAUSE[reason])}."
        )
    if society.held:
        said.append(_society_stays(society))
    edits = base.carry.edits
    if stays:
        said.append(
            "Take back starts from this step, because not everything in your world carries over."
        )
    elif edits:
        said.append("Take back still reaches the changes you made before this step.")
    said.append("Your world as it is now stays saved as its previous version.")
    counts: dict[str, Any] = {
        "photographs_added": adding,
        "photographs_joining_places": sum(joining.values()),
        "places_growing": len(joining),
        "new_places": len(new_places),
        "photographs_in_new_places": sum(new_places.values()),
        "left_out_in_no_place": composition.outside_scene_groups,
        "left_out_between_places": composition.between_places,
        "kept_not_allowed": not_allowed,
        "kept_in_no_place": len(composition.made_outside_groups),
        "carried": {str(subject): carried[subject] for subject in EditSubject},
        "carried_removals": sum(
            1 for part in base.carry.parts if part.outcome is CarryOutcome.CARRIED and part.removed
        ),
        "region_appearances": len(region_styles),
        "avatar_revisions": base.avatar_revisions,
        "stays_behind": [
            {"kind": str(subject), "reason": str(reason), "count": count}
            for (subject, reason), count in sorted(stays.items())
        ],
        "society_staying": society.held,
        "changes_carried": 0 if stays else edits,
    }
    entry = base.entry
    document = {
        "profile": ADDITION_PREVIEW_PROFILE,
        "world_id": world_id,
        "entry_id": str(entry.entry_id),
        "entry_revision": entry.revision,
        "entry_source_snapshot_id": str(entry.source_snapshot_id),
        "snapshot_id": str(base.made.snapshot.snapshot_id),
        "snapshot_sha256": base.made.snapshot.digests.snapshot_sha256,
        "authored_version_id": str(entry.authored_version_id),
        "authored_state_sha256": entry.authored_state_sha256,
        "authored_edit_seq": entry.authored_edit_seq,
        "style_version_id": str(entry.style_version_id),
        "topology_digest": topology_digest,
        "added": [str(source.capture_id) for source in composition.added],
        "counts": counts,
        "sentences": said,
    }
    return AdditionPreview(
        sha256=sha256_of_canonical(document).hex(),
        sentences=tuple(said),
        counts=counts,
        document=document,
    )


def personal_world_plan(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    sources: PersonalSources,
    *,
    store: ContentAddressedStore | None,
) -> PersonalWorldPlan:
    """Decide from the registry, the world's snapshot and its saved entry what may happen now."""
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
    snapshot = (
        None
        if world_id is None
        else WorldStructureRepository(connection, workspace_id, world_id=world_id).current()
    )

    def digest_of(composition: PersonalComposition) -> str | None:
        if not composition.sources:
            return None
        return sha256_of_canonical(personal_composition_record(workspace_id, composition)).hex()

    def refused(
        refusal: PersonalWorldRefused, composition: PersonalComposition
    ) -> PersonalWorldPlan:
        return PersonalWorldPlan(
            None, refusal, world_id, saved_entry_id, digest_of(composition), current, composition
        )

    def plan(action: Action, composition: PersonalComposition) -> PersonalWorldPlan:
        return PersonalWorldPlan(
            action, None, world_id, saved_entry_id, digest_of(composition), current, composition
        )

    if len(personal) > 1:
        return refused(
            PersonalWorldRefused(
                "several_personal_source_worlds",
                f"This account holds {len(personal)} worlds made from its photographs; "
                "choose the one to bring up to date.",
            ),
            arrange(sources),
        )
    if snapshot is None:
        composition = arrange(sources)
        if composition.reviewed == 0:
            return refused(_no_reviewed_sources(), composition)
        if not composition.sources:
            return refused(_no_grouped_sources(composition.reviewed), composition)
        if world_id is None:
            return plan("create_world", composition)
        # Composed but never made: a new topology is what making it will open.
        return plan(
            "update_world" if digest_of(composition) != current else "save_entry", composition
        )
    # Made: its structural snapshot is what every saved world of it opens.
    assert world_id is not None
    if snapshot.invalidated:
        return refused(_source_deleted(), arrange(sources))
    try:
        made = made_world(connection, workspace_id, world_id, snapshot)
    except PersonalWorldRefused as refusal:
        return refused(refusal, arrange(sources))
    composition = arrange(sources, made)
    if saved_entry_id is None:
        # Nothing saves it yet: it opens as it was made, and photographs are added once it is.
        return plan("save_entry", composition)
    not_allowed = len(
        lapsed_personal_captures(
            connection, workspace_id, [source.capture_id for source in made.sources]
        )
    )
    if not composition.added:
        return refused(
            _world_current(composition, not_allowed, len(composition.made_outside_groups)),
            composition,
        )
    entry = SavedWorldEntryRepository(connection, workspace_id, store).entry(saved_entry_id)
    if entry.unavailable_reason == "source_deleted":
        return refused(_source_deleted(), composition)
    if entry.availability != "available":
        return refused(_changed_elsewhere(), composition)
    if entry.source_snapshot_id != snapshot.snapshot_id:
        # A saved world can be moved to any valid version of its world, an earlier one included,
        # and an addition extends only the latest snapshot.
        return refused(_not_latest(), composition)
    society = _society(connection, workspace_id, world_id, entry.authored_version_id)
    if society.here:
        return refused(_inhabitants_here(len(composition.added)), composition)
    objects = WorldObjectRepository(connection, workspace_id, world_id=world_id, store=store)
    base = _AdditionBase(
        entry=entry,
        made=made,
        carry=objects.carry_plan(entry.authored_version_id),
        avatar_revisions=CharacterAppearanceRepository(
            connection, workspace_id, entry.created_by, world_id=world_id
        ).avatar_revisions(entry.authored_version_id),
    )
    digest = digest_of(composition)
    assert digest is not None
    preview = _addition_preview(
        connection,
        workspace_id,
        world_id,
        composition,
        base,
        topology_digest=digest,
        not_allowed=not_allowed,
        society=society,
    )
    return replace(plan("add_photographs", composition), preview=preview, _base=base)


def compose_personal_world(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    sources: PersonalSources,
    *,
    expected_topology_digest: str,
    expected_preview_sha256: str | None = None,
    actor: uuid.UUID,
    store: ContentAddressedStore | None,
) -> tuple[PersonalWorldPlan, dict[str, Any]]:
    """Carry out the plan for exactly the composition, and the preview, the caller was shown.

    The caller reads ``sources`` holding the workspace lock, so nothing it read can change before
    this returns. ``expected_topology_digest`` is the digest the caller was shown; any other
    composition is refused as ``personal_sources_changed`` and nothing is written. Adding
    photographs to a made world also needs ``expected_preview_sha256``, the digest of the preview
    the person confirmed; a preview that no longer matches, a missing one, or one given for any
    other action is refused as ``personal_world_preview_changed`` and nothing is written.
    ``save_entry`` writes nothing and answers with the world and its current topology.
    """
    with connection.transaction():
        lock_workspace(connection, workspace_id)
        plan = personal_world_plan(connection, workspace_id, sources, store=store)
        # The refusal first: it says what is true now, which a digest mismatch alone would not.
        if plan.refusal is not None:
            raise plan.refusal
        if (plan.action == "add_photographs") != (expected_preview_sha256 is not None):
            raise _preview_changed()
        if plan.action == "add_photographs":
            assert plan.preview is not None
            if plan.preview.sha256 != expected_preview_sha256:
                raise _preview_changed()
            try:
                return plan, _add_photographs(
                    connection, workspace_id, plan, actor=actor, store=store
                )
            except (StaleObjectBase, StaleStructuralBase, StaleSavedWorldEntry) as exc:
                # A base the preview named moved between the read under this lock and a write,
                # as a right that ends at that moment does: what the person saw is not what
                # would be written, and raising here undoes every write of the addition.
                raise _preview_changed() from exc
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
        composition = plan.composition
        return plan, register_composition(
            connection,
            workspace_id,
            record=personal_composition_record(workspace_id, composition),
            sources=composition.sources,
            region_ids=composition.region_ids,
            actor=actor,
            reason=_CREATED_BY_ROUTE,
        )


def _add_photographs(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    plan: PersonalWorldPlan,
    *,
    actor: uuid.UUID,
    store: ContentAddressedStore | None,
) -> dict[str, Any]:
    """Every write of an addition, in the caller's transaction, each comparing the base it read."""
    base, preview, composition = plan._base, plan.preview, plan.composition
    assert base is not None and preview is not None and plan.world_id is not None
    world_id, entry, snapshot = plan.world_id, base.entry, base.made.snapshot
    entries = SavedWorldEntryRepository(connection, workspace_id, store)
    entries.lock_authored_advance_base(
        entry.entry_id,
        base_revision=entry.revision,
        world_id=world_id,
        authored_version_id=entry.authored_version_id,
        authored_state_sha256=entry.authored_state_sha256,
        authored_edit_seq=entry.authored_edit_seq,
        mutation_base_state_sha256=entry.authored_state_sha256,
    )
    registered = register_composition(
        connection,
        workspace_id,
        record=personal_composition_record(workspace_id, composition),
        sources=composition.sources,
        region_ids=composition.region_ids,
        actor=actor,
        reason=_CREATED_BY_ROUTE,
    )
    contract = WorldStyleRepository(
        connection, workspace_id, world_id=world_id
    ).current_topology_contract()
    graph_sha256, reconstruction_sha256 = structural_input_digests(connection, workspace_id)
    joining = Counter(
        source.region_id
        for source in composition.added
        if source.region_id in composition.made_region_ids
    )
    candidate = replace(
        composed_candidate(contract, graph_sha256, reconstruction_sha256),
        placement_migrations=tuple(
            PlacementMigration(
                uuid.uuid5(_MIGRATION_NAMESPACE, f"{world_id}:{snapshot.snapshot_id}:{region}"),
                region,
                f"{_photographs(count)} reviewed by the account holder added to this place on "
                f"their confirmation of addition preview {preview.sha256}",
            )
            for region, count in sorted(joining.items())
        ),
    )
    structures = WorldStructureRepository(connection, workspace_id, world_id=world_id)
    structural = structures.preview(candidate, proposed_by=actor)
    advanced = structures.apply(
        structural.preview_id,
        base_snapshot_id=structural.base_snapshot_id,
        base_graph_sha256=structural.base_graph_sha256,
        base_reconstruction_sha256=structural.base_reconstruction_sha256,
        committed_by=actor,
        advanced_composed_topology_digest=registered["topology_digest"],
        confirmed_preview_sha256=preview.sha256,
    )
    version = WorldObjectRepository(
        connection, workspace_id, world_id=world_id, store=store
    ).carry_version(base.carry, source_snapshot_id=advanced.snapshot_id, created_by=actor)
    CharacterAppearanceRepository(
        connection, workspace_id, actor, world_id=world_id
    ).carry_avatar_history(entry.authored_version_id, version.version_id)
    # Written, not read back: the carry holds the asset read lock until this transaction commits,
    # and reading the entry checks its photographs' viewer images in the store. The answer names the
    # entry's own id and the appearance this write keeps.
    entries.update(
        entry.entry_id,
        base_revision=entry.revision,
        authored_version_id=version.version_id,
        expected_authored_state_sha256=version.state_sha256,
        expected_authored_edit_seq=version.edit_seq,
        style_version_id=entry.style_version_id,
    )
    return {
        "world_id": world_id,
        "topology_digest": registered["topology_digest"],
        "style_version_id": str(entry.style_version_id),
        "saved_entry_id": entry.entry_id,
    }
