"""Migration 0102: an id a caller chooses is unique within its workspace, never across them.

Each database test migrates a schema of its own to just below 0102 with the migrations exactly as
they are on disk, writes rows in two workspaces through the domain code a deployment writes them
with, then applies 0102 itself and reads what it left: every id and every reference as it was,
each of the three tables keyed by (workspace_id, id), the foreign keys to place bound to the new key
under their own names and definitions, and an id one workspace used free for another while still
refused within its own. The arm before the migration shows the refusal the migration removes, so
the arm after it is a change and not a condition that always held.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from exulanica.environment import (
    DeclaredPlaceFrame,
    EnvironmentRepository,
    GeographicBounds,
    GeographicFrame,
    OperationRights,
    PlaceFrameConflict,
    SourceAdmission,
)
from exulanica.migrations import migrations
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import (
    InvalidInteractionData,
    InvalidStyleData,
    TopologyContract,
    WorldStyleRepository,
)
from exulanica.world.interaction_repository import WorldInteractionPolicyRepository
from exulanica.world.models import (
    DEFAULT_WORLD_ID,
    ProposalOrigin,
    ProposalProvenance,
    StyleProposal,
    StyleReference,
    StyleScope,
)
from psycopg.rows import dict_row

import pg_harness
from test_interaction_policy_postgres import proposal as interaction_proposal

pytestmark = pytest.mark.postgres

MIGRATION = next(migration for migration in migrations() if migration.version == "0102")
#: The three tables whose caller-chosen id 0102 keys by workspace, with the column it is.
CHOSEN = {
    "place": "place_id",
    "world_style_proposal": "proposal_id",
    "world_interaction_policy_proposal": "proposal_id",
}
FIELD_OF_VIEW = {"comfort.field-of-view-degrees": 82}


@contextmanager
def _below_0102(monkeypatch) -> Iterator[psycopg.Connection]:
    everything = list(migrations())
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness, "migrations", lambda: iter(m for m in everything if m.version < "0102")
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            admin.commit()
            admin.autocommit = True
            admin.row_factory = dict_row
            yield admin


def _as(admin: psycopg.Connection, workspace: uuid.UUID) -> None:
    admin.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))


def _frame() -> GeographicFrame:
    return GeographicFrame(
        name="nyc-grid",
        crs="EPSG:6539",
        axis_order=("east", "north", "height"),
        horizontal_unit="metre",
        vertical_unit="metre",
        orientation="right-handed",
        altitude_reference="NAVD88",
    )


def _bounds() -> GeographicBounds:
    return GeographicBounds(
        kind="bbox",
        frame_name="nyc-grid",
        coordinate_scale=1000,
        coordinates=(0, 0, 0, 100_000, 100_000, 10_000),
    )


def _declare(admin, workspace, store, place_id, statement="as published"):
    _as(admin, workspace)
    return EnvironmentRepository(admin, workspace, store).declare_place_frame(
        DeclaredPlaceFrame(
            place_id=place_id,
            provider_key="nyc-open-data",
            provider_frame_statement=f"The provider publishes these bounds {statement}.",
            geographic_frame=_frame(),
            geographic_bounds=_bounds(),
        ),
        actor=uuid.uuid4(),
    )


def _admit(admin, workspace, store, place_id, tmp_path) -> uuid.UUID:
    """A source admitted to the place, so a row elsewhere references it by (workspace, place)."""
    data = f"a source for {place_id}".encode()
    local = tmp_path / f"{uuid.uuid4().hex}.bin"
    local.write_bytes(data)
    source = SourceAdmission(
        place_id=place_id,
        provider_key="nyc-open-data",
        provider_original_id="rehearsal",
        provider_revision="1",
        expected_sha256=hashlib.sha256(data).hexdigest(),
        expected_byte_size=len(data),
        source_path="fixture/rehearsal.bin",
        media_type="application/octet-stream",
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=OperationRights(
            display=True,
            extract=True,
            index=True,
            persist=True,
            modify=True,
            compose=True,
            export=False,
            model_processing=False,
        ),
        attribution="rehearsal",
        modification_notice="unchanged",
        local_path=local,
    )
    _as(admin, workspace)
    EnvironmentRepository(admin, workspace, store).admit_source(source, actor=uuid.uuid4())
    return source.admission_id


def _styles(admin, workspace, topology) -> WorldStyleRepository:
    _as(admin, workspace)
    styles = WorldStyleRepository(admin, workspace, world_id=DEFAULT_WORLD_ID)
    if (
        admin.execute(
            "select 1 from world_style_state where workspace_id = %s", (workspace,)
        ).fetchone()
        is None
    ):
        styles.register_topology(TopologyContract(topology, ("region-a",)))
    return styles


def _style_preview(admin, workspace, proposal_id):
    styles = _styles(admin, workspace, f"rehearsal-{workspace.hex[:8]}")
    return styles.preview(
        StyleProposal(
            proposal_id=proposal_id,
            provenance=ProposalProvenance(ProposalOrigin.SETTINGS, uuid.uuid4(), "panel"),
            scope=StyleScope("global"),
            base_style_version_id=styles.current().version_id,
            base_topology_digest=styles.current_topology_digest(),
            profile=StyleReference("origin-landscape", 1, {"vitality": 0.25}),
            reference_ids=(),
            model_id=None,
            prompt_version=None,
            refines_proposal_id=None,
        )
    )


def _interaction_preview(admin, workspace, proposal_id):
    _as(admin, workspace)
    policies = WorldInteractionPolicyRepository(admin, workspace, world_id=DEFAULT_WORLD_ID)
    return policies.preview(interaction_proposal(policies, FIELD_OF_VIEW, proposal_id=proposal_id))


def _rows(admin) -> dict[str, list[tuple]]:
    """Every row 0102 must leave as it was, read as the administrative role."""
    queries = {
        "place": "select workspace_id, place_id from place",
        "place_source_frame": (
            "select workspace_id, place_id, receipt_sha256 from place_source_frame"
        ),
        "environment_source_admission": (
            "select workspace_id, admission_id, place_id from environment_source_admission"
        ),
        "world_style_proposal": (
            "select workspace_id, world_id, proposal_id from world_style_proposal"
        ),
        "world_style_preview": (
            "select workspace_id, world_id, proposal_id, preview_id from world_style_preview"
        ),
        "world_interaction_policy_proposal": (
            "select workspace_id, world_id, proposal_id from world_interaction_policy_proposal"
        ),
        "world_interaction_policy_preview": (
            "select workspace_id, world_id, proposal_id, preview_id "
            "from world_interaction_policy_preview"
        ),
    }
    return {
        table: sorted(tuple(row.values()) for row in admin.execute(query).fetchall())
        for table, query in queries.items()
    }


def _primary_key(admin, table: str) -> list[str]:
    return [
        row["attname"]
        for row in admin.execute(
            "select a.attname from pg_index i "
            "join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey) "
            "where i.indrelid = %s::regclass and i.indisprimary "
            "order by array_position(i.indkey::int2[], a.attnum)",
            (table,),
        ).fetchall()
    ]


def _references_to_place(admin) -> dict[str, tuple[str, str, str]]:
    """Each foreign key to place: its table, its definition and the index it is bound to."""
    rows = admin.execute(
        "select c.conname, c.conrelid::regclass::text as referencing, "
        "pg_get_constraintdef(c.oid) as definition, i.relname as bound_to "
        "from pg_constraint c join pg_class i on i.oid = c.conindid "
        "where c.contype = 'f' and c.confrelid = 'place'::regclass and c.conparentid = 0"
    ).fetchall()
    return {
        row["conname"]: (row["referencing"], row["definition"], row["bound_to"]) for row in rows
    }


def test_0102_keeps_every_id_and_reference_and_keys_each_table_by_workspace(monkeypatch, tmp_path):
    store = LocalContentAddressedStore(tmp_path / "blobs")
    first, second = uuid.uuid4(), uuid.uuid4()
    place, style_id, interaction_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with _below_0102(monkeypatch) as admin:
        _declare(admin, first, store, place)
        _admit(admin, first, store, place, tmp_path)
        _declare(admin, second, store, uuid.uuid4())
        _style_preview(admin, first, style_id)
        _style_preview(admin, second, uuid.uuid4())
        _interaction_preview(admin, first, interaction_id)
        _interaction_preview(admin, second, uuid.uuid4())

        # Before 0102 each id was the whole key, so the second workspace could not use them.
        with pytest.raises(PlaceFrameConflict, match="cannot be declared under this identifier"):
            _declare(admin, second, store, place)
        with pytest.raises(InvalidStyleData, match="was already used"):
            _style_preview(admin, second, style_id)
        with pytest.raises(InvalidInteractionData, match="was already used"):
            _interaction_preview(admin, second, interaction_id)
        before = _rows(admin)
        references = _references_to_place(admin)
        assert references, "no foreign key references place, so the rebinding below proves nothing"
        assert {bound for _table, _definition, bound in references.values()} == {
            "place_workspace_id_place_id_key"
        }
        for table, column in CHOSEN.items():
            assert _primary_key(admin, table) == [column]

        admin.execute(MIGRATION.sql)

        assert _rows(admin) == before
        for table, column in CHOSEN.items():
            assert _primary_key(admin, table) == ["workspace_id", column]
        assert _references_to_place(admin) == {
            name: (table, definition, "place_pkey")
            for name, (table, definition, _bound) in references.items()
        }
        assert admin.execute(
            "select count(*) as unique_keys from pg_constraint "
            "where conrelid = 'place'::regclass and contype = 'u'"
        ).fetchone() == {"unique_keys": 0}, "the key the references moved to is the only one"

        # The same three ids are free for the second workspace, as new rows of its own.
        _declare(admin, second, store, place)
        _style_preview(admin, second, style_id)
        _interaction_preview(admin, second, interaction_id)
        for table, column in CHOSEN.items():
            chosen = {place} if table == "place" else {style_id, interaction_id}
            owners = admin.execute(
                f"select distinct workspace_id from {table} where {column} = any(%s)",
                (list(chosen),),
            ).fetchall()
            assert {row["workspace_id"] for row in owners} == {first, second}, table

        # And still refused, by name, within the workspace that used them.
        with pytest.raises(PlaceFrameConflict, match="already declared a different frame"):
            _declare(admin, first, store, place, statement="in another frame")
        with pytest.raises(InvalidStyleData, match="was already used"):
            _style_preview(admin, first, style_id)
        with pytest.raises(InvalidInteractionData, match="was already used"):
            _interaction_preview(admin, first, interaction_id)


def test_a_reference_to_place_id_alone_stops_0102_and_leaves_the_key_as_it_was(monkeypatch):
    """The migration's own claim: a reference 0102 could not keep stops it rather than
    being dropped."""
    with _below_0102(monkeypatch) as admin:
        admin.execute(
            "create table rehearsal_reference (place_id uuid references place (place_id))"
        )
        with pytest.raises(psycopg.errors.InvalidForeignKey):
            admin.execute(MIGRATION.sql)
        admin.execute("rollback")
        assert _primary_key(admin, "place") == ["place_id"]
        assert (
            admin.execute(
                "select count(*) as references_kept from pg_constraint "
                "where contype = 'f' and confrelid = 'place'::regclass"
            ).fetchone()["references_kept"]
            > 1
        )
