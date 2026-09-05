"""Reference source composition preserves existing evidence and stable world identities."""

import uuid

import pytest
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.orchestration.reference_world import compose_reference_sources
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import WorldStyleRepository

from conftest import write_photo

pytestmark = pytest.mark.postgres


def test_reference_source_topology_is_stable_and_uses_only_existing_live_evidence(
    repository, tmp_path, photo_dir
):
    store = LocalContentAddressedStore(tmp_path / "blobs")
    result = PhotoIngestPipeline(repository, store, vision=None).ingest_file(
        write_photo(photo_dir, "source.jpg")
    )
    assert result.error is None
    capture = repository.connection.execute(
        "select capture_id,blob_sha256 from capture where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()
    selected = [(capture["capture_id"], bytes(capture["blob_sha256"]).hex(), "source.jpg")]
    before = repository.connection.execute("select count(*) as n from evidence_span").fetchone()[
        "n"
    ]
    options = {
        "region_id": "existing-region",
        "captures": selected,
        "source_manifest_sha256": "ab" * 32,
    }
    first = compose_reference_sources(repository, **options)
    assert compose_reference_sources(repository, **options) == first
    assert (
        repository.connection.execute("select count(*) as n from evidence_span").fetchone()["n"]
        == before
    )
    [source] = WorldStyleRepository(repository.connection, repository.workspace_id).source_media(
        store
    )
    assert source.capture_ids == (capture["capture_id"],)
    assert str(source.source_id) == first["record"]["source_slots"][0]["source_id"]
    for replacement in (
        [(capture["capture_id"], "ff" * 32, "changed.jpg")],
        [(uuid.uuid4(), selected[0][1], "foreign.jpg")],
        selected * 2,
    ):
        with pytest.raises(ValueError):
            compose_reference_sources(repository, **{**options, "captures": replacement})
    repository.insert_tombstone(
        scope="capture",
        capture_id=capture["capture_id"],
        requested_by=uuid.uuid4(),
        reason="isolated test withdrawal",
    )
    with pytest.raises(ValueError, match="unavailable"):
        compose_reference_sources(repository, **options)
