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


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"profile": "other/v1"}, "profile"),
        ({"rules": {"not": "a list"}}, "no rules list"),
        ({"rules": [{"content": "a", "body": {}}]}, "exactly one of content and body"),
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
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["exulanica"]

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
