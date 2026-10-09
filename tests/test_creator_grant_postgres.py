"""A creator's upload from a browser needs the operator's creator grant; a bearer token's does not.

Through the application ``create_app`` builds, signed in with Google over the signed fake
provider, on the account role a deployment provisions, with the operator's command:

*   a browser owner whose account holds no grant is refused on both upload routes, 403
    ``creator_grant_required``, while their bodies are still arriving, and nothing is written;
*   once the operator grants it, the same owner's asset upload is admitted, and the style pack
    upload reaches the installation's switch; once the grant is revoked, refused again;
*   a bearer token holding ``admission.write`` uploads with no grant at all.

The revocation's way across a restore is ``tests/test_restore_replay_withdrawals.py``'s.
"""

from __future__ import annotations

import io
import json
import uuid
from dataclasses import dataclass
from typing import Any

import anyio
import httpx2
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


@pytest.fixture
def site(repository, spine_schema, account_role, tmp_path):
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
        # The installation's switch left off, as by default.
        workspace_style_packs=WorkspaceStylePackRuntime.over(
            LocalWorkspaceStores(tmp_path / "packs")
        ),
    )
    app = create_app(services, verify=False)
    client = TestClient(app, base_url=_ORIGIN, follow_redirects=False)
    return Site(app, client, database, account_role, fake, repository.workspace_id)


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
