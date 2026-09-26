"""Providers are data in the model manifest, and a role a world chooses offers only verified models.

Each refusal here is by name: a provider the manifest does not declare, a chain that crosses two
providers, an endpoint no egress allowlist could declare, a catalog the preflight cannot read, a
role both bound and chosen, and an answering mechanism no probe record verified.
"""

from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal

import pytest
from exulanica.canonical import canonical_json
from exulanica.models.client import ModelClient
from exulanica.models.egress import declared_origin
from exulanica.models.errors import ManifestError
from exulanica.models.handoff import ModelHandoff, egress_origin
from exulanica.models.manifest import (
    MANIFEST_PATH,
    AnsweringMechanism,
    Role,
    load_manifest,
    parse_manifest,
)

from model_fakes import FakeTransport

#: The probe record the shipped manifest names; the parser checks only a record path's shape.
PROBE_RECORD = "docs/evaluation/2026-09-25-society-person-models-probe.json"


def _document() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)


def _a_chat_model(document: dict) -> str:
    """The first declared model a chosen role could take once verified: a chat model with text."""
    return next(
        model_id
        for model_id, raw in sorted(document["models"].items())
        if raw["min_max_tokens"] is not None and "text" in raw["catalog_use_cases"]
    )


def test_every_model_names_a_declared_provider_and_every_provider_has_a_derived_origin(manifest):
    assert manifest.providers
    for spec in manifest.models.values():
        assert spec.provider in manifest.providers
        assert spec.description.strip()
    for provider in manifest.providers.values():
        assert provider.origin == declared_origin(provider.base_url)
        assert provider.catalog_origin == declared_origin(provider.catalog_url)


def test_a_hosted_handoff_goes_to_the_origin_of_the_provider_serving_the_role(manifest):
    for role, binding in manifest.roles.items():
        handoff = ModelHandoff.hosted(manifest, role)
        assert handoff.destination == manifest.provider(binding.provider).origin
        assert {identity.provider for identity in handoff.identities} == {binding.provider}
    # The handoff's own spelling of an origin is the egress allowlist's, one function.
    assert egress_origin is declared_origin


def test_a_model_naming_an_undeclared_provider_is_refused():
    document = _document()
    model_id = next(iter(document["models"]))
    document["models"][model_id]["provider"] = "nobody_declared_this"
    with pytest.raises(ManifestError, match="nobody_declared_this"):
        parse_manifest(document)


def test_a_role_whose_chain_crosses_two_providers_is_refused():
    document = _document()
    (key,) = list(document["providers"])[:1]
    document["providers"]["second_provider"] = copy.deepcopy(document["providers"][key])
    role = document["roles"]["reasoning_cheap"]
    document["models"][role["fallback"]]["provider"] = "second_provider"
    with pytest.raises(ManifestError, match="stays on one provider"):
        parse_manifest(document)


@pytest.mark.parametrize(
    ("field", "url"),
    [
        ("base_url", "http://api.example.com/v1"),
        ("base_url", "https://192.0.2.10/v1"),
        ("catalog_url", "https://user@catalog.example.com/models"),
    ],
    ids=["plain-http-remote", "address", "userinfo"],
)
def test_a_provider_url_no_allowlist_could_declare_is_refused_by_name(field, url):
    document = _document()
    key = next(iter(document["providers"]))
    document["providers"][key][field] = url
    with pytest.raises(ManifestError, match=f"provider {key}: {field}"):
        parse_manifest(document)


def test_an_unknown_catalog_format_is_refused_by_name():
    document = _document()
    key = next(iter(document["providers"]))
    document["providers"][key]["catalog_format"] = "a_format_nobody_reads"
    with pytest.raises(ManifestError, match="a_format_nobody_reads"):
        parse_manifest(document)


def test_a_provider_states_exactly_its_fields():
    document = _document()
    key = next(iter(document["providers"]))
    document["providers"][key]["egress_origin"] = "https://stated.twice.example.com"
    with pytest.raises(ManifestError, match="states exactly"):
        parse_manifest(document)


def test_a_role_both_bound_and_chosen_is_refused():
    document = _document()
    document["chosen_roles"]["vision"] = {"required_use_cases": ["text"], "rationale": "twice"}
    with pytest.raises(ManifestError, match="never both"):
        parse_manifest(document)


def test_a_chosen_role_has_no_model_of_its_own(manifest):
    with pytest.raises(ManifestError, match="chosen by the world"):
        manifest[Role.SOCIETY_DECISION]
    with pytest.raises(ManifestError, match="not chosen by a world"):
        manifest.chosen(Role.VISION)


def test_a_chosen_role_states_no_primary_or_timeout():
    document = _document()
    document["chosen_roles"]["society_decision"]["timeout_seconds"] = 20
    with pytest.raises(ManifestError, match="caller bounds its calls"):
        parse_manifest(document)


def test_a_model_is_offered_to_a_chosen_role_only_with_a_verified_mechanism():
    document = _document()
    model_id = _a_chat_model(document)
    for raw in document["models"].values():
        raw.pop("answering", None)
    bare = parse_manifest(document)
    assert bare.offered_models(Role.SOCIETY_DECISION) == ()
    with pytest.raises(ManifestError, match="not offered"):
        bare.offered(Role.SOCIETY_DECISION, model_id)

    document["models"][model_id]["answering"] = {"tool_call": PROBE_RECORD}
    verified = parse_manifest(document)
    spec = verified.offered(Role.SOCIETY_DECISION, model_id)
    assert spec.answering == {AnsweringMechanism.TOOL_CALL: PROBE_RECORD}
    assert [s.model_id for s in verified.offered_models(Role.SOCIETY_DECISION)] == [model_id]
    assert model_id in verified.referenced_model_ids()
    handoff = ModelHandoff.chosen(verified, Role.SOCIETY_DECISION, model_id)
    assert [identity.model_id for identity in handoff.identities] == [model_id]
    assert handoff.destination == verified.provider(spec.provider).origin


def test_a_verified_model_without_the_roles_use_cases_is_not_offered():
    document = _document()
    model_id = _a_chat_model(document)
    document["models"][model_id]["answering"] = {"json_schema": PROBE_RECORD}
    document["chosen_roles"]["society_decision"]["required_use_cases"] = ["a_use_case_nobody_has"]
    manifest = parse_manifest(document)
    assert manifest.offered_models(Role.SOCIETY_DECISION) == ()


@pytest.mark.parametrize(
    ("answering", "message"),
    [
        ({"telepathy": PROBE_RECORD}, "not a mechanism the client asks by"),
        ({"tool_call": "notes/somewhere.json"}, "probe record that verified it"),
        ({"tool_call": ""}, "probe record that verified it"),
    ],
    ids=["unknown-mechanism", "record-outside-evaluation", "no-record"],
)
def test_an_answering_mechanism_names_a_known_mechanism_and_its_record(answering, message):
    document = _document()
    document["models"][_a_chat_model(document)]["answering"] = answering
    with pytest.raises(ManifestError, match=message):
        parse_manifest(document)


def test_every_verified_mechanism_names_a_probe_record_whose_verdict_verified_it():
    """What the shipped manifest offers a chosen role is what a recorded probe verified.

    Each mechanism a model's entry names points at a retained evaluation record that reproduces
    its own digest and whose verdict for that model and mechanism is verified; a mechanism the
    probe did not verify, or a record the tree does not hold, fails here.
    """
    manifest = load_manifest()
    offered = manifest.offered_models(Role.SOCIETY_DECISION)
    # A positive control: the probe verified some model, so the loop below reads real verdicts.
    assert offered, "no model is offered to a person's decisions"
    root = MANIFEST_PATH.parents[2]
    for spec in manifest.models.values():
        for mechanism, record_path in spec.answering.items():
            document = json.loads((root / record_path).read_bytes())
            digest = hashlib.sha256(canonical_json(document["record"])).hexdigest()
            assert digest == document["record_sha256"], record_path
            verdicts = document["record"].get("verdicts", {})
            assert spec.model_id in verdicts, (spec.model_id, record_path, "names no verdict")
            verdict = verdicts[spec.model_id][mechanism.value]
            assert verdict["verified"] is True, (spec.model_id, mechanism)


@pytest.mark.parametrize(
    "variable",
    ["EXULANICA_DATABASE_URL", "EXULANICA_API_TOKENS", "HOME", "nebius_api_key", "_API_KEY"],
    ids=["a-database-url", "the-api-tokens", "home", "lowercase", "no-name"],
)
def test_a_provider_credential_is_read_only_from_an_api_key_variable(variable):
    """A manifest entry naming another setting would send its value as a bearer token."""
    document = _document()
    (provider,) = list(document["providers"])[:1]
    document["providers"][provider]["api_key_env"] = variable
    with pytest.raises(ManifestError, match="is not a provider's API key variable"):
        parse_manifest(document)


def test_one_key_serves_one_provider_and_several_are_given_by_provider():
    """A single key is never sent to a second provider: several are named, one each."""
    document = _document()
    (first,) = list(document["providers"])[:1]
    second = copy.deepcopy(document["providers"][first])
    second["base_url"] = "https://second.example.com/v1"
    second["catalog_url"] = "https://second.example.com/models"
    second["api_key_env"] = "SECOND_PROVIDER_TEST_API_KEY"
    document["providers"]["second_provider"] = second
    manifest = parse_manifest(document)
    with pytest.raises(ValueError, match="each provider's key by provider"):
        ModelClient(api_key="one-key-for-all", manifest=manifest, transport=FakeTransport())
    client = ModelClient(
        api_key={provider: f"key-of-{provider}" for provider in manifest.providers},
        manifest=manifest,
        transport=FakeTransport(),
    )
    assert client.refusals == {}
