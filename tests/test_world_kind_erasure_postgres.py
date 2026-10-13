"""Kept world-kind erasure protects authority, copied receipts and real backup replay."""

from __future__ import annotations

import copy
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from exulanica.deletion.restore import verify_restore
from exulanica.world.composers import site_plan
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.erasure import KindErasureRefused, erase_kind, removal_preview
from exulanica.world.kinds.repository import WorkspaceKinds
from exulanica.world.kinds.samples import check_samples
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.world_erasure import erase_world
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from test_kind_requirements import compile_, farm
from test_purge import purged as purged
from test_restore_replay import _app, _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _replay
from test_support_site import authoring
from test_tombstone_workspace_lock_postgres import waiting
from test_world_kinds_postgres import _uploaded

pytestmark = pytest.mark.postgres


def _context(purged):
    app, headers = _app(purged, None)
    [session] = app.state.services.tokens.sessions.values()
    return app, headers, session.workspace_id, session.actor


def _keep(purged, workspace, actor, kind):
    with purged.database().session(workspace) as connection:
        WorkspaceKinds(connection, workspace).append(kind, check_samples(kind), created_by=actor)


def _make(purged, workspace, actor, kind, *, support=False, composed=None):
    world_id = f"world:generated:{uuid.uuid4()}"
    values = kind.values(kind.presets[0][0])
    if support:
        baseline = site_plan.compose_kind(kind, values, world_id, place_id="place:erasure")
        composed = site_plan.compose_kind(kind, values, world_id, support=authoring(baseline.place))
    if composed is not None:
        world_id = composed.receipt["world_id"]
    with purged.database().session(workspace) as connection:
        return SavedWorldEntryRepository(connection, workspace, purged.store).create_from_kind(
            title="An independent world",
            kind=kind,
            values=values,
            created_by=actor,
            fixed_world_id=world_id,
            compose=None if composed is None else lambda *_: composed,
        )


@pytest.mark.parametrize("requirements", [False, True])
def test_api_erases_one_version_and_sql_retires_content_and_identity(purged, requirements):
    app, headers, workspace, actor = _context(purged)
    kind = read_kind(compile_(farm()).document if requirements else _uploaded("farm"))
    _keep(purged, workspace, actor, kind)
    later_document = copy.deepcopy(dict(kind.document))
    later_document["version"] += 1
    later = read_kind(later_document)
    _keep(purged, workspace, actor, later)
    with purged.database().session(workspace) as connection:
        original = connection.execute(
            "select to_jsonb(k) as row from world_kind_version k where workspace_id=%s "
            "and document_sha256=%s",
            (workspace, kind.sha256),
        ).fetchone()["row"]
        with pytest.raises(KindErasureRefused, match="creator"):
            erase_kind(connection, workspace, kind.sha256, erased_by=uuid.uuid4())
    path = f"/worlds/kinds/versions/{kind.sha256}"
    with TestClient(app) as client:
        # Deletion remains available while accepting new kinds is disabled.
        assert not app.state.services.kinds_from_people
        assert client.get(path + "/removal", headers=headers).json()["removable"]
        removed = client.delete(path, headers=headers)
        assert removed.status_code == 204, removed.text
        assert client.delete(path, headers=headers).status_code == 410
        assert (
            client.delete("/worlds/kinds/versions/" + "0" * 64, headers=headers).status_code == 404
        )
    with purged.database().session(workspace) as connection:
        kinds = WorkspaceKinds(connection, workspace)
        assert kinds.version(kind.kind, kind.version) is None
        assert kinds.version(later.kind, later.version).kind.sha256 == later.sha256
        record = connection.execute(
            "select * from world_kind_erasure where workspace_id=%s", (workspace,)
        ).fetchone()
        assert set(record) == {
            "workspace_id",
            "erasure_id",
            "document_sha256",
            "kind_key_sha256",
            "version",
            "tombstone_id",
            "erased_by",
            "erased_at",
            "kind_draft_id",
        }
        # An uploaded kind has no native generation request to erase on restore.
        assert record["kind_draft_id"] is None
        assert record["kind_key_sha256"] == hashlib.sha256(kind.kind.encode()).hexdigest()
        with pytest.raises(KindErasureRefused, match="permanently erased"):
            kinds.append(kind, check_samples(kind), created_by=actor)
        # Bypass Python preflight, and change document bytes under the retired key/version.
        for modified in (False, True):
            row = copy.deepcopy(original)
            if modified:
                doc = row["document"]
                doc["label"] += " changed"
                changed = read_kind(doc)
                row["document_sha256"] = changed.sha256
                row["validation"] = check_samples(changed)
            with pytest.raises(psycopg.errors.CheckViolation) as refused, connection.transaction():
                connection.execute(
                    "insert into world_kind_version select * from "
                    "jsonb_populate_record(null::world_kind_version,%s)",
                    (Jsonb(row),),
                )
            assert refused.value.diag.constraint_name == "world_kind_erased"


@pytest.mark.parametrize("support", [False, True])
def test_all_retained_receipts_block_erasure_and_stale_composition_cannot_publish(purged, support):
    _, _, workspace, actor = _context(purged)
    kind = read_kind(_uploaded("farm"))
    _keep(purged, workspace, actor, kind)
    entry = _make(purged, workspace, actor, kind, support=support)
    with purged.database().session(workspace) as connection:
        preview = removal_preview(connection, workspace, kind.sha256, actor=actor)
        assert not preview["removable"] and preview["world_receipts"] == 1
        with pytest.raises(KindErasureRefused, match="retained world"):
            erase_kind(connection, workspace, kind.sha256, erased_by=actor)
        assert not connection.execute("select 1 from world_kind_erasure").fetchall()
        erase_world(connection, workspace, entry.world_id, erased_by=actor)
    stale = site_plan.compose_kind(
        kind, kind.values("small_farm"), f"world:generated:{uuid.uuid4()}"
    )
    with purged.database().session(workspace) as connection:
        erase_kind(connection, workspace, kind.sha256, erased_by=actor)
    with pytest.raises(psycopg.errors.CheckViolation) as refused:
        _make(purged, workspace, actor, kind, composed=stale)
    assert refused.value.diag.constraint_name == "world_kind_erased"
    with purged.database().session(workspace) as connection:
        assert not connection.execute(
            "select 1 from world_identity where workspace_id=%s and world_id=%s",
            (workspace, stale.receipt["world_id"]),
        ).fetchall(), "late publication rolls back registration as well as receipt"


@pytest.mark.parametrize("backup_at", ["before-kind", "kept-kind", "used-kind"])
def test_actual_restore_carries_erasure_before_and_after_creation(
    purged, commands, tmp_path, backup_at
):
    _, _, workspace, actor = _context(purged)
    kind = read_kind(_uploaded("farm"))
    if backup_at == "before-kind":
        dump, blobs = _backup(purged, tmp_path)
    _keep(purged, workspace, actor, kind)
    entry = (
        _make(purged, workspace, actor, kind, support=True) if backup_at == "used-kind" else None
    )
    if backup_at != "before-kind":
        dump, blobs = _backup(purged, tmp_path)
    with purged.database().session(workspace) as connection:
        if entry is not None:
            erase_world(connection, workspace, entry.world_id, erased_by=actor)
        erase_kind(connection, workspace, kind.sha256, erased_by=actor)
    source, marker = _seal(tmp_path)
    carried = source.read_text()
    assert kind.kind not in carried and kind.label not in carried
    _restore(purged, dump, blobs)
    with purged.database().session(workspace) as connection:
        held = WorkspaceKinds(connection, workspace).version(kind.kind, kind.version)
        assert (held is not None) == (backup_at != "before-kind")
        if entry is not None:
            assert connection.execute(
                "select 1 from world_generation_receipt where workspace_id=%s and world_id=%s",
                (workspace, entry.world_id),
            ).fetchone(), "positive control: old backup restores full support receipt"
    _replay(source, marker)
    verify_restore(purged.database(), marker)
    with purged.database().session(workspace) as connection:
        assert WorkspaceKinds(connection, workspace).version(kind.kind, kind.version) is None
        assert (
            connection.execute("select count(*) as n from world_kind_erasure").fetchone()["n"] == 1
        )
        with pytest.raises(KindErasureRefused, match="permanently erased"):
            WorkspaceKinds(connection, workspace).append(
                kind, check_samples(kind), created_by=actor
            )
        if entry is not None:
            assert not connection.execute(
                "select 1 from world_generation_receipt where workspace_id=%s and world_id=%s",
                (workspace, entry.world_id),
            ).fetchall()


def test_runtime_erasure_works_without_parsing_and_sealed_restore_leaves_no_partial_rows(
    purged, repository, spine_schema, monkeypatch
):
    from exulanica.db.roles import provision_runtime_role
    from exulanica.world.kinds import repository as kind_repository

    from conftest import scratch_role_database
    from test_existence_oracle import _RUNTIME_ROLE

    _, _, workspace, actor = _context(purged)
    kind = read_kind(_uploaded("farm"))
    _keep(purged, workspace, actor, kind)
    provision_runtime_role(repository.connection, role=_RUNTIME_ROLE)
    repository.connection.commit()
    database = scratch_role_database(spine_schema[1], _RUNTIME_ROLE)
    repository.connection.execute(
        "insert into restore_control(checkpoint_id,checkpoint_sha256,state) values(%s,%s,'sealed')",
        (uuid.uuid4(), "b" * 64),
    )
    repository.connection.commit()
    with database.session(workspace) as connection:
        with pytest.raises(KindErasureRefused, match="sealed"):
            erase_kind(connection, workspace, kind.sha256, erased_by=actor)
        assert not connection.execute("select 1 from world_kind_erasure").fetchall()
        assert WorkspaceKinds(connection, workspace).version(kind.kind, kind.version)
    repository.connection.execute("delete from restore_control")
    repository.connection.commit()

    def no_parse(*_):
        raise AssertionError("an erasure must not need a parseable document")

    monkeypatch.setattr(kind_repository, "_read_stored", no_parse)
    with database.session(workspace) as connection:
        # Owner override, as supplied only by the current browser membership at the route.
        erase_kind(connection, workspace, kind.sha256, erased_by=uuid.uuid4(), by_owner=True)
        for operation in (
            "delete from world_kind_erasure",
            "update world_kind_erasure set version=2",
        ):
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(operation)


def test_inline_same_key_version_with_different_bytes_neither_blocks_nor_revives_kept_kind(purged):
    _, _, workspace, actor = _context(purged)
    original = read_kind(_uploaded("farm"))
    _keep(purged, workspace, actor, original)
    document = copy.deepcopy(dict(original.document))
    document["label"] = "An independent inline farm"
    inline = read_kind(document)
    assert (inline.kind, inline.version) == (original.kind, original.version)
    assert inline.sha256 != original.sha256
    earlier = _make(purged, workspace, actor, inline)
    with purged.database().session(workspace) as connection:
        assert removal_preview(connection, workspace, original.sha256, actor=actor)["removable"]
        erase_kind(connection, workspace, original.sha256, erased_by=actor)
    later = _make(purged, workspace, actor, inline)
    with purged.database().session(workspace) as connection:
        for entry in (earlier, later):
            row = connection.execute(
                "select receipt->'kind'->>'sha256' as digest from world_generation_receipt "
                "where workspace_id=%s and world_id=%s",
                (workspace, entry.world_id),
            ).fetchone()
            assert row["digest"] == inline.sha256
        # The receipt identity is independent, but the old kept-library version stays retired.
        with pytest.raises(KindErasureRefused, match="permanently erased"):
            WorkspaceKinds(connection, workspace).append(
                inline, check_samples(inline), created_by=actor
            )
    with pytest.raises(psycopg.errors.CheckViolation) as refused:
        _make(purged, workspace, actor, original)
    assert refused.value.diag.constraint_name == "world_kind_erased"


def test_publication_waiting_on_uncommitted_erasure_cannot_keep_its_old_document(purged):
    _, _, workspace, actor = _context(purged)
    kind = read_kind(_uploaded("farm"))
    _keep(purged, workspace, actor, kind)
    world_id = f"world:generated:{uuid.uuid4()}"
    values = kind.values("small_farm")
    composed = site_plan.compose_kind(kind, values, world_id)
    database = purged.database()
    with (
        database.session(workspace) as erasing,
        database.session(workspace) as publishing,
        database.session(workspace) as observer,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):

        def publish():
            return SavedWorldEntryRepository(publishing, workspace, purged.store).create_from_kind(
                title="Already composed",
                kind=kind,
                values=values,
                created_by=actor,
                fixed_world_id=world_id,
                compose=lambda *_: composed,
            )

        with erasing.transaction():
            erase_kind(erasing, workspace, kind.sha256, erased_by=actor)
            future = executor.submit(publish)
            waiting(observer, publishing.info.backend_pid)
            assert observer.execute(
                "select %s=any(pg_blocking_pids(%s)) as blocked",
                (erasing.info.backend_pid, publishing.info.backend_pid),
            ).fetchone()["blocked"], "the publication waits on this uncommitted erasure"
        with pytest.raises(psycopg.errors.CheckViolation) as refused:
            future.result(timeout=10)
        assert refused.value.diag.constraint_name == "world_kind_erased"
        assert not observer.execute(
            "select 1 from world_identity where workspace_id=%s and world_id=%s",
            (workspace, world_id),
        ).fetchall()
