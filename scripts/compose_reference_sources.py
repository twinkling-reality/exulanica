"""Bind a reviewed source selection to one explicitly chosen existing Atlas region."""

import argparse
import json
import uuid
from pathlib import Path

from exulanica.db import Database
from exulanica.evaluation.reference_inputs import read_manifest
from exulanica.graph.scene_groups import scene_group_rows
from exulanica.ingest.repository import IngestRepository
from exulanica.orchestration.reference_world import compose_reference_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--directory", type=Path, help="Prepared inputs/intake output directory")
    parser.add_argument("--region", help="Required when the live graph has more than one region")
    args = parser.parse_args()
    root = args.directory or Path(".exulanica/reference-baseline") / args.scene
    manifest = read_manifest(root / "inputs.json")
    intake = json.loads((root / "intake.json").read_bytes())
    if intake["source_manifest_sha256"] != manifest["record_sha256"] or intake["refused"]:
        raise ValueError("only complete exact intake can be composed")
    accepted = {row["blob_sha256"]: row for row in intake["accepted"]}
    with Database.from_env().session(args.workspace) as connection:
        regions = scene_group_rows(connection, args.workspace)
        available = {str(region.group_id) for region in regions}
        if args.region is None and len(available) != 1:
            raise ValueError(
                f"choose an existing region explicitly with --region; available={sorted(available)}"
            )
        region = args.region or next(iter(available))
        if region not in available:
            raise ValueError("requested region is not in the current workspace graph")
        record = compose_reference_sources(
            IngestRepository(connection, args.workspace),
            region_id=region,
            captures=[
                (uuid.UUID(accepted[item["sha256"]]["capture_id"]), item["sha256"], item["path"])
                for item in manifest["record"]["files"]
            ],
            source_manifest_sha256=manifest["record_sha256"],
        )
    (root / "world-composition.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"Registered {len(record['record']['source_slots'])} exact source slots in {region}.")


if __name__ == "__main__":
    main()
