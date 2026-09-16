"""Import an explicitly reviewed CC0 asset without replacing its upstream provenance.

This is a host administration boundary, not an upload API or a licence classifier.
Asset decode, character rig compatibility and current subject authority remain separate.
"""

from __future__ import annotations

import hashlib
import json
import struct
from typing import Annotated, Literal

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StrictInt

from exulanica.canonical import canonical_json
from exulanica.store.base import ContentAddressedStore

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=1000, pattern=r"\S")]
MAX_ASSET_BYTES = 32 * 1024 * 1024
MAX_LICENCE_BYTES = 1024 * 1024


class ReviewedAssetImport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["exulanica.reviewed-asset-import/v1"]
    asset_key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9.-]{0,199}$")]
    title: Text
    summary: Text
    content_sha256: Digest
    byte_size: Annotated[StrictInt, Field(gt=0, le=MAX_ASSET_BYTES)]
    licence_id: Literal["CC0-1.0"]
    licence_sha256: Digest
    source_url: HttpUrl
    source_revision: Text
    producer: Text


def validate_import_container(payload: bytes) -> None:
    """Match the browser's self-contained, uncompressed GLB admission boundary.

    This does not certify glTF accessors, rigs, skin weights or asset quality.
    """
    if not 20 <= len(payload) <= MAX_ASSET_BYTES or len(payload) % 4:
        raise ValueError("asset must be an aligned GLB between 20 bytes and 32 MB")
    if struct.unpack_from("<III", payload) != (0x46546C67, 2, len(payload)):
        raise ValueError("invalid GLB version or declared length")
    chunks: list[tuple[int, bytes]] = []
    offset = 12
    while offset < len(payload):
        if offset + 8 > len(payload):
            raise ValueError("truncated GLB chunk header")
        length, kind = struct.unpack_from("<II", payload, offset)
        offset += 8
        if length % 4 or offset + length > len(payload):
            raise ValueError("invalid GLB chunk length")
        chunks.append((kind, payload[offset : offset + length]))
        offset += length
    if not 1 <= len(chunks) <= 2 or chunks[0][0] != 0x4E4F534A:
        raise ValueError("GLB requires JSON followed by optional BIN")
    if len(chunks) == 2 and chunks[1][0] != 0x004E4942:
        raise ValueError("unexpected GLB binary chunk")
    if not 0 < len(chunks[0][1]) <= 4 * 1024 * 1024:
        raise ValueError("GLB JSON exceeds the renderer budget")
    document = json.loads(chunks[0][1].decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("expected glTF document object")
    asset = document.get("asset")
    if not isinstance(asset, dict) or asset.get("version") != "2.0":
        raise ValueError("expected glTF 2.0 document")
    if document.get("extensionsRequired"):
        raise ValueError("required GLB extensions are not admitted")
    codecs = {"KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_texture_basisu"}
    used = document.get("extensionsUsed", [])
    if not isinstance(used, list) or any(not isinstance(item, str) for item in used):
        raise ValueError("invalid GLB extension list")
    if codecs.intersection(used):
        raise ValueError("compressed GLB requires an unsupported decoder")
    binary_length = len(chunks[1][1]) if len(chunks) == 2 else 0
    for name in ("buffers", "images", "meshes", "nodes"):
        entries = document.get(name, [])
        if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
            raise ValueError(f"invalid GLB {name}")
        for entry in entries:
            if name in ("buffers", "images") and "uri" in entry:
                raise ValueError("GLB dependencies must be embedded, not URI references")
            if name == "buffers":
                length = entry.get("byteLength")
                if len(chunks) < 2 or type(length) is not int or not 0 <= length <= binary_length:
                    raise ValueError("GLB buffer exceeds embedded bytes")
            if name == "images" and type(entry.get("bufferView")) is not int:
                raise ValueError("GLB image requires an embedded buffer view")


def validate_asset_import(manifest: ReviewedAssetImport, payload: bytes, licence: bytes) -> bytes:
    if (
        len(payload) != manifest.byte_size
        or hashlib.sha256(payload).hexdigest() != manifest.content_sha256
    ):
        raise ValueError("asset bytes disagree with reviewed manifest")
    if (
        not 0 < len(licence) <= MAX_LICENCE_BYTES
        or hashlib.sha256(licence).hexdigest() != manifest.licence_sha256
    ):
        raise ValueError("licence evidence disagrees with reviewed manifest")
    validate_import_container(payload)
    return canonical_json(manifest.model_dump(mode="json"))


def import_reviewed_asset(
    connection: psycopg.Connection,
    store: ContentAddressedStore,
    manifest: ReviewedAssetImport,
    payload: bytes,
    licence: bytes,
) -> str:
    """Retain exact bytes and append one registry entry; never update an existing key.

    The caller controls the database transaction. Blobs may outlive a failed transaction,
    but no registry entry can commit before its asset, licence and receipt are retained.
    """
    receipt = validate_asset_import(manifest, payload, licence)
    if connection.autocommit and connection.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("asset publication requires an explicit database transaction")
    receipt_sha = hashlib.sha256(receipt).hexdigest()
    expected = {
        "asset_key": manifest.asset_key,
        "title": manifest.title,
        "summary": manifest.summary,
        "media_type": "model/gltf-binary",
        "content_sha256": manifest.content_sha256,
        "byte_size": manifest.byte_size,
        "licence_id": manifest.licence_id,
        "licence_sha256": manifest.licence_sha256,
    }
    with connection.cursor(row_factory=dict_row) as cursor:
        # Serialize administrative imports, including first publication of a new key.
        cursor.execute("select pg_advisory_xact_lock(119622310)")
        cursor.execute(
            "select * from world_reviewed_asset where asset_key=%s", (manifest.asset_key,)
        )
        existing = cursor.fetchone()
        cursor.execute(
            "select receipt_sha256 from world_reviewed_asset_import where asset_key=%s",
            (manifest.asset_key,),
        )
        prior = cursor.fetchone()
        if existing is not None and any(existing[k] != v for k, v in expected.items()):
            raise ValueError("reviewed asset keys cannot be rebound")
        if prior is not None and prior["receipt_sha256"] != receipt_sha:
            raise ValueError("reviewed import provenance cannot be rewritten")
        if existing is not None and prior is None:
            raise ValueError("existing registry entry cannot acquire replacement provenance")
        if prior is not None and existing is None:
            raise ValueError("withdrawn registry entry cannot be republished by import")
        for data in (payload, licence, receipt):
            held = store.put_bytes(data)
            if store.get(held.blob_id) != data:
                raise ValueError("asset store did not retain exact bytes")
        if existing is None:
            cursor.execute(
                "insert into world_reviewed_asset "
                "(asset_key,title,summary,media_type,content_sha256,byte_size,"
                "licence_id,licence_sha256) "
                "values (%(asset_key)s,%(title)s,%(summary)s,%(media_type)s,%(content_sha256)s,"
                "%(byte_size)s,%(licence_id)s,%(licence_sha256)s)",
                expected,
            )
            cursor.execute(
                "insert into world_reviewed_asset_import(asset_key,content_sha256,receipt_sha256) "
                "values(%s,%s,%s)",
                (manifest.asset_key, manifest.content_sha256, receipt_sha),
            )
    return receipt_sha
