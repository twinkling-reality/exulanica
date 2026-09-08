#!/usr/bin/env python3
"""Verify a saved bundle and capture-ID-named downloads without database access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from exulanica.canonical import canonical_json
from exulanica.graph.world_read_verification import EvidenceError, verify_downloads


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--downloads", required=True, type=Path)
    parser.add_argument("--at", required=True)
    parser.add_argument("--expected-bundle-sha256", required=True)
    args = parser.parse_args()
    try:
        envelope = json.loads(args.bundle.read_bytes())
        downloads = {path.stem: path.read_bytes() for path in args.downloads.glob("*.image")}
        result = verify_downloads(
            envelope, downloads, at=args.at, expected_bundle_sha256=args.expected_bundle_sha256
        )
    except (EvidenceError, ValueError, OSError) as error:
        reason = str(error) if isinstance(error, EvidenceError) else "view_package_unreadable"
        print(canonical_json({"state": "invalid", "reason": reason}).decode(), file=sys.stderr)
        raise SystemExit(1) from None
    print(canonical_json(result).decode())


if __name__ == "__main__":
    main()
