"""Queue a reviewed reference through the production exact-set reconstruction boundary."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import uuid
from pathlib import Path

from exulanica.db import Database
from exulanica.evaluation.reference_inputs import read_manifest
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.scene_selection import enqueue_exact_scene_reconstruction
from exulanica.ingest.scene_splat import SceneSplatRequest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    parser.add_argument("--actor", type=uuid.UUID, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--training-request", type=Path)
    parser.add_argument(
        "--worker-command",
        nargs=argparse.REMAINDER,
        help="launch this command after queueing; --once, --job and --workspace are supplied",
    )
    args = parser.parse_args()
    if args.worker_command is not None:
        if not args.worker_command:
            parser.error("--worker-command requires an executable")
        if any(
            value.startswith(("--job", "--workspace"))
            or (
                value.startswith("--")
                and any(
                    option.startswith(value.split("=", 1)[0]) for option in ("--job", "--workspace")
                )
            )
            for value in args.worker_command
        ):
            parser.error("worker command must not override the queued job or workspace")
    manifest = read_manifest(args.directory / "inputs.json")
    intake = json.loads((args.directory / "intake.json").read_bytes())
    if intake["source_manifest_sha256"] != manifest["record_sha256"] or intake["refused"]:
        raise ValueError("intake must cover the frozen source set")
    accepted = {row["blob_sha256"]: row for row in intake["accepted"]}
    if set(accepted) != {row["sha256"] for row in manifest["record"]["files"]}:
        raise ValueError("intake differs from the frozen source set")
    training = None
    if args.training_request:
        training = SceneSplatRequest.from_payload(json.loads(args.training_request.read_bytes()))
        if set(training.heldout_source_sha256) != set(
            manifest["record"]["evaluation_split"]["heldout_sha256"]
        ):
            raise ValueError("training request changes the frozen held-out split")
    with Database.from_env().session(args.workspace) as connection:
        selected = enqueue_exact_scene_reconstruction(
            IngestRepository(connection, args.workspace),
            [
                uuid.UUID(accepted[row["sha256"]]["capture_id"])
                for row in manifest["record"]["files"]
            ],
            actor=args.actor,
            purpose="retained reference reconstruction and declared visual evaluation",
            authorized_at=dt.datetime.now(dt.UTC),
            splat_training=training,
        )
        if selected is None:
            raise ValueError(
                "scene is not ready: exact human screening and current point maps are required"
            )
    result = {
        "source_manifest_sha256": manifest["record_sha256"],
        "job_id": str(selected.job_id),
        "member_count": selected.member_count,
        "inserted": selected.inserted,
        "splat_requested": training is not None,
    }
    (args.directory / "reconstruction-job.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if args.worker_command is not None:
        # The worker parser unions flags and environment; replace inherited scope so an old
        # deployment setting cannot spend another job's final attempt during this pass.
        environment = dict(os.environ)
        environment["EXULANICA_SCENE_JOB_IDS"] = str(selected.job_id)
        environment["EXULANICA_WORKSPACE_IDS"] = str(args.workspace)
        return subprocess.call(
            [
                *args.worker_command,
                "--once",
                "--job",
                str(selected.job_id),
                "--workspace",
                str(args.workspace),
            ],
            env=environment,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
