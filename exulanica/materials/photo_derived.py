"""A recipe a model derived from a person's photographs: data that cannot exist without a right.

This is the object a future inverse model (``ml/``) will emit: a recipe, the photographs it was
read from, the model that read them, and the processing right that allowed it. It is inert today.
Nothing in this repository constructs one from a photograph, no function here takes pixels or a
capture, and ``material_recipe`` refuses a ``photo_derived`` row until the personal model right
(migration 0073) exists.

**The right is a reference, not a check.** ``exulanica.materials`` may not import
``exulanica.ingest``, where the right's types live, so :class:`ProcessingRightReference` holds the
right's id and the digest of its record as plain data. Whether that right is current, names this
model and this destination, and has not been withdrawn is asked at the boundary, by the world
service that writes the recipe, never here. What this object does guarantee is that it cannot be
built without naming one.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Final

from exulanica.materials.objects import MaterialObjectError, is_sha256

__all__ = [
    "PHOTO_DERIVED_RECIPE_PROFILE",
    "ModelIdentity",
    "PhotoDerivedRecipe",
    "ProcessingRightReference",
]

PHOTO_DERIVED_RECIPE_PROFILE: Final = "exulanica.photo-derived-recipe/v1"
_MODEL_ID: Final = re.compile(r"[a-z][a-z0-9.-]*/v[1-9][0-9]*")


@dataclass(frozen=True, slots=True)
class ProcessingRightReference:
    """Which personal model right allowed the reading, by id and by the digest of its record."""

    right_id: uuid.UUID
    record_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.right_id, uuid.UUID):
            raise MaterialObjectError("a processing right is named by its uuid")
        if not is_sha256(self.record_sha256):
            raise MaterialObjectError("a processing right's record is named by its sha256")


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """The model that read the photographs: a versioned id and the digest of its weights."""

    model_id: str
    weights_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or _MODEL_ID.fullmatch(self.model_id) is None:
            raise MaterialObjectError("a model id is lowercase, then /v and a version")
        if not is_sha256(self.weights_sha256):
            raise MaterialObjectError("a model's weights are named by their sha256")


@dataclass(frozen=True, slots=True)
class PhotoDerivedRecipe:
    """A recipe, the photographs it came from, the model, and the right. Nothing is optional."""

    recipe_sha256: str
    source_capture_ids: tuple[uuid.UUID, ...]
    model: ModelIdentity
    right: ProcessingRightReference

    def __post_init__(self) -> None:
        if not is_sha256(self.recipe_sha256):
            raise MaterialObjectError("a photo-derived recipe names its recipe by sha256")
        if not isinstance(self.right, ProcessingRightReference):
            raise MaterialObjectError(
                "a photo-derived recipe is never built without the processing right that "
                "allowed the reading"
            )
        if not isinstance(self.model, ModelIdentity):
            raise MaterialObjectError("a photo-derived recipe names the model that read it")
        captures = self.source_capture_ids
        if (
            not isinstance(captures, tuple)
            or not captures
            or not all(isinstance(capture, uuid.UUID) for capture in captures)
            or len(set(captures)) != len(captures)
        ):
            raise MaterialObjectError(
                "a photo-derived recipe names at least one photograph, each once, by capture id"
            )

    def as_document(self) -> dict[str, Any]:
        """The object as canonical JSON would hold it: captures in the order they were read."""
        return {
            "profile": PHOTO_DERIVED_RECIPE_PROFILE,
            "recipe_sha256": self.recipe_sha256,
            "source_capture_ids": [str(capture) for capture in self.source_capture_ids],
            "model": {"id": self.model.model_id, "weights_sha256": self.model.weights_sha256},
            "right": {
                "id": str(self.right.right_id),
                "record_sha256": self.right.record_sha256,
            },
        }
