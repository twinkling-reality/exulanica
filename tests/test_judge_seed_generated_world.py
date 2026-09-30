"""A judge seed of a workspace holding a generated world carries the world's baked tiles.

The judge deployment runs no bake worker (``deploy/judge/compose.yaml``), so a generated world
whose tiles did not travel with its seed would read as baking for ever on the stack a judge is
given. These tests make a town the way the product makes one, bake its tiles through the bake
worker's own claim and publish path with a stand-in for the Node tessellator, serve the workspace
one more tile through the delivery ledger, and hold three things:

*   The seed restores into a freshly migrated database and an empty data directory, verifies, and
    the restored stack reads every tile of the town as baked and serves the same bytes, to the
    runtime role, under row-level security.
*   The seed carries only the baked tiles the workspace reaches: a tile no world of it names and
    nobody served it stays behind.
*   A reset keeps an identical baked tile row, puts back a missing one, and refuses by name one the
    stack holds differently.

And one about the format: an archive of format 1, which carried no tiles, is refused by name.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import psycopg
import pytest
from exulanica.api.quotas import declare_tile_quota
from exulanica.canonical import canonical_json
from exulanica.db.migrate import provision_workspace
from exulanica.db.roles import provision_runtime_role
from exulanica.db.session import Database
from exulanica.grammar.grammars.city.common import TILE_SIZE_MM
from exulanica.ingest.generated_tiles import GeneratedTileBaker
from exulanica.ingest.stages import STAGES
from exulanica.orchestration.judge_seed import (
    SeedManifest,
    SeedRefused,
    export_seed,
    read_manifest,
    reset_to_seed,
    restore_seed,
    verify_restored,
    verify_seed,
)
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import tile_store
from exulanica.world.baked_tiles import BakedTileRepository
from exulanica.world.generated_worlds import (
    compose_generated_world,
    create_generated_authorities,
    generated_tiles,
)
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM, town_recipe
from exulanica.world.worlds import GENERATED, new_world_id
from psycopg.rows import dict_row

from pg_harness import migrated_schema
from test_route_permissions import APP_ROLE, app_role_dsn

pytestmark = pytest.mark.postgres

_CREATED_AT: Final = "2026-09-29T00:00:00Z"
#: The preset the judged town is made from: two tiles of the city grammar.
_RECIPE: Final = "small_town"
#: The workspace's tile ceiling: room for the one tile it is served through the ledger, and more.
_TILES_LIMIT: Final = 4
#: A public tile's edit subsequence must be the empty one (migration 0072): SHA-256 of ``[]``.
_EMPTY_EDIT_DELTA: Final = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
#: The halo the corridor's tile records state: half a tile each way.
_HALO_RADIUS_MM: Final = TILE_SIZE_MM // 2


@dataclasses.dataclass(frozen=True)
class Exported:
    """A source workspace holding one baked town and one served tile, and its seed archive."""

    archive: Path
    manifest: SeedManifest
    workspace: uuid.UUID
    world_id: str
    snapshot_id: uuid.UUID
    #: The town's current bake of each tile, in the order the town lists its tiles, with the
    #: bytes the source served for it.
    town: dict[uuid.UUID, bytes]
    #: A tile no world here names, served to the workspace through the delivery ledger.
    served: uuid.UUID
    served_bytes: bytes
    #: A tile stored in the source that this workspace never reaches.
    unreached: uuid.UUID
    unreached_bytes: bytes


def _stand_in_bake(self, document: Path, container: Path) -> dict[str, object]:
    """The tessellator's statement for bytes named by the tile document, so two bakes of one
    document agree, as the worker requires before it marks a tile's job done."""
    data = b"owd:" + hashlib.sha256(document.read_bytes()).digest()
    container.write_bytes(data)
    return {
        "container_sha256": hashlib.sha256(data).hexdigest(),
        "triangle_digests": {
            "render_batch": hashlib.sha256(b"render batch").hexdigest(),
            "nav_envelope": hashlib.sha256(b"navigation envelope").hexdigest(),
        },
    }


def _stand_in_web(root: Path) -> Path:
    """A web directory holding the two files the worker checks for before it will run."""
    web = root / "web"
    for relative in ("packages/loom-tess/src/node/cli.ts", "node_modules/.bin/tsx"):
        (web / relative).parent.mkdir(parents=True, exist_ok=True)
        (web / relative).write_text("")
    return web


def _baker(
    admin: psycopg.Connection, scratch: str, tiles: LocalContentAddressedStore, root: Path
) -> GeneratedTileBaker:
    """A baker as the worker runs one: claiming as the runtime role, publishing as the owner."""

    @contextlib.contextmanager
    def publisher() -> Iterator[psycopg.Connection]:
        # The owner connection, the only one migration 0072 lets publish a baked tile.
        yield admin
        admin.commit()

    return GeneratedTileBaker(
        session=Database(url=app_role_dsn(scratch)).session,
        publisher=publisher,
        store=tiles,
        web_directory=_stand_in_web(root),
        worker="judge-seed-test",
    )


def _ledger_tile(label: str, tile_x: int) -> dict[str, object]:
    """A tile record as ``BakedTileRepository.record`` is handed one, for a tile no generated world
    here names. It states ``city_seed`` because the tile record does (migration 0081)."""
    return {
        "tile_inputs_digest": hashlib.sha256(f"inputs of {label}".encode()).hexdigest(),
        "city_seed": hashlib.sha256(b"a corridor city").hexdigest(),
        "grammar_versions": [
            {
                "grammar_id": "city",
                "grammar_version": STAGES["baked_tile"].version,
                "descriptor_sha256": hashlib.sha256(b"descriptor").hexdigest(),
            }
        ],
        "catalog_digest": hashlib.sha256(b"catalogs").hexdigest(),
        "edit_delta_digest": _EMPTY_EDIT_DELTA,
        "tile_x": tile_x,
        "tile_y": 0,
        "lod": 0,
        "tile_size_mm": TILE_SIZE_MM,
        "halo_radius_mm": _HALO_RADIUS_MM,
    }


def _record_ledger_tile(
    repository: BakedTileRepository,
    label: str,
    tile_x: int,
    container: bytes,
    key: uuid.UUID | None = None,
) -> tuple[uuid.UUID, str]:
    """Record one bake of a ledger tile with synthetic container bytes, as the offline bake does."""
    key = key or uuid.uuid4()
    outcome = repository.record(
        baked_tile_id=key,
        stage_version=STAGES["baked_tile"].version,
        stage_params_sha256=STAGES["baked_tile"].params_digest,
        tile=_ledger_tile(label, tile_x),
        document=f"the tile document of {label}".encode(),
        container=container,
        render_batch_sha256=hashlib.sha256(b"render batch").digest(),
        nav_envelope_sha256=hashlib.sha256(b"navigation envelope").digest(),
        receipt={"stage": "baked_tile", "made_for": label},
    )
    return key, outcome


def _scratch(admin: psycopg.Connection) -> str:
    row = admin.execute("select current_schema()").fetchone()
    assert row is not None
    return str(row["current_schema"])


def _baked_rows(admin: psycopg.Connection) -> dict[str, str]:
    """Every ``baked_tile`` row, whole, by key."""
    return {
        str(row["baked_tile_id"]): row["whole"]
        for row in admin.execute(
            "select baked_tile_id, to_jsonb(t.*)::text as whole from baked_tile t"
        ).fetchall()
    }


def _runtime(scratch: str, workspace: uuid.UUID) -> psycopg.Connection:
    """A connection as the runtime role, in autocommit, idle between statements as a route is."""
    connection = psycopg.connect(app_role_dsn(scratch), autocommit=True, row_factory=dict_row)
    connection.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
    return connection


@pytest.fixture(scope="module")
def exported(tmp_path_factory) -> Iterator[Exported]:
    root = tmp_path_factory.mktemp("source")
    with migrated_schema() as (_psycopg, admin), pytest.MonkeyPatch.context() as patch:
        admin.row_factory = dict_row
        scratch = _scratch(admin)
        provision_runtime_role(admin, role=APP_ROLE)
        workspace, actor = uuid.uuid4(), uuid.uuid4()
        admin.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
        provision_workspace(admin, workspace)
        declare_tile_quota(admin, workspace, tiles_limit=_TILES_LIMIT, declared_by=actor)

        # The town is made as `POST /worlds/generated` makes one, with the catalog's most
        # candidates so an identity none of the preset's candidates generate is not a refusal
        # this test did not ask for.
        recipe = dataclasses.replace(town_recipe(_RECIPE), candidates=CANDIDATES_MAXIMUM)
        world_id = new_world_id(GENERATED)
        composed = compose_generated_world(recipe, world_id)
        with admin.transaction():
            snapshot_id, _style, _version = create_generated_authorities(
                admin,
                workspace_id=workspace,
                actor=actor,
                title="A judged town",
                recipe=recipe,
                composed=composed,
            )
        admin.commit()

        tiles = tile_store(root)
        patch.setattr(GeneratedTileBaker, "_bake", _stand_in_bake)
        outcomes = _baker(admin, scratch, tiles, root).drain([workspace])
        assert [outcome.status for outcome in outcomes] == ["baked"] * len(recipe.tiles)

        repository = BakedTileRepository(connection=admin, store=tiles)
        served, _ = _record_ledger_tile(repository, "served", 1, b"a tile the workspace is served")
        unreached_bytes = b"a tile nobody in this workspace reaches"
        unreached, _ = _record_ledger_tile(repository, "unreached", 2, unreached_bytes)
        admin.commit()

        with _runtime(scratch, workspace) as runtime:
            delivered = BakedTileRepository(connection=runtime, store=tiles).serve(
                workspace, served
            )
            assert delivered.charged is True
            town_tiles = generated_tiles(runtime, workspace, world_id, snapshot_id)
            assert {tile.state for tile in town_tiles} == {"baked"}
            town = {
                tile.baked_tile_id: BakedTileRepository(connection=runtime, store=tiles)
                .serve_to_its_world(tile.baked_tile_id)
                .data
                for tile in town_tiles
                if tile.baked_tile_id is not None
            }
        assert len(town) == len(recipe.tiles)

        archive = tmp_path_factory.mktemp("seed") / "archive"
        manifest = export_seed(
            admin,
            LocalContentAddressedStore(root / "blobs"),
            workspace_id=workspace,
            destination=archive,
            created_at=_CREATED_AT,
            tiles=tiles,
        )
        yield Exported(
            archive=archive,
            manifest=manifest,
            workspace=workspace,
            world_id=world_id,
            snapshot_id=snapshot_id,
            town=town,
            served=served,
            served_bytes=delivered.data,
            unreached=unreached,
            unreached_bytes=unreached_bytes,
        )


def _files(manifest: SeedManifest) -> dict[str, str]:
    return {str(value["table"]): name for name, value in manifest.rows.items()}


def test_the_seed_carries_exactly_the_baked_tiles_the_workspace_reaches(exported):
    """The town's tiles and the served one, with their bytes; not the tile nobody here reaches."""
    files = _files(exported.manifest)
    # Row files are named in load order, so the ledger's foreign key finds its tile loaded first.
    assert files["baked_tile"] < files["workspace_baked_tile"]
    carried = (exported.archive / "rows" / files["baked_tile"]).read_bytes()
    assert exported.manifest.rows[files["baked_tile"]]["rows"] == len(exported.town) + 1
    for key in [*exported.town, exported.served]:
        assert str(key).encode() in carried
    assert str(exported.unreached).encode() not in carried

    held = {key.rsplit("/", 1)[-1] for key in exported.manifest.tiles}
    wanted = {hashlib.sha256(data).hexdigest() for data in exported.town.values()}
    wanted.add(hashlib.sha256(exported.served_bytes).hexdigest())
    assert held == wanted
    for key, recorded in exported.manifest.tiles.items():
        payload = (exported.archive / "tiles" / key).read_bytes()
        assert (hashlib.sha256(payload).hexdigest(), len(payload)) == (
            recorded["sha256"],
            recorded["bytes"],
        )


def test_a_restored_seed_serves_its_generated_world_s_tiles_with_no_bake_worker(exported, tmp_path):
    """Restored into a fresh database and an empty data directory, the town reads as baked and
    every tile is served with the bytes the source served, to the runtime role."""
    data = tmp_path / "data"
    blobs, tiles = LocalContentAddressedStore(data / "blobs"), tile_store(data)
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        scratch = _scratch(admin)
        landed = restore_seed(admin, blobs, archive=exported.archive, tiles=tiles)
        assert landed.tiles == exported.manifest.tiles
        verify_restored(admin, blobs, exported.manifest, tiles=tiles)
        provision_runtime_role(admin, role=APP_ROLE)
        admin.commit()

        with _runtime(scratch, exported.workspace) as runtime:
            restored = generated_tiles(
                runtime, exported.workspace, exported.world_id, exported.snapshot_id
            )
            assert [(tile.state, tile.baked_tile_id) for tile in restored] == [
                ("baked", key) for key in exported.town
            ]
            repository = BakedTileRepository(connection=runtime, store=tiles)
            for key, served in exported.town.items():
                assert repository.serve_to_its_world(key).data == served
            again = repository.serve(exported.workspace, exported.served)
            # The ledger row travelled, so serving the tile again costs the workspace nothing.
            assert (again.data, again.charged) == (exported.served_bytes, False)


def test_a_reset_keeps_an_identical_baked_tile_puts_back_a_missing_one_and_refuses_another(
    exported, tmp_path
):
    data = tmp_path / "data"
    blobs, tiles = LocalContentAddressedStore(data / "blobs"), tile_store(data)
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        admin.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(exported.workspace),)
        )
        restore_seed(admin, blobs, archive=exported.archive, tiles=tiles)
        admin.commit()
        held = _baked_rows(admin)

        reset_to_seed(admin, archive=exported.archive, tiles=tiles)
        admin.commit()
        assert _baked_rows(admin) == held

        first = next(iter(exported.town))
        admin.execute("delete from baked_tile where baked_tile_id = %s", (first,))
        admin.commit()
        reset_to_seed(admin, archive=exported.archive, tiles=tiles)
        admin.commit()
        assert _baked_rows(admin) == held
        town = generated_tiles(admin, exported.workspace, exported.world_id, exported.snapshot_id)
        assert [(tile.state, tile.baked_tile_id) for tile in town] == [
            ("baked", key) for key in exported.town
        ]

        # The stack's copy of the served tile is rebaked into other bytes, which migration 0072
        # marks as a fault. The archive's row is no longer the stack's, and the reset says which.
        _key, outcome = _record_ledger_tile(
            BakedTileRepository(connection=admin, store=tiles),
            "served",
            1,
            b"other bytes under the served tile's key",
            key=exported.served,
        )
        assert outcome == "nondeterminism_detected"
        admin.commit()
        with pytest.raises(SeedRefused) as refusal:
            reset_to_seed(admin, archive=exported.archive, tiles=tiles)
        assert str(exported.served) in str(refusal.value)
        admin.rollback()


def test_an_archive_of_format_1_is_refused_by_name(exported, tmp_path):
    """Format 1 carried no baked tiles. Its archive is refused for that by both paths a restore
    reads a manifest through, before any row file, blob or tile of it is read or anything is
    written, rather than restored into a stack whose town never draws."""
    earlier = tmp_path / "format-1"
    shutil.copytree(exported.archive, earlier)
    shutil.rmtree(earlier / "tiles")
    document = json.loads((earlier / "manifest.json").read_bytes())
    document["seed_format_version"] = 1
    del document["tiles"]
    del document["totals"]["tiles"]
    del document["totals"]["tile_bytes"]
    payload = canonical_json(document)
    (earlier / "manifest.json").write_bytes(payload)
    (earlier / "manifest.sha256").write_text(
        f"{hashlib.sha256(payload).hexdigest()}  manifest.json\n", encoding="utf-8"
    )
    for read in (read_manifest, verify_seed):
        with pytest.raises(SeedRefused) as refusal:
            read(earlier)
        message = str(refusal.value)
        assert "seed format 1" in message
        assert "carries no baked tiles" in message
