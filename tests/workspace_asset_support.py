"""The application the workspace asset tests drive: two workspaces, as provisioned runtime roles.

Not loaded by the application. A test about isolation as deployed connects the app as a runtime
role that neither owns the schema nor bypasses row-level security, and asserts both, because a
superuser app measures a route's own predicate rather than the deployment (the lesson of
``tests/test_existence_oracle.py``). The owner's workspace holds a registered world with a
structure snapshot of two regions, so placement has somewhere to go.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.roles import provision_runtime_role
from exulanica.db.session import Database
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import LocalWorkspaceStores
from exulanica.world import WorldStructureRepository
from exulanica.world.asset_preparation import AssetPreparationWorker, PreparationOutcome
from exulanica.world.workspace_assets import (
    DECLARATION_PROFILE,
    RIGHTS_STATEMENT,
    WorkspaceAssetRuntime,
)
from fastapi.testclient import TestClient

from conftest import scratch_role_database
from tests_support_api import EVERY_PERMISSION, scratch_database
from world_structure_fixtures import structural_candidate
from world_support import registered_world

__all__ = ["AssetsApi", "assets_api", "declaration"]

RUNTIME_ROLE = "exulanica_workspace_asset_suite"
OWNER_TOKEN = "workspace-asset-owner-token-long-enough-for-tests"
STRANGER_TOKEN = "workspace-asset-stranger-token-long-enough-for-tests"
TABLES = (
    "workspace_asset",
    "workspace_asset_withdrawal",
    "workspace_asset_blob",
    "workspace_preparation",
    "workspace_preparation_request",
)


def declaration(payload: bytes, **overrides: Any) -> dict[str, Any]:
    """A declaration of these exact bytes as the person's own work in metres, with overrides.

    ``rights`` in ``overrides`` is merged into the default rights rather than replacing them.
    """
    document: dict[str, Any] = {
        "profile": DECLARATION_PROFILE,
        "content_kind": "static_glb",
        "title": "Oak bench",
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "byte_size": len(payload),
        "unit": "metre",
        "expected_dimensions_mm": None,
        "rights": {
            "basis": "own_work",
            "licence_id": None,
            "attribution": None,
            "source_reference": None,
            "statement": RIGHTS_STATEMENT,
        },
    }
    rights = overrides.pop("rights", None)
    document.update(overrides)
    if rights is not None:
        document["rights"] = {**document["rights"], **rights}
    return document


@dataclass
class AssetsApi:
    client: TestClient
    #: The schema owner, which bypasses row-level security: for counting every workspace's rows
    #: and for writing what a test simulates (an expired lease), never for what the product does.
    owner_database: Database
    database: Database
    stores: LocalWorkspaceStores
    store: LocalContentAddressedStore
    owner: uuid.UUID
    stranger: uuid.UUID
    actor: uuid.UUID
    world_id: str
    snapshot_id: uuid.UUID
    tmp_path: Path

    def headers(self, who: str = "owner") -> dict[str, str]:
        token = OWNER_TOKEN if who == "owner" else STRANGER_TOKEN
        return {"Authorization": f"Bearer {token}"}

    def admit(
        self,
        payload: bytes,
        document: Mapping[str, Any] | None = None,
        *,
        who: str = "owner",
        raw_declaration: str | None = None,
    ) -> httpx.Response:
        text = (
            raw_declaration
            if raw_declaration is not None
            else json.dumps(document if document is not None else declaration(payload))
        )
        return self.client.post(
            "/workspace-assets",
            headers=self.headers(who),
            data={"declaration": text},
            files={"content": ("object.glb", payload, "model/gltf-binary")},
        )

    def get(self, path: str, who: str = "owner") -> httpx.Response:
        return self.client.get(path, headers=self.headers(who))

    def post(self, path: str, body: Any = None, who: str = "owner") -> httpx.Response:
        return self.client.post(path, headers=self.headers(who), json=body)

    def worker(self, workspace: uuid.UUID | None = None, **options: Any) -> AssetPreparationWorker:
        return AssetPreparationWorker(
            self.database, self.stores, frozenset({workspace or self.owner}), **options
        )

    def drain(self, workspace: uuid.UUID | None = None) -> PreparationOutcome:
        return self.worker(workspace).drain()

    def admitted(self, payload: bytes, **overrides: Any) -> dict[str, Any]:
        """Admit and prepare, and return the prepared asset's view."""
        response = self.admit(payload, declaration(payload, **overrides))
        assert response.status_code in (200, 201), response.text
        outcome = self.drain()
        assert not outcome.errors, outcome.errors
        view = self.get(f"/workspace-assets/{response.json()['asset_id']}")
        assert view.status_code == 200, view.text
        return view.json()

    def counts(self) -> dict[str, int]:
        """Rows in every workspace asset table, every workspace, read as the schema owner."""
        return {table: self.sql(f"select count(*) as n from {table}")[0]["n"] for table in TABLES}

    def namespace_files(self, workspace: uuid.UUID | None = None) -> list[Path]:
        root = self.stores.root / (workspace or self.owner).hex
        return sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []

    def sql(
        self, statement: str, *parameters: Any, workspace: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        """One statement as the schema owner in a workspace's context, and its rows if any."""
        with self.owner_database.session(workspace or self.owner) as connection:
            cursor = connection.execute(statement, parameters)
            return cursor.fetchall() if cursor.description is not None else []


def assets_api(repository: Any, spine_schema: Any, tmp_path: Path) -> Iterator[AssetsApi]:
    """The fixture body; each test module wraps it in its own ``pytest.fixture``."""
    _psycopg, scratch = spine_schema
    admin = repository.connection
    provision_runtime_role(admin, role=RUNTIME_ROLE)
    admin.commit()
    database = scratch_role_database(scratch, RUNTIME_ROLE)
    owner, stranger, actor = repository.workspace_id, uuid.uuid4(), uuid.uuid4()
    with database.session(owner) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role

    world_id = registered_world(admin, owner)
    structures = WorldStructureRepository(admin, owner, world_id=world_id)
    preview = structures.preview(structural_candidate(), proposed_by=actor)
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )
    admin.commit()

    grants = {
        OWNER_TOKEN: {
            "workspace_id": str(owner),
            "actor": str(actor),
            "permissions": EVERY_PERMISSION,
        },
        STRANGER_TOKEN: {
            "workspace_id": str(stranger),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        },
    }
    store = LocalContentAddressedStore(tmp_path / "blobs")
    stores = LocalWorkspaceStores(tmp_path / "workspace-assets")
    services = Services(
        database=database,
        readonly_database=database,
        store=store,
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=True,
        model_client=None,
        workspace_assets=WorkspaceAssetRuntime(stores=stores),
    )
    app = create_app(services, verify=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield AssetsApi(
            client=client,
            owner_database=scratch_database(scratch),
            database=database,
            stores=stores,
            store=store,
            owner=owner,
            stranger=stranger,
            actor=actor,
            world_id=world_id,
            snapshot_id=snapshot.snapshot_id,
            tmp_path=tmp_path,
        )


def without(document: Mapping[str, Any], *path: str) -> dict[str, Any]:
    """A deep copy of a declaration with one nested key removed."""
    copied = copy.deepcopy(dict(document))
    cursor = copied
    for key in path[:-1]:
        cursor = cursor[key]
    del cursor[path[-1]]
    return copied
