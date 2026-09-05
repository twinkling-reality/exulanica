"""Immutable values crossing the adaptive-world domain boundary."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeAlias

__all__ = [
    "DEFAULT_WORLD_ID",
    "ProposalOrigin",
    "ProposalProvenance",
    "SourceMediaState",
    "StyleParameterValue",
    "StylePreview",
    "StyleProposal",
    "StyleProposalRecord",
    "StyleReference",
    "StyleScope",
    "StyleVersion",
    "TopologyContract",
    "TopologySourceSlot",
    "WorldSourceMedia",
]

DEFAULT_WORLD_ID = "atlas:default"

StyleParameterValue: TypeAlias = bool | int | float | str


class ProposalOrigin(StrEnum):
    USER = "user"
    SETTINGS = "settings"
    COMPANION = "companion"


class SourceMediaState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE_ASSET = "unavailable_asset"
    MISSING_EVIDENCE = "missing_evidence"


@dataclass(frozen=True, slots=True)
class ProposalProvenance:
    origin: ProposalOrigin
    actor: uuid.UUID
    origin_reference: str | None = None


@dataclass(frozen=True, slots=True)
class StyleReference:
    profile_id: str
    profile_version: int
    parameters: Mapping[str, StyleParameterValue]


@dataclass(frozen=True, slots=True)
class StyleScope:
    kind: str
    region_id: str | None = None


@dataclass(frozen=True, slots=True)
class StyleProposal:
    proposal_id: uuid.UUID
    provenance: ProposalProvenance
    scope: StyleScope
    base_style_version_id: uuid.UUID
    base_topology_digest: str
    profile: StyleReference
    reference_ids: tuple[str, ...] = ()
    model_id: str | None = None
    prompt_version: str | None = None
    refines_proposal_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class StyleProposalRecord:
    proposal: StyleProposal
    recipe_binding: Mapping[str, object]
    capability_mapping: Mapping[str, str]
    status: str
    validation_issues: tuple[str, ...]
    created_at: dt.datetime
    updated_at: dt.datetime


@dataclass(frozen=True, slots=True)
class StyleVersion:
    version_id: uuid.UUID
    revision: int
    parent_version_id: uuid.UUID | None
    topology_digest: str
    global_style: StyleReference
    region_styles: Mapping[str, StyleReference]
    applied_from_proposal_id: uuid.UUID | None
    rollback_target_version_id: uuid.UUID | None
    provenance: ProposalProvenance | None
    created_at: dt.datetime
    warnings: tuple[str, ...] = ()
    recipe_binding: Mapping[str, object] = field(default_factory=dict)
    capability_mapping: Mapping[str, str] = field(default_factory=dict)
    reference_ids: tuple[str, ...] = ()
    model_id: str | None = None
    prompt_version: str | None = None
    refines_proposal_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class StylePreview:
    preview_id: uuid.UUID
    proposal: StyleProposal
    candidate: StyleVersion
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class TopologySourceSlot:
    source_id: uuid.UUID
    slot_key: str
    region_id: str | None
    evidence_span_id: uuid.UUID | None
    missing_reason: str | None


@dataclass(frozen=True, slots=True)
class TopologyContract:
    topology_digest: str
    region_ids: tuple[str, ...]
    source_slots: tuple[TopologySourceSlot, ...] = ()
    compatibility_key: str = "atlas-topology-v1"
    world_id: str = DEFAULT_WORLD_ID


@dataclass(frozen=True, slots=True)
class WorldSourceMedia:
    source_id: uuid.UUID
    slot_key: str
    region_id: str | None
    state: SourceMediaState
    reason: str | None
    evidence_span_id: uuid.UUID | None
    evidence_path: str | None
    modality: str | None
    media_type: str | None
    byte_size: int | None
    width: int | None
    height: int | None
    captured_at: dt.datetime | None
    captured_at_uncertainty_ms: int | None
    capture_ids: tuple[uuid.UUID, ...] = ()
