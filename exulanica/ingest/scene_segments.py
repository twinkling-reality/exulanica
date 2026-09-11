"""What the photographs found, lifted into the scene they reconstructed.

The segmentation stage finds objects per photograph and a reviewer outlines people per photograph.
Neither says anything about the scene. This module carries both into it: every sample of the
scene's geometry is projected through every recovered camera, each camera says which of its
regions the sample falls in, and a sample joins an entity when enough of the views that could see
it agree. The result is one durable artifact per scene, a list of per-entity segments, each a set
of occupied voxels in the scene's own frame that a renderer can tint and a click can resolve to.

**One projector.** The arithmetic is the masked-geometry check's, exposed from
``exulanica/ingest/masked_geometry.py`` as ``camera_point``, ``image_point`` and ``ppm_point`` and
called here with arrays instead of floats. That check counts Gaussians over person outlines for
privacy; this counts samples over any outline for membership. A second projector would one day
disagree with the first about which side of an outline a point falls on, and the check is the one
whose answer matters more. The margin is zero here: the check grows regions because reporting too
much is its safe direction, and a segment grown past its object would vote for its neighbours.

**What is sampled.** Every placed member's posed point map, subsampled evenly to a declared budget
and carried into the scene frame by the placement's own transform, and, when the caller supplies
one, the centres of a trained Gaussian scene read by the check's own PLY reader. The volcanic scene
has no trained delivery, so it lifts from point maps alone, and says so in its bindings.

**What a view counts.** A sample is seen by a view when it projects in front of the camera, inside
the frame, and not clearly behind the surface that view's own placed point map records at that
pixel. Without the last test a background sample would vote for whatever foreground object hides
it in that view. A sample then belongs to an entity when at least ``min_votes`` views put it
inside one of that entity's regions and those views are at least ``vote_threshold`` of the views
that saw it at all. Both numbers are stage parameters, so tuning them re-keys the artifact.

**What an entity is.** A person is their subject: every reviewed region naming one subject is one
entity, and only a region a human confirmed or drew, naming a subject whose presentation state is
``shown``, is lifted at all. An object is a label split into connected pieces: the samples of one
label are voxelised and every 26-connected component is its own entity, so two rocks that do not
touch are two segments and the naming flow can tell them apart.

**Bound, and refused when a binding moves.** The artifact names the pose, placement and gate
receipt digests, the member list, the placement's point maps, the exact segmentation artifact of
every member, every person region by its digest, and the Gaussian source. Each segment also names
the regions and point maps it rests on. The graph reader in
``exulanica/graph/reconstruction_scenes.py`` refuses the whole artifact when a scene-level binding
or an object mask input has moved, and withholds a single segment when a region it rests on has
changed, a point map it came from is purged, or the person it depicts is no longer shown. It
parses these bytes itself, because ``graph`` and ``ingest`` are siblings that may not import each
other; a test pins the two spellings together.

**Privacy-bearing, unlike the projection.** A person segment is where a person's body is in the
scene. It is written only under the rule above, it carries a subject reference and never a name,
and the reader re-checks the live consent state on every request and applies the geometry
asset-read policy before any of it leaves the API.

**When it runs.** Right after a scene publishes, in the scene worker's process and in the run that
published it, with the placement that worker has just validated
(``SceneReconstructionProcessor._lift_segments``); a lift that fails there fails its own stage and
never the scene. Again whenever every member of a published scene has object masks that its newest
segments do not bind, which is how masks written after the scene was built reach it
(``scenes_due_segments`` and ``SceneReconstructionWorker.refresh_scene_segments``). And on demand,
from the command at the bottom of this module. All three run numpy and nothing else: the scene
worker holds pycolmap, which cannot share a process with torch on macOS, so the lift reads the masks
the derivative worker's segmenter wrote and never loads a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from exulanica.canonical import canonical_json
from exulanica.consent.regions import Silhouette
from exulanica.evidence.region import PPM
from exulanica.ingest.masked_geometry import (
    GaussianView,
    camera_point,
    image_point,
    ppm_point,
    read_gaussian_centres,
)
from exulanica.ingest.stages.segmentation import OBJECT_MASK_KIND, OBJECT_MASK_PROFILE
from exulanica.reconstruction.placement import (
    PlacementRecord,
    PointMapInput,
    recovered_camera_records,
    validate_placement_record,
)

if TYPE_CHECKING:
    import numpy as np

    from exulanica.ingest.ledger import Ledger, StageRecorder
    from exulanica.ingest.repository import IngestRepository
    from exulanica.ingest.stages import StageSpec
    from exulanica.store.base import ContentAddressedStore

__all__ = [
    "SCENE_SEGMENTS_ENVELOPE",
    "SCENE_SEGMENTS_KIND",
    "SCENE_SEGMENTS_PROFILE",
    "SCENE_SEGMENTS_STAGE",
    "LiftRegion",
    "SegmentsDue",
    "ValidatedBuild",
    "build_scene_segments",
    "object_regions_from_artifact",
    "publish_scene_segments",
    "scenes_due_segments",
    "validate_scene_segments",
]

#: Spelled here and again in ``exulanica/graph/reconstruction_scenes.py``, because the layers
#: contract forbids either sibling importing the other. A test pins the spellings together and the
#: stage registry's ``output_kind`` to this one.
SCENE_SEGMENTS_KIND: Final = "scene_segments"
SCENE_SEGMENTS_STAGE: Final = "scene_segments"
SCENE_SEGMENTS_PROFILE: Final = "exulanica.scene-segments/v1"
SCENE_SEGMENTS_ENVELOPE: Final = "exulanica.scene-segments-envelope/v1"


@dataclass(frozen=True, slots=True)
class LiftRegion:
    """One outline in one member's frame, and the entity it would vote for.

    ``reference`` identifies the region in the terms its owner uses: an object mask by its
    segmentation artifact and index, a person region by its region key. ``digest`` is what the
    reader re-derives to decide whether the region is still the one this segment rests on.
    """

    capture_ref: str
    kind: str
    label: str | None
    subject_ref: str | None
    reference: dict[str, Any]
    digest: str
    outline: Silhouette

    @property
    def entity_key(self) -> str:
        return f"person:{self.subject_ref}" if self.kind == "person" else f"object:{self.label}"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_regions_from_artifact(
    capture_ref: str, artifact_ref: str, data: bytes
) -> list[LiftRegion]:
    """Every mask in one segmentation artifact, as a region that can vote.

    The region digest is the SHA-256 of the mask's canonical record, which contains its outline,
    its label and its span digest, so any change to what the mask says changes the digest.
    """
    document = json.loads(data)
    if not isinstance(document, dict) or document.get("profile") != OBJECT_MASK_PROFILE:
        raise ValueError("the object mask list profile is unsupported")
    regions: list[LiftRegion] = []
    for record in document.get("masks", []):
        outline = Silhouette.from_digest_input(record["outline"])
        regions.append(
            LiftRegion(
                capture_ref=capture_ref,
                kind="object",
                label=str(record["label"]),
                subject_ref=None,
                reference={
                    "kind": "object_mask",
                    "artifact_ref": artifact_ref,
                    "mask_index": int(record["index"]),
                    "span_digest": str(record["span_digest"]),
                    # The hosted box this mask was prompted with, when it was, which is the span
                    # the vision stage's own occurrence of the object stands on. It is how a reader
                    # finds something the naming flow can name.
                    "prompt_span_digest": record.get("prompt_span_digest"),
                },
                digest=_digest(canonical_json(record)),
                outline=outline,
            )
        )
    return regions


# -- geometry in --------------------------------------------------------------------------------


def _cameras(pose_receipt: bytes) -> dict[str, GaussianView]:
    """Every accepted recovered camera, in the masked-geometry check's own view type.

    ``recovered_camera_records`` validates the receipt and resolves each camera's calibration,
    including the distortion models that are projected as a pinhole approximation. The rotation
    and translation are then read from the same receipt, because the check's projector takes the
    COLMAP camera-from-world pose rather than the scene-from-camera matrix the graph publishes.
    """
    records = recovered_camera_records(pose_receipt)
    if not records:
        return {}
    receipt = json.loads(pose_receipt)
    frames = {frame["filename"]: frame["capture_ref"] for frame in receipt["manifest"]["frames"]}
    views: dict[str, GaussianView] = {}
    for camera in receipt["quality"]["cameras"]:
        capture_ref = frames.get(camera["image_name"])
        record = records.get(capture_ref) if capture_ref is not None else None
        if record is None:
            continue
        calibration = record["calibration"]
        views[capture_ref] = GaussianView(
            image_name=str(camera["image_name"]),
            quaternion_wxyz=tuple(float(value) for value in camera["quaternion_wxyz"]),  # type: ignore[arg-type]
            translation_xyz=tuple(float(value) for value in camera["translation_xyz"]),  # type: ignore[arg-type]
            image_size=(int(calibration["width"]), int(calibration["height"])),
            focal_xy=(float(calibration["fx"]), float(calibration["fy"])),
            principal_xy=(float(calibration["cx"]), float(calibration["cy"])),
            masked=(),
            confirmed=(),
            projection="exact" if record["projection"] == "pinhole" else "pinhole-approximation",
        )
    return views


def _opm_positions(data: bytes) -> np.ndarray:
    """The position section of an OPM/2 container, as an (N, 3) float64 array.

    Bounds-checked against the header rather than trusted, and every value checked finite. The
    bytes were validated when the point map was produced and are content addressed, so this is a
    second guard and not a second validator: ``validate_opm`` walks every point in Python and is
    exactly the cost the scene projection was built to avoid.
    """
    import numpy as np

    if data[:4] != b"OPM1" or len(data) < 8:
        raise ValueError("not an OPM container")
    length = int.from_bytes(data[4:8], "little")
    header = json.loads(data[8 : 8 + length])
    if header.get("version") != 2:
        raise ValueError("only OPM/2 point maps can be lifted")
    section = next(item for item in header["sections"] if item["name"] == "position")
    offset, size = int(section["byteOffset"]), int(section["byteLength"])
    if offset < 0 or size % 12 or offset + size > len(data):
        raise ValueError("the point map position section lies outside its bytes")
    positions = np.frombuffer(data, dtype="<f4", count=size // 4, offset=offset).reshape(-1, 3)
    if not np.isfinite(positions).all():
        raise ValueError("the point map contains nonfinite positions")
    return positions.astype(np.float64)


def _placed(matrix: Sequence[float], positions: np.ndarray) -> np.ndarray:
    """OPM-frame points into the scene frame, by the placement's own row-major transform.

    Written out per component rather than as a matrix product, so the arithmetic is elementwise
    and does not depend on which BLAS a host links: the stage declares itself deterministic.
    """
    import numpy as np

    x, y, z = positions[:, 0], positions[:, 1], positions[:, 2]
    m = [float(value) for value in matrix]
    return np.stack(
        (
            m[0] * x + m[1] * y + m[2] * z + m[3],
            m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11],
        ),
        axis=1,
    )


def _evenly(count: int, budget: int) -> np.ndarray:
    """At most ``budget`` indices spread evenly over ``range(count)``, the same every time."""
    import numpy as np

    if count <= budget:
        return np.arange(count)
    return np.unique(np.floor(np.arange(budget) * (count / budget)).astype(np.int64))


def _project(
    view: GaussianView, points: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Pixel coordinates and depth for every point in front of the camera.

    Returns ``(front, u, v, depth)`` where ``front`` indexes ``points`` and the other three are
    aligned with it. The masked-geometry projector, called with arrays: numpy is imported where it
    is used throughout this module, so an instance with no extras can still import its constants.
    """
    import numpy as np

    camera = camera_point(view, (points[:, 0], points[:, 1], points[:, 2]))
    front = np.flatnonzero(camera[2] > 0)
    u, v = image_point(view, (camera[0][front], camera[1][front], camera[2][front]))
    return front, u, v, camera[2][front]


def _depth_buffer(
    view: GaussianView, points: np.ndarray, cells: int
) -> tuple[np.ndarray, int, int]:
    """The nearest surface a view's own point map records, on a coarse grid of its frame."""
    import numpy as np

    width, height = view.image_size
    grid_w = max(1, round(cells * width / max(width, height)))
    grid_h = max(1, round(cells * height / max(width, height)))
    buffer = np.full(grid_w * grid_h, np.inf)
    _front, u, v, depth = _project(view, points)
    inside = (u >= 0) & (u < width) & (v >= 0) & (v < height)
    column = np.minimum((u[inside] * grid_w / width).astype(np.int64), grid_w - 1)
    row = np.minimum((v[inside] * grid_h / height).astype(np.int64), grid_h - 1)
    np.minimum.at(buffer, row * grid_w + column, depth[inside])
    return buffer.reshape(grid_h, grid_w), grid_w, grid_h


def _raster(outline: Silhouette, width: int, height: int) -> np.ndarray:
    """An outline as a boolean grid over the unit square, by even-odd scanline parity.

    A cell is inside when its centre is, under the crossing rule ``Silhouette.contains`` uses: an
    edge that spans the row toggles every cell whose centre lies strictly left of its crossing.
    Vectorised over rows and edges at once, then accumulated as a prefix sum along each row.
    """
    import numpy as np

    points = np.asarray(outline.points, dtype=np.float64)
    x1, y1 = points[:, 0], points[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    centres = (2 * np.arange(height, dtype=np.float64) + 1) * PPM / (2 * height)
    rows = centres[:, None]
    spans = (y1[None, :] > rows) != (y2[None, :] > rows)
    rise = (y2 - y1)[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        crossing = x1[None, :] + (rows - y1[None, :]) * (x2 - x1)[None, :] / rise
    # A horizontal edge never spans a row, and its crossing is a division by zero; zero it before
    # the cast rather than let a NaN become an arbitrary integer the mask then happens to drop.
    crossing = np.where(spans, crossing, 0.0)
    # The number of cell centres (2j + 1) / (2 width) strictly left of the crossing.
    limit = np.clip(np.ceil((crossing * 2 * width / PPM - 1) / 2), 0, width).astype(np.int64)
    toggles = np.zeros((height, width + 1), dtype=np.int64)
    row_index, edge_index = np.nonzero(spans)
    np.add.at(toggles, (row_index, 0), 1)
    np.add.at(toggles, (row_index, limit[row_index, edge_index]), -1)
    return (np.cumsum(toggles[:, :width], axis=1) % 2).astype(bool)


# -- the lift -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Samples:
    points: np.ndarray
    source: np.ndarray  # member index for a point-map sample, -1 for a Gaussian centre
    members: tuple[tuple[str, str, str], ...]  # (capture_ref, artifact_ref, content_sha256)


def _samples(
    placement: PlacementRecord,
    point_maps: Mapping[str, bytes],
    gaussian_centres: Sequence[Sequence[float]] | None,
    params: Mapping[str, Any],
) -> tuple[_Samples, dict[str, np.ndarray]]:
    """Every sample the lift votes over, and each member's full placed map for its depth test."""
    import numpy as np

    budget = int(params["point_map_samples_per_member"])
    chunks: list[np.ndarray] = []
    sources: list[np.ndarray] = []
    members: list[tuple[str, str, str]] = []
    own: dict[str, np.ndarray] = {}
    for member in placement.placed:
        data = point_maps.get(member.capture_ref)
        if data is None:
            continue
        placed = _placed(member.scene_from_opm, _opm_positions(data))
        own[member.capture_ref] = placed
        chosen = placed[_evenly(len(placed), budget)]
        chunks.append(chosen)
        sources.append(np.full(len(chosen), len(members), dtype=np.int64))
        members.append(
            (member.capture_ref, member.point_map_artifact_ref, member.point_map_content_sha256)
        )
    if gaussian_centres:
        centres = np.asarray(gaussian_centres, dtype=np.float64).reshape(-1, 3)
        centres = centres[_evenly(len(centres), int(params["gaussian_samples_max"]))]
        chunks.append(centres)
        sources.append(np.full(len(centres), -1, dtype=np.int64))
    points = np.concatenate(chunks) if chunks else np.zeros((0, 3))
    source = np.concatenate(sources) if sources else np.zeros(0, dtype=np.int64)
    return _Samples(points, source, tuple(members)), own


def _lift(
    samples: _Samples,
    cameras: Mapping[str, GaussianView],
    own: Mapping[str, np.ndarray],
    regions: Sequence[LiftRegion],
    params: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Vote every sample into at most one entity, then cut entities into segments."""
    import numpy as np

    count = len(samples.points)
    seen = np.zeros(count, dtype=np.int64)
    keys = sorted({region.entity_key for region in regions}, key=_key_order)
    votes = {key: np.zeros(count, dtype=np.int64) for key in keys}
    inside_of: list[np.ndarray] = [np.zeros(0, dtype=np.int64) for _ in regions]
    by_capture: dict[str, list[int]] = {}
    for position, region in enumerate(regions):
        by_capture.setdefault(region.capture_ref, []).append(position)

    cells = int(params["region_raster_cells"])
    grid = int(params["occlusion_grid_cells"])
    tolerance = 1 + int(params["occlusion_relative_tolerance_millionths"]) / 1_000_000
    for capture_ref in sorted(cameras):
        view = cameras[capture_ref]
        width, height = view.image_size
        front, u, v, depth = _project(view, samples.points)
        frame = (u >= 0) & (u < width) & (v >= 0) & (v < height)
        index, u, v, depth = front[frame], u[frame], v[frame], depth[frame]
        if capture_ref in own:
            buffer, grid_w, grid_h = _depth_buffer(view, own[capture_ref], grid)
            column = np.minimum((u * grid_w / width).astype(np.int64), grid_w - 1)
            row = np.minimum((v * grid_h / height).astype(np.int64), grid_h - 1)
            nearest = buffer[row, column]
            visible = ~np.isfinite(nearest) | (depth <= nearest * tolerance)
            index, u, v = index[visible], u[visible], v[visible]
        seen[index] += 1
        positions = by_capture.get(capture_ref, [])
        if not positions:
            continue
        x_ppm, y_ppm = ppm_point(view, u, v)
        raster_w = max(1, round(cells * width / max(width, height)))
        raster_h = max(1, round(cells * height / max(width, height)))
        column = np.minimum((x_ppm * raster_w // PPM).astype(np.int64), raster_w - 1)
        row = np.minimum((y_ppm * raster_h // PPM).astype(np.int64), raster_h - 1)
        # One vote per view per entity, however many of the view's regions of that entity
        # contain the sample. Two overlapping masks of one rock are one observation of it.
        hit = {key: np.zeros(len(index), dtype=bool) for key in keys}
        for position in positions:
            inside = _raster(regions[position].outline, raster_w, raster_h)[row, column]
            inside_of[position] = index[inside]
            hit[regions[position].entity_key] |= inside
        for key, mask in hit.items():
            votes[key][index[mask]] += 1

    minimum = int(params["min_votes"])
    threshold = int(params["vote_threshold_millionths"])
    scored = np.full((max(1, len(keys)), count), -1, dtype=np.int64)
    for row_number, key in enumerate(keys):
        accepted = (votes[key] >= minimum) & (votes[key] * 1_000_000 >= threshold * seen)
        scored[row_number] = np.where(accepted, votes[key], -1)
    # Highest vote count wins a contested sample, and `_key_order` breaks a tie toward the person,
    # so an object never takes a sample a reviewed person's regions also claim.
    winner = np.argmax(scored, axis=0)
    assigned = scored[winner, np.arange(count)] >= 0 if keys else np.zeros(count, dtype=bool)

    voxel = _voxel_size(samples.points, int(params["voxel_grid_cells"]))
    link = voxel * int(params["instance_link_voxels"])
    minimum_samples = int(params["min_segment_samples"])
    segments: list[dict[str, Any]] = []
    for row_number, key in enumerate(keys):
        members = np.flatnonzero(assigned & (winner == row_number))
        if len(members) < minimum_samples:
            continue
        pieces = (
            [members]
            if key.startswith("person:")
            else _components(
                samples.points,
                members,
                link,
                [inside_of[at] for at, region in enumerate(regions) if region.entity_key == key],
            )
        )
        for piece in pieces:
            if len(piece) < minimum_samples:
                continue
            segments.append(
                _segment(key, piece, samples, votes[key], seen, regions, inside_of, voxel)
            )
    segments.sort(key=lambda item: (_key_order(item["entity_key"]), item["segment_id"]))
    summary = {
        "samples": {
            "point_map": int(np.count_nonzero(samples.source >= 0)),
            "gaussian": int(np.count_nonzero(samples.source < 0)),
        },
        "seen_by_at_least_one_view": int(np.count_nonzero(seen)),
        "assigned": int(np.count_nonzero(assigned)),
        "voxel_size_microunits": voxel,
    }
    return segments, summary


def _key_order(key: str) -> tuple[int, str]:
    return (0 if key.startswith("person:") else 1, key)


def _voxel_size(points: np.ndarray, cells: int) -> int:
    """The voxel edge in millionths of a scene unit: the robust extent over the declared cells.

    The second and ninety-eighth percentiles rather than the extremes, so one stray sample a long
    way out does not make every voxel in the scene coarse.
    """
    import numpy as np

    if len(points) == 0:
        return 1
    low = np.percentile(points, 2, axis=0)
    high = np.percentile(points, 98, axis=0)
    extent = float(np.max(high - low))
    return max(1, round(extent / cells * 1_000_000))


def _voxels(points: np.ndarray, voxel: int) -> np.ndarray:
    import numpy as np

    return np.floor(points * 1_000_000 / voxel).astype(np.int64)


def _components(
    points: np.ndarray, members: np.ndarray, voxel: int, masks: Sequence[np.ndarray]
) -> list[np.ndarray]:
    """One label's samples split into instances, largest first.

    Two samples are one instance when they are joined by a chain of either link: they fall in the
    same or a neighbouring cell of a grid ``voxel`` coarse (26-neighbourhood), or one of the
    label's masks contained both in some view. Space alone fragments any object sampled more
    sparsely than the grid, which two synthetic cubes of 400 samples each did into 29 pieces; a
    mask is the photograph saying "this is one thing", and it glues those pieces back. The price
    is stated rather than hidden: a mask that covered two objects in one view joins them.
    """
    import numpy as np

    position = {int(sample): index for index, sample in enumerate(members.tolist())}
    parent = list(range(len(members)))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(first: int, second: int) -> None:
        a, b = find(first), find(second)
        if a != b:
            parent[max(a, b)] = min(a, b)

    cells = _voxels(points[members], voxel)
    by_cell: dict[tuple[int, int, int], int] = {}
    for index, cell in enumerate(map(tuple, cells.tolist())):
        if cell in by_cell:
            union(by_cell[cell], index)
        else:
            by_cell[cell] = index
    forward = [
        (dx, dy, dz)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dz in (-1, 0, 1)
        if (dx, dy, dz) > (0, 0, 0)
    ]
    for (x, y, z), index in by_cell.items():
        for dx, dy, dz in forward:
            neighbour = by_cell.get((x + dx, y + dy, z + dz))
            if neighbour is not None:
                union(index, neighbour)
    for inside in masks:
        joined = [position[int(sample)] for sample in inside.tolist() if int(sample) in position]
        for index in joined[1:]:
            union(joined[0], index)

    groups: dict[int, list[int]] = {}
    for index in range(len(members)):
        groups.setdefault(find(index), []).append(index)
    pieces = [members[np.asarray(group, dtype=np.int64)] for group in groups.values()]
    pieces.sort(key=lambda piece: (-len(piece), int(piece[0])))
    return pieces


def _segment(
    key: str,
    piece: np.ndarray,
    samples: _Samples,
    votes: np.ndarray,
    seen: np.ndarray,
    regions: Sequence[LiftRegion],
    inside_of: Sequence[np.ndarray],
    voxel: int,
) -> dict[str, Any]:
    import numpy as np

    points = samples.points[piece]
    cells = np.unique(_voxels(points, voxel), axis=0)
    voxels = [[int(a), int(b), int(c)] for a, b, c in cells.tolist()]
    kind, _, name = key.partition(":")
    supporting = []
    for position, region in enumerate(regions):
        if region.entity_key != key or not len(inside_of[position]):
            continue
        overlap = int(np.count_nonzero(np.isin(inside_of[position], piece)))
        if overlap:
            supporting.append(
                {
                    "capture_ref": region.capture_ref,
                    **region.reference,
                    "region_digest": region.digest,
                    "samples": overlap,
                }
            )
    supporting.sort(key=lambda item: (item["capture_ref"], json.dumps(item, sort_keys=True)))
    counts = np.sort(votes[piece])
    fractions = np.sort(votes[piece] * 1_000_000 // np.maximum(seen[piece], 1))
    sources = sorted(
        {samples.members[int(index)][2] for index in samples.source[piece] if index >= 0}
    )
    identity = {
        "kind": kind,
        "label": name if kind == "object" else None,
        "subject_ref": name if kind == "person" else None,
        "voxels": voxels,
    }
    return {
        "segment_id": _digest(canonical_json(identity))[:32],
        "entity_key": key,
        **identity,
        "bounds_microunits": {
            "min": [int(value) for value in np.round(points.min(axis=0) * 1_000_000)],
            "max": [int(value) for value in np.round(points.max(axis=0) * 1_000_000)],
        },
        "centroid_microunits": [int(value) for value in np.round(points.mean(axis=0) * 1_000_000)],
        "samples": {
            "point_map": int(np.count_nonzero(samples.source[piece] >= 0)),
            "gaussian": int(np.count_nonzero(samples.source[piece] < 0)),
        },
        "votes": {
            "views": len({item["capture_ref"] for item in supporting}),
            "min": int(counts[0]),
            "median": int(counts[len(counts) // 2]),
            "max": int(counts[-1]),
            "fraction_min_millionths": int(fractions[0]),
            "fraction_median_millionths": int(fractions[len(fractions) // 2]),
        },
        "regions": supporting,
        "point_map_sources": sources,
    }


# -- the artifact -------------------------------------------------------------------------------


def build_scene_segments(
    *,
    scene_ref: str,
    pose_receipt: bytes,
    pose_receipt_sha256: str,
    placement: PlacementRecord,
    placement_receipt_sha256: str,
    gate_receipt_sha256: str,
    member_capture_refs: Sequence[str],
    point_maps: Mapping[str, bytes],
    object_mask_inputs: Sequence[tuple[str, str, str]],
    object_mask_missing: Sequence[str],
    regions: Sequence[LiftRegion],
    params: Mapping[str, Any],
    gaussian_ply: bytes | None = None,
    gaussian_source: Mapping[str, Any] | None = None,
) -> bytes:
    """Lift one published scene's regions into segments, and bind them to everything they used.

    ``placement`` must already have been validated against ``pose_receipt`` and these exact point
    maps, as the projection requires; the transforms are used as they stand. Every person region
    offered must already have passed the reviewed-and-shown rule; ``publish_scene_segments`` is
    the one caller that selects them, and a test holds it to that.
    """
    if placement.scene_ref != scene_ref or placement.pose_receipt_sha256 != pose_receipt_sha256:
        raise ValueError("the placement belongs to another scene or another pose receipt")
    if tuple(placement.member_capture_refs) != tuple(member_capture_refs):
        raise ValueError("the placement member list differs from the scene member list")
    if (gaussian_ply is None) != (gaussian_source is None):
        raise ValueError("a Gaussian source must be declared exactly when its bytes are supplied")
    if (
        gaussian_ply is not None
        and gaussian_source is not None
        and gaussian_source.get("ply_sha256") != _digest(gaussian_ply)
    ):
        raise ValueError("the declared Gaussian source is not these bytes")
    centres = None if gaussian_ply is None else read_gaussian_centres(gaussian_ply)[0]
    samples, own = _samples(placement, point_maps, centres, params)
    cameras = _cameras(pose_receipt)
    segments, summary = _lift(samples, cameras, own, regions, params)
    payload = {
        "profile": SCENE_SEGMENTS_PROFILE,
        "scene_ref": scene_ref,
        "bindings": {
            "pose_receipt_sha256": pose_receipt_sha256,
            "placement_receipt_sha256": placement_receipt_sha256,
            "gate_receipt_sha256": gate_receipt_sha256,
            "member_capture_refs": list(member_capture_refs),
            "point_map_inputs": [
                {"capture_ref": capture, "artifact_ref": artifact, "content_sha256": digest}
                for capture, artifact, digest in (
                    (item.capture_ref, item.artifact_ref, item.content_sha256)
                    for item in placement.point_map_inputs
                )
            ],
            "object_mask_inputs": [
                {"capture_ref": capture, "artifact_ref": artifact, "content_sha256": digest}
                for capture, artifact, digest in sorted(object_mask_inputs)
            ],
            "object_mask_missing": sorted(object_mask_missing),
            "person_regions": sorted(
                (
                    {
                        "capture_ref": region.capture_ref,
                        "region_key": region.reference["region_key"],
                        "region_digest": region.digest,
                        "subject_ref": region.subject_ref,
                    }
                    for region in regions
                    if region.kind == "person"
                ),
                key=lambda item: (item["capture_ref"], item["region_key"]),
            ),
            "gaussian_source": None if gaussian_source is None else dict(gaussian_source),
        },
        "policy": {
            key: params[key]
            for key in (
                "projector",
                "region_margin_ppm",
                "point_map_samples_per_member",
                "gaussian_samples_max",
                "visibility",
                "occlusion_grid_cells",
                "occlusion_relative_tolerance_millionths",
                "region_raster_cells",
                "min_votes",
                "vote_threshold_millionths",
                "voxel_grid_cells",
                "instance_link_voxels",
                "min_segment_samples",
                "object_instances",
                "person_segments",
            )
        },
        "grid": {"frame": "scene", "voxel_size_microunits": summary["voxel_size_microunits"]},
        "cameras": len(cameras),
        "regions_offered": {
            "object": sum(region.kind == "object" for region in regions),
            "person": sum(region.kind == "person" for region in regions),
        },
        "samples": summary["samples"],
        "samples_seen": summary["seen_by_at_least_one_view"],
        "samples_assigned": summary["assigned"],
        "segments": [
            {key: value for key, value in segment.items() if key != "entity_key"}
            for segment in segments
        ],
    }
    envelope = {
        "profile": SCENE_SEGMENTS_ENVELOPE,
        "payload_sha256": _digest(canonical_json(payload)),
        "segments": payload,
    }
    return canonical_json(envelope) + b"\n"


def validate_scene_segments(
    data: bytes,
    *,
    expected_scene_ref: str,
    pose_receipt_sha256: str,
    placement_receipt_sha256: str,
    gate_receipt_sha256: str,
    member_capture_refs: Sequence[str],
) -> dict[str, Any]:
    """Refuse segments that are malformed or bound to another scene state. Returns the payload.

    The producer checks its own bytes with this before publishing them. The graph reader repeats
    these checks in its own module, and adds the live ones this cannot make.
    """
    envelope = json.loads(data)
    if not isinstance(envelope, dict) or envelope.get("profile") != SCENE_SEGMENTS_ENVELOPE:
        raise ValueError("the scene segments envelope version is unsupported")
    payload = envelope.get("segments")
    if not isinstance(payload, dict) or payload.get("profile") != SCENE_SEGMENTS_PROFILE:
        raise ValueError("the scene segments format version is unsupported")
    if envelope.get("payload_sha256") != _digest(canonical_json(payload)):
        raise ValueError("the scene segments payload disagrees with its digest")
    if payload.get("scene_ref") != expected_scene_ref:
        raise ValueError("the scene segments name another scene")
    bindings = payload["bindings"]
    for field, expected in (
        ("pose_receipt_sha256", pose_receipt_sha256),
        ("placement_receipt_sha256", placement_receipt_sha256),
        ("gate_receipt_sha256", gate_receipt_sha256),
    ):
        if bindings.get(field) != expected:
            raise ValueError(f"the scene segments are bound to another {field}")
    if bindings.get("member_capture_refs") != list(member_capture_refs):
        raise ValueError("the scene segments are bound to another member list")
    for segment in payload["segments"]:
        identity = {key: segment[key] for key in ("kind", "label", "subject_ref", "voxels")}
        if segment["segment_id"] != _digest(canonical_json(identity))[:32]:
            raise ValueError("a segment id does not recompute from its content")
        if segment["kind"] == "person" and segment["label"] is not None:
            raise ValueError("a person segment carries a label")
    return payload


# -- publication --------------------------------------------------------------------------------

#: The scene's CURRENT job and its three receipts, modelled on the projection backfill's query and
#: narrowed the same way: a superseded job is not selected at all.
_SCENE = """
select s.scene_id, j.job_id,
       pose.artifact_id as pose_id, pose.content_sha256 as pose_sha256,
       placement.artifact_id as placement_id, placement.content_sha256 as placement_sha256,
       gate.artifact_id as gate_id, gate.content_sha256 as gate_sha256
  from reconstruction_scene s
  join reconstruction_scene_job j
    on j.workspace_id = s.workspace_id and j.job_id = s.current_job_id and j.status = 'succeeded'
  join artifact pose on pose.workspace_id = s.workspace_id
   and pose.artifact_id = j.pose_receipt_artifact_id and pose.kind = 'pose_receipt'
   and pose.purged_at is null
  join artifact placement on placement.workspace_id = s.workspace_id
   and placement.artifact_id = j.placement_artifact_id
   and placement.kind = 'point_map_placement' and placement.purged_at is null
  join artifact gate on gate.workspace_id = s.workspace_id
   and gate.artifact_id = j.gate_artifact_id and gate.kind = 'scene_gate_receipt'
   and gate.purged_at is null
 where s.workspace_id = %s and s.scene_id = %s
   and not tombstone_blocks_scene(s.workspace_id, s.scene_id)
"""

#: The newest live segmentation artifact of each member's photograph. The reader asks the same
#: question, so an artifact written after these segments is how it knows they are stale.
_OBJECT_MASKS = """
select distinct on (c.capture_id)
       c.capture_id, a.artifact_id, a.content_sha256
  from capture c
  join artifact a on a.workspace_id = c.workspace_id and a.source_blob_sha256 = c.blob_sha256
 where c.workspace_id = %s and c.capture_id = any(%s) and a.kind = %s
   and a.purged_at is null and not a.needs_repair and a.content_sha256 is not null
   and a.byte_size is not null and not tombstone_blocks_capture(c.workspace_id, c.capture_id)
 order by c.capture_id, a.created_at desc, a.artifact_id desc
"""

#: Reviewed person regions of the members, with the state that holds now. A region is lifted only
#: when a human confirmed or drew it, it names a subject, and that subject is ``shown``: likeness
#: granted, not withdrawn, not temporarily hidden. The composition is migration 0037's own.
_PEOPLE = """
select r.capture_id, encode(r.region_key, 'hex') as region_key, r.silhouette, r.subject_id,
       encode(r.region_digest, 'hex') as region_digest
  from person_region_current r
 where r.workspace_id = %s and r.capture_id = any(%s)
   and r.action in ('confirmed', 'added') and r.confirmed_by is not null
   and r.subject_id is not null
   and not person_region_is_masked(r.workspace_id, r.subject_id, r.region_key)
   and not person_subject_is_withdrawn(r.workspace_id, r.subject_id)
   and not person_consent_is_granted(r.workspace_id, r.subject_id, r.region_key, 'temporary_hide')
 order by r.capture_id, r.region_key
"""

_POINT_MAP = """
select a.artifact_id from artifact a
  join capture c on c.workspace_id = a.workspace_id and c.capture_id = %s
   and c.blob_sha256 = a.source_blob_sha256
 where a.workspace_id = %s and a.artifact_id = %s and a.kind = 'point_map'
   and a.content_sha256 = %s and a.byte_size is not null and a.purged_at is null
   and not tombstone_blocks_capture(a.workspace_id, c.capture_id)
"""


#: Every published scene in the workspace with its current receipts, how many members its build
#: has, the newest live segmentation artifact of each member that has one, and the newest live
#: segments artifact of the scene. The build is narrowed exactly as ``_SCENE`` narrows it, and the
#: masks are ``_OBJECT_MASKS``'s own question asked of every scene at once.
_SCENES_WITH_MASKS = """
with build as (
  select s.scene_id, j.job_id,
         pose.content_sha256 as pose_sha256,
         placement.content_sha256 as placement_sha256,
         gate.content_sha256 as gate_sha256
    from reconstruction_scene s
    join reconstruction_scene_job j
      on j.workspace_id = s.workspace_id and j.job_id = s.current_job_id
     and j.status = 'succeeded'
    join artifact pose on pose.workspace_id = s.workspace_id
     and pose.artifact_id = j.pose_receipt_artifact_id and pose.kind = 'pose_receipt'
     and pose.purged_at is null
    join artifact placement on placement.workspace_id = s.workspace_id
     and placement.artifact_id = j.placement_artifact_id
     and placement.kind = 'point_map_placement' and placement.purged_at is null
    join artifact gate on gate.workspace_id = s.workspace_id
     and gate.artifact_id = j.gate_artifact_id and gate.kind = 'scene_gate_receipt'
     and gate.purged_at is null
   where s.workspace_id = %(workspace)s
     and not tombstone_blocks_scene(s.workspace_id, s.scene_id)
),
member as (
  select b.scene_id, m.capture_id
    from build b
    join reconstruction_scene_build_member m
      on m.workspace_id = %(workspace)s and m.job_id = b.job_id
),
mask as (
  select distinct on (member.scene_id, member.capture_id)
         member.scene_id, member.capture_id, a.artifact_id, a.content_sha256
    from member
    join capture c on c.workspace_id = %(workspace)s and c.capture_id = member.capture_id
    join artifact a on a.workspace_id = c.workspace_id and a.source_blob_sha256 = c.blob_sha256
   where a.kind = %(mask_kind)s
     and a.purged_at is null and not a.needs_repair and a.content_sha256 is not null
     and a.byte_size is not null and not tombstone_blocks_capture(c.workspace_id, c.capture_id)
   order by member.scene_id, member.capture_id, a.created_at desc, a.artifact_id desc
)
select b.scene_id, b.job_id, b.pose_sha256, b.placement_sha256, b.gate_sha256,
       (select count(*) from member where member.scene_id = b.scene_id) as member_count,
       coalesce(
         (select jsonb_agg(jsonb_build_array(
                   mask.capture_id::text, mask.artifact_id::text,
                   encode(mask.content_sha256, 'hex')))
            from mask where mask.scene_id = b.scene_id),
         '[]'::jsonb) as masks,
       (select a.content_sha256 from artifact a
         where a.workspace_id = %(workspace)s and a.scene_id = b.scene_id
           and a.kind = %(segments_kind)s and a.purged_at is null and not a.needs_repair
           and a.content_sha256 is not null and a.byte_size is not null
         order by a.created_at desc, a.artifact_id desc
         limit 1) as segments_sha256
  from build b
 order by b.scene_id
"""


class _LiftRefused(RuntimeError):
    """This scene cannot be lifted as it stands. Fails its own stage and returns as a skip.

    Raised inside an open ``scene_segments`` stage, so the ledger writes ``stage_failed`` naming
    the cause, and caught by ``publish_scene_segments``: a receipt, a point map or a mask that has
    gone is a state of the scene rather than a fault in whoever asked for the lift.
    """


@dataclass(frozen=True, slots=True)
class ValidatedBuild:
    """A build its caller has just validated, so that the lift need not validate it again.

    The scene worker builds the placement from the pose receipt and every point map and checks the
    stored bytes against it before it publishes, and doing that a second time is most of a lift:
    48.6 s on the volcanic scene, most of it re-validating the placement against 210 point maps
    and a 107,742,795 byte pose receipt (``docs/scene-segments.md`` section 7).
    ``publish_scene_segments`` still reads the scene's current build from the database, uses these
    only when they are that build's own receipts byte for byte, and otherwise reads and validates
    the stored ones as the command does. ``placement`` is the record ``build_placement_record``
    makes from that pose receipt and those point maps, which is exactly what
    ``validate_placement_record`` returns for them, so both paths lift from the same record.
    """

    job_id: uuid.UUID
    pose_receipt: bytes
    placement_receipt: bytes
    placement: PlacementRecord
    point_maps: Mapping[str, bytes]


def publish_scene_segments(
    repository: IngestRepository,
    store: ContentAddressedStore,
    scene_id: uuid.UUID,
    *,
    gaussian_ply: bytes | None = None,
    gaussian_source: Mapping[str, Any] | None = None,
    ledger: Ledger | None = None,
    validated: ValidatedBuild | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Lift one published scene and write its segments artifact, idempotently.

    Returns what happened. A scene with no current build or nothing to lift, a receipt, point map
    or mask that has gone, and a deletion that reaches the scene are each returned as a skip with
    its reason rather than raised; anything else raises, after its stage has recorded it as
    ``stage_failed``. The artifact id is derived from every input digest, so a second run over
    unchanged inputs writes nothing and says so.

    ``ledger`` is a run to record into, which is how the scene worker files the lift beside the
    projection in the run that published the scene; the caller closes it. Without one the lift
    opens a run of its own under ``trigger`` and closes it. A skip decided before any work begins
    is a ``stage_skipped`` event in the caller's run, and no run at all otherwise.
    """
    from exulanica.errors import TombstonedError
    from exulanica.ingest.ledger import Ledger
    from exulanica.ingest.stages import stage

    started = time.monotonic()
    spec = stage(SCENE_SEGMENTS_STAGE)
    workspace = repository.workspace_id
    connection = repository.connection
    row = connection.execute(_SCENE, (workspace, scene_id)).fetchone()
    if row is None:
        return _skipped(
            ledger,
            spec,
            {"scene_id": str(scene_id)},
            "the scene has no current succeeded build with live receipts",
        )
    outcome: dict[str, Any] = {"scene_id": str(scene_id), "job_id": str(row["job_id"])}
    members = [
        str(item["capture_id"])
        for item in connection.execute(
            "select capture_id from reconstruction_scene_build_member "
            "where workspace_id = %s and job_id = %s order by ordinal, capture_id",
            (workspace, row["job_id"]),
        ).fetchall()
    ]
    capture_ids = [uuid.UUID(member) for member in members]
    masks = connection.execute(_OBJECT_MASKS, (workspace, capture_ids, OBJECT_MASK_KIND)).fetchall()
    people = connection.execute(_PEOPLE, (workspace, capture_ids)).fetchall()
    if not masks and not people:
        # Not a lift of nothing. An artifact with no segments in it would tell a reader that these
        # photographs were looked at and nothing was found, when nobody looked. With none the
        # reader says `absent`, which is true, and `scenes_due_segments` finds the scene once its
        # members have masks.
        return _skipped(
            ledger,
            spec,
            outcome,
            "no member has object masks or a reviewed, shown person region to lift",
        )

    run = ledger if ledger is not None else Ledger.start_run(repository, trigger=trigger)
    try:
        with run.stage(
            spec,
            input_artifact_ids=[
                row["pose_id"],
                row["placement_id"],
                row["gate_id"],
                *(mask["artifact_id"] for mask in masks),
            ],
        ) as recorder:
            outcome, inserted = _lift_and_write(
                repository,
                store,
                scene_id,
                row,
                members,
                masks,
                people,
                spec=spec,
                recorder=recorder,
                outcome=outcome,
                validated=validated,
                gaussian_ply=gaussian_ply,
                gaussian_source=gaussian_source,
                started=started,
            )
    except _LiftRefused as refusal:
        _finish(run, ledger, "failed")
        return {**outcome, "action": "skipped", "reason": str(refusal)}
    except TombstonedError as error:
        _finish(run, ledger, "failed")
        return {**outcome, "action": "skipped", "reason": f"deletion reaches this scene: {error}"}
    except BaseException:
        _finish(run, ledger, "failed")
        raise
    _finish(run, ledger, "succeeded")
    return {**outcome, "action": "written" if inserted else "already-present"}


def _lift_and_write(
    repository: IngestRepository,
    store: ContentAddressedStore,
    scene_id: uuid.UUID,
    row: Mapping[str, Any],
    members: list[str],
    masks: Sequence[Mapping[str, Any]],
    people: Sequence[Mapping[str, Any]],
    *,
    spec: StageSpec,
    recorder: StageRecorder,
    outcome: dict[str, Any],
    validated: ValidatedBuild | None,
    gaussian_ply: bytes | None,
    gaussian_source: Mapping[str, Any] | None,
    started: float,
) -> tuple[dict[str, Any], bool]:
    """The lift itself, inside its open stage: read, validate, lift, check and write."""
    from exulanica.evidence.blob import BlobId
    from exulanica.ingest.committed_store import committed_writes
    from exulanica.ingest.scene_reconstruction import _scene_key
    from exulanica.ingest.stages import artifact_id_for, input_digest_of

    workspace = repository.workspace_id
    connection = repository.connection
    pose_digest = bytes(row["pose_sha256"]).hex()
    placement_digest = bytes(row["placement_sha256"]).hex()
    gate_digest = bytes(row["gate_sha256"]).hex()
    build = validated if validated is not None and _is_build(validated, row) else None
    if build is not None:
        pose_bytes, placement_bytes = build.pose_receipt, build.placement_receipt
    else:
        pose_bytes = _stored(store, pose_digest, "a scene receipt")
        placement_bytes = _stored(store, placement_digest, "a scene receipt")

    point_maps: dict[str, PointMapInput] = {}
    for item in json.loads(placement_bytes)["placement"]["point_map_inputs"]:
        capture_ref, artifact_ref = str(item["capture_ref"]), str(item["artifact_ref"])
        digest = str(item["content_sha256"])
        # Asked even of a build validated a moment ago: a purge that landed in between is exactly
        # what this is for, and it costs one indexed read per member.
        live = connection.execute(
            _POINT_MAP,
            (uuid.UUID(capture_ref), workspace, uuid.UUID(artifact_ref), bytes.fromhex(digest)),
        ).fetchone()
        if live is None:
            raise _LiftRefused(f"point map {artifact_ref} is gone")
        content = build.point_maps.get(capture_ref) if build is not None else None
        if content is None:
            content = _stored(store, digest, "a point map")
        point_maps[capture_ref] = PointMapInput(capture_ref, artifact_ref, digest, content)
    placement = (
        build.placement
        if build is not None
        else validate_placement_record(
            placement_bytes,
            expected_scene_ref=str(scene_id),
            pose_receipt=pose_bytes,
            member_capture_refs=members,
            point_maps=point_maps,
        )
    )

    regions: list[LiftRegion] = []
    mask_inputs: list[tuple[str, str, str]] = []
    for mask in masks:
        digest = bytes(mask["content_sha256"]).hex()
        capture_ref = str(mask["capture_id"])
        data = _stored(store, digest, "an object mask artifact")
        regions.extend(object_regions_from_artifact(capture_ref, str(mask["artifact_id"]), data))
        mask_inputs.append((capture_ref, str(mask["artifact_id"]), digest))
    missing = sorted(set(members) - {capture for capture, _, _ in mask_inputs})
    for person in people:
        regions.append(
            LiftRegion(
                capture_ref=str(person["capture_id"]),
                kind="person",
                label=None,
                subject_ref=str(person["subject_id"]),
                reference={"kind": "person_region", "region_key": person["region_key"]},
                digest=person["region_digest"],
                outline=Silhouette.from_digest_input(person["silhouette"]),
            )
        )

    payload = build_scene_segments(
        scene_ref=str(scene_id),
        pose_receipt=pose_bytes,
        pose_receipt_sha256=pose_digest,
        placement=placement,
        placement_receipt_sha256=placement_digest,
        gate_receipt_sha256=gate_digest,
        member_capture_refs=members,
        point_maps={capture: item.content for capture, item in point_maps.items()},
        object_mask_inputs=mask_inputs,
        object_mask_missing=missing,
        regions=regions,
        params=spec.params,
        gaussian_ply=gaussian_ply,
        gaussian_source=gaussian_source,
    )
    checked = validate_scene_segments(
        payload,
        expected_scene_ref=str(scene_id),
        pose_receipt_sha256=pose_digest,
        placement_receipt_sha256=placement_digest,
        gate_receipt_sha256=gate_digest,
        member_capture_refs=members,
    )
    # Keyed on the whole binding set rather than on the bytes, so the key names what the output
    # SHOULD be before it is computed and a rerun over the same inputs is recognised as one.
    input_digest = input_digest_of(
        [
            bytes.fromhex(_digest(canonical_json(json.loads(payload)["segments"]["bindings"]))),
        ]
    )
    key = _scene_key(scene_id, spec.key, input_digest)
    artifact_id = artifact_id_for(key)
    content_id = BlobId.of_bytes(payload)
    outcome = {
        **outcome,
        "artifact_id": str(artifact_id),
        "segments_sha256": content_id.hex,
        "byte_size": len(payload),
        "segments": len(checked["segments"]),
        "object_mask_inputs": len(mask_inputs),
        "object_mask_missing": len(missing),
        "person_regions": sum(region.kind == "person" for region in regions),
        "regions_offered": len(regions),
        "placement_revalidated": build is None,
        "lift_seconds": round(time.monotonic() - started, 3),
    }
    with (
        repository.locked_stored_objects([content_id]),
        committed_writes(repository, store) as pending,
    ):
        inserted = repository.insert_scene_artifact(
            artifact_id=artifact_id,
            kind=spec.output_kind,
            scene_id=scene_id,
            stage_key=spec.key,
            stage_version=spec.version,
            params_digest=spec.params_digest,
            input_digest=input_digest,
            idempotency_key=key,
            content_sha256=content_id.digest,
            storage_key=store.key_for(content_id),
            byte_size=len(payload),
            produced_by_event=recorder.stage_started_event,
        )
        # Appended whether or not the row was new, for the reason the projection backfill gives: a
        # run killed between the row commit and the byte flush leaves a live row with nothing
        # behind it, and the rerun is what heals it.
        pending.append(payload)
        if inserted:
            recorder.record_output(artifact_id)
    return outcome, inserted


def _is_build(build: ValidatedBuild, row: Mapping[str, Any]) -> bool:
    """Whether a caller's validated build is the scene's current one, receipt for receipt."""
    return (
        build.job_id == row["job_id"]
        and hashlib.sha256(build.pose_receipt).digest() == bytes(row["pose_sha256"])
        and hashlib.sha256(build.placement_receipt).digest() == bytes(row["placement_sha256"])
    )


def _stored(store: ContentAddressedStore, digest: str, what: str) -> bytes:
    from exulanica.errors import BlobNotFoundError, IntegrityError
    from exulanica.evidence.blob import BlobId

    try:
        return store.get(BlobId.from_hex(digest))
    except (BlobNotFoundError, IntegrityError) as error:
        raise _LiftRefused(f"{what} is unreadable: {error}") from error


def _skipped(
    ledger: Ledger | None, spec: StageSpec, outcome: dict[str, Any], reason: str
) -> dict[str, Any]:
    """A skip decided before any work began: an event in a caller's run, and nothing otherwise."""
    if ledger is not None:
        ledger.skipped(spec, reason=reason)
    return {**outcome, "action": "skipped", "reason": reason}


def _finish(run: Ledger, caller: Ledger | None, status: str) -> None:
    """Close a run this lift opened. A caller's run is the caller's to close."""
    if caller is None:
        run.finish(status)


# -- lifting again --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SegmentsDue:
    """A published scene to lift again, why, and the mask set a lift of it now would bind."""

    scene_id: uuid.UUID
    job_id: uuid.UUID
    object_masks: tuple[tuple[str, str, str], ...]
    reason: str

    @property
    def state(self) -> tuple[uuid.UUID, tuple[tuple[str, str, str], ...]]:
        """What a lift would bind beyond the receipts, which the job id already names."""
        return (self.job_id, self.object_masks)


def scenes_due_segments(
    repository: IngestRepository, store: ContentAddressedStore
) -> list[SegmentsDue]:
    """Published scenes whose members all have object masks that their newest segments lack.

    The case this exists for is a scene built before its photographs were segmented, because the
    derivative worker reached them late or had no segmenter until an operator turned one on. The
    lift at publication bound the members that had masks then and named the rest missing, and the
    reader calls those segments stale as soon as one more member has a mask.

    A scene is due only once EVERY member of its current build has a live segmentation artifact,
    and then only when its newest segments are absent, unreadable, bound to another build or bound
    to other masks. Waiting for the whole set is deliberate: a derivative worker segments one
    photograph at a time, and lifting after each would lift a 210 member scene 210 times. The price
    is that a scene whose segmentation never completes stays stale until the command is run for
    it. Person regions play no part: one reviewed after the lift is reported in the reader's
    ``stale_inputs`` while everything else is still served.
    """
    rows = repository.connection.execute(
        _SCENES_WITH_MASKS,
        {
            "workspace": repository.workspace_id,
            "mask_kind": OBJECT_MASK_KIND,
            "segments_kind": SCENE_SEGMENTS_KIND,
        },
    ).fetchall()
    due: list[SegmentsDue] = []
    for row in rows:
        masks = tuple(sorted((str(c), str(a), str(d)) for c, a, d in row["masks"]))
        if not row["member_count"] or len(masks) != row["member_count"]:
            continue
        reason = _why_due(store, row, masks)
        if reason is not None:
            due.append(SegmentsDue(row["scene_id"], row["job_id"], masks, reason))
    return due


def _why_due(
    store: ContentAddressedStore,
    row: Mapping[str, Any],
    masks: tuple[tuple[str, str, str], ...],
) -> str | None:
    """Why a scene's newest segments do not answer for these masks under its build, or None."""
    from exulanica.errors import BlobNotFoundError, IntegrityError
    from exulanica.evidence.blob import BlobId

    if row["segments_sha256"] is None:
        return "no segments have been lifted for this build"
    try:
        envelope = json.loads(store.get(BlobId(bytes(row["segments_sha256"]))))
        bindings = envelope["segments"]["bindings"]
        receipts = tuple(
            str(bindings[field])
            for field in (
                "pose_receipt_sha256",
                "placement_receipt_sha256",
                "gate_receipt_sha256",
            )
        )
        bound = tuple(
            sorted(
                (str(item["capture_ref"]), str(item["artifact_ref"]), str(item["content_sha256"]))
                for item in bindings["object_mask_inputs"]
            )
        )
    except (BlobNotFoundError, IntegrityError, KeyError, TypeError, ValueError):
        return "the newest segments cannot be read"
    if receipts != tuple(
        bytes(row[field]).hex() for field in ("pose_sha256", "placement_sha256", "gate_sha256")
    ):
        return "the newest segments belong to another build"
    if bound != masks:
        return "a member's object masks changed after the newest segments were lifted"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m exulanica.ingest.scene_segments --workspace <uuid> --scene <uuid>``."""
    from exulanica.db import Database
    from exulanica.env import resolve_data_dir
    from exulanica.ingest.repository import IngestRepository
    from exulanica.ingest.stages import STAGES
    from exulanica.store.local import LocalContentAddressedStore

    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    parser.add_argument("--scene", type=uuid.UUID, required=True)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument(
        "--gaussian-ply",
        type=Path,
        default=None,
        help="a PLY of the scene's trained Gaussians, decoded from its delivery",
    )
    parser.add_argument(
        "--gaussian-delivery-sha256",
        default=None,
        help="the delivery artifact digest the PLY was decoded from; required with --gaussian-ply",
    )
    args = parser.parse_args(argv)
    store = LocalContentAddressedStore(resolve_data_dir(explicit=args.data_dir).resolve() / "blobs")
    gaussian_ply = None if args.gaussian_ply is None else args.gaussian_ply.read_bytes()
    gaussian_source = None
    if gaussian_ply is not None:
        if not args.gaussian_delivery_sha256:
            parser.error("--gaussian-ply needs --gaussian-delivery-sha256")
        gaussian_source = {
            "ply_sha256": _digest(gaussian_ply),
            "delivery_sha256": args.gaussian_delivery_sha256,
            "basis": "decoded trained delivery",
        }
    with Database.from_env().session(args.workspace) as connection:
        repository = IngestRepository(connection, args.workspace)
        repository.register_stages(STAGES)
        result = publish_scene_segments(
            repository,
            store,
            args.scene,
            gaussian_ply=gaussian_ply,
            gaussian_source=gaussian_source,
        )
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result.get("action") in {"written", "already-present"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
