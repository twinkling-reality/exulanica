"""A made town's tiles baked with a version's changes: its workspace's own, and erased with it
(migration 0219).

Against PostgreSQL as a deployment runs it: the API and the worker's claims as the runtime role,
publishes as the tile role, the purge as the purge role, each under row-level security. The tile
documents are baked by a stand-in tessellator whose bytes are named by the document it was given,
so a second bake of one document is identical (as ``tests/test_generated_worlds.py`` bakes them).

*   a version whose change to a building alters a tile lists that tile as baking, then, once its
    queued job is baked, as its workspace's bake, keyed by the changes' fold; the bytes route serves
    it from the workspace's own namespace to that version alone, and the shared tile store never
    holds it;
*   ``record_version_baked_tile`` writes only for a running ``bake_version_tile`` job of the
    session's workspace under its claim token, naming this version and tile, with the bytes in the
    namespace's inventory; no role writes the table directly;
*   a world's erasure deletes its bakes, cancels its queued bakes and enqueues their bytes on its
    tombstone, which the purge destroys, completing it; a workspace's tombstone does the same for
    every object its namespace holds.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import threading
import uuid

import psycopg
import pytest
from exulanica.db.roles import provision_purge_role
from exulanica.db.session import set_workspace
from exulanica.db.tiles_role import assert_tiles_role, provision_tiles_role
from exulanica.deletion.worker import PurgeWorker
from exulanica.evidence.blob import BlobId
from exulanica.ingest import generated_tiles
from exulanica.ingest.generated_tiles import GeneratedTileBaker, claim_bake
from exulanica.ingest.stages import STAGES, baked_tile_key
from exulanica.store.configured import local_content_stores
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import version_tile_lock_key
from exulanica.world import version_tiles as version_tiles_module
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import BAKE_JOB_KIND, town_records, version_ground
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import ElementOverride
from exulanica.world.town_parts import town_buildings
from exulanica.world.version_tiles import (
    VERSION_BAKE_JOB_KIND,
    queue_version_bakes,
    version_changes,
)
from psycopg.rows import dict_row

from baked_tile_stages import stated_stage
from conftest import scratch_role_database
from personal_world_support import OWNER_TOKEN, STRANGER_TOKEN
from test_generated_worlds import _stub_tessellator
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

TILES_ROLE = "exulanica_tiles_version_suite"
PURGE_ROLE = "exulanica_purge_version_suite"


@pytest.fixture(name="made")
def _made_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_made")


@dataclasses.dataclass
class Town:
    """A small town made through the API, its public tiles baked, and one of its buildings removed
    in its version."""

    api: object
    scratch: str
    stores: object
    baker: GeneratedTileBaker
    entry: dict
    snapshot_id: uuid.UUID
    version_id: uuid.UUID

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.api.repository.workspace_id  # type: ignore[attr-defined]

    @property
    def world_id(self) -> str:
        return str(self.entry["world_id"])

    def owner_rows(self, sql: str, *params):  # type: ignore[no-untyped-def]
        """Rows read as the owner, across every workspace."""
        connection = self.api.repository.connection  # type: ignore[attr-defined]
        with connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(sql, params).fetchall()
        connection.commit()
        return rows

    def session(self):  # type: ignore[no-untyped-def]
        return self.api.database.session(self.workspace_id)  # type: ignore[attr-defined]

    def change(self, override: ElementOverride, building: str) -> None:
        version = self.api.version(self.entry)  # type: ignore[attr-defined]
        with self.session() as connection:
            WorldObjectRepository(
                connection, self.workspace_id, world_id=self.world_id
            ).set_part_change(
                self.version_id,
                override,
                base_state_sha256=version["state_sha256"],
                actor=self.api.actor,  # type: ignore[attr-defined]
                part_ids=frozenset({building}),
            )

    def buildings(self) -> list[str]:
        with self.session() as connection:
            generated = town_records(connection, self.workspace_id, self.world_id, self.snapshot_id)
        return [building.identity for building in town_buildings(generated.records)]

    def tiles(self):  # type: ignore[no-untyped-def]
        with self.session() as connection:
            return version_ground(
                connection, self.workspace_id, self.world_id, self.snapshot_id, self.version_id
            ).tiles

    def queue(self):  # type: ignore[no-untyped-def]
        with self.session() as connection, connection.transaction():
            changes = version_changes(
                connection, self.workspace_id, self.world_id, self.snapshot_id, self.version_id
            )
            return queue_version_bakes(
                connection,
                self.workspace_id,
                self.world_id,
                self.snapshot_id,
                self.version_id,
                changes,
            )

    def bytes_path(self, baked_tile_id, version_id=None) -> str:  # type: ignore[no-untyped-def]
        return (
            f"/world/versions/{version_id or self.version_id}/tiles/{baked_tile_id}/bytes"
            f"?world_id={self.world_id}"
        )

    def in_namespace(self, digest: str) -> bool:
        store = self.stores.version_tiles.for_workspace(self.workspace_id)  # type: ignore[attr-defined]
        return bool(store.exists(BlobId.from_hex(digest)))

    def purge(self) -> None:
        PurgeWorker(
            scratch_role_database(self.scratch, PURGE_ROLE),
            self.stores.blobs,  # type: ignore[attr-defined]
            frozenset({self.workspace_id}),
            name="test-version-tile-purge",
            version_tile_stores=self.stores.version_tiles,  # type: ignore[attr-defined]
        ).drain()


def _tiles_publisher(scratch: str):  # type: ignore[no-untyped-def]
    @contextlib.contextmanager
    def publisher():  # type: ignore[no-untyped-def]
        database = scratch_role_database(scratch, TILES_ROLE)
        with psycopg.connect(database.url, autocommit=True, row_factory=dict_row) as connection:
            yield connection

    return publisher


@pytest.fixture(name="town")
def _town(made, spine_schema, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    _psycopg, scratch = spine_schema
    api = made
    owner = api.repository.connection
    provision_tiles_role(owner, role=TILES_ROLE)
    provision_purge_role(owner, role=PURGE_ROLE)
    owner.commit()
    stores = local_content_stores(tmp_path / "data")
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, tiles=stores.tiles, content_stores=stores
    )
    response = api.post("/worlds/generated", {"recipe": "small_town", "title": "Changed"})
    assert response.status_code == 201, response.text
    entry = response.json()
    baker = GeneratedTileBaker(
        session=api.database.session,
        publisher=_tiles_publisher(scratch),
        store=stores.tiles,
        web_directory=_stub_tessellator(tmp_path, monkeypatch),
        worker="test",
        version_stores=stores.version_tiles,
    )
    public = baker.drain([api.repository.workspace_id])
    assert {o.status for o in public} == {"baked"}
    version = api.version(entry)
    made_town = Town(
        api,
        scratch,
        stores,
        baker,
        entry,
        uuid.UUID(version["source_snapshot_id"]),
        uuid.UUID(entry["authored_version_id"]),
    )
    building = made_town.buildings()[0]
    made_town.change(ElementOverride(f"part:{building}", suppressed=True), building)
    return made_town


def _baked(town: Town) -> list:  # type: ignore[type-arg]
    """Queue the version's changed tiles where not queued yet and bake them; their listing, once
    baked."""
    town.queue()
    pending = town.owner_rows(
        "select payload from job where kind = %s and state = 'queued'", VERSION_BAKE_JOB_KIND
    )
    assert pending, "removing a building of the small town alters a tile"
    outcomes = town.baker.drain([town.workspace_id])
    assert [(o.status, o.detail) for o in outcomes] == [("baked", "stored then identical")] * len(
        pending
    )
    digests = {job["payload"]["tile_inputs_digest"] for job in pending}
    return [t for t in town.tiles() if t.tile_inputs_digest in digests]


def test_a_changed_tile_is_baked_for_its_workspace_and_served_to_its_version_alone(town):
    public = {
        row["tile_inputs_digest"].hex()
        for row in town.owner_rows("select tile_inputs_digest from baked_tile")
    }
    waiting = [t for t in town.tiles() if t.tile_inputs_digest not in public]
    assert waiting and {(t.state, t.baked_tile_id) for t in waiting} == {("baking", None)}
    queued = town.queue()
    assert {(q.tile_x, q.tile_y) for q in queued} == {(t.tile_x, t.tile_y) for t in waiting}
    # A tile queued is not queued twice.
    assert town.queue() == ()
    changed = _baked(town)
    assert {t.state for t in town.tiles()} == {"baked"}
    stored = town.owner_rows(
        "select baked_tile_id, workspace_id, world_id, container_sha256, store_namespace "
        "from world_version_baked_tile"
    )
    assert {row["baked_tile_id"] for row in stored} == {t.baked_tile_id for t in changed}
    assert {(row["workspace_id"], row["world_id"], row["store_namespace"]) for row in stored} == {
        (town.workspace_id, town.world_id, "version-tiles")
    }
    assert not town.owner_rows(
        "select 1 from baked_tile where baked_tile_id = any(%s)",
        [r["baked_tile_id"] for r in stored],
    )
    # Both tables are held to the session's workspace, whatever a statement asks.
    tables = ("world_version_baked_tile", "world_version_tile_object")
    with town.session() as own, town.api.database.session(uuid.uuid4()) as stranger:
        for table in tables:
            assert own.execute(f"select count(*) as n from {table}").fetchone()["n"] > 0
            assert stranger.execute(f"select count(*) as n from {table}").fetchone()["n"] == 0
    objects = town.owner_rows("select world_id, content_sha256 from world_version_tile_object")
    assert {(o["world_id"], o["content_sha256"]) for o in objects} == {
        (town.world_id, row["container_sha256"].hex()) for row in stored
    }
    tile = changed[0]
    served = town.api.get(town.bytes_path(tile.baked_tile_id))
    assert served.status_code == 200, served.text
    container = hashlib.sha256(served.content).hexdigest()
    assert served.headers["etag"] == f'"{container}"'
    assert served.headers["x-exulanica-tile-inputs-digest"] == tile.tile_inputs_digest
    assert town.in_namespace(container)
    assert not town.stores.tiles.exists(BlobId.from_hex(container))
    # Another version of the world, with no change, names the public tile there; a stranger is
    # told the world does not exist.
    version = town.api.version(town.entry)
    with town.session() as connection:
        other = WorldObjectRepository(
            connection, town.workspace_id, world_id=town.world_id
        ).create_version(
            source_snapshot_id=town.snapshot_id,
            title="Unchanged",
            style_version_id=uuid.UUID(version["style_version_id"]),
            created_by=town.api.actor,
        )
    refused = town.api.get(town.bytes_path(tile.baked_tile_id, other.version_id))
    assert refused.status_code == 404, refused.text
    assert refused.json()["code"] == "unknown_reference"
    assert (
        town.api.get(town.bytes_path(tile.baked_tile_id), token=STRANGER_TOKEN).status_code == 404
    )


def test_a_changed_town_s_tiles_of_a_stage_before_are_baked_again_once_by_a_new_worker(
    town, tmp_path, monkeypatch
):
    """A stage change ships with a new worker. A version's changed tiles queue only on a write,
    so without the worker's first look over its workspace a changed town's changed tiles would
    read baking for ever; with it, each is baked once again, and the stored bake stays."""
    before = {t.baked_tile_id for t in _baked(town)}
    assert {t.state for t in town.tiles()} == {"baked"}
    owner = town.api.repository.connection
    spec = STAGES["baked_tile"]
    monkeypatch.setitem(
        generated_tiles.STAGES, "baked_tile", dataclasses.replace(spec, version=spec.version + 1)
    )
    with stated_stage(owner, spec.version + 1, spec.params_digest):
        assert {t.state for t in town.tiles()} == {"baking"}
        worker = GeneratedTileBaker(
            session=town.api.database.session,
            publisher=_tiles_publisher(town.scratch),
            store=town.stores.tiles,
            web_directory=_stub_tessellator(tmp_path, monkeypatch),
            worker="test-after-the-stage",
            version_stores=town.stores.version_tiles,
        )
        outcomes = worker.drain([town.workspace_id])
        assert outcomes and {o.status for o in outcomes} == {"baked"}
        after = town.tiles()
        assert {t.state for t in after} == {"baked"}
        assert not {t.baked_tile_id for t in after} & before
        # Looked over once: nothing more is queued, and the bakes of the stage before stay.
        assert worker.drain([town.workspace_id]) == []
        kept = town.owner_rows(
            "select baked_tile_id from world_version_baked_tile where baked_tile_id = any(%s)",
            list(before),
        )
        assert {row["baked_tile_id"] for row in kept} == before


def test_a_version_whose_changes_its_grammar_refuses_is_passed_over_and_the_worker_bakes_on(
    town, tmp_path, monkeypatch
):
    """A town whose grammar no longer generates it, or refuses a version's changes, raises when its
    changed tiles are asked for. The new worker's first look passes that version over: it still
    queues and bakes the town's own tiles, queues nothing for the refused version, and its drain
    never raises, so one such town cannot stop the worker baking every workspace."""
    _baked(town)
    owner = town.api.repository.connection
    spec = STAGES["baked_tile"]
    monkeypatch.setitem(
        generated_tiles.STAGES, "baked_tile", dataclasses.replace(spec, version=spec.version + 1)
    )
    read = version_tiles_module.version_changes

    def refused(connection, workspace_id, world_id, snapshot_id, version_id):  # type: ignore[no-untyped-def]
        if version_id == town.version_id:
            raise InvalidStructuralData("the town's grammar refuses this version's changes")
        return read(connection, workspace_id, world_id, snapshot_id, version_id)

    monkeypatch.setattr(version_tiles_module, "version_changes", refused)

    def queued(kind: str) -> int:
        return len(town.owner_rows("select 1 from job where kind = %s and state = 'queued'", kind))

    with stated_stage(owner, spec.version + 1, spec.params_digest):
        version_jobs = len(
            town.owner_rows("select 1 from job where kind = %s", VERSION_BAKE_JOB_KIND)
        )
        worker = GeneratedTileBaker(
            session=town.api.database.session,
            publisher=_tiles_publisher(town.scratch),
            store=town.stores.tiles,
            web_directory=_stub_tessellator(tmp_path, monkeypatch),
            worker="test-a-refused-version",
            version_stores=town.stores.version_tiles,
        )
        outcomes = worker.drain([town.workspace_id])
        assert outcomes and {o.status for o in outcomes} == {"baked"}
        assert queued(BAKE_JOB_KIND) == 0 and queued(VERSION_BAKE_JOB_KIND) == 0
        assert (
            len(town.owner_rows("select 1 from job where kind = %s", VERSION_BAKE_JOB_KIND))
            == version_jobs
        )
        assert worker.drain([town.workspace_id]) == []


#: The container the refusals name, which no bake stored.
NEVER_STORED = hashlib.sha256(b"never stored").digest()


def _key(inputs: bytes) -> uuid.UUID:
    """The bake's id these inputs give, by the tile worker's own derivation."""
    return baked_tile_key(STAGES["baked_tile"], inputs.hex())


def _publish(connection, job, token, **changed):  # type: ignore[no-untyped-def]
    """Call the version's publish for ``job`` as the job names it, with ``changed`` in place."""
    payload = job["payload"]
    arguments = {
        "job": job["job_id"],
        "token": token,
        "version": uuid.UUID(payload["version_id"]),
        "inputs": bytes.fromhex(payload["tile_inputs_digest"]),
        "fold": bytes.fromhex(payload["edit_delta_digest"]),
        "container": NEVER_STORED,
        "key": None,
        **changed,
    }
    return connection.execute(
        "select record_version_baked_tile(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, 8, %s, 8, "
        "%s, %s, %s::jsonb) as outcome",
        (
            arguments["job"],
            arguments["token"],
            arguments["version"],
            arguments["key"] or _key(arguments["inputs"]),
            STAGES["baked_tile"].version,
            STAGES["baked_tile"].params_digest,
            arguments["inputs"],
            arguments["fold"],
            payload["tile"][0],
            payload["tile"][1],
            hashlib.sha256(b"document").digest(),
            arguments["container"],
            hashlib.sha256(b"batch").digest(),
            hashlib.sha256(b"nav").digest(),
            json.dumps({}),
        ),
    ).fetchone()


def test_a_version_s_bake_is_published_only_for_a_claimed_job_of_its_workspace_naming_it(town):
    assert town.queue()
    with _tiles_publisher(town.scratch)() as tiles:
        assert_tiles_role(tiles)
        set_workspace(tiles, town.workspace_id)
        with town.session() as runtime:
            [queued] = runtime.execute(
                "select job_id, payload from job where kind = %s order by job_id limit 1",
                (VERSION_BAKE_JOB_KIND,),
            ).fetchall()
            # A job no worker claimed publishes nothing.
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="no claimed"):
                _publish(tiles, queued, uuid.uuid4())
            job = claim_bake(
                runtime, town.workspace_id, worker="test", kinds=(VERSION_BAKE_JOB_KIND,)
            )
            assert job is not None
            token = job["claim_token"]
            # Not with another claim token, and not from another workspace: the job is read in the
            # session's workspace, and the row's workspace is the job's.
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="no claimed"):
                _publish(tiles, job, uuid.uuid4())
            set_workspace(tiles, uuid.uuid4())
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="no claimed"):
                _publish(tiles, job, token)
            set_workspace(tiles, town.workspace_id)
            # Not for another tile key, fold or version than the job names.
            for changed in (
                {"inputs": hashlib.sha256(b"another tile").digest()},
                {"fold": hashlib.sha256(b"another fold").digest()},
                {"version": uuid.uuid4()},
            ):
                with pytest.raises(psycopg.errors.InvalidParameterValue, match="another version"):
                    _publish(tiles, job, token, **changed)
            # Not under another tile's id: a bake's id is the key its inputs give.
            with pytest.raises(psycopg.errors.InvalidParameterValue, match="tile's key"):
                _publish(tiles, job, token, key=uuid.uuid4())
            # Not while the purger holds the lock for these bytes: the publish waits for it.
            lock = version_tile_lock_key(town.workspace_id, NEVER_STORED.hex())
            with town.session() as holder:
                holder.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (lock,))
                tiles.execute("set lock_timeout = '300ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    _publish(tiles, job, token)
                tiles.execute("reset lock_timeout")
                holder.execute("select pg_advisory_unlock(hashtextextended(%s, 0))", (lock,))
            # Not for bytes the namespace's inventory does not hold for the job's world.
            with pytest.raises(psycopg.errors.ForeignKeyViolation, match="inventory"):
                _publish(tiles, job, token)
            # The inventory names only a world its workspace holds.
            with pytest.raises(psycopg.errors.ForeignKeyViolation, match="names a world"):
                runtime.execute(
                    "insert into world_version_tile_object "
                    "(workspace_id, world_id, content_sha256, byte_size) values (%s, %s, %s, 8)",
                    (town.workspace_id, "world:generated:none", NEVER_STORED.hex()),
                )
            # No role writes the table directly: not the tile role, not the runtime role.
            for connection in (tiles, runtime):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(
                        "insert into world_version_baked_tile (workspace_id) values (%s)",
                        (town.workspace_id,),
                    )
    # Nor the owner, who holds every privilege on it: the table's own guard refuses any writer
    # but the publish's.
    owner = town.api.repository.connection
    set_workspace(owner, town.workspace_id)
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="record_version_baked_tile"):
        owner.execute(
            "insert into world_version_baked_tile (workspace_id) values (%s)", (town.workspace_id,)
        )
    owner.rollback()
    assert town.owner_rows("select 1 from world_version_baked_tile") == []


def test_a_world_s_erasure_takes_its_version_tiles_and_the_purge_their_bytes(town):
    changed = _baked(town)
    objects = {
        o["content_sha256"] for o in town.owner_rows("select * from world_version_tile_object")
    }
    assert objects and all(town.in_namespace(digest) for digest in objects)
    # A further change queues bakes the erasure cancels.
    second = town.buildings()[1]
    town.change(ElementOverride(f"part:{second}", suppressed=True), second)
    assert town.queue()
    removed = town.api.client.delete(
        f"/worlds/{town.world_id}", headers={"Authorization": f"Bearer {OWNER_TOKEN}"}
    )
    assert removed.status_code == 204, removed.text
    assert town.owner_rows("select 1 from world_version_baked_tile") == []
    assert {
        (row["state"], row["failure_class"])
        for row in town.owner_rows(
            "select state, failure_class from job where kind = %s", VERSION_BAKE_JOB_KIND
        )
    } <= {("done", None), ("cancelled", "world_removed")}
    [stone] = town.owner_rows(
        "select tombstone_id from world_erasure where world_id = %s", town.world_id
    )
    jobs = town.owner_rows(
        "select target_ref from purge_job where tombstone_id = %s and target_kind = 'version_tile'",
        stone["tombstone_id"],
    )
    assert {job["target_ref"] for job in jobs} == objects
    # The world's tombstone may destroy its world's bytes, and no other bytes of the namespace.
    with scratch_role_database(town.scratch, PURGE_ROLE).session(town.workspace_id) as purger:
        for digest, allowed in [(d, True) for d in objects] + [
            (hashlib.sha256(b"x").hexdigest(), False)
        ]:
            [row] = purger.execute(
                "select version_tile_purge_is_authorized(%s, %s, %s) as allowed",
                (town.workspace_id, stone["tombstone_id"], digest),
            ).fetchall()
            assert row["allowed"] is allowed, digest
    town.purge()
    assert not any(town.in_namespace(digest) for digest in objects)
    assert {
        row["purged_at"] is not None
        for row in town.owner_rows("select purged_at from world_version_tile_object")
    } == {True}
    [complete] = town.owner_rows(
        "select tombstone_purge_is_complete(%s) as done", stone["tombstone_id"]
    )
    assert complete["done"] is True
    # The removed world is answered as removed, its tile with it.
    assert changed and town.api.get(town.bytes_path(changed[0].baked_tile_id)).status_code == 410


def test_a_workspace_tombstone_takes_every_version_tile_and_the_purge_their_bytes(town):
    _baked(town)
    objects = {
        o["content_sha256"] for o in town.owner_rows("select * from world_version_tile_object")
    }
    tombstone = town.api.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    town.api.repository.connection.commit()
    assert town.owner_rows("select 1 from world_version_baked_tile") == []
    jobs = town.owner_rows(
        "select target_ref from purge_job where tombstone_id = %s and target_kind = 'version_tile'",
        tombstone,
    )
    assert {job["target_ref"] for job in jobs} == objects
    town.purge()
    assert not any(town.in_namespace(digest) for digest in objects)
    assert not town.owner_rows("select 1 from world_version_tile_object where purged_at is null")
    # The tombstoned workspace records no more objects.
    with (
        town.session() as runtime,
        pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="tombstoned"),
    ):
        runtime.execute(
            "insert into world_version_tile_object "
            "(workspace_id, world_id, content_sha256, byte_size) values (%s, %s, %s, 8)",
            (town.workspace_id, town.world_id, NEVER_STORED.hex()),
        )


def test_a_world_erasure_a_restore_carries_before_its_tombstone_still_purges(town):
    _baked(town)
    objects = {
        o["content_sha256"] for o in town.owner_rows("select * from world_version_tile_object")
    }
    owner = town.api.repository.connection
    set_workspace(owner, town.workspace_id)
    tombstone = uuid.uuid4()
    with owner.transaction(), owner.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "insert into restore_control (checkpoint_id, checkpoint_sha256, state, restore_id) "
            "values (%s, %s, 'replaying', %s)",
            (uuid.uuid4(), "a" * 64, uuid.uuid4()),
        )
        # Carried first: the world's bakes are deleted, and with no tombstone held nothing is
        # enqueued.
        cursor.execute(
            "insert into world_erasure (workspace_id, world_id, tombstone_id, erased_by, made_at, "
            "tiles) values (%s, %s, %s, %s, now(), 0)",
            (town.workspace_id, town.world_id, tombstone, town.api.actor),
        )
        assert (
            cursor.execute("select count(*) as n from world_version_baked_tile").fetchone()["n"]
            == 0
        )
        assert (
            cursor.execute(
                "select count(*) as n from purge_job where tombstone_id = %s", (tombstone,)
            ).fetchone()["n"]
            == 0
        )
        # Replayed after it, the world's tombstone enqueues the world's bytes.
        cursor.execute(
            "insert into tombstone (tombstone_id, workspace_id, scope, requested_by, reason) "
            "values (%s, %s, 'world', %s, 'world_removed')",
            (tombstone, town.workspace_id, town.api.actor),
        )
        jobs = cursor.execute(
            "select target_ref from purge_job where tombstone_id = %s and "
            "target_kind = 'version_tile'",
            (tombstone,),
        ).fetchall()
        assert {job["target_ref"] for job in jobs} == objects
        raise psycopg.Rollback()


def test_a_bake_job_names_the_version_and_its_fold_and_never_the_changes(town):
    """A person's changes live in the version alone: the job names the version and their fold, the
    worker reads the changes from the version, and a world's erasure leaves no change in a job."""
    removed, second = town.buildings()[:2]
    assert town.queue()
    payloads = [
        row["payload"]
        for row in town.owner_rows("select payload from job where kind = %s", VERSION_BAKE_JOB_KIND)
    ]
    assert payloads and {frozenset(payload) for payload in payloads} == {
        frozenset(
            {
                "world_id",
                "snapshot_id",
                "receipt_sha256",
                "version_id",
                "tile",
                "tile_inputs_digest",
                "edit_delta_digest",
            }
        )
    }
    assert removed not in json.dumps(payloads)
    # The version's changes moved after its jobs were queued: their bakes are refused by name,
    # never made from changes the jobs no longer stand for.
    town.change(ElementOverride(f"part:{second}", suppressed=True), second)
    outcomes = town.baker.drain([town.workspace_id])
    assert outcomes and {o.status for o in outcomes} == {"failed"}
    assert all("no longer the ones this bake was queued for" in o.detail for o in outcomes)
    removed_world = town.api.client.delete(
        f"/worlds/{town.world_id}", headers={"Authorization": f"Bearer {OWNER_TOKEN}"}
    )
    assert removed_world.status_code == 204, removed_world.text
    kept = json.dumps([row["payload"] for row in town.owner_rows("select payload from job")])
    assert removed not in kept and second not in kept


def test_a_purge_started_while_a_bake_s_bytes_are_put_waits_and_destroys_them(town, monkeypatch):
    """A workspace's tombstone written while a version's bytes are being put: the purge waits for
    the put under the bytes' lock and then destroys them. Without the lock it would find no bytes,
    mark the object purged, and the bytes written after would outlive every tombstone."""
    assert town.queue()
    put = LocalContentAddressedStore.put_bytes
    seen: dict = {}

    def put_while_the_workspace_is_erased(self, data):  # type: ignore[no-untyped-def]
        if "version-tiles" in str(self._root) and not seen:
            seen["digest"] = hashlib.sha256(data).hexdigest()
            town.api.repository.insert_tombstone(
                scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
            )
            town.api.repository.connection.commit()
            purge = threading.Thread(target=town.purge)
            purge.start()
            purge.join(timeout=3)
            seen["waited"] = purge.is_alive()
            seen["purge"] = purge
        return put(self, data)

    monkeypatch.setattr(LocalContentAddressedStore, "put_bytes", put_while_the_workspace_is_erased)
    town.baker.drain([town.workspace_id])
    seen["purge"].join(timeout=120)
    assert not seen["purge"].is_alive()
    assert seen["waited"], "the purge did not wait for the bytes being put"
    assert not town.in_namespace(seen["digest"])
    [stored] = town.owner_rows(
        "select purged_at from world_version_tile_object where content_sha256 = %s",
        seen["digest"],
    )
    assert stored["purged_at"] is not None


def test_a_bake_whose_bytes_lock_stays_held_goes_back_to_the_queue(town, monkeypatch):
    """A version's bake waits a bounded time for the purger's lock on its bytes: a lock held past
    the wait sends the job back to the queue with the reason, rather than holding its claim."""
    assert town.queue()
    held = "a version tile's bytes, held by the test"
    monkeypatch.setattr(generated_tiles, "LOCK_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(generated_tiles, "version_tile_lock_key", lambda _workspace, _content: held)
    with town.session() as holder:
        holder.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (held,))
        try:
            outcomes = town.baker.drain([town.workspace_id])
        finally:
            holder.execute("select pg_advisory_unlock(hashtextextended(%s, 0))", (held,))
    assert outcomes and {outcome.status for outcome in outcomes} == {"requeued"}
    assert all("lock on a version tile's bytes" in outcome.detail for outcome in outcomes)
    jobs = town.owner_rows(
        "select state, run_after > now() as later from job where kind = 'bake_version_tile'"
    )
    assert jobs and all(job["state"] == "queued" and job["later"] for job in jobs)
