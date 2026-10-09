"""Drive a generated asset job on Nebius Serverless AI from this Mac, through the two CLIs.

- ``stage``: a deterministic archive of the code the job runs (this package, its container
  assets and weights manifests, and the colour table), the job record, its requests, the entry
  script and any cut-outs, copied to the bucket with the aws CLI at Nebius's S3 endpoint.
- ``submit``: ``nebius ai job create``, refused unless the worst case (the job's timeout, which is
  its stop at 150 per cent of the estimate, times the rate read that day) fits the allocated bound.
- ``status``, ``fetch``, ``cancel``: ``nebius ai job get``, an aws sync of the outputs, and
  ``nebius ai job cancel``.
- ``clear`` and ``usage``: remove everything the bucket holds, and list what it still holds, so
  weights and outputs are not kept (and billed) once fetched.
- ``session_stage``, ``queue``, ``session_status``, ``session_stop`` and ``session_fetch``: a warm
  session's record, code and entry script; a batch put in its queue with ``ready.json`` copied
  last; the session's latest heartbeat; its stop marker; and its outputs and markers
  (:mod:`exulanica_appearance.assets.queue` holds the layout). A session is submitted like a job,
  with ``mode="session"``.

The bucket key is the JSON file ``EXULANICA_GEN_S3_KEY_FILE`` names (fields aws_access_key_id,
aws_secret_access_key, endpoint_url, region, bucket, as the account setup writes it, mode 600).
It is read in this process and handed to each aws child in that child's environment only: never
on a command line, never printed, never written to another file; the aws CLI's own credential and
config files are switched off for the call. The job itself reads no key: the bucket arrives as a
mount. The nebius CLI uses its own profile. Nothing is printed but the commands' own output.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from exulanica_pieces.canonical import Refused, is_sha256, parse_canonical, sha256_hex

from exulanica_appearance.assets.queue import (
    BEAT_PROFILE,
    build_ready,
    entry_files,
    read_session,
)

__all__ = [
    "IMAGE",
    "clear",
    "code_archive",
    "queue",
    "session_fetch",
    "session_stage",
    "session_status",
    "session_stop",
    "submit_arguments",
    "usage",
    "worst_case_cents",
]

#: Track A's pinned base, which ran torch on a 96 GB card; CUDA comes from the locked wheels.
IMAGE: Final = "python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254"
#: What the job's code archive holds, relative to the repository root.
_CODE: Final = (
    "assets/colour",
    "assets/style-packs/piece-budgets.v1.json",
    "exulanica_pieces",
    "ml/appearance/container/assets",
    "ml/appearance/exulanica_appearance",
    "ml/appearance/pyproject.toml",
    "ml/appearance/weights",
)
_MOUNT: Final = "/mnt/data"
#: The entry script this tree stages (session_stage and stage copy it to runs/<sha256>/).
JOB_SCRIPT: Final = Path(__file__).resolve().parents[2] / "container/assets/job.sh"
#: Where the container copies the staged entry script before checking it: the machine's own disk,
#: so the bytes checked are the bytes run.
_LOCAL_SCRIPT: Final = "/opt/job.sh"


def code_archive(repository: Path) -> bytes:
    """The same bytes for the same files: sorted entries, no owners, a fixed time and modes."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        paths: list[Path] = []
        for name in _CODE:
            root = repository / name
            if root.is_file():
                paths.append(root)
            else:
                paths.extend(
                    path
                    for path in root.rglob("*")
                    if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
                )
        for path in sorted(paths, key=lambda item: item.relative_to(repository).as_posix()):
            data = path.read_bytes()
            info = tarfile.TarInfo(path.relative_to(repository).as_posix())
            info.size = len(data)
            info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def worst_case_cents(timeout_seconds: int, rate_cents_per_hour: int) -> int:
    """What a job can cost if it runs to its timeout, rounded up to a cent."""
    return -(-timeout_seconds * rate_cents_per_hour // 3600)


def _run(command: Sequence[str], *, environment: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        list(command), check=False, capture_output=True, text=True, env=environment
    )
    if completed.returncode != 0:
        raise Refused(
            f"{command[0]} {command[1] if len(command) > 1 else ''} failed: {completed.stderr.strip()[:500]}"
        )
    return completed.stdout


_KEY_FIELDS: Final = (
    "aws_access_key_id",
    "aws_secret_access_key",
    "bucket",
    "endpoint_url",
    "region",
)


def _aws(region: str, arguments: Sequence[str], bucket: str) -> str:
    path = os.environ.get("EXULANICA_GEN_S3_KEY_FILE")
    if not path:
        raise Refused("EXULANICA_GEN_S3_KEY_FILE names no bucket key file")
    key = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(key, dict) or set(key) != set(_KEY_FIELDS):
        raise Refused(f"the bucket key file holds exactly {', '.join(_KEY_FIELDS)}")
    endpoint = f"https://storage.{region}.nebius.cloud"
    if (key["region"], key["endpoint_url"], key["bucket"]) != (region, endpoint, bucket):
        raise Refused("the bucket key file is for another region, endpoint or bucket")
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("AWS_") and name != "EXULANICA_GEN_S3_KEY_FILE"
    }
    environment.update(
        AWS_ACCESS_KEY_ID=key["aws_access_key_id"],
        AWS_SECRET_ACCESS_KEY=key["aws_secret_access_key"],
        AWS_SHARED_CREDENTIALS_FILE=os.devnull,
        AWS_CONFIG_FILE=os.devnull,
    )
    return _run(
        ["aws", "--endpoint-url", endpoint, "--region", region, *arguments], environment=environment
    )


def stage(
    *,
    repository: Path,
    job: Path,
    requests: Path,
    bucket: str,
    region: str,
    cutouts: Path | None = None,
    sketches: Path | None = None,
) -> dict[str, Any]:
    """Copy everything the job reads to ``s3://<bucket>/runs/<job sha256>/``, and any cut-outs
    an item names to ``out/inputs/``, where every job writes its own and route B reads them. A
    creature job (route C) also reads its requests' sketch containers, from ``sketches/``."""
    job_raw = job.read_bytes()
    job_sha256 = sha256_hex(job_raw)
    code = code_archive(repository)
    staging = job.parent / f"stage-{job_sha256[:12]}"
    (staging / "requests").mkdir(parents=True, exist_ok=True)
    (staging / "code.tar").write_bytes(code)
    (staging / "job.json").write_bytes(job_raw)
    # The entry script the submit command pins: this tooling's own (JOB_SCRIPT).
    (staging / "job.sh").write_bytes(JOB_SCRIPT.read_bytes())
    files = {"code.tar": sha256_hex(code), "job.json": job_sha256}
    for path in sorted(requests.glob("*.json")):
        (staging / "requests" / path.name).write_bytes(path.read_bytes())
        files[f"requests/{path.name}"] = sha256_hex(path.read_bytes())
    if sketches is not None:
        (staging / "sketches").mkdir(parents=True, exist_ok=True)
        for path in sorted(sketches.glob("*.glb")):
            (staging / "sketches" / path.name).write_bytes(path.read_bytes())
            files[f"sketches/{path.name}"] = sha256_hex(path.read_bytes())
    _aws(
        region,
        [
            "s3",
            "cp",
            "--recursive",
            "--only-show-errors",
            str(staging),
            f"s3://{bucket}/runs/{job_sha256}/",
        ],
        bucket,
    )
    if cutouts is not None:
        _aws(
            region,
            [
                "s3",
                "cp",
                "--recursive",
                "--only-show-errors",
                str(cutouts),
                f"s3://{bucket}/out/inputs/",
            ],
            bucket,
        )
    return {"code_sha256": files["code.tar"], "files": files, "job_sha256": job_sha256}


def submit_arguments(
    *,
    route: str,
    job_sha256: str,
    code_sha256: str,
    bucket_id: str,
    subnet_id: str,
    platform: str,
    preset: str,
    timeout_seconds: int,
    rate_cents_per_hour: int,
    bound_cents: int,
    preemptible: bool,
    profile: str,
    dry_run: bool = False,
    mode: str = "job",
    job_script_sha256: str | None = None,
) -> list[str]:
    """The ``nebius ai job create`` command, or a refusal when the worst case passes the bound.

    In ``session`` mode ``job_sha256`` is the session record's digest and ``timeout_seconds`` its
    hard stop. Nothing the machine runs is taken from the bucket on trust: the container copies the
    staged ``job.sh`` to its own disk and runs it only when it is ``job_script_sha256`` (by default
    the digest of this tree's :data:`JOB_SCRIPT`), and ``job.sh`` holds the code archive and the
    session record to the digests this command names. Anyone who can write the bucket can
    therefore make a start fail, never run other code. The container command is ``sh -c`` with the
    check as its script, which relies on the service splitting ``--args`` as a shell does; the
    sessions measured so far ran a single path there, so this form is verified only by the next
    live session (contract: generated pieces, 5.1)."""
    if route not in ("A", "B", "C"):
        raise Refused("a job on the rented machine takes route A, B or C")
    if mode not in ("job", "session"):
        raise Refused("a submission runs one job or a session")
    # The service's shortest timeout is one hour, so a shorter stop still risks an hour; the
    # job's own stop is enforced inside the job (STOP_SECONDS in job.sh).
    script_sha256 = job_script_sha256 or sha256_hex(JOB_SCRIPT.read_bytes())
    if not is_sha256(script_sha256):
        raise Refused("job_script_sha256 is a sha256")
    service_timeout = max(timeout_seconds, 3600)
    worst = worst_case_cents(service_timeout, rate_cents_per_hour)
    if worst > bound_cents:
        raise Refused(
            f"the worst case is {worst} cents ({service_timeout} s at {rate_cents_per_hour} cents "
            f"an hour), over the allocated {bound_cents}"
        )
    command = [
        "nebius", "--profile", profile, "ai", "job", "create",
        "--name", f"exulanica-gen-{'session-' if mode == 'session' else ''}{route.lower()}-{job_sha256[:12]}",
        "--image", IMAGE,
        "--platform", platform,
        "--preset", preset,
        "--disk-size", "250Gi",
        "--subnet-id", subnet_id,
        "--volume", f"{bucket_id}:{_MOUNT}",
        "--timeout", f"{service_timeout}s",
        "--restart-policy", "never",
        "--env", f"ROUTE={route}",
        "--env", f"JOB={job_sha256}",
        "--env", f"CODE_SHA256={code_sha256}",
        "--env", f"STOP_SECONDS={timeout_seconds}",
        "--env", f"MODE={mode}",
        "--env", f"JOB_SCRIPT_SHA256={script_sha256}",
        "--container-command", "sh",
        "--args", f"-c '{loader_script(job_sha256)}'",
        "--async",
        "--format", "json",
    ]  # fmt: skip
    command.append("--preemptible" if preemptible else "--on-demand")
    if dry_run:
        command.append("--dry-run")
    return command


def loader_script(job_sha256: str) -> str:
    """The container's own script: copy the staged ``job.sh`` to local disk, refuse it unless it
    is the digest the submit command pinned (``JOB_SCRIPT_SHA256``), then run the copy. It holds no
    single quote, so it sits inside one."""
    staged = f"{_MOUNT}/runs/{job_sha256}/job.sh"
    return (
        f"set -eu; cp {staged} {_LOCAL_SCRIPT}; "
        f'test "$(sha256sum {_LOCAL_SCRIPT} | cut -c1-64)" = "$JOB_SCRIPT_SHA256"; '
        f"exec sh {_LOCAL_SCRIPT}"
    )


def submit(**arguments: Any) -> dict[str, Any]:
    """The create operation (its resource_id is the job's id), or a dry run's verdict in words."""
    output = _run(submit_arguments(**arguments))
    if arguments.get("dry_run"):
        return {"dry_run": output.strip()}
    return json.loads(output)


def status(job_id: str, profile: str) -> dict[str, Any]:
    return json.loads(
        _run(
            ["nebius", "--profile", profile, "ai", "job", "get", "--id", job_id, "--format", "json"]
        )
    )


def cancel(job_id: str, profile: str) -> str:
    return _run(["nebius", "--profile", profile, "ai", "job", "cancel", job_id])


def fetch(*, bucket: str, region: str, out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    return _aws(
        region, ["s3", "sync", "--only-show-errors", f"s3://{bucket}/out/", str(out)], bucket
    )


def clear(*, bucket: str, region: str) -> str:
    """Remove every object: weights, caches, staged runs and outputs. Storage bills per byte held."""
    return _aws(
        region, ["s3", "rm", "--recursive", "--only-show-errors", f"s3://{bucket}/"], bucket
    )


def usage(*, bucket: str, region: str) -> str:
    """What the bucket still holds, with the totals line the aws CLI prints."""
    return _aws(region, ["s3", "ls", "--recursive", "--summarize", f"s3://{bucket}/"], bucket)


def _copy(region: str, bucket: str, files: dict[str, bytes], prefix: str) -> None:
    """Copy ``files`` (names relative to ``prefix``) to the bucket in one call."""
    with tempfile.TemporaryDirectory(prefix="exulanica-gen-") as staging:
        for name, data in files.items():
            path = Path(staging) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        _aws(
            region,
            [
                "s3",
                "cp",
                "--recursive",
                "--only-show-errors",
                staging,
                f"s3://{bucket}/{prefix}",
            ],
            bucket,
        )


def session_stage(
    *, repository: Path, session_raw: bytes, bucket: str, region: str
) -> dict[str, Any]:
    """Copy a session's record, the code archive it names and the entry script to
    ``runs/<session sha256>/``; refused when the archive is not the one the record names."""
    session = read_session(session_raw)
    code = code_archive(repository)
    if sha256_hex(code) != session["code_sha256"]:
        raise Refused("the session record names another code archive than this tree makes")
    session_sha256 = sha256_hex(session_raw)
    _copy(
        region,
        bucket,
        {
            "code.tar": code,
            "job.sh": JOB_SCRIPT.read_bytes(),
            "session.json": session_raw,
        },
        f"runs/{session_sha256}/",
    )
    return {"code_sha256": session["code_sha256"], "session_sha256": session_sha256}


def queue(
    *,
    entry_id: str,
    session_sha256: str,
    job_raw: bytes,
    requests: Sequence[bytes],
    bucket: str,
    region: str,
    queued_at: datetime,
    not_after: datetime,
) -> dict[str, Any]:
    """Put a batch in the queue as entry ``entry_id``: its job and requests first, then
    ``ready.json`` in a second copy, so the session never sees a ready entry whose files are not
    all there. Only the session ``session_sha256`` takes it, and none after ``not_after``."""
    ready = build_ready(
        entry_id,
        job_raw,
        requests,
        session_sha256=session_sha256,
        queued_at=queued_at,
        not_after=not_after,
    )
    prefix = f"queue/{entry_id}/"
    _copy(region, bucket, entry_files(job_raw, requests), prefix)
    _copy(region, bucket, {"ready.json": ready}, prefix)
    return {"entry_id": entry_id, "job_sha256": sha256_hex(job_raw), "requests": len(requests)}


def session_stop(*, session_sha256: str, bucket: str, region: str) -> dict[str, Any]:
    """The stop marker: the session ends at its next poll, after the batch in hand."""
    _copy(region, bucket, {"stop": b""}, f"session/{session_sha256}/")
    return {"session_sha256": session_sha256, "stop": "written"}


def session_status(*, session_sha256: str, bucket: str, region: str) -> dict[str, Any]:
    """The session's latest heartbeat, read strictly enough to show, and how many it has written."""
    listing = _aws(region, ["s3", "ls", f"s3://{bucket}/session/{session_sha256}/"], bucket)
    beats = sorted(
        line.split()[-1]
        for line in listing.splitlines()
        if line.split() and line.split()[-1].startswith("beat-")
    )
    if not beats:
        return {"beats": 0, "session_sha256": session_sha256}
    raw = _aws(
        region, ["s3", "cp", f"s3://{bucket}/session/{session_sha256}/{beats[-1]}", "-"], bucket
    )
    beat = parse_canonical(raw.encode("ascii"), "heartbeat")
    if beat.get("profile") != BEAT_PROFILE or beat.get("session_sha256") != session_sha256:
        raise Refused("the latest heartbeat is not this session's")
    return {"beats": len(beats), "latest": beat}


def session_fetch(*, bucket: str, region: str, out: Path) -> str:
    """Everything the session wrote (outputs, claimed and done markers, heartbeats), not the staged
    code or the queue."""
    out.mkdir(parents=True, exist_ok=True)
    return _aws(
        region,
        [
            "s3",
            "sync",
            "--only-show-errors",
            "--exclude",
            "runs/*",
            "--exclude",
            "queue/*",
            f"s3://{bucket}/",
            str(out),
        ],
        bucket,
    )
