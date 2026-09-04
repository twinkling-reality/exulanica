"""Write a digest-bound comparison of a production pose receipt to synthetic camera truth."""

from __future__ import annotations

import argparse
from pathlib import Path

from exulanica.evaluation.synthetic_pose import evaluate_synthetic_pose


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--camera-manifest", type=Path, required=True)
    parser.add_argument("--pose-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate_synthetic_pose(
        source_manifest_path=args.source_manifest,
        camera_manifest_path=args.camera_manifest,
        pose_receipt_path=args.pose_receipt,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result.to_bytes())
    print(f"synthetic pose evaluation {result.record_sha256} written to {args.output}")


if __name__ == "__main__":
    main()
