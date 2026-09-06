"""The detectors a person-region stage can be given, and the honest limits of each.

**No local person detector exists in this deployment, and that is a measured fact rather than an
assumption.** Verified 2026-09-05 against ``uv.lock`` and the installed environment: torchvision,
transformers, ultralytics, mediapipe, onnxruntime, rembg and segment-anything are all absent, and
``opencv-python-headless`` resolves to 5.0.0, which removed ``cv2.HOGDescriptor`` and ships an
empty ``cv2/data``. The reconstruction extra is torch, numpy, opencv, scipy, MoGe and
huggingface-hub; the pose extra is pycolmap. Nothing in either finds people. So no adapter here
loads weights, and none is invented: a fabricated detection would be worse than no detection,
because a reviewer would be confirming somebody else's guess about their own photograph.

**What ships instead is one real adapter over detections this system already made.**
:class:`RecordedObservationDetector` reads the ``person_objects`` the ``vision`` stage already
recorded for a photograph. Those are real detections with real boxes, produced under the existing
vision controls and already written as ``person`` occurrences; this adapter calls no model and
adds no capability. It is the difference between reusing a fact and inventing one.

**A box is reported as a box.** The vision schema gives an axis-aligned box, not an outline.
Masking a box hides a superset of the person, which is the safe direction under default deny, so
the region is usable immediately; but ``shape='box'`` travels with it so that nothing downstream
describes it as a measured silhouette. Whole-person outlines are what the protocol asks a future
pinned segmenter for, and this adapter does not pretend to be one.

**A detection with no box is not a smaller problem than a detection with one.** The vision schema
makes ``box`` optional and the stage refuses to guess where an unlocated person is, so a
photograph with one masks whole. Reconstructing a person because nobody could say where they
were is the failure this whole design exists to prevent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from PIL import Image

from exulanica.consent.regions import DetectedPerson, Silhouette
from exulanica.evidence.region import PPM, Rect

__all__ = [
    "WHOLE_IMAGE",
    "NoRegionDetector",
    "PathologicalRegionDetector",
    "RecordedObservationDetector",
    "StubRegionDetector",
    "whole_image_silhouette",
]

#: The outline used when a person is known to be present but not locatable. Deliberately the whole
#: frame: an unlocated person masks the photograph rather than a guessed part of it.
WHOLE_IMAGE: Final = "whole-image"


def whole_image_silhouette() -> Silhouette:
    """Every pixel. What an unlocated person costs."""
    return Silhouette(((0, 0), (PPM, 0), (PPM, PPM), (0, PPM)))


class RecordedObservationDetector:
    """Regions from the ``person_objects`` the vision stage already recorded.

    Calls no model and downloads nothing. ``context['person_boxes']`` is a sequence of
    ``(x, y, w, h, confidence)`` in normalised coordinates, already clamped by the caller, and
    ``context['unlocated_people']`` is how many people the observation named without a usable
    box. The two are separate because they mask differently.
    """

    @property
    def model_id(self) -> str:
        return "recorded-vision-observation/v1"

    def detect(self, image: Image.Image, context: Mapping[str, Any]) -> tuple[DetectedPerson, ...]:
        del image  # The observation was made against these bytes; re-reading them adds nothing.
        found: list[DetectedPerson] = []
        for x, y, width, height, confidence in context.get("person_boxes", ()):
            found.append(
                DetectedPerson(
                    silhouette=Silhouette.from_rect(Rect.from_normalised(x, y, width, height)),
                    shape="box",
                    confidence=confidence,
                    detector=self.model_id,
                )
            )
        for _ in range(int(context.get("unlocated_people", 0))):
            found.append(
                DetectedPerson(
                    silhouette=whole_image_silhouette(),
                    shape="box",
                    confidence="low",
                    detector=self.model_id,
                )
            )
        return tuple(found)


class StubRegionDetector:
    """Returns exactly the outlines it was constructed with, and never looks at the pixels.

    Deliberately blind, following :class:`exulanica.reconstruction.testing.FlatDepthModel`: a
    double that produced convincing-looking regions would invite somebody to read a test of the
    plumbing as a test of detection.
    """

    def __init__(self, regions: tuple[DetectedPerson, ...] = ()) -> None:
        self._regions = regions

    @property
    def model_id(self) -> str:
        return "fixed-region-double"

    def detect(self, image: Image.Image, context: Mapping[str, Any]) -> tuple[DetectedPerson, ...]:
        del image, context
        return self._regions


class NoRegionDetector:
    """Finds nothing, which is not the same fact as never having looked.

    Kept as its own double because those two are different rows and must stay different: a
    photograph screened and found empty may proceed, and a photograph never screened may not.
    Collapsing them is precisely how a default-deny system quietly becomes default-allow.
    """

    @property
    def model_id(self) -> str:
        return "no-region-double"

    def detect(self, image: Image.Image, context: Mapping[str, Any]) -> tuple[DetectedPerson, ...]:
        del image, context
        return ()


class PathologicalRegionDetector:
    """Everything a real detector eventually emits that the schema must refuse or clamp.

    A whole-frame region, a one-pixel sliver and a region touching every edge. Present so the
    clamping and refusal paths are exercised by something other than a hand-written literal in
    one test.
    """

    @property
    def model_id(self) -> str:
        return "pathological-region-double"

    def detect(self, image: Image.Image, context: Mapping[str, Any]) -> tuple[DetectedPerson, ...]:
        del image, context
        return (
            DetectedPerson(whole_image_silhouette(), "box", "low", self.model_id),
            DetectedPerson(
                Silhouette(((0, 0), (1, 0), (1, PPM), (0, PPM))), "box", "low", self.model_id
            ),
            DetectedPerson(
                Silhouette(((0, 0), (PPM, 0), (PPM, 1), (0, 1))), "box", "high", self.model_id
            ),
        )
