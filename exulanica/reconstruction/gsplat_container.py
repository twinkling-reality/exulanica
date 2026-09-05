"""Run the scene trainer in the exact image named by its build manifest."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import time
import uuid
from contextlib import suppress
from pathlib import Path

from exulanica.reconstruction.gsplat_protocol import RUNNER_PROFILE
from exulanica.reconstruction.gsplat_runner import read_manifest
from exulanica.reconstruction.splat import (
    SplatBuildManifest,
    _verify_dataset_sources,
    _verify_pose_receipt,
    _write_atomic,
)


def container_command(
    manifest: SplatBuildManifest,
    *,
    manifest_path: Path,
    pose_receipt: Path,
    dataset: Path,
    output: Path,
    cidfile: Path | None = None,
    owner_label: str | None = None,
) -> tuple[str, ...]:
    """Expose only these inputs and this output to a network-isolated CUDA process."""
    mounts = (
        (manifest_path, "/run/input/manifest.json", True),
        (pose_receipt, "/run/input/pose.json", True),
        (dataset, "/run/dataset", True),
        (output, "/run/output", False),
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--gpus",
        "device=0",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,nosuid,size=2g",
        "--env",
        "TORCH_HOME=/opt/torch-cache",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
    ]
    if (cidfile is None) != (owner_label is None):
        raise ValueError("container ownership requires both a cidfile and a unique label")
    if cidfile is not None:
        command.extend(["--cidfile", str(cidfile), "--label", f"{_OWNER_LABEL}={owner_label}"])
    for source, target, readonly in mounts:
        if "," in str(source):
            raise ValueError("Docker bind source paths may not contain commas")
        command.extend(
            [
                "--mount",
                (
                    f"type=bind,src={source.resolve()},dst={target}"
                    + (",readonly" if readonly else "")
                ),
            ]
        )
    command.extend(
        [
            "--entrypoint",
            "python",
            manifest.execution_image,
            "-m",
            "exulanica.reconstruction.gsplat_runner",
            "train",
            "--profile",
            RUNNER_PROFILE,
            "--manifest",
            "/run/input/manifest.json",
            "--pose-receipt",
            "/run/input/pose.json",
            "--dataset",
            "/run/dataset",
            "--output",
            "/run/output",
            "--resume",
            "auto",
        ]
    )
    return tuple(command)


_OWNER_LABEL = "exulanica.scene-job-launch"
_CLEANUP_MARKER = "container-cleanup-required.json"
UNCERTAIN_CLEANUP_EXIT = 76


class ContainerCleanupUncertain(RuntimeError):
    """Scratch must remain until the owned container is confirmed stopped or absent."""


def _control(
    docker: str, *arguments: str, timeout: float = 5.0
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [docker, *arguments], check=False, text=True, capture_output=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ContainerCleanupUncertain("Docker did not confirm owned container state") from error


def _owned_running(docker: str, container_id: str, owner: str) -> bool:
    result = _control(
        docker,
        "inspect",
        "--type",
        "container",
        "--format",
        '{{ index .Config.Labels "' + _OWNER_LABEL + '" }}|{{.State.Running}}',
        container_id,
    )
    if result.returncode != 0:
        if "No such container" in result.stderr or "No such object" in result.stderr:
            return False
        raise ContainerCleanupUncertain("Docker inspection could not confirm container state")
    label, separator, running = result.stdout.strip().partition("|")
    if separator != "|" or label != owner or running not in {"true", "false"}:
        raise ContainerCleanupUncertain("container ownership or running state did not verify")
    return running == "true"


def _owned_ids(docker: str, cidfile: Path, owner: str) -> set[str]:
    ids: set[str] = set()
    if cidfile.is_file():
        container_id = cidfile.read_text().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", container_id):
            raise ContainerCleanupUncertain("owned container ID was not durably recorded")
        ids.add(container_id)
    result = _control(
        docker,
        "ps",
        "--all",
        "--filter",
        f"label={_OWNER_LABEL}={owner}",
        "--format",
        "{{.ID}}",
        "--no-trunc",
    )
    if result.returncode != 0:
        raise ContainerCleanupUncertain("Docker could not enumerate the owned launch")
    for container_id in result.stdout.splitlines():
        if not re.fullmatch(r"[0-9a-f]{64}", container_id):
            raise ContainerCleanupUncertain("Docker returned an invalid owned container ID")
        ids.add(container_id)
    return ids


def _stop_owned(docker: str, cidfile: Path, owner: str, grace_seconds: int) -> None:
    owned_ids = _owned_ids(docker, cidfile, owner)
    if len(owned_ids) > 1:
        raise ContainerCleanupUncertain("one launch unexpectedly owns multiple containers")
    for container_id in owned_ids:
        if not _owned_running(docker, container_id, owner):
            continue
        with suppress(ContainerCleanupUncertain):
            _control(
                docker,
                "stop",
                "--time",
                str(grace_seconds),
                container_id,
                timeout=grace_seconds + 3,
            )
        if _owned_running(docker, container_id, owner):
            _control(docker, "kill", container_id)
        if _owned_running(docker, container_id, owner):
            raise ContainerCleanupUncertain("owned container remains running after stop and kill")


def _reap_cli(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _mark_uncertain(output: Path, owner: str, reason: str) -> None:
    _write_atomic(
        output / _CLEANUP_MARKER,
        {
            "profile": "exulanica.gsplat-container-cleanup/v1",
            "owner_label": owner,
            "cidfile": f".containers/{owner}.cid",
            "reason": reason,
        },
    )
    descriptor = os.open(output, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def reconcile_container_cleanup(output: Path, *, docker: str = "docker") -> None:
    marker = output / _CLEANUP_MARKER
    if not marker.exists():
        return
    try:
        value = json.loads(marker.read_text())
        owner = value["owner_label"]
        if (
            value.get("profile") != "exulanica.gsplat-container-cleanup/v1"
            or not isinstance(owner, str)
            or not re.fullmatch(r"[0-9a-f]{32}", owner)
        ):
            raise ValueError("no verified ownership record")
        cidfile = output / ".containers" / f"{owner}.cid"
        _stop_owned(docker, cidfile, owner, 10)
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ContainerCleanupUncertain(
            "prior container cleanup requires ownership review"
        ) from error
    marker.unlink()
    cidfile.unlink(missing_ok=True)


def run_managed_container(
    command: tuple[str, ...],
    *,
    output: Path,
    cidfile: Path,
    owner: str,
    docker: str = "docker",
    grace_seconds: int = 15,
    startup_wait_seconds: float = 5,
) -> int:
    """Stop the owned daemon container before exit; code76 forbids scratch cleanup."""
    from typing import Any

    # Ownership must survive abrupt launcher death, including before Docker writes its cidfile.
    _mark_uncertain(output, owner, "launch active; owned daemon cleanup not yet confirmed")
    process: subprocess.Popen[bytes] | None = None
    requested_at: float | None = None

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal requested_at
        if requested_at is None:
            requested_at = time.monotonic()

    handlers = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        process = subprocess.Popen(command)
        stopped = False
        while process.poll() is None:
            if requested_at is not None:
                if cidfile.exists():
                    _stop_owned(docker, cidfile, owner, grace_seconds)
                    stopped = True
                    break
                if time.monotonic() - requested_at >= startup_wait_seconds:
                    raise ContainerCleanupUncertain(
                        "launch stopped before container ownership settled"
                    )
            time.sleep(0.05)
        if not stopped:
            # A disconnected Docker CLI can exit while its daemon-managed container continues.
            _stop_owned(docker, cidfile, owner, grace_seconds)
        try:
            returncode = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _reap_cli(process)
            returncode = process.returncode
        cidfile.unlink(missing_ok=True)
        (output / _CLEANUP_MARKER).unlink()
        return int(returncode)
    except (ContainerCleanupUncertain, OSError) as error:
        # Write first: even killing the local CLI is not proof that Docker stopped the GPU job.
        _mark_uncertain(output, owner, str(error))
        if process is not None:
            _reap_cli(process)
        return UNCERTAIN_CLEANUP_EXIT
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["train"])
    parser.add_argument("--profile", choices=[RUNNER_PROFILE], required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pose-receipt", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", choices=["auto"], required=True)
    args = parser.parse_args(argv)
    manifest = read_manifest(args.manifest)
    _verify_dataset_sources(manifest, args.dataset)
    _verify_pose_receipt(manifest, args.pose_receipt, args.dataset)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "container-launch.lock").open("a+b") as launch_lock:
        try:
            fcntl.flock(launch_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # A live owner already protects this output and its cleanup marker.
            return UNCERTAIN_CLEANUP_EXIT
        return _launch(args, manifest)


def _launch(args: argparse.Namespace, manifest: SplatBuildManifest) -> int:
    try:
        reconcile_container_cleanup(args.output)
    except ContainerCleanupUncertain:
        return UNCERTAIN_CLEANUP_EXIT
    owner = uuid.uuid4().hex
    container_ids = args.output / ".containers"
    container_ids.mkdir(exist_ok=True)
    cidfile = container_ids / f"{owner}.cid"
    command = container_command(
        manifest,
        manifest_path=args.manifest,
        pose_receipt=args.pose_receipt,
        dataset=args.dataset,
        output=args.output,
        cidfile=cidfile,
        owner_label=owner,
    )
    return run_managed_container(
        command,
        output=args.output,
        cidfile=cidfile,
        owner=owner,
    )


if __name__ == "__main__":
    raise SystemExit(main())
