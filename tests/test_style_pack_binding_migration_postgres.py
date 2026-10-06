"""Migration 0141 over rows written before it, and the checks it adds.

Every proposal, preview and version written before 0141 stands as it was: the new columns read null
on each earlier row, which names no pack. After it, a version names a whole pack or none, and a
proposal's request is either absent or ``{"pack": ...}``; the database refuses anything between.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.migrations import migrations
from exulanica.world import ProposalOrigin, StylePackBinding, WorldStyleRepository
from psycopg.rows import dict_row

import pg_harness
from test_world_style_postgres import proposal, topology
from world_support import registered_world

pytestmark = pytest.mark.postgres

TABLES = ("world_style_proposal", "world_style_version", "world_style_preview")
NEW_COLUMNS = {"style_pack", "style_pack_id", "style_pack_version", "style_pack_manifest_sha256"}
COZY = Path(__file__).resolve().parents[1] / "assets/style-packs/packs/exulanica.cozy-town"


def _copy_version(connection, source, **pack):
    """Insert a copy of version ``source`` as the next revision, naming ``pack``'s columns."""
    columns = ",".join(sorted(pack))
    values = ",".join(f"%({name})s" for name in sorted(pack))
    connection.execute(
        "insert into world_style_version (version_id,workspace_id,world_id,revision,"
        "parent_version_id,topology_digest,global_profile_id,global_profile_version,"
        "global_parameters,origin,actor,origin_reference,provenance_schema_version,"
        f"recipe_binding,capability_mapping,{columns}) "
        "select %(id)s,workspace_id,world_id,(select max(revision)+1 from world_style_version),"
        "version_id,topology_digest,global_profile_id,global_profile_version,global_parameters,"
        "'user',%(actor)s,null,1,recipe_binding,capability_mapping,"
        f"{values} from world_style_version where version_id=%(source)s",
        {"id": uuid.uuid4(), "actor": uuid.uuid4(), "source": source, **pack},
    )


def test_earlier_style_rows_stand_and_the_new_checks_refuse_half_a_pack(monkeypatch):
    every = list(migrations())
    [packs] = [item for item in every if item.version == "0141"]
    monkeypatch.setattr(
        pg_harness, "migrations", lambda: iter(m for m in every if m.version < "0141")
    )
    with pg_harness.migrated_schema() as (_, connection):
        connection.autocommit = True
        connection.row_factory = dict_row
        workspace = uuid.uuid4()
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
        )
        world_id = registered_world(connection, workspace)
        styles = WorldStyleRepository(connection, workspace, world_id=world_id)
        initial = styles.register_topology(topology(world_id=world_id))
        applied = styles.apply(
            styles.preview(
                proposal(initial, origin=ProposalOrigin.SETTINGS, origin_reference="s")
            ).preview_id,
            base_style_version_id=initial.version_id,
            base_topology_digest="topology-a",
            applied_by=uuid.uuid4(),
        )
        styles.preview(proposal(applied, parameters={"vitality": 0.5}))

        def contents():
            return {
                name: [
                    {key: value for key, value in row["row"].items() if key not in NEW_COLUMNS}
                    for row in connection.execute(
                        f"select to_jsonb(t) as row from {name} t order by to_jsonb(t)::text"
                    ).fetchall()
                ]
                for name in TABLES
            }

        before = contents()
        connection.execute(packs.sql)
        assert contents() == before
        for name, column in (
            ("world_style_version", "style_pack_id"),
            ("world_style_proposal", "style_pack"),
        ):
            named = connection.execute(
                f"select count(*) as n from {name} where {column} is not null"
            ).fetchone()
            assert named["n"] == 0
        assert WorldStyleRepository(connection, workspace, world_id=world_id).current() == (
            styles.current()
        )

        text = (COZY / "manifest.json").read_bytes()
        whole = {
            "style_pack_id": "exulanica.cozy-town",
            "style_pack_version": json.loads(text)["version"],
            "style_pack_manifest_sha256": hashlib.sha256(text[:-1]).hexdigest(),
        }
        for half in (
            {**whole, "style_pack_version": None},
            {**whole, "style_pack_manifest_sha256": None},
            {**whole, "style_pack_id": None},
            {**whole, "style_pack_manifest_sha256": "A" * 64},
            {**whole, "style_pack_id": "Cozy Town"},
            {**whole, "style_pack_version": 0},
        ):
            with pytest.raises(psycopg.errors.CheckViolation) as refused:
                _copy_version(connection, applied.version_id, **half)
            assert refused.value.diag.constraint_name == "world_style_version_style_pack_is_whole"
        _copy_version(connection, applied.version_id, **whole)
        named = connection.execute(
            "select style_pack_id,style_pack_version,style_pack_manifest_sha256 "
            "from world_style_version where style_pack_id is not null"
        ).fetchone()
        assert StylePackBinding(
            named["style_pack_id"],
            named["style_pack_version"],
            named["style_pack_manifest_sha256"],
        ) == StylePackBinding(*whole.values())

        written = styles.preview(proposal(applied, parameters={"vitality": 0.7})).proposal
        columns = [
            row["column_name"]
            for row in connection.execute(
                "select column_name from information_schema.columns where table_schema="
                "current_schema() and table_name='world_style_proposal' order by ordinal_position"
            ).fetchall()
            if row["column_name"] not in ("proposal_id", "style_pack")
        ]

        def ask(style_pack: str) -> None:
            """A copy of a proposal the repository wrote, asking ``style_pack``."""
            listed = ",".join(columns)
            connection.execute(
                f"insert into world_style_proposal (proposal_id,style_pack,{listed}) "
                f"select %s,%s::jsonb,{listed} from world_style_proposal where proposal_id=%s",
                (uuid.uuid4(), style_pack, written.proposal_id),
            )

        for wrong in ('"exulanica.cozy-town"', "{}", "null"):
            with pytest.raises(psycopg.errors.CheckViolation) as refused:
                ask(wrong)
            assert refused.value.diag.constraint_name == "world_style_proposal_style_pack_check"
        # The same row with each request the domain writes is taken: only the request was wrong.
        ask('{"pack": null}')
        ask(
            json.dumps(
                {
                    "pack": {
                        "pack_id": whole["style_pack_id"],
                        "version": 1,
                        "manifest_sha256": whole["style_pack_manifest_sha256"],
                    }
                }
            )
        )
