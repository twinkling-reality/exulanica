"""Every model a person's own runner holds, checked once on this computer before a person may choose
one (L1).

A runner's fake answers its tag list, ``/api/show`` and ``/api/chat`` as Ollama does; nothing
reaches a network. The check asks the role's own two cases (``assets/catalogs/local-check``), holds
every answer to the host's own rule (``answer_outcome``), and keeps one record per digest in the
install's own directory.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from exulanica.api import runner_models as runner_models_api
from exulanica.api import services as services_module
from exulanica.api.authorisation import TokenDirectory
from exulanica.api.decision_admission import answer_tokens
from exulanica.api.routes.society_models import offered_models
from exulanica.api.services import Services
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import LocalLiveness, ModelClient
from exulanica.models.egress import parse_egress_allowlist
from exulanica.models.errors import ModelUnavailableError, ProviderRefused, TransportError
from exulanica.models.local_runner import (
    CASES_PATH,
    CheckStore,
    LocalChecks,
    able_specs,
    check_cases,
    check_model,
    checked_ms,
    role_context_tokens,
    runner_answer,
    runner_models,
    runner_name,
    runner_request,
    runner_spec,
    with_runner_models,
)
from exulanica.models.manifest import AnsweringMechanism, load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.world.decision_roles import decision_roles
from exulanica.world.role_decisions import answer_outcome
from scripts import make_local_check_cases

from model_fakes import RecordingPolicy
from test_egress_allowlist import _deployment_environ
from test_egress_allowlist import sockets as sockets

DIGEST_A, DIGEST_B, DIGEST_C = "a" * 64, "b" * 64, "c" * 64
#: A licence as a runner states it: a name on its first line, then pages of terms.
LICENCE = "\n  AN INVENTED COMMUNITY LICENSE  \nVersion 1. Terms that run for pages.\n"
WORKSPACE = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
TAGS = {
    "models": [
        {
            "name": "small:1b",
            "digest": DIGEST_A,
            "details": {"family": "llama", "parameter_size": "1.2B"},
            "capabilities": ["completion", "tools"],
        },
        # An alias of the same weights: one model, known by its digest.
        {
            "name": "another-company-model:latest",
            "digest": DIGEST_A,
            "details": {"family": "llama", "parameter_size": "1.2B"},
            "capabilities": ["completion"],
        },
        {
            "name": "thinker:4b",
            "digest": f"sha256:{DIGEST_B}",
            "details": {"family": "qwen3", "parameter_size": "4.0B"},
            "capabilities": ["completion", "thinking"],
        },
        {
            "name": "embedder:latest",
            "digest": DIGEST_C,
            "details": {"family": "bert"},
            "capabilities": ["embedding"],
        },
        {"name": "no-digest:latest", "digest": "not-a-digest", "capabilities": ["completion"]},
    ]
}


def _cases():
    cases = check_cases()
    role = decision_roles().role(cases["role"])
    return cases, role, role.contract(cases["contract_versions"])


def _judge(role, cases):
    """The host's rule for an answer under the cases' contract versions, as a check is handed it."""
    return lambda case, label, line: answer_outcome(
        role, case, cases["contract_versions"], label, line
    )


def _provider():
    return load_manifest().providers["ollama_local"]


class Runner:
    """Ollama's three reads, answered by script: ``answer(model, case_number)`` returns the
    arguments or raises.
    """

    egress = parse_egress_allowlist(["http://localhost:11434"])

    def __init__(self, *, context: int | None = 131_072, answer=None) -> None:
        self.context = context
        self.answer = answer or (lambda model, payload: _first_label(payload))
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def get_json(self, url, *, headers, timeout):
        self.egress.require(url)
        return HttpResponse(status_code=200, text=json.dumps(TAGS))

    def post_json(self, url, *, headers, payload, timeout):
        self.egress.require(url)
        self.posts.append((url, dict(payload)))
        if url.endswith("/api/show"):
            info = {} if self.context is None else {"llama.context_length": self.context}
            return HttpResponse(
                status_code=200, text=json.dumps({"model_info": info, "license": LICENCE})
            )
        arguments = self.answer(payload["model"], payload)
        return HttpResponse(
            status_code=200,
            text=json.dumps(
                {
                    "model": payload["model"],
                    "message": {"role": "assistant", "content": json.dumps(arguments)},
                    "done": True,
                    "prompt_eval_count": 900,
                    "eval_count": 12,
                }
            ),
        )


def _first_label(payload: dict[str, Any]) -> dict[str, Any]:
    """An answer naming the first offered option that says nothing, with no line."""
    schema = payload["format"]
    labels = schema["properties"]["action"]["enum"]
    plain = [label for label in labels if not label.startswith("say")]
    arguments = {"action": plain[0]}
    if "line" in schema["properties"]:
        arguments["line"] = None
    return arguments


def test_the_runner_s_models_are_known_by_their_weights_with_their_family_and_size():
    models = runner_models(TAGS)
    assert [(m.digest, m.tag, m.family, m.parameter_size) for m in models] == [
        # Name order; an alias of the same digest is one model, named by its first tag in that
        # order.
        (DIGEST_A, "another-company-model:latest", "llama", "1.2B"),
        (DIGEST_C, "embedder:latest", "bert", None),
        (DIGEST_B, "thinker:4b", "qwen3", "4.0B"),
    ]
    assert models[0].model_id == f"local/sha256-{DIGEST_A}"
    assert runner_models({"models": "not a list"}) == () and runner_models(None) == ()


def test_a_person_s_request_needs_the_contract_s_bound_read_at_three_bytes_a_token():
    contract = _cases()[2]
    tokens = role_context_tokens(contract)
    assert tokens % 1_024 == 0
    assert tokens >= int(contract.value("context_bytes_maximum")) / 3 + 2_048 > tokens - 1_024


def test_an_able_model_is_asked_each_case_as_the_role_asks_through_the_runner_s_own_route():
    cases, role, contract = _cases()
    runner = Runner()
    small = runner_models(TAGS)[0]
    record = check_model(
        _provider(),
        runner,
        small,
        role=role,
        contract=contract,
        cases=cases,
        judge=_judge(role, cases),
    )
    assert (record["able"], record["reason"]) == (True, None)
    assert record["model_id"] == f"local/sha256-{DIGEST_A}" and record["served_as"] == small.tag
    assert [case["outcome"] for case in record["cases"]] == ["offered_label", "offered_label"]
    # One read of its context, one unrecorded ask to load it, then each case: all at the runner's
    # own origin.
    assert [url for url, _ in runner.posts] == [
        "http://localhost:11434/api/show",
        "http://localhost:11434/api/chat",
        "http://localhost:11434/api/chat",
        "http://localhost:11434/api/chat",
    ]
    _url, payload = runner.posts[-1]
    assert payload["model"] == small.tag and payload["stream"] is False
    assert payload["options"]["num_ctx"] == role_context_tokens(contract)
    assert payload["format"] == role.choice(cases["cases"][1]).schema()
    # Only a model that reasons is told to stop reasoning.
    assert "think" not in payload


def test_a_model_that_reasons_is_asked_with_reasoning_off():
    cases, role, contract = _cases()
    runner = Runner()
    thinker = next(m for m in runner_models(TAGS) if m.tag == "thinker:4b")
    check_model(
        _provider(),
        runner,
        thinker,
        role=role,
        contract=contract,
        cases=cases,
        judge=_judge(role, cases),
    )
    assert all(
        payload["think"] is False for url, payload in runner.posts if url.endswith("/api/chat")
    )


def test_each_reason_a_model_is_not_able():
    cases, role, contract = _cases()
    small, embedder = runner_models(TAGS)[0], runner_models(TAGS)[1]

    def check(runner, model=small):
        return check_model(
            _provider(),
            runner,
            model,
            role=role,
            contract=contract,
            cases=cases,
            judge=_judge(role, cases),
        )

    # It does not read text: nothing is asked of it.
    text = Runner()
    assert (check(text, embedder)["reason"], text.posts) == ("text", [])
    # It reads less than a person is told here: its context is read and nothing is asked.
    short = Runner(context=4_096)
    record = check(short)
    assert (record["able"], record["reason"], record["context_tokens"]) == (False, "context", 4_096)
    assert [url for url, _ in short.posts] == ["http://localhost:11434/api/show"]
    # It names something not offered, or answers no JSON at all.
    assert check(Runner(answer=lambda model, payload: {"action": "fly away"}))["reason"] == "form"

    def no_json(model, payload):
        raise ValueError

    class Prose(Runner):
        def post_json(self, url, *, headers, payload, timeout):
            if url.endswith("/api/chat"):
                self.posts.append((url, dict(payload)))
                return HttpResponse(
                    status_code=200, text=json.dumps({"message": {"content": "I would rest."}})
                )
            return super().post_json(url, headers=headers, payload=payload, timeout=timeout)

    assert check(Prose())["reason"] == "form"

    # It says a line where its choice says nothing.
    def line_where_none(model, payload):
        arguments = _first_label(payload)
        if "line" in arguments:
            arguments["line"] = "Hello there."
        return arguments

    record = check(Runner(answer=line_where_none))
    assert record["reason"] == "form" and [c["outcome"] for c in record["cases"]] == [
        "offered_label",
        "line_where_none",
    ]

    # It says its line to someone by naming them, which the host does not take.
    def naming(model, payload):
        if "line" not in payload["format"]["properties"]:
            return _first_label(payload)
        labels = payload["format"]["properties"]["action"]["enum"]
        label = next(label for label in labels if label.startswith("say something to C"))
        name = label.removeprefix("say something to ").split(" (")[0]
        return {"action": label, "line": f"Good morning, {name}."}

    record = check(Runner(answer=naming))
    assert record["reason"] == "form" and record["cases"][1]["outcome"] == "line_names_listener"

    # The runner answers the ask with an error: the check could not be made, which is not the form.
    class Failing(Runner):
        def post_json(self, url, *, headers, payload, timeout):
            if url.endswith("/api/chat"):
                return HttpResponse(status_code=500, text=json.dumps({"error": "no room for it"}))
            return super().post_json(url, headers=headers, payload=payload, timeout=timeout)

    record = check(Failing())
    assert record["reason"] == "error" and record["cases"][0]["outcome"] == "not_answered"

    # It took longer than a person has to decide.
    class Slow(Runner):
        def post_json(self, url, *, headers, payload, timeout):
            if url.endswith("/api/chat") and timeout < 60:
                raise TransportError("read timed out", timed_out=True, reached_provider=True)
            return super().post_json(url, headers=headers, payload=payload, timeout=timeout)

    record = check(Slow())
    assert record["reason"] == "slow" and record["cases"][0]["outcome"] == "timed_out"


def test_the_load_ask_is_not_counted_and_its_failure_is_not_a_verdict():
    cases, role, contract = _cases()
    asked: list[float] = []

    class Loading(Runner):
        def post_json(self, url, *, headers, payload, timeout):
            if url.endswith("/api/chat"):
                asked.append(timeout)
                if len(asked) == 1:
                    raise TransportError("loading", reached_provider=True)
            return super().post_json(url, headers=headers, payload=payload, timeout=timeout)

    record = check_model(
        _provider(),
        Loading(),
        runner_models(TAGS)[0],
        role=role,
        contract=contract,
        cases=cases,
        judge=_judge(role, cases),
    )
    assert record["able"] is True
    # The load waits longer than a person; each case waits the role's deadline.
    assert asked[0] > asked[1] == asked[2] == int(contract.value("decision_deadline_ms")) / 1_000


def test_checks_are_kept_by_digest_and_made_one_at_a_time_in_the_background(tmp_path):
    cases, role, contract = _cases()
    store = CheckStore(tmp_path / "local-checks")
    started: list = []
    checked: list[str] = []

    def check(provider, transport, model, **kwargs):
        checked.append(model.digest)
        return check_model(provider, transport, model, **kwargs)

    checks = LocalChecks(
        _provider(),
        Runner(),
        store,
        role=role,
        contract=contract,
        cases=cases,
        judge=_judge(role, cases),
        start=started.append,
        check=check,
    )
    small, embedder, thinker = runner_models(TAGS)
    # Every model is being checked until its record is kept; one worker is started for all of them.
    assert [checks.state(m) for m in (small, embedder, thinker)] == [("checking", None)] * 3
    checks.ensure((small, thinker))
    assert len(started) == 1 and checked == []
    started[0]()
    # The smallest first, so the list fills fastest; one stating no size last.
    assert checked == [small.digest, thinker.digest, embedder.digest]
    assert [checks.state(m) for m in (small, embedder, thinker)] == [
        ("able", None),
        ("not_able", "text"),
        ("able", None),
    ]
    assert sorted(path.name for path in (tmp_path / "local-checks").iterdir()) == sorted(
        f"sha256-{m.digest}.json" for m in (small, embedder, thinker)
    )
    # A kept record answers without checking again.
    checks.ensure((small,))
    assert len(started) == 1


def test_a_record_made_under_other_cases_is_checked_again_and_a_failed_check_keeps_nothing(
    tmp_path,
):
    cases, role, contract = _cases()
    store = CheckStore(tmp_path)
    small = runner_models(TAGS)[0]
    store.write(
        {
            **check_model(
                _provider(),
                Runner(),
                small,
                role=role,
                contract=contract,
                cases=cases,
                judge=_judge(role, cases),
            ),
            "cases_sha256": "other",
        }
    )
    started: list = []

    def broken(*args, **kwargs):
        raise TransportError("the runner went away", reached_provider=False)

    checks = LocalChecks(
        _provider(),
        Runner(),
        store,
        role=role,
        contract=contract,
        cases=cases,
        judge=_judge(role, cases),
        start=started.append,
        check=broken,
    )
    assert checks.state(small) == ("checking", None)
    started[0]()
    assert store.read(small.digest)["cases_sha256"] == "other"
    assert checks.state(small) == ("checking", None) and len(started) == 2


def test_the_liveness_read_keeps_the_runner_s_list_only_while_it_answers():
    provider = _provider()

    class Tags(Runner):
        up = True
        broken = False

        def get_json(self, url, *, headers, timeout):
            if not self.up:
                raise TransportError("refused", reached_provider=False)
            if self.broken:
                raise RuntimeError("the read failed in a way nobody named")
            return super().get_json(url, headers=headers, timeout=timeout)

    runner, now = Tags(), [0.0]
    liveness = LocalLiveness([provider], runner, clock=lambda: now[0])
    assert liveness.catalog(provider.provider_id) is None
    liveness.stopped()
    assert liveness.catalog(provider.provider_id) == TAGS
    runner.up, now[0] = False, 60.0
    liveness.stopped()
    assert liveness.catalog(provider.provider_id) is None
    # A read that fails in a way nobody named keeps none either.
    runner.up, now[0] = True, 120.0
    liveness.stopped()
    assert liveness.catalog(provider.provider_id) == TAGS
    runner.broken, now[0] = True, 180.0
    liveness.stopped()
    assert liveness.catalog(provider.provider_id) is None


def test_the_shipped_cases_are_the_maker_s():
    document = check_cases()
    # The cases, the terms they are asked under and their digest: a new contract version makes the
    # file again, and every kept check under the old one is made again.
    assert document == json.loads(json.dumps(make_local_check_cases.document()))
    assert CASES_PATH.name == "local-check-cases.v1.json"
    role = decision_roles().role(document["role"])
    assert [role.takes_line(case) for case in document["cases"]] == [False, True]


@pytest.mark.parametrize(
    "bad",
    [
        {"profile": "other", "cases": [{}, {}]},
        {"profile": "exulanica.local-check-cases/v1", "cases": [{}]},
    ],
)
def test_a_case_catalog_that_is_not_the_check_s_is_refused(tmp_path, bad):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        check_cases(path)


def _able(model, cases, role, contract):
    """``model``'s kept check, made against a runner that answers every case."""
    return check_model(
        _provider(),
        Runner(),
        model,
        role=role,
        contract=contract,
        cases=cases,
        judge=_judge(role, cases),
    )


def test_a_runner_model_is_named_by_its_family_and_size_or_by_the_name_its_person_gave_it():
    small, embedder, thinker = runner_models(TAGS)
    assert [runner_name(m) for m in (small, embedder, thinker)] == [
        "Llama · 1.2B",
        "Bert",
        "Qwen3 · 4.0B",
    ]
    bare = runner_models({"models": [{"name": "mine:latest", "digest": DIGEST_C}]})[0]
    assert runner_name(bare) == "mine"
    cases, role, contract = _cases()
    spec = runner_spec(small, _able(small, cases, role, contract), provider="ollama_local")
    # The name a person reads is the manifest's one rule, applied to the runner's model.
    manifest = with_runner_models(load_manifest(), [spec])
    assert manifest.model_name(spec.model_id) == "Llama · 1.2B"
    assert spec.served_as == small.tag and spec.model_id == small.model_id
    assert spec.input_usd_per_mtok == spec.output_usd_per_mtok == Decimal(0)
    assert spec.context_window_tokens == role_context_tokens(contract)
    assert dict(spec.answering) == {
        AnsweringMechanism.JSON_SCHEMA: f"local-check:sha256-{DIGEST_A}"
    }
    assert role.chosen.offers(spec)


def test_runner_models_are_added_beside_the_manifest_s_never_in_place_of_one():
    shipped = load_manifest()
    cases, role, contract = _cases()
    small = runner_models(TAGS)[0]
    spec = runner_spec(small, _able(small, cases, role, contract), provider="ollama_local")
    added = with_runner_models(shipped, [spec])
    assert {k: v for k, v in added.models.items() if k != spec.model_id} == dict(shipped.models)
    assert spec.model_id not in shipped.models
    local = next(s for s in shipped.models.values() if s.provider == "ollama_local")
    for bad in (replace(spec, model_id=local.model_id), replace(spec, served_as=None)):
        with pytest.raises(ValueError, match="beside"):
            with_runner_models(shipped, [bad])


def test_only_a_model_the_runner_serves_now_and_a_kept_check_finds_able_is_added(tmp_path):
    cases, role, contract = _cases()
    started: list = []
    checks = LocalChecks(
        _provider(),
        Runner(),
        CheckStore(tmp_path),
        role=role,
        contract=contract,
        cases=cases,
        judge=_judge(role, cases),
        start=started.append,
    )
    manifest = load_manifest()
    # Nothing is offered until a check is kept; asking queues them.
    assert able_specs(manifest, TAGS, checks) == ()
    started[0]()
    small, _embedder, thinker = runner_models(TAGS)
    assert [s.model_id for s in able_specs(manifest, TAGS, checks)] == [
        small.model_id,
        thinker.model_id,
    ]
    # Asked by the name the runner serves the weights by now: renamed, the new name.
    renamed = {"models": [{**TAGS["models"][2], "name": "renamed:4b"}]}
    (spec,) = able_specs(manifest, renamed, checks)
    assert (spec.model_id, spec.served_as) == (thinker.model_id, "renamed:4b")
    # Weights no name serves now are not offered, whatever was checked.
    assert able_specs(manifest, {"models": []}, checks) == ()
    # The manifest's own model on this computer is never offered a second time.
    local = next(s for s in manifest.models.values() if s.provider == "ollama_local")
    shipped_tag = {"models": [{**TAGS["models"][0], "name": f"{local.model_id}:latest"}]}
    assert able_specs(manifest, shipped_tag, checks) == ()


def test_a_chosen_runner_model_is_asked_exactly_as_its_check_asked_it():
    cases, role, contract = _cases()
    thinker = next(m for m in runner_models(TAGS) if m.tag == "thinker:4b")
    checked = Runner()
    record = check_model(
        _provider(),
        checked,
        thinker,
        role=role,
        contract=contract,
        cases=cases,
        judge=_judge(role, cases),
    )
    spec = runner_spec(thinker, record, provider="ollama_local")
    asked = Runner()
    client = ModelClient(
        manifest=with_runner_models(load_manifest(), [spec]),
        transport=asked,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
        local_only=True,
    )
    case = cases["cases"][1]
    result = client.choose(
        role.chosen,
        spec.model_id,
        role.adapter.messages(role, case, AnsweringMechanism.JSON_SCHEMA),
        role.choice(case),
        mechanism=AnsweringMechanism.JSON_SCHEMA,
        prompt_version=role.terms_of(case).prompt_version,
        timeout=20,
        max_tokens=answer_tokens(spec),
    )
    ((url, payload),) = asked.posts
    # The runner's own route, and the very request the check's own ask of this case sent.
    assert url == "http://localhost:11434/api/chat"
    assert payload == checked.posts[-1][1]
    assert payload["think"] is False and payload["options"]["temperature"] == 0
    assert result.label in {option["label"] for option in case["options"]}
    # It costs nothing, and its counts are the runner's.
    call = client.ledger.calls[-1]
    assert call.usd == 0 and (call.prompt_tokens, call.completion_tokens) == (900, 12)
    assert result.call.served_model_id == spec.model_id


def test_a_check_is_told_by_its_slowest_case():
    assert checked_ms({"cases": [{"latency_ms": 86}, {"latency_ms": 2_104}]}) == 2_104
    assert checked_ms({"cases": []}) is None and checked_ms(None) is None


def test_a_runner_s_answer_is_read_as_it_was_given():
    cases, role, contract = _cases()
    small = runner_models(TAGS)[0]
    spec = runner_spec(small, _able(small, cases, role, contract), provider="ollama_local")
    body = {"model": small.tag, "message": {"content": '{"action": "x"'}, "done_reason": "length"}
    read = runner_answer(spec, body)
    # Cut short where the runner says so, so the client never takes half an answer.
    assert read["choices"][0]["finish_reason"] == "length"
    assert read["choices"][0]["message"]["content"] == '{"action": "x"'
    assert read["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    # Named by its weights only where the runner answered for the name it was asked by.
    assert read["model"] == small.model_id
    assert runner_answer(spec, {**body, "model": "another:1b"})["model"] == "another:1b"
    # A runner's model is asked only for a choice by its schema.
    with pytest.raises(ValueError, match="JSON schema"):
        runner_request(spec, {"messages": [], "max_tokens": 512, "tools": []})


def test_a_runner_model_no_name_serves_when_asked_is_unavailable():
    cases, role, contract = _cases()
    small = runner_models(TAGS)[0]
    spec = runner_spec(small, _able(small, cases, role, contract), provider="ollama_local")

    class Gone(Runner):
        def post_json(self, url, *, headers, payload, timeout):
            return HttpResponse(status_code=404, text=json.dumps({"error": "model not found"}))

    client = ModelClient(
        manifest=with_runner_models(load_manifest(), [spec]),
        transport=Gone(),
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
        local_only=True,
    )
    case = cases["cases"][0]
    with pytest.raises(ModelUnavailableError):
        client.choose(
            role.chosen,
            spec.model_id,
            role.adapter.messages(role, case, AnsweringMechanism.JSON_SCHEMA),
            role.choice(case),
            mechanism=AnsweringMechanism.JSON_SCHEMA,
            prompt_version=role.terms_of(case).prompt_version,
            timeout=20,
            max_tokens=answer_tokens(spec),
        )


def test_a_check_that_fails_in_a_way_nobody_named_is_kept_as_not_able(tmp_path):
    cases, role, contract = _cases()
    started: list = []
    calls: list[str] = []

    def broken(provider, transport, model, **kwargs):
        calls.append(model.digest)
        raise RuntimeError("something nobody named, with /a/path in its text")

    checks = LocalChecks(
        _provider(),
        Runner(),
        CheckStore(tmp_path),
        role=role,
        contract=contract,
        cases=cases,
        judge=_judge(role, cases),
        start=started.append,
        check=broken,
    )
    small = runner_models(TAGS)[0]
    assert checks.state(small) == ("checking", None)
    started[0]()
    assert checks.state(small) == ("not_able", "error") and len(started) == 1
    kept = CheckStore(tmp_path).read(small.digest)
    # By the error's kind, never its text.
    assert kept["error"] == "RuntimeError" and "/a/path" not in json.dumps(kept)
    # Kept, so it is not checked again on every list.
    checks.ensure((small,))
    assert calls == [small.digest] and len(started) == 1


# -- offered, chosen and asked by an install ------------------------------------------------------


def _installed(tmp_path):
    """A keyless install that checks its runner's models: a client asking only this computer, over
    the fake runner, whose checks are made when the test says (``started``)."""
    cases, role, contract = _cases()
    runner = Runner()
    client = ModelClient(
        transport=runner,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
        local_only=True,
    )
    started: list = []
    checks = client.local_checks(
        CheckStore(tmp_path / "local-checks"),
        role=role,
        contract=contract,
        cases=cases,
        judge=_judge(role, cases),
        start=started.append,
    )
    services = Services(
        database=None,  # type: ignore[arg-type]
        readonly_database=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        tokens=TokenDirectory(sessions={}),
        executor_shares_the_write_role=True,
        model_client=None,
        choice_client=client,
        local_checks=checks,
    )
    # The liveness read that keeps the runner's list, as any read of the refusals makes it.
    assert "ollama_local" not in client.refusals
    return services, started, client, runner


def test_an_install_offers_its_runner_s_able_models_only_to_the_people_they_were_checked_for(
    tmp_path,
):
    services, started, _client, _runner = _installed(tmp_path)
    engine = check_cases()["engine"]
    shipped = load_manifest().models.keys()
    # Nothing is offered until a check is kept; reading the list queues every model once.
    assert services.workspace_choice_manifest(None, WORKSPACE, engine).models.keys() == shipped
    assert len(started) == 1
    started[0]()
    small, _embedder, thinker = runner_models(TAGS)
    offered = services.workspace_choice_manifest(None, WORKSPACE, engine)
    assert offered.models.keys() - shipped == {small.model_id, thinker.model_id}
    # A society asked under another engine's terms is offered none.
    other = next(e for e in decision_roles().role("society_decision").engines if e != engine)
    assert services.workspace_choice_manifest(None, WORKSPACE, other).models.keys() == shipped
    assert runner_models_api.runner_rows(services, other) == []
    rows = runner_models_api.runner_rows(services, engine)
    assert [(row["name"], row["state"], row["reason"]) for row in rows] == [
        ("Llama · 1.2B", "able", None),
        ("Bert", "not_able", "text"),
        ("Qwen3 · 4.0B", "able", None),
    ]
    assert rows[0]["served_as"] == small.tag and rows[0]["model_id"] == small.model_id
    # The licence as the runner states it: its first line, quoted, never classed.
    assert rows[0]["licence"] == "AN INVENTED COMMUNITY LICENSE"
    # With the numbers a reason is told by.
    deadline = int(_cases()[2].value("decision_deadline_ms"))
    assert (rows[0]["context_tokens"], rows[0]["deadline_ms"]) == (131_072, deadline)


def test_the_models_read_says_what_a_runner_states_of_an_able_model(tmp_path):
    services, started, _client, _runner = _installed(tmp_path)
    rows = runner_models_api.runner_rows(services, check_cases()["engine"])
    assert {row["state"] for row in rows} == {"checking"}
    started[0]()
    role = decision_roles().role("society_decision")
    manifest = services.workspace_choice_manifest(None, WORKSPACE, check_cases()["engine"])
    small = runner_models(TAGS)[0]
    (row,) = [
        m
        for m in offered_models(role, services, manifest=manifest)
        if m["model_id"] == small.model_id
    ]
    assert row["name"] == "Llama · 1.2B" and row["on_this_computer"] is True
    assert (row["source"], row["fresh_rates_required"]) == ("this_computer_check", False)
    assert row["mechanism"] == "json_schema" and row["usd_per_mtok"] == {
        "input": "0",
        "output": "0",
    }
    runner = dict(row["runner"])
    # How long its check's slowest case took, which the row tells.
    assert isinstance(runner.pop("checked_ms"), int)
    assert runner == {
        "family": "llama",
        "size": "1.2B",
        "served_as": small.tag,
        "licence": "AN INVENTED COMMUNITY LICENSE",
    }
    # A shipped model's row says nothing of a runner.
    assert all(
        "runner" not in m
        for m in offered_models(role, services)
        if m["model_id"] in load_manifest().models
    )
    # A choice naming a runner's model is named by its kept check, held or not.
    assert runner_models_api.runner_model_name(services, small.model_id) == "Llama · 1.2B"
    local = next(s for s in load_manifest().models.values() if s.provider == "ollama_local")
    assert runner_models_api.runner_model_name(services, local.model_id) is None


def test_the_host_asks_a_chosen_runner_model_by_the_name_serving_its_weights_now(
    tmp_path, monkeypatch
):
    services, started, client, runner = _installed(tmp_path)
    cases, role, _contract = _cases()
    engine = cases["engine"]
    # A list read queues the checks; then they are made.
    runner_models_api.runner_rows(services, engine)
    started[0]()
    _small, _embedder, thinker = runner_models(TAGS)
    assert (
        runner_models_api.local_execution_source(
            services, WORKSPACE, engine, frozenset({"another"})
        )
        is None
    )
    bound, manifest, digest = runner_models_api.local_execution_source(
        services, WORKSPACE, engine, frozenset({thinker.model_id})
    )
    assert manifest.models.keys() - load_manifest().models.keys() == {thinker.model_id}
    again = runner_models_api.local_execution_source(
        services, WORKSPACE, engine, frozenset({thinker.model_id})
    )
    assert again[2] == digest and len(digest) == 64
    spec = manifest.spec(thinker.model_id)
    case = cases["cases"][1]
    _, prompt_version = services.local_checks.scope

    def ask(prompt: str = prompt_version):
        return bound.choose(
            role.chosen,
            thinker.model_id,
            role.adapter.messages(role, case, AnsweringMechanism.JSON_SCHEMA),
            role.choice(case),
            mechanism=AnsweringMechanism.JSON_SCHEMA,
            prompt_version=prompt,
            timeout=20,
            max_tokens=answer_tokens(spec),
        )

    asked = len(runner.posts)
    # Free of any licence class: a model on a person's own computer is theirs to choose.
    assert ask().label in {option["label"] for option in case["options"]}
    ((url, payload),) = runner.posts[asked:]
    assert url == "http://localhost:11434/api/chat" and payload["model"] == "thinker:4b"
    # Only for the role and prompt it was checked under.
    with pytest.raises(ProviderRefused) as refused:
        ask("another-prompt/v1")
    assert refused.value.reason == "model_binding_scope_mismatch"
    # Its weights served by another name now, or by none: not asked by the old one.
    renamed = {"models": [{**TAGS["models"][2], "name": "renamed:4b"}]}
    monkeypatch.setattr(client, "runner_catalog", lambda provider_id: renamed)
    with pytest.raises(ProviderRefused) as refused:
        ask()
    assert refused.value.reason == "model_binding_stale_or_unavailable"
    assert len(runner.posts) == asked + 1


def test_a_check_that_could_not_be_made_is_made_again_after_six_hours(tmp_path):
    cases, role, contract = _cases()
    store = CheckStore(tmp_path)
    small = runner_models(TAGS)[0]
    at = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    now = [at]
    started: list = []
    checks = LocalChecks(
        _provider(),
        Runner(),
        store,
        role=role,
        contract=contract,
        cases=cases,
        judge=_judge(role, cases),
        start=started.append,
        now=lambda: now[0],
    )
    kept = _able(small, cases, role, contract)
    store.write(
        {
            **kept,
            "able": False,
            "reason": "error",
            "error": "RuntimeError",
            "checked_at": at.isoformat(),
        }
    )
    now[0] = at + timedelta(hours=5, minutes=59)
    assert checks.state(small) == ("not_able", "error") and started == []
    now[0] = at + timedelta(hours=6)
    assert checks.state(small) == ("checking", None) and len(started) == 1
    # Any other verdict stands until the cases, contract or context change.
    store.write({**kept, "checked_at": at.isoformat()})
    assert checks.state(small) == ("able", None)


def test_a_minute_asks_about_only_the_runner_models_it_chose(tmp_path):
    services, started, _client, _runner = _installed(tmp_path)
    engine = check_cases()["engine"]
    _small, _embedder, thinker = runner_models(TAGS)
    # A minute that chose none begins no check: a check begins the first time a list shows a model.
    assert (
        runner_models_api.local_execution_source(services, WORKSPACE, engine, frozenset()) is None
    )
    assert started == []
    # One that chose a model asks about it alone.
    chosen = frozenset({thinker.model_id})
    assert runner_models_api.local_execution_source(services, WORKSPACE, engine, chosen) is None
    started[0]()
    store = tmp_path / "local-checks"
    assert [path.name for path in store.iterdir()] == [f"sha256-{thinker.digest}.json"]
    assert runner_models_api.local_execution_source(services, WORKSPACE, engine, chosen) is not None


def test_an_install_checks_its_runner_s_models_where_it_keeps_its_checks(tmp_path, sockets):
    def built(**extra: str):
        environ = _deployment_environ(
            tmp_path,
            EXULANICA_SPENDING="process",
            EXULANICA_EGRESS_ALLOWLIST='["http://localhost:11434"]',
            **extra,
        )
        with pytest.MonkeyPatch.context() as patch:
            for name, value in environ.items():
                patch.setenv(name, value)
            for name in ("NEBIUS_API_KEY", "EXULANICA_BUDGET_USD", "EXULANICA_BUDGET_MAX_CALLS"):
                patch.delenv(name, raising=False)
            return services_module.build_services(environ)

    checks = built(EXULANICA_LOCAL_CHECKS_DIR=str(tmp_path / "local-checks")).local_checks
    assert checks is not None and checks.provider.provider_id == "ollama_local"
    assert checks.engine == check_cases()["engine"]
    # No directory, nothing checked; an install admitting workspace models asks their source.
    assert built().local_checks is None
    assert (
        built(
            EXULANICA_LOCAL_CHECKS_DIR=str(tmp_path / "local-checks"),
            EXULANICA_WORKSPACE_MODELS="on",
        ).local_checks
        is None
    )
    # Building it opened nothing.
    assert sockets == []
