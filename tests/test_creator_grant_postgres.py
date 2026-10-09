"""A creator's upload from a browser needs the operator's creator grant; a bearer token's does not.

Through the application ``create_app`` builds, signed in with Google over the signed fake
provider, on the account role a deployment provisions, with the operator's command:

*   a browser owner whose account holds no grant is refused on both upload routes, 403
    ``creator_grant_required``, while their bodies are still arriving, and nothing is written;
*   once the operator grants it, the same owner's asset upload is admitted, and the style pack
    upload reaches the installation's switch; once the grant is revoked, refused again;
*   a bearer token holding ``admission.write`` uploads with no grant at all;
*   with the installation's switch on, a granted pack upload passes it and is counted, where one
    without the grant was counted nothing;
*   an account's chain of grant events refuses a revoke first, a second grant, a gap, any change
    and any deletion, a repeated grant records nothing, and two writers racing for one number meet
    the unique key.

The revocation's way across a restore is ``tests/test_restore_replay_withdrawals.py``'s.
"""

from __future__ import annotations

import io
import json
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

import anyio
import httpx2
import psycopg
import pytest
from exulanica.api import creator_grants
from exulanica.api.account_runtime import SESSION_COOKIE, AccountRuntime, GoogleOIDCProvider
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.session import Database
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import LocalWorkspaceStores
from exulanica.world.workspace_assets import WorkspaceAssetRuntime
from exulanica.world.workspace_style_packs import WorkspaceStylePackRuntime
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from account_fixtures import FakeGoogle, google_config, production_shaped_allowlist
from account_fixtures import account_role as account_role
from asgi_requests import Exchange
from static_glb_builder import cube, png
from tests_support_api import EVERY_PERMISSION, scratch_database
from workspace_asset_support import declaration

pytestmark = pytest.mark.postgres

_TOKEN = "creator-grant-bearer-token-long-enough-for-tests"
_ORIGIN = "https://app.test"


@dataclass
class Site:
    app: Any
    client: TestClient
    database: Database
    account_role: str
    fake: FakeGoogle
    #: The bearer token's workspace, which no account owns.
    token_workspace: uuid.UUID

    def signed_in(self) -> dict[str, Any]:
        start = self.client.get("/auth/google/start")
        assert start.status_code == 303, start.text
        assert self.client.get(self.fake.issue(start.headers["location"])).status_code == 303
        session = self.client.get("/auth/session")
        assert session.status_code == 200, session.text
        return session.json()

    def operator(self, *arguments: str) -> dict[str, Any]:
        out = io.StringIO()
        environ = {"EXULANICA_ACCOUNT_DATABASE_URL": self.account_role}
        assert creator_grants.main(list(arguments), stream=out, environ=environ) == 0
        return json.loads(out.getvalue())

    def upload_asset(self, headers: dict[str, str]) -> Any:
        payload = cube(offset=(0.0, 0.0, 0.0), texture=png(4, 4)).build()
        return self.client.post(
            "/workspace-assets",
            headers=headers,
            data={"declaration": json.dumps(declaration(payload))},
            files={"content": ("object.glb", payload, "model/gltf-binary")},
        )

    def rows(self, workspace: uuid.UUID) -> dict[str, int]:
        """What an upload would have written for ``workspace``, read as the schema owner."""
        with self.database.session(workspace) as connection:
            return {
                table: connection.execute(
                    f"select count(*) as n from {table} where workspace_id = %s", (workspace,)
                ).fetchone()["n"]
                for table in ("workspace_asset", "workspace_style_pack_attempt_day")
            }


def _site(repository, spine_schema, account_role, tmp_path, *, uploads: bool) -> Site:
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
    grants = {
        _TOKEN: {
            "workspace_id": str(repository.workspace_id),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        }
    }
    services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "store"),
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=True,
        model_client=None,
        accounts=runtime,
        workspace_assets=WorkspaceAssetRuntime(stores=LocalWorkspaceStores(tmp_path / "assets")),
        workspace_style_packs=WorkspaceStylePackRuntime.over(
            LocalWorkspaceStores(tmp_path / "packs"), uploads=uploads
        ),
    )
    app = create_app(services, verify=False)
    client = TestClient(app, base_url=_ORIGIN, follow_redirects=False)
    return Site(app, client, database, account_role, fake, repository.workspace_id)


@pytest.fixture
def site(repository, spine_schema, account_role, tmp_path):
    """The installation's switch for pack uploads left off, as by default."""
    return _site(repository, spine_schema, account_role, tmp_path, uploads=False)


@pytest.fixture
def site_with_uploads(repository, spine_schema, account_role, tmp_path):
    return _site(repository, spine_schema, account_role, tmp_path, uploads=True)


def _held(site: Site, path: str, account: dict[str, Any]) -> Exchange:
    """A browser upload whose multipart body has begun and then stalls."""
    cookie = site.client.cookies.get(SESSION_COOKIE)
    return Exchange(
        site.app,
        "POST",
        path,
        headers=[
            (b"cookie", f"{SESSION_COOKIE}={cookie}".encode()),
            (b"origin", _ORIGIN.encode()),
            (b"x-csrf-token", account["csrf_token"].encode()),
            (b"content-type", b"multipart/form-data; boundary=held"),
        ],
        body=[b"--held\r\n"],
        hold_body=True,
    )


def _answered_unread(*exchanges: Exchange) -> dict[str, int]:
    """Run each until it is answered; how many body pieces each had read by then."""
    read: dict[str, int] = {}

    async def main() -> None:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as group:
                for exchange in exchanges:
                    group.start_soon(exchange.run)
                    await exchange.started.wait()
                    read[exchange.path] = exchange._sent
                    exchange.leave()

    anyio.run(main)
    return read


def test_a_browser_owner_uploads_only_while_their_account_holds_the_creator_grant(site):
    account = site.signed_in()
    assert account["role"] == "owner" and account["creator"] is False
    workspace = uuid.UUID(account["workspace_id"])
    nothing = {"workspace_asset": 0, "workspace_style_pack_attempt_day": 0}

    packs, assets = (
        _held(site, path, account) for path in ("/workspace-style-packs", "/workspace-assets")
    )
    assert _answered_unread(packs, assets) == {"/workspace-style-packs": 0, "/workspace-assets": 0}
    for refused in (packs, assets):
        assert (refused.status, refused.json()["code"]) == (403, "creator_grant_required")
    assert site.rows(workspace) == nothing

    granted = site.operator(
        "grant", "--user", account["user_id"], "--reason", "invited_creator", "--operator", "ops"
    )
    assert granted == {"user_id": account["user_id"], "kind": "grant", "recorded": True}
    assert site.client.get("/auth/session").json()["creator"] is True
    assert site.operator("list")["creators"][0]["user_id"] == account["user_id"]
    headers = {"Origin": _ORIGIN, "X-CSRF-Token": account["csrf_token"]}
    admitted = site.upload_asset(headers)
    assert admitted.status_code == 201, admitted.text
    # Past the grant, the installation's switch is the next thing a pack upload meets.
    pack = site.client.post("/workspace-style-packs", headers=headers, files={"x": b""})
    assert (pack.status_code, pack.json()["code"]) == (503, "style_pack_uploads_off")

    revoked = site.operator(
        "revoke", "--user", account["user_id"], "--reason", "creator_left", "--operator", "ops"
    )
    assert revoked["recorded"] is True
    again = site.upload_asset(headers)
    assert (again.status_code, again.json()["code"]) == (403, "creator_grant_required")
    assert site.rows(workspace)["workspace_asset"] == 1
    assert site.operator("list") == {"creators": []}


def test_a_bearer_token_uploads_on_its_own_admission_write(site):
    admitted = site.upload_asset({"Authorization": f"Bearer {_TOKEN}"})
    assert admitted.status_code == 201, admitted.text
    assert site.rows(site.token_workspace)["workspace_asset"] == 1


def test_with_uploads_on_a_granted_pack_upload_passes_the_switch_and_is_counted(site_with_uploads):
    site = site_with_uploads
    account = site.signed_in()
    workspace = uuid.UUID(account["workspace_id"])
    headers = {"Origin": _ORIGIN, "X-CSRF-Token": account["csrf_token"]}
    refused = site.client.post("/workspace-style-packs", headers=headers, files={"x": b""})
    assert (refused.status_code, refused.json()["code"]) == (403, "creator_grant_required")
    assert site.rows(workspace)["workspace_style_pack_attempt_day"] == 0
    site.operator(
        "grant", "--user", account["user_id"], "--reason", "invited_creator", "--operator", "ops"
    )
    # Past the grant and the switch, the attempt is counted before the body is read; this body is
    # no pack.
    counted = site.client.post("/workspace-style-packs", headers=headers, files={"x": b""})
    assert (counted.status_code, counted.json()["code"]) == (422, "invalid_style_pack_body")
    assert site.rows(workspace)["workspace_style_pack_attempt_day"] == 1


def _insert(connection: psycopg.Connection, user: uuid.UUID, sequence: int, kind: str) -> None:
    connection.execute(
        "insert into account_creator_grant_event "
        "(event_id, user_id, sequence, kind, reason, operator) values (%s, %s, %s, %s, %s, %s)",
        (uuid.uuid4(), user, sequence, kind, "test_case", "ops"),
    )


def _refused(connection: psycopg.Connection, statement: str, *parameters: object) -> str:
    """The message the database refuses ``statement`` with, as a check violation."""
    with pytest.raises(psycopg.errors.CheckViolation) as refused:
        connection.execute(statement, parameters)
    return refused.value.diag.message_primary or ""


def test_an_account_s_grant_events_keep_their_chain(site):
    user = uuid.UUID(site.signed_in()["user_id"])
    table = "account_creator_grant_event"
    insert = f"insert into {table} (event_id, user_id, sequence, kind, reason, operator) "
    insert += "values (gen_random_uuid(), %s, %s, %s, 'test_case', 'ops')"
    with psycopg.connect(site.account_role, autocommit=True, row_factory=dict_row) as accounts:
        assert "alternate" in _refused(accounts, insert, user, 1, "revoke")
        assert creator_grants.grant(accounts, user, reason="invited_creator", operator="ops")
        assert not creator_grants.grant(accounts, user, reason="invited_creator", operator="ops")
        assert "alternate" in _refused(accounts, insert, user, 2, "grant")
        assert "alternate" in _refused(accounts, insert, user, 3, "revoke")
        assert "immutable" in _refused(
            accounts, f"update {table} set reason = 'changed' where user_id = %s", user
        )
        # The account role holds no delete at all; even the table's owner meets 0058's rule.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            accounts.execute(f"delete from {table} where user_id = %s", (user,))
    with psycopg.connect(site.database.url, autocommit=True) as owner:
        assert "retained" in _refused(owner, f"delete from {table} where user_id = %s", user)
    with psycopg.connect(site.account_role, autocommit=True, row_factory=dict_row) as accounts:
        held = accounts.execute(
            f"select sequence, kind from {table} where user_id = %s", (user,)
        ).fetchall()
        assert held == [{"sequence": 1, "kind": "grant"}]
    # Two writers racing for the next number: the second waits on the first's key and is refused
    # by it once the first commits, rather than both being recorded.
    with (
        psycopg.connect(site.account_role) as first,
        psycopg.connect(site.account_role) as second,
        psycopg.connect(site.database.url, autocommit=True) as watcher,
    ):
        _insert(first, user, 2, "revoke")
        outcome: dict[str, BaseException] = {}

        def race() -> None:
            try:
                _insert(second, user, 2, "revoke")
                second.commit()
            except psycopg.Error as error:
                outcome["error"] = error
                second.rollback()

        racer = threading.Thread(target=race)
        racer.start()
        deadline = time.monotonic() + 10
        while not watcher.execute(
            "select 1 from pg_stat_activity where pid = %s and wait_event_type = 'Lock'",
            (second.info.backend_pid,),
        ).fetchone():
            assert time.monotonic() < deadline, "the second writer never waited on the first"
            time.sleep(0.05)
        first.commit()
        racer.join(10)
        assert isinstance(outcome.get("error"), psycopg.errors.UniqueViolation), outcome
