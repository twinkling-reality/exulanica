#!/usr/bin/env python3
"""Write a digest-bound ETH3D camera-pose comparison for a production receipt."""

from __future__ import annotations

import argparse
from pathlib import Path

from exulanica.evaluation.benchmark_pose import evaluate_benchmark_pose


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--pose-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate_benchmark_pose(
        benchmark_root=args.benchmark_root,
        pose_receipt_path=args.pose_receipt,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result.to_bytes())
    print(f"benchmark pose evaluation {result.record_sha256} written to {args.output}")


if __name__ == "__main__":
    main()
