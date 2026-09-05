"""Withdrawal is checked before an evidence endpoint reads bytes awaiting asynchronous purge."""

from __future__ import annotations

import uuid

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.store.resolve import address_from_span_row

from test_api import (
    deployment as deployment,
)


def _requests(deployment, repository):
    row = repository.connection.execute(
        "select * from evidence_span where span_id=%s", (deployment.span_id,),
    ).fetchone()
    address = address_from_span_row(row)
    return address, (
        (f"/evidence/{deployment.span_id}", {"headers": {"Range": "bytes=0-9"}}),
        (f"/evidence/{deployment.span_id}/region", {}),
        ("/evidence", {"params": {"uri": address.to_uri()}}),
    )


@pytest.mark.parametrize("scope", ["capture", "interval", "workspace"])
def test_every_evidence_entrypoint_refuses_withdrawal_before_bytes_are_purged(
    deployment, repository, scope,
):
    address, requests = _requests(deployment, repository)
    for path, options in requests:
        response = deployment.as_owner("GET", path, **options)
        assert response.status_code in (200, 206)
        assert response.headers["cache-control"] == "private, no-store"
    capture_id = repository.connection.execute(
        "select capture_id from capture where workspace_id=%s and deleted_at is null",
        (repository.workspace_id,),
    ).fetchone()["capture_id"]
    details = {}
    if scope != "workspace":
        details["capture_id"] = capture_id
    if scope == "interval":
        details.update(track_key=address.track_key,
                       interval_ns=[(address.interval.start_ns, address.interval.end_ns)])
    repository.insert_tombstone(scope=scope, requested_by=uuid.uuid4(), **details)
    # No purge worker runs here: the guard, not missing object-store bytes, must refuse.
    assert deployment.store.exists(address.blob_id)
    for path, options in requests:
        response = deployment.as_owner("GET", path, **options)
        assert response.status_code == 410, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert deployment.as_stranger("GET", path, **options).status_code == 404


def test_foreign_shared_bytes_do_not_make_withdrawn_owner_evidence_readable(
    deployment, repository,
):
    address, requests = _requests(deployment, repository)
    foreign_capture = repository.connection.execute(
        "insert into capture(workspace_id,blob_sha256) values (%s,%s) returning capture_id",
        (uuid.uuid4(), address.blob_id.digest),
    ).fetchone()["capture_id"]
    capture_id = repository.connection.execute(
        "select capture_id from capture where workspace_id=%s", (repository.workspace_id,),
    ).fetchone()["capture_id"]
    repository.insert_tombstone(scope="capture", capture_id=capture_id, requested_by=uuid.uuid4())
    assert deployment.store.exists(address.blob_id)
    assert repository.connection.execute(
        "select deleted_at from capture where capture_id=%s", (foreign_capture,),
    ).fetchone()["deleted_at"] is None
    for path, options in requests:
        assert deployment.as_owner("GET", path, **options).status_code == 410


def test_deliberate_same_workspace_reimport_uses_the_canonical_release_rule(
    deployment, repository,
):
    address, requests = _requests(deployment, repository)
    old_capture = repository.connection.execute(
        "select capture_id from capture where workspace_id=%s", (repository.workspace_id,),
    ).fetchone()["capture_id"]
    repository.insert_tombstone(scope="capture", capture_id=old_capture, requested_by=uuid.uuid4())
    assert deployment.as_owner("GET", requests[0][0]).status_code == 410
    new_capture = repository.insert_capture(
        BlobId(address.blob_id.digest), device_id="deliberate-reimport", started_at=None,
    )
    assert new_capture.capture_id != old_capture
    for path, options in requests:
        assert deployment.as_owner("GET", path, **options).status_code in (200, 206)
