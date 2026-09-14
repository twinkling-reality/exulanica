#!/usr/bin/env python3
"""Download and compile the bounded Flatiron owned-world district."""

from __future__ import annotations

import argparse
from pathlib import Path

from exulanica.environment.owned_district import (
    BUILDING_DATASET,
    SIDEWALK_DATASET,
    compile_district,
    download_layer,
    write_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--building-file", type=Path)
    parser.add_argument("--sidewalk-file", type=Path)
    parser.add_argument("--building-revision")
    parser.add_argument("--sidewalk-revision")
    parser.add_argument(
        "--interpretation-from",
        type=Path,
        help="Compile only the optional interpretation from exact retained v1 bytes",
    )
    args = parser.parse_args()
    if args.interpretation_from:
        if any(
            (args.building_file, args.sidewalk_file, args.building_revision, args.sidewalk_revision)
        ):
            parser.error("--interpretation-from cannot be combined with source layer options")
        from exulanica.environment.district_interpretation import (
            compile_interpretation,
            validate_interpretation,
        )

        base_bytes = args.interpretation_from.read_bytes()
        result = compile_interpretation(base_bytes)
        document = validate_interpretation(result, base_bytes)
        args.destination.mkdir(parents=True, exist_ok=True)
        output = args.destination / "district-interpretation.json"
        if output.resolve() == args.interpretation_from.resolve():
            parser.error("interpretation output must not overwrite its source")
        output.write_bytes(result)
        print(f"interpretation={document.document_sha256}")
        print(f"navigation_nodes={len(document.navigation.nodes)}")
        return 0

    supplied = args.building_file is not None or args.sidewalk_file is not None
    if supplied and not all(
        (
            args.building_file,
            args.sidewalk_file,
            args.building_revision,
            args.sidewalk_revision,
        )
    ):
        parser.error("offline compilation requires both files and both provider revisions")

    if supplied:
        from exulanica.environment.owned_district import DownloadedLayer

        buildings = DownloadedLayer(
            BUILDING_DATASET,
            args.building_file.read_bytes(),
            f"https://data.cityofnewyork.us/resource/{BUILDING_DATASET}.geojson",
            args.building_revision,
        )
        sidewalks = DownloadedLayer(
            SIDEWALK_DATASET,
            args.sidewalk_file.read_bytes(),
            f"https://data.cityofnewyork.us/resource/{SIDEWALK_DATASET}.geojson",
            args.sidewalk_revision,
        )
    else:
        buildings = download_layer(BUILDING_DATASET)
        sidewalks = download_layer(SIDEWALK_DATASET)

    compiled = compile_district(buildings, sidewalks)
    write_bundle(args.destination, buildings, sidewalks, compiled)
    print(f"buildings={compiled.buildings}")
    print(f"sidewalks={compiled.sidewalks}")
    print(f"artifact_bytes={len(compiled.data)}")
    print(f"destination={args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
