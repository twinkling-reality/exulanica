"""Migration 0128 over rows written before it: every existing proposal and version stands as it was.

A Companion proposal written before 0128 names its evidence and states no basis; a Settings one
states neither. The revised check reads a Companion row with no basis as drawn from evidence, so
both satisfy it unchanged, and applying the migration moves no stored value: the one new column
reads null on every earlier row. After it, the domain takes a design choice with no references.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from exulanica.migrations import migrations
from exulanica.world import (
    InvalidStyleData,
    ProposalOrigin,
    ProposalProvenance,
    StyleProposal,
    StyleReference,
    StyleScope,
    WorldStyleRepository,
)
from psycopg.rows import dict_row

import pg_harness
from test_world_style_postgres import proposal, topology
from world_support import registered_world

pytestmark = pytest.mark.postgres

TABLES = ("world_style_proposal", "world_style_version", "world_style_preview")


def test_existing_style_rows_are_unaffected_and_a_design_choice_is_taken_after(monkeypatch):
    every = list(migrations())
    [basis] = [item for item in every if item.version == "0128"]
    monkeypatch.setattr(
        pg_harness, "migrations", lambda: iter(m for m in every if m.version < "0128")
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
        drawn = styles.preview(
            proposal(initial, origin=ProposalOrigin.COMPANION, origin_reference="c")
        )
        applied = styles.apply(
            drawn.preview_id,
            base_style_version_id=initial.version_id,
            base_topology_digest="topology-a",
            applied_by=uuid.uuid4(),
        )
        styles.preview(
            proposal(
                applied,
                origin=ProposalOrigin.SETTINGS,
                origin_reference="s",
                parameters={"vitality": 0.5},
            )
        )

        def contents():
            return {
                name: [
                    {key: value for key, value in row["row"].items() if key != "appearance_basis"}
                    for row in connection.execute(
                        f"select to_jsonb(t) as row from {name} t order by to_jsonb(t)::text"
                    ).fetchall()
                ]
                for name in TABLES
            }

        before = contents()
        connection.execute(basis.sql)
        assert contents() == before
        for name in ("world_style_proposal", "world_style_version"):
            stated = connection.execute(
                f"select count(*) as n from {name} where appearance_basis is not null"
            ).fetchone()
            assert stated["n"] == 0

        after = WorldStyleRepository(connection, workspace, world_id=world_id)
        current = after.current()
        design = StyleProposal(
            proposal_id=uuid.uuid4(),
            provenance=ProposalProvenance(ProposalOrigin.COMPANION, uuid.uuid4(), "companion:test"),
            scope=StyleScope("global"),
            base_style_version_id=current.version_id,
            base_topology_digest="topology-a",
            profile=StyleReference("origin-landscape", 1, {"vitality": 0.4}),
            reference_ids=(),
            model_id="test-style-proposer/v1",
            prompt_version="proposal-authored-1",
            appearance_basis="authored_design",
        )
        previewed = after.preview(design)
        version = after.apply(
            previewed.preview_id,
            base_style_version_id=current.version_id,
            base_topology_digest="topology-a",
            applied_by=uuid.uuid4(),
        )
        assert version.appearance_basis == "authored_design"
        assert version.reference_ids == ()
        with pytest.raises(InvalidStyleData):
            # The same design choice, now claiming to be drawn from evidence it does not name.
            after.preview(
                replace(
                    design,
                    proposal_id=uuid.uuid4(),
                    base_style_version_id=version.version_id,
                    appearance_basis="evidence",
                )
            )
