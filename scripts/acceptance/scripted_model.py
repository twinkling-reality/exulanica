"""The acceptance API with a scripted model: product code, a test transport, nothing else changed.

    <worktree>/.venv/bin/python scripts/acceptance/scripted_model.py PLAN.json PORT

Serves ``exulanica.api.app:create_app`` on 127.0.0.1 with one change: the model client's transport
answers from a plan instead of a network. Everything a model call passes through in production
still runs, in order: the role routing and manifest, the hosted request policy attached per
workspace, the budget authority, receipts and replay. It exists so an acceptance run can drive
model-shaped paths (a Companion answer, a person's decision, a comparison arm) over real processes
without a provider, a key or money. Its results establish mechanics only, never model quality.

It lives under ``scripts/acceptance`` and nowhere else. The wheel packages only ``exulanica`` and
every image's build context is an allowlist that names no ``scripts`` path, which
``tests/test_acceptance_scripted_model.py`` checks, so a deployment cannot load it.

It refuses to start, before building anything, when any provider credential the manifest names,
any ``NEBIUS_``, ``OPENAI_`` or ``ANTHROPIC_`` variable or an egress allowlist is set: a scripted
process that could also reach a provider would make every result ambiguous. Its budget is the
durable spending authority when ``EXULANICA_SPENDING=durable`` is set, which ``build_services``
attaches itself, and otherwise the plan's explicit ``BudgetGuard`` bounds.

The plan (``profile`` ``q10-scripted-model-plan/v1``) is an ordered list of rules. A request takes
the first rule whose every ``match`` field holds: ``model`` equals the payload's model and
``contains`` is a substring of its serialized messages. A rule answers ``content`` wrapped as a
chat completion, or a whole provider ``body``, with an optional ``status``. A request no rule
matches is answered 500, as an unavailable provider would be, so the product's own fallback runs.
Every request is appended to ``EXULANICA_SCRIPTED_MODEL_LOG`` as one JSON line holding the model,
the matched rule and the payload's digest, never headers. ``/readyz`` answers with an added
``acceptance_model`` member naming the mode and the plan's digest; the application's own answer is
otherwise unchanged, because the member is added by wrapping the application, not in it.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

PLAN_PROFILE = "q10-scripted-model-plan/v1"
#: Every variable whose presence means a provider could be reached.
PROVIDER_PREFIXES = ("NEBIUS_", "OPENAI_", "ANTHROPIC_")
EGRESS_VARIABLE = "EXULANICA_EGRESS_ALLOWLIST"
LOG_VARIABLE = "EXULANICA_SCRIPTED_MODEL_LOG"
DURABLE_SPENDING = ("EXULANICA_SPENDING", "durable")
#: What a request no rule matches is answered with.
UNMATCHED_STATUS = 500
#: The only address the scripted API listens on.
LOOPBACK = "127.0.0.1"
#: The name the readiness answer carries the mode under.
READINESS_MEMBER = "acceptance_model"


class Refused(SystemExit):
    """The scripted API will not start, and says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"scripted-model refused: {reason}")


def provider_settings(
    environ: Mapping[str, str], credential_variables: frozenset[str]
) -> list[str]:
    """Every set variable that could let this process reach a provider, by name."""
    named = {
        name
        for name, value in environ.items()
        if value and (name.startswith(PROVIDER_PREFIXES) or name == EGRESS_VARIABLE)
    }
    named |= {name for name in credential_variables if environ.get(name)}
    return sorted(named)


def load_plan(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    plan = json.loads(raw)
    if plan.get("profile") != PLAN_PROFILE:
        raise Refused(f"the plan's profile is {plan.get('profile')!r}, not {PLAN_PROFILE}")
    rules = plan.get("rules")
    if not isinstance(rules, list):
        raise Refused("the plan states no rules list")
    for index, rule in enumerate(rules):
        if ("content" in rule) == ("body" in rule):
            raise Refused(f"rule {index} must answer with exactly one of content and body")
        unknown = set(rule.get("match", {})) - {"model", "contains"}
        if unknown:
            raise Refused(f"rule {index} matches on unknown fields {sorted(unknown)}")
    bounds = plan.get("bounds") or {}
    if not {"ceiling_usd", "max_calls"} <= set(bounds):
        raise Refused("the plan states no ceiling_usd and max_calls bounds")
    return plan, hashlib.sha256(raw).hexdigest()


def completion(content: str, model: str) -> dict[str, Any]:
    """A chat completion shaped as the provider's are, with usage so accounting has numbers."""
    return {
        "id": "chatcmpl-scripted",
        "model": model,
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


class ScriptedTransport:
    """The model transport, answering from the plan. It carries no egress allowlist, which is how
    the client knows it reaches no network (``exulanica.models.client``)."""

    def __init__(self, plan: Mapping[str, Any], log: Path | None, response_type: Any) -> None:
        self.rules = list(plan["rules"])
        self.log = log
        self.response_type = response_type
        self.calls = 0
        self._lock = threading.Lock()

    def match(self, payload: Mapping[str, Any]) -> int | None:
        model = payload.get("model")
        messages = json.dumps(payload.get("messages", []), sort_keys=True)
        for index, rule in enumerate(self.rules):
            wanted = rule.get("match", {})
            if "model" in wanted and wanted["model"] != model:
                continue
            if "contains" in wanted and wanted["contains"] not in messages:
                continue
            return index
        return None

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> Any:
        del url, headers, timeout
        index = self.match(payload)
        model = str(payload.get("model"))
        with self._lock:
            self.calls += 1
            if self.log is not None:
                with self.log.open("a") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "call": self.calls,
                                "model": model,
                                "rule": index,
                                "payload_sha256": hashlib.sha256(
                                    json.dumps(payload, sort_keys=True).encode()
                                ).hexdigest(),
                            }
                        )
                        + "\n"
                    )
        if index is None:
            body = {"error": {"message": "no scripted rule matches this request"}}
            return self.response_type(status_code=UNMATCHED_STATUS, text=json.dumps(body))
        rule = self.rules[index]
        body = rule["body"] if "body" in rule else completion(str(rule["content"]), model)
        return self.response_type(status_code=int(rule.get("status", 200)), text=json.dumps(body))

    def get_json(self, url: str, *, headers: Mapping[str, str], timeout: float) -> Any:
        del url, headers, timeout
        return self.response_type(status_code=200, text=json.dumps({"data": []}))


class ReadinessLabel:
    """Adds ``acceptance_model`` to the ``/readyz`` JSON answer, wrapping the application."""

    def __init__(self, app: Any, label: Mapping[str, Any]) -> None:
        self.app = app
        self.label = dict(label)

    async def __call__(self, scope: Mapping[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/readyz":
            await self.app(scope, receive, send)
            return
        start: dict[str, Any] = {}
        chunks: list[bytes] = []

        async def capture(message: Mapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                start.update(message)
                return
            chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            body = b"".join(chunks)
            try:
                document = json.loads(body)
                document[READINESS_MEMBER] = self.label
                body = json.dumps(document).encode()
            except (ValueError, TypeError):
                pass
            headers = [
                (name, value)
                for name, value in start.get("headers", [])
                if name.lower() != b"content-length"
            ]
            headers.append((b"content-length", str(len(body)).encode()))
            await send({**start, "headers": headers})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, capture)


def build(plan_path: Path, environ: Mapping[str, str] | None = None) -> Any:
    """The wrapped application, or a refusal before anything is built."""
    environ = os.environ if environ is None else environ
    from exulanica.models.manifest import load_manifest

    manifest = load_manifest()
    reachable = provider_settings(environ, manifest.credential_variables(manifest.roles))
    if reachable:
        raise Refused(f"provider settings are present: {', '.join(reachable)}")
    plan, digest = load_plan(plan_path)

    from exulanica.api.app import create_app
    from exulanica.api.services import build_services
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.transport import HttpResponse

    log = Path(environ[LOG_VARIABLE]) if environ.get(LOG_VARIABLE) else None
    transport = ScriptedTransport(plan, log, HttpResponse)
    durable = environ.get(DURABLE_SPENDING[0]) == DURABLE_SPENDING[1]
    budget = (
        None
        if durable
        else BudgetGuard(
            ceiling_usd=Decimal(str(plan["bounds"]["ceiling_usd"])),
            max_calls=int(plan["bounds"]["max_calls"]),
        )
    )
    client = ModelClient(
        api_key={
            provider.provider_id: "scripted-not-a-key" for provider in manifest.providers.values()
        },
        transport=transport,
        budget=budget,
    )
    app = create_app(build_services(environ, model_client=client))
    label = {
        "mode": "scripted",
        "plan_sha256": digest,
        "budget": "durable" if durable else "plan-bounds",
        "results_establish": "mechanics only",
    }
    return ReadinessLabel(app, label)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        raise Refused("usage: scripted_model.py PLAN.json PORT")
    application = build(Path(arguments[0]))
    import uvicorn

    uvicorn.run(application, host=LOOPBACK, port=int(arguments[1]), log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
