"""A fact about N photographs, and the deletion of one of them.

ADR-0009 D9. Every artifact before migration 0024 is keyed to exactly one source blob, which is
what the purge cascade and the export projector join on, and a pose receipt, a splat and a
placement record are facts about a set. D9 gives them a subject and requires that deletion reach
it: "a tombstone path that reaches a scene artifact through any of its members".

**The reduction inverts, and that is what every test here is about.** For an artifact of one
photograph the question is an OR over the captures holding a blob: imported twice is one artifact
and two captures, and deleting one withdraws nothing. ``purge_releases_bytes`` and
``orimera/graph/geometry.py`` both read that way and are right to. For a fact about eight
photographs, deleting ONE withdraws it, because a receipt over eight is not a claim about the
seven that are left.

**Three members, and the one that is deleted is the middle one.** D9's no-ship rule is "the test
that deletes one of N members and asserts the bytes are released and the export changes", and a
test that deleted every member would pass on either reduction, which is the failure the defect
register calls this project's recurring one. Two members would leave the surviving-member
assertions trivial. The middle one rather than an end, because the presentation order this
workspace is read in is ``started_at`` then ``capture_id``, so a deletion at either end would be
indistinguishable from an off-by-one in anything that walks the list.

Both halves of the no-ship rule are here, under "the export" below: the bytes go through the
purge queue and the export through ``orimera/world_package/projector.py``. They are in one file
rather than split across this and ``tests/test_world_package_postgres.py`` because D9 states them
as one rule, and a reader checking whether it is met should not have to find the second half.
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
import uuid
from pathlib import Path

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.db.roles import (
    PURGE_CROSS_WORKSPACE_TABLES,
    PURGE_ROLE,
    RUNTIME_ROLE,
    provision_purge_role,
    provision_runtime_role,
)
from exulanica.deletion import queue
from exulanica.deletion.worker import PurgeWorker
from exulanica.env import env_get
from exulanica.epistemics.vocabulary import RECONSTRUCTION_SCENE_RUNG_PREDICATE
from exulanica.evidence import EvidenceAddress
from exulanica.evidence.blob import BlobId
from exulanica.evidence.scene import scene_id_for, scene_member_digest
from exulanica.graph import SceneRungRow, scene_rung_rows
from exulanica.graph.scene_groups import rung_by_capture
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.scene_rung import record_scene_rung
from exulanica.reconstruction.scene_gate import SceneGateDecision
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world_package import diff_packages, project_world_package

from conftest import CountingVisionModel, iso, write_photo, write_point_map

#: Suffixed, because a role is a CLUSTER object and the harness's "the database name must contain
#: test" guard does not reach one. See the same comment in ``tests/test_purge.py``.
_PURGE_ROLE = f"{PURGE_ROLE}_scene"
_APP_ROLE = f"{RUNTIME_ROLE}_scene"
_PURGE_PASSWORD = secrets.token_urlsafe(32)
_APP_PASSWORD = secrets.token_urlsafe(32)

#: The receipt's own bytes, distinct from every photograph and from every point map, so that a
#: test which destroyed the wrong object says so rather than passing because two payloads
#: happened to be equal.
_RECEIPT = b"a pose receipt over three photographs"


class SceneWorkspace:
    """Three photographs, a scene over all three, and a receipt that is a fact about the set."""

    def __init__(self, repository, store, scratch, captures, scene_id, receipt_id) -> None:
        self.repository = repository
        self.store = store
        self.scratch = scratch
        self.workspace_id = repository.workspace_id
        #: In ingest order. ``captures[1]`` is the member every deletion test removes.
        self.captures = captures
        self.scene_id = scene_id
        self.receipt_id = receipt_id
        self.receipt_digest = BlobId.of_bytes(_RECEIPT)

    def rows(self, sql: str, *params):
        return self.repository.connection.execute(sql, params).fetchall()

    def one(self, sql: str, *params):
        return self.repository.connection.execute(sql, params).fetchone()

    def releases(self, blob: BlobId) -> bool:
        """Ask the destroy predicate directly, which is what the worker does before acting."""
        row = self.one(
            "select purge_releases_bytes(%s) as releases", blob.digest
        )
        assert row is not None
        return bool(row["releases"])

    def blocked(self, scene_id: uuid.UUID | None = None) -> bool:
        row = self.one(
            "select tombstone_blocks_scene(%s, %s) as blocked",
            self.workspace_id,
            scene_id or self.scene_id,
        )
        assert row is not None
        return bool(row["blocked"])

    def delete(self, capture_id: uuid.UUID) -> uuid.UUID:
        """Delete a photograph the way the product does, which is one call and nothing else.

        No ``update capture set deleted_at``. That line in ``tests/test_purge.py``'s helper was
        migration 0015's defect 1: the fixture supplied a production step the shipping code did
        not have, and every test passed against a flow that did not exist.
        """
        return self.repository.insert_tombstone(
            scope="capture",
            capture_id=capture_id,
            requested_by=uuid.uuid4(),
            reason="the user deleted this photograph",
        )

    def database(self, *, role: str | None = None, password: str | None = None):
        import urllib.parse

        from exulanica.db.session import Database

        base = env_get("TEST_DATABASE_URL")
        assert base is not None
        options = urllib.parse.quote(f"-csearch_path={self.scratch},public", safe="")
        url = f"{base}{'&' if '?' in base else '?'}options={options}"
        if role is not None:
            parsed = urllib.parse.urlsplit(url)
            netloc = f"{role}:{password}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            url = urllib.parse.urlunsplit(parsed._replace(netloc=netloc))
        return Database(url=url)

    def export(self, output: Path, *, parent: str | None = None):
        """Project a package the way the command line does, one consistent snapshot."""
        return project_world_package(
            self.repository.connection,
            workspace_id=self.workspace_id,
            actor=uuid.uuid4(),
            output=output,
            private_key=Ed25519PrivateKey.generate(),
            parent_merkle_root_sha256=parent,
        )

    @staticmethod
    def reconstruction(result) -> dict:
        return json.loads((result.output / "reconstruction/artifacts.json").read_text())

    def worker(self) -> PurgeWorker:
        return PurgeWorker(
            self.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD),
            self.store,
            frozenset({self.workspace_id}),
            name="test-scene-purge",
        )


def _insert_scene(
    workspace, capture_ids, *, registered: list[bool | None] | None = None
) -> uuid.UUID:
    """Write a scene and its members with raw SQL, because nothing in ``orimera/`` writes one.

    That is deliberate rather than missing. D9 says no scene-level artifact ships before this
    test exists, so the identity and the deletion path land before any producer does, and a test
    that drove a producer would be waiting on one. It is the same arrangement
    ``test_a_person_scoped_withdrawal_reaches_no_derivative`` uses to write a tombstone the
    product cannot express.
    """
    scene_id = scene_id_for(capture_ids)
    workspace.repository.connection.execute(
        "insert into reconstruction_scene (scene_id, workspace_id, member_digest) "
        "values (%s, %s, %s)",
        (scene_id, workspace.workspace_id, scene_member_digest(capture_ids)),
    )
    registration = registered if registered is not None else [True] * len(capture_ids)
    if len(registration) != len(capture_ids):
        raise ValueError("one registration value is required for each scene member")
    for ordinal, (capture_id, did_register) in enumerate(
        zip(capture_ids, registration, strict=True)
    ):
        workspace.repository.connection.execute(
            "insert into reconstruction_scene_member "
            "(workspace_id, scene_id, capture_id, ordinal, registered) "
            "values (%s, %s, %s, %s, %s)",
            (workspace.workspace_id, scene_id, capture_id, ordinal, did_register),
        )
    return scene_id


def _insert_scene_artifact(
    workspace, scene_id: uuid.UUID, payload: bytes = _RECEIPT
) -> uuid.UUID:
    """A pose receipt over a scene, in the store and in the spine.

    ``stage_key`` names a stage that is not in the registry, and that is honest rather than
    sloppy: no pose stage exists, ``artifact`` carries no foreign key onto the registry, and the
    descriptor read left-joins ``stage_definition`` precisely so that a row whose definition was
    never recorded reports None rather than a guess.

    **The identity key carries the payload digest as well as the scene**, and that is not
    tidiness. Keyed on the scene alone, a second call for one scene collides with
    ``unique (workspace_id, idempotency_key)`` and raises ``UniqueViolation``, which is an
    ``IntegrityError`` and is indistinguishable from the refusal a tombstone guard raises. The
    write-guard test below passed on that collision with the guard removed entirely, which is
    the "test that passes without exercising its case" the defect register calls this project's
    recurring failure.
    """
    stored = workspace.store.put_bytes(payload)
    artifact_id = uuid.uuid4()
    workspace.repository.connection.execute(
        "insert into artifact (artifact_id, workspace_id, kind, scene_id, stage_key, "
        "stage_version, params_digest, input_digest, idempotency_key, content_sha256, "
        "storage_key, byte_size) "
        "values (%s, %s, 'pose_receipt', %s, 'pose', 1, %s, %s, %s, %s, %s, %s)",
        (
            artifact_id,
            workspace.workspace_id,
            scene_id,
            b"\x01" * 32,
            b"\x02" * 32,
            f"pose:{scene_id}:{stored.blob_id.hex}",
            stored.blob_id.digest,
            workspace.store.key_for(stored.blob_id),
            stored.byte_size,
        ),
    )
    return artifact_id


def _record_gate_rung(workspace, scene_id: uuid.UUID, run_id: uuid.UUID):
    members = workspace.repository.reconstruction_scene_members(scene_id)
    registered = sum(member.registered is True for member in members)
    decision = SceneGateDecision(
        rung=3 if registered else 4,
        member_count=len(members),
        registered_member_count=registered,
        reasons=("the durable gate recorded this test decision",),
        receipts=(),
    )
    return record_scene_rung(
        workspace.repository,
        scene_id=scene_id,
        run_id=run_id,
        decision=decision,
    ), decision


@pytest.fixture
def scene(tmp_path, photo_dir, repository, spine_schema):
    """Three photographs, each with its own point map, one scene over all three, one receipt."""
    _psycopg, scratch = spine_schema
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())

    captures = []
    for name, when, payload in (
        ("a.jpg", iso(9), b"point map for a"),
        ("b.jpg", iso(10), b"point map for b"),
        ("c.jpg", iso(11), b"point map for c"),
    ):
        outcome = pipeline.ingest_file(write_photo(photo_dir, name, when=when))
        assert outcome.error is None, outcome.error
        blob = BlobId.of_bytes((photo_dir / name).read_bytes())
        write_point_map(repository, store, blob, payload)
        captures.append(
            repository.connection.execute(
                "select capture_id from capture where blob_sha256 = %s", (blob.digest,)
            ).fetchone()["capture_id"]
        )

    import urllib.parse

    from exulanica.db.session import Database

    base = env_get("TEST_DATABASE_URL")
    assert base is not None
    options = urllib.parse.quote(f"-csearch_path={scratch},public", safe="")
    owner = Database(url=f"{base}{'&' if '?' in base else '?'}options={options}")
    with owner.unscoped() as connection:
        connection.execute(f"set search_path to {scratch}, public")
        provision_runtime_role(connection, role=_APP_ROLE, password=_APP_PASSWORD)
        provision_purge_role(connection, role=_PURGE_ROLE, password=_PURGE_PASSWORD)

    workspace = SceneWorkspace(repository, store, scratch, captures, None, None)
    workspace.scene_id = _insert_scene(
        workspace, captures, registered=[True, False, True]
    )
    workspace.receipt_id = _insert_scene_artifact(workspace, workspace.scene_id)
    return workspace


# -- the identity ------------------------------------------------------------------------------


def test_a_scene_id_is_the_same_on_every_machine_and_in_any_order():
    """Deterministic, order independent, and duplicate free, because the subject is a set."""
    first = uuid.UUID("018f0000-0000-7000-8000-000000000001")
    second = uuid.UUID("018f0000-0000-7000-8000-000000000002")
    third = uuid.UUID("018f0000-0000-7000-8000-000000000003")

    assert scene_id_for([first, second, third]) == scene_id_for([third, first, second])
    assert scene_id_for([first, second, first]) == scene_id_for([first, second])
    assert scene_id_for([first, second]) != scene_id_for([first, second, third])
    # Spelled out rather than derived from the function under test. An expectation written as
    # `scene_id_for(members)` would agree with any implementation, including one that returned a
    # constant.
    assert str(scene_id_for([first])) == str(uuid.uuid5(
        uuid.UUID("2b7c9e14-5d38-5a4f-8c61-7e0d9a3b5f28"),
        scene_member_digest([first]).hex(),
    ))


def test_the_scene_digest_is_frozen_to_these_exact_bytes():
    """A golden value, because every input to this digest is a constant nothing else pins.

    ``scene_id`` is the primary key of ``reconstruction_scene``, the target of
    ``artifact.scene_id``'s composite foreign key, and the join key of every membership row.
    Its inputs are the namespace, the format version and the domain separator, and all three are
    frozen the moment a producer writes its first scene: changing any of them makes
    ``scene_id_for`` return a different uuid for photographs that already have one, so the
    existing rows become unreachable by derivation.

    **The other tests in this file cannot catch that**, because each of them reaches the
    constants only through the function under test and therefore agrees with any value. Measured,
    not supposed: the domain separator was silently changed to a placeholder string in this
    working tree and the whole 1222-test suite stayed green. This is the test that goes red.

    The expectation is spelled out. Deriving it from ``scene_member_digest`` would be the exact
    mistake ``test_a_scene_id_is_the_same_on_every_machine_and_in_any_order`` warns about, one
    level down.
    """
    members = [
        uuid.UUID("018f0000-0000-7000-8000-000000000001"),
        uuid.UUID("018f0000-0000-7000-8000-000000000002"),
        uuid.UUID("018f0000-0000-7000-8000-000000000003"),
    ]
    assert scene_member_digest(members).hex() == (
        "6c508e1469fae04523b9be123fe84cf361daec95872a6e0c7192a5154c119d9f"
    )
    assert str(scene_id_for(members)) == "6c45661b-9120-5d4e-9921-e43b8be75391"
    # A second set, so a digest that ignored its members entirely would still fail.
    assert scene_member_digest(members[:1]).hex() == (
        "517b3ab4dfe7e85dde51e493f3871ebc55b5f3c6f2e1006eda0ecf8d8b304e22"
    )
    assert str(scene_id_for(members[:1])) == "f5944f44-14eb-51c3-8bd9-3ade5f965171"


def test_a_scene_of_no_photographs_has_no_identity():
    """A digest over nothing is a name every empty question would share."""
    with pytest.raises(ValueError, match="cannot be empty"):
        scene_id_for([])


# -- the subject -------------------------------------------------------------------------------


def test_an_artifact_names_a_scene_or_a_photograph_and_never_both(scene):
    """The check constraint is what survives ``source_blob_sha256`` losing ``not null``.

    Relaxing that column is the one widening migration 0024 makes, and without this an artifact
    could name a scene and a photograph at once, which is two subjects for one claim, or neither,
    which is a derivative of nothing.
    """
    blob = scene.rows("select blob_sha256 from capture order by capture_id")[0]["blob_sha256"]
    for description, source, scene_id in (
        ("both", bytes(blob), scene.scene_id),
        ("neither", None, None),
    ):
        with (
            pytest.raises(psycopg.errors.CheckViolation),
            scene.repository.connection.transaction(),
        ):
            scene.repository.connection.execute(
                "insert into artifact (artifact_id, workspace_id, kind, source_blob_sha256, "
                "scene_id, stage_key, stage_version, params_digest, input_digest, "
                "idempotency_key) values (%s, %s, 'pose_receipt', %s, %s, 'pose', 1, %s, %s, %s)",
                (
                    uuid.uuid4(),
                    scene.workspace_id,
                    source,
                    scene_id,
                    b"\x01" * 32,
                    b"\x02" * 32,
                    f"pose:{description}",
                ),
            )


def test_a_scene_artifact_of_each_stage_is_its_own_row_in_the_current_view(scene):
    """``distinct on`` treats NULLs as equal, so the widening needed the view's key to move.

    Without ``scene_id`` in it, every scene artifact of one stage in one workspace collapses into
    one row and ``artifact_current`` reports that a workspace holds one pose receipt however many
    it holds.
    """
    second = _insert_scene(scene, scene.captures[:2])
    _insert_scene_artifact(scene, second, payload=b"a pose receipt over two photographs")
    rows = scene.rows("select artifact_id from artifact_current where kind = 'pose_receipt'")
    assert len(rows) == 2, rows


# -- the predicate -----------------------------------------------------------------------------


def test_a_scene_every_member_of_which_is_live_is_not_blocked(scene):
    """The control for every test below. A predicate that always blocked would pass them all."""
    assert scene.blocked() is False


def test_a_scene_with_no_members_blocks(scene):
    """Fail closed. An unbuilt scene and an invisible one are the same answer to this session.

    ``reconstruction_scene_member`` carries FORCE row-level security, so a session that never set
    ``exulanica.workspace_id`` reads it as empty, and answering "nothing blocks it" to a question
    whose inputs could not be seen is the direction ``_require_workspace_context`` exists to
    prevent. The ordering discipline it forces is members first, then the artifact.
    """
    assert scene.blocked(_empty_scene(scene, 0x09)) is True


def test_the_deletion_of_one_member_reaches_a_scene_two_members_still_stand_in(scene):
    """The inversion, asked of the predicate directly.

    This is the test that goes red on the reduction ``orimera/graph/geometry.py`` warns about.
    ``_LIVE_HOLDER`` is an OR over the captures holding a blob and is right for a per-capture
    artifact; copied to a scene it asks "is any member still live", which after this deletion is
    emphatically true, and a corridor would be served after a photograph in it was deleted.
    """
    scene.delete(scene.captures[1])

    live = scene.rows("select capture_id from capture where deleted_at is null")
    assert len(live) == 2, "the other two photographs must still be there for this to mean anything"
    assert scene.blocked() is True


def test_a_scene_the_deleted_photograph_was_never_in_is_untouched(scene):
    """The control on the other side, and without it "ANY" could just mean "always".

    Two scenes over one workspace: the fixture's over all three photographs, and a second over
    the two that survive. Deleting the middle one must withdraw the first and leave the second
    exactly as it was, bytes included. A predicate that reached every scene in the workspace
    rather than every scene the photograph was in would pass every other test in this file.
    """
    survivor = _insert_scene(scene, [scene.captures[0], scene.captures[2]])
    survivor_receipt = _insert_scene_artifact(
        scene, survivor, payload=b"a pose receipt over the two survivors"
    )
    survivor_bytes = BlobId.of_bytes(b"a pose receipt over the two survivors")

    scene.delete(scene.captures[1])

    assert scene.blocked() is True, "the scene holding the deleted photograph"
    assert scene.blocked(survivor) is False, "the scene that never held it"
    assert scene.releases(survivor_bytes) is False

    outcome = scene.worker().drain()
    assert outcome.failed == 0, outcome.errors
    assert scene.store.exists(survivor_bytes), "a receipt over two live photographs was destroyed"
    assert scene.one(
        "select purged_at from artifact where artifact_id = %s", survivor_receipt
    )["purged_at"] is None
    assert not scene.rows(
        "select purge_id from purge_job where target_kind = 'artifact' and target_ref = %s",
        survivor_bytes.hex,
    ), "a scene the deleted photograph was never in was asked to be destroyed"


def test_an_interval_redaction_blocks_the_scene_without_asking_for_its_bytes(scene):
    """Both halves of the same paragraph, and they answer different questions.

    A redaction over the whole frame of a still image withdraws the scene from every read, which
    is what ``tombstone_blocks_scene`` covers and ``purge_releases_bytes`` deliberately does not:
    migration 0013's scope paragraph says the purger does not act on interval scope, "because a
    redaction removes a moment and not a photograph", and migration 0015's trigger returns early
    for that scope so nothing is enqueued at all. Withheld and still on the disk, exactly as
    ``test_an_interval_redaction_over_the_whole_frame_withdraws_the_geometry_too`` records for a
    point map.
    """
    tombstone = scene.repository.insert_tombstone(
        scope="interval",
        capture_id=scene.captures[1],
        track_key="img",
        interval_ns=[(0, 1)],
        requested_by=uuid.uuid4(),
        reason="the user redacted a moment",
    )
    assert scene.one(
        "select deleted_at from capture where capture_id = %s", scene.captures[1]
    )["deleted_at"] is None
    assert scene.blocked() is True
    assert scene.rows("select purge_id from purge_job where tombstone_id = %s", tombstone) == []


# -- the write guards --------------------------------------------------------------------------


def test_a_scene_artifact_over_a_deleted_photograph_cannot_be_written(scene):
    """0011's guard asked ``tombstone_blocks_derivative`` of a column a scene artifact has not.

    With ``source_blob_sha256`` null, every branch of that predicate except the workspace one is
    dead, because ``c.blob_sha256 = NULL`` is never true. So without the branch migration 0024
    adds, a receipt over deleted photographs inserts cleanly, which is the exact leak R7 was.

    **Matched on the refusal's own message, not on ``IntegrityError``.** ``UniqueViolation`` is
    an ``IntegrityError`` too, and with the guard's branch removed this test still passed on a
    duplicate identity key until the payload was made to vary. What is asserted is that the
    tombstone guard is what refused.
    """
    scene.delete(scene.captures[1])
    with (
        pytest.raises(psycopg.errors.IntegrityError, match="tombstoned: write refused"),
        scene.repository.connection.transaction(),
    ):
        _insert_scene_artifact(scene, scene.scene_id, payload=b"a receipt written too late")


def _empty_scene(scene, marker: int) -> uuid.UUID:
    scene_id = uuid.uuid4()
    scene.repository.connection.execute(
        "insert into reconstruction_scene (scene_id, workspace_id, member_digest) "
        "values (%s, %s, %s)",
        (scene_id, scene.workspace_id, bytes([marker]) * 32),
    )
    return scene_id


def test_a_member_naming_a_deleted_photograph_is_refused(scene):
    """A scene is built out of live photographs, asserted at insert rather than found at read.

    The liveness branch, matched on its own message rather than on any error: the composite
    foreign key would also raise here if the capture row were gone, and those are two different
    facts.
    """
    scene.delete(scene.captures[1])
    later = _empty_scene(scene, 0x08)
    with (
        pytest.raises(psycopg.errors.Error, match="absent or deleted"),
        scene.repository.connection.transaction(),
    ):
        scene.repository.connection.execute(
                "insert into reconstruction_scene_member "
                "(workspace_id, scene_id, capture_id, ordinal) values (%s, %s, %s, 0)",
                (scene.workspace_id, later, scene.captures[1]),
            )


def test_a_member_naming_a_redacted_photograph_is_refused_too(scene):
    """The other branch, and the one the liveness check cannot reach.

    An interval redaction leaves ``deleted_at`` null, so the photograph is live and the liveness
    check above passes. What refuses it is ``tombstone_blocks_capture``, which covers interval
    scope. Without this branch a scene could be assembled out of frames the user had redacted.
    """
    scene.repository.insert_tombstone(
        scope="interval",
        capture_id=scene.captures[1],
        track_key="img",
        interval_ns=[(0, 1)],
        requested_by=uuid.uuid4(),
        reason="the user redacted a moment",
    )
    assert scene.one(
        "select deleted_at from capture where capture_id = %s", scene.captures[1]
    )["deleted_at"] is None
    later = _empty_scene(scene, 0x07)
    with (
        pytest.raises(psycopg.errors.IntegrityError, match="tombstoned: write refused"),
        scene.repository.connection.transaction(),
    ):
        scene.repository.connection.execute(
                "insert into reconstruction_scene_member "
                "(workspace_id, scene_id, capture_id, ordinal) values (%s, %s, %s, 0)",
                (scene.workspace_id, later, scene.captures[1]),
            )


def test_a_membership_cannot_be_edited_out_from_under_a_deletion(scene):
    """The insert guard is worth nothing without this, and it was missing.

    ``tg_guard_reconstruction_scene_member`` fires ``before insert``, and the runtime role holds
    ``select, insert, update`` on every table. So an UPDATE that re-points a member away from the
    photograph that was deleted would un-withdraw a scene a tombstone had already reached, and
    deletion is monotonic: del-1 says there is no undo, and an UPDATE would be one.

    Both tables and both statements, because a DELETE of the member row does the same thing by a
    different route and the runtime role's lack of DELETE is a grant rather than a rule.
    """
    scene.delete(scene.captures[1])
    assert scene.blocked() is True

    for statement, params in (
        (
            "update reconstruction_scene_member set capture_id = %s "
            "where workspace_id = %s and scene_id = %s and capture_id = %s",
            (scene.captures[0], scene.workspace_id, scene.scene_id, scene.captures[1]),
        ),
        (
            "delete from reconstruction_scene_member "
            "where workspace_id = %s and scene_id = %s and capture_id = %s",
            (scene.workspace_id, scene.scene_id, scene.captures[1]),
        ),
        (
            "update reconstruction_scene set member_digest = %s where scene_id = %s",
            (b"\x00" * 32, scene.scene_id),
        ),
    ):
        with (
            pytest.raises(psycopg.errors.IntegrityError, match="append-only"),
            scene.repository.connection.transaction(),
        ):
            scene.repository.connection.execute(statement, params)

    assert scene.blocked() is True, "the scene was un-withdrawn"


def test_a_workspace_deletion_reaches_every_scene_in_it(scene):
    """The other disjunct of the enqueue, which no other test executes.

    The scene branch of ``tg_tombstone_enqueues_its_purge`` is
    ``new.scope = 'workspace' or exists (a member row naming new.capture_id)``, and every other
    test here takes the second half. A workspace tombstone names no capture at all, so the first
    half is the only thing that reaches a scene artifact, and without it deleting a whole
    workspace would leave its receipts on disk while ``tombstone_purge_is_complete`` reported the
    workspace purged: migration 0015's defect 2, in the one scope that file exists to have fixed.
    """
    survivor = _insert_scene(scene, [scene.captures[0], scene.captures[2]])
    _insert_scene_artifact(scene, survivor, payload=b"a second receipt")
    second_bytes = BlobId.of_bytes(b"a second receipt")

    tombstone = scene.repository.insert_tombstone(
        scope="workspace",
        requested_by=uuid.uuid4(),
        reason="the user deleted the whole workspace",
    )
    queued = {
        row["target_ref"]
        for row in scene.rows(
            "select target_ref from purge_job where tombstone_id = %s and target_kind = 'artifact'",
            tombstone,
        )
    }
    assert scene.receipt_digest.hex in queued
    assert second_bytes.hex in queued

    outcome = scene.worker().drain()
    assert outcome.failed == 0, outcome.errors
    assert not scene.store.exists(scene.receipt_digest)
    assert not scene.store.exists(second_bytes)
    # Completion for a workspace tombstone asks about the workspace rather than about the enqueue
    # snapshot, and an unpurged scene artifact would keep it false for ever.
    assert scene.one(
        "select tombstone_purge_is_complete(%s) as done", tombstone
    )["done"] is True


# -- the rung ----------------------------------------------------------------------------------


def _registered_scene_span_ids(scene, scene_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    rows = scene.rows(
        "select c.blob_sha256 from reconstruction_scene_member m "
        "join capture c on c.workspace_id = m.workspace_id and c.capture_id = m.capture_id "
        "where m.workspace_id = %s and m.scene_id = %s and m.registered is true "
        "order by m.ordinal",
        scene.workspace_id,
        scene_id or scene.scene_id,
    )
    return [
        scene.repository.upsert_span(
            EvidenceAddress.photograph(BlobId(bytes(row["blob_sha256"])))
        )
        for row in rows
    ]


def _insert_raw_scene_rung(
    scene,
    *,
    kind: str = "inference",
    scene_id: uuid.UUID | None = None,
    support_span_ids: list[uuid.UUID] | None = None,
    object_value: dict | None = None,
) -> uuid.UUID:
    run = scene.one(
        "select run_id from pipeline_run where workspace_id = %s order by started_at limit 1",
        scene.workspace_id,
    )
    assert run is not None
    row = scene.one(
        "insert into assertion (workspace_id, kind, predicate_id, subject_ref, object_value, "
        "support_span_ids, produced_by_run, emit_key) values "
        "(%s, %s, %s, %s, %s, %s::uuid[], %s, %s) returning assertion_id",
        scene.workspace_id,
        kind,
        scene.repository.predicate_id(RECONSTRUCTION_SCENE_RUNG_PREDICATE),
        psycopg.types.json.Jsonb({"type": "scene", "id": str(scene_id or scene.scene_id)}),
        psycopg.types.json.Jsonb(
            object_value
            or {
                "rung": 3,
                "reasons": ["rungs 1 and 2 require measurements that do not exist"],
                "member_count": len(scene.captures),
            }
        ),
        support_span_ids if support_span_ids is not None else _registered_scene_span_ids(scene),
        run["run_id"] if kind == "inference" else None,
        f"test:scene-rung:{uuid.uuid4()}",
    )
    assert row is not None
    return row["assertion_id"]


def test_a_scene_rung_is_an_inference_and_cannot_be_filed_as_capture(scene):
    with (
        pytest.raises(psycopg.errors.IntegrityError, match="does not accept a capture assertion"),
        scene.repository.connection.transaction(),
    ):
        _insert_raw_scene_rung(scene, kind="capture")


def test_a_scene_rung_requires_the_whole_sets_member_count(scene):
    with (
        pytest.raises(
            psycopg.errors.IntegrityError,
            match="missing required key 'member_count'",
        ),
        scene.repository.connection.transaction(),
    ):
        _insert_raw_scene_rung(
            scene,
            object_value={
                "rung": 3,
                "reasons": ["rungs 1 and 2 require measurements that do not exist"],
            },
        )


def test_a_scene_rung_over_a_deleted_unregistered_member_is_refused(scene):
    member = scene.one(
        "select registered from reconstruction_scene_member "
        "where workspace_id = %s and scene_id = %s and capture_id = %s",
        scene.workspace_id,
        scene.scene_id,
        scene.captures[1],
    )
    assert member == {"registered": False}
    scene.delete(scene.captures[1])

    with (
        pytest.raises(psycopg.errors.IntegrityError, match="tombstoned: write refused"),
        scene.repository.connection.transaction(),
    ):
        _insert_raw_scene_rung(scene)


def test_a_scene_rung_over_a_deleted_registered_member_is_refused(scene):
    support_span_ids = _registered_scene_span_ids(scene)
    scene.delete(scene.captures[0])
    with (
        pytest.raises(psycopg.errors.IntegrityError, match="tombstoned: write refused"),
        scene.repository.connection.transaction(),
    ):
        _insert_raw_scene_rung(scene, support_span_ids=support_span_ids)


def test_the_scene_rung_cites_exactly_the_registered_members_in_ordinal_order(scene):
    expected_support = _registered_scene_span_ids(scene)
    run = scene.one(
        "select run_id from pipeline_run where workspace_id = %s order by started_at limit 1",
        scene.workspace_id,
    )
    assert run is not None

    assertion_id, decision = _record_gate_rung(scene, scene.scene_id, run["run_id"])
    assert assertion_id is not None
    row = scene.one(
        "select kind, subject_ref, object_value, support_span_ids from assertion "
        "where assertion_id = %s",
        assertion_id,
    )
    assert row == {
        "kind": "inference",
        "subject_ref": {"type": "scene", "id": str(scene.scene_id)},
        "object_value": {
            "rung": 3,
            "reasons": ["the durable gate recorded this test decision"],
            "member_count": 3,
            "registered_member_count": 2,
            "gate_digest": decision.digest,
        },
        "support_span_ids": expected_support,
    }
    assert _record_gate_rung(scene, scene.scene_id, run["run_id"])[0] is None


def test_a_scene_nobody_registered_records_rung_4_over_the_complete_input_set(scene):
    unregistered = _insert_scene(
        scene,
        scene.captures[:2],
        registered=[False, None],
    )
    run = scene.one(
        "select run_id from pipeline_run where workspace_id = %s order by started_at limit 1",
        scene.workspace_id,
    )
    assert run is not None

    assertion_id, decision = _record_gate_rung(scene, unregistered, run["run_id"])
    row = scene.one(
        "select object_value,support_span_ids from assertion where assertion_id=%s",
        assertion_id,
    )
    assert row["object_value"]["rung"] == 4
    assert row["object_value"]["gate_digest"] == decision.digest
    assert len(row["support_span_ids"]) == 2


def test_a_scene_rung_is_not_a_capture_rung(scene):
    run = scene.one(
        "select run_id from pipeline_run where workspace_id = %s order by started_at limit 1",
        scene.workspace_id,
    )
    assert run is not None
    _record_gate_rung(scene, scene.scene_id, run["run_id"])

    assert scene.scene_id not in rung_by_capture(
        scene.repository.connection, scene.workspace_id
    )


def test_the_scene_rung_read_withdraws_the_claim_after_any_member_is_deleted(scene):
    run = scene.one(
        "select run_id from pipeline_run where workspace_id = %s order by started_at limit 1",
        scene.workspace_id,
    )
    assert run is not None
    rung_id, _decision = _record_gate_rung(scene, scene.scene_id, run["run_id"])

    assert scene_rung_rows(scene.repository.connection, scene.workspace_id) == [
        SceneRungRow(
            scene_id=scene.scene_id,
            member_capture_ids=scene.captures,
            registered_capture_ids=[scene.captures[0], scene.captures[2]],
            rung=3,
            reasons=["the durable gate recorded this test decision"],
            member_count=3,
        )
    ]

    tombstone_id = scene.delete(scene.captures[1])
    assert scene_rung_rows(scene.repository.connection, scene.workspace_id) == []
    assertion = scene.one(
        "select status from assertion where assertion_id=%s", rung_id
    )
    retraction = scene.one(
        "select r.retracted_by,r.reason,t.requested_by,t.effective_at,r.retracted_at "
        "from retraction r join tombstone t on t.tombstone_id=%s "
        "where r.assertion_id=%s",
        tombstone_id,
        rung_id,
    )
    assert assertion == {"status": "retracted"}
    assert retraction is not None
    assert retraction["retracted_by"] == retraction["requested_by"]
    assert retraction["retracted_at"] == retraction["effective_at"]
    assert str(tombstone_id) in retraction["reason"]


def test_person_withdrawal_reaches_unregistered_members_and_every_scene_build(scene, tmp_path):
    """A confirmed person in an unregistered frame withdraws every build, but not its source."""
    from exulanica.db.migrate import provision_workspace
    from exulanica.epistemics.assertions import AssertionWriter
    from exulanica.identity import IdentityRepository, name_occurrence

    capture = scene.captures[1]
    row = scene.one(
        "select c.blob_sha256,s.span_id from capture c join evidence_span s "
        "on s.workspace_id=c.workspace_id and s.blob_sha256=c.blob_sha256 "
        "where c.workspace_id=%s and c.capture_id=%s order by s.span_id limit 1",
        scene.workspace_id,
        capture,
    )
    run = scene.one(
        "select run_id from pipeline_run where workspace_id=%s order by started_at limit 1",
        scene.workspace_id,
    )
    occurrence = scene.repository.connection.execute(
        "insert into occurrence (workspace_id,capture_id,class,primary_span_id,span_ids,presence,"
        "produced_by_run,detector_version,identity_key,emit_key) values "
        "(%s,%s,'person',%s,array[%s]::uuid[],'{[0,1)}'::int8multirange,%s,'test',%s,%s) "
        "returning occurrence_id",
        (
            scene.workspace_id,
            capture,
            row["span_id"],
            row["span_id"],
            run["run_id"],
            bytes([73]) * 32,
            f"person:{uuid.uuid4()}",
        ),
    ).fetchone()["occurrence_id"]
    named = name_occurrence(
        IdentityRepository(scene.repository.connection, scene.workspace_id),
        AssertionWriter(scene.repository.connection, scene.workspace_id),
        occurrence_id=occurrence,
        display_name="Person In Unregistered Frame",
        actor=uuid.uuid4(),
    )
    provision_workspace(scene.repository.connection, scene.workspace_id)
    embedding = scene.repository.connection.execute(
        "insert into embedding (workspace_id,family,ref_type,ref_id,model_ref,pipeline_version,"
        "dims,v) values (%s,'face','occurrence',%s,'test',1,4096,%s) returning embedding_id",
        (
            scene.workspace_id,
            occurrence,
            "[" + ",".join(["0.5"] * 4096) + "]",
        ),
    ).fetchone()["embedding_id"]
    rung_id, _decision = _record_gate_rung(scene, scene.scene_id, run["run_id"])
    older_receipt = scene.receipt_digest
    newer_payload = b"a superseding build over the same three photographs"
    newer_artifact = _insert_scene_artifact(scene, scene.scene_id, newer_payload)
    newer_receipt = BlobId.of_bytes(newer_payload)
    source_blob = BlobId(bytes(row["blob_sha256"]))
    source_point_map = scene.one(
        "select a.artifact_id,a.content_sha256 from artifact a join capture c "
        "on c.workspace_id=a.workspace_id and c.blob_sha256=a.source_blob_sha256 "
        "where c.capture_id=%s and a.kind='point_map'",
        capture,
    )

    tombstone = scene.repository.insert_tombstone(
        scope="entity",
        entity_id=named.entity_id,
        requested_by=uuid.uuid4(),
        reason="the person withdrew from reconstruction",
    )

    assert scene.blocked()
    assert scene_rung_rows(scene.repository.connection, scene.workspace_id) == []
    assert scene.one("select status from assertion where assertion_id=%s", rung_id)[
        "status"
    ] == "retracted"
    queued = {
        row["target_ref"]
        for row in scene.rows(
            "select target_ref from purge_job where tombstone_id=%s and target_kind='artifact'",
            tombstone,
        )
    }
    assert older_receipt.hex in queued
    assert newer_receipt.hex in queued
    assert bytes(source_point_map["content_sha256"]).hex() in queued

    outcome = scene.worker().drain()
    assert outcome.blocked is None, outcome.blocked
    assert outcome.failed == 0, outcome.errors
    assert not scene.store.exists(older_receipt)
    assert not scene.store.exists(newer_receipt)
    assert not scene.store.exists(BlobId(bytes(source_point_map["content_sha256"])))
    assert scene.one(
        "select count(*) as n from embedding where workspace_id=%s and embedding_id=%s",
        scene.workspace_id,
        embedding,
    )["n"] == 0
    assert scene.store.exists(source_blob)
    assert scene.one("select deleted_at from capture where capture_id=%s", capture)[
        "deleted_at"
    ] is None
    assert scene.one("select purged_at from artifact where artifact_id=%s", newer_artifact)[
        "purged_at"
    ] is not None
    assert scene.reconstruction(scene.export(tmp_path / "after-person-withdrawal.wmp"))[
        "scenes"
    ] == []


# -- the bytes ---------------------------------------------------------------------------------


def test_a_receipt_holds_its_bytes_while_every_member_is_live(scene):
    """The fail-open catch, and it is the reason the destroy predicate grew a third clause.

    A scene artifact has no ``source_blob_sha256``, so the inner join in the artifact clause
    drops it out of the question entirely and the answer comes back "destroy these bytes" while
    every member of the scene is live. That is correction 2's shape, created by the widening
    rather than fixed by it.
    """
    assert scene.releases(scene.receipt_digest) is False


def test_deleting_one_member_of_three_enqueues_the_receipt(scene):
    """The enqueue reaches artifacts by joining ``capture`` on ``source_blob_sha256``.

    A scene artifact cannot be found that way, so without migration 0024's third insert this is
    not a failure and not an error: zero rows, an empty queue, and ``tombstone_purge_is_complete``
    answering true because a tombstone with no jobs is complete.
    """
    tombstone = scene.delete(scene.captures[1])
    queued = {
        row["target_ref"]
        for row in scene.rows(
            "select target_ref from purge_job where tombstone_id = %s and target_kind = 'artifact'",
            tombstone,
        )
    }
    assert scene.receipt_digest.hex in queued, "the receipt was never asked to be destroyed"


def test_deleting_one_member_of_three_releases_the_receipts_bytes(scene):
    """D9's no-ship rule, the bytes half, end to end through the product's own path.

    Four steps and each fails for its own reason: the queue holds the receipt, the predicate
    says the bytes may go, the worker destroys them and the store agrees they are gone, and the
    two surviving photographs keep everything of their own. The last one is not decoration. A
    purger that destroyed the whole workspace would satisfy the first three.

    **Some jobs are skipped and that is the deduplication case working**, so it is checked rather
    than tolerated. The three fixture photographs differ only in an EXIF timestamp, so their
    renditions are byte identical and ``CountingVisionModel`` returns one payload for all three:
    one object, three artifact rows, two of them belonging to photographs nobody deleted. Every
    skip below is asserted to be one of those. A bare ``skipped == 0`` would have been wrong here,
    and a bare ``failed == 0`` would have let a real skip of the receipt through.
    """
    survivors = [
        BlobId(bytes(row["content_sha256"]))
        for row in scene.rows(
            "select a.content_sha256 from artifact a join capture c "
            "on c.blob_sha256 = a.source_blob_sha256 and c.workspace_id = a.workspace_id "
            "where c.capture_id in (%s, %s) and a.content_sha256 is not null",
            scene.captures[0],
            scene.captures[2],
        )
    ]
    assert survivors, "the surviving photographs must own derivatives for the control to bite"
    assert scene.store.exists(scene.receipt_digest)

    scene.delete(scene.captures[1])
    outcome = scene.worker().drain()

    assert outcome.blocked is None, outcome.blocked
    assert outcome.failed == 0, outcome.errors
    assert scene.one(
        "select state from purge_job where target_kind = 'artifact' and target_ref = %s",
        scene.receipt_digest.hex,
    )["state"] == "done", "the receipt was deferred rather than destroyed"
    assert not scene.store.exists(scene.receipt_digest), "the receipt's bytes are still on disk"
    assert scene.one(
        "select purged_at from artifact where artifact_id = %s", scene.receipt_id
    )["purged_at"] is not None
    for blob in survivors:
        assert scene.store.exists(blob), f"{blob.hex[:12]} belonged to a photograph nobody deleted"

    # Every deferral is a hash a photograph nobody deleted still owns, which is the shared-object
    # case rather than a predicate that refused too much.
    for row in scene.rows("select target_ref from purge_job where state = 'skipped'"):
        assert BlobId.from_hex(row["target_ref"]) in survivors, row["target_ref"]


# -- the export -------------------------------------------------------------------------------


@pytest.mark.postgres
def test_a_deleted_scene_rung_leaves_both_export_copies(scene, tmp_path):
    run = scene.one(
        "select run_id from pipeline_run where workspace_id = %s order by started_at limit 1",
        scene.workspace_id,
    )
    assert run is not None
    _record_gate_rung(scene, scene.scene_id, run["run_id"])

    before = scene.export(tmp_path / "before-rung.wmp")
    reconstruction = scene.reconstruction(before)
    graph = json.loads((before.output / "memory/graph.json").read_text())
    scene_subject = reconstruction["scenes"][0]["scene_id"]
    claims = [
        claim for claim in reconstruction["rung_claims"] if claim["subject"] == scene_subject
    ]
    assert len(claims) == 1, reconstruction["rung_claims"]
    assert claims[0]["value"]["member_count"] == 3
    scene_assertions = [
        assertion
        for assertion in graph["assertions"]
        if assertion["predicate"] == RECONSTRUCTION_SCENE_RUNG_PREDICATE
    ]
    assert len(scene_assertions) == 1, graph["assertions"]
    assert scene_assertions[0]["subject_ref"]["id"] == scene_subject

    scene.delete(scene.captures[1])
    after = scene.export(tmp_path / "after-rung.wmp")
    reconstruction = scene.reconstruction(after)
    graph = json.loads((after.output / "memory/graph.json").read_text())
    assert not [
        claim for claim in reconstruction["rung_claims"] if claim["subject"] == scene_subject
    ], "the deleted scene's rung remained in reconstruction/artifacts.json"
    assert not [
        assertion
        for assertion in graph["assertions"]
        if assertion["predicate"] == RECONSTRUCTION_SCENE_RUNG_PREDICATE
    ], "the deleted scene's rung remained in memory/graph.json"


@pytest.mark.postgres
def test_deleting_one_member_of_three_changes_the_export(scene, tmp_path):
    """D9's no-ship rule, the export half. Both halves are the rule; this is the second.

    "No scene-level artifact ships before the test that deletes one of N members and asserts the
    bytes are released and the export changes."

    **Asserted on the component payload, not on the Merkle root and not on ``diff.changed``.**
    Inserting any tombstone rewrites ``deletion/tombstones.json`` and moves the root by itself, so
    a root-level assertion passes with the projector completely unchanged and proves nothing about
    scenes. ``tests/test_world_package_postgres.py`` has a deletion test written that way, and it
    is correct for what it covers because it also asserts on ``memory/graph.json``.

    **The before-assertion is an assertion, not setup.** With the projector's scene clause
    reverted the receipt is absent from the export BEFORE the deletion too, so a test written only
    as "absent afterwards" would pass against a projector that never exported it at all. That is
    the shape this project's defect register calls its recurring failure, and it is why the first
    three lines below assert rather than arrange.
    """
    before = scene.export(tmp_path / "before.wmp")
    body = scene.reconstruction(before)
    receipt = next(
        item for item in body["items"] if item["content_sha256"] == scene.receipt_digest.hex
    )
    assert receipt["scene"] is not None, "a scene artifact reached the package with no subject"
    exported_scene = next(s for s in body["scenes"] if s["scene_id"] == receipt["scene"])
    assert len(exported_scene["members"]) == 3
    # The subject resolves against the same pseudonyms the graph uses for its captures, which is
    # what makes "a fact about these three photographs" checkable by a third party.
    graph_captures = {
        row["capture_id"]
        for row in json.loads((before.output / "memory/graph.json").read_text())["captures"]
    }
    assert {member["capture_id"] for member in exported_scene["members"]} <= graph_captures

    scene.delete(scene.captures[1])
    after = scene.export(tmp_path / "after.wmp", parent=before.merkle_root_sha256)
    body = scene.reconstruction(after)

    assert not [
        item for item in body["items"] if item["content_sha256"] == scene.receipt_digest.hex
    ], "the receipt survived the deletion of one of its three photographs"
    assert body["scenes"] == [], "the scene itself survived"
    # The control. Deleting one photograph must not empty the package: the other two keep their
    # own point maps, and a projector that dropped everything would satisfy the assertion above.
    surviving = {item["content_sha256"] for item in body["items"]}
    assert len(surviving) >= 2, body["items"]

    difference = diff_packages(before.output, after.output)
    assert "reconstruction/artifacts.json" in difference.changed_files
    # Named rather than collapsed. Without `artifact_id` in the diff's identity keys the whole
    # item list is one opaque "replaced" entry, and section 6.6 promises the diff is the honest
    # answer to what changed.
    named = [
        change
        for change in difference.semantic_changes
        if change["kind"] == "removed"
        and change.get("pointer", "").startswith("/reconstruction~1artifacts.json/items/")
    ]
    assert named, difference.semantic_changes
    # And the subject, which is what `scene_id` earns its place in `_IDENTITY_KEYS` for. Without
    # it the `scenes` list has no identity key either and collapses to one opaque `replaced`,
    # so a reader is told the scene list changed and not that a scene went.
    assert [
        change
        for change in difference.semantic_changes
        if change["kind"] == "removed"
        and change.get("pointer", "").startswith("/reconstruction~1artifacts.json/scenes/")
    ], difference.semantic_changes


@pytest.mark.postgres
@pytest.mark.postgres
def test_the_deleted_photographs_own_point_map_leaves_the_export_too(scene, tmp_path):
    """The clause this change rewrote, asserted from the side that was already working.

    The per-capture branch of the artifacts query moved: it used to be the whole ``where`` and is
    now the first half of an ``or``, behind a new ``a.scene_id is null`` guard. Nothing in this
    file asserted the behaviour it already had, so a rewrite that broke it would have been caught
    only by tests about other things.
    """
    doomed = {
        bytes(row["content_sha256"]).hex()
        for row in scene.rows(
            "select a.content_sha256 from artifact a join capture c "
            "on c.blob_sha256 = a.source_blob_sha256 and c.workspace_id = a.workspace_id "
            "where c.capture_id = %s and a.content_sha256 is not null",
            scene.captures[1],
        )
    }
    assert doomed, "the deleted photograph must own derivatives for this to mean anything"
    before = {item["content_sha256"] for item in scene.reconstruction(
        scene.export(tmp_path / "before.wmp"))["items"]}
    assert doomed <= before

    scene.delete(scene.captures[1])
    after = {item["content_sha256"] for item in scene.reconstruction(
        scene.export(tmp_path / "after.wmp"))["items"]}
    # Its renditions and vision payloads are byte-identical to the survivors' and are still held
    # by them, so only the artifacts nothing else owns are expected to go.
    survivors = {
        bytes(row["content_sha256"]).hex()
        for row in scene.rows(
            "select a.content_sha256 from artifact a join capture c "
            "on c.blob_sha256 = a.source_blob_sha256 and c.workspace_id = a.workspace_id "
            "where c.capture_id in (%s, %s) and a.content_sha256 is not null",
            scene.captures[0],
            scene.captures[2],
        )
    }
    assert (doomed - survivors), "the deleted photograph owned nothing of its own"
    assert not (doomed - survivors) & after, "a deleted photograph's own derivative was exported"


@pytest.mark.postgres
def test_a_redaction_over_a_members_whole_frame_withdraws_the_scene_from_the_export(
    scene, tmp_path
):
    """The claim the projector's comment rests on, made executable.

    An interval redaction never sets ``capture.deleted_at``, so a scene clause written against
    that column would keep the receipt in the package. ``tombstone_blocks_scene`` covers interval
    scope, which is the whole reason the projector asks the predicate rather than testing the
    column, and without this test that sentence is a comment nothing checks.

    **The photograph itself stays**, and its own point map's descriptor stays with it, which is
    the pre-existing inconsistency the same comment records: the older per-capture clause tests
    ``deleted_at`` too. Asserted here rather than left implicit so that closing that gap fails
    this test and brings somebody to the comment.
    """
    before = scene.reconstruction(scene.export(tmp_path / "before.wmp"))
    assert any(
        item["content_sha256"] == scene.receipt_digest.hex for item in before["items"]
    )

    scene.repository.insert_tombstone(
        scope="interval",
        capture_id=scene.captures[1],
        track_key="img",
        interval_ns=[(0, 1)],
        requested_by=uuid.uuid4(),
        reason="the user redacted a moment",
    )
    assert scene.one(
        "select deleted_at from capture where capture_id = %s", scene.captures[1]
    )["deleted_at"] is None

    after = scene.reconstruction(scene.export(tmp_path / "after.wmp"))
    assert not any(
        item["content_sha256"] == scene.receipt_digest.hex for item in after["items"]
    ), "a receipt over a redacted frame is still described in the package"
    assert after["scenes"] == []
    # The photograph is still live, so it is still in the graph, and its own point map is still
    # described. That second half is the gap, not the guarantee.
    redacted_point_map = scene.one(
        "select a.content_sha256 from artifact a join capture c "
        "on c.blob_sha256 = a.source_blob_sha256 and c.workspace_id = a.workspace_id "
        "where c.capture_id = %s and a.kind = 'point_map'",
        scene.captures[1],
    )
    assert bytes(redacted_point_map["content_sha256"]).hex() in {
        item["content_sha256"] for item in after["items"]
    }, "the older clause started covering interval scope; update the projector comment with it"


def test_a_scene_the_deleted_photograph_was_never_in_stays_in_the_export(scene, tmp_path):
    """The over-reach control, on the export side.

    A predicate that dropped every scene in the workspace rather than every scene the photograph
    was in would pass the test above.
    """
    survivor = _insert_scene(scene, [scene.captures[0], scene.captures[2]])
    _insert_scene_artifact(scene, survivor, payload=b"a receipt over the two survivors")
    survivor_bytes = BlobId.of_bytes(b"a receipt over the two survivors")

    scene.delete(scene.captures[1])
    body = scene.reconstruction(scene.export(tmp_path / "after.wmp"))

    kept = [item for item in body["items"] if item["content_sha256"] == survivor_bytes.hex]
    assert len(kept) == 1, "a scene the deleted photograph was never in left the package"
    assert len(body["scenes"]) == 1
    # Two members, and the ordinals and registration the scene was built with. NOT compared
    # against "every live capture in the workspace", which after this deletion is also exactly
    # those two and would make the assertion true of any membership at all.
    assert len(body["scenes"][0]["members"]) == 2
    assert [
        (member["ordinal"], member["registered"]) for member in body["scenes"][0]["members"]
    ] == [(0, True), (1, True)]


def _stranger_holding_the_same_receipt(scene, captures):
    """A second workspace that ran the same job over the same photographs, sharing one object.

    Realistic rather than contrived: ``blob`` is not workspace-scoped, so two workspaces that
    import the same photographs share one row and one stored object per photograph, and a
    deterministic reconstruction over the same set produces byte-identical receipt bytes. One
    object, two artifact rows, two scenes.

    Written through a session scoped to the stranger, because every guard involved calls
    ``assert_workspace_context`` and a connection that declared workspace A may not write rows
    into workspace B. That is the guard working, not an obstacle to route around.
    """
    stranger = uuid.uuid4()
    with scene.database().session(stranger) as connection:
        their_captures = []
        for capture_id in captures:
            blob = scene.one(
                "select blob_sha256 from capture where capture_id = %s", capture_id
            )["blob_sha256"]
            their_captures.append(
                connection.execute(
                    "insert into capture (workspace_id, blob_sha256) values (%s, %s) "
                    "returning capture_id",
                    (stranger, bytes(blob)),
                ).fetchone()["capture_id"]
            )
        their_scene = scene_id_for(their_captures)
        connection.execute(
            "insert into reconstruction_scene (scene_id, workspace_id, member_digest) "
            "values (%s, %s, %s)",
            (their_scene, stranger, scene_member_digest(their_captures)),
        )
        for ordinal, capture_id in enumerate(their_captures):
            connection.execute(
                "insert into reconstruction_scene_member "
                "(workspace_id, scene_id, capture_id, ordinal, registered) "
                "values (%s, %s, %s, %s, true)",
                (stranger, their_scene, capture_id, ordinal),
            )
        connection.execute(
            "insert into artifact (artifact_id, workspace_id, kind, scene_id, stage_key, "
            "stage_version, params_digest, input_digest, idempotency_key, content_sha256, "
            "storage_key, byte_size) "
            "values (%s, %s, 'pose_receipt', %s, 'pose', 1, %s, %s, %s, %s, %s, %s)",
            (
                uuid.uuid4(),
                stranger,
                their_scene,
                b"\x01" * 32,
                b"\x02" * 32,
                f"pose:{their_scene}",
                scene.receipt_digest.digest,
                scene.store.key_for(scene.receipt_digest),
                len(_RECEIPT),
            ),
        )
    return stranger, their_captures


def test_a_receipt_another_workspace_still_stands_behind_is_not_destroyed(scene):
    """Correction 7's shape, for the relation migration 0024 added to the destroy predicate.

    ``blob`` is shared between workspaces, so "may these bytes be destroyed" is a question about
    every workspace, and the predicate is only as truthful as the caller can see. For the scene
    clause the failure direction is the opposite of correction 7's: a purger blind to the other
    workspace's membership finds no deleted member there, concludes the artifact still holds the
    bytes, and REFUSES. So this asserts the safe direction is taken for the right reason, and the
    next test asserts the bytes do eventually go, because a purge that always refuses is not a
    purge.
    """
    stranger, _their_captures = _stranger_holding_the_same_receipt(scene, scene.captures)

    scene.delete(scene.captures[1])
    outcome = scene.worker().drain()

    assert outcome.failed == 0, outcome.errors
    assert scene.store.exists(scene.receipt_digest), (
        "a receipt another workspace still stands behind was destroyed, which breaks every "
        "citation that workspace has into it"
    )
    assert scene.one(
        "select state from purge_job where target_kind = 'artifact' and target_ref = %s",
        scene.receipt_digest.hex,
    )["state"] == "skipped"
    # And this workspace's tombstone is NOT recorded as purged, because it is not.
    assert scene.one(
        "select purge_completed_at from tombstone where scope = 'capture'"
    )["purge_completed_at"] is None
    assert stranger is not None, "the second workspace was never created"


def test_the_receipt_goes_once_no_workspace_stands_behind_it(scene, monkeypatch):
    """The other half, and without it the test above is satisfied by a purger that never acts.

    A deferral is correct while somebody still holds the bytes and is a permanent stall if the
    predicate can never be satisfied. Once the second workspace deletes a member of its own scene,
    nothing stands behind the object and the deferred job destroys it.

    ``RETRY_AFTER`` is collapsed rather than waited out, which is the pattern
    ``tests/test_purge.py`` already uses for the same reason: a skipped job backs off fifteen
    minutes so a permanently-held blob does not spin, and this test is about the predicate
    flipping rather than about the clock. **The predicate is also asserted directly**, because
    without that the drain assertion alone could pass on a job that was never deferred in the
    first place.
    """
    stranger, their_captures = _stranger_holding_the_same_receipt(scene, scene.captures)
    scene.delete(scene.captures[1])
    scene.worker().drain()
    # The RECEIPT's own job, not a count. Two unrelated jobs defer here anyway, because the three
    # fixture photographs render identically and share one rendition object and one vision
    # object, so a bare `skipped >= 1` is satisfied without the receipt being deferred at all.
    assert scene.one(
        "select state from purge_job where target_kind = 'artifact' and target_ref = %s",
        scene.receipt_digest.hex,
    )["state"] == "skipped"
    assert scene.store.exists(scene.receipt_digest)
    assert scene.releases(scene.receipt_digest) is False

    with scene.database().session(stranger) as connection:
        connection.execute(
            "insert into tombstone (workspace_id, scope, capture_id, requested_by, reason) "
            "values (%s, 'capture', %s, %s, 'the other workspace deleted one too')",
            (stranger, their_captures[1], uuid.uuid4()),
        )
    assert scene.releases(scene.receipt_digest) is True, (
        "nothing stands behind these bytes and the predicate still refuses them"
    )

    monkeypatch.setattr(queue, "RETRY_AFTER", dt.timedelta(0))
    outcome = scene.worker().drain()
    assert outcome.failed == 0, outcome.errors
    assert not scene.store.exists(scene.receipt_digest), (
        "no workspace stands behind these bytes any more and they are still on disk"
    )


def test_the_purger_sees_the_membership_of_every_workspace(scene):
    """Correction 7, asked of the relation migration 0024 added to the destroy predicate.

    ``blob`` is shared between workspaces, so "does anything still hold these bytes" is a question
    about every one of them, and a purger that could see only its own answers it in the direction
    that destroys another tenant's photograph. The predicate now reads
    ``reconstruction_scene_member`` too, and a narrowed view of that relation would report a scene
    with no live members and release bytes another workspace's receipt is made of.
    """
    assert "reconstruction_scene_member" in PURGE_CROSS_WORKSPACE_TABLES
    with scene.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD).session(
        scene.workspace_id
    ) as connection:
        visibility = queue.read_visibility(connection)
        assert visibility.refusal is None, visibility.refusal
        assert visibility.sees_every_workspace
