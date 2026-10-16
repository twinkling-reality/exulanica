"""The pictures of a world's History (migration 0223, on 0221's moments): a picture of each moment,
a portrait of each look.

A moment is recorded when it happens (where its people stood, what they did), not drawn: the server
cannot draw a world. The first page that shows the moment draws it, the world at the moment's
version with its people placed as recorded and the camera a framing recipe gives, and keeps the
frame here; a portrait is one look drawn alone. Every later view, on any computer, reads the kept
bytes by their digest. The server holds a picture to what it can check:

- what it is: a JPEG or WebP walked whole
  (:func:`exulanica.world.saved_entry_pictures.checked_picture`
  for a moment, the same walk with a portrait's square bounds), its digest the server's own;
- what it is of: a moment the version of the world records (world_society_moment), or a look by its
  digest, each with the recipe it was drawn by. The first picture kept under a name stays: another
  is refused (``picture_kept``, 409) and answered with the one kept, so no page draws it twice and
  every page shows the same one. A new recipe is a new name;
- what it may show: no world that holds, or held, a photograph is given one (a personal source's, or
  an authored world with any source attached now or before), so every kept picture is a render of
  made geometry and drawn figures. The server cannot see pixels: the rule is held on what the world
  is made of;
- how many: at most :data:`MOMENT_PICTURES_PER_WORLD` moment pictures and
  :data:`PORTRAITS_PER_WORLD` portraits a world.

A moment's pictures are deleted with their moment, by the moment's own trigger, so a society's
erasure reaches them; both kinds are deleted with their world, by its identity's own trigger (0223).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg

from exulanica.world.errors import UnknownWorldResource
from exulanica.world.saved_entry_pictures import (
    PICTURE_MEDIA_TYPES,
    PictureRefused,
    checked_picture,
)
from exulanica.world.style_pack_preview import PreviewRefused, walk_preview
from exulanica.world.worlds import require_world

__all__ = [
    "MOMENT_PICTURES_PER_WORLD",
    "PORTRAITS_PER_WORLD",
    "PORTRAIT_LEAST",
    "PORTRAIT_MAX_BYTES",
    "PORTRAIT_MOST",
    "RECIPE_PATTERN",
    "KeptHistoryPicture",
    "MomentPictureRepository",
    "PictureKept",
    "checked_portrait",
]

#: A recipe's name: the framing or portrait recipe a page drew by, and its version.
RECIPE_PATTERN: Final = re.compile(r"^[a-z][a-z0-9-]{0,47}/v[1-9][0-9]{0,5}$")
#: A portrait's bytes, at most: a 512-pixel square JPEG at quality 0.8 is about a fifth of it.
PORTRAIT_MAX_BYTES: Final = 128 * 1024
#: A portrait's side, pixels: square, from a small round mark to twice a card's portrait.
PORTRAIT_LEAST: Final = 128
PORTRAIT_MOST: Final = 512
#: The most moment pictures a world keeps, and portraits: far more than a History shows, so a page
#: that keeps drawing cannot fill the database.
MOMENT_PICTURES_PER_WORLD: Final = 4096
PORTRAITS_PER_WORLD: Final = 1024


@dataclass(frozen=True, slots=True)
class KeptHistoryPicture:
    """A kept picture's record, without its bytes."""

    kind: Literal["moment", "portrait"]
    #: The moment's id, or the look's digest.
    of: str
    recipe: str
    media_type: str
    sha256: str
    byte_size: int
    width: int
    height: int
    taken_by: uuid.UUID
    taken_at: dt.datetime

    def view(self) -> dict[str, Any]:
        """What a read serves of it: the digest that fetches it, and its size."""
        return {"sha256": self.sha256, "width": self.width, "height": self.height}


def checked_portrait(data: bytes, media_type: str) -> tuple[int, int, str]:
    """A portrait's width, height and digest, once every byte of it has been walked and allowed."""
    if media_type not in PICTURE_MEDIA_TYPES:
        raise PictureRefused(
            "picture_media_type", f"a picture is a JPEG or a WebP, not {media_type}", 415
        )
    if not 0 < len(data) <= PORTRAIT_MAX_BYTES:
        raise PictureRefused(
            "picture_too_large",
            f"a portrait is 1 to {PORTRAIT_MAX_BYTES} bytes, not {len(data)}",
            413,
        )
    try:
        size = walk_preview(data, media_type)
    except PreviewRefused as exc:
        raise PictureRefused("picture_refused", str(exc), 422) from exc
    width, height = size.width_px, size.height_px
    if width != height or not PORTRAIT_LEAST <= width <= PORTRAIT_MOST:
        raise PictureRefused(
            "picture_size",
            f"a portrait is square, {PORTRAIT_LEAST} to {PORTRAIT_MOST} pixels a side, not "
            f"{width} by {height}",
            422,
        )
    return width, height, hashlib.sha256(data).hexdigest()


def _recipe(recipe: str) -> str:
    if not RECIPE_PATTERN.match(recipe):
        raise PictureRefused("picture_recipe", "a recipe is a name and a version, as name/v1", 422)
    return recipe


_MOMENT_COLUMNS: Final = (
    "moment_id::text as of,recipe,media_type,sha256,byte_size,width,height,taken_by,taken_at"
)
_PORTRAIT_COLUMNS: Final = (
    "look_sha256 as of,recipe,media_type,sha256,byte_size,width,height,taken_by,taken_at"
)


def _kept(kind: Literal["moment", "portrait"], row: dict[str, Any]) -> KeptHistoryPicture:
    return KeptHistoryPicture(
        kind=kind,
        of=row["of"],
        recipe=row["recipe"],
        media_type=row["media_type"],
        sha256=row["sha256"],
        byte_size=row["byte_size"],
        width=row["width"],
        height=row["height"],
        taken_by=row["taken_by"],
        taken_at=row["taken_at"],
    )


class PictureKept(PictureRefused):
    """Another picture is kept under this name already: the one kept rides along."""

    def __init__(self, kept: KeptHistoryPicture) -> None:
        super().__init__("picture_kept", "a picture is kept for this already", 409)
        self.kept = kept


class MomentPictureRepository:
    """Keep and read the History pictures of one workspace's worlds."""

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self.connection = connection
        self.workspace_id = workspace_id

    def held_world(self, world_id: str) -> None:
        """Refuse a world this workspace does not hold (404, as every world route)."""
        require_world(self.connection, self.workspace_id, world_id)

    def _refuse_photographs(self, world_id: str) -> None:
        """Refuse a world that holds, or held, a photograph: a personal source's, or any source
        attached to one of its saved entries now or before."""
        row = self.connection.execute(
            "select i.kind = 'personal-source' "
            "or exists(select 1 from saved_world_entry k "
            "join saved_world_source_current_membership m "
            "on m.workspace_id=k.workspace_id and m.entry_id=k.entry_id "
            "where k.workspace_id=i.workspace_id and k.world_id=i.world_id) "
            "or exists(select 1 from saved_world_entry k join saved_world_source_detach d "
            "on d.workspace_id=k.workspace_id and d.entry_id=k.entry_id "
            "where k.workspace_id=i.workspace_id and k.world_id=i.world_id) as photographs "
            "from world_identity i where i.workspace_id=%s and i.world_id=%s",
            (self.workspace_id, world_id),
        ).fetchone()
        if row is None or row["photographs"]:
            raise PictureRefused(
                "picture_of_photographs",
                "a world that holds a photograph is given no pictures for its History",
                422,
            )

    def _version(self, world_id: str, version_id: uuid.UUID) -> None:
        held = self.connection.execute(
            "select 1 from world_alternate_version where workspace_id=%s and world_id=%s "
            "and version_id=%s",
            (self.workspace_id, world_id, version_id),
        ).fetchone()
        if held is None:
            raise UnknownWorldResource("no such world version")

    def _moment(self, world_id: str, version_id: uuid.UUID, moment_id: uuid.UUID) -> None:
        """Refuse a moment this version of the world does not record, as any unknown name is."""
        held = self.connection.execute(
            "select 1 from world_society_moment m join world_society s "
            "on s.workspace_id = m.workspace_id and s.society_id = m.society_id "
            "where m.workspace_id = %s and m.moment_id = %s and m.version_id = %s "
            "and s.world_id = %s",
            (self.workspace_id, moment_id, version_id, world_id),
        ).fetchone()
        if held is None:
            raise UnknownWorldResource("no such moment")

    def _room(self, table: str, world_id: str, most: int) -> None:
        row = self.connection.execute(
            f"select count(*) as n from {table} where workspace_id=%s and world_id=%s",
            (self.workspace_id, world_id),
        ).fetchone()
        if row is not None and row["n"] >= most:
            raise PictureRefused(
                "pictures_full", f"a world keeps at most {most} of these pictures", 409
            )

    def keep_moment(
        self,
        world_id: str,
        version_id: uuid.UUID,
        moment_id: uuid.UUID,
        recipe: str,
        data: bytes,
        media_type: str,
        taken_by: uuid.UUID,
    ) -> KeptHistoryPicture:
        """Keep ``data`` as the moment's picture by ``recipe``, unless one is kept already."""
        self.held_world(world_id)
        self._version(world_id, version_id)
        recipe = _recipe(recipe)
        self._refuse_photographs(world_id)
        width, height, digest = checked_picture(data, media_type)
        self._moment(world_id, version_id, moment_id)
        self._room("world_moment_picture", world_id, MOMENT_PICTURES_PER_WORLD)
        row = self.connection.execute(
            "insert into world_moment_picture (workspace_id,world_id,version_id,moment_id,recipe,"
            "media_type,bytes,byte_size,sha256,width,height,taken_by) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (workspace_id,moment_id,recipe) do nothing "
            f"returning {_MOMENT_COLUMNS}",
            (
                self.workspace_id,
                world_id,
                version_id,
                moment_id,
                recipe,
                media_type,
                data,
                len(data),
                digest,
                width,
                height,
                taken_by,
            ),
        ).fetchone()
        if row is None:
            raced = self.moment(world_id, moment_id, recipe)
            assert raced is not None
            raise PictureKept(raced)
        return _kept("moment", row)

    def keep_portrait(
        self,
        world_id: str,
        look_sha256: str,
        recipe: str,
        data: bytes,
        media_type: str,
        taken_by: uuid.UUID,
    ) -> KeptHistoryPicture:
        """Keep ``data`` as the look's portrait in the world by ``recipe``, unless one is kept."""
        self.held_world(world_id)
        if not re.fullmatch(r"[0-9a-f]{64}", look_sha256):
            raise PictureRefused("picture_look", "a look is named by its sha256 digest", 422)
        recipe = _recipe(recipe)
        self._refuse_photographs(world_id)
        width, height, digest = checked_portrait(data, media_type)
        self._room("world_look_portrait", world_id, PORTRAITS_PER_WORLD)
        row = self.connection.execute(
            "insert into world_look_portrait (workspace_id,world_id,look_sha256,recipe,media_type,"
            "bytes,byte_size,sha256,width,height,taken_by) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (workspace_id,world_id,look_sha256,recipe) do nothing "
            f"returning {_PORTRAIT_COLUMNS}",
            (
                self.workspace_id,
                world_id,
                look_sha256,
                recipe,
                media_type,
                data,
                len(data),
                digest,
                width,
                height,
                taken_by,
            ),
        ).fetchone()
        if row is None:
            raced = self.portraits(world_id, [look_sha256], recipe).get(look_sha256)
            assert raced is not None
            raise PictureKept(raced)
        return _kept("portrait", row)

    def moment(self, world_id: str, moment_id: uuid.UUID, recipe: str) -> KeptHistoryPicture | None:
        row = self.connection.execute(
            f"select {_MOMENT_COLUMNS} from world_moment_picture "
            "where workspace_id=%s and world_id=%s and moment_id=%s and recipe=%s",
            (self.workspace_id, world_id, moment_id, recipe),
        ).fetchone()
        return None if row is None else _kept("moment", row)

    def moments(
        self, world_id: str, moment_ids: Iterable[uuid.UUID], recipe: str
    ) -> dict[uuid.UUID, KeptHistoryPicture]:
        """The kept pictures of these moments by ``recipe``, by moment; none is absent."""
        asked = list(moment_ids)
        if not asked:
            return {}
        rows = self.connection.execute(
            f"select {_MOMENT_COLUMNS} from world_moment_picture "
            "where workspace_id=%s and world_id=%s and recipe=%s and moment_id = any(%s)",
            (self.workspace_id, world_id, recipe, asked),
        ).fetchall()
        return {uuid.UUID(row["of"]): _kept("moment", row) for row in rows}

    def portraits(
        self, world_id: str, looks: Iterable[str], recipe: str
    ) -> dict[str, KeptHistoryPicture]:
        """The kept portraits of these looks by ``recipe``, by look; a look with none is absent."""
        asked = list(looks)
        if not asked:
            return {}
        rows = self.connection.execute(
            f"select {_PORTRAIT_COLUMNS} from world_look_portrait "
            "where workspace_id=%s and world_id=%s and recipe=%s and look_sha256 = any(%s)",
            (self.workspace_id, world_id, recipe, asked),
        ).fetchall()
        return {row["of"]: _kept("portrait", row) for row in rows}

    def picture(self, world_id: str, sha256: str) -> tuple[str, bytes] | None:
        """A kept History picture's type and bytes in the world, by its digest; else none.

        Refuses a world this workspace does not hold as the world routes do, so the world's own
        workspace and a stranger are told apart only by what the workspace holds.
        """
        self.held_world(world_id)
        row = self.connection.execute(
            "select media_type,bytes from world_moment_picture "
            "where workspace_id=%s and world_id=%s and sha256=%s "
            "union all select media_type,bytes from world_look_portrait "
            "where workspace_id=%s and world_id=%s and sha256=%s limit 1",
            (self.workspace_id, world_id, sha256, self.workspace_id, world_id, sha256),
        ).fetchone()
        return None if row is None else (row["media_type"], bytes(row["bytes"]))
