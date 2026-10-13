"""An actual dump/restore/replay forgets draft content and keeps financial identifiers."""

from dataclasses import replace

import pytest
from exulanica.api.app import create_app
from exulanica.api.kind_drafts import KindDrafts
from exulanica.deletion.restore import verify_restore
from exulanica.world.world_erasure import erase_world
from fastapi.testclient import TestClient

import test_world_making_postgres as native
from spending_support import bench as bench
from test_purge import purged as purged
from test_restore_replay import _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _replay
from test_world_draft_native_postgres import HEADERS, done
from test_world_making_postgres import (  # noqa: F401
    _drafts_alias,
    _named_alias,
    imported_drafts,
    saved_named,
)

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("scope", ["world", "workspace"])
def test_restore_replays_erasure_of_draft_content_without_refunding_spend(
    drafts,
    bench,
    purged,
    commands,
    tmp_path,
    scope,
):
    factory, transport = drafts
    transport.responses.extend(
        [
            native._tool("town", native.TOWN_WORDS),
            native._json(native._town_form()),
            *native._plain(),
        ]
    )
    with factory() as client:
        services = client.app.state.services
        session = services.tokens.session_for(native.TOKEN)
        assert session.workspace_id == purged.workspace_id
        prepared = client.post(
            "/selection/world-drafts/prepare",
            headers=HEADERS,
            json={"description": native.TOWN_WORDS},
        ).json()
        body = prepared["steps"][0]["body"]
        start = client.post("/worlds/drafts", headers=HEADERS, json=body)
        assert start.status_code == 202, start.text
        result = done(client, start.json()["draft_id"])
        assert result["state"] == "ready", result
    # The private API and its workers have stopped before this schema is dumped/restored.
    asked = len(transport.requests)
    liability = bench.query(
        "select reservation_id,state,reserved_usd,settled_usd "
        "from spending_reservation order by reservation_id"
    )
    bounds = bench.query("select * from world_draft_bound order by provider")
    anchors = bench.query("select * from world_draft_start")
    dump, blobs = _backup(purged, tmp_path)
    with bench.runtime.session(session.workspace_id) as connection:
        if scope == "world":
            erase_world(
                connection,
                session.workspace_id,
                result["entry"]["world_id"],
                erased_by=session.actor,
            )
        else:
            connection.execute(
                "insert into tombstone(workspace_id,scope,requested_by,reason) "
                "values(%s,'workspace',%s,'Private restore fixture erasure')",
                (session.workspace_id, session.actor),
            )
    assert bench.query("select 1 from world_draft_request") == []
    source, marker = _seal(tmp_path)
    _restore(purged, dump, blobs)
    assert bench.query("select 1 from world_draft_request")  # Positive control: backup held words.
    _replay(source, marker)
    verify_restore(purged.database(), marker)
    for table in (
        "world_draft_request",
        "world_draft_input",
        "world_draft_progress",
        "world_draft_attempt",
        "world_draft_outcome",
    ):
        assert bench.query(f"select 1 from {table}") == []
    assert bench.query("select * from world_draft_start") == anchors
    assert bench.query("select * from world_draft_bound order by provider") == bounds
    assert (
        bench.query(
            "select reservation_id,state,reserved_usd,settled_usd "
            "from spending_reservation order by reservation_id"
        )
        == liability
    )
    assert bench.query("select payload from job where kind='world_draft'") == [{"payload": {}}]
    restarted = replace(services, kind_drafts=KindDrafts())
    with TestClient(create_app(restarted, verify=False)) as client:
        assert (
            client.get(f"/worlds/drafts/{result['draft_id']}", headers=HEADERS).status_code == 404
        )
        assert client.post("/worlds/drafts", headers=HEADERS, json=body).status_code == 404
    assert len(transport.requests) == asked
