"""The delivery route: the first production path by which a derivative reaches a renderer.

ADR-0009 D10. Until this existed, "no route serves artifact bytes, and the only loader in the
workspace is a development preview, while the app's own comment claiming that production reads
point maps from an API describes an implementation that does not exist". Every test here is about
one of the three clauses that record puts on the route: **bytes in hand, a bearer in the header,
and the content hash verified against the descriptor that named it.**

The authorisation half is not repeated here. ``tests/test_api.py`` sweeps every route in the
application, generated from the router, and both geometry routes are in it: an anonymous caller
gets 401, an unknown token gets 401, a stranger never gets a 403, and a stranger probing a real
artifact id gets the same bytes-for-bytes response as one probing an invented one. What is here
is what that sweep cannot see: what the owner gets, and what happens to it when the owner deletes
something.

**Two tests in this file pin a gap rather than a guarantee**, and they say so in their own
docstrings. A test that asserts today's wrong answer is a liability unless it names what would
make it right, so each one names the record the gap is written down in and fails the day the gap
is closed, which is the moment somebody should be reading it.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.routes.geometry import POINT_MAP_MEDIA_TYPE
from exulanica.api.services import Services
from exulanica.evidence.blob import BlobId
from exulanica.graph.geometry import POINT_MAP_KIND
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.stages import stage
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient

from conftest import CountingVisionModel, iso, write_photo, write_point_map

_TOKEN = "geometry-owner-token-that-is-long-enough"
_STRANGER = "geometry-stranger-token-that-is-long-enough"

#: Distinct bytes per photograph, so a test that fetched the wrong artifact says so rather than
#: passing because two payloads happened to be equal.
_FIRST = b"point map for the first photograph"
_SECOND = b"point map for the second photograph"


class Delivered:
    """A workspace with two photographs, a point map for each, and an app in front of them."""

    def __init__(self, client, repository, store, database, first, second) -> None:
        self.client = client
        self.repository = repository
        self.store = store
        self.database = database
        self.first = first
        self.second = second

    def get(self, path: str, token: str = _TOKEN, headers: dict[str, str] | None = None):
        return self.client.get(
            path, headers={"Authorization": f"Bearer {token}", **(headers or {})}
        )

    def descriptors(self, token: str = _TOKEN) -> list[dict]:
        response = self.get("/geometry", token)
        assert response.status_code == 200, response.text
        return response.json()

    def sql(self, statement: str, *params):
        return self.repository.connection.execute(statement, params).fetchall()


@pytest.fixture
def delivered(tmp_path, photo_dir, repository, spine_schema, monkeypatch):
    """Two ingested photographs, each with a hand-written point map, behind a real application.

    The point maps are written by hand rather than by running the depth stage. The stage needs
    torch and a 1.3 GB checkpoint and is an optional extra that CI does not install, and what is
    under test here is the route rather than the model:
    :func:`conftest.write_point_map` computes the identity key with the real stage registry, so
    the rows it writes are the rows the stage would write.
    """
    _psycopg, scratch = spine_schema
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())

    written = []
    for name, when, payload in (
        ("second.jpg", iso(14), _SECOND),
        ("first.jpg", iso(9), _FIRST),
    ):
        # Ingested newest first, so a route that returned rows in insertion order rather than in
        # the documented presentation order would pass the ordering test by accident.
        outcome = pipeline.ingest_file(write_photo(photo_dir, name, when=when))
        assert outcome.error is None, outcome.error
        blob = BlobId.of_bytes((photo_dir / name).read_bytes())
        artifact_id, _ = write_point_map(repository, store, blob, payload)
        written.append((artifact_id, blob, payload))

    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                _TOKEN: {
                    "workspace_id": str(repository.workspace_id),
                    "actor": str(uuid.uuid4()),
                },
                _STRANGER: {"workspace_id": str(uuid.uuid4()), "actor": str(uuid.uuid4())},
            }
        ),
    )
    from tests_support_api import scratch_database

    database = scratch_database(scratch)
    app = create_app(
        Services(
            database=database,
            readonly_database=database,
            store=store,
            tokens=load_token_directory(),
            executor_shares_the_write_role=True,
            model_client=None,
        ),
        verify=False,
    )
    with TestClient(app) as client:
        # `written` is in ingest order, which is second then first. The names below are the
        # photographs' own order in time, which is what the route is documented to return.
        yield Delivered(
            client, repository, store, database, first=written[1], second=written[0]
        )


# -- what the route is for ------------------------------------------------------------------


def test_the_kind_the_route_serves_is_the_kind_the_depth_stage_writes():
    """The one string that spans two packages the layering forbids from importing each other.

    ``exulanica.graph`` and ``exulanica.ingest`` are siblings in the import contract, so the
    artifact kind is spelled twice. A rename that reached only the stage would
    leave the route serving an empty list for ever, with nothing failing
    anywhere, which is exactly the shape of defect this
    repository's register keeps recording: a test that passes without exercising its case.
    """
    assert stage("depth").output_kind == POINT_MAP_KIND


def test_the_descriptor_names_the_digest_the_bytes_actually_hash_to(delivered):
    """D10's third clause, end to end. This is the whole point of there being two routes."""
    descriptors = delivered.descriptors()
    assert len(descriptors) == 2
    for descriptor in descriptors:
        reference = descriptor["reference"]
        assert reference["authorization"] == "workspace-bearer"
        assert reference["href"] == f"/geometry/{descriptor['artifact_id']}"
        response = delivered.get(reference["href"])
        assert response.status_code == 200, response.text
        assert hashlib.sha256(response.content).hexdigest() == reference["content_sha256"]
        assert len(response.content) == reference["byte_size"]


def test_the_bytes_arrive_as_a_container_and_never_as_an_image(delivered):
    """A point map is not evidence and is not a picture. Nothing may sniff it into one."""
    href = delivered.descriptors()[0]["reference"]["href"]
    response = delivered.get(href)
    assert response.headers["content-type"] == POINT_MAP_MEDIA_TYPE
    assert response.headers["x-content-type-options"] == "nosniff"
    # Somebody's photograph, one derivation removed, and the user holds no second copy of it. A
    # cache holding it is a copy of the corpus the deletion path cannot reach, and the browser's
    # own on-disk cache is as much of one as a shared proxy. `private` alone would leave a
    # deleted region's geometry redrawable from disk for an hour after the tombstone committed.
    assert response.headers["cache-control"] == "no-store"


def test_the_etag_is_the_content_hash_and_is_not_the_check(delivered):
    """It is a strong validator, because a content-addressed store has nothing weaker to offer.

    A client that verified the body against this header would be checking the response against
    itself. The descriptor is what named the digest before the transfer began, and
    ``web/packages/app/src/geometry-api.ts`` verifies against that.
    """
    descriptor = delivered.descriptors()[0]
    response = delivered.get(descriptor["reference"]["href"])
    assert response.headers["etag"] == f'"{descriptor["reference"]["content_sha256"]}"'


def test_a_range_request_gets_the_whole_file_rather_than_a_fragment(delivered):
    """The one byte route in this API that offers no ranges, and it says so in a header.

    The evidence route offers them, because a citation deep link should not have to transfer a
    whole photograph to show the top of it. Here a fragment is exactly the thing a client cannot
    check against a digest of the whole, so the response is the whole file and ``Accept-Ranges``
    says ``none`` rather than leaving a client to infer it from a missing header.
    """
    descriptor = delivered.descriptors()[0]
    response = delivered.get(descriptor["reference"]["href"], headers={"Range": "bytes=0-3"})
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "none"
    assert len(response.content) == descriptor["reference"]["byte_size"]


def test_the_list_is_keyed_by_capture_and_ships_no_island(delivered):
    """ADR-0005 leaves what an island is to the client, and this route does not settle it.

    ``exulanica.graph``'s own docstring: "A server that shipped an island id would be settling that
    question by accident." The client maps captures to islands through the same function its
    occurrences went through, so geometry lands in the regions the anchors did.
    """
    descriptors = delivered.descriptors()
    live = {str(row["capture_id"]) for row in delivered.sql("select capture_id from capture")}
    assert {row["capture_id"] for row in descriptors} == live
    for row in descriptors:
        assert not any("island" in key or "region" in key for key in row)
        # And no rung: the recorded claim already reaches the client on the graph payload, and a
        # second copy on the wire is the divergence ADR-0009 D11 complains about.
        assert "rung" not in row


def test_the_order_is_the_first_photograph_of_the_visit_first(delivered):
    """A region holds several point maps and the renderer takes one, so something has to choose.

    The choice is made once, here, so that two clients cannot make it differently. The order is
    ``capture.started_at`` and then ``capture_id``; the fixture ingests the later photograph
    first so that insertion order and the documented order disagree.
    """
    descriptors = delivered.descriptors()
    assert [row["artifact_id"] for row in descriptors] == [
        str(delivered.first[0]),
        str(delivered.second[0]),
    ]


def test_a_descriptor_says_which_container_the_bytes_were_written_under(delivered):
    """Read from the stage definition carrying the row's own params digest, not from the registry.

    ADR-0010 gives ``.opm`` a version 2 whose validators "refuse version 1 by name". A client
    that can read one container and not the other has to know before it spends three megabytes,
    and the answer has to be what this artifact was written under rather than what the stage
    would write today.
    """
    for descriptor in delivered.descriptors():
        assert descriptor["container"] == stage("depth").params["container"]


# -- what happens when the user deletes something --------------------------------------------


def test_a_deleted_capture_makes_its_geometry_gone_rather_than_missing(delivered):
    """410, not 404, and the distinction is one the user is entitled to.

    It also happens **before the purger has run**: a tombstone is authoritative from the moment
    it commits and the bytes catch up later, so a route that consulted ``artifact.purged_at``
    alone would keep serving a deleted photograph's geometry for as long as the queue took.
    """
    capture = delivered.sql(
        "select capture_id from capture where blob_sha256 = %s", delivered.first[1].digest
    )[0]["capture_id"]
    href = f"/geometry/{delivered.first[0]}"
    assert delivered.get(href).status_code == 200

    delivered.repository.insert_tombstone(
        scope="capture", requested_by=uuid.uuid4(), capture_id=capture, reason="the user asked"
    )
    assert delivered.sql("select purged_at from artifact where content_sha256 is not null")
    gone = delivered.get(href)
    assert gone.status_code == 410, gone.text
    assert gone.json()["code"] == "tombstoned"
    assert [row["artifact_id"] for row in delivered.descriptors()] == [str(delivered.second[0])]


def test_an_interval_redaction_over_the_whole_frame_withdraws_the_geometry_too(delivered):
    """The capture is still live, and the geometry is still gone.

    This is why the read asks ``tombstone_blocks_capture`` rather than testing ``deleted_at``.
    An interval tombstone soft-marks nothing: migration 0015's trigger returns early for any
    scope but ``capture`` and ``workspace``. A route that keyed on the capture being deleted
    would serve the redacted frame's geometry back, which is the whole of what a still image's
    interval covers.
    """
    capture = delivered.sql(
        "select capture_id from capture where blob_sha256 = %s", delivered.first[1].digest
    )[0]["capture_id"]
    tombstone = delivered.repository.insert_tombstone(
        scope="interval",
        requested_by=uuid.uuid4(),
        capture_id=capture,
        track_key="img",
        interval_ns=[(0, 1)],
        reason="redacted",
    )
    live = delivered.sql(
        "select deleted_at from capture where capture_id = %s", capture
    )[0]["deleted_at"]
    assert live is None, "an interval tombstone does not soft-mark the capture, and should not"
    assert delivered.get(f"/geometry/{delivered.first[0]}").status_code == 410
    assert [row["artifact_id"] for row in delivered.descriptors()] == [str(delivered.second[0])]

    # The other half of the same paragraph in domain-and-evidence-model.md 6.4, and it is the
    # half that is a gap: nothing is enqueued, nothing is soft-marked, and the artifact the
    # cascade table says would be marked `needs_repair` is not marked. The bytes are withheld
    # and they are still on the disk.
    assert not delivered.sql(
        "select purge_id from purge_job where tombstone_id = %s", tombstone
    ), "an interval tombstone now enqueues work; rewrite the CORRECTED note in section 6.4"
    assert delivered.sql(
        "select needs_repair from artifact where artifact_id = %s", delivered.first[0]
    )[0]["needs_repair"] is False


def test_a_purged_artifact_is_gone_rather_than_absent(delivered):
    """The other half of the same fact, from the far side of the queue."""
    delivered.repository.connection.execute(
        "update artifact set purged_at = now(), storage_key = null where artifact_id = %s",
        (delivered.first[0],),
    )
    assert delivered.get(f"/geometry/{delivered.first[0]}").status_code == 410


def test_an_artifact_whose_object_vanished_is_reported_rather_than_served(delivered):
    """A row that survived its bytes is a third state, and it is not "no geometry here".

    The list says ``bytes_missing`` and offers no reference, because a reference to bytes that
    are not there is an invitation to fetch them. The byte route answers **424** with the same
    ``unavailable_asset`` code ``/world/source-media`` uses for the same fact, and does **not**
    borrow the application's ``BlobNotFoundError`` handler, whose message is "no such evidence":
    a point map is not evidence, and saying it is in a message would undo, in prose, the
    separation invariant 2 keeps in the schema. 424 rather than 404 is safe because only a caller
    whose own workspace holds the row can reach it; a stranger's read found nothing and stopped.
    """
    path = delivered.store.root / delivered.store.key_for(
        BlobId.from_hex(delivered.descriptors()[0]["reference"]["content_sha256"])
    )
    os.chmod(path, 0o644)
    path.unlink()

    descriptor = next(
        row for row in delivered.descriptors() if row["artifact_id"] == str(delivered.first[0])
    )
    assert descriptor["state"] == "bytes_missing"
    assert descriptor["reference"] is None
    assert descriptor["reason"] is not None

    response = delivered.get(f"/geometry/{delivered.first[0]}")
    assert response.status_code == 424
    assert response.json()["code"] == "unavailable_asset"
    assert "evidence" not in response.text


def test_bytes_that_no_longer_hash_to_their_key_are_refused_loudly(delivered):
    """500, never a 404 and never the bytes. The store re-hashes and this route lets it.

    ``app.py`` on ``IntegrityError``: "Stored bytes that do not hash to the key they are stored
    under means a citation has stopped verifying, and serving anything at all here would hide
    it." A derivative is not a citation, and the reasoning survives the difference: the digest in
    the descriptor is what a client checks against, so bytes that stopped matching their key are
    bytes no client could accept and no server should hand over.
    """
    path = delivered.store.root / delivered.store.key_for(
        BlobId.from_hex(delivered.descriptors()[0]["reference"]["content_sha256"])
    )
    os.chmod(path, 0o644)
    path.write_bytes(b"substituted, same length as nothing in particular")

    response = delivered.get(f"/geometry/{delivered.first[0]}")
    assert response.status_code == 500
    assert response.json()["code"] == "integrity_failure"


# -- the gaps this work found, pinned so that closing one is visible -------------------------


def test_a_person_scoped_withdrawal_reaches_every_recorded_derivative(delivered):
    """The person vanishes, their geometry and vector are purged, and the source remains."""
    from exulanica.db.migrate import provision_workspace
    from exulanica.deletion.worker import PurgeWorker
    from exulanica.epistemics.assertions import AssertionWriter
    from exulanica.identity import IdentityRepository, name_occurrence

    connection = delivered.repository.connection
    workspace = delivered.repository.workspace_id
    capture = delivered.sql(
        "select capture_id from capture where workspace_id=%s and blob_sha256=%s",
        workspace,
        delivered.first[1].digest,
    )[0]["capture_id"]
    span = delivered.sql(
        "select span_id from evidence_span where workspace_id=%s and blob_sha256=%s "
        "order by span_id limit 1",
        workspace,
        delivered.first[1].digest,
    )[0]["span_id"]
    run_id = delivered.sql(
        "select run_id from pipeline_run where workspace_id=%s order by started_at limit 1",
        workspace,
    )[0]["run_id"]
    occurrence = connection.execute(
        "insert into occurrence (workspace_id,capture_id,class,primary_span_id,span_ids,presence,"
        "produced_by_run,detector_version,identity_key,emit_key) values "
        "(%s,%s,'person',%s,array[%s]::uuid[],'{[0,1)}'::int8multirange,%s,'test',%s,%s) "
        "returning occurrence_id",
        (workspace, capture, span, span, run_id, bytes([71]) * 32, f"person:{uuid.uuid4()}"),
    ).fetchone()["occurrence_id"]
    named = name_occurrence(
        IdentityRepository(connection, workspace),
        AssertionWriter(connection, workspace),
        occurrence_id=occurrence,
        display_name="Withdrawn Person",
        actor=uuid.uuid4(),
    )
    derived = uuid.uuid4()
    connection.execute(
        "insert into derived_artifact (derived_id,workspace_id,kind,depends_on,dep_index,payload) "
        "values (%s,%s,'entity_exemplars','[]'::jsonb,%s::text[],'{}'::jsonb)",
        (derived, workspace, [f"entity:{named.entity_id}"]),
    )
    provision_workspace(connection, workspace)
    embedding = connection.execute(
        "insert into embedding (workspace_id,family,ref_type,ref_id,model_ref,pipeline_version,"
        "dims,v) values (%s,'face','occurrence',%s,'test',1,4096,%s) returning embedding_id",
        (workspace, occurrence, "[" + ",".join(["0.5"] * 4096) + "]"),
    ).fetchone()["embedding_id"]

    before = delivered.get("/graph").json()
    assert any(row["entity_id"].endswith(str(named.entity_id)) for row in before["entities"])
    assert delivered.get(f"/geometry/{delivered.first[0]}").status_code == 200

    tombstone = delivered.repository.insert_tombstone(
        scope="entity",
        entity_id=named.entity_id,
        requested_by=uuid.uuid4(),
        reason="the person withdrew",
    )

    after = delivered.get("/graph").json()
    assert not any(row["entity_id"].endswith(str(named.entity_id)) for row in after["entities"])
    assert not any(
        row["occurrence_id"].endswith(str(occurrence)) for row in after["occurrences"]
    )
    assert delivered.get(f"/geometry/{delivered.first[0]}").status_code == 410
    assert delivered.get(f"/geometry/{delivered.second[0]}").status_code == 200
    assert delivered.sql(
        "select stale from derived_artifact where derived_id=%s", derived
    )[0]["stale"]
    assert delivered.sql(
        "select status from assertion where assertion_id=%s", named.assertion_id
    )[0]["status"] == "retracted"

    jobs = delivered.sql(
        "select target_kind,target_ref from purge_job where tombstone_id=%s order by target_kind",
        tombstone,
    )
    assert {row["target_kind"] for row in jobs} == {"artifact", "embedding"}
    assert any(row["target_ref"] == str(embedding) for row in jobs)
    receipt = delivered.sql(
        "select record,canonical_bytes,record_digest from person_withdrawal_receipt "
        "where tombstone_id=%s",
        tombstone,
    )[0]
    assert hashlib.sha256(bytes(receipt["canonical_bytes"])).digest() == bytes(
        receipt["record_digest"]
    )
    assert receipt["record"]["source_capture_policy"] == "retained"

    outcome = PurgeWorker(
        delivered.database,
        delivered.store,
        frozenset({workspace}),
        require_cross_workspace_view=False,
    ).drain()
    assert outcome.failed == 0
    assert outcome.skipped == 0
    assert not delivered.store.exists(BlobId.of_bytes(_FIRST))
    assert delivered.sql(
        "select purged_at from artifact where workspace_id=%s and artifact_id=%s",
        workspace,
        delivered.first[0],
    )[0]["purged_at"] is not None
    assert not delivered.sql(
        "select embedding_id from embedding where workspace_id=%s and embedding_id=%s",
        workspace,
        embedding,
    )
    assert delivered.sql(
        "select deleted_at from capture where workspace_id=%s and capture_id=%s",
        workspace,
        capture,
    )[0]["deleted_at"] is None
    assert delivered.sql(
        "select purged_at from blob where blob_sha256=%s", delivered.first[1].digest
    )[0]["purged_at"] is None
    assert delivered.store.exists(delivered.first[1])


def test_a_pose_job_directory_is_not_an_artifact_and_no_tombstone_reaches_it(tmp_path):
    """PINS A GAP. ADR-0009 D12, and one detail of it that the record does not yet carry.

    A COLMAP job writes ``database.db``, holding SIFT descriptors of every image it was given,
    into a directory keyed by the manifest digest and known to nothing else in the system.
    Nothing registers it as an artifact, so no tombstone reaches it, and D12 says so.

    What D12 also says is "the job directory is deleted when the receipt is accepted", and that
    is not implementable as written: ``receipt.json`` and ``manifest.json`` live **inside** the
    job directory and are what makes a completed job return without invoking COLMAP again.
    Deleting the directory would destroy the reuse path along with the descriptors. The
    separation this asserts is the one a fix has to keep: the working database is not the
    receipt, and only one of the two is a derivative of a photograph.
    """
    import inspect

    from exulanica.reconstruction import pose

    source = inspect.getsource(pose)
    assert 'job_dir / "database.db"' in source, (
        "the working SIFT database has moved. Whatever holds it now is still a derivative of "
        "photographs outside the deletion cascade until something registers it as an artifact."
    )
    assert 'job_dir / "receipt.json"' in source, (
        "the receipt no longer lives in the job directory. D12's 'the job directory is deleted "
        "when the receipt is accepted' may now be implementable as written; check whether it is, "
        "and update ADR-0009 D12 with what was done."
    )
