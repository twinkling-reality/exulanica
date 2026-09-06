"""The observation graph behind click-to-evidence: recorded, bounded, and honest about both.

The claim under test is that a viewer selecting a surface can be told which photographs actually
observed it, from what COLMAP recorded rather than from a reprojection guess, and that the answer
never overstates itself: the retained set is a bounded sample, and every point says how much of
its real track it is holding.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from exulanica.evidence.blob import BlobId
from exulanica.graph.observations import OBSERVATIONS_PROFILE, scene_observations
from exulanica.ingest.repository import IngestRepository

from test_world_read_bundle import _published_scene


def _canonical(value: object) -> bytes:
    """The pose receipt's own canonicalisation. It permits floats; the digest layer does not."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _pose_receipt_bytes(repository, scene_id, store) -> bytes:
    row = repository.connection.execute(
        "select a.content_sha256 from reconstruction_scene s "
        "join reconstruction_scene_job j on j.workspace_id = s.workspace_id "
        " and j.job_id = s.current_job_id "
        "join artifact a on a.workspace_id = s.workspace_id "
        " and a.artifact_id = j.pose_receipt_artifact_id "
        "where s.workspace_id = %s and s.scene_id = %s",
        (repository.workspace_id, scene_id),
    ).fetchone()
    return store.get(BlobId(bytes(row["content_sha256"])))


def _replace_pose_receipt(repository, scene_id, store, receipt: dict) -> None:
    """Rewrite the stored pose receipt in place, and repoint the artifact row at the new bytes.

    A content-addressed store will not let one key hold two contents, so the edited receipt is a
    new object and the artifact row has to name it. Test-only surgery on a disposable schema; the
    ordinary pipeline never rewrites a receipt.
    """
    payload = _canonical(receipt)
    digest = BlobId.of_bytes(payload)
    path = store.root / store.key_for(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    repository.connection.execute(
        "update artifact set content_sha256=%s, byte_size=%s "
        "where workspace_id=%s and scene_id=%s and kind='pose_receipt'",
        (digest.digest, len(payload), repository.workspace_id, scene_id),
    )


def _scene(repository, tmp_path):
    return _published_scene(repository, tmp_path, registered=3, spacing=5)


def test_every_point_names_the_photographs_that_observed_it(repository, tmp_path):
    store, captures, scene_id = _scene(repository, tmp_path)
    records = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert records is not None
    assert records["profile"] == OBSERVATIONS_PROFILE
    assert records["provenance"] == "recorded"
    assert records["point_count"] > 0

    live = {str(capture) for capture in captures}
    multi_view = 0
    for point in records["points"]:
        observers = [item["capture_id"] for item in point["observations"]]
        assert observers, "a point with no observation should not be listed at all"
        assert len(set(observers)) == len(observers), "one photograph cannot observe a point twice"
        assert set(observers) <= live
        if len(observers) > 1:
            multi_view += 1
    assert multi_view > 0, (
        "the fixture projects one plane through several cameras, so some points must be seen by "
        "more than one photograph. Without that this proves nothing about multi-view provenance."
    )


def test_the_answer_says_how_much_of_each_track_it_is_holding(repository, tmp_path):
    """The bounded sample, stated per point rather than as a footnote a caller can skip."""
    store, _captures, scene_id = _scene(repository, tmp_path)
    records = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert records is not None
    assert records["retained_per_image"] == 4096
    assert "track_length" in records["sampling"]
    for point in records["points"]:
        assert point["observations_retained"] == len(point["observations"])
        assert point["track_length"] >= point["observations_retained"]


def test_a_truncated_track_reports_the_count_it_could_not_hold(repository, tmp_path):
    """The assertion above is trivially true on this fixture, and this is the one that is not.

    Nothing here is truncated: three photographs, far under the 4096-per-image cap, so a point's
    track length always equals the observations held and ``track_length >= retained`` cannot fail.
    A real capture is where the two diverge, and the 2026-09-06 read of the retained volcanic set
    measured tracks up to 100.

    So this edits the scene's own pose receipt to declare a longer track than its retained rows
    support, which is exactly the shape truncation produces, and requires the answer to report the
    photographs that observed the point rather than the ones it happens to hold. A reader that
    counted its own rows would say 3 where the world says 40.
    """
    store, _captures, scene_id = _scene(repository, tmp_path)
    honest = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert honest is not None
    sample = honest["points"][0]
    assert sample["track_length"] == sample["observations_retained"]

    receipt = json.loads(_pose_receipt_bytes(repository, scene_id, store))
    target = sample["point_id"]
    touched = 0
    for camera in receipt["quality"]["cameras"]:
        for row in camera["sparse_observations"]:
            if int(row[0]) == target:
                row[7] = 40
                touched += 1
    assert touched == sample["observations_retained"] > 1
    receipt["quality_digest"] = hashlib.sha256(_canonical(receipt["quality"])).hexdigest()
    _replace_pose_receipt(repository, scene_id, store, receipt)

    records = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert records is not None
    point = next(item for item in records["points"] if item["point_id"] == target)
    assert point["track_length"] == 40
    assert point["observations_retained"] == touched
    assert point["observations_retained"] < point["track_length"]


def test_no_float_reaches_the_wire(repository, tmp_path):
    store, _captures, scene_id = _scene(repository, tmp_path)
    records = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert records is not None
    for point in records["points"]:
        assert all(isinstance(value, str) for value in point["world_xyz"])
        assert isinstance(point["point_id"], int)
        for item in point["observations"]:
            assert isinstance(item["x"], str)
            assert isinstance(item["y"], str)
            assert isinstance(item["reprojection_error_px"], str)


def test_every_observation_carries_its_photograph_consent_state(repository, tmp_path):
    """A photograph a person has not consented to appear in is never the answer to a click."""
    store, _captures, scene_id = _scene(repository, tmp_path)
    records = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert records is not None
    for point in records["points"]:
        for item in point["observations"]:
            consent = item["consent"]
            assert consent["basis"] == "human-screening-receipt"
            assert consent["person_consent"] == "unavailable"


def test_a_scene_without_an_accepted_pose_has_no_observation_graph(repository, tmp_path):
    """Absence, not an empty point list, which would read as "this scene observed nothing"."""
    store, _captures, scene_id = _published_scene(repository, tmp_path, registered=2, spacing=1)
    assert (
        scene_observations(repository.connection, repository.workspace_id, scene_id, store) is None
    )


def test_another_workspace_reads_nothing(repository, tmp_path, ingest_spine):
    store, _captures, scene_id = _scene(repository, tmp_path)
    _primary, open_another = ingest_spine
    elsewhere = uuid.uuid4()
    other = IngestRepository(open_another().connection, elsewhere)
    assert scene_observations(other.connection, elsewhere, scene_id, store) is None


def test_withdrawing_a_member_withdraws_the_whole_observation_graph(repository, tmp_path):
    """Scene-scoped, because these rows are a fact about N photographs together.

    A per-capture guard would keep serving the graph while one withdrawn photograph's observations
    were merely filtered out of it, and what remained would still be a claim about a set the user
    withdrew from.
    """
    store, captures, scene_id = _scene(repository, tmp_path)
    assert (
        scene_observations(repository.connection, repository.workspace_id, scene_id, store)
        is not None
    )
    repository.insert_tombstone(
        scope="capture",
        capture_id=captures[0],
        requested_by=uuid.uuid4(),
        reason="observation graph withdrawal test",
    )
    assert (
        scene_observations(repository.connection, repository.workspace_id, scene_id, store) is None
    )


def test_the_method_sentence_refuses_to_claim_reprojection_is_provenance(repository, tmp_path):
    store, _captures, scene_id = _scene(repository, tmp_path)
    records = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert records is not None
    assert "not visibility inferred" in records["method"]
