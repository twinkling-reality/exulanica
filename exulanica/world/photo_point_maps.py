"""Pure authored-world contracts for a depth estimate placed from a reviewed photograph.

**What a placement of this kind is.** One photograph the account holder took, reviewed by a named
human, processed by a depth model under a right that person granted, and put somewhere in their own
world by them. The stored instance is an authored placement of a MODEL INFERENCE: content truth
class ``authored_version`` from an ``authorized_memory`` source. It is not evidence that anybody
was anywhere, it carries no spatial authority (nothing here joins navigation or collision), and it
is never an observation of a surface the camera did not see.

**Three things this module refuses to let an interface forget**, because each of them is a sentence
somebody could otherwise read off the screen and believe:

*Scale.* The depth model declares whether its output is metric. Nothing in this system validates
that flag against a measurement, and no island is metric, so the binding's ``declared_metric``
is named for what it is: a declaration. :func:`scale_statement` is the only sentence this module
will produce about size, and it says approximate.

*Coverage.* A point map holds what one camera saw. Nothing here fills, completes or smooths the
rest, and :func:`coverage_statement` says so rather than leaving an empty region to be read as an
empty room.

*Permission.* The placement pins the authority, the screening and the depth right by receipt
digest. Availability is computed at read time from those, never stored, and never folded into the
state digest: whether a person may see it changes without anybody editing their world, and a
concurrency token that moved when a right expired would refuse unrelated edits.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Final, Literal

from exulanica.world.errors import InvalidObjectData
from exulanica.world.objects import ObjectOrigin, Transform, validate_origin, validate_transform

POINT_MAP_INSTANCE_ID_PATTERN: Final = "^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$"
_INSTANCE_ID = re.compile(POINT_MAP_INSTANCE_ID_PATTERN)

#: The manifest role whose right permits a depth estimate.
#:
#: Written out here rather than imported. ``exulanica.ingest`` and ``exulanica.world`` are sibling
#: layers and neither imports the other, so the alternative to a second spelling is a world module
#: reaching into the pipeline for a string. ``tests/test_photo_point_map_composition.py`` asserts
#: this equals ``exulanica.ingest.stages.segmentation.DEPTH_ROLE``, which is what stops two
#: spellings from becoming two meanings: a rename on either side fails there rather than silently
#: making every resolution answer "no current permission".
DEPTH_ROLE: Final = "depth"

#: The only container this kind places. A renderer that cannot decode it draws nothing rather than
#: guessing at an older layout.
POINT_MAP_CONTAINER: Final = "opm/2"

#: The rung a placeable estimate earned: enough of the frame was recovered to be worth standing in
#: front of. A rung 4 photograph produced a map and not a place, and composing one would put a
#: handful of points in somebody's world and call it their kitchen.
PLACEABLE_RUNG: Final = 3

#: Why an instance cannot be drawn right now. Computed at read time, never stored.
#:
#: ``withdrawn`` covers every end of permission and carries which one in
#: :attr:`PointMapInstance.unavailable_reason`, because the recoveries differ: a stopped right is
#: recovered by reviewing and allowing again, an expired review by reviewing again, and a deleted
#: photograph is not recovered at all.
PointMapAvailability = Literal[
    "available", "unavailable_bytes", "withdrawn", "detached", "binding_drift", "unknown"
]

#: The stable reasons behind ``withdrawn``. A client branches on these and never on a sentence.
WITHDRAWN_REASONS: Final = frozenset(
    {"model_right_withdrawn", "review_expired", "source_deleted", "person_withdrawn"}
)


@dataclass(frozen=True, slots=True)
class PointMapModel:
    """The checkpoint that produced the estimate, as the right that permitted it names it."""

    provider: str
    role: str
    identifier: str
    revision: str | None
    destination: str

    @property
    def ref(self) -> str:
        return self.identifier if self.revision is None else f"{self.identifier}@{self.revision}"

    def document(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "identifier": self.identifier,
            "provider": self.provider,
            "revision": self.revision,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class PointMapSourceBinding:
    """Everything a reader needs to say what is drawn and what permitted it, from the row alone."""

    entry_id: uuid.UUID
    attachment_id: uuid.UUID
    capture_id: uuid.UUID
    source_sha256: str
    authorization_id: uuid.UUID
    authorization_evidence_sha256: str
    screening_id: uuid.UUID
    screening_receipt_sha256: str
    right_id: uuid.UUID
    right_receipt_sha256: str
    model: PointMapModel
    artifact_id: uuid.UUID
    point_map_sha256: str
    byte_size: int
    container: str
    stage_version: int
    rung: int
    declared_metric: bool
    declared_fov_y_microdegrees: int

    def document(self) -> dict[str, Any]:
        return {
            "artifact": {
                "artifact_id": str(self.artifact_id),
                "byte_size": self.byte_size,
                "container": self.container,
                "content_sha256": self.point_map_sha256,
                "declared_fov_y_microdegrees": self.declared_fov_y_microdegrees,
                "declared_metric": self.declared_metric,
                "rung": self.rung,
                "stage_version": self.stage_version,
            },
            "attachment": {
                "attachment_id": str(self.attachment_id),
                "entry_id": str(self.entry_id),
            },
            "authorization": {
                "authorization_id": str(self.authorization_id),
                "evidence_sha256": self.authorization_evidence_sha256,
            },
            "capture_id": str(self.capture_id),
            "model": self.model.document(),
            "right": {
                "receipt_sha256": self.right_receipt_sha256,
                "right_id": str(self.right_id),
            },
            "screening": {
                "receipt_sha256": self.screening_receipt_sha256,
                "screening_id": str(self.screening_id),
            },
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True, slots=True)
class PointMapInstance:
    instance_id: str
    source: PointMapSourceBinding
    region_id: str
    transform: Transform
    origin: ObjectOrigin
    removed: bool = False
    availability: PointMapAvailability = "unknown"
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PointMapPlacement:
    """What the person asked for: a membership, a place to put it, and what to call it."""

    instance_id: str
    entry_id: uuid.UUID
    attachment_id: uuid.UUID
    region_id: str
    transform: Transform
    origin: ObjectOrigin


def point_map_instance_document(instance: PointMapInstance) -> dict[str, Any]:
    """Canonical state. Availability is left out: it changes without anybody editing the world."""
    return {
        "instance_id": instance.instance_id,
        "origin": instance.origin.document(),
        "region_id": instance.region_id,
        "removed": instance.removed,
        "source": instance.source.document(),
        "transform": instance.transform.document(),
    }


def validate_point_map_instance(
    instance: PointMapInstance, *, region_ids: frozenset[str]
) -> PointMapInstance:
    if not _INSTANCE_ID.fullmatch(instance.instance_id):
        raise InvalidObjectData("point map instance_id has an invalid shape")
    if instance.region_id not in region_ids:
        raise InvalidObjectData(f"{instance.region_id} is not a region of the source snapshot")
    validate_transform(instance.transform)
    validate_origin(instance.origin)
    if instance.origin.role != "personal":
        raise InvalidObjectData(
            "an estimate from the account holder's own photograph is placed as personal, "
            "never as fictional"
        )
    source = instance.source
    if source.container != POINT_MAP_CONTAINER:
        raise InvalidObjectData(f"a placed point map is {POINT_MAP_CONTAINER}")
    if source.rung != PLACEABLE_RUNG:
        raise InvalidObjectData(
            "only a point map that recovered enough of its frame to stand in front of is placed"
        )
    if not 1 <= source.declared_fov_y_microdegrees <= 180_000_000:
        raise InvalidObjectData("the declared field of view is not a possible camera")
    return instance


def scale_statement(instance: PointMapInstance) -> str:
    """The only sentence this system makes about the size of a placed estimate.

    It says approximate whatever the model declared, because nothing validates that flag and no
    island is metric. The scale is stated as a multiple of the model's own estimate rather than in
    millimetres, which would read as a measurement of the room.
    """
    multiple = instance.transform.scale_milli / 1000
    shown = f"{multiple:.3f}".rstrip("0").rstrip(".") or "0"
    return (
        f"Approximate size from one photograph; not measured. Shown at {shown}x the model's own "
        "estimate."
    )


def coverage_statement() -> str:
    """What a point map holds, said before somebody reads an empty region as an empty room."""
    return (
        "This shows only the surfaces that one camera saw. Nothing behind or beside them was "
        "filled in."
    )


def truth_statement() -> str:
    """The one line an inspector leads with. Four clauses, none of them removable."""
    return (
        "Model estimate from one photograph, not measured, shows only what the camera saw, "
        "placed here by you."
    )
