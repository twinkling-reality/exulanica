"""Publish and withdraw character catalogs: host administration, never a request.

    exulanica-character-catalog publish [--directory DIR] [--apply] [--data-dir DIR]
    exulanica-character-catalog withdraw --catalog-sha256 X --reason CODE [--apply]
    exulanica-character-catalog list

A catalog directory (``assets/characters`` in a checkout, whatever an installer ships elsewhere)
holds two kinds of catalog. The layered people catalog is ``catalog.json`` with its designed
``looks.json``; each family's containers carry reviewed import manifests beside their licence
(``imports.json``). Parametric families are listed in ``parametric-catalog.json``, one folder each,
whose published document :func:`~exulanica.world.character_parametric.parametric_family_document`
derives and measures.

Publishing runs in one transaction on the owner connection (``EXULANICA_DATABASE_URL``), in this
order: every container a document names is imported as a reviewed asset through
:func:`~exulanica.world.asset_import.import_reviewed_asset` (idempotent, and refusing any key bound
to other bytes); each prepared body's preparation receipt is put in the store; every asset is then
checked against the registry and the store; and only then is the publication row written
(migration 0131). A document already published is left as it is; a different document under a
published catalog id and revision is refused, as is a revision older than one already published.
Without ``--apply`` nothing is written and the documents are only derived and checked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.world.asset_import import (
    ReviewedAssetImport,
    import_reviewed_asset,
    validate_asset_import,
)
from exulanica.world.asset_kinds import AssetKind
from exulanica.world.character_appearance import CHARACTER_DIRECTORY, document_sha256
from exulanica.world.character_catalogs import (
    LAYERED_PROFILE,
    PARAMETRIC_PROFILE,
    CatalogPublication,
    PublicationRefused,
    layered_bundle,
    read_publication_document,
)
from exulanica.world.character_parametric import parametric_catalog, parametric_family_document

__all__ = [
    "Import",
    "PublishOutcome",
    "catalog_documents",
    "catalog_imports",
    "main",
    "publish_catalogs",
    "withdraw_catalog",
]

PARAMETRIC_SOURCE_PROFILE: Final = "exulanica.parametric-character-catalog-source/v1"
PRODUCER: Final = "exulanica-character-catalog/1"
#: Serialises publishers of every catalog, as 0131's revision trigger serialises one catalog id.
_PUBLISH_LOCK: Final = 119622331


@dataclass(frozen=True, slots=True)
class Import:
    """One container to publish as a reviewed asset, verified against its bytes and licence."""

    manifest: ReviewedAssetImport
    payload: bytes
    licence: bytes


@dataclass(frozen=True, slots=True)
class PublishOutcome:
    catalog_sha256: str
    catalog_id: str
    revision: int
    kind: str
    #: ``published`` when this call wrote the row, ``unchanged`` when it was already there.
    state: str


def _layered_assets(catalog: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    for family in catalog["families"]:
        for base in family["bases"]:
            yield base["asset"]
            for part in base["parts"]:
                if "asset" in part:
                    yield part["asset"]
        for material in family["materials"]:
            yield material["asset"]


def catalog_documents(directory: Path = CHARACTER_DIRECTORY) -> list[dict[str, Any]]:
    """Every publishable document in a catalog directory, derived and checked, oldest kind first."""
    documents: list[dict[str, Any]] = []
    catalog_path, looks_path = directory / "catalog.json", directory / "looks.json"
    if catalog_path.exists() or looks_path.exists():
        documents.append(
            layered_bundle(json.loads(catalog_path.read_text()), json.loads(looks_path.read_text()))
        )
    index_path = directory / "parametric-catalog.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
        if index.get("profile") != PARAMETRIC_SOURCE_PROFILE:
            raise PublicationRefused("parametric-catalog.json is not a parametric catalog source")
        families = [
            parametric_family_document(
                directory / entry["folder"], characters=directory, budget=entry["budget"]
            )
            for entry in index["families"]
        ]
        documents.append(
            parametric_catalog(families, revision=index["revision"], catalog_id=index["catalogId"])
        )
    for document in documents:
        read_publication_document(document)
    return documents


def catalog_imports(
    document: Mapping[str, Any], directory: Path = CHARACTER_DIRECTORY
) -> list[Import]:
    """Every container a document names, with its reviewed manifest and licence, each verified."""
    imports: list[Import] = []
    if document["profile"] == LAYERED_PROFILE:
        catalog = document["catalog"]
        manifests: dict[str, tuple[ReviewedAssetImport, bytes]] = {}
        for family in catalog["families"]:
            licence_path = directory / family["licence"]["file"]
            licence = licence_path.read_bytes()
            if hashlib.sha256(licence).hexdigest() != family["licence"]["sha256"]:
                raise PublicationRefused(f"{family['familyId']} licence digest changed")
            for manifest in json.loads((licence_path.parent / "imports.json").read_text()):
                manifests[manifest["asset_key"]] = (
                    ReviewedAssetImport.model_validate(manifest),
                    licence,
                )
        for asset in _layered_assets(catalog):
            imports.append(
                _verified(directory, asset["file"], asset, *manifests[asset["assetKey"]])
            )
        return imports
    for family in document["families"]:
        licence = (directory / family["licence"]["file"]).read_bytes()
        if hashlib.sha256(licence).hexdigest() != family["licence"]["sha256"]:
            raise PublicationRefused(f"{family['familyId']} licence digest changed")
        for representation in family["representations"]:
            asset = representation["asset"]
            folder = (directory / asset["file"]).parent
            manifest = ReviewedAssetImport.model_validate_json(
                (folder / (Path(asset["file"]).stem + ".import.json")).read_text()
            )
            imports.append(_verified(directory, asset["file"], asset, manifest, licence))
    return imports


def _verified(
    directory: Path,
    file: str,
    asset: Mapping[str, Any],
    manifest: ReviewedAssetImport,
    licence: bytes,
) -> Import:
    payload = (directory / file).read_bytes()
    if (len(payload), hashlib.sha256(payload).hexdigest()) != (
        asset["byteSize"],
        asset["contentSha256"],
    ) or manifest.asset_key != asset["assetKey"]:
        raise PublicationRefused(f"{file} does not match its catalog entry")
    validate_asset_import(manifest, payload, licence)
    return Import(manifest=manifest, payload=payload, licence=licence)


def _preparation_receipts(document: Mapping[str, Any], directory: Path) -> list[bytes]:
    """The canonical preparation receipt of each reviewed body a parametric document lists."""
    receipts = []
    if document["profile"] != PARAMETRIC_PROFILE:
        return receipts
    for family in document["families"]:
        for representation in family["representations"]:
            folder = (directory / representation["asset"]["file"]).parent
            look = json.loads((folder / "default.look.json").read_text())
            receipt = canonical_json(look["preparationReceipt"])
            if hashlib.sha256(receipt).hexdigest() != representation["preparationReceiptSha256"]:
                raise PublicationRefused("a reviewed body's preparation receipt changed")
            receipts.append(receipt)
    return receipts


def _check_published(
    connection: psycopg.Connection, store: ContentAddressedStore, imports: Sequence[Import]
) -> None:
    """Every container is a reviewed asset with these bytes and licence, and its bytes are held."""
    keys = [item.manifest.asset_key for item in imports]
    rows = {
        row["asset_key"]: row
        for row in connection.execute(
            "select a.asset_key,a.content_sha256,a.byte_size,a.licence_sha256 "
            "from world_reviewed_asset a "
            "join world_reviewed_asset_import i using(asset_key,content_sha256) "
            "where a.asset_key = any(%s)",
            (keys,),
        ).fetchall()
    }
    for item in imports:
        row = rows.get(item.manifest.asset_key)
        if row is None or (row["content_sha256"], row["byte_size"], row["licence_sha256"]) != (
            item.manifest.content_sha256,
            item.manifest.byte_size,
            item.manifest.licence_sha256,
        ):
            raise PublicationRefused(f"{item.manifest.asset_key} is not a reviewed asset here")
        for digest in (item.manifest.content_sha256, item.manifest.licence_sha256):
            if not store.exists(BlobId.from_hex(digest)):
                raise PublicationRefused(f"{item.manifest.asset_key} bytes are not in the store")


def _insert(connection: psycopg.Connection, publication: CatalogPublication) -> str:
    existing = connection.execute(
        "select catalog_sha256 from character_catalog_publication "
        "where catalog_sha256=%s or (catalog_id=%s and revision=%s)",
        (publication.catalog_sha256, publication.catalog_id, publication.revision),
    ).fetchall()
    if any(row["catalog_sha256"] == publication.catalog_sha256 for row in existing):
        return "unchanged"
    if existing:
        raise PublicationRefused(
            f"{publication.catalog_id} revision {publication.revision} is already published "
            "with another document; a changed catalog is a new revision"
        )
    connection.execute(
        "insert into character_catalog_publication"
        "(catalog_sha256,catalog_id,profile,kind,revision,document,producer) "
        "values(%s,%s,%s,%s,%s,%s,%s)",
        (
            publication.catalog_sha256,
            publication.catalog_id,
            publication.profile,
            publication.kind,
            publication.revision,
            Jsonb(publication.document),
            PRODUCER,
        ),
    )
    return "published"


def publish_catalogs(
    connection: psycopg.Connection,
    store: ContentAddressedStore,
    documents: Sequence[Mapping[str, Any]],
    directory: Path = CHARACTER_DIRECTORY,
) -> list[PublishOutcome]:
    """Import every container, then publish each document, in the caller's transaction."""
    if connection.autocommit and connection.info.transaction_status != TransactionStatus.INTRANS:
        raise PublicationRefused("catalog publication requires an explicit database transaction")
    connection.execute("select pg_advisory_xact_lock(%s)", (_PUBLISH_LOCK,))
    outcomes = []
    for document in documents:
        publication = read_publication_document(document)
        if document_sha256(document) != publication.catalog_sha256:
            raise PublicationRefused("a document's digest changed while it was published")
        imports = catalog_imports(document, directory)
        for item in imports:
            import_reviewed_asset(
                connection,
                store,
                item.manifest,
                item.payload,
                item.licence,
                kind=AssetKind.COMPONENT,
            )
        for receipt in _preparation_receipts(document, directory):
            held = store.put_bytes(receipt)
            if store.get(held.blob_id) != receipt:
                raise PublicationRefused("the store did not keep a preparation receipt exactly")
        _check_published(connection, store, imports)
        outcomes.append(
            PublishOutcome(
                catalog_sha256=publication.catalog_sha256,
                catalog_id=publication.catalog_id,
                revision=publication.revision,
                kind=publication.kind,
                state=_insert(connection, publication),
            )
        )
    return outcomes


def withdraw_catalog(connection: psycopg.Connection, catalog_sha256: str, reason: str) -> str:
    """Withdraw one publication for good; ``withdrawn`` now, ``unchanged`` if it already was."""
    known = connection.execute(
        "select 1 from character_catalog_publication where catalog_sha256=%s", (catalog_sha256,)
    ).fetchone()
    if known is None:
        raise PublicationRefused("no such published catalog")
    done = connection.execute(
        "select 1 from character_catalog_withdrawal where catalog_sha256=%s", (catalog_sha256,)
    ).fetchone()
    if done is not None:
        return "unchanged"
    connection.execute(
        "insert into character_catalog_withdrawal(catalog_sha256,reason) values(%s,%s)",
        (catalog_sha256, reason),
    )
    return "withdrawn"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exulanica-character-catalog", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish", help="derive, check and publish a catalog directory")
    publish.add_argument("--directory", type=Path, default=CHARACTER_DIRECTORY)
    publish.add_argument("--data-dir", type=Path)
    publish.add_argument("--apply", action="store_true", help="write; otherwise only check")
    withdraw = commands.add_parser("withdraw", help="withdraw one publication for good")
    withdraw.add_argument("--catalog-sha256", required=True)
    withdraw.add_argument("--reason", required=True)
    withdraw.add_argument("--apply", action="store_true")
    commands.add_parser("list", help="the publications this database holds")
    args = parser.parse_args(argv)

    if args.command == "publish" and not args.apply:
        for document in catalog_documents(args.directory):
            publication = read_publication_document(document)
            count = len(catalog_imports(document, args.directory))
            print(
                f"{publication.catalog_id} revision {publication.revision} "
                f"({publication.kind}) {publication.catalog_sha256}: {count} containers checked"
            )
        return 0

    from psycopg.rows import dict_row

    from exulanica.env import env_get
    from exulanica.store.configured import content_stores

    url = env_get("DATABASE_URL")
    if not url:
        parser.error("EXULANICA_DATABASE_URL is required")
    with psycopg.connect(url, row_factory=dict_row) as connection:
        if args.command == "list":
            for row in connection.execute(
                "select p.catalog_id,p.revision,p.kind,p.catalog_sha256,p.published_at,"
                "w.reason from character_catalog_publication p "
                "left join character_catalog_withdrawal w using(catalog_sha256) "
                "order by p.catalog_id,p.revision"
            ).fetchall():
                state = f"withdrawn ({row['reason']})" if row["reason"] else "served"
                print(
                    f"{row['catalog_id']} revision {row['revision']} ({row['kind']}) "
                    f"{row['catalog_sha256']} {state}"
                )
            return 0
        if args.command == "withdraw":
            if not args.apply:
                print(f"Would withdraw {args.catalog_sha256} ({args.reason})")
                return 0
            with connection.transaction():
                print(withdraw_catalog(connection, args.catalog_sha256, args.reason))
            return 0
        # The store this deployment's API serves from: local blobs, or the shared object store
        # EXULANICA_STORE_KIND names, built by the one configuration every process uses.
        stores = content_stores(data_dir=args.data_dir)
        try:
            documents = catalog_documents(args.directory)
            with connection.transaction():
                for outcome in publish_catalogs(
                    connection, stores.blobs, documents, args.directory
                ):
                    print(
                        f"{outcome.state}: {outcome.catalog_id} revision {outcome.revision} "
                        f"({outcome.kind}) {outcome.catalog_sha256}"
                    )
        finally:
            stores.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
