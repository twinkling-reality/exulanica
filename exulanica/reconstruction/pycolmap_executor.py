"""COLMAP in this process, so pose recovery runs where the photographs already are.

``pose.py`` drives COLMAP through a ``CommandExecutor`` seam, and its default shells out to a
``colmap`` binary. That binary is not installed on a developer machine and is not in the container
image, so the pose job has never run: it is a controller with no backend, and
``docs/scene-reconstruction-operations.md`` section 12 records exactly that. This module is the
backend. It recognises the four command shapes ``pose.py`` emits and performs each one through
``pycolmap`` in process, returning the same ``CommandResult`` the subprocess executor returns, so
the checkpointing, the lock, the manifest digest, the receipt and the quality gate above it are
unchanged and untested code paths do not multiply.

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
RANSAC threading still admits variation, and **MEASURED 2026-09-09 it admits this much**. Two runs
of this executor over the same forty 12 megapixel photographs, same options, same seed, registered
the same forty images and produced the same keypoints and descriptors byte for byte, and then
disagreed about everything downstream: different ``matches`` blobs, a different sparse model,
44,261 points against 44,263, mean reprojection error 0.483878 px against 0.483942 px, and
recovered camera extent 7.342342 against 7.359589, a spread of 2.3 parts in a thousand. The full
table, and the same comparison across thread counts and process placements, is in
``docs/reconstruction-throughput.md``.

Two consequences follow and both are larger than this module. **A pose receipt reproduces in what
it concludes and not in its bytes**, so ``scene_pose`` remains declared deterministic without being
exactly recomputable, which is the distinction
``tests/test_exact_recomputation.py::test_the_flag_is_a_claim_about_events_not_a_proof_of_reproduction``
exists to keep. And **the recovered camera extent is the number to watch**, because
``min_camera_translation_units`` is a gate threshold: two bowl captures were refused at 8.13 and
8.96 against a 9.0 floor, and 8.96 is 0.44 per cent short of passing while the run-to-run spread
measured here is 0.23 per cent at a fixed configuration and 0.51 per cent across the configurations
compared. Those are the same order of magnitude on a different capture. That is a reason to
re-measure that refusal, not a claim about it.

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

**Feature extraction is bounded by capping its thread count, and that is the whole of the memory
fix.** ``docs/records/2026-09-08-scene-inspection.md`` records a 210 photograph run that reached
file 199 with the process footprint at about 20 GB, the machine swapping at 17.5 of 18.4 GB, and
was SIGTERMed. MEASURED 2026-09-09, reproducing it on forty of those photographs: the footprint
reaches 23.9 GB after twelve images and the run then stalls in swap. Twelve is not a coincidence,
it is ``os.cpu_count()`` on this machine, and COLMAP says so itself in its own log before it
starts:

    Your current options use the maximum number of threads on the machine to extract features.
    Extracting SIFT features on the CPU can consume a lot of RAM per thread for large images.

The growth is pycolmap's and it is per thread, not per image and not ours. It is not the
``StringIO`` redirects, which MEASURED capture zero bytes for every stage, and not a retained Python
object, because this executor holds none between calls. ``FeatureExtractionOptions`` defaults
``max_image_size`` to -1, so a 4272x2848 photograph is not downscaled, and ``first_octave`` to -1,
so it is upsampled to 8544x5696 before the pyramid is built: about 2 GB of working set per thread at
12 megapixels, times one thread per core. So ``extraction_threads`` caps the thread count against
the machine's physical memory, which leaves a 70 GiB twelve core host running all twelve threads
exactly as it does today and stops an 18 GB laptop from asking for 24 GB. It changes no output:
each image is extracted independently and the results are written by COLMAP's own writer, which
``docs/reconstruction-throughput.md`` records as byte-identical across thread counts.

**Each stage also runs in its own process, which bounds retention rather than the peak.** Say this
precisely, because it is easy to overclaim: process isolation does NOT fix the extraction peak, as
that peak is reached inside one ``extract_features`` call and a child would reach it too. What it
bounds is what a stage leaves behind for the next one, and it buys two things that matter on a
machine that has already been driven into swap once. The parent no longer imports pycolmap to run a
stage, so glog never claims its SIGTERM; and a stage killed for memory now returns a failed
``CommandResult`` the controller can checkpoint, instead of taking the worker down with it and
losing the record of which stage died.

Nothing above the command boundary changes. The child runs the same dispatch this module already
had, through the same ``run_stage_here``, so the ``returncode``, ``stdout`` and ``stderr`` that
reach ``CommandResult`` are produced by the same code and the pose controller's checkpoint,
receipt, manifest digest and quality gate see exactly what they saw before. The child inherits file
descriptors 1 and 2, so COLMAP's own glog output still goes where it went. ``stage_isolation=False``
restores the old single-process behaviour and exists for the comparison that proves the outputs did
not move, not as a supported production setting. The costs are one interpreter start and one
pycolmap import per stage, and a ``KeyboardInterrupt`` inside a stage becoming a failed result
rather than an exception raised through ``__call__``.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from exulanica.reconstruction.pose import CommandResult

__all__ = [
    "EXTRACTION_BYTES_PER_THREAD",
    "EXTRACTION_MEMORY_FRACTION",
    "PYCOLMAP_EXECUTABLE",
    "PYCOLMAP_STAGE_MODULE",
    "PycolmapExecutor",
    "default_extraction_threads",
    "pycolmap_version",
    "run_stage_here",
]

#: What to pass as ``run_colmap_pose_job(executable=...)`` when this executor is used. It is
#: never spawned; it travels into the checkpoint's recorded argument vector, where it says which
#: backend produced the stage rather than naming a binary that was never run.
PYCOLMAP_EXECUTABLE = "pycolmap"

#: UNVALIDATED DEFAULT. Fixed so one manifest reproduces, rather than chosen by measurement of
#: what it does to registration quality. See the module docstring.
DEFAULT_RANDOM_SEED = 0

#: The module spawned once per stage. Named here rather than inline so a reader of the executor can
#: see what it starts, and so the test that proves the two paths agree names the same thing.
PYCOLMAP_STAGE_MODULE = "exulanica.reconstruction.pycolmap_stage_process"

#: MEASURED 2026-09-09 on an Apple M3 Pro, pycolmap 4.2.0, CPU only, on 4272x2848 photographs from
#: the volcanic reference set: twelve extraction threads reach a 23.9 GB process footprint, or about
#: 2 GB of working set per thread. The number is a working set at 12 megapixels and it scales with
#: pixels, because `max_image_size` is -1 and `first_octave` is -1, so the pyramid is built over an
#: image upsampled to four times its area. It is not a measured ceiling for a larger photograph.
EXTRACTION_BYTES_PER_THREAD = 2 * 1024**3

#: How much of the machine feature extraction may plan to occupy. Under 1.0 because the extractor
#: is not alone: on the worker there is a Python process, a database connection and the operating
#: system, and on a developer machine there is everything else. MEASURED: at 0.5 an 18 GB machine
#: gets four threads and about 8 GB, which does not swap; twelve threads asked for 24 GB and did.
EXTRACTION_MEMORY_FRACTION = 0.5


def pycolmap_version() -> str:
    """The exact version, for the manifest field the receipt is keyed by.

    ``PoseBuildManifest.colmap_version`` is required to be non-empty and is never checked against
    the thing that ran, which ``docs/scene-reconstruction-operations.md`` section 12 records as
    overstated. A caller that builds its manifest from this function closes that gap for the
    in-process backend, because the string then comes from the library that is about to do the
    work.
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


def default_extraction_threads() -> int:
    """How many SIFT threads this machine can afford, from its own physical memory.

    Derived rather than fixed, because the right answer differs by an order of magnitude between
    the two machines this code runs on: the rented Linux worker has 70 GiB and twelve vCPUs and
    should keep using all twelve, and this laptop has 18 GB and twelve cores and must not. A fixed
    small number would slow the worker down for a problem the worker does not have, and a fixed
    large one is what stalled the laptop.

    Falls back to the core count where the machine will not say how much memory it has, which is
    the behaviour before this cap existed.
    """
    cores = os.cpu_count() or 1
    try:
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):  # pragma: no cover - platform without sysconf
        return cores
    if total <= 0:  # pragma: no cover - a machine that will not say
        return cores
    affordable = int(total * EXTRACTION_MEMORY_FRACTION) // EXTRACTION_BYTES_PER_THREAD
    return max(1, min(cores, affordable))


def run_stage_here(
    command: tuple[str, ...],
    cwd: Path,
    *,
    random_seed: int = DEFAULT_RANDOM_SEED,
    camera_model: str = "SIMPLE_RADIAL",
    extraction_threads: int | None = None,
) -> tuple[int, str, str]:
    """Run one COLMAP stage in the calling process and report ``(returncode, stdout, stderr)``.

    This is the whole of what ``PycolmapExecutor.__call__`` used to be, minus the timing, and it is
    a module function so that the stage process runs the identical code rather than a copy of it.
    The two paths therefore cannot drift: the strings the pose controller hashes into its
    checkpoint come from here whichever process ran the stage.
    """
    out, err = io.StringIO(), io.StringIO()
    returncode = 0
    try:
        # COLMAP's own logging goes to the process's file descriptors, which `redirect_stdout`
        # does not touch: it rebinds `sys.stdout`, and the library never writes through it. So
        # these buffers capture Python-level output only, the checkpoint's stream digests are the
        # digests of that, and the child process inherits the real descriptors so glog's output
        # still reaches the operator. What is captured is identical either way, which is the
        # property that matters here.
        with redirect_stdout(out), redirect_stderr(err):
            _dispatch(
                command,
                cwd,
                random_seed=random_seed,
                camera_model=camera_model,
                extraction_threads=(
                    default_extraction_threads()
                    if extraction_threads is None
                    else extraction_threads
                ),
            )
    except Exception as error:
        # The controller reads returncode and falls back to rung 3 with the reason. Raising
        # here instead would lose the checkpoint write that records which stage failed.
        returncode = 1
        err.write(f"{type(error).__name__}: {error}\n")
    return returncode, out.getvalue(), err.getvalue()


def _child_environment() -> dict[str, str]:
    """The parent's environment, with the tree this module was imported from on ``PYTHONPATH``.

    The child must import the code that is running, not whatever a bare interpreter would resolve.
    A worktree, an editable install and a wheel all satisfy that with the same two lines, and
    prepending rather than replacing leaves a caller's own path intact.
    """
    environment = dict(os.environ)
    root = str(Path(__file__).resolve().parent.parent.parent)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else root
    return environment


class PycolmapExecutor:
    """Runs ``pose.py``'s COLMAP commands through the pycolmap library, one process per stage.

    Stateless between calls except for the options it was constructed with, because the
    controller's checkpoint is the only state that may survive a stage: an executor that
    remembered a database handle would be a second place a resumed job could disagree with its
    own receipt. Spawning per stage makes that literal rather than a convention.
    """

    def __init__(
        self,
        *,
        random_seed: int = DEFAULT_RANDOM_SEED,
        camera_model: str = "SIMPLE_RADIAL",
        stage_isolation: bool = True,
        extraction_threads: int | None = None,
    ) -> None:
        self._random_seed = random_seed
        self._camera_model = camera_model
        self._stage_isolation = stage_isolation
        self._extraction_threads = (
            default_extraction_threads() if extraction_threads is None else extraction_threads
        )
        if self._extraction_threads < 1:
            raise ValueError("extraction_threads must be at least one")

    def __call__(self, command: tuple[str, ...], cwd: Path) -> CommandResult:
        started = time.monotonic_ns()
        if self._stage_isolation:
            returncode, out, err = self._run_isolated(command, cwd)
        else:
            returncode, out, err = run_stage_here(
                command,
                cwd,
                random_seed=self._random_seed,
                camera_model=self._camera_model,
                extraction_threads=self._extraction_threads,
            )
        return CommandResult(
            returncode=returncode,
            stdout=out,
            stderr=err,
            duration_ms=(time.monotonic_ns() - started) / 1_000_000,
        )

    def _run_isolated(self, command: tuple[str, ...], cwd: Path) -> tuple[int, str, str]:
        """Run the stage in a child that exits with it, and report what the child reported.

        The child's own file descriptors 1 and 2 are inherited rather than captured, because they
        carry COLMAP's glog output and that has always gone to the worker's streams. The result
        travels by file instead.
        """
        request = {
            "command": list(command),
            "cwd": str(cwd),
            "random_seed": self._random_seed,
            "camera_model": self._camera_model,
            "extraction_threads": self._extraction_threads,
        }
        with tempfile.TemporaryDirectory(prefix="exulanica-colmap-stage-") as scratch:
            directory = Path(scratch)
            request_path, response_path = directory / "request.json", directory / "response.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            argv = [
                sys.executable,
                "-m",
                PYCOLMAP_STAGE_MODULE,
                str(request_path),
                str(response_path),
            ]
            completed = subprocess.run(argv, env=_child_environment(), check=False)
            if response_path.is_file():
                try:
                    response = json.loads(response_path.read_text(encoding="utf-8"))
                    return (
                        int(response["returncode"]),
                        str(response["stdout"]),
                        str(response["stderr"]),
                    )
                except (ValueError, KeyError, TypeError) as error:
                    return 1, "", f"the COLMAP stage process wrote an unreadable result: {error}\n"
        # No result at all: the child died before it could write one. In-process this was the case
        # that took the whole worker with it, so there was nothing to report; here the controller
        # gets a failed stage it can checkpoint, and a reason that names how the child ended.
        if completed.returncode < 0:
            ended = f"was killed by signal {-completed.returncode}"
        else:
            ended = f"exited {completed.returncode}"
        stage = command[1] if len(command) > 1 else "?"
        return 1, "", f"the COLMAP {stage} stage process {ended} without a result\n"


def _dispatch(
    command: tuple[str, ...],
    cwd: Path,
    *,
    random_seed: int,
    camera_model: str,
    extraction_threads: int,
) -> None:
    if len(command) < 2:
        raise ValueError("a COLMAP command needs at least an executable and a stage")
    stage = command[1]
    flags = _flags(command)
    pycolmap = _pycolmap()
    if stage == "feature_extractor":
        _feature_extractor(
            pycolmap, flags, cwd, camera_model=camera_model, threads=extraction_threads
        )
    elif stage == "exhaustive_matcher":
        _exhaustive_matcher(pycolmap, flags, cwd)
    elif stage == "mapper":
        _mapper(pycolmap, flags, cwd, random_seed=random_seed)
    elif stage == "model_converter":
        _model_converter(pycolmap, flags, cwd)
    else:
        raise ValueError(f"no in-process equivalent for COLMAP stage {stage!r}")


def _feature_extractor(
    pycolmap: Any, flags: dict[str, str], cwd: Path, *, camera_model: str, threads: int
) -> None:
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = camera_model
    # `--ImageReader.single_camera 0` is what pose.py emits, and AUTO is its meaning: one
    # camera per distinct EXIF camera, which for images with no EXIF is one per image.
    single = flags.get("ImageReader.single_camera", "0") == "1"
    mode = pycolmap.CameraMode.SINGLE if single else pycolmap.CameraMode.AUTO
    # Everything on this options object keeps its default except the thread count, so the features
    # themselves are the ones this backend has always produced. `max_image_size` and `first_octave`
    # would each bound memory harder and each would change what SIFT finds, which is why the cap is
    # on threads: it is the only one of the three that COLMAP's own warning offers that leaves the
    # descriptors alone.
    extraction = pycolmap.FeatureExtractionOptions()
    extraction.num_threads = threads
    pycolmap.extract_features(
        database_path=_path(flags, "database_path", cwd),
        image_path=_path(flags, "image_path", cwd),
        camera_mode=mode,
        reader_options=reader,
        extraction_options=extraction,
        device=pycolmap.Device.cpu,
    )


def _exhaustive_matcher(pycolmap: Any, flags: dict[str, str], cwd: Path) -> None:
    pycolmap.match_exhaustive(
        database_path=_path(flags, "database_path", cwd),
        device=pycolmap.Device.cpu,
    )


def _mapper(pycolmap: Any, flags: dict[str, str], cwd: Path, *, random_seed: int) -> None:
    output = _path(flags, "output_path", cwd)
    output.mkdir(parents=True, exist_ok=True)
    options = pycolmap.IncrementalPipelineOptions()
    options.random_seed = random_seed
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


def _model_converter(pycolmap: Any, flags: dict[str, str], cwd: Path) -> None:
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
