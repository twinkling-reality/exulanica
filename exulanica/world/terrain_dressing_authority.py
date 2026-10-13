"""Current reviewed component rows and bounded bytes for immutable terrain dressing."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.world.asset_kinds import AssetKind
from exulanica.world.errors import InvalidStructuralData, UnknownWorldResource
from exulanica.world.reviewed_catalog import ReviewedCatalog
from exulanica.world.terrain_authoring import TerrainAuthoring
from exulanica.world.terrain_dressing import (
    DressingCoverage,
    TerrainDressing,
    TerrainDressingInvalid,
    read_terrain_dressing,
)


@dataclass(frozen=True, slots=True)
class ComponentPin:
    asset_key: str
    content_sha256: str
    byte_size: int
    media_type: str
    licence_id: str
    licence_sha256: str


@dataclass(frozen=True, slots=True)
class ResolvedTerrainDressing:
    dressing: TerrainDressing
    coverage: DressingCoverage
    components: tuple[ComponentPin, ...]


def _pin(catalog: ReviewedCatalog, key: str, digest: str) -> ComponentPin:
    # No store argument: this is also used under the final read/write barrier.
    try:
        row = catalog.asset(key)
    except UnknownWorldResource as exc:
        raise InvalidStructuralData("terrain_dressing_source_unavailable") from exc
    if (
        row.kind != AssetKind.COMPONENT
        or row.content_sha256 != digest
        or row.media_type != "model/gltf-binary"
        or type(row.byte_size) is not int
        or not 0 < row.byte_size <= 32 * 1024 * 1024
    ):
        raise InvalidStructuralData("terrain_dressing_source_unavailable")
    return ComponentPin(
        row.asset_key,
        row.content_sha256,
        row.byte_size,
        row.media_type,
        row.licence_id,
        row.licence_sha256,
    )


def require_terrain_dressing_current(
    catalog: ReviewedCatalog, resolved: ResolvedTerrainDressing
) -> None:
    """Ask only registry rows; caller owns the final read/write barrier and world checks."""
    for pin in resolved.components:
        if _pin(catalog, pin.asset_key, pin.content_sha256) != pin:
            raise InvalidStructuralData("terrain_dressing_source_changed")


def resolve_terrain_dressing(
    catalog: ReviewedCatalog,
    store: ContentAddressedStore | None,
    source: TerrainAuthoring,
    *,
    compile_coverage: Callable[[TerrainDressing, dict[str, bytes]], DressingCoverage],
) -> ResolvedTerrainDressing | None:
    """Read bounded bytes before a barrier, then derive complete contact in the bounded worker.

    The returned value is checked input, not continuing authority. Each handover or write asks
    its row-only final question again under the existing read/write barrier. No cache substitutes
    for these byte reads or current registry rows; only pure geometry compilation may be cached.
    """
    if source.composer_version == 3:
        return None
    if store is None:
        raise InvalidStructuralData("terrain_dressing_source_unavailable")
    document = source.document()
    dressing = read_terrain_dressing(document["dressing"], document["dressing_sha256"])
    sources = {(instance.asset_key, instance.content_sha256) for instance in dressing.instances}
    pins = tuple(_pin(catalog, key, digest) for key, digest in sorted(sources))
    sizes: dict[str, int] = {}
    for pin in pins:
        if pin.content_sha256 in sizes and sizes[pin.content_sha256] != pin.byte_size:
            raise InvalidStructuralData("terrain_dressing_source_changed")
        sizes[pin.content_sha256] = pin.byte_size
    if sum(sizes.values()) > 32 * 1024 * 1024:
        raise InvalidStructuralData("terrain_dressing_source_budget")
    payloads: dict[str, bytes] = {}
    by_digest: dict[str, bytes] = {}
    for pin in pins:
        if pin.content_sha256 not in by_digest:
            try:
                with store.open(BlobId.from_hex(pin.content_sha256)) as stream:
                    payload = stream.read(pin.byte_size + 1)
            except (BlobNotFoundError, IntegrityError, OSError) as exc:
                raise InvalidStructuralData("terrain_dressing_source_bytes_unavailable") from exc
            if (
                len(payload) != pin.byte_size
                or hashlib.sha256(payload).hexdigest() != pin.content_sha256
            ):
                raise InvalidStructuralData("terrain_dressing_source_bytes_changed")
            by_digest[pin.content_sha256] = payload
        payloads[pin.asset_key] = by_digest[pin.content_sha256]
    coverage = compile_coverage(dressing, payloads)
    try:
        coverage.require_contact(document["contact"]["obstructions"])
    except TerrainDressingInvalid as exc:
        raise InvalidStructuralData("terrain_dressing_contact_differs") from exc
    resolved = ResolvedTerrainDressing(dressing, coverage, pins)
    require_terrain_dressing_current(catalog, resolved)
    return resolved


def require_terrain_dressing_available(
    catalog: ReviewedCatalog, store: ContentAddressedStore | None, source: TerrainAuthoring
) -> None:
    """Cheap library availability only; drawing/contact still validate complete exact bytes."""
    if source.composer_version == 3:
        return
    if store is None:
        raise InvalidStructuralData("terrain_dressing_source_unavailable")
    doc = source.document()
    dressing = read_terrain_dressing(doc["dressing"], doc["dressing_sha256"])
    for instance in dressing.instances:
        pin = _pin(catalog, instance.asset_key, instance.content_sha256)
        if not store.exists(BlobId.from_hex(pin.content_sha256)):
            raise InvalidStructuralData("terrain_dressing_source_bytes_unavailable")
