"""The acceptance scripted-model API in ``scripts/acceptance/scripted_model.py``, without a server.

It may only ever run as an acceptance tool: it must refuse whenever a provider could be reached,
answer strictly from its plan, label itself in readiness without changing anything else there, and
never reach a wheel or an image. The last is a packaging check over the build configuration the
deployment uses, because a test transport a deployment could load would make every model result
ambiguous.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "acceptance" / "scripted_model.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_acceptance_scripted_model", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPTED = _load()


def _plan(tmp_path: Path, **overrides) -> Path:
    plan = {
        "profile": SCRIPTED.PLAN_PROFILE,
        "bounds": {"ceiling_usd": "0.01", "max_calls": 5},
        "rules": [
            {"match": {"contains": "bench"}, "content": "The bench was added."},
            {"match": {"model": "m/one"}, "body": {"custom": True}, "status": 200},
        ],
        **overrides,
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    return path


# -- refusals --------------------------------------------------------------------------------------


def test_every_setting_that_could_reach_a_provider_refuses_the_start():
    manifest = load_manifest()
    credentials = manifest.credential_variables(manifest.roles)
    some_credential = sorted(credentials)[0]

    assert SCRIPTED.provider_settings({}, credentials) == []
    assert SCRIPTED.provider_settings({"NEBIUS_API_KEY": ""}, credentials) == []
    for name in ("NEBIUS_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", some_credential):
        assert SCRIPTED.provider_settings({name: "x"}, credentials) == [name]
    assert SCRIPTED.provider_settings({SCRIPTED.EGRESS_VARIABLE: "https://x"}, credentials) == [
        SCRIPTED.EGRESS_VARIABLE
    ]


def test_build_refuses_a_reachable_provider_before_it_reads_the_plan(tmp_path):
    with pytest.raises(SystemExit, match="provider settings are present: NEBIUS_API_KEY"):
        SCRIPTED.build(tmp_path / "absent.json", {"NEBIUS_API_KEY": "key"})


def test_durable_spending_without_its_witness_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="EXULANICA_SPENDING_WITNESS_DIR"):
        SCRIPTED.build(_plan(tmp_path), {"EXULANICA_SPENDING": "durable"})


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"profile": "other/v1"}, "profile"),
        ({"rules": {"not": "a list"}}, "no rules list"),
        ({"rules": [{"content": "a", "body": {}}]}, "exactly one of content, body, choose"),
        ({"rules": [{"match": {}}]}, "exactly one of content, body, choose"),
        ({"rules": [{"choose": {"containing": "a", "first": True}}]}, "one containing text"),
        ({"rules": [{"choose": "a"}]}, "one containing text"),
        ({"rules": [{"choose": {"containing": []}}]}, "one containing text or a list"),
        ({"rules": [{"choose": {"containing": ["a", 1]}}]}, "one containing text or a list"),
        ({"rules": [{"content": "a", "line": {"text": "Hi.", "for": "say"}}]}, "on a choose rule"),
        ({"rules": [{"choose": {"containing": "a"}, "line": "Hi."}]}, "on a choose rule"),
        ({"rules": [{"choose": {"containing": "a"}, "line": {"text": ""}}]}, "on a choose rule"),
        ({"rules": [{"match": {"role": "vision"}, "content": "a"}]}, "unknown fields"),
        ({"bounds": {"ceiling_usd": "1"}}, "bounds"),
    ],
)
def test_a_plan_that_would_answer_ambiguously_is_refused(tmp_path, overrides, reason):
    with pytest.raises(SystemExit, match=reason):
        SCRIPTED.load_plan(_plan(tmp_path, **overrides))


# -- answers ---------------------------------------------------------------------------------------


def test_the_first_matching_rule_answers_and_an_unmatched_request_fails_like_a_provider(tmp_path):
    plan, _ = SCRIPTED.load_plan(_plan(tmp_path))
    log = tmp_path / "calls.jsonl"
    transport = SCRIPTED.ScriptedTransport(plan, log, HttpResponse)
    headers = {"Authorization": "Bearer scripted-not-a-key"}

    content = transport.post_json(
        "u",
        headers=headers,
        payload={"model": "m/one", "messages": [{"content": "a bench"}]},
        timeout=1,
    )
    custom = transport.post_json(
        "u", headers=headers, payload={"model": "m/one", "messages": []}, timeout=1
    )
    missing = transport.post_json(
        "u", headers=headers, payload={"model": "m/two", "messages": []}, timeout=1
    )

    assert json.loads(content.text)["choices"][0]["message"]["content"] == "The bench was added."
    assert json.loads(content.text)["usage"]["total_tokens"] > 0
    assert json.loads(custom.text) == {"custom": True}
    assert missing.status_code == SCRIPTED.UNMATCHED_STATUS
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [c["rule"] for c in calls] == [0, 1, None]
    assert transport.calls == 3
    assert "Bearer" not in log.read_text()


def _choice(options: list[str], asked: str) -> dict:
    """A request offering ``options`` as the product's choices ask: a forced tool or a schema."""
    schema = {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": options}},
        "required": ["action"],
        "additionalProperties": False,
    }
    if asked == "tool":
        return {
            "model": "m/one",
            "messages": [],
            "tools": [{"type": "function", "function": {"name": "act", "parameters": schema}}],
            "tool_choice": {"type": "function", "function": {"name": "act"}},
        }
    return {
        "model": "m/one",
        "messages": [],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "act", "strict": True, "schema": schema},
        },
    }


def test_a_choose_rule_answers_an_offered_option_the_way_the_request_asks(tmp_path):
    plan, _ = SCRIPTED.load_plan(
        _plan(tmp_path, rules=[{"match": {"model": "m/one"}, "choose": {"containing": " m away"}}])
    )
    log = tmp_path / "calls.jsonl"
    transport = SCRIPTED.ScriptedTransport(plan, log, HttpResponse)
    options = ["wait here a minute", "go to the bench, 12 m away", "go to the stall, 30 m away"]

    by_tool = json.loads(
        transport.post_json("u", headers={}, payload=_choice(options, "tool"), timeout=1).text
    )
    by_schema = json.loads(
        transport.post_json("u", headers={}, payload=_choice(options, "schema"), timeout=1).text
    )
    none_contains = json.loads(
        transport.post_json(
            "u", headers={}, payload=_choice(["stand still", "wait"], "tool"), timeout=1
        ).text
    )
    offers_nothing = transport.post_json(
        "u", headers={}, payload={"model": "m/one", "messages": []}, timeout=1
    )

    (call,) = by_tool["choices"][0]["message"]["tool_calls"]
    assert call["function"]["name"] == "act"
    assert json.loads(call["function"]["arguments"]) == {"action": options[1]}
    assert json.loads(by_schema["choices"][0]["message"]["content"]) == {"action": options[1]}
    assert json.loads(
        none_contains["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    ) == {"action": "stand still"}
    assert offers_nothing.status_code == SCRIPTED.UNMATCHED_STATUS
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [c["chose"] for c in calls] == [options[1], options[1], "stand still", None]


def test_a_choose_rule_takes_its_preferences_in_order(tmp_path):
    # A-122: the knight picks the sword up when offered, else gives it, else waits; the order is
    # the plan's, never the options'.
    plan, _ = SCRIPTED.load_plan(
        _plan(
            tmp_path,
            rules=[
                {
                    "match": {"model": "m/one"},
                    "choose": {"containing": ["pick up the sword", "give the sword to", "wait"]},
                }
            ],
        )
    )
    transport = SCRIPTED.ScriptedTransport(plan, None, HttpResponse)

    def chose(options: list[str]) -> str:
        answer = json.loads(
            transport.post_json("u", headers={}, payload=_choice(options, "tool"), timeout=1).text
        )
        return json.loads(
            answer["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        )["action"]

    assert chose(
        ["wait a minute", "give the sword to knight 2", "pick up the sword, 3 m away"]
    ) == ("pick up the sword, 3 m away")
    assert chose(["wait a minute", "give the sword to knight 2"]) == "give the sword to knight 2"
    assert chose(["rest on the bench", "wait a minute"]) == "wait a minute"
    assert chose(["rest on the bench", "talk to the knight"]) == "rest on the bench"


def test_a_choice_that_takes_a_line_is_answered_with_none_said(tmp_path):
    # A-122: a choice whose options say something requires the line argument, null or a line
    # (exulanica.models.choice); left out, the product refuses the answer and the routine decides.
    plan, _ = SCRIPTED.load_plan(
        _plan(tmp_path, rules=[{"match": {"model": "m/one"}, "choose": {"containing": "wait"}}])
    )
    transport = SCRIPTED.ScriptedTransport(plan, None, HttpResponse)
    for asked in ("tool", "schema"):
        payload = _choice(["say hello", "wait a minute"], asked)
        schema = (
            payload["tools"][0]["function"]["parameters"]
            if asked == "tool"
            else payload["response_format"]["json_schema"]["schema"]
        )
        schema["properties"]["line"] = {"type": ["string", "null"], "maxLength": 80}
        schema["required"] = ["action", "line"]
        answer = json.loads(transport.post_json("u", headers={}, payload=payload, timeout=1).text)
        message = answer["choices"][0]["message"]
        arguments = (
            message["tool_calls"][0]["function"]["arguments"]
            if asked == "tool"
            else message["content"]
        )
        assert json.loads(arguments) == {"action": "wait a minute", "line": None}
    # A rule's line is said only beside an option it is for; beside any other the line is null.
    speaking, _ = SCRIPTED.load_plan(
        _plan(
            tmp_path,
            rules=[
                {
                    "match": {"model": "m/one"},
                    "choose": {"containing": ["say", "wait"]},
                    "line": {"text": "Good morning.", "for": "say"},
                }
            ],
        )
    )
    talker = SCRIPTED.ScriptedTransport(speaking, None, HttpResponse)

    def said(options: list[str]) -> dict:
        payload = _choice(options, "tool")
        schema = payload["tools"][0]["function"]["parameters"]
        schema["properties"]["line"] = {"type": ["string", "null"], "maxLength": 80}
        schema["required"] = ["action", "line"]
        answer = json.loads(talker.post_json("u", headers={}, payload=payload, timeout=1).text)
        return json.loads(answer["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])

    assert said(["wait a minute", "say hello"]) == {"action": "say hello", "line": "Good morning."}
    assert said(["wait a minute", "rest"]) == {"action": "wait a minute", "line": None}
    # A choice that takes no line is answered with its one argument, as before.
    plain = json.loads(
        transport.post_json("u", headers={}, payload=_choice(["wait"], "tool"), timeout=1).text
    )
    assert json.loads(plain["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]) == {
        "action": "wait"
    }


def test_the_transport_declares_no_egress_so_the_client_knows_it_reaches_no_network(tmp_path):
    plan, _ = SCRIPTED.load_plan(_plan(tmp_path))
    assert not hasattr(SCRIPTED.ScriptedTransport(plan, None, HttpResponse), "egress")


def test_readiness_gains_the_label_and_every_other_answer_is_untouched():
    async def application(scope, receive, send):
        body = json.dumps({"status": "ready", "path": scope["path"]}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})

    wrapped = SCRIPTED.ReadinessLabel(application, {"mode": "scripted"})

    def call(path: str) -> tuple[dict, dict]:
        sent: list[dict] = []

        async def send(message):
            sent.append(message)

        asyncio.run(wrapped({"type": "http", "path": path}, None, send))
        headers = dict(sent[0]["headers"])
        return json.loads(sent[1]["body"]), headers

    ready, ready_headers = call("/readyz")
    other, _ = call("/healthz")

    assert ready == {"status": "ready", "path": "/readyz", "acceptance_model": {"mode": "scripted"}}
    assert int(ready_headers[b"content-length"]) == len(json.dumps(ready).encode())
    assert other == {"status": "ready", "path": "/healthz"}


# -- packaging -------------------------------------------------------------------------------------


def test_no_wheel_or_image_can_carry_the_scripted_model():
    """The wheel packages the product alone, the image build context is an allowlist naming no
    ``scripts`` path, and no Dockerfile copies one."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    # The product and the piece formats it shares (exulanica_pieces); nothing else.
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "exulanica",
        "exulanica_pieces",
    ]

    allowlist = (ROOT / ".dockerignore").read_text().splitlines()
    assert allowlist[[line.strip() for line in allowlist].index("*")] == "*"
    admitted = [line[1:] for line in allowlist if line.startswith("!")]
    assert admitted
    assert not [path for path in admitted if path.startswith("scripts")]

    dockerfiles = [ROOT / "Dockerfile", *sorted((ROOT / "deploy").rglob("*Dockerfile"))]
    copied = [
        line.split()[1:]
        for dockerfile in dockerfiles
        for line in dockerfile.read_text().splitlines()
        if line.startswith("COPY ") and "--from=" not in line
    ]
    assert copied
    assert not [paths for paths in copied if any(p.startswith("scripts") for p in paths[:-1])]
