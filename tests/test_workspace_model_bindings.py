"""Workspace bindings reconstruct proof and retain exact execution parameters."""

import copy
import datetime as dt
import uuid
from dataclasses import replace
from decimal import Decimal

import pytest
from exulanica.models import provider_catalog
from exulanica.models.manifest import load_manifest
from exulanica.models.provider_catalog import ProviderPrice
from exulanica.world.model_probe_contract import prepare_definition, replay_outcome, seal
from exulanica.world.workspace_model_bindings import priced_snapshot, proof
from exulanica.world.workspace_models import WorkspaceModel

from test_model_probe_contract import successful_receipts


def candidate():
    manifest = load_manifest()
    return next(
        m
        for m in provider_catalog.provider_models().values()
        if m.model_id not in manifest.models
        and m.provider in manifest.providers
        and provider_catalog.licence_class(m.provider, m.model_id) == provider_catalog.ACCEPTED
        and provider_catalog.decision_capable(m, ("text",))
    )


def evidence():
    stated = candidate()
    found = prepare_definition(
        stated,
        ProviderPrice(stated.model_id, Decimal("0.1"), Decimal("0.3"), 32000, "a" * 64),
        added_seq=1,
        added_sha256="b" * 64,
        catalog_sha256=provider_catalog.catalog_sha256(),
        price_read_at=dt.datetime.now(dt.UTC).isoformat(),
    )
    receipts = successful_receipts(found)
    outcome = seal({**replay_outcome(found, receipts), "code": "completed", "reason": None})
    state = WorkspaceModel(
        stated.provider,
        stated.model_id,
        "probed",
        2,
        {},
        "c" * 64,
        str(uuid.uuid4()),
        "now",
        {},
        {
            "profile": "exulanica.workspace-model-probe/v1",
            "probe_id": str(uuid.uuid4()),
            "outcome_sha256": outcome["document_sha256"],
            "added_seq": 1,
            "added_sha256": "b" * 64,
            "verified": True,
        },
        1,
        "b" * 64,
    )
    return state, found, receipts, outcome


def test_asserted_verdict_partial_identity_and_wrong_engine_grant_no_binding():
    state, found, receipts, outcome = evidence()

    def bind(s, d, r, o, e=found["engine"]):
        return proof(s, d, r, o, engine=e, manifest=load_manifest())

    assert bind(state, found, receipts, outcome).spec.answering
    for args in [
        (replace(state, verdict={"verified": True}), found, receipts, outcome),
        (replace(state, added_seq=3), found, receipts, outcome),
        (state, found, receipts[:-1], outcome),
        (state, found, receipts, outcome, "exulanica-society/v6"),
    ]:
        with pytest.raises(ValueError):
            bind(*args)
    bad = copy.deepcopy(receipts)
    bad[0]["calls"][0]["served_model"] = "another/model"
    seal(bad[0])
    with pytest.raises(ValueError):
        bind(state, found, bad, outcome)


def test_plain_only_success_and_catalog_revocation_never_admit_lines(monkeypatch):
    state, found, receipts, _ = evidence()
    for receipt in receipts:
        if receipt["request"]["takes_line"]:
            receipt["outcome"] = "invalid"
            receipt["answer"] = None
            seal(receipt)
    outcome = seal({**replay_outcome(found, receipts), "code": "completed", "reason": None})
    state = replace(state, verdict={**state.verdict, "outcome_sha256": outcome["document_sha256"]})
    assert outcome["verified"]
    with pytest.raises(ValueError, match="lines_not_verified"):
        proof(state, found, receipts, outcome, engine=found["engine"], manifest=load_manifest())
    monkeypatch.setattr(provider_catalog, "licence_class", lambda *args: "conditional")
    with pytest.raises(ValueError, match="licence_or_capability"):
        proof(state, found, receipts, outcome, engine=found["engine"], manifest=load_manifest())


def test_runtime_snapshot_keeps_full_scoped_manifest_and_current_rates_without_rebinding():
    state, found, receipts, outcome = evidence()
    binding = proof(
        state, found, receipts, outcome, engine=found["engine"], manifest=load_manifest()
    )
    manifest = load_manifest()
    current, document = priced_snapshot(
        manifest,
        [binding],
        {
            binding.spec.model_id: ProviderPrice(
                binding.spec.model_id, Decimal("0.2"), Decimal("0.6"), 64000, "d" * 64
            )
        },
        read_at=dt.datetime.now(dt.UTC),
    )
    assert current.roles == manifest.roles and current.providers == manifest.providers
    assert all(current.models[key] == spec for key, spec in manifest.models.items())
    assert current.spec(binding.spec.model_id).input_usd_per_mtok == Decimal("0.2")
    assert document["manifest"]["models"][binding.spec.model_id]["context_window_tokens"] == 64000
    assert document["sources"][0]["added_seq"] == state.added_seq
    assert document["sources"][0]["outcome_sha256"] == outcome["document_sha256"]
    assert document["sources"][0]["rate_response_sha256"] == "d" * 64
    assert not current.spec(binding.spec.model_id).answering_order


def test_private_client_catalog_cannot_replace_shipped_bindings_or_automatic_metadata():
    from exulanica.models.client import ModelClient
    from exulanica.world.workspace_model_bindings import with_bindings

    from model_fakes import FakeTransport

    state, found, receipts, outcome = evidence()
    base = load_manifest()
    binding = proof(state, found, receipts, outcome, engine=found["engine"], manifest=base)
    manifest = with_bindings(base, [binding])
    client = ModelClient(api_key="test-key-not-real", manifest=base, transport=FakeTransport())
    scoped = client.with_chosen_manifest(
        manifest, {state.model_id: (binding.role, binding.prompt_version)}
    )
    assert scoped.manifest is manifest and client.manifest is base
    for changed in [
        replace(manifest, pipeline_version=base.pipeline_version + 1),
        replace(manifest, roles={}),
        replace(manifest, models={state.model_id: binding.spec}),
    ]:
        with pytest.raises(ValueError, match="cannot replace"):
            client.with_chosen_manifest(
                changed, {state.model_id: (binding.role, binding.prompt_version)}
            )
