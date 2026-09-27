"""Reviewed interaction-policy values and immutable lifecycle records."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, TypeAlias

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.world.errors import InvalidInteractionData
from exulanica.world.models import ProposalProvenance

__all__ = [
    "INTERACTION_POLICY_REGISTRY",
    "InteractionPolicyRegistry",
    "InteractionPolicyState",
    "InteractionPolicyValue",
    "InteractionPolicyVersion",
    "InteractionPreview",
    "InteractionProposal",
    "InteractionProposalRecord",
    "InteractionRecommendation",
]

InteractionPolicyValue: TypeAlias = bool | int | str


@dataclass(frozen=True, slots=True)
class InteractionProposal:
    proposal_id: uuid.UUID
    provenance: ProposalProvenance
    capability_patch: Mapping[str, InteractionPolicyValue]
    base_policy_version_id: uuid.UUID | None
    base_structure_snapshot_id: uuid.UUID | None
    base_topology_sha256: str | None
    proposal_input: Mapping[str, Any]
    explanation: str
    reference_ids: tuple[str, ...] = ()
    model_id: str | None = None
    prompt_version: str | None = None
    refines_proposal_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class InteractionPolicyVersion:
    version_id: uuid.UUID
    revision: int
    parent_version_id: uuid.UUID | None
    parameters: Mapping[str, InteractionPolicyValue]
    policy_sha256: str
    applied_from_proposal_id: uuid.UUID | None
    rollback_target_version_id: uuid.UUID | None
    provenance: ProposalProvenance
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class InteractionPolicyState:
    current: InteractionPolicyVersion | None
    parameters: Mapping[str, InteractionPolicyValue]
    base_structure_snapshot_id: uuid.UUID | None
    base_topology_sha256: str | None


@dataclass(frozen=True, slots=True)
class InteractionPreview:
    preview_id: uuid.UUID
    proposal: InteractionProposal
    candidate_parameters: Mapping[str, InteractionPolicyValue]
    candidate_sha256: str
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class InteractionProposalRecord:
    proposal: InteractionProposal
    status: str
    validation_issues: tuple[str, ...]
    created_at: dt.datetime
    updated_at: dt.datetime


@dataclass(frozen=True, slots=True)
class InteractionRecommendation:
    capability_key: str
    proposed_value: InteractionPolicyValue
    accepted_observation_count: int
    rejected_observation_count: int
    explanation: str


@dataclass(frozen=True, slots=True)
class _Capability:
    key: str
    version: int
    category: str
    kind: str
    default: InteractionPolicyValue
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()
    #: Whether the settings page offers a control for it; data, so the page keeps no list.
    shown_in_settings: bool = True
    #: Why a capability the settings page does not offer is not offered; None when it is.
    settings_note: str | None = None


class InteractionPolicyRegistry:
    """Closed reviewed parameter vocabulary shared by Settings and Companion proposals."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        if document.get("schema_version") != 1 or not isinstance(
            document.get("capabilities"), list
        ):
            raise RuntimeError("interaction policy registry schema is invalid")
        capabilities: dict[str, _Capability] = {}
        for raw in document["capabilities"]:
            if not isinstance(raw, Mapping):
                raise RuntimeError("interaction policy capability must be an object")
            key = raw.get("key")
            kind = raw.get("kind")
            category = raw.get("category")
            version = raw.get("version")
            if (
                not isinstance(key, str)
                or key in capabilities
                or kind not in {"integer", "choice", "toggle"}
                or category not in {"comfort", "navigation", "disclosure", "initiative"}
                or isinstance(version, bool)
                or not isinstance(version, int)
                or version < 1
                or not isinstance(raw.get("shown_in_settings"), bool)
                or (raw["shown_in_settings"] == ("settings_note" in raw))
                or ("settings_note" in raw and not str(raw["settings_note"]).strip())
            ):
                raise RuntimeError(f"invalid interaction policy capability: {key!r}")
            capability = _Capability(
                key=key,
                version=version,
                category=category,
                kind=kind,
                default=raw.get("default"),
                minimum=raw.get("minimum"),
                maximum=raw.get("maximum"),
                choices=tuple(raw.get("choices", ())),
                shown_in_settings=raw["shown_in_settings"],
                settings_note=raw.get("settings_note"),
            )
            self._validate_value(capability, capability.default)
            capabilities[key] = capability
        self.capabilities = capabilities
        self.defaults = {key: value.default for key, value in capabilities.items()}
        canonical_json(self.defaults)

    def validate_patch(
        self, patch: Mapping[str, InteractionPolicyValue]
    ) -> dict[str, InteractionPolicyValue]:
        if not patch:
            raise InvalidInteractionData(
                "an interaction proposal must change at least one capability"
            )
        result: dict[str, InteractionPolicyValue] = {}
        for key, value in patch.items():
            capability = self.capabilities.get(key)
            if capability is None:
                raise InvalidInteractionData(f"unknown interaction capability {key}")
            self._validate_value(capability, value)
            result[key] = value
        canonical_json(result)
        return dict(sorted(result.items()))

    def validate_parameters(
        self, parameters: Mapping[str, InteractionPolicyValue]
    ) -> dict[str, InteractionPolicyValue]:
        if set(parameters) != set(self.capabilities):
            missing = sorted(set(self.capabilities) - set(parameters))
            extra = sorted(set(parameters) - set(self.capabilities))
            raise InvalidInteractionData(
                f"interaction policy capability set is not exact; missing={missing}, extra={extra}"
            )
        result = self.validate_patch(parameters)
        return result

    def candidate(
        self,
        current: Mapping[str, InteractionPolicyValue],
        patch: Mapping[str, InteractionPolicyValue],
    ) -> dict[str, InteractionPolicyValue]:
        validated = self.validate_patch(patch)
        candidate = {**self.validate_parameters(current), **validated}
        return dict(sorted(candidate.items()))

    @staticmethod
    def digest(parameters: Mapping[str, InteractionPolicyValue]) -> str:
        return sha256_of_canonical(dict(sorted(parameters.items()))).hex()

    def catalog(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "capabilities": [
                {
                    "key": capability.key,
                    "version": capability.version,
                    "category": capability.category,
                    "kind": capability.kind,
                    "default": capability.default,
                    "minimum": capability.minimum,
                    "maximum": capability.maximum,
                    "choices": list(capability.choices),
                    "shown_in_settings": capability.shown_in_settings,
                    "settings_note": capability.settings_note,
                }
                for capability in self.capabilities.values()
            ],
        }

    @staticmethod
    def _validate_value(capability: _Capability, value: Any) -> None:
        if capability.kind == "toggle":
            valid = isinstance(value, bool)
        elif capability.kind == "integer":
            valid = (
                not isinstance(value, bool)
                and isinstance(value, int)
                and capability.minimum is not None
                and capability.maximum is not None
                and capability.minimum <= value <= capability.maximum
            )
        else:
            valid = isinstance(value, str) and value in capability.choices
        if not valid:
            raise InvalidInteractionData(
                f"invalid value for interaction capability {capability.key}: {value!r}"
            )


def _load_registry() -> InteractionPolicyRegistry:
    path = files("exulanica.world").joinpath("interaction-policy-registry.v1.json")
    return InteractionPolicyRegistry(json.loads(path.read_text(encoding="utf-8")))


INTERACTION_POLICY_REGISTRY = _load_registry()


def default_interaction_state(
    *,
    structure_snapshot_id: uuid.UUID | None = None,
    topology_sha256: str | None = None,
) -> InteractionPolicyState:
    return InteractionPolicyState(
        current=None,
        parameters=INTERACTION_POLICY_REGISTRY.defaults,
        base_structure_snapshot_id=structure_snapshot_id,
        base_topology_sha256=topology_sha256,
    )
