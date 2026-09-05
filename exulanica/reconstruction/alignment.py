"""Conservative scale alignment from COLMAP tracks to unchanged OPM samples.

This measures consistency between two reconstructions. It cannot establish physical scale,
complete surfaces, navigation, or visual quality. Thresholds are explicit engineering rejection
limits, not a calibrated statement about arbitrary photographs.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from exulanica.reconstruction.validation import validate_opm

# Integer policy is shared with the stage registry, so a changed limit changes build identity.
ALIGNMENT_POLICY = {
    "method": "colmap-track-opm-robust-scalar/v1",
    "max_sparse_observations_per_image": 4096,
    "minimum_track_length": 2,
    "maximum_reprojection_error_micropixels": 2_000_000,
    "minimum_training_correspondences": 24,
    "minimum_validation_correspondences": 6,
    "validation_stride": 5,
    "maximum_match_distance_millipixels": 1000,
    "maximum_relative_residual_millionths": 150_000,
    "minimum_inlier_fraction_millionths": 600_000,
    "minimum_image_grid_cells": 6,
    "image_grid_size": 4,
}

AlignmentReason = Literal[
    "alignment-unavailable", "alignment-insufficient-correspondences", "alignment-inconsistent"
]


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    scale: float | None
    reason: AlignmentReason | None
    diagnostics: dict[str, object]


def _rotation(q: Sequence[float]) -> tuple[tuple[float, ...], ...]:
    w, x, y, z = q
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


def fit_point_map_scale(
    data: bytes | None,
    *,
    image_size: tuple[int, int] | None,
    observations: Sequence[Sequence[float]],
    quaternion_wxyz: Sequence[float],
    translation_xyz: Sequence[float],
) -> AlignmentResult:
    """Fit on four fifths of unique samples and reject on untouched fifth-fold samples.

    Correspondence rows are [point id, source x, source y, world x/y/z, reprojection error,
    track length]. All three camera-space components enter residuals, so wrong focal geometry
    cannot pass merely by matching depth. No translation/rotation is fitted over the pose.
    """
    diagnostics: dict[str, object] = {"method": ALIGNMENT_POLICY["method"]}

    def refused(reason: AlignmentReason) -> AlignmentResult:
        return AlignmentResult(None, reason, diagnostics)

    if data is None or image_size is None or not observations:
        return refused("alignment-unavailable")
    policy = ALIGNMENT_POLICY
    grid_size = int(policy["image_grid_size"])
    minimum_train = int(policy["minimum_training_correspondences"])
    minimum_validation = int(policy["minimum_validation_correspondences"])
    maximum_residual = int(policy["maximum_relative_residual_millionths"]) / 1_000_000
    minimum_fraction = int(policy["minimum_inlier_fraction_millionths"]) / 1_000_000
    integrity = validate_opm(data)
    if integrity.source_size != image_size:
        raise ValueError("COLMAP and point-map source dimensions disagree")
    width, height = integrity.model_size
    header = json.loads(data[8 : 8 + int.from_bytes(data[4:8], "little")])
    section = next(item for item in header["sections"] if item["name"] == "position")
    focal = height / (2 * math.tan(math.radians(integrity.fov_y_degrees) / 2))
    lattice: dict[tuple[int, int], tuple[float, float, tuple[float, float, float]]] = {}
    for x, y, z in struct.iter_unpack(
        "<fff", data[section["byteOffset"] : section["byteOffset"] + section["byteLength"]]
    ):
        # MoGe and the OPM renderer use centred pinhole projection in the model image grid.
        u, v = focal * x / -z + width / 2, -focal * y / -z + height / 2
        cell = (math.floor(u), math.floor(v))
        if 0 <= cell[0] < width and 0 <= cell[1] < height:
            candidate = (u, v, (x, -y, -z))
            previous = lattice.get(cell)
            if previous is None or candidate[2][2] < previous[2][2]:
                lattice[cell] = candidate
    rotation = _rotation(quaternion_wxyz)
    used_cells: set[tuple[int, int]] = set()
    pairs: list[tuple[tuple[float, ...], tuple[float, ...], tuple[int, int], tuple[int, int]]] = []
    # Best measured tracks get first use of a model sample; IDs break ties deterministically.
    for row in sorted(observations, key=lambda item: (item[6], item[0])):
        _point_id, px, py, wx, wy, wz, error, track_length = row
        if (
            error > int(policy["maximum_reprojection_error_micropixels"]) / 1_000_000
            or error < 0
            or track_length < int(policy["minimum_track_length"])
        ):
            continue
        if not (0 <= px < image_size[0] and 0 <= py < image_size[1]):
            continue
        target = tuple(
            sum(rotation[axis][column] * (wx, wy, wz)[column] for column in range(3))
            + translation_xyz[axis]
            for axis in range(3)
        )
        if target[2] <= 0:
            continue
        u, v = px * width / image_size[0], py * height / image_size[1]
        cell = (math.floor(u), math.floor(v))
        candidates = [
            (math.hypot(lattice[key][0] - u, lattice[key][1] - v), key, lattice[key][2])
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            if (key := (cell[0] + dx, cell[1] + dy)) in lattice
        ]
        if not candidates:
            continue
        distance, nearest, local = min(candidates)
        if (
            distance > int(policy["maximum_match_distance_millipixels"]) / 1000
            or nearest in used_cells
        ):
            continue
        used_cells.add(nearest)
        grid_cell = (
            min(grid_size - 1, int(px * grid_size / image_size[0])),
            min(grid_size - 1, int(py * grid_size / image_size[1])),
        )
        pairs.append((local, target, grid_cell, nearest))
    # Hash source sample position, rather than input iteration order, before the held-out split.
    pairs.sort(key=lambda pair: hashlib.sha256(repr(pair[3]).encode()).digest())
    train = [pair for index, pair in enumerate(pairs) if index % int(policy["validation_stride"])]
    held_out = [
        pair for index, pair in enumerate(pairs) if not index % int(policy["validation_stride"])
    ]
    diagnostics.update(
        {
            "matched_unique_samples": len(pairs),
            "training_samples": len(train),
            "validation_samples": len(held_out),
            "occupied_image_grid_cells": len({pair[2] for pair in pairs}),
        }
    )
    if (
        len(train) < minimum_train
        or len(held_out) < minimum_validation
        or len({pair[2] for pair in pairs}) < int(policy["minimum_image_grid_cells"])
    ):
        return refused("alignment-insufficient-correspondences")

    def sample_scale(pair: tuple) -> float:
        local, target, _cell, _pixel = pair
        return sum(a * b for a, b in zip(local, target, strict=True)) / sum(a * a for a in local)

    scale = statistics.median(sample_scale(pair) for pair in train)

    def residual(pair: tuple) -> float:
        local, target, _cell, _pixel = pair
        return math.dist(tuple(scale * value for value in local), target) / math.sqrt(
            sum(value * value for value in target)
        )

    if not math.isfinite(scale) or scale <= 0:
        return refused("alignment-inconsistent")
    inliers = [pair for pair in train if residual(pair) <= maximum_residual]
    if len(inliers) >= minimum_train:
        scale = statistics.median(sample_scale(pair) for pair in inliers)
    validation_errors = [residual(pair) for pair in held_out]
    train_fraction = sum(residual(pair) <= maximum_residual for pair in train) / len(train)
    validation_fraction = sum(error <= maximum_residual for error in validation_errors) / len(
        held_out
    )
    diagnostics.update(
        {
            "training_inlier_fraction": train_fraction,
            "validation_inlier_fraction": validation_fraction,
            "validation_median_relative_residual": statistics.median(validation_errors),
            "validation_p90_relative_residual": sorted(validation_errors)[
                math.ceil(0.9 * len(validation_errors)) - 1
            ],
            "local_units_to_scene_units": scale,
            "physically_validated": False,
        }
    )
    if (
        len(inliers) < minimum_train
        or train_fraction < minimum_fraction
        or validation_fraction < minimum_fraction
    ):
        return refused("alignment-inconsistent")
    return AlignmentResult(scale, None, diagnostics)
