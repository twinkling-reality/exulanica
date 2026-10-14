"""Durable personal-world state: protected topology, reviewed styles, immutable versions,
and source availability.

Repositories own the PostgreSQL transactions. Document modules
(:mod:`exulanica.world.objects`, :mod:`exulanica.world.structure`,
:mod:`exulanica.world.environment_instances`, :mod:`exulanica.world.interaction`)
are pure: an independent verifier can reproduce their documents without a database.

This package's public exports are the style, object, structure, environment-instance,
interaction, composition-preview, saved-entry, and shared society-core types. Scene tiles,
character appearance, companion memory, and society stepping live in sibling modules and are
imported by name, not through this package.

The exports are named once, in the imports under ``TYPE_CHECKING`` below, which type checkers and
the import contracts read. At run time each name is imported from its module on first use, so a
module of this package (a pure document module, a society engine) loads only what it imports
itself, never the repositories and the database driver beside it.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from exulanica.world.assets import (
        CC0_LICENCE_ID,
        CC0_LICENCE_TEXT,
        GLB_MEDIA_TYPE,
        ReviewedAsset,
        reviewed_assets,
        seed_reviewed_assets,
    )
    from exulanica.world.authored_delta import (
        AlternateVersion,
        canonical_delta_document,
        delta_sha256,
    )
    from exulanica.world.composition_preview import (
        CompositionBlocked,
        CompositionPlacement,
        CompositionPreview,
        CompositionRequest,
        EnvironmentAdmissionSource,
        PhotoPointMapSource,
        ReviewedAssetSource,
        SourceAttachmentSource,
        WorkspaceAssetSource,
        apply_composition,
        preview_composition,
    )
    from exulanica.world.environment_instances import (
        ENVIRONMENT_INSTANCE_ID_PATTERN,
        EnvironmentInstance,
        EnvironmentPlacement,
        EnvironmentSelection,
        EnvironmentSourceBinding,
        SourceAnchor,
        environment_instance_document,
        validate_environment_instance,
    )
    from exulanica.world.errors import (
        EnvironmentBindingDrift,
        EnvironmentCompositionDenied,
        EnvironmentSourceWithdrawn,
        ExpiredPreview,
        InvalidatedSourceVersion,
        InvalidEnvironmentData,
        InvalidEnvironmentState,
        InvalidInteractionData,
        InvalidInteractionPreviewState,
        InvalidObjectData,
        InvalidObjectState,
        InvalidPreviewState,
        InvalidStructuralData,
        InvalidStructuralPreviewState,
        InvalidStyleData,
        ProtectedTopologyConflict,
        StaleInteractionPolicy,
        StaleObjectBase,
        StaleStructuralBase,
        StaleStyleVersion,
        StyleWriteBusy,
        UnavailableAsset,
        UnknownWorldResource,
        WorldNotConfigured,
    )
    from exulanica.world.interaction import (
        INTERACTION_POLICY_REGISTRY,
        InteractionPolicyRegistry,
        InteractionPolicyState,
        InteractionPolicyVersion,
        InteractionPreview,
        InteractionProposal,
        InteractionProposalRecord,
        InteractionRecommendation,
    )
    from exulanica.world.interaction_repository import WorldInteractionPolicyRepository
    from exulanica.world.models import (
        ProposalOrigin,
        ProposalProvenance,
        SourceMediaState,
        StylePackBinding,
        StylePreview,
        StyleProposal,
        StyleProposalRecord,
        StyleReference,
        StyleScope,
        StyleVersion,
        TopologyContract,
        TopologySourceSlot,
        WorldSourceMedia,
    )
    from exulanica.world.object_repository import ReviewedAssetRow, WorldObjectRepository
    from exulanica.world.objects import (
        MAX_SCALE_MILLI,
        MAX_YAW_MICRORADIANS,
        OBJECT_ID_PATTERN,
        AuthoredObject,
        ElementOverride,
        ObjectBehaviour,
        ObjectOrigin,
        Transform,
        VersionEdit,
        object_document,
        override_document,
        validate_behaviour,
    )
    from exulanica.world.photo_point_maps import (
        POINT_MAP_INSTANCE_ID_PATTERN,
        PointMapInstance,
        PointMapModel,
        PointMapPlacement,
        PointMapSourceBinding,
        coverage_statement,
        point_map_instance_document,
        scale_statement,
        truth_statement,
        validate_point_map_instance,
    )
    from exulanica.world.registry import STYLE_REGISTRY, StyleRegistry
    from exulanica.world.repository import WorldStyleRepository
    from exulanica.world.saved_entries import (
        SavedWorldCandidate,
        SavedWorldEntry,
        SavedWorldEntryRepository,
        SavedWorldSourceAttachment,
        SourceAttachmentOperationConflict,
        SourceAttachmentSelection,
        StaleSavedWorldEntry,
    )
    from exulanica.world.society import (
        SOCIETY_ENGINE_VERSION,
        SOCIETY_POPULATION,
        StaleSocietyState,
        UnknownSociety,
    )
    from exulanica.world.society_repository import SocietyRepository
    from exulanica.world.structure import (
        PlacementMigration,
        SpatialCandidate,
        SpatialDigests,
        SpatialPreview,
        SpatialSnapshot,
    )
    from exulanica.world.structure_repository import WorldStructureRepository
    from exulanica.world.style_structure import (
        AuthoredVersionRef,
        CompatibilityIntent,
        ComposedTopologyRef,
        SourceAttachmentRef,
        StructuralSnapshotRef,
        StructureStyleCompatibility,
        StyleStructureFacts,
        StyleVersionRef,
        classify_structure_style_compatibility,
        raise_for_incompatible_structure_style,
    )


def _exports() -> dict[str, str]:
    """Each exported name and the module it is imported from, read from the imports above."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    guarded = next(
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "TYPE_CHECKING"
    )
    return {
        alias.asname or alias.name: statement.module
        for statement in guarded.body
        if isinstance(statement, ast.ImportFrom) and statement.module is not None
        for alias in statement.names
    }


_EXPORTS: Final = _exports()


def __getattr__(name: str) -> Any:
    """An exported name, imported from its module on first use, or a module of this package."""
    module = _EXPORTS.get(name)
    if module is None:
        try:
            return importlib.import_module(f"{__name__}.{name}")
        except ModuleNotFoundError as missing:
            if missing.name != f"{__name__}.{name}":
                raise
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


__all__ = [
    "CC0_LICENCE_ID",
    "CC0_LICENCE_TEXT",
    "ENVIRONMENT_INSTANCE_ID_PATTERN",
    "GLB_MEDIA_TYPE",
    "INTERACTION_POLICY_REGISTRY",
    "MAX_SCALE_MILLI",
    "MAX_YAW_MICRORADIANS",
    "OBJECT_ID_PATTERN",
    "POINT_MAP_INSTANCE_ID_PATTERN",
    "SOCIETY_ENGINE_VERSION",
    "SOCIETY_POPULATION",
    "STYLE_REGISTRY",
    "AlternateVersion",
    "AuthoredObject",
    "AuthoredVersionRef",
    "CompatibilityIntent",
    "ComposedTopologyRef",
    "CompositionBlocked",
    "CompositionPlacement",
    "CompositionPreview",
    "CompositionRequest",
    "ElementOverride",
    "EnvironmentAdmissionSource",
    "EnvironmentBindingDrift",
    "EnvironmentCompositionDenied",
    "EnvironmentInstance",
    "EnvironmentPlacement",
    "EnvironmentSelection",
    "EnvironmentSourceBinding",
    "EnvironmentSourceWithdrawn",
    "ExpiredPreview",
    "InteractionPolicyRegistry",
    "InteractionPolicyState",
    "InteractionPolicyVersion",
    "InteractionPreview",
    "InteractionProposal",
    "InteractionProposalRecord",
    "InteractionRecommendation",
    "InvalidEnvironmentData",
    "InvalidEnvironmentState",
    "InvalidInteractionData",
    "InvalidInteractionPreviewState",
    "InvalidObjectData",
    "InvalidObjectState",
    "InvalidPreviewState",
    "InvalidStructuralData",
    "InvalidStructuralPreviewState",
    "InvalidStyleData",
    "InvalidatedSourceVersion",
    "ObjectBehaviour",
    "ObjectOrigin",
    "PhotoPointMapSource",
    "PlacementMigration",
    "PointMapInstance",
    "PointMapModel",
    "PointMapPlacement",
    "PointMapSourceBinding",
    "ProposalOrigin",
    "ProposalProvenance",
    "ProtectedTopologyConflict",
    "ReviewedAsset",
    "ReviewedAssetRow",
    "ReviewedAssetSource",
    "SavedWorldCandidate",
    "SavedWorldEntry",
    "SavedWorldEntryRepository",
    "SavedWorldSourceAttachment",
    "SocietyRepository",
    "SourceAnchor",
    "SourceAttachmentOperationConflict",
    "SourceAttachmentRef",
    "SourceAttachmentSelection",
    "SourceAttachmentSource",
    "SourceMediaState",
    "SpatialCandidate",
    "SpatialDigests",
    "SpatialPreview",
    "SpatialSnapshot",
    "StaleInteractionPolicy",
    "StaleObjectBase",
    "StaleSavedWorldEntry",
    "StaleSocietyState",
    "StaleStructuralBase",
    "StaleStyleVersion",
    "StructuralSnapshotRef",
    "StructureStyleCompatibility",
    "StylePackBinding",
    "StylePreview",
    "StyleProposal",
    "StyleProposalRecord",
    "StyleReference",
    "StyleRegistry",
    "StyleScope",
    "StyleStructureFacts",
    "StyleVersion",
    "StyleVersionRef",
    "StyleWriteBusy",
    "TopologyContract",
    "TopologySourceSlot",
    "Transform",
    "UnavailableAsset",
    "UnknownSociety",
    "UnknownWorldResource",
    "VersionEdit",
    "WorkspaceAssetSource",
    "WorldInteractionPolicyRepository",
    "WorldNotConfigured",
    "WorldObjectRepository",
    "WorldSourceMedia",
    "WorldStructureRepository",
    "WorldStyleRepository",
    "apply_composition",
    "canonical_delta_document",
    "classify_structure_style_compatibility",
    "coverage_statement",
    "delta_sha256",
    "environment_instance_document",
    "object_document",
    "override_document",
    "point_map_instance_document",
    "preview_composition",
    "raise_for_incompatible_structure_style",
    "reviewed_assets",
    "scale_statement",
    "seed_reviewed_assets",
    "truth_statement",
    "validate_behaviour",
    "validate_environment_instance",
    "validate_point_map_instance",
]
