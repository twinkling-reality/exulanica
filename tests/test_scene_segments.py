"""Lifting per-photograph regions into a scene, and the read that stands behind the result.

Three layers, cheapest first. The projector and the rasteriser against the arithmetic they must
agree with. The vote on a synthetic scene whose answer is known by construction. And the whole
path on the production pipeline's own synthetic scene: FakeColmap's three cameras at x = 1, 2, 3
looking down +z at a world plane at z = 6, the placed point maps lying on that plane, masks from a
scripted segmenter that knows where a marker is, and the reader refusing or withholding as each
binding moves.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import math
import uuid
from pathlib import Path

import pytest
from exulanica.consent.regions import Silhouette, region_key
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import PPM, DisplayGeometry, Rect
from exulanica.graph import reconstruction_scenes as reader
from exulanica.graph.asset_read_policy import clear_scene_inputs_memo
from exulanica.graph.reconstruction_scenes import clear_placement_memo, scene_segments_read
from exulanica.ingest import scene_segments as lift
from exulanica.ingest.masked_geometry import GaussianView, camera_point, image_point, ppm_point
from exulanica.ingest.person_review import create_subject, record_consent, record_region_edits
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.stages import STAGES
from exulanica.ingest.stages import segmentation as segmentation_stage
from exulanica.ingest.stages.segmentation import BoxPrompt, Detections, SegmentedMask

from test_scene_reconstruction_pipeline import FakeColmap, _processor, _queued_scene

np = pytest.importorskip("numpy")

PARAMS = STAGES["scene_segments"].params
ACTOR = uuid.UUID("a244f9d0-9bd9-5f55-a133-2712cd05d720")


# -- the projector and the rasteriser ------------------------------------------------------------


def _view(position, *, size=(1000, 800), focal=700.0):
    """A pinhole camera at ``position`` looking at the origin, as the check's view type."""
    from scipy.spatial.transform import Rotation

    forward = -np.asarray(position, dtype=float)
    forward /= np.linalg.norm(forward)
    right = np.cross(np.array([0.0, 1.0, 0.0]), forward)
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    rotation = np.stack([right, down, forward])
    x, y, z, w = Rotation.from_matrix(rotation).as_quat()
    translation = -rotation @ np.asarray(position, dtype=float)
    return GaussianView(
        image_name=str(position),
        quaternion_wxyz=(float(w), float(x), float(y), float(z)),
        translation_xyz=tuple(float(value) for value in translation),
        image_size=size,
        focal_xy=(focal, focal),
        principal_xy=(size[0] / 2, size[1] / 2),
        masked=(),
        confirmed=(),
    )


def test_the_exposed_projector_gives_arrays_the_values_it_gives_floats():
    """One projector: the lift's array call and the check's scalar call agree bit for bit."""
    pytest.importorskip("scipy")
    view = _view((3.0, -1.0, -5.0))
    points = np.random.default_rng(7).uniform(-1, 1, (50, 3))
    camera = camera_point(view, (points[:, 0], points[:, 1], points[:, 2]))
    u, v = image_point(view, camera)
    x_ppm, y_ppm = ppm_point(view, u, v)
    for index, point in enumerate(points.tolist()):
        scalar = camera_point(view, point)
        su, sv = image_point(view, scalar)
        assert (scalar[2], su, sv) == (camera[2][index], u[index], v[index])
        if 0 <= su < view.image_size[0] and 0 <= sv < view.image_size[1]:
            assert tuple(int(value) for value in ppm_point(view, su, sv)) == (
                int(x_ppm[index]),
                int(y_ppm[index]),
            )


def test_the_raster_agrees_with_the_outline_containment_it_stands_in_for():
    concave = Silhouette(
        (
            (100_000, 100_000),
            (900_000, 120_000),
            (500_000, 450_000),
            (880_000, 900_000),
            (140_000, 860_000),
        )
    )
    box = Silhouette.from_rect(Rect(250_000, 300_000, 300_000, 200_000))
    for outline in (concave, box):
        width, height = 97, 61
        raster = lift._raster(outline, width, height)
        for row in range(height):
            y = (2 * row + 1) * PPM // (2 * height)
            for column in range(width):
                x = (2 * column + 1) * PPM // (2 * width)
                assert raster[row, column] == outline.contains(x, y), (outline, row, column)


# -- the vote, on a scene whose answer is known ------------------------------------------------


def _hull(points):
    ordered = sorted(set(points))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return tuple(lower[:-1] + upper[:-1])


def _outline_of(view, corners):
    camera = camera_point(view, (corners[:, 0], corners[:, 1], corners[:, 2]))
    u, v = image_point(view, camera)
    x_ppm, y_ppm = ppm_point(view, u, v)
    return Silhouette(_hull([(int(x), int(y)) for x, y in zip(x_ppm, y_ppm, strict=True)]))


def _cube(centre, half=0.5, count=400, seed=0):
    rng = np.random.default_rng(seed)
    return rng.uniform(-half, half, (count, 3)) + np.asarray(centre)


def _corners(centre, half=0.5):
    return np.array(
        [[x, y, z] for x in (-half, half) for y in (-half, half) for z in (-half, half)]
    ) + np.asarray(centre)


def _views():
    return {
        f"cam{index}": _view((6 * math.sin(angle), -1.0, -6 * math.cos(angle)))
        for index, angle in enumerate(np.linspace(-0.6, 0.6, 5))
    }


def _region(capture, outline, *, label="box", subject=None):
    return lift.LiftRegion(
        capture_ref=capture,
        kind="person" if subject else "object",
        label=None if subject else label,
        subject_ref=subject,
        reference=(
            {"kind": "person_region", "region_key": capture.encode().hex().ljust(64, "0")}
            if subject
            else {
                "kind": "object_mask",
                "artifact_ref": capture,
                "mask_index": 0,
                "span_digest": "0" * 64,
                "prompt_span_digest": None,
            }
        ),
        digest="d" * 64,
        outline=outline,
    )


def _samples(*clouds):
    points = np.concatenate(clouds)
    return lift._Samples(points, np.zeros(len(points), dtype=np.int64), (("m", "a", "0" * 64),))


def test_an_object_every_view_outlines_is_one_segment_and_the_wall_behind_it_is_not():
    pytest.importorskip("scipy")
    views = _views()
    rng = np.random.default_rng(1)
    wall = np.stack(
        [rng.uniform(-4, 4, 1600), rng.uniform(-3, 3, 1600), np.full(1600, 3.0)], axis=1
    )
    cube = _cube((0.0, 0.0, 0.0))
    regions = [
        _region(name, _outline_of(view, _corners((0, 0, 0)))) for name, view in views.items()
    ]
    segments, summary = lift._lift(_samples(cube, wall), views, {}, regions, PARAMS)
    [segment] = segments
    assert segment["label"] == "box"
    assert segment["votes"]["views"] == 5
    assert segment["votes"]["min"] == segment["votes"]["max"] == 5
    assert segment["votes"]["fraction_min_millionths"] == 1_000_000
    # Every sample in the segment is a cube sample: none of the 1600 wall samples, which each
    # fall inside the cube's outline in at most two of the five views, reached a majority.
    low, high = segment["bounds_microunits"]["min"], segment["bounds_microunits"]["max"]
    assert all(value >= -500_000 for value in low) and all(value <= 500_000 for value in high)
    assert segment["samples"]["point_map"] >= 380
    assert summary["samples"]["point_map"] == 2000


def test_one_view_is_a_projection_and_not_a_vote():
    pytest.importorskip("scipy")
    views = _views()
    cube = _cube((0.0, 0.0, 0.0))
    name, view = next(iter(views.items()))
    regions = [_region(name, _outline_of(view, _corners((0, 0, 0))))]
    segments, _summary = lift._lift(_samples(cube), views, {}, regions, PARAMS)
    assert segments == []


def test_two_objects_that_do_not_touch_are_two_segments_of_one_label():
    pytest.importorskip("scipy")
    views = _views()
    left, right = (-1.5, 0.0, 0.0), (1.5, 0.0, 0.0)
    regions = [
        _region(name, _outline_of(view, _corners(centre)))
        for name, view in views.items()
        for centre in (left, right)
    ]
    samples = _samples(_cube(left, seed=2), _cube(right, seed=3))
    segments, _summary = lift._lift(samples, views, {}, regions, PARAMS)
    assert [segment["label"] for segment in segments] == ["box", "box"]
    centroids = sorted(segment["centroid_microunits"][0] for segment in segments)
    assert centroids[0] < -1_000_000 and centroids[1] > 1_000_000
    assert len({segment["segment_id"] for segment in segments}) == 2


def test_a_reviewed_person_takes_a_sample_an_object_ties_for():
    pytest.importorskip("scipy")
    views = _views()
    regions = []
    for name, view in views.items():
        outline = _outline_of(view, _corners((0, 0, 0)))
        regions.append(_region(name, outline, label="bag"))
        regions.append(_region(name, outline, subject="11111111-1111-1111-1111-111111111111"))
    segments, _summary = lift._lift(_samples(_cube((0, 0, 0))), views, {}, regions, PARAMS)
    [segment] = segments
    assert segment["kind"] == "person" and segment["label"] is None
    assert segment["subject_ref"] == "11111111-1111-1111-1111-111111111111"


def _wall_in_front_of(view, distance=3.0):
    """A dense plane square to a camera's axis, ``distance`` in front of it: its own point map."""
    from scipy.spatial.transform import Rotation

    w, x, y, z = view.quaternion_wxyz
    rotation = Rotation.from_quat([x, y, z, w]).as_matrix()
    centre = -rotation.T @ np.asarray(view.translation_xyz)
    # Dense enough that every occlusion cell holds a point, as a real per-pixel map does.
    grid = np.linspace(-3, 3, 240)
    across, down = np.meshgrid(grid, grid)
    return (
        centre
        + distance * rotation[2]
        + across.reshape(-1, 1) * rotation[0]
        + down.reshape(-1, 1) * rotation[1]
    )


def test_a_view_whose_own_map_puts_a_surface_in_front_does_not_count_as_seeing():
    """The depth test, isolated. Two views outline the cube and three do not. With no depth
    buffers the three count as seeing it, two of five is a minority, and nothing is lifted. Give
    the three a wall in front of the cube in their own maps and they did not see it: two of two."""
    pytest.importorskip("scipy")
    views = _views()
    names = list(views)
    regions = [_region(name, _outline_of(views[name], _corners((0, 0, 0)))) for name in names[:2]]
    samples = _samples(_cube((0, 0, 0)))
    assert lift._lift(samples, views, {}, regions, PARAMS)[0] == []
    walls = {name: _wall_in_front_of(views[name]) for name in names[2:]}
    [segment] = lift._lift(samples, views, walls, regions, PARAMS)[0]
    assert segment["votes"]["views"] == 2
    assert segment["votes"]["fraction_min_millionths"] == 1_000_000


# -- the whole path, on the pipeline's own synthetic scene ---------------------------------------

#: FakeColmap's cameras sit at x = 5, 10 and 15 and its world plane at z = 30. Spaced this far so
#: the pose clears the policy's camera-translation floor and is ACCEPTED: an unaccepted receipt
#: publishes no recovered cameras, and a scene with no cameras lifts nothing, correctly.
SPACING = 5
DEPTH = 6 * SPACING
#: A marker on the world plane, and where people stand on the same plane.
MARKER = ((7.0, 13.0), (-4.0, 4.0))
PERSON = ((17.0, 21.0), (-4.0, 4.0))


def _plane_outline(width, height, camera_x, area):
    """Where a rectangle on the world plane falls in the FakeColmap camera at ``camera_x``."""
    focal = height / (2 * math.tan(math.radians(60) / 2))
    (x0, x1), (y0, y1) = area
    points = []
    for wx, wy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        u = (wx - camera_x) / DEPTH * focal + width / 2
        v = wy / DEPTH * focal + height / 2
        points.append((round(u / width * PPM), round(v / height * PPM)))
    return Silhouette(tuple(points))


@dataclasses.dataclass
class SceneSegmenter:
    """Knows where the marker is in each of the three synthetic photographs, by their widths."""

    revision: str = "0" * 40
    area: tuple = MARKER

    @property
    def identity(self):
        pin = {"repo_id": "test/scene-segmenter", "revision": self.revision, "license": "mit"}
        return {
            "contract": "exulanica.object-segmenter/v1",
            "segmenter": pin,
            "detector": pin,
            "detector_fallback": None,
            "library": {},
        }

    @property
    def device(self):
        return "cpu"

    def _outline(self, image):
        return _plane_outline(image.width, image.height, (image.width - 159) * SPACING, self.area)

    def detect(self, image, policy):
        box = self._outline(image).bounding_rect()
        prompt = BoxPrompt("sign", box, "local_detector", 900_000)
        return Detections(
            (prompt,),
            "test/scene-detector@" + self.revision,
            ("test/scene-detector@" + self.revision,),
            False,
        )

    def segment(self, image, boxes, policy):
        outline = self._outline(image)
        bound = outline.bounding_rect()
        return [SegmentedMask(outline, 950_000, bound.w_ppm * bound.h_ppm // PPM, 1) for _ in boxes]


def _published(repository, tmp_path, worker):
    clear_placement_memo()
    clear_scene_inputs_memo()
    store, captures, point_artifacts, _job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker=worker, lease_seconds=60)
    executor = FakeColmap(registered=3, camera_spacing=SPACING)
    outcome = _processor(repository, store, tmp_path, executor).process(claimed)
    assert outcome.status == "succeeded"
    return store, captures, point_artifacts, outcome.scene_id


class MarkerVisionModel:
    """A hosted pass that locates the marker in each synthetic photograph, by its width."""

    model_id = "MiniMaxAI/MiniMax-M3"

    def observe(self, *, image_bytes, media_type):
        import io

        from exulanica.ingest.vision import VisionObservation, VisionResult
        from PIL import Image

        width, height = Image.open(io.BytesIO(image_bytes)).size
        bound = _plane_outline(width, height, (width - 159) * SPACING, MARKER).bounding_rect()
        payload = {
            "scene_description": "A marker on a plane.",
            "objects": [
                {
                    "label": "trail sign",
                    "salience": "primary",
                    "confidence": "high",
                    "box": {
                        "x": bound.x_ppm / PPM,
                        "y": bound.y_ppm / PPM,
                        "w": bound.w_ppm / PPM,
                        "h": bound.h_ppm / PPM,
                    },
                }
            ],
        }
        return VisionResult(
            observation=VisionObservation.model_validate(payload),
            payload=payload,
            model_id=self.model_id,
            model_ref={"provider": "test", "model_id": self.model_id, "endpoint": "test"},
            cost={"input_tokens": 1, "output_tokens": 1, "usd_estimate": "0"},
            attempts=1,
            tried=(self.model_id,),
            latency_ms=1,
        )


def _segment_members(repository, store, captures, segmenter, *, vision=None):
    pipeline = PhotoIngestPipeline(repository, store, vision=vision, segmenter=segmenter)
    for capture in captures:
        screening = repository.latest_privacy_screening(capture)
        outcome = pipeline.ingest_derivatives(capture, privacy_screening_id=screening.screening_id)
        assert outcome.error is None, outcome.error
        assert "segmentation" in outcome.stages_run + outcome.stages_reused


def _add_person(repository, captures, subject, area=PERSON, *, only_last=False):
    for capture in captures[-1:] if only_last else captures:
        row = repository.connection.execute(
            "select blob_sha256 from capture where capture_id=%s", (capture,)
        ).fetchone()
        blob = BlobId(bytes(row["blob_sha256"]))
        width = 160 + captures.index(capture)
        outline = _plane_outline(width, 100, (captures.index(capture) + 1) * SPACING, area)
        key = region_key(blob, outline, DisplayGeometry(w=width, h=100))
        record_region_edits(
            repository,
            capture_id=capture,
            actor=ACTOR,
            edits=[
                {
                    "action": "add",
                    "region_key": key.hex(),
                    "silhouette": outline.as_digest_input(),
                    "subject_id": str(subject) if subject else None,
                }
            ],
        )


def _published_with_person(repository, tmp_path, worker):
    """A published scene whose person was reviewed BEFORE the screening its point maps bind.

    The order production follows and `_published` cannot: a synthetic exemption is refused for a
    photograph with any region in it, so a person added after one makes the scene's geometry
    unreadable, correctly. Here the person is outlined and consents first, a human screening lists
    them, and the point maps are bound to that screening, so the asset-read policy admits the
    scene and its person segment together.
    """
    from exulanica.ingest.person_review import review_list
    from exulanica.ingest.privacy import authorize_synthetic_capture, record_human_screening
    from exulanica.ingest.scenes import run_scene_grouping
    from exulanica.store.local import LocalContentAddressedStore

    from conftest import CountingVisionModel, write_photo, write_point_map
    from test_scene_reconstruction_pipeline import _numeric_point_map

    clear_placement_memo()
    clear_scene_inputs_memo()
    store = LocalContentAddressedStore(tmp_path / "store")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    photos = tmp_path / "photos"
    photos.mkdir(exist_ok=True)
    subject = create_subject(repository, actor=ACTOR)
    record_consent(
        repository, subject_id=subject, actor=ACTOR, consent_scope="likeness", decision="granted"
    )
    captures = []
    for index in range(3):
        path = write_photo(
            photos, f"{index}.jpg", when=f"2026:09:04 12:0{index}:00", size=(160 + index, 100)
        )
        outcome = pipeline.ingest_file(path)
        assert outcome.error is None, outcome.error
        captures.append(outcome.capture_id)
        _add_person(repository, captures, subject, only_last=True)
        authorization = authorize_synthetic_capture(
            repository,
            capture_id=outcome.capture_id,
            actor=ACTOR,
            generator_manifest={
                "profile": "exulanica.scene-segments-test/v1",
                "notice": "SYNTHETIC TEST FIXTURE",
            },
            authorization_scope={"purpose": "scene segment person path"},
        )
        screening = record_human_screening(
            repository,
            authorization_id=authorization.authorization_id,
            reviewed_by=ACTOR,
            sensitive_regions=review_list(repository, outcome.capture_id),
        )
        write_point_map(
            repository,
            store,
            BlobId.of_bytes(path.read_bytes()),
            payload=_numeric_point_map(index),
            privacy_screening_id=screening.screening_id,
        )
    assert len(run_scene_grouping(repository).reconstruction_jobs) == 1
    claimed = repository.claim_reconstruction_scene(worker=worker, lease_seconds=60)
    executor = FakeColmap(registered=3, camera_spacing=SPACING)
    outcome = _processor(repository, store, tmp_path, executor).process(claimed)
    assert outcome.status == "succeeded"
    return store, captures, subject, outcome.scene_id


def _read(repository, store, scene_id):
    return scene_segments_read(repository.connection, repository.workspace_id, scene_id, store)


def test_a_published_scene_lifts_its_masks_into_one_bound_segment(repository, tmp_path):
    store, captures, point_artifacts, scene_id = _published(repository, tmp_path, "lift")
    assert _read(repository, store, scene_id).state == "absent"
    _segment_members(repository, store, captures, SceneSegmenter())

    written = lift.publish_scene_segments(repository, store, scene_id)
    assert written["action"] == "written", written
    assert written["object_mask_inputs"] == 3 and written["object_mask_missing"] == 0
    again = lift.publish_scene_segments(repository, store, scene_id)
    assert again["action"] == "already-present"
    assert again["artifact_id"] == written["artifact_id"]

    envelope = json.loads(store.get(BlobId.from_hex(written["segments_sha256"])))
    payload = envelope["segments"]
    bindings = payload["bindings"]
    assert bindings["member_capture_refs"] == [str(capture) for capture in captures]
    assert [item["artifact_ref"] for item in bindings["point_map_inputs"]] == [
        str(item) for item in point_artifacts
    ]
    assert len(bindings["object_mask_inputs"]) == 3
    assert bindings["person_regions"] == [] and bindings["gaussian_source"] is None
    assert payload["policy"]["vote_threshold_millionths"] == PARAMS["vote_threshold_millionths"]

    read = _read(repository, store, scene_id)
    assert read.state == "available", read.reason
    [segment] = read.segments
    assert segment["kind"] == "object" and segment["label"] == "sign"
    # Three views outline the marker. A sample on its very edge can fall just outside one view's
    # outline, which is why the floor is the policy's minimum rather than three.
    assert segment["votes"]["views"] == 3 and segment["votes"]["max"] == 3
    assert segment["votes"]["min"] >= PARAMS["min_votes"]
    assert segment["voxel_count"] == len(segment["voxels"]) > 0
    # Every sample in the segment lies on the marker, on the world plane.
    low, high = segment["bounds_microunits"]["min"], segment["bounds_microunits"]["max"]
    assert low[0] >= 6_500_000 and high[0] <= 13_500_000
    assert low[1] >= -4_500_000 and high[1] <= 4_500_000
    assert abs(low[2] - DEPTH * 1_000_000) < 100_000 and abs(high[2] - DEPTH * 1_000_000) < 100_000
    assert all(region["span_id"] is not None for region in segment["regions"])
    assert segment["occurrence_ids"] == [], "a detector-prompted mask has no hosted occurrence"
    assert read.withheld_segment_count == 0


def test_a_changed_region_makes_the_segments_stale(repository, tmp_path):
    store, captures, _points, scene_id = _published(repository, tmp_path, "lift-region")
    _segment_members(repository, store, captures, SceneSegmenter())
    assert lift.publish_scene_segments(repository, store, scene_id)["action"] == "written"
    assert _read(repository, store, scene_id).state == "available"

    # A new checkpoint re-segments one photograph: its newest mask artifact is no longer the one
    # these segments were lifted from, and every vote could have moved.
    _segment_members(repository, store, captures[:1], SceneSegmenter(revision="1" * 40))
    read = _read(repository, store, scene_id)
    assert read.state == "stale"
    assert read.segments == ()
    assert read.stale_inputs == (f"object_masks:{captures[0]}",)


def test_a_purged_point_map_withholds_the_segments_it_rests_on(repository, tmp_path):
    store, captures, point_artifacts, scene_id = _published(repository, tmp_path, "lift-purge")
    _segment_members(repository, store, captures, SceneSegmenter())
    assert lift.publish_scene_segments(repository, store, scene_id)["action"] == "written"
    repository.connection.execute(
        "update artifact set purged_at = now() where workspace_id=%s and artifact_id=%s",
        (repository.workspace_id, point_artifacts[1]),
    )
    read = _read(repository, store, scene_id)
    assert read.state == "available"
    assert read.segments == ()
    assert read.withheld_segment_count == 1


def test_only_a_reviewed_and_shown_person_is_lifted_and_a_withdrawal_takes_them_back(
    repository, tmp_path
):
    store, captures, _points, scene_id = _published(repository, tmp_path, "lift-person")
    _segment_members(repository, store, captures, SceneSegmenter())
    shown = create_subject(repository, actor=ACTOR)
    record_consent(
        repository, subject_id=shown, actor=ACTOR, consent_scope="likeness", decision="granted"
    )
    _add_person(repository, captures, shown)
    unconsented = create_subject(repository, actor=ACTOR)
    _add_person(repository, captures, unconsented, area=((-2.0, 2.0), (-4.0, 4.0)))
    _add_person(repository, captures, None, area=((24.0, 27.0), (-4.0, 4.0)))

    written = lift.publish_scene_segments(repository, store, scene_id)
    assert written["action"] == "written", written
    assert written["person_regions"] == 3, "only the shown subject's three regions are offered"
    read = _read(repository, store, scene_id)
    people = [segment for segment in read.segments if segment["kind"] == "person"]
    [person] = people
    assert person["subject_id"] == str(shown)
    assert person["label"] is None and person["display_name"] is None
    assert person["votes"]["views"] == 3
    assert {region["kind"] for region in person["regions"]} == {"person_region"}
    assert [segment["label"] for segment in read.segments if segment["kind"] == "object"] == [
        "sign"
    ]

    record_consent(
        repository, subject_id=shown, actor=ACTOR, consent_scope="likeness", decision="withdrawn"
    )
    after = _read(repository, store, scene_id)
    assert [segment["kind"] for segment in after.segments] == ["object"]
    assert after.withheld_segment_count == 1


def test_segments_bound_to_another_build_are_stale_not_served(repository, tmp_path):
    store, captures, _points, scene_id = _published(repository, tmp_path, "lift-build")
    _segment_members(repository, store, captures, SceneSegmenter())
    written = lift.publish_scene_segments(repository, store, scene_id)
    envelope = json.loads(store.get(BlobId.from_hex(written["segments_sha256"])))
    envelope["segments"]["bindings"]["pose_receipt_sha256"] = "f" * 64
    payload = envelope["segments"]
    envelope["payload_sha256"] = lift._digest(lift.canonical_json(payload))
    tampered = store.put_bytes(lift.canonical_json(envelope) + b"\n")
    repository.connection.execute(
        "update artifact set content_sha256=%s, storage_key=%s, byte_size=%s "
        "where workspace_id=%s and artifact_id=%s",
        (
            tampered.blob_id.digest,
            store.key_for(tampered.blob_id),
            tampered.byte_size,
            repository.workspace_id,
            uuid.UUID(written["artifact_id"]),
        ),
    )
    read = _read(repository, store, scene_id)
    assert read.state == "stale" and read.stale_inputs == ("scene_build",)


def test_a_scene_nobody_has_is_not_found_rather_than_empty(repository, tmp_path):
    store, _captures, _points, _scene_id = _published(repository, tmp_path, "lift-none")
    assert _read(repository, store, uuid.uuid4()) is None


def test_the_kinds_and_profiles_are_spelled_the_same_in_every_place():
    assert (
        reader.SCENE_SEGMENTS_KIND
        == lift.SCENE_SEGMENTS_KIND
        == (STAGES["scene_segments"].output_kind)
    )
    assert (
        reader.OBJECT_MASK_KIND
        == segmentation_stage.OBJECT_MASK_KIND
        == (STAGES["segmentation"].output_kind)
    )
    assert reader._SEGMENTS_PROFILE == lift.SCENE_SEGMENTS_PROFILE == PARAMS["profile"]
    assert reader._SEGMENTS_ENVELOPE == lift.SCENE_SEGMENTS_ENVELOPE == PARAMS["envelope"]


# -- the route -----------------------------------------------------------------------------------

_OWNER = "owner-token-that-is-long-enough-to-be-accepted"
_STRANGER = "stranger-token-that-is-long-enough-to-pass"


@contextlib.contextmanager
def _client(repository, store, spine_schema, monkeypatch):
    from exulanica.api.app import create_app
    from exulanica.api.authorisation import load_token_directory
    from exulanica.api.services import Services
    from fastapi.testclient import TestClient

    from tests_support_api import scratch_database

    _psycopg, scratch = spine_schema
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                _OWNER: {"workspace_id": str(repository.workspace_id), "actor": str(ACTOR)},
                _STRANGER: {"workspace_id": str(uuid.uuid4()), "actor": str(uuid.uuid4())},
            }
        ),
    )
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    clear_placement_memo()
    clear_scene_inputs_memo()
    with TestClient(create_app(services, verify=False)) as client:
        yield client


@pytest.fixture
def segments_client(repository, tmp_path, spine_schema, monkeypatch):
    """A published synthetic scene with lifted segments, and an app over the same schema."""
    store, captures, _points, scene_id = _published(repository, tmp_path, "lift-route")
    _segment_members(repository, store, captures, SceneSegmenter())
    assert lift.publish_scene_segments(repository, store, scene_id)["action"] == "written"
    with _client(repository, store, spine_schema, monkeypatch) as client:
        yield client, scene_id


@pytest.fixture
def person_segments_client(repository, tmp_path, spine_schema, monkeypatch):
    """A scene with a reviewed, shown person and hosted-prompted masks, lifted and served.

    This is the scene the published fixture in
    ``web/packages/graph-client/test/fixtures/scene-segments.json`` was generated from.
    """
    store, captures, subject, scene_id = _published_with_person(repository, tmp_path, "person")
    _segment_members(repository, store, captures, SceneSegmenter(), vision=MarkerVisionModel())
    assert lift.publish_scene_segments(repository, store, scene_id)["action"] == "written"
    with _client(repository, store, spine_schema, monkeypatch) as client:
        yield client, scene_id, subject


def _get(client, token, path):
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


def test_the_route_withholds_segments_exactly_when_the_graph_withholds_geometry(segments_client):
    """The same asset-read policy as geometry, checked against the graph's own answer rather
    than against a restatement of the policy: where the graph draws this scene's point maps the
    segments are served, and where it withholds them the segments are withheld too."""
    client, scene_id = segments_client
    response = _get(client, _OWNER, f"/scene-segments/{scene_id}")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    graph = _get(client, _OWNER, "/graph").json()
    [scene] = [row for row in graph["reconstruction_scenes"] if row["scene_id"] == str(scene_id)]
    if scene["placement_state"] == "unavailable":
        assert body["state"] == "unavailable"
        assert body["segments"] == [] and body["withheld_segment_count"] == 1
        assert body["reason"] == scene["display_reasons"][0]
    else:
        assert body["state"] == "available", body
        [segment] = body["segments"]
        assert segment["label"] == "sign" and segment["kind"] == "object"
        assert body["grid"]["frame"] == "scene"
    assert body["schema_version"] == 1
    assert body["pose_receipt_sha256"] == scene["pose_receipt_sha256"]


def test_the_route_is_not_an_existence_oracle(segments_client):
    client, scene_id = segments_client
    assert _get(client, _STRANGER, f"/scene-segments/{scene_id}").status_code == 404
    assert _get(client, _OWNER, f"/scene-segments/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/scene-segments/{scene_id}").status_code == 401


def test_a_scene_the_policy_denies_has_its_segments_withheld_not_served(
    segments_client, repository
):
    """The deny branch, forced: retracting the scene's rung assertion stops `scene_inputs`
    resolving, which is how the graph route withholds the scene's geometry, and the segments read
    still proves its own bindings and is withheld by the same predicate."""
    client, scene_id = segments_client
    assert _get(client, _OWNER, f"/scene-segments/{scene_id}").json()["state"] == "available"
    repository.connection.execute(
        "update assertion set status='retracted' where workspace_id=%s and assertion_id="
        "(select rung_assertion_id from reconstruction_scene_job j "
        " join reconstruction_scene s on s.workspace_id=j.workspace_id "
        " and s.current_job_id=j.job_id where s.workspace_id=%s and s.scene_id=%s)",
        (repository.workspace_id, repository.workspace_id, scene_id),
    )
    clear_scene_inputs_memo()
    body = _get(client, _OWNER, f"/scene-segments/{scene_id}").json()
    assert body["state"] == "unavailable"
    assert body["segments"] == [] and body["grid"] is None
    assert body["withheld_segment_count"] == 1
    assert body["reason"] == "Current permission or persisted geometry lineage is unavailable."


def test_a_reviewed_shown_person_is_served_beside_the_objects_through_the_route(
    person_segments_client,
):
    client, scene_id, subject = person_segments_client
    body = _get(client, _OWNER, f"/scene-segments/{scene_id}").json()
    assert body["state"] == "available", body["reason"]
    by_kind = {segment["kind"]: segment for segment in body["segments"]}
    assert set(by_kind) == {"object", "person"}
    person, sign = by_kind["person"], by_kind["object"]
    assert person["subject_id"] == str(subject)
    assert person["label"] is None and person["display_name"] is None
    assert person["occurrence_ids"] == []
    assert {region["kind"] for region in person["regions"]} == {"person_region"}
    assert all(region["span_id"] is None for region in person["regions"])
    # The marker's masks were prompted by the hosted pass, so the vision stage's own occurrences
    # of it are what the naming flow is offered.
    assert sign["label"] == "trail sign"
    assert len(sign["occurrence_ids"]) == 3
    assert all(region["span_id"] is not None for region in sign["regions"])


# -- the published fixture -----------------------------------------------------------------------
#
# `web/packages/graph-client/test/fixtures/scene-segments.json` is one complete, served
# `GET /scene-segments/{scene_id}` body, generated from the `person_segments_client` scene above.
# It is stable once published: fields may be added, and no field in it may be renamed, retyped or
# removed. These tests are what makes that a rule rather than an intention, and they are here
# rather than in `web/` because the shape is the backend's to keep.

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "web/packages/graph-client/test/fixtures/scene-segments.json"
)


def _shape(value):
    """The key and type structure of a JSON value, with list members merged."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        shapes = [_shape(item) for item in value]
        merged = {}
        for shape in shapes:
            if isinstance(shape, dict):
                merged.update(shape)
        return [merged] if merged else sorted({json.dumps(shape) for shape in shapes})
    return "null" if value is None else type(value).__name__


def test_the_published_fixture_is_a_body_the_route_serves():
    from exulanica.api.routes.scene_segments import (
        SceneSegmentsView,
        SceneSegmentView,
        SegmentRegionView,
    )

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    SceneSegmentsView.model_validate(fixture)
    assert set(fixture) == set(SceneSegmentsView.model_fields)
    assert fixture["state"] == "available" and fixture["schema_version"] == 1
    assert {segment["kind"] for segment in fixture["segments"]} == {"object", "person"}
    for segment in fixture["segments"]:
        assert set(segment) == set(SceneSegmentView.model_fields)
        for region in segment["regions"]:
            assert set(region) == set(SegmentRegionView.model_fields)
        # The one check editing the file to look right cannot satisfy: the id is a digest over
        # the segment's own kind, label, subject and voxels.
        identity = {
            "kind": segment["kind"],
            "label": segment["label"],
            "subject_ref": segment["subject_id"],
            "voxels": segment["voxels"],
        }
        assert segment["segment_id"] == lift._digest(lift.canonical_json(identity))[:32]
        assert segment["voxel_count"] == len(segment["voxels"])
        if segment["kind"] == "person":
            assert segment["label"] is None and segment["occurrence_ids"] == []
        else:
            assert segment["subject_id"] is None and segment["display_name"] is None


def test_a_served_body_has_exactly_the_published_fixtures_shape(person_segments_client):
    client, scene_id, _subject = person_segments_client
    body = _get(client, _OWNER, f"/scene-segments/{scene_id}").json()
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert _shape(body) == _shape(fixture)
