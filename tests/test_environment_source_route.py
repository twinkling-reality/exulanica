from __future__ import annotations

import hashlib
import uuid

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


def test_route_admits_local_bytes_and_enforces_each_requested_operation(
    deployment, repository, tmp_path
):
    place_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    data = b"small route environment source fixture"
    path = tmp_path / "route-source.zip"
    path.write_bytes(data)
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
    path = tmp_path / "missing-source.zip"
    path.write_bytes(data)
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
