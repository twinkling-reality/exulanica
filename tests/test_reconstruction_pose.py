from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exulanica.reconstruction.pose import (
    CommandResult,
    PoseBuildManifest,
    SourceFrame,
    run_colmap_pose_job,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(source: Path, *, metric: bool = False) -> PoseBuildManifest:
    frames = tuple(
        SourceFrame(
            capture_ref=f"capture-{index}",
            filename=path.name,
            sha256=_digest(path.read_bytes()),
            capture_set="visit-a" if index < 2 else "visit-b",
        )
        for index, path in enumerate(sorted(source.iterdir()))
    )
    return PoseBuildManifest(
        scene_ref="room-1",
        code_revision="a" * 40,
        colmap_version="4.0",
        execution_image="registry.example/exulanica-colmap@sha256:" + "b" * 64,
        frames=frames,
        min_registered_fraction=0.75,
        max_mean_reprojection_error_px=1.0,
        min_camera_translation_units=0.5,
        metric_scale_metres_per_unit=0.25 if metric else None,
        metric_scale_method="reviewed calibration target" if metric else None,
    )


def _sources(root: Path) -> Path:
    root.mkdir()
    for index in range(4):
        (root / f"image-{index}.jpg").write_bytes(f"source-{index}".encode())
    return root


class FakeColmap:
    def __init__(self, *, fail_stage: str | None = None, omit_visit_b: bool = False) -> None:
        self.calls: list[str] = []
        self.fail_stage = fail_stage
        self.omit_visit_b = omit_visit_b

    def __call__(self, command: tuple[str, ...], cwd: Path) -> CommandResult:
        stage = command[1]
        self.calls.append(stage)
        if stage == self.fail_stage:
            return CommandResult(9, "", "measured failure", 3.0)
        (cwd / "database.db").write_bytes(stage.encode())
        if stage == "mapper":
            model = cwd / "sparse" / "0"
            model.mkdir(parents=True)
            names = ["image-0.jpg", "image-1.jpg", "image-2.jpg", "image-3.jpg"]
            if self.omit_visit_b:
                names = names[:2]
            lines: list[str] = []
            for index, name in enumerate(names, 1):
                lines.extend(
                    [
                        f"{index} 1 0 0 0 {-index} 0 0 1 {name}",
                        "0 0 -1",
                    ]
                )
            (model / "images.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            (model / "points3D.txt").write_text(
                "1 0 0 0 255 255 255 0.4 1 0 2 0\n2 1 0 0 255 255 255 0.6 2 0 3 0\n",
                encoding="utf-8",
            )
        return CommandResult(0, "ok", "", 4.0)


def test_pose_job_checkpoints_and_reuses_the_exact_completed_manifest(tmp_path):
    source = _sources(tmp_path / "sources")
    fake = FakeColmap()
    manifest = _manifest(source, metric=True)
    first = run_colmap_pose_job(
        manifest, source_dir=source, jobs_root=tmp_path / "jobs", executor=fake
    )
    second = run_colmap_pose_job(
        manifest, source_dir=source, jobs_root=tmp_path / "jobs", executor=fake
    )
    assert first.status == "completed" and first.reused is False
    assert second.status == "completed" and second.reused is True
    assert fake.calls == ["feature_extractor", "exhaustive_matcher", "mapper"]
    assert first.quality is not None and first.quality.accepted is True
    assert first.quality.jointly_coregistered is True
    assert first.quality.shared_metric_frame is True
    assert [camera.image_name for camera in first.quality.cameras] == [
        "image-0.jpg",
        "image-1.jpg",
        "image-2.jpg",
        "image-3.jpg",
    ]
    assert first.quality.cameras[3].camera_centre_xyz == (4.0, 0.0, 0.0)
    receipt = json.loads((first.job_directory / "receipt.json").read_bytes())
    assert receipt["profile"] == "exulanica.colmap-pose-receipt/v2"
    assert receipt["manifest"] == manifest.as_payload()


def test_joint_geometry_without_measured_scale_never_becomes_a_shared_metric_frame(tmp_path):
    source = _sources(tmp_path / "sources")
    result = run_colmap_pose_job(
        _manifest(source),
        source_dir=source,
        jobs_root=tmp_path / "jobs",
        executor=FakeColmap(),
    )
    assert result.quality is not None
    assert result.quality.jointly_coregistered is True
    assert result.quality.shared_metric_frame is False
    assert "no measured metric scale" in " ".join(result.quality.reasons)


def test_disconnected_capture_sets_fall_back_without_semantic_promotion(tmp_path):
    source = _sources(tmp_path / "sources")
    result = run_colmap_pose_job(
        _manifest(source, metric=True),
        source_dir=source,
        jobs_root=tmp_path / "jobs",
        executor=FakeColmap(omit_visit_b=True),
    )
    assert result.quality is not None
    assert result.quality.accepted is False
    assert result.quality.fallback_rung == 3
    assert result.quality.jointly_coregistered is False
    assert result.quality.shared_metric_frame is False


def test_a_failed_stage_is_checkpointed_and_resumed_without_repeating_completed_work(tmp_path):
    source = _sources(tmp_path / "sources")
    manifest = _manifest(source)
    failing = FakeColmap(fail_stage="exhaustive_matcher")
    failed = run_colmap_pose_job(
        manifest, source_dir=source, jobs_root=tmp_path / "jobs", executor=failing
    )
    assert failed.status == "failed"
    assert failing.calls == ["feature_extractor", "exhaustive_matcher"]

    recovered = FakeColmap()
    result = run_colmap_pose_job(
        manifest, source_dir=source, jobs_root=tmp_path / "jobs", executor=recovered
    )
    assert result.status == "completed"
    assert recovered.calls == ["exhaustive_matcher", "mapper"]


def test_source_bytes_must_exactly_match_the_manifest(tmp_path):
    source = _sources(tmp_path / "sources")
    manifest = _manifest(source)
    (source / "image-0.jpg").write_bytes(b"changed")
    try:
        run_colmap_pose_job(
            manifest,
            source_dir=source,
            jobs_root=tmp_path / "jobs",
            executor=FakeColmap(),
        )
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("changed private source bytes were accepted")


def test_unmeasured_thresholds_remain_none_and_block_acceptance(tmp_path):
    source = _sources(tmp_path / "sources")
    measured = _manifest(source)
    manifest = PoseBuildManifest(
        scene_ref=measured.scene_ref,
        code_revision=measured.code_revision,
        colmap_version=measured.colmap_version,
        execution_image=measured.execution_image,
        frames=measured.frames,
        min_registered_fraction=None,
        max_mean_reprojection_error_px=None,
        min_camera_translation_units=None,
    )
    result = run_colmap_pose_job(
        manifest, source_dir=source, jobs_root=tmp_path / "jobs", executor=FakeColmap()
    )
    assert result.quality is not None
    assert result.quality.accepted is False
    assert result.quality.reasons == (
        "minimum registered-image fraction is unmeasured",
        "maximum mean reprojection error is unmeasured",
        "minimum recovered camera translation is unmeasured",
        "joint reconstruction has no measured metric scale",
    )
    assert manifest.as_payload()["quality_thresholds"] == {
        "min_registered_fraction": None,
        "max_mean_reprojection_error_px": None,
        "min_camera_translation_units": None,
    }


def test_a_deletion_during_an_executor_call_cancels_before_the_next_stage(tmp_path):
    source = _sources(tmp_path / "sources")
    fake = FakeColmap()

    result = run_colmap_pose_job(
        _manifest(source),
        source_dir=source,
        jobs_root=tmp_path / "jobs",
        executor=fake,
        cancellation_check=lambda: fake.calls == ["feature_extractor"],
    )

    assert result.status == "cancelled"
    assert result.failed_stage == "feature_extractor"
    assert fake.calls == ["feature_extractor"]
    assert not (result.job_directory / "receipt.json").exists()


def test_pose_quality_retains_real_sparse_correspondences_and_camera_dimensions(tmp_path):
    from exulanica.reconstruction.pose import _alignment_observations, _images

    model = tmp_path / "model"
    model.mkdir()
    (model / "cameras.txt").write_text("1 PINHOLE 320 240 200 200 160 120\n")
    (model / "images.txt").write_text("1 1 0 0 0 -2 0 0 1 a.jpg\n160 120 7\n")
    (model / "points3D.txt").write_text("7 2 0 8 120 130 140 0.25 1 0 2 3\n")
    camera = _alignment_observations(model, _images(model / "images.txt"))["a.jpg"]
    assert camera.image_size == (320, 240)
    assert camera.camera_model == "PINHOLE"
    assert camera.camera_parameters == (200, 200, 160, 120)
    assert camera.as_payload()["calibration"] == {
        "model": "PINHOLE",
        "parameters": [200, 200, 160, 120],
    }
    assert camera.sparse_observations == ((7, 160, 120, 2, 0, 8, 0.25, 2),)
    assert camera.as_payload()["sparse_observations"] == [[7, 160, 120, 2, 0, 8, 0.25, 2]]


def test_pose_receipt_drops_points_one_image_observes_twice(tmp_path):
    """Real COLMAP models can merge tracks so one image sees a point at two keypoints."""
    from exulanica.reconstruction.pose import _alignment_observations, _images

    model = tmp_path / "model"
    model.mkdir()
    (model / "cameras.txt").write_text("1 PINHOLE 320 240 200 200 160 120\n")
    (model / "images.txt").write_text("1 1 0 0 0 -2 0 0 1 a.jpg\n160 120 7 161 121 7 40 50 8\n")
    (model / "points3D.txt").write_text(
        "7 2 0 8 120 130 140 0.25 1 0 1 1 2 3\n8 1 0 8 120 130 140 0.5 1 2 2 3\n"
    )
    camera = _alignment_observations(model, _images(model / "images.txt"))["a.jpg"]
    assert camera.sparse_observations == ((8, 40, 50, 1, 0, 8, 0.5, 2),)
    assert len({item[0] for item in camera.sparse_observations}) == len(camera.sparse_observations)
