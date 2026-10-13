"""Eligibility, recorded verdicts and executable bindings remain distinct in discovery."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from exulanica.models import provider_catalog as catalog
from exulanica.models.manifest import load_manifest
from exulanica.world.decision_roles import decision_roles
from exulanica.world.model_discovery import discovery, model_preflight
from exulanica.world.workspace_models import WorkspaceModel


def _read(provider, model_id, workspace=None):
    return model_preflight(
        provider,
        model_id,
        manifest=load_manifest(),
        roles=tuple(decision_roles()),
        workspace=workspace,
        provider_refusal="provider_credential_absent",
        host_refusal=lambda role: "models_not_run_here",
    )


def _record(provider, model_id):
    return WorkspaceModel(
        provider=provider,
        model_id=model_id,
        kind="probed",
        model_seq=2,
        facts={"verified": True, "licence_class": "accepted"},
        document_sha256="a" * 64,
        recorded_by="not-served",
        recorded_at="2026-10-11T00:00:00Z",
        added={"licence_class": "accepted"},
        verdict={"verified": True},
    )


def test_a_catalog_eligible_model_and_forged_verdict_are_not_an_executable_binding():
    manifest = load_manifest()
    stated = next(
        model
        for model in catalog.provider_models().values()
        if model.model_id not in manifest.models
        and catalog.licence_class(model.provider, model.model_id) == catalog.ACCEPTED
    )
    view = _read(stated.provider, stated.model_id, _record(stated.provider, stated.model_id))
    assert view["eligibility"] == {"eligible": True, "reason": None}
    assert view["workspace"]["verified"] is True  # This is only what was recorded.
    assert view["execution"]["offered_roles"] == []
    assert view["execution"]["reason"] == "model_not_verified_for_execution"
    assert view["probe"]["operation_estimate"] is None
    assert view["admission"]["state"] == view["probe"]["state"] == "supported"
    assert view["stored_rates"] is None
    assert "recorded_by" not in view["workspace"]


def test_shipped_verification_does_not_imply_runtime_readiness_or_live_prices():
    spec = next(spec for spec in load_manifest().models.values() if spec.answering)
    view = _read(spec.provider, spec.model_id)
    assert view["execution"]["offered_roles"]
    assert view["execution"]["answering"] == {
        m.value: record for m, record in spec.answering.items()
    }
    assert view["runtime"]["provider_refusal"] == "provider_credential_absent"
    assert all(role["host_refusal"] == "models_not_run_here" for role in view["runtime"]["roles"])
    assert Decimal(view["stored_rates"]["input_usd_per_mtok"]) == spec.input_usd_per_mtok
    assert view["stored_rates"]["live_verified"] is False
    assert view["probe"]["operation_estimate"] is None


def test_catalog_owned_licence_is_checked_for_every_read_and_preflight(monkeypatch):
    spec = next(spec for spec in load_manifest().models.values() if spec.answering)
    record = _record(spec.provider, spec.model_id)
    for licence in (catalog.CONDITIONAL, catalog.NOT_CLASSIFIED, catalog.REJECTED):
        monkeypatch.setattr(catalog, "licence_class", lambda *args, value=licence: value)
        view = _read(spec.provider, spec.model_id, record)
        assert view["eligibility"] == {"eligible": False, "reason": "licence_not_admitted"}
        assert view["execution"]["offered_roles"] == []
        listed = discovery(
            manifest=load_manifest(),
            roles=tuple(decision_roles()),
            workspace=[record],
            provider_refusal=lambda provider: None,
            host_refusal=lambda role: None,
        )
        assert all(model["execution"]["offered_roles"] == [] for model in listed["models"])


def test_unknown_unlisted_and_non_decision_models_have_distinct_preflight_refusals():
    assert _read("unknown", "maker/Unknown")["eligibility"]["reason"] == "provider_not_served"
    provider = next(iter(load_manifest().providers))
    assert _read(provider, "maker/Unknown")["eligibility"]["reason"] == "model_not_listed"
    spec = next(spec for spec in load_manifest().models.values() if not spec.is_chat)
    assert _read(spec.provider, spec.model_id)["eligibility"]["reason"] == "model_not_for_decisions"


def test_discovery_keeps_unlisted_removed_records_without_ranking_by_probe_figures():
    provider = next(iter(load_manifest().providers))
    record = replace(_record(provider, "maker/Withdrawn"), kind="removed")
    view = discovery(
        manifest=load_manifest(),
        roles=tuple(decision_roles()),
        workspace=[record],
        provider_refusal=lambda provider: None,
        host_refusal=lambda role: None,
    )
    keys = [(model["provider"], model["model_id"]) for model in view["models"]]
    assert keys == sorted(keys)
    missing = next(model for model in view["models"] if model["model_id"] == record.model_id)
    assert missing["workspace"]["state"] == "removed"
    assert missing["execution"]["offered_roles"] == []
    assert view["live_catalog_verified"] is False
