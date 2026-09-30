"""A judge opens the world a prepared seed carries, and nothing has to be written for it.

The judge deployment's API connects as ``exulanica_judge``, which may not write
``world_identity``. The page lists the workspace's saved world entries and, finding none, asks for
an authored starter, whose world is a new ``world_identity`` row, so on a judge stack a seed that
carries the world and no entry opens for nobody. ``prepare_sandbox_world`` therefore saves the
entry, and these tests hold what that is for, end to end:

*   A workspace prepared as ``scripts/seed_workspace.py prepare`` prepares one, exported, and
    restored into a freshly migrated database and an empty data directory as the judge stack's
    seeding job restores one, lists exactly its one saved entry to the API connecting as the judge
    role under a judge token, and every read the page makes to open that world answers 200.
*   The judge places an object in that world as the page does, bound to the entry, and the edit
    advances the entry, which is why the judge role may write ``saved_world_entry``.
*   Preparing the workspace again saves no second entry.
*   The control: the same seed without its entry lists nothing to the judge, and the starter the
    page would ask for next is not made.

The role is suffixed for the reason ``tests/test_judge_seed.py`` gives: a role is a CLUSTER object,
and provisioning the deployment's own ``exulanica_judge`` would rewrite a developer's live grants.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.migrate import provision_workspace
from exulanica.db.session import Database
from exulanica.env import env_get
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.orchestration.judge_seed import (
    JUDGE_ROLE,
    export_seed,
    mint_judge_token,
    provision_judge_role,
    restore_seed,
)
from exulanica.orchestration.reference_world import compose_reference_sources
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import tile_store
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from conftest import write_photo
from pg_harness import migrated_schema, open_scratch_connection

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import seed_workspace

pytestmark = pytest.mark.postgres

#: Suffixed, because a role is a CLUSTER object. See the module docstring.
_JUDGE_ROLE: Final = f"{JUDGE_ROLE}_opens"
_CREATED_AT: Final = "2026-09-29T00:00:00Z"
#: The photographs the personal-source world is composed from: three, as
#: ``tests/test_world_bootstrap.py`` composes it, each its own width so each is its own bytes.
_PHOTOGRAPH_WIDTHS: Final = (160, 161, 162)
_PHOTOGRAPH_HEIGHT: Final = 100
_REGION: Final = "region-a"
#: The composition records its manifest's SHA-256 and reads nothing else of it, so any 64 hex
#: characters serve.
_MANIFEST_SHA256: Final = "ab" * 32
#: Where the judge places an object: the region's origin, unturned, at the asset's own size (a
#: scale of one thousand thousandths).
_PLACED_AT: Final = {"x_mm": 0, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0, "scale_milli": 1_000}


@dataclasses.dataclass(frozen=True)
class Seeds:
    """One prepared source workspace, exported twice: as prepared, and without its entry."""

    workspace: uuid.UUID
    world_id: str
    #: What ``prepare_workspace`` returned the first time and the second.
    prepared: dict[str, Any]
    again: dict[str, Any]
    #: The source's saved entries for the world after both runs.
    entries_after_both: int
    archive: Path
    entryless: Path


def _owner_connection(scratch: str) -> psycopg.Connection:
    """The owner, in a transaction, as the script connects to the database it prepares."""
    base = env_get("TEST_DATABASE_URL")
    assert base is not None
    return psycopg.connect(
        make_conninfo(base, options=f"-csearch_path={scratch},public"), row_factory=dict_row
    )


def _export(admin: psycopg.Connection, root: Path, workspace: uuid.UUID, into: Path) -> Path:
    export_seed(
        admin,
        LocalContentAddressedStore(root / "blobs"),
        workspace_id=workspace,
        destination=into,
        created_at=_CREATED_AT,
        tiles=tile_store(root),
    )
    return into


@pytest.fixture(scope="module")
def seeds(tmp_path_factory) -> Iterator[Seeds]:
    root = tmp_path_factory.mktemp("source")
    photographs = tmp_path_factory.mktemp("photographs")
    with migrated_schema() as (psycopg_module, admin):
        admin.row_factory = dict_row
        scratch = admin.execute("select current_schema()").fetchone()["current_schema"]
        workspace = uuid.uuid4()
        admin.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
        provision_workspace(admin, workspace)
        admin.commit()

        # The personal-source world, from photographs ingested and composed as the product does.
        repository = IngestRepository(open_scratch_connection(psycopg_module, scratch), workspace)
        pipeline = PhotoIngestPipeline(
            repository, LocalContentAddressedStore(root / "blobs"), vision=None
        )
        for width in _PHOTOGRAPH_WIDTHS:
            photograph = write_photo(
                photographs, f"source-{width}.jpg", size=(width, _PHOTOGRAPH_HEIGHT)
            )
            assert pipeline.ingest_file(photograph).error is None
        rows = repository.connection.execute(
            "select capture_id, blob_sha256 from capture where workspace_id = %s "
            "order by capture_id",
            (workspace,),
        ).fetchall()
        world_id = compose_reference_sources(
            repository,
            region_id=_REGION,
            source_manifest_sha256=_MANIFEST_SHA256,
            captures=[
                (row["capture_id"], bytes(row["blob_sha256"]).hex(), str(index))
                for index, row in enumerate(rows)
            ],
            actor=uuid.uuid4(),
        )["world_id"]
        repository.connection.close()

        # What `seed_workspace.py prepare` runs once its copy is made, twice.
        with _owner_connection(scratch) as connection:
            prepared = seed_workspace.prepare_workspace(connection, workspace)
        with _owner_connection(scratch) as connection:
            again = seed_workspace.prepare_workspace(connection, workspace)
        entries_after_both = admin.execute(
            "select count(*) as n from saved_world_entry where workspace_id = %s and world_id = %s",
            (workspace, world_id),
        ).fetchone()["n"]

        archive = _export(admin, root, workspace, tmp_path_factory.mktemp("seed") / "archive")
        # The control: the same workspace as a prepare that saved no entry left it.
        admin.execute("delete from saved_world_entry where workspace_id = %s", (workspace,))
        admin.commit()
        entryless = _export(
            admin, root, workspace, tmp_path_factory.mktemp("entryless") / "archive"
        )
        yield Seeds(
            workspace=workspace,
            world_id=world_id,
            prepared=prepared,
            again=again,
            entries_after_both=entries_after_both,
            archive=archive,
            entryless=entryless,
        )


@contextlib.contextmanager
def _judge_stack(archive: Path, workspace: uuid.UUID, data: Path) -> Iterator[TestClient]:
    """A fresh stack brought up from ``archive`` as the judge deployment brings one up, and its API
    connecting as the judge role, holding one judge token. The client sends that token."""
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        scratch = admin.execute("select current_schema()").fetchone()["current_schema"]
        # `exulanica-seed role`, then `exulanica-seed restore`, in the compose file's order.
        provision_judge_role(admin, role=_JUDGE_ROLE)
        admin.commit()
        blobs = LocalContentAddressedStore(data / "blobs")
        restore_seed(admin, blobs, archive=archive, tiles=tile_store(data))
        admin.commit()

        base = env_get("TEST_DATABASE_URL")
        assert base is not None
        judge = Database(
            url=make_conninfo(base, user=_JUDGE_ROLE, options=f"-csearch_path={scratch},public")
        )
        with judge.unscoped() as probe:
            assert probe.execute("select current_user as who").fetchone()["who"] == _JUDGE_ROLE
        token = f"judge-{uuid.uuid4().hex}{uuid.uuid4().hex}"
        directory = mint_judge_token(workspace_id=workspace, actor=uuid.uuid4(), token=token)
        services = Services(
            database=judge,
            readonly_database=judge,
            store=blobs,
            tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(directory)}),
            executor_shares_the_write_role=True,
            model_client=None,
        )
        # A refused write answers whatever it answers rather than raising into the test.
        with TestClient(
            create_app(services, verify=False), raise_server_exceptions=False
        ) as client:
            client.headers["Authorization"] = f"Bearer {token}"
            yield client


def _ok(client: TestClient, path: str, **params: str) -> Any:
    response = client.get(path, params=params)
    assert response.status_code == 200, (path, response.status_code, response.text)
    return response.json()


def test_preparing_saves_the_sandbox_world_s_entry_once(seeds):
    """The entry names the version the bootstrap opened, and a second run reuses it."""
    assert seeds.prepared["entry"] == "created"
    assert seeds.again["entry"] == "reused"
    assert seeds.again["entry_id"] == seeds.prepared["entry_id"]
    assert seeds.again["version_id"] == seeds.prepared["version_id"]
    assert seeds.entries_after_both == 1


def test_the_judge_opens_the_seeded_world_with_no_starter(seeds, tmp_path):
    """Every read the page makes to open a lone saved world, as the judge, each answering 200.

    In the page's order: ``openAppSession`` reads the graph and the saved entries, and with one
    available entry opens it without asking for a starter; ``openWorldEntryContext`` connects the
    entry's style, its interaction settings and its source media; ``mountSessionGeometry`` reads the
    geometry list and the entry's authored version.
    """
    with _judge_stack(seeds.archive, seeds.workspace, tmp_path / "data") as client:
        _ok(client, "/graph")
        listed = _ok(client, "/world-entries")
        assert [entry["entry_id"] for entry in listed] == [seeds.prepared["entry_id"]]
        (entry,) = listed
        # `automaticWorldEntry`: one entry, available, so the page opens it and never asks for a
        # starter, which the judge role could not make.
        assert entry["availability"] == "available"
        assert entry["world_id"] == seeds.world_id
        assert entry["source_kind"] == "personal"
        assert entry["authored_version_id"] == seeds.prepared["version_id"]
        assert _ok(client, f"/world-entries/{entry['entry_id']}") == entry

        world = {"world_id": seeds.world_id}
        _ok(client, "/world/styles/catalog")
        current = _ok(client, "/world/styles/current", **world)
        assert current["current"]["version_id"] == entry["style_version_id"]
        versions = _ok(client, "/world/styles/versions", **world)
        assert entry["style_version_id"] in {version["version_id"] for version in versions}
        _ok(client, "/world/interactions/current", **world)
        _ok(client, "/graph/sources")
        _ok(
            client,
            "/world/source-media",
            **world,
            source_snapshot_id=entry["source_snapshot_id"],
        )
        _ok(client, "/geometry")
        version = _ok(client, f"/world/versions/{entry['authored_version_id']}", **world)
        assert version["version_id"] == entry["authored_version_id"]


def test_the_judge_edits_the_opened_world_through_its_saved_entry(seeds, tmp_path):
    """A reviewed object placed as the page places one in a world it opened from a saved entry:
    bound to that entry, which the edit advances to the version it made, so the page's next edit
    is bound to the entry as it now is."""
    with _judge_stack(seeds.archive, seeds.workspace, tmp_path / "data") as client:
        (entry,) = _ok(client, "/world-entries")
        world = {"world_id": seeds.world_id}
        version = _ok(client, f"/world/versions/{entry['authored_version_id']}", **world)
        asset = min(
            (
                asset
                for asset in _ok(client, "/world/assets")
                if asset["placeable"] and asset["availability"] == "available"
            ),
            key=lambda asset: asset["asset_key"],
        )
        placed = client.post(
            f"/world/versions/{entry['authored_version_id']}/objects",
            params=world,
            json={
                "object_id": "object:judge-placed",
                "asset_sha256": asset["content_sha256"],
                "region_id": _REGION,
                "transform": _PLACED_AT,
                "origin_role": "fictional",
                "behaviour": None,
                "base_state_sha256": version["state_sha256"],
                "saved_entry": {
                    "entry_id": entry["entry_id"],
                    "base_revision": entry["revision"],
                    "authored_state_sha256": entry["authored_state_sha256"],
                    "authored_edit_seq": entry["authored_edit_seq"],
                },
            },
        )
        assert placed.status_code == 201, placed.text
        edited = placed.json()
        assert edited["edit_seq"] > entry["authored_edit_seq"]
        advanced = _ok(client, f"/world-entries/{entry['entry_id']}")
        assert advanced["revision"] == entry["revision"] + 1
        assert (advanced["authored_state_sha256"], advanced["authored_edit_seq"]) == (
            edited["state_sha256"],
            edited["edit_seq"],
        )
        assert advanced["availability"] == "available"


def test_control_a_seed_without_its_entry_opens_nothing_for_the_judge(seeds, tmp_path):
    """Without the entry the judge lists nothing, and the starter the page asks for next is not
    made, which is the page's "Your world did not open"."""
    with _judge_stack(seeds.entryless, seeds.workspace, tmp_path / "data") as client:
        assert _ok(client, "/world-entries") == []
        starter = client.post("/world-entries/starter", json={"title": "My world"})
        assert not starter.is_success, starter.text
        assert _ok(client, "/world-entries") == []
