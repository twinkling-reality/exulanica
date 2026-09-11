"""The segmentation stage: local object masks per photograph, filed as regions and inference.

Most of this runs a scripted segmenter through the real pipeline against real PostgreSQL, because
what the stage promises is about rows, keys and pixels rather than about a model: which image the
segmenter was shown, which spans and assertions were written, what the ledger names, and that a
person never becomes an object. The checkpoints themselves are exercised at the bottom of the
file, behind a marker that skips when the segmentation extra is not installed.
"""

from __future__ import annotations

import copy
import dataclasses
import functools
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from exulanica.consent.regions import DetectedPerson, Silhouette
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import PPM, Rect
from exulanica.ingest.person_review import review_list
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import (
    authorize_synthetic_capture,
    record_human_screening,
    record_person_detection_screening,
)
from exulanica.ingest.stages import STAGES, stage
from exulanica.ingest.stages import segmentation as segmentation_stage
from exulanica.ingest.stages.segmentation import (
    BoxPrompt,
    Detections,
    LocalModelPin,
    LocalObjectSegmenter,
    SegmentedMask,
    SegmenterUnavailable,
    box_iou_millionths,
    deduplicate,
    local_model_roles,
    person_overlap_millionths,
)
from exulanica.ingest.vision import DetectedObject, VisionObservation
from exulanica.models.manifest import MANIFEST_PATH, load_manifest
from exulanica.store.local import LocalContentAddressedStore
from PIL import Image

from conftest import CountingVisionModel, ingest_observed, write_photo

ROOT = Path(__file__).resolve().parents[1]
ACTOR = uuid.UUID("a244f9d0-9bd9-5f55-a133-2712cd05d720")


@dataclasses.dataclass
class ScriptedSegmenter:
    """A segmenter that returns each box, inset, as its mask, and remembers what it was shown.

    ``detections`` is what ``detect`` returns; ``revision`` is the only thing that differs between
    two otherwise identical segmenters, which is how a test swaps a checkpoint.
    """

    detections: list[BoxPrompt] = dataclasses.field(default_factory=list)
    revision: str = "0" * 40
    quality_millionths: int = 910_000
    detect_calls: int = 0
    segment_calls: int = 0
    images: list[Image.Image] = dataclasses.field(default_factory=list)
    boxes: list[list[Rect]] = dataclasses.field(default_factory=list)

    @property
    def identity(self):
        pin = {"repo_id": "test/scripted-segmenter", "revision": self.revision, "license": "mit"}
        return {
            "contract": "exulanica.object-segmenter/v1",
            "segmenter": pin,
            "detector": {**pin, "repo_id": "test/scripted-detector"},
            "detector_fallback": None,
            "library": {"torch": "test", "transformers": "test"},
        }

    @property
    def device(self):
        return "cpu"

    def detect(self, image, policy):
        self.detect_calls += 1
        self.images.append(image.copy())
        return Detections(
            boxes=tuple(self.detections),
            model="test/scripted-detector@" + self.revision,
            models_tried=("test/scripted-detector@" + self.revision,),
            fallback_used=False,
        )

    def segment(self, image, boxes, policy):
        self.segment_calls += 1
        self.images.append(image.copy())
        self.boxes.append(list(boxes))
        masks = []
        for box in boxes:
            inset_x, inset_y = box.w_ppm // 10, box.h_ppm // 10
            outline = Silhouette.from_rect(
                Rect(
                    box.x_ppm + inset_x,
                    box.y_ppm + inset_y,
                    box.w_ppm - 2 * inset_x,
                    box.h_ppm - 2 * inset_y,
                )
            )
            area = (box.w_ppm - 2 * inset_x) * (box.h_ppm - 2 * inset_y) // PPM
            masks.append(SegmentedMask(outline, self.quality_millionths, area, 1))
        return masks


def _rows(repository, sql, *params):
    return repository.connection.execute(sql, params).fetchall()


def _segmentation_artifact(repository, store):
    rows = _rows(
        repository,
        "select artifact_id, content_sha256, read_source_sha256, privacy_screening_id "
        "from artifact where workspace_id=%s and stage_key='segmentation' order by created_at",
        repository.workspace_id,
    )
    assert rows, "the segmentation stage wrote no artifact"
    row = rows[-1]
    return row, json.loads(store.get(BlobId(bytes(row["content_sha256"]))))


def _segmentation_assertions(repository):
    return _rows(
        repository,
        "select a.object_value #>> '{}' as label, a.raw_score, a.support_span_ids, a.emit_key, "
        "a.produced_by_run, e.region from assertion a join predicate p on p.predicate_id = "
        "a.predicate_id join evidence_span e on e.span_id = a.support_span_ids[1] "
        "where a.workspace_id = %s and p.key = 'object_present' and a.emit_key like %s "
        "order by a.emit_key",
        repository.workspace_id,
        "%:m:%",
    )


# -- the pure parts ------------------------------------------------------------------------------


def test_no_vocabulary_term_is_a_person_by_the_vision_stages_own_filter():
    """The local detector can only label a box from the vocabulary, so a person term there would
    be the one way a person became an object prompt. Checked with the vision stage's own split
    rather than a list restated here."""
    vocabulary = STAGES["segmentation"].params["detector_vocabulary"]
    observation = VisionObservation(
        scene_description="x",
        objects=[
            DetectedObject(label=word, salience="primary", confidence="high") for word in vocabulary
        ],
    )
    assert [item.label for item in observation.non_person_objects] == list(vocabulary)


def test_the_stage_is_declared_not_bit_reproducible_and_carries_no_model_role():
    spec = STAGES["segmentation"]
    assert spec.deterministic is False
    assert spec.model_role is None
    assert spec.output_kind == segmentation_stage.OBJECT_MASK_KIND
    assert spec.params["profile"] == segmentation_stage.OBJECT_MASK_PROFILE
    assert spec.params["segmenter_contract"] == segmentation_stage.SEGMENTER_CONTRACT


def test_the_manifest_pins_both_local_roles_by_revision_with_frontmatter_licences():
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    roles = local_model_roles(document)
    segmenter = roles[segmentation_stage.SEGMENTATION_ROLE]
    detector = roles[segmentation_stage.DETECTION_ROLE]
    assert segmenter.fallback is None
    assert detector.fallback is not None
    for pin in (segmenter.primary, detector.primary, detector.fallback):
        assert len(pin.revision) == 40 and all(c in "0123456789abcdef" for c in pin.revision)
        assert pin.license == "apache-2.0"
        entry = document["local_models"][pin.repo_id]
        assert len(entry["readme_sha256"]) == 64
    assert "Cap4M" in document["local_models"][detector.primary.repo_id]["provenance_caveat"]
    # The bump that retires every cached hosted response produced under the old manifest.
    assert load_manifest().pipeline_version == 3


def test_no_local_checkpoint_identifier_is_inlined_in_python_source():
    """Invariant 7, extended to the checkpoints this codebase runs itself."""
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    offenders = []
    for path in sorted((ROOT / "exulanica").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for repo_id in document["local_models"]:
            if repo_id in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {repo_id!r}")
    assert offenders == []


def test_a_local_role_that_is_not_pinned_to_a_full_revision_is_refused():
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    broken = copy.deepcopy(document)
    repo = broken["local_roles"]["object_segmentation"]["primary"]
    broken["local_models"][repo]["revision"] = "main"
    with pytest.raises(ValueError, match="full lowercase revision"):
        local_model_roles(broken)
    unlicensed = copy.deepcopy(document)
    unlicensed["local_models"][repo]["license"] = ""
    with pytest.raises(ValueError, match="licence"):
        local_model_roles(unlicensed)


def test_the_frontmatter_licence_is_read_from_the_leading_block_only():
    read = segmentation_stage._frontmatter_licence
    assert read("---\nlicense: apache-2.0\npipeline_tag: x\n---\nbody license: mit\n") == (
        "apache-2.0"
    )
    assert read("---\ntags:\n- vision\n---\nlicense: mit\n") is None
    assert read("no frontmatter\nlicense: mit\n") is None


def test_a_licence_that_drifted_from_the_manifest_refuses_to_load(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    readme.write_text("---\nlicense: cc-by-nc-4.0\n---\n", encoding="utf-8")
    monkeypatch.setattr("huggingface_hub.hf_hub_download", lambda *a, **k: str(readme))
    pytest.importorskip("huggingface_hub")
    pin = LocalModelPin("test/model", "a" * 40, "apache-2.0")
    with pytest.raises(SegmenterUnavailable, match=r"cc-by-nc-4\.0"):
        segmentation_stage.verify_frontmatter_licence(pin)


def test_duplicate_boxes_keep_the_higher_score_whatever_their_labels():
    rock = BoxPrompt("rock", Rect(100_000, 100_000, 200_000, 200_000), "local_detector", 700_000)
    boulder = BoxPrompt(
        "boulder", Rect(110_000, 105_000, 195_000, 200_000), "local_detector", 650_000
    )
    tree = BoxPrompt("tree", Rect(600_000, 100_000, 100_000, 300_000), "local_detector", 400_000)
    assert box_iou_millionths(rock.box, boulder.box) > 700_000
    kept = deduplicate([boulder, tree, rock], iou_millionths=700_000, limit=24)
    assert [item.label for item in kept] == ["rock", "tree"]
    assert deduplicate([boulder, tree, rock], iou_millionths=700_000, limit=1) == [rock]


def test_person_overlap_is_measured_over_the_object_not_the_person():
    person = Silhouette.from_rect(Rect(0, 0, 500_000, 1_000_000))
    inside = Silhouette.from_rect(Rect(100_000, 100_000, 200_000, 200_000))
    half = Silhouette.from_rect(Rect(400_000, 100_000, 200_000, 200_000))
    apart = Silhouette.from_rect(Rect(700_000, 100_000, 200_000, 200_000))
    assert person_overlap_millionths(inside, [person]) == 1_000_000
    assert 450_000 <= person_overlap_millionths(half, [person]) <= 550_000
    assert person_overlap_millionths(apart, [person]) == 0


def test_the_detector_falls_back_when_the_primary_cannot_run():
    """The real class's chain, with its two forward passes replaced: the fallback exists for the
    primary failing, and a fallback that has never executed is not a mitigation."""
    primary = LocalModelPin("test/primary", "a" * 40, "apache-2.0")
    fallback = LocalModelPin("test/fallback", "b" * 40, "apache-2.0")
    segmenter = object.__new__(LocalObjectSegmenter)
    segmenter._detector_pins = (primary, fallback)

    def refuse(pin, image, policy):
        raise RuntimeError("the primary checkpoint could not be loaded")

    found = BoxPrompt("rock", Rect(0, 0, 500_000, 500_000), "local_detector", 800_000)
    segmenter._grounding_boxes = refuse
    segmenter._owl_boxes = lambda pin, image, policy: [found]
    policy, _outline = segmentation_stage._policies(STAGES["segmentation"].params)
    result = segmenter.detect(Image.new("RGB", (8, 8)), policy)
    assert result.fallback_used is True
    assert result.model == fallback.ref
    assert result.models_tried == (primary.ref, fallback.ref)
    assert result.boxes == (found,)

    segmenter._owl_boxes = refuse
    with pytest.raises(SegmenterUnavailable, match="no detector could run"):
        segmenter.detect(Image.new("RGB", (8, 8)), policy)


def test_a_forward_pass_that_mps_refuses_moves_to_the_cpu_once():
    class Model:
        def __init__(self):
            self.moves = []

        def to(self, device):
            self.moves.append(device)
            return self

    segmenter = object.__new__(LocalObjectSegmenter)
    segmenter._device = "mps"
    segmenter._fallback_note = None
    segmenter._sam = Model()
    detector = Model()
    segmenter._detectors = {"x": (detector, None)}
    seen = []

    def call(device):
        seen.append(device)
        if device == "mps":
            raise RuntimeError("unsupported on mps")
        return "ran"

    assert segmenter._on_device(call) == "ran"
    assert seen == ["mps", "cpu"]
    assert segmenter._sam.moves == ["cpu"] and detector.moves == ["cpu"]
    assert segmenter.device == "cpu (fell back from mps: RuntimeError)"


def test_a_mask_becomes_the_largest_contour_in_ppm():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    policy = segmentation_stage.OutlinePolicy(
        simplify_millionths_of_diagonal=1_500, max_vertices=64
    )
    mask = np.zeros((200, 300), dtype=bool)
    yy, xx = np.mgrid[:200, :300]
    mask[(xx - 100) ** 2 + (yy - 100) ** 2 <= 60**2] = True
    mask[10:20, 250:260] = True  # a second, smaller piece
    traced = segmentation_stage.outline_from_mask(mask, policy)
    assert traced is not None
    outline, area, components = traced
    assert components == 2
    assert area == int(mask.sum()) * 1_000_000 // (200 * 300)
    assert 3 <= len(outline.points) <= 64
    bound = outline.bounding_rect()
    # The disk spans 40..160 px of 300 and 40..160 of 200, and the stray square is not in it.
    assert abs(bound.x_ppm - 40 * PPM // 300) < 8_000
    assert abs(bound.x_ppm + bound.w_ppm - 161 * PPM // 300) < 8_000
    assert outline.contains(100 * PPM // 300, 100 * PPM // 200)
    assert not outline.contains(255 * PPM // 300, 15 * PPM // 200)
    assert segmentation_stage.outline_from_mask(np.zeros((4, 4), dtype=bool), policy) is None


# -- through the pipeline ------------------------------------------------------------------------


def _pipeline(repository, tmp_path, **kwargs):
    store = LocalContentAddressedStore(tmp_path / "blobs")
    return store, PhotoIngestPipeline(repository, store, **kwargs)


def test_hosted_boxes_prompt_the_segmenter_and_each_mask_is_a_span_and_an_inference(
    repository, photo_dir, tmp_path
):
    segmenter = ScriptedSegmenter()
    store, pipeline = _pipeline(
        repository, tmp_path, vision=CountingVisionModel(), segmenter=segmenter
    )
    outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, "a.jpg"))
    assert outcome.error is None, outcome.error
    assert "segmentation" in outcome.stages_run
    assert segmenter.detect_calls == 0, "hosted boxes were present, so no detector should run"
    assert segmenter.segment_calls == 1

    row, document = _segmentation_artifact(repository, store)
    assert document["profile"] == "exulanica.object-mask-list/v1"
    assert document["prompt_source"] == "hosted_vision"
    assert document["detector"] is None
    # DEFAULT_PAYLOAD locates one object and names one unlocated person. The person is never a
    # prompt: people are not objects, and an unlocated one has no box to offer anyway.
    assert [prompt["label"] for prompt in document["prompts"]] == ["red block"]
    [mask] = document["masks"]
    assert mask["label"] == "red block"
    assert mask["label_source"] == "hosted_vision"
    assert mask["label_confidence"] == {"band": "high"}
    assert mask["mask_confidence_millionths"] == 910_000
    assert mask["model"] == "test/scripted-segmenter@" + "0" * 40
    assert mask["outline"]["kind"] == "polygon"
    assert mask["prompt_span_digest"] is not None
    assert row["privacy_screening_id"] is not None
    assert row["read_source_sha256"] is None, "nobody was hidden, so the original was read"

    [assertion] = _segmentation_assertions(repository)
    assert assertion["label"] == "red block"
    assert assertion["raw_score"] == pytest.approx(0.91)
    region = assertion["region"]
    assert region["kind"] == "rect"
    assert region["rect"] == mask["bounds"], "the span is the mask's own bounding rectangle"

    # The model is named where every model is named: on the run the assertion points at.
    event = _rows(
        repository,
        "select model_ref, models_tried from pipeline_event where run_id=%s "
        "and stage_key='segmentation' and type='stage_succeeded'",
        assertion["produced_by_run"],
    )[0]
    assert event["model_ref"]["model_id"] == "test/scripted-segmenter"
    assert event["model_ref"]["revision"] == "0" * 40
    assert event["model_ref"]["provider"] == "local"
    assert event["models_tried"] == ["test/scripted-segmenter@" + "0" * 40]


def test_with_no_hosted_boxes_the_local_detector_prompts_and_is_named(
    repository, photo_dir, tmp_path
):
    found = BoxPrompt("rock", Rect(100_000, 200_000, 300_000, 300_000), "local_detector", 640_000)
    stray = BoxPrompt("person", Rect(600_000, 100_000, 200_000, 600_000), "local_detector", 990_000)
    segmenter = ScriptedSegmenter(detections=[found, stray])
    store, pipeline = _pipeline(repository, tmp_path, segmenter=segmenter)
    outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, "a.jpg"))
    assert outcome.error is None, outcome.error
    assert segmenter.detect_calls == 1

    _row, document = _segmentation_artifact(repository, store)
    assert document["prompt_source"] == "local_detector"
    assert document["detector"]["model"] == "test/scripted-detector@" + "0" * 40
    # A label outside the vocabulary is not believed, and a person term is the case that matters.
    assert [prompt["label"] for prompt in document["prompts"]] == ["rock"]
    assert document["dropped"]["outside_vocabulary"] == 1
    [mask] = document["masks"]
    assert mask["label_confidence"] == {"score_millionths": 640_000}
    assert mask["prompt_span_digest"] is None

    event = _rows(
        repository,
        "select model_ref, models_tried from pipeline_event where run_id=%s "
        "and stage_key='segmentation' and type='stage_succeeded'",
        outcome.run_id,
    )[0]
    assert event["model_ref"]["detector"] == "test/scripted-detector@" + "0" * 40
    assert event["models_tried"] == [
        "test/scripted-detector@" + "0" * 40,
        "test/scripted-segmenter@" + "0" * 40,
    ]
    [assertion] = _segmentation_assertions(repository)
    assert assertion["label"] == "rock"


def test_no_segmenter_and_no_screening_are_both_unavailable_rather_than_failed(
    repository, photo_dir, tmp_path
):
    _store, pipeline = _pipeline(repository, tmp_path)
    outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, "a.jpg"))
    assert outcome.error is None
    assert "segmentation" in outcome.stages_unavailable

    segmenter = ScriptedSegmenter()
    _store, unscreened = _pipeline(repository, tmp_path, segmenter=segmenter)
    second = unscreened.ingest_file(write_photo(photo_dir, "b.jpg", when="2026:09:04 12:01:00"))
    assert second.error is None, second.error
    assert "segmentation" in second.stages_unavailable
    assert segmenter.segment_calls == 0 and segmenter.detect_calls == 0
    reasons = _rows(
        repository,
        "select error_message from pipeline_event where run_id=%s and stage_key='segmentation'",
        second.run_id,
    )
    assert "privacy screening" in reasons[0]["error_message"]


def test_a_second_run_reuses_the_masks_and_a_new_checkpoint_rekeys_them(
    repository, photo_dir, tmp_path
):
    path = write_photo(photo_dir, "a.jpg")
    segmenter = ScriptedSegmenter()
    _store, pipeline = _pipeline(
        repository, tmp_path, vision=CountingVisionModel(), segmenter=segmenter
    )
    first = ingest_observed(pipeline, repository, path)
    assert first.error is None
    capture_id = first.capture_id
    screening = repository.latest_privacy_screening(capture_id)
    again = pipeline.ingest_derivatives(capture_id, privacy_screening_id=screening.screening_id)
    assert again.error is None
    assert "segmentation" in again.stages_reused
    assert segmenter.segment_calls == 1

    swapped = ScriptedSegmenter(revision="1" * 40)
    _store, other = _pipeline(repository, tmp_path, vision=CountingVisionModel(), segmenter=swapped)
    third = other.ingest_derivatives(capture_id, privacy_screening_id=screening.screening_id)
    assert third.error is None
    assert "segmentation" in third.stages_run
    assert swapped.segment_calls == 1
    artifacts = _rows(
        repository,
        "select count(*) as n from artifact where workspace_id=%s and stage_key='segmentation'",
        repository.workspace_id,
    )
    assert artifacts[0]["n"] == 2


def _people_photograph(repository, photo_dir, tmp_path, segmenter, *, vision_payload=None):
    """One synthetic photograph with one located person nobody has consented for, screened."""
    from exulanica.ingest.person_detectors import StubRegionDetector

    person = Silhouette.from_rect(Rect.from_normalised(0.55, 0.1, 0.3, 0.8))
    detections = (DetectedPerson(person, "box", "high", "fixed-region-double", part="full_body"),)
    path = write_photo(photo_dir, "people.jpg")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    vision = CountingVisionModel(payload=vision_payload) if vision_payload else None
    pipeline = PhotoIngestPipeline(
        repository,
        store,
        vision=vision,
        detector=StubRegionDetector(detections),
        segmenter=segmenter,
    )
    intake = pipeline.ingest_intake(path.read_bytes(), filename=path.name)
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=intake.capture_id,
        actor=ACTOR,
        generator_manifest={
            "profile": "exulanica.segmentation-test/v1",
            "notice": "SYNTHETIC TEST FIXTURE",
        },
        authorization_scope={"purpose": "segmentation masking test"},
    )
    detection = record_person_detection_screening(
        repository,
        authorization_id=authorization.authorization_id,
        authorized_by=ACTOR,
        purpose="Locate simulated people in generated fixture bytes",
    )
    observed = pipeline.ingest_derivatives(
        intake.capture_id, privacy_screening_id=detection.screening_id
    )
    assert observed.error is None, observed.error
    screening = record_human_screening(
        repository,
        authorization_id=authorization.authorization_id,
        reviewed_by=ACTOR,
        sensitive_regions=review_list(repository, intake.capture_id),
    )
    outcome = pipeline.ingest_derivatives(
        intake.capture_id, privacy_screening_id=screening.screening_id
    )
    assert outcome.error is None, outcome.error
    return store, person, outcome


def test_the_segmenter_reads_the_masked_derivative_when_somebody_is_hidden(
    repository, photo_dir, tmp_path
):
    """The rule depth follows, for the same reason: a person who has not consented is neutral
    fill before a pixel reaches the model."""
    found = BoxPrompt("bench", Rect(50_000, 300_000, 300_000, 300_000), "local_detector", 700_000)
    segmenter = ScriptedSegmenter(detections=[found])
    store, _person, _outcome = _people_photograph(repository, photo_dir, tmp_path, segmenter)
    assert segmenter.images, "the segmenter never ran"
    seen = segmenter.images[-1].convert("RGB")
    width, height = seen.size
    centre = (int(0.7 * width), int(0.5 * height))
    assert seen.getpixel(centre) == (128, 128, 128), "the hidden person reached the segmenter"

    row, document = _segmentation_artifact(repository, store)
    assert document["source"]["masked"] is True
    assert row["read_source_sha256"] is not None
    masked = _rows(
        repository,
        "select content_sha256 from artifact where workspace_id=%s and kind='masked_source'",
        repository.workspace_id,
    )
    assert bytes(row["read_source_sha256"]) == bytes(masked[-1]["content_sha256"])
    assert document["source"]["read_sha256"] == bytes(masked[-1]["content_sha256"]).hex()


def test_a_mask_that_is_mostly_a_person_is_dropped_and_never_asserted(
    repository, photo_dir, tmp_path
):
    """An object outline must never become a second, unreviewed outline of somebody."""
    over_person = BoxPrompt(
        "bag", Rect.from_normalised(0.6, 0.2, 0.2, 0.5), "local_detector", 800_000
    )
    elsewhere = BoxPrompt(
        "bench", Rect.from_normalised(0.05, 0.3, 0.3, 0.3), "local_detector", 700_000
    )
    segmenter = ScriptedSegmenter(detections=[over_person, elsewhere])
    store, _person, _outcome = _people_photograph(repository, photo_dir, tmp_path, segmenter)
    _row, document = _segmentation_artifact(repository, store)
    assert [mask["label"] for mask in document["masks"]] == ["bench"]
    assert document["dropped"]["person_overlap"] == 1
    assert [row["label"] for row in _segmentation_assertions(repository)] == ["bench"]


def test_the_stage_is_registered_so_its_ledger_events_are_accepted(repository):
    repository.register_stages(STAGES)
    registered = _rows(
        repository,
        "select stage_key, output_kind, deterministic from stage_definition "
        "where stage_key in ('segmentation', 'scene_segments') order by stage_key",
    )
    assert [(row["stage_key"], row["output_kind"], row["deterministic"]) for row in registered] == [
        ("scene_segments", "scene_segments", True),
        ("segmentation", "object_mask_list", False),
    ]
    assert stage("segmentation").params_digest == STAGES["segmentation"].params_digest


# -- the real checkpoints ------------------------------------------------------------------------
#
# Each runs in a child pytest, never in the suite's own process. MEASURED 2026-09-11: run in
# process, the first of these aborted the whole backend suite at 76 per cent with SIGABRT and no
# summary, because earlier tests had already loaded pycolmap and torch brings a second OpenMP
# runtime (`exulanica/reconstruction/pycolmap_executor.py` records the same abort, OMP Error #15).
# `tests/test_gsplat_runner.py` isolates its torch tests the same way, for the same reason.

_EXTRA = all(
    importlib.util.find_spec(name) is not None
    for name in ("torch", "transformers", "numpy", "cv2", "huggingface_hub")
)
real_models = pytest.mark.skipif(
    not _EXTRA, reason="the segmentation extra (torch, transformers, opencv) is not installed"
)
_CHILD = "EXULANICA_SEGMENTATION_TEST_CHILD"


def _isolated_torch(test):
    """Run ``test`` alone in a child pytest, so torch never shares a process with pycolmap."""

    @functools.wraps(test)
    def execute():
        if os.environ.get(_CHILD) == test.__name__:
            return test()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                f"{Path(__file__).resolve()}::{test.__name__}",
            ],
            env={**os.environ, _CHILD: test.__name__},
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    return execute


@functools.cache
def _local_segmenter() -> LocalObjectSegmenter:
    return LocalObjectSegmenter()


def _disk_photograph() -> tuple[Image.Image, Rect]:
    """A red disk on a grey ground, and a box around it with some slack."""
    from PIL import ImageDraw

    image = Image.new("RGB", (640, 480), (118, 122, 126))
    draw = ImageDraw.Draw(image)
    draw.ellipse((200, 120, 440, 360), fill=(200, 30, 30))
    return image, Rect.from_normalised(180 / 640, 100 / 480, 280 / 640, 280 / 480)


@real_models
@_isolated_torch
def test_the_pinned_checkpoints_load_with_their_frontmatter_licences():
    local_segmenter = _local_segmenter()
    identity = local_segmenter.identity
    roles = local_model_roles()
    assert identity["segmenter"] == roles["object_segmentation"].primary.as_identity()
    assert identity["detector"] == roles["open_vocabulary_detection"].primary.as_identity()
    assert (
        identity["detector_fallback"] == roles["open_vocabulary_detection"].fallback.as_identity()
    )
    assert identity["library"]["transformers"] == "5.17.0"
    assert local_segmenter.device in {"mps", "cpu"} or local_segmenter.device.startswith("cpu (")


@real_models
@_isolated_torch
def test_sam_masks_a_drawn_disk_from_a_box():
    local_segmenter = _local_segmenter()
    np = pytest.importorskip("numpy")
    image, box = _disk_photograph()
    policy = segmentation_stage._policies(STAGES["segmentation"].params)[1]
    [mask] = local_segmenter.segment(image, [box], policy)
    assert mask is not None
    assert mask.confidence_millionths > 500_000
    # Intersection over union of the outline against the disk, on a lattice.
    inside_both = inside_either = 0
    for y in range(0, 480, 4):
        for x in range(0, 640, 4):
            disk = (x - 320) ** 2 + (y - 240) ** 2 <= 120**2
            traced = mask.outline.contains(x * PPM // 640, y * PPM // 480)
            inside_both += disk and traced
            inside_either += disk or traced
    assert inside_both / inside_either > 0.85
    assert np is not None


@real_models
@_isolated_torch
def test_both_detectors_run_and_answer_in_the_vocabulary():
    local_segmenter = _local_segmenter()
    image, _box = _disk_photograph()
    policy = segmentation_stage._policies(STAGES["segmentation"].params)[0]
    primary, fallback = local_segmenter._detector_pins
    for boxes in (
        local_segmenter._grounding_boxes(primary, image, policy),
        local_segmenter._owl_boxes(fallback, image, policy),
    ):
        for found in boxes:
            assert found.label in policy.vocabulary
            assert found.source == "local_detector"
            assert 0 < found.score_millionths <= 1_000_000
    detected = local_segmenter.detect(image, policy)
    assert detected.model == primary.ref and detected.fallback_used is False
