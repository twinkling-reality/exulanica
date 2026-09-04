"""The in-process COLMAP backend, exercised for real where the extra is installed.

Every other pose test drives ``run_colmap_pose_job`` with a fake executor, which proves the
controller's checkpointing and gate and proves nothing about COLMAP. These tests are the other
half: they run the real library through the real controller and assert that a pose job produces a
receipt. They skip where the `pose` extra is absent, which is CI, so the suite that must stay
green stays green and the claim that pose recovery runs is made only where it was executed.

The photographs are deterministic renders of the versioned procedural room in
``exulanica.evaluation.synthetic_multiview``. They are generated rather than committed, because
the repository has no consented multi-view capture and the compact scene definition reproduces
the exact source and camera manifests. These tests check wiring and COLMAP on easy input. They
are NOT evidence about photographs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from exulanica.evaluation.synthetic_multiview import generate_synthetic_multiview
from exulanica.reconstruction.pose import (
    PoseBuildManifest,
    SourceFrame,
    run_colmap_pose_job,
)

pytest.importorskip("pycolmap", reason="the pose extra is not installed")
pytest.importorskip("numpy", reason="rendering the synthetic capture needs numpy")
pytest.importorskip("PIL.Image", reason="rendering the synthetic capture needs Pillow")

from exulanica.reconstruction.pycolmap_executor import (
    PYCOLMAP_EXECUTABLE,
    PycolmapExecutor,
    pycolmap_version,
)

_VIEWS = 8


@pytest.fixture(scope="module")
def synthetic_capture(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("capture")
    return generate_synthetic_multiview(directory).image_directory


def _manifest(source: Path) -> PoseBuildManifest:
    frames = tuple(
        SourceFrame(
            capture_ref=f"capture-{index}",
            filename=path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            capture_set="courtyard",
        )
        for index, path in enumerate(sorted(source.iterdir()))
    )
    return PoseBuildManifest(
        scene_ref="glasshouse-courtyard",
        code_revision="a" * 40,
        # The version the backend reports rather than a string somebody typed, which is the gap
        # `docs/colmap-pose-jobs.md` claims is closed and is not for the subprocess backend.
        colmap_version=pycolmap_version(),
        execution_image="registry.example/exulanica-colmap@sha256:" + "b" * 64,
        frames=frames,
        min_registered_fraction=0.75,
        max_mean_reprojection_error_px=2.0,
        min_camera_translation_units=0.1,
    )


def test_the_in_process_backend_recovers_poses_through_the_unmodified_controller(
    synthetic_capture: Path, tmp_path: Path
):
    """The controller is what ships; this asserts it runs COLMAP rather than a fake.

    Everything checked here is the controller's own output: the receipt it writes, the quality it
    parses out of COLMAP's text export, and the checkpoint that would let a preempted job resume.
    If this passes, the pose path has a backend on this machine.
    """
    result = run_colmap_pose_job(
        _manifest(synthetic_capture),
        source_dir=synthetic_capture,
        jobs_root=tmp_path / "jobs",
        executable=PYCOLMAP_EXECUTABLE,
        executor=PycolmapExecutor(),
    )

    assert result.status == "completed", result.failure_reason
    assert result.quality is not None
    quality = result.quality
    assert quality.source_count == _VIEWS
    assert len(quality.registered_images) == _VIEWS, "every synthetic view should register"
    assert quality.registered_fraction == 1.0
    assert quality.mean_reprojection_error_px is not None
    assert quality.mean_reprojection_error_px < 2.0
    assert quality.camera_translation_extent_units > 0.1
    assert quality.accepted is True
    assert quality.reasons == ()
    # COLMAP is scale ambiguous and the manifest carried no measured scale, so the frame is not
    # metric however well it registered. This is the line rung 2 and rung 1 both wait on.
    assert quality.shared_metric_frame is False

    receipt = result.job_directory / "receipt.json"
    assert receipt.is_file()
    checkpoint = result.job_directory / "checkpoint.json"
    assert checkpoint.is_file()


def test_a_completed_job_is_reused_rather_than_recomputed(
    synthetic_capture: Path, tmp_path: Path
):
    """The expensive half of the controller's contract, against a real backend.

    A second call must return the stored receipt without invoking COLMAP again. The executor here
    fails on any call at all, so a single command would turn the reuse into a failure.
    """
    manifest = _manifest(synthetic_capture)
    jobs_root = tmp_path / "jobs"
    first = run_colmap_pose_job(
        manifest,
        source_dir=synthetic_capture,
        jobs_root=jobs_root,
        executable=PYCOLMAP_EXECUTABLE,
        executor=PycolmapExecutor(),
    )
    assert first.status == "completed"

    def refuse(command: tuple[str, ...], cwd: Path):
        raise AssertionError(f"a reused job must not run {command[1]!r}")

    second = run_colmap_pose_job(
        manifest,
        source_dir=synthetic_capture,
        jobs_root=jobs_root,
        executable=PYCOLMAP_EXECUTABLE,
        executor=refuse,
    )
    assert second.reused is True
    assert second.status == "completed"
    assert second.quality is not None
    assert second.quality.registered_images == first.quality.registered_images


def test_an_unknown_stage_is_a_failed_result_and_not_a_raised_exception():
    """The controller reads a return code and publishes rung 3 with a reason.

    An executor that raised instead would skip the checkpoint write that records which stage
    failed, so the job would lose the one fact worth keeping about its failure.
    """
    outcome = PycolmapExecutor()(("pycolmap", "point_triangulator"), Path.cwd())
    assert outcome.returncode == 1
    assert "point_triangulator" in outcome.stderr
