#!/usr/bin/env python3
"""Prepare a private partial-surface candidate from current authorized scene segments.

Uses EXULANICA_DATABASE_URL and existing workspace policy. Never publishes an asset, registers
new rights, trains a model or changes source geometry. The output is not a permission receipt.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import uuid

from exulanica.db import Database
from exulanica.environment.scene_extraction import ExtractionPolicy, prepare_current_surface
from exulanica.env import resolve_data_dir
from exulanica.store.local import LocalContentAddressedStore


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    parser.add_argument("--scene", type=uuid.UUID, required=True)
    parser.add_argument("--segment", required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-source-maps", type=int, default=4)
    parser.add_argument("--samples-per-map", type=int, default=25000)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if output.exists() or any(
        a.name == "evaluation" and a.parent.name == "docs" for a in (output, *output.parents)
    ):
        parser.error("output must be a new private directory outside immutable evaluation paths")
    policy = ExtractionPolicy(args.max_source_maps, args.samples_per_map)
    store_path = resolve_data_dir(explicit=args.data_dir).resolve() / "blobs"
    if not store_path.is_dir():
        parser.error("existing source blob store is required")
    store = LocalContentAddressedStore(store_path)
    with Database.from_env().session(args.workspace) as connection:
        candidate = prepare_current_surface(
            connection,
            store,
            workspace=args.workspace,
            scene=args.scene,
            segment_id=args.segment,
            policy=policy,
        )
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, data in (
        ("candidate.json", candidate.manifest),
        ("surface.ply", candidate.points_ply),
    ):
        with (output / name).open("xb") as stream:
            stream.write(data)
        (output / name).chmod(0o600)
    manifest = json.loads(candidate.manifest)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "document_sha256": manifest["document_sha256"],
                "points": manifest["geometry"]["points"],
                "publication_authorized": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
