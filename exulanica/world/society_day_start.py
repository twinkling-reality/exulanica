"""The minute a new society's day starts at, from its world's setting and look.

A world made "at dusk" is lit from its look's evening; a society made in it starts its clock at
that hour, so the clock and the sky agree. ``society-day-start.v1.json`` gives a minute for each
sky part a setting may name (``from: sky_part``), and, for a world whose setting names no sky part
or that has none, a minute by where its look's own day sun stands (``from: day_sun``: the first
entry whose ``sun_azimuth_below_mdeg`` passes the sun's azimuth in the pack's default preset). A
look the style pack library does not hold, or none, starts at the society policy's own minute. The
minute is read once, when a society's first input is composed, and recorded in its people frame
(:func:`~exulanica.world.town_people.people_frame`), so a society keeps the clock it started with
whatever its world's look becomes, and one made before the catalog keeps the minute it recorded.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol

import psycopg

from exulanica.grammar.catalogs import load_catalog
from exulanica.world.society_catalogs import ROUTINE_DIRECTORY, SCHEMAS
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.style_packs import StylePackRefused
from exulanica.world.world_settings import resolve_chain, setting_rules

__all__ = [
    "CATALOG_PATH",
    "DayStartRefused",
    "DayStarts",
    "World",
    "day_starts",
    "day_sun_azimuth",
    "start_minute_for",
    "world_day_start",
]

CATALOG_PATH: Final = ROUTINE_DIRECTORY / "society-day-start.v1.json"
#: The schema the society catalogs' directory claims the file under.
_SCHEMA: Final = SCHEMAS[("society-day-start", 1)]
#: A whole turn of azimuth, which the day sun's entries together cover.
_TURN_MDEG: Final = 360_000
#: The setting and the pack the world's current appearance states, if any: one row.
_LOOK_SQL: Final = (
    "select v.style_pack_setting as setting, v.style_pack_manifest_sha256 as manifest "
    "from world_style_state s join world_style_version v on v.workspace_id=s.workspace_id "
    "and v.world_id=s.world_id and v.version_id=s.current_style_version_id "
    "where s.workspace_id=%s and s.world_id=%s"
)


class DayStartRefused(ValueError):
    """The catalog states something no setting or sun may be read as."""


class World(Protocol):
    """A world by its workspace and id, as a society's binding names it."""

    @property
    def workspace_id(self) -> uuid.UUID: ...

    @property
    def world_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class DayStarts:
    """The catalog as read: a minute by sky part, and by the look's day sun."""

    by_sky: Mapping[str, int]
    #: ``(azimuth below, minute)``, ascending, the last bound a whole turn.
    by_sun: tuple[tuple[int, int], ...]

    def for_sun(self, azimuth_mdeg: int) -> int:
        """The minute of the first day sun entry whose bound passes ``azimuth_mdeg``."""
        return next(minute for below, minute in self.by_sun if azimuth_mdeg % _TURN_MDEG < below)


@functools.cache
def day_starts(path: Path = CATALOG_PATH) -> DayStarts:
    """The catalog, checked: every sky part entry a sky part the setting rules name, with no
    bound; every day sun entry named apart from them, with one; and the day sun's bounds reaching
    a whole turn, so every sun is read."""
    catalog = load_catalog(path, _SCHEMA)
    skies = setting_rules().part_names["sky"]
    by_sky: dict[str, int] = {}
    by_sun: list[tuple[int, int]] = []
    for entry in catalog.entries:
        values = dict(entry.values)
        below, minute = int(values["sun_azimuth_below_mdeg"]), int(values["start_minute_of_day"])
        if values["from"] == "sky_part":
            if entry.key not in skies or below != 0:
                raise DayStartRefused(
                    f"{path.name}: {entry.key!r} is no sky part, or states a bound"
                )
            by_sky[entry.key] = minute
        elif entry.key in skies or below == 0:
            raise DayStartRefused(
                f"{path.name}: {entry.key!r} is named as a sky part, or has no bound"
            )
        else:
            by_sun.append((below, minute))
    by_sun.sort()
    if not by_sun or by_sun[-1][0] != _TURN_MDEG:
        raise DayStartRefused(f"{path.name}: the day sun's entries reach {_TURN_MDEG} millidegrees")
    return DayStarts(MappingProxyType(by_sky), tuple(by_sun))


def day_sun_azimuth(manifest_sha256: str | None) -> int | None:
    """Where the sun stands in the look's own day (its pack's default preset), as an azimuth in
    millidegrees, for a pack the style pack library holds; None for any other, or none."""
    chain = None if manifest_sha256 is None else style_pack_library().chain(manifest_sha256)
    if chain is None:
        return None
    try:
        light = resolve_chain(chain).light
    except StylePackRefused:
        return None
    sun = light["presets"].get(light["default_preset"], {}).get("sun")
    return None if sun is None else int(sun["azimuth_mdeg"])


def start_minute_for(setting: Mapping[str, Any] | None, day_sun_mdeg: int | None) -> int | None:
    """The minute a society made in a world of ``setting`` (a stored setting document, or none)
    and of a look whose day sun stands at ``day_sun_mdeg`` starts its day at, or None for the
    policy's own: the minute of its sky part, else of its look's day sun."""
    starts = day_starts()
    for part in (setting or {}).get("parts") or ():
        if part.get("axis") == "sky" and part.get("key") in starts.by_sky:
            return starts.by_sky[part["key"]]
    return None if day_sun_mdeg is None else starts.for_sun(day_sun_mdeg)


def world_day_start(connection: psycopg.Connection, world: World) -> int | None:
    """:func:`start_minute_for` the setting and look the current appearance of ``world`` states,
    read on ``connection`` (rows as mappings); None where it states neither."""
    row = connection.execute(_LOOK_SQL, (world.workspace_id, world.world_id)).fetchone()
    if row is None:
        return None
    return start_minute_for(row["setting"], day_sun_azimuth(row["manifest"]))
