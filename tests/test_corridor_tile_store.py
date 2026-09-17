"""Migration 0072: how a baked tile is recorded, what a differing rebake does, and who may write.

Every check here runs against a migrated schema. The fault path is the tessellator lane's gate 5:
a key that bakes twice into different containers keeps its stored row and is marked, and nothing
serves it afterwards. The write path is the offline bake's alone; the runtime role may record that
a workspace was served a tile, and may not publish one.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from exulanica.api.quotas import declare_tile_quota
from exulanica.db.roles import INSERT_ONLY_TABLES, READ_ONLY_TABLES, provision_runtime_role
from exulanica.orchestration.judge_seed import GLOBAL_TABLES
from exulanica.store.namespaces import TILE_NAMESPACE, tile_store
from exulanica.world.baked_tiles import (
    BakedTileFaulted,
    BakedTileRepository,
    TileBytesMissing,
    TileQuotaRefused,
    UnknownBakedTile,
)
from psycopg.rows import dict_row

from pg_harness import migrated_schema
from test_route_permissions import APP_ROLE, app_role_dsn

pytestmark = pytest.mark.postgres

EMPTY_EDIT_DELTA = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


def _tile(tile_x: int = 2, seed: str | None = None) -> dict[str, object]:
    return {
        "tile_inputs_digest": hashlib.sha256(f"inputs {tile_x}".encode()).hexdigest(),
        "city_seed": seed or hashlib.sha256(b"a corridor city").hexdigest(),
        "grammar_versions": [
            {"grammar_id": "city", "grammar_version": 2, "descriptor_sha256": "0" * 64}
        ],
        "catalog_digest": hashlib.sha256(b"catalogs").hexdigest(),
        "edit_delta_digest": EMPTY_EDIT_DELTA,
        "tile_x": tile_x,
        "tile_y": 0,
        "lod": 0,
        "tile_size_mm": 128_000,
        "halo_radius_mm": 64_000,
    }


def _record(repository: BakedTileRepository, key: uuid.UUID, container: bytes, **changes) -> str:
    tile = {**_tile(), **changes.pop("tile", {})}
    return repository.record(
        baked_tile_id=key,
        stage_version=3,
        stage_params_sha256=hashlib.sha256(b"params").digest(),
        tile=tile,
        document=b"a tile document",
        container=container,
        render_batch_sha256=hashlib.sha256(b"render").digest(),
        nav_envelope_sha256=hashlib.sha256(b"nav").digest(),
        receipt={"tessellator": 3, "container": "owd/3"},
    )


@pytest.fixture
def stored(tmp_path) -> Iterator[tuple[psycopg.Connection, BakedTileRepository, str]]:
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        scratch = admin.execute("select current_schema()").fetchone()["current_schema"]
        provision_runtime_role(admin, role=APP_ROLE)
        admin.commit()
        yield admin, BakedTileRepository(connection=admin, store=tile_store(tmp_path)), scratch


def test_the_table_is_global_and_read_only_for_the_runtime():
    assert "baked_tile" in GLOBAL_TABLES
    assert "baked_tile" in READ_ONLY_TABLES
    assert "workspace_baked_tile" in INSERT_ONLY_TABLES


def test_a_bake_is_stored_once_and_the_same_bytes_change_nothing(stored):
    admin, repository, _scratch = stored
    key = uuid.uuid4()
    assert _record(repository, key, b"container one") == "stored"
    assert _record(repository, key, b"container one") == "identical"
    row = admin.execute("select * from baked_tile where baked_tile_id = %s", (key,)).fetchone()
    assert row["state"] == "baked"
    assert row["store_namespace"] == TILE_NAMESPACE
    assert row["fault_container_sha256"] is None
    assert repository.read(key).container_bytes == len(b"container one")


def test_a_rebake_into_other_bytes_keeps_the_row_and_marks_the_fault(stored):
    admin, repository, _scratch = stored
    key = uuid.uuid4()
    _record(repository, key, b"container one")
    assert _record(repository, key, b"container two") == "nondeterminism_detected"
    row = admin.execute("select * from baked_tile where baked_tile_id = %s", (key,)).fetchone()
    assert row["state"] == "nondeterminism_detected"
    assert bytes(row["container_sha256"]) == hashlib.sha256(b"container one").digest()
    assert bytes(row["fault_container_sha256"]) == hashlib.sha256(b"container two").digest()
    assert row["fault_detected_at"] is not None
    # And it stays that way, whatever bakes next.
    assert _record(repository, key, b"container one") == "nondeterminism_detected"
    with pytest.raises(BakedTileFaulted):
        repository.serve(uuid.uuid4(), key)


def test_one_tile_document_baked_by_two_tessellators_makes_two_rows(stored):
    """The case migration 0077 exists for, and the one 0072 forbade by accident.

    A tile document says nothing about the tessellator, so its `tile_inputs_digest` does not move
    when the tessellator does. The key does, because it is uuid5 over the stage version, the stage
    params digest and that digest, which is how a new tessellator's bake becomes a new row rather
    than a fault under the old key. 0072 made `tile_inputs_digest` unique on its own, so the first
    bake after a tessellator bump failed on a key that had correctly moved.
    """
    _admin, repository, _scratch = stored
    older, newer = uuid.uuid4(), uuid.uuid4()
    assert _record(repository, older, b"as the old tessellator wrote it") == "stored"
    assert (
        repository.record(
            baked_tile_id=newer,
            stage_version=3,
            # The same tile, the same inputs; a tessellator whose stated version has moved.
            stage_params_sha256=hashlib.sha256(b"params with tessellator 5").digest(),
            tile=_tile(),
            document=b"a tile document",
            container=b"as the new tessellator writes it",
            render_batch_sha256=hashlib.sha256(b"render").digest(),
            nav_envelope_sha256=hashlib.sha256(b"nav that now holds triangles").digest(),
            receipt={"tessellator": 5, "container": "owd/3"},
        )
        == "stored"
    )
    # Both are servable, neither is faulted, and the older bake is still exactly what it was.
    assert repository.read(older).state == "baked"
    assert repository.read(newer).state == "baked"
    assert repository.read(older).container_bytes == len(b"as the old tessellator wrote it")


def test_two_keys_may_not_claim_one_bake(stored):
    """The other half of 0077: the key is a uuid5 the caller computes, so the database checks that
    two rows cannot claim the same (stage version, params, inputs) under different uuids."""
    _admin, repository, _scratch = stored
    assert _record(repository, uuid.uuid4(), b"one bake") == "stored"
    with pytest.raises(psycopg.errors.UniqueViolation):
        _record(repository, uuid.uuid4(), b"the same bake under another uuid")


def test_a_tile_carrying_edits_is_refused_outright(stored):
    admin, repository, _scratch = stored
    with pytest.raises(psycopg.errors.CheckViolation):
        _record(
            repository,
            uuid.uuid4(),
            b"edited",
            tile={"edit_delta_digest": hashlib.sha256(b"an edit").hexdigest()},
        )
    admin.rollback()


def test_an_unknown_key_and_missing_bytes_are_named_apart(stored, tmp_path):
    admin, repository, _scratch = stored
    with pytest.raises(UnknownBakedTile):
        repository.read(uuid.uuid4())
    key = uuid.uuid4()
    _record(repository, key, b"container one")
    empty = BakedTileRepository(connection=admin, store=tile_store(tmp_path / "elsewhere"))
    workspace = uuid.uuid4()
    admin.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
    declare_tile_quota(admin, workspace, tiles_limit=4, declared_by=uuid.uuid4())
    with pytest.raises(TileBytesMissing):
        empty.serve(workspace, key)


def test_a_workspace_is_charged_once_for_a_tile_however_often_it_is_served(stored):
    admin, repository, _scratch = stored
    workspace = uuid.uuid4()
    admin.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
    declare_tile_quota(admin, workspace, tiles_limit=1, declared_by=uuid.uuid4())
    first, second = uuid.uuid4(), uuid.uuid4()
    _record(repository, first, b"container one")
    _record(repository, second, b"container two", tile={"tile_inputs_digest": "1" * 64})
    assert repository.serve(workspace, first).charged is True
    assert repository.serve(workspace, first).charged is False
    used = admin.execute(
        "select tiles_used from workspace_tile_quota where workspace_id = %s", (workspace,)
    ).fetchone()["tiles_used"]
    assert used == 1
    with pytest.raises(TileQuotaRefused):
        repository.serve(workspace, second)


def test_a_workspace_with_no_quota_is_served_nothing(stored):
    admin, repository, _scratch = stored
    workspace = uuid.uuid4()
    admin.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
    key = uuid.uuid4()
    _record(repository, key, b"container one")
    with pytest.raises(TileQuotaRefused):
        repository.serve(workspace, key)


def test_the_delivery_ledger_is_forced_row_level_security_keyed_on_the_workspace(stored):
    admin, _repository, scratch = stored
    row = admin.execute(
        "select c.relrowsecurity, c.relforcerowsecurity, p.policyname, p.qual "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "left join pg_policies p on p.schemaname = n.nspname and p.tablename = c.relname "
        "where n.nspname = %s and c.relname = 'workspace_baked_tile'",
        (scratch,),
    ).fetchone()
    assert (row["relrowsecurity"], row["relforcerowsecurity"]) == (True, True)
    assert row["policyname"] == "ws_isolation"
    assert "current_workspace()" in row["qual"]


def test_the_runtime_role_may_record_a_delivery_and_may_not_publish_a_tile(stored, tmp_path):
    admin, repository, scratch = stored
    key = uuid.uuid4()
    _record(repository, key, b"container one")
    workspace = uuid.uuid4()
    admin.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
    declare_tile_quota(admin, workspace, tiles_limit=3, declared_by=uuid.uuid4())
    admin.commit()
    with psycopg.connect(app_role_dsn(scratch), autocommit=True, row_factory=dict_row) as runtime:
        runtime.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
        served = BakedTileRepository(connection=runtime, store=tile_store(tmp_path)).serve(
            workspace, key
        )
        assert served.data == b"container one"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute(
                "update baked_tile set receipt = '{}'::jsonb where baked_tile_id = %s", (key,)
            )
