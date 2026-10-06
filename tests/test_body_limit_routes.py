"""A route that states its own body limit is held to it before its body is read.

The server-wide body limit is sized for photographs; a route whose body is a small document (a
world kind) states a tighter one beside the route, which the body limit applies both ways it
applies its own: a declared length over it is refused before a byte is read, and a body that
declares none is counted as it arrives. A small application here echoes what it received, so a
body the limit lets through is seen to reach the route.
"""

from __future__ import annotations

from collections.abc import Iterator

from exulanica.api.body_limit import BodyLimit
from exulanica.api.routes.world_kinds import BODY_LIMITS
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

ROUTE_LIMIT = 64


async def _echo(request: Request) -> JSONResponse:
    return JSONResponse({"read": len(await request.body())})


def _client(global_limit: int = 1_000) -> TestClient:
    app = Starlette(
        routes=[
            Route("/worlds/kinds/{kind}/worlds", _echo, methods=["GET", "POST"]),
            Route("/worlds/kinds/{kind}/other", _echo, methods=["POST"]),
        ]
    )
    limited = BodyLimit(
        app,
        limit=global_limit,
        routes=(("POST", "/worlds/kinds/{kind}/worlds", ROUTE_LIMIT),),
    )
    return TestClient(limited)


def _chunks(total: int) -> Iterator[bytes]:
    for _ in range(total // 16):
        yield b"x" * 16


def test_a_declared_body_over_a_route_s_own_limit_is_refused_before_it_is_read():
    client = _client()
    refused = client.post("/worlds/kinds/farm/worlds", content=b"x" * (ROUTE_LIMIT + 1))
    assert refused.status_code == 413
    assert refused.json()["code"] == "body_too_large"
    assert f"at most {ROUTE_LIMIT}" in refused.json()["detail"]
    within = client.post("/worlds/kinds/farm/worlds", content=b"x" * ROUTE_LIMIT)
    assert (within.status_code, within.json()) == (200, {"read": ROUTE_LIMIT})


def test_a_body_that_declares_no_length_is_counted_against_the_route_s_limit():
    client = _client()
    refused = client.post("/worlds/kinds/farm/worlds", content=_chunks(4 * ROUTE_LIMIT))
    assert refused.status_code == 413


def test_another_method_or_path_keeps_the_server_wide_limit():
    client = _client()
    body = b"x" * (4 * ROUTE_LIMIT)
    other_path = client.post("/worlds/kinds/farm/other", content=body)
    assert (other_path.status_code, other_path.json()) == (200, {"read": len(body)})
    other_method = client.request("GET", "/worlds/kinds/farm/worlds", content=body)
    assert (other_method.status_code, other_method.json()) == (200, {"read": len(body)})


def test_a_route_s_limit_never_loosens_the_server_wide_one():
    client = _client(global_limit=ROUTE_LIMIT // 2)
    refused = client.post("/worlds/kinds/farm/worlds", content=b"x" * (ROUTE_LIMIT // 2 + 1))
    assert refused.status_code == 413


def test_the_kinds_routes_state_limits_the_application_applies():
    # The application passes these to its body limit (exulanica/api/app.py); a document route's
    # limit is a small fraction of the server-wide one.
    from exulanica.api.body_limit import MAX_BODY_BYTES

    stated = {(method, path): limit for method, path, limit in BODY_LIMITS}
    assert stated[("POST", "/worlds/kinds")] == 131_072
    assert stated[("POST", "/worlds/kinds/{kind}/worlds")] == 16_384
    assert all(limit < MAX_BODY_BYTES // 1000 for limit in stated.values())


def _asgi(limited: BodyLimit, scope: dict[str, object]) -> list[dict[str, object]]:
    """Run one request through the body limit; every message it sends."""
    import anyio

    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    anyio.run(limited, scope, receive, send)
    return sent


def test_behind_a_proxy_prefix_a_route_keeps_its_own_limit():
    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    limited = BodyLimit(
        app, limit=1_000, routes=(("POST", "/worlds/kinds/{kind}/worlds", ROUTE_LIMIT),)
    )
    scope = {
        "type": "http",
        "method": "POST",
        "root_path": "/exulanica",
        "path": "/exulanica/worlds/kinds/farm/worlds",
        "headers": [(b"content-length", str(ROUTE_LIMIT + 1).encode())],
    }
    assert _asgi(limited, scope)[0]["status"] == 413
    within = {**scope, "headers": [(b"content-length", str(ROUTE_LIMIT).encode())]}
    assert _asgi(limited, within)[0]["status"] == 200


def test_the_path_a_route_limit_reads_is_the_one_admission_routes_by():
    from exulanica.api.admission import _route_path
    from exulanica.api.body_limit import route_path

    for root, path in (
        ("", "/worlds/kinds"),
        ("/api", "/api/worlds/kinds"),
        ("/api", "/api"),
        ("/api", "/apiworlds/kinds"),
        ("/api", "/elsewhere/worlds/kinds"),
    ):
        scope = {"type": "http", "root_path": root, "path": path}
        assert route_path(scope) == _route_path(scope)
