"""Addressing a place and a time, and what each answer refuses to pretend.

The plane's constraints are ``tests/test_place_plane.py``. What is checked here is the read over
it: that a time resolves to the version that was in force then, that every way a place can fail to
resolve produces a different and honest answer, and that a transform this reader could not verify
is never served as identity, because identity is what a place drawn with no alignment looks like.

Each test is named for the failure it catches.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.graph.places import PLACE_ALIGNMENT_RECEIPT_PROFILE, place_history
from exulanica.graph.world_read import place_read_bundle, world_read_bundle
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.scenes import run_scene_grouping
from exulanica.reconstruction.place_alignment import PLACE_ALIGNMENT_POLICY

from conftest import CountingVisionModel, write_photo, write_point_map
from test_scene_reconstruction_pipeline import (
    FakeColmap,
    _numeric_point_map,
    _processor,
)
from test_world_read_bundle import _canonical, _published_scene

#: The two capture occasions this file photographs the same fixture "place" on. They are a month
#: apart because that is the case the place plane exists for, and every time assertion below is
#: written against these two rather than against ``now()``.
FIRST = dt.datetime(2026, 9, 4, 12, 0, tzinfo=dt.UTC)
SECOND = dt.datetime(2026, 10, 4, 12, 0, tzinfo=dt.UTC)


def _second_scene(repository, store, tmp_path: Path):
    """A second published scene in the same workspace, which is the least a place needs.

    ``_queued_scene`` cannot be called twice: it writes the same three photographs, and identical
    bytes are the same blobs, the same captures and therefore the same scene. So this ingests
    three different photographs, taken a month later, and takes them through the same grouping,
    claim and processor path the first scene went through.
    """
    photos = tmp_path / "second-capture"
    photos.mkdir(exist_ok=True)
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    captures = []
    for index in range(3):
        # The same dimensions as the first occasion and a later EXIF time, so the bytes differ
        # and the frames do not. A different size fails the processor's own check that COLMAP and
        # the point-map source agree, which is a fixture defect that would surface here as an
        # unpublishable second scene rather than as the thing this file is about.
        path = write_photo(
            photos, f"second{index}.jpg", when=f"2026:10:04 12:0{index}:00", size=(160 + index, 100)
        )
        outcome = pipeline.ingest_file(path)
        assert outcome.error is None
        captures.append(outcome.capture_id)
        write_point_map(
            repository, store, BlobId.of_bytes(path.read_bytes()), payload=_numeric_point_map(index)
        )
    report = run_scene_grouping(repository)
    assert report.reconstruction_jobs, "the second occasion must form a scene job of its own"
    claimed = repository.claim_reconstruction_scene(worker="place-read", lease_seconds=60)
    assert claimed is not None
    outcome = _processor(
        repository, store, tmp_path / "second", FakeColmap(registered=3, camera_spacing=5)
    ).process(claimed)
    assert outcome.scene_id is not None, outcome.message
    return captures, outcome.scene_id


def _receipt_body(place_id, candidate, against, *, matrix, scale, hops):
    """One place-alignment receipt in the agreed shape, as the stage will write it.

    Written by hand rather than produced by the stage, for the reason ``write_point_map`` gives
    for its own row: this file must be able to place a receipt that is wrong in one specific way,
    and a helper that could only produce correct ones could not test a reader's refusals.
    """
    fit = {
        "accepted": True,
        "reason": None,
        "joint_from_scene_row_major": list(matrix),
        "scene_units_to_joint_units": scale,
        "diagnostics": {"method": PLACE_ALIGNMENT_POLICY["method"], "physically_validated": False},
        "training_count": 12,
        "validation_count": 3,
    }
    return {
        "profile": PLACE_ALIGNMENT_RECEIPT_PROFILE,
        "place_id": str(place_id),
        "candidate_scene_id": str(candidate),
        "against_scene_id": str(against),
        "policy": PLACE_ALIGNMENT_POLICY,
        "policy_sha256": hashlib.sha256(_canonical(PLACE_ALIGNMENT_POLICY)).hexdigest(),
        "union": {"member_digest": "ab" * 32, "frames": []},
        "joint_model_sha256": "cd" * 32,
        "fits": {"candidate": fit, "against": dict(fit, scene_units_to_joint_units=1.0)},
        "place_from_candidate_row_major": list(matrix),
        "candidate_units_to_place_units": scale,
        "frame_hops": hops,
        "accepted": True,
        "reason": None,
        "physically_validated": False,
    }


class Bound:
    """A place over two published scenes, and the handles a test needs to disturb it."""

    def __init__(self, store, place_id, anchor, candidate, alignment_id, receipt_digest) -> None:
        self.store = store
        self.place_id = place_id
        self.anchor = anchor
        self.candidate = candidate
        self.alignment_id = alignment_id
        self.receipt_digest = receipt_digest


def _artifact(repository, place_id, digest, byte_size) -> uuid.UUID:
    artifact_id = uuid.uuid4()
    repository.connection.execute(
        "insert into artifact (artifact_id, workspace_id, kind, stage_key, stage_version, "
        "params_digest, input_digest, idempotency_key, place_id, content_sha256, byte_size) "
        "values (%s, %s, 'place_alignment_receipt', 'place_alignment', 1, %s, %s, %s, %s, %s, %s)",
        (
            artifact_id,
            repository.workspace_id,
            bytes(32),
            bytes(32),
            f"place-alignment:{uuid.uuid4()}",
            place_id,
            digest,
            byte_size,
        ),
    )
    return artifact_id


def _bind(
    repository,
    store,
    anchor_scene,
    candidate_scene,
    *,
    matrix=(2.0, 0.0, 0.0, 5.0, 0.0, 2.0, 0.0, 6.0, 0.0, 0.0, 2.0, 7.0, 0.0, 0.0, 0.0, 1.0),
    scale=2.0,
    body=None,
    accepted=True,
    reason=None,
) -> Bound:
    """Create a place, anchor it, and admit the candidate by one accepted alignment.

    This is the forward migration ``docs/place-identity.md`` describes, written out: a place row,
    an alignment receipt, and one ``place_version`` per scene. No UPDATE is issued against
    ``reconstruction_scene``, which the append-only trigger would refuse anyway.
    """
    place_id = repository.connection.execute(
        "insert into place (workspace_id) values (%s) returning place_id",
        (repository.workspace_id,),
    ).fetchone()["place_id"]
    payload = _canonical(
        body
        if body is not None
        else _receipt_body(
            place_id, candidate_scene, anchor_scene, matrix=matrix, scale=scale, hops=1
        )
    )
    written = store.put_bytes(payload)
    artifact_id = _artifact(repository, place_id, written.blob_id.digest, len(payload))
    alignment_id = uuid.uuid4()
    repository.connection.execute(
        "insert into place_alignment (alignment_id, workspace_id, place_id, candidate_scene_id, "
        "against_scene_id, union_member_digest, policy_digest, joint_model_sha256, accepted, "
        "reason, receipt_artifact_id) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            alignment_id,
            repository.workspace_id,
            place_id,
            candidate_scene,
            anchor_scene,
            uuid.uuid4().bytes + uuid.uuid4().bytes,
            bytes(32),
            bytes.fromhex("cd" * 32),
            accepted,
            reason,
            artifact_id,
        ),
    )
    repository.connection.execute(
        "insert into place_version (workspace_id, place_id, scene_id, ordinal, ordered_by_utc, "
        "ordered_by_basis, frame_hops) values (%s, %s, %s, 0, %s, 'capture_exif', 0)",
        (repository.workspace_id, place_id, anchor_scene, FIRST),
    )
    if accepted:
        repository.connection.execute(
            "insert into place_version (workspace_id, place_id, scene_id, ordinal, "
            "ordered_by_utc, ordered_by_basis, frame_hops, admitted_by_alignment_id) "
            "values (%s, %s, %s, 1, %s, 'capture_exif', 1, %s)",
            (repository.workspace_id, place_id, candidate_scene, SECOND, alignment_id),
        )
    return Bound(store, place_id, anchor_scene, candidate_scene, alignment_id, written.blob_id)


@pytest.fixture
def two_scenes(repository, tmp_path):
    """Two published scenes a month apart, both readable on their own before any place exists."""
    store, _captures, first = _published_scene(repository, tmp_path, registered=3, spacing=5)
    _second_captures, second = _second_scene(repository, store, tmp_path)
    assert first != second
    return store, first, second


@pytest.fixture
def place(repository, two_scenes):
    store, first, second = two_scenes
    return _bind(repository, store, first, second)


def _bundle(repository, place_id, store, at=None):
    return place_read_bundle(repository.connection, repository.workspace_id, place_id, store, at=at)


def test_a_time_between_two_versions_resolves_to_the_earlier_one(repository, place):
    """Rounding forward answers with photographs that did not exist at the time asked for.

    This is the whole arithmetic of addressing a place by time, and it has exactly one off-by-one:
    a moment after the first capture and before the second is a moment when the first capture was
    the latest record of this place. Answering with the second would show a visitor a world that
    had not been photographed yet.
    """
    between = FIRST + dt.timedelta(days=10)
    envelope = _bundle(repository, place.place_id, place.store, at=between)
    assert envelope is not None
    addressing = envelope["bundle"]["addressing"]
    assert addressing["by"] == "place_at_time"
    assert addressing["scene_id"] == str(place.anchor)
    assert addressing["place"]["version_ordinal"] == 0
    assert addressing["place"]["version_count"] == 2
    assert addressing["at"] == between.isoformat()
    assert envelope["bundle"]["scene"]["scene_id"] == str(place.anchor)

    # And the boundary itself: at the exact instant a version was captured, that version is the
    # answer. A strict `<` here would resolve a place to its predecessor on its own capture day.
    exact = _bundle(repository, place.place_id, place.store, at=SECOND)
    assert exact is not None
    assert exact["bundle"]["addressing"]["place"]["version_ordinal"] == 1
    assert exact["bundle"]["scene"]["scene_id"] == str(place.candidate)

    # After the last version, the last version stands. A place is not unreadable on the day after
    # its most recent capture.
    later = _bundle(repository, place.place_id, place.store, at=SECOND + dt.timedelta(days=400))
    assert later is not None
    assert later["bundle"]["scene"]["scene_id"] == str(place.candidate)


def test_a_time_before_the_first_version_answers_rather_than_reporting_a_missing_place(
    repository, place
):
    """A place with no version that early is not a missing place, and must not answer like one.

    The two failures this catches are opposite. A 404 says the place does not exist, which is
    false and which a caller cannot distinguish from a wrong id. An ordinary bundle with an empty
    scene reads as a place with nothing in it, which is worse, because it is a claim about the
    world rather than about this address.
    """
    envelope = _bundle(repository, place.place_id, place.store, at=FIRST - dt.timedelta(days=1))
    assert envelope is not None
    bundle = envelope["bundle"]
    assert bundle["addressing"]["place"]["state"] == "no_version_at_that_time"
    assert bundle["addressing"]["scene_id"] is None
    assert bundle["unresolved"]["earliest_version_utc"] == FIRST.isoformat()
    assert bundle["unresolved"]["latest_version_utc"] == SECOND.isoformat()
    # No scene, no views, no geometry: a consumer reaching for one gets a KeyError rather than an
    # empty list it could render as an empty world.
    assert "scene" not in bundle
    assert "views" not in bundle
    assert "geometry" not in bundle
    # The place is still fully described, so the caller can see what it could have asked for.
    assert bundle["place"]["version_count"] == 2
    assert [version["ordered_by_utc"] for version in bundle["place"]["versions"]] == [
        FIRST.isoformat(),
        SECOND.isoformat(),
    ]
    # And it is digest-bound like every other answer this API gives.
    assert hashlib.sha256(_canonical(bundle)).hexdigest() == envelope["bundle_sha256"]


def test_a_place_whose_anchor_is_withdrawn_is_not_served(repository, place):
    """Every version's frame is the anchor's, so serving the rest routes around the withdrawal.

    The failure is not that a withdrawn photograph is returned. It is that the OTHER version's
    geometry, which nobody withdrew, is expressed in a frame recovered from photographs somebody
    did withdraw, and serving it under the place address publishes that frame.
    """
    assert _bundle(repository, place.place_id, place.store, at=SECOND) is not None
    member = repository.connection.execute(
        "select capture_id from reconstruction_scene_member "
        "where workspace_id=%s and scene_id=%s order by ordinal limit 1",
        (repository.workspace_id, place.anchor),
    ).fetchone()
    repository.insert_tombstone(
        scope="capture",
        capture_id=member["capture_id"],
        requested_by=uuid.uuid4(),
        reason="place anchor withdrawal test",
    )
    assert _bundle(repository, place.place_id, place.store, at=SECOND) is None
    assert (
        place_history(repository.connection, repository.workspace_id, place.place_id, None) is None
    )
    # The candidate scene is untouched, which is the other half of the rule: a place is a join,
    # and withdrawing the anchor takes the shared frame away rather than the other capture.
    assert (
        world_read_bundle(
            repository.connection, repository.workspace_id, place.candidate, place.store
        )
        is not None
    )


def test_a_withdrawn_later_capture_leaves_the_place_and_its_anchor_standing(repository, place):
    """A place is a join, never a merge, and the version list has to show that.

    The failure this catches is a place-wide guard reduced over its members: an AND would keep
    serving a version whose own photographs were withdrawn, and an OR would take the whole place
    down when one later capture left. Neither is what the schema's own function does.
    """
    member = repository.connection.execute(
        "select capture_id from reconstruction_scene_member "
        "where workspace_id=%s and scene_id=%s order by ordinal limit 1",
        (repository.workspace_id, place.candidate),
    ).fetchone()
    repository.insert_tombstone(
        scope="capture",
        capture_id=member["capture_id"],
        requested_by=uuid.uuid4(),
        reason="place later-version withdrawal test",
    )
    envelope = _bundle(repository, place.place_id, place.store, at=SECOND)
    assert envelope is not None
    bundle = envelope["bundle"]
    assert bundle["place"]["version_count"] == 1
    assert [version["scene_id"] for version in bundle["place"]["versions"]] == [str(place.anchor)]
    # And the address resolves to the anchor, because at that time the withdrawn version is no
    # longer a record of this place at all.
    assert bundle["scene"]["scene_id"] == str(place.anchor)


def test_the_anchor_is_reported_as_identity_rather_than_as_a_measured_fit(repository, place):
    """A frame nothing measured must not be presented beside ones something did.

    ``place_from_scene`` for the anchor is identity by construction. Reporting it with the same
    ``available`` state an accepted receipt earns would tell a reader a joint reconstruction had
    measured the anchor against itself, which is the shape ``an_alignment_is_between_two_scenes``
    refuses in the schema.
    """
    envelope = _bundle(repository, place.place_id, place.store)
    assert envelope is not None
    versions = {item["ordinal"]: item for item in envelope["bundle"]["place"]["versions"]}
    anchor = versions[0]["place_from_scene"]
    assert anchor["state"] == "identity"
    assert anchor["receipt_sha256"] is None
    assert versions[0]["admitted_by_alignment_id"] is None
    assert versions[0]["frame_hops"] == 0
    assert anchor["row_major"] == [
        "1.000000000000" if index % 5 == 0 else "0.000000000000" for index in range(16)
    ]

    measured = versions[1]["place_from_scene"]
    assert measured["state"] == "available"
    assert versions[1]["frame_hops"] == 1
    assert measured["receipt_sha256"] == place.receipt_digest.hex
    assert measured["scene_units_to_place_units"] == "2.000000000000"
    assert measured["row_major"][3] == "5.000000000000"


def test_a_version_whose_receipt_bytes_are_gone_is_not_reported_as_identity(repository, place):
    """An unreadable transform substituted with identity looks exactly like a good alignment.

    It is the one wrong answer this seam must never give: a place drawn with an identity it never
    measured shows two captures on top of each other and offers no sign that anything is missing.
    """
    path = place.store.root / place.store.key_for(place.receipt_digest)
    path.unlink()
    envelope = _bundle(repository, place.place_id, place.store)
    assert envelope is not None
    versions = {item["ordinal"]: item for item in envelope["bundle"]["place"]["versions"]}
    transform = versions[1]["place_from_scene"]
    assert transform["state"] == "unavailable"
    assert transform["row_major"] is None
    assert transform["scene_units_to_place_units"] is None
    assert "missing from object storage" in transform["reason"]
    # The version is still listed, and the address still resolves to it. What is withheld is the
    # frame, not the fact that this capture is part of this place.
    assert envelope["bundle"]["scene"]["scene_id"] == str(place.candidate)


def test_a_receipt_measured_for_another_scene_is_refused_rather_than_served_as_this_frame(
    repository, two_scenes
):
    """The row says which scene was admitted; the receipt says what was measured.

    A reader that trusted the row alone would serve a transform fitted for some other capture as
    this one's frame, and every number in it would be a real measurement of the wrong thing.
    """
    store, first, second = two_scenes
    stranger = uuid.uuid4()
    place = _bind(
        repository,
        store,
        first,
        second,
        body=None,
    )
    # Replace the stored receipt with one that names a different candidate, keeping the artifact
    # row pointing at the new bytes the way the store's own immutability forces.
    original = json.loads(store.get(place.receipt_digest))
    original["candidate_scene_id"] = str(stranger)
    payload = _canonical(original)
    written = store.put_bytes(payload)
    repository.connection.execute(
        "update artifact set content_sha256=%s, byte_size=%s "
        "where workspace_id=%s and place_id=%s and kind='place_alignment_receipt'",
        (written.blob_id.digest, len(payload), repository.workspace_id, place.place_id),
    )

    envelope = _bundle(repository, place.place_id, store)
    assert envelope is not None
    versions = {item["ordinal"]: item for item in envelope["bundle"]["place"]["versions"]}
    transform = versions[1]["place_from_scene"]
    assert transform["state"] == "invalid"
    assert transform["row_major"] is None
    assert "not the scene this alignment admitted" in transform["reason"]


def test_a_refused_alignment_is_readable_as_a_refusal(repository, two_scenes):
    """A refusal that nothing can read is indistinguishable from a join nobody attempted.

    ``docs/place-identity.md`` makes refusal an outcome precisely so the world can say two
    captures are of related places whose frames could not be reconciled. That sentence needs the
    row, the reason and the two scenes, and this is the seam that has to carry all three.
    """
    store, first, second = two_scenes
    place = _bind(
        repository,
        store,
        first,
        second,
        accepted=False,
        reason="place-alignment-inconsistent",
    )
    envelope = _bundle(repository, place.place_id, store)
    assert envelope is not None
    bundle = envelope["bundle"]
    # The refused candidate is not a version: its frame was never reconciled with the anchor's.
    assert bundle["place"]["version_count"] == 1
    refusals = bundle["place"]["refused_alignments"]
    assert len(refusals) == 1
    assert refusals[0]["reason"] == "place-alignment-inconsistent"
    assert refusals[0]["candidate_scene_id"] == str(second)
    assert refusals[0]["against_scene_id"] == str(first)
    assert "did not reconcile their frames" in refusals[0]["means"]
    # And the refused scene is still a scene, readable at its own address. A refusal makes two
    # places; it does not withdraw a capture.
    assert (
        world_read_bundle(repository.connection, repository.workspace_id, second, store) is not None
    )


def test_a_scene_address_still_answers_with_the_same_scene_after_it_joins_a_place(
    repository, two_scenes
):
    """A scene is still a real thing after it joins a place, and its bundle has to prove it.

    Everything a scene bundle says about the world is unchanged by the bind. What does change is
    the addressing block, which now names the place, and therefore the digest. That is correct
    rather than unfortunate and it is why the two are asserted separately: a bind is a write, and
    a digest that ignored a write would be a digest a recipient could not use to detect one.
    """
    store, first, second = two_scenes
    before = world_read_bundle(repository.connection, repository.workspace_id, first, store)
    assert before is not None
    assert before["bundle"]["addressing"]["place"]["state"] == "none"

    place = _bind(repository, store, first, second)
    after = world_read_bundle(repository.connection, repository.workspace_id, first, store)
    assert after is not None

    for key in ("scene", "rungs", "views", "geometry", "generated", "consent", "release"):
        assert after["bundle"][key] == before["bundle"][key], key
    assert after["bundle"]["addressing"] != before["bundle"]["addressing"]
    assert after["bundle_sha256"] != before["bundle_sha256"]

    membership = after["bundle"]["addressing"]["place"]
    assert membership["state"] == "member"
    assert membership["place_id"] == str(place.place_id)
    assert membership["version_ordinal"] == 0
    assert membership["version_count"] == 2
    assert after["bundle"]["addressing"]["by"] == "reconstruction_scene"


def test_the_recorded_digest_moves_with_the_addressing_block_and_recomputes_from_it(
    repository, place
):
    """The recipient's half: the recipe is the keys the bundle names, and addressing is one.

    Two claims, and the second is the one a constant would pass. The recorded digest recomputes
    from the wire bytes under an independent canonicaliser, and it is genuinely a function of the
    addressing block, which is what makes a place-addressed bundle and a scene-addressed one over
    the same scene different documents rather than the same one served twice.
    """
    envelope = _bundle(repository, place.place_id, place.store, at=SECOND)
    assert envelope is not None
    received = json.loads(json.dumps(envelope))["bundle"]
    recorded = {key: received[key] for key in received["recorded_keys"]}
    assert hashlib.sha256(_canonical(recorded)).hexdigest() == received["recorded_sha256"]
    assert "addressing" in received["recorded_keys"]
    assert "place" in received["recorded_keys"]

    mutated = json.loads(json.dumps(recorded))
    mutated["addressing"]["place"]["version_ordinal"] = 0
    assert hashlib.sha256(_canonical(mutated)).hexdigest() != received["recorded_sha256"]

    # The same scene under its own address is a different document, because it was asked a
    # different question. A recipient must never take one digest as evidence about the other.
    scene = world_read_bundle(
        repository.connection, repository.workspace_id, place.candidate, place.store
    )
    assert scene is not None
    assert scene["bundle"]["scene"] == received["scene"]
    assert scene["bundle"]["recorded_sha256"] != received["recorded_sha256"]


def test_the_bundle_names_what_it_can_and_cannot_be_addressed_by(repository, place):
    """The deleted limitation said place addressing was not implemented. It is now.

    A stale limitation is worse than none: it tells a recipient not to look for the thing they
    are holding. What replaces it has to be checkable, so both halves are asserted, including the
    one that is still true, which is that no entity has an address here.
    """
    scene = world_read_bundle(
        repository.connection, repository.workspace_id, place.anchor, place.store
    )
    envelope = _bundle(repository, place.place_id, place.store)
    assert scene is not None and envelope is not None
    for addressing in (scene["bundle"]["addressing"], envelope["bundle"]["addressing"]):
        assert "limitation" not in addressing
        assert "a place by its id with a time" in addressing["addresses"]
        assert addressing["not_addressable"].startswith("an entity")


def test_a_place_with_no_anchor_is_not_readable(repository, two_scenes):
    """A place row exists before its first alignment lands, and for that window it has no frame.

    The failure is a read that treats "no anchor" as "nothing blocks this": it would serve a
    place with no shared frame as an available one, which is the empty case failing open.
    """
    store, _first, _second = two_scenes
    place_id = repository.connection.execute(
        "insert into place (workspace_id) values (%s) returning place_id",
        (repository.workspace_id,),
    ).fetchone()["place_id"]
    assert place_history(repository.connection, repository.workspace_id, place_id, store) is None
    assert _bundle(repository, place_id, store) is None


def test_a_place_in_another_workspace_is_not_readable(repository, place, ingest_spine):
    """The cross-tenant probe, holding a real place id and a valid session for somewhere else."""
    from exulanica.ingest.repository import IngestRepository

    _primary, open_another = ingest_spine
    elsewhere = uuid.uuid4()
    other = IngestRepository(open_another().connection, elsewhere)
    assert place_read_bundle(other.connection, elsewhere, place.place_id, place.store) is None


def test_an_unknown_place_is_not_readable(repository, place):
    assert _bundle(repository, uuid.uuid4(), place.store) is None
