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

import pytest
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
    """A photograph a person has not consented to appear in is never the answer to a click.

    The fixture writes no person regions, so every photograph here is ``unscreened``: nobody has
    looked at it for people. That is the restrictive answer and it is deliberately not the same
    fact as "there is nobody in it", which is what the pre-2026-09-07 vocabulary's ``unavailable``
    would have collapsed to now that the layer it referred to has merged.

    What this route still cannot do is filter, and P10-A-b's last open box is exactly that: the
    caller can now tell a screened photograph from an unscreened one, but no per-person state
    reaches an observation, so "not offered because that person forbids it" has nothing to read.
    """
    store, _captures, scene_id = _scene(repository, tmp_path)
    records = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert records is not None
    seen = 0
    for point in records["points"]:
        for item in point["observations"]:
            consent = item["consent"]
            assert consent["basis"] == "human-screening-receipt"
            assert consent["person_consent"] == "unscreened"
            assert consent["recorded_person_count"] == 0
            seen += 1
    assert seen, "a consent assertion over an empty observation set proves nothing"


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


def test_the_unbounded_answer_holds_every_point_and_now_says_so(repository, tmp_path):
    """The default did not change, and a complete answer has to state that it is complete.

    Both halves matter. A caller already reading this route asked for the whole graph and still
    gets it, so no default quietly started answering a smaller question. And "complete" is now a
    field rather than an inference from the absence of a cursor, because an inference is what a
    client gets wrong.
    """
    store, _captures, scene_id = _scene(repository, tmp_path)
    records = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert records is not None
    bounds = records["bounds"]
    assert bounds["state"] == "complete"
    assert bounds["limit"] is None
    assert bounds["after_point_id"] is None
    assert bounds["next_point_id"] is None
    assert bounds["point_count_not_returned"] == 0
    assert bounds["point_count_total"] == bounds["point_count_returned"] == records["point_count"]
    assert bounds["observations_total"] == bounds["observations_returned"]
    assert bounds["observations_total"] == sum(
        point["observations_retained"] for point in records["points"]
    )


def test_a_page_says_it_is_a_page_and_names_the_points_it_left_behind(repository, tmp_path):
    """A truncated answer that reads as complete is the failure this route can produce.

    It is the sampling rule one level up. A point that holds 3 of 40 observations says so through
    ``track_length``; an answer that holds 1 of 15005 points has to say so the same way, or a
    client counting what it received understates the world and has no way to know it did.
    """
    store, _captures, scene_id = _scene(repository, tmp_path)
    whole = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert whole is not None
    total = whole["point_count"]
    assert total > 1, "a one-point scene cannot demonstrate a page"

    page = scene_observations(
        repository.connection, repository.workspace_id, scene_id, store, limit=1
    )
    assert page is not None
    bounds = page["bounds"]
    assert bounds["state"] == "page"
    assert bounds["limit"] == 1
    assert bounds["point_count_returned"] == page["point_count"] == len(page["points"]) == 1
    assert bounds["point_count_total"] == total
    assert bounds["point_count_not_returned"] == total - 1
    assert bounds["next_point_id"] == page["points"][0]["point_id"]
    assert f"1 of the {total} points" in bounds["note"]
    # `point_count` keeps meaning "points in this answer", which is what it has always meant. The
    # scene's own total lives in `bounds`, and the two are never the same field: one field that
    # changed meaning between a complete answer and a page is a field a client reads wrongly.
    assert page["point_count"] != bounds["point_count_total"]


def test_a_page_is_smaller_on_the_wire_than_the_whole_graph(repository, tmp_path):
    """The size claim, measured rather than asserted, and measured twice.

    MEASURED 2026-09-07, read-only against the retained reference instance
    (``postgresql://localhost:5433/exulanica_spine_test``, store
    ``.exulanica/reference-baseline/runtime/blobs``): the bowl scene
    ``851ca35b-31c3-560c-84f9-4e142962755b`` serialises to 97,633,587 canonical bytes over 15005
    points, and a 500-point page of it to 4,973,392, which is 5.1%. The volcanic scene
    ``45ad50b7`` serialises to 1,179,240,157 bytes over 111694 points, and a 500-point page to
    8,173,297, which is 0.7%. This fixture is three photographs and cannot reproduce those
    numbers; what it can do, and does here, is fail if a page ever stops being smaller than the
    graph it came from, which is what those measurements would stop meaning.
    """
    store, _captures, scene_id = _scene(repository, tmp_path)
    whole = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    page = scene_observations(
        repository.connection, repository.workspace_id, scene_id, store, limit=1
    )
    assert whole is not None and page is not None
    whole_bytes = len(_canonical(whole))
    page_bytes = len(_canonical(page))
    assert page_bytes < whole_bytes, (whole_bytes, page_bytes)
    assert whole["point_count"] > page["point_count"]


def test_a_cursor_walks_every_point_exactly_once(repository, tmp_path):
    """A cursor that skipped or repeated a point would assemble a graph nobody observed.

    The order is COLMAP's global point id and the pose receipt holding it is immutable, so the
    walk is asserted against the complete answer rather than against itself: paging must be a way
    of receiving the same graph, not a different graph that happens to be the same length.
    """
    store, _captures, scene_id = _scene(repository, tmp_path)
    whole = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert whole is not None

    walked: list[dict] = []
    cursor = None
    while True:
        page = scene_observations(
            repository.connection,
            repository.workspace_id,
            scene_id,
            store,
            limit=2,
            after_point_id=cursor,
        )
        assert page is not None
        walked.extend(page["points"])
        cursor = page["bounds"]["next_point_id"]
        if cursor is None:
            break
    assert walked == whole["points"]
    assert len(walked) == whole["point_count"]


def test_a_limit_of_zero_is_refused_rather_than_answering_with_no_points(repository, tmp_path):
    """An empty point list reads as "this scene observed nothing", which is the one sentence this
    module refuses to write. A caller asking for zero points has made a mistake, and a page of
    none is not the answer to it."""
    store, _captures, scene_id = _scene(repository, tmp_path)
    with pytest.raises(ValueError, match="at least one point"):
        scene_observations(repository.connection, repository.workspace_id, scene_id, store, limit=0)


def test_withdrawal_between_pages_refuses_the_remaining_observations(repository, tmp_path):
    """The first response gives no authority to keep reading after its source is withdrawn."""
    store, captures, scene_id = _scene(repository, tmp_path)
    first = scene_observations(
        repository.connection, repository.workspace_id, scene_id, store, limit=1
    )
    assert first is not None
    cursor = first["bounds"]["next_point_id"]
    assert cursor is not None
    repository.insert_tombstone(
        scope="capture",
        capture_id=captures[0],
        requested_by=uuid.uuid4(),
        reason="withdrawal between observation pages",
    )
    assert (
        scene_observations(
            repository.connection,
            repository.workspace_id,
            scene_id,
            store,
            limit=1,
            after_point_id=cursor,
        )
        is None
    )


def test_an_exhausted_cursor_does_not_claim_the_scene_observed_nothing(repository, tmp_path):
    """An empty continuation retains scene totals and never claims to be the complete graph."""
    store, _captures, scene_id = _scene(repository, tmp_path)
    whole = scene_observations(repository.connection, repository.workspace_id, scene_id, store)
    assert whole is not None and whole["point_count"] > 0
    page = scene_observations(
        repository.connection,
        repository.workspace_id,
        scene_id,
        store,
        limit=2,
        after_point_id=whole["points"][-1]["point_id"],
    )
    assert page is not None
    assert page["points"] == []
    assert page["bounds"]["state"] == "page"
    assert page["bounds"]["next_point_id"] is None
    assert page["bounds"]["point_count_total"] == whole["point_count"]
    assert page["bounds"]["point_count_not_returned"] == whole["point_count"]
    assert page["bounds"]["observations_returned"] == 0
    assert page["bounds"]["observations_total"] == whole["bounds"]["observations_total"]
