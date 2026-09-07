"""The evaluation harness, and the rules it is supposed to enforce on itself.

A harness that overclaims is worse than no harness, because a number carries authority a
paragraph does not. So most of what is tested here is refusal: refusing an interval over nothing,
refusing a failure with no evidence, refusing a measurement from one run of a stochastic system,
and refusing to print a word section 3.1 rule 9 bans.
"""

from __future__ import annotations

import io
import pathlib

import pytest
from exulanica.evaluation import (
    METRICS,
    Count,
    GroundTruth,
    NamedCase,
    Sample,
    banned_words_in,
    render,
    render_report,
    wilson,
)
from exulanica.evaluation.report import quoted_from_the_methodology

_ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = _ROOT / ".exulanica" / "media" / "intake" / "synthetic"


# -- the rules that are refusals ------------------------------------------------------------


def test_a_failure_with_no_evidence_is_refused():
    """Rule 4. A failure reported without the case that produced it is a number nobody can check.

    The only thing anybody can do with such a number is believe it, which is the opposite of
    what this harness is for.
    """
    NamedCase("a passing case", True)
    NamedCase("a failing case", False, "here is what went wrong")
    with pytest.raises(ValueError, match="carries no evidence"):
        NamedCase("a failing case", False)


def test_one_run_of_a_stochastic_component_is_refused():
    """Rule 2. "A single run of a stochastic system is not a measurement."

    The refusal is in the type rather than in the caller, because the caller is where "just this
    once" gets written.
    """
    runs = (Count(1, 1), Count(1, 1), Count(0, 1))
    Sample(runs)
    with pytest.raises(ValueError, match="at least three"):
        Sample(runs[:2])


def test_an_interval_over_nothing_is_refused():
    """A zero must say which zero it is.

    ``[0, 1]`` renders "nothing was scored" and "everything failed" identically, which is exactly
    the conflation this project refuses everywhere else.
    """
    with pytest.raises(ValueError, match="not an interval"):
        wilson(0, 0)


def test_the_interval_reproduces_the_methodology_worked_example():
    """52 of 52 -> [93.1%, 100%], the one example in the document that reproduces at all.

    The other two worked intervals it prints match no standard interval this was checked
    against. They are recorded as open items against the document and this code is not bent to
    hit them.
    """
    low, high = wilson(52, 52)
    assert round(low * 100, 1) == 93.1
    assert round(high * 100, 1) == 100.0


# -- rendering ------------------------------------------------------------------------------


def test_a_synthetic_corpus_never_gets_an_interval():
    """An interval describes a sample drawn from a population, and a render is not one.

    It describes how faithfully a generator does what it was written to do, which is not a fact
    about photographs and must not be printed as one.
    """
    text = render(Count(40, 40), synthetic=True, corpus_tag="SYNTH-1")
    assert "no interval" in text
    assert "CI" not in text


def test_a_small_sample_prints_its_cases_instead_of_a_percentage():
    """Rule 3, and the renderer does it rather than every caller remembering to."""
    count = Count(1, 2, (NamedCase("first", True), NamedCase("second", False, "because")))
    text = render(count, synthetic=False, corpus_tag="OGC-1")
    assert "%" not in text
    assert "second: FAIL  because" in text


def test_every_number_carries_the_corpus_it_was_measured_on():
    """Rule 2 of 3.1: the corpus name travels with every number, into every surface."""
    assert "OGC-1" in render(Count(9, 10), synthetic=False, corpus_tag="OGC-1")
    assert "SYNTH-1" in render(Count(9, 10), synthetic=True, corpus_tag="SYNTH-1")


# -- the metric table -------------------------------------------------------------------------


def test_every_metric_the_methodology_defines_has_at_least_one_component():
    """A report missing a metric reads as a clean one. Fifteen appear or the table is wrong.

    Fifteen rather than fourteen since M15 was added: M6 stopped being a corpus metric, and the
    corpus metric that replaced it over the capture-time dimension is a metric of its own rather
    than a second component of M6, because it measures neither ANY, ALL nor TOGETHER.
    """
    covered = {component.metric for component in METRICS}
    assert covered == {f"M{number}" for number in range(1, 16)}, sorted(covered)


def test_a_component_that_cannot_run_says_what_stopped_it():
    """Blocked and scored-zero are different facts, and the table has to hold the difference."""
    for component in METRICS:
        if component.blocked_on is not None:
            assert len(component.blocked_on) > 30, component.key


def test_an_enforced_component_carries_the_bar_it_is_measured_against():
    for component in METRICS:
        if component.kind == "enforced":
            assert component.bar, component.key
            assert component.licenses, component.key
            assert component.withholds, component.key


def test_the_report_says_what_a_result_does_not_license():
    """Section 6's third column is the one that stops a report being read as more than it is.

    M10's is the clearest: the sweep licenses that no cross-tenant read succeeded on a route
    generated from the router, and explicitly not that anonymous asset URLs are protected.
    """
    report = _report({})
    assert "does NOT license" in report
    assert "asset URLs are protected. They are not" in report


def test_a_row_that_did_not_run_licenses_nothing():
    """The licence column is a claim, and a row that did not run must not print one flatly.

    M9's gate precision is what this is for. It once ran a scorer counting `external`-class
    assertions, which nothing in the tree writes, printed "1 of 1", and carried section 6's cell
    beside it: "No external lookup occurred for any private entity, any historical question, or
    with opt-in off, across the tested negatives". Not one negative had been probed. The scorer
    is gone and the row now says what stopped it, but the cell is still printed, so the tense is
    the last thing standing between a blocked row and a licence it did not earn.

    The withheld column is untouched, because "this does not license X" stays true of a row that
    produced no result at all.
    """
    from exulanica.evaluation.cli import SCORED

    report = _report(dict.fromkeys(SCORED, Count(1, 1, (NamedCase("a case", True),))))
    unmeasured = [
        c for c in METRICS if f"{c.metric}.{c.key}" not in set(SCORED) and c.licenses
    ]
    assert len(unmeasured) > 5, "almost nothing was unmeasured, so nothing was exercised"
    for component in unmeasured:
        assert f"licenses, quoted from section 6: {component.licenses}" not in report, (
            f"{component.metric}.{component.key} did not run and licensed anyway"
        )
        assert (
            "licenses NOTHING, because it did not run. What a result would have licensed, "
            f"quoted from section 6: {component.licenses}"
        ) in report, f"{component.metric}.{component.key}"
        assert f"does NOT license, quoted from section 6: {component.withholds}" in report

    measured = [c for c in METRICS if f"{c.metric}.{c.key}" in set(SCORED) and c.licenses]
    assert measured, "no measured row carries a licence, so the other half proves nothing"
    for component in measured:
        assert f"licenses, quoted from section 6: {component.licenses}" in report


# -- the banned vocabulary --------------------------------------------------------------------


def _report(results: dict) -> str:
    return render_report(
        results,
        corpus_tag="SYNTH-1",
        corpus_version="exulanica-corpus 1",
        manifest_sha256="0" * 64,
        synthetic=True,
        disclosure="a synthetic frame",
        frames=80,
        git_commit="abc1234",
    )


def test_the_scan_catches_a_banned_word():
    assert banned_words_in("this system is reliable") == ["reliable"]
    assert banned_words_in("measured on OGC-1") == []
    # Whole words only: a substring inside another word is not the claim rule 9 forbids.
    assert banned_words_in("reliability engineering") == []


def test_the_report_refuses_to_print_a_banned_word():
    """The check runs unconditionally, over the report, every time it is rendered.

    An earlier design scanned the whole documentation set, found 85 hits it could not adjudicate,
    and put the scan behind a flag. A check nobody turns on is not a check.
    """
    with pytest.raises(ValueError, match="rule 9"):
        render_report(
            {},
            corpus_tag="SYNTH-1",
            corpus_version="v",
            manifest_sha256="0" * 64,
            synthetic=True,
            disclosure="this corpus is fully deleted",
            frames=1,
            git_commit="abc",
        )


def test_the_exemption_is_exactly_the_quoted_cells_and_nothing_else():
    """The scan steps over section 6's verbatim text, and the exemption has to be enumerable.

    Rule 9 bans those words as CAPABILITY CLAIMS, and the "does not license" column is the
    anti-claim column: scanning it would forbid the report from saying something is NOT
    guaranteed. So the quotations are exempt, and this asserts the exemption is those cells and
    not a hole somebody could widen.
    """
    quoted = set(quoted_from_the_methodology())
    from_table = {
        text
        for component in METRICS
        for text in (component.licenses, component.withholds, component.bar)
        if text
    }
    assert quoted == from_table


def test_a_banned_word_outside_a_quotation_is_still_caught():
    """The exemption must not become a way to smuggle a claim in beside a quotation."""
    with pytest.raises(ValueError, match="rule 9"):
        render_report(
            {},
            corpus_tag="SYNTH-1",
            corpus_version="v",
            manifest_sha256="0" * 64,
            synthetic=True,
            disclosure="the store is immutable",
            frames=1,
            git_commit="abc",
        )


# -- the ground truth join ---------------------------------------------------------------------


@pytest.mark.skipif(not CORPUS.exists(), reason="the synthetic corpus has not been generated")
def test_the_manifest_is_keyed_by_the_hash_ingest_computes():
    """Which is the whole reason an evaluation can join to a stored capture by evidence address.

    A filename is a thing a user renames. The content hash is what the system keys on, so a join
    on it measures the system rather than a naming convention.
    """
    truth = GroundTruth.read(CORPUS)
    assert len(truth.frames) == len(truth.by_hash), "two frames share a hash"
    for frame in truth.frames:
        assert len(frame.sha256) == 64


@pytest.mark.skipif(not CORPUS.exists(), reason="the synthetic corpus has not been generated")
def test_the_manifest_records_which_frames_can_be_placed_on_a_timeline():
    """So the unknown-offset case is scored without crediting the pipeline for guessing.

    One device in the corpus writes ``OffsetTimeOriginal`` and one does not. A frame from the
    second has a wall clock reading in the file and no way to place it, and a pipeline that
    produced an instant for it would be inventing one.
    """
    from exulanica.evaluation.ground_truth import instant_is_correct

    truth = GroundTruth.read(CORPUS)
    recoverable = [f for f in truth.frames if f.instant_is_recoverable_from_the_file]
    unrecoverable = [f for f in truth.frames if not f.instant_is_recoverable_from_the_file]
    assert recoverable and unrecoverable, "the corpus no longer covers both cases"

    passed, _ = instant_is_correct(unrecoverable[0], None)
    assert passed, "storing no instant for an unplaceable frame is the correct behaviour"
    guessed, why = instant_is_correct(unrecoverable[0], "2026-04-18T09:14:21+00:00")
    assert not guessed and "guessed rather than read" in why


def test_a_correct_instant_compares_equal_however_either_side_spells_it():
    """The comparison is between instants, not between two renderings of them.

    psycopg renders a ``timestamptz`` with a SPACE between the date and the time and the manifest
    writes the same instant with a ``T``, so a prefix comparison of the two strings never matches
    and every placeable frame in the corpus scored as a failure. Measured against the live corpus
    on 2026-08-29: 0 pass and 80 fail before this, 48 pass and 32 fail after, and the 32 are the
    unplaceable frames the pipeline guessed an instant for, which is the failure this is for.

    The offset is asserted too, because "same instant" is the claim and an instant written at a
    different offset is the same instant. A value carrying no offset is not one and is refused.
    """
    from exulanica.evaluation.ground_truth import Frame, instant_is_correct

    frame = Frame(
        filename="courtyard-spring-000.jpg",
        sha256="0" * 64,
        trip="courtyard-spring",
        place="courtyard",
        device_model="Synthetic Camera A",
        display_size=(1600, 1200),
        utc_instant="2026-04-18T09:14:21+00:00",
        instant_is_recoverable_from_the_file=True,
        gps_e7=None,
        subjects=(),
    )

    for rendering in (
        "2026-04-18 09:14:21+00:00",
        "2026-04-18T09:14:21+00:00",
        "2026-04-18T11:14:21+02:00",
        "2026-04-18 09:14:21.000000+00:00",
    ):
        passed, why = instant_is_correct(frame, rendering)
        assert passed, f"{rendering}: {why}"

    off_by_an_hour, why = instant_is_correct(frame, "2026-04-18 10:14:21+00:00")
    assert not off_by_an_hour, why
    no_offset, why = instant_is_correct(frame, "2026-04-18 09:14:21")
    assert not no_offset and "names no instant" in why

# -- M6: the two vocabularies, and what is still in the way ----------------------------------


def test_a_detector_label_resolves_to_the_subject_the_corpus_placed():
    """The join the manifest now makes possible, and the rule it makes it by.

    Containment rather than equality, because a model that says "a small red cube on the
    platform" is describing the corpus's satchel correctly, and refusing to join that would be
    scoring the model down for being right about pixels.
    """
    from exulanica.corpus.world import SUBJECT_LABELS
    from exulanica.evaluation.coverage import subject_of

    assert subject_of("a small red cube", SUBJECT_LABELS) == "satchel"
    assert subject_of("the teal cylinder on the shelf", SUBJECT_LABELS) == "thermos"
    assert subject_of("amber prism", SUBJECT_LABELS) == "lantern"
    assert subject_of("BAG", SUBJECT_LABELS) == "satchel", "the rule is case-insensitive"


def test_a_label_that_could_mean_two_subjects_means_neither():
    """Ambiguity must resolve to nothing, or the mapping manufactures matches.

    "cube" appears in the appearance words of more than one subject. Letting it count for
    whichever is iterated first would make a gold comparison depend on dictionary order, which is
    a number that changes for a reason nobody could explain.
    """
    from exulanica.corpus.world import SUBJECT_LABELS
    from exulanica.evaluation.coverage import subject_of

    assert subject_of("cube", SUBJECT_LABELS) is None
    assert subject_of("red cube beside a gold cube", SUBJECT_LABELS) is None
    assert subject_of("octagonal platform", SUBJECT_LABELS) is None


def test_the_generated_manifest_carries_the_mapping_the_harness_reads():
    """A pin across the boundary between the corpus generator and the harness that reads it."""
    import json
    import tempfile
    from pathlib import Path

    from exulanica.corpus.__main__ import main as corpus_main
    from exulanica.corpus.world import SUBJECT_LABELS
    from exulanica.evaluation.ground_truth import GroundTruth

    with tempfile.TemporaryDirectory() as directory:
        corpus_main(["--out", directory, "--frames-per-trip", "3"], stream=io.StringIO())
        document = json.loads((Path(directory) / "MANIFEST.json").read_text())
        assert document["subject_labels"] == {
            key: list(labels) for key, labels in SUBJECT_LABELS.items()
        }
        truth = GroundTruth.read(directory)
        assert truth.subject_labels == SUBJECT_LABELS


def test_a_manifest_written_before_the_mapping_existed_still_reads():
    """Absent is a real state and it is not an error.

    The report then says this corpus cannot describe what a detector recovered, instead of
    printing a zero that reads as "it recovered nothing".
    """
    import json
    import tempfile
    from pathlib import Path

    from exulanica.evaluation.ground_truth import GroundTruth

    with tempfile.TemporaryDirectory() as directory:
        (Path(directory) / "MANIFEST.json").write_text(
            json.dumps(
                {
                    "generator": "g",
                    "synthetic": True,
                    "disclosure": "d",
                    "trips": [],
                    "places": {},
                    "subjects": {"satchel": "a bag"},
                    "frames": [],
                }
            )
        )
        assert GroundTruth.read(directory).subject_labels == {}


# -- the quoted cells and the blocked sentences ------------------------------------------------


def test_a_row_that_carries_no_sentence_is_a_row_something_scores():
    """"Blocked" and "scored zero" are different facts, and so are "blocked" and "not run".

    ``metrics.py`` says ``blocked_on=None`` means the component is runnable. Nothing enforced
    that, and a row that claimed it while no scorer could produce a result rendered as the
    literal line "NOT MEASURED: None": a reader is told the metric was not measured and given
    ``None`` as the reason, which is the collapse this whole harness exists to refuse.

    So the table and the harness must agree, and then the report is clean: given a result for
    every component the harness scores, no unmeasured line falls back to an empty reason.
    """
    from exulanica.evaluation.cli import SCORED

    runnable = {f"{c.metric}.{c.key}" for c in METRICS if c.blocked_on is None}
    assert runnable == set(SCORED), sorted(runnable ^ set(SCORED))

    report = _report(dict.fromkeys(SCORED, Count(1, 1, (NamedCase("a case", True),))))
    assert "NOT MEASURED: None" not in report
    # The rest of the table is unmeasured in that call, so the fallback really was exercised.
    assert "NOT MEASURED" in report


def test_the_scoring_package_contains_no_direct_product_write_sql():
    """The package holds no direct INSERT, UPDATE or DELETE that could bypass the pipeline.

    It is the load-bearing rule of the scoring path. A Selection filters on confirmed entity
    ids, an entity exists only where a person confirmed an occurrence, and the tempting way to
    make such a metric computable is for the harness to confirm one out of ``MANIFEST.json``. That
    is a machine performing a user-class act, invariant 3 forbids it, and no flag or dedicated
    workspace changes what is being written. ``replay-bundle`` invokes the normal pipeline only
    after checking a new empty database; it does not carry SQL around this boundary. So every SQL
    string this package owns is scanned, and a direct write in any of them fails here.
    """
    import ast
    import re

    package = pathlib.Path(__file__).resolve().parents[1] / "exulanica" / "evaluation"
    writes = re.compile(r"\b(insert\s+into|delete\s+from|update\s+\w+\s+set|truncate)\b")
    modules = sorted(package.glob("*.py"))
    assert len(modules) > 5, "the scan found almost nothing, so it is scanning the wrong place"
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found = writes.search(node.value.lower())
                assert not found, f"{module.name}: {found.group(0)!r} in {node.value[:80]!r}"


def test_every_quoted_cell_is_in_section_6_verbatim():
    """The report says "quoted from section 6", and that sentence has to be true.

    ``metrics.py`` claims its ``licenses`` and ``withholds`` are copied verbatim, and the report
    reproduces them under a label that attributes them to the document. A cell that has drifted
    from section 6, or one invented in the code and attributed to the document, is a quotation of
    something nobody wrote. The bar is excluded because section 6 renders it as a table cell that
    is sometimes reformatted, and the two license columns are the ones the report attributes.
    """
    document = (
        pathlib.Path(__file__).resolve().parents[1] / "docs" / "evaluation-methodology.md"
    ).read_text(encoding="utf-8")
    section6 = document[document.index("## 6. Acceptance targets") :]
    for component in METRICS:
        for column in (component.licenses, component.withholds):
            if column:
                assert column in section6, f"{component.metric}.{component.key}: {column}"


# -- M15, the capture-time window metric -------------------------------------------------------


@pytest.fixture
def timed_corpus(tmp_path, photo_dir, repository):
    """Two trips of four photographs each, ingested, with a manifest that matches them.

    The manifest is built from the bytes that were actually written, so ``sha256`` is the real
    content address and ``utc_instant`` is what the generator put in the file rather than what
    the pipeline concluded. That is what makes it ground truth: it existed before the pipeline
    ran and does not depend on anything the pipeline decided.
    """
    import datetime as dt
    import hashlib

    from exulanica.evaluation.ground_truth import Frame, GroundTruth
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    from conftest import CountingVisionModel, ingest_observed, write_photo

    store = LocalContentAddressedStore(tmp_path / "blobs")
    plates = [
        ("morning", 10, 0), ("morning", 10, 1), ("morning", 10, 2), ("morning", 10, 3),
        ("evening", 20, 0), ("evening", 20, 1), ("evening", 20, 2), ("evening", 20, 3),
    ]
    frames = []
    for index, (trip, hour, minute) in enumerate(plates):
        name = f"{trip}-{index}.jpg"
        path = write_photo(
            photo_dir, name, when=f"2026:03:04 {hour:02d}:{minute:02d}:00", offset="+00:00"
        )
        pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
        outcome = ingest_observed(pipeline, repository, path)
        assert outcome.error is None, outcome.error
        frames.append(
            Frame(
                filename=name,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                trip=trip,
                place="a room",
                device_model="Synthetic Camera A",
                display_size=(64, 64),
                utc_instant=dt.datetime(
                    2026, 3, 4, hour, minute, tzinfo=dt.UTC
                ).isoformat(),
                instant_is_recoverable_from_the_file=True,
                gps_e7=None,
                # Three of the eight, so the coverage disclosure has both a recovery number and
                # a not-placed number to get wrong. The fake vision model labels every frame
                # "red block", so a mapping from that label to `satchel` recovers all three and
                # resolves the subject in five frames the generator never placed it in.
                subjects=("satchel",) if index < 3 else (),
            )
        )
    return repository, GroundTruth(
        path=tmp_path / "MANIFEST.json",
        manifest_sha256="0" * 64,
        generator="a test",
        synthetic=True,
        disclosure="eight synthetic frames",
        frames=tuple(frames),
        trips=("morning", "evening"),
        places=("a room",),
        subjects=("satchel",),
        subject_labels={"satchel": ("red block",)},
    )


def _score_windows(timed_corpus, truth=None):
    from exulanica.evaluation.scorers import score_capture_time_windows

    repository, built = timed_corpus
    return score_capture_time_windows(
        repository.connection, repository.workspace_id, truth or built
    )


def test_a_capture_time_window_returns_the_frames_the_corpus_placed_in_it(timed_corpus):
    """M15 through the real path: parse, then validate, then execute.

    Nine windows, every one of them scored, because the workspace holds this corpus and nothing
    else. The half-open case is the one that matters most: a window ending exactly on a frame's
    instant must exclude that frame, and an off-by-one there is invisible in every other case.
    """
    count, why = _score_windows(timed_corpus)
    assert count is not None, why
    assert count.n == 9, [case.name for case in count.cases]
    failures = [case for case in count.cases if not case.passed]
    assert failures == [], [(case.name, case.evidence) for case in failures]
    assert count.k == count.n
    names = " ".join(case.name for case in count.cases)
    assert "a half-open end excludes the frame sitting on it" in names
    assert "two windows are ORed with each other" in names


def test_the_capture_time_metric_falls_when_the_gold_set_disagrees(timed_corpus):
    """It must be able to return a number below its bar, or it is not a measurement.

    The defect this metric replaces scored M6 by comparing a manifest against a set comprehension
    over rows the scorer had just read, so nothing it could have been pointed at would have made
    it fail. This moves one frame's ground-truth instant into the other trip and asserts the score
    drops, that the drop is not total, and that the failing case names the frame with both
    instants so a reader can tell a filter defect from a stored instant that disagrees.
    """
    import dataclasses

    _repository, built = timed_corpus
    moved = dataclasses.replace(built.frames[0], utc_instant="2026-03-04T20:02:00+00:00")
    perturbed = dataclasses.replace(built, frames=(moved, *built.frames[1:]))

    clean, _ = _score_windows(timed_corpus)
    count, why = _score_windows(timed_corpus, perturbed)
    assert count is not None, why
    assert clean is not None and clean.k == clean.n
    assert count.k < count.n, "a gold set that disagrees with the data must not score full marks"
    failed = [case for case in count.cases if not case.passed]
    assert failed, "the score dropped but no case was named, which rule 4 forbids"
    assert any(moved.filename in case.evidence for case in failed)
    assert any("manifest 2026-03-04T20:02:00+00:00" in case.evidence for case in failed)
    assert any("stored 2026-03-04T10:00:00" in case.evidence for case in failed)


def test_a_frame_the_manifest_cannot_place_is_left_out_of_the_gold_set(tmp_path, timed_corpus):
    """A frame with no recoverable offset is not ground truth about any window.

    One device in the real corpus writes ``OffsetTimeOriginal`` and one does not, and for the
    second the pipeline has to guess an offset. Measured on the live corpus: it guesses, and for
    32 of 80 frames the instant it stored differs from the generator's by an hour. Including such
    a frame in a gold set would score that guess under a name that says filters, so it is
    excluded, and this asserts the exclusion rather than trusting the comment above it.
    """
    import dataclasses

    _repository, built = timed_corpus
    # The SECOND frame of the trip, not the first. Windows are derived from the placeable frames,
    # so an unplaceable frame at the edge of a trip simply falls outside every window and proves
    # nothing. One in the middle is still caught by its trip's window, which is the case the
    # guard exists for.
    unplaceable = dataclasses.replace(
        built.frames[1], instant_is_recoverable_from_the_file=False
    )
    truth = dataclasses.replace(
        built, frames=(built.frames[0], unplaceable, *built.frames[2:])
    )
    count, why = _score_windows(timed_corpus, truth)
    assert count is not None, why
    # The frame is still ingested and its trip's window still returns it. It is in no gold set,
    # so scoring that window would count a returned frame as an extra and fail it. Instead the
    # window is not scored, and the report says how many were dropped and why.
    reported = " ".join(case.name for case in count.cases)
    assert "cannot place" in reported
    assert count.k == count.n, "an unadjudicable frame must not be scored as a failure"
    assert count.n < 9, "the windows holding it must have been dropped rather than scored"


def test_the_corpus_coverage_is_measured_against_the_workspace_not_asserted(timed_corpus):
    """The report's coverage claims are recomputed, not remembered.

    This is the measurement that decided M6 was not worth scoring against a corpus, so it has to
    be a measurement rather than a sentence somebody wrote down once: run it again and it says
    what is true now. The numbers asserted here are ones a constant could not produce. The
    generator placed ``satchel`` in three of these eight frames and the vision stage labels all
    eight "red block", so the mapping recovers all three AND resolves the subject in five frames
    it was never placed in, and the disclosure has to report both halves. Reporting only the
    first would read as a detector that is right about everything it finds.
    """
    from exulanica.evaluation.coverage import what_the_corpus_cannot_support

    repository, built = timed_corpus
    lines = what_the_corpus_cannot_support(
        repository.connection, repository.workspace_id, built
    )
    text = "\n".join(lines)
    assert "CONFIRMED ENTITIES IN THIS WORKSPACE: 0" in text
    assert "satchel: placed in 3, recovered in 3, resolved in 5" in text, text


def test_a_bounded_page_is_reported_rather_than_scored(tmp_path, photo_dir, timed_corpus):
    """A page is not a set, and comparing one against a gold set reports the limit as a defect.

    This is the live corpus workspace's situation rather than a hypothetical: it holds 327
    captures of which 80 are this corpus, and their capture times overlap, so a window drawn over
    the corpus matches far more than one page returns. Scoring such a window would report every
    corpus frame the limit pushed off the page as a frame the filter failed to return.

    Twenty-two more captures are ingested inside the morning trip's window and none of them is in
    the manifest, so two different things must happen at once: the trip's whole-window case must
    drop out of the score, and the captures the manifest says nothing about must be reported
    rather than counted for or against anything.
    """
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    from conftest import CountingVisionModel, write_photo

    repository, _built = timed_corpus
    store = LocalContentAddressedStore(tmp_path / "more-blobs")
    for index in range(22):
        path = write_photo(
            photo_dir,
            f"stray-{index}.jpg",
            when=f"2026:03:04 10:00:{index + 10:02d}",
            offset="+00:00",
        )
        outcome = PhotoIngestPipeline(
            repository, store, vision=CountingVisionModel()
        ).ingest_file(path)
        assert outcome.error is None, outcome.error

    count, why = _score_windows(timed_corpus)
    assert count is not None, why
    reported = " ".join(case.name for case in count.cases)
    assert "the result is a page and not a set" in reported
    assert "outside this corpus" in reported
    assert count.n < 9, "the bounded window must be dropped rather than scored"
    assert count.k == count.n, "and dropping it must not turn it into a failure"


def test_captures_outside_the_corpus_are_counted_once_each_not_once_per_window(
    tmp_path, photo_dir, timed_corpus
):
    """The sentence says captures, so the number has to be a count of captures.

    The windows overlap by construction: a trip's whole span, its opening half and its closing
    half all cover the same captures, and two of the three shape cases are drawn over the opening
    of the first trip. Adding up each window's out-of-corpus count therefore reports (window,
    capture) PAIRS under a sentence that asserts a count of captures, and the two numbers are not
    close: on the live corpus workspace the summed figure was 149 against 106 distinct.

    Three captures are ingested inside the morning trip and left out of the manifest. Four of the
    nine windows return all three, so a sum says twelve and the truth is three.
    """
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    from conftest import CountingVisionModel, write_photo

    repository, _built = timed_corpus
    store = LocalContentAddressedStore(tmp_path / "stray-blobs")
    for index in range(3):
        path = write_photo(
            photo_dir,
            f"unlisted-{index}.jpg",
            when=f"2026:03:04 10:00:{(index + 1) * 10:02d}",
            offset="+00:00",
        )
        outcome = PhotoIngestPipeline(
            repository, store, vision=CountingVisionModel()
        ).ingest_file(path)
        assert outcome.error is None, outcome.error

    count, why = _score_windows(timed_corpus)
    assert count is not None, why
    reported = " ".join(case.name for case in count.cases)
    assert "3 distinct capture(s) returned across these windows are outside this corpus" in (
        reported
    ), reported
    # Nothing was dropped and nothing failed, so the number really is the whole difference
    # between counting captures and counting appearances.
    assert count.n == 9 and count.k == 9, [(c.name, c.evidence) for c in count.cases]
