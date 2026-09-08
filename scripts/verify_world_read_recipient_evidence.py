#!/usr/bin/env python3
"""Verify a saved World Read response in a fresh process without a database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from exulanica.canonical import canonical_json
from exulanica.graph.world_read_verification import EvidenceError, verify


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--at", required=True)
    parser.add_argument("--expected-bundle-sha256", required=True)
    args = parser.parse_args()
    try:
        result = verify(
            json.loads(args.bundle.read_bytes()),
            at=args.at,
            expected_bundle_sha256=args.expected_bundle_sha256,
        )
    except (EvidenceError, json.JSONDecodeError, OSError) as error:
        reason = (
            str(error)
            if isinstance(error, EvidenceError)
            else "bundle_unreadable"
            if isinstance(error, OSError)
            else "bundle_invalid_json"
        )
        print(canonical_json({"state": "invalid", "reason": reason}).decode(), file=sys.stderr)
        raise SystemExit(1) from None
    print(canonical_json(result).decode())


if __name__ == "__main__":
    main()
