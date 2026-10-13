"""Removing a v2 world erases its requirements and draft words across restore."""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest
from exulanica.api.kind_drafts import KindDrafts
from exulanica.world.errors import WorldRemoved
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.repository import WorkspaceKinds
from exulanica.world.kinds.samples import check_samples
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.world_draft_jobs import WorldDraftRepository
from exulanica.world.worlds import require_world
from fastapi.testclient import TestClient

from test_kind_requirements import DESCRIPTION, claim, compile_, farm
from test_purge import purged as purged
from test_restore_replay import _app, _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _replay
from test_world_draft_jobs_postgres import submit

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("keep_library_kind", [False, True], ids=["receipt-only", "kept-library"])
def test_v2_world_removal_and_restore_erase_receipt_and_omissions_preserve_library(
    purged, commands, tmp_path, keep_library_kind
):
    omitted = claim("a flying boat", (), status="omitted", omission="unsupported_behavior", form="")
    kind = read_kind(compile_(farm(claim(), omitted), size=True).document)
    assert kind.origin == "drafted"
    app, headers = _app(purged, None)
    [session] = app.state.services.tokens.sessions.values()
    workspace, actor = session.workspace_id, session.actor
    with purged.database().session(workspace) as connection:
        if keep_library_kind:
            WorkspaceKinds(connection, workspace).append(
                kind, check_samples(kind), created_by=actor
            )
        drafts = WorldDraftRepository(connection, workspace)
        draft_id = submit(drafts, actor, uuid.uuid4(), DESCRIPTION, maximum=1)
        queued = drafts.get(actor, draft_id)
        # No provider work is needed: claim a durable fixture job and finish it with the
        # independently compiled kind, through the same fenced completion as a worker.
        connection.execute("update job set run_after=now() where job_id=%s", (queued["job_id"],))
        claimed = drafts.claim()
        assert claimed is not None and claimed.draft_id == draft_id
        connection.execute(
            "select set_config('exulanica.world_draft_claim',%s,false)",
            (str(claimed.claim_token),),
        )
        entry = SavedWorldEntryRepository(connection, workspace, purged.store).create_from_kind(
            title="A private requirement world",
            kind=kind,
            values=kind.values(kind.presets[0][0]),
            created_by=actor,
            fixed_world_id=claimed.world_id,
        )
        drafts.finish(
            claimed,
            dict(
                profile="exulanica.world-draft-result/v1",
                state="ready",
                entry_id=str(entry.entry_id),
                left_out=["a flying boat"],
                calls=[],
            ),
        )
        anchors = connection.execute("select * from world_draft_start").fetchall()
        _digest, receipt = generation_receipt(
            connection, workspace, entry.world_id, entry.source_snapshot_id
        )
        saved_kind = receipt["kind"]["document"]
        assert saved_kind["profile"] == "exulanica.world-kind/v2"
        for key in ("requirement_source", "requirements"):
            assert saved_kind[key] == kind.document[key]
        assert "a flying boat" not in json.dumps(dict(receipt))
        library_before = connection.execute(
            "select to_jsonb(k) as row from world_kind_version k where workspace_id=%s",
            (workspace,),
        ).fetchall()
        assert bool(library_before) is keep_library_kind

    dump, blobs = _backup(purged, tmp_path)
    draft_path = f"/worlds/drafts/{draft_id}"

    with TestClient(app) as client:
        response = client.get(draft_path, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["left_out"] == ["a flying boat"]
        response = client.delete(f"/worlds/{entry.world_id}", headers=headers)
        assert response.status_code == 204, response.text
        response = client.get(draft_path, headers=headers)
        assert response.status_code == 404, response.text
        assert "a flying boat" not in response.text

        # A fresh process-local holder reads the same durable erasure authority.
        app.state.services = dataclasses.replace(app.state.services, kind_drafts=KindDrafts())
        response = client.get(draft_path, headers=headers)
        assert response.status_code == 404, response.text
        assert "a flying boat" not in response.text

    def assert_erased():
        with purged.database().session(workspace) as connection:
            for table in (
                "world_draft_request",
                "world_draft_input",
                "world_draft_progress",
                "world_draft_attempt",
                "world_draft_outcome",
            ):
                assert not connection.execute(f"select 1 from {table}").fetchall()
            assert connection.execute("select * from world_draft_start").fetchall() == anchors
            assert WorldDraftRepository(connection, workspace).allowance(actor, 1)["left"] == 0
            assert not connection.execute(
                "select 1 from world_generation_receipt where workspace_id=%s and world_id=%s",
                (workspace, entry.world_id),
            ).fetchall()
            assert not connection.execute(
                "select 1 from saved_world_entry where workspace_id=%s and world_id=%s",
                (workspace, entry.world_id),
            ).fetchall()
            erasure = connection.execute(
                "select to_jsonb(e) as row from world_erasure e "
                "where workspace_id=%s and world_id=%s",
                (workspace, entry.world_id),
            ).fetchone()["row"]
            for value in (
                "requirement_source",
                "requirements",
                "a flying boat",
                DESCRIPTION,
                entry.title,
                kind.sha256,
                kind.document["requirement_source"]["sha256"],
            ):
                assert value not in json.dumps(erasure)
            assert (
                connection.execute(
                    "select to_jsonb(k) as row from world_kind_version k where workspace_id=%s",
                    (workspace,),
                ).fetchall()
                == library_before
            )
            with pytest.raises(WorldRemoved):
                require_world(connection, workspace, entry.world_id)

    assert_erased()
    source, marker = _seal(tmp_path)
    for value in ("a flying boat", DESCRIPTION, entry.title):
        assert value not in source.read_text()
    _restore(purged, dump, blobs)
    with purged.database().session(workspace) as connection:
        restored = WorldDraftRepository(connection, workspace).get(actor, draft_id)
        assert restored["outcome"]["left_out"] == ["a flying boat"]
    _replay(source, marker)
    assert_erased()
    with TestClient(app) as client:
        response = client.get(draft_path, headers=headers)
        assert response.status_code == 404, response.text
        assert "a flying boat" not in response.text
