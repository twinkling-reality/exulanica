"""Admitted reusable environment sources and derived assets.

Admission validates container bytes, licence and provenance receipts
(:mod:`exulanica.environment.admission`). The repository persists those resources and
fails closed on withdrawal or digest mismatch (:mod:`exulanica.environment.repository`).
Derived surfaces include the feature index, the Flatiron owned-district compiler, optional
district interpretation recipes, scene-extraction candidates (preparation, never admission),
and the NYC Building Footprints preparer.

This package does not grant source-reuse rights, animation quality, or a runnable import.
"""

from exulanica.environment.admission import (
    MAX_ENVIRONMENT_PAYLOAD_BYTES,
    DerivedEnvironmentAsset,
    EnvironmentOperation,
    GeographicBounds,
    GeographicFrame,
    OperationRights,
    SourceAdmission,
    derived_receipt,
    source_receipt,
)
from exulanica.environment.feature_index import (
    FEATURE_INDEX_DERIVATION,
    FEATURE_INDEX_ENVELOPE,
    FEATURE_INDEX_ENVELOPE_V1,
    FEATURE_INDEX_ENVELOPE_V2,
    FEATURE_INDEX_PROFILE,
    FEATURE_INDEX_PROFILE_V1,
    FEATURE_INDEX_PROFILE_V2,
    MAX_ENVIRONMENT_FEATURES,
    EnvironmentFeatureInput,
    EnvironmentFeatureKind,
    FeatureIndexPublication,
    InvalidEnvironmentFeatureFilter,
    build_feature_index,
    filter_features,
    segment_id,
    validate_feature_index,
)
from exulanica.environment.repository import (
    AuthorizedEnvironmentBytes,
    EnvironmentFeatureCatalog,
    EnvironmentOperationDenied,
    EnvironmentPayloadTooLarge,
    EnvironmentRepository,
    EnvironmentResource,
    EnvironmentResourceWithdrawn,
    SourceDigestMismatch,
    UnknownEnvironmentResource,
)

__all__ = [
    "FEATURE_INDEX_DERIVATION",
    "FEATURE_INDEX_ENVELOPE",
    "FEATURE_INDEX_ENVELOPE_V1",
    "FEATURE_INDEX_ENVELOPE_V2",
    "FEATURE_INDEX_PROFILE",
    "FEATURE_INDEX_PROFILE_V1",
    "FEATURE_INDEX_PROFILE_V2",
    "MAX_ENVIRONMENT_FEATURES",
    "MAX_ENVIRONMENT_PAYLOAD_BYTES",
    "AuthorizedEnvironmentBytes",
    "DerivedEnvironmentAsset",
    "EnvironmentFeatureCatalog",
    "EnvironmentFeatureInput",
    "EnvironmentFeatureKind",
    "EnvironmentOperation",
    "EnvironmentOperationDenied",
    "EnvironmentPayloadTooLarge",
    "EnvironmentRepository",
    "EnvironmentResource",
    "EnvironmentResourceWithdrawn",
    "FeatureIndexPublication",
    "GeographicBounds",
    "GeographicFrame",
    "InvalidEnvironmentFeatureFilter",
    "OperationRights",
    "SourceAdmission",
    "SourceDigestMismatch",
    "UnknownEnvironmentResource",
    "build_feature_index",
    "derived_receipt",
    "filter_features",
    "segment_id",
    "source_receipt",
    "validate_feature_index",
]
