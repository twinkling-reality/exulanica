"""The lift itself: what each photograph's regions say about a scene's geometry, as voxel segments.

The arithmetic only, over arrays and with no database or store. The scene's samples (its point map
or Gaussians, placed in the scene's frame) are projected through every recovered camera with the
masked-geometry check's projector, a depth buffer per camera keeps a sample behind what that camera
saw from voting, each region votes for the samples it covers, and the samples enough views agree on
become each entity's occupied voxels (:class:`LiftRegion` in, segments out).
:mod:`exulanica.ingest.scene_segments` builds, checks and publishes the artifact from them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from exulanica.canonical import canonical_json
from exulanica.consent.regions import Silhouette
from exulanica.evidence.region import PPM
from exulanica.ingest.masked_geometry import GaussianView, camera_point, image_point, ppm_point
from exulanica.reconstruction.placement import PlacementRecord, validated_receipt_cameras

if TYPE_CHECKING:
    import numpy as np


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


# -- geometry in --------------------------------------------------------------------------------


def _cameras(pose_receipt: bytes) -> dict[str, GaussianView]:
    """Every accepted recovered camera, in the masked-geometry check's own view type.

    Read by ``validated_receipt_cameras``, which resolves each camera's calibration through the
    same code ``recovered_camera_records`` uses, including the distortion models projected as a
    pinhole approximation, and returns the COLMAP camera-from-world pose the check's projector
    takes. It leaves the sparse observations unread, which is why the receipt must already have
    been validated: ``build_scene_segments`` holds these bytes to the digest its placement is
    bound to, and that placement was built from them.
    """
    views: dict[str, GaussianView] = {}
    for capture_ref, record in validated_receipt_cameras(pose_receipt).items():
        calibration = record["calibration"]
        assert isinstance(calibration, dict)
        views[capture_ref] = GaussianView(
            image_name=str(record["image_name"]),
            quaternion_wxyz=tuple(float(value) for value in record["quaternion_wxyz"]),  # type: ignore[arg-type,attr-defined]
            translation_xyz=tuple(float(value) for value in record["translation_xyz"]),  # type: ignore[arg-type,attr-defined]
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


#: A view's occlusion grid: the nearest depth per cell, and the grid's width and height.
_Occlusion = tuple["np.ndarray", int, int]


def _samples(
    placement: PlacementRecord,
    point_maps: Mapping[str, bytes],
    gaussian_centres: np.ndarray | None,
    params: Mapping[str, Any],
    cameras: Mapping[str, GaussianView],
) -> tuple[_Samples, dict[str, _Occlusion]]:
    """Every sample the lift votes over, and each recovered view's occlusion grid.

    A member's whole placed map is needed once, for its own view's depth test, so the grid is built
    the moment the map is placed and the map is dropped with it. MEASURED 2026-09-11 on the
    volcanic scene: keeping all 210 placed maps until the vote peaked the build at 1,052 MiB of
    traced allocations, and this is arithmetic on the same arrays in the same order, so the grids
    and the artifact are byte for byte what they were.
    """
    import numpy as np

    budget = int(params["point_map_samples_per_member"])
    grid = int(params["occlusion_grid_cells"])
    chunks: list[np.ndarray] = []
    sources: list[np.ndarray] = []
    members: list[tuple[str, str, str]] = []
    occlusion: dict[str, _Occlusion] = {}
    for member in placement.placed:
        data = point_maps.get(member.capture_ref)
        if data is None:
            continue
        placed = _placed(member.scene_from_opm, _opm_positions(data))
        view = cameras.get(member.capture_ref)
        if view is not None:
            occlusion[member.capture_ref] = _depth_buffer(view, placed, grid)
        chosen = placed[_evenly(len(placed), budget)]
        chunks.append(chosen)
        sources.append(np.full(len(chosen), len(members), dtype=np.int64))
        members.append(
            (member.capture_ref, member.point_map_artifact_ref, member.point_map_content_sha256)
        )
    if gaussian_centres is not None and len(gaussian_centres):
        centres = np.asarray(gaussian_centres, dtype=np.float64).reshape(-1, 3)
        centres = centres[_evenly(len(centres), int(params["gaussian_samples_max"]))]
        chunks.append(centres)
        sources.append(np.full(len(centres), -1, dtype=np.int64))
    points = np.concatenate(chunks) if chunks else np.zeros((0, 3))
    source = np.concatenate(sources) if sources else np.zeros(0, dtype=np.int64)
    return _Samples(points, source, tuple(members)), occlusion


def _lift(
    samples: _Samples,
    cameras: Mapping[str, GaussianView],
    occlusion: Mapping[str, _Occlusion],
    regions: Sequence[LiftRegion],
    params: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Vote every sample into at most one entity, then cut entities into segments.

    ``occlusion`` holds a depth grid for each view that has a placed map of its own, from
    ``_depth_buffer``; a view without one counts every sample in its frame as seen.
    """
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
    tolerance = 1 + int(params["occlusion_relative_tolerance_millionths"]) / 1_000_000
    for capture_ref in sorted(cameras):
        view = cameras[capture_ref]
        width, height = view.image_size
        front, u, v, depth = _project(view, samples.points)
        frame = (u >= 0) & (u < width) & (v >= 0) & (v < height)
        index, u, v, depth = front[frame], u[frame], v[frame], depth[frame]
        if capture_ref in occlusion:
            buffer, grid_w, grid_h = occlusion[capture_ref]
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
