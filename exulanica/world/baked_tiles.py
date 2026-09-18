"""Baked tiles: recording what an offline bake produced, and serving those bytes once.

Migration 0072 holds the shape and every rule; this is the path that reaches it.

* :meth:`BakedTileRepository.record` runs the bake through ``record_baked_tile_bake``: a new key is
  stored, the same bytes again change nothing, and different bytes under one key leave the stored
  row exactly as it is and mark it ``nondeterminism_detected``. The bytes are put in the ``tiles``
  store before the row is written, so a row never names bytes that were never stored.
* :meth:`BakedTileRepository.tiles_of_city` lists the CURRENT bake of each tile of one city seed,
  as metadata: one row per level of detail and coordinate, the most recently published.
* :meth:`BakedTileRepository.serve` delivers one tile's bytes to a workspace. The bytes are read
  from the store, held to the row's digest, and the row is read again under the 0041 asset read
  lock, so a tile that stopped being servable between the read and the delivery is refused rather
  than served. Only then is the delivery recorded: the first delivery of a tile to a workspace
  inserts the ledger row migration 0072 keys ``(workspace, tile)``, whose trigger spends one of the
  workspace's 0062 tile quota in the same statement, and later deliveries of that tile to that
  workspace are free. A delivery that fails costs nothing.
* :meth:`BakedTileRepository.servable` answers what a tile's bytes would be without fetching or
  charging, which is what a conditional request needs.

Nothing here bakes, and nothing here reads ``assets/``. A faulted tile is never served.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final

import psycopg

from exulanica.errors import BlobNotFoundError, ExulanicaError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "TILE_MEDIA_TYPE",
    "BakedTile",
    "BakedTileError",
    "BakedTileFaulted",
    "BakedTileRepository",
    "TileBytesMissing",
    "TileQuotaRefused",
    "UnknownBakedTile",
]

TILE_MEDIA_TYPE: Final = "application/vnd.exulanica.owd"


class BakedTileError(ExulanicaError):
    """A baked tile could not be served, and nothing was delivered."""


class UnknownBakedTile(BakedTileError):
    """No tile is stored under this key."""


class BakedTileFaulted(BakedTileError):
    """This key once baked into two different containers. It is never served."""


class TileBytesMissing(BakedTileError):
    """The row is here and the store does not hold its bytes."""


class TileQuotaRefused(BakedTileError):
    """The workspace has no tile quota, or has spent it. Never retried."""


@dataclass(frozen=True, slots=True)
class BakedTile:
    """One stored tile, as a caller may see it. The container's bytes are fetched separately.

    ``stage_version`` and ``stage_params_sha256`` are what tell two rows for ONE tile apart. A tile
    document may be baked by more than one tessellator (migration 0077), so a listing can carry two
    rows with the same coordinate, the same level of detail and the same ``tile_inputs_digest``,
    differing only in the program that baked them. Without these a caller reading the listing by
    coordinate has no way to choose and will take whichever came first; on 2026-09-18 a loader did
    exactly that and drew a container its runtime then refused.
    """

    baked_tile_id: uuid.UUID
    tile_x: int
    tile_y: int
    lod: int
    stage_version: int
    stage_params_sha256: str
    tile_inputs_digest: str
    container_sha256: str
    container_bytes: int
    render_batch_sha256: str
    nav_envelope_sha256: str
    state: str

    def document(self) -> dict[str, object]:
        return {
            "baked_tile_id": str(self.baked_tile_id),
            "tile_x": self.tile_x,
            "tile_y": self.tile_y,
            "lod": self.lod,
            "stage_version": self.stage_version,
            "stage_params_sha256": self.stage_params_sha256,
            "tile_inputs_digest": self.tile_inputs_digest,
            "container_sha256": self.container_sha256,
            "container_bytes": self.container_bytes,
            "render_batch_sha256": self.render_batch_sha256,
            "nav_envelope_sha256": self.nav_envelope_sha256,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class ServedTile:
    data: bytes
    tile: BakedTile
    charged: bool


def _hex(value: object) -> str:
    return bytes(value).hex()  # type: ignore[arg-type]


def _row(row: Mapping[str, Any]) -> BakedTile:
    return BakedTile(
        baked_tile_id=row["baked_tile_id"],
        tile_x=row["tile_x"],
        tile_y=row["tile_y"],
        lod=row["lod"],
        stage_version=int(row["stage_version"]),
        stage_params_sha256=_hex(row["stage_params_sha256"]),
        tile_inputs_digest=_hex(row["tile_inputs_digest"]),
        container_sha256=_hex(row["container_sha256"]),
        container_bytes=int(row["container_bytes"]),
        render_batch_sha256=_hex(row["render_batch_sha256"]),
        nav_envelope_sha256=_hex(row["nav_envelope_sha256"]),
        state=row["state"],
    )


_COLUMNS: Final = (
    "baked_tile_id, tile_x, tile_y, lod, stage_version, stage_params_sha256, tile_inputs_digest, "
    "container_sha256, container_bytes, render_batch_sha256, nav_envelope_sha256, state"
)


@contextmanager
def _refusals() -> Iterator[None]:
    try:
        yield
    except psycopg.errors.ProgramLimitExceeded as error:
        raise TileQuotaRefused(error.diag.message_primary or "tile quota refused") from error


@dataclass(frozen=True, slots=True)
class BakedTileRepository:
    """The one path to the baked tile tables, for one connection."""

    connection: psycopg.Connection
    store: ContentAddressedStore

    def record(
        self,
        *,
        baked_tile_id: uuid.UUID,
        stage_version: int,
        stage_params_sha256: bytes,
        tile: Mapping[str, Any],
        document: bytes,
        container: bytes,
        render_batch_sha256: bytes,
        nav_envelope_sha256: bytes,
        receipt: Mapping[str, Any],
    ) -> str:
        """Put the container in the tile store and record the bake. Answers what 0072 decided."""
        self.store.put_bytes(container)
        row = self.connection.execute(
            "select record_baked_tile_bake(%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) as outcome",
            (
                baked_tile_id,
                stage_version,
                stage_params_sha256,
                bytes.fromhex(tile["tile_inputs_digest"]),
                bytes.fromhex(tile["city_seed"]),
                json.dumps(tile["grammar_versions"]),
                bytes.fromhex(tile["catalog_digest"]),
                bytes.fromhex(tile["edit_delta_digest"]),
                tile["tile_x"],
                tile["tile_y"],
                tile["lod"],
                tile["tile_size_mm"],
                tile["halo_radius_mm"],
                hashlib.sha256(document).digest(),
                len(document),
                hashlib.sha256(container).digest(),
                len(container),
                render_batch_sha256,
                nav_envelope_sha256,
                json.dumps(dict(receipt), sort_keys=True),
            ),
        ).fetchone()
        assert row is not None
        return str(row["outcome"])

    def read(self, baked_tile_id: uuid.UUID) -> BakedTile:
        row = self.connection.execute(
            f"select {_COLUMNS} from baked_tile where baked_tile_id = %s", (baked_tile_id,)
        ).fetchone()
        if row is None:
            raise UnknownBakedTile(f"no baked tile {baked_tile_id} is stored here")
        return _row(row)

    def tiles_of_city(self, city_seed: str, lod: int | None = None) -> Sequence[BakedTile]:
        """THE CURRENT BAKE OF EACH TILE OF A CITY: one row per level of detail and coordinate.

        CURRENT IS THE MOST RECENTLY PUBLISHED, greatest ``baked_at``, ties broken by
        ``baked_tile_id`` so the answer is total rather than whichever row the plan happened to
        yield. A store serves what was last published into it, so republishing an earlier bake
        makes that bake current, which is the behaviour an operator republishing one would expect.

        WHY THIS IS ONE ROW PER TILE. A tile document says nothing about the tessellator, so a new
        tessellator's bake is a NEW ROW under a new key rather than a replacement (migration 0077).
        This listing used to return every one of them ordered by ``lod, tile_y, tile_x``, WHICH DOES
        NOT ORDER AMONG ROWS SHARING ALL THREE. So a caller reading by coordinate did not get the
        oldest, it got whichever row the plan yielded, not necessarily the same one twice, and
        nothing in the answer said which. On 2026-09-18 a page was handed a tessellator 5 container
        baked the previous night while the store held a 19, and refused it at the decode; the
        failure read as a missing tile rather than as an ambiguous listing. Returning one row per
        tile is what makes a client's ``find`` by coordinate correct rather than lucky, and it fixes
        every client at once rather than the one that noticed.

        A FAULTED ROW THAT IS CURRENT STAYS CURRENT. Skipping it would silently fall back to older
        geometry, which is a substitution nobody asked for. It is listed, it carries its state, and
        :meth:`servable` refuses it when its bytes are asked for, which is where the two disagreeing
        facts actually meet.

        THE HISTORY IS NOT LOST, only unlisted: every earlier bake keeps its row and its bytes, and
        :meth:`read` reaches any of them by key.
        """
        rows = self.connection.execute(
            f"select distinct on (lod, tile_y, tile_x) {_COLUMNS} from baked_tile "
            "where city_seed = %s and (%s::int is null or lod = %s) "
            "order by lod, tile_y, tile_x, baked_at desc, baked_tile_id desc",
            (bytes.fromhex(city_seed), lod, lod),
        ).fetchall()
        return [_row(row) for row in rows]

    def servable(self, baked_tile_id: uuid.UUID) -> BakedTile:
        """The tile, if it is one this deployment serves. Reads nothing from the store and charges
        nothing: a caller that only needs to know what the bytes would be, to answer a conditional
        request or to skip a fetch, must not spend a workspace's ceiling to find out."""
        tile = self.read(baked_tile_id)
        if tile.state != "baked":
            raise BakedTileFaulted(
                f"baked tile {baked_tile_id} baked twice into different containers and is not "
                "served; rebake it after the bake is made deterministic again"
            )
        return tile

    def serve(self, workspace_id: uuid.UUID, baked_tile_id: uuid.UUID) -> ServedTile:
        """One tile's bytes for one workspace, charged once and checked twice.

        The bytes are fetched and held to their digest **before** the quota is charged. A delivery
        that cannot happen costs nothing: a row whose bytes are missing from the store is an
        operator's fault, and charging a workspace a tile of its ceiling for it would make our
        problem theirs.
        """
        tile = self.servable(baked_tile_id)
        try:
            data = self.store.get(BlobId(bytes.fromhex(tile.container_sha256)))
        except BlobNotFoundError as error:
            raise TileBytesMissing(
                f"baked tile {baked_tile_id} is recorded and its bytes are not in the store"
            ) from error
        if hashlib.sha256(data).hexdigest() != tile.container_sha256 or len(data) != (
            tile.container_bytes
        ):
            raise TileBytesMissing(f"baked tile {baked_tile_id}'s bytes are not what it records")
        self._final_check(tile)
        charged = self._charge(workspace_id, baked_tile_id)
        return ServedTile(data=data, tile=tile, charged=charged)

    def _charge(self, workspace_id: uuid.UUID, baked_tile_id: uuid.UUID) -> bool:
        """Record the delivery, spending one tile of the quota the first time only.

        The insert is conditional in SQL rather than ``on conflict do nothing``, because the quota
        is spent by a ``before insert`` trigger and that trigger runs before any conflict is
        resolved: discarding the row afterwards would keep the charge, and a workspace would pay
        again every time a walk reloaded a tile it had already been served. With no row to insert
        the trigger never fires. Two first deliveries racing each other both pass the test and both
        charge; one then loses the unique index and its transaction is rolled back, charge and all.
        """
        try:
            with _refusals(), self.connection.transaction():
                row = self.connection.execute(
                    "insert into workspace_baked_tile (workspace_id, baked_tile_id) "
                    "select %s, %s where not exists ("
                    "  select 1 from workspace_baked_tile"
                    "  where workspace_id = %s and baked_tile_id = %s"
                    ") returning baked_tile_id",
                    (workspace_id, baked_tile_id, workspace_id, baked_tile_id),
                ).fetchone()
        except psycopg.errors.UniqueViolation:
            return False
        return row is not None

    def _final_check(self, seen: BakedTile) -> None:
        """The 0041 final check: under the asset read lock, the tile is still what was read."""
        with self.connection.transaction():
            self.connection.execute("select asset_read_lock()")
            current = self.connection.execute(
                f"select {_COLUMNS} from baked_tile where baked_tile_id = %s",
                (seen.baked_tile_id,),
            ).fetchone()
        if current is None:
            raise UnknownBakedTile(f"baked tile {seen.baked_tile_id} stopped being stored")
        now = _row(current)
        if now.state != "baked" or now.container_sha256 != seen.container_sha256:
            raise BakedTileFaulted(
                f"baked tile {seen.baked_tile_id} stopped being servable while it was read"
            )
