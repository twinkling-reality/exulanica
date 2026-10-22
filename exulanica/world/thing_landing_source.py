"""A world's ground as a move or a placing of a thing reads it, prepared before the edit's
transaction.

:func:`prepare_landing` (a move, by the thing's own region) and :func:`prepare_landing_in_region`
(a placing, by the region it names) read the version's source the way its society does
(:func:`~exulanica.world.society_authored_ground.read_authored_ground`), and return the
:class:`~exulanica.world.thing_landing.LandingGround` the edit is held to, or None for a world whose
ground the rule cannot read, which is edited as before and said to be unchecked:

* a ground walked on a lattice (a starter, a world made from photographs): the plane at its
  elevation, edged where the world's own ground states its area;
* a site world: its place and named blocked parts from the kind worker, through the cache its
  society reads (made with the world, or asked of the worker here, outside any lock, answered as
  :class:`~exulanica.world.kinds.worker.KindWorkWaiting` while it is being made); a site world
  made from terrain has no society projection and is not checked;
* a town: its records with the version's changes to its buildings
  (:mod:`~exulanica.world.version_town`) and their blocked parts, so a thing lands where a removed
  building stood and against a taller or lower one's own massing, and rests on the city's own
  street surface where it stands (:func:`town_surface`, the surface the town's tiles draw and its
  walkers walk on), elsewhere at the walking line nearest it.

Every figure is turned into the region's frame (east and south), the frame a placed thing's pose
is in. The version's other placed objects are read inside the edit's own transaction
(:func:`~exulanica.world.thing_landing.blocking_things`), so they cannot have moved since.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from exulanica.grammar.grammars.city.surface import city_surface_z_at
from exulanica.world.errors import InvalidStructuralData, UnknownWorldResource
from exulanica.world.generated_worlds import generated_extent, generation_receipt, states_site
from exulanica.world.kinds.worker import (
    PLACE_SECONDS,
    KindWorkWaiting,
    kind_worker,
    place_job,
    place_key,
    site_ground_place_id,
)
from exulanica.world.site_parts import changes_document, changes_sha256
from exulanica.world.society_authored_ground import SocietyGround, read_authored_ground
from exulanica.world.society_city_place import city_blocked_parts
from exulanica.world.society_walking_surfaces import (
    rests_on_surface,
    surface_height_at,
    walking_surfaces_place,
)
from exulanica.world.thing_landing import BlockedPart, LandingGround, plane_height, rests_on_plane
from exulanica.world.version_town import town_key, version_town_records

if TYPE_CHECKING:
    import psycopg

    from exulanica.world.object_repository import WorldObjectRepository

__all__ = ["prepare_landing", "prepare_landing_in_region", "town_surface"]


def prepare_landing(
    repository: WorldObjectRepository, version_id: uuid.UUID, thing_id: str
) -> LandingGround | None:
    """The ground a move of ``thing_id`` in ``version_id`` is held to, or None where it is not
    checked. Raises ``UnknownWorldResource`` for an unknown version, as the move does first, and
    ``KindWorkWaiting`` while a site's place is being made. An unknown thing is left to the move,
    which checks its base before it looks the thing up: a stale base is answered as stale
    whatever the id."""
    repository.edit_base_row(version_id)
    try:
        thing = repository.placed_thing(version_id, thing_id)
    except UnknownWorldResource:
        return None
    return prepare_landing_in_region(repository, version_id, thing.region_id)


def prepare_landing_in_region(
    repository: WorldObjectRepository, version_id: uuid.UUID, region_id: str
) -> LandingGround | None:
    """The ground a thing placed in ``region_id`` of ``version_id`` is held to, or None where it is
    not checked. Raises as :func:`prepare_landing` does. A region the version's source does not
    hold is left to the placing, which refuses it after checking its base."""
    row = repository.edit_base_row(version_id)
    connection = repository.connection
    try:
        ground = read_authored_ground(
            connection,
            repository.workspace_id,
            repository.world_id,
            row["source_snapshot_id"],
            region_id=region_id,
        )
    except InvalidStructuralData:
        return None
    if ground is None:
        return None
    if ground.navigation_form != "walking_surfaces":
        area = (
            ground.area
            if ground.area.source == "ground" and ground.ground_kind != "endless"
            else None
        )
        return LandingGround(
            ground.region_id,
            area,
            rests_on_plane(ground.elevation_mm),
            (),
            plane_height(ground.elevation_mm),
        )
    if states_site(connection, repository.workspace_id, repository.world_id, ground.snapshot_id):
        answer = _site_place(repository, ground, version_id)
        if answer is None:
            return None
        place, parts = answer
        rest = surface_height_at(place, ground)
    else:
        scope = (repository.workspace_id, repository.world_id, ground.snapshot_id)
        key, changes = town_key(connection, *scope, version_id)
        if key is None:
            return None  # A change the town does not take: its ground cannot be read.
        try:
            generated = version_town_records(connection, *scope, changes)
        except InvalidStructuralData:
            return None
        place = walking_surfaces_place(ground.place_id, generated.records)
        rest = town_surface(connection, *scope, generated.records, surface_height_at(place, ground))
        parts = tuple(
            BlockedPart(kind, label, tuple((x, -y) for x, y in ring))
            for kind, label, ring in city_blocked_parts(generated.records)
        )
    return LandingGround(ground.region_id, ground.area, rests_on_surface(rest), parts, rest)


def town_surface(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot_id: uuid.UUID,
    records: Sequence[object],
    lines: Callable[[tuple[int, int]], int],
) -> Callable[[tuple[int, int]], int]:
    """The height a thing rests at in a town, at a point of its region (east and south), in the
    frame a thing's pose is in: the city's own street surface there (``city_surface_z_at``, east
    and north, above the city's datum), and where it states none (a corner, a junction, a lot) the
    height of ``lines``, the walking line nearest the point (``surface_height_at``). A town on land
    hangs its region at the city's datum, as its tiles stand on the land; any other town hangs it
    at its arrival's height, where its people stand. A society of things reads whether a placed
    thing rests by the same surface
    (:func:`~exulanica.world.society_walking_surfaces.build_walking_surfaces_input`'s ``rest``)."""
    scope = (connection, workspace_id, world_id, snapshot_id)
    surface = city_surface_z_at(records)
    _, receipt = generation_receipt(*scope)
    floor = 0 if receipt.get("land_sha256") is not None else generated_extent(*scope).arrival_mm[1]

    def rest(point: tuple[int, int]) -> int:
        height = surface((point[0], -point[1]))
        return (lines(point) if height is None else height) - floor

    return rest


def _site_place(
    repository: WorldObjectRepository, ground: SocietyGround, version_id: uuid.UUID
) -> tuple[Mapping[str, Any], tuple[BlockedPart, ...]] | None:
    """A site world's place and blocked parts as the version's society reads them, made from its
    records with the version's changes to its parts, or None for a site the worker makes no place
    for (one made from terrain)."""
    digest, receipt = generation_receipt(
        repository.connection, repository.workspace_id, repository.world_id, ground.snapshot_id
    )
    changes = repository.part_changes(version_id)
    worker = kind_worker()
    workspace = str(repository.workspace_id)
    placed = worker.run(
        place_key(workspace, digest, site_ground_place_id(), changes_sha256(changes)),
        PLACE_SECONDS,
        place_job,
        workspace,
        dict(receipt),
        digest,
        site_ground_place_id(),
        changes_document(changes),
        workspace=workspace,
        kept=worker.places,
    )
    if placed.status != "done" or placed.value is None:
        raise KindWorkWaiting(placed.status, kept=True, reason=placed.reason)
    if placed.value["status"] != "done":
        return None
    named = placed.value.get("blocked_parts")
    if named is None:
        # A place the worker kept before it named its parts: the same boxes, unnamed.
        named = [{"part": "blocked", "label": "", "box": box} for box in placed.value["blocked"]]
    return placed.value["place"], tuple(_site_part(part) for part in named)


def _site_part(part: Mapping[str, Any]) -> BlockedPart:
    """A site's box (east and north from its south-west corner) as a ring in the region's frame,
    whose east is the site's and whose south is minus its north."""
    x0, y0, x1, y1 = (int(value) for value in part["box"])
    return BlockedPart(
        part["part"], str(part["label"]), ((x0, -y0), (x1, -y0), (x1, -y1), (x0, -y1))
    )
