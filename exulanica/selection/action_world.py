"""The world a Companion plan is read against: what the page supplied, and the reads it rests on.

:func:`read_world` reads a version once per utterance, in one read-only snapshot: the kinds a person
may place, its objects, the published arrangements and its capability descriptors, and what a plan
of things rests on (the kinds a thing may be added as, the placed objects and, where a society is
read, its beings and the places they use). The drafters' options are listed from that read, and
:mod:`exulanica.selection.action_plan` types and prepares every step against it.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import psycopg

from exulanica.selection import action_budget, action_minds, action_things
from exulanica.selection.action_vocabulary import (
    MAX_OBJECT_CHOICES,
    MIND,
    Minds,
    Pieces,
    Play,
    SocietyReader,
)
from exulanica.selection.validation import Session
from exulanica.store.base import ContentAddressedStore
from exulanica.world import InvalidStructuralData
from exulanica.world.arrangements import arrangement_catalog
from exulanica.world.kinds.worker import KindWorkWaiting
from exulanica.world.object_edit_preview import read_only_snapshot
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.placed_things import PlacedThing
from exulanica.world.society_authored_ground import read_authored_ground
from exulanica.world.thing_landing import LandingGround
from exulanica.world.thing_landing_source import prepare_landing_in_region
from exulanica.world.thing_looks import look_choices

# -- what the request is, and what the world offers ---------------------------------------------


@dataclass(frozen=True, slots=True)
class _Context:
    """What the page supplied, carried into request bodies exactly as supplied."""

    version_id: uuid.UUID
    base_state_sha256: str
    origin_role: str | None
    placement: Mapping[str, Any] | None
    viewer: Mapping[str, Any] | None
    selected_object_id: str | None
    saved_entry: Mapping[str, Any] | None

    @classmethod
    def read(cls, request: Mapping[str, Any]) -> _Context:
        context = request.get("context") or {}
        return cls(
            version_id=uuid.UUID(str(request["version_id"])),
            base_state_sha256=str(request["base_state_sha256"]),
            origin_role=request.get("origin_role"),
            placement=context.get("placement"),
            viewer=context.get("viewer"),
            selected_object_id=context.get("selected_object_id"),
            saved_entry=request.get("saved_entry"),
        )

    def viewer_point(self) -> tuple[int, int] | None:
        """Where the person stands on the ground, region-local, where the page said."""
        if self.viewer is None:
            return None
        return (int(self.viewer["x_mm"]), int(self.viewer["z_mm"]))

    def edit_entry(self) -> dict[str, Any] | None:
        """The saved entry as an authored edit takes it: without the style version."""
        if self.saved_entry is None:
            return None
        return {
            key: _plain(self.saved_entry[key])
            for key in ("entry_id", "base_revision", "authored_state_sha256", "authored_edit_seq")
        }


@dataclass(frozen=True, slots=True)
class _Choice:
    label: str
    value: str
    title: str
    detail: str = ""
    selected: bool = False


@dataclass(frozen=True, slots=True)
class _World:
    """The reads one plan rests on: the version, its options and its capability descriptors."""

    world_id: str
    version_id: uuid.UUID
    state_sha256: str
    edit_seq: int
    assets: tuple[_Choice, ...]
    objects: tuple[_Choice, ...]
    arrangements: tuple[_Choice, ...]
    arrangement_versions: Mapping[str, int]
    descriptors: Mapping[str, Mapping[str, Any]]
    object_ids: frozenset[str]
    #: The version's regions and its society, as the capability read lists them.
    region_ids: tuple[str, ...] = ()
    society_held: bool = False
    society_engine: str | None = None
    #: What a plan of things rests on, and the drafter's options for it: the kinds a thing may be
    #: added as, the version's placed objects, the society's beings and the places they use.
    things: action_things.ThingsRead | None = None
    #: Who asks, as a direct request records it.
    actor: uuid.UUID | None = None
    kinds: tuple[_Choice, ...] = ()
    placed: tuple[_Choice, ...] = ()
    beings: tuple[_Choice, ...] = ()
    places: tuple[_Choice, ...] = ()
    #: What new pieces of the world's look rest on, as the route hands it (:class:`Pieces`), or
    #: None where it hands none and the step is not offered.
    pieces: Pieces | None = None
    #: Who may decide for this version's beings, as the route hands it (:class:`Minds`), or None
    #: where it hands none and the step is not offered; with the drafter's options for it: the
    #: society's groups and the minds a being may be given.
    minds: Minds | None = None
    groups: tuple[_Choice, ...] = ()
    mind_choices: tuple[_Choice, ...] = ()
    society_groups: tuple[action_minds.Group, ...] = ()
    #: Playing a being, as the route hands it (:class:`Play`), or None where it hands none.
    play: Play | None = None
    #: The amounts the person's sentence states, as code read them, and the drafter's options
    #: for a budget: each amount, then the two budgets a person may name with no figure.
    said_amounts: tuple[action_budget.Amount, ...] = ()
    amounts: tuple[_Choice, ...] = ()
    #: The budgets with no figure that the sentence states in its own words, and what the shape
    #: of the whole sentence plans (None where it is no shape, and a budget is asked about).
    said_fixed: tuple[str, ...] = ()
    said_shape: str | None = None
    #: The ground a thing added or moved is held to, by region, as the things routes hold it
    #: (:mod:`exulanica.world.thing_landing`); a region missing here, or None, is not checked (a
    #: world the rule cannot read, or a site whose place is still being made). With the version's
    #: placed things, which block one another.
    landings: Mapping[str, LandingGround | None] = field(default_factory=dict)
    placed_things: tuple[PlacedThing, ...] = ()

    def descriptor(self, operation: str) -> Mapping[str, Any] | None:
        return self.descriptors.get(operation)


def read_world(
    connection: psycopg.Connection,
    session: Session,
    context: _Context,
    *,
    world_id: str,
    capabilities: Mapping[str, Any],
    store: ContentAddressedStore | None,
    society: SocietyReader | None = None,
) -> _World:
    """The version, the kinds a person may place, its objects and the published arrangements, and
    what a plan of things rests on: the kinds a thing may be added as, the version's placed objects
    and, where ``society`` reads one, the society's beings and the places they use.

    Raises ``UnknownWorldResource`` for a version this world does not hold, as every version read
    does. Objects are listed newest first by the last edit that touched them, at most
    :data:`MAX_OBJECT_CHOICES`, with the page's selected object always among them. The version,
    its edits and the catalog are read in one read-only snapshot, so the pins a plan states
    (``state_sha256`` and ``edit_seq``) describe one state.
    """
    repository = WorldObjectRepository(
        connection, session.workspace_id, world_id=world_id, store=store
    )
    # Read as the actions route reads it, before the snapshot below: authorizing its inputs needs
    # a transaction of its own at read committed.
    held = None if society is None else society()
    with read_only_snapshot(connection):
        version = repository.version(context.version_id, with_availability=False)
        registry = {row.content_sha256: row for row in repository.reviewed_assets()}
        placeable = repository.placeable_assets(store)
        chosen = look_choices(connection, session.workspace_id, world_id, context.version_id)
        looks = {str(row["thing_id"]): row["look"] for row in chosen["looks"]}
        elevation = _ground_elevation(
            connection,
            session,
            world_id,
            version.source_snapshot_id,
            region_id=(
                str(held[0]["region_id"])
                if held is not None
                else None
                if context.placement is None
                else str(context.placement["region_id"])
            ),
        )
    # Where a step may stand a thing, as its route will judge it: the society's region and the one
    # the person points into. Prepared after the snapshot, as the routes prepare it before theirs.
    landings: dict[str, LandingGround | None] = {}
    for region in {
        str(held[0]["region_id"]) if held is not None else None,
        None if context.placement is None else str(context.placement["region_id"]),
    } - {None}:
        try:
            landings[str(region)] = prepare_landing_in_region(
                repository, context.version_id, str(region)
            )
        except KindWorkWaiting:
            landings[str(region)] = None
    assets = tuple(
        _Choice(label=row.asset_key, value=row.asset_key, title=row.title, detail=row.summary)
        for row in placeable
    )
    last_touch: dict[str, int] = {}
    for edit in version.edits:
        if edit.object_id is not None:
            last_touch[edit.object_id] = edit.edit_seq
    standing = [obj for obj in version.objects if not obj.removed]
    standing.sort(key=lambda obj: (-last_touch.get(obj.object_id, 0), obj.object_id))
    selected = context.selected_object_id
    chosen = [obj for obj in standing if obj.object_id == selected]
    chosen += [obj for obj in standing if obj.object_id != selected][
        : MAX_OBJECT_CHOICES - len(chosen)
    ]
    objects = tuple(
        _Choice(
            label=f"object-{index}",
            value=obj.object_id,
            title=(
                registry[obj.asset_sha256].title
                if obj.asset_sha256 in registry
                else "an unlisted kind"
            ),
            selected=obj.object_id == selected,
        )
        for index, obj in enumerate(chosen, start=1)
    )
    catalog = arrangement_catalog()
    arrangements = tuple(
        _Choice(label=item.key, value=item.key, title=item.title, detail=item.summary)
        for item in catalog.arrangements
    )
    descriptors: dict[str, Mapping[str, Any]] = {}
    for descriptor in capabilities.get("operations", ()):
        # The matrix operations are bound to the version alone, so each key is listed once; the
        # models route is listed once a decision role, and a plan chooses for people.
        if descriptor["operation"] == MIND and descriptor.get("subject") != "person":
            continue
        descriptors.setdefault(str(descriptor["operation"]), descriptor)
    regions = capabilities.get("regions") or {}
    stated = capabilities.get("society") or {}
    read = action_things.read_things(
        world_id=world_id,
        version=version,
        reviewed=registry,
        looks=looks,
        society=held,
        elevation_mm=elevation,
        viewer=context.viewer_point(),
    )
    kinds, placed, beings, places = _thing_choices(read)
    return _World(
        world_id=world_id,
        version_id=context.version_id,
        state_sha256=version.state_sha256,
        edit_seq=version.edit_seq,
        assets=assets,
        objects=objects,
        arrangements=arrangements,
        arrangement_versions={item.key: item.version for item in catalog.arrangements},
        descriptors=descriptors,
        object_ids=frozenset(obj.object_id for obj in standing),
        region_ids=tuple(str(region) for region in regions.get("region_ids") or ()),
        society_held=bool(stated.get("held")),
        society_engine=None if stated.get("engine") is None else str(stated["engine"]),
        things=read,
        actor=session.actor,
        kinds=kinds,
        placed=placed,
        beings=beings,
        places=places,
        landings=landings,
        placed_things=tuple(version.things),
    )


def _ground_elevation(
    connection: psycopg.Connection,
    session: Session,
    world_id: str,
    snapshot_id: uuid.UUID,
    *,
    region_id: str | None,
) -> int | None:
    """The elevation the version's ground stands at in ``region_id``, as the society reads it, or
    None where the version states no ground there (a world made from photographs)."""
    if region_id is None:
        return None
    try:
        ground = read_authored_ground(
            connection, session.workspace_id, world_id, snapshot_id, region_id=region_id
        )
    except (InvalidStructuralData, ValueError):
        return None
    return None if ground is None else ground.elevation_mm


def _thing_choices(
    read: action_things.ThingsRead,
) -> tuple[tuple[_Choice, ...], tuple[_Choice, ...], tuple[_Choice, ...], tuple[_Choice, ...]]:
    """The drafter's options for a plan of things, each by an opaque label: kinds by their key,
    placed objects, beings and places by number. A being from outside is named by its kind and
    number alone."""
    kinds = tuple(
        _Choice(label=kind.key, value=kind.key, title=kind.label, detail=kind.summary)
        for kind in read.kinds
    )
    placed = tuple(
        _Choice(
            label=f"thing-{index}",
            value=f"thing:{item.thing_id}",
            title=item.label
            if item.look_label in (None, item.label)
            else f"{item.label} (looks like: {item.look_label})",
        )
        for index, item in enumerate(read.placed, start=1)
    )
    society = read.society
    beings: tuple[_Choice, ...] = ()
    places: tuple[_Choice, ...] = ()
    if society is not None:
        beings = tuple(
            _Choice(
                label=f"being-{index}",
                value=being.id,
                title=(
                    f"{being.display_name} (a visitor from outside)"
                    if being.from_outside
                    else being.display_name
                    + (
                        ""
                        if being.kind_label is None
                        else f" (kind: {being.kind_label}"
                        + ("" if being.look_label is None else f"; looks like: {being.look_label}")
                        + ")"
                    )
                ),
            )
            for index, being in enumerate(society.beings, start=1)
        )
        places = tuple(
            _Choice(
                label=f"place-{index}",
                value=place.target_id,
                title=f"the {place.title}, to {place.affordance.replace('_', ' ')}",
            )
            for index, place in enumerate(society.places, start=1)
        )
    return kinds, placed, beings, places


def _plain(value: Any) -> Any:
    """A request value as JSON carries it: ids as strings, mappings and lists copied."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value
