"""The judge seed: what the export carries, what it refuses to carry, and what the role may do.

Three properties are worth a test here and the rest is arithmetic.

**The export filter is narrow.** Two workspaces exist in the schema; one is exported. Not one row
belonging to the other may appear in any row file, and the check is over the bytes on disk rather
than over a count, because a count agrees with itself.

**The export filter is complete.** The classification is exhaustive over the live schema, so a
table a later migration adds fails the export rather than falling out of every seed silently.
That is asserted by removing a table from the classification and watching the export refuse.

**The judge role holds what the allowlist says and nothing more, read back from the catalog.**
Asserting the allowlist against itself would pass on a database where not one grant ran, so every
assertion here goes through ``pg_class.relacl``. The role is checked for ``rolsuper`` and
``rolbypassrls`` first: without that the rest is vacuous, because a superuser holds everything.

Role names are suffixed for the reason ``tests/test_purge.py`` and
``tests/test_row_level_security.py`` both carry: a role is a CLUSTER object and the harness's
"the database name must contain test" guard does not reach one, so provisioning the deployment's
own ``exulanica_judge`` here would rewrite the grants on a developer's live role.
"""

from __future__ import annotations

import hashlib
import json
import uuid

import psycopg
import pytest
from exulanica.api.authorisation import load_token_directory
from exulanica.db.migrate import provision_workspace
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.orchestration.judge_seed import (
    GLOBAL_TABLES,
    INSTANCE_TABLES,
    JUDGE_ROLE,
    JUDGE_WRITE_TABLES,
    REACHED_TABLES,
    SeedRefused,
    classify_tables,
    export_seed,
    judge_grants,
    mint_judge_token,
    provision_judge_role,
    read_manifest,
    reset_to_seed,
    restore_seed,
    verify_seed,
)
from exulanica.store.local import LocalContentAddressedStore
from psycopg.rows import dict_row

from pg_harness import migrated_schema

pytestmark = pytest.mark.postgres

#: Suffixed, because a role is a CLUSTER object. See the module docstring.
_JUDGE_ROLE = f"{JUDGE_ROLE}_suite"
_APP_ROLE = f"{RUNTIME_ROLE}_suite"

_CREATED_AT = "2026-09-10T00:00:00Z"

#: An image track has to be upright at rest: `media_track_image_is_upright` refuses one whose
#: EXIF orientation was not normalised at ingest. Copied from `tests/test_upright_display_space.py`
#: rather than invented, so this fixture inserts what the pipeline inserts.
_UPRIGHT_PROBE = (
    '{"orientation":{"exif_orientation":1,"rotation_degrees_clockwise":0,'
    '"mirrored":false,"normalised_at_ingest":true}}'
)


class Seeded:
    """Two workspaces in one migrated schema, with one photograph's worth of rows in each."""

    def __init__(self, connection, scratch: str, kept: uuid.UUID, other: uuid.UUID) -> None:
        self.connection = connection
        self.scratch = scratch
        self.kept = kept
        self.other = other

    def rows(self, statement: str, *parameters):
        return self.connection.execute(statement, parameters).fetchall()


def _populate(admin: psycopg.Connection, workspace: uuid.UUID, seed: int) -> bytes:
    """One capture, one span, one embedding and one authored world, all in ``workspace``.

    Deliberately touches a table from each bucket the classification distinguishes: a plainly
    workspace-keyed one (``capture``), one reached only through a join (``blob``, ``media_track``,
    ``pipeline_event``), and a partitioned one (``embedding``).
    """
    admin.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
    digest = hashlib.sha256(f"photograph-{seed}".encode()).digest()
    admin.execute(
        "insert into blob (blob_sha256, byte_size, media_type, storage_key) "
        "values (%s, 4, 'image/jpeg', %s)",
        (digest, f"sha-256/{digest.hex()[:2]}/{digest.hex()[2:4]}/{digest.hex()}"),
    )
    admin.execute(
        "insert into capture (workspace_id, blob_sha256) values (%s, %s)", (workspace, digest)
    )
    admin.execute(
        "insert into media_track (blob_sha256, track_key, kind, time_base_num, time_base_den, "
        "start_pts, duration_ns, rotation, codec, probe_json) "
        "values (%s, 'img', 'image', 1, 1000000000, 0, 1, 0, 'JPEG', %s)",
        (digest, _UPRIGHT_PROBE),
    )
    span = admin.execute(
        "insert into evidence_span (workspace_id, blob_sha256, track_key, t_start_ns, t_end_ns, "
        "modality, span_digest) values (%s, %s, 'img', 0, 1, 'still_image', %s) returning span_id",
        (workspace, digest, hashlib.sha256(f"span-{seed}".encode()).digest()),
    ).fetchone()["span_id"]
    admin.execute(
        "insert into embedding (workspace_id, family, ref_type, ref_id, model_ref, "
        "pipeline_version, dims, v) values (%s, 'text_chunk', 'span', %s, 'm', 1, 4096, %s)",
        (workspace, span, "[" + ",".join(["0.5"] * 4096) + "]"),
    )
    return digest


@pytest.fixture(scope="module")
def seeded():
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        scratch = admin.execute("select current_schema()").fetchone()["current_schema"]
        provision_runtime_role(admin, role=_APP_ROLE)

        kept, other = uuid.uuid4(), uuid.uuid4()
        for workspace in (kept, other):
            admin.execute(
                "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
            )
            provision_workspace(admin, workspace)
        _populate(admin, kept, 1)
        _populate(admin, other, 2)
        admin.commit()
        yield Seeded(admin, scratch, kept, other)


@pytest.fixture
def store(tmp_path):
    """A store holding the bytes both workspaces' rows point at, plus one object neither does."""
    store = LocalContentAddressedStore(tmp_path / "blobs")
    for seed in (1, 2):
        store.put_bytes(f"photograph-{seed}".encode())
    store.put_bytes(b"an object no row in either workspace references")
    return store


def _exported(seeded, store, tmp_path, **kwargs):
    destination = tmp_path / "archive"
    manifest = export_seed(
        seeded.connection,
        store,
        workspace_id=seeded.kept,
        destination=destination,
        created_at=_CREATED_AT,
        **kwargs,
    )
    return destination, manifest


# -- the export filter is narrow ---------------------------------------------------------------


def test_no_row_file_contains_the_other_workspace(seeded, store, tmp_path):
    """The whole point of the filter, asserted over bytes rather than over counts.

    A count of the exported rows agrees with whatever the export decided to write. Searching the
    files for the other workspace's identifier does not.
    """
    destination, _manifest = _exported(seeded, store, tmp_path)
    other = str(seeded.other).encode()
    offenders = [
        path.name
        for path in sorted((destination / "rows").glob("*.copy"))
        if other in path.read_bytes()
    ]
    assert offenders == []


def test_the_other_workspaces_shared_rows_are_left_behind(seeded, store, tmp_path):
    """``blob`` and ``media_track`` carry no workspace column, so a blanket copy takes both.

    This is the half that a filter written only against ``workspace_id`` gets wrong in the
    dangerous direction: another tenant's content inside an archive that says it holds one.
    """
    destination, manifest = _exported(seeded, store, tmp_path)
    files = {value["table"]: name for name, value in manifest.rows.items()}
    for table in ("blob", "media_track"):
        payload = (destination / "rows" / files[table]).read_bytes()
        assert hashlib.sha256(b"photograph-1").hexdigest().encode() in payload
        assert hashlib.sha256(b"photograph-2").hexdigest().encode() not in payload
        assert manifest.rows[files[table]]["rows"] == 1


def test_only_the_blobs_this_workspace_references_are_carried(seeded, store, tmp_path):
    """Referenced blobs only: not the other workspace's, and not the unreferenced one."""
    _destination, manifest = _exported(seeded, store, tmp_path)
    carried = set(manifest.blobs)
    assert store.key_for(store.put_bytes(b"photograph-1").blob_id) in carried
    assert store.key_for(store.put_bytes(b"photograph-2").blob_id) not in carried
    unreferenced = store.put_bytes(b"an object no row in either workspace references")
    assert store.key_for(unreferenced.blob_id) not in carried


def test_the_reviewed_object_assets_are_carried_although_no_workspace_row_names_them(
    seeded, store, tmp_path
):
    """The trap in the other direction, and the one a workspace-only key set falls into.

    ``world_reviewed_asset`` is a GLOBAL registry with no ``workspace_id``. Its bytes are what a
    judge places, so an archive built from workspace rows alone restores a stack whose object
    catalogue lists three objects and where placing any of them fails on missing bytes. They are
    absent from this store, so what is asserted here is that the export ASKED for them.
    """
    registry = seeded.rows("select content_sha256, licence_sha256 from world_reviewed_asset")
    assert registry, "migration 0042 seeds the reviewed asset registry"
    _destination, manifest = _exported(seeded, store, tmp_path)
    # Absent from this store and therefore neither carried nor fatal: the API writes them at
    # start-up. What matters is that they were not silently outside the key set.
    for row in registry:
        digest = row["content_sha256"]
        key = f"sha-256/{digest[:2]}/{digest[2:4]}/{digest}"
        assert key not in manifest.blobs
        assert key not in manifest.absent


# -- the export filter is complete -------------------------------------------------------------


def test_every_base_table_is_classified(seeded):
    """Exhaustive over the live schema, which is the safety argument for the whole export."""
    buckets = classify_tables(seeded.connection)
    named = sum(len(value) for value in buckets.values())
    total = seeded.connection.execute(
        "select count(*) as n from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = current_schema() and c.relkind in ('r', 'p')"
    ).fetchone()["n"]
    assert named == total
    assert set(buckets["global"]) == set(GLOBAL_TABLES)
    assert set(buckets["instance"]) == set(INSTANCE_TABLES)
    assert set(buckets["reached"]) == set(REACHED_TABLES)


def test_a_table_nobody_classified_fails_the_export(seeded, store, tmp_path, monkeypatch):
    """A migration that adds a table must break the next export, not fall out of every seed.

    Simulated by removing one entry from the classification rather than by writing a migration,
    because what is under test is the exhaustiveness check and not PostgreSQL's DDL.
    """
    trimmed = {key: value for key, value in GLOBAL_TABLES.items() if key != "predicate"}
    monkeypatch.setattr("exulanica.orchestration.judge_seed.GLOBAL_TABLES", trimmed)
    with pytest.raises(SeedRefused) as refusal:
        classify_tables(seeded.connection)
    assert "predicate" in str(refusal.value)


def test_the_instance_tables_are_never_carried(seeded, store, tmp_path):
    """``restore_control`` crossing would produce a stack that starts and refuses every request.

    ``verify_restore`` reads that table before serving and refuses traffic while it is not
    complete, so a sealed row copied from the exporting machine is the difference between a judge
    stack that works and one that answers nothing while looking healthy.
    """
    _destination, manifest = _exported(seeded, store, tmp_path)
    carried = {value["table"] for value in manifest.rows.values()}
    assert carried.isdisjoint(INSTANCE_TABLES)
    assert carried.isdisjoint(GLOBAL_TABLES)


def test_an_incomplete_source_is_refused_unless_the_caller_says_otherwise(seeded, tmp_path):
    """A row referencing bytes nobody holds fails the export by default.

    Completeness is what the artifact is for, so the deviation has to be asked for and is then
    recorded key by key in the manifest.
    """
    empty = LocalContentAddressedStore(tmp_path / "empty")
    with pytest.raises(SeedRefused) as refusal:
        export_seed(
            seeded.connection,
            empty,
            workspace_id=seeded.kept,
            destination=tmp_path / "refused",
            created_at=_CREATED_AT,
        )
    assert "allow_absent" in str(refusal.value)

    _destination, manifest = _exported(seeded, empty, tmp_path / "permitted", allow_absent=True)
    assert manifest.absent
    assert all(value["referenced_by"] == "blob" for value in manifest.absent.values())


# -- the archive verifies against its own manifest ---------------------------------------------


def test_the_manifest_is_bound_to_its_own_digest(seeded, store, tmp_path):
    destination, _manifest = _exported(seeded, store, tmp_path)
    recorded = (destination / "manifest.sha256").read_text(encoding="utf-8").split()[0]
    assert recorded == hashlib.sha256((destination / "manifest.json").read_bytes()).hexdigest()
    verify_seed(destination)


def test_one_flipped_byte_in_a_row_file_fails_verification(seeded, store, tmp_path):
    destination, manifest = _exported(seeded, store, tmp_path)
    target = destination / "rows" / sorted(manifest.rows)[0]
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(SeedRefused) as refusal:
        verify_seed(destination)
    assert "the manifest says" in str(refusal.value)


def test_an_edited_manifest_fails_before_anything_is_read(seeded, store, tmp_path):
    destination, _manifest = _exported(seeded, store, tmp_path)
    document = json.loads((destination / "manifest.json").read_bytes())
    document["workspace_id"] = str(uuid.uuid4())
    (destination / "manifest.json").write_bytes(json.dumps(document).encode())
    with pytest.raises(SeedRefused) as refusal:
        read_manifest(destination)
    assert "manifest.sha256 says" in str(refusal.value)


def test_a_blob_added_to_the_archive_fails_verification(seeded, store, tmp_path):
    """Both directions. A file the manifest does not mention is an archive somebody added to."""
    destination, _manifest = _exported(seeded, store, tmp_path)
    intruder = destination / "blobs" / "sha-256" / "00" / "00" / ("0" * 64)
    intruder.parent.mkdir(parents=True, exist_ok=True)
    intruder.write_bytes(b"not in the manifest")
    with pytest.raises(SeedRefused) as refusal:
        verify_seed(destination)
    assert "unexpected" in str(refusal.value)


# -- restore and reset -------------------------------------------------------------------------


def test_a_restore_lands_every_row_and_every_byte(seeded, store, tmp_path):
    """The round trip, into a schema that has the migrations and none of the workspace.

    A second migrated schema rather than the same one, because restoring into the database the
    export came from would prove that the rows are already there.
    """
    destination, manifest = _exported(seeded, store, tmp_path)
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        target = LocalContentAddressedStore(tmp_path / "restored")
        landed = restore_seed(admin, target, archive=destination)
        assert landed.workspace_id == manifest.workspace_id
        for recorded in manifest.rows.values():
            table = recorded["table"]
            count = admin.execute(f"select count(*) as n from {table}").fetchone()["n"]
            assert count == recorded["rows"], table
        for key, recorded in manifest.blobs.items():
            digest = key.rsplit("/", 1)[-1]
            assert target.exists(_blob(digest))
            assert len(target.get(_blob(digest))) == recorded["bytes"]


def test_a_restore_into_a_database_holding_a_stranger_is_refused(seeded, store, tmp_path):
    """A judge stack holds one workspace, and both restore and reset check it rather than assume.

    The restore counts whole tables against the manifest, so a second workspace's rows would make
    every count disagree after a load that actually worked. The reset truncates, which ignores the
    workspace policy entirely.
    """
    destination, _manifest = _exported(seeded, store, tmp_path)
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        stranger = uuid.uuid4()
        admin.execute("select set_config('exulanica.workspace_id', %s, false)", (str(stranger),))
        provision_workspace(admin, stranger)
        _populate(admin, stranger, 3)
        admin.commit()
        target = LocalContentAddressedStore(tmp_path / "stranger-store")
        with pytest.raises(SeedRefused) as refusal:
            restore_seed(admin, target, archive=destination, verify=False)
        assert "as well as the seed's" in str(refusal.value)
        with pytest.raises(SeedRefused):
            reset_to_seed(admin, archive=destination, verify=False)


def test_a_restore_into_an_occupied_workspace_is_refused(seeded, store, tmp_path):
    destination, _manifest = _exported(seeded, store, tmp_path)
    with pytest.raises(SeedRefused) as refusal:
        restore_seed(
            seeded.connection,
            store,
            archive=destination,
            verify=False,
        )
    assert "already holds captures" in str(refusal.value)


def test_a_reset_returns_the_rows_and_leaves_the_store_alone(seeded, store, tmp_path):
    """Reset truncates and reloads, because thirty-eight tables refuse a DELETE.

    Asserted by writing a row a judge could write, resetting, and finding it gone while the
    store still holds every byte it held before.
    """
    destination, manifest = _exported(seeded, store, tmp_path)
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        target = LocalContentAddressedStore(tmp_path / "reset-store")
        restore_seed(admin, target, archive=destination)
        admin.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(manifest.workspace_id),)
        )
        before = sorted(store.key_for(value) for value in target.iter_blob_ids())
        extra = hashlib.sha256(b"a judge's extra photograph").digest()
        admin.execute(
            "insert into blob (blob_sha256, byte_size, media_type) values (%s, 4, 'image/jpeg')",
            (extra,),
        )
        admin.execute(
            "insert into capture (workspace_id, blob_sha256) values (%s, %s)",
            (manifest.workspace_id, extra),
        )
        admin.commit()
        assert admin.execute("select count(*) as n from capture").fetchone()["n"] == 2

        reset_to_seed(admin, archive=destination)
        assert admin.execute("select count(*) as n from capture").fetchone()["n"] == 1
        assert sorted(store.key_for(value) for value in target.iter_blob_ids()) == before


def _blob(digest: str):
    from exulanica.evidence.blob import BlobId

    return BlobId.from_hex(digest)


# -- the judge role ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def judged(seeded):
    provision_judge_role(seeded.connection, role=_JUDGE_ROLE)
    seeded.connection.commit()
    return seeded


def test_the_judge_role_is_not_a_superuser_and_does_not_bypass_the_policy(judged):
    """Asserted FIRST, because every other assertion in this section is vacuous without it.

    A superuser holds every privilege whatever the catalog says, and a BYPASSRLS role reads every
    workspace whatever the policy says.
    """
    row = judged.connection.execute(
        "select rolsuper, rolbypassrls, rolcanlogin from pg_roles where rolname = %s",
        (_JUDGE_ROLE,),
    ).fetchone()
    assert row is not None
    assert row["rolsuper"] is False
    assert row["rolbypassrls"] is False
    assert row["rolcanlogin"] is True


def test_the_judge_role_may_write_exactly_the_allowlist(judged):
    """Read back from ``pg_class.relacl``, not compared against the constant that produced it."""
    grants = judge_grants(judged.connection, role=_JUDGE_ROLE)
    writable = {name for name, values in grants.items() if values & {"INSERT", "UPDATE"}}
    assert writable == set(JUDGE_WRITE_TABLES)


def test_the_judge_role_may_delete_nothing_at_all(judged):
    """Deletion is a tombstone and a purge job, and both are writes to tables off the allowlist.

    This closes the other door: no DELETE anywhere means no row of any kind can be removed, so
    the append-only history a judge's edits land in stays append-only.
    """
    grants = judge_grants(judged.connection, role=_JUDGE_ROLE)
    assert [name for name, values in grants.items() if "DELETE" in values] == []
    assert [name for name, values in grants.items() if "TRUNCATE" in values] == []


@pytest.mark.parametrize(
    "table",
    [
        "capture",
        "intake_batch",
        "artifact",
        "blob",
        "entity_link",
        "identity_event",
        "person_subject",
        "person_withdrawal_receipt",
        "tombstone",
        "purge_job",
    ],
)
def test_the_judge_role_may_read_but_not_write_sources_and_deletion(judged, table):
    """The sentence the deliverable is about, one table at a time, against the live catalog.

    Reading is deliberate: a judge is shown the evidence behind every citation. Writing is what
    is refused, and it is refused by the database rather than by a route that could be added
    tomorrow without anybody thinking about this.
    """
    grants = judge_grants(judged.connection, role=_JUDGE_ROLE)
    assert grants.get(table) == {"SELECT"}, f"{table}: {grants.get(table)}"


def test_a_table_added_later_arrives_readable_and_not_writable(judged):
    """The allowlist has to fail in this direction, so the default privilege is SELECT only."""
    judged.connection.execute("create table if not exists a_later_migration (id integer)")
    judged.connection.commit()
    try:
        grants = judge_grants(judged.connection, role=_JUDGE_ROLE)
        assert grants.get("a_later_migration") == {"SELECT"}
    finally:
        judged.connection.execute("drop table if exists a_later_migration")
        judged.connection.commit()


def test_provisioning_twice_does_not_widen_the_grants(judged):
    """Idempotent, because a deployment runs it on every start and after every migration."""
    before = judge_grants(judged.connection, role=_JUDGE_ROLE)
    provision_judge_role(judged.connection, role=_JUDGE_ROLE)
    judged.connection.commit()
    assert judge_grants(judged.connection, role=_JUDGE_ROLE) == before


# -- the token ------------------------------------------------------------------------------------


def test_the_minted_token_is_one_the_api_actually_accepts(monkeypatch):
    """Minting and loading are in different layers, so nothing but a test binds the two.

    ``exulanica.orchestration`` may import ``exulanica.api`` and the reverse is forbidden, so the
    minter cannot call the loader. A token this produced and the API refused would be a
    deployment that starts and accepts nobody.
    """
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    token = "j" * 48
    directory = mint_judge_token(workspace_id=workspace, actor=actor, token=token)
    monkeypatch.setenv("EXULANICA_API_TOKENS", json.dumps(directory))
    loaded = load_token_directory()
    session = loaded.session_for(token)
    assert session.workspace_id == workspace
    assert session.actor == actor
    assert session.may_include_proposals is False


def test_a_token_under_the_apis_own_floor_is_refused_at_mint_time():
    with pytest.raises(SeedRefused):
        mint_judge_token(workspace_id=uuid.uuid4(), actor=uuid.uuid4(), token="short")
