"""Plane-typed compatibility between structural snapshots and composed style authority.

``compatibility_key`` binds a reviewed profile family to a topology family.  It is not a
structure/style identity.  Live composed digests are appearance CAS tokens.  Structural
``source_snapshot_id`` values are authored-write tokens.  Hex equality across those planes
is never the reason for compatibility.  Live typed identities may still agree when hex
strings collide.

Starter refuse uses a stored origin when the caller supplies one (``starter_world`` or the
current snapshot composer key).  Otherwise it uses the stored starter ``world_id`` scheme
``world:authored:``, not a heuristic over arbitrary strings.

``preview_required`` is a CLASSIFY-family result.  ``REGISTER_TOPOLOGY`` does not emit it:
family-matched digest change on a non-starter is the composer handoff.  COMPOSE tokens are
unused: there is no compose write.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from exulanica.world.errors import (
    InvalidStyleData,
    ProtectedTopologyConflict,
    StaleStyleVersion,
    UnknownWorldResource,
)

__all__ = [
    "AuthoredVersionRef",
    "CompatibilityIntent",
    "ComposedTopologyRef",
    "SourceAttachmentRef",
    "StructuralSnapshotRef",
    "StructureStyleCompatibility",
    "StyleStructureFacts",
    "StyleVersionRef",
    "classify_structure_style_compatibility",
    "raise_for_incompatible_structure_style",
]


class CompatibilityIntent(StrEnum):
    CLASSIFY = "classify"
    APPEARANCE_WRITE = "appearance_write"
    REGISTER_TOPOLOGY = "register_topology"
    BOOTSTRAP = "bootstrap"
    ATTACH = "attach"
    COMPOSE = "compose"


@dataclass(frozen=True, slots=True)
class StyleVersionRef:
    """Appearance-plane style version. Never a topology or snapshot digest."""

    version_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ComposedTopologyRef:
    """Appearance-plane composed topology. Never a structural snapshot digest."""

    digest: str


@dataclass(frozen=True, slots=True)
class StructuralSnapshotRef:
    """Spatial-plane snapshot identity. Never a composed topology digest."""

    snapshot_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class SourceAttachmentRef:
    """Project-reference membership. Never a topology source slot."""

    attachment_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class AuthoredVersionRef:
    """Authored-plane version whose writes compare ``source_snapshot_id``."""

    version_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class StructureStyleCompatibility:
    outcome: Literal["compatible", "preview_required", "refuse"]
    token: str
    planes_named: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StyleStructureFacts:
    intent: CompatibilityIntent
    world_id: str
    live_style_version_id: uuid.UUID | None = None
    live_composed_digest: str | None = None
    live_composed_compatibility_key: str | None = None
    named_style_version_id: uuid.UUID | None = None
    named_style_known: bool = True
    named_style_is_current: bool = False
    named_style_bound_digest: str | None = None
    named_style_compatibility_key: str | None = None
    named_composed_digest: str | None = None
    named_snapshot_id: uuid.UUID | None = None
    named_snapshot_known: bool = True
    named_snapshot_topology_sha256: str | None = None
    named_authored_version_id: uuid.UUID | None = None
    named_authored_known: bool = True
    authored_source_snapshot_id: uuid.UUID | None = None
    proposed_digest: str | None = None
    proposed_compatibility_key: str | None = None
    proposed_has_sourced_slots: bool = False
    attachments_named: bool = False
    attachments_known: bool = True
    attachments_expired: bool = False
    conflicting_addresses: bool = False
    starter_world: bool | None = None


def classify_structure_style_compatibility(
    facts: StyleStructureFacts,
) -> StructureStyleCompatibility:
    """Return a plane-typed decision.

    Compatible is never caused by key or digest equality. Live typed identities may
    still agree when hex strings collide.
    """

    planes = _planes_named(facts)
    if facts.conflicting_addresses:
        return _refuse("conflicting_plane_addresses", planes)
    if facts.named_style_version_id is not None and not facts.named_style_known:
        return _refuse("unknown_reference", planes)
    if facts.named_snapshot_id is not None and not facts.named_snapshot_known:
        return _refuse("unknown_reference", planes)
    if facts.named_authored_version_id is not None and not facts.named_authored_known:
        return _refuse("unknown_reference", planes)
    if facts.attachments_named and not facts.attachments_known:
        return _refuse("unknown_reference", planes)

    if facts.intent is CompatibilityIntent.COMPOSE:
        token = (
            "expired_source_not_composable"
            if facts.attachments_expired
            else "attachment_is_not_composition"
        )
        return _refuse(token, planes)
    if facts.attachments_named and facts.intent is not CompatibilityIntent.ATTACH:
        token = (
            "expired_source_not_composable"
            if facts.attachments_expired
            else "attachment_is_not_composition"
        )
        return _refuse(token, planes)

    hex_collision = _hex_collision(facts)
    live_style_ok = (
        facts.named_style_version_id is not None
        and facts.named_style_version_id == facts.live_style_version_id
    )
    live_composed_ok = (
        facts.named_composed_digest is not None
        and facts.named_composed_digest == facts.live_composed_digest
    )
    snapshot_is_authored_source = (
        facts.named_snapshot_id is not None
        and facts.authored_source_snapshot_id is not None
        and facts.named_snapshot_id == facts.authored_source_snapshot_id
    )
    family_match = _family_match(facts)

    if (
        hex_collision
        and facts.intent is CompatibilityIntent.CLASSIFY
        and not (
            live_style_ok
            and live_composed_ok
            and (facts.named_snapshot_id is None or snapshot_is_authored_source)
        )
    ):
        return _refuse("cross_plane_digest_equality", planes)

    if facts.intent is CompatibilityIntent.REGISTER_TOPOLOGY:
        return _classify_register(facts, planes)
    if facts.intent is CompatibilityIntent.APPEARANCE_WRITE:
        return _classify_appearance_write(facts, planes, live_style_ok, live_composed_ok)
    if facts.intent is CompatibilityIntent.BOOTSTRAP:
        return _classify_bootstrap(facts, planes, live_composed_ok)
    if facts.intent is CompatibilityIntent.ATTACH:
        return _result("compatible", "attachment_membership_only", planes)

    if (
        live_style_ok
        and live_composed_ok
        and (facts.named_snapshot_id is None or snapshot_is_authored_source)
    ):
        return _result("compatible", "live_authorities_agree", planes)
    if family_match and (
        facts.named_style_bound_digest != facts.live_composed_digest
        or (
            facts.named_snapshot_topology_sha256 is not None
            and facts.live_composed_digest is not None
            and facts.named_snapshot_topology_sha256 != facts.live_composed_digest
        )
    ):
        return _result("preview_required", "style_topology_drift", planes)
    if family_match:
        return _result("preview_required", "style_topology_drift", planes)
    if facts.named_style_compatibility_key and facts.live_composed_compatibility_key:
        return _refuse("profile_family_incompatible", planes)
    return _refuse("unknown_reference", planes)


def raise_for_incompatible_structure_style(decision: StructureStyleCompatibility) -> None:
    """Raise the existing domain error for a refused classification.

    Preview stays a result. Write paths map ``historical_style_write_base`` to
    ``StaleStyleVersion`` and ``historical_style_topology_apply_base`` to
    ``ProtectedTopologyConflict``.
    """

    if decision.outcome != "refuse":
        return
    if decision.token == "unknown_reference":
        raise UnknownWorldResource("no such world resource")
    if decision.token == "historical_style_write_base":
        raise StaleStyleVersion("historical style is not a write base")
    if decision.token in {
        "historical_style_topology_apply_base",
        "starter_sourced_activation",
        "starter_overlay",
        "profile_family_incompatible",
        "cross_plane_digest_equality",
    }:
        raise ProtectedTopologyConflict(decision.token.replace("_", " "))
    if decision.token in {
        "attachment_is_not_composition",
        "expired_source_not_composable",
        "conflicting_plane_addresses",
        "source_composition_refused",
    }:
        raise InvalidStyleData(decision.token.replace("_", " "))
    raise InvalidStyleData(decision.token.replace("_", " "))


def _classify_register(
    facts: StyleStructureFacts,
    planes: tuple[str, ...],
) -> StructureStyleCompatibility:
    authored_world = _is_starter_world(facts)
    if authored_world and facts.proposed_has_sourced_slots:
        return _refuse("starter_sourced_activation", planes)
    if (
        authored_world
        and facts.live_composed_digest is not None
        and facts.proposed_digest is not None
        and facts.proposed_digest != facts.live_composed_digest
    ):
        return _refuse("starter_overlay", planes)
    if (
        facts.named_style_compatibility_key
        and facts.proposed_compatibility_key
        and facts.named_style_compatibility_key != facts.proposed_compatibility_key
    ):
        return _refuse("profile_family_incompatible", planes)
    return _result("compatible", "register_topology", planes)


def _classify_appearance_write(
    facts: StyleStructureFacts,
    planes: tuple[str, ...],
    live_style_ok: bool,
    live_composed_ok: bool,
) -> StructureStyleCompatibility:
    if facts.named_style_version_id is not None and not live_style_ok:
        return _refuse("historical_style_write_base", planes)
    if facts.named_composed_digest is not None and not live_composed_ok:
        if (
            facts.named_style_bound_digest is not None
            and facts.named_composed_digest == facts.named_style_bound_digest
        ):
            return _refuse("historical_style_topology_apply_base", planes)
        return _refuse("historical_style_topology_apply_base", planes)
    return _result("compatible", "live_authorities_agree", planes)


def _classify_bootstrap(
    facts: StyleStructureFacts,
    planes: tuple[str, ...],
    live_composed_ok: bool,
) -> StructureStyleCompatibility:
    if facts.named_composed_digest is not None and not live_composed_ok:
        return _refuse("historical_style_topology_apply_base", planes)
    if facts.named_snapshot_id is not None:
        return _result("compatible", "bootstrap_reuse", planes)
    return _result("compatible", "bootstrap_initial", planes)


STARTER_WORLD_ID_PREFIX = "world:authored:"


def _is_starter_world(facts: StyleStructureFacts) -> bool:
    """Use a stored origin when supplied; otherwise the stored ``world:authored:`` scheme."""

    if facts.starter_world is not None:
        return facts.starter_world
    return facts.world_id.startswith(STARTER_WORLD_ID_PREFIX)


def _family_match(facts: StyleStructureFacts) -> bool:
    proposed_or_live = facts.proposed_compatibility_key or facts.live_composed_compatibility_key
    return (
        facts.named_style_compatibility_key is not None
        and proposed_or_live is not None
        and facts.named_style_compatibility_key == proposed_or_live
    )


def _hex_collision(facts: StyleStructureFacts) -> bool:
    return (
        facts.named_composed_digest is not None
        and facts.named_snapshot_topology_sha256 is not None
        and facts.named_composed_digest == facts.named_snapshot_topology_sha256
    )


def _planes_named(facts: StyleStructureFacts) -> tuple[str, ...]:
    names: list[str] = []
    if facts.named_style_version_id is not None:
        names.append("style_version")
    if facts.named_composed_digest is not None or facts.proposed_digest is not None:
        names.append("composed_topology")
    if facts.named_snapshot_id is not None:
        names.append("structural_snapshot")
    if facts.named_authored_version_id is not None:
        names.append("authored_version")
    if facts.attachments_named:
        names.append("source_attachment")
    if (
        facts.named_style_compatibility_key
        or facts.live_composed_compatibility_key
        or facts.proposed_compatibility_key
    ):
        names.append("profile_family")
    return tuple(names)


def _result(
    outcome: Literal["compatible", "preview_required", "refuse"],
    token: str,
    planes: tuple[str, ...],
) -> StructureStyleCompatibility:
    return StructureStyleCompatibility(outcome, token, planes)


def _refuse(token: str, planes: tuple[str, ...]) -> StructureStyleCompatibility:
    return StructureStyleCompatibility("refuse", token, planes)
