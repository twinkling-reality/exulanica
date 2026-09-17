"""The two tile routes, through the real application: what they serve, refuse and charge.

Everything a request passes through here ships: the permission floor, the token directory, the
workspace-scoped connection as the non-owner runtime role, migration 0072's tables under row-level
security, migration 0062's ceiling and the error map. Only the tiles themselves are made up.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.permissions import ROUTE_RULES, SELF_CHARGING_TILE_ROUTES, Permission
from exulanica.api.quotas import declare_tile_quota
from exulanica.api.services import Services
from exulanica.db.roles import provision_runtime_role
from exulanica.db.session import Database
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import tile_store
from exulanica.world.baked_tiles import TILE_MEDIA_TYPE, BakedTileRepository
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from pg_harness import migrated_schema
from test_route_permissions import ALL_PERMISSIONS, APP_ROLE, app_role_dsn

pytestmark = pytest.mark.postgres

CITY_SEED = hashlib.sha256(b"a corridor city for the route test").hexdigest()
EMPTY_EDIT_DELTA = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
GRANTS = {
    "walker": ("walker", ALL_PERMISSIONS),
    "cramped": ("cramped", ALL_PERMISSIONS),
    "viewer": ("walker", ["world.read"]),
}


@dataclass
class Tiles:
    client: TestClient
    tokens: dict[str, str]
    workspaces: dict[str, uuid.UUID]
    keys: dict[str, uuid.UUID]
    digests: dict[str, str]
    dsn: str

    def get(self, who: str, path: str, **headers: str):
        return self.client.get(
            path, headers={"Authorization": f"Bearer {self.tokens[who]}", **headers}
        )

    def used(self, who: str) -> int:
        """How many tiles of its ceiling this workspace has spent."""
        with psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row) as connection:
            connection.execute(
                "select set_config('exulanica.workspace_id', %s, false)",
                (str(self.workspaces[who]),),
            )
            row = connection.execute(
                "select tiles_used from workspace_tile_quota where workspace_id = %s",
                (self.workspaces[who],),
            ).fetchone()
            return int(row["tiles_used"]) if row else 0


def _record(repository: BakedTileRepository, key: uuid.UUID, tile_x: int, container: bytes) -> str:
    return repository.record(
        baked_tile_id=key,
        stage_version=3,
        stage_params_sha256=hashlib.sha256(b"params").digest(),
        tile={
            "tile_inputs_digest": hashlib.sha256(f"inputs {tile_x}".encode()).hexdigest(),
            "city_seed": CITY_SEED,
            "grammar_versions": [
                {"grammar_id": "city", "grammar_version": 2, "descriptor_sha256": "0" * 64}
            ],
            "catalog_digest": hashlib.sha256(b"catalogs").hexdigest(),
            "edit_delta_digest": EMPTY_EDIT_DELTA,
            "tile_x": tile_x,
            "tile_y": 0,
            "lod": 0,
            "tile_size_mm": 128_000,
            "halo_radius_mm": 64_000,
        },
        document=b"a tile document",
        container=container,
        render_batch_sha256=hashlib.sha256(b"render").digest(),
        nav_envelope_sha256=hashlib.sha256(b"nav").digest(),
        receipt={"tessellator": 3, "container": "owd/3"},
    )


@pytest.fixture(scope="module")
def tiles(tmp_path_factory) -> Iterator[Tiles]:
    root = tmp_path_factory.mktemp("tile-route")
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        scratch = admin.execute("select current_schema()").fetchone()["current_schema"]
        provision_runtime_role(admin, role=APP_ROLE)
        admin.commit()
        store = tile_store(root)
        repository = BakedTileRepository(connection=admin, store=store)
        keys = {"first": uuid.uuid4(), "second": uuid.uuid4(), "faulted": uuid.uuid4()}
        _record(repository, keys["first"], 2, b"the corridor tile")
        _record(repository, keys["second"], 3, b"the tile east of it")
        _record(repository, keys["faulted"], 4, b"one bake")
        _record(repository, keys["faulted"], 4, b"another bake")
        admin.commit()
        workspaces = {name: uuid.uuid4() for name in ("walker", "cramped")}
        tokens = {who: f"{who}-token-{uuid.uuid4().hex}" for who in GRANTS}
        directory = load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        tokens[who]: {
                            "workspace_id": str(workspaces[workspace]),
                            "actor": str(uuid.uuid4()),
                            "permissions": granted,
                        }
                        for who, (workspace, granted) in GRANTS.items()
                    }
                )
            }
        )
        dsn = app_role_dsn(scratch)
        database = Database(url=dsn)
        services = Services(
            database=database,
            readonly_database=database,
            store=LocalContentAddressedStore(root / "blobs"),
            tokens=directory,
            executor_shares_the_write_role=True,
            model_client=None,
            tiles=store,
        )
        app = create_app(services, verify=False)
        for name, limit in (("walker", 8), ("cramped", 1)):
            with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
                connection.execute(
                    "select set_config('exulanica.workspace_id', %s, false)",
                    (str(workspaces[name]),),
                )
                declare_tile_quota(
                    connection, workspaces[name], tiles_limit=limit, declared_by=uuid.uuid4()
                )
        with TestClient(app) as client:
            yield Tiles(
                client=client,
                dsn=dsn,
                tokens=tokens,
                workspaces=workspaces,
                keys=keys,
                digests={
                    "first": hashlib.sha256(b"the corridor tile").hexdigest(),
                    "second": hashlib.sha256(b"the tile east of it").hexdigest(),
                },
            )


def test_both_routes_are_declared_and_charge_their_own_quota():
    for path in ("/tiles", "/tiles/{baked_tile_id}/bytes"):
        rule = ROUTE_RULES[("GET", path)]
        assert rule.permissions == frozenset({Permission.TILES_MATERIALISE})
        assert ("GET", path) in SELF_CHARGING_TILE_ROUTES


def test_a_city_lists_the_tiles_stored_for_it(tiles):
    answer = tiles.get("walker", f"/tiles?city_seed={CITY_SEED}")
    assert answer.status_code == 200
    listed = answer.json()["tiles"]
    assert [tile["tile_x"] for tile in listed] == [2, 3, 4]
    states = {tile["tile_x"]: tile["state"] for tile in listed}
    assert states == {2: "baked", 3: "baked", 4: "nondeterminism_detected"}
    assert answer.headers["Cache-Control"] == "private, no-cache"
    other = tiles.get("walker", f"/tiles?city_seed={'a' * 64}")
    assert other.status_code == 200 and other.json()["tiles"] == []


def test_the_bytes_are_served_once_charged_and_named_by_their_digest(tiles):
    key = tiles.keys["first"]
    answer = tiles.get("walker", f"/tiles/{key}/bytes")
    assert answer.status_code == 200
    assert answer.content == b"the corridor tile"
    assert answer.headers["ETag"] == f'"{tiles.digests["first"]}"'
    assert answer.headers["Content-Type"] == TILE_MEDIA_TYPE
    assert answer.headers["Cache-Control"] == "private, no-cache"
    assert answer.headers["X-Content-Type-Options"] == "nosniff"
    again = tiles.get("walker", f"/tiles/{key}/bytes")
    assert again.status_code == 200 and again.content == answer.content


def test_a_walk_that_reloads_one_tile_spends_one_of_the_ceiling(tiles):
    key = tiles.keys["second"]
    for _ in range(3):
        assert tiles.get("cramped", f"/tiles/{key}/bytes").status_code == 200
    refused = tiles.get("cramped", f"/tiles/{tiles.keys['first']}/bytes")
    assert refused.status_code == 429
    assert refused.json()["code"] == "tile_quota_exceeded"


def test_a_revalidation_is_answered_304_and_costs_no_tile(tiles):
    """What the ETag is for. A loader that already holds the bytes gets no body and pays nothing."""
    key = tiles.keys["first"]
    etag = f'"{tiles.digests["first"]}"'
    before = tiles.used("walker")
    answer = tiles.get("walker", f"/tiles/{key}/bytes", **{"If-None-Match": etag})
    assert answer.status_code == 304
    assert answer.content == b""
    assert answer.headers["ETag"] == etag
    assert tiles.used("walker") == before
    # The weak form and the wildcard name the same representation; a digest that is not this
    # tile's does not.
    assert (
        tiles.get("walker", f"/tiles/{key}/bytes", **{"If-None-Match": f"W/{etag}"}).status_code
        == 304
    )
    assert tiles.get("walker", f"/tiles/{key}/bytes", **{"If-None-Match": "*"}).status_code == 304
    stale = tiles.get("walker", f"/tiles/{key}/bytes", **{"If-None-Match": '"' + "0" * 64 + '"'})
    assert stale.status_code == 200 and stale.content == b"the corridor tile"


def test_a_faulted_tile_is_never_revalidated_either(tiles):
    """A faulted tile answers 409 whatever the caller holds: it is never current."""
    answer = tiles.get("walker", f"/tiles/{tiles.keys['faulted']}/bytes", **{"If-None-Match": "*"})
    assert answer.status_code == 409 and answer.json()["code"] == "nondeterminism_detected"


def test_a_faulted_tile_is_never_served(tiles):
    answer = tiles.get("walker", f"/tiles/{tiles.keys['faulted']}/bytes")
    assert answer.status_code == 409
    assert answer.json()["code"] == "nondeterminism_detected"
    assert answer.content != b"one bake"


def test_an_unknown_key_and_a_missing_permission_are_refused_alike(tiles):
    """The floor's rule: on a route addressed by an id, a refusal answers as a missing id does."""
    missing = tiles.get("walker", f"/tiles/{uuid.uuid4()}/bytes")
    assert missing.status_code == 404 and missing.json()["code"] == "unknown_reference"
    refused = tiles.get("viewer", f"/tiles/{tiles.keys['first']}/bytes")
    assert refused.status_code == 404 and refused.json()["code"] == "unknown_reference"
    assert refused.content != b"the corridor tile"
    # The listing route names no id, so it says plainly that the credential is not the reason.
    listing = tiles.get("viewer", f"/tiles?city_seed={CITY_SEED}")
    assert listing.status_code == 403 and listing.json()["code"] == "not_authorised"
