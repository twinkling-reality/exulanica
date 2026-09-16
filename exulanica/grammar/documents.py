"""Reading a versioned JSON data file, strictly.

Every data file this package reads is named ``<id>.v<version>.json`` and says the same id and
version inside it, the shape ``exulanica/world/style-registry.v1.json`` set. Parsing is strict
in the three ways the standard library is not: a float is refused at parse time rather than
carried to a digest, ``NaN`` and ``Infinity`` are refused, and a key repeated inside one object
is refused rather than silently resolved to its last value.

Paths are joined with ``joinpath`` throughout this package rather than the ``/`` operator,
because the package forbids true division outright and a scan cannot tell the two apart.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final

from exulanica.grammar.errors import CatalogError

__all__ = ["read_json", "split_versioned_name"]

_NAME: Final = re.compile(r"([a-z][a-z0-9-]*)\.v([1-9][0-9]*)\.json")


def split_versioned_name(path: Path) -> tuple[str, int]:
    """``typology.v1.json`` becomes ``("typology", 1)``. Anything else is refused."""
    matched = _NAME.fullmatch(path.name)
    if matched is None:
        raise CatalogError(f"{path.name} is not named <id>.v<version>.json")
    return matched.group(1), int(matched.group(2))


def read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CatalogError(f"cannot read {path}: {error}") from error
    try:
        return json.loads(
            text,
            parse_float=_refuse_float,
            parse_constant=_refuse_constant,
            object_pairs_hook=_refuse_duplicates,
        )
    except json.JSONDecodeError as error:
        raise CatalogError(f"{path.name} is not valid JSON: {error}") from error
    except CatalogError as error:
        raise CatalogError(f"{path.name}: {error}") from error


def _refuse_float(literal: str) -> Any:
    raise CatalogError(f"non-integer number {literal}; quantise it to an integer unit first")


def _refuse_constant(literal: str) -> Any:
    raise CatalogError(f"{literal} is not a JSON value this package accepts")


def _refuse_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError(f"key {key!r} appears twice in one object")
        result[key] = value
    return result
