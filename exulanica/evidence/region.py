"""Normalised spatial regions, quantised to integers so a digest can survive a language change.

The committed schema says a region is normalised to ``[0, 1]`` in **display** space, after
orientation is applied, and that the region is an input to ``span_digest``. It does not say how
the numbers are encoded, and that gap is load bearing: a JSON float in a digest input has no
canonical rendering that every implementation agrees on, so ``0.312`` written by Python and
``0.312`` written by a future Rust reader could hash differently while denoting the same box.

**Decision taken here:** coordinates are integers in parts per million of the normalised unit
square, ``0 .. 1_000_000``. One ppm of a 6000 pixel wide photograph is 0.006 px, so the
quantisation is far below any detector's own precision, and it makes the digest exact.
Conversion from a float uses ``Fraction`` for an exact binary value and then the project's one
rounding rule, so quantisation is deterministic rather than platform dependent.

Regions are non-empty for the same reason intervals are: a zero-area box overlaps nothing, and
a guard that tests overlap would silently pass it.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final, Literal

from exulanica.canonical import round_half_down
from exulanica.errors import InvalidAddressError

__all__ = [
    "MIRRORED_EXIF_ORIENTATIONS",
    "PPM",
    "DisplayGeometry",
    "Rect",
    "Region",
    "rotation_for_exif_orientation",
]

#: Parts per million: the denominator of the normalised coordinate grid.
PPM: Final = 1_000_000

_ALLOWED_ROTATIONS: Final = (0, 90, 180, 270)

#: EXIF Orientation values that include a mirror. ``rotation`` is four values and cannot express
#: a flip, which is why deriving a display rotation from a raw EXIF value is only ever valid for
#: the other four. ADR-0004 and ADR-0012 took the branch where that derivation never happens:
#: ingest normalises the pixels, so every photograph's display space is upright and these four
#: values are admitted like any other.
MIRRORED_EXIF_ORIENTATIONS: Final = frozenset({2, 4, 5, 7})

_EXIF_ROTATION: Final = {1: 0, 3: 180, 6: 90, 8: 270}


def rotation_for_exif_orientation(orientation: int) -> int:
    """Map an EXIF Orientation value to a display ``rotation``, or refuse.

    **This is the guard on the branch Exulanica did not take, and it is kept because the branch
    is still reachable by mistake.** ADR-0012 records the semantics: a photograph's display space
    is its upright pixel space, ingest normalises the pixels, and every ``img`` region therefore
    carries ``display.rotation == 0``. Nothing in the pipeline calls this function.

    What it exists to stop is the plausible-looking shortcut of skipping normalisation and
    turning the EXIF tag straight into a display rotation. That works for exactly four of the
    eight values. For the other four it silently drops a mirror, which puts every region on the
    wrong side of the image, and because ``region`` is inside ``span_digest`` those wrong regions
    are baked into permanent citation addresses rather than showing up as a crooked picture.
    """
    if orientation in MIRRORED_EXIF_ORIENTATIONS:
        raise InvalidAddressError(
            f"EXIF Orientation {orientation} is mirrored and no rotation expresses a flip. "
            "Normalise the pixels at ingest instead, the way exulanica.ingest.exif does, and "
            "leave display.rotation at 0. Refusing rather than mis-placing a region that "
            "enters span_digest."
        )
    try:
        return _EXIF_ROTATION[orientation]
    except KeyError:
        raise InvalidAddressError(f"not a valid EXIF Orientation value: {orientation}") from None


def to_ppm(value: float | int | Fraction) -> int:
    """Quantise a normalised ``[0, 1]`` coordinate to parts per million, exactly."""
    fraction = Fraction(value)
    if not 0 <= fraction <= 1:
        raise InvalidAddressError(f"normalised coordinate out of [0, 1]: {value}")
    return round_half_down(fraction.numerator * PPM, fraction.denominator)


@dataclass(frozen=True, slots=True, order=True)
class DisplayGeometry:
    """The display space a normalised region is relative to, after orientation is applied."""

    w: int
    h: int
    rotation: int = 0
    sar_num: int = 1
    sar_den: int = 1

    def __post_init__(self) -> None:
        if self.w <= 0 or self.h <= 0:
            raise InvalidAddressError(f"display geometry must be positive: {self.w}x{self.h}")
        if self.rotation not in _ALLOWED_ROTATIONS:
            raise InvalidAddressError(
                f"rotation must be one of {_ALLOWED_ROTATIONS}, got {self.rotation}"
            )
        if self.sar_num <= 0 or self.sar_den <= 0:
            raise InvalidAddressError("sample aspect ratio components must be positive")

    def as_digest_input(self) -> dict[str, int]:
        return {
            "w": self.w,
            "h": self.h,
            "rotation": self.rotation,
            "sar_num": self.sar_num,
            "sar_den": self.sar_den,
        }


@dataclass(frozen=True, slots=True, order=True)
class Rect:
    """A non-empty axis-aligned box in normalised display space, in parts per million."""

    x_ppm: int
    y_ppm: int
    w_ppm: int
    h_ppm: int

    def __post_init__(self) -> None:
        for name, value in (
            ("x_ppm", self.x_ppm),
            ("y_ppm", self.y_ppm),
            ("w_ppm", self.w_ppm),
            ("h_ppm", self.h_ppm),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise InvalidAddressError(f"{name} must be an int, got {type(value).__name__}")
        if self.w_ppm < 1 or self.h_ppm < 1:
            raise InvalidAddressError(
                f"region must be non-empty: {self.w_ppm}x{self.h_ppm} ppm. A zero-area region "
                "overlaps nothing, so every overlap guard would pass it."
            )
        if self.x_ppm < 0 or self.y_ppm < 0:
            raise InvalidAddressError("region origin must be non-negative")
        if self.x_ppm + self.w_ppm > PPM or self.y_ppm + self.h_ppm > PPM:
            raise InvalidAddressError("region extends outside the normalised unit square")

    @classmethod
    def from_normalised(
        cls,
        x: float | Fraction,
        y: float | Fraction,
        w: float | Fraction,
        h: float | Fraction,
    ) -> Rect:
        """Build from normalised ``[0, 1]`` floats, quantising deterministically."""
        return cls(to_ppm(x), to_ppm(y), to_ppm(w), to_ppm(h))

    def as_digest_input(self) -> dict[str, int]:
        return {"x": self.x_ppm, "y": self.y_ppm, "w": self.w_ppm, "h": self.h_ppm}

    def as_percent_string(self) -> str:
        """Render as Media-Fragments-style ``x,y,w,h`` percentages with 4 decimal places.

        One ppm is 0.0001 percent, so four decimal places is exactly lossless and the string
        parses back to the same integers. Formatted by integer division rather than by dividing
        into a float, for the same reason floats are banned from digest inputs.
        """
        parts = (self.x_ppm, self.y_ppm, self.w_ppm, self.h_ppm)
        return ",".join(f"{v // 10000}.{v % 10000:04d}" for v in parts)

    @classmethod
    def from_percent_string(cls, text: str) -> Rect:
        parts = text.split(",")
        if len(parts) != 4:
            raise InvalidAddressError(f"xywh needs four components, got {text!r}")
        values: list[int] = []
        for part in parts:
            whole, _, frac = part.strip().partition(".")
            if not whole.isdigit() or (frac and not frac.isdigit()):
                raise InvalidAddressError(f"not a decimal percentage: {part!r}")
            if len(frac) > 4:
                raise InvalidAddressError(
                    f"percentage {part!r} is finer than one part per million, which the "
                    "normalised grid cannot represent"
                )
            values.append(int(whole) * 10000 + int(frac.ljust(4, "0") or "0"))
        return cls(*values)


@dataclass(frozen=True, slots=True, order=True)
class Region:
    """A spatial refinement of an evidence address.

    ``kind`` is a discriminator so that a polygon kind can be added later without changing the
    digest of any rectangle region already issued: a new ``kind`` value is additive, a changed
    tuple shape for an existing kind is not.
    """

    rect: Rect
    display: DisplayGeometry
    kind: Literal["rect"] = "rect"

    def __post_init__(self) -> None:
        if self.kind != "rect":
            raise InvalidAddressError(
                f"unsupported region kind {self.kind!r}. Only 'rect' exists at v1; a polygon "
                "kind is an additive extension."
            )

    def as_digest_input(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "rect": self.rect.as_digest_input(),
            "display": self.display.as_digest_input(),
        }
