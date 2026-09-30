"""The traffic route, through the real application: what it serves, refuses, and never charges.

Everything a request passes through ships: the permission floor, the token directory, the
workspace-scoped connection as the non-owner runtime role, migration 0072's tables under row-level
security and the tile quota. The corridor's tiles are recorded with a container that states their
records in the tessellator's header layout; the development preview's committed tile is a real bake,
and its header is read the same way.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.permissions import ROUTE_RULES, SELF_CHARGING_TILE_ROUTES, Permission
from exulanica.api.quotas import declare_tile_quota
from exulanica.api.services import Services
from exulanica.db.roles import provision_runtime_role
from exulanica.db.session import Database
from exulanica.grammar.grammars.city.document import read_tile_document
from exulanica.grammar.grammars.city.generation.corridor import CORRIDOR_SEED
from exulanica.grammar.grammars.city.tile import tile_inputs_digest
from exulanica.grammar.records import record_payload
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import tile_store
from exulanica.world import traffic_host
from exulanica.world.baked_tiles import BakedTileRepository
from exulanica.world.traffic_episodes import EPISODE
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

import traffic_corridor_support as corridor
from pg_harness import migrated_schema
from test_route_permissions import ALL_PERMISSIONS, APP_ROLE, app_role_dsn

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
#: A real bake: the development preview's committed tile, tess's conformance fixture.
REAL_CONTAINER = (
    ROOT / "web" / "packages" / "app" / "src" / "dev" / "tiles" / "tile-conformance.owd"
)
REAL_DOCUMENT = ROOT / "tests" / "fixtures" / "city-v2" / "tile-document.json"
FIXTURE_SEED = hashlib.sha256(b"the fixture tile for the traffic route test").hexdigest()
GRANTS = {"walker": ALL_PERMISSIONS, "viewer": ["world.read"]}


@dataclass
class Route:
    client: TestClient
    tokens: dict[str, str]
    workspace: uuid.UUID
    dsn: str

    def get(self, who: str, path: str):
        return self.client.get(path, headers={"Authorization": f"Bearer {self.tokens[who]}"})

    def used(self) -> int:
        with psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row) as connection:
            connection.execute(
                "select set_config('exulanica.workspace_id', %s, false)", (str(self.workspace),)
            )
            row = connection.execute(
                "select tiles_used from workspace_tile_quota where workspace_id = %s",
                (self.workspace,),
            ).fetchone()
            return int(row["tiles_used"]) if row else 0


def _record(repository: BakedTileRepository, tile, container: bytes, seed: str) -> None:
    fields = record_payload(tile)["fields"]
    repository.record(
        baked_tile_id=uuid.uuid4(),
        stage_version=3,
        stage_params_sha256=hashlib.sha256(b"params").digest(),
        tile={**fields, "city_seed": seed, "tile_inputs_digest": tile_inputs_digest(tile)},
        document=b"a tile document",
        container=container,
        render_batch_sha256=hashlib.sha256(b"render").digest(),
        nav_envelope_sha256=hashlib.sha256(b"nav").digest(),
        receipt={"tessellator": 20, "container": "owd/3"},
    )


@pytest.fixture(scope="module")
def route(tmp_path_factory) -> Iterator[Route]:
    root = tmp_path_factory.mktemp("tile-traffic")
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        scratch = admin.execute("select current_schema()").fetchone()["current_schema"]
        provision_runtime_role(admin, role=APP_ROLE)
        admin.commit()
        store = tile_store(root)
        repository = BakedTileRepository(connection=admin, store=store)
        for document in corridor.documents().values():
            _record(repository, document.tile, corridor.container_of(document), CORRIDOR_SEED)
        fixture = read_tile_document(REAL_DOCUMENT.read_bytes())
        _record(repository, fixture.tile, REAL_CONTAINER.read_bytes(), FIXTURE_SEED)
        admin.commit()
        workspace = uuid.uuid4()
        tokens = {who: f"{who}-token-{uuid.uuid4().hex}" for who in GRANTS}
        directory = load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        tokens[who]: {
                            "workspace_id": str(workspace),
                            "actor": str(uuid.uuid4()),
                            "permissions": granted,
                        }
                        for who, granted in GRANTS.items()
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
        with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
            connection.execute(
                "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
            )
            declare_tile_quota(connection, workspace, tiles_limit=2, declared_by=uuid.uuid4())
        with TestClient(create_app(services, verify=False)) as client:
            yield Route(client=client, tokens=tokens, workspace=workspace, dsn=dsn)


@pytest.fixture(autouse=True)
def in_this_process(monkeypatch):
    """The route's worker, in this process: the spawned one is tests/test_traffic_episodes.py's."""
    from concurrent.futures import ThreadPoolExecutor

    worker = traffic_host.TrafficEpisodes(lambda: ThreadPoolExecutor(max_workers=1))
    monkeypatch.setattr(traffic_host, "_episodes", worker)
    yield
    worker.close()


def test_the_route_requires_tiles_materialise_and_charges_nothing_itself():
    rule = ROUTE_RULES[("GET", "/tiles/traffic")]
    assert rule.permissions == frozenset({Permission.TILES_MATERIALISE})
    assert "materialises none" in SELF_CHARGING_TILE_ROUTES[("GET", "/tiles/traffic")]


def _near_the_clock(offset: int) -> int:
    """A second ``offset`` into the episode the shared clock is in, which the clock's reach
    admits."""
    clock = traffic_host.traffic_clock()
    return clock - clock % EPISODE + offset


def test_a_window_of_the_corridors_traffic_is_served_and_no_tile_is_charged(route):
    start = _near_the_clock(150)
    answer = route.get("walker", f"/tiles/traffic?world_seed={CORRIDOR_SEED}&from_second={start}")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["profile"], body["from_second"], body["seconds"]) == (
        "exulanica.traffic-window/v2",
        start,
        60,
    )
    assert body["world_seed"] == CORRIDOR_SEED and body["crossings_fed"] is False
    assert len(body["vehicles"]) == sum(corridor.prepared().fleet.values())
    assert any(2 in row["mode"] for row in body["vehicles"]), "some vehicle drives this minute"
    assert route.used() == 0


def test_a_window_without_a_second_starts_at_the_shared_clock(route):
    answer = route.get("walker", f"/tiles/traffic?world_seed={CORRIDOR_SEED}&seconds=5")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert 0 <= body["clock_second"] - body["from_second"] <= 30


def test_refusals_name_what_is_wrong(route):
    near = _near_the_clock(0)
    cases = [
        (f"/tiles/traffic?world_seed={'0' * 64}&from_second={near}", 404, "roads_not_stated"),
        (
            f"/tiles/traffic?world_seed={CORRIDOR_SEED}&from_second={near}&seconds=61",
            422,
            "traffic_window_too_long",
        ),
        (
            f"/tiles/traffic?world_seed={CORRIDOR_SEED}&from_second={near - 3 * EPISODE}",
            422,
            "traffic_second_out_of_range",
        ),
    ]
    for path, status, code in cases:
        answer = route.get("walker", path)
        assert (answer.status_code, answer.json()["code"]) == (status, code), path


def test_a_world_whose_roads_traffic_cannot_drive_is_refused_with_the_reason(route):
    """The fixture tile's square-cornered turns carry no class; its real bake's header is read."""
    clock = traffic_host.traffic_clock()
    answer = route.get("walker", f"/tiles/traffic?world_seed={FIXTURE_SEED}&from_second={clock}")
    assert answer.status_code == 409, answer.text
    assert answer.json()["code"] == "roads_unavailable"
    assert "carries no class" in answer.json()["detail"]


def test_a_session_without_the_permission_is_refused_before_the_route(route):
    answer = route.get("viewer", f"/tiles/traffic?world_seed={CORRIDOR_SEED}")
    assert answer.status_code in (403, 404)
    assert "vehicles" not in answer.text


def test_a_real_bakes_header_carries_its_documents_records_as_the_host_reads_them():
    document = read_tile_document(REAL_DOCUMENT.read_bytes())
    header = traffic_host._header(REAL_CONTAINER.read_bytes(), "the conformance tile")
    [grammar] = document.grammars
    stated = {
        record.identity: record_payload(record)  # type: ignore[attr-defined]
        for record in (*grammar.owned, *grammar.halo)
    }
    read = {
        row["identity"]: {"kind": row["kind"], "version": row["version"], "fields": row["fields"]}
        for row in header["records"]
        if row["kind"] != "city.tile"
    }
    assert read == stated
    assert [
        (g["grammar_id"], g["grammar_version"], g["subject_identity"]) for g in header["grammars"]
    ] == [(grammar.grammar_id, grammar.grammar_version, grammar.subject_identity)]
