"""One process spending under the durable authority, for the race and crash tests.

Run as ``python tests/spending_race_child.py CONFIG.json``. It builds the client the way its
``mode`` says a process of that kind does, waits for the parent's start file, then asks until the
authority refuses, or until its deadline, and writes what happened to ``result``:

*   ``plain``: a client composed with :class:`exulanica.spending.DurableSpending` directly;
*   ``api``: the API's own composition, ``build_services`` with an injected client and
    ``Services.hosted_model`` for the workspace, the policy a route attaches;
*   ``worker``: the derivative worker's, ``worker_model_client`` and the workspace policy the
    caption pass attaches, asking for embeddings.

``kill_at`` stops the process with SIGKILL at one point of its first call: after admission,
after dispatch, after the request is sent, after the reply is received and before it is settled,
after it is settled, or after the witness is written and before the admission commits.
Every request is sent to a scripted transport that appends one line per request to ``sends``,
and answers without a usage report, so each attempt keeps its whole reservation.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from exulanica.db.session import Database
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.spending import SpendingRefused, spending_request_key
from exulanica.models.transport import HttpResponse

MESSAGES = [{"role": "user", "content": "how much is left?"}]


class CountingTransport:
    """Appends one line per request to a file of its own, and answers with no usage."""

    def __init__(self, sends: Path, *, kill_on_send: bool = False, usage: bool = False) -> None:
        self.sends = sends
        self.kill_on_send = kill_on_send
        self.usage = usage
        self.dimensions = load_manifest()[Role.EMBEDDING].primary.embedding_dimensions or 8

    def post_json(self, url, *, headers, payload, timeout) -> HttpResponse:
        with self.sends.open("a") as stream:
            stream.write(json.dumps({"model": payload.get("model"), "pid": os.getpid()}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if self.kill_on_send:
            os.kill(os.getpid(), signal.SIGKILL)
        if "input" in payload:
            body: dict[str, Any] = {
                "model": payload.get("model"),
                "data": [{"embedding": [0.0] * self.dimensions} for _ in payload["input"]],
            }
        else:
            body = {
                "model": payload.get("model"),
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": "OK"}}
                ],
            }
            if self.usage:
                body["usage"] = {"prompt_tokens": 100, "completion_tokens": 200}
        return HttpResponse(status_code=200, text=json.dumps(body))

    def get_json(self, url, *, headers, timeout) -> HttpResponse:
        return HttpResponse(status_code=200, text="[]")


def _kill() -> None:
    os.kill(os.getpid(), signal.SIGKILL)


def _wrap_gate(gate: Any, kill_at: str | None) -> Any:
    """The gate, stopping this process at the named point of its first call."""
    if kill_at not in ("admitted", "dispatched", "received", "settled"):
        return gate

    class Stopping:
        def __init__(self, inner: Any) -> None:
            self.inner = inner
            self.workspace_id = inner.workspace_id

        def admit(self, request):
            ticket = self.inner.admit(request)
            if kill_at == "admitted":
                _kill()
            return ticket

        def dispatch(self, ticket):
            self.inner.dispatch(ticket)
            if kill_at == "dispatched":
                _kill()

        def settle(self, ticket, usage):
            if kill_at == "received":
                _kill()
            self.inner.settle(ticket, usage)
            if kill_at == "settled":
                _kill()

        def release(self, ticket):
            self.inner.release(ticket)

    return Stopping(gate)


class _StoppingSource:
    def __init__(self, inner: Any, kill_at: str | None) -> None:
        self.inner = inner
        self.kill_at = kill_at

    def for_workspace(self, workspace_id: uuid.UUID) -> Any:
        return _wrap_gate(self.inner.for_workspace(workspace_id), self.kill_at)


def _client(transport: CountingTransport) -> ModelClient:
    return ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal(100), max_calls=100_000),
        max_attempts=1,
    )


def _stop_before_commit() -> None:
    """SIGKILL this process the first time an admission writes its witness, before the commit."""
    from exulanica.spending import witness

    original = witness._FileHandle.write

    def write(self, record, *, confirmed):
        original(self, record, confirmed=confirmed)
        if not confirmed:
            _kill()

    witness._FileHandle.write = write  # type: ignore[method-assign]


def _ask(config: dict[str, Any]) -> Any:
    """A function making one call the way this process's composition makes it."""
    from exulanica.spending import DurableSpending, FileSpendingWitness, holder_label

    workspace = uuid.UUID(config["workspace"])
    kill_at = config.get("kill_at")
    transport = CountingTransport(
        Path(config["sends"]), kill_on_send=kill_at == "sent", usage=bool(config.get("usage"))
    )
    database = Database(url=config["database_url"])
    environ = {
        "EXULANICA_DATABASE_URL": config["database_url"],
        "EXULANICA_SPENDING": "durable",
        "EXULANICA_DATA_DIR": config["data_dir"],
    }
    witness_dir = config.get("witness_dir")
    if witness_dir:
        environ["EXULANICA_SPENDING_WITNESS_DIR"] = witness_dir
    if kill_at == "witnessed":
        _stop_before_commit()
    mode = config["mode"]
    if mode == "plain":
        durable = DurableSpending(
            database,
            FileSpendingWitness(Path(witness_dir)) if witness_dir else None,
            holder=holder_label(config.get("label", "race-plain")),
        )
        client = _client(transport).with_spending_source(_StoppingSource(durable, kill_at))

        class Policy:
            workspace_id = workspace

            def admit(self, request):
                return request.texts

        scoped = client.with_policy(Policy())

        def ask() -> None:
            scoped.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="race", use_cache=False)

        return ask
    if mode == "api":
        from exulanica.api.services import build_services

        environ["EXULANICA_API_TOKENS"] = json.dumps(
            {
                secrets.token_hex(24): {
                    "workspace_id": str(workspace),
                    "actor": str(uuid.uuid4()),
                    "permissions": ["model.invoke", "library.read"],
                }
            }
        )
        services = build_services(environ, model_client=_client(transport))
        assert services.spending is not None and services.model_client is not None

        def ask() -> None:
            with services.database.session(workspace) as connection:
                client = services.hosted_model(connection, workspace)
                assert client is not None and client.spending is not None
                client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="race", use_cache=False)

        return ask
    if mode == "worker":
        from exulanica.epistemics.hosted_requests import (
            WorkspaceRequestPolicy,
            borrowing,
            no_place_released,
        )
        from exulanica.ingest.worker_command import worker_model_client

        client = worker_model_client(environ, database, model_client=_client(transport))
        assert client is not None and client.spending_source is not None

        def no_photograph(_connection, _workspace, photographs, _handoff) -> None:
            if photographs:
                raise AssertionError("the race sends no photograph")

        def ask() -> None:
            with database.session(workspace) as connection:
                policy = WorkspaceRequestPolicy(
                    workspace,
                    connection=borrowing(connection),
                    photograph_right=no_photograph,
                    released_places=no_place_released,
                )
                client.with_policy(policy).embed(["a caption"], use_cache=False)

        return ask
    raise AssertionError(mode)


def main(path: str) -> int:
    config = json.loads(Path(path).read_text())
    ask = _ask(config)
    Path(config["result"]).with_suffix(".ready").write_text("ready")
    go = Path(config["go"])
    while not go.exists():
        time.sleep(0.01)
    deadline = time.monotonic() + float(config.get("seconds", 30))
    result: dict[str, Any] = {"pid": os.getpid(), "sent": 0, "refused": {}, "errors": []}
    key = config.get("request_key")
    while time.monotonic() < deadline:
        try:
            if key:
                with spending_request_key(key):
                    ask()
            else:
                ask()
            result["sent"] += 1
        except SpendingRefused as refused:
            result["refused"][refused.reason] = result["refused"].get(refused.reason, 0) + 1
            if refused.reason in ("spending_limit_reached",) or key:
                result["last_refusal"] = {"reason": refused.reason, "detail": refused.detail}
                break
        except Exception as exc:  # recorded, never hidden: the parent asserts there are none
            result["errors"].append(f"{type(exc).__name__}: {exc}"[:300])
            break
        if key or config.get("once"):
            break
    Path(config["result"]).write_text(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
