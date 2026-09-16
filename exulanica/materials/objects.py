"""Material objects as bytes: the strict reader, the profiles, and freezing.

Every material object is canonical JSON, named by the sha256 of its bytes, and says what it is in
its ``profile``. The package that writes them, ``web/packages/loom-texture``, accepts only safe
integers and printable ASCII, so a document is read back here under exactly the same rules: a
float, a non-finite constant, a repeated key, an integer JavaScript cannot hold exactly, or a
character outside printable ASCII is refused, and so is any byte sequence that is not already the
canonical serialisation of what it parses to. A document that passes has one byte form, and that
form is its identity.

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
    "RECIPE_PROFILE",
    "SAFE_INTEGER",
    "MaterialObjectError",
    "canonical_bytes",
    "freeze",
    "is_sha256",
    "portable",
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

_PRINTABLE: Final = re.compile(r"[\x20-\x7e]*")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")


class MaterialObjectError(ExulanicaError):
    """A document is not the material object it claims to be, or objects disagree."""


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


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


def _refuse_float(literal: str) -> Any:
    raise MaterialObjectError(f"non-integer number {literal} in a material object")


def _refuse_constant(literal: str) -> Any:
    raise MaterialObjectError(f"{literal} is not a value a material object may hold")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MaterialObjectError(f"key {key!r} appears twice in one object")
        result[key] = value
    return result


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


def canonical_bytes(document: Any) -> bytes:
    """A document's canonical bytes, frozen or not: what its digest is taken over."""
    return canonical_json(thaw(document))


def read_object(raw: bytes, where: str) -> Any:
    """Parse a material object's bytes strictly and return the document, frozen."""
    try:
        document = json.loads(
            raw.decode("utf-8"),
            parse_float=_refuse_float,
            parse_constant=_refuse_constant,
            object_pairs_hook=_unique_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise MaterialObjectError(f"{where} is not JSON: {error}") from error
    except MaterialObjectError as error:
        raise MaterialObjectError(f"{where}: {error}") from error
    if not portable(document):
        raise MaterialObjectError(f"{where} holds an integer or a string the baker cannot write")
    try:
        canonical = canonical_json(document)
    except CanonicalisationError as error:
        raise MaterialObjectError(f"{where}: {error}") from error
    if canonical != raw:
        raise MaterialObjectError(
            f"{where} is not canonical JSON, so its bytes are not its content"
        )
    return freeze(document)
