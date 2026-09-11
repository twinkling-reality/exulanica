"""The production derivative worker command.

It owns no HTTP surface and accepts no bytes. Workspaces are deployment configuration, jobs carry
capture identifiers, and the content-addressed store is the only place source bytes are read.
"""

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
from typing import Any, Final

from exulanica.db.migrate import verify_schema
from exulanica.db.roles import assert_runtime_role
from exulanica.db.session import Database
from exulanica.env import env_get, env_name, resolve_data_dir
from exulanica.ingest.vision import NebiusVisionModel
from exulanica.ingest.worker import DerivativeWorker, lease_seconds_for
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role
from exulanica.store.local import LocalContentAddressedStore

__all__ = [
    "DATA_DIR_ENV",
    "DEPTH_MODEL_ENV",
    "PERSON_DETECTOR_ENV",
    "SEGMENTATION_DEVICE_ENV",
    "SEGMENTATION_MODEL_ENV",
    "WORKSPACES_ENV",
    "main",
    "parse_workspaces",
]

WORKSPACES_ENV: Final = env_name("WORKSPACE_IDS")
DATA_DIR_ENV: Final = env_name("DATA_DIR")
MODEL_KEY_ENV: Final = "NEBIUS_API_KEY"
DEPTH_MODEL_ENV: Final = env_name("DEPTH_MODEL")
PERSON_DETECTOR_ENV: Final = env_name("PERSON_DETECTOR")
DEPTH_MODEL_ID_ENV: Final = env_name("DEPTH_MODEL_ID")
DEPTH_MODEL_REVISION_ENV: Final = env_name("DEPTH_MODEL_REVISION")
DEPTH_DEVICE_ENV: Final = env_name("DEPTH_DEVICE")
SEGMENTATION_MODEL_ENV: Final = env_name("SEGMENTATION_MODEL")
SEGMENTATION_DEVICE_ENV: Final = env_name("SEGMENTATION_DEVICE")


def parse_workspaces(values: list[str], environ: Mapping[str, str]) -> frozenset[uuid.UUID]:
    """Resolve explicit flags plus a comma-separated deployment value, refusing an empty set."""
    raw = list(values)
    raw.extend(
        part.strip()
        for part in (env_get("WORKSPACE_IDS", environ) or "").split(",")
        if part.strip()
    )
    try:
        workspaces = frozenset(uuid.UUID(value) for value in raw)
    except ValueError as exc:
        raise ValueError(f"{WORKSPACES_ENV} and --workspace accept UUIDs only: {exc}") from exc
    if not workspaces:
        raise ValueError(
            f"no workspace was configured. Set {WORKSPACES_ENV} or pass --workspace; a worker "
            "that silently drains nothing is not healthy."
        )
    return workspaces


def _worker_name(value: str | None) -> str:
    if value:
        return value
    host = platform.node() or "unknown"
    return f"{host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _emit(stream: Any, event: str, **fields: Any) -> None:
    print(
        json.dumps({"component": "derivative-worker", "event": event, **fields}, sort_keys=True),
        file=stream,
        flush=True,
    )


def _build_worker(args: argparse.Namespace, environ: Mapping[str, str]) -> DerivativeWorker:
    database = Database.from_env(environ)
    verify_schema(database)
    with database.unscoped() as connection:
        assert_runtime_role(connection)

    client = ModelClient(max_attempts=1) if environ.get(MODEL_KEY_ENV) else None
    vision = NebiusVisionModel(client) if client is not None else None
    depth = _build_depth(environ)
    detector = _build_detector(environ)
    segmenter = _build_segmenter(environ)
    lease_seconds = lease_seconds_for(
        client.worst_case_seconds(Role.VISION) if client is not None else None
    )
    data_dir = resolve_data_dir(environ)
    return DerivativeWorker(
        database,
        LocalContentAddressedStore(data_dir / "blobs"),
        parse_workspaces(args.workspace, environ),
        vision=vision,
        depth=depth,
        detector=detector,
        segmenter=segmenter,
        name=_worker_name(args.name),
        poll_seconds=args.poll_seconds,
        lease_seconds=lease_seconds,
    )


def _build_depth(environ: Mapping[str, str]) -> Any:
    mode = (env_get("DEPTH_MODEL", environ) or "unavailable").strip().lower()
    if mode == "unavailable":
        return None
    if mode != "moge":
        raise ValueError(f"{DEPTH_MODEL_ENV} must be 'moge' or 'unavailable', not {mode!r}")
    from exulanica.ingest.stages import stage
    from exulanica.reconstruction.moge import (
        DEFAULT_MOGE_MODEL,
        DEFAULT_MOGE_REVISION,
        MoGeDepthModel,
    )

    revision = env_get("DEPTH_MODEL_REVISION", environ) or DEFAULT_MOGE_REVISION
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise ValueError(f"{DEPTH_MODEL_REVISION_ENV} must be a full lowercase Git commit")

    return MoGeDepthModel(
        model_id=env_get("DEPTH_MODEL_ID", environ) or DEFAULT_MOGE_MODEL,
        revision=revision,
        max_edge_px=int(stage("depth").params["max_edge_px"]),
        device=env_get("DEPTH_DEVICE", environ) or None,
    )


def _build_segmenter(environ: Mapping[str, str]) -> Any:
    """Resolve the local object segmenter, defaulting to none configured.

    ``local`` loads SAM 2.1 and its detectors from the manifest's ``local_roles``, re-reading each
    pinned licence first; there is no model or revision override here, because the checkpoints are
    manifest data and a swap re-keys every mask. A missing ``segmentation`` extra or a licence
    drift is a startup failure, not a worker that quietly segments nothing.

    It is built here and nowhere else. This is the process that already holds torch for depth,
    and pycolmap and torch cannot share a process on macOS (``pycolmap_executor.py``), so the scene
    worker never loads a segmenter: it lifts the masks this one wrote, with numpy alone.
    """
    mode = (env_get("SEGMENTATION_MODEL", environ) or "unavailable").strip().lower()
    if mode == "unavailable":
        return None
    if mode != "local":
        raise ValueError(f"{SEGMENTATION_MODEL_ENV} must be 'local' or 'unavailable', not {mode!r}")
    from exulanica.ingest.stages.segmentation import LocalObjectSegmenter

    return LocalObjectSegmenter(device=env_get("SEGMENTATION_DEVICE", environ) or None)


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stream: Any = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="exulanica-derivative-worker",
        description="Drain PostgreSQL derivative jobs with renewable leases and durable events.",
    )
    parser.add_argument(
        "--workspace", action="append", default=[], help="workspace UUID; repeatable"
    )
    parser.add_argument("--name", help="stable worker identifier; generated when omitted")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--grace-seconds", type=float, default=900.0)
    parser.add_argument(
        "--once", action="store_true", help="drain currently eligible work and exit"
    )
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    environment = os.environ if environ is None else environ

    try:
        worker = _build_worker(args, environment)
    except Exception as exc:
        _emit(output, "startup_failed", failure_class=type(exc).__name__, message=str(exc))
        return 1

    _emit(
        output,
        "startup",
        worker=worker.name,
        workspaces=worker.workspace_count,
        mode="once" if args.once else "daemon",
    )
    if args.once:
        try:
            outcomes = worker.drain_observed()
        except Exception as exc:
            _emit(output, "pass_failed", failure_class=type(exc).__name__, message=str(exc))
            return 1
        _emit(
            output,
            "stopped",
            jobs=len(outcomes),
            failed=sum(outcome.failed for outcome in outcomes),
            cancelled=sum(outcome.cancelled for outcome in outcomes),
            unavailable=sum(outcome.unavailable for outcome in outcomes),
        )
        return 0

    requested = threading.Event()

    def request_shutdown(signum: int, _frame: Any) -> None:
        _emit(output, "shutdown_requested", signal=signal.Signals(signum).name)
        requested.set()

    previous = {
        signum: signal.signal(signum, request_shutdown)
        for signum in (signal.SIGTERM, signal.SIGINT)
    }
    worker.start()
    try:
        while not requested.wait(0.5):
            if not worker.alive:
                _emit(output, "worker_stopped_unexpectedly", last_error=worker.last_error)
                return 1
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)

    clean = worker.stop(timeout=args.grace_seconds)
    if not clean:
        _emit(
            output,
            "shutdown_timed_out",
            grace_seconds=args.grace_seconds,
            message="the held lease will expire and another worker will reclaim the job",
        )
        return 2
    _emit(output, "stopped", failed_passes=worker.failed_passes)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


def _build_detector(environ: Mapping[str, str]) -> Any:
    """Resolve the person detector, defaulting to none configured.

    Defaulting to ``unavailable`` rather than to the recorded-observation adapter is deliberate.
    A worker that quietly started proposing person regions would start refusing point maps over
    every photograph it found somebody in, which is the correct behaviour and a bad surprise; an
    operator turns it on, and the stage says plainly that nothing looked until they do.
    """
    mode = (env_get("PERSON_DETECTOR", environ) or "unavailable").strip().lower()
    if mode == "unavailable":
        return None
    if mode != "recorded-observation":
        raise ValueError(
            f"{PERSON_DETECTOR_ENV} must be 'recorded-observation' or 'unavailable', not {mode!r}"
        )
    from exulanica.ingest.person_detectors import RecordedObservationDetector

    return RecordedObservationDetector()
