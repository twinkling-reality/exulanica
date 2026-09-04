#!/usr/bin/env python3
"""Acquire and verify the licensed ETH3D pipes validation scene."""

from __future__ import annotations

import argparse
from pathlib import Path

from exulanica.evaluation.benchmark import acquire_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    fixture = acquire_benchmark(args.destination)
    print(f"source_manifest_sha256={fixture.source_manifest_digest}")
    print(f"images={fixture.image_directory}")
    print(f"receipt={fixture.acquisition_receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
