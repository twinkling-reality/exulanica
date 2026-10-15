"""One picture of a saved world's own first view, kept for its card on Your worlds (0218).

A page draws the world and keeps a frame of its first view; one that may change the world puts
it here, so every browser shows it, not only the one that drew it. The server cannot draw a
world, so it holds the picture to what it can check:

- what it is: a JPEG or WebP of at most :data:`PICTURE_MAX_BYTES`, from :data:`PICTURE_LEAST`
  to :data:`PICTURE_MOST` pixels, walked whole by the style pack preview's walk (no metadata, no
  embedded thumbnail, nothing after the picture), its digest the server's own;
- what it shows: the entry's authored version, the state digest the entry is saved at (the state
  opening the world draws) and the style version it is drawn in, which must be the entry's own as
  it is put, so a page that drew an older world cannot replace the picture of the current one; a
  page shows it only while they still are;
- what it may show: no world that holds a photograph is given one (a personal source's, or an
  authored world with any source attached now or before), so a kept picture is a render of made
  geometry and drawn figures, never a photograph. The server cannot see pixels: the rule is held on
  what the world is made of.

One per entry; a new one replaces the old. It is deleted with its entry, by the entry's own trigger.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Final

import psycopg

from exulanica.world.errors import UnknownWorldResource
from exulanica.world.saved_entries import SavedWorldEntry
from exulanica.world.style_pack_preview import PreviewRefused, walk_preview

__all__ = [
    "PICTURE_LEAST",
    "PICTURE_MAX_BYTES",
    "PICTURE_MEDIA_TYPES",
    "PICTURE_MOST",
    "KeptPicture",
    "PictureRefused",
    "PictureShows",
    "SavedEntryPictureRepository",
    "checked_picture",
    "refuse_a_world_of_photographs",
]

#: The picture types a card is drawn from: what a page's canvas writes.
PICTURE_MEDIA_TYPES: Final = ("image/jpeg", "image/webp")
#: A picture's bytes, at most: the style pack preview's bound, about three times a page's 1280 by
#: 720 JPEG at quality 0.7.
PICTURE_MAX_BYTES: Final = 512 * 1024
#: A picture's smallest and largest size, pixels: a card's 16 by 9, from a quarter of the page's
#: frame to the whole of it.
PICTURE_LEAST: Final = (320, 180)
PICTURE_MOST: Final = (1280, 720)


class PictureRefused(ValueError):
    """A picture refused by name: the code a page reads, and why."""

    def __init__(self, code: str, message: str, status: int) -> None:
        self.code = code
        self.status = status
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PictureShows:
    """What a picture is of: the entry's authored version, the state it is saved at and its look."""

    authored_version_id: uuid.UUID
    authored_state_sha256: str
    style_version_id: uuid.UUID

    @staticmethod
    def of(entry: SavedWorldEntry) -> PictureShows:
        """What opening the entry draws now: its saved cursor, not a later state of the branch."""
        return PictureShows(
            entry.authored_version_id, entry.authored_state_sha256, entry.style_version_id
        )


@dataclass(frozen=True, slots=True)
class KeptPicture:
    entry_id: uuid.UUID
    media_type: str
    sha256: str
    byte_size: int
    width: int
    height: int
    shows: PictureShows
    taken_by: uuid.UUID
    taken_at: dt.datetime


def checked_picture(data: bytes, media_type: str) -> tuple[int, int, str]:
    """The picture's width, height and digest, once every byte of it has been walked and allowed."""
    if media_type not in PICTURE_MEDIA_TYPES:
        raise PictureRefused(
            "picture_media_type", f"a picture is a JPEG or a WebP, not {media_type}", 415
        )
    if not 0 < len(data) <= PICTURE_MAX_BYTES:
        raise PictureRefused(
            "picture_too_large",
            f"a picture is 1 to {PICTURE_MAX_BYTES} bytes, not {len(data)}",
            413,
        )
    try:
        size = walk_preview(data, media_type)
    except PreviewRefused as exc:
        raise PictureRefused("picture_refused", str(exc), 422) from exc
    width, height = size.width_px, size.height_px
    if not (
        PICTURE_LEAST[0] <= width <= PICTURE_MOST[0]
        and PICTURE_LEAST[1] <= height <= PICTURE_MOST[1]
    ):
        raise PictureRefused(
            "picture_size",
            f"a picture is {PICTURE_LEAST[0]} by {PICTURE_LEAST[1]} to {PICTURE_MOST[0]} by "
            f"{PICTURE_MOST[1]} pixels, not {width} by {height}",
            422,
        )
    return width, height, hashlib.sha256(data).hexdigest()


def refuse_a_world_of_photographs(entry: SavedWorldEntry) -> None:
    """Refuse a picture of a world that holds, or held, a photograph."""
    if (
        entry.source_kind == "personal"
        or entry.source_attachments
        or entry.previous_source_attachments
    ):
        raise PictureRefused(
            "picture_of_photographs",
            "a world that holds a photograph is given no picture for its card",
            422,
        )


_COLUMNS: Final = (
    "entry_id,media_type,sha256,byte_size,width,height,authored_version_id,"
    "authored_state_sha256,style_version_id,taken_by,taken_at"
)


def _kept(row: dict[str, Any]) -> KeptPicture:
    return KeptPicture(
        entry_id=row["entry_id"],
        media_type=row["media_type"],
        sha256=row["sha256"],
        byte_size=row["byte_size"],
        width=row["width"],
        height=row["height"],
        shows=PictureShows(
            row["authored_version_id"],
            row["authored_state_sha256"],
            row["style_version_id"],
        ),
        taken_by=row["taken_by"],
        taken_at=row["taken_at"],
    )


class SavedEntryPictureRepository:
    """Keep and read the pictures of one workspace's saved worlds."""

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self.connection = connection
        self.workspace_id = workspace_id

    def keep(
        self,
        entry: SavedWorldEntry,
        data: bytes,
        media_type: str,
        shows: PictureShows,
        taken_by: uuid.UUID,
    ) -> KeptPicture:
        """Keep ``data`` as ``entry``'s picture in place of any other, once it is allowed."""
        refuse_a_world_of_photographs(entry)
        width, height, digest = checked_picture(data, media_type)
        if shows != PictureShows.of(entry):
            raise PictureRefused(
                "picture_not_current",
                "the picture is of a version, state or look the saved world no longer has",
                409,
            )
        row = self.connection.execute(
            "insert into saved_world_entry_picture (workspace_id,entry_id,media_type,bytes,"
            "byte_size,sha256,width,height,authored_version_id,authored_state_sha256,"
            "style_version_id,taken_by) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (workspace_id,entry_id) do update set media_type=excluded.media_type,"
            "bytes=excluded.bytes,byte_size=excluded.byte_size,sha256=excluded.sha256,"
            "width=excluded.width,height=excluded.height,"
            "authored_version_id=excluded.authored_version_id,"
            "authored_state_sha256=excluded.authored_state_sha256,"
            "style_version_id=excluded.style_version_id,taken_by=excluded.taken_by,"
            "taken_at=statement_timestamp() "
            f"returning {_COLUMNS}",
            (
                self.workspace_id,
                entry.entry_id,
                media_type,
                data,
                len(data),
                digest,
                width,
                height,
                shows.authored_version_id,
                shows.authored_state_sha256,
                shows.style_version_id,
                taken_by,
            ),
        ).fetchone()
        assert row is not None
        return _kept(row)

    def records(self) -> dict[uuid.UUID, KeptPicture]:
        """Every kept picture's record, by entry, without its bytes."""
        rows = self.connection.execute(
            f"select {_COLUMNS} from saved_world_entry_picture where workspace_id=%s",
            (self.workspace_id,),
        ).fetchall()
        return {row["entry_id"]: _kept(row) for row in rows}

    def record(self, entry_id: uuid.UUID) -> KeptPicture | None:
        row = self.connection.execute(
            f"select {_COLUMNS} from saved_world_entry_picture "
            "where workspace_id=%s and entry_id=%s",
            (self.workspace_id, entry_id),
        ).fetchone()
        return None if row is None else _kept(row)

    def picture(self, entry_id: uuid.UUID, sha256: str) -> tuple[str, bytes] | None:
        """The kept picture's type and bytes while ``sha256`` is its digest; else none.

        Refuses an entry this workspace does not hold as the entry routes do, so an entry's own
        workspace and a stranger are told apart only by what the workspace holds.
        """
        row = self.connection.execute(
            "select p.media_type,p.bytes from saved_world_entry e "
            "left join saved_world_entry_picture p on p.workspace_id=e.workspace_id "
            "and p.entry_id=e.entry_id and p.sha256=%s "
            "where e.workspace_id=%s and e.entry_id=%s",
            (sha256, self.workspace_id, entry_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such saved world entry")
        return None if row["media_type"] is None else (row["media_type"], bytes(row["bytes"]))
