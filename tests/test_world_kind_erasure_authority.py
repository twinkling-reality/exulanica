"""A kept kind's current actor/permission boundary and upgrade stay independent of its content."""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.db.session import set_workspace
from exulanica.migrations import migrations
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.erasure import erase_kind
from exulanica.world.kinds.repository import WorkspaceKinds
from exulanica.world.kinds.samples import check_samples
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import pg_harness
from test_purge import purged as purged
from test_world_kind_erasure_postgres import _context, _keep
from test_world_kinds_postgres import _uploaded
from tests_support_api import EVERY_PERMISSION

pytestmark = pytest.mark.postgres


def test_permissions_and_workspace_actor_do_not_inherit_owner_authority(purged):
    base, _, workspace, actor = _context(purged)
    kind = read_kind(_uploaded("farm"))
    _keep(purged, workspace, actor, kind)
    candidates = {
        "writer": (workspace, actor, ["world.write"]),
        "deleter": (workspace, actor, ["deletion.write"]),
        "participant": (workspace, actor, ["world.read", "world.enter", "being.act"]),
        "other-actor": (workspace, uuid.uuid4(), EVERY_PERMISSION),
        "foreign": (uuid.uuid4(), actor, EVERY_PERMISSION),
        "creator": (workspace, actor, ["world.read", "world.write", "deletion.write"]),
    }
    tokens = {
        f"kind-erasure-test-{name}-token-with-sufficient-length": {
            "workspace_id": str(w),
            "actor": str(a),
            "permissions": list(p),
        }
        for name, (w, a, p) in candidates.items()
    }
    directory = load_token_directory({"EXULANICA_API_TOKENS": json.dumps(tokens)})
    app = create_app(dataclasses.replace(base.state.services, tokens=directory), verify=False)
    path = f"/worlds/kinds/versions/{kind.sha256}"
    with TestClient(app) as client:
        for name in candidates:
            headers = {
                "Authorization": f"Bearer kind-erasure-test-{name}-token-with-sufficient-length"
            }
            response = client.delete(path, headers=headers)
            expected = 204 if name == "creator" else 403 if name == "other-actor" else 404
            assert response.status_code == expected, (name, response.text)
            if name != "creator":
                with purged.database().session(workspace) as connection:
                    assert WorkspaceKinds(connection, workspace).version(kind.kind, kind.version)


def test_populated_0207_upgrade_preserves_kind_until_explicit_erasure(monkeypatch):
    everything = list(migrations())
    [successor] = [m for m in everything if m.version == "0208"]
    monkeypatch.setattr(
        pg_harness, "migrations", lambda: iter(m for m in everything if m.version < "0208")
    )
    with pg_harness.migrated_schema() as (_, admin):
        admin.row_factory = dict_row
        workspace, actor = uuid.uuid4(), uuid.uuid4()
        set_workspace(admin, workspace)
        kind = read_kind(_uploaded("farm"))
        # The historical API predates the retirement table; store its valid admitted row directly.
        admin.execute(
            "insert into world_kind_version(workspace_id,kind,version,document_sha256,document,"
            "origin,validation,created_by) values(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                workspace,
                kind.kind,
                kind.version,
                kind.sha256,
                Jsonb(dict(kind.document)),
                kind.origin,
                Jsonb(check_samples(kind)),
                actor,
            ),
        )
        before = admin.execute("select to_jsonb(k) as row from world_kind_version k").fetchall()
        admin.commit()
        admin.execute(successor.sql)
        admin.commit()
        assert (
            admin.execute("select to_jsonb(k) as row from world_kind_version k").fetchall()
            == before
        )
        erase_kind(admin, workspace, kind.sha256, erased_by=actor)
        assert not admin.execute("select 1 from world_kind_version").fetchall()
        assert admin.execute("select 1 from world_kind_erasure").fetchone()
