#!/usr/bin/env python3
"""Generate Exulanica's deterministic synthetic multi-view regression corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from exulanica.evaluation.synthetic_multiview import (
    SyntheticFixtureParameters,
    generate_synthetic_multiview,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", type=int, default=20260904)
    arguments = parser.parse_args()
    fixture = generate_synthetic_multiview(
        arguments.output,
        SyntheticFixtureParameters(seed=arguments.seed),
    )
    print(
        json.dumps(
            {
                "camera_manifest_sha256": fixture.camera_manifest_digest,
                "scene_manifest_sha256": fixture.scene_manifest_digest,
                "source_manifest_sha256": fixture.source_manifest_digest,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
