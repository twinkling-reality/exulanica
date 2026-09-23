"""Fakes for the model-client tests. No test here performs network I/O or spends credits.

The fixtures that wrap these live in ``tests/conftest.py``; the fakes themselves are here so a
test module can import ``chat_body`` and ``model_not_found`` directly rather than reaching
into a conftest.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.models.manifest import Role
from exulanica.models.policy import HostedRequest
from exulanica.models.transport import HttpResponse

CHEAP_FLOOR = 640


def chat_body(
    content: str = "OK",
    *,
    model: str = "test/model",
    finish_reason: str = "stop",
    reasoning_content: str | None = None,
    prompt_tokens: int = 100,
    completion_tokens: int = 200,
    reasoning_tokens: int = 150,
) -> dict[str, Any]:
    """A response body shaped exactly like the archived runtime ones."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    message["reasoning_content"] = reasoning_content
    message["reasoning"] = reasoning_content
    return {
        "id": "chatcmpl-test",
        "model": model,
        "object": "chat.completion",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
            "prompt_cache_hit_tokens": 0,
        },
    }


def model_not_found(model_id: str, *, status: int = 404) -> HttpResponse:
    """What the endpoint returns for an identifier that has been withdrawn."""
    return HttpResponse(
        status_code=status,
        text=json.dumps(
            {
                "error": {
                    "message": f"The model `{model_id}` does not exist",
                    "type": "invalid_request_error",
                }
            }
        ),
    )


class FakeTransport:
    """Scripted transport. Records every request so a test can assert on what was sent."""

    def __init__(self, responses: Sequence[HttpResponse | Exception] | None = None) -> None:
        self.responses: list[HttpResponse | Exception] = list(responses or [])
        self.requests: list[dict[str, Any]] = []
        self.gets: list[str] = []
        #: When set, consulted by model id instead of popping the queue in order.
        self.by_model: dict[str, HttpResponse] = {}
        self.default: HttpResponse | None = None

    @property
    def models_called(self) -> list[str]:
        return [r["payload"].get("model") for r in self.requests]

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> HttpResponse:
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        model_id = payload.get("model")
        if model_id in self.by_model:
            return self.by_model[model_id]
        if self.responses:
            nxt = self.responses.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        if self.default is not None:
            return self.default
        return HttpResponse(status_code=200, text=json.dumps(chat_body(model=str(model_id))))

    def get_json(self, url: str, *, headers: Mapping[str, str], timeout: float) -> HttpResponse:
        self.gets.append(url)
        if self.responses:
            nxt = self.responses.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        return HttpResponse(status_code=200, text="[]")


class RecordingPolicy:
    """A hosted-request policy for tests whose requests carry nothing of an account holder's.

    Admits every request unchanged and keeps each one it judged, so a test can read what the
    client's policy was shown. Product code has no such policy: it attaches a workspace's rules,
    and ``BenchmarkInputs`` is for scripts whose inputs carry no account holder's data.
    """

    def __init__(self) -> None:
        self.requests: list[HostedRequest] = []

    def admit(self, request: HostedRequest) -> Sequence[str]:
        self.requests.append(request)
        return request.texts


CHEAP = Role.REASONING_CHEAP
VISION = Role.VISION
EMBEDDING = Role.EMBEDDING
