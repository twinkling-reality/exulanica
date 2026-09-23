"""Validate or publish a reviewed reusable asset through the existing authenticated catalog."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import psycopg

from exulanica.env import env_get, resolve_data_dir
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.asset_import import (
    MAX_ASSET_BYTES,
    MAX_LICENCE_BYTES,
    ReviewedAssetImport,
    import_reviewed_asset,
    validate_asset_import,
)
from exulanica.world.asset_kinds import ASSET_KINDS, AssetKind


def read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"{path.name} exceeds its import budget")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument("--licence", type=Path, required=True)
    parser.add_argument(
        "--kind",
        required=True,
        choices=[kind.value for kind in AssetKind],
        help="What the asset is for, declared rather than inferred: "
        + "; ".join(f"{kind.value}: {ASSET_KINDS[kind].summary}" for kind in AssetKind),
    )
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Publish to EXULANICA_DATABASE_URL and the configured blob store; otherwise validate only",
    )
    args = parser.parse_args()
    manifest = ReviewedAssetImport.model_validate_json(read_bounded(args.manifest, 64 * 1024))
    payload = read_bounded(args.asset, MAX_ASSET_BYTES)
    licence = read_bounded(args.licence, MAX_LICENCE_BYTES)
    receipt = validate_asset_import(manifest, payload, licence)
    receipt_sha = hashlib.sha256(receipt).hexdigest()
    if args.apply:
        url = env_get("DATABASE_URL")
        if not url:
            parser.error("EXULANICA_DATABASE_URL is required for publication")
        store = LocalContentAddressedStore(resolve_data_dir(explicit=args.data_dir) / "blobs")
        with psycopg.connect(url) as connection:
            import_reviewed_asset(
                connection, store, manifest, payload, licence, kind=AssetKind(args.kind)
            )
    print(
        f"{'Published' if args.apply else 'Validated'} {manifest.asset_key}; receipt {receipt_sha}"
    )


if __name__ == "__main__":
    main()
