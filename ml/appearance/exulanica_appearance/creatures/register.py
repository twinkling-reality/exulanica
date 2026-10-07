"""Register a sculpted mesh onto its plan: turn it to face the plan's front and fit it to the sketch's
box, judged by silhouette against the control picture.

A 3D model returns a mesh in its own frame and size. The plan's sketch, drawn from the control
camera, is the picture the concept followed, so the mesh is turned about the vertical through a
fixed set of yaws, each turned mesh fitted by uniform scale to the sketch's box and drawn by the same
camera in the control picture's framing. A turn scores its silhouette's overlap with the sketch's
(intersection over union) times how well its depth agrees with the sketch's where both are drawn
(their correlation, none below zero), so a body turned back to front, whose outline can match,
scores nothing. Every 10 degrees is scored, and the three best are each refined to the degree
within 5 either side, so a thin-legged body whose best turn falls between two tried ones is not
lost to a turn back to front that happened to score well; the best refined turn is kept (the
smaller turn on a tie). The kept mesh is then fitted to the sketch's box axis by axis; the three
scales may differ by at most a quarter from one another, as a mesh further from the plan's
proportions is not the plan's body. A mesh refused for its proportions is refused with that fit and
its measures, so the refusal's record states how far from the plan it was. Proper rotations only: a
mirror would swap left and right.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

from exulanica_appearance.creatures.geometry import CONTROL_CAMERA, Camera, Drawn, rasterise

__all__ = ["PROPORTION_RATIO", "YAWS", "Registered", "RegistrationRefused", "register"]

#: The turns tried first, in degrees about the vertical, counterclockwise seen from above; the
#: REFINED best are each refined to the degree within REFINE either side.
YAWS: Final = tuple(range(0, 360, 10))
REFINED: Final = 3
REFINE: Final = 5
#: The largest ratio between two of the three axis scales that fit a mesh to the sketch's box.
PROPORTION_RATIO: Final = 1.25
#: The side of the silhouettes the search compares, in pixels.
SEARCH_PX: Final = 192


class RegistrationRefused(ValueError):
    """A registration refused by name, with the fit it refused when there was one."""

    def __init__(self, code: str, detail: str, refused: Registered | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.refused = refused


@dataclass(frozen=True)
class Registered:
    """The mesh's positions in the slot frame fitted to the sketch's box, and what was done."""

    positions: np.ndarray
    yaw_degrees: int
    scale: tuple[float, float, float]
    score_per_mille: dict[int, int]
    overlap_kept_per_mille: int
    depth_agreement_kept_per_mille: int


def _turn(points: np.ndarray, degrees: float) -> np.ndarray:
    angle = np.radians(degrees)
    cos, sin = np.cos(angle), np.sin(angle)
    x, y = points[..., 0], points[..., 1]
    return np.stack([x * cos - y * sin, x * sin + y * cos, points[..., 2]], axis=-1)


def _box(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    flat = points.reshape(-1, 3)
    return flat.min(axis=0), flat.max(axis=0)


def _fit(points: np.ndarray, low: np.ndarray, high: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """``points`` scaled about their box's bottom centre and stood on the target box's."""
    own_low, own_high = _box(points)
    base = np.array([(own_low[0] + own_high[0]) / 2, (own_low[1] + own_high[1]) / 2, own_low[2]])
    target = np.array([(low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]])
    return (points - base) * scale + target


def _overlap(a: Drawn, b: Drawn) -> int:
    union = int((a.mask | b.mask).sum())
    return 0 if union == 0 else (1000 * int((a.mask & b.mask).sum())) // union


def _agreement(a: Drawn, b: Drawn) -> int:
    """The correlation of two depths where both are drawn, per mille, none below zero."""
    both = a.mask & b.mask
    if int(both.sum()) < 16:
        return 0
    first, second = a.depth[both], b.depth[both]
    spread = float(first.std() * second.std())
    if spread == 0.0:
        return 0
    correlation = float(((first - first.mean()) * (second - second.mean())).mean()) / spread
    return max(round(correlation * 1000), 0)


def register(
    positions: np.ndarray,
    triangles: np.ndarray,
    sketch: np.ndarray,
    *,
    camera: Camera = CONTROL_CAMERA,
) -> Registered:
    """``positions`` (slot frame, any size) turned and fitted onto the sketch's triangles
    (T x 3 x 3, slot frame, metres)."""
    low, high = _box(sketch)
    size = high - low
    if (size <= 0).any():
        raise RegistrationRefused("sculpt_unfit", "the sketch has no extent along an axis")
    reference: Drawn = rasterise(sketch, camera, SEARCH_PX)
    scores: dict[int, int] = {}

    def score(yaw: int) -> int:
        if yaw not in scores:
            turned = _turn(positions, yaw)
            own_low, own_high = _box(turned)
            extent = own_high - own_low
            if (extent <= 0).any():
                raise RegistrationRefused("sculpt_unfit", "the mesh has no extent along an axis")
            uniform = float(np.min(size / extent))
            fitted = _fit(turned, low, high, np.full(3, uniform))
            drawn = rasterise(fitted[triangles], camera, SEARCH_PX, frame=reference)
            scores[yaw] = _overlap(drawn, reference) * _agreement(drawn, reference) // 1000
        return scores[yaw]

    def order(yaw: int) -> tuple[int, int]:
        return score(yaw), -min(yaw, 360 - yaw)

    coarse = sorted(YAWS, key=order, reverse=True)[:REFINED]
    best = max(
        sorted({(yaw + step) % 360 for yaw in coarse for step in range(-REFINE, REFINE + 1)}),
        key=order,
    )
    turned = _turn(positions, best)
    own_low, own_high = _box(turned)
    scale = size / (own_high - own_low)
    fitted = _fit(turned, low, high, scale)
    kept = rasterise(fitted[triangles], camera, SEARCH_PX, frame=reference)
    registered = Registered(
        positions=fitted,
        yaw_degrees=best,
        scale=(float(scale[0]), float(scale[1]), float(scale[2])),
        score_per_mille=dict(sorted(scores.items())),
        overlap_kept_per_mille=_overlap(kept, reference),
        depth_agreement_kept_per_mille=_agreement(kept, reference),
    )
    if float(scale.max() / scale.min()) > PROPORTION_RATIO:
        raise RegistrationRefused(
            "sculpt_proportions_unfit",
            "the sculpted body's length, width and height are not the plan's proportions",
            registered,
        )
    return registered
