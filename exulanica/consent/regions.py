"""Where a person is in a photograph, and never who they are.

Default deny is a property of this module's silence rather than of a policy call somewhere else:
a region carries no state at all. :mod:`exulanica.consent.states` resolves one, and only
from receipts, so a region nobody has decided about resolves to ``unknown`` and ``unknown`` masks.
Nothing here can produce a state, which is what stops a detector from admitting anybody.

**The outline is integers, for the reason a citation region is.** Coordinates are parts per
million of the normalised display unit square, the grid :mod:`exulanica.evidence.region` already
froze, so an outline enters a digest with no float and two implementations agree on the bytes. A
detector that reports a box reports a four point outline and says so; nothing here quietly
promotes a box into a claim about a silhouette, because masking a box hides more than the person
and describing it as an outline would claim precision that was never measured.

**A region's identity is the one identity already in use.** ``region_key`` is
:func:`exulanica.identity.keys.occurrence_identity_key` over the outline's bounding box, which is
bucketed on a 16 by 16 grid precisely so that two runs of two detector versions land in the same
cell. That is what makes a human's confirmation survive a re-run: a deleted false positive stays
deleted and a confirmed person stays confirmed, because neither is keyed on a row id. It also
means a confirmed region and the ``person`` occurrence the vision stage wrote for the same body
share one key, so the existing rejection and naming memory applies to it unchanged.

**No template, ever.** A region is a location. This module derives nothing from the pixels it
names, persists no descriptor, and offers no comparison of two regions in two photographs.
:mod:`exulanica.identity.keys` records the standing reason: ``face`` is absent from
``PRODUCIBLE_MODALITIES`` because the decision that would permit a face embedding belongs to a
human and has not been made. Locating a body does not make that decision.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

from PIL import Image

from exulanica.evidence.address import EvidenceAddress
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import PPM, DisplayGeometry, Rect, Region
from exulanica.identity.keys import occurrence_identity_key

__all__ = [
    "PERSON_OCCURRENCE_CLASS",
    "DetectedPerson",
    "PersonDetector",
    "Silhouette",
    "region_key",
]

#: The occurrence class the vision stage already writes for a located person. Shared here rather
#: than spelled again, so a confirmed region and that occurrence cannot drift into two keys.
PERSON_OCCURRENCE_CLASS: Final = "person"

#: The fewest points that bound an area. Two points are a line and a line masks nothing.
_MIN_POINTS: Final = 3


@dataclass(frozen=True, slots=True)
class Silhouette:
    """A closed, non-degenerate outline in normalised display space, in parts per million.

    Stored as the points themselves rather than as a mask image because the outline is what a
    reviewer edits, what the graph payload draws, and what a digest is taken over; a rasterised
    mask is a function of this and an image size, recomputed wherever it is needed.
    """

    points: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        if len(self.points) < _MIN_POINTS:
            raise ValueError(
                f"an outline needs at least {_MIN_POINTS} points to bound an area, got "
                f"{len(self.points)}. A degenerate outline covers no pixel, so every mask built "
                "from it would hide nobody while reporting that it had."
            )
        for x, y in self.points:
            if not isinstance(x, int) or not isinstance(y, int):
                raise ValueError("outline coordinates must be integers in parts per million")
            if isinstance(x, bool) or isinstance(y, bool):
                raise ValueError("outline coordinates must be integers in parts per million")
            if not 0 <= x <= PPM or not 0 <= y <= PPM:
                raise ValueError(f"outline point ({x}, {y}) is outside the normalised square")
        if self._twice_area() == 0:
            raise ValueError(
                "an outline must enclose a positive area. A zero-area outline is the same "
                "failure as a zero-area region: every containment test passes it and nothing "
                "is ever masked."
            )

    def _twice_area(self) -> int:
        """Twice the signed shoelace area, in exact integer arithmetic."""
        total = 0
        for index, (x1, y1) in enumerate(self.points):
            x2, y2 = self.points[(index + 1) % len(self.points)]
            total += x1 * y2 - x2 * y1
        return total

    @classmethod
    def from_rect(cls, rect: Rect) -> Silhouette:
        """The four corners of a box, clockwise from its origin.

        A detector that reports only a box comes through here, and the region it produces records
        ``shape='box'`` so that nothing downstream reads these four points as a measured outline.
        """
        right = rect.x_ppm + rect.w_ppm
        bottom = rect.y_ppm + rect.h_ppm
        return cls(
            (
                (rect.x_ppm, rect.y_ppm),
                (right, rect.y_ppm),
                (right, bottom),
                (rect.x_ppm, bottom),
            )
        )

    def bounding_rect(self) -> Rect:
        """The smallest box containing the outline. What the identity key is bucketed on."""
        xs = [x for x, _ in self.points]
        ys = [y for _, y in self.points]
        left, top = min(xs), min(ys)
        return Rect(
            x_ppm=left,
            y_ppm=top,
            w_ppm=max(1, max(xs) - left),
            h_ppm=max(1, max(ys) - top),
        )

    def contains(self, x_ppm: int, y_ppm: int) -> bool:
        """Even-odd containment, in exact integer arithmetic.

        The crossing test is written as two integer products rather than as an x intercept
        because an intercept is a division, a division here is a float, and a float decides
        differently on two machines. A mask whose edge pixels depend on the host is not a
        deterministic derivative, and the whole point of this stage is that it is one.
        """
        inside = False
        for index, (x1, y1) in enumerate(self.points):
            x2, y2 = self.points[(index + 1) % len(self.points)]
            if (y1 > y_ppm) == (y2 > y_ppm):
                continue
            delta_y = y2 - y1
            left = (x_ppm - x1) * delta_y
            right = (y_ppm - y1) * (x2 - x1)
            if (delta_y > 0 and left < right) or (delta_y < 0 and left > right):
                inside = not inside
        return inside

    def as_digest_input(self) -> dict[str, Any]:
        return {"kind": "polygon", "points": [[x, y] for x, y in self.points]}

    @classmethod
    def from_digest_input(cls, value: Mapping[str, Any]) -> Silhouette:
        """Rebuild an outline from what :meth:`as_digest_input` wrote.

        Needed because the outline is stored as ``jsonb`` and read back as a plain dictionary,
        and the validation in ``__post_init__`` is the only thing standing between a corrupted
        row and a mask that covers nothing. Rebuilding through the constructor rather than
        trusting the stored shape is what makes a bad row raise instead of silently hiding
        nobody.
        """
        if value.get("kind") != "polygon":
            raise ValueError(f"unsupported outline kind {value.get('kind')!r}")
        points = value.get("points")
        if not isinstance(points, list):
            raise ValueError("an outline needs a list of points")
        return cls(tuple((int(x), int(y)) for x, y in points))


def region_key(blob_id: BlobId, silhouette: Silhouette, display: DisplayGeometry) -> bytes:
    """The 32 byte identity of a person region, stable across detector versions.

    Deliberately the same function the vision stage keys its ``person`` occurrences with, over
    the same bounding box. Two detectors that find the same body in the same photograph agree
    here even when their outlines differ, which is what a human's confirmation is recorded
    against.
    """
    address = EvidenceAddress.photograph(
        blob_id, region=Region(rect=silhouette.bounding_rect(), display=display)
    )
    return occurrence_identity_key(address, PERSON_OCCURRENCE_CLASS)


@dataclass(frozen=True, slots=True)
class DetectedPerson:
    """One candidate region, before any human has looked at it.

    ``confidence`` is the detector's own band and is never a threshold: a low confidence
    detection still masks, because the states in :mod:`exulanica.consent.states` decide
    that and absence of a decision is not consent. It is carried so a reviewer can sort.
    """

    silhouette: Silhouette
    shape: Literal["box", "polygon"]
    confidence: Literal["low", "medium", "high"]
    detector: str
    #: Which visible trace this is, when the detector said. A reviewer shown an outline on a
    #: neutral field cannot otherwise tell a hand at the frame edge from a coat on a chair, and
    #: the partial traces are exactly the ones the old whitelist missed.
    part: str | None = None


class PersonDetector(Protocol):
    """What a person detector must be, and the little it is trusted to do.

    Small on purpose. A detector proposes regions and is believed about nothing else: it does not
    name, does not decide a state, does not link a body across photographs, and returns no
    descriptor that could be compared with one from another photograph. An implementation that
    wanted to do any of those would have nowhere to put the result.

    ``model_id`` is read before the call and enters the stage's idempotency key as a run-time
    binding, so swapping a detector regenerates rather than leaving the corpus keyed as though
    nothing had changed. That is why this stage names a model role at all: a detector chosen at
    run time cannot be described by a compile-time parameter.
    """

    @property
    def model_id(self) -> str: ...

    @property
    def requires_observation(self) -> bool:
        """Whether this detector cannot look without a recorded vision observation.

        Declared rather than inferred, because the alternative is to hand an adapter an empty
        context and read the nothing it returns as "found nobody". Those are different facts and
        conflating them is how a photograph nobody screened is treated as a photograph with
        nobody in it.
        """
        ...

    def detect(self, image: Image.Image, context: Mapping[str, Any]) -> tuple[DetectedPerson, ...]:
        """Propose every region that might be a person. Over-proposing is the safe direction.

        ``context`` carries whatever the pipeline already knows about this photograph, so an
        adapter over an observation another stage recorded needs no second look at the pixels.
        An adapter is free to ignore it.
        """
        ...
