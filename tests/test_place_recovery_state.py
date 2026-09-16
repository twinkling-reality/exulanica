"""A set of photographs with a recovery state, written and read through the real schema.

The rules this file holds are the ones ``0063_place_recovery_state.sql`` enforces and
``exulanica.graph.places.place_record`` reads back. Each test writes the row a careless writer
would write and requires the database to refuse it, or builds the record a real outcome produces
and requires the reader to show it as a room of its photographs with a stated reason.

Every runtime behaviour here is exercised as the non-owner role ``exulanica_app`` through
``scratch_role_database``. The owner connection builds the throwaway schema and provisions the
role, and nothing else.

The room is built from real photographs: six of the Montserrat volcanic sample (Mike R. James and
Stuart Robson, CC0), read through the ``.exulanica`` symlink, and the real pose receipt their
2026-09-11 run wrote, which placed none of them. Neither is copied into the repository. The
tests that need them skip when they are absent.
"""

from __future__ import annotations

import dataclasses
import glob
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.capture import Photograph, assess_capture_set
from exulanica.capture.recovery import RECOVERY_STATES, member_digest
from exulanica.capture.verdict import POLICY_V1
from exulanica.db.roles import provision_runtime_role
from exulanica.evidence.scene import scene_id_for, scene_member_digest
from exulanica.graph.places import place_record, place_record_ids
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.stages import STAGES, stage
from exulanica.store.local import LocalContentAddressedStore
from psycopg.types.json import Jsonb

from conftest import scratch_role_database

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/capture-overlap"
VOLCANIC = ROOT / ".exulanica/reference-baseline/inputs/volcanic-sample/photographs"
SCRATCH_STORE = Path(
    "/Users/glendonchin/dev/Technology/exulanica-scratch/capture-size/segments-view-data/blobs"
)
_RUNS = {
    run["label"]: run for run in json.loads((FIXTURES / "measured-runs.json").read_text())["runs"]
}
_NAMES = [
    row["name"]
    for row in json.loads((FIXTURES / "volcanic-cameras.json").read_text())["photographs"]
]


def _real_six() -> list[Path]:
    if not VOLCANIC.is_dir():
        pytest.skip("the retained volcanic photographs are not reachable through .exulanica")
    return [VOLCANIC / _NAMES[index] for index in _RUNS["six"]["indices"]]


def _real_receipt(label: str) -> bytes:
    run = _RUNS[label]
    matches = glob.glob(str(SCRATCH_STORE / f"sha-256/*/*/{run['receipt_sha256']}"))
    if not matches:
        pytest.skip(f"the retained {label} pose receipt is not on this machine")
    data = Path(matches[0]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == run["receipt_sha256"]
    return data


@dataclasses.dataclass
class Room:
    app: object
    owner_repository: IngestRepository
    store: LocalContentAddressedStore
    workspace: uuid.UUID
    captures: list[uuid.UUID]
    blobs: list[bytes]

    def session(self, workspace: uuid.UUID | None = None):
        return self.app.session(workspace or self.workspace)


@pytest.fixture
def room(repository, spine_schema, tmp_path):
    """Six real photographs admitted as captures, and a runtime role to read and write them as."""
    _, scratch = spine_schema
    provision_runtime_role(repository.connection)
    repository.register_stages(STAGES)
    store = LocalContentAddressedStore(tmp_path / "store")
    pipeline = PhotoIngestPipeline(repository, store, vision=None)
    captures, blobs = [], []
    for path in _real_six():
        data = path.read_bytes()
        intake = pipeline.ingest_intake(data, filename=path.name)
        assert intake.capture_id is not None, intake.error
        pipeline.ingest_derivatives(intake.capture_id)
        captures.append(intake.capture_id)
        blobs.append(hashlib.sha256(data).digest())
    return Room(
        scratch_role_database(scratch, "exulanica_app"),
        repository,
        store,
        repository.workspace_id,
        captures,
        blobs,
    )


def _open_record(connection, workspace, captures, verdict=None) -> uuid.UUID:
    """Insert a record and its members in one transaction, the only shape the schema admits."""
    record_id = uuid.uuid4()
    columns = {
        "workspace_id": workspace,
        "record_id": record_id,
        "member_digest": member_digest(captures),
        "member_count": len(captures),
    }
    if verdict is not None:
        graph = verdict.graph
        columns |= {
            "verdict_policy": verdict.policy.version,
            "verdict_canonical": verdict.canonical_bytes(),
            "verdict_record": Jsonb(verdict.record()),
            "verdict_sha256": verdict.sha256(),
            "verdict_refusal_authorised": verdict.policy.refusal_authorised,
            "predicted_ceiling": verdict.predicted_ceiling,
            "verdict_worth_attempting": verdict.worth_attempting,
            "verdict_fault": verdict.fault,
            "photograph_count": graph.photograph_count,
            "measured_count": graph.measured_count,
            "edge_min_score": graph.edge_min_score,
            "edge_count": len(graph.edges),
            "largest_component": graph.largest_component,
            "group_count": graph.groups,
            "isolated_count": graph.isolated,
        }
    names = ", ".join(columns)
    marks = ", ".join(["%s"] * len(columns))
    # One transaction, because the member check is deferred to commit and a record committed
    # before its members is refused there.
    with connection.transaction():
        connection.execute(
            f"insert into place_record ({names}) values ({marks})", tuple(columns.values())
        )
        for ordinal, capture_id in enumerate(captures):
            connection.execute(
                "insert into place_record_member (workspace_id, record_id, capture_id, ordinal) "
                "values (%s, %s, %s, %s)",
                (workspace, record_id, capture_id, ordinal),
            )
    return record_id


def _verdict_for(room: Room, policy=POLICY_V1):
    """The real verdict over the room's six photographs, refs being their capture ids."""
    photographs = [
        Photograph.from_path(str(capture_id), path)
        for capture_id, path in zip(room.captures, _real_six(), strict=True)
    ]
    return assess_capture_set(photographs, policy)


def _scene(room: Room, captures=None) -> uuid.UUID:
    """A completed scene over exactly ``captures``, as the scene worker records one."""
    captures = captures or room.captures
    scene_id = scene_id_for(captures)
    room.owner_repository.insert_completed_reconstruction_scene(
        scene_id=scene_id,
        member_digest=scene_member_digest(captures),
        scene_members=[(capture_id, False) for capture_id in captures],
    )
    return scene_id


_STAGE_FOR_KIND = {
    "pose_receipt": "scene_pose",
    "scene_splat_receipt": "scene_splat_training",
    "gaussian_splat_scene": "scene_splat_delivery",
}


def _receipt(room: Room, scene_id: uuid.UUID, payload: bytes, kind: str = "pose_receipt"):
    """One artifact about a scene, stored as bytes the reader can re-check."""
    stored = room.store.put_bytes(payload)
    spec = stage(_STAGE_FOR_KIND[kind])
    assert spec.output_kind == kind
    artifact_id = uuid.uuid4()
    room.owner_repository.insert_scene_artifact(
        artifact_id=artifact_id,
        kind=kind,
        scene_id=scene_id,
        stage_key=spec.key,
        stage_version=spec.version,
        params_digest=spec.params_digest,
        input_digest=bytes(32),
        idempotency_key=f"test-receipt/{artifact_id}",
        content_sha256=stored.blob_id.digest,
        storage_key=room.store.key_for(stored.blob_id),
        byte_size=stored.byte_size,
        produced_by_event=None,
    )
    return artifact_id


def _event(connection, workspace, record_id, seq, from_state, to_state, basis, **evidence):
    columns = {
        "workspace_id": workspace,
        "record_id": record_id,
        "seq": seq,
        "from_state": from_state,
        "to_state": to_state,
        "basis": basis,
        **evidence,
    }
    connection.execute(
        f"insert into place_record_state_event ({', '.join(columns)}) "
        f"values ({', '.join(['%s'] * len(columns))})",
        tuple(columns.values()),
    )


def _refused(room: Room, write, *, workspace=None) -> str:
    import psycopg

    with pytest.raises(psycopg.Error) as raised, room.session(workspace) as connection:
        write(connection)
    return str(raised.value)


def test_the_schema_carries_exactly_the_five_states_the_package_names(room):
    with room.session() as connection:
        rows = connection.execute(
            "select pg_get_constraintdef(c.oid) as definition from pg_constraint c "
            "join pg_class t on t.oid = c.conrelid "
            "where t.relname = 'place_record' and c.contype = 'c' "
            "and pg_get_constraintdef(c.oid) like '%%recovery_state%%'"
            "and pg_get_constraintdef(c.oid) like '%%ANY%%'"
        ).fetchall()
    assert len(rows) == 1
    named = [part.split("'")[1] for part in rows[0]["definition"].split("::text")[:-1]]
    assert tuple(named) == RECOVERY_STATES


def test_a_set_that_placed_nothing_is_a_room_of_its_own_photographs_with_a_reason(room):
    """The whole point of the lane, on the real six photographs and their real receipt.

    The 2026-09-11 run over these six found no initial pair and placed none of them. The record
    moves to ``insufficient_overlap`` on that receipt, and the read returns the six photographs,
    the state, and a reason built from the receipt's own counts and re-checked against its bytes.
    """
    artifact_id = _receipt(room, _scene(room), _real_receipt("six"))
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures)
    with room.session() as connection:
        _event(
            connection, room.workspace, record_id, 1, "not_attempted", "insufficient_overlap",
            "pose_receipt", receipt_artifact_id=artifact_id, registered_count=0,
            receipt_accepted=False,
        )  # fmt: skip
    with room.session() as connection:
        read = place_record(connection, room.workspace, record_id, room.store)
        listed = place_record_ids(connection, room.workspace, "insufficient_overlap")
    assert read is not None and listed == [record_id]
    assert read.recovery_state == "insufficient_overlap"
    assert [photo.capture_id for photo in read.photographs] == room.captures
    assert read.reason is not None
    assert read.reason.state == "stated", read.reason.reason
    assert read.reason.basis == "pose_receipt"
    [said] = read.reason.instructions
    assert said.key == "run_placed_none"
    assert "6 photographs" in said.detail
    assert said.action and "overlaps the one before it" in said.action
    assert [change.basis for change in read.history] == ["pose_receipt"]
    assert read.history[0].receipt_sha256 == _RUNS["six"]["receipt_sha256"]
    # The photographs are whatever the viewer route would serve now, and nothing is invented for
    # the ones it would not serve.
    for photo in read.photographs:
        assert (photo.state == "available") == (photo.photograph is not None)
        assert photo.state == "available" or photo.reason
    # Measured: nobody is in these photographs, so the viewer route serves all six originals.
    assert {photo.state for photo in read.photographs} == {"available"}
    for photo in read.photographs:
        if photo.photograph is not None:
            assert photo.photograph.href.endswith("/masked")
            assert photo.photograph.content_sha256 in {blob.hex() for blob in room.blobs}


def test_withdrawing_one_photograph_withdraws_the_room(room):
    """ANY and not ALL: the record is a fact about six photographs and one was withdrawn."""
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures)
    room.owner_repository.insert_tombstone(
        scope="capture", capture_id=room.captures[2], requested_by=uuid.uuid4()
    )
    with room.session() as connection:
        assert place_record(connection, room.workspace, record_id, room.store) is None
        assert place_record_ids(connection, room.workspace, "not_attempted") == []
        blocked = connection.execute(
            "select tombstone_blocks_place_record(%s, %s) as blocked", (room.workspace, record_id)
        ).fetchone()["blocked"]
    assert blocked is True
    message = _refused(
        room,
        lambda c: _event(
            c, room.workspace, record_id, 1, "not_attempted", "insufficient_overlap", "verdict",
            verdict_sha256=bytes(32),
        ),
    )  # fmt: skip
    assert "tombstoned" in message


def test_a_withdrawn_photograph_cannot_join_a_new_record(room):
    room.owner_repository.insert_tombstone(
        scope="capture", capture_id=room.captures[0], requested_by=uuid.uuid4()
    )
    message = _refused(room, lambda c: _open_record(c, room.workspace, room.captures))
    assert "absent or deleted" in message or "tombstoned" in message


def test_another_workspace_reads_nothing_and_cannot_write_here(room):
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures)
    elsewhere = uuid.uuid4()
    with room.session(elsewhere) as connection:
        assert place_record(connection, elsewhere, record_id, room.store) is None
        assert place_record(connection, room.workspace, record_id, room.store) is None
        for table in ("place_record", "place_record_member", "place_record_state_event"):
            count = connection.execute(f"select count(*) as n from {table}").fetchone()["n"]
            assert count == 0, table
    message = _refused(
        room,
        lambda c: _open_record(c, room.workspace, room.captures[:1]),
        workspace=elsewhere,
    )
    assert "workspace context" in message or "row-level security" in message


def test_the_runtime_role_is_not_the_owner_and_does_not_bypass_row_security(room):
    with room.session() as connection:
        row = connection.execute(
            "select current_user as who, r.rolbypassrls, r.rolsuper, "
            "(select t.tableowner from pg_tables t where t.tablename = 'place_record' "
            "  and t.schemaname = current_schema()) as owner "
            "from pg_roles r where r.rolname = current_user"
        ).fetchone()
    assert row["who"] == "exulanica_app"
    assert row["rolbypassrls"] is False and row["rolsuper"] is False
    assert row["owner"] != "exulanica_app"


def test_a_verdict_under_a_policy_not_authorised_to_refuse_cannot_seal_a_set(room):
    """Policy v1 failed its held-out check, so its refusal is advice and the schema says so."""
    verdict = _verdict_for(room)
    assert verdict.policy.refusal_authorised is False
    assert verdict.worth_attempting is False
    assert verdict.refusal() is None
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures, verdict)
    message = _refused(
        room,
        lambda c: _event(
            c, room.workspace, record_id, 1, "not_attempted", "insufficient_overlap", "verdict",
            verdict_sha256=verdict.sha256(),
        ),
    )  # fmt: skip
    assert "not authorised to refuse" in message
    with room.session() as connection:
        read = place_record(connection, room.workspace, record_id, room.store)
    assert read is not None
    assert read.recovery_state == "not_attempted" and read.reason is None
    assert read.verdict is not None and read.verdict.state == "verified"
    assert read.verdict.refusal_authorised is False
    # An unvalidated policy does not speak to the person: its sentences stay in the verdict, for
    # evaluation, and are not offered as advice.
    assert read.verdict.instructions
    assert read.advice == []


def test_an_authorised_refusal_is_a_room_whose_reason_is_the_verdict(room):
    """The verdict path, under a test policy explicitly marked as authorised.

    Synthetic in exactly one respect: the policy's authorisation flag. The photographs, the
    measurement and the thresholds are the real ones.
    """
    authorised = dataclasses.replace(
        POLICY_V1,
        version="exulanica.capture-overlap-policy/test-authorised",
        refusal_authorised=True,
    )
    verdict = _verdict_for(room, authorised)
    assert verdict.refusal() == "insufficient_overlap"
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures, verdict)
        _event(
            connection, room.workspace, record_id, 1, "not_attempted", "insufficient_overlap",
            "verdict", verdict_sha256=verdict.sha256(),
        )  # fmt: skip
    with room.session() as connection:
        read = place_record(connection, room.workspace, record_id, room.store)
    assert read is not None and read.recovery_state == "insufficient_overlap"
    assert read.reason is not None and read.reason.state == "stated"
    assert read.reason.basis == "verdict"
    assert [item.key for item in read.reason.instructions] == ["mostly_unconnected"]
    assert read.advice == []
    assert len(read.photographs) == 6


def test_a_verdict_may_not_name_another_verdict_or_claim_a_registration(room):
    authorised = dataclasses.replace(POLICY_V1, refusal_authorised=True)
    verdict = _verdict_for(room, authorised)
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures, verdict)
    wrong = _refused(
        room,
        lambda c: _event(
            c, room.workspace, record_id, 1, "not_attempted", "insufficient_overlap", "verdict",
            verdict_sha256=bytes(32),
        ),
    )  # fmt: skip
    assert "not this record's verdict" in wrong
    for state in ("registered_partial", "registered_scene", "trained_radiance"):
        claimed = _refused(
            room,
            lambda c, state=state: _event(
                c, room.workspace, record_id, 1, "not_attempted", state, "verdict",
                verdict_sha256=verdict.sha256(),
            ),
        )  # fmt: skip
        assert "the_basis_can_reach_the_state" in claimed, state


def test_a_pose_receipt_state_must_be_its_counts_and_about_this_set(room):
    artifact_id = _receipt(room, _scene(room), _real_receipt("six"))
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures)
    lying = _refused(
        room,
        lambda c: _event(
            c, room.workspace, record_id, 1, "not_attempted", "registered_scene", "pose_receipt",
            receipt_artifact_id=artifact_id, registered_count=0, receipt_accepted=False,
        ),
    )  # fmt: skip
    assert "a_pose_receipt_state_is_its_counts" in lying
    with room.session() as connection:
        other = _open_record(connection, room.workspace, room.captures[:5])
    elsewhere = _refused(
        room,
        lambda c: _event(
            c, room.workspace, other, 1, "not_attempted", "insufficient_overlap", "pose_receipt",
            receipt_artifact_id=artifact_id, registered_count=0, receipt_accepted=False,
        ),
    )  # fmt: skip
    assert "different set of photographs" in elsewhere


def test_a_receipt_that_disagrees_with_its_event_is_read_as_invalid(room):
    """The schema checks the counts are self-consistent; only the bytes say they are true."""
    artifact_id = _receipt(room, _scene(room), _real_receipt("twelve_wide"))
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures)
        _event(
            connection, room.workspace, record_id, 1, "not_attempted", "insufficient_overlap",
            "pose_receipt", receipt_artifact_id=artifact_id, registered_count=0,
            receipt_accepted=False,
        )  # fmt: skip
    with room.session() as connection:
        read = place_record(connection, room.workspace, record_id, room.store)
        missing = place_record(connection, room.workspace, record_id, None)
    assert read is not None and read.reason is not None
    assert read.reason.state == "invalid" and read.reason.instructions == []
    assert missing is not None and missing.reason is not None
    assert missing.reason.state == "unavailable"


def test_training_needs_a_delivered_scene_and_an_accepted_registration(room):
    """Only a delivered trained scene makes ``trained_radiance``, and only after registration.

    The receipt bytes here are stand-ins, which the schema cannot tell and the reader can: this
    test is about what the schema admits, and the reader's own check is exercised above.
    """
    scene_id = _scene(room)
    pose = _receipt(room, scene_id, b'{"stand-in": "pose"}')
    training = _receipt(room, scene_id, b'{"stand-in": "training"}', "scene_splat_receipt")
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures)
    # A delivered scene over five of the photographs, so the only thing wrong with training a
    # record that never registered is that it never registered.
    five = room.captures[:5]
    five_scene = _scene(room, five)
    five_training = _receipt(room, five_scene, b'{"stand-in": "5"}', "scene_splat_receipt")
    _receipt(room, five_scene, b'{"stand-in": "5 delivered"}', "gaussian_splat_scene")
    with room.session() as connection:
        unregistered = _open_record(connection, room.workspace, five)
    skipped = _refused(
        room,
        lambda c: _event(
            c, room.workspace, unregistered, 1, "not_attempted", "trained_radiance",
            "training_receipt", receipt_artifact_id=five_training,
        ),
    )  # fmt: skip
    assert "the_basis_can_reach_the_state" in skipped
    with room.session() as connection:
        _event(
            connection, room.workspace, record_id, 1, "not_attempted", "registered_scene",
            "pose_receipt", receipt_artifact_id=pose, registered_count=6, receipt_accepted=True,
        )  # fmt: skip
    undelivered = _refused(
        room,
        lambda c: _event(
            c, room.workspace, record_id, 2, "registered_scene", "trained_radiance",
            "training_receipt", receipt_artifact_id=training,
        ),
    )  # fmt: skip
    assert "no trained scene was delivered" in undelivered
    wrong_kind = _refused(
        room,
        lambda c: _event(
            c, room.workspace, record_id, 2, "registered_scene", "trained_radiance",
            "training_receipt", receipt_artifact_id=pose,
        ),
    )  # fmt: skip
    assert "not a live receipt" in wrong_kind
    _receipt(room, scene_id, b'{"stand-in": "delivery"}', "gaussian_splat_scene")
    with room.session() as connection:
        _event(
            connection, room.workspace, record_id, 2, "registered_scene", "trained_radiance",
            "training_receipt", receipt_artifact_id=training,
        )  # fmt: skip
        state = connection.execute(
            "select recovery_state, state_seq from place_record where record_id = %s",
            (record_id,),
        ).fetchone()
    assert (state["recovery_state"], state["state_seq"]) == ("trained_radiance", 2)


def test_the_state_moves_only_through_an_event_and_the_record_is_otherwise_fixed(room):
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures)
    arrived = _refused(
        room,
        lambda c: c.execute(
            "insert into place_record (workspace_id, member_digest, member_count, recovery_state) "
            "values (%s, %s, 1, 'registered_scene')",
            (room.workspace, bytes(32)),
        ),
    )
    assert "arrives not_attempted" in arrived
    direct = _refused(
        room,
        lambda c: c.execute(
            "update place_record set recovery_state = 'insufficient_overlap', state_seq = 1 "
            "where record_id = %s",
            (record_id,),
        ),
    )
    assert "only through place_record_state_event" in direct
    edited = _refused(
        room,
        lambda c: c.execute(
            "update place_record set member_count = 5 where record_id = %s", (record_id,)
        ),
    )
    assert "immutable except for its recovery state" in edited
    moved = _refused(
        room,
        lambda c: c.execute(
            "update place_record_member set ordinal = ordinal + 10 where record_id = %s",
            (record_id,),
        ),
    )
    assert "append-only" in moved
    # The runtime role holds no DELETE at all, so a delete is refused before the append-only
    # trigger is reached; the trigger is what stops a role that does hold it, and
    # ``tests/test_capture_overlap_migration.py`` checks it is installed.
    for table in ("place_record", "place_record_member"):
        message = _refused(
            room,
            lambda c, t=table: c.execute(f"delete from {t} where record_id = %s", (record_id,)),
        )
        assert "permission denied" in message, table


def test_a_record_holds_exactly_its_declared_members_and_its_verdict_describes_them(room):
    count = _refused(
        room,
        lambda c: c.execute(
            "insert into place_record (workspace_id, member_digest, member_count) "
            "values (%s, %s, 3)",
            (room.workspace, bytes(32)),
        ),
    )
    assert "holds 0 members and declares 3" in count
    verdict = _verdict_for(room)
    pipeline = PhotoIngestPipeline(room.owner_repository, room.store, vision=None)
    seventh = VOLCANIC / _NAMES[1]
    intake = pipeline.ingest_intake(seventh.read_bytes(), filename=seventh.name)
    assert intake.capture_id is not None, intake.error
    swapped = _refused(
        room,
        lambda c: _open_record(c, room.workspace, [*room.captures[:5], intake.capture_id], verdict),
    )
    assert "describes other photographs" in swapped


def test_state_events_are_append_only_and_ordered(room):
    artifact_id = _receipt(room, _scene(room), _real_receipt("six"))
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures)
    skipped = _refused(
        room,
        lambda c: _event(
            c, room.workspace, record_id, 2, "not_attempted", "insufficient_overlap",
            "pose_receipt", receipt_artifact_id=artifact_id, registered_count=0,
            receipt_accepted=False,
        ),
    )  # fmt: skip
    assert "must follow the record's current state" in skipped
    with room.session() as connection:
        _event(
            connection, room.workspace, record_id, 1, "not_attempted", "insufficient_overlap",
            "pose_receipt", receipt_artifact_id=artifact_id, registered_count=0,
            receipt_accepted=False,
        )  # fmt: skip
    rewritten = _refused(
        room,
        lambda c: c.execute(
            "update place_record_state_event set to_state = 'registered_scene' "
            "where record_id = %s",
            (record_id,),
        ),
    )
    assert "append-only" in rewritten
    erased = _refused(
        room,
        lambda c: c.execute(
            "delete from place_record_state_event where record_id = %s", (record_id,)
        ),
    )
    assert "permission denied" in erased


def test_a_withdrawal_only_lowers_a_state_and_names_a_real_tombstone(room):
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures)
    invented = _refused(
        room,
        lambda c: _event(
            c, room.workspace, record_id, 1, "not_attempted", "registered_scene", "withdrawal",
            withdrawal_tombstone_id=uuid.uuid4(),
        ),
    )  # fmt: skip
    assert "not a tombstone in this workspace" in invented
    # A tombstone that exists, over a photograph outside this record, so the record stays live
    # and the only thing wrong is the direction.
    pipeline = PhotoIngestPipeline(room.owner_repository, room.store, vision=None)
    outsider = VOLCANIC / _NAMES[1]
    intake = pipeline.ingest_intake(outsider.read_bytes(), filename=outsider.name)
    assert intake.capture_id is not None, intake.error
    tombstone_id = room.owner_repository.insert_tombstone(
        scope="capture", capture_id=intake.capture_id, requested_by=uuid.uuid4()
    )
    raised = _refused(
        room,
        lambda c: _event(
            c, room.workspace, record_id, 1, "not_attempted", "registered_scene", "withdrawal",
            withdrawal_tombstone_id=tombstone_id,
        ),
    )  # fmt: skip
    assert "the_basis_can_reach_the_state" in raised


def test_nothing_in_the_record_is_a_float_or_a_clock_in_the_digest(room):
    verdict = _verdict_for(room)
    record = verdict.record()

    def walk(value, path="$"):
        assert not isinstance(value, float), path
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(record)
    with room.session() as connection:
        record_id = _open_record(connection, room.workspace, room.captures, verdict)
        stored = connection.execute(
            "select verdict_canonical, verdict_record from place_record where record_id = %s",
            (record_id,),
        ).fetchone()
    assert bytes(stored["verdict_canonical"]) == verdict.canonical_bytes()
    assert canonical_json(stored["verdict_record"]) == verdict.canonical_bytes()
