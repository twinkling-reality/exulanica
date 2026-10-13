"""V2 admission is additive over populated storage; v1 data and identity gates survive."""

from __future__ import annotations

import copy
import json
import uuid

import psycopg
import pytest
from exulanica.migrations import migrations
from exulanica.world.composers import site_plan
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.repository import WorkspaceKinds
from exulanica.world.kinds.samples import check_samples
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import pg_harness
from kind_briefs import fixture_kind
from test_kind_requirements import compile_, farm
from test_society_made_world import made as imported_made  # noqa: F401
from world_support import historical_world_fixture_schema

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def test_populated_v1_storage_upgrades_without_rewriting_and_keeps_v2(monkeypatch):
    every = list(migrations())
    [upgrade] = [m for m in every if m.version == "0198"]
    monkeypatch.setattr(
        pg_harness, "migrations", lambda: iter(m for m in every if m.version < "0198")
    )
    with pg_harness.migrated_schema() as (_, connection):
        connection.autocommit = True
        connection.row_factory = dict_row
        workspace = uuid.uuid4()
        actor = uuid.uuid4()
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
        )
        repository = WorkspaceKinds(connection, workspace)
        old = read_kind(fixture_kind("cafe"))
        with historical_world_fixture_schema(connection, erasure=False, kinds=True):
            repository.append(old, check_samples(old), created_by=actor)
        before = connection.execute(
            "select to_jsonb(k) as row from world_kind_version k"
        ).fetchall()
        new = read_kind(compile_(farm(), size=True).document)
        report = check_samples(new)
        with (
            historical_world_fixture_schema(connection, erasure=False, kinds=True),
            pytest.raises(psycopg.errors.CheckViolation) as error,
        ):
            repository.append(new, report, created_by=actor)
        assert error.value.diag.constraint_name == "world_kind_version_names_itself"
        connection.execute(upgrade.sql)
        assert (
            connection.execute("select to_jsonb(k) as row from world_kind_version k").fetchall()
            == before
        )
        with historical_world_fixture_schema(connection, erasure=False, kinds=True):
            repository.append(new, report, created_by=actor)
        rows = connection.execute(
            "select document,document_sha256 from world_kind_version order by kind"
        ).fetchall()
        assert {r["document"]["profile"] for r in rows} == {
            "exulanica.world-kind/v1",
            "exulanica.world-kind/v2",
        }
        for row in rows:
            kept = read_kind(row["document"])
            assert kept.sha256 == row["document_sha256"]
            made = site_plan.compose_kind(
                kept, kept.values(kept.presets[0][0]), "world:generated:kept"
            )
            assert site_plan.records(json.loads(json.dumps(made.receipt))) == made.records

        for change in (
            {"profile": "exulanica.world-kind/v99"},
            {"profile": None},
            {"kind": "other_kind"},
            {"version": 99},
            {"origin": "uploaded"},
        ):
            document = copy.deepcopy(dict(new.document))
            document.update(change)
            # Separate workspace avoids uniqueness masking an identity-check failure.
            ws = uuid.uuid4()
            connection.execute("select set_config('exulanica.workspace_id', %s, false)", (str(ws),))
            with connection.transaction(), pytest.raises(psycopg.errors.CheckViolation) as refused:
                connection.execute(
                    "insert into world_kind_version (workspace_id,kind,version,document_sha256,"
                    "document,origin,validation,created_by) values (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        ws,
                        new.kind,
                        new.version,
                        new.sha256,
                        Jsonb(document),
                        new.origin,
                        Jsonb(report),
                        actor,
                    ),
                )
            assert refused.value.diag.constraint_name == "world_kind_version_names_itself"


def test_uploaded_v2_kind_is_kept_and_its_world_receipt_replays(made):
    api = made
    document = compile_(farm(), size=True).document
    document.update(origin="uploaded", provenance={"by": "a test creator"})
    response = api.post("/worlds/kinds", {"document": document})
    assert response.status_code == 201, response.text
    kept = response.json()
    assert kept["validation"]["kind"]["profile"] == "exulanica.world-kind/v2"
    response = api.post(
        f"/worlds/kinds/{document['kind']}/worlds",
        {"preset": document["presets"][0]["key"], "title": "Farm"},
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    path = f"/world/versions/{entry['authored_version_id']}/site?world_id={entry['world_id']}"
    drawn = api.get(path)
    assert drawn.status_code == 200, drawn.text
    assert drawn.json()["kind"]["kind"] == document["kind"]
    with api.database.session(api.repository.workspace_id) as connection:
        _digest, receipt = generation_receipt(
            connection,
            api.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
        )
    for key in ("profile", "parts", "requirement_source", "requirements"):
        assert receipt["kind"]["document"][key] == document[key]
    assert receipt["kind"]["sha256"] == kept["kind"]["sha256"]
    records = site_plan.records(receipt)
    assert records and read_kind(receipt["kind"]["document"]).sha256 == receipt["kind"]["sha256"]
