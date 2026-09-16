"""Records: frozen dataclasses of integers and strings, and the canonical form a digest reads.

Every value a grammar emits is a record, and every record reaches a digest through
:func:`canonical_record`, which is ``exulanica.canonical.canonical_json`` over
:func:`record_payload`. Nothing else serialises a record.

**A float is left for canonical JSON to refuse.** The conversion below passes an unrecognised
value through untouched rather than rejecting it itself, so the refusal that fires is
``CanonicalisationError`` from ``exulanica.canonical``, the one every digest in the repository
already relies on. A second, local float check would be a second rule that could drift from the
first. Quantise to millimetres, microradians and millionths before a value becomes a record.

Everything else that is not an ``int``, a ``str``, a ``tuple`` or a nested dataclass is refused
here, including ``bool`` and ``None``. A value a record does not have is a field it does not
carry, not a ``None`` somebody has to remember to read.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from typing import Any, Final, TypeVar

from exulanica.canonical import canonical_json
from exulanica.grammar.errors import InvalidRecordError

__all__ = [
    "KEY_PATTERN",
    "MAX_SAFE_INTEGER",
    "canonical_record",
    "record_payload",
    "require_hex64",
    "require_identity",
    "require_increasing",
    "require_integer",
    "require_key",
    "require_pairs",
    "require_record",
    "require_text",
]

_R = TypeVar("_R")

#: The largest integer an IEEE 754 double holds exactly. A record is read by a TypeScript
#: tessellator as well as by Python, so a record integer beyond this would be two different
#: numbers in two languages. A raw 64-bit draw is beyond it; bound a draw before recording it.
MAX_SAFE_INTEGER: Final = (1 << 53) - 1

#: A key into a catalog or a closed vocabulary.
KEY_PATTERN: Final = re.compile(r"[a-z][a-z0-9_]*")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_IDENTITY: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def record_payload(record: object) -> dict[str, Any]:
    """``{"kind", "version", "fields"}`` for a record class that declares both, else the fields."""
    if not dataclasses.is_dataclass(record) or isinstance(record, type):
        raise InvalidRecordError(f"a record is a dataclass instance, not {type(record).__name__}")
    if not type(record).__dataclass_params__.frozen:  # type: ignore[attr-defined]
        raise InvalidRecordError(f"{type(record).__name__} is not frozen")
    fields = {
        field.name: _convert(getattr(record, field.name), f"{type(record).__name__}.{field.name}")
        for field in dataclasses.fields(record)
    }
    kind = getattr(type(record), "RECORD_KIND", None)
    version = getattr(type(record), "RECORD_VERSION", None)
    if kind is None and version is None:
        return fields
    if type(kind) is not str or type(version) is not int:
        raise InvalidRecordError(f"{type(record).__name__} declares only half of kind and version")
    return {"kind": kind, "version": version, "fields": fields}


def canonical_record(record: object) -> bytes:
    """The canonical JSON bytes of one record. Raises ``CanonicalisationError`` on any float."""
    return canonical_json(record_payload(record))


def _convert(value: object, path: str) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return record_payload(value)
    if isinstance(value, tuple):
        return [_convert(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if type(value) is int:
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise InvalidRecordError(f"{path}: {value} does not survive a JavaScript reader")
        return value
    if type(value) is str:
        return value
    if value is None or isinstance(value, bool | list | dict | Mapping):
        raise InvalidRecordError(
            f"{path}: {type(value).__name__} is not an int, a str, a tuple or a record"
        )
    # Anything else goes through untouched, and canonical JSON refuses it: a float by name,
    # everything else as an unsupported type. This module never names the float type at all.
    return value


def require_record(record: object, record_type: type[_R]) -> _R:
    """``record`` is exactly ``record_type``, and its canonical form exists. Floats raise here."""
    if type(record) is not record_type:
        raise InvalidRecordError(f"expected {record_type.__name__}, got {type(record).__name__}")
    canonical_record(record)
    return record  # type: ignore[return-value]


def require_increasing(name: str, value: object, *, minimum: int = 0) -> tuple[int, ...]:
    """A tuple of ints, each at least ``minimum``, strictly increasing. Order is part of meaning."""
    if not isinstance(value, tuple):
        raise InvalidRecordError(f"{name} is a tuple of ints")
    for index, item in enumerate(value):
        require_integer(f"{name}[{index}]", item, minimum=minimum)
        if index and item <= value[index - 1]:
            raise InvalidRecordError(f"{name} is strictly increasing")
    return value


def require_integer(
    name: str, value: object, *, minimum: int | None = None, maximum: int | None = None
) -> int:
    if type(value) is not int:
        raise InvalidRecordError(f"{name} is an int, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise InvalidRecordError(f"{name} is {value}, below its minimum {minimum}")
    if maximum is not None and value > maximum:
        raise InvalidRecordError(f"{name} is {value}, above its maximum {maximum}")
    return value


def require_key(name: str, value: object) -> str:
    if type(value) is not str or KEY_PATTERN.fullmatch(value) is None:
        raise InvalidRecordError(f"{name} is a lowercase key, got {value!r}")
    return value


def require_text(name: str, value: object) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise InvalidRecordError(f"{name} is non-empty text with no surrounding space")
    return value


def require_hex64(name: str, value: object) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise InvalidRecordError(f"{name} is 64 lowercase hexadecimal characters")
    return value


def require_identity(name: str, value: object) -> str:
    """A subject identity is a canonical lowercase UUID string, supplied by whoever admitted it."""
    if type(value) is not str or _IDENTITY.fullmatch(value) is None:
        raise InvalidRecordError(f"{name} is a canonical lowercase UUID string, got {value!r}")
    return value


def require_pairs(name: str, value: object, *, minimum_count: int) -> tuple[tuple[int, int], ...]:
    """A tuple of integer pairs, such as a polyline in millimetres. Not vertices of a mesh."""
    if not isinstance(value, tuple) or len(value) < minimum_count:
        raise InvalidRecordError(f"{name} is a tuple of at least {minimum_count} integer pairs")
    for index, pair in enumerate(value):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise InvalidRecordError(f"{name}[{index}] is a pair")
        require_integer(f"{name}[{index}][0]", pair[0])
        require_integer(f"{name}[{index}][1]", pair[1])
    return value
