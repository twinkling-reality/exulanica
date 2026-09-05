"""Command line for the separate pycolmap reconstruction-scene worker."""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import sys
import threading
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from exulanica.db.migrate import verify_schema
from exulanica.db.roles import assert_runtime_role
from exulanica.db.session import Database
from exulanica.env import env_get, env_name, resolve_data_dir
from exulanica.ingest.scene_worker import SceneReconstructionWorker
from exulanica.ingest.worker_command import parse_workspaces
from exulanica.store.local import LocalContentAddressedStore

__all__ = ["JOB_IDS_ENV", "main", "parse_job_ids"]

CODE_REVISION_ENV: Final = env_name("CODE_REVISION")
POSE_IMAGE_ENV: Final = env_name("POSE_RUNTIME_IMAGE")
JOB_IDS_ENV: Final = env_name("SCENE_JOB_IDS")


def parse_job_ids(values: list[str], environment: Mapping[str, str]) -> frozenset[uuid.UUID] | None:
    """Resolve explicit ``--job`` flags plus a comma-separated deployment value.

    Nothing configured means the worker drains its workspaces as before. Anything
    configured must parse as UUIDs; a typo that silently widened the scope back to
    every job would defeat the reason an operator named jobs at all.
    """
    raw = list(values)
    raw.extend(
        part.strip()
        for part in (env_get("SCENE_JOB_IDS", environment) or "").split(",")
        if part.strip()
    )
    if not raw:
        return None
    try:
        return frozenset(uuid.UUID(value) for value in raw)
    except ValueError as exc:
        raise ValueError(f"{JOB_IDS_ENV} and --job accept UUIDs only: {exc}") from exc


def _required(environment: Mapping[str, str], name: str) -> str:
    suffix = name.removeprefix("EXULANICA_")
    value = env_get(suffix, environment)
    if not value:
        raise ValueError(f"{name} is required for a provenance-complete pose manifest")
    return value


def _worker_name(value: str | None) -> str:
    return value or f"{platform.node() or 'unknown'}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _emit(stream: Any, event: str, **fields: Any) -> None:
    print(
        json.dumps({"component": "scene-worker", "event": event, **fields}, sort_keys=True),
        file=stream,
        flush=True,
    )


def _worker_data_directory(environment: Mapping[str, str]) -> Path:
    """Keep pycolmap source paths stable after its executor changes directories."""
    return resolve_data_dir(environment).resolve()


def _build(
    args: argparse.Namespace, environment: Mapping[str, str]
) -> SceneReconstructionWorker:
    database = Database.from_env(environment)
    verify_schema(database)
    with database.unscoped() as connection:
        assert_runtime_role(connection)
    data_directory = _worker_data_directory(environment)
    return SceneReconstructionWorker(
        database,
        LocalContentAddressedStore(data_directory / "blobs"),
        data_directory / "reconstruction-scratch",
        parse_workspaces(args.workspace, environment),
        name=_worker_name(args.name),
        code_revision=_required(environment, CODE_REVISION_ENV),
        execution_image=_required(environment, POSE_IMAGE_ENV),
        lease_seconds=args.lease_seconds,
        heartbeat_seconds=args.heartbeat_seconds,
        abandoned_after_seconds=args.abandoned_after_seconds,
        job_ids=parse_job_ids(args.job, environment),
    )


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stream: Any = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="exulanica-scene-worker",
        description="Drain exact scene sets through checkpointed camera-pose recovery.",
    )
    parser.add_argument("--workspace", action="append", default=[])
    parser.add_argument(
        "--job",
        action="append",
        default=[],
        help="claim only this scene job (repeatable); default drains the workspaces",
    )
    parser.add_argument("--name")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--lease-seconds", type=float, default=900.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument("--abandoned-after-seconds", type=float, default=3600.0)
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    environment = os.environ if environ is None else environ
    try:
        worker = _build(args, environment)
        removed = worker.cleanup_abandoned()
    except Exception as error:
        _emit(output, "startup_failed", failure_class=type(error).__name__, message=str(error))
        return 1
    _emit(
        output,
        "startup",
        worker=worker.name,
        removed_scratch=len(removed),
        **({} if worker.job_ids is None else {"job_ids": sorted(map(str, worker.job_ids))}),
    )
    requested = threading.Event()

    def stop(signum: int, _frame: Any) -> None:
        _emit(output, "shutdown_requested", signal=signal.Signals(signum).name)
        requested.set()
        worker.request_stop()

    previous = {
        signum: signal.signal(signum, stop) for signum in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        if args.once:
            outcomes = worker.drain_observed()
            _emit(
                output,
                "stopped",
                jobs=len(outcomes),
                succeeded=sum(outcome.status == "succeeded" for outcome in outcomes),
                failed=sum(outcome.status == "failed" for outcome in outcomes),
                cancelled=sum(outcome.status == "cancelled" for outcome in outcomes),
            )
            return 1 if any(outcome.status == "failed" for outcome in outcomes) else 0
        while not requested.is_set():
            outcomes = worker.drain_observed()
            if any(outcome.status == "failed" for outcome in outcomes):
                _emit(output, "pass_failed", jobs=len(outcomes))
            requested.wait(args.poll_seconds)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    _emit(output, "stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
