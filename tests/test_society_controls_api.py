"""Token-authenticated HTTP controls with real PostgreSQL reload and runtime authority."""

import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.roles import provision_runtime_role
from fastapi.testclient import TestClient

from conftest import scratch_role_database
from test_society_controls_postgres import create
from test_society_runtime import runtime_world
from test_world_objects_api import STRANGER_TOKEN, TOKEN, ObjectsApi

pytestmark = pytest.mark.postgres
# Imported fixtures are deliberately registered in this module.
__all__ = ["runtime_world"]


@pytest.fixture
def control_api(runtime_world, spine_schema, monkeypatch):
    w = runtime_world
    actor = w["session"].actor
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {"workspace_id": str(w["workspace"]), "actor": str(actor)},
                STRANGER_TOKEN: {"workspace_id": str(uuid.uuid4()), "actor": str(uuid.uuid4())},
            }
        ),
    )
    provision_runtime_role(w["connection"], role="exulanica_social_suite")
    w["connection"].commit()
    database = scratch_role_database(spine_schema[1], "exulanica_social_suite")
    with database.session(w["workspace"]) as connection:
        role = connection.execute(
            "select rolsuper,rolbypassrls from pg_roles where rolname=current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}
        assert not connection.execute(
            "select exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace "
            "where n.nspname=current_schema() and c.relowner=(select oid from pg_roles "
            "where rolname=current_user)) as owns"
        ).fetchone()["owns"]
    services = Services(
        database=database,
        readonly_database=database,
        store=w["store"],
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    with TestClient(create_app(services, verify=False)) as client:
        yield ObjectsApi(client, w["binding"].source_snapshot_id, actor, w["store"])
    with database.session(uuid.uuid4()) as connection:
        assert connection.execute("select * from world_society_control").fetchall() == []
        assert connection.execute("select * from world_society_control_event").fetchall() == []


def test_authenticated_controls_reload_cas_and_manual_step(runtime_world, control_api):
    w, api = runtime_world, control_api
    create(w)
    w["connection"].commit()
    app = api.client.app
    app.state.society_input_authorizer = w["runtime"].authorize
    path = f"/world/versions/{w['binding'].version_id}/society/control"
    assert api.client.get(path).status_code == 401
    assert api.stranger_get(path).status_code == 404
    before = api.get(path).json()
    assert before["mode"] == "paused" and before["revision"] == 0
    body = dict(base_revision=0, mode="playing", speed=2)
    saved = api.client.put(path, headers=api.headers, json=body)
    assert saved.status_code == 200, saved.text
    assert api.get(path).json() == saved.json()
    assert saved.json()["tick_interval_ms"] == 500
    assert api.client.put(path, headers=api.headers, json=body).status_code == 409
    step = dict(base_revision=1, base_tick=0, base_state_sha256=before["state_sha256"])
    assert api.post(path + "/steps", step).json()["detail"] == "pause_before_manual_step"
    paused = api.client.put(
        path, headers=api.headers, json=dict(base_revision=1, mode="paused", speed=4)
    )
    assert paused.status_code == 200
    step["base_revision"] = 2
    after = api.post(path + "/steps", step)
    assert after.status_code == 200, after.text
    assert after.json()["society"]["current_tick"] == 1
    assert api.get(path).json()["current_tick"] == 1
    assert api.post(path + "/steps", step).status_code == 409
    events = api.get(path + "/events").json()["events"]
    assert events[0]["kind"] == "manual_step" and events[0]["requested_by"] == str(api.actor)
    for invalid in ({**body, "base_revision": True}, {**body, "speed": True}, {**body, "extra": 1}):
        assert api.client.put(path, headers=api.headers, json=invalid).status_code == 422
    assert api.stranger_get(path + "/events").status_code == 404
