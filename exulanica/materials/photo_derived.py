"""A recipe a model derived from a person's photographs: data that cannot exist without rights.

This is the object a future inverse model (``ml/``) will emit: a recipe, the model that read the
photographs, where the photographs went to be read, and, for each photograph, the personal model
right that allowed it. It is inert today. Nothing in this repository constructs one from a
photograph, no function here takes pixels or a capture, and ``material_recipe`` refuses a
``photo_derived`` row until the migration after 0073 replaces its two refusal triggers.

**It has the personal model right's shape, as plain data.** A right (migration 0073,
``exulanica.ingest.model_rights``) names one capture, one model and one destination. So this
object names one right per photograph, and the model and the destination every one of those
rights must name. ``exulanica.materials`` may not import ``exulanica.ingest``, so the model is
spelled field for field as ``ModelIdentity.as_record`` spells it, a destination is held to the
spelling migration 0073 checks, and a right is its id and the digest of its receipt.

**One rule is stricter than the right's.** A right refuses a hosted model for photographs kept in
this process. This object also refuses a local model anywhere else: a photo-derived recipe is read
by a checkpoint loaded in this process, so its destination is ``local-process``.

**The rights are references, not checks.** Whether each right is current, names this model and
this destination, and has not been withdrawn is asked at the boundary, by the world service that
writes the recipe, through ``require_model_right``, never here. What this object guarantees is
that it cannot be built without naming a right for every photograph it was read from.

**A checkpoint this project trains cannot be named yet.** A right pins a local checkpoint to a
full 40-character commit, and the weights ``ml/`` trains have no commit. They will be pinned by
content, a revision spelled ``sha256:`` and the 64-character digest of the weights, with the
training receipt as their provenance. That form arrives with the first trained checkpoint, in a
migration and in the personal model right's code together, and not here first.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Final

from exulanica.materials.objects import MaterialObjectError, is_sha256

__all__ = [
    "LOCAL_PROCESS",
    "LOCAL_PROVIDER",
    "PHOTO_DERIVED_RECIPE_PROFILE",
    "ModelReference",
    "PhotoDerivedRecipe",
    "PhotoSource",
]

PHOTO_DERIVED_RECIPE_PROFILE: Final = "exulanica.photo-derived-recipe/v1"
#: The provider a right names for a checkpoint loaded in this process.
LOCAL_PROVIDER: Final = "local"
#: The destination of photographs that never leave this process.
LOCAL_PROCESS: Final = "local-process"

# The spellings migration 0073 checks, each matched whole.
_NAME: Final = re.compile(r"[a-z][a-z0-9_]{0,62}")
_MODEL_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
_REVISION: Final = re.compile(r"[0-9a-f]{40}")
_LABEL: Final = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
_HOSTED: Final = re.compile(rf"https://{_LABEL}(\.{_LABEL})+(:[1-9][0-9]{{0,4}})?")
_LOCALHOST: Final = re.compile(r"https?://localhost(:[1-9][0-9]{0,4})?")
_NUMERIC_HOST: Final = re.compile(r"\.([0-9]+|0x[0-9a-f]*)(:[0-9]+)?\Z")
_DEFAULT_PORT: Final = re.compile(r"https://[^/]*:443|http://[^/]*:80")
_PORT: Final = re.compile(r":([0-9]+)\Z")


def _is_destination(value: object) -> bool:
    """``local-process``, or an origin written the one way migration 0073 accepts it."""
    if type(value) is not str or len(value) > 270:
        return False
    if value == LOCAL_PROCESS:
        return True
    hosted = _HOSTED.fullmatch(value) is not None and _NUMERIC_HOST.search(value) is None
    if not (hosted or _LOCALHOST.fullmatch(value)) or _DEFAULT_PORT.fullmatch(value):
        return False
    port = _PORT.search(value)
    return port is None or 1 <= int(port.group(1)) <= 65535


@dataclass(frozen=True, slots=True)
class ModelReference:
    """The model that read the photographs, as a personal model right names it."""

    provider: str
    role: str
    model_id: str
    revision: str | None

    def __post_init__(self) -> None:
        if type(self.provider) is not str or _NAME.fullmatch(self.provider) is None:
            raise MaterialObjectError("a model's provider is a provider key")
        if type(self.role) is not str or _NAME.fullmatch(self.role) is None:
            raise MaterialObjectError("a model's role is a role name")
        if type(self.model_id) is not str or _MODEL_ID.fullmatch(self.model_id) is None:
            raise MaterialObjectError("a model is named by its identifier")
        if self.revision is not None and (
            type(self.revision) is not str or _REVISION.fullmatch(self.revision) is None
        ):
            raise MaterialObjectError("a model's revision is a full lowercase commit")
        if self.provider == LOCAL_PROVIDER and self.revision is None:
            raise MaterialObjectError("a local checkpoint is pinned to a full commit")

    def as_record(self) -> dict[str, str | None]:
        """The model as ``ModelIdentity.as_record`` spells it."""
        return {
            "provider": self.provider,
            "role": self.role,
            "model_id": self.model_id,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class PhotoSource:
    """One photograph the recipe was read from, and the right that allowed that reading."""

    capture_id: uuid.UUID
    right_id: uuid.UUID
    right_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.capture_id, uuid.UUID):
            raise MaterialObjectError("a photograph is named by its capture id")
        if not isinstance(self.right_id, uuid.UUID):
            raise MaterialObjectError("a personal model right is named by its uuid")
        if not is_sha256(self.right_receipt_sha256):
            raise MaterialObjectError("a personal model right's receipt is named by its sha256")

    def as_record(self) -> dict[str, str]:
        return {
            "capture_id": str(self.capture_id),
            "right_id": str(self.right_id),
            "right_receipt_sha256": self.right_receipt_sha256,
        }


@dataclass(frozen=True, slots=True)
class PhotoDerivedRecipe:
    """A recipe, the model and destination, and one right per photograph. Nothing is optional."""

    recipe_sha256: str
    model: ModelReference
    destination: str
    sources: tuple[PhotoSource, ...]

    def __post_init__(self) -> None:
        if not is_sha256(self.recipe_sha256):
            raise MaterialObjectError("a photo-derived recipe names its recipe by sha256")
        if not isinstance(self.model, ModelReference):
            raise MaterialObjectError("a photo-derived recipe names the model that read it")
        if not _is_destination(self.destination):
            raise MaterialObjectError(
                "a photo-derived recipe names where the photographs went: local-process, or an "
                "origin as a personal model right spells it"
            )
        if (self.destination == LOCAL_PROCESS) != (self.model.provider == LOCAL_PROVIDER):
            raise MaterialObjectError(
                "a local model reads photographs in this process, and only a local model does"
            )
        sources = self.sources
        if (
            not isinstance(sources, tuple)
            or not sources
            or not all(isinstance(source, PhotoSource) for source in sources)
        ):
            raise MaterialObjectError(
                "a photo-derived recipe is never built without a right for each photograph it "
                "was read from"
            )
        if len({source.capture_id for source in sources}) != len(sources):
            raise MaterialObjectError("a photo-derived recipe names each photograph once")
        if len({source.right_id for source in sources}) != len(sources):
            raise MaterialObjectError(
                "a personal model right names one photograph, so no two photographs share one"
            )

    @property
    def source_capture_ids(self) -> tuple[uuid.UUID, ...]:
        """The photographs, in the order they were read."""
        return tuple(source.capture_id for source in self.sources)

    def as_document(self) -> dict[str, Any]:
        """The object as canonical JSON would hold it: photographs in the order they were read."""
        return {
            "profile": PHOTO_DERIVED_RECIPE_PROFILE,
            "recipe_sha256": self.recipe_sha256,
            "model": self.model.as_record(),
            "destination": self.destination,
            "sources": [source.as_record() for source in self.sources],
        }
