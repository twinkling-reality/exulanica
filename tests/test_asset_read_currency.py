"""Authenticated generated media, actual mask producer, and persisted read lineage."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.consent.regions import Silhouette
from exulanica.db.roles import provision_runtime_role
from exulanica.evidence.blob import BlobId
from exulanica.graph.asset_read_policy import final_check, image_source
from fastapi.testclient import TestClient

from conftest import scratch_role_database
from test_screening_currency import ACTOR, Case
from tests_support_api import scratch_database

TOKEN = "asset-read-generated-owner-token"
FOREIGN = "asset-read-generated-foreign-token"


class Delivery:
    def __init__(self, case, client, readonly):
        self.case, self.client, self.readonly = case, client, readonly
        row = case.repo.connection.execute(
            "select span_id from evidence_span where workspace_id=%s and blob_sha256=%s",
            (case.repo.workspace_id, hashlib.sha256(case.data).digest()),
        ).fetchone()
        self.path = f"/evidence/{row['span_id']}"
        self.events = []
        self.bodies = []

    def get(self, path=None, *, foreign=False, **headers):
        response = self.client.get(
            path or self.path + "/masked",
            headers={
                "Authorization": f"Bearer {FOREIGN if foreign else TOKEN}",
                **headers,
            },
        )
        self.bodies.append(response.content)
        self.events.append(
            {
                "path": path or self.path + "/masked",
                "status": response.status_code,
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "byte_size": len(response.content),
                "foreign": foreign,
                "range": headers.get("Range"),
            }
        )
        return response

    def point(self, screening, mask=None):
        data = b"GENERATED GEOMETRY DELIVERY FIXTURE: exact source lineage, no depth inference"
        put = self.case.store.put_bytes(data)
        artifact = uuid.uuid4()
        self.case.repo.insert_artifact(
            artifact_id=artifact,
            kind="point_map",
            source_blob=BlobId.of_bytes(self.case.data),
            stage_key="depth",
            stage_version=99,
            params_digest=b"p" * 32,
            input_digest=b"i" * 32,
            idempotency_key=str(uuid.uuid4()),
            content_sha256=put.blob_id.digest,
            storage_key=self.case.store.key_for(put.blob_id),
            byte_size=len(data),
            produced_by_event=None,
            privacy_screening_id=screening.screening_id,
            read_source_sha256=mask.content_sha256 if mask else None,
        )
        return f"/geometry/{artifact}", data


@pytest.fixture
def delivery(repository, tmp_path, spine_schema, monkeypatch):
    case = Case(repository, tmp_path)
    _, schema = spine_schema
    provision_runtime_role(repository.connection, role="exulanica_ro", read_only=True)
    readonly = scratch_role_database(schema, "exulanica_ro")
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {"workspace_id": str(repository.workspace_id), "actor": str(ACTOR)},
                FOREIGN: {"workspace_id": str(uuid.uuid4()), "actor": str(ACTOR)},
            }
        ),
    )
    app = create_app(
        Services(
            database=scratch_database(schema),
            readonly_database=readonly,
            store=case.store,
            tokens=load_token_directory(),
            executor_shares_the_write_role=False,
            model_client=None,
        ),
        verify=False,
    )
    with readonly.session(repository.workspace_id) as conn:
        row = conn.execute(
            "select current_user as role, r.rolsuper, r.rolbypassrls, "
            "has_table_privilege(current_user,'capture','INSERT') as writes "
            "from pg_roles r where rolname=current_user"
        ).fetchone()
        assert row == {
            "role": "exulanica_ro",
            "rolsuper": False,
            "rolbypassrls": False,
            "writes": False,
        }
        assert not conn.execute(
            "select exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace "
            "where n.nspname=current_schema() and c.relowner=(select oid from pg_roles "
            "where rolname=current_user)) as owns"
        ).fetchone()["owns"]
    with TestClient(app) as client:
        d = Delivery(case, client, readonly)
        yield d
    if target := os.environ.get("EXULANICA_ASSET_EVIDENCE_DIR"):
        directory = Path(target)
        directory.mkdir(parents=True, exist_ok=True)
        label = os.environ["PYTEST_CURRENT_TEST"].split("::")[-1].split(" ")[0]
        (directory / f"{label}.json").write_text(json.dumps(d.events, sort_keys=True))
        (directory / f"{label}-generated.jpg").write_bytes(case.data)
        for index, body in enumerate(d.bodies):
            (directory / f"{label}-response-{index:03d}.bin").write_bytes(body)
        rows = case.repo.connection.execute(
            "select artifact_id,kind,stage_key,stage_version,byte_size,privacy_screening_id,"
            "encode(source_blob_sha256,'hex') as source_sha256,"
            "encode(read_source_sha256,'hex') as read_source_sha256,"
            "encode(input_digest,'hex') as input_digest,"
            "encode(content_sha256,'hex') as content_sha256 "
            "from artifact where workspace_id=%s order by artifact_id",
            (case.repo.workspace_id,),
        ).fetchall()
        (directory / f"{label}-lineage.json").write_text(
            json.dumps(rows, sort_keys=True, default=str)
        )
        for blob in case.store.iter_blob_ids():
            (directory / (blob.hex + ".blob")).write_bytes(case.store.get(blob))


def test_changed_outline_rebuild_does_not_revive_geometry(delivery):
    d = delivery
    c = d.case
    c.edit()
    c.build()
    mask = c.mask()
    screening = c.screen()
    geometry, data = d.point(screening, mask)
    assert d.get().content == c.store.get(BlobId(mask.content_sha256))
    assert d.get(geometry).content == data
    assert d.get("/geometry").json()
    c.edit("confirm", outline=Silhouette(((0, 0), (800000, 0), (800000, 500000), (0, 500000))))
    assert d.get().status_code == 409
    assert d.get(geometry).status_code == 404
    assert d.get("/geometry").json() == []
    c.build()
    assert d.get().content == c.store.get(BlobId(c.mask().content_sha256))
    assert d.get(geometry).status_code == 404
    fresh = c.screen()
    current, content = d.point(fresh, c.mask())
    assert d.get(current).content == content
    assert d.get(geometry).status_code == 404


def test_original_saved_urls_refuse_required_mask_and_ranges(delivery):
    d = delivery
    c = d.case
    assert d.get(d.path).content == c.data
    assert d.get(Range="bytes=2-9").content == c.data[2:10]
    c.edit()
    for path in (d.path, d.path + "/region", d.path + "/masked"):
        assert d.get(path, Range="bytes=2-9").status_code == 409
        assert d.get(path, foreign=True).status_code == 404
    c.build()
    masked = c.store.get(BlobId(c.mask().content_sha256))
    response = d.get(Range="bytes=2-9")
    assert response.status_code == 206 and response.content == masked[2:10]
    assert d.get(d.path).status_code == 409
    assert d.get(d.path + "/region").status_code == 409
    assert d.get(Range="bytes=999999-").status_code == 416


def test_expiry_without_write_withholds_original_geometry(delivery):
    d = delivery
    c = d.case
    c.edit(subject=c.subject)
    deadline = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=2)
    c.consent(valid_until=deadline)
    path, _ = d.point(c.screen())
    assert d.get(path).status_code == 200
    assert d.get(d.path).status_code == 200
    time.sleep(max(0, (deadline - dt.datetime.now(dt.UTC)).total_seconds()) + 0.05)
    assert d.get(d.path).status_code == 409
    assert d.get(path).status_code == 404
    assert d.get("/geometry").json() == []
    c.build()
    assert d.get().status_code == 200
    assert d.get(path).status_code == 404


def test_withdrawal_deleted_and_missing_mask(delivery):
    d = delivery
    c = d.case
    c.edit(subject=c.subject)
    c.build()
    mask = c.mask()
    (c.store.root / c.store.key_for(BlobId(mask.content_sha256))).unlink()
    assert d.get().status_code in (404, 424)
    c.consent(decision="withdrawn")
    assert d.get().status_code == 409
    assert d.get(d.path).status_code == 409
    c.repo.insert_tombstone(scope="capture", capture_id=c.capture, requested_by=ACTOR)
    assert d.get().status_code == 410


def test_unchanged_no_person_and_missing_legacy_lineage(delivery):
    d = delivery
    c = d.case
    screen = c.screen()
    path, data = d.point(screen)
    assert d.get().content == c.data
    assert d.get(path).content == data
    with d.readonly.session(c.repo.workspace_id) as conn, conn.transaction():
        conn.execute("set transaction isolation level repeatable read read only")
        assert (
            image_source(
                conn,
                c.repo.workspace_id,
                hashlib.sha256(c.data).digest(),
                dt.datetime.now(dt.UTC),
            )
            == hashlib.sha256(c.data).digest()
        )
    # A legacy receipt that never recorded inputs cannot authorize delivery. The existing
    # trigger would refuse rewriting a produced point map, so test the read predicate directly
    # against an unknown historical identity rather than forge successful production.
    assert d.get("/geometry/" + str(uuid.uuid4())).status_code == 404
    assert d.get(path, foreign=True).status_code == 404


def test_final_check_sees_edit_during_buffer_read(delivery, monkeypatch):
    d = delivery
    c = d.case
    original = c.store.get
    armed = True

    def changed(blob):
        nonlocal armed
        result = original(blob)
        if armed and blob == BlobId.of_bytes(c.data):
            armed = False
            c.edit()
        return result

    monkeypatch.setattr(c.store, "get", changed)
    assert d.get(d.path).status_code == 409


def test_reader_waits_for_prior_writer_and_later_writer_retries(delivery, ingest_spine):
    d = delivery
    c = d.case
    _, open_another = ingest_spine
    writer = open_another()
    started = threading.Event()

    def read():
        started.set()
        return d.get().status_code

    with ThreadPoolExecutor(max_workers=1) as pool:
        with writer.connection.transaction():
            writer.connection.execute(
                "update capture set started_at=started_at where capture_id=%s", (c.capture,)
            )
            from exulanica.ingest.person_review import record_region_edits

            record_region_edits(
                writer,
                capture_id=c.capture,
                actor=ACTOR,
                edits=[
                    {
                        "action": "add",
                        "region_key": "dd" * 32,
                        "silhouette": {
                            "kind": "polygon",
                            "points": [[0, 0], [300000, 0], [300000, 300000]],
                        },
                    }
                ],
            )
            future = pool.submit(read)
            assert started.wait(2)
            time.sleep(0.1)
            assert not future.done()
        assert future.result(timeout=5) == 409
    c.build()
    with (
        d.readonly.session(c.repo.workspace_id) as conn,
        final_check(conn),
        pytest.raises(psycopg.errors.SerializationFailure),
    ):
        writer.connection.execute(
            "update capture set started_at=started_at where capture_id=%s", (c.capture,)
        )
    assert d.get().status_code == 200


def test_source_metadata_review_and_mask_bytes_agree(delivery):
    from exulanica.world import TopologyContract, TopologySourceSlot, WorldStyleRepository

    d = delivery
    c = d.case
    span = uuid.UUID(d.path.rsplit("/", 1)[1])
    source = uuid.uuid4()
    WorldStyleRepository(c.repo.connection, c.repo.workspace_id).register_topology(
        TopologyContract(
            "currency-source",
            ("region-a",),
            (TopologySourceSlot(source, "generated", "region-a", span, None),),
        )
    )
    [row] = d.get("/world/source-media").json()
    assert row["evidence_path"] == d.path + "/masked"
    c.edit()
    c.build()
    [row] = d.get("/world/source-media").json()
    assert row["state"] == "available" and d.get(row["evidence_path"]).status_code == 200
    c.edit("confirm", outline=Silhouette(((0, 0), (900000, 0), (900000, 500000), (0, 500000))))
    [row] = d.get("/world/source-media").json()
    assert row["state"] == "unavailable_asset" and row["asset_reference"] is None
    assert row["capture_ids"] == [str(c.capture)]
    assert d.get().status_code == 409
    assert d.get("/person-regions/" + str(c.capture)).status_code == 200
    c.build()
    [row] = d.get("/world/source-media").json()
    assert row["state"] == "available"
    (c.store.root / c.store.key_for(BlobId(c.mask().content_sha256))).unlink()
    [row] = d.get("/world/source-media").json()
    assert row["state"] == "unavailable_asset" and row["capture_ids"] == [str(c.capture)]
    assert d.get("/person-regions/" + str(c.capture)).status_code == 200


def test_by_uri_rechecks_original_permission(delivery):
    from exulanica.store.resolve import address_from_span_row

    d = delivery
    c = d.case
    row = c.repo.connection.execute(
        "select * from evidence_span where span_id=%s", (uuid.UUID(d.path.rsplit("/", 1)[1]),)
    ).fetchone()
    address = address_from_span_row(row)
    from urllib.parse import quote

    path = "/evidence?uri=" + quote(address.to_uri(), safe="")
    assert d.get(path).content == c.data
    c.edit()
    c.build()
    assert d.get(path, Range="bytes=0-4").status_code == 409
    assert d.get(path, foreign=True).status_code == 404


def test_legacy_point_lineage_is_withheld(delivery):
    d = delivery
    c = d.case
    path, _ = d.point(c.screen())
    # Simulate a pre-admission legacy row in the disposable schema. This is deliberately
    # not a production writer: current write triggers correctly reject missing lineage.
    with c.repo.connection.transaction():
        c.repo.connection.execute("set local session_replication_role=replica")
        c.repo.connection.execute(
            "update artifact set privacy_screening_id=null where artifact_id=%s",
            (uuid.UUID(path.rsplit("/", 1)[1]),),
        )
    assert d.get(path).status_code == 404
    assert d.get("/geometry").json() == []


def test_restrictive_duplicate_identity_cannot_be_overridden(delivery):
    d = delivery
    c = d.case
    with pytest.raises(psycopg.errors.UniqueViolation):
        c.repo.connection.execute(
            "insert into capture(workspace_id,blob_sha256) values (%s,%s)",
            (c.repo.workspace_id, hashlib.sha256(c.data).digest()),
        )
    assert d.get().status_code == 200
    c.edit()
    c.build()
    assert d.get(d.path).status_code == 409
    assert d.get().status_code == 200


@pytest.mark.parametrize(
    "table,statement",
    [
        ("stage_registry", "update stage_registry set params_schema=params_schema"),
        ("entity_link", "delete from entity_link"),
        ("assertion", "update assertion set status=status"),
    ],
)
def test_dependency_barrier_inventory_and_global_stage_lock(delivery, table, statement):
    d = delivery
    c = d.case
    rows = c.repo.connection.execute(
        "select tgname from pg_trigger where tgrelid=%s::regclass "
        "and tgname='aaa_asset_read_mutation'",
        (table,),
    ).fetchall()
    assert rows
    if table == "stage_registry":
        with (
            d.readonly.session(c.repo.workspace_id) as conn,
            final_check(conn),
            pytest.raises(psycopg.errors.SerializationFailure),
        ):
            c.repo.connection.execute(statement)


def test_trained_and_embedded_geometry_require_recorded_current_inputs(delivery, tmp_path):
    from exulanica.store.local import LocalContentAddressedStore

    from test_training_inputs import scene_sample

    d = delivery
    c = d.case
    root = tmp_path / "trained"
    root.mkdir()
    _, materials = scene_sample(c.repo, root)
    stored = LocalContentAddressedStore(root / "store")
    for blob in stored.iter_blob_ids():
        c.store.put_bytes(stored.get(blob))
    scene = materials[0]["provenance"]["scene_id"]
    trained = next(
        asset for m in materials for asset in m["assets"] if asset["role"] == "trained_geometry"
    )
    path = "/scene-geometry/" + trained["artifact_id"]
    response = d.get(path)
    assert response.status_code == 200, response.text
    assert hashlib.sha256(response.content).hexdigest() == trained["sha256"]
    for route in ("/world-read/scenes/" + scene, "/world-read/scenes/" + scene + "/observations"):
        assert d.get(route).status_code == 200
    # Add a region to one real recorded source. The scene's persisted original frames
    # cannot become masked frames merely because a current mask is subsequently built.
    from exulanica.ingest.person_review import record_region_edits

    capture = uuid.UUID(materials[0]["capture_id"])
    record_region_edits(
        c.repo,
        capture_id=capture,
        actor=ACTOR,
        edits=[
            {
                "action": "add",
                "region_key": "cc" * 32,
                "silhouette": {
                    "kind": "polygon",
                    "points": [[0, 0], [400000, 0], [400000, 400000], [0, 400000]],
                },
            }
        ],
    )
    assert d.get(path).status_code == 404
    assert d.get("/world-read/scenes/" + scene).status_code == 404
    assert d.get("/world-read/scenes/" + scene + "/observations").status_code == 404
    graph = d.get("/graph").json()
    selected = next(s for s in graph["reconstruction_scenes"] if s["scene_id"] == scene)
    assert selected["trained_geometry"] is None
    assert all(
        m["placement"] is None and m["recovered_camera"] is None for m in selected["members"]
    )
    assert d.get("/person-regions/" + str(capture)).status_code == 200

    # The real mask stage can now rebuild the photograph, but the old trained artifact
    # and the embedded observations still carry their original input lineage.
    from exulanica.ingest.privacy import (
        authorize_personal_capture,
        record_person_detection_screening,
    )

    authorization = authorize_personal_capture(
        c.repo,
        capture_id=capture,
        actor=ACTOR,
        account_authority_basis="Generated fixture only",
        authorization_scope={"purpose": "asset test"},
        purpose="Generated asset read test",
    )
    detection = record_person_detection_screening(
        c.repo,
        authorization_id=authorization.authorization_id,
        authorized_by=ACTOR,
        purpose="Generated asset read test",
    )
    result = c.pipeline.ingest_derivatives(capture, privacy_screening_id=detection.screening_id)
    assert result.error is None, result.error
    assert d.get(path).status_code == 404
    assert d.get("/world-read/scenes/" + scene + "/observations").status_code == 404


def test_expiry_is_evaluated_after_a_waiting_read_acquires_the_lock(delivery, ingest_spine):
    d = delivery
    c = d.case
    c.edit(subject=c.subject)
    boundary = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=1)
    c.consent(valid_until=boundary)
    _, open_another = ingest_spine
    writer = open_another()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with writer.connection.transaction():
            writer.connection.execute(
                "update capture set started_at=started_at where capture_id=%s", (c.capture,)
            )
            future = pool.submit(d.get, d.path)
            time.sleep(max(0, (boundary - dt.datetime.now(dt.UTC)).total_seconds()) + 0.05)
            assert not future.done()
        assert future.result(timeout=5).status_code == 409


def test_read_barrier_does_not_wait_for_purge_object_lock(delivery, ingest_spine):
    d = delivery
    c = d.case
    _, open_another = ingest_spine
    purger = open_another()
    with purger.connection.transaction():
        purger.connection.execute("select purge_lock_object(%s)", (BlobId.of_bytes(c.data).hex,))
        # The object lock and nested savepoint precede the reader barrier. Mutation must
        # refuse rather than waiting while it retains the object lock.
        with (
            d.readonly.session(c.repo.workspace_id) as conn,
            final_check(conn),
            pytest.raises(psycopg.errors.SerializationFailure),
            purger.connection.transaction(),
        ):
            purger.connection.execute(
                "update blob set byte_size=byte_size where blob_sha256=%s",
                (hashlib.sha256(c.data).digest(),),
            )
    assert d.get().content == c.data


def test_tombstone_cascade_commits_before_waiting_delivery(delivery, ingest_spine):
    d = delivery
    c = d.case
    _, open_another = ingest_spine
    writer = open_another()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with writer.connection.transaction():
            writer.connection.execute(
                "update capture set started_at=started_at where capture_id=%s", (c.capture,)
            )
            future = pool.submit(d.get, d.path)
            deadline = time.monotonic() + 3
            waiting = False
            while time.monotonic() < deadline:
                waiting = c.repo.connection.execute(
                    "select exists(select 1 from pg_locks where locktype='advisory' "
                    "and classid=0 and objid=119622341 and not granted) as waiting"
                ).fetchone()["waiting"]
                if waiting:
                    break
                time.sleep(0.01)
            assert waiting, "the reader must reach the actual barrier before cascade"
            writer.insert_tombstone(scope="capture", capture_id=c.capture, requested_by=ACTOR)
        assert future.result(timeout=5).status_code == 410
