"""Settings: named landscapes a world of a kind can stand in, as data.

One reviewed file, ``assets/catalogs/landscape-settings/landscape-setting.vN.json``. Each entry
states a ``key``, a ``label``, an ``exulanica.landscape/v1`` document (``landscape``) read and held
as every landscape is (:func:`~exulanica.grammar.landscape.document.read_landscape_document`), the
shipped kinds whose worlds start on it (``starters``, each a ``kind`` and its ``version``), and a
``reason`` and a ``licence``. A kind starts on one setting at most; keys are unique. From version 2
an entry may name ``setting_parts``: a part's key for each axis it names (a sky, a ground, a cover),
the setting a world started on it is drawn in, over whatever look the world wears.

What a starter is made on and drawn in is the world layer's to say (the library's
:func:`~exulanica.world.kinds.library.starter_landscape` and
:func:`~exulanica.world.kinds.library.starter_setting_parts`, which hold the kind to the shipped
document itself and the parts to the setting parts catalog). A catalog changes only by a new
version; version 1 stays at its path and is not read. Read on first use, never at import, and kept
for the process; each landscape handed out is a copy.
"""

from __future__ import annotations

import copy
import functools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.grammar.documents import read_json
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.landscape.document import LandscapeRefused, read_landscape_document

__all__ = [
    "SETTINGS_DIRECTORY",
    "SETTINGS_VERSION",
    "LandscapeSetting",
    "landscape_settings",
    "read_settings",
    "starting_setting",
]

SETTINGS_DIRECTORY: Final = (
    Path(__file__).resolve().parents[3].joinpath("assets", "catalogs", "landscape-settings")
)
#: The settings catalog this code reads.
SETTINGS_VERSION: Final = 2
_CATALOG_ID: Final = "landscape-setting"
_KEYS: Final = frozenset({"schema_version", "catalog_id", "catalog_version", "entries"})
_ENTRY: Final = frozenset({"key", "label", "landscape", "starters", "reason", "licence"})
#: What an entry may state besides.
_OPTIONAL: Final = frozenset({"setting_parts"})
#: The most axes an entry's parts name, as a style pack's stated parts may.
_PARTS_AT_MOST: Final = 8
_STARTER: Final = frozenset({"kind", "version"})
_KEY: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")
_LICENCES: Final = ("Apache-2.0", "CC-BY-4.0", "CC0-1.0", "MIT")


@dataclass(frozen=True, slots=True)
class LandscapeSetting:
    key: str
    label: str
    #: The kinds whose worlds start on it, each its key and version.
    starters: tuple[tuple[str, int], ...]
    _landscape: Mapping[str, Any]
    #: The setting a world started on it is drawn in: each axis it names and that axis's part.
    setting_parts: tuple[tuple[str, str], ...] = ()

    def landscape(self) -> dict[str, Any]:
        """The setting's landscape document, a copy the caller owns."""
        return copy.deepcopy(dict(self._landscape))


def _refused(where: str, detail: str) -> CatalogError:
    return CatalogError(f"landscape-setting.v{SETTINGS_VERSION}.json {where}: {detail}")


def _keys(
    where: str, raw: object, keys: frozenset[str], optional: frozenset[str] = frozenset()
) -> Mapping[str, Any]:
    if not isinstance(raw, dict) or not keys <= set(raw) <= keys | optional:
        got = sorted(raw) if isinstance(raw, dict) else type(raw).__name__
        also = f", and may state {sorted(optional)}" if optional else ""
        raise _refused(where, f"states exactly {sorted(keys)}{also}, got {got}")
    return raw


def _text(where: str, raw: object, words: int = 1) -> str:
    if not isinstance(raw, str) or len(raw.split()) < words or raw != raw.strip():
        raise _refused(where, f"is text of at least {words} words, trimmed")
    return raw


def _entry(index: int, raw: object) -> LandscapeSetting:
    where = f"entries[{index}]"
    entry = _keys(where, raw, _ENTRY, _OPTIONAL)
    key = entry["key"]
    if not isinstance(key, str) or _KEY.fullmatch(key) is None:
        raise _refused(f"{where}.key", "is a lowercase key of letters, digits and underscores")
    _text(f"{where}.label", entry["label"])
    _text(f"{where}.reason", entry["reason"], 5)
    licence = entry["licence"]
    if not isinstance(licence, dict) or licence.get("spdx") not in _LICENCES:
        raise _refused(f"{where}.licence", f"names one of {list(_LICENCES)}")
    try:
        read_landscape_document(entry["landscape"])
    except LandscapeRefused as exc:
        raise _refused(f"{where}.landscape", str(exc)) from exc
    starters = entry["starters"]
    if not isinstance(starters, list) or not starters:
        raise _refused(f"{where}.starters", "lists at least one kind")
    named: list[tuple[str, int]] = []
    for at, raw_starter in enumerate(starters):
        starter = _keys(f"{where}.starters[{at}]", raw_starter, _STARTER)
        kind, version = starter["kind"], starter["version"]
        if not isinstance(kind, str) or _KEY.fullmatch(kind) is None:
            raise _refused(f"{where}.starters[{at}].kind", "is a kind's key")
        if type(version) is not int or version < 1:
            raise _refused(f"{where}.starters[{at}].version", "is a whole number from 1")
        named.append((kind, version))
    return LandscapeSetting(
        key=key,
        label=entry["label"],
        starters=tuple(named),
        _landscape=copy.deepcopy(entry["landscape"]),
        setting_parts=_parts(f"{where}.setting_parts", entry.get("setting_parts", {})),
    )


def _parts(where: str, raw: object) -> tuple[tuple[str, str], ...]:
    """An entry's setting parts by axis, in the axes' names' order. Which axes and parts exist is
    the setting parts catalog's, held where a world is drawn in them."""
    if not isinstance(raw, dict) or len(raw) > _PARTS_AT_MOST:
        raise _refused(where, f"names a part for each of at most {_PARTS_AT_MOST} axes")
    for axis, part in raw.items():
        if (
            _KEY.fullmatch(axis) is None
            or not isinstance(part, str)
            or _KEY.fullmatch(part) is None
        ):
            raise _refused(f"{where}.{axis}", "names an axis's part by its lowercase key")
    return tuple(sorted(raw.items()))


def read_settings(raw: object) -> tuple[LandscapeSetting, ...]:
    """Admit a settings catalog, or refuse it by where it broke."""
    document = _keys("", raw, _KEYS)
    if document["schema_version"] != 1 or document["catalog_id"] != _CATALOG_ID:
        raise _refused("", f"is schema version 1 of {_CATALOG_ID}")
    if document["catalog_version"] != SETTINGS_VERSION:
        raise _refused("catalog_version", f"is {SETTINGS_VERSION}")
    entries = document["entries"]
    if not isinstance(entries, list) or not entries:
        raise _refused("entries", "lists at least one setting")
    settings = tuple(_entry(index, entry) for index, entry in enumerate(entries))
    keys = [setting.key for setting in settings]
    if len(set(keys)) != len(keys):
        raise _refused("entries", "name each setting once")
    starters: Sequence[tuple[str, int]] = [s for setting in settings for s in setting.starters]
    if len(set(starters)) != len(starters):
        raise _refused("entries", "start each kind on one setting at most")
    return settings


@functools.cache
def landscape_settings() -> tuple[LandscapeSetting, ...]:
    """Every setting the product ships, read once."""
    return read_settings(
        read_json(SETTINGS_DIRECTORY.joinpath(f"landscape-setting.v{SETTINGS_VERSION}.json"))
    )


def starting_setting(kind: str, version: int) -> LandscapeSetting | None:
    """The setting a kind of this key and version starts on, or None."""
    return next(
        (s for s in landscape_settings() if (kind, version) in s.starters),
        None,
    )
