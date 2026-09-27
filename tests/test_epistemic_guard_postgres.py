"""The epistemic guard, executed against a real PostgreSQL server.

Everything in ``test_migration.py`` is a text check over the migration file. A text check cannot
tell the difference between a rule the database enforces and a rule the file merely describes,
and that difference is exactly what the review found: ``predicate.allows_kind`` was declared,
documented as the reason "there is no code path in which a model writes a name", and enforced by
nothing. A live probe inserted ``kind='inference'`` against ``name_is`` with the object value
``"Aunt Marjorie"`` and it landed with ``status='active'``.

So these tests write the offending rows and require the database to refuse them.

Running them
------------
Set ``EXULANICA_TEST_DATABASE_URL`` to a scratch database; without it every test here skips, which
is the normal state on a machine with no server. The server must be the documented target,
PostgreSQL 18 with pgvector: nothing is substituted, and a server that cannot run the schema
fails loudly rather than being faked. ``tests/pg_harness.py`` explains how the schema is applied
and torn down. Each test runs inside a savepoint, so no test sees another one's rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from exulanica.models.manifest import Role, load_manifest

from pg_harness import REQUIRED_EXTENSIONS, REQUIRED_SERVER_VERSION, migrated_schema

pytestmark = pytest.mark.postgres


class _Rollback(Exception):
    """Raised to unwind a savepoint after a write that was supposed to succeed."""


@pytest.fixture(scope="module")
def spine():
    """A migrated schema plus the few rows an assertion needs to reference."""
    with migrated_schema() as (psycopg, conn):
        workspace = uuid.uuid4()
        cursor = conn.cursor()
        cursor.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
        digest = bytes(range(32))
        cursor.execute(
            "insert into blob (blob_sha256, byte_size, media_type) values (%s, 1, 'image/jpeg')",
            (digest,),
        )
        cursor.execute(
            "insert into evidence_span (workspace_id, blob_sha256, track_key, t_start_ns, "
            "t_end_ns, modality, span_digest) "
            "values (%s, %s, 'img', 0, 1, 'still_image', %s) returning span_id",
            (workspace, digest, bytes(32)),
        )
        span_id = cursor.fetchone()[0]
        cursor.execute(
            "insert into pipeline_run (workspace_id, trigger) values (%s, 'ingest') "
            "returning run_id",
            (workspace,),
        )
        run_id = cursor.fetchone()[0]
        cursor.execute("select key, predicate_id from predicate")
        predicates = dict(cursor.fetchall())
        yield Spine(psycopg, conn, workspace, span_id, run_id, predicates)


class Spine:
    def __init__(self, psycopg, conn, workspace, span_id, run_id, predicates) -> None:
        self.psycopg = psycopg
        self.conn = conn
        self.workspace = workspace
        self.span_id = span_id
        self.run_id = run_id
        self.predicates = predicates
        self.subject = psycopg.types.json.Json(
            {"type": "entity", "id": str(uuid.uuid4())}
        )

    @contextmanager
    def undone(self) -> Iterator[None]:
        """Run a statement in a savepoint that is always rolled back."""
        try:
            with self.conn.transaction():
                yield
                raise _Rollback
        except _Rollback:
            pass

    def refuses(self, sql: str, params: tuple) -> str:
        """Assert the database refuses this statement. Returns the message it refused with."""
        with pytest.raises(self.psycopg.Error) as raised, self.undone():
            self.conn.execute(sql, params)
        return str(raised.value)

    def accepts(self, sql: str, params: tuple) -> None:
        with self.undone():
            self.conn.execute(sql, params)

    def assertion_sql(self, columns: str, values: str) -> str:
        return (
            f"insert into assertion (workspace_id, kind, predicate_id, subject_ref, {columns}) "
            f"values (%s, %s, %s, %s, {values})"
        )


def test_the_schema_under_test_is_the_one_that_ships(spine):
    """Nothing here is substituted, and this is what proves it.

    The harness used to swap ``uuidv7()`` for ``gen_random_uuid()`` and ``halfvec(4096)`` for
    ``bytea`` so the suite could run on PostgreSQL 14. Everything passed and the vector path had
    never executed once. So the two substituted features are asserted to be the real ones: a
    server-supplied ``uuidv7`` resolving in ``pg_catalog`` rather than a scratch-schema stand-in,
    and a column whose type is genuinely ``halfvec``.
    """
    version = int(spine.conn.execute("show server_version_num").fetchone()[0])
    assert version >= REQUIRED_SERVER_VERSION, spine.conn.execute(
        "show server_version"
    ).fetchone()[0]

    owner = spine.conn.execute(
        "select n.nspname from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where p.oid = to_regprocedure('uuidv7()')"
    ).fetchone()
    assert owner is not None and owner[0] == "pg_catalog", owner

    column_type = spine.conn.execute(
        "select format_type(a.atttypid, a.atttypmod) from pg_attribute a "
        "where a.attrelid = 'embedding'::regclass and a.attname = 'v'"
    ).fetchone()
    # The width the manifest declares for the embedding role's primary, which the code reads.
    width = load_manifest()[Role.EMBEDDING].primary.embedding_dimensions
    assert column_type is not None and column_type[0] == f"halfvec({width})", column_type

    installed = {
        row[0]
        for row in spine.conn.execute(
            "select extname from pg_extension where extname = any(%s)",
            (list(REQUIRED_EXTENSIONS),),
        ).fetchall()
    }
    assert installed == set(REQUIRED_EXTENSIONS), sorted(installed)


def test_the_live_vocabulary_is_the_one_that_was_decided(spine):
    """Read the live rows, not the migration text, and compare them to the recorded decisions.

    A substring search over the migration cannot notice a trigger that refused the seed: a
    vocabulary that failed to insert surfaces as an empty table, which reads as "no predicate
    accepts anything" and refuses every write for a reason nobody would guess from the error.

    Row for row against ``exulanica.epistemics.vocabulary.DECISIONS``, which is defect R4's answer.
    There is deliberately no count to bump here: a predicate added without a decision fails
    ``tests/test_vocabulary_decisions.py``, and a decision that does not match the database fails
    this. The count assertion it replaces was ``len(rows) == 12``, whose repair when
    ``reconstruction_rung_is`` was added was to type 13.

    ``allows_kind`` is sorted on both sides. Array element order is a storage detail, and a
    vocabulary row reordered by a later migration is not a decision anybody made.
    """
    from exulanica.epistemics.vocabulary import DECISIONS

    live = {
        row[0]: (tuple(sorted(row[1])), row[2], row[3])
        for row in spine.conn.execute(
            "select key, allows_kind::text[], writes_a_name, functional from predicate"
        ).fetchall()
    }
    recorded = {
        decision.key: (tuple(sorted(decision.allows_kind)), decision.writes_a_name,
                       decision.functional)
        for decision in DECISIONS
    }
    assert live == recorded

    for key, (kinds, _writes, _functional) in live.items():
        assert kinds, f"{key} allows no kind at all, which refuses every write"
        assert None not in kinds, f"{key} has a NULL element, which disarms the guard"


def test_a_vocabulary_row_must_state_whether_it_writes_a_name(spine):
    """R4, migration 0007. The fail-open value was the one you got by saying nothing.

    Whether a predicate's object IS a name cannot be enforced here and is not claimed to be. What
    is enforced is that somebody answered: before 0007 an insert omitting the column was accepted
    and read back false, so a row whose author never considered naming was silently declared not
    to name anyone.
    """
    message = spine.refuses(
        "insert into predicate (key, value_schema, allows_kind) values "
        "('alias_is', '{\"type\":\"string\"}', array['inference']::assertion_kind[])",
        (),
    )
    assert "writes_a_name" in message


# -- defect 1: a model writing a name ---------------------------------------------------


@pytest.mark.parametrize("kind", ["inference", "capture", "external"])
def test_only_the_user_may_write_a_name(spine, kind):
    """The exact insert the review's live probe got accepted with status='active'."""
    message = spine.refuses(
        spine.assertion_sql(
            "object_value, support_span_ids, produced_by_run, external_source, emit_key",
            "'\"Aunt Marjorie\"', array[%s]::uuid[], %s, "
            "'{\"url\":\"https://x\",\"retrieved_at\":\"now\",\"snapshot_hash\":\"h\"}', %s",
        ),
        (
            spine.workspace,
            kind,
            spine.predicates["name_is"],
            spine.subject,
            spine.span_id,
            spine.run_id,
            f"name:{kind}",
        ),
    )
    assert "name_is" in message and kind in message


def test_the_user_may_write_a_name(spine):
    """The guard has to refuse the three wrong kinds without refusing the right one.

    Without this, a trigger that refused everything would pass every other test in this file.
    """
    spine.accepts(
        spine.assertion_sql(
            "object_value, stated_by_user, emit_key", "'\"Aunt Marjorie\"', %s, %s"
        ),
        (
            spine.workspace,
            "user",
            spine.predicates["name_is"],
            spine.subject,
            uuid.uuid4(),
            "name:user",
        ),
    )


def test_a_caption_cannot_be_filed_as_a_capture_supported_fact(spine):
    """The second half of the live probe: a caption accepted as kind='capture'."""
    message = spine.refuses(
        spine.assertion_sql(
            "object_value, support_span_ids, emit_key",
            "'\"a sunny beach\"', array[%s]::uuid[], %s",
        ),
        (
            spine.workspace,
            "capture",
            spine.predicates["caption_is"],
            spine.subject,
            spine.span_id,
            "caption:capture",
        ),
    )
    assert "caption_is" in message


def test_a_model_may_write_a_caption(spine):
    spine.accepts(
        spine.assertion_sql(
            "object_value, support_span_ids, produced_by_run, emit_key",
            "'\"a sunny beach\"', array[%s]::uuid[], %s, %s",
        ),
        (
            spine.workspace,
            "inference",
            spine.predicates["caption_is"],
            spine.subject,
            spine.span_id,
            spine.run_id,
            "caption:inference",
        ),
    )


# -- the two-step route round an insert-only guard --------------------------------------


def test_a_name_cannot_be_relabelled_as_an_inference_afterwards(spine):
    """Insert legally, then update the kind. An INSERT-only guard would wave this through."""
    with spine.undone():
        cursor = spine.conn.cursor()
        cursor.execute(
            spine.assertion_sql(
                "object_value, stated_by_user, emit_key", "'\"Aunt Marjorie\"', %s, %s"
            )
            + " returning assertion_id",
            (
                spine.workspace,
                "user",
                spine.predicates["name_is"],
                spine.subject,
                uuid.uuid4(),
                "name:relabel",
            ),
        )
        assertion_id = cursor.fetchone()[0]
        with pytest.raises(spine.psycopg.Error, match="name_is"), spine.conn.transaction():
                spine.conn.execute(
                    "update assertion set kind = 'inference' where assertion_id = %s",
                    (assertion_id,),
                )


def test_an_inference_cannot_be_repointed_at_a_naming_predicate(spine):
    """The other half of the same hole: keep the kind, move the predicate."""
    with spine.undone():
        cursor = spine.conn.cursor()
        cursor.execute(
            spine.assertion_sql(
                "object_value, support_span_ids, produced_by_run, emit_key",
                "'\"a sunny beach\"', array[%s]::uuid[], %s, %s",
            )
            + " returning assertion_id",
            (
                spine.workspace,
                "inference",
                spine.predicates["caption_is"],
                spine.subject,
                spine.span_id,
                spine.run_id,
                "caption:repoint",
            ),
        )
        assertion_id = cursor.fetchone()[0]
        with pytest.raises(spine.psycopg.Error, match="name_is"), spine.conn.transaction():
                spine.conn.execute(
                    "update assertion set predicate_id = %s where assertion_id = %s",
                    (spine.predicates["name_is"], assertion_id),
                )


# -- failing closed ---------------------------------------------------------------------


def test_a_write_with_no_workspace_context_is_refused(spine):
    """The guard reads a lookup table, so an unset session context must refuse, not pass.

    ``set_config(..., true)`` is transaction local, so the savepoint rollback restores the
    context for the rest of the module.
    """
    with spine.undone():
        spine.conn.execute("select set_config('exulanica.workspace_id', '', true)")
        with pytest.raises(spine.psycopg.Error, match="workspace context"), (
            spine.conn.transaction()
        ):
                spine.conn.execute(
                    spine.assertion_sql(
                        "object_value, stated_by_user, emit_key", "'\"Anna\"', %s, %s"
                    ),
                    (
                        spine.workspace,
                        "user",
                        spine.predicates["name_is"],
                        spine.subject,
                        uuid.uuid4(),
                        "name:nocontext",
                    ),
                )


def test_an_unknown_predicate_is_refused_rather_than_skipped(spine):
    """A BEFORE trigger runs ahead of the foreign key check, so this branch is reachable."""
    message = spine.refuses(
        spine.assertion_sql("object_value, stated_by_user, emit_key", "'\"Anna\"', %s, %s"),
        (spine.workspace, "user", 999_999, spine.subject, uuid.uuid4(), "name:nopredicate"),
    )
    assert "no such predicate" in message


# -- the vocabulary itself --------------------------------------------------------------


def test_a_naming_predicate_cannot_be_widened_to_admit_a_model(spine):
    """Enforcement that only guards assertions is one UPDATE away from being irrelevant."""
    spine.refuses(
        "update predicate set allows_kind = array['user','inference']::assertion_kind[] "
        "where predicate_id = %s",
        (spine.predicates["name_is"],),
    )


def test_a_new_naming_predicate_cannot_be_seeded_as_model_writable(spine):
    """The vocabulary churns weekly. 'nickname_is' must not be able to escape the rule."""
    spine.refuses(
        "insert into predicate (key, value_schema, allows_kind, writes_a_name) "
        "values ('nickname_is', '{\"type\":\"string\"}', "
        "array['inference']::assertion_kind[], true)",
        (),
    )


def test_allows_kind_cannot_hold_a_null_element(spine):
    """`kind = any(arr)` is NULL, not false, against a NULL element, and plpgsql accepts NULL.

    One NULL in this array would silently disarm the guard, so the array may not contain one.
    """
    spine.refuses(
        "update predicate set allows_kind = array['inference',null]::assertion_kind[] "
        "where predicate_id = %s",
        (spine.predicates["caption_is"],),
    )


def test_the_guard_still_fails_closed_if_a_null_element_ever_reaches_the_array(spine):
    """The second of the two defences, exercised by removing the first.

    ``x = any(arr)`` returns NULL rather than false when arr holds a NULL and x matches nothing
    else, and plpgsql takes the else branch on a NULL condition, so a single NULL element would
    turn the guard into a no-op. The constraint above stops that array existing; the coalesce in
    the guard stops it mattering. With both in place the coalesce is unreachable, and an
    unreachable defence is one nothing would notice the removal of. So drop the constraint
    inside a savepoint and check the guard alone still refuses.
    """
    with spine.undone():
        spine.conn.execute(
            "alter table predicate drop constraint allows_kind_has_no_null_element"
        )
        spine.conn.execute(
            "update predicate set allows_kind = array['user',null]::assertion_kind[] "
            "where predicate_id = %s",
            (spine.predicates["caption_is"],),
        )
        with pytest.raises(spine.psycopg.Error, match="caption_is"), spine.conn.transaction():
                spine.conn.execute(
                    spine.assertion_sql(
                        "object_value, support_span_ids, produced_by_run, emit_key",
                        "'\"a sunny beach\"', array[%s]::uuid[], %s, %s",
                    ),
                    (
                        spine.workspace,
                        "inference",
                        spine.predicates["caption_is"],
                        spine.subject,
                        spine.span_id,
                        spine.run_id,
                        "caption:nullarray",
                    ),
                )


# -- the other schema errors, verified rather than read ---------------------------------


def test_re_uploading_deleted_bytes_creates_a_new_capture(spine):
    """Decision del-3. A total unique (workspace_id, blob_sha256) makes this impossible."""
    with spine.undone():
        digest = bytes([7]) * 32
        spine.conn.execute(
            "insert into blob (blob_sha256, byte_size, media_type) values (%s, 1, 'image/jpeg')",
            (digest,),
        )
        spine.conn.execute(
            "insert into capture (workspace_id, blob_sha256, deleted_at) values (%s, %s, now())",
            (spine.workspace, digest),
        )
        spine.conn.execute(
            "insert into capture (workspace_id, blob_sha256) values (%s, %s)",
            (spine.workspace, digest),
        )
        # ... and a second LIVE capture of the same bytes still collapses.
        with pytest.raises(spine.psycopg.errors.UniqueViolation), spine.conn.transaction():
                spine.conn.execute(
                    "insert into capture (workspace_id, blob_sha256) values (%s, %s)",
                    (spine.workspace, digest),
                )


def test_the_embedding_width_is_the_measured_one(spine):
    """Runtime measurement recorded 4096 dimensions. A row claiming 1024 is a bug, not a variant.

    Both halves of the guarantee are exercised, because they fail differently. ``dims`` is a
    check constraint on a number the writer supplies, so a row that lies about its width is a
    CheckViolation. The width of ``v`` is the column type, so a vector of the wrong length is a
    type error the writer cannot argue with. A 4096-wide vector with an honest ``dims`` lands.
    """
    insert = (
        "insert into embedding (workspace_id, family, ref_type, ref_id, model_ref, "
        "pipeline_version, dims, v) values (%s,'text_chunk','span',%s,'m',1,%s,%s)"
    )
    wide = "[" + ",".join(["0.5"] * 4096) + "]"
    narrow = "[" + ",".join(["0.5"] * 1024) + "]"
    with spine.undone():
        spine.conn.execute(
            f"create table embedding_ws_test partition of embedding "
            f"for values in ('{spine.workspace}')"
        )

        # Honest width, real vector: accepted.
        with spine.conn.transaction():
            spine.conn.execute(insert, (spine.workspace, spine.span_id, 4096, wide))

        # A row claiming a width the column cannot hold.
        with pytest.raises(spine.psycopg.errors.CheckViolation), spine.conn.transaction():
            spine.conn.execute(insert, (spine.workspace, spine.span_id, 1024, wide))

        # A vector that is genuinely the wrong width. Under the old bytea substitution this
        # column accepted arbitrary bytes and this assertion could not have been written.
        with pytest.raises(spine.psycopg.Error), spine.conn.transaction():
            spine.conn.execute(insert, (spine.workspace, spine.span_id, 4096, narrow))


def test_the_tombstone_guard_fires_on_a_table_with_no_capture_id_column(spine):
    """The polymorphic guard the review found raised 'record NEW has no field capture_id' here.

    evidence_span carries none of capture_id, entity_id or t_start_ns under those names, so a
    single guard reading NEW.capture_id could not run at all. This asserts the replacement does.
    """
    with spine.undone():
        digest = bytes([9]) * 32
        spine.conn.execute(
            "insert into blob (blob_sha256, byte_size, media_type) values (%s, 1, 'image/jpeg')",
            (digest,),
        )
        cursor = spine.conn.cursor()
        cursor.execute(
            "insert into capture (workspace_id, blob_sha256) values (%s, %s) returning capture_id",
            (spine.workspace, digest),
        )
        capture_id = cursor.fetchone()[0]
        spine.conn.execute(
            "update capture set deleted_at = now() where capture_id = %s", (capture_id,)
        )
        spine.conn.execute(
            "insert into tombstone (workspace_id, scope, capture_id, requested_by) "
            "values (%s, 'capture', %s, %s)",
            (spine.workspace, capture_id, uuid.uuid4()),
        )
        with pytest.raises(spine.psycopg.Error, match="tombstoned"), spine.conn.transaction():
                spine.conn.execute(
                    "insert into evidence_span (workspace_id, blob_sha256, track_key, "
                    "t_start_ns, t_end_ns, modality, span_digest) "
                    "values (%s, %s, 'img', 0, 1, 'still_image', %s)",
                    (spine.workspace, digest, bytes([1]) * 32),
                )
