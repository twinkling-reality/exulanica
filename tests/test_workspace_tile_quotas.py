"""Per-workspace tile quotas, refused through a real request and held by the table itself.

No on-demand tile route exists, and none may until this floor does, so the request half mounts one
probe route onto the real application for the length of this module and declares it the way a
tile route will be declared: ``world.read`` plus ``tiles.materialise``. Everything the request
passes through is production code: the application-level dependency, the token directory, the
workspace-scoped connection as a non-owner role, the quota table under row-level security, and the
error map. The probe route is the only thing here that does not ship.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

import psycopg
import pytest
from exulanica.api import permissions
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.permissions import ROUTE_RULES, Permission, Requires
from exulanica.api.quotas import (
    TileQuota,
    TileQuotaExceeded,
    TileQuotaUndeclared,
    charge_tiles,
    declare_tile_quota,
    read_tile_quota,
)
from exulanica.api.services import Services
from exulanica.canonical import canonical_json
from exulanica.db.roles import provision_runtime_role
from exulanica.db.session import Database
from exulanica.errors import CanonicalisationError
from exulanica.store.local import LocalContentAddressedStore
from fastapi import APIRouter
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from pg_harness import migrated_schema
from test_route_permissions import ALL_PERMISSIONS, APP_ROLE, app_role_dsn

pytestmark = pytest.mark.postgres

PROBE_PATH = "/tiles-probe/{tile_key}"
PROBE_RULE = Requires(frozenset({Permission.WORLD_READ, Permission.TILES_MATERIALISE}))

_probe = APIRouter()


@_probe.get(PROBE_PATH)
def _materialise(tile_key: str) -> dict[str, str]:
    """Stands in for a tile route. It runs only if the charge before it succeeded."""
    _materialised.append(tile_key)
    return {"tile_key": tile_key}


_materialised: list[str] = []


@dataclass
class Quotas:
    client: TestClient
    dsn: str
    workspaces: dict[str, uuid.UUID]
    tokens: dict[str, str]

    def get(self, who: str, tile_key: str):
        return self.client.get(
            f"/tiles-probe/{tile_key}", headers={"Authorization": f"Bearer {self.tokens[who]}"}
        )

    def connect(self, workspace: str) -> psycopg.Connection:
        connection = psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row)
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, false)",
            (str(self.workspaces[workspace]),),
        )
        return connection


GRANTS = {
    # Workspace "limited" has a ceiling of two tiles.
    "limited": ("limited", ALL_PERMISSIONS),
    # Workspace "undeclared" never gets a quota row.
    "undeclared": ("undeclared", ALL_PERMISSIONS),
    # Same workspace as "limited", without the tile permission.
    "viewer": ("limited", ["world.read"]),
    # A roomy workspace, for the row-level security and trigger checks.
    "roomy": ("roomy", ALL_PERMISSIONS),
}


@pytest.fixture(scope="module")
def quotas(tmp_path_factory) -> Iterator[Quotas]:
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        scratch = admin.execute("select current_schema()").fetchone()["current_schema"]
        provision_runtime_role(admin, role=APP_ROLE)
        admin.commit()
        workspaces = {name: uuid.uuid4() for name in ("limited", "undeclared", "roomy")}
        tokens = {who: f"{who}-tile-token-{uuid.uuid4().hex}" for who in GRANTS}
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
            store=LocalContentAddressedStore(tmp_path_factory.mktemp("tiles") / "blobs"),
            tokens=directory,
            executor_shares_the_write_role=True,
            model_client=None,
        )
        app = create_app(services, verify=False)
        app.include_router(_probe)
        declared = MappingProxyType({**ROUTE_RULES, ("GET", PROBE_PATH): PROBE_RULE})
        with pytest.MonkeyPatch.context() as patch, TestClient(app) as client:
            patch.setattr(permissions, "ROUTE_RULES", declared)
            harness = Quotas(client=client, dsn=dsn, workspaces=workspaces, tokens=tokens)
            with harness.connect("limited") as connection:
                declare_tile_quota(
                    connection, workspaces["limited"], tiles_limit=2, declared_by=uuid.uuid4()
                )
            with harness.connect("roomy") as connection:
                declare_tile_quota(
                    connection, workspaces["roomy"], tiles_limit=1000, declared_by=uuid.uuid4()
                )
            yield harness


def test_a_real_request_is_refused_once_the_workspace_quota_is_spent(quotas):
    _materialised.clear()
    assert quotas.get("limited", "t-1").status_code == 200
    assert quotas.get("limited", "t-2").status_code == 200
    refused = quotas.get("limited", "t-3")
    assert refused.status_code == 429, refused.text
    assert refused.json()["code"] == "tile_quota_exceeded"
    assert "Do not retry" in refused.json()["detail"]
    # The route never ran for the refused request: the charge precedes it.
    assert _materialised == ["t-1", "t-2"]
    with quotas.connect("limited") as connection:
        quota = read_tile_quota(connection, quotas.workspaces["limited"])
    assert quota == TileQuota(quotas.workspaces["limited"], tiles_limit=2, tiles_used=2)
    # Raising the ceiling is what lets the next request through, and only the next one.
    with quotas.connect("limited") as connection:
        declare_tile_quota(
            connection, quotas.workspaces["limited"], tiles_limit=3, declared_by=uuid.uuid4()
        )
    assert quotas.get("limited", "t-4").status_code == 200
    assert quotas.get("limited", "t-5").status_code == 429


def test_a_workspace_with_no_declared_quota_materialises_nothing(quotas):
    _materialised.clear()
    refused = quotas.get("undeclared", "t-1")
    assert (refused.status_code, refused.json()["code"]) == (429, "tile_quota_undeclared")
    assert _materialised == []
    with quotas.connect("undeclared") as connection:
        assert read_tile_quota(connection, quotas.workspaces["undeclared"]) is None


def test_the_permission_is_checked_before_the_quota_is_touched(quotas):
    with quotas.connect("limited") as connection:
        before = read_tile_quota(connection, quotas.workspaces["limited"])
    refused = quotas.get("viewer", "t-1")
    assert (refused.status_code, refused.json()["code"]) == (404, "unknown_reference")
    with quotas.connect("limited") as connection:
        assert read_tile_quota(connection, quotas.workspaces["limited"]) == before


def test_a_route_without_the_tile_permission_is_never_charged(quotas):
    with quotas.connect("roomy") as connection:
        before = read_tile_quota(connection, quotas.workspaces["roomy"])
    headers = {"Authorization": f"Bearer {quotas.tokens['roomy']}"}
    assert quotas.client.get("/world/styles/catalog", headers=headers).status_code == 200
    with quotas.connect("roomy") as connection:
        assert read_tile_quota(connection, quotas.workspaces["roomy"]) == before


def test_the_table_holds_the_ceiling_even_when_the_function_is_bypassed(quotas):
    workspace = quotas.workspaces["roomy"]
    with quotas.connect("roomy") as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "update workspace_tile_quota set tiles_used = tiles_limit + 1 "
                "where workspace_id = %s",
                (workspace,),
            )
        charge_tiles(connection, workspace, 3)
        with pytest.raises(psycopg.errors.CheckViolation, match="never falls"):
            connection.execute(
                "update workspace_tile_quota set tiles_used = 0 where workspace_id = %s",
                (workspace,),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            declare_tile_quota(connection, workspace, tiles_limit=1, declared_by=uuid.uuid4())
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "delete from workspace_tile_quota where workspace_id = %s", (workspace,)
            )
    with quotas.connect("undeclared") as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="starts with nothing used"):
            connection.execute(
                "insert into workspace_tile_quota (workspace_id, tiles_limit, tiles_used, "
                "declared_by) values (%s, 10, 5, %s)",
                (quotas.workspaces["undeclared"], uuid.uuid4()),
            )
        assert read_tile_quota(connection, quotas.workspaces["undeclared"]) is None


def test_the_app_role_reads_and_writes_only_its_own_workspace_quota(quotas):
    """Provisioning reaches the new table with no change to roles.py, and the policy holds."""
    with quotas.connect("roomy") as connection:
        assert (
            connection.execute("select count(*) as n from workspace_tile_quota").fetchone()["n"]
            == 1
        )
        # Naming another workspace fails closed in the guard's first statement.
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="workspace context"):
            connection.execute(
                "insert into workspace_tile_quota (workspace_id, tiles_limit, declared_by) "
                "values (%s, 5, %s)",
                (quotas.workspaces["undeclared"], uuid.uuid4()),
            )
        # And the other workspaces' rows are invisible rather than refused.
        assert (
            connection.execute(
                "update workspace_tile_quota set tiles_limit = tiles_limit + 1 "
                "where workspace_id = %s returning 1",
                (quotas.workspaces["limited"],),
            ).fetchone()
            is None
        )


def test_charging_needs_a_whole_positive_number_of_tiles(quotas):
    workspace = quotas.workspaces["roomy"]
    with quotas.connect("roomy") as connection:
        for bad in (0, -1):
            with pytest.raises(ValueError):
                charge_tiles(connection, workspace, bad)
        for bad in (1.0, True, Decimal(1), "1"):
            with pytest.raises(TypeError):
                charge_tiles(connection, workspace, bad)  # type: ignore[arg-type]


def test_refusals_are_quota_errors_that_name_what_happened(quotas):
    with (
        quotas.connect("undeclared") as connection,
        pytest.raises(TileQuotaUndeclared, match="no declared tile quota"),
    ):
        charge_tiles(connection, quotas.workspaces["undeclared"], 1)
    with (
        quotas.connect("limited") as connection,
        pytest.raises(TileQuotaExceeded, match="Nothing was materialised"),
    ):
        charge_tiles(connection, quotas.workspaces["limited"], 10_000)


# -- integers only, and no clock ------------------------------------------------------------


def test_the_quota_document_is_integers_and_canonical():
    quota = TileQuota(uuid.UUID(int=7), tiles_limit=5, tiles_used=2)
    document = quota.document()
    assert document == {
        "workspace_id": str(uuid.UUID(int=7)),
        "tiles_limit": 5,
        "tiles_used": 2,
        "tiles_remaining": 3,
    }
    assert canonical_json(document) == (
        b'{"tiles_limit":5,"tiles_remaining":3,"tiles_used":2,'
        b'"workspace_id":"00000000-0000-0000-0000-000000000007"}'
    )


def test_a_float_cannot_become_a_quota():
    with pytest.raises(TypeError):
        TileQuota(uuid.UUID(int=7), tiles_limit=5.0, tiles_used=0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        TileQuota(uuid.UUID(int=7), tiles_limit=5, tiles_used=0.0)  # type: ignore[arg-type]
    with pytest.raises(CanonicalisationError):
        canonical_json({"tiles_limit": 5.0})


def test_no_clock_reaches_the_quota_document():
    """Two readings of the same counters are the same document, whenever they are taken."""
    first = TileQuota(uuid.UUID(int=9), tiles_limit=4, tiles_used=1).document()
    second = TileQuota(uuid.UUID(int=9), tiles_limit=4, tiles_used=1).document()
    assert canonical_json(first) == canonical_json(second)
    assert set(first) == {"workspace_id", "tiles_limit", "tiles_used", "tiles_remaining"}
