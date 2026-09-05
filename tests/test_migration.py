"""Checks over the migration files themselves.

Most of what is here is a text check, and a text check is deliberately the weaker half. It
cannot tell a rule the database enforces from a rule the file merely describes, and that
difference is the whole of defect 1: ``predicate.allows_kind`` was declared, documented as the
reason a model could not write a name, and enforced by nothing. So the behavioural half lives in
``test_epistemic_guard_postgres.py``, ``test_row_level_security.py`` and
``test_ingest_persistence.py``, all of which write the offending row and require a refusal.

What a text check is still good for is catching a rule that has been deleted or renamed out of
the file, which is why the assertions below name the specific mechanism rather than checking a
shape. If a guard is removed, something fails here even when no behavioural test happened to
cover the route it protected.

Every migration is covered. 0001 is the spine; 0002 closes the two defects that blocked
identity work, corrects the tombstone predicate from ``now()`` to ``clock_timestamp()``, and adds
the ingest admission function; 0003 adds the intake batch, which is the unit the interface calls
a capture and this schema does not; 0004 records a stage resolved from an existing artifact,
which the ledger previously left out of its own replay; 0005 seeds the reconstruction rung as
a claim a model may make and a capture may not carry as a fact.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from exulanica.migrations import Migration, migrations, verify_applied

from pg_harness import migrated_schema

ROOT = pathlib.Path(__file__).resolve().parents[1]

MIGRATIONS = {migration.version: migration.sql for migration in migrations()}
SQL = MIGRATIONS["0001"]
SQL_0002 = MIGRATIONS["0002"]

#: Every migration concatenated. A table added by a later file exists just as much as one in
#: 0001, and a required-table check that only read the spine would go green on a table nobody
#: ever created the day somebody moved a `create table` into a new file.
ALL_SQL = "\n".join(MIGRATIONS[version] for version in sorted(MIGRATIONS))

HISTORICAL_MIGRATION_CHECKSUMS = {
    "0001": "05909f3d36fba433f2adc22f57af4e0ce1cef5c8894a05d56fce8a6f53f6412e",
    "0002": "08250a55180ba6ac1174625d0e5007688a8f693664625aa4fddfe03a3e056300",
    "0003": "9e4304dae50f60b9e8d619e50c5200a60c9a1e20b3003b1da2e46b4dd5cd5173",
    "0004": "61040674bb27f37d40778a554c1cdefbf477ff07016c0b055ecc9704ddfe38fd",
    "0005": "0d005aa84a64554727105ad1f94265a7759a71cf4db0e32665718210fd603996",
    "0006": "e4e2110efec6269136596a35f656201b35dc536e00754aaaeb32f82afc87fa33",
    "0007": "1dde0d4134de293e3126a63650e43676188e0b378f27755618d2472301eb344a",
    "0008": "d0cbc0f413a1dbd5cb4a891ba0257f183ecd833be2216f178104bd7d78570386",
    "0009": "8f9bc42ce40d6a9ee6310b68d459e47643ac42c9c30f44eb8d4b4f38ef19e616",
    "0010": "0b8faf2bd38e9670bffcffdc7c646669da95b26c2fa6b9dd81f27a2ea15821aa",
    "0011": "e8424d8d9547f139ef9453216b46d6b17ca72012951140043eded2aac6ebad1b",
    "0012": "b70bb1261b079f3e593ffa0305ebcd9565e6c6710a7f0b3000e607cb9125779a",
    "0013": "98b775fac728553b08263631e2ef2f311eaba78724f13b7b8939e125edc64491",
    "0014": "46cc44a17b3af7d077858bfe09d3d5332d2f705afdb39af0464e9712ebbaf79d",
    "0015": "b66eed0e288a0b25994285dc44d7d7bc3843c15ac1ca500c623c5466665161a8",
    "0016": "369fb8a502220238149cf77faac2ffa7594f6001225c247bef725f916a453037",
    "0017": "7ebc764ba48f83f6a0cd60ca9b6c1e2a4e33434a99ca22a7f69ba490e36ded85",
    "0018": "53d6f3ada2ea50cdd3def16388bc6e7e70649a22f259f5a8937d7cb8856b66b1",
    "0019": "f1cb348a6cc7602a3b7192494f4fcaabf2e42a72328f1206be7b0f3c3aac0ead",
    "0020": "36f951579afb29cb930388f353a73f4893824e3f8a703a746534e8c78a7d4262",
    "0021": "b1579836aaae4d848db82e708a338c14f34e646d7bdf7bfec870d5ec9e9e65e4",
    "0022": "6fbce45468e39c3f2d0957ab36d25a7e4a97558e8623575b895af9bb3a567d6d",
    "0023": "4dcddc82fd95ccf78e4afac82f73cc487dc2d5884a02789b45fbc17bba061527",
    "0024": "bc11ed3928ec17b2bb4a1c1cf93d5e20403109e606e634e0b55384beaec74696",
    "0025": "2419f702b54764fc6015a2a72b64957db8ef8f9c37ac930f25a4155e04ffcd21",
    "0026": "92d59d62447265497e1e7d99e11690216622d3a880cf24c89b7888246eed3a26",
    "0027": "a462b000291f105ee056cbe0001aa875bdfce868dcd185eaa09db52917d10517",
    "0028": "dea14ffa802d37c6d56ef0571ea19b4eb280898dc1437ac5dc4653e511299257",
    "0029": "81e74e6e058fb7cb6717d2c866efea8ff43b1b6af9f17ebde1fc3c3795a78067",
    "0030": "05de5e5a7456bd606ff8d27d00f64d9de3310ad971bdf3598bc124cad3927401",
    "0031": "d26cc740342e95530838962e1567047b312cff8ac5569f5ff6ff5e65d2d3bffb",
    "0032": "49ca35fbfc9f4301a52bb927a23264c3f3477f1aa85fa424dbae8f223a8b2dc2",
    "0033": "86eb68c55fcae9385056a04ecc9d063183b03e520979480403e207a5f6ce3d84",
    "0034": "a499bf47d63d9a7ae7f2d043bc21131a6b26100acefd9b002684ecc5250b280c",
    "0035": "bc6ac3bf51058ce1ff4c9ad6ef6e7adccfe2133675cc17fda4702dca28e8ff2f",
}


def test_the_migrations_are_numbered_and_ordered():
    files = list(migrations())
    assert [m.version for m in files] == [
        f"{number:04d}" for number in range(1, len(files) + 1)
    ], [m.version for m in files]
    assert len(files) >= 8, "a migration went missing from the directory"


def test_historical_migrations_0001_through_0035_are_byte_identical():
    """The backend program freezes every previously applied migration byte for byte."""
    actual = {
        migration.version: migration.checksum.hex()
        for migration in migrations()
        if migration.version <= "0035"
    }
    assert actual == HISTORICAL_MIGRATION_CHECKSUMS


@pytest.mark.parametrize("migration", list(migrations()), ids=lambda m: m.version)
def test_every_migration_is_a_single_transaction_with_no_down_path(migration):
    sql = migration.sql
    statements = [line for line in sql.splitlines() if line and not line.startswith("--")]
    assert statements[0].strip() == "begin;"
    assert statements[-1].strip() == "commit;"
    assert sql.count("\nbegin;") == 1 and sql.count("\ncommit;") == 1
    lowered = sql.lower()
    # Forward-only. A drop in a migration is how a "reversible" schema quietly loses data.
    for banned in ("drop table", "drop column", "drop type", "rollback;"):
        assert banned not in lowered, f"forward-only migrations must not {banned}"


@pytest.mark.parametrize(
    "table",
    [
        "schema_migrations",
        "blob",
        "media_track",
        "capture",
        "capture_reconstruction_authorization",
        "clock_anchor",
        "evidence_span",
        "stage_registry",
        "stage_definition",
        "intake_batch",
        "pipeline_run",
        "pipeline_event",
        "artifact",
        "anchor_resolution",
        "predicate",
        "calibration",
        "assertion",
        "dispute",
        "retraction",
        "user_annotation",
        "occurrence",
        "entity",
        "entity_link",
        "match_proposal",
        "identity_rejection",
        "never_same",
        "identity_event",
        "derived_artifact",
        "embedding",
        "text_chunk",
        "consent_record",
        "tombstone",
        "purge_job",
        "job",
        "derivative_job_event",
        "world_style_capability_registry",
        "world_art_profile_registry",
        "world_art_profile_parameter",
        "world_style_module_registry",
        "world_style_module_capability",
        "world_art_profile_module",
        "world_topology_contract",
        "world_topology_region",
        "world_topology_source",
        "world_style_version",
        "world_region_style_version",
        "world_style_state",
        "world_style_proposal",
        "world_style_preview",
        "world_style_audit_event",
        "world_structure_snapshot",
        "world_structure_state",
        "world_structure_preview",
        "world_structure_snapshot_region",
        "world_structure_element_identity",
        "world_structure_snapshot_element",
        "world_structure_dependency",
        "world_structure_placement_migration",
        "world_structure_invalidation",
        "world_structure_audit_event",
        "interaction_capability_registry",
        "world_interaction_policy_version",
        "world_interaction_policy_state",
        "world_interaction_policy_proposal",
        "world_interaction_policy_preview",
        "world_interaction_policy_audit_event",
        "reconstruction_scene",
        "reconstruction_scene_build_member",
        "reconstruction_scene_job",
        "reconstruction_scene_job_member",
        "reconstruction_scene_member",
        "reconstruction_privacy_admission",
        "reconstruction_privacy_admission_member",
        "reconstruction_privacy_screening",
        "person_derivative_dependency",
        "person_withdrawal_receipt",
    ],
)
def test_every_required_table_exists(table):
    assert re.search(rf"create table (if not exists )?{table} \(", ALL_SQL)


def test_a_span_interval_is_half_open_and_never_empty():
    """The check that keeps [0, 0) out of the spine.

    Without it, an image span could be empty, and an empty range overlaps nothing, so the
    tombstone interval guard would pass every write it was meant to refuse.
    """
    assert "check (t_end_ns > t_start_ns)" in SQL
    assert "int8range(t_start_ns, t_end_ns, '[)')" in SQL


def test_the_extensions_the_indexes_need_are_declared():
    """btree_gist is not optional: without it three GiST indexes fail to build at all.

    Core GiST has no operator class for bytea or uuid, and every interval index in this schema
    leads with one of those.
    """
    for extension in ("vector", "pgcrypto", "pg_trgm", "btree_gist"):
        assert f"create extension if not exists {extension}" in SQL, extension


def test_the_span_digest_is_unique_per_workspace():
    assert "create unique index evidence_span_digest_uniq" in SQL


def test_the_interval_overlap_index_exists():
    """Co-presence, interval tombstones and 'what else is in this moment' all land on it."""
    assert "using gist (blob_sha256, t_range)" in SQL
    assert "using gist (capture_id, presence)" in SQL


def test_indexes_the_architecture_depends_on_are_present():
    for index in (
        "using gin (support_span_ids)",  # assertion -> spans
        "using gin (dep_index)",  # derived artifact invalidation
        "using gin (tsv)",  # lexical arm
        "using gin (body gin_trgm_ops)",  # trigram arm
        "using gist (workspace_id, valid_time)",  # bitemporal assertion lookup
        "using gin (output_artifact_ids)",  # assembly replay
    ):
        assert index in SQL, index


def test_an_occurrence_is_never_named_by_a_detector():
    """display_name lives on entity, never on occurrence, and only a 'user' assertion writes it."""
    occurrence_ddl = SQL.split("create table occurrence (")[1].split("\n);")[0]
    entity_ddl = SQL.split("create table entity (")[1].split("\n);")[0]
    assert "display_name" not in occurrence_ddl
    assert "display_name" in entity_ddl
    assert "'{user}'" in SQL  # name_is allows only the user kind


def test_a_confirmed_link_requires_a_human_decision():
    assert "constraint confirmed_needs_a_human" in SQL
    assert "state <> 'confirmed' or (decided_by is not null and method = 'user_confirm')" in SQL


def test_rejection_memory_is_keyed_by_evidence_not_by_a_pipeline_row():
    """Keying by occurrence_id resurrects every rejected proposal on the next detector run."""
    rejection_ddl = SQL.split("create table identity_rejection (")[1].split("\n);")[0]
    assert "occurrence_id" not in rejection_ddl
    assert "key_a" in rejection_ddl and "basis_digest" in rejection_ddl
    assert "revoked_at" in rejection_ddl  # undo is a revocation, never a DELETE
    assert "unique (workspace_id, scope, key_a, key_b, basis_digest)" in rejection_ddl


def test_the_four_provenance_classes_are_never_flattened():
    assert re.search(r"create type assertion_kind as enum", SQL)
    for kind in ("'capture'", "'inference'", "'user'", "'external'"):
        assert kind in SQL
    assert "constraint external_no_history" in SQL
    assert "constraint inference_support_required" in SQL


def test_allows_kind_is_enforced_rather_than_merely_declared():
    """The defect: allows_kind was a column no code path read.

    A live probe against the committed schema inserted kind='inference' against name_is with the
    value "Aunt Marjorie" and it landed with status='active'. The behavioural proof that this is
    now refused is in test_epistemic_guard_postgres.py; what is checked here is that the
    mechanism is present in the file at all, and that it has the four properties it needs.
    """
    assert "create or replace function tg_assertion_kind_is_allowed()" in SQL
    body = SQL.split("create or replace function tg_assertion_kind_is_allowed()")[1]
    body = body.split("$fn$;")[0]
    # It refuses rather than warns.
    assert "raise exception" in body
    # It fails closed on a missing predicate row rather than skipping the check.
    assert "v_allows is null" in body
    # `k = any(arr)` is NULL, not false, against a NULL element, and plpgsql accepts NULL.
    assert "coalesce(new.kind = any(v_allows), false)" in body
    # It cannot be defeated by a session that never declared a workspace.
    assert "perform assert_workspace_context(new.workspace_id);" in body


def test_the_epistemic_guard_covers_updates_as_well_as_inserts():
    """Otherwise insert-then-update is an unguarded route to the row the guard refuses."""
    assert (
        "before insert or update of kind, predicate_id on assertion" in SQL
    ), "the epistemic guard must fire on UPDATE too"


def test_the_vocabulary_cannot_be_edited_into_letting_a_model_name_someone():
    """Enforcement on assertions alone is one UPDATE on predicate away from irrelevant."""
    predicate_ddl = SQL.split("create table predicate (")[1].split("\n);")[0]
    assert "writes_a_name boolean not null default false" in predicate_ddl
    assert "constraint a_name_comes_only_from_the_user" in predicate_ddl
    assert "not writes_a_name or allows_kind <@ array['user']::assertion_kind[]" in predicate_ddl
    assert "constraint allows_kind_has_no_null_element" in predicate_ddl
    # The seed has to mark the one predicate the rule exists for.
    seed = SQL.split("insert into predicate")[1].split(";")[0]
    assert "'{user}',             true" in seed


def test_the_seed_comment_describes_enforcement_that_exists():
    """The comment that was false. It claimed a guarantee the schema did not provide.

    A comment is not testable in general, but this one names the mechanism, so the name can be
    required to resolve to something. If the guard is ever renamed or removed, this fails.
    """
    seed_section = SQL.split("-- 13. Seed vocabulary.")[1]
    assert "tg_assertion_kind_is_allowed()" in seed_section
    assert "a_name_comes_only_from_the_user" in seed_section
    for claimed in ("tg_assertion_kind_is_allowed()", "a_name_comes_only_from_the_user"):
        assert SQL.count(claimed) > 1, f"{claimed} is described but not defined"
    # The old wording, which was not true of the schema it annotated.
    assert "there is no code path in which a model writes a name onto anything" not in SQL


def test_the_embedding_column_carries_the_measured_width():
    """Runtime measurement recorded 4096 dimensions, and pgvector cannot index halfvec above
    4000."""
    embedding_ddl = SQL.split("create table embedding (")[1].split("\n);")[0]
    assert "halfvec(4096)" in embedding_ddl
    assert "check (dims = 4096)" in embedding_ddl
    # No ANN index on v: exact search is the decision, and it is recorded as one.
    assert "using hnsw" not in SQL and "using ivfflat" not in SQL


def test_a_re_import_after_deletion_is_possible():
    """Decision del-3. A total unique (workspace_id, blob_sha256) forbids it outright."""
    assert (
        "create unique index capture_live_bytes_uniq\n"
        "  on capture (workspace_id, blob_sha256) where deleted_at is null;" in SQL
    )
    capture_ddl = SQL.split("create table capture (")[1].split("\n);")[0]
    assert "unique (workspace_id, blob_sha256)" not in capture_ddl


def test_the_tombstone_guard_reads_only_columns_its_table_has():
    """The committed guard was one polymorphic function reading NEW.capture_id everywhere.

    plpgsql raises "record NEW has no field capture_id" the first time that fires on
    evidence_span. So each guard is checked against the columns of the table it is attached to.
    """
    columns = {
        "span": _column_names("evidence_span"),
        "occurrence": _column_names("occurrence"),
        "assertion": _column_names("assertion"),
        "embedding": _column_names("embedding"),
        "entity_link": _column_names("entity_link"),
    }
    for suffix, available in columns.items():
        # A parser that returned nothing would make the comparison below meaningless.
        assert "workspace_id" in available, f"failed to parse the columns of {suffix}"
        body = SQL.split(f"create or replace function tg_tombstone_guard_{suffix}()")[1]
        body = body.split("$fn$;")[0]
        referenced = set(re.findall(r"new\.([a-z_0-9]+)", body))
        assert referenced <= available, (
            f"tg_tombstone_guard_{suffix} reads {sorted(referenced - available)}, "
            f"which {suffix} does not have"
        )
        assert referenced, f"tg_tombstone_guard_{suffix} reads no NEW field at all"


#: Words that begin a table-level clause rather than a column.
_NOT_A_COLUMN = frozenset({"constraint", "unique", "primary", "check", "foreign", "exclude"})


def _column_names(table: str) -> set[str]:
    """Column names of one table, from its DDL.

    Columns sit at exactly two spaces of indentation; continuation lines of a multi-line CHECK
    are indented further, which is what keeps a string literal out of the result.
    """
    body = SQL.split(f"create table {table} (")[1].split("\n);")[0]
    names = set()
    for line in body.splitlines():
        match = re.match(r"^ {2}([a-z_0-9]+)\s+\S", line.split("--")[0])
        if match and match.group(1) not in _NOT_A_COLUMN:
            names.add(match.group(1))
    return names


def test_the_tombstone_guard_fires_on_every_derived_write_path():
    for table in ("evidence_span", "occurrence", "assertion", "embedding", "entity_link"):
        assert re.search(rf"before insert on {table}\b", SQL), table


def test_every_guard_asserts_the_workspace_context_before_it_trusts_a_lookup():
    """Otherwise the guard fails open, which is the worst direction for it to fail in.

    The guards read tombstone and evidence_span, both under FORCE row-level security. A session
    that never set exulanica.workspace_id sees them as empty and finds no tombstone. A BYPASSRLS
    role skips the policy entirely. Triggers are bypassed by neither, so the assertion belongs
    here rather than only in the policy.
    """
    assert "create or replace function assert_workspace_context(" in SQL
    for guard in (
        "tg_tombstone_guard_span",
        "tg_tombstone_guard_occurrence",
        "tg_tombstone_guard_assertion",
        "tg_tombstone_guard_embedding",
        "tg_tombstone_guard_entity_link",
    ):
        body = SQL.split(f"create or replace function {guard}()")[1].split("$fn$;")[0]
        assert "perform assert_workspace_context(new.workspace_id);" in body, guard


def test_current_workspace_is_defined_before_anything_calls_it():
    assert SQL.index("create or replace function current_workspace()") < SQL.index(
        "perform assert_workspace_context"
    )


def test_the_tombstone_guard_uses_a_fresh_snapshot():
    """A stable function reuses the statement snapshot, which reopens the race it closes."""
    assert "language sql volatile" in SQL
    guard = SQL.split("create or replace function tombstone_blocks_span(")[1]
    assert "language sql stable" not in guard.split("$fn$")[0]


def test_a_capture_tombstone_is_not_keyed_by_the_blob_hash():
    """A hash-keyed tombstone would silently blocklist a deliberate re-import."""
    tombstone_ddl = SQL.split("create table tombstone (")[1].split("\n);")[0]
    assert "blob_sha256" not in tombstone_ddl
    assert "blocklist_hash" in tombstone_ddl  # the explicit opt-in for the other intent


def test_a_re_import_after_a_deletion_is_not_blocked_by_a_uniqueness_error():
    """del-3 needs a PARTIAL unique index.

    A total unique (workspace_id, blob_sha256) makes the soft-deleted row collide with the
    re-import, so the deliberate re-upload the decision promises fails with a uniqueness error
    instead of proceeding. Live duplicates must still collapse to one capture, which is what the
    partial index preserves.
    """
    capture_ddl = SQL.split("create table capture (")[1].split("\n);")[0]
    assert "unique (workspace_id, blob_sha256)" not in capture_ddl
    assert (
        "create unique index capture_live_bytes_uniq\n"
        "  on capture (workspace_id, blob_sha256) where deleted_at is null" in SQL
    )


def test_the_embedding_column_is_the_width_gate_0_measured():
    """Runtime measurement recorded Qwen3-Embedding-8B at 4096 dimensions, and that document wins on
    conflict.

    pgvector indexes halfvec to at most 4000 dimensions, so 4096 cannot carry an ANN index at
    all: the consequence of storing the real width is exact search. A declared HNSW or IVFFlat
    index over this column would not build.
    """
    embedding_ddl = SQL.split("create table embedding (")[1].split("\n) partition by list")[0]
    assert "halfvec(4096)" in embedding_ddl
    assert "dims" in embedding_ddl  # the real width is recorded per row
    assert "halfvec(1024)" not in embedding_ddl
    assert "using hnsw" not in SQL
    assert "using ivfflat" not in SQL


def test_row_level_security_is_forced_not_merely_enabled():
    """ENABLE alone is bypassed by the table owner, which makes every policy inert."""
    assert "force  row level security" in SQL
    assert SQL.count("enable row level security") == SQL.count("force  row level security")


#: Every file that states in prose how many tables are workspace-isolated. Written out by hand,
#: because a list built by grepping the tree for the sentence would contain exactly the files
#: that still carry it and would go quiet on the one that stopped.
_FILES_STATING_THE_WORKSPACE_POLICY_COUNT = (
    "exulanica/db/session.py",
    "exulanica/ingest/spine/__init__.py",
    "tests/test_ingest_persistence.py",
)

#: The sentence those files carry. The number is the capture; the rest is the phrase that says
#: what the number counts, so a file that changed the subject fails rather than matching.
_WORKSPACE_POLICY_COUNT_CLAIM = re.compile(
    r"(\d+) tables are under FORCE row-level security keyed on\s+``current_workspace\(\)``"
)


@pytest.mark.postgres
def test_the_prose_count_of_workspace_isolated_tables_matches_the_schema():
    """Three docstrings state a number, and this is where the number comes from.

    The number was twenty, which is the length of the do-block array in 0001, and it was wrong
    by two for as long as three files repeated it: ``embedding`` is forced a few lines further
    down in 0001 on its own, and ``intake_batch`` arrives forced in 0003. A count carried in
    prose drifts every time a migration adds a table, so it is measured against a live schema
    here rather than remembered in three places.

    The count is of tables keyed on ``current_workspace()`` rather than of forced tables,
    because those are two different numbers: ``consent_record`` is forced and keyed on the
    tenant, so it is named below rather than folded into a total that would then mean neither
    thing. Partitions are excluded for the same reason: ``embedding_ws_*`` is created per
    workspace, so counting relations would make the number a function of how many workspaces
    happened to exist when it was taken.
    """
    with migrated_schema() as (_psycopg, conn):
        scratch = conn.execute("select current_schema()").fetchone()[0]
        forced = conn.execute(
            "select c.relname, coalesce(p.qual, '') from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "left join pg_policies p on p.schemaname = n.nspname and p.tablename = c.relname "
            "where n.nspname = %s and c.relforcerowsecurity and not c.relispartition",
            (scratch,),
        ).fetchall()

    workspace_keyed = sorted({name for name, qual in forced if "current_workspace()" in qual})
    others = sorted({name for name, _ in forced} - set(workspace_keyed))
    assert others == ["consent_record"], (
        f"{others} are under FORCE row-level security and not keyed on current_workspace(). "
        "The count below is of the workspace-keyed tables, so a new table in this list is a "
        "table the sentence in three docstrings does not describe."
    )
    for relative in _FILES_STATING_THE_WORKSPACE_POLICY_COUNT:
        stated = _WORKSPACE_POLICY_COUNT_CLAIM.findall(
            (ROOT / relative).read_text(encoding="utf-8")
        )
        assert stated, (
            f"{relative} no longer states how many tables are keyed on current_workspace(), so "
            "nothing checks the number it used to carry."
        )
        assert {int(number) for number in stated} == {len(workspace_keyed)}, (
            f"{relative} says {stated} and the schema has {len(workspace_keyed)}: "
            f"{workspace_keyed}"
        )


def test_consent_is_deny_by_default_and_expires():
    consent_ddl = SQL.split("create table consent_record (")[1].split("\n);")[0]
    assert "expires_at            timestamptz not null" in consent_ddl
    assert "adult_attested        boolean not null check (adult_attested = true)" in consent_ddl
    assert "notice_text_sha256" in consent_ddl  # the exact wording shown, hashed
    assert "constraint operator_attested_has_no_demo_scopes" in consent_ddl


def test_checksum_drift_refuses_to_start(tmp_path):
    migration = next(iter(migrations()))
    verify_applied({migration.version: migration.checksum})  # clean
    with pytest.raises(RuntimeError, match="checksum drift"):
        verify_applied({migration.version: b"\x00" * 32})
    with pytest.raises(RuntimeError, match="absent from the package"):
        verify_applied({"9999": b"\x00" * 32})


def test_a_checksum_is_stable_across_reads():
    migration = next(iter(migrations()))
    assert migration.checksum == Migration(migration.version, migration.path).checksum


# -- migration 0002 ---------------------------------------------------------------------


def test_a_user_statement_cannot_carry_a_producing_run():
    """R2. One UPDATE laundered a model row into a user-stated name, and the laundered row kept
    produced_by_run pointing at the pipeline run that made it. A claim the user made was not
    produced by a run, so the row is refusable on exactly that."""
    assert "constraint a_user_statement_has_no_producing_run" in SQL_0002
    assert "check (kind <> 'user' or produced_by_run is null)" in SQL_0002


def test_an_assertion_is_not_editable_in_place():
    """The other half of R2. Rewriting object_value bypasses supersedes and retraction, and
    every citation already issued against the row then points at a different claim."""
    body = SQL_0002.split("create or replace function tg_assertion_no_in_place_rewrite()")[1]
    body = body.split("$fn$;")[0]
    for column in (
        "kind",
        "predicate_id",
        "subject_ref",
        "object_value",
        "support_span_ids",
        "produced_by_run",
        "stated_by_user",
        "supersedes",
        "emit_key",
    ):
        assert f"new.{column}" in body, column
    # status, calibration_id and calibrated_p are the mutable surface and must NOT be listed.
    for mutable in ("new.status", "new.calibration_id", "new.calibrated_p"):
        assert mutable not in body, mutable
    assert "before update on assertion" in SQL_0002


def test_a_name_on_an_entity_requires_an_active_user_assertion():
    """R1. display_name was enforced by a comment, on the single most important column in
    canonical state."""
    body = SQL_0002.split("create or replace function tg_entity_name_is_user_stated()")[1]
    body = body.split("$fn$;")[0]
    assert "raise exception" in body
    assert "a.kind         = 'user'" in body
    assert "a.status       = 'active'" in body
    # Matched on the vocabulary flag, never on the key 'name_is', so a later 'nickname_is'
    # cannot escape the rule by being spelled differently.
    assert "p.writes_a_name" in body
    assert "name_is" not in body
    assert "perform assert_workspace_context(new.workspace_id);" in body
    assert "before insert or update of display_name on entity" in SQL_0002


def test_a_retracted_name_does_not_survive_on_the_entity():
    """A name that outlives the statement supporting it is the failure the deletion design
    exists to prevent."""
    assert "create or replace function tg_entity_name_follows_its_assertion()" in SQL_0002
    assert "after update of status on assertion" in SQL_0002
    body = SQL_0002.split("create or replace function tg_entity_name_follows_its_assertion()")[1]
    body = body.split("$fn$;")[0]
    assert "set display_name = null" in body
    assert "perform assert_workspace_context(new.workspace_id);" in body


def test_the_tombstone_predicates_use_the_wall_clock_rather_than_the_transaction_clock():
    """now() is transaction_timestamp(), pinned when the WRITING transaction began.

    0001 made the tombstone functions VOLATILE specifically so a tombstone committed during a
    write would be seen. It is seen, and then discarded by `effective_at <= now()`, because its
    effective_at is later than the writing transaction's start. Measured: the row is visible,
    the predicate is false, and the guard returns false. The volatility bought nothing until
    this changed.
    """
    for function in (
        "tombstone_blocks_span",
        "tombstone_blocks_capture",
        "tombstone_blocks_entity",
        "tombstone_admits_new_capture",
    ):
        body = SQL_0002.split(f"create or replace function {function}(")[1].split("$fn$;")[0]
        assert "effective_at <= clock_timestamp()" in body, function
        assert "effective_at <= now()" not in body, function
    # And no executable line anywhere in the file still carries the old predicate. Comments
    # quote it deliberately, which is why they are stripped rather than searched.
    executable = "\n".join(
        line for line in SQL_0002.splitlines() if not line.lstrip().startswith("--")
    )
    assert "effective_at <= now()" not in executable
    assert executable.count("effective_at <= clock_timestamp()") == 4


def test_the_admission_function_omits_only_the_capture_branch():
    """It answers a different question from tombstone_blocks_span: "given that I am about to
    register a live capture for these bytes, will the span write be refused?" The capture branch
    of the guard fires precisely because no live capture exists yet, so including it would
    refuse every deliberate re-import."""
    body = SQL_0002.split("create or replace function tombstone_admits_new_capture(")[1]
    body = body.split("$fn$;")[0]
    assert "t.scope = 'workspace'" in body
    assert "t.blocklist_hash" in body
    assert "t.scope = 'interval'" in body
    assert "t.scope = 'capture'" not in body
    assert "language sql volatile" in body


def test_migration_0002_records_no_checksum_of_its_own():
    """The runner writes schema_migrations. A migration that writes its own row invents a
    checksum, and verify_applied then compares the file against a number the file chose."""
    assert "insert into schema_migrations" not in SQL_0002


@pytest.mark.postgres
def test_the_migration_actually_applies():
    """Runs only against a real PostgreSQL server.

    Everything above is a text check. This is the test that proves the SQL parses, that the
    multirange types are present, and that every trigger and function from both migrations
    attaches.

    The earlier version of this test applied the migration to ``public`` and then called
    ``rollback()``. That does not undo it: the migration contains its own ``commit;``, so the
    schema was already committed and the next run failed on "type already exists". The shared
    harness applies it to a throwaway schema and drops that schema instead.
    """
    with migrated_schema() as (_psycopg, conn):
        scratch = conn.execute("select current_schema()").fetchone()[0]
        tables = conn.execute(
            "select count(*) from information_schema.tables where table_schema = %s",
            (scratch,),
        ).fetchone()
        assert tables is not None and tables[0] >= 30
        triggers = conn.execute(
            "select trigger_name from information_schema.triggers "
            "where trigger_schema = %s",
            (scratch,),
        ).fetchall()
        names = {row[0] for row in triggers}
        for trigger in (
            "tg_assertion_kind_is_allowed",
            "tg_guard_span",
            "tg_guard_occurrence",
            "tg_guard_assertion",
            "tg_guard_embedding",
            "tg_guard_entity_link",
            # 0002. Without these three, identity work has no enforcement behind it.
            "tg_assertion_no_in_place_rewrite",
            "tg_entity_name_is_user_stated",
            "tg_entity_name_follows_its_assertion",
        ):
            assert trigger in names, trigger
        functions = {
            row[0]
            for row in conn.execute(
                "select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
                "where n.nspname = %s",
                (scratch,),
            ).fetchall()
        }
        assert "tombstone_admits_new_capture" in functions
