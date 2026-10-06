"""A baked tile is published and read only under the stage the installation runs, and a fault is
cleared by a recorded decision that never changes the stored tile (migration 0144).

Each test names a way the shared tile table could serve the wrong bytes: the schema's stage drifting
from the code's, a bake published under another stage, a reader or the create path taking a row of
another stage, a clearance of a tile with no fault, or a clearance that rewrites what was stored.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from exulanica.ingest.stages import STAGES
from exulanica.world.baked_tiles import current_bake
from exulanica.world.tile_faults import clear_fault, faulted_tiles
from psycopg.rows import dict_row

from pg_harness import open_scratch_connection

pytestmark = pytest.mark.postgres

NO_EDITS = hashlib.sha256(b"[]").digest()
SPEC = STAGES["baked_tile"]


@pytest.fixture
def owner(spine_schema) -> Iterator[psycopg.Connection]:
    """The owner's connection, in a transaction rolled back at the end: the tile table is global."""
    psycopg_module, scratch = spine_schema
    connection = open_scratch_connection(psycopg_module, scratch)
    connection.row_factory = dict_row
    connection.autocommit = False
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _publish(
    connection,
    *,
    version: int,
    params: bytes,
    container: bytes,
    inputs: bytes,
    key: uuid.UUID | None = None,
):
    return connection.execute(
        "select record_baked_tile_bake(%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s, %s, %s, %s, %s::jsonb) as outcome",
        (
            key or uuid.uuid4(),
            version,
            params,
            inputs,
            hashlib.sha256(b"seed").digest(),
            json.dumps([]),
            hashlib.sha256(b"catalog").digest(),
            NO_EDITS,
            0,
            0,
            0,
            250_000,
            0,
            hashlib.sha256(b"document").digest(),
            8,
            hashlib.sha256(container).digest(),
            len(container),
            hashlib.sha256(b"batch").digest(),
            hashlib.sha256(b"nav").digest(),
            json.dumps({}),
        ),
    ).fetchone()["outcome"]


def test_the_schema_s_current_stage_is_the_code_s(owner):
    """A change to the bake stage in code comes with a migration that retires the stage the schema
    states and states the next one; without it, every bake would be refused, and this says so."""
    rows = owner.execute(
        "select stage_version, stage_params_sha256 from baked_tile_stage where retired_at is null"
    ).fetchall()
    assert [(row["stage_version"], bytes(row["stage_params_sha256"])) for row in rows] == [
        (SPEC.version, SPEC.params_digest)
    ], (
        "STAGES['baked_tile'] moved: add a migration that retires the current baked_tile_stage "
        "row and states the new version and parameter digest"
    )


def test_a_bake_of_another_stage_is_refused_before_anything_is_stored(owner):
    inputs = uuid.uuid4().bytes * 2
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="stage this installation runs"):
        _publish(
            owner,
            version=SPEC.version + 1,
            params=SPEC.params_digest,
            container=b"x",
            inputs=hashlib.sha256(inputs).digest(),
        )
    owner.rollback()
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        _publish(
            owner,
            version=SPEC.version,
            params=hashlib.sha256(b"other parameters").digest(),
            container=b"x",
            inputs=hashlib.sha256(inputs).digest(),
        )
    owner.rollback()
    assert (
        _publish(
            owner,
            version=SPEC.version,
            params=SPEC.params_digest,
            container=b"x",
            inputs=hashlib.sha256(inputs).digest(),
        )
        == "stored"
    )


def test_a_row_of_another_stage_is_never_read_as_a_tile_s_bake(owner):
    """A row stored under another stage (here by the owner, past the function) is not the bake of
    its inputs: the reader, and so the create path's reuse, see nothing."""
    inputs = hashlib.sha256(uuid.uuid4().bytes).digest()
    owner.execute(
        "insert into baked_tile (baked_tile_id, stage_key, stage_version, stage_params_sha256, "
        "tile_inputs_digest, world_seed, grammar_pins, catalog_digest, edit_delta_digest, tile_x, "
        "tile_y, lod, tile_size_mm, halo_radius_mm, document_sha256, document_bytes, "
        "container_sha256, container_bytes, store_namespace, render_batch_sha256, "
        "nav_envelope_sha256, receipt, state) values (%s, 'baked_tile', %s, %s, %s, %s, '[]', %s, "
        "%s, 0, 0, 0, 250000, 0, %s, 8, %s, 1, 'tiles', %s, %s, '{}', 'baked')",
        (
            uuid.uuid4(),
            SPEC.version + 7,
            hashlib.sha256(b"another stage").digest(),
            inputs,
            hashlib.sha256(b"seed").digest(),
            hashlib.sha256(b"catalog").digest(),
            NO_EDITS,
            hashlib.sha256(b"document").digest(),
            hashlib.sha256(b"y").digest(),
            hashlib.sha256(b"batch").digest(),
            hashlib.sha256(b"nav").digest(),
        ),
    )
    assert current_bake(owner, inputs.hex()) is None
    assert (
        _publish(
            owner, version=SPEC.version, params=SPEC.params_digest, container=b"z", inputs=inputs
        )
        == "stored"
    )
    bake = current_bake(owner, inputs.hex())
    assert bake is not None and bake.stage_version == SPEC.version


def test_a_key_naming_another_stage_s_or_another_tile_s_bake_faults_nothing(owner):
    """The stage check reads the stored row, not only the arguments: current-stage arguments that
    name the key of a row stored under another stage, or of another tile's bake, are refused, and
    the stored row keeps its bytes and its state."""
    older_key, older_inputs = uuid.uuid4(), hashlib.sha256(uuid.uuid4().bytes).digest()
    owner.execute(
        "insert into baked_tile (baked_tile_id, stage_key, stage_version, stage_params_sha256, "
        "tile_inputs_digest, world_seed, grammar_pins, catalog_digest, edit_delta_digest, tile_x, "
        "tile_y, lod, tile_size_mm, halo_radius_mm, document_sha256, document_bytes, "
        "container_sha256, container_bytes, store_namespace, render_batch_sha256, "
        "nav_envelope_sha256, receipt, state) values (%s, 'baked_tile', %s, %s, %s, %s, '[]', %s, "
        "%s, 0, 0, 0, 250000, 0, %s, 8, %s, 1, 'tiles', %s, %s, '{}', 'baked')",
        (
            older_key,
            SPEC.version + 7,
            hashlib.sha256(b"another stage").digest(),
            older_inputs,
            hashlib.sha256(b"seed").digest(),
            hashlib.sha256(b"catalog").digest(),
            NO_EDITS,
            hashlib.sha256(b"document").digest(),
            hashlib.sha256(b"y").digest(),
            hashlib.sha256(b"batch").digest(),
            hashlib.sha256(b"nav").digest(),
        ),
    )
    this_key, this_inputs = uuid.uuid4(), hashlib.sha256(uuid.uuid4().bytes).digest()
    current = {"version": SPEC.version, "params": SPEC.params_digest}
    assert _publish(owner, **current, container=b"a", inputs=this_inputs, key=this_key) == "stored"
    attempts = (
        (older_key, older_inputs),  # another stage's row, under its own inputs
        (this_key, hashlib.sha256(b"another tile").digest()),  # this stage, another tile's inputs
    )
    for key, inputs in attempts:
        # A savepoint each, so the refusal leaves the rows stored above in the open transaction.
        refused = pytest.raises(psycopg.errors.InvalidParameterValue, match="another stage or tile")
        with refused, owner.transaction():
            _publish(owner, **current, container=b"other bytes", inputs=inputs, key=key)
    rows = owner.execute(
        "select baked_tile_id, state, container_sha256, fault_container_sha256 from baked_tile "
        "where baked_tile_id in (%s, %s) order by baked_tile_id",
        (older_key, this_key),
    ).fetchall()
    kept = {row["baked_tile_id"]: (row["state"], row["fault_container_sha256"]) for row in rows}
    assert kept == {older_key: ("baked", None), this_key: ("baked", None)}


def test_a_fault_is_cleared_by_a_recorded_decision_and_the_stored_tile_is_untouched(owner):
    inputs = hashlib.sha256(uuid.uuid4().bytes).digest()
    tile_id = uuid.uuid4()

    def publish(container: bytes) -> str:
        return owner.execute(
            "select record_baked_tile_bake(%s, %s, %s, %s, %s, '[]'::jsonb, %s, %s, 0, 0, 0, "
            "250000, 0, %s, 8, %s, %s, %s, %s, '{}'::jsonb) as outcome",
            (
                tile_id,
                SPEC.version,
                SPEC.params_digest,
                inputs,
                hashlib.sha256(b"seed").digest(),
                hashlib.sha256(b"catalog").digest(),
                NO_EDITS,
                hashlib.sha256(b"document").digest(),
                hashlib.sha256(container).digest(),
                len(container),
                hashlib.sha256(b"batch").digest(),
                hashlib.sha256(b"nav").digest(),
            ),
        ).fetchone()["outcome"]

    assert publish(b"first") == "stored"
    # A tile whose bakes agreed has no fault to clear.
    with pytest.raises(psycopg.errors.CheckViolation, match="whose bakes disagreed"):
        clear_fault(owner, tile_id, operator="test-operator", reason="nothing to clear")
    owner.rollback()
    assert publish(b"first") == "stored"
    assert publish(b"second") == "nondeterminism_detected"
    stored_before = owner.execute(
        "select container_sha256, state, fault_container_sha256 from baked_tile "
        "where baked_tile_id = %s",
        (tile_id,),
    ).fetchone()
    bake = current_bake(owner, inputs.hex())
    assert bake is not None and not bake.servable
    assert clear_fault(owner, tile_id, operator="test-operator", reason="first bake checked")
    assert not clear_fault(owner, tile_id, operator="test-operator", reason="again")
    bake = current_bake(owner, inputs.hex())
    assert bake is not None and bake.servable and bake.cleared
    assert bytes.fromhex(bake.container_sha256) == hashlib.sha256(b"first").digest()
    assert (
        owner.execute(
            "select container_sha256, state, fault_container_sha256 from baked_tile "
            "where baked_tile_id = %s",
            (tile_id,),
        ).fetchone()
        == stored_before
    )
    # The listing shows what a clearance serves and what disagreed with it: the digests here are
    # of the bytes this test published, not read back from the code that lists them.
    [listed] = [row for row in faulted_tiles(owner) if row["baked_tile_id"] == str(tile_id)]
    assert listed["cleared"]
    assert listed["container_sha256"] == hashlib.sha256(b"first").hexdigest()
    assert listed["fault_container_sha256"] == hashlib.sha256(b"second").hexdigest()
    assert listed["baked_at"] and listed["receipt"] == {}
    with pytest.raises(psycopg.errors.CheckViolation, match="never changes"):
        owner.execute(
            "update baked_tile_fault_clearance set reason = 'rewritten' where baked_tile_id = %s",
            (tile_id,),
        )
