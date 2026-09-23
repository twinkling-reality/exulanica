"""Prepared character bytes use the same authenticated catalog as other reviewed assets.

They are components, so they are served by key and never listed as something to place.
"""

import json
from pathlib import Path

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.world.asset_import import ReviewedAssetImport, import_reviewed_asset
from exulanica.world.asset_kinds import AssetKind

import test_world_objects_api as helpers

objects_api = helpers.objects_api
pytestmark = pytest.mark.postgres
ASSETS = Path(__file__).resolve().parents[1] / "assets/characters/quaternius-modular-v2"


def test_prepared_characters_are_delivered_exactly_and_withdrawal_revokes_delivery(
    objects_api, repository
):
    connection = repository.connection
    imports = sorted(ASSETS.glob("*.import.json"))
    assert imports, "Prepared character import manifests must be present"
    for path in imports:
        manifest = ReviewedAssetImport.model_validate_json(path.read_bytes())
        payload = path.with_name(path.name.replace(".import.json", ".glb")).read_bytes()
        family = "women" if path.name.endswith("-f.import.json") else "men"
        licence = (ASSETS / f"{family}-LICENSE.txt").read_bytes()
        assert manifest.licence_sha256 == BlobId.of_bytes(licence).hex
        with connection.transaction():
            receipt = import_reviewed_asset(
                connection, objects_api.store, manifest, payload, licence, kind=AssetKind.COMPONENT
            )
        connection.commit()
        route = f"/world/assets/{manifest.asset_key}"
        try:
            served = objects_api.get(route)
            assert served.status_code == 200, served.text
            assert served.json()["availability"] == "available"
            assert served.json()["content_sha256"] == manifest.content_sha256
            assert served.json()["placeable"] is False
            assert manifest.asset_key not in {
                row["asset_key"] for row in objects_api.get("/world/assets").json()
            }
            response = objects_api.get(route + "/bytes")
            assert response.status_code == 200, response.text
            assert response.content == payload
            assert response.headers["etag"] == f'"{manifest.content_sha256}"'
            assert objects_api.get(route + "/licence").content == licence
            assert objects_api.client.get(route + "/bytes").status_code == 401
            retained = json.loads(objects_api.store.get(BlobId.from_hex(receipt)))
            assert retained["source_revision"] == manifest.source_revision
            assert retained["licence_sha256"] == manifest.licence_sha256
        finally:
            with connection.transaction():
                connection.execute(
                    "delete from world_reviewed_asset where asset_key=%s", (manifest.asset_key,)
                )
            connection.commit()
        # A retained blob is not sufficient authority to continue serving a withdrawn asset.
        assert objects_api.store.get(BlobId.from_hex(manifest.content_sha256)) == payload
        assert objects_api.get(route + "/bytes").status_code == 404
        assert objects_api.get(route + "/licence").status_code == 404
        assert objects_api.get(route).status_code == 404
