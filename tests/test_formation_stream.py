"""The formation stream: the ledger projected into the phases a person can see.

The property most of this file is about is that a RESUMED stream tells the same story as an
uninterrupted one. Server-sent events are redelivered on reconnect and a client resumes from its
last event id, so a counter computed against the present rather than against the point in history
being replayed would make a reconnect show numbers jumping for a reason nobody could explain.

The other half is that the two vocabularies stay in step. The ordered list of visible stages
exists in this repository twice, once in Python and once in TypeScript, and it has to, because
neither language can import the other's. So it is pinned by a test that reads both.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest
from exulanica.ingest.batch import IntakeBatch
from exulanica.ingest.formation import (
    FORMATION_OUTCOMES,
    FORMATION_STAGES,
    RECEIVED_TOKEN,
    project_formation,
)
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.scenes import run_scene_grouping
from exulanica.store.local import LocalContentAddressedStore

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, iso, write_photo

#: The client's copy of the ordered stage list. It lives in its own package because two
#: surfaces need it and neither may import the other: the signed-out page demonstrates formation
#: with a scripted source and the app watches a real one.
_EVENTS_TS = (
    Path(__file__).resolve().parents[1]
    / "web"
    / "packages"
    / "formation"
    / "src"
    / "events.ts"
)


def _ts_list(name: str) -> list[str]:
    """Read one ``as const`` string array out of the client's contract file."""
    assert _EVENTS_TS.is_file(), (
        f"{_EVENTS_TS} is gone. The ordered stage list exists in two languages and this test is "
        "the only thing keeping them in step. If the client's copy has moved, point this at its "
        "new home; do not delete the pin."
    )
    source = _EVENTS_TS.read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", source, re.S)
    assert match, f"{name} not found in {_EVENTS_TS}"
    return re.findall(r"'([a-z_]+)'", match.group(1))


# ---------------------------------------------------------------------------------------------
# The two vocabularies


def test_the_visible_stages_are_the_same_list_on_both_sides():
    """The client rejects an event whose phase sorts before the one it is showing.

    So the ORDER is load bearing and not only the membership: a server that emitted
    `continuity_search` at index 3 while the client had it at 5 would have every later event
    silently dropped as out of order, and the display would stop with no error anywhere.
    """
    assert list(FORMATION_STAGES) == _ts_list("FORMATION_STAGES")


def test_the_terminal_states_are_the_same_set_on_both_sides():
    assert sorted(FORMATION_OUTCOMES) == sorted(_ts_list("FORMATION_OUTCOMES"))


# ---------------------------------------------------------------------------------------------
# A real batch


@pytest.fixture
def ingested(repository, photo_dir, tmp_path):
    """One watched intake of three photographs, grouped, closed."""
    paths = [
        write_photo(photo_dir, f"{index}.jpg", when=iso(hour), gps=(64.3271, -20.1199))
        for index, hour in enumerate((10, 11, 12))
    ]
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(
        repository, store, vision=CountingVisionModel(payload=DEFAULT_PAYLOAD)
    )
    batch = IntakeBatch.open(repository, label="test")
    # One photograph at a time rather than ``ingest_directory``, because entity indexing IS the
    # vision stage and vision now needs a privacy screening for the exact bytes. A screening is
    # keyed to a capture, which does not exist until intake has committed, so the directory walk
    # has nowhere to put one.
    #
    # The declaration of size is the one thing ``ingest_directory`` owned that this stream reads,
    # and it is the denominator of every counter below. So it is written here in the same order
    # that method writes it: the batch exists before the walk, and the total is written once,
    # from what the walk found, rather than accumulated as it goes.
    batch.declare_size(len(paths))
    for path in paths:
        outcome = ingest_observed(pipeline, repository, path, batch_id=batch.batch_id)
        assert outcome.error is None, outcome.error
    run_scene_grouping(
        repository,
        ledger=Ledger.start_run(repository, trigger="ingest", batch_id=batch.batch_id),
    )
    batch.close("succeeded")
    return batch.batch_id


def _project(repository, batch_id, after=None):
    return project_formation(
        repository.connection, repository.workspace_id, batch_id, after=after
    )


# ---------------------------------------------------------------------------------------------
# What the stream contains


def test_the_stream_opens_with_what_arrived_and_how_many(repository, ingested):
    first = _project(repository, ingested)[0]
    assert first.phase == "received"
    assert first.event_id == RECEIVED_TOKEN
    assert first.photographs == 3


def test_a_stage_that_never_ran_never_appears(repository, ingested):
    """Camera recovery and reconstruction are visible stages that nothing produces.

    Emitting them as instantly complete is the exact dishonesty the formation design is written
    against: a stage reported as done that never ran. They are absent, and the client renders a
    jump from media extraction to entity indexing because that is what happened.
    """
    phases = {event.phase for event in _project(repository, ingested)}
    assert "camera_recovery" not in phases
    assert "reconstruction" not in phases
    assert {"media_extraction", "entity_indexing", "continuity_search"} <= phases


def test_media_extraction_counts_renditions_and_not_intakes(repository, ingested):
    """A photograph whose bytes were hashed but not decoded has not finished being extracted."""
    counts = [
        event.counters["done"]
        for event in _project(repository, ingested)
        if event.phase == "media_extraction" and event.counters
    ]
    # Three photographs, so the count runs 1, 2, 3 and stops. Six would mean intake was counted
    # as well, which would report the stage half done when it was a quarter done.
    assert counts == [1, 2, 3]


def test_a_stage_that_cannot_count_itself_reports_no_counters(repository, ingested):
    """Continuity search is one run for the whole batch, so "1 of 1" would say nothing.

    The client already has a first-class state for a stage with no counters: a breathing visual
    and an elapsed time. Reporting a fraction that is always one whole would be inventing a
    measurement to fill a field.
    """
    for event in _project(repository, ingested):
        if event.phase == "continuity_search":
            assert event.counters is None


def test_the_total_is_what_the_walk_counted_once_it_has_counted(repository, ingested):
    """Three photographs were found, so three is the denominator. Not a guess: a count."""
    for event in _project(repository, ingested):
        if event.counters is not None:
            assert event.counters["total"] == 3


def test_a_batch_that_has_not_been_counted_yet_reports_no_total(repository, photo_dir, tmp_path):
    """The load-bearing case, and the reason both the column and the field are nullable.

    Walking a directory takes time proportional to the corpus, and a client can subscribe during
    the walk. Until the walk finishes there is no total, and a client shown one would be shown a
    denominator nobody had measured. `total: null` is the honest answer and the client renders it
    as a count with no fraction rather than falling back to a guess.
    """
    write_photo(photo_dir, "a.jpg", when=iso(10))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=None)

    # Opened, joined by a run, and never declared: the state a subscriber sees mid-walk.
    batch = IntakeBatch.open(repository, label="counting")
    pipeline.ingest_file(photo_dir / "a.jpg", batch_id=batch.batch_id)

    events = _project(repository, batch.batch_id)
    assert events[0].photographs is None
    for event in events:
        if event.counters is not None:
            assert event.counters["total"] is None


def test_the_terminal_event_says_what_was_left_behind(repository, ingested):
    last = _project(repository, ingested)[-1]
    assert last.phase in FORMATION_OUTCOMES
    assert last.outcome is not None
    assert last.outcome["photographsAvailable"] == 3
    # The rung the regions actually earned. Nothing reconstructs, so nothing earned better than 4.
    assert last.outcome["rung"] == 4
    assert last.outcome["openQuestions"] == 0


def test_detections_are_counted_from_occurrences_that_landed(repository, ingested):
    """One mote per detection that has actually landed, so this counts rows and not intentions."""
    events = _project(repository, ingested)
    detections = events[-1].detections
    assert detections is not None
    assert detections["objects"] >= 3
    assert set(detections) == {"people", "objects", "places"}


# ---------------------------------------------------------------------------------------------
# Resuming


def test_a_resumed_stream_tells_the_same_story_as_an_uninterrupted_one(repository, ingested):
    """The property the fold exists for.

    A counter recomputed against the present would make the second half of a resumed stream carry
    the totals as they are NOW rather than as they were at that point, and a client reconnecting
    mid-ingest would watch its numbers jump. Splitting the stream at every point and comparing is
    the only check that would notice.
    """
    whole = _project(repository, ingested)
    assert len(whole) > 4, whole

    for cut in range(len(whole) - 1):
        head = whole[: cut + 1]
        tail = _project(repository, ingested, after=whole[cut].event_id)
        rejoined = [event.as_payload() for event in head + tail]
        assert rejoined == [event.as_payload() for event in whole], f"diverged after {cut}"


def test_resuming_from_the_opening_event_replays_everything_the_ledger_recorded(
    repository, ingested
):
    whole = _project(repository, ingested)
    resumed = _project(repository, ingested, after=RECEIVED_TOKEN)
    assert [event.as_payload() for event in resumed] == [
        event.as_payload() for event in whole[1:]
    ]


# ---------------------------------------------------------------------------------------------
# Outcomes that are not success


def test_a_batch_with_a_failed_run_ends_partial_and_says_where_it_stopped(
    repository, photo_dir, tmp_path
):
    """Failure leaves the partial region in place, and partial usability is the point.

    So a batch that lost one photograph reports `partial` with the stage it stopped at, not
    `failed`, and still reports how many photographs the user can open.
    """
    write_photo(photo_dir, "good.jpg", when=iso(10))
    (photo_dir / "bad.jpg").write_bytes(b"not an image at all")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=None)
    batch = IntakeBatch.open(repository, label="test")
    report = pipeline.ingest_directory(photo_dir, batch=batch)
    assert len(report.failed) == 1
    batch.close(
        IntakeBatch.outcome_for(
            succeeded=len(report.outcomes) - len(report.failed), failed=len(report.failed)
        )
    )

    last = _project(repository, batch.batch_id)[-1]
    assert last.phase == "partial"
    assert last.outcome is not None
    assert last.outcome["photographsAvailable"] == 1


def test_an_unwatched_ingest_produces_no_stream(repository, photo_dir, tmp_path):
    """A single file is not an upload. Inventing a batch of one would put it where one goes."""
    write_photo(photo_dir, "one.jpg", when=iso(10))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=None)
    outcome = pipeline.ingest_file(photo_dir / "one.jpg")
    assert outcome.error is None
    row = repository.connection.execute(
        "select batch_id from pipeline_run where run_id = %s", (outcome.run_id,)
    ).fetchone()
    assert row["batch_id"] is None


def test_a_batch_in_another_workspace_is_not_visible(repository, ingested):
    """Not an exception and not a different code: the same empty answer a missing batch gets."""
    assert _project(repository, uuid.uuid4()) == []
    stranger = uuid.uuid4()
    assert project_formation(repository.connection, stranger, ingested) == []


# ---------------------------------------------------------------------------------------------
# The wire


def test_every_event_carries_the_fields_the_client_reducer_reads(repository, ingested):
    for event in _project(repository, ingested):
        payload = json.loads(json.dumps(event.as_payload()))
        assert set(payload) >= {"eventId", "captureId", "phase", "stageIndex", "at"}
        assert isinstance(payload["at"], int)
        assert payload["phase"] in (*FORMATION_STAGES, *FORMATION_OUTCOMES)
        # An absent field is absent rather than null: the client reads `event.counters ?? state`
        # and a null costs bytes on every event of a long stream to mean exactly what absent means.
        assert None not in payload.values()


def test_the_terminal_event_is_genuinely_the_last_one(repository, ingested):
    """A client stops listening when it sees an outcome, so nothing may follow one.

    This caught a real defect. The batch used to be closed by ``ingest_directory``, which finishes
    before continuity search runs, so the terminal event carried an earlier timestamp than the
    stage event after it. A client that stopped on the outcome, which is exactly what a client
    should do, never saw continuity search at all, and one that kept reading watched its elapsed
    time go backwards.
    """
    events = _project(repository, ingested)
    outcomes = [i for i, event in enumerate(events) if event.phase in FORMATION_OUTCOMES]
    assert outcomes == [len(events) - 1], "an outcome is not the final event"
    assert events[-1].at >= events[-2].at, "the outcome is stamped before the event before it"


def test_no_event_ever_goes_backwards_in_time(repository, ingested):
    """The client drops an event older than the one it is showing, so an out-of-order stream is
    a silently truncated one rather than a visibly wrong one."""
    stamps = [event.at for event in _project(repository, ingested)]
    assert stamps == sorted(stamps), stamps


def test_a_second_ingest_reports_the_photographs_as_extracted_rather_than_as_missing(
    repository, photo_dir, tmp_path
):
    """The counter answers how many photographs are ready, not how much work was done.

    A reused stage did not run, and until migration 0004 it wrote no ledger event at all, so a
    re-ingest of six photographs streamed "3 of 6" over a corpus that was entirely ready. Three
    of them had simply been extracted already. The count is of photographs that have finished the
    stage, and a photograph whose rendition already exists has finished it.
    """
    for index in range(3):
        write_photo(photo_dir, f"{index}.jpg", when=iso(10 + index))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=None)

    first = IntakeBatch.open(repository, label="first")
    pipeline.ingest_directory(photo_dir, batch=first)
    first.close("succeeded")

    second = IntakeBatch.open(repository, label="second")
    report = pipeline.ingest_directory(photo_dir, batch=second)
    second.close("succeeded")
    # Nothing was recomputed, which is the idempotency guarantee holding.
    assert len(report.unchanged) == 3, report.outcomes

    counts = [
        event.counters["done"]
        for event in _project(repository, second.batch_id)
        if event.phase == "media_extraction" and event.counters
    ]
    assert counts == [1, 2, 3], counts


def test_a_reused_stage_appears_in_the_assembly_replay(repository, photo_dir, tmp_path):
    """The ledger's own rule: the replay is rebuilt from it and from nothing else.

    A rendition satisfied by an existing artifact is a step in the DAG. Before 0004 the replay of
    a second ingest had no rendition step in it at all, which is the failure the ledger's
    docstring predicts: a DAG that is only implicit in the source lies most convincingly about
    old runs.
    """
    write_photo(photo_dir, "a.jpg", when=iso(10))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=None)
    pipeline.ingest_file(photo_dir / "a.jpg")
    again = pipeline.ingest_file(photo_dir / "a.jpg")

    replayed = Ledger(repository, again.run_id).replay()
    reused = [event for event in replayed if event["type"] == "stage_reused"]
    assert [event["stage_key"] for event in reused] == ["rendition"], replayed
    assert reused[0]["output_artifact_ids"], "a reuse that names no artifact explains nothing"
