"""Roles as data: a part of a world that changes is run by a chosen model through one path.

The registry (``assets/catalogs/roles``) declares every decision role as data and names one
adapter module for each, imported from one package. What is shown here:

*   the person is a registered role like any other, its contract read from its catalogs;
*   a role declared in test data alone, a traffic signal at a junction
    (``tests/decision_role_fixtures``), runs end to end through the same ask, request, receipt,
    bounds and minute loop as the person, with a scripted model behind the real client, and
    replays from what it stored with no call; a copy of it registered under a new key, with its
    own copy of the adapter module and nothing else, runs the same way;
*   an adapter is imported only from its package, by a key, declaring the role it serves, or it is
    refused by name;
*   the model layer names no role, and a role's key, profiles and prompt texts are stated in its
    registry entry and its adapter module and nowhere else in the product;
*   the preflight still checks exactly the models it checked when the manifest named the role.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from exulanica.api.decision_host import (
    RoleAsk,
    ask,
    ask_bound_usd,
    host_refusal,
    hour_refusal,
)
from exulanica.grammar.errors import CatalogError
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import (
    MANIFEST_PATH,
    AnsweringMechanism,
    load_manifest,
    parse_manifest,
)
from exulanica.models.transport import HttpResponse
from exulanica.world.deciders import EXTERNAL_REASONS
from exulanica.world.decision_roles import (
    ADAPTER_PACKAGE,
    CHOICE_SUBJECT_FIELDS,
    PROFILE_PATTERNS,
    REGISTRY_DIRECTORY,
    RoleRefused,
    decision_roles,
    load_decision_roles,
)
from exulanica.world.role_decisions import (
    ReplayMismatch,
    play_minutes,
    replay_minutes,
    validate_role_receipt,
)
from exulanica.world.society_engines import ENGINES

from model_fakes import FakeTransport, RecordingPolicy, chat_body

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "decision_role_fixtures"
PACKAGE = "decision_role_fixtures"
PROBE_RECORD = "docs/evaluation/2026-09-25-society-person-models-probe.json"
MODEL_ID = "example/tool-model"
SEED = "d1" * 32
MINUTES = 40
BRANCH = uuid.UUID("0f1e2d3c-4b5a-4968-8776-655443322110")
#: What an answer outside the offer reads as.
NOT_OFFERED = "turn every light blue"


def _manifest():
    """The manifest with one example model verified by a forced function, at stated prices."""
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    template = next(
        raw
        for _model_id, raw in sorted(document["models"].items())
        if raw.get("answering") and raw["min_max_tokens"] is not None
    )
    document["models"][MODEL_ID] = {
        **template,
        "description": "Example tool model, asked by a forced function",
        "input_usd_per_mtok": Decimal("0.10"),
        "output_usd_per_mtok": Decimal("0.40"),
        "context_window_tokens": 131072,
        "min_max_tokens": 64,
        "default_max_tokens": 512,
        "catalog_use_cases": ["text", "function_calling"],
        "answering": {"tool_call": PROBE_RECORD},
    }
    document["models"][MODEL_ID].pop("answering_order", None)
    return parse_manifest(document)


class _Signaller(FakeTransport):
    """A model that lets the longer queue go once three cars wait, and otherwise keeps the
    lights; at some minutes it first answers with an action it was never offered, and at others
    it never answers with one."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        enum = payload["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
        minute = int(payload["messages"][1]["content"].split("minute ", 1)[1].split(".", 1)[0])
        turns = sorted(
            (int(label.split(", ")[1].split()[0]), label) for label in enum if ", " in label
        )
        keep = next(label for label in enum if ", " not in label)
        pick = turns[-1][1] if turns and turns[-1][0] >= 3 else keep
        first = len(payload["messages"]) == 2
        if minute % 11 == 4 or (minute % 11 == 7 and first):
            pick = NOT_OFFERED
        body = chat_body(
            "", model=payload["model"], prompt_tokens=200, completion_tokens=30, reasoning_tokens=5
        )
        body["choices"][0]["finish_reason"] = "tool_calls"
        body["choices"][0]["message"]["content"] = None
        body["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "call",
                "type": "function",
                "function": {"name": "act", "arguments": json.dumps({"action": pick})},
            }
        ]
        return HttpResponse(200, json.dumps(body))


class _Live:
    """A run's asks, through the one generic ask path and the real client."""

    def __init__(self, role, client, spec, mechanism, contract) -> None:
        self.role, self.client, self.spec = role, client, spec
        self.mechanism, self.contract = mechanism, contract

    def offerable(self, tick, due):
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests):
        return [
            ask(
                self.client,
                RoleAsk(self.role, request, self.spec, self.mechanism),
                self.contract,
                time.monotonic() + 20.0,
            )
            for request in requests
        ]


def _run(registry, key: str, adapter) -> dict[str, Any]:
    """The role ``key`` of ``registry`` played for :data:`MINUTES` minutes, asking a scripted
    model through the real client, then replayed from what it stored."""
    role = registry.role(key)
    contract = role.contract()
    manifest = _manifest()
    spec = manifest.offered(role.chosen, MODEL_ID)
    mechanism = contract.mechanism_for(spec)
    assert mechanism is AnsweringMechanism.TOOL_CALL
    transport = _Signaller()
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("5"), max_calls=1000),
    ).with_policy(RecordingPolicy())
    config = {
        "provider": spec.provider,
        "model_id": MODEL_ID,
        "mechanism": mechanism.value,
        "choice_seq": 1,
        "manifest_sha256": "a" * 64,
        "prompt_version": role.prompt_version,
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }

    def play(asking):
        return play_minutes(
            [role],
            role,
            start=adapter.genesis(BRANCH, 3),
            sources=[adapter.source(BRANCH)],
            seed=SEED,
            ticks=MINUTES,
            step=adapter.step,
            config_for=lambda _subject: config,
            request_id_for=lambda subject, tick: uuid.uuid5(
                BRANCH, f"{role.subject}-decision:{subject}:{tick}"
            ),
            asking=asking,
            seam=lambda _state, _due: {},
        )

    played = play(_Live(role, client, spec, mechanism, contract))
    asked = transport.call_count
    stored = list(zip(played.requests, played.receipts, strict=True))
    replayed = replay_minutes(stored, minute_digests=played.minute_digests, play=play)
    return {
        "role": role,
        "played": played,
        "replayed": replayed,
        "stored": stored,
        "transport": transport,
        "asked": asked,
        "play": play,
    }


def test_the_person_is_a_registered_role_read_from_its_catalogs():
    registry = decision_roles()
    person = registry.role("society_decision")
    assert person.adapter.__name__ == f"{ADAPTER_PACKAGE}.person"
    assert person.engines == (
        "exulanica-society/v2",
        "exulanica-society/v5",
        "exulanica-society/v7",
    )
    assert person.chosen.required_use_cases == ("text",)
    second = person.contract()
    first = person.contract({"society-decision-action": 1, "society-decision-policy": 1})
    assert second.versions == person.contract_versions
    assert set(second.words) == {"target", "wait", "stand", "talk"}
    assert set(first.words) == {"target", "wait"}
    # The first policy asks in the policy's own order; the second in a model's measured order.
    assert (first.asks_in_a_models_own_order, second.asks_in_a_models_own_order) == (False, True)


def test_a_role_declared_in_test_data_runs_through_the_one_path_and_replays_with_no_call():
    import decision_role_fixtures.junction_signal as adapter

    registry = load_decision_roles(FIXTURES, adapters=PACKAGE)
    assert list(registry.roles) == ["junction_signal"]
    run = _run(registry, "junction_signal", adapter)
    role, played, transport = run["role"], run["played"], run["transport"]
    assert played.requests and len(played.receipts) == len(played.requests)
    for request, receipt in run["stored"]:
        assert request["profile"] == role.request_profile
        validate_role_receipt(role, receipt, request)
    reasons = {receipt["reason"] for receipt in played.receipts}
    assert {"validated_choice", "answer_not_offered"} <= reasons, reasons
    # A model's choices changed the junction: signals switched ways at its word.
    switched = [event for event in played.events if event["disposition"] == "applied"]
    assert switched
    assert any(
        receipt["proposal"] and receipt["proposal"]["option"]["kind"] == "green"
        for receipt in played.receipts
    )
    # What the model read is the role's own data: its instruction and its catalog's words.
    sent = transport.requests[0]["payload"]
    assert sent["messages"][0]["content"] == role.instruction
    assert sent["tools"][0]["function"]["description"] == role.choice_description
    assert any(r["provider"]["answers_asked"] == 2 for r in played.receipts if r["provider"])
    # Replay rebuilt every request, receipt and minute to the byte, and asked nothing.
    assert transport.call_count == run["asked"]
    assert run["replayed"].receipts == played.receipts
    assert run["replayed"].minute_digests == played.minute_digests


def test_a_replay_that_differs_from_what_the_role_stored_is_refused_by_name():
    import decision_role_fixtures.junction_signal as adapter

    registry = load_decision_roles(FIXTURES, adapters=PACKAGE)
    run = _run(registry, "junction_signal", adapter)
    stored = run["stored"]
    index = next(i for i, (_, receipt) in enumerate(stored) if receipt["status"] == "accepted")
    request, receipt = stored[index]
    options = request["context"]["options"]
    other = next(o for o in options if o["label"] != receipt["proposal"]["label"])
    forged = {**receipt, "proposal": {"label": other["label"], "option": other}}
    tampered = [*stored[:index], (request, forged), *stored[index + 1 :]]
    with pytest.raises(ReplayMismatch):
        replay_minutes(tampered, minute_digests=run["played"].minute_digests, play=run["play"])


def test_a_new_role_needs_only_its_data_and_its_adapter_module(tmp_path, monkeypatch):
    """A second junction signal registered under a new key: a registry entry, its own copy of the
    adapter module declaring the new key, and nothing else anywhere, runs end to end."""
    package = tmp_path / "copied_roles"
    package.mkdir()
    (package / "__init__.py").write_text('"""A copied role."""\n', encoding="utf-8")
    source = (FIXTURES / "junction_signal.py").read_text(encoding="utf-8")
    copied = source.replace('ROLE: Final = "junction_signal"', 'ROLE: Final = "crossing_signal"')
    assert copied != source
    (package / "crossing_signal.py").write_text(copied, encoding="utf-8")
    registry_document = json.loads((FIXTURES / "decision-roles.v1.json").read_text("utf-8"))
    (entry,) = registry_document["entries"]
    entry.update(
        key="crossing_signal",
        adapter="crossing_signal",
        request_profile="exulanica.crossing-signal-decision-request/v1",
        receipt_profile="exulanica.crossing-signal-decision/v1",
        choice_profile="exulanica.crossing-signal-model-choice/v1",
        context_profile="exulanica.crossing-signal-context/v1",
        prompt_version="crossing-signal-choice/v1",
    )
    directory = tmp_path / "registry"
    directory.mkdir()
    (directory / "decision-roles.v1.json").write_text(json.dumps(registry_document), "utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    import copied_roles.crossing_signal as adapter

    registry = load_decision_roles(directory, adapters="copied_roles")
    run = _run(registry, "crossing_signal", adapter)
    assert run["played"].receipts and run["replayed"].receipts == run["played"].receipts
    assert {r["profile"] for r in run["played"].receipts} == {
        "exulanica.crossing-signal-decision/v1"
    }


def test_a_minute_refuses_a_receipt_of_no_role_its_engine_hosts():
    """An engine applies the receipts of the roles it hosts and names any other by its profile,
    never passing it to a role that would read it as its own."""
    from exulanica.world.role_decisions import apply_receipts

    import decision_role_fixtures.junction_signal as adapter

    signal = load_decision_roles(FIXTURES, adapters=PACKAGE).role("junction_signal")
    person = decision_roles().role("society_decision")
    state, document = adapter.genesis(BRANCH, 1), adapter.source(BRANCH)
    # The positive control: with no receipt, the seam is what the minute began with.
    assert apply_receipts([signal], state, document, [], {}) == ({}, ())
    stranger = {"profile": person.receipt_profile, "decision_seq": 1}
    with pytest.raises(ValueError, match="not one this engine's roles record"):
        apply_receipts([signal], state, document, [stranger], {})


def _registry_in(tmp_path: Path, **changes: Any) -> Path:
    document = json.loads((FIXTURES / "decision-roles.v1.json").read_text("utf-8"))
    document["entries"][0].update(changes)
    directory = tmp_path / "registry"
    directory.mkdir(exist_ok=True)
    (directory / "decision-roles.v1.json").write_text(json.dumps(document), "utf-8")
    return directory


def test_an_adapter_is_imported_from_its_package_alone_or_refused_by_name(tmp_path, monkeypatch):
    # The positive control: the fixture's own entry loads from its package.
    assert load_decision_roles(FIXTURES, adapters=PACKAGE).role("junction_signal")
    with pytest.raises(RoleRefused) as unknown:
        load_decision_roles(_registry_in(tmp_path, adapter="no_such_adapter"), adapters=PACKAGE)
    assert unknown.value.code == "role_adapter_unknown"
    # The product has an adapter under this key as well; the package selects which code runs.
    production = load_decision_roles(FIXTURES, adapters=ADAPTER_PACKAGE)
    assert production.role("junction_signal").adapter.__name__ == (
        "exulanica.world.roles.junction_signal"
    )
    # Data never names an import path: an adapter is a key, so a dotted name is refused.
    with pytest.raises(CatalogError, match="lowercase key"):
        load_decision_roles(_registry_in(tmp_path, adapter="os.path"), adapters=PACKAGE)
    # A module that serves another role, or lacks what the path calls, is refused by name.
    with pytest.raises(RoleRefused) as another:
        load_decision_roles(_registry_in(tmp_path, key="another_signal"), adapters=PACKAGE)
    assert another.value.code == "role_adapter_serves_another_role"
    package = tmp_path / "thin_roles"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "junction_signal.py").write_text('ROLE = "junction_signal"\n', encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(RoleRefused) as incomplete:
        load_decision_roles(FIXTURES, adapters="thin_roles")
    assert incomplete.value.code == "role_adapter_incomplete"


def test_the_registry_is_read_at_its_newest_version_and_refused_where_there_is_none(tmp_path):
    """A new role is published as a new registry version beside the last, and the newest is the
    one read; a directory holding no version is refused by name, never read as empty."""
    with pytest.raises(RoleRefused) as absent:
        load_decision_roles(tmp_path, adapters=PACKAGE)
    assert absent.value.code == "role_registry_absent"
    first = json.loads((FIXTURES / "decision-roles.v1.json").read_text("utf-8"))
    second = json.loads(json.dumps(first))
    second["catalog_version"] = 2
    second["entries"][0]["prompt_version"] = "junction-signal-choice/v2"
    (tmp_path / "decision-roles.v1.json").write_text(json.dumps(first), "utf-8")
    (tmp_path / "decision-roles.v2.json").write_text(json.dumps(second), "utf-8")
    registry = load_decision_roles(tmp_path, adapters=PACKAGE)
    assert registry.version == 2
    assert registry.role("junction_signal").prompt_version == "junction-signal-choice/v2"


def _stated(role) -> list[str]:
    """Everything a role states once, in its registry entry, beside its key: its profiles and its
    prompt."""
    return [
        role.request_profile,
        role.receipt_profile,
        role.choice_profile,
        role.context_profile,
        role.prompt_version,
        role.instruction,
        role.choice_description,
        role.not_offered,
    ]


def _names(text: str, role) -> list[str]:
    """What of ``role``'s own statements ``text`` restates: its key as a whole name, never as a
    part of another (``world_society_decision`` is a table), and its profiles and prompt texts."""
    key = re.compile(rf"(?<![A-Za-z0-9_.]){re.escape(role.key)}(?![A-Za-z0-9_])")
    return ([role.key] if key.search(text) else []) + [s for s in _stated(role) if s in text]


def test_the_model_layer_names_no_role():
    registry = decision_roles()
    toy = load_decision_roles(FIXTURES, adapters=PACKAGE)
    files = [*sorted((ROOT / "exulanica" / "models").glob("*.py")), MANIFEST_PATH]
    # The positive control: the scan reads what it claims to, the manifest among them, and it
    # finds a key where one is named.
    assert MANIFEST_PATH in files and len(files) > 10
    assert _names('ROLE = "society_decision"', registry.role("society_decision"))
    for role in [*registry, *toy]:
        for path in files:
            assert not _names(path.read_text(encoding="utf-8"), role), (role.key, path.name)


def test_a_roles_key_profiles_and_prompt_are_stated_in_its_entry_and_adapter_alone():
    """No product module but a role's adapter restates what its registry entry states. Migrations
    are fixed history and are not code, so they are not read."""
    package = ROOT / "exulanica"
    modules = sorted(package.rglob("*.py"))
    for role in decision_roles():
        adapter = Path(role.adapter.__file__).resolve()
        seen_in_adapter = False
        for path in modules:
            hits = _names(path.read_text(encoding="utf-8"), role)
            if path.resolve() == adapter:
                seen_in_adapter = role.key in hits
                continue
            # The city grammar's older junction_signal is a record kind, not a role declaration.
            if path.relative_to(ROOT).as_posix() == "exulanica/grammar/grammars/city/document.py":
                hits = [hit for hit in hits if hit != "junction_signal"]
            assert not hits, (path.relative_to(ROOT).as_posix(), hits)
        # The positive control: the adapter declares its key, so the scan can see one.
        assert seen_in_adapter, role.key


def test_every_adapter_module_serves_exactly_one_registered_role():
    registry = decision_roles()
    named = {role.adapter.__name__ for role in registry}
    held = {
        f"{ADAPTER_PACKAGE}.{path.stem}"
        for path in (ROOT / "exulanica" / "world" / "roles").glob("*.py")
        if path.stem != "__init__"
    }
    assert named == held and len(named) == len(registry.roles)


def test_every_role_s_contract_loads_at_every_version_its_catalogs_keep():
    for registry, directory in ((decision_roles(), None), (None, FIXTURES)):
        roles = registry or load_decision_roles(directory, adapters=PACKAGE)
        for role in roles:
            actions = sorted(
                int(path.name.rsplit(".v", 1)[1].split(".")[0])
                for path in role.catalog_directory.glob(f"{role.action_catalog}.v*.json")
            )
            policies = sorted(
                int(path.name.rsplit(".v", 1)[1].split(".")[0])
                for path in role.catalog_directory.glob(f"{role.policy_catalog}.v*.json")
            )
            assert actions and actions == policies, role.key
            for version in actions:
                contract = role.contract(
                    {role.action_catalog: version, role.policy_catalog: version}
                )
                assert role.adapter.IDLE_KIND in contract.words


def test_the_registry_spells_each_profile_as_migration_0117_admits_it():
    migration = (
        ROOT
        / "exulanica"
        / "migrations"
        / "0117_a_decision_role_s_documents_are_admitted_by_their_shape.sql"
    ).read_text(encoding="utf-8")
    for name in ("request_profile", "receipt_profile", "choice_profile"):
        assert f"'^{PROFILE_PATTERNS[name]}$'" in migration, name
    # And a choice names its subjects under exactly the fields the migration admits.
    admitted = set(re.findall(r"jsonb_typeof\(document->'([a-z_]+)'\) = 'array'", migration))
    assert admitted == set(CHOICE_SUBJECT_FIELDS)


def test_the_engines_roles_name_are_those_whose_owner_may_choose_a_model():
    """Two tables state it: the engine table says which engines let a world's owner choose a model
    (``owner_model_choice``), and the registry which engines host each role. A role on an engine
    whose owner may choose none would never be asked, and such an engine hosting no role would
    record choices nobody asks, so the two are held equal."""
    choosing = {engine.engine for engine in ENGINES if engine.owner_model_choice}
    assert choosing, "no engine lets its owner choose a model"
    assert {engine for role in decision_roles() for engine in role.engines} == choosing


def test_the_preflight_checks_the_models_it_checked_when_the_manifest_named_the_role():
    """Before the registry, the preflight read the models a role reached: every bound chain and
    every model offered to a chosen role. It reads the same set now."""
    manifest = load_manifest()
    bound = {spec.model_id for binding in manifest.roles.values() for spec in binding.chain}
    offered = {
        spec.model_id for role in decision_roles() for spec in manifest.offered_models(role.chosen)
    }
    assert manifest.referenced_model_ids() == bound | offered
    assert offered, "no registered role is offered a model"


def test_the_preflight_holds_a_registered_role_s_models_to_the_role_s_use_cases():
    """The product's preflights pass the registry's roles, so a model a role is offered is held to
    the use cases the role needs, as it was when the manifest named the role; the model package's
    own command, which cannot read the registry, checks every model verified to answer a choice
    and reports the roles it knows."""
    from exulanica.models.preflight import run_preflight

    from test_models_manifest import _entry, live_catalogs_for

    manifest = load_manifest()
    person = decision_roles().role("society_decision")
    offered = manifest.offered_models(person.chosen)[0].model_id
    catalogs = live_catalogs_for(manifest)
    _entry(catalogs, offered)["flavors"][0]["use_cases"] = ["reasoning"]
    held = run_preflight(manifest=manifest, catalogs=catalogs, chosen=decision_roles().chosen)
    lost = {issue.roles for issue in held.failures if issue.kind == "use_case_lost"}
    assert (person.key,) in lost
    unheld = run_preflight(manifest=manifest, catalogs=catalogs)
    assert (person.key,) not in {issue.roles for issue in unheld.failures}
    # Both check the same models.
    assert held.checked == unheld.checked


def test_the_deployment_gate_fails_when_a_role_s_model_loses_the_role_s_use_case(tmp_path, capsys):
    """``exulanica-preflight``, the gate docs/deployment.md section 7.3 wires into the build, gives
    the model package's check the registry's roles. A model only a registered role reaches (here
    the structured extraction fallback, unbound from every role in a copy of the manifest) that
    no longer declares the role's use case fails it, naming the role; the model package's own
    check passes it."""
    from exulanica.models import preflight
    from exulanica.orchestration import catalog_preflight

    from test_models_manifest import _catalog_files, _entry, live_catalogs_for

    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    only_offered = document["roles"]["structured_extraction"]["fallback"]
    for binding in document["roles"].values():
        if binding["fallback"] == only_offered:
            binding["fallback"] = None
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    manifest = parse_manifest(
        json.loads(manifest_path.read_text(encoding="utf-8"), parse_float=Decimal)
    )
    person = decision_roles().role("society_decision")
    bound = {spec.model_id for binding in manifest.roles.values() for spec in binding.chain}
    assert only_offered not in bound
    assert only_offered in {spec.model_id for spec in manifest.offered_models(person.chosen)}
    given = ["--manifest", str(manifest_path)]
    # The positive control: every model fits, and the gate passes.
    assert (
        catalog_preflight.main(
            [*given, *_catalog_files(tmp_path, live_catalogs_for(manifest), "good")]
        )
        == 0
    )
    lost = live_catalogs_for(manifest)
    _entry(lost, only_offered)["flavors"][0]["use_cases"] = ["reasoning"]
    checked = [*given, *_catalog_files(tmp_path, lost, "lost")]
    capsys.readouterr()
    assert catalog_preflight.main(checked) == 1
    failed = capsys.readouterr().err
    assert only_offered in failed and person.key in failed
    assert preflight.main(checked) == 0


def test_two_roles_sharing_a_profile_or_a_subject_word_are_refused_and_an_unknown_key_named(
    tmp_path, monkeypatch
):
    """Each role states its own profiles and prompt version, and decides for its own kind of
    subject: a request's id is derived from the role's subject word, the subject and the minute,
    so two roles sharing a word would reserve one id and the second would be skipped. A key the
    registry does not hold is named, never guessed."""
    from decision_role_support import person_entry, person_like, write_registry

    def loaded(name: str, second: dict[str, Any]):
        root = tmp_path / name
        monkeypatch.syspath_prepend(str(root))
        directory, package = write_registry(root, [person_entry(), second])
        return load_decision_roles(directory, adapters=package)

    # The positive control: a second role deciding for its own kind of subject loads beside it.
    registry = loaded("apart", person_like("tenant_decision", "tenant"))
    assert {role.key for role in registry} == {"society_decision", "tenant_decision"}
    with pytest.raises(RoleRefused) as unknown:
        registry.role("weather_decision")
    assert unknown.value.code == "role_not_registered"
    with pytest.raises(RoleRefused) as profile:
        loaded(
            "profile",
            {
                **person_like("tenant_decision", "tenant"),
                "receipt_profile": person_entry()["receipt_profile"],
            },
        )
    assert profile.value.code == "role_profile_shared"
    with pytest.raises(RoleRefused) as subject:
        loaded("subject", person_like("tenant_decision", "person"))
    assert subject.value.code == "role_subject_shared"


def test_a_role_s_bounds_are_read_from_its_own_contract():
    role = load_decision_roles(FIXTURES, adapters=PACKAGE).role("junction_signal")
    contract = role.contract()
    manifest = _manifest()
    spec = manifest.offered(role.chosen, MODEL_ID)
    budget = BudgetGuard(ceiling_usd=Decimal("5"), max_calls=1000)
    bound = ask_bound_usd(role, budget, spec, contract)
    chars = (
        len(role.instruction) + len(role.not_offered) + 2 * contract.value("context_bytes_maximum")
    )
    assert bound == contract.value("answer_attempts_maximum") * budget.estimate_usd(
        spec, prompt_chars=chars, max_tokens=512
    )
    client = ModelClient(
        api_key="test-key-not-real", manifest=manifest, transport=FakeTransport([]), budget=budget
    )
    assert host_refusal(role, client, manifest, contract) is None
    poor = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=FakeTransport([]),
        budget=BudgetGuard(ceiling_usd=bound / 2, max_calls=1000),
    )
    assert host_refusal(role, poor, manifest, contract) == "process_budget_spent"
    ceiling = contract.value("decisions_per_world_hour_maximum")
    assert hour_refusal(ceiling - 1, Decimal(0), bound, contract) is None
    assert hour_refusal(ceiling, Decimal(0), bound, contract) == "world_hour_decisions_spent"


def test_the_fixture_role_is_its_data_and_one_module():
    """What the junction signal needed, for the record: its data files and one module."""
    held = sorted(path.name for path in FIXTURES.iterdir() if path.name != "__pycache__")
    assert held == [
        "__init__.py",
        "decision-roles.v1.json",
        "junction-signal-action.v1.json",
        "junction-signal-policy.v1.json",
        "junction_signal.py",
    ]


def test_a_role_names_the_offered_option_that_changes_nothing():
    """What an outside program answers for a subject when nobody there acts for it: the option of
    the role's idle kind, read from the request's own context, or none where none is offered."""
    person = decision_roles().role("society_decision")
    signal = decision_roles().role("junction_signal")
    offered = {
        "options": [
            {"label": "A", "kind": "target"},
            {"label": "B", "kind": person.adapter.IDLE_KIND},
        ]
    }
    assert person.idle_label(offered) == "B"
    assert person.idle_label({"options": offered["options"][:1]}) is None
    assert signal.idle_label({"options": [{"label": "C", "kind": signal.adapter.IDLE_KIND}]}) == "C"
    # A pass is an outside program's own reason, recorded at once, which every role records.
    assert "decider_passed" in EXTERNAL_REASONS
    assert "decider_passed" in person.reasons and "decider_passed" in signal.reasons


THINGS = "exulanica-society/v7"


def test_a_society_of_things_people_are_asked_under_their_engine_s_own_terms():
    person = decision_roles().role("society_decision")
    own, things = person.terms(), person.terms(THINGS)
    assert own == person.terms("exulanica-society/v2") == person.terms("exulanica-society/v5")
    assert own.versions == {"society-decision-action": 2, "society-decision-policy": 2}
    assert things.versions == {"society-decision-action": 3, "society-decision-policy": 3}
    assert (own.prompt_version, things.prompt_version) == (
        "society-person-choice/v1",
        "society-person-choice/v2",
    )
    contract = person.contract(things.versions)
    assert {"carry_on", "say_to", "say_all", "leave"} <= set(contract.words)
    assert contract.value("line_characters_maximum") == 200
    # The role's own contract keeps exactly its keys: the line bounds are the third policy's.
    assert "line_characters_maximum" not in person.contract().policy
    # A request names the engine it was asked under in its context and is asked by its terms.
    assert person.terms_of({"engine": THINGS, "options": []}) == things
    assert person.terms_of({"options": []}) == own
    said = {
        "engine": THINGS,
        "line_characters_maximum": 200,
        "options": [
            {"label": "say something to everyone near you", "kind": "say_all"},
            {"label": "wait here a minute", "kind": "wait"},
        ],
    }
    assert person.choice(said).line_characters_maximum == 200
    assert person.choice(said).description == things.choice_description
    assert person.line_labels(said) == ("say something to everyone near you",)
    quiet = {**said, "options": said["options"][1:]}
    assert person.choice(quiet).line_characters_maximum is None
    # What an outside program answers when nobody acts: going on with what is under way first.
    carry = {"label": "carry on with what you are doing", "kind": "carry_on"}
    assert person.idle_label({"options": [*said["options"], carry]}) == carry["label"]
    assert person.idle_label(said) == "wait here a minute"


def _things_registry(root: Path, monkeypatch, change) -> Any:
    """The production registry's version 5 with ``change`` made to its person entry, loaded with
    a copy of the person's adapter."""
    from decision_role_support import write_registry

    document = json.loads(
        (REGISTRY_DIRECTORY / "decision-roles.v5.json").read_text(encoding="utf-8")
    )
    (entry,) = [e for e in document["entries"] if e["key"] == "society_decision"]
    entry = json.loads(json.dumps(entry))
    change(entry)
    directory, package = write_registry(root, [entry])
    first = directory / "decision-roles.v1.json"
    written = json.loads(first.read_text(encoding="utf-8"))
    first.unlink()
    (directory / "decision-roles.v5.json").write_text(
        json.dumps({**written, "catalog_version": 5}), encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(root))
    return load_decision_roles(directory, adapters=package)


def test_an_engine_states_terms_only_for_a_role_it_hosts_and_with_a_prompt_of_its_own(
    tmp_path, monkeypatch
):
    # The positive control: the production entry loads, with its one engine's terms.
    held = _things_registry(tmp_path / "held", monkeypatch, lambda entry: None)
    assert sorted(held.role("society_decision").engine_terms) == [THINGS]

    def unhosted(entry):
        entry["engine_terms"][0]["engine"] = "exulanica-society/v4"

    with pytest.raises(RoleRefused) as refused:
        _things_registry(tmp_path / "unhosted", monkeypatch, unhosted)
    assert refused.value.code == "role_terms_unhosted"

    def shared(entry):
        entry["engine_terms"][0]["prompt_version"] = entry["prompt_version"]

    with pytest.raises(RoleRefused) as refused:
        _things_registry(tmp_path / "shared", monkeypatch, shared)
    assert refused.value.code == "role_profile_shared"
