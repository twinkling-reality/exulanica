"""Current dressing authority survives neither withdrawn sources nor stale cached work."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.world.asset_import import import_reviewed_asset
from exulanica.world.asset_kinds import AssetKind
from exulanica.world.asset_preparation import decode_texture
from exulanica.world.heightfield_contact import read_heightfield_contact
from exulanica.world.heightfield_geometry import read_heightfield_geometry
from exulanica.world.terrain_authoring import CAPABILITIES, DRESSED_PROFILE
from exulanica.world.terrain_dressing import (
    COLLISION,
    FRAME,
    PROFILE,
    compile_terrain_dressing,
    read_terrain_dressing,
)

from asset_lock_support import recorded_store_reads
from static_glb_builder import cube
from test_heightfield_contact import contact_document
from test_heightfield_geometry import terrain
from test_reviewed_asset_import import imported_fixture
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres


@dataclass
class Dressed:
    api: object
    document: dict
    key: str
    digest: str

    def create(self):
        return self.api.post(
            "/worlds/generated/terrain", {"title": "Pinned dressing", "authoring": self.document}
        )

    def paths(self, entry):
        prefix = f"/world/versions/{entry['authored_version_id']}"
        scope = f"?world_id={entry['world_id']}"
        return prefix + "/site" + scope, prefix + "/terrain-contact" + scope

    def withdraw(self):
        admin = self.api.repository.connection
        admin.execute("delete from world_reviewed_asset where asset_key=%s", (self.key,))
        admin.commit()


@pytest.fixture
def dressed(request):
    api = request.getfixturevalue("imported_made")
    manifest, payload, licence = imported_fixture(cube().build())
    key = "test.terrain-authority-" + uuid.uuid4().hex
    manifest = manifest.model_copy(update={"asset_key": key})
    admin = api.repository.connection
    with admin.transaction():
        import_reviewed_asset(
            admin, api.store, manifest, payload, licence, kind=AssetKind.COMPONENT
        )
    source = read_terrain_dressing(
        {
            "profile": PROFILE,
            "frame": FRAME,
            "collision": COLLISION,
            "instances": [
                {
                    "instance_id": "cube",
                    "source": {
                        "kind": "reviewed_component",
                        "asset_key": key,
                        "content_sha256": manifest.content_sha256,
                    },
                    "position_mm": [8000, 1000, -8000],
                    "quarter_turns": 0,
                    "scale_per_mille": 1000,
                }
            ],
        }
    )
    coverage = compile_terrain_dressing(source, {key: payload}, decode_image=decode_texture)
    geometry = read_heightfield_geometry(
        terrain(range(0, 10001, 2000), range(-10000, 1, 2000), [1000] * 36)
    )
    contact = read_heightfield_contact(
        contact_document(geometry, coverage.obstructions_document()), geometry
    )
    document = {
        "profile": DRESSED_PROFILE,
        "region_id": "region:generated",
        "geometry": geometry.document(),
        "geometry_sha256": geometry.sha256,
        "contact": contact.document(),
        "contact_sha256": contact.sha256,
        "bounds_mm": {"east": [0, 10000], "south": [-10000, 0]},
        "entry": {"position_mm": [2000, -2000], "facing_mm": [1, 0]},
        "capabilities": dict(CAPABILITIES),
        "dressing": source.document(),
        "dressing_sha256": source.sha256,
    }
    case = Dressed(api, document, key, manifest.content_sha256)
    try:
        yield case
    finally:
        case.withdraw()


def test_creation_and_cached_delivery_read_store_outside_final_barrier(dressed, monkeypatch):
    api = dressed.api
    reads = recorded_store_reads(
        api.repository.connection,
        api.database,
        api.repository.workspace_id,
        api.store,
        monkeypatch,
        planted=dressed.digest,
    )
    created = dressed.create()
    assert created.status_code == 201, created.text
    assert reads.every, "creation actually read the admitted source"
    assert reads.under_the_lock == []
    for path in dressed.paths(created.json()):
        for _ in range(2):
            before = len(reads.every)
            response = api.get(path)
            assert response.status_code == 200, response.text
            assert len(reads.every) > before, "cached coverage must still read current bytes"
            assert reads.under_the_lock == []


@pytest.mark.parametrize("change", ["withdrawn", "rebound", "wrong_kind", "missing_bytes"])
def test_warm_drawing_and_proof_refuse_unavailable_component(dressed, change):
    api = dressed.api
    created = dressed.create()
    assert created.status_code == 201, created.text
    paths = dressed.paths(created.json())
    for path in paths:
        positive = api.get(path)
        assert positive.status_code == 200, positive.text
    admin = api.repository.connection
    if change == "withdrawn":
        dressed.withdraw()
    elif change == "missing_bytes":
        # Private fixture corruption models lost physical bytes, not an authorized withdrawal.
        (api.store.root / api.store.key_for(BlobId.from_hex(dressed.digest))).unlink()
    else:
        column, value = (
            ("kind", "object") if change == "wrong_kind" else ("content_sha256", "f" * 64)
        )
        from psycopg import sql

        admin.execute(
            sql.SQL("update world_reviewed_asset set {}=%s where asset_key=%s").format(
                sql.Identifier(column)
            ),
            (value, dressed.key),
        )
        admin.commit()
    for path in paths:
        refused = api.get(path)
        assert refused.status_code in (404, 409, 422), refused.text


def _authority_counts(api):
    return tuple(
        api.repository.connection.execute(
            f"select count(*) as n from {table} where workspace_id=%s",
            (api.repository.workspace_id,),
        ).fetchone()["n"]
        for table in ("saved_world_entry", "world_structure_snapshot", "world_generation_receipt")
    )


def test_source_withdrawn_after_composition_rolls_back_all_created_authorities(
    dressed, monkeypatch
):
    from exulanica.world.kinds.worker import TerrainWorkerComposer

    before = _authority_counts(dressed.api)
    original = TerrainWorkerComposer.__call__
    completed = []

    def composed_then_withdraw(self, authoring, world_id):
        result = original(self, authoring, world_id)
        completed.append(result.receipt_sha256)
        dressed.withdraw()
        return result

    monkeypatch.setattr(TerrainWorkerComposer, "__call__", composed_then_withdraw)
    refused = dressed.create()
    assert completed, "the actual worker completed admission and composition before withdrawal"
    assert refused.status_code in (404, 409, 422), refused.text
    assert _authority_counts(dressed.api) == before


def test_coverage_wait_neither_publishes_nor_returns_cached_authority(dressed, monkeypatch):
    from exulanica.world.kinds.worker import KindWorkWaiting, TerrainDressingWorkerCompiler

    created = dressed.create()
    assert created.status_code == 201, created.text
    paths = dressed.paths(created.json())
    for path in paths:
        assert dressed.api.get(path).status_code == 200
    before = _authority_counts(dressed.api)

    def waiting(self, dressing, components):
        assert components, "real source reads still precede worker admission"
        raise KindWorkWaiting("overran", kept=True)

    monkeypatch.setattr(TerrainDressingWorkerCompiler, "__call__", waiting)
    for response in [dressed.create(), *(dressed.api.get(path) for path in paths)]:
        assert response.status_code == 503, response.text
        assert response.json()["code"] == "kind_work_overran"
        assert response.headers["retry-after"] == "2"
    assert _authority_counts(dressed.api) == before


@pytest.mark.parametrize("target", ["drawing", "proof"])
@pytest.mark.parametrize("change", ["withdrawn", "source_invalidated", "authored_edit"])
def test_final_delivery_barrier_rechecks_after_completed_work(dressed, monkeypatch, target, change):
    import exulanica.db.read_check as checks
    import exulanica.world.terrain_source as terrain_source
    from exulanica.world.object_repository import WorldObjectRepository

    from test_terrain_source_postgres import _object

    api = dressed.api
    created = dressed.create()
    assert created.status_code == 201, created.text
    entry = created.json()
    path = dressed.paths(entry)[target == "proof"]
    positive = api.get(path)
    assert positive.status_code == 200, positive.text
    original = checks.final_read_check
    changed = []

    def mutate():
        if change == "withdrawn":
            dressed.withdraw()
        elif change == "authored_edit":
            with api.database.session(api.repository.workspace_id) as connection:
                repo = WorldObjectRepository(
                    connection,
                    api.repository.workspace_id,
                    world_id=entry["world_id"],
                    store=api.store,
                )
                repo.add_object(
                    uuid.UUID(entry["authored_version_id"]),
                    _object(),
                    base_state_sha256=entry["authored_state_sha256"],
                    actor=api.actor,
                )
        else:
            admin = api.repository.connection
            tombstone = admin.execute(
                "insert into tombstone(workspace_id,scope,capture_id,requested_by,reason) "
                "values(%s,'capture',%s,%s,'source race fixture') returning tombstone_id",
                (api.repository.workspace_id, uuid.uuid4(), api.actor),
            ).fetchone()["tombstone_id"]
            admin.execute(
                "insert into world_structure_invalidation "
                "(workspace_id,world_id,snapshot_id,tombstone_id,reason) "
                "values(%s,%s,%s,%s,'source race fixture')",
                (
                    api.repository.workspace_id,
                    entry["world_id"],
                    uuid.UUID(entry["source_snapshot_id"]),
                    tombstone,
                ),
            )
            admin.commit()

    @contextmanager
    def changed_before_barrier(connection, *, not_idle, **kwargs):
        if not changed and not_idle in (
            "dressed drawing requires an idle read",
            "terrain proof requires an idle read",
        ):
            mutate()
            changed.append(change)
        with original(connection, not_idle=not_idle, **kwargs) as at:
            yield at

    # The route imports this helper locally; the proof module holds its imported reference.
    monkeypatch.setattr(checks, "final_read_check", changed_before_barrier)
    monkeypatch.setattr(terrain_source, "final_read_check", changed_before_barrier)
    refused = api.get(path)
    assert changed == [change], "the race occurred after all byte/worker/cache work"
    expected = 422 if target == "proof" and change == "withdrawn" else 409
    assert refused.status_code == expected, refused.text
