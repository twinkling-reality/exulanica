"""COLMAP in this process, so pose recovery runs where the photographs already are.

``pose.py`` drives COLMAP through a ``CommandExecutor`` seam, and its default shells out to a
``colmap`` binary. That binary is not installed on a developer machine and is not in the
container image, so the pose job has never run: it is a controller with no backend, and
``docs/colmap-pose-jobs.md`` records exactly that. This module is the backend. It recognises the
four command shapes ``pose.py`` emits and performs each one through ``pycolmap`` in process,
returning the same ``CommandResult`` the subprocess executor returns, so the checkpointing, the
lock, the manifest digest, the receipt and the quality gate above it are unchanged and untested
code paths do not multiply.

**Why in process rather than a bundled binary.** ``pycolmap`` publishes a macOS arm64 wheel and
needs no CUDA, so the same code recovers poses on the laptop that holds the library and on the
Linux worker. MEASURED 2026-09-02 on an Apple M3 Pro, pycolmap 4.2.0, CPU only, on eight
1024x768 renders: feature extraction 1.4 s, exhaustive matching 0.4 s, incremental mapping 1.8 s,
all eight images registered at 0.44 px mean reprojection error. The full table, and the caveat
that those inputs were renders of a monocular point map rather than photographs, is in
``docs/reconstruction-findings.md`` section 3.

**Two behaviours are set here rather than left to the defaults, and both are recorded because
they change what the job can produce.**

``random_seed`` is fixed. COLMAP's mapper seeds itself from the clock by default, so two runs of
one manifest produce different point counts, and the roadmap's Phase 3B gate asks for a report
reproducible from the same manifest. A fixed seed is necessary for that and is not sufficient:
RANSAC threading still admits variation, and how much has not been measured.

``ignore_two_view_tracks`` is left at its default, which is to discard every track a two-image
model would produce. MEASURED: with the default, two images never register at all, whatever the
baseline, because the initial pair is accepted and then dropped for having no points. Turning it
off makes pairs register, and it is deliberately not turned off here: a two-image model is the
case where a pose is least constrained, and the honest place to relax it is a manifest field
somebody chose, not a default nobody saw.

**The import is lazy, and on macOS it must stay that way for a second reason.** ``pycolmap`` is an
optional extra and CI does not install it, so a module-scope import would take the whole suite
down in the one environment that has to stay green. But MEASURED 2026-09-03 on this machine, with
pycolmap 4.2.0 and torch 2.14.0 both installed: **importing both into one process aborts**, in
either order, with ``OMP: Error #15: Initializing libomp.dylib, but found libomp.dylib already
initialized`` followed by SIGABRT. Each wheel carries its own OpenMP runtime. The documented
escape, ``KMP_DUPLICATE_LIB_OK=TRUE``, does let both load, and OpenMP's own message says it "may
cause crashes or silently produce incorrect results", so it is not set here and should not be set
by a caller: a silently wrong pose is worse than a refused one.

The consequence is architectural rather than cosmetic. **Depth and pose cannot share a process on
macOS.** They do not need to: they are separate stages over separate inputs, the pose job already
owns a manifest and a job directory, and the barrel does not import the depth model, so
``from exulanica.reconstruction import run_colmap_pose_job`` pulls no torch. A caller that wants
both on one machine runs them as two processes. On Linux the two wheels have not been tested
together here, and nothing should assume they coexist until they have been.
"""

from __future__ import annotations

import io
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from exulanica.reconstruction.pose import CommandResult

__all__ = ["PYCOLMAP_EXECUTABLE", "PycolmapExecutor", "pycolmap_version"]

#: What to pass as ``run_colmap_pose_job(executable=...)`` when this executor is used. It is
#: never spawned; it travels into the checkpoint's recorded argument vector, where it says which
#: backend produced the stage rather than naming a binary that was never run.
PYCOLMAP_EXECUTABLE = "pycolmap"

#: UNVALIDATED DEFAULT. Fixed so one manifest reproduces, rather than chosen by measurement of
#: what it does to registration quality. See the module docstring.
DEFAULT_RANDOM_SEED = 0


def pycolmap_version() -> str:
    """The exact version, for the manifest field the receipt is keyed by.

    ``PoseBuildManifest.colmap_version`` is required to be non-empty and is never checked against
    the thing that ran, which ``docs/colmap-pose-jobs.md`` overstates as pinning an exact version.
    A caller that builds its manifest from this function closes that gap for the in-process
    backend, because the string then comes from the library that is about to do the work.
    """
    return f"pycolmap {_pycolmap().__version__}"


def _pycolmap() -> Any:
    # Importing pycolmap installs glog's failure signal handler, and glog claims SIGTERM along with
    # the crash signals: the process prints a native stack trace and dies. MEASURED 2026-09-05 on
    # the first real run: a scene worker asked to stop died that way before it could request its
    # trainer's shutdown or confirm the container's cleanup, leaving the trainer running. The
    # process's own termination handling is therefore restored once the import has happened.
    import signal
    import threading

    numbers = (signal.SIGINT, signal.SIGTERM)
    preserved = {number: signal.getsignal(number) for number in numbers}
    try:
        import pycolmap
    except ModuleNotFoundError as error:  # pragma: no cover - the extra is absent in CI
        raise RuntimeError(
            "pycolmap is not installed. It is the 'pose' extra: "
            "uv sync --extra pose. Without it, pose recovery has no backend."
        ) from error
    # Python's signal module still reports the old handler after the import because glog replaced
    # the disposition beneath it, so the restore is unconditional rather than change-detected.
    if threading.current_thread() is threading.main_thread():
        for number, handler in preserved.items():
            if handler is not None:
                signal.signal(number, handler)
    return pycolmap


def _flags(command: tuple[str, ...]) -> dict[str, str]:
    """The ``--key value`` pairs of a COLMAP argument vector, by name without the dashes."""
    values: dict[str, str] = {}
    index = 0
    while index < len(command):
        token = command[index]
        if token.startswith("--") and index + 1 < len(command):
            values[token[2:]] = command[index + 1]
            index += 2
        else:
            index += 1
    return values


class PycolmapExecutor:
    """Runs ``pose.py``'s COLMAP commands through the pycolmap library.

    Stateless between calls except for the options it was constructed with, because the
    controller's checkpoint is the only state that may survive a stage: an executor that
    remembered a database handle would be a second place a resumed job could disagree with its
    own receipt.
    """

    def __init__(
        self,
        *,
        random_seed: int = DEFAULT_RANDOM_SEED,
        camera_model: str = "SIMPLE_RADIAL",
    ) -> None:
        self._random_seed = random_seed
        self._camera_model = camera_model

    def __call__(self, command: tuple[str, ...], cwd: Path) -> CommandResult:
        started = time.monotonic_ns()
        out, err = io.StringIO(), io.StringIO()
        returncode = 0
        try:
            # COLMAP's own logging goes to the process's streams. Capturing it keeps the
            # checkpoint's stdout and stderr digests meaningful for an in-process run, which is
            # the only record of what a stage actually said.
            with redirect_stdout(out), redirect_stderr(err):
                self._dispatch(command, cwd)
        except Exception as error:
            # The controller reads returncode and falls back to rung 3 with the reason. Raising
            # here instead would lose the checkpoint write that records which stage failed.
            returncode = 1
            err.write(f"{type(error).__name__}: {error}\n")
        return CommandResult(
            returncode=returncode,
            stdout=out.getvalue(),
            stderr=err.getvalue(),
            duration_ms=(time.monotonic_ns() - started) / 1_000_000,
        )

    def _dispatch(self, command: tuple[str, ...], cwd: Path) -> None:
        if len(command) < 2:
            raise ValueError("a COLMAP command needs at least an executable and a stage")
        stage = command[1]
        flags = _flags(command)
        pycolmap = _pycolmap()
        handler = {
            "feature_extractor": self._feature_extractor,
            "exhaustive_matcher": self._exhaustive_matcher,
            "mapper": self._mapper,
            "model_converter": self._model_converter,
        }.get(stage)
        if handler is None:
            raise ValueError(f"no in-process equivalent for COLMAP stage {stage!r}")
        handler(pycolmap, flags, cwd)

    def _feature_extractor(self, pycolmap: Any, flags: dict[str, str], cwd: Path) -> None:
        reader = pycolmap.ImageReaderOptions()
        reader.camera_model = self._camera_model
        # `--ImageReader.single_camera 0` is what pose.py emits, and AUTO is its meaning: one
        # camera per distinct EXIF camera, which for images with no EXIF is one per image.
        single = flags.get("ImageReader.single_camera", "0") == "1"
        mode = pycolmap.CameraMode.SINGLE if single else pycolmap.CameraMode.AUTO
        pycolmap.extract_features(
            database_path=_path(flags, "database_path", cwd),
            image_path=_path(flags, "image_path", cwd),
            camera_mode=mode,
            reader_options=reader,
            device=pycolmap.Device.cpu,
        )

    def _exhaustive_matcher(self, pycolmap: Any, flags: dict[str, str], cwd: Path) -> None:
        pycolmap.match_exhaustive(
            database_path=_path(flags, "database_path", cwd),
            device=pycolmap.Device.cpu,
        )

    def _mapper(self, pycolmap: Any, flags: dict[str, str], cwd: Path) -> None:
        output = _path(flags, "output_path", cwd)
        output.mkdir(parents=True, exist_ok=True)
        options = pycolmap.IncrementalPipelineOptions()
        options.random_seed = self._random_seed
        reconstructions = pycolmap.incremental_mapping(
            database_path=_path(flags, "database_path", cwd),
            image_path=_path(flags, "image_path", cwd),
            output_path=output,
            options=options,
        )
        if not reconstructions:
            # Not an error here. The controller checks that the declared output exists and the
            # gate reports the registration shortfall, which is a more precise fact than a
            # non-zero exit would be. An empty sparse directory is a real outcome: COLMAP
            # registers nothing from two images under its own defaults.
            return

    def _model_converter(self, pycolmap: Any, flags: dict[str, str], cwd: Path) -> None:
        if flags.get("output_type", "TXT").upper() != "TXT":
            raise ValueError("only the TXT interchange the pose parser reads is supported")
        source = _path(flags, "input_path", cwd)
        destination = _path(flags, "output_path", cwd)
        destination.mkdir(parents=True, exist_ok=True)
        pycolmap.Reconstruction(source).write_text(str(destination))


def _path(flags: dict[str, str], name: str, cwd: Path) -> Path:
    value = flags.get(name)
    if not value:
        raise ValueError(f"COLMAP command is missing --{name}")
    candidate = Path(value)
    return candidate if candidate.is_absolute() else cwd / candidate
