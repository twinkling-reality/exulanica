"""The place plane, executed against a real PostgreSQL server rather than read off the file.

``docs/place-identity.md`` decides that a place is a durable plane of its own and not an entity,
not a region and not a column on a scene. Every rule that decision leans on is written as a
constraint in ``0038`` rather than as prose, and these tests write the offending row and require
the database to refuse it. A text check over the migration cannot tell a rule the database
enforces from a rule the file describes, which is the distinction ``test_epistemic_guard_postgres``
exists to make and the one that found a declared-but-unenforced guard in the first place.

Each test names the failure it catches, not the constraint it calls.

Running them: set ``EXULANICA_TEST_DATABASE_URL`` to a scratch database. Without it these skip,
which is the normal state on a machine with no server.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from exulanica.epistemics import AssertionWriter
from exulanica.identity import IdentityRepository, name_occurrence

from pg_harness import migrated_schema

pytestmark = pytest.mark.postgres


class _Rollback(Exception):
    """Raised to unwind a savepoint after a write that was supposed to succeed."""


class Plane:
    """A migrated schema, one workspace, and two scenes a place could be built from."""

    def __init__(self, psycopg, conn, workspace, scene_a, scene_b, blob) -> None:
        self.psycopg = psycopg
        self.conn = conn
        self.workspace = workspace
        self.scene_a = scene_a
        self.scene_b = scene_b
        self.blob = blob

    @contextmanager
    def undone(self) -> Iterator[None]:
        try:
            with self.conn.transaction():
                yield
                raise _Rollback
        except _Rollback:
            pass

    def refuses(self, sql: str, params: tuple) -> str:
        with pytest.raises(self.psycopg.Error) as raised, self.undone():
            self.conn.execute(sql, params)
        return str(raised.value)

    def accepts(self, sql: str, params: tuple) -> None:
        with self.undone():
            self.conn.execute(sql, params)

    def place(self) -> uuid.UUID:
        return self.conn.execute(
            "insert into place (workspace_id) values (%s) returning place_id", (self.workspace,)
        ).fetchone()[0]

    def receipt(self, place_id: uuid.UUID) -> uuid.UUID:
        """One artifact naming a place, which is what an alignment receipt is."""
        return self.conn.execute(
            "insert into artifact (artifact_id, workspace_id, kind, stage_key, stage_version, "
            "params_digest, input_digest, idempotency_key, place_id) "
            "values (%s, %s, 'place_alignment_receipt', 'place_alignment', 1, %s, %s, %s, %s) "
            "returning artifact_id",
            (
                uuid.uuid4(),
                self.workspace,
                bytes(32),
                bytes(32),
                f"place-alignment:{uuid.uuid4()}",
                place_id,
            ),
        ).fetchone()[0]

    def alignment(self, place_id: uuid.UUID, *, accepted: bool = True) -> uuid.UUID:
        alignment_id = uuid.uuid4()
        self.conn.execute(
            "insert into place_alignment (alignment_id, workspace_id, place_id, "
            "candidate_scene_id, against_scene_id, union_member_digest, policy_digest, "
            "accepted, reason, receipt_artifact_id) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                alignment_id,
                self.workspace,
                place_id,
                self.scene_b,
                self.scene_a,
                uuid.uuid4().bytes + uuid.uuid4().bytes,
                bytes(32),
                accepted,
                None if accepted else "place-alignment-inconsistent",
                self.receipt(place_id),
            ),
        )
        return alignment_id

    def count(self, table: str) -> int:
        """A row count that survives the row factory changing under us.

        ``IdentityRepository`` and ``AssertionWriter`` both set ``row_factory = dict_row`` on the
        connection they are handed, and this fixture is module-scoped, so one test that names an
        occurrence changes how every later test's rows are shaped.
        """
        row = self.conn.execute(f"select count(*) as n from {table}").fetchone()
        return row["n"] if isinstance(row, dict) else row[0]

    def place_occurrence(self) -> uuid.UUID:
        """One place the vision stage would have proposed: a whole-image label over a photograph."""
        capture_id = self.conn.execute(
            "select capture_id from reconstruction_scene_member "
            " where workspace_id = %s and scene_id = %s",
            (self.workspace, self.scene_a),
        ).fetchone()[0]
        span_id = self.conn.execute(
            "insert into evidence_span (workspace_id, blob_sha256, track_key, t_start_ns, "
            "t_end_ns, modality, span_digest) values (%s, %s, 'img', 0, 1, 'still_image', %s) "
            "returning span_id",
            (self.workspace, self.blob, uuid.uuid4().bytes + uuid.uuid4().bytes),
        ).fetchone()[0]
        run_id = self.conn.execute(
            "insert into pipeline_run (workspace_id, trigger) values (%s, 'ingest') "
            "returning run_id",
            (self.workspace,),
        ).fetchone()[0]
        return self.conn.execute(
            "insert into occurrence (workspace_id, capture_id, class, primary_span_id, span_ids, "
            "presence, produced_by_run, detector_version, identity_key, emit_key) "
            "values (%s, %s, 'place', %s, %s, '{[0,1)}', %s, 'v1', %s, %s) "
            "returning occurrence_id",
            (
                self.workspace,
                capture_id,
                span_id,
                [span_id],
                run_id,
                uuid.uuid4().bytes + uuid.uuid4().bytes,
                f"place-occurrence:{uuid.uuid4()}",
            ),
        ).fetchone()[0]

    def anchor(self, place_id: uuid.UUID, scene_id: uuid.UUID | None = None) -> None:
        self.conn.execute(
            "insert into place_version (workspace_id, place_id, scene_id, ordinal, "
            "ordered_by_utc, ordered_by_basis, frame_hops) "
            "values (%s, %s, %s, 0, now(), 'capture_exif', 0)",
            (self.workspace, place_id, scene_id or self.scene_a),
        )


def _scene(cursor, workspace: uuid.UUID, blob: bytes, digest: bytes) -> uuid.UUID:
    scene_id = uuid.uuid4()
    cursor.execute(
        "insert into reconstruction_scene (scene_id, workspace_id, member_digest) "
        "values (%s, %s, %s)",
        (scene_id, workspace, digest),
    )
    capture_id = uuid.uuid4()
    cursor.execute(
        "insert into capture (capture_id, workspace_id, blob_sha256) values (%s, %s, %s)",
        (capture_id, workspace, blob),
    )
    cursor.execute(
        "insert into reconstruction_scene_member (workspace_id, scene_id, capture_id, ordinal) "
        "values (%s, %s, %s, 0)",
        (workspace, scene_id, capture_id),
    )
    return scene_id


@pytest.fixture(scope="module")
def plane():
    with migrated_schema() as (psycopg, conn):
        workspace = uuid.uuid4()
        cursor = conn.cursor()
        cursor.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace),))
        # One capture per (workspace, blob), so two scenes need two distinct sets of bytes.
        blobs = [bytes([n]) * 32 for n in (1, 2)]
        for digest in blobs:
            cursor.execute(
                "insert into blob (blob_sha256, byte_size, media_type) "
                "values (%s, 1, 'image/jpeg')",
                (digest,),
            )
        scene_a = _scene(cursor, workspace, blobs[0], bytes([1]) * 32)
        scene_b = _scene(cursor, workspace, blobs[1], bytes([2]) * 32)
        blob = blobs[0]
        conn.commit()
        yield Plane(psycopg, conn, workspace, scene_a, scene_b, blob)


@pytest.fixture(autouse=True)
def isolated(plane):
    """Every test writes places and versions, so every test runs inside its own savepoint.

    Without this the module-scoped scenes fill up: the first test to bind ``scene_a`` to a place
    makes every later test's bind a duplicate, and the failure that surfaces is a unique violation
    on the fixture rather than the constraint the test was written to probe.
    """
    try:
        with plane.conn.transaction():
            yield
            raise _Rollback
    except _Rollback:
        pass


def test_a_scene_claimed_by_two_places_is_refused(plane):
    """Two places holding one scene would be two coordinate frames claiming one capture set.

    This is the rule ``docs/place-identity.md`` states in prose and the one a join written by hand
    would break first, because binding a scene twice looks like an ordinary second insert.
    """
    first, second = plane.place(), plane.place()
    plane.anchor(first)
    message = plane.refuses(
        "insert into place_version (workspace_id, place_id, scene_id, ordinal, ordered_by_utc, "
        "ordered_by_basis, frame_hops) values (%s, %s, %s, 0, now(), 'capture_exif', 0)",
        (plane.workspace, second, plane.scene_a),
    )
    assert "place_version_workspace_id_scene_id_key" in message


def test_a_place_with_two_anchors_is_refused(plane):
    """A second anchor is a second shared frame, and the versions would disagree silently."""
    place_id = plane.place()
    plane.anchor(place_id)
    message = plane.refuses(
        "insert into place_version (workspace_id, place_id, scene_id, ordinal, ordered_by_utc, "
        "ordered_by_basis, frame_hops) values (%s, %s, %s, 1, now(), 'capture_exif', 0)",
        (plane.workspace, place_id, plane.scene_b),
    )
    assert "place_version_one_anchor_idx" in message


def test_a_version_measured_against_nothing_is_refused(plane):
    """A frame with hops and no receipt is a transform no alignment produced.

    The anchor is the one version that legitimately arrives unmeasured, because its transform is
    identity by construction. Every other version has a receipt or it has no business existing.
    """
    place_id = plane.place()
    plane.anchor(place_id)
    message = plane.refuses(
        "insert into place_version (workspace_id, place_id, scene_id, ordinal, ordered_by_utc, "
        "ordered_by_basis, frame_hops) values (%s, %s, %s, 1, now(), 'capture_exif', 1)",
        (plane.workspace, place_id, plane.scene_b),
    )
    assert "only_the_anchor_arrives_unmeasured" in message


def test_an_anchor_carrying_a_receipt_is_refused(plane):
    """The other half of the same rule: the anchor was not admitted by an alignment."""
    place_id = plane.place()
    alignment_id = plane.alignment(place_id)
    message = plane.refuses(
        "insert into place_version (workspace_id, place_id, scene_id, ordinal, ordered_by_utc, "
        "ordered_by_basis, frame_hops, admitted_by_alignment_id) "
        "values (%s, %s, %s, 0, now(), 'capture_exif', 0, %s)",
        (plane.workspace, place_id, plane.scene_a, alignment_id),
    )
    assert "only_the_anchor_arrives_unmeasured" in message


def test_a_version_with_no_time_that_does_not_say_so_is_refused(plane):
    """A null capture time with a stated basis is a time the basis cannot account for.

    A scene has no capture-time column, so the time here was recorded at bind time from something.
    A version whose time could not be established has to say `unavailable`, because the alternative
    is a null that reads as "not looked up yet" and is really "there was nothing to look up".
    """
    place_id = plane.place()
    message = plane.refuses(
        "insert into place_version (workspace_id, place_id, scene_id, ordinal, ordered_by_utc, "
        "ordered_by_basis, frame_hops) values (%s, %s, %s, 0, null, 'capture_exif', 0)",
        (plane.workspace, place_id, plane.scene_a),
    )
    assert "a_missing_time_says_so" in message


def test_an_unavailable_time_carrying_a_timestamp_is_refused(plane):
    place_id = plane.place()
    message = plane.refuses(
        "insert into place_version (workspace_id, place_id, scene_id, ordinal, ordered_by_utc, "
        "ordered_by_basis, frame_hops) values (%s, %s, %s, 0, now(), 'unavailable', 0)",
        (plane.workspace, place_id, plane.scene_a),
    )
    assert "a_missing_time_says_so" in message


def test_a_refusal_with_no_reason_is_refused(plane):
    """A refused alignment whose reason is null is the one outcome this design must read back.

    ``docs/place-identity.md`` makes refusal an outcome rather than an error precisely so the world
    can say two captures are of related places whose frames could not be reconciled. It cannot say
    that from a row with no reason.
    """
    place_id = plane.place()
    message = plane.refuses(
        "insert into place_alignment (alignment_id, workspace_id, place_id, candidate_scene_id, "
        "against_scene_id, union_member_digest, policy_digest, accepted, reason, "
        "receipt_artifact_id) values (%s, %s, %s, %s, %s, %s, %s, false, null, %s)",
        (
            uuid.uuid4(),
            plane.workspace,
            place_id,
            plane.scene_b,
            plane.scene_a,
            bytes(32),
            bytes(32),
            plane.receipt(place_id),
        ),
    )
    assert "a_refusal_says_why" in message


def test_an_acceptance_carrying_a_refusal_reason_is_refused(plane):
    place_id = plane.place()
    message = plane.refuses(
        "insert into place_alignment (alignment_id, workspace_id, place_id, candidate_scene_id, "
        "against_scene_id, union_member_digest, policy_digest, accepted, reason, "
        "receipt_artifact_id) values (%s, %s, %s, %s, %s, %s, %s, true, "
        "'place-alignment-inconsistent', %s)",
        (
            uuid.uuid4(),
            plane.workspace,
            place_id,
            plane.scene_b,
            plane.scene_a,
            bytes(32),
            bytes(32),
            plane.receipt(place_id),
        ),
    )
    assert "a_refusal_says_why" in message


def test_a_refusal_reason_outside_the_fitters_vocabulary_is_refused(plane):
    """The three reasons are the ones `place_alignment.py` can return, and free text is not one."""
    place_id = plane.place()
    message = plane.refuses(
        "insert into place_alignment (alignment_id, workspace_id, place_id, candidate_scene_id, "
        "against_scene_id, union_member_digest, policy_digest, accepted, reason, "
        "receipt_artifact_id) values (%s, %s, %s, %s, %s, %s, %s, false, 'it did not work', %s)",
        (
            uuid.uuid4(),
            plane.workspace,
            place_id,
            plane.scene_b,
            plane.scene_a,
            bytes(32),
            bytes(32),
            plane.receipt(place_id),
        ),
    )
    assert "place_alignment_reason_check" in message


def test_an_alignment_against_itself_is_refused(plane):
    """One scene jointly reconstructed with itself measures nothing and would fit perfectly."""
    place_id = plane.place()
    message = plane.refuses(
        "insert into place_alignment (alignment_id, workspace_id, place_id, candidate_scene_id, "
        "against_scene_id, union_member_digest, policy_digest, accepted, receipt_artifact_id) "
        "values (%s, %s, %s, %s, %s, %s, %s, true, %s)",
        (
            uuid.uuid4(),
            plane.workspace,
            place_id,
            plane.scene_a,
            plane.scene_a,
            bytes(32),
            bytes(32),
            plane.receipt(place_id),
        ),
    )
    assert "an_alignment_is_between_two_scenes" in message


def test_an_artifact_naming_a_scene_and_a_place_is_refused(plane):
    """0024's rule survives the widening: exactly one subject, now chosen from three.

    An artifact about both is an artifact whose readers disagree about what it is about, and both
    readers find a row.
    """
    place_id = plane.place()
    message = plane.refuses(
        "insert into artifact (artifact_id, workspace_id, kind, stage_key, stage_version, "
        "params_digest, input_digest, idempotency_key, scene_id, place_id) "
        "values (%s, %s, 'place_alignment_receipt', 'place_alignment', 1, %s, %s, %s, %s, %s)",
        (
            uuid.uuid4(),
            plane.workspace,
            bytes(32),
            bytes(32),
            f"two-subjects:{uuid.uuid4()}",
            plane.scene_a,
            place_id,
        ),
    )
    assert "an_artifact_names_one_subject" in message


def test_an_artifact_naming_no_subject_at_all_is_refused(plane):
    """The widening's other edge: three nullable columns make "none" expressible for the first
    time, and a subjectless artifact is unreachable from every reader in the system."""
    message = plane.refuses(
        "insert into artifact (artifact_id, workspace_id, kind, stage_key, stage_version, "
        "params_digest, input_digest, idempotency_key) "
        "values (%s, %s, 'place_alignment_receipt', 'place_alignment', 1, %s, %s, %s)",
        (uuid.uuid4(), plane.workspace, bytes(32), bytes(32), f"no-subject:{uuid.uuid4()}"),
    )
    assert "an_artifact_names_one_subject" in message


def test_an_artifact_naming_only_a_place_is_accepted(plane):
    """The point of the widening. Without this the other two tests would pass on a schema that
    refused everything."""
    place_id = plane.place()
    plane.accepts(
        "insert into artifact (artifact_id, workspace_id, kind, stage_key, stage_version, "
        "params_digest, input_digest, idempotency_key, place_id) "
        "values (%s, %s, 'place_alignment_receipt', 'place_alignment', 1, %s, %s, %s, %s)",
        (
            uuid.uuid4(),
            plane.workspace,
            bytes(32),
            bytes(32),
            f"one-subject:{uuid.uuid4()}",
            place_id,
        ),
    )


def test_a_place_with_no_anchor_is_blocked(plane):
    """The empty case fails closed, the same shape `tombstone_blocks_scene` uses.

    A guard that reads an unbuilt place as available is the failure this catches: the place exists
    as a row before its first alignment lands, and for that window it has no frame at all.
    """
    place_id = plane.place()
    blocked = plane.conn.execute(
        "select tombstone_blocks_place(%s, %s) as blocked", (plane.workspace, place_id)
    ).fetchone()[0]
    assert blocked is True


def test_a_place_whose_anchor_capture_was_deleted_is_blocked(plane):
    """A withdrawn anchor takes the place with it, because every version's frame is the anchor's.

    Serving the other versions would be serving geometry expressed in a frame recovered from
    photographs somebody withdrew, which routes around the withdrawal rather than honouring it.
    """
    place_id = plane.place()
    if True:
        plane.anchor(place_id)
        assert (
            plane.conn.execute(
                "select tombstone_blocks_place(%s, %s) as blocked", (plane.workspace, place_id)
            ).fetchone()[0]
            is False
        )
        plane.conn.execute(
            "update capture set deleted_at = now() where capture_id in "
            "(select capture_id from reconstruction_scene_member "
            "  where workspace_id = %s and scene_id = %s)",
            (plane.workspace, plane.scene_a),
        )
        assert (
            plane.conn.execute(
                "select tombstone_blocks_place(%s, %s) as blocked", (plane.workspace, place_id)
            ).fetchone()[0]
            is True
        )


def test_a_place_row_cannot_be_updated(plane):
    """Append-only, like every other durable record here. A place has no mutable field by design:
    naming is the identity plane's job and the frame is a version's."""
    place_id = plane.place()
    message = plane.refuses(
        "update place set created_at = now() where workspace_id = %s and place_id = %s",
        (plane.workspace, place_id),
    )
    assert "place is append-only" in message


def test_a_place_version_cannot_be_deleted(plane):
    """A version unbound by deletion would leave its alignment receipt describing a join that the
    row set no longer records."""
    place_id = plane.place()
    plane.anchor(place_id)
    message = plane.refuses(
        "delete from place_version where workspace_id = %s and place_id = %s",
        (plane.workspace, place_id),
    )
    assert "place_version is append-only" in message


def test_all_three_place_tables_are_forced_and_workspace_keyed(plane):
    """Read off the live catalog, because ENABLE alone is bypassed by the table owner.

    This is a catalog assertion and not an isolation probe: this harness connects as the schema
    owner, and a superuser bypasses row-level security outright, so a cross-workspace read here
    would report zero rows for a reason that has nothing to do with the policy. The executed
    probe under a non-owner role is
    ``test_row_level_security.py::test_a_workspace_reads_its_own_rows_and_no_other_workspace_sees_them``,
    which 0038 added ``place`` to.
    """
    rows = dict(
        plane.conn.execute(
            "select c.relname, coalesce(p.qual, '') from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "left join pg_policies p on p.schemaname = n.nspname and p.tablename = c.relname "
            "where n.nspname = current_schema() and c.relforcerowsecurity "
            "  and c.relname in ('place', 'place_version', 'place_alignment')"
        ).fetchall()
    )
    assert sorted(rows) == ["place", "place_alignment", "place_version"], (
        f"{sorted(rows)}: a place table that is enabled but not FORCED leaves the workspace-keyed "
        "count at 65, so the three prose docstrings need no edit and nothing notices."
    )
    for table, qual in rows.items():
        assert "current_workspace()" in qual, f"{table} is forced against something else: {qual}"


def test_naming_a_place_a_person_saw_creates_no_place_row(plane):
    """A label is not a measurement, and this is the checkable form of that sentence.

    ``occurrence_class`` has carried `'place'` since 0001 and means a place observed in one
    photograph. The vision stage still emits those, ``name_occurrence`` turns one into an entity
    whose class is copied from it, and ``tests/test_selection.py:163`` has said so for as long as
    it has existed: "Places are entities too, and the same mechanism names them." That path is
    correct and 0038 does not touch it.

    What must never happen is the convenience a future implementer would reach for: naming a place
    also creating the durable place, so that a user who typed "kitchen" gets a coordinate frame
    they never photographed twice. There is no code doing that today, which is exactly why this
    test exists: it is the guard against a helpful trigger nobody would think to argue with.
    """
    occurrence_id = plane.place_occurrence()
    before = plane.count("place")
    # Both of these set row_factory to dict_row on the connection they are handed, and this
    # fixture is module-scoped, so the change would outlive this test and reshape every later
    # one's rows. Restored rather than worked around, because a fixture whose row shape depends on
    # test order is a fixture that fails somewhere other than where it broke.
    original_factory = plane.conn.row_factory
    try:
        named = name_occurrence(
            IdentityRepository(plane.conn, plane.workspace),
            AssertionWriter(plane.conn, plane.workspace),
            occurrence_id=occurrence_id,
            display_name="Gullfoss",
            actor=uuid.uuid4(),
        )
        entity_class = plane.conn.execute(
            "select class as c from entity where entity_id = %s", (named.entity_id,)
        ).fetchone()["c"]
    finally:
        plane.conn.row_factory = original_factory
    assert entity_class == "place", "the naming path stopped producing a place entity"
    after = plane.count("place")
    assert after == before, (
        "naming a place occurrence created a row on the geometric plane. A place is admitted by a "
        "joint reconstruction and never by a label, and this is the write that would break that."
    )


def test_admitting_a_place_version_creates_no_entity(plane):
    """The other direction: geometry is not a name.

    An accepted alignment must not mint an entity, because an entity is the plane where a user
    assertion carries a name, and nothing here said anything. A place with no name is the ordinary
    case and stays the ordinary case.
    """
    before = plane.count("entity")
    place_id = plane.place()
    plane.anchor(place_id)
    alignment_id = plane.alignment(place_id)
    plane.conn.execute(
        "insert into place_version (workspace_id, place_id, scene_id, ordinal, ordered_by_utc, "
        "ordered_by_basis, frame_hops, admitted_by_alignment_id) "
        "values (%s, %s, %s, 1, now(), 'capture_exif', 1, %s)",
        (plane.workspace, place_id, plane.scene_b, alignment_id),
    )
    after = plane.count("entity")
    assert after == before, "admitting a place version wrote to the identity plane"
