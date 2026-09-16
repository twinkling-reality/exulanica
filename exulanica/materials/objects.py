"""Material objects as bytes: the strict reader, the profiles, and freezing.

Every material object is canonical JSON, named by the sha256 of its bytes, and says what it is in
its ``profile``. The package that writes them, ``web/packages/loom-texture``, accepts only safe
integers and printable ASCII, so a document is read back here under exactly the same rules.

:func:`parse_strict` is the byte-level rule both languages share with ``loom-texture``'s
``src/strict-json.ts``: a number is an integer literal in the safe range, no object repeats a key,
nothing nests deeper than :data:`MAXIMUM_DEPTH`, and the bytes are UTF-8 with no byte-order mark.
Every refusal is one of the five :data:`STRICT_JSON_PROBLEMS`, chosen by the same fixed precedence
in both languages, and the ``documents`` cases in ``web/packages/loom-texture/test/
recipe-cases.json`` hold the two to it. :func:`read_object` adds the object rules on top: every
string printable ASCII, and the bytes exactly the canonical serialisation of what they parse to, so
a document that passes has one byte form and that form is its identity.

Documents are handed out frozen, mappings as read-only proxies and lists as tuples, because a
digest names content and content named by a digest must not change under anyone's hands.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.errors import CanonicalisationError, ExulanicaError

__all__ = [
    "BAKE_PIPELINE",
    "BAKE_RECEIPT_PROFILE",
    "CATALOG_PROFILE",
    "LIBRARY_ENTRY_PROFILE",
    "MAKER_PROFILE",
    "MAXIMUM_DEPTH",
    "RECIPE_PROFILE",
    "SAFE_INTEGER",
    "STRICT_JSON_PROBLEMS",
    "MaterialObjectError",
    "canonical_bytes",
    "freeze",
    "identical",
    "is_sha256",
    "nesting",
    "parse_strict",
    "portable",
    "read_document",
    "read_object",
    "sha256_hex",
    "thaw",
]

MAKER_PROFILE: Final = "exulanica.texture-maker/v1"
RECIPE_PROFILE: Final = "exulanica.texture-recipe/v1"
LIBRARY_ENTRY_PROFILE: Final = "exulanica.texture-library-entry/v1"
BAKE_RECEIPT_PROFILE: Final = "exulanica.texture-bake-receipt/v1"
CATALOG_PROFILE: Final = "exulanica.texture-catalog/v1"
#: The bake itself: sampling, the normal and cavity derivations, quantisation and the container.
BAKE_PIPELINE: Final = "exulanica.texture-bake/v1"
#: The largest integer an IEEE double holds exactly, which is the largest the baker can write.
SAFE_INTEGER: Final = 9_007_199_254_740_991

_SAFE_DIGITS: Final = str(SAFE_INTEGER)
MAXIMUM_DEPTH: Final = 64
#: The five ways strict JSON is refused, in the order of precedence both languages apply.
STRICT_JSON_PROBLEMS: Final = MappingProxyType(
    {
        "depth": f"a document nests more than {MAXIMUM_DEPTH} deep",
        "syntax": "a document is not JSON",
        "number": "a number is written with a fraction or an exponent",
        "range": "an integer is outside the safe range",
        "duplicate": "an object repeats a key",
    }
)

_PRINTABLE: Final = re.compile(r"[\x20-\x7e]*")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")


class MaterialObjectError(ExulanicaError):
    """A document is not the material object it claims to be, or objects disagree."""


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def is_sha256(value: object) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


def portable(value: object) -> bool:
    """Whether both languages serialise ``value`` identically: safe integers, printable ASCII."""
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return -SAFE_INTEGER <= value <= SAFE_INTEGER
    if isinstance(value, str):
        return _PRINTABLE.fullmatch(value) is not None
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and _PRINTABLE.fullmatch(key) is not None and portable(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return all(portable(item) for item in value)
    return False


class _NotJson(Exception):
    """Raised inside the parser for a constant JSON does not have, such as NaN."""


def nesting(text: str) -> int:
    """The deepest bracket nesting outside strings. Defined on any text, JSON or not."""
    depth = 0
    deepest = 0
    in_string = False
    index = 0
    while index < len(text):
        character = text[index]
        if in_string:
            if character == "\\":
                index += 1
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif character in "]}":
            depth -= 1
        index += 1
    return deepest


def parse_strict(raw: bytes) -> Any:
    """Parse strict JSON, or raise :class:`MaterialObjectError` naming the one problem it has."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MaterialObjectError(STRICT_JSON_PROBLEMS["syntax"]) from error
    if nesting(text) > MAXIMUM_DEPTH:
        raise MaterialObjectError(STRICT_JSON_PROBLEMS["depth"])
    found: set[str] = set()

    def on_float(literal: str) -> int:
        found.add("number")
        return 0

    def on_int(literal: str) -> int:
        digits = literal[1:] if literal.startswith("-") else literal
        if len(digits) > len(_SAFE_DIGITS) or (
            len(digits) == len(_SAFE_DIGITS) and digits > _SAFE_DIGITS
        ):
            found.add("range")
            return 0
        return int(literal)

    def on_constant(literal: str) -> Any:
        raise _NotJson(literal)

    def on_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                found.add("duplicate")
            result[key] = value
        return result

    try:
        document = json.loads(
            text,
            parse_float=on_float,
            parse_int=on_int,
            parse_constant=on_constant,
            object_pairs_hook=on_pairs,
        )
    except (json.JSONDecodeError, _NotJson, ValueError, RecursionError) as error:
        raise MaterialObjectError(STRICT_JSON_PROBLEMS["syntax"]) from error
    for kind in ("number", "range", "duplicate"):
        if kind in found:
            raise MaterialObjectError(STRICT_JSON_PROBLEMS[kind])
    return document


def freeze(value: Any) -> Any:
    """A deep, read-only copy: mappings become proxies over fresh dicts, lists become tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """A deep, mutable copy of a frozen document, as ``json.loads`` would have returned it."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [thaw(item) for item in value]
    return value


def identical(left: Any, right: Any) -> bool:
    """Whether two documents are the same JSON, frozen or not, with ``true`` never equal to ``1``.

    Python's ``==`` says ``True == 1`` and ``1 == 1.0``, which two canonical documents never do:
    their bytes differ. Every comparison between a document and what it must say uses this.
    """
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(
            identical(item, right[key]) for key, item in left.items()
        )
    if isinstance(left, list | tuple) and isinstance(right, list | tuple):
        return len(left) == len(right) and all(map(identical, left, right))
    return type(left) is type(right) and left == right


def canonical_bytes(document: Any) -> bytes:
    """A document's canonical bytes, frozen or not: what its digest is taken over."""
    return canonical_json(thaw(document))


def read_document(raw: bytes, where: str) -> Any:
    """A material object's document, read strictly and held to its canonical form, mutable."""
    try:
        document = parse_strict(raw)
    except MaterialObjectError as error:
        raise MaterialObjectError(f"{where}: {error}") from error
    if not portable(document):
        raise MaterialObjectError(f"{where} holds a string the baker cannot write")
    try:
        canonical = canonical_json(document)
    except CanonicalisationError as error:
        raise MaterialObjectError(f"{where}: {error}") from error
    if canonical != raw:
        raise MaterialObjectError(
            f"{where} is not canonical JSON, so its bytes are not its content"
        )
    return document


def read_object(raw: bytes, where: str) -> Any:
    """A material object's document, read as :func:`read_document` reads it, and frozen."""
    return freeze(read_document(raw, where))
