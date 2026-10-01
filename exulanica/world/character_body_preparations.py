"""A workspace's prepared character bodies, read through the workspace preparation queue.

A parametric family publishes the bodies it has reviewed (``reviewed:<asset key>``). Any other
recipe over it is fitted per workspace by
:class:`~exulanica.world.character_preparation.CharacterBodyPreparer`, which the one preparation
queue runs (:mod:`exulanica.world.workspace_preparations`, migration 0126). A saved look names such
a body ``preparation:<preparation id>``. This module answers what that name binds to, whether the
body can be drawn now, and what a request for one pins; it never writes the queue's table, whose
requesting, cancelling and delivery are the queue's own.

A preparation pins its recipe as parameters (``family_id``, ``family_sha256``, ``values``,
``seed``) and, as inputs, the publication that served the family (``catalog_sha256``), that
publication's declaration of the family (``family``) and the preparer identity requested against
(``identity_sha256``). Identical requests in one workspace are one preparation, so an expensive
body is fitted once and every later request answers it; a recipe that differs in any value is
another preparation and leaves the others as they are.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.world.character_appearance import (
    AssetPin,
    CharacterFamily,
    CharacterRecipe,
    RepresentationBinding,
    RepresentationNotPrepared,
)
from exulanica.world.character_parametric import PREPARATION_PREFIX, PREPARER_ID, PREPARER_VERSION
from exulanica.world.workspace_preparations import (
    PreparationRecord,
    UnknownPreparation,
    WorkspacePreparationRepository,
)

__all__ = [
    "PREPARATION_VIEW_PROFILE",
    "QueuedCharacterPreparations",
    "is_character_preparation",
    "preparation_id",
    "preparation_view",
    "receipt_sha256",
    "representation_id",
    "requested_inputs",
]

PREPARATION_VIEW_PROFILE: Final = "exulanica.character-preparation/v1"


def preparation_id(representation_id: str) -> uuid.UUID | None:
    """The preparation a body name refers to, or None when it names no preparation."""
    if not representation_id.startswith(PREPARATION_PREFIX):
        return None
    try:
        return uuid.UUID(representation_id.removeprefix(PREPARATION_PREFIX))
    except ValueError:
        return None


def representation_id(preparation: uuid.UUID) -> str:
    return f"{PREPARATION_PREFIX}{preparation}"


def is_character_preparation(record: PreparationRecord) -> bool:
    """A body this plane's preparer made from a recipe, never another plane's preparation."""
    return record.input_kind == "character_recipe" and (
        record.preparer_id,
        record.preparer_version,
    ) == (PREPARER_ID, PREPARER_VERSION)


def receipt_sha256(record: PreparationRecord) -> str | None:
    """The digest of the preparation's receipt: the canonical bytes the queue recorded."""
    if record.receipt is None:
        return None
    return hashlib.sha256(canonical_json(record.receipt)).hexdigest()


class QueuedCharacterPreparations:
    """The prepared bodies of one workspace, as a saved look binds and reads them."""

    def __init__(self, queue: WorkspacePreparationRepository) -> None:
        self.queue = queue

    def record(self, representation: str) -> PreparationRecord | None:
        """The character preparation a body name refers to in this workspace, else None."""
        found = preparation_id(representation)
        if found is None:
            return None
        try:
            record = self.queue.preparation(found)
        except UnknownPreparation:
            return None
        return record if is_character_preparation(record) else None

    def binding(self, family: CharacterFamily, representation: str) -> RepresentationBinding | None:
        """The prepared body a recipe over ``family`` may name, bound to exactly its inputs.

        None when the name refers to no preparation of this workspace over this family; a
        preparation that is requested or running is not a body yet, and says so.
        """
        record = self.record(representation)
        if record is None:
            return None
        parameters = record.parameters
        if (parameters.get("family_id"), parameters.get("family_sha256")) != (
            family.family_id,
            family.sha256,
        ):
            return None
        digest = receipt_sha256(record)
        if record.state != "prepared" or record.output_sha256 is None or digest is None:
            raise RepresentationNotPrepared(f"{representation} is {record.state}, not prepared")
        recipe = CharacterRecipe(
            family_id=family.family_id,
            family_sha256=family.sha256,
            parameters=parameters["values"],
            seed=parameters["seed"],
        )
        assert record.output_byte_size is not None
        return RepresentationBinding(
            binding_id=representation,
            recipe_input_sha256=recipe.input_sha256,
            asset=AssetPin(
                asset_key=representation,
                content_sha256=record.output_sha256,
                receipt_sha256=digest,
                byte_size=record.output_byte_size,
            ),
            rig_id=family.rig_id,
            rig_revision=family.rig_revision,
            rig_sha256=family.rig_sha256,
            producer=record.preparer_id,
            producer_revision=str(record.preparer_version),
            preparation_receipt_sha256=digest,
        )

    def render_status(self, binding: RepresentationBinding) -> str:
        """Whether a saved look's prepared body can be drawn now, and if not, why."""
        record = self.record(binding.binding_id)
        if (
            record is None
            or self.queue.blocked(record.preparation_id)
            or record.state != "prepared"
            or record.output_sha256 != binding.asset.content_sha256
        ):
            return "preparation_unavailable"
        if receipt_sha256(record) != binding.preparation_receipt_sha256:
            return "asset_integrity_unavailable"
        # The bytes themselves, read and hash-checked, as a reviewed body's are.
        store = self.queue.stores.for_workspace(self.queue.workspace_id)
        try:
            data = store.get(BlobId.from_hex(binding.asset.content_sha256))
        except BlobNotFoundError:
            return "asset_bytes_unavailable"
        except IntegrityError:
            return "asset_integrity_unavailable"
        return (
            "available" if len(data) == binding.asset.byte_size else "asset_integrity_unavailable"
        )


def preparation_view(record: PreparationRecord, *, output_present: bool | None) -> dict[str, Any]:
    """A character preparation as the character routes answer it.

    ``representation_id`` is what a saved look names once the body is prepared; ``descriptor`` is
    the integer render descriptor the preparer measured, as its receipt states it.
    """
    receipt: Mapping[str, Any] = record.receipt or {}
    failure = (
        None
        if record.failure_class is None
        else {
            "class": record.failure_class,
            "code": record.failure_code,
            "message": record.failure_message,
        }
    )
    return {
        "profile": PREPARATION_VIEW_PROFILE,
        "preparation_id": str(record.preparation_id),
        "state": record.state,
        "representation_id": representation_id(record.preparation_id)
        if record.state == "prepared"
        else None,
        "family_id": record.parameters.get("family_id"),
        "family_sha256": record.parameters.get("family_sha256"),
        "values": record.parameters.get("values"),
        "catalog_sha256": record.inputs.get("catalog_sha256"),
        "attempts": record.attempts,
        "requested_at": record.requested_at.isoformat(),
        "prepared_at": None if record.prepared_at is None else record.prepared_at.isoformat(),
        "output": None
        if record.output_sha256 is None
        else {
            "sha256": record.output_sha256,
            "byte_size": record.output_byte_size,
            "present": output_present,
        },
        "descriptor": receipt.get("descriptor"),
        "failure": failure,
    }


def requested_inputs(
    catalog_sha256: str, identity_sha256: str, family_document: Mapping[str, Any]
) -> dict[str, Any]:
    """The inputs a request pins: the serving publication, its family and the preparer identity."""
    return {
        "catalog_sha256": catalog_sha256,
        "family": dict(family_document),
        "identity_sha256": identity_sha256,
    }
