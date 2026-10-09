"""Admission: work refused before it starts, slots given back on every path, health never queued.

What these hold, and the order they hold it in:

*   **The settings** are refused at startup by name, like the society settings.
*   **A full class is refused before anything is spent**: no body read, no route, no connection.
*   **A slot comes back** after a response, a route that raised and a client that left mid-body.
*   **Liveness and readiness answer** while every admitted slot and every request thread is held.
*   **A workspace's share** refuses that workspace and nobody else.
*   **A stalled body** is answered 408 and its slot returns.
*   **The permission floor never opens a connection on the event loop**, on any path it takes.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid

import anyio
import anyio.to_thread
import pytest
from exulanica.api import admission as admission_module
from exulanica.api import dependencies, permissions
from exulanica.api.admission import (
    CAPACITY_ROUTES,
    REQUESTS,
    STREAMS,
    UPLOADS,
    Admission,
    AdmissionSettingRefused,
    AdmissionSettings,
    CapacityDeclarationError,
    CapacityRefused,
    require_capacity_declaration,
)
from exulanica.api.body_limit import MAX_BODY_BYTES
from exulanica.api.routes import workspace_assets as workspace_assets_routes
from exulanica.db.session import Database

from account_fixtures import account_role as account_role
from asgi_requests import Exchange
from capacity_support import FIRST_TOKEN, SECOND_TOKEN, auth, serve

pytestmark = pytest.mark.postgres

#: A route that reads a JSON body before its caller is resolved, so a stalled body holds its slot.
_BODY_ROUTE = "/world/versions"


@pytest.fixture
def served(tmp_path, repository, spine_schema, monkeypatch):
    return serve(tmp_path, repository, spine_schema, monkeypatch)


# -- the settings -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("environ", "code", "variable"),
    [
        ({"EXULANICA_API_REQUESTS": "twelve"}, "admission_setting_not_integer", "API_REQUESTS"),
        ({"EXULANICA_API_REQUESTS": "-3"}, "admission_setting_not_integer", "API_REQUESTS"),
        ({"EXULANICA_API_STREAMS": "0"}, "admission_setting_out_of_bounds", "API_STREAMS"),
        ({"EXULANICA_API_DECODES": "65"}, "admission_setting_out_of_bounds", "API_DECODES"),
        (
            {"EXULANICA_API_WORKSPACE_UPLOADS": "3"},
            "admission_share_exceeds_limit",
            "API_WORKSPACE_UPLOADS",
        ),
        ({"EXULANICA_API_THREADS": "20"}, "admission_threads_too_few", "API_THREADS"),
    ],
)
def test_a_malformed_or_unworkable_setting_is_refused_by_name(environ, code, variable):
    with pytest.raises(AdmissionSettingRefused) as refused:
        AdmissionSettings.from_env(environ)
    assert refused.value.code == code
    assert refused.value.variable == f"EXULANICA_{variable}"


def test_absent_settings_are_the_declared_defaults_and_present_ones_are_read():
    assert AdmissionSettings.from_env({}) == AdmissionSettings()
    read = AdmissionSettings.from_env(
        {"EXULANICA_API_STREAMS": "16", "EXULANICA_API_UPLOADS": " 3 "}
    )
    assert (read.streams, read.uploads) == (16, 3)


def test_a_declaration_naming_a_route_the_application_does_not_serve_is_refused(served):
    app = served.app()
    require_capacity_declaration(app)
    with pytest.raises(CapacityDeclarationError, match=r"GET /formation/\{nothing\}"):
        require_capacity_declaration(app, {("GET", "/formation/{nothing}"): STREAMS})
    assert ("GET", "/formation/{batch_id}") in CAPACITY_ROUTES


# -- refused before anything is spent ---------------------------------------------------------


def test_a_full_class_is_refused_before_its_body_is_read_or_a_connection_opened(served):
    app = served.app(requests=1, workspace_requests=1, threads=8)
    # A body that stalls after its first piece: admitted, and held there before any caller is
    # resolved, so it holds the one requests slot and nothing else.
    holder = Exchange(
        app, "POST", _BODY_ROUTE, headers=auth(FIRST_TOKEN), body=[b"{"], hold_body=True
    )
    refused = Exchange(
        app,
        "POST",
        _BODY_ROUTE,
        headers=[*auth(FIRST_TOKEN), (b"content-length", b"2")],
        body=[b"{}"],
    )
    observed: dict[str, int] = {}

    async def main() -> None:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as group:
                group.start_soon(holder.run)
                await _until(
                    lambda: app.state.admission.snapshot()["classes"][REQUESTS]["in_flight"] == 1
                )
                observed["before"] = await anyio.to_thread.run_sync(served.backends)
                group.start_soon(refused.run)
                await refused.done.wait()
                observed["after"] = await anyio.to_thread.run_sync(served.backends)
                holder.leave()

    anyio.run(main)
    assert refused.status == 503
    assert refused.json() == {
        "code": "capacity_exhausted",
        "detail": refused.json()["detail"],
        "capacity": "requests",
        "retry_after_seconds": 1,
    }
    assert refused.response_headers["retry-after"] == "1"
    # The refused request declared a body, so the connection ends with the answer, after the body
    # was read and thrown away so that the client meets the answer rather than a reset.
    assert refused.response_headers["connection"] == "close"
    assert refused._sent == 1
    assert app.state.admission.snapshot()["refusal_drains"]["drained"] == 1
    # It opened no connection.
    assert observed["after"] == observed["before"]
    counts = app.state.admission.snapshot()["classes"][REQUESTS]
    assert (counts["in_flight"], counts["refused"]) == (0, 1)


def test_an_asset_upload_holds_the_upload_class_a_photograph_upload_waits_for(served):
    # Both bodies are multipart and spooled before any route runs, so an asset admission takes an
    # upload's slot and its 600 second body bound, never an ordinary request's.
    app = served.app(requests=1, workspace_requests=1, uploads=1, workspace_uploads=1, threads=8)
    holder = Exchange(
        app,
        "POST",
        "/workspace-assets",
        headers=[*auth(FIRST_TOKEN), (b"content-type", b"multipart/form-data; boundary=held")],
        body=[b"--held\r\n"],
        hold_body=True,
    )
    refused = Exchange(
        app,
        "POST",
        "/intake",
        headers=[*auth(SECOND_TOKEN), (b"content-length", b"2")],
        body=[b"--"],
    )
    held: dict[str, int] = {}

    async def main() -> None:
        with anyio.fail_after(20):
            async with anyio.create_task_group() as group:
                group.start_soon(holder.run)
                await _until(
                    lambda: app.state.admission.snapshot()["classes"][UPLOADS]["in_flight"] == 1
                )
                held.update(
                    {
                        name: counts["in_flight"]
                        for name, counts in app.state.admission.snapshot()["classes"].items()
                    }
                )
                group.start_soon(refused.run)
                await refused.done.wait()
                holder.leave()

    anyio.run(main)
    assert held[REQUESTS] == 0
    assert refused.status == 503
    assert (refused.json()["code"], refused.json()["capacity"]) == ("capacity_exhausted", "uploads")
    assert refused.response_headers["retry-after"] == "10"
    # Its body was read only to be thrown away (tests/test_admission_refusal_drain.py).
    assert refused._sent == 1
    counts = app.state.admission.snapshot()["classes"][UPLOADS]
    assert (counts["in_flight"], counts["refused"]) == (0, 1)


def test_an_asset_upload_is_authenticated_and_held_to_its_share_before_its_body_is_read(served):
    # The route reads its own body, so the caller is authenticated and the workspace's upload share
    # claimed before any of it is read: each refusal below is answered while its body is still
    # arriving, which a route the framework parsed first could not do.
    # Three upload slots, so each request below meets its own refusal rather than a full class.
    app = served.app(requests=2, workspace_requests=1, uploads=3, workspace_uploads=1, threads=9)
    multipart = (b"content-type", b"multipart/form-data; boundary=held")
    holder = Exchange(
        app,
        "POST",
        "/workspace-assets",
        headers=[*auth(FIRST_TOKEN), multipart],
        body=[b"--held\r\n"],
        hold_body=True,
    )
    again = Exchange(
        app,
        "POST",
        "/workspace-assets",
        headers=[*auth(FIRST_TOKEN), multipart],
        body=[b"--held\r\n"],
        hold_body=True,
    )
    stranger = Exchange(
        app, "POST", "/workspace-assets", headers=[multipart], body=[b"--held\r\n"], hold_body=True
    )
    read_when_answered: dict[str, int] = {}

    async def main() -> None:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as group:
                group.start_soon(holder.run)
                # It reads its first piece only once its share is claimed, then waits for more.
                await _until(lambda: holder._sent == 1)
                group.start_soon(again.run)
                group.start_soon(stranger.run)
                await again.started.wait()
                read_when_answered["again"] = again._sent
                await stranger.started.wait()
                read_when_answered["stranger"] = stranger._sent
                for exchange in (holder, again, stranger):
                    exchange.leave()

    anyio.run(main)
    assert again.status == 429
    assert again.json()["code"] == "workspace_capacity_exhausted"
    assert again.json()["capacity"] == "uploads"
    assert stranger.status == 401
    assert read_when_answered == {"again": 0, "stranger": 0}


def test_a_photograph_upload_is_authenticated_and_held_to_its_share_before_its_body_is_read(served):
    # As an asset upload: the route reads its own body, so each refusal below is answered while its
    # body is still arriving, which a route the framework parsed first could not do.
    app = served.app(requests=2, workspace_requests=1, uploads=3, workspace_uploads=1, threads=9)
    multipart = (b"content-type", b"multipart/form-data; boundary=held")
    holder = Exchange(
        app,
        "POST",
        "/intake",
        headers=[*auth(FIRST_TOKEN), multipart],
        body=[b"--held\r\n"],
        hold_body=True,
    )
    again = Exchange(
        app,
        "POST",
        "/intake",
        headers=[*auth(FIRST_TOKEN), multipart],
        body=[b"--held\r\n"],
        hold_body=True,
    )
    stranger = Exchange(
        app, "POST", "/intake", headers=[multipart], body=[b"--held\r\n"], hold_body=True
    )
    read_when_answered: dict[str, int] = {}

    async def main() -> None:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as group:
                group.start_soon(holder.run)
                await _until(lambda: holder._sent == 1)
                group.start_soon(again.run)
                group.start_soon(stranger.run)
                await again.started.wait()
                read_when_answered["again"] = again._sent
                await stranger.started.wait()
                read_when_answered["stranger"] = stranger._sent
                for exchange in (holder, again, stranger):
                    exchange.leave()

    anyio.run(main)
    assert (again.status, again.json()["code"]) == (429, "workspace_capacity_exhausted")
    assert again.json()["capacity"] == "uploads"
    assert stranger.status == 401
    assert read_when_answered == {"again": 0, "stranger": 0}


def test_an_asset_upload_over_its_routes_limit_is_refused_before_its_body_is_read(served):
    # The server-wide limit is sized for photographs; an asset upload's own is one asset and one
    # declaration at their bounds, with the framing around them.
    app = served.app(requests=2, workspace_requests=1, uploads=2, workspace_uploads=1, threads=8)
    over = Exchange(
        app,
        "POST",
        "/workspace-assets",
        headers=[
            *auth(FIRST_TOKEN),
            (b"content-type", b"multipart/form-data; boundary=held"),
            (b"content-length", str(workspace_assets_routes.UPLOAD_BODY_MAXIMUM + 1).encode()),
        ],
        body=[b"--held\r\n"],
        hold_body=True,
    )
    read_when_answered: dict[str, int] = {}

    async def main() -> None:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as group:
                group.start_soon(over.run)
                await over.started.wait()
                read_when_answered["over"] = over._sent
                over.leave()

    anyio.run(main)
    assert over.status == 413
    assert over.json()["code"] == "body_too_large"
    assert read_when_answered == {"over": 0}
    assert workspace_assets_routes.UPLOAD_BODY_MAXIMUM < MAX_BODY_BYTES


def test_a_slot_comes_back_after_success_failure_and_a_client_that_left(served):
    app = served.app()

    async def main() -> None:
        with anyio.fail_after(10):
            await walk()

    async def walk() -> None:
        ok = Exchange(app, "GET", "/formation", headers=auth(FIRST_TOKEN))
        missing = Exchange(app, "GET", f"/formation/{uuid.uuid4()}", headers=auth(FIRST_TOKEN))
        unauthenticated = Exchange(app, "GET", "/formation")
        left = Exchange(
            app, "POST", _BODY_ROUTE, headers=auth(FIRST_TOKEN), body=[b"{"], hold_body=True
        )
        async with anyio.create_task_group() as group:
            for exchange in (ok, missing, unauthenticated, left):
                group.start_soon(exchange.run)
            await ok.done.wait()
            await missing.done.wait()
            await unauthenticated.done.wait()
            left.leave()
        assert (ok.status, missing.status, unauthenticated.status) == (200, 404, 401)

    anyio.run(main)
    snapshot = app.state.admission.snapshot()
    assert all(held["in_flight"] == 0 for held in snapshot["classes"].values())
    assert snapshot["classes"][REQUESTS]["admitted"] == 3
    assert snapshot["classes"][STREAMS]["admitted"] == 1


# -- health never waits for the work it reports on ------------------------------------------


def test_liveness_and_readiness_answer_while_every_slot_and_request_thread_is_held(served):
    app = served.app(requests=1, workspace_requests=1, threads=8)
    holder = Exchange(
        app, "POST", _BODY_ROUTE, headers=auth(FIRST_TOKEN), body=[b"{"], hold_body=True
    )
    live = Exchange(app, "GET", "/healthz")
    ready = Exchange(app, "GET", "/readyz")

    async def main() -> None:
        limiter = anyio.to_thread.current_default_thread_limiter()
        borrowers = [object() for _ in range(int(limiter.total_tokens))]
        for borrower in borrowers:
            await limiter.acquire_on_behalf_of(borrower)
        try:
            async with anyio.create_task_group() as group:
                group.start_soon(holder.run)
                await _until(
                    lambda: app.state.admission.snapshot()["classes"][REQUESTS]["in_flight"] == 1
                )
                with anyio.fail_after(10):
                    group.start_soon(live.run)
                    group.start_soon(ready.run)
                    await live.done.wait()
                    await ready.done.wait()
                holder.leave()
        finally:
            for borrower in borrowers:
                limiter.release_on_behalf_of(borrower)

    anyio.run(main)
    assert (live.status, live.json()) == (200, {"status": "alive"})
    # Answered, with every check it makes. Whether the checks pass is the harness's business: its
    # throwaway schema records no migrations, so the schema check says so here.
    body = ready.json()
    assert "database" in body["checks"] and "checked_at" in body
    assert body["capacity"]["classes"][REQUESTS] == {"limit": 1, "workspace_share": 1}


def test_concurrent_readiness_probes_share_one_evaluation(served, monkeypatch):
    from exulanica.api.routes import health

    app = served.app()
    evaluations: list[float] = []
    original = health._evaluate

    def slow(request):
        evaluations.append(1.0)
        threading.Event().wait(0.3)
        return original(request)

    monkeypatch.setattr(health, "_evaluate", slow)
    probes = [Exchange(app, "GET", "/readyz") for _ in range(12)]

    async def main() -> None:
        async with anyio.create_task_group() as group:
            for probe in probes:
                group.start_soon(probe.run)

    anyio.run(main)
    assert len(evaluations) == 1
    assert len({probe.status for probe in probes}) == 1
    assert len({probe.json()["checked_at"] for probe in probes}) == 1
    # Nobody else asking: a probe on its own gets an evaluation of its own.
    alone = Exchange(app, "GET", "/readyz")
    anyio.run(alone.run)
    assert len(evaluations) == 2


def test_readiness_shows_limits_and_only_an_operator_reads_the_counts(served, monkeypatch):
    """Readiness is unauthenticated, so what is in use, other workspaces' activity, is not in it."""
    app = served.app()
    held = Exchange(app, "GET", "/formation", headers=auth(FIRST_TOKEN))
    ready = Exchange(app, "GET", "/readyz")
    counts = Exchange(app, "GET", "/operations/capacity", headers=auth(SECOND_TOKEN))
    anonymous = Exchange(app, "GET", "/operations/capacity")

    async def main() -> None:
        for exchange in (held, ready, counts, anonymous):
            await exchange.run()

    anyio.run(main)
    limits = ready.json()["capacity"]
    assert limits == {
        "per_process": True,
        "threads": 40,
        "classes": {
            "requests": {"limit": 24, "workspace_share": 12},
            "uploads": {"limit": 2, "workspace_share": 1},
            "streams": {"limit": 128, "workspace_share": 8},
        },
        "decodes": {"limit": limits["decodes"]["limit"]},
    }
    assert counts.status == 200
    document = counts.json()
    # The read itself is a request in flight; the earlier one from another workspace is counted.
    assert document["classes"][REQUESTS]["in_flight"] == 1
    assert document["classes"][REQUESTS]["admitted"] == 2
    assert document["workspace_in_flight"] == {"requests": 1, "uploads": 0, "streams": 0}
    assert {"limit", "in_use", "peak", "waited", "refused"} <= set(document["decodes"])
    assert str(served.first) not in counts.text and str(served.second) not in counts.text
    assert anonymous.status == 401


# -- a workspace's share ----------------------------------------------------------------------


def test_a_workspace_at_its_share_is_refused_and_another_workspace_is_not(served):
    app = served.app(streams=4, workspace_streams=1)
    batch = _open_batch(served, served.first)
    other = _open_batch(served, served.second)
    first = Exchange(app, "GET", f"/formation/{batch}", headers=auth(FIRST_TOKEN))
    again = Exchange(app, "GET", f"/formation/{batch}", headers=auth(FIRST_TOKEN))
    elsewhere = Exchange(app, "GET", f"/formation/{other}", headers=auth(SECOND_TOKEN))

    async def main() -> None:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as group:
                group.start_soon(first.run)
                await first.started.wait()
                group.start_soon(again.run)
                group.start_soon(elsewhere.run)
                await again.started.wait()
                await elsewhere.started.wait()
                for exchange in (first, again, elsewhere):
                    exchange.leave()

    anyio.run(main)
    assert (first.status, elsewhere.status) == (200, 200)
    assert again.status == 429
    assert again.json()["code"] == "workspace_capacity_exhausted"
    assert again.json()["capacity"] == "streams"
    assert again.response_headers["retry-after"] == "5"
    assert str(served.second) not in again.text
    counts = app.state.admission.snapshot()
    assert counts["classes"][STREAMS]["refused_workspace"] == 1
    assert counts["classes"][STREAMS]["in_flight"] == 0


def test_a_ticket_claimed_twice_for_one_workspace_counts_once():
    admission = Admission(AdmissionSettings(requests=2, workspace_requests=1))
    workspace = uuid.uuid4()
    ticket = admission.try_acquire(REQUESTS)
    assert ticket is not None
    admission.claim_workspace(ticket, workspace)
    admission.claim_workspace(ticket, workspace)
    second = admission.try_acquire(REQUESTS)
    assert second is not None
    with pytest.raises(CapacityRefused) as refused:
        admission.claim_workspace(second, workspace)
    assert (refused.value.status, refused.value.code) == (429, "workspace_capacity_exhausted")
    admission.release(second)
    admission.release(ticket)
    admission.release(ticket)
    assert admission.snapshot()["classes"][REQUESTS]["in_flight"] == 0


# -- bodies have deadlines --------------------------------------------------------------------


def test_a_stalled_body_is_answered_408_and_its_slot_returns(served, monkeypatch):
    monkeypatch.setattr(admission_module, "BODY_IDLE_SECONDS", 0.3)
    app = served.app()
    stalled = Exchange(
        app, "POST", _BODY_ROUTE, headers=auth(FIRST_TOKEN), body=[b"{"], hold_body=True
    )

    async def main() -> None:
        with anyio.fail_after(10):
            await stalled.run()

    anyio.run(main)
    assert stalled.status == 408
    assert stalled.json()["code"] == "body_timeout"
    assert stalled.response_headers["connection"] == "close"
    counts = app.state.admission.snapshot()["classes"][REQUESTS]
    assert (counts["in_flight"], counts["body_timeouts"]) == (0, 1)


# -- the permission floor stays off the event loop --------------------------------------------


def test_the_permission_floor_opens_no_connection_on_the_event_loop(served, monkeypatch):
    opened: list[tuple[str, bool]] = []
    session, unscoped = Database.session, Database.unscoped

    def running_loop() -> bool:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return True

    def watched_session(self, workspace_id):
        opened.append(("session", running_loop()))
        return session(self, workspace_id)

    def watched_unscoped(self):
        opened.append(("unscoped", running_loop()))
        return unscoped(self)

    monkeypatch.setattr(Database, "session", watched_session)
    monkeypatch.setattr(Database, "unscoped", watched_unscoped)
    # The floor's own tile charge applies to no route today (every metered route charges itself),
    # so one is taken off that list here to put the charge on the path this test walks.
    monkeypatch.setattr(
        dependencies,
        "SELF_CHARGING_TILE_ROUTES",
        {
            key: value
            for key, value in permissions.SELF_CHARGING_TILE_ROUTES.items()
            if key != ("GET", "/tiles")
        },
    )
    narrow = "capacity-narrow-token-that-is-long-enough"
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                FIRST_TOKEN: {
                    "workspace_id": str(served.first),
                    "actor": str(uuid.uuid4()),
                    "permissions": [str(p) for p in permissions.Permission],
                },
                narrow: {
                    "workspace_id": str(served.first),
                    "actor": str(uuid.uuid4()),
                    "permissions": ["library.read"],
                },
            }
        ),
    )
    app = served.app()
    exchanges = [
        Exchange(app, "GET", "/healthz"),
        Exchange(app, "GET", "/formation", headers=auth(FIRST_TOKEN)),
        # Refused by permission: the refusal is recorded on a connection.
        Exchange(app, "GET", "/world/versions", headers=auth(narrow)),
        # Charged one tile by the floor: undeclared quota, refused, after a connection.
        Exchange(app, "GET", "/tiles", headers=auth(FIRST_TOKEN)),
    ]

    async def main() -> None:
        for exchange in exchanges:
            await exchange.run()

    anyio.run(main)
    assert [exchange.status for exchange in exchanges] == [200, 200, 403, 429], [
        exchange.text for exchange in exchanges
    ]
    # The 429 is the floor's own tile charge refusing, not a capacity refusal.
    assert exchanges[3].json()["code"] == "tile_quota_undeclared"
    assert opened, "the walk opened no connection, so it proved nothing"
    assert not [kind for kind, on_loop in opened if on_loop], opened


# -- helpers ----------------------------------------------------------------------------------


async def _until(condition, timeout: float = 10.0) -> None:
    with anyio.fail_after(timeout):
        while not condition():
            await anyio.sleep(0.01)


def _open_batch(served, workspace: uuid.UUID) -> uuid.UUID:
    """A running batch, which is a stream that stays open until the test leaves it."""
    row = served.repository.connection.execute(
        "insert into intake_batch (workspace_id, label) values (%s, 'capacity') returning batch_id",
        (workspace,),
    ).fetchone()
    return row["batch_id"]


def test_a_request_the_floor_refuses_by_permission_claims_no_share(served, monkeypatch):
    """Permission first: a refused request holds none of its workspace's share of one."""
    claimed: list[uuid.UUID] = []
    original = Admission.claim_workspace

    def watched(self, ticket, workspace_id):
        claimed.append(workspace_id)
        return original(self, ticket, workspace_id)

    monkeypatch.setattr(Admission, "claim_workspace", watched)
    narrow = "capacity-narrow-token-that-is-long-enough"
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                narrow: {
                    "workspace_id": str(served.first),
                    "actor": str(uuid.uuid4()),
                    "permissions": ["library.read"],
                }
            }
        ),
    )
    app = served.app(requests=4, workspace_requests=1)
    refused = Exchange(app, "GET", "/world/versions", headers=auth(narrow))
    allowed = Exchange(app, "GET", "/formation", headers=auth(narrow))

    async def main() -> None:
        await refused.run()
        await allowed.run()

    anyio.run(main)
    assert (refused.status, allowed.status) == (403, 200)
    assert claimed == [served.first], "the refused request claimed a share"


def test_a_request_refused_for_its_workspace_share_is_never_charged(served, monkeypatch):
    """The share is claimed before the tile charge, so a capacity refusal costs no tile."""
    charged: list[uuid.UUID] = []
    monkeypatch.setattr(
        dependencies,
        "charge_tiles",
        lambda _connection, workspace, _count: charged.append(workspace),
    )
    monkeypatch.setattr(
        dependencies,
        "SELF_CHARGING_TILE_ROUTES",
        {
            key: value
            for key, value in permissions.SELF_CHARGING_TILE_ROUTES.items()
            if key != ("GET", "/tiles")
        },
    )

    def full(self, ticket, workspace_id):
        raise CapacityRefused(ticket.capacity, workspace=True)

    app = served.app()
    monkeypatch.setattr(Admission, "claim_workspace", full)
    refused = Exchange(app, "GET", "/tiles", headers=auth(FIRST_TOKEN))
    anyio.run(refused.run)
    assert refused.status == 429
    assert refused.json()["code"] == "workspace_capacity_exhausted"
    assert charged == []


def test_a_browser_session_is_resolved_off_the_event_loop(
    repository, spine_schema, account_role, tmp_path, monkeypatch
):
    """The account-cookie branch of the floor opens its account connection in a worker thread."""
    import httpx2
    import psycopg
    from exulanica.api.account_runtime import AccountRuntime, GoogleOIDCProvider
    from exulanica.api.app import create_app
    from exulanica.api.authorisation import TokenDirectory
    from exulanica.api.services import Services
    from exulanica.store.local import LocalContentAddressedStore
    from fastapi.testclient import TestClient

    from account_fixtures import FakeGoogle, google_config, production_shaped_allowlist
    from tests_support_api import scratch_database

    _, scratch = spine_schema
    database = scratch_database(scratch)
    config = google_config()
    fake = FakeGoogle()
    runtime = AccountRuntime(
        config,
        account_role,
        GoogleOIDCProvider(
            config,
            transport=httpx2.MockTransport(fake.handle),
            egress=production_shaped_allowlist(),
        ),
    )
    runtime.verify_database(database.url)
    services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "store"),
        tokens=TokenDirectory(sessions={}),
        executor_shares_the_write_role=True,
        model_client=None,
        accounts=runtime,
    )
    with TestClient(
        create_app(services, verify=False), base_url="https://app.test", follow_redirects=False
    ) as client:
        start = client.get("/auth/google/start")
        assert start.status_code == 303, start.text
        assert client.get(fake.issue(start.headers["location"])).status_code == 303
        opened: list[bool] = []
        connect = psycopg.connect

        def watched(*args, **kwargs):
            try:
                asyncio.get_running_loop()
                opened.append(True)
            except RuntimeError:
                opened.append(False)
            return connect(*args, **kwargs)

        monkeypatch.setattr(psycopg, "connect", watched)
        response = client.get("/formation")
    assert response.status_code == 200, response.text
    assert opened, "the cookie was resolved without opening a connection, so this proved nothing"
    assert not any(opened), opened


@pytest.mark.parametrize("conflict", ["SerializationFailure", "DeadlockDetected"])
def test_a_transient_database_conflict_on_any_route_is_answered_busy(served, monkeypatch, conflict):
    """40001 and 40P01 are a moment's conflict: a problem with Retry-After, never a bare 500."""
    import psycopg
    from exulanica.api.routes import operations

    def conflicted(*_args, **_kwargs):
        raise getattr(psycopg.errors, conflict)("a conflict with another transaction")

    monkeypatch.setattr(operations, "derivative_job_metrics", conflicted)
    app = served.app()
    answer = Exchange(app, "GET", "/operations/derivative-jobs", headers=auth(FIRST_TOKEN))
    anyio.run(answer.run)
    assert answer.status == 409
    assert answer.json()["code"] == "busy"
    assert answer.response_headers["retry-after"] == "1"
