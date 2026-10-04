"""Drive a generated asset job on Nebius Serverless AI from this Mac, through the two CLIs.

- ``stage``: a deterministic archive of the code the job runs (this package, its container
  assets and weights manifests, and the colour table), the job record, its requests, the entry
  script and any cut-outs, copied to the bucket with the aws CLI at Nebius's S3 endpoint.
- ``submit``: ``nebius ai job create``, refused unless the worst case (the job's timeout, which is
  its stop at 150 per cent of the estimate, times the rate read that day) fits the allocated bound.
- ``status``, ``fetch``, ``cancel``: ``nebius ai job get``, an aws sync of the outputs, and
  ``nebius ai job cancel``.

No credential passes through this module: the aws CLI reads the file
``EXULANICA_GEN_S3_CREDENTIALS`` names (as ``AWS_SHARED_CREDENTIALS_FILE``), and the nebius CLI
its own profile. Nothing is printed but the commands' own output.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from exulanica_appearance.canonical import Refused, sha256_hex

__all__ = [
    "IMAGE",
    "code_archive",
    "submit_arguments",
    "worst_case_cents",
]

#: Track A's pinned base, which ran torch on a 96 GB card; CUDA comes from the locked wheels.
IMAGE: Final = "python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254"
#: What the job's code archive holds, relative to the repository root.
_CODE: Final = (
    "assets/colour",
    "ml/appearance/container/assets",
    "ml/appearance/exulanica_appearance",
    "ml/appearance/pyproject.toml",
    "ml/appearance/weights",
)
_MOUNT: Final = "/mnt/data"


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


def _aws(region: str, arguments: Sequence[str]) -> str:
    credentials = os.environ.get("EXULANICA_GEN_S3_CREDENTIALS")
    if not credentials:
        raise Refused("EXULANICA_GEN_S3_CREDENTIALS names no credentials file")
    environment = dict(os.environ, AWS_SHARED_CREDENTIALS_FILE=credentials)
    environment.pop("AWS_ACCESS_KEY_ID", None)
    environment.pop("AWS_SECRET_ACCESS_KEY", None)
    endpoint = f"https://storage.{region}.nebius.cloud"
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
) -> dict[str, Any]:
    """Copy everything the job reads to ``s3://<bucket>/runs/<job sha256>/``, and any cut-outs
    an item names to ``out/inputs/``, where every job writes its own and route B reads them."""
    job_raw = job.read_bytes()
    job_sha256 = sha256_hex(job_raw)
    code = code_archive(repository)
    staging = job.parent / f"stage-{job_sha256[:12]}"
    (staging / "requests").mkdir(parents=True, exist_ok=True)
    (staging / "code.tar").write_bytes(code)
    (staging / "job.json").write_bytes(job_raw)
    (staging / "job.sh").write_bytes(
        (repository / "ml/appearance/container/assets/job.sh").read_bytes()
    )
    files = {"code.tar": sha256_hex(code), "job.json": job_sha256}
    for path in sorted(requests.glob("*.json")):
        (staging / "requests" / path.name).write_bytes(path.read_bytes())
        files[f"requests/{path.name}"] = sha256_hex(path.read_bytes())
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
) -> list[str]:
    """The ``nebius ai job create`` command, or a refusal when the worst case passes the bound."""
    if route not in ("A", "B"):
        raise Refused("a job on the rented machine takes route A or B")
    # The service's shortest timeout is one hour, so a shorter stop still risks an hour; the
    # job's own stop is enforced inside the job (STOP_SECONDS in job.sh).
    service_timeout = max(timeout_seconds, 3600)
    worst = worst_case_cents(service_timeout, rate_cents_per_hour)
    if worst > bound_cents:
        raise Refused(
            f"the worst case is {worst} cents ({service_timeout} s at {rate_cents_per_hour} cents "
            f"an hour), over the allocated {bound_cents}"
        )
    command = [
        "nebius", "--profile", profile, "ai", "job", "create",
        "--name", f"exulanica-gen-{route.lower()}-{job_sha256[:12]}",
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
        "--container-command", "sh",
        "--args", f"{_MOUNT}/runs/{job_sha256}/job.sh",
        "--format", "json",
    ]  # fmt: skip
    if preemptible:
        command.append("--preemptible")
    return command


def submit(**arguments: Any) -> dict[str, Any]:
    return json.loads(_run(submit_arguments(**arguments)))


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
    return _aws(region, ["s3", "sync", "--only-show-errors", f"s3://{bucket}/out/", str(out)])
