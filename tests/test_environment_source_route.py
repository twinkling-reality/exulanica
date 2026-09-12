from __future__ import annotations

import hashlib
import uuid

from exulanica.environment import MAX_ENVIRONMENT_PAYLOAD_BYTES
from exulanica.evidence.blob import BlobId
from exulanica.store.base import PurgeAuthorization, privileged_purger

from test_api import deployment as deployment


def _body(path, place_id, data):
    return {
        "admission_id": str(uuid.uuid4()),
        "place_id": str(place_id),
        "provider_key": "plateau",
        "provider_original_id": "shibuya-2023-citygml-v3",
        "provider_revision": "2023",
        "expected_sha256": hashlib.sha256(data).hexdigest(),
        "expected_byte_size": len(data),
        "source_path": "https://example.invalid/official-source.zip",
        "member_path": "udx/bldg/53393567.gml",
        "media_type": "application/zip",
        "geographic_frame": {
            "name": "plateau-epsg-6697",
            "crs": "EPSG:6697",
            "axis_order": ["east", "north", "height"],
            "horizontal_unit": "metre",
            "vertical_unit": "metre",
            "orientation": "right-handed",
            "altitude_reference": "JGD2011 vertical datum",
        },
        "geographic_bounds": {
            "kind": "bbox",
            "frame_name": "plateau-epsg-6697",
            "coordinate_scale": 1000,
            "coordinates": [0, 0, 0, 1000, 1000, 1000],
        },
        "operation_rights": {
            "display": True,
            "extract": True,
            "index": True,
            "persist": True,
            "modify": True,
            "compose": True,
            "export": False,
            "model_processing": False,
        },
        "attribution": "Project PLATEAU; source attribution required.",
        "modification_notice": "Modified outputs must be marked.",
        "local_path": str(path),
    }


def _staged(tmp_path, workspace_id, name, data):
    directory = tmp_path / str(workspace_id)
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_bytes(data)
    return path


def test_route_admits_local_bytes_and_enforces_each_requested_operation(
    deployment, repository, tmp_path
):
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    data = b"small route environment source fixture"
    path = _staged(tmp_path, deployment.owner, "route-source.zip", data)
    body = _body(path, place_id, data)

    admitted = deployment.as_owner(
        "POST", "/environment-resources/sources", json=body
    )
    assert admitted.status_code == 201, admitted.text
    resource_id = admitted.json()["resource_id"]
    metadata_path = f"/environment-resources/source/{resource_id}"
    bytes_path = metadata_path + "/bytes"

    metadata = deployment.as_owner(
        "GET", metadata_path, params={"operation": "display"}
    )
    assert metadata.status_code == 200
    assert metadata.json()["receipt"]["operation_rights"]["export"] is False
    assert deployment.as_owner(
        "GET", bytes_path, params={"operation": "display"}
    ).content == data
    denied = deployment.as_owner(
        "GET", bytes_path, params={"operation": "export"}
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "operation_denied"

    real = deployment.as_stranger(
        "GET", metadata_path, params={"operation": "display"}
    )
    invented = deployment.as_stranger(
        "GET",
        f"/environment-resources/source/{uuid.uuid4()}",
        params={"operation": "display"},
    )
    assert real.status_code == invented.status_code == 404
    assert real.json() == invented.json()


def test_route_reports_missing_bytes_and_withdrawal(deployment, repository, tmp_path):
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    data = b"small missing source fixture"
    path = _staged(tmp_path, deployment.owner, "missing-source.zip", data)
    body = _body(path, place_id, data)
    admitted = deployment.as_owner(
        "POST", "/environment-resources/sources", json=body
    )
    assert admitted.status_code == 201, admitted.text
    resource_id = uuid.UUID(admitted.json()["resource_id"])
    route = f"/environment-resources/source/{resource_id}"

    privileged_purger(
        deployment.store,
        PurgeAuthorization(tombstone_id="route-test", actor="test", reason="missing control"),
    ).purge(BlobId.of_bytes(data))
    missing = deployment.as_owner(
        "GET", route + "/bytes", params={"operation": "display"}
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "unknown_reference"

    repository.connection.execute(
        "update environment_source_admission set withdrawn_at=statement_timestamp() "
        "where workspace_id=%s and admission_id=%s",
        (repository.workspace_id, resource_id),
    )
    withdrawn = deployment.as_owner(
        "GET", route, params={"operation": "display"}
    )
    assert withdrawn.status_code == 410
    assert withdrawn.json()["code"] == "withdrawn"


def test_route_refuses_a_local_path_outside_the_environment_inbox(
    deployment, repository, tmp_path
):
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    data = b"must not be read"
    outside = tmp_path.parent / f"outside-{uuid.uuid4()}.zip"
    outside.write_bytes(data)
    try:
        response = deployment.as_owner(
            "POST",
            "/environment-resources/sources",
            json=_body(outside, place_id, data),
        )
        assert response.status_code == 404
        assert response.json()["code"] == "unknown_reference"
        assert repository.connection.execute(
            "select count(*) n from environment_source_admission where workspace_id=%s",
            (repository.workspace_id,),
        ).fetchone()["n"] == 0
    finally:
        outside.unlink()


def test_post_reference_failures_are_indistinguishable(deployment, repository, tmp_path):
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    data = b"reference probe"
    owner_path = _staged(tmp_path, deployment.owner, "owner-probe.zip", data)
    stranger_path = _staged(tmp_path, deployment.stranger, "stranger-probe.zip", data)

    foreign_stage = deployment.as_stranger(
        "POST", "/environment-resources/sources", json=_body(owner_path, place_id, data)
    )
    absent_stage = deployment.as_stranger(
        "POST",
        "/environment-resources/sources",
        json=_body(stranger_path.with_name("absent.zip"), place_id, data),
    )
    foreign_place = deployment.as_stranger(
        "POST", "/environment-resources/sources", json=_body(stranger_path, place_id, data)
    )
    absent_place = deployment.as_stranger(
        "POST",
        "/environment-resources/sources",
        json=_body(stranger_path, uuid.uuid4(), data),
    )
    assert (
        foreign_stage.json()
        == absent_stage.json()
        == foreign_place.json()
        == absent_place.json()
    )
    assert foreign_stage.status_code == absent_stage.status_code == 404


def test_post_rejects_payload_over_the_buffered_limit_before_hashing(
    deployment, repository, tmp_path
):
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    path = tmp_path / str(deployment.owner) / "oversized.zip"
    path.parent.mkdir(exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(MAX_ENVIRONMENT_PAYLOAD_BYTES + 1)
    body = _body(path, place_id, b"")
    body["expected_byte_size"] = MAX_ENVIRONMENT_PAYLOAD_BYTES + 1
    response = deployment.as_owner(
        "POST", "/environment-resources/sources", json=body
    )
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


def test_corrupt_stored_bytes_keep_the_global_integrity_failure(deployment, repository, tmp_path):
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    data = b"integrity route fixture"
    path = _staged(tmp_path, deployment.owner, "integrity.zip", data)
    admitted = deployment.as_owner(
        "POST", "/environment-resources/sources", json=_body(path, place_id, data)
    )
    assert admitted.status_code == 201
    blob = BlobId.of_bytes(data)
    stored_path = deployment.store.root / deployment.store.key_for(blob)
    stored_path.chmod(0o644)
    stored_path.write_bytes(b"x" * len(data))

    response = deployment.as_owner(
        "GET",
        f"/environment-resources/source/{admitted.json()['resource_id']}/bytes",
        params={"operation": "display"},
    )
    assert response.status_code == 500
    assert response.json()["code"] == "integrity_failure"
