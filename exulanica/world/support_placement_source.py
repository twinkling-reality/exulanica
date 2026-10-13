"""Reconciled site sources and current authored occupancy for bounded support placement.

Expensive source reconstruction uses the existing scoped worker drawing/place caches. Current
occupancy is read under the normal authored writer lock. No new cache, table or renderer-derived
authority is introduced.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from exulanica.canonical import sha256_of_canonical
from exulanica.things.kinds import ThingKind
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.generated_worlds import generation_receipt, states_site
from exulanica.world.kinds.worker import (
    DRAWING_SECONDS,
    PLACE_SECONDS,
    KindWorkWaiting,
    drawing_job,
    drawing_key,
    kind_worker,
    place_job,
    place_key,
    site_ground_place_id,
)
from exulanica.world.placed_things import PlacedThing, WorkspaceKindReference, shipped_kind
from exulanica.world.support_placement import (
    PlacementContext,
    PlacementSolid,
    SupportedPlacement,
    SupportPlacementRefused,
    all_yaw_radius,
    protected_actor_volumes,
    validate_supported_placement,
)
from exulanica.world.support_surfaces import SupportNetwork, read_support_network
from exulanica.world.thing_store import ThingStore

if TYPE_CHECKING:
    from exulanica.world.object_repository import WorldObjectRepository


@dataclass(frozen=True, slots=True)
class SupportPlacementSource:
    """An immutable worker-reconciled source for one exact generated snapshot."""

    world_id: str
    source_snapshot_id: uuid.UUID
    receipt_sha256: str
    region_id: str
    network: SupportNetwork
    actor_volumes: tuple[PlacementSolid, ...]
    physical_solids: tuple[PlacementSolid, ...] = ()


def source_from_documents(
    world_id: str,
    snapshot_id: uuid.UUID,
    digest: str,
    drawing: Mapping[str, Any],
    place: Mapping[str, Any],
) -> SupportPlacementSource:
    """Read only worker-reconciled source documents; never a client's network declaration."""
    if drawing["profile"] != "exulanica.site-drawing/v2" or drawing["receipt_sha256"] != digest:
        raise SupportPlacementRefused("source", "requires the exact reconciled drawing version 2")
    network = read_support_network(drawing["support"]["network"])
    if network.document()["source"]["world_id"] != world_id:
        raise SupportPlacementRefused("source", "reconciled network belongs to another world")
    if place["document_sha256"] != drawing["support"]["place_sha256"]:
        raise SupportPlacementRefused("source", "drawing and combined actor place disagree")
    physical = []
    for slot in drawing["slots"]:
        width, depth, height = slot["boxMm"]
        if slot["primitive"] == "none" or height <= 0:
            continue
        if slot["yawQuarterTurns"] % 2:
            width, depth = depth, width
        x, north, z = slot["positionMm"]
        hx, hy = (width + 1) // 2, (depth + 1) // 2
        key = "source-slot/" + sha256_of_canonical(slot["identity"]).hex()
        physical.append(
            PlacementSolid(key, (x - hx, -north - hy, z, x + hx, -north + hy, z + height))
        )
    return SupportPlacementSource(
        world_id,
        snapshot_id,
        digest,
        "region:generated",
        network,
        protected_actor_volumes(place, network, north_positive=True),
        tuple(sorted(physical, key=lambda volume: volume.solid_id)),
    )


def prepare_support_source(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    *,
    base_state_sha256: str | None = None,
) -> SupportPlacementSource:
    """Read only an authorized, noninvalidated version; reconcile its source outside edit locks."""
    row = repository.edit_base_row(version_id)
    repository.require_edit_base(
        row, row["state_sha256"] if base_state_sha256 is None else base_state_sha256
    )
    if not states_site(
        repository.connection,
        repository.workspace_id,
        repository.world_id,
        row["source_snapshot_id"],
    ):
        raise SupportPlacementRefused(
            "source", "requires an admitted site-plan version 2 support network"
        )
    digest, receipt = generation_receipt(
        repository.connection,
        repository.workspace_id,
        repository.world_id,
        row["source_snapshot_id"],
    )
    if receipt.get("composer") != {"key": "site-plan", "version": 2}:
        raise SupportPlacementRefused(
            "source", "requires an admitted site-plan version 2 support network"
        )
    worker = kind_worker()
    workspace = str(repository.workspace_id)
    drawn = worker.run(
        drawing_key(workspace, digest),
        DRAWING_SECONDS,
        drawing_job,
        workspace,
        repository.world_id,
        dict(receipt),
        digest,
        workspace=workspace,
        kept=worker.drawings,
    )
    if drawn.status != "done" or drawn.value is None:
        raise KindWorkWaiting(drawn.status)
    if drawn.value["status"] != "done":
        raise SupportPlacementRefused("source", drawn.value["detail"])
    drawing = json.loads(drawn.value["body"])
    if drawing["profile"] != "exulanica.site-drawing/v2":
        raise SupportPlacementRefused("source", "requires a reconciled drawing version 2")
    place_id = site_ground_place_id()
    placed = worker.run(
        place_key(workspace, digest, place_id),
        PLACE_SECONDS,
        place_job,
        workspace,
        dict(receipt),
        digest,
        place_id,
        workspace=workspace,
        kept=worker.places,
    )
    if placed.status != "done" or placed.value is None:
        raise KindWorkWaiting(placed.status)
    if placed.value["status"] != "done":
        raise SupportPlacementRefused("source", placed.value["detail"])
    place = placed.value["place"]
    return source_from_documents(
        repository.world_id, row["source_snapshot_id"], digest, drawing, place
    )


def placed_kind(repository: WorldObjectRepository, thing: PlacedThing) -> ThingKind:
    """Resolve the actual pinned kind, with no look or requested box substitution."""
    if thing.kind_gone:
        raise SupportPlacementRefused("kind", "the placed kind is no longer available")
    if isinstance(thing.kind, WorkspaceKindReference):
        kind = ThingStore(repository.connection, repository.workspace_id, None).kind_by_digest(
            thing.kind.sha256
        )
        if kind is None:
            raise SupportPlacementRefused("kind", "the workspace no longer holds that kind")
        return kind
    try:
        return shipped_kind(thing.kind)
    except InvalidThingPlacement as exc:
        raise SupportPlacementRefused("kind", "the pinned shipped kind is unavailable") from exc


def occupancy(
    version: AlternateVersion,
    source: SupportPlacementSource,
    kinds: Mapping[str, ThingKind],
    *,
    exclude_thing_id: str | None = None,
) -> tuple[tuple[PlacementSolid, ...], tuple[str, ...]]:
    """Conservative physical proxies; unknown content refuses, even if it offers no activity."""
    # Placement is physical occupancy, so nonblocking source fixture envelopes matter too.
    # Walking's published network keeps its original semantic blockers and bytes unchanged.
    solids = list(source.physical_solids)
    unknown = []
    for section, identity in (
        (version.objects, "object_id"),
        (version.environment_instances, "instance_id"),
        (version.point_map_instances, "instance_id"),
    ):
        for item in section:
            if not item.removed and item.region_id == source.region_id:
                unknown.append(getattr(item, identity))
    if version.element_overrides:
        unknown.append("source-element-overrides")
    for thing in version.things:
        if (
            thing.removed
            or thing.region_id != source.region_id
            or thing.thing_id == exclude_thing_id
        ):
            continue
        kind = kinds.get(thing.thing_id)
        if (
            kind is None
            or not isinstance(kind, ThingKind)
            or kind.klass != "object"
            or kind.plan != "rigid/v1"
            or kind.document["moves"]
        ):
            unknown.append(thing.thing_id)
            continue
        body = kind.document["body"]["box_mm"]
        radius = all_yaw_radius(body)
        pose = thing.transform
        solids.append(
            PlacementSolid(
                thing.thing_id,
                (
                    pose.x_mm - radius,
                    pose.z_mm - radius,
                    pose.y_mm,
                    pose.x_mm + radius,
                    pose.z_mm + radius,
                    pose.y_mm + body["height"],
                ),
            )
        )
    return tuple(sorted(solids, key=lambda s: s.solid_id)), tuple(sorted(unknown))


def placement_context(
    repository: WorldObjectRepository,
    version: AlternateVersion,
    source: SupportPlacementSource,
    *,
    exclude_thing_id: str | None = None,
) -> PlacementContext:
    """Recheck semantic source equality inside the same transaction as the authored write."""
    if (
        version.world_id != source.world_id
        or version.source_snapshot_id != source.source_snapshot_id
    ):
        raise SupportPlacementRefused("source", "owning version and support source disagree")
    digest, _ = generation_receipt(
        repository.connection,
        repository.workspace_id,
        repository.world_id,
        version.source_snapshot_id,
    )
    if digest != source.receipt_sha256:
        raise SupportPlacementRefused("source", "the source receipt binding changed")
    kinds = {}
    for thing in version.things:
        if not thing.removed and thing.region_id == source.region_id:
            with suppress(SupportPlacementRefused):
                kinds[thing.thing_id] = placed_kind(repository, thing)
    solids, unknown = occupancy(version, source, kinds, exclude_thing_id=exclude_thing_id)
    return PlacementContext(
        version.world_id,
        version.version_id,
        version.source_snapshot_id,
        source.receipt_sha256,
        version.state_sha256,
        source.region_id,
        source.network,
        solids,
        unknown,
        source.actor_volumes,
    )


def validate_bound_thing(
    repository: WorldObjectRepository,
    version: AlternateVersion,
    thing: PlacedThing,
    source: SupportPlacementSource,
) -> SupportedPlacement:
    """Current availability excludes the queried thing's own obstruction, never its neighbors."""
    from exulanica.world.placed_things import ThingPlacement

    if thing.support is None:
        raise SupportPlacementRefused("support", "this thing has no authored support affinity")
    ctx = placement_context(repository, version, source, exclude_thing_id=thing.thing_id)
    p = ThingPlacement(thing.thing_id, thing.kind, thing.region_id, thing.transform, thing.origin)
    return validate_supported_placement(
        p, placed_kind(repository, thing), thing.support.document(), context=ctx
    )
