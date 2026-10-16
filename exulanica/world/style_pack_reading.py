"""The value readers every field of a style pack manifest goes through, and the refusal they raise.

Each reader takes a JSON value and the path it was read at, and answers the value as read or refuses
it by name (:class:`StylePackRefused`): the reason, and the path of the first fault.
:mod:`~exulanica.world.style_packs` reads a manifest with them and re-exports the public names. The
browser's reader holds the same rules in ``web/packages/atlas-core/src/style-pack-reading.ts``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, NoReturn

#: C0 controls, DEL and C1 controls.
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")

#: The Unicode Bidi_Control characters: marks, embeddings, overrides and isolates, which can make
#: text read in an order other than the one it is stored in.
_BIDI_CONTROL: Final = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")

#: A surrogate code point on its own: JSON can escape one, but it is no character, and no UTF-8
#: or UTF-16 encoder writes it.
_SURROGATE: Final = re.compile("[\ud800-\udfff]")


class StylePackRefused(ValueError):
    """A manifest refused by name: the reason, and the path of the first fault."""

    def __init__(self, reason: str, path: str, detail: str) -> None:
        self.reason = reason
        self.path = path
        super().__init__(f"{path or 'manifest'}: {detail}")


Reader = Callable[[Any, str], Any]


@dataclass(frozen=True, slots=True)
class _Optional:
    """A field a manifest may leave out.

    A field added within a profile is optional and its absence keeps the meaning a manifest had
    before the field existed, so every manifest written under the profile still reads. A manifest
    that leaves it out is returned without it, as given, so its bytes and digest are its own; a
    reader of the result takes the absence as that earlier meaning.
    """

    read: Reader


def _fail(reason: str, path: str, detail: str) -> NoReturn:
    raise StylePackRefused(reason, path, detail)


def _join(path: str, key: str) -> str:
    return key if path == "" else f"{path}.{key}"


def _object(value: Any, path: str, fields: Mapping[str, Reader | _Optional]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("shape", path, "must be an object")
    for key in value:
        if key not in fields:
            _fail("shape", path, f"has an unknown key {json.dumps(key)}")
    out: dict[str, Any] = {}
    for key, field in fields.items():
        if key not in value:
            if isinstance(field, _Optional):
                continue
            _fail("shape", path, f"is missing {json.dumps(key)}")
        read = field.read if isinstance(field, _Optional) else field
        out[key] = read(value[key], _join(path, key))
    return out


def _integer(minimum: int, maximum: int) -> Reader:
    def read(value: Any, path: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            _fail("shape", path, "must be a whole number")
        if value < minimum or value > maximum:
            _fail("range", path, f"must be within {minimum} to {maximum}")
        return int(value)

    return read


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail("shape", path, "must be true or false")
    return bool(value)


def _one_of(values: tuple[str, ...]) -> Reader:
    def read(value: Any, path: str) -> str:
        if not isinstance(value, str) or value not in values:
            _fail("range", path, f"must be one of {', '.join(values)}")
        return str(value)

    return read


def _literal(expected: str) -> Reader:
    def read(value: Any, path: str) -> str:
        if value != expected or not isinstance(value, str):
            _fail("shape", path, f"must be {json.dumps(expected)}")
        return expected

    return read


def _pattern(regex: re.Pattern[str], what: str) -> Reader:
    def read(value: Any, path: str) -> str:
        if not isinstance(value, str) or regex.fullmatch(value) is None:
            _fail("shape", path, f"must be {what}")
        return str(value)

    return read


def _text(maximum: int, *, allow_empty: bool = False) -> Reader:
    def read(value: Any, path: str) -> str:
        if not isinstance(value, str):
            _fail("shape", path, "must be text")
        # No leading or trailing space, and no control character: the same rule in every reader.
        if value.startswith(" ") or value.endswith(" ") or (not allow_empty and value == ""):
            _fail("shape", path, "must be trimmed text, not empty")
        if _SURROGATE.search(value):
            _fail("shape", path, "must hold no lone surrogate")
        # JavaScript counts UTF-16 code units; count the same here.
        if len(value.encode("utf-16-le")) // 2 > maximum:
            _fail("range", path, f"must be at most {maximum} characters")
        if _CONTROL.search(value):
            _fail("shape", path, "must hold no control characters")
        if _BIDI_CONTROL.search(value):
            _fail("shape", path, "must hold no bidirectional control characters")
        return str(value)

    return read


def is_plain_text(value: str, maximum: int) -> bool:
    """Whether ``value`` meets the readers' text rule: trimmed, not empty, at most ``maximum``
    UTF-16 units, and no lone surrogate, control or bidirectional control character."""
    try:
        _text(maximum)(value, "")
    except StylePackRefused:
        return False
    return True


def _nullable(read: Reader) -> Reader:
    def wrapped(value: Any, path: str) -> Any:
        return None if value is None else read(value, path)

    return wrapped


def _srgb8(value: Any, path: str) -> list[int]:
    if not isinstance(value, list) or len(value) != 3:
        _fail("shape", path, "must be three sRGB bytes")
    return [_integer(0, 255)(channel, f"{path}[{index}]") for index, channel in enumerate(value)]


def _list(read: Reader, minimum: int, maximum: int) -> Reader:
    def wrapped(value: Any, path: str) -> list[Any]:
        if not isinstance(value, list):
            _fail("shape", path, "must be a list")
        if len(value) < minimum or len(value) > maximum:
            _fail("range", path, f"must hold {minimum} to {maximum} items")
        return [read(item, f"{path}[{index}]") for index, item in enumerate(value)]

    return wrapped


def _record(read_key: Callable[[str, str], None], read: Reader, maximum: int) -> Reader:
    def wrapped(value: Any, path: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            _fail("shape", path, "must be an object")
        if len(value) > maximum:
            _fail("range", path, f"must hold at most {maximum} entries")
        out: dict[str, Any] = {}
        for key, item in value.items():
            read_key(key, _join(path, key))
            out[key] = read(item, _join(path, key))
        return out

    return wrapped
