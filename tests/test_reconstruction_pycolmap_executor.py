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
import json
import sqlite3
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

from exulanica.reconstruction import pycolmap_executor as executor_module
from exulanica.reconstruction.pycolmap_executor import (
    PYCOLMAP_EXECUTABLE,
    PycolmapExecutor,
    default_extraction_threads,
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


def test_a_completed_job_is_reused_rather_than_recomputed(synthetic_capture: Path, tmp_path: Path):
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

    Asserted for both process placements and asserted to be the SAME strings, because the failure
    text is what the checkpoint hashes: the stage process runs the same ``run_stage_here`` the
    in-process path does, so an error message that differed would mean the two had drifted apart.
    """
    unknown = ("pycolmap", "point_triangulator")
    isolated = PycolmapExecutor(stage_isolation=True)(unknown, Path.cwd())
    here = PycolmapExecutor(stage_isolation=False)(unknown, Path.cwd())
    assert isolated.returncode == here.returncode == 1
    assert "point_triangulator" in here.stderr
    assert (isolated.stdout, isolated.stderr) == (here.stdout, here.stderr)


def _extracted_features(job_directory: Path) -> dict[str, tuple]:
    """Every image's keypoint and descriptor blob from the COLMAP database, by image name.

    This, and not the sparse model, is what a comparison across process placements can assert.
    MEASURED 2026-09-09 on forty 12 megapixel photographs and recorded in
    `docs/reconstruction-throughput.md`: two runs of the SAME executor on the SAME inputs produce
    different `matches`, different `two_view_geometries` and a different sparse model, because
    COLMAP's matcher and incremental mapper are not bit-reproducible run to run even with the
    mapper's `random_seed` fixed. Feature extraction is, and feature extraction is what the memory
    bound touches. A test that compared model bytes would be asserting a property the pipeline has
    never had, and would fail at random rather than when something broke.
    """
    database = job_directory / "database.db"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        names = dict(connection.execute("select image_id, name from images"))
        found = {}
        for image_id, name in names.items():
            blobs = []
            for table in ("keypoints", "descriptors"):
                row = connection.execute(
                    f"select rows, cols, data from {table} where image_id=?", (image_id,)
                ).fetchone()
                blobs.append(
                    None if row is None else (row[0], row[1], hashlib.sha256(row[2]).hexdigest())
                )
            found[name] = tuple(blobs)
        return found
    finally:
        connection.close()


def _placeless(command: list[str], job_directory: Path) -> list[str]:
    """The recorded argument vector with this run's own job directory taken out of it.

    Two runs need two directories, so the absolute paths in the vector differ by construction.
    Everything else in it must not.
    """
    return [token.replace(str(job_directory), "<job>") for token in command]


def test_the_stage_process_records_the_same_result_and_checkpoint_as_running_in_process(
    synthetic_capture: Path, tmp_path: Path
):
    """The bound may not move anything the controller writes down.

    Running each stage in its own process is only admissible if the pose job cannot tell. What the
    job keeps is the checkpoint, so this compares it field by field across the two placements: the
    same stages, the same status and return code, the same stdout and stderr digests, and the same
    argument vector once each run's own directory is removed. `duration_ms` is wall clock and is
    expected to differ; it is asserted to be present and numeric rather than equal, because a test
    that demanded equality there would be asserting that two runs took the same time.

    Then the output the bound actually touches, byte for byte: every image's keypoint and
    descriptor blob. Not the sparse model, which `docs/reconstruction-throughput.md` measures as
    not bit-reproducible between two runs of the same executor; see `_extracted_features`. The
    model is compared on the facts the quality gate reads instead, which are stable.
    """
    manifest = _manifest(synthetic_capture)
    results = {}
    for name, isolation in (("in_process", False), ("child_process", True)):
        results[name] = run_colmap_pose_job(
            manifest,
            source_dir=synthetic_capture,
            jobs_root=tmp_path / name,
            executable=PYCOLMAP_EXECUTABLE,
            # Pinned rather than derived so the comparison is between process placements and
            # nothing else, on a machine of any size.
            executor=PycolmapExecutor(stage_isolation=isolation, extraction_threads=2),
        )
        assert results[name].status == "completed", results[name].failure_reason

    here, isolated = results["in_process"], results["child_process"]
    checkpoints = {
        name: json.loads((result.job_directory / "checkpoint.json").read_text(encoding="utf-8"))
        for name, result in results.items()
    }
    left, right = checkpoints["in_process"]["stages"], checkpoints["child_process"]["stages"]
    assert set(left) == set(right), "the same stages ran, under the same names"
    for stage, recorded in left.items():
        other = right[stage]
        assert set(recorded) == set(other), stage
        for field in ("status", "returncode", "stdout_sha256", "stderr_sha256"):
            assert recorded[field] == other[field], (stage, field)
        assert isinstance(recorded["duration_ms"], float)
        assert isinstance(other["duration_ms"], float)
        assert _placeless(recorded["command"], here.job_directory) == _placeless(
            other["command"], isolated.job_directory
        )

    left = _extracted_features(here.job_directory)
    right = _extracted_features(isolated.job_directory)
    assert left == right, "the same photographs must yield the same keypoints and descriptors"
    assert len(left) == _VIEWS
    assert here.quality is not None and isolated.quality is not None
    assert here.quality.registered_images == isolated.quality.registered_images
    assert here.quality.source_count == isolated.quality.source_count
    assert here.quality.accepted == isolated.quality.accepted
    assert here.manifest_digest == isolated.manifest_digest


def test_a_stage_process_that_dies_without_a_result_is_a_failed_stage_not_a_lost_worker(
    tmp_path: Path, monkeypatch
):
    """The failure mode process isolation introduces, and the one it removes.

    In-process, a stage killed for memory took the whole worker with it and the checkpoint never
    recorded which stage died: that is what happened on 2026-09-08. Here the child dies and the
    parent survives to report a failed `CommandResult`, which the controller checkpoints and turns
    into a rung 3 fallback with a reason. The reason has to name the stage, or the report is worse
    than the crash it replaced.
    """
    (tmp_path / "dying_stage.py").write_text(
        "import os, sys\nos._exit(9)\n", encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setattr(executor_module, "PYCOLMAP_STAGE_MODULE", "dying_stage")

    outcome = PycolmapExecutor(stage_isolation=True)(
        ("pycolmap", "feature_extractor", "--database_path", "d.db"), tmp_path
    )

    assert outcome.returncode == 1
    assert outcome.stdout == ""
    assert "feature_extractor" in outcome.stderr
    assert "exited 9" in outcome.stderr
    assert outcome.duration_ms > 0


def test_the_extraction_thread_cap_is_derived_from_the_machine_and_never_zero():
    """The cap is a measurement about this machine, not a constant somebody liked.

    MEASURED 2026-09-09: twelve threads on 4272x2848 photographs reached a 23.9 GB footprint on an
    18 GB machine and stalled it in swap. The derived cap must stay inside the core count, because
    more threads than cores buys nothing, and must never fall to zero, because a zero would refuse
    to extract at all on a machine that reported very little memory.
    """
    import os

    threads = default_extraction_threads()
    assert 1 <= threads <= (os.cpu_count() or 1)
    assert PycolmapExecutor(extraction_threads=1)._extraction_threads == 1
    with pytest.raises(ValueError):
        PycolmapExecutor(extraction_threads=0)


def test_importing_pycolmap_leaves_the_process_termination_handling_in_python():
    """glog's failure handler claimed SIGTERM and killed a worker mid-shutdown (2026-09-05)."""
    import subprocess
    import sys

    program = (
        "import os, signal, sys\n"
        "seen = []\n"
        "signal.signal(signal.SIGTERM, lambda *_: seen.append('python'))\n"
        "from exulanica.reconstruction.pycolmap_executor import _pycolmap\n"
        "_pycolmap()\n"
        "os.kill(os.getpid(), signal.SIGTERM)\n"
        "signal.sigtimedwait([signal.SIGTERM], 0) if False else None\n"
        "import time; time.sleep(0.2)\n"
        "sys.exit(0 if seen == ['python'] else 3)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=False, timeout=120
    )
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr[-800:])
