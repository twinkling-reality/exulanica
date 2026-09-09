"""Measure what a COLMAP pose run costs in memory, per photograph, and prove two runs agree.

WHY THIS EXISTS. `docs/records/2026-09-08-scene-inspection.md` records the one measurement that stopped a
real 210 photograph run on this laptop: in-process pycolmap feature extraction reached file 199 of
210 with the process footprint at about 20 GB, the machine swapping at 17.5 of 18.4 GB, and the job
was SIGTERMed. A resumed attempt extracted the remaining eleven in 0.748 minutes. That record
observed the footprint from outside, at one moment, with no per-image series and no attribution.
This script produces the series.

WHAT IT DOES. It builds a scratch COLMAP workspace holding the first N photographs of a directory,
spawns a subject process that drives the same four COLMAP command vectors `pose.py` emits through a
chosen executor, and samples the subject process TREE from the parent while it runs. Sampling from
the parent is the point: the in-process executor is one process and the child-process executor is a
parent plus one short-lived child per stage, and only a tree-wide sample compares them honestly.

Each sample carries two numbers because they mean different things on macOS. `resident` is
`ri_resident_size`, which counts file-backed clean pages that the kernel can drop without cost.
`footprint` is `ri_phys_footprint`, the number Activity Monitor shows and the one an operator
watching a machine swap is actually reading. Both come from `proc_pid_rusage`, which needs no third
party package and no privilege for a process the caller owns.

Progress comes from COLMAP's own log. MEASURED on a three image trial run: pycolmap 4.2.0 does not
commit keypoints to the database as it goes, it writes them at the end of the whole extraction, so
`select count(*) from keypoints` stays at zero for the entire run and is useless as a progress
signal. The log line `Processed file [k/N]` is emitted per image, which is also what the operator
watching the 2026-09-08 run was reading when they recorded "reached file 199 of 210". The subject's
streams are therefore captured to a log file and the sampler parses its tail. The database count is
still recorded alongside, because the gap between the two is itself the finding.

WHAT IT PROVES. The digests block hashes the COLMAP database and every file under `sparse/` after
the run. Two runs of this script that differ only in `--mode` produce two records, and comparing
their digest blocks is the byte-identity check: the bound is only admissible if the outputs do not
move. The stage block carries the exact `CommandResult` fields the pose controller writes into its
checkpoint, including the stdout and stderr digests, so a checkpoint difference shows up here too.

USAGE

    uv run --extra pose python scripts/measure_extraction_memory.py \
        --photographs .exulanica/reference-baseline/inputs/volcanic-sample/photographs \
        --count 40 --mode in_process \
        --workspace /tmp/recon-scratch/in-process --out /tmp/recon-scratch/in-process.json

`--mode child_process` selects the isolating executor. `--mode` is the only thing that should differ
between two runs being compared. Nothing here reads or writes a database, a blob store or any
retained state; the workspace is a scratch directory the caller names and may delete.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parent.parent
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))


# -- macOS process accounting ---------------------------------------------------------------------
#
# proc_pid_rusage(pid, RUSAGE_INFO_V2, &buffer) fills a rusage_info_v2, whose layout is
# 16 bytes of uuid followed by uint64 fields. ri_resident_size is field 6 and ri_phys_footprint is
# field 7, counting ri_user_time as field 0, so both live at offset 16 + 6*8.
_RUSAGE_INFO_V2 = 2
_RESIDENT_OFFSET = 16 + 6 * 8

try:
    _LIBSYSTEM = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
except OSError:  # pragma: no cover - not macOS
    _LIBSYSTEM = None


def process_memory(pid: int) -> tuple[int, int] | None:
    """(resident_bytes, footprint_bytes) for one live process, or None if it is gone."""
    if _LIBSYSTEM is None:
        return None
    buffer = (ctypes.c_uint8 * 512)()
    if _LIBSYSTEM.proc_pid_rusage(ctypes.c_int(pid), ctypes.c_int(_RUSAGE_INFO_V2), ctypes.byref(buffer)) != 0:
        return None
    resident, footprint = struct.unpack_from("<QQ", bytes(buffer), _RESIDENT_OFFSET)
    return int(resident), int(footprint)


def process_tree(root: int) -> list[int]:
    """`root` and every descendant, from one `ps` snapshot so the walk cannot race itself."""
    listing = subprocess.run(
        ["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, check=False
    ).stdout
    children: dict[int, list[int]] = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, parent = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        children.setdefault(parent, []).append(pid)
    found, pending = [], [root]
    while pending:
        pid = pending.pop()
        found.append(pid)
        pending.extend(children.get(pid, ()))
    return found


_PROCESSED = re.compile(rb"Processed file \[(\d+)/(\d+)\]")


def processed_images(log: Path) -> int | None:
    """How many images COLMAP says it has processed, from the last such line in its own log.

    Only the tail is read, so the cost of a sample does not grow with the length of the run. This
    is the number the 2026-09-08 observation was made from.
    """
    if not log.is_file():
        return None
    size = log.stat().st_size
    with log.open("rb") as handle:
        handle.seek(max(0, size - 65536))
        tail = handle.read()
    found = _PROCESSED.findall(tail)
    return int(found[-1][0]) if found else None


def committed_images(database: Path) -> int | None:
    """How many images have their keypoints durably in the COLMAP database.

    One row in `keypoints` per image whose features are written. Read-only and with a short
    timeout, so a sample never blocks or perturbs the subject: an unavailable count is recorded as
    null rather than waited for. MEASURED: this stays at zero until extraction finishes, which is
    why it is a second signal rather than the one the series is built on.
    """
    if not database.is_file():
        return None
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=0.2)
    except sqlite3.Error:
        return None
    try:
        return int(connection.execute("select count(*) from keypoints").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        connection.close()


# -- digests --------------------------------------------------------------------------------------


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def output_digests(job: Path) -> dict[str, str]:
    """Every COLMAP output the run produced, by path relative to the job directory."""
    found: dict[str, str] = {}
    database = job / "database.db"
    if database.is_file():
        found["database.db"] = file_digest(database)
    sparse = job / "sparse"
    if sparse.is_dir():
        for path in sorted(sparse.rglob("*")):
            if path.is_file():
                found[str(path.relative_to(job))] = file_digest(path)
    return found


# -- the subject ----------------------------------------------------------------------------------


def commands(job: Path, images: Path) -> list[tuple[str, tuple[str, ...]]]:
    """The COLMAP argument vectors `exulanica/reconstruction/pose.py` emits, in its order.

    Copied rather than imported so this script measures the command boundary rather than the pose
    controller, which would need a manifest, a receipt and a quality gate to run at all. The
    model_converter vector is emitted per connected model after the mapper, exactly as pose.py
    does, so it is appended by the subject once the mapper has written `sparse/`.
    """
    database, sparse = job / "database.db", job / "sparse"
    return [
        (
            "feature_extractor",
            ("pycolmap", "feature_extractor", "--database_path", str(database),
             "--image_path", str(images), "--ImageReader.single_camera", "0"),
        ),
        ("exhaustive_matcher", ("pycolmap", "exhaustive_matcher", "--database_path", str(database))),
        (
            "mapper",
            ("pycolmap", "mapper", "--database_path", str(database),
             "--image_path", str(images), "--output_path", str(sparse)),
        ),
    ]


def run_subject(job: Path, images: Path, mode: str, progress: Path, stages: str, threads: int) -> int:
    """Drive the COLMAP stages through the chosen executor. Runs in the spawned subject process."""
    from exulanica.reconstruction.pycolmap_executor import PycolmapExecutor

    executor = PycolmapExecutor(
        stage_isolation=(mode == "child_process"),
        extraction_threads=threads or None,
    )
    job.mkdir(parents=True, exist_ok=True)
    (job / "sparse").mkdir(exist_ok=True)
    wanted = commands(job, images)
    if stages == "extract":
        wanted = wanted[:1]
    records = []
    with progress.open("w", encoding="utf-8") as handle:
        for stage, command in wanted:
            handle.write(json.dumps({"event": "start", "stage": stage, "at": time.time()}) + "\n")
            handle.flush()
            result = executor(command, job)
            records.append(_stage_record(stage, command, result))
            handle.write(json.dumps({"event": "end", "stage": stage, "at": time.time()}) + "\n")
            handle.flush()
            if result.returncode != 0:
                break
        else:
            sparse = job / "sparse"
            for model in sorted(path for path in sparse.iterdir() if path.is_dir()):
                stage = f"model_converter:{model.name}"
                command = ("pycolmap", "model_converter", "--input_path", str(model),
                           "--output_path", str(model), "--output_type", "TXT")
                handle.write(json.dumps({"event": "start", "stage": stage, "at": time.time()}) + "\n")
                handle.flush()
                result = executor(command, job)
                records.append(_stage_record(stage, command, result))
                handle.write(json.dumps({"event": "end", "stage": stage, "at": time.time()}) + "\n")
                handle.flush()
                if result.returncode != 0:
                    break
    (job / "stages.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return 0 if all(record["returncode"] == 0 for record in records) else 1


def _stage_record(stage: str, command: tuple[str, ...], result) -> dict:
    """Exactly the fields `pose.py` writes into its checkpoint, plus the raw stream lengths.

    The lengths are here because a stdout digest that matches tells you nothing about whether
    anything was captured at all, and that distinction decides whether the checkpoint's stream
    digests are evidence or a constant.
    """
    return {
        "stage": stage,
        "command": list(command),
        "returncode": result.returncode,
        "duration_ms_hundredths": round(result.duration_ms * 100),
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        "stdout_bytes": len(result.stdout.encode()),
        "stderr_bytes": len(result.stderr.encode()),
        "stdout_head": result.stdout[:400],
        "stderr_head": result.stderr[:400],
    }


# -- the parent -----------------------------------------------------------------------------------


def build_workspace(photographs: Path, count: int, workspace: Path) -> tuple[Path, list[str]]:
    """A scratch workspace holding the first `count` photographs by name, as symlinks.

    Symlinks rather than copies: COLMAP records the image name relative to `--image_path`, so the
    database and the model see the same names either way, and 586 MB is not copied twice.
    """
    chosen = sorted(p.name for p in photographs.iterdir() if p.suffix.lower() in {".jpg", ".jpeg"})[:count]
    if len(chosen) < count:
        raise SystemExit(f"{photographs} holds {len(chosen)} photographs, fewer than the {count} asked for")
    images = workspace / "images"
    if images.exists():
        shutil.rmtree(images)
    images.mkdir(parents=True)
    for name in chosen:
        (images / name).symlink_to((photographs / name).resolve())
    return images, chosen


def sample_until_exit(process: subprocess.Popen, database: Path, progress: Path, log: Path, interval: float) -> tuple[list[dict], list[dict]]:
    started = time.time()
    samples: list[dict] = []
    while process.poll() is None:
        pids = process_tree(process.pid)
        readings = [reading for reading in (process_memory(pid) for pid in pids) if reading]
        if readings:
            samples.append({
                "at_ms": round((time.time() - started) * 1000),
                "processes": len(readings),
                "resident_bytes": sum(reading[0] for reading in readings),
                "footprint_bytes": sum(reading[1] for reading in readings),
                "extracted": processed_images(log),
                "committed": committed_images(database),
            })
        time.sleep(interval)
    events = []
    if progress.is_file():
        for line in progress.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = json.loads(line)
                event["at_ms"] = round((event.pop("at") - started) * 1000)
                events.append(event)
    return samples, events


def per_image(samples: list[dict]) -> list[dict]:
    """The first sample at each distinct extracted-image count, which is the growth series."""
    seen: dict[int, dict] = {}
    for sample in samples:
        count = sample["extracted"]
        if count is not None and count not in seen:
            seen[count] = sample
    return [
        {
            "extracted": count,
            "at_ms": sample["at_ms"],
            "resident_mb_hundredths": round(sample["resident_bytes"] / 1e6 * 100),
            "footprint_mb_hundredths": round(sample["footprint_bytes"] / 1e6 * 100),
        }
        for count, sample in sorted(seen.items())
    ]


def growth(series: list[dict], key: str) -> dict | None:
    """Least squares MB per image over the series, and the plain first-to-last difference."""
    points = [(entry["extracted"], entry[key] / 100.0) for entry in series if entry["extracted"] > 0]
    if len(points) < 2:
        return None
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    variance = sum((x - mean_x) ** 2 for x, _ in points)
    if variance == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / variance
    first, last = points[0], points[-1]
    span = last[0] - first[0]
    return {
        "mb_per_image_least_squares_hundredths": round(slope * 100),
        "mb_per_image_first_to_last_hundredths": round((last[1] - first[1]) / span * 100) if span else None,
        "first_image": first[0],
        "last_image": last[0],
        "first_mb_hundredths": round(first[1] * 100),
        "last_mb_hundredths": round(last[1] * 100),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photographs", type=Path, required=True)
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--mode", choices=("in_process", "child_process"), required=True)
    parser.add_argument("--stages", choices=("all", "extract"), default="all")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--label", default="")
    parser.add_argument(
        "--threads", type=int, default=0,
        help="feature extraction threads; 0 means the executor's own memory-derived default",
    )
    parser.add_argument("--subject-job", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--subject-images", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--subject-progress", type=Path, help=argparse.SUPPRESS)
    arguments = parser.parse_args()

    if arguments.subject_job is not None:
        return run_subject(
            arguments.subject_job, arguments.subject_images, arguments.mode,
            arguments.subject_progress, arguments.stages, arguments.threads,
        )

    from exulanica.reconstruction.pycolmap_executor import default_extraction_threads

    effective_threads = arguments.threads or default_extraction_threads()
    workspace = arguments.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    images, chosen = build_workspace(arguments.photographs.resolve(), arguments.count, workspace)
    job = workspace / "job"
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    (job / "sparse").mkdir()
    progress = workspace / "progress.jsonl"
    progress.unlink(missing_ok=True)

    command = [
        sys.executable, str(Path(__file__).resolve()),
        "--photographs", str(arguments.photographs), "--count", str(arguments.count),
        "--workspace", str(workspace), "--mode", arguments.mode, "--stages", arguments.stages,
        "--out", str(arguments.out), "--threads", str(arguments.threads),
        "--subject-job", str(job), "--subject-images", str(images), "--subject-progress", str(progress),
    ]
    started = time.time()
    log = workspace / "colmap.log"
    # COLMAP's glog output is the progress signal, so it is captured to a file rather than left on
    # the terminal. The subject's CommandResult is unaffected: those streams were never what the
    # executor captures, which is the point measured below.
    with log.open("wb") as handle:
        process = subprocess.Popen(
            command, cwd=str(REPOSITORY), env=dict(os.environ), stdout=handle, stderr=handle
        )
        samples, events = sample_until_exit(
            process, job / "database.db", progress, log, arguments.interval
        )
        returncode = process.wait()
    elapsed = time.time() - started

    stages = json.loads((job / "stages.json").read_text(encoding="utf-8")) if (job / "stages.json").is_file() else []
    series = per_image(samples)
    record = {
        "label": arguments.label,
        "mode": arguments.mode,
        "requested_threads": arguments.threads,
        "effective_threads": effective_threads,
        "stages_requested": arguments.stages,
        "photographs": str(arguments.photographs),
        "image_count": len(chosen),
        "image_names": chosen,
        "subject_returncode": returncode,
        "elapsed_ms": round(elapsed * 1000),
        "sample_interval_ms": round(arguments.interval * 1000),
        "colmap_log": str(log),
        "colmap_log_sha256": file_digest(log) if log.is_file() else None,
        "samples": samples,
        "stage_events": events,
        "per_image": series,
        "growth_footprint": growth(series, "footprint_mb_hundredths"),
        "growth_resident": growth(series, "resident_mb_hundredths"),
        "peak_footprint_mb_hundredths": round(max((s["footprint_bytes"] for s in samples), default=0) / 1e6 * 100),
        "peak_resident_mb_hundredths": round(max((s["resident_bytes"] for s in samples), default=0) / 1e6 * 100),
        "peak_processes": max((s["processes"] for s in samples), default=0),
        "stages": stages,
        "digests": output_digests(job),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    peak = record["peak_footprint_mb_hundredths"] / 100.0
    print(f"{arguments.mode} at {effective_threads} threads: subject exit {returncode}, "
          f"peak footprint {peak:.1f} MB, "
          f"{len(samples)} samples, {len(record['digests'])} outputs digested -> {arguments.out}")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
