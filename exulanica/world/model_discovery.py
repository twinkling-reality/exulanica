"""Discovery and admission preflight, without fetching a provider or asking a model.

Catalog eligibility, a workspace's recorded facts, a shipped probe and runtime readiness are
separate claims. A workspace verdict alone is not an executable role binding. The product probe
has a separate prepared quote and explicit bounded start. Prices here are stored rates,
never an operation estimate. World-specific subjects, choices and receipts remain the world's
models read's job.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from typing import Any, Final

from exulanica.models import provider_catalog
from exulanica.models.manifest import Manifest
from exulanica.world.decision_roles import DecisionRole
from exulanica.world.model_probe_contract import case_book
from exulanica.world.workspace_model_bindings import ProvenBinding
from exulanica.world.workspace_models import WorkspaceModel

PROFILE: Final = "exulanica.model-discovery/v1"
PREFLIGHT_PROFILE: Final = "exulanica.model-admission-preflight/v1"


def model_preflight(
    provider: str,
    model_id: str,
    *,
    manifest: Manifest,
    roles: Sequence[DecisionRole],
    workspace: WorkspaceModel | None,
    provider_refusal: str | None,
    host_refusal: Callable[[DecisionRole], str | None],
    probe_served: bool = False,
    bindings: Mapping[tuple[str, str], ProvenBinding] | None = None,
    execution_enabled: bool = False,
) -> dict[str, Any]:
    """One exact identifier's eligibility and evidence; no stored licence class is trusted."""
    book, _digest = case_book()
    stated = provider_catalog.provider_model(provider, model_id)
    licence = provider_catalog.licence_class(provider, model_id)
    candidates = [
        role
        for role in roles
        if stated is not None
        and provider_catalog.decision_capable(stated, role.chosen.required_use_cases)
    ]
    refusal = (
        "provider_not_served"
        if provider not in manifest.providers
        else "model_not_listed"
        if stated is None
        else "model_not_for_decisions"
        if not candidates
        else "licence_not_admitted"
        if licence != provider_catalog.ACCEPTED
        else None
    )
    binding = (bindings or {}).get((provider, model_id))
    spec = manifest.models.get(model_id)
    if spec is None and binding is not None:
        spec = binding.spec
    if spec is not None and spec.provider != provider:
        spec = None
    # Added candidates carry fully replayed proof with a role and engine scope.
    # Arbitrary recorded verdicts and copied licence words grant nothing.
    offered = [
        role
        for role in candidates
        if refusal is None
        and spec is not None
        and role.chosen.offers(spec)
        and (binding is None or (execution_enabled and role.key == binding.role))
        and (
            role.contract() if binding is None else role.contract_for(binding.engine)
        ).mechanism_for(spec)
        is not None
    ]
    return {
        "provider": provider,
        "model_id": model_id,
        "name": manifest.model_name(model_id) if model_id in manifest.models else model_id,
        "catalog": None if stated is None else asdict(stated),
        "catalog_sha256": provider_catalog.catalog_sha256(),
        "licence_class": licence,
        "eligibility": {"eligible": refusal is None, "reason": refusal},
        "candidate_roles": [role.key for role in candidates],
        "workspace": None if workspace is None else workspace.view(),
        "binding_evidence": None if binding is None else binding.source(),
        "execution": {
            "source": ("shipped_manifest" if binding is None else "workspace_probe")
            if offered
            else None,
            "engine": None if binding is None else binding.engine,
            "fresh_rates_required": binding is not None,
            "offered_roles": [role.key for role in offered],
            "reason": refusal
            or (
                None
                if offered
                else "workspace_models_not_run_here"
                if binding is not None
                else "model_not_verified_for_execution"
            ),
            "answering": {}
            if spec is None
            else {key.value: value for key, value in spec.answering.items()},
            "not_offered_for_lines": None if spec is None else spec.not_offered_for_lines,
        },
        "runtime": {
            "provider_refusal": provider_refusal,
            "roles": [{"key": role.key, "host_refusal": host_refusal(role)} for role in offered],
            "world_prerequisites": "read_the_world_models_route",
        },
        "stored_rates": None
        if spec is None
        else {
            "source": "shipped_manifest" if binding is None else "recorded_probe",
            "input_usd_per_mtok": str(spec.input_usd_per_mtok),
            "output_usd_per_mtok": str(spec.output_usd_per_mtok),
            "context_window_tokens": spec.context_window_tokens,
            "live_verified": False,
        },
        "admission": {"state": "supported", "eligible": refusal is None, "reason": refusal},
        "probe": {
            "state": "supported",
            "role": book["role"],
            "engine": book["engine"],
            "prepare_ready": refusal is None
            and provider_refusal is None
            and workspace is not None
            and not workspace.removed,
            "start_served": probe_served,
            "reason": refusal
            or provider_refusal
            or ("model_not_added" if workspace is None or workspace.removed else None),
            "operation_estimate": None,
            "execution_admitted_by_probe": False,
        },
    }


def discovery(
    *,
    manifest: Manifest,
    roles: Sequence[DecisionRole],
    workspace: Sequence[WorkspaceModel],
    provider_refusal: Callable[[str], str | None],
    host_refusal: Callable[[DecisionRole], str | None],
    probe_served: bool = False,
    bindings: Mapping[tuple[str, str], ProvenBinding] | None = None,
    execution_enabled: bool = False,
) -> dict[str, Any]:
    """Models by identifier, never by probe figures; includes removed/unlisted workspace facts."""
    recorded = {(model.provider, model.model_id): model for model in workspace}
    identifiers = (
        {(model.provider, model.model_id) for model in provider_catalog.provider_models().values()}
        | {(model.provider, model.model_id) for model in manifest.models.values()}
        | set(recorded)
    )
    providers = {key: provider_refusal(key) for key, _ in identifiers}
    hosts = {role.key: host_refusal(role) for role in roles}
    return {
        "profile": PROFILE,
        "ordering": "provider_then_model_id",
        "live_catalog_verified": False,
        "roles": [
            {"key": role.key, "subject": role.subject, "engines": list(role.engines)}
            for role in roles
        ],
        "models": [
            model_preflight(
                provider,
                model_id,
                manifest=manifest,
                roles=roles,
                workspace=recorded.get((provider, model_id)),
                provider_refusal=providers[provider],
                host_refusal=lambda role: hosts[role.key],
                probe_served=probe_served,
                bindings=bindings,
                execution_enabled=execution_enabled,
            )
            for provider, model_id in sorted(identifiers)
        ],
    }
