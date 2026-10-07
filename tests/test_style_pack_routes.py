"""The committed style pack library over HTTP, as a page meets it.

No database: the routes read the library the host loaded, and a token from the configured directory
resolves without one. The expected bytes come from the committed files (each manifest file is its
canonical JSON and one newline), not from the library loader the routes call.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.session import Database
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient

PACKS = Path(__file__).resolve().parents[1] / "assets" / "style-packs" / "packs"
TOKEN = "style-pack-reader-" + uuid.uuid4().hex


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    # Never connected: these routes take no connection, and a token resolves without one.
    unused = Database(url="postgresql://unused.invalid/none")
    tokens = load_token_directory(
        {
            "EXULANICA_API_TOKENS": json.dumps(
                {
                    TOKEN: {
                        "workspace_id": str(uuid.uuid4()),
                        "actor": str(uuid.uuid4()),
                        "permissions": ["world.read"],
                    }
                }
            )
        }
    )
    services = Services(
        database=unused,
        readonly_database=unused,
        store=LocalContentAddressedStore(tmp_path / "store"),
        tokens=tokens,
        executor_shares_the_write_role=True,
        model_client=None,
    )
    # Not entered as a context manager: the lifespan checks a database these routes never need.
    return TestClient(create_app(services, verify=False))


def _get(client: TestClient, path: str):
    return client.get(path, headers={"Authorization": f"Bearer {TOKEN}"})


def _cozy() -> tuple[dict, bytes]:
    text = (PACKS / "exulanica.cozy-town" / "manifest.json").read_bytes()
    return json.loads(text), text[:-1]


def test_both_routes_refuse_a_caller_without_a_session(client: TestClient) -> None:
    _manifest, canonical = _cozy()
    assert client.get("/world/style-packs").status_code == 401
    digest = hashlib.sha256(canonical).hexdigest()
    assert client.get(f"/world/style-packs/{digest}").status_code == 401


def test_the_list_names_every_committed_pack_with_its_licence_and_attribution(client) -> None:
    response = _get(client, "/world/style-packs")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    body = response.json()
    assert body["profile"] == "exulanica.style-pack-list/v1"
    listed = {pack["pack_id"]: pack for pack in body["packs"]}
    assert sorted(listed) == sorted(folder.name for folder in PACKS.iterdir())
    manifest, canonical = _cozy()
    cozy = listed["exulanica.cozy-town"]
    assert cozy["manifest_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert cozy["licence"] == {"id": "CC0-1.0", "attribution": None}
    assert cozy["licence"] == manifest["licence"]
    assert cozy["authors"] == manifest["authors"]
    # The pack the library file names is the one marked default, and no other is.
    library = json.loads((PACKS.parent / "library.v1.json").read_text(encoding="utf-8"))
    assert {pack_id: pack["default"] for pack_id, pack in listed.items()} == {
        pack_id: pack_id == library["default"] for pack_id in listed
    }


def test_a_manifest_and_a_piece_are_served_as_the_bytes_their_digest_names(client) -> None:
    manifest, canonical = _cozy()
    digest = hashlib.sha256(canonical).hexdigest()
    response = _get(client, f"/world/style-packs/{digest}")
    assert response.status_code == 200
    assert response.content == canonical
    assert response.headers["content-type"] == "application/json"
    assert response.headers["etag"] == f'"{digest}"'
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    picture = (PACKS / "exulanica.cozy-town" / manifest["preview"]).read_bytes()
    response = _get(client, f"/world/style-packs/{hashlib.sha256(picture).hexdigest()}")
    assert response.status_code == 200
    assert response.content == picture
    assert response.headers["content-type"] == "image/jpeg"
    listed = manifest["files"][0]
    piece = (PACKS / "exulanica.cozy-town" / listed["path"]).read_bytes()
    response = _get(client, f"/world/style-packs/{listed['sha256']}")
    assert response.status_code == 200
    assert response.content == piece
    assert response.headers["content-type"] == "model/gltf-binary"
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"


def test_a_digest_the_library_does_not_hold_is_404_and_anything_else_is_no_path(client) -> None:
    unknown = _get(client, f"/world/style-packs/{'e' * 64}")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "unknown_reference"
    # The bytes of a committed file that no manifest lists are not served either.
    store_file = hashlib.sha256((PACKS.parent / "piece-budgets.v1.json").read_bytes()).hexdigest()
    assert _get(client, f"/world/style-packs/{store_file}").status_code == 404
    for malformed in ("E" * 64, "e" * 63, "manifest.json", "..%2Fpiece-budgets.v1.json"):
        assert _get(client, f"/world/style-packs/{malformed}").status_code in (404, 422), malformed
