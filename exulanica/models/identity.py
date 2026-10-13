"""Admitted provider identity for new workflow records, separate from raw replies."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from exulanica.models.manifest import Manifest, ModelSpec
from exulanica.models.results import NO_MODEL_IN_RESPONSE, ChatResult

REPORTED_MODEL_NOT_ADMITTED = "reported_model_not_admitted"


@dataclass(frozen=True, slots=True)
class ReportedModelIdentity:
    model_id: str | None
    unavailable: str | None


def reported_model_identity(
    reported: object, *, provider: str, manifest: Manifest, admitted_specs: Iterable[ModelSpec] = ()
) -> ReportedModelIdentity:
    """Keep an exact admitted provider/model pair; never infer an alias or requested identity."""
    if reported is None or reported == "":
        return ReportedModelIdentity(None, NO_MODEL_IN_RESPONSE)
    if isinstance(reported, str) and any(
        spec.provider == provider and spec.model_id == reported
        for spec in (*manifest.models.values(), *admitted_specs)
    ):
        return ReportedModelIdentity(reported, None)
    return ReportedModelIdentity(None, REPORTED_MODEL_NOT_ADMITTED)


def chat_model_identity(
    call: ChatResult, manifest: Manifest, *, admitted_specs: Iterable[ModelSpec] = ()
) -> ReportedModelIdentity:
    """Read the actual wire identity, including when ChatResult fills an absent one."""
    return reported_model_identity(
        call.raw.get("model"),
        provider=call.provider,
        manifest=manifest,
        admitted_specs=admitted_specs,
    )
