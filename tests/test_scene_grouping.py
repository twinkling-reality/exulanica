"""Scene grouping, and the line between a proposal and a fact.

Grouping photographs by time and position is what turns a folder into somewhere the user has
been. It is also the easiest place in the system to quietly assert something: a cluster with a
confident label looks exactly like a known place. It is not one, and these tests pin that.

The first five tests are arithmetic over dicts and touch no database. Everything below the
``grouped`` fixture runs against a real PostgreSQL server, because the derived rows, their
dependency index and the ledger events are the whole point: a proposal that is not persisted as
a proposal has not been shown to be one.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.scenes import group_captures, metres_between, run_scene_grouping
from exulanica.store.local import LocalContentAddressedStore

from conftest import CountingVisionModel, ingest_observed, write_photo

# No module-level postgres marker. tests/conftest.py marks each test by the fixtures it
# actually requests, so the handful here that need no server stay runnable without one.

GULLFOSS = (643271000, -201199000)


def _capture(hour: int, minute: int = 0, position=None, day: int = 27):
    return {
        "capture_id": uuid.uuid4(),
        "utc_instant": f"2026-08-{day:02d}T{hour:02d}:{minute:02d}:00+00:00",
        "gps": {"lat_e7": position[0], "lon_e7": position[1]} if position else None,
    }


def test_a_long_gap_starts_a_new_scene():
    captures = [_capture(10, 0), _capture(10, 5), _capture(14, 0)]
    groups, ungrouped = group_captures(captures, max_time_gap_s=3600, max_distance_m=250)
    assert [len(g.capture_ids) for g in groups] == [2, 1]
    assert ungrouped == 0


def test_moving_far_enough_starts_a_new_scene_even_within_the_time_window():
    far = (GULLFOSS[0] + 100_000, GULLFOSS[1])  # about 1.1 km north
    captures = [_capture(10, 0, GULLFOSS), _capture(10, 5, GULLFOSS), _capture(10, 10, far)]
    groups, _ = group_captures(captures, max_time_gap_s=3600, max_distance_m=250)
    assert [len(g.capture_ids) for g in groups] == [2, 1]


def test_a_missing_position_is_unknown_and_not_treated_as_far_away():
    """Otherwise one photograph with GPS switched off splits every scene it lands in."""
    captures = [_capture(10, 0, GULLFOSS), _capture(10, 5, None), _capture(10, 10, GULLFOSS)]
    groups, _ = group_captures(captures, max_time_gap_s=3600, max_distance_m=250)
    assert len(groups) == 1
    assert len(groups[0].capture_ids) == 3
    assert len(groups[0].positions) == 2


def test_a_capture_with_no_timestamp_is_left_ungrouped_rather_than_guessed():
    captures = [_capture(10, 0), {"capture_id": uuid.uuid4(), "utc_instant": None, "gps": None}]
    groups, ungrouped = group_captures(captures, max_time_gap_s=3600, max_distance_m=250)
    assert ungrouped == 1
    assert sum(len(g.capture_ids) for g in groups) == 1


def test_the_centroid_and_radius_are_integers_computed_the_same_way_every_run():
    captures = [_capture(10, 0, GULLFOSS), _capture(10, 1, (GULLFOSS[0] + 1000, GULLFOSS[1]))]
    groups, _ = group_captures(captures, max_time_gap_s=3600, max_distance_m=250)
    first = groups[0]
    assert first.centroid == (GULLFOSS[0] + 500, GULLFOSS[1])
    assert isinstance(first.radius_m, int)
    assert metres_between(GULLFOSS, GULLFOSS) == 0.0


@pytest.fixture
def grouped(tmp_path, photo_dir, repository):
    paths = [
        write_photo(photo_dir, "a.jpg", when="2026:08:27 10:00:00", gps=(64.3271, -20.1199)),
        write_photo(
            photo_dir, "b.jpg", when="2026:08:27 10:05:00", gps=(64.3271, -20.1199), size=(120, 90)
        ),
        write_photo(photo_dir, "c.jpg", when="2026:08:27 16:00:00", size=(100, 100)),
    ]
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    # One photograph at a time rather than ``ingest_directory``, because the place proposal these
    # tests are about is drawn from what vision inferred, and vision now needs a privacy screening
    # for the exact bytes. A screening is keyed to a capture, which does not exist until intake
    # has committed, so the directory walk has no place to put one.
    for path in paths:
        ingest_observed(pipeline, repository, path)
    return repository


def test_grouping_produces_derived_artifacts_that_record_what_they_came_from(grouped):
    report = run_scene_grouping(grouped)
    assert len(report.groups) == 2

    rows = grouped.connection.execute(
        "select kind, source_ids, dep_index, payload from derived_artifact order by kind"
    ).fetchall()
    kinds = [row["kind"] for row in rows]
    assert kinds.count("scene_group") == 2
    for row in rows:
        # source_ids is uuid[] and dep_index is text[], so both arrive as Python lists. The
        # emptiness check is the same one it always was; only the decoding is gone.
        assert row["source_ids"], "a derived object must record its sources"
        assert row["dep_index"]


def test_a_place_candidate_is_a_proposal_and_says_so(grouped):
    report = run_scene_grouping(grouped)
    assert report.proposals
    proposal = report.proposals[0]
    assert proposal["proposed_label"] == "Gullfoss"
    assert proposal["requires_user_confirmation"] is True
    assert proposal["epistemic_class"] == "inference"
    assert proposal["supporting_assertion_ids"]


def test_grouping_never_creates_an_entity(grouped):
    """Model confidence is never user confirmation, so promotion cannot happen here at all.

    This used to be checked by the absence of the table: the mirror carried only the fourteen
    tables ingestion needed and ``entity`` was not one of them, so the claim "this pipeline
    physically cannot create an entity" was true by omission. The real spine has ``entity`` and
    ``entity_link``, so the guarantee has to be stated as what it always meant. Grouping leaves
    canonical identity empty, it emits nothing but proposals, and the label it proposed cannot
    be written into ``entity.display_name`` even by SQL that goes around the repository:
    ``tg_entity_name_is_user_stated`` requires an active ``kind='user'`` assertion naming that
    entity, and an inference drawn from a photograph of a signpost is not one.
    """
    run_scene_grouping(grouped)
    assert grouped.rows_in_schema("entity") == 0
    assert grouped.rows_in_schema("entity_link") == 0
    kinds = {
        row["kind"]
        for row in grouped.connection.execute("select kind from derived_artifact").fetchall()
    }
    assert kinds <= {"scene_group", "place_proposal"}

    # Contained in its own transaction: the refusal aborts it, and the count below still runs.
    # Matched on the message, so a different 23xxx from some unrelated constraint cannot pass
    # this off as the naming guard having fired.
    refusal = pytest.raises(
        psycopg.errors.IntegrityConstraintViolation, match="no active user assertion says so"
    )
    with refusal, grouped.connection.transaction():
        grouped.connection.execute(
            "insert into entity (workspace_id, class, display_name) values (%s, 'place', %s)",
            (grouped.workspace_id, "Gullfoss"),
        )
    assert grouped.rows_in_schema("entity") == 0


def test_running_grouping_twice_writes_nothing_new(grouped):
    run_scene_grouping(grouped)
    before = grouped.rows_in_schema("derived_artifact")
    run_scene_grouping(grouped)
    assert grouped.rows_in_schema("derived_artifact") == before


def test_grouping_is_recorded_in_the_ledger_as_a_proposal_event(grouped):
    run_scene_grouping(grouped)
    types = [
        row["type"]
        for row in grouped.connection.execute(
            "select type from pipeline_event where stage_key = 'scene_group' or "
            "type = 'proposal_emitted'"
        ).fetchall()
    ]
    assert "proposal_emitted" in types
    assert "stage_succeeded" in types
