"""World projects over HTTP, as a deployment serves them, for the project-context tests.

The application runs as a provisioned runtime role (neither a superuser nor BYPASSRLS), so row-level
security is the deployment's and not bypassed, with a read-only role beside it and no model client:
every operation here is one a no-model installation serves. Four tokens: the owner, another person
of the owner's workspace, a person of another workspace, and the owner holding ``world.read`` only.

A starter world is made the way the product makes one (``POST /world-entries/starter``). Another
world of the same workspace is made through the domain, because the starter route refuses a second
saved world, and a project needs a registered world with an authored version, not a saved entry.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.roles import provision_runtime_role
from exulanica.db.session import set_workspace
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.assets import seed_reviewed_assets
from exulanica.world.society_composition import reviewed_affordance_registry
from exulanica.world.starter import AUTHORED_STARTER_REGION_ID, create_starter_authorities
from exulanica.world.worlds import AUTHORED_STARTER, new_world_id
from fastapi.testclient import TestClient

from conftest import scratch_role_database
from tests_support_api import EVERY_PERMISSION

OWNER = "project-context-owner-token-long-enough-to-be-accepted"
PEER = "project-context-peer-token-long-enough-to-be-accepted"
STRANGER = "project-context-stranger-token-long-enough-to-be-accepted"
READER = "project-context-reader-token-long-enough-to-be-accepted"
RUNTIME_ROLE = "exulanica_project_context_suite"
READ_ROLE = "exulanica_project_context_reader"

#: Where each placed object stands on the starter's ground plane, as Q10's journey places them.
PLACES = {"stall": (6000, 0, 0), "bench": (-6000, 0, 4000), "lamp": (-6000, 0, -4000)}
APPLY = "POST /world/versions/{version_id}/compositions/apply"


@dataclass
class Api:
    client: TestClient
    repository: Any
    scratch: Any
    workspace_id: uuid.UUID
    stranger_workspace: uuid.UUID
    owner: uuid.UUID
    peer: uuid.UUID
    grants: dict[str, dict[str, Any]]
    database: Any

    def call(self, method: str, path: str, *, token: str = OWNER, world: str | None, **kw):
        params = dict(kw.pop("params", {}) or {})
        if world is not None:
            params["world_id"] = world
        return self.client.request(
            method, path, params=params, headers={"Authorization": f"Bearer {token}"}, **kw
        )

    def ok(self, response, *expected: int) -> Any:
        assert response.status_code in expected, (response.status_code, response.text)
        return response.json() if response.content else None


def build_app(services: Services) -> TestClient:
    return TestClient(create_app(services, verify=False), raise_server_exceptions=False)


def services_for(api_scratch, grants: dict[str, dict[str, Any]], store) -> Services:
    """The services an instance builds, with the society runtime every instance has, and no
    model client."""
    return Services(
        database=scratch_role_database(api_scratch, RUNTIME_ROLE),
        readonly_database=scratch_role_database(api_scratch, READ_ROLE),
        store=store,
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=False,
        model_client=None,
        society_runtime=SocietyRuntime(
            store=store, authored_bindings=[], reviewed_affordances=reviewed_affordance_registry()
        ),
    )


def projects_api(tmp_path, repository, spine_schema) -> Iterator[Api]:
    """The application as a deployment runs it, and the four callers above."""
    _psycopg, scratch = spine_schema
    provision_runtime_role(repository.connection, role=RUNTIME_ROLE)
    provision_runtime_role(repository.connection, role=READ_ROLE, read_only=True)
    database = scratch_role_database(scratch, RUNTIME_ROLE)
    with database.session(repository.workspace_id) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
    owner, peer, stranger_workspace = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    workspace = str(repository.workspace_id)
    grants = {
        OWNER: {"workspace_id": workspace, "actor": str(owner), "permissions": EVERY_PERMISSION},
        PEER: {"workspace_id": workspace, "actor": str(peer), "permissions": EVERY_PERMISSION},
        STRANGER: {
            "workspace_id": str(stranger_workspace),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        },
        READER: {"workspace_id": workspace, "actor": str(owner), "permissions": ["world.read"]},
    }
    store = LocalContentAddressedStore(tmp_path / "blobs")
    seed_reviewed_assets(store)
    with build_app(services_for(scratch, grants, store)) as client:
        assert client.app.state.services.model_client is None
        yield Api(
            client,
            repository,
            scratch,
            repository.workspace_id,
            stranger_workspace,
            owner,
            peer,
            grants,
            database,
        )


def starter(api: Api, title: str = "Project square", token: str = OWNER) -> dict[str, Any]:
    """The workspace's authored starter, as its saved entry reads."""
    return api.ok(
        api.call("POST", "/world-entries/starter", token=token, world=None, json={"title": title}),
        200,
        201,
    )


def other_world(api: Api) -> tuple[str, str]:
    """A second authored world of the owner's workspace with one version: (world, version)."""
    connection = api.repository.connection
    set_workspace(connection, api.workspace_id)
    world_id = new_world_id(AUTHORED_STARTER)
    with connection.transaction():
        _snapshot, _style, version_id = create_starter_authorities(
            connection,
            workspace_id=api.workspace_id,
            actor=api.owner,
            title="Another place",
            world_id=world_id,
        )
    return world_id, str(version_id)


def entry(api: Api, entry_id: str) -> dict[str, Any]:
    return api.ok(api.call("GET", f"/world-entries/{entry_id}", world=None), 200)


def place(api: Api, saved: dict[str, Any], asset: str, subject: str, where: str) -> dict:
    """Apply one reviewed object through the composition authority, bound to the saved entry."""
    x, y, z = PLACES[where]
    body = {
        "base_state_sha256": saved["authored_state_sha256"],
        "source": {"kind": "reviewed_asset", "asset_key": asset},
        "placement": {
            "subject_id": subject,
            "region_id": AUTHORED_STARTER_REGION_ID,
            "transform": {
                "x_mm": x,
                "y_mm": y,
                "z_mm": z,
                "yaw_microradians": 0,
                "scale_milli": 1000,
            },
            "origin_role": "fictional",
        },
        "saved_entry": {
            "entry_id": saved["entry_id"],
            "base_revision": saved["revision"],
            "authored_state_sha256": saved["authored_state_sha256"],
            "authored_edit_seq": saved["authored_edit_seq"],
        },
    }
    return api.ok(
        api.call(
            "POST",
            f"/world/versions/{saved['authored_version_id']}/compositions/apply",
            world=saved["world_id"],
            json=body,
        ),
        200,
        201,
    )


def edit_reference(version: dict[str, Any], subject: str) -> dict[str, Any]:
    """The accepted-operation reference of the edit that added ``subject``, as M6 reports it."""
    edit = next(e for e in version["edits"] if e["object_id"] == subject)
    return {
        "kind": "world_edit",
        "operation": APPLY,
        "world_id": version["world_id"],
        "version_id": version["version_id"],
        "edit_id": edit["edit_id"],
        "edit_seq": edit["edit_seq"],
        "result_state_sha256": edit["result_state_sha256"],
    }


def project(api: Api, world: str, version: str, title: str = "Rest spots", **kw) -> dict:
    return api.ok(
        api.call(
            "POST",
            "/world/projects",
            world=world,
            json={"title": title, "version_id": version, **kw},
        ),
        201,
    )


def add(api: Api, world: str, made: dict, body: dict, *, token: str = OWNER, status=(201,)):
    response = api.call(
        "POST",
        f"/world/projects/{made['project_id']}/items",
        token=token,
        world=world,
        json=body,
    )
    return api.ok(response, *status)


def revision(api: Api, world: str, project_id: str, token: str = OWNER) -> int:
    return api.ok(api.call("GET", f"/world/projects/{project_id}", token=token, world=world), 200)[
        "revision"
    ]


def remembered_answer(api: Api, question: str = "Where do people rest?") -> str:
    """One of the owner's Companion answers, kept as the browser keeps one."""
    return api.ok(
        api.call(
            "POST",
            "/companion/memory/answers",
            world=None,
            json={
                "question": question,
                "answer_text": "Nobody rests here yet.",
                "prompt_version": "selection-3",
                "latency_ms": 1,
                "composed": "none",
                "used_fallback": False,
                "unanswered_attempts": 0,
                "unanswered_cost_unknown": False,
            },
        ),
        201,
    )["answer_id"]


def invalidate(api, world_id: str, version_id: str) -> None:
    """Record, as the structural plane's tombstone trigger records, that a deletion invalidated
    this version's source. The tombstone is a capture tombstone of a photograph the world never
    used, so nothing else of the workspace is deleted."""
    connection = api.repository.connection
    set_workspace(connection, api.workspace_id)
    capture = uuid.uuid4()
    tombstone = connection.execute(
        "insert into tombstone (workspace_id, scope, capture_id, requested_by, reason) "
        "values (%s, 'capture', %s, %s, 'test') returning tombstone_id",
        (api.workspace_id, capture, api.owner),
    ).fetchone()["tombstone_id"]
    connection.execute(
        "insert into world_structure_invalidation (workspace_id, world_id, snapshot_id, "
        "tombstone_id, reason) select v.workspace_id, v.world_id, v.source_snapshot_id, %s, "
        "'source withdrawn in a test' from world_alternate_version v where v.workspace_id=%s "
        "and v.world_id=%s and v.version_id=%s",
        (tombstone, api.workspace_id, world_id, version_id),
    )
