"""A model on this computer: a provider that takes no credential, asked like any other chosen model.

The manifest may declare a provider whose every URL reaches ``localhost`` (an Ollama server beside
the application) with no credential. Its requests carry no ``Authorization`` header; a client that
asks only such providers (``local_only``) never reads a credential; the preflight reports such a
provider's models as unavailable rather than failing a deployment that runs no server; and a
deployment with no model credential whose allowlist admits it builds a client for the models a
world chooses and nothing else. The shipped laptop model's entry is held to its recipe, the decision
contract's bounds and the probe record that verified it.
"""

from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal

import pytest
from exulanica.api.routes.society_models import offered_models
from exulanica.canonical import canonical_json
from exulanica.models import client as client_module
from exulanica.models.budget import BudgetGuard
from exulanica.models.choice import ChoiceRequest
from exulanica.models.client import (
    PROVIDER_CREDENTIAL_ABSENT,
    PROVIDER_NOT_ADMITTED,
    ModelClient,
)
from exulanica.models.egress import EGRESS_ALLOWLIST_ENV, parse_egress_allowlist
from exulanica.models.errors import ManifestError, ProviderRefused
from exulanica.models.manifest import (
    MANIFEST_PATH,
    AnsweringMechanism,
    ChosenRoleBinding,
    Role,
    load_manifest,
    parse_manifest,
)
from exulanica.models.preflight import ollama_tags, run_preflight
from exulanica.models.transport import HttpResponse
from exulanica.world.decision_roles import decision_roles

from model_fakes import FakeTransport, RecordingPolicy, chat_body
from test_egress_allowlist import _deployment_environ
from test_egress_allowlist import sockets as sockets
from test_models_manifest import live_catalogs_for

#: A role a world chooses a model for, as the decision role registry would pass one down.
CHOSEN = ChosenRoleBinding(
    role="example_choice", required_use_cases=("text",), rationale="A role these tests declare."
)
#: The probe record a test's own laptop model names; the parser checks only a record path's shape.
RECORD = "docs/evaluation/2026-10-13-laptop-mind-probe.json"
LOCAL_ID = "test-laptop-model"


def _document() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)


def _local_provider(document: dict) -> str:
    (provider,) = [key for key, raw in document["providers"].items() if raw["api_key_env"] is None]
    return provider


def _with_local_model(document: dict) -> dict:
    """The shipped manifest with one more model on this computer, verified by the schema."""
    document = copy.deepcopy(document)
    document["models"][LOCAL_ID] = {
        "provider": _local_provider(document),
        "description": "Test Model, an invented model that runs on this computer.",
        "answering": {"json_schema": RECORD},
        "input_usd_per_mtok": 0,
        "output_usd_per_mtok": 0,
        "context_window_tokens": 16384,
        "min_max_tokens": 256,
        "default_max_tokens": 512,
        "emits_inline_reasoning": False,
        "supports_json_schema": True,
        "catalog_type": "text2text",
        "catalog_use_cases": ["text"],
        "catalog_license": "apache-2.0",
        "region_informational": "this computer",
        "recipe": {
            "server": "ollama",
            "from": "test-library-model:tag",
            "parameters": {"num_ctx": 16384},
        },
    }
    return document


def _laptop_models(manifest) -> list:
    return [
        spec
        for spec in manifest.models.values()
        if manifest.provider(spec.provider).on_this_computer
    ]


# -- the manifest -------------------------------------------------------------------------------


def test_only_a_provider_on_this_computer_may_take_no_credential():
    document = _document()
    local = _local_provider(document)
    manifest = parse_manifest(document)
    assert not manifest.provider(local).takes_credential
    assert manifest.provider(local).on_this_computer
    assert manifest.provider(local).origin == "http://localhost:11434"
    # Its absent variable is never one a deployment is told to set.
    assert None not in manifest.credential_variables(manifest.roles)
    # A hosted provider stating no credential is refused by name.
    hosted = next(key for key, raw in document["providers"].items() if raw["api_key_env"])
    document["providers"][hosted]["api_key_env"] = None
    with pytest.raises(ManifestError, match="only a provider on this computer"):
        parse_manifest(document)


def test_a_provider_with_one_url_elsewhere_is_not_on_this_computer():
    document = _document()
    local = _local_provider(document)
    document["providers"][local]["catalog_url"] = "https://catalog.example.com/api/tags"
    with pytest.raises(ManifestError, match="only a provider on this computer"):
        parse_manifest(document)


def test_no_role_the_manifest_binds_is_served_on_this_computer():
    document = _with_local_model(_document())
    document["roles"]["reasoning_cheap"]["fallback"] = None
    document["roles"]["reasoning_cheap"]["primary"] = LOCAL_ID
    document["roles"]["reasoning_cheap"]["timeout_basis"]["model"] = LOCAL_ID
    with pytest.raises(ManifestError, match="a provider on this computer"):
        parse_manifest(document)


def test_a_model_on_this_computer_states_its_recipe_and_no_other_does():
    document = _with_local_model(_document())
    assert parse_manifest(document).spec(LOCAL_ID).recipe["parameters"]["num_ctx"] == 16384
    without = copy.deepcopy(document)
    del without["models"][LOCAL_ID]["recipe"]
    with pytest.raises(ManifestError, match="recipe"):
        parse_manifest(without)
    # The recipe's context is the context window the entry states.
    shrunk = copy.deepcopy(document)
    shrunk["models"][LOCAL_ID]["recipe"]["parameters"]["num_ctx"] = 4096
    with pytest.raises(ManifestError, match="num_ctx"):
        parse_manifest(shrunk)
    hosted = copy.deepcopy(document)
    hosted_id = next(m for m, raw in hosted["models"].items() if raw["provider"] != "ollama_local")
    hosted["models"][hosted_id]["recipe"] = document["models"][LOCAL_ID]["recipe"]
    with pytest.raises(ManifestError, match="recipe"):
        parse_manifest(hosted)


# -- the client ---------------------------------------------------------------------------------


def _choice(client: ModelClient, model_id: str):
    request = ChoiceRequest(
        description="Choose what the being does next: exactly one of the offered actions.",
        options=("rest by the pond", "walk to the bench"),
        line_characters_maximum=None,
    )
    return client.choose(
        CHOSEN,
        model_id,
        [{"role": "user", "content": "An invented being by an invented pond."}],
        request,
        mechanism=AnsweringMechanism.JSON_SCHEMA,
        prompt_version="test/v1",
        timeout=20,
        max_tokens=256,
    )


def test_a_model_on_this_computer_is_sent_no_credential(monkeypatch):
    manifest = parse_manifest(_with_local_model(_document()))
    transport = FakeTransport()
    transport.default = HttpResponse(
        status_code=200,
        text=json.dumps(chat_body('{"action": "rest by the pond"}', model=LOCAL_ID)),
    )
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
    )
    chosen = _choice(client, LOCAL_ID)
    assert chosen.label == "rest by the pond"
    (sent,) = transport.requests
    assert sent["url"] == "http://localhost:11434/v1/chat/completions"
    assert "Authorization" not in sent["headers"]
    assert "test-key-not-real" not in json.dumps(sent)
    # It costs nothing, and the ledger says so.
    assert client.ledger.calls[-1].usd == 0
    # The positive control: a hosted model's request carries the key.
    client.chat(Role.REASONING_CHEAP, [{"role": "user", "content": "x"}], prompt_version="t")
    assert transport.requests[-1]["headers"]["Authorization"] == "Bearer test-key-not-real"


def test_a_local_only_client_reads_no_credential_and_refuses_every_keyed_provider(monkeypatch):
    def no_credential_is_read(*_args, **_kwargs):
        raise AssertionError("a local-only client read a credential")

    monkeypatch.setattr(client_module, "api_key_from_env", no_credential_is_read)
    manifest = parse_manifest(_with_local_model(_document()))
    transport = FakeTransport()
    transport.default = HttpResponse(
        status_code=200,
        text=json.dumps(chat_body('{"action": "walk to the bench"}', model=LOCAL_ID)),
    )
    client = ModelClient(
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
        local_only=True,
    )
    keyed = {p.provider_id for p in manifest.providers.values() if p.takes_credential}
    assert dict(client.refusals) == dict.fromkeys(keyed, PROVIDER_CREDENTIAL_ABSENT)
    assert _choice(client, LOCAL_ID).label == "walk to the bench"
    hosted = next(
        spec.model_id
        for spec in manifest.offered_models(CHOSEN)
        if spec.provider in keyed and AnsweringMechanism.JSON_SCHEMA in spec.answering
    )
    with pytest.raises(ProviderRefused) as refused:
        _choice(client, hosted)
    assert refused.value.reason == PROVIDER_CREDENTIAL_ABSENT
    # A role the manifest binds is refused before anything is sent.
    with pytest.raises(ProviderRefused):
        client.chat(Role.REASONING_CHEAP, [{"role": "user", "content": "x"}], prompt_version="t")
    assert len(transport.requests) == 1


def test_a_local_only_client_refuses_its_provider_where_the_allowlist_does_not_admit_it():
    manifest = parse_manifest(_with_local_model(_document()))

    class Listed(FakeTransport):
        egress = parse_egress_allowlist(["https://elsewhere.example"])

    client = ModelClient(manifest=manifest, transport=Listed(), local_only=True)
    local = _local_provider(_document())
    assert client.refusals[local] == PROVIDER_NOT_ADMITTED


def test_a_deployment_that_runs_no_laptop_server_is_not_alerted_about_it(caplog):
    """A hosted deployment's allowlist names its provider and not this computer's server: the
    server is refused by name, and nothing is logged as the alert an attempt to leave is."""
    import logging

    manifest = load_manifest()

    class Hosted(FakeTransport):
        egress = parse_egress_allowlist(sorted(manifest.bound_origins()))

    with caplog.at_level(logging.WARNING, logger="exulanica.models.egress"):
        client = ModelClient(api_key="test-key-not-real", manifest=manifest, transport=Hosted())
    local = {p.provider_id for p in manifest.providers.values() if p.on_this_computer}
    assert dict(client.refusals) == dict.fromkeys(local, PROVIDER_NOT_ADMITTED)
    assert not [record for record in caplog.records if "11434" in record.getMessage()]
    # The positive control: an attempt to reach it is refused and logged.
    with caplog.at_level(logging.WARNING, logger="exulanica.models.egress"):
        assert not Hosted.egress.permits("http://localhost:11434/v1/chat/completions")
    assert [record for record in caplog.records if "11434" in record.getMessage()]


# -- the preflight ------------------------------------------------------------------------------


def test_the_tag_list_is_read_as_bare_identifiers_with_their_capabilities():
    found = ollama_tags(
        {
            "models": [
                {
                    "name": "a-model:latest",
                    "digest": "abc",
                    "capabilities": ["completion", "tools"],
                },
                {"name": "a-model:other-tag", "digest": "def", "capabilities": ["completion"]},
                {"name": "", "digest": "nothing"},
            ]
        }
    )
    assert set(found) == {"a-model", "a-model:other-tag"}
    assert found["a-model"]["use_cases"] == ["text", "tools"]
    assert found["a-model"]["digest"] == "abc"


def _catalogs_with_local_model(manifest):
    catalogs = live_catalogs_for(manifest)
    local = _local_provider(_document())
    return catalogs, local


def test_a_deployment_without_the_laptop_model_passes_the_preflight_with_a_warning(monkeypatch):
    manifest = parse_manifest(_with_local_model(_document()))
    catalogs, local = _catalogs_with_local_model(manifest)
    assert LOCAL_ID in manifest.referenced_model_ids()
    # Not supplied.
    del catalogs[local]
    report = run_preflight(manifest=manifest, catalogs=catalogs)
    assert report.ok, [str(issue) for issue in report.failures]
    assert {(i.kind, i.model_id) for i in report.warnings} >= {
        ("unavailable_on_this_computer", LOCAL_ID)
    }
    # Not admitted by the allowlist this deployment states, and so never asked.
    monkeypatch.setenv(EGRESS_ALLOWLIST_ENV, json.dumps(["https://elsewhere.example"]))
    (hosted,) = [entries for entries in catalogs.values() if isinstance(entries, list)]
    fetched = []
    monkeypatch.setattr(
        "exulanica.models.preflight.fetch_catalog",
        lambda url, **kwargs: fetched.append(url) or hosted,
    )
    report = run_preflight(manifest=manifest)
    assert report.ok, [str(issue) for issue in report.failures]
    assert all("11434" not in url for url in fetched)
    assert ("unavailable_on_this_computer", LOCAL_ID) in {
        (i.kind, i.model_id) for i in report.warnings
    }


def test_a_laptop_model_its_server_does_not_serve_is_a_warning_and_a_hosted_one_a_failure():
    manifest = parse_manifest(_with_local_model(_document()))
    catalogs, local = _catalogs_with_local_model(manifest)
    report = run_preflight(manifest=manifest, catalogs={**catalogs, local: {"models": []}})
    assert report.ok
    assert ("absent_from_catalog", LOCAL_ID) in {(i.kind, i.model_id) for i in report.warnings}
    # Served, it passes clean.
    served = {"models": [{"name": f"{LOCAL_ID}:latest", "capabilities": ["completion"]}]}
    report = run_preflight(manifest=manifest, catalogs={**catalogs, local: served})
    assert report.ok and not [i for i in report.issues if i.model_id == LOCAL_ID]
    # The positive control: a hosted model missing from its catalog still fails.
    hosted = next(iter(manifest.roles.values())).primary
    withdrawn = {
        provider: [e for e in entries if e["flavors"][0]["model_id"] != hosted.model_id]
        if isinstance(entries, list)
        else entries
        for provider, entries in catalogs.items()
    }
    assert not run_preflight(manifest=manifest, catalogs=withdrawn).ok


def test_a_laptop_server_that_does_not_answer_is_a_warning(monkeypatch):
    from exulanica.models.errors import TransportError

    manifest = parse_manifest(_with_local_model(_document()))
    catalogs, local = _catalogs_with_local_model(manifest)

    class Down(FakeTransport):
        egress = parse_egress_allowlist(
            ["http://localhost:11434", *sorted(manifest.bound_origins())]
        )

        def get_json(self, url, *, headers, timeout):
            self.gets.append(url)
            raise TransportError("connection refused", reached_provider=False)

    hosted = {provider: entries for provider, entries in catalogs.items() if provider != local}
    monkeypatch.setattr(
        "exulanica.models.preflight.fetch_catalog",
        lambda url, **kwargs: next(iter(hosted.values())),
    )
    down = Down()
    report = run_preflight(manifest=manifest, transport=down)
    assert report.ok, [str(issue) for issue in report.failures]
    assert down.gets == ["http://localhost:11434/api/tags"]
    assert ("unavailable_on_this_computer", LOCAL_ID) in {
        (i.kind, i.model_id) for i in report.warnings
    }


# -- the deployment -----------------------------------------------------------------------------


def test_a_deployment_with_no_credential_asks_only_the_laptop_model(tmp_path, sockets, monkeypatch):
    from exulanica.api.services import build_services

    def no_credential_is_read(*_args, **_kwargs):
        raise AssertionError("a deployment with no credential read one")

    monkeypatch.setattr(client_module, "api_key_from_env", no_credential_is_read)

    def built(allowlist: list[str]):
        environ = _deployment_environ(
            tmp_path, EXULANICA_SPENDING="process", **{EGRESS_ALLOWLIST_ENV: json.dumps(allowlist)}
        )
        with pytest.MonkeyPatch.context() as patch:
            for name, value in environ.items():
                patch.setenv(name, value)
            for name in ("NEBIUS_API_KEY", "EXULANICA_BUDGET_USD", "EXULANICA_BUDGET_MAX_CALLS"):
                patch.delenv(name, raising=False)
            return build_services(environ)

    # An allowlist without this computer's server: no model client of any kind.
    services = built(["https://elsewhere.example"])
    assert services.model_client is None and services.decision_client is None
    services = built(["http://localhost:11434"])
    assert services.model_client is None
    assert services.choice_client is not None
    assert services.decision_client is services.choice_client
    manifest = load_manifest()
    keyed = {p.provider_id for p in manifest.providers.values() if p.takes_credential}
    local = {p.provider_id for p in manifest.providers.values() if p.on_this_computer}
    for provider in keyed:
        assert services.provider_refusal(provider) == PROVIDER_CREDENTIAL_ABSENT
    for provider in local:
        assert services.provider_refusal(provider) is None
    assert any("only models on this computer" in note for note in services.warnings)
    # Building it opened nothing.
    assert sockets == []


# -- the shipped laptop model -------------------------------------------------------------------


def test_the_shipped_laptop_model_is_offered_for_a_being_and_costs_nothing():
    manifest = load_manifest()
    laptop = _laptop_models(manifest)
    assert laptop, "the positive control: the manifest offers a model on this computer"
    person = decision_roles().role("society_decision")
    offered = {spec.model_id for spec in manifest.offered_models(person.chosen)}
    for spec in laptop:
        assert spec.model_id in offered
        assert spec.input_usd_per_mtok == 0 and spec.output_usd_per_mtok == 0
        assert "this computer" in spec.description
        assert ":" not in spec.model_id
        # Ollama does not honour a forced call, so only a schema answers for it.
        assert set(spec.answering) == {AnsweringMechanism.JSON_SCHEMA}
        assert spec.not_offered_for_lines is None


def test_the_models_read_says_which_offered_models_run_on_this_computer():
    """The model list words a model on this computer "On this computer · Free" from the read's own
    answer: the provider's, true for the shipped laptop model and false for every hosted one."""

    class Services:
        def provider_refusal(self, provider: str) -> None:
            return None

    manifest = load_manifest()
    person = decision_roles().role("society_decision")
    served = {
        model["model_id"]: model["on_this_computer"]
        for model in offered_models(person, Services(), manifest=manifest)  # type: ignore[arg-type]
    }
    laptop = {spec.model_id for spec in _laptop_models(manifest)}
    assert laptop and laptop <= served.keys(), "the positive control: the laptop model is served"
    assert served.keys() - laptop, "and a hosted model beside it"
    assert all(served[model_id] is (model_id in laptop) for model_id in served)


def test_the_laptop_model_s_context_holds_the_largest_request_the_contract_sends():
    """What a being is shown is bounded in bytes by the decision contract; the budget guard reads
    three characters a token. The recipe's context must hold the largest instruction, twice the
    largest situation (its rendering and each message's framing, as ``ask_bound_usd`` bounds a
    prompt) and the model's answer bound, or the server cuts the prompt without saying so."""
    from exulanica.api.decision_host import answer_tokens

    manifest = load_manifest()
    person = decision_roles().role("society_decision")
    for spec in _laptop_models(manifest):
        for terms in person.every_terms():
            contract = person.contract(terms.versions)
            prompt_chars = (
                len(terms.instruction)
                + len(terms.not_offered)
                + 2 * contract.value("context_bytes_maximum")
            )
            needed = -(-prompt_chars // 3) + (answer_tokens(spec) or 0)
            assert needed <= spec.recipe["parameters"]["num_ctx"], (spec.model_id, needed)
        assert spec.recipe["parameters"]["num_ctx"] == spec.context_window_tokens


def test_the_laptop_model_names_the_record_whose_probe_verified_it_on_this_computer():
    manifest = load_manifest()
    root = MANIFEST_PATH.parents[2]
    for spec in _laptop_models(manifest):
        for mechanism, path in spec.answering.items():
            document = json.loads((root / path).read_bytes())
            digest = hashlib.sha256(canonical_json(document["record"])).hexdigest()
            assert digest == document["record_sha256"]
            verdict = document["record"]["verdicts"][spec.model_id][mechanism.value]
            assert verdict["verified"] is True and verdict["answers_lines"] is True
            assert document["record"]["chosen"]["chosen"] == spec.model_id
            served = document["record"]["served"]["candidates"][spec.model_id]
            assert served["recipe"] == {
                key: value
                for key, value in spec.recipe.items()
                if key not in {"server", "server_environment"}
            }


def test_the_modelfile_written_from_a_recipe_creates_the_model_as_it_was_measured(tmp_path):
    """``scripts/laptop_model_recipe.py`` writes the Modelfile from the manifest's recipe, so the
    context the bound above rests on is the one the alias is created with."""
    import importlib.util

    path = MANIFEST_PATH.parents[2] / "scripts" / "laptop_model_recipe.py"
    loaded = importlib.util.spec_from_file_location("laptop_model_recipe", path)
    assert loaded is not None and loaded.loader is not None
    script = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(script)
    for spec in _laptop_models(load_manifest()):
        out = tmp_path / f"{spec.model_id}.Modelfile"
        assert script.main([spec.model_id, str(out)]) == 0
        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[0] == f"FROM {spec.recipe['from']}"
        assert f"PARAMETER num_ctx {spec.context_window_tokens}" in lines
        for directive in ("renderer", "parser"):
            if directive in spec.recipe:
                assert f"{directive.upper()} {spec.recipe[directive]}" in lines
    # A hosted model has no recipe, and nothing is written for it.
    hosted = next(iter(load_manifest().roles.values())).primary.model_id
    assert script.main([hosted, str(tmp_path / "hosted.Modelfile")]) == 1
    assert not (tmp_path / "hosted.Modelfile").exists()


# -- spending -----------------------------------------------------------------------------------


def test_a_provider_on_this_computer_bills_nothing_and_no_spending_read_names_it():
    manifest = load_manifest()
    local = {p.provider_id for p in manifest.providers.values() if p.on_this_computer}
    assert local, "the positive control: the manifest declares a provider on this computer"
    assert set(manifest.billing_providers()) == set(manifest.providers) - local
    assert manifest.billing_providers()  # every hosted provider still bills
    # A model it serves is priced at nothing, or the manifest is refused.
    document = _with_local_model(_document())
    document["models"][LOCAL_ID]["output_usd_per_mtok"] = Decimal("0.01")
    with pytest.raises(ManifestError, match="bills nothing"):
        parse_manifest(document)


def test_a_model_on_this_computer_asks_the_durable_authority_nothing():
    """A client composed with the durable authority admits every billed attempt through it; an
    attempt to a provider on this computer is reserved and counted by the process's guard alone,
    and needs no workspace's spending to be attached."""
    import uuid

    from exulanica.models.spending import SpendingRefused

    from test_spending_protocol import Journal, ScriptedSource

    manifest = parse_manifest(_with_local_model(_document()))
    hosted = next(
        spec.model_id
        for spec in manifest.offered_models(CHOSEN)
        if manifest.provider(spec.provider).takes_credential
        and AnsweringMechanism.JSON_SCHEMA in spec.answering
    )
    transport = FakeTransport()
    for model_id in (LOCAL_ID, hosted):
        transport.by_model[model_id] = HttpResponse(
            status_code=200,
            text=json.dumps(chat_body('{"action": "rest by the pond"}', model=model_id)),
        )
    journal = Journal()
    source = ScriptedSource(journal)
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
        spending=source,
    )
    assert _choice(client, LOCAL_ID).label == "rest by the pond"
    assert journal == []
    assert client.ledger.calls[-1].model_id == LOCAL_ID
    # The positive control: a billed model with no workspace's spending attached sends nothing.
    with pytest.raises(SpendingRefused) as refused:
        _choice(client, hosted)
    assert refused.value.reason == "spending_scope_missing"
    # With a workspace's spending attached, the billed ask is admitted and the free one is not.
    spent = client.with_spending(source.for_workspace(uuid.uuid4()))
    _choice(spent, LOCAL_ID)
    _choice(spent, hosted)
    assert [step for step in journal if step[0] == "admit"] == [("admit", hosted)]


def test_a_comparison_opens_no_bound_and_reads_no_allowance_for_a_model_on_this_computer():
    from exulanica.api.society_comparison_start import asked_providers

    manifest = load_manifest()
    local = next(p.provider_id for p in manifest.providers.values() if p.on_this_computer)
    hosted = manifest.billing_providers()[0]
    body = {
        "arms": {
            "laptop": {"provider_config": {"provider": local}},
            "hosted": {"provider_config": {"provider": hosted}},
            "routine": {"provider_config": None},
        },
        "others": [{"provider_config": {"provider": local}}],
    }
    assert asked_providers(body) == (hosted,)
    # A provider the manifest no longer names is still named, as before: only the free one is not.
    body["arms"]["gone"] = {"provider_config": {"provider": "a_provider_since_removed"}}
    assert asked_providers(body) == tuple(sorted((hosted, "a_provider_since_removed")))
