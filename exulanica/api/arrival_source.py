"""Resolve one saved world's retained scene pin through current source and scene rights."""

from __future__ import annotations

import datetime as dt
import uuid
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass

import psycopg
from psycopg.pq import TransactionStatus

from exulanica.api.arrival_scene_pose import scene_arrival_pose, standalone_opm_footprint
from exulanica.errors import BlobNotFoundError, IntegrityError, TombstonedError
from exulanica.evidence.blob import BlobId
from exulanica.graph.asset_read_policy import (
    evaluation_time,
    final_check,
    point_allowed,
    scene_allowed,
    scene_inputs,
)
from exulanica.graph.geometry import point_map_descriptors, read_point_map
from exulanica.graph.payload import ReconstructionSceneRow
from exulanica.graph.reconstruction_scenes import reconstruction_scene_rows
from exulanica.graph.scene_geometry import read_scene_geometry
from exulanica.graph.snapshot import read_snapshot
from exulanica.store.base import ContentAddressedStore
from exulanica.world.arrival_selection import (
    ArrivalDescriptor,
    OwnedSource,
    PhotographArrivalPin,
    PointMapArrivalPin,
    RetainedScenePin,
    fallback_arrival_pose,
    fallback_arrival_pose_for_radius,
    select_owned_opening_region,
    unique_source_regions,
)
from exulanica.world.errors import InvalidatedSourceVersion, UnknownWorldResource
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.repository import WorldStyleRepository


def arrival_read_check(connection: psycopg.Connection) -> AbstractContextManager[dt.datetime]:
    """Read now in a writer transaction; its caller performs the locked final check.

    Entry GETs use the ordinary final read barrier. Society creation buffers store bytes inside
    its write transaction and checks the same rows after taking its asset barrier.
    """
    return (
        final_check(connection)
        if connection.info.transaction_status == TransactionStatus.IDLE
        else nullcontext(evaluation_time(connection))
    )


def _buffer_exact_bytes(store: ContentAddressedStore, digest: str, size: int) -> bytes | None:
    """Buffer manifest-named bytes before a writer's asset lock, with no permission claim."""
    try:
        payload = store.get(BlobId(bytes.fromhex(digest)))
    except (BlobNotFoundError, IntegrityError, ValueError):
        return None
    return payload if len(payload) == size else None


def _scene_point_bytes(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene: ReconstructionSceneRow,
    artifact_id: str,
    store: ContentAddressedStore,
) -> bytes | None:
    if connection.info.transaction_status == TransactionStatus.IDLE:
        value = read_point_map(connection, workspace, uuid.UUID(artifact_id), store)
        return None if value is None else value.payload
    for member in scene.members:
        for value in (member.placement, member.unposed_point_map):
            if value is not None and str(value.artifact_id) == artifact_id:
                if value.state != "available" or value.reference is None:
                    return None
                return _buffer_exact_bytes(store, value.content_sha256, value.reference.byte_size)
    return None


def _scene_trained_bytes(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene: ReconstructionSceneRow,
    artifact_id: str,
    job_id: uuid.UUID,
    store: ContentAddressedStore,
) -> bytes | None:
    if connection.info.transaction_status == TransactionStatus.IDLE:
        value = read_scene_geometry(
            connection, workspace, uuid.UUID(artifact_id), store, retained_job_id=job_id
        )
        return None if value is None else value.payload
    trained = scene.trained_geometry
    if (
        trained is None
        or str(trained.artifact_id) != artifact_id
        or trained.state != "available"
        or trained.reference is None
    ):
        return None
    return _buffer_exact_bytes(store, trained.content_sha256, trained.reference.byte_size)


def selected_arrival_region(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    source_snapshot_id: uuid.UUID,
    store: ContentAddressedStore,
) -> str | None:
    """Resolve the v4 region from current world membership, graph and version placements."""
    version = WorldObjectRepository(connection, workspace, world_id=world_id, store=None).version(
        version_id, with_availability=False
    )
    if version.source_snapshot_id != source_snapshot_id or version.source_invalidated:
        return None
    snapshot = connection.execute(
        "select topology from world_structure_snapshot where workspace_id=%s and world_id=%s "
        "and snapshot_id=%s",
        (workspace, world_id, source_snapshot_id),
    ).fetchone()
    if snapshot is None:
        return None
    topology_regions = [str(row["region_id"]) for row in snapshot["topology"]["regions"]]
    sources = WorldStyleRepository(connection, workspace, world_id=world_id).source_media(
        store, source_snapshot_id=source_snapshot_id
    )
    owned = [
        OwnedSource(
            source.region_id,
            tuple(str(capture) for capture in source.capture_ids),
            source.captured_at,
            source.state.value == "available",
        )
        for source in sources
        if source.region_id is not None and source.state.value == "available"
    ]
    graph = read_snapshot(connection, workspace, store)
    graph_captures = {str(occurrence.capture_id) for occurrence in graph.occurrences}
    graph_captures.update(
        str(capture) for entity in graph.entities for capture in entity.capture_ids
    )
    graph_captures.update(
        str(capture) for group in graph.scene_groups for capture in group.capture_ids
    )
    graph_captures.update(
        str(member.capture_id) for scene in graph.reconstruction_scenes for member in scene.members
    )
    placements = [
        value.region_id
        for values in (version.objects, version.environment_instances, version.point_map_instances)
        for value in values
        if not value.removed
    ]
    return select_owned_opening_region(owned, topology_regions, graph_captures, placements)


def photograph_arrival_descriptor(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    source_snapshot_id: uuid.UUID,
    store: ContentAddressedStore,
) -> ArrivalDescriptor | None:
    """Pin the current owned source photograph where no drawable geometry overrides it."""
    region = selected_arrival_region(
        connection, workspace, world_id, version_id, source_snapshot_id, store
    )
    if region is None:
        return None
    sources = WorldStyleRepository(connection, workspace, world_id=world_id).source_media(
        store, source_snapshot_id=source_snapshot_id
    )
    owned = [
        OwnedSource(
            source.region_id,
            tuple(str(capture) for capture in source.capture_ids),
            source.captured_at,
            source.state.value == "available",
        )
        for source in sources
        if source.region_id is not None and source.state.value == "available"
    ]
    region_by_capture = unique_source_regions(owned)
    first = sorted(
        (
            source.captured_at is None,
            source.captured_at,
            str(capture),
        )
        for source in sources
        if source.region_id == region and source.state.value == "available"
        for capture in source.capture_ids
        if region_by_capture.get(str(capture)) == region
    )
    if not first:
        return None
    graph = read_snapshot(connection, workspace, store)
    anchors = sum(
        occurrence.occurrence_class in {"person", "place", "object", "event"}
        and region_by_capture.get(str(occurrence.capture_id)) == region
        for occurrence in graph.occurrences
    )
    position, forward = fallback_arrival_pose(anchors)
    return ArrivalDescriptor.model_validate(
        {
            "profile": "exulanica.arrival-descriptor/v1",
            "presentation_policy": "exulanica.arrival-presentation/v1",
            "region_id": region,
            "position_local_mm": position,
            "forward_local_millionths": forward,
            "source": {
                "profile": "exulanica.arrival-photograph-pin/v1",
                "world_id": world_id,
                "version_id": str(version_id),
                "source_snapshot_id": str(source_snapshot_id),
                "region_id": region,
                "capture_id": first[0][2],
            },
        }
    )


def current_arrival_descriptor(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    source_snapshot_id: uuid.UUID,
    store: ContentAddressedStore,
) -> ArrivalDescriptor | None:
    """Pin the authorized geometry branch the browser can draw in the selected owned region."""
    photograph = photograph_arrival_descriptor(
        connection, workspace, world_id, version_id, source_snapshot_id, store
    )
    if photograph is None:
        return None
    region = photograph.region_id
    sources = WorldStyleRepository(connection, workspace, world_id=world_id).source_media(
        store, source_snapshot_id=source_snapshot_id
    )
    region_of = unique_source_regions(
        OwnedSource(
            source.region_id,
            tuple(str(capture) for capture in source.capture_ids),
            source.captured_at,
            source.state.value == "available",
        )
        for source in sources
        if source.region_id is not None and source.state.value == "available"
    )
    graph = read_snapshot(connection, workspace, store)
    substrate_rank = {
        "gaussian_splats": 3,
        "posed_point_maps": 2,
        "unposed_point_maps": 1,
        "source_photographs": 0,
    }
    candidates = sorted(
        (
            scene
            for scene in graph.reconstruction_scenes
            if scene.members
            and all(region_of.get(str(member.capture_id)) == region for member in scene.members)
        ),
        key=lambda scene: (
            -len(scene.members),
            -substrate_rank[scene.rendering_substrate],
            str(scene.scene_id),
        ),
    )
    if candidates:
        scene = candidates[0]
        buffered = scene_inputs(connection, workspace, scene.scene_id, store)
        if buffered is not None:
            job_id = buffered[0]["job_id"]

            def map_bytes(artifact_id: str) -> bytes | None:
                try:
                    return _scene_point_bytes(connection, workspace, scene, artifact_id, store)
                except (BlobNotFoundError, IntegrityError, TombstonedError):
                    return None

            def trained_bytes(artifact_id: str) -> bytes | None:
                try:
                    return _scene_trained_bytes(
                        connection, workspace, scene, artifact_id, job_id, store
                    )
                except (BlobNotFoundError, IntegrityError, TombstonedError):
                    return None

            pose = scene_arrival_pose(scene, map_bytes, trained_bytes)
            if pose is not None:
                with arrival_read_check(connection) as at:
                    permitted = scene_allowed(connection, workspace, scene.scene_id, buffered, at)
                if permitted:
                    row = buffered[0]
                    return _descriptor(
                        region,
                        pose,
                        {
                            "profile": "exulanica.arrival-scene-pin/v1",
                            "world_id": world_id,
                            "version_id": str(version_id),
                            "source_snapshot_id": str(source_snapshot_id),
                            "region_id": region,
                            "scene_id": str(scene.scene_id),
                            "job_id": str(job_id),
                            "pose_receipt_sha256": bytes(row["content_sha256"]).hex(),
                            "placement_receipt_sha256": bytes(row["placement_sha256"]).hex(),
                            "gate_receipt_sha256": bytes(row["gate_sha256"]).hex(),
                        },
                    )

    for candidate in point_map_descriptors(connection, workspace, store):
        if (
            region_of.get(str(candidate.capture_id)) != region
            or candidate.state.value != "available"
        ):
            continue
        if connection.info.transaction_status == TransactionStatus.IDLE:
            value = read_point_map(connection, workspace, candidate.artifact_id, store)
            payload = (
                None
                if value is None or value.content_sha256 != candidate.content_sha256
                else value.payload
            )
        else:
            payload = _buffer_exact_bytes(store, candidate.content_sha256, candidate.byte_size)
        if payload is None:
            continue
        position, forward = fallback_arrival_pose_for_radius(standalone_opm_footprint(payload))
        return ArrivalDescriptor.model_validate(
            {
                "profile": "exulanica.arrival-descriptor/v1",
                "presentation_policy": "exulanica.arrival-presentation/v1",
                "region_id": region,
                "position_local_mm": position,
                "forward_local_millionths": forward,
                "source": {
                    "profile": "exulanica.arrival-point-map-pin/v1",
                    "world_id": world_id,
                    "version_id": str(version_id),
                    "source_snapshot_id": str(source_snapshot_id),
                    "region_id": region,
                    "capture_id": str(candidate.capture_id),
                    "artifact_id": str(candidate.artifact_id),
                    "content_sha256": candidate.content_sha256,
                    "byte_size": candidate.byte_size,
                },
            }
        )
    return photograph


def _descriptor(
    region: str,
    pose: tuple[tuple[float, float, float], tuple[float, float, float]],
    source: dict,
) -> ArrivalDescriptor:
    position, forward = pose
    return ArrivalDescriptor.model_validate(
        {
            "profile": "exulanica.arrival-descriptor/v1",
            "presentation_policy": "exulanica.arrival-presentation/v1",
            "region_id": region,
            "position_local_mm": [round(value * 1000) for value in position],
            "forward_local_millionths": [round(value * 1_000_000) for value in forward],
            "source": source,
        }
    )


def authorized_retained_scene(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    pin: RetainedScenePin,
    store: ContentAddressedStore,
) -> ReconstructionSceneRow | None:
    """Read a pinned scene only in its world and after a final authorization recheck.

    The caller obtains ``pin`` from the stored v4 input, not a request field. A valid shape alone
    has no authority: this checks the bound version's snapshot, world source membership, retained
    build claim, exact receipt digests and every member's current point-map rights.
    """
    version = connection.execute(
        "select 1 from world_alternate_version where workspace_id=%s and world_id=%s "
        "and version_id=%s and source_snapshot_id=%s",
        (workspace, pin.world_id, pin.version_id, pin.source_snapshot_id),
    ).fetchone()
    if version is None:
        return None
    try:
        sources = WorldStyleRepository(connection, workspace, world_id=pin.world_id).source_media(
            store, source_snapshot_id=pin.source_snapshot_id
        )
    except (InvalidatedSourceVersion, UnknownWorldResource):
        return None
    owned = [
        OwnedSource(
            source.region_id,
            tuple(str(capture) for capture in source.capture_ids),
            source.captured_at,
            source.state.value == "available",
        )
        for source in sources
        if source.region_id is not None and source.state.value == "available"
    ]
    region_by_capture = unique_source_regions(owned)
    buffered = scene_inputs(connection, workspace, pin.scene_id, store, retained_job_id=pin.job_id)
    if buffered is None:
        return None
    row = buffered[0]
    if any(
        bytes(row[key]).hex() != expected
        for key, expected in (
            ("content_sha256", pin.pose_receipt_sha256),
            ("placement_sha256", pin.placement_receipt_sha256),
            ("gate_sha256", pin.gate_receipt_sha256),
        )
    ):
        return None
    scenes = reconstruction_scene_rows(
        connection, workspace, store, scene_id=pin.scene_id, retained_job_id=pin.job_id
    )
    if len(scenes) != 1:
        return None
    scene = scenes[0]
    if not scene.members or any(
        region_by_capture.get(str(member.capture_id)) != pin.region_id for member in scene.members
    ):
        return None
    with arrival_read_check(connection) as at:
        if not scene_allowed(
            connection, workspace, pin.scene_id, buffered, at, retained_job_id=pin.job_id
        ):
            return None
    return scene


def authorized_arrival_descriptor(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    descriptor: ArrivalDescriptor,
    store: ContentAddressedStore,
) -> bool:
    """Reopen a stored v4 pin only while its exact source and geometry remain authorized."""
    pin = descriptor.source
    version = connection.execute(
        "select source_snapshot_id from world_alternate_version where workspace_id=%s "
        "and world_id=%s and version_id=%s",
        (workspace, pin.world_id, pin.version_id),
    ).fetchone()
    if version is None or version["source_snapshot_id"] != pin.source_snapshot_id:
        return False
    try:
        sources = WorldStyleRepository(connection, workspace, world_id=pin.world_id).source_media(
            store, source_snapshot_id=pin.source_snapshot_id
        )
    except (InvalidatedSourceVersion, UnknownWorldResource):
        return False
    region_of = unique_source_regions(
        OwnedSource(
            source.region_id,
            tuple(str(capture) for capture in source.capture_ids),
            source.captured_at,
            source.state.value == "available",
        )
        for source in sources
        if source.region_id is not None and source.state.value == "available"
    )
    verified_viewers = {
        str(capture): source.viewer_sha256
        for source in sources
        if source.region_id == pin.region_id
        and source.state.value == "available"
        and source.viewer_sha256 is not None
        for capture in source.capture_ids
        if region_of.get(str(capture)) == pin.region_id
    }
    repository = WorldStyleRepository(connection, workspace, world_id=pin.world_id)

    def source_still_bound(capture_id: uuid.UUID) -> bool:
        expected = verified_viewers.get(str(capture_id))
        return expected is not None and repository.source_capture_binding(
            pin.source_snapshot_id, capture_id
        ) == (pin.region_id, expected)

    if isinstance(pin, PhotographArrivalPin):
        if region_of.get(str(pin.capture_id)) != pin.region_id:
            return False
        with arrival_read_check(connection):
            return source_still_bound(pin.capture_id)
    if isinstance(pin, PointMapArrivalPin):
        if region_of.get(str(pin.capture_id)) != pin.region_id:
            return False
        try:
            if connection.info.transaction_status == TransactionStatus.IDLE:
                value = read_point_map(connection, workspace, pin.artifact_id, store)
                payload = (
                    None
                    if value is None or value.content_sha256 != pin.content_sha256
                    else value.payload
                )
            else:
                payload = _buffer_exact_bytes(store, pin.content_sha256, pin.byte_size)
            if payload is None or len(payload) != pin.byte_size:
                return False
            pose = fallback_arrival_pose_for_radius(standalone_opm_footprint(payload))
        except (BlobNotFoundError, IntegrityError, TombstonedError, ValueError):
            return False
        pose_matches = (
            tuple(descriptor.position_local_mm) == pose[0]
            and tuple(descriptor.forward_local_millionths) == pose[1]
        )
        if not pose_matches:
            return False
        with arrival_read_check(connection) as at:
            return source_still_bound(pin.capture_id) and point_allowed(
                connection, workspace, pin.artifact_id, at
            )
    scene = authorized_retained_scene(connection, workspace, pin, store)
    if scene is None:
        return False
    try:

        def map_bytes(artifact_id: str) -> bytes | None:
            return _scene_point_bytes(connection, workspace, scene, artifact_id, store)

        def trained_bytes(artifact_id: str) -> bytes | None:
            return _scene_trained_bytes(
                connection, workspace, scene, artifact_id, pin.job_id, store
            )

        pose = scene_arrival_pose(scene, map_bytes, trained_bytes)
    except (BlobNotFoundError, IntegrityError, TombstonedError, ValueError):
        return False
    if pose is None or _descriptor(pin.region_id, pose, pin.model_dump(mode="json")) != descriptor:
        return False
    buffered = scene_inputs(connection, workspace, pin.scene_id, store, retained_job_id=pin.job_id)
    if buffered is None:
        return False
    with arrival_read_check(connection) as at:
        return all(
            source_still_bound(member.capture_id) for member in scene.members
        ) and scene_allowed(
            connection, workspace, pin.scene_id, buffered, at, retained_job_id=pin.job_id
        )


@dataclass(frozen=True, slots=True)
class ArrivalAuthority:
    """Store-checked v4 source and scene manifest buffered before the asset read lock."""

    descriptor: ArrivalDescriptor
    capture_bindings: tuple[tuple[uuid.UUID, str], ...]
    scene_buffered: tuple | None
    trained_artifact: tuple[uuid.UUID, str] | None


def buffer_arrival_authority(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    descriptor: ArrivalDescriptor,
    store: ContentAddressedStore,
) -> ArrivalAuthority | None:
    """Read exact source bytes and the pinned scene manifest before a society takes its lock."""
    if not authorized_arrival_descriptor(connection, workspace, descriptor, store):
        return None
    pin = descriptor.source
    buffered = None
    if isinstance(pin, RetainedScenePin):
        scene = authorized_retained_scene(connection, workspace, pin, store)
        buffered = scene_inputs(
            connection, workspace, pin.scene_id, store, retained_job_id=pin.job_id
        )
        if scene is None or buffered is None:
            return None
        captures = {member.capture_id for member in scene.members}
        trained = scene.trained_geometry
        trained_artifact = (
            (trained.artifact_id, trained.content_sha256)
            if trained is not None and trained.state == "available"
            else None
        )
    else:
        captures = {pin.capture_id}
        trained_artifact = None
    repository = WorldStyleRepository(connection, workspace, world_id=pin.world_id)
    try:
        sources = repository.source_media(store, source_snapshot_id=pin.source_snapshot_id)
    except (InvalidatedSourceVersion, UnknownWorldResource):
        return None
    region_of = unique_source_regions(
        OwnedSource(
            source.region_id,
            tuple(str(capture) for capture in source.capture_ids),
            source.captured_at,
            True,
        )
        for source in sources
        if source.region_id is not None and source.state.value == "available"
    )
    verified_viewers = {
        capture: source.viewer_sha256
        for source in sources
        if source.region_id == pin.region_id and source.state.value == "available"
        for capture in source.capture_ids
        if region_of.get(str(capture)) == pin.region_id
    }
    bindings = []
    for capture in sorted(captures):
        try:
            binding = repository.source_capture_binding(pin.source_snapshot_id, capture)
        except (InvalidatedSourceVersion, UnknownWorldResource):
            return None
        if binding is None or binding != (pin.region_id, verified_viewers.get(capture)):
            return None
        bindings.append((capture, binding[1]))
    return ArrivalAuthority(descriptor, tuple(bindings), buffered, trained_artifact)


def arrival_authority_under_lock(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    authority: ArrivalAuthority,
) -> bool:
    """Recheck rows only; the asset read lock holds the checked bytes until commit."""
    pin = authority.descriptor.source
    version = connection.execute(
        "select source_snapshot_id from world_alternate_version where workspace_id=%s "
        "and world_id=%s and version_id=%s",
        (workspace, pin.world_id, pin.version_id),
    ).fetchone()
    if version is None or version["source_snapshot_id"] != pin.source_snapshot_id:
        return False
    repository = WorldStyleRepository(connection, workspace, world_id=pin.world_id)
    for capture, viewer_sha256 in authority.capture_bindings:
        try:
            binding = repository.source_capture_binding(pin.source_snapshot_id, capture)
        except (InvalidatedSourceVersion, UnknownWorldResource):
            return False
        if binding != (
            pin.region_id,
            viewer_sha256,
        ):
            return False
    at = evaluation_time(connection)
    if isinstance(pin, RetainedScenePin):
        if authority.scene_buffered is None or not scene_allowed(
            connection,
            workspace,
            pin.scene_id,
            authority.scene_buffered,
            at,
            retained_job_id=pin.job_id,
        ):
            return False
        if authority.trained_artifact is not None:
            artifact_id, digest = authority.trained_artifact
            row = connection.execute(
                "select content_sha256,asset_artifact_live(workspace_id,artifact_id,%s) as live "
                "from artifact where workspace_id=%s and artifact_id=%s",
                (at, workspace, artifact_id),
            ).fetchone()
            if row is None or not row["live"] or bytes(row["content_sha256"]).hex() != digest:
                return False
    elif isinstance(pin, PointMapArrivalPin):
        row = connection.execute(
            "select content_sha256 from artifact where workspace_id=%s and artifact_id=%s",
            (workspace, pin.artifact_id),
        ).fetchone()
        if (
            row is None
            or bytes(row["content_sha256"]).hex() != pin.content_sha256
            or not point_allowed(connection, workspace, pin.artifact_id, at)
        ):
            return False
    return True
