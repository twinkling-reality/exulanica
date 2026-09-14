#!/usr/bin/env python3
"""Print a read-only source-bound scene run plan or stage-specific blocker.

Uses EXULANICA_DATABASE_URL. Never allocates compute, queues work, writes a plan or changes
retained artifacts. Redirect stdout to a new private file if a saved report is needed.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from exulanica.db import Database
from exulanica.env import resolve_data_dir
from exulanica.orchestration.scene_run_preflight import RunResources, prepare_current_scene_run
from exulanica.store.local import LocalContentAddressedStore


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    parser.add_argument("--scene", type=uuid.UUID, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--pose-receipt", type=Path)
    parser.add_argument("--run-output", type=Path)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument(
        "--resources",
        type=Path,
        help="JSON RunResources with explicit allowances and dated quote inputs",
    )
    args = parser.parse_args(argv)
    root = resolve_data_dir(explicit=args.data_dir).resolve() / "blobs"
    if not root.is_dir():
        parser.error("existing source store is required; preflight creates nothing")
    try:
        resources = (
            RunResources(**json.loads(args.resources.read_bytes())) if args.resources else None
        )
        with Database.from_env().session(args.workspace) as connection:
            result = prepare_current_scene_run(
                connection,
                LocalContentAddressedStore(root),
                workspace=args.workspace,
                scene=args.scene,
                manifest_path=args.manifest,
                dataset=args.dataset,
                pose_receipt=args.pose_receipt,
                output=args.run_output,
                resources=resources,
                source_manifest=args.source_manifest,
            )
    except (ValueError, TypeError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    return 0 if result["status"] == "plan_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
