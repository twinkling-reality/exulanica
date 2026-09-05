"""Gold is independent of the product; scored answers traverse the real evidence path."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from exulanica.evaluation.counts import Count
from exulanica.evaluation.ground_truth import Frame, GroundTruth
from exulanica.evaluation.question_scorers import score_gold_questions
from exulanica.evaluation.questions import GoldQuestions, derive_questions
from exulanica.evaluation.report import render_report

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic-gold-questions"


def test_frozen_gold_is_bound_to_manifest_and_rejects_rewritten_answers(tmp_path):
    truth = GroundTruth.read(FIXTURE)
    frozen = GoldQuestions.read(FIXTURE / "QUESTIONS.json", truth)
    for question in frozen.questions:
        if question.dimension == "object":
            expected = tuple(
                sorted(f.sha256 for f in truth.frames if question.context["subject"] in f.subjects)
            )
            assert question.expected_photo_sha256 == expected
        elif question.dimension == "place":
            assert question.expected_capture_count == sum(
                f.place == question.context["place"] for f in truth.frames
            )
            assert question.plan is None and "human-confirmed" in question.blocked_on
    wrong_manifest = replace(truth, manifest_sha256="f" * 64)
    with pytest.raises(ValueError, match="different corpus manifest"):
        GoldQuestions.read(FIXTURE / "QUESTIONS.json", wrong_manifest)
    document = frozen.model_dump(mode="json")
    document["questions"][0]["expected_photo_sha256"] = []
    document["questions"][0]["expected_capture_count"] = 0
    tampered = tmp_path / "QUESTIONS.json"
    tampered.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="manifest-derived answers"):
        GoldQuestions.read(tampered, truth)
    # Direct callers cannot bypass the file loader and retain a rewritten gold set either.
    with pytest.raises(ValueError, match="manifest-derived answers"):
        score_gold_questions(None, None, truth, GoldQuestions.model_validate(document))


@pytest.fixture
def question_library(repository, photo_dir, tmp_path):
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    from conftest import write_photo

    store = LocalContentAddressedStore(tmp_path / "blobs")
    frames = []
    for minute in range(2):
        path = write_photo(
            photo_dir, f"frame-{minute}.jpg", when=f"2026:03:04 10:0{minute}:00", offset="+00:00"
        )
        # Truth is fixed before ingest; vision is deliberately omitted, not derived from gold.
        frames.append(
            Frame(
                filename=path.name,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                trip="morning",
                place="room",
                device_model="fixture",
                display_size=(160, 100),
                utc_instant=f"2026-03-04T10:0{minute}:00+00:00",
                instant_is_recoverable_from_the_file=True,
                gps_e7=None,
                subjects=("satchel",),
            )
        )
        outcome = PhotoIngestPipeline(repository, store, vision=None).ingest_file(path)
        assert outcome.error is None, outcome.error
    truth = GroundTruth(
        path=tmp_path / "MANIFEST.json",
        manifest_sha256="0" * 64,
        generator="test fixture",
        synthetic=True,
        disclosure="Two synthetic EXIF plates; vision omitted.",
        frames=tuple(frames),
        trips=("morning",),
        places=("room",),
        subjects=("satchel",),
        subject_labels={"satchel": ("red block",)},
    )
    return repository, truth


def test_gold_scoring_executes_plans_and_checks_real_answer_tokens(question_library):
    repository, truth = question_library
    scores = score_gold_questions(
        repository.connection, repository.workspace_id, truth, derive_questions(truth)
    )
    assert not scores.blocked
    assert (scores.results["M8.plan_validity"].k, scores.results["M8.plan_validity"].n) == (9, 9)
    # No captions were ingested. The object miss stays a failure, never manufactured success.
    assert (
        scores.results["M8.gold_result_exact_match"].k,
        scores.results["M8.gold_result_exact_match"].n,
    ) == (2, 3)
    assert (
        scores.results["M1.answer_citation_grounding"].k,
        scores.results["M1.answer_citation_grounding"].n,
    ) == (2, 3)
    whole = next(o for o in scores.observations if o["question_id"] == "time:morning:whole")
    assert whole["retrieved_photo_sha256"] == sorted(truth.by_hash)
    assert whole["answer_grounded"] is True
    assert any(c["citations"] for c in whole["answer"]["clauses"])
    empty = next(o for o in scores.observations if o["question_id"] == "time:morning:before")
    assert empty["abstention"] == "UNANSWERABLE_NOT_CAPTURED"


def test_incomplete_corpus_cannot_shrink_gold_to_retrieved_rows(question_library):
    repository, truth = question_library
    missing = replace(truth.frames[0], filename="missing.jpg", sha256="f" * 64)
    truth = replace(truth, frames=(*truth.frames, missing))
    scores = score_gold_questions(
        repository.connection, repository.workspace_id, truth, derive_questions(truth)
    )
    assert all(value is None for value in scores.results.values())
    assert all("exactly once" in reason for reason in scores.blocked.values())
    assert not scores.observations


def test_bounded_results_stay_in_the_question_denominator(question_library, photo_dir, tmp_path):
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    from conftest import write_photo

    repository, truth = question_library
    frames = list(truth.frames)
    store = LocalContentAddressedStore(tmp_path / "more-blobs")
    for minute in range(2, 25):
        path = write_photo(
            photo_dir, f"extra-{minute}.jpg", when=f"2026:03:04 10:{minute:02}:00", offset="+00:00"
        )
        frames.append(
            replace(
                truth.frames[0],
                filename=path.name,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                utc_instant=f"2026-03-04T10:{minute:02}:00+00:00",
            )
        )
        assert PhotoIngestPipeline(repository, store, vision=None).ingest_file(path).error is None
    truth = replace(truth, frames=tuple(frames))
    scores = score_gold_questions(
        repository.connection, repository.workspace_id, truth, derive_questions(truth)
    )
    whole = next(o for o in scores.observations if o["question_id"] == "time:morning:whole")
    assert whole["bounded_result"] is True
    # The bounded page fails the full-set check; its honest total and cited subset can ground.
    assert (
        scores.results["M8.gold_result_exact_match"].k,
        scores.results["M8.gold_result_exact_match"].n,
    ) == (1, 3)
    assert (
        scores.results["M1.answer_citation_grounding"].k,
        scores.results["M1.answer_citation_grounding"].n,
    ) == (2, 3)


def test_report_refuses_static_and_runtime_blocked_numbers():
    options = dict(
        corpus_tag="SYNTH-1",
        corpus_version="fixture",
        manifest_sha256="0" * 64,
        synthetic=True,
        disclosure="synthetic",
        frames=2,
        git_commit="test",
    )
    with pytest.raises(ValueError, match="blocked component"):
        render_report({"M2.hallucination_rate": Count(0, 2)}, **options)
    with pytest.raises(ValueError, match="blocked component"):
        render_report(
            {"M8.plan_validity": Count(2, 2)},
            blocked={"M8.plan_validity": "incomplete corpus"},
            **options,
        )
