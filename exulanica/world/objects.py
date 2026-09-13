"""The authored delta: what an alternate world version stores, and what makes it a digest.

This module is pure. It holds no connection and issues no SQL, for the same reason
:mod:`exulanica.world.structure` does not: the canonical document and the validation that guards
it are the half an independent verifier has to be able to reproduce, and a function that needs a
database is a function a verifier cannot run.

The one rule worth stating twice is the fixed point. Every coordinate here is an integer in
millimetres, microradians or thousandths, exactly as ``world/placement.json`` stores them.
:func:`exulanica.canonical.canonical_json` refuses IEEE-754 outright, so a float would not produce
a wrong digest, it would produce no digest at all. That is the intended failure: the state token
this plane compares and swaps on has to be bytes another implementation can rebuild.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.world.errors import InvalidObjectData

if TYPE_CHECKING:
    from exulanica.world.environment_instances import EnvironmentInstance

__all__ = [
    "MAX_SCALE_MILLI",
    "MAX_YAW_MICRORADIANS",
    "OBJECT_ID_PATTERN",
    "AlternateVersion",
    "AuthoredObject",
    "ElementOverride",
    "ObjectBehaviour",
    "ObjectOrigin",
    "Transform",
    "VersionEdit",
    "canonical_delta_document",
    "delta_sha256",
    "object_document",
    "override_document",
    "validate_behaviour",
]

#: One full turn. Yaw is stored as a non-negative integer below 2*pi so that one orientation has
#: exactly one representation; without the normalisation two equal worlds would digest differently.
MAX_YAW_MICRORADIANS: Final = 6_283_185
#: A thousand is unscaled. The ceiling is a thousand times life size, which is far past anything a
#: person would place and still small enough that the product of scale and travel cannot overflow.
MAX_SCALE_MILLI: Final = 1_000_000
_MAX_TRANSLATION_MM: Final = 1_000_000_000

_OBJECT_ID_MAX: Final = 200
_ORIGIN_ROLES: Final = frozenset({"fictional", "personal"})

#: The object id contract, and the ONLY statement of it.
#:
#: Migration 0042 carries this exact pattern as a CHECK constraint, and
#: ``test_the_object_id_contract_is_the_same_in_python_and_in_the_schema`` compares the two
#: strings. They were briefly different: Python accepted any 1-to-200-character string while the
#: schema required lowercase and at least two characters, so a caller sending "a" or
#: "Object:Lantern" got a CheckViolation escaping as a 500 rather than the 422 this surface
#: promises. A regex in two places is a regex that disagrees with itself eventually; the fix is
#: that the schema quotes this one and a test holds them together.
OBJECT_ID_PATTERN: Final = "^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$"
_OBJECT_ID: Final = re.compile(OBJECT_ID_PATTERN)


@dataclass(frozen=True, slots=True)
class Transform:
    """A pose in region-local fixed point.

    Region-local rather than world-local is a decision, not a convenience. The renderer composes
    this with the region's own placement, so a later placement migration that moves a region does
    not silently move every object a person put inside it.
    """

    x_mm: int
    y_mm: int
    z_mm: int
    yaw_microradians: int
    scale_milli: int

    def document(self) -> dict[str, Any]:
        return {
            "coordinate_space": "region_local",
            "coordinate_unit": "millimetre",
            "scale_milli": self.scale_milli,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "yaw_microradians": self.yaw_microradians,
            "z_mm": self.z_mm,
        }


@dataclass(frozen=True, slots=True)
class ObjectOrigin:
    """Where an object came from, as the person said rather than as anything inferred."""

    kind: str
    role: str

    def document(self) -> dict[str, Any]:
        return {"kind": self.kind, "role": self.role}


@dataclass(frozen=True, slots=True)
class ObjectBehaviour:
    behaviour_key: str
    behaviour_version: int
    parameters: Mapping[str, Any]

    def document(self) -> dict[str, Any]:
        return {
            "behaviour_key": self.behaviour_key,
            "behaviour_version": self.behaviour_version,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class AuthoredObject:
    object_id: str
    asset_sha256: str
    region_id: str
    transform: Transform
    origin: ObjectOrigin
    behaviour: ObjectBehaviour | None = None
    removed: bool = False


@dataclass(frozen=True, slots=True)
class ElementOverride:
    """A suppression or a replacement transform for one element of the source snapshot."""

    element_id: str
    suppressed: bool
    transform: Transform | None = None


@dataclass(frozen=True, slots=True)
class VersionEdit:
    edit_id: uuid.UUID
    edit_seq: int
    kind: str
    object_id: str | None
    element_id: str | None
    environment_instance_id: str | None
    undone_edit_id: uuid.UUID | None
    base_state_sha256: str
    result_state_sha256: str
    actor: uuid.UUID
    recorded_at: str


@dataclass(frozen=True, slots=True)
class AlternateVersion:
    version_id: uuid.UUID
    world_id: str
    source_snapshot_id: uuid.UUID
    parent_version_id: uuid.UUID | None
    title: str
    style_version_id: uuid.UUID | None
    state_sha256: str
    edit_seq: int
    source_invalidated: bool
    created_by: uuid.UUID
    created_at: str
    objects: tuple[AuthoredObject, ...] = ()
    element_overrides: tuple[ElementOverride, ...] = ()
    environment_instances: tuple[EnvironmentInstance, ...] = ()
    edits: tuple[VersionEdit, ...] = ()


def object_document(obj: AuthoredObject) -> dict[str, Any]:
    """The canonical document for one authored object.

    This is what an edit stores as its ``before`` and ``after``, so undo restores a document
    rather than replaying an intention.
    """
    return {
        "asset_sha256": obj.asset_sha256,
        "behaviour": None if obj.behaviour is None else obj.behaviour.document(),
        "object_id": obj.object_id,
        "origin": obj.origin.document(),
        "region_id": obj.region_id,
        "removed": obj.removed,
        "transform": obj.transform.document(),
    }


def override_document(override: ElementOverride) -> dict[str, Any]:
    return {
        "element_id": override.element_id,
        "suppressed": override.suppressed,
        "transform": None if override.transform is None else override.transform.document(),
    }


def canonical_delta_document(
    objects: Sequence[AuthoredObject],
    overrides: Sequence[ElementOverride],
    environment_instances: Sequence[EnvironmentInstance] = (),
) -> dict[str, Any]:
    """The whole delta, in the one order its digest is defined over.

    Sorting here rather than trusting the caller is the point. The state digest is the concurrency
    token, and a token that depended on the order rows came back in would make two identical
    worlds disagree the first time a query plan changed.
    """
    document = {
        "schema_version": 1,
        "element_overrides": [
            override_document(o) for o in sorted(overrides, key=lambda o: o.element_id)
        ],
        "objects": [object_document(o) for o in sorted(objects, key=lambda o: o.object_id)],
    }
    if environment_instances:
        from exulanica.world.environment_instances import environment_instance_document

        document["schema_version"] = 2
        document["environment_instances"] = [
            environment_instance_document(instance)
            for instance in sorted(environment_instances, key=lambda value: value.instance_id)
        ]
    return document


def delta_sha256(
    objects: Sequence[AuthoredObject],
    overrides: Sequence[ElementOverride],
    environment_instances: Sequence[EnvironmentInstance] = (),
) -> str:
    """The state token: SHA-256 over the canonical delta, hex."""
    document = canonical_delta_document(objects, overrides, environment_instances)
    # Round-trips through canonical_json first so a value the digest could not represent raises
    # here, where the message names this plane, rather than inside the hashing helper.
    canonical_json(document)
    return sha256_of_canonical(document).hex()


def validate_object_id(object_id: str) -> str:
    if not isinstance(object_id, str) or not 1 <= len(object_id) <= _OBJECT_ID_MAX:
        raise InvalidObjectData(f"object_id must be 1 to {_OBJECT_ID_MAX} characters")
    # fullmatch, not match. Python's ``$`` also matches immediately before a trailing newline
    # and PostgreSQL's POSIX ``$`` does not, so "object:lantern\n" passed here and then violated
    # the identical CHECK, which is a 500 where this surface promises a 422. fullmatch is what
    # makes one literal mean the same thing in both languages.
    if not _OBJECT_ID.fullmatch(object_id):
        raise InvalidObjectData(
            "object_id must be lowercase letters, digits, colon, dot, underscore or hyphen, "
            "starting and ending with a letter or digit"
        )
    return object_id


def validate_transform(value: Any) -> Transform:
    """Refuse anything the digest cannot represent, and say which field it was."""
    if not isinstance(value, Transform):
        raise InvalidObjectData("transform is required")
    fields = {
        "x_mm": value.x_mm,
        "y_mm": value.y_mm,
        "z_mm": value.z_mm,
        "yaw_microradians": value.yaw_microradians,
        "scale_milli": value.scale_milli,
    }
    for name, number in fields.items():
        # bool is an int in Python and would sail through a bare isinstance check, then digest as
        # `true` rather than `1`. Excluded explicitly.
        if isinstance(number, bool) or not isinstance(number, int):
            raise InvalidObjectData(f"transform.{name} must be a fixed-point integer")
    for name in ("x_mm", "y_mm", "z_mm"):
        if abs(fields[name]) > _MAX_TRANSLATION_MM:
            raise InvalidObjectData(f"transform.{name} is outside the representable world")
    if not 0 <= value.yaw_microradians <= MAX_YAW_MICRORADIANS:
        raise InvalidObjectData(
            f"transform.yaw_microradians must be between 0 and {MAX_YAW_MICRORADIANS}"
        )
    if not 1 <= value.scale_milli <= MAX_SCALE_MILLI:
        raise InvalidObjectData(f"transform.scale_milli must be between 1 and {MAX_SCALE_MILLI}")
    return value


def validate_origin(origin: Any) -> ObjectOrigin:
    if not isinstance(origin, ObjectOrigin):
        raise InvalidObjectData("origin is required")
    if origin.kind != "authored":
        raise InvalidObjectData("origin.kind must be authored")
    if origin.role not in _ORIGIN_ROLES:
        # Named rather than guessed: product direction is explicit that the person chooses the
        # role and that the first slice does not ship a reality classifier.
        raise InvalidObjectData("origin.role must be fictional or personal, chosen by the person")
    return origin


def validate_behaviour(
    behaviour: ObjectBehaviour | None, registry: Mapping[tuple[str, int], Mapping[str, Any]]
) -> ObjectBehaviour | None:
    """Check a behaviour against the reviewed registry, or accept its absence.

    Fails closed on every axis the registry can be asked about: unknown key, unknown version,
    unknown parameter, missing parameter, wrong kind, out of range, unlisted choice. An
    unsupported behaviour has to fail visibly, which the first milestone names as its own
    acceptance evidence.
    """
    if behaviour is None:
        return None
    descriptor = registry.get((behaviour.behaviour_key, behaviour.behaviour_version))
    if descriptor is None:
        raise InvalidObjectData(
            f"behaviour {behaviour.behaviour_key}@{behaviour.behaviour_version} is not reviewed"
        )
    supplied = behaviour.parameters
    if not isinstance(supplied, Mapping):
        raise InvalidObjectData("behaviour.parameters must be an object")
    unknown = sorted(set(supplied) - set(descriptor))
    if unknown:
        raise InvalidObjectData(f"unknown behaviour parameter {unknown[0]}")
    missing = sorted(set(descriptor) - set(supplied))
    if missing:
        raise InvalidObjectData(f"behaviour parameter {missing[0]} is required")
    for key in sorted(descriptor):
        _validate_parameter(key, supplied[key], descriptor[key])
    return behaviour


def _validate_parameter(key: str, value: Any, bound: Mapping[str, Any]) -> None:
    kind = bound["kind"]
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidObjectData(f"behaviour parameter {key} must be an integer")
        if not bound["minimum"] <= value <= bound["maximum"]:
            raise InvalidObjectData(
                f"behaviour parameter {key} must be between "
                f"{bound['minimum']} and {bound['maximum']}"
            )
    elif kind == "choice":
        if value not in bound["choices"]:
            raise InvalidObjectData(
                f"behaviour parameter {key} must be one of {', '.join(bound['choices'])}"
            )
    elif kind == "toggle":
        if not isinstance(value, bool):
            raise InvalidObjectData(f"behaviour parameter {key} must be true or false")
    else:  # pragma: no cover - only a migration can seed a kind, and none seeds another
        # NOT guarded by a constraint. world_object_behaviour_registry checks only that
        # `parameters` is a JSON object; unlike 0021, it does not constrain each descriptor's
        # shape. Reaching this branch would mean a migration seeded a kind this validator does
        # not know, so it fails closed rather than treating the parameter as unbounded.
        raise InvalidObjectData(f"behaviour parameter {key} has an unreviewed kind")


def validate_object(
    obj: AuthoredObject,
    *,
    region_ids: frozenset[str],
    asset_digests: frozenset[str],
    registry: Mapping[tuple[str, int], Mapping[str, Any]],
) -> AuthoredObject:
    """Everything about one object that can be checked without writing it."""
    validate_object_id(obj.object_id)
    if obj.removed:
        # A removal is a stored edit against an object that exists, not a state to arrive in.
        # An object created already removed could never be moved, removed, or added again.
        raise InvalidObjectData("an object cannot be created already removed")
    if obj.asset_sha256 not in asset_digests:
        raise InvalidObjectData(f"{obj.asset_sha256} is not a reviewed asset")
    if obj.region_id not in region_ids:
        raise InvalidObjectData(f"{obj.region_id} is not a region of the source snapshot")
    return replace(
        obj,
        transform=validate_transform(obj.transform),
        origin=validate_origin(obj.origin),
        behaviour=validate_behaviour(obj.behaviour, registry),
    )
