"""A world's paintings (migration 0226): its own views painted by an open model from its words.

A painting is invented appearance on exact structure. The operator's painting run draws the
world's structure at a view through the install's own page (its depth, from the camera the page
opens the world at, or a heading from there), has an open picture model on a GPU paint that view
from the words written for the world (its sentence and, where it has them, its notes), measures how
much of the structure's edges the painting kept, and keeps what passes here
(:meth:`WorldPaintingRepository.keep`). Every reader of the world reads them (:meth:`paintings`,
:meth:`picture`). The one route that writes one is a showcase world's copy
(``POST /worlds/showcase/{showcase}``): it keeps the card paintings its document names, painted by
that run, for the copy's world (:func:`exulanica.world.showcase_worlds.make_showcase_world`). The
server holds a painting to what it can check:

- what it is: a JPEG or WebP walked whole, of a saved world's card picture's bounds
  (:func:`exulanica.world.saved_entry_pictures.checked_picture`), its digest the server's own;
- what it is of: a world this workspace holds, a named view with its camera, the words it was
  painted from and the painter that made it, each a bounded object;
- what it may show: no world that holds, or held, a photograph is given one, so nothing derived
  from a photograph is painted or kept (held on what the world is made of, as History's pictures);
- how many: at most :data:`PAINTINGS_PER_WORLD` a world. The same bytes kept twice are one.

A world's paintings are deleted with it, by its identity's own trigger (0226).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Final

import psycopg

from exulanica.world.saved_entry_pictures import PictureRefused, checked_picture
from exulanica.world.worlds import require_world

__all__ = [
    "LABEL",
    "PAINTINGS_PER_WORLD",
    "PAINTINGS_PROFILE",
    "KeptPainting",
    "WorldPaintingRepository",
]

PAINTINGS_PROFILE: Final = "exulanica.world-paintings/v1"
#: What every painting is, said wherever one is shown.
LABEL: Final = "invented appearance"
#: The most paintings a world keeps: a few views a run, a few runs a world.
PAINTINGS_PER_WORLD: Final = 64
VIEW_PATTERN: Final = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
RECIPE_PATTERN: Final = re.compile(r"^[a-z][a-z0-9-]{0,47}/v[1-9][0-9]{0,5}$")
RUN_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
#: Each described part's canonical JSON, at most (the migration holds the same bounds).
_OBJECT_BYTES: Final = {"camera": 4096, "words": 8192, "painter": 8192}
_COLUMNS: Final = (
    "view,recipe,media_type,sha256,byte_size,width,height,camera,words,painter,held_permille,"
    "cost_microusd,run_id,made_at"
)


@dataclass(frozen=True, slots=True)
class KeptPainting:
    """A kept painting's record, without its bytes."""

    view: str
    recipe: str
    media_type: str
    sha256: str
    byte_size: int
    width: int
    height: int
    camera: dict[str, Any]
    words: dict[str, Any]
    painter: dict[str, Any]
    held_permille: int
    cost_microusd: int
    run_id: str
    made_at: dt.datetime

    def view_record(self) -> dict[str, Any]:
        """What a read serves of it: the digest that fetches it, what it is of, how it was made."""
        return {
            "view": self.view,
            "recipe": self.recipe,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "camera": self.camera,
            "words": self.words,
            "painter": self.painter,
            "held_permille": self.held_permille,
            "made_at": self.made_at.isoformat(),
            "label": LABEL,
        }


def _kept(row: dict[str, Any]) -> KeptPainting:
    return KeptPainting(**{key: row[key] for key in KeptPainting.__slots__})


def _named(pattern: re.Pattern[str], value: str, code: str, what: str) -> str:
    if not pattern.match(value):
        raise PictureRefused(code, f"{what} is not a name this run may state", 422)
    return value


def _object(name: str, value: Any) -> str:
    if not isinstance(value, dict):
        raise PictureRefused("painting_record", f"a painting's {name} is an object", 422)
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(text) > _OBJECT_BYTES[name]:
        raise PictureRefused(
            "painting_record",
            f"a painting's {name} is at most {_OBJECT_BYTES[name]} bytes",
            422,
        )
    return text


class WorldPaintingRepository:
    """A workspace's world paintings: kept by the operator's run and by a showcase world's copy,
    read by the world's readers."""

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self.connection = connection
        self.workspace_id = workspace_id

    def held_world(self, world_id: str) -> None:
        """Refuse a world this workspace does not hold (404, as every world route)."""
        require_world(self.connection, self.workspace_id, world_id)

    def _refuse_photographs(self, world_id: str) -> None:
        """Refuse a world that holds, or held, a photograph: a personal source's, or any source
        attached to one of its saved entries now or before (History's pictures hold the same)."""
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
                "a world that holds a photograph is given no painting",
                422,
            )

    def keep(
        self,
        world_id: str,
        *,
        view: str,
        recipe: str,
        data: bytes,
        media_type: str,
        camera: dict[str, Any],
        words: dict[str, Any],
        painter: dict[str, Any],
        held_permille: int,
        cost_microusd: int,
        run_id: str,
    ) -> KeptPainting:
        """Keep one painting of the world, or answer the one already kept with the same bytes."""
        self.held_world(world_id)
        self._refuse_photographs(world_id)
        _named(VIEW_PATTERN, view, "painting_view", "the view")
        _named(RECIPE_PATTERN, recipe, "painting_recipe", "the recipe")
        _named(RUN_PATTERN, run_id, "painting_run", "the run")
        if not 0 <= held_permille <= 1000 or cost_microusd < 0:
            raise PictureRefused(
                "painting_record", "a hold is 0 to 1000 and a cost is not negative", 422
            )
        width, height, sha256 = checked_picture(data, media_type)
        texts = {
            "camera": _object("camera", camera),
            "words": _object("words", words),
            "painter": _object("painter", painter),
        }
        held = self.connection.execute(
            "select count(*) as n from world_painting where workspace_id=%s and world_id=%s",
            (self.workspace_id, world_id),
        ).fetchone()
        if held is not None and held["n"] >= PAINTINGS_PER_WORLD:
            raise PictureRefused(
                "paintings_full", f"a world keeps at most {PAINTINGS_PER_WORLD} paintings", 409
            )
        self.connection.execute(
            "insert into world_painting(workspace_id,world_id,view,recipe,media_type,bytes,"
            "byte_size,sha256,width,height,camera,words,painter,held_permille,cost_microusd,"
            "run_id) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s) "
            "on conflict (workspace_id,world_id,sha256) do nothing",
            (
                self.workspace_id,
                world_id,
                view,
                recipe,
                media_type,
                data,
                len(data),
                sha256,
                width,
                height,
                texts["camera"],
                texts["words"],
                texts["painter"],
                held_permille,
                cost_microusd,
                run_id,
            ),
        )
        row = self.connection.execute(
            f"select {_COLUMNS} from world_painting "
            "where workspace_id=%s and world_id=%s and sha256=%s",
            (self.workspace_id, world_id, sha256),
        ).fetchone()
        return _kept(row)

    def paintings(self, world_id: str) -> list[KeptPainting]:
        """The world's paintings, newest first, without their bytes."""
        self.held_world(world_id)
        rows = self.connection.execute(
            f"select {_COLUMNS} from world_painting where workspace_id=%s and world_id=%s "
            "order by made_at desc, view, sha256",
            (self.workspace_id, world_id),
        ).fetchall()
        return [_kept(row) for row in rows]

    def picture(self, world_id: str, sha256: str) -> tuple[str, bytes] | None:
        """A kept painting's type and bytes in the world, by its digest; else none."""
        self.held_world(world_id)
        row = self.connection.execute(
            "select media_type,bytes from world_painting "
            "where workspace_id=%s and world_id=%s and sha256=%s",
            (self.workspace_id, world_id, sha256),
        ).fetchone()
        return None if row is None else (row["media_type"], bytes(row["bytes"]))
