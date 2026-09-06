"""The observation graph behind click-to-evidence: recorded, bounded, and honest about both.

The claim under test is that a viewer selecting a surface can be told which photographs actually
observed it, from what COLMAP recorded rather than from a reprojection guess, and that the answer
never overstates itself: the retained set is a bounded sample, and every point says how much of
its real track it is holding.
"""

from __future__ import annotations

import uuid

from exulanica.graph.observations import OBSERVATIONS_PROFILE, scene_observations
from exulanica.ingest.repository import IngestRepository

from test_world_read_bundle import _published_scene


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
        # COLMAP's full count is read before truncation, so it is never smaller than what is held.
        assert point["track_length"] >= point["observations_retained"]


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
