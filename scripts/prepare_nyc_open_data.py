#!/usr/bin/env python3
"""Download and deterministically prepare the bounded NYC Building Footprints corridor."""

from __future__ import annotations

import argparse
from datetime import UTC
from email.utils import parsedate_to_datetime
from pathlib import Path

from exulanica.environment.nyc_open_data import (
    download_bounded,
    prepare,
    write_prepared,
)


def _iso_http_date(value: str, *, field: str) -> str:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is missing or is not an HTTP date") from exc
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--source-file",
        type=Path,
        help="prepare an already-downloaded exact response instead of making a public request",
    )
    parser.add_argument("--provider-revision")
    parser.add_argument("--retrieved-at")
    args = parser.parse_args()

    if args.source_file is None:
        if args.provider_revision or args.retrieved_at:
            parser.error("--provider-revision and --retrieved-at apply only with --source-file")
        downloaded = download_bounded()
        data = downloaded.data
        headers = downloaded.response_headers
        provider_revision = _iso_http_date(
            headers.get("x-soda2-truth-last-modified", ""),
            field="X-SODA2-Truth-Last-Modified",
        )
        retrieved_at = _iso_http_date(headers.get("date", ""), field="Date")
    else:
        if not args.provider_revision or not args.retrieved_at:
            parser.error("--source-file requires --provider-revision and --retrieved-at")
        data = args.source_file.read_bytes()
        headers = {}
        provider_revision = args.provider_revision
        retrieved_at = args.retrieved_at

    prepared = prepare(
        data,
        provider_revision=provider_revision,
        retrieval_timestamp=retrieved_at,
        response_headers=headers,
    )
    write_prepared(prepared, args.destination)
    print(f"source_sha256={prepared.source_sha256}")
    print(f"source_bytes={prepared.source_byte_size}")
    print(f"features={prepared.feature_count}")
    print(f"shards={len(prepared.shards)}")
    print(f"manifest_sha256={prepared.manifest.sha256}")
    print(f"destination={args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
