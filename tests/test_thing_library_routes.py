"""The shipped thing library over HTTP, as a renderer meets it.

No database: the routes read the library the host loaded, and a token from the configured directory
resolves without one. The expected bytes come from the committed files (a kind is served as the
canonical JSON of its file's document) and from the authored looks' writer, not from the library
the routes call.
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
from exulanica.canonical import canonical_json
from exulanica.db.session import Database
from exulanica.grammar.documents import read_json
from exulanica.store.local import LocalContentAddressedStore
from exulanica.things.authored import container_of
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
WELL_KIND = ROOT / "assets/catalogs/things/kinds/well.v1.json"
WELL_LOOK = ROOT / "assets/catalogs/things/looks/primitive-well.v1.json"
TOKEN = "thing-library-reader-" + uuid.uuid4().hex


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


def _well() -> bytes:
    return canonical_json(read_json(WELL_KIND))


def test_both_routes_refuse_a_caller_without_a_session(client: TestClient) -> None:
    assert client.get("/things/library").status_code == 401
    digest = hashlib.sha256(_well()).hexdigest()
    assert client.get(f"/things/library/{digest}").status_code == 401


def test_the_list_names_the_well_with_its_look_and_the_look_with_its_container(client) -> None:
    response = _get(client, "/things/library")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body["profile"] == "exulanica.thing-library/v1"
    kind = read_json(WELL_KIND)
    [well] = [k for k in body["kinds"] if (k["kind"], k["version"]) == ("well", 1)]
    assert well["sha256"] == hashlib.sha256(_well()).hexdigest()
    assert well["looks"] == kind["looks"]
    look = read_json(WELL_LOOK)
    [listed] = [k for k in body["looks"] if (k["look"], k["version"]) == ("primitive-well", 1)]
    assert listed["container"] == look["container"]
    assert {"look": "primitive-well", "version": 1, "sha256": listed["sha256"]} in well["looks"]


def test_a_kind_and_a_container_are_served_as_the_bytes_their_digest_names(client) -> None:
    canonical = _well()
    digest = hashlib.sha256(canonical).hexdigest()
    response = _get(client, f"/things/library/{digest}")
    assert response.status_code == 200
    assert response.content == canonical
    assert response.headers["content-type"] == "application/json"
    assert response.headers["etag"] == f'"{digest}"'
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    container = read_json(WELL_LOOK)["container"]
    response = _get(client, f"/things/library/{container['sha256']}")
    assert response.status_code == 200
    assert response.content == container_of("primitive-well")
    assert hashlib.sha256(response.content).hexdigest() == container["sha256"]
    assert response.headers["content-type"] == "model/gltf-binary"
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"


def test_a_digest_the_library_does_not_hold_is_404_and_anything_else_is_no_path(client) -> None:
    unknown = _get(client, f"/things/library/{'e' * 64}")
    assert unknown.status_code == 404
    assert unknown.json() == {
        "code": "unknown_reference",
        "detail": "no such thing library content",
    }
    # The well's file as committed (not canonical) is not what any address names.
    as_committed = hashlib.sha256(WELL_KIND.read_bytes()).hexdigest()
    assert _get(client, f"/things/library/{as_committed}").status_code == 404
    for malformed in ("E" * 64, "e" * 63, "well.v1.json", "..%2Fkinds.lock.json"):
        assert _get(client, f"/things/library/{malformed}").status_code in (404, 422), malformed
