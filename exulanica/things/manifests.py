"""What an import or a crossing kept and lost: the translation manifest every translation writes.

Bringing something into a world from elsewhere is a translation, and nothing about it is silent.
Every importer and every crossing writes a manifest, profile ``exulanica.translation-manifest/v1``:
which translator (key, version, digest), from what source (its format, the source's own type for
the thing, the digest of what it read), into which thing kind and look, and for every field of the
source exactly one disposition:

*   ``exact``: carried across unchanged, to the field it names;
*   ``approximated``: carried across with a stated reason, to the field it names (an arm of one
    box mapped onto the upper arm, its elbow bend lost);
*   ``dropped``: not carried, with a stated reason (a player's name: a person's name never
    crosses; health: this world has no health);
*   ``opaque``: kept and never read here: by an importer verbatim in the kind's ``ext``; by a
    crossing, by the program it came from, under the thing's id, never stored here.

:func:`read_manifest` holds a manifest to its shape, and :func:`check_accounting` to its source:
every field the source states appears exactly once, and nothing else does. Foreign mechanics are
never emulated: a field only a module this world's rules hold could act on is dropped or opaque,
never guessed at.

Pure: no connection, no store.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

__all__ = [
    "DISPOSITIONS",
    "MANIFEST_PROFILE",
    "ManifestRefused",
    "TranslationManifest",
    "check_accounting",
    "read_manifest",
]

MANIFEST_PROFILE: Final = "exulanica.translation-manifest/v1"
DISPOSITIONS: Final = ("exact", "approximated", "dropped", "opaque")
#: The most fields one manifest accounts for: a game entity or an asset's declared fields, not a
#: mesh's every vertex.
FIELDS_MAXIMUM: Final = 512
_KEY: Final = re.compile(r"[a-z][a-z0-9_-]{0,47}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
#: A field's path in its document, as a JSON pointer: ``/inventory/0/count``.
_POINTER: Final = re.compile(r"(/[^/\x00-\x1f]{1,64}){1,8}")
_TOP: Final = frozenset({"profile", "translator", "source", "target", "fields"})
_FIELD: Final = frozenset({"path", "disposition", "to", "reason"})


class ManifestRefused(ValueError):
    """A manifest this code will not read, or one that does not account for its source."""

    code: Final = "manifest_invalid"


def _fail(where: str, message: str) -> ManifestRefused:
    return ManifestRefused(f"{where}: {message}")


def _closed(where: str, value: object, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _fail(where, f"states exactly {sorted(keys)}")
    return value


def _hex(where: str, value: object) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise _fail(where, "is a SHA-256 digest in lowercase hex")
    return value


def _reason(where: str, value: object) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or len(value) > 300
        or any(ord(c) < 32 for c in value)
    ):
        raise _fail(where, "is one line of plain words, at most 300 characters")
    return value


@dataclass(frozen=True, slots=True)
class TranslationManifest:
    """A read manifest: its document, and its fields by path."""

    document: Mapping[str, Any]
    dispositions: Mapping[str, str]

    def paths(self, disposition: str) -> tuple[str, ...]:
        return tuple(path for path, held in self.dispositions.items() if held == disposition)


def read_manifest(raw: object) -> TranslationManifest:
    """``raw`` as a translation manifest, or :class:`ManifestRefused`."""
    document = _closed("manifest", raw, _TOP)
    if document["profile"] != MANIFEST_PROFILE:
        raise _fail("profile", f"is {MANIFEST_PROFILE}")
    translator = _closed(
        "translator", document["translator"], frozenset({"key", "version", "sha256"})
    )
    if type(translator["key"]) is not str or _KEY.fullmatch(translator["key"]) is None:
        raise _fail("translator.key", "is a lowercase key")
    if type(translator["version"]) is not int or not 1 <= translator["version"] <= 10_000:
        raise _fail("translator.version", "is a whole number from 1")
    _hex("translator.sha256", translator["sha256"])
    source = _closed("source", document["source"], frozenset({"format", "type", "sha256"}))
    for key in ("format", "type"):
        if type(source[key]) is not str or _KEY.fullmatch(source[key]) is None:
            raise _fail(f"source.{key}", "is a lowercase key")
    _hex("source.sha256", source["sha256"])
    target = _closed("target", document["target"], frozenset({"kind", "look"}))
    kind = _closed("target.kind", target["kind"], frozenset({"kind", "version", "sha256"}))
    _hex("target.kind.sha256", kind["sha256"])
    if target["look"] is not None:
        look = _closed("target.look", target["look"], frozenset({"look", "version", "sha256"}))
        _hex("target.look.sha256", look["sha256"])
    fields = document["fields"]
    if not isinstance(fields, list) or not 1 <= len(fields) <= FIELDS_MAXIMUM:
        raise _fail("fields", f"accounts for 1 to {FIELDS_MAXIMUM} fields")
    dispositions: dict[str, str] = {}
    for index, raw_field in enumerate(fields):
        at = f"fields[{index}]"
        field = _closed(at, raw_field, _FIELD)
        path = field["path"]
        if type(path) is not str or _POINTER.fullmatch(path) is None:
            raise _fail(f"{at}.path", "is a JSON pointer into the source")
        if path in dispositions:
            raise _fail(f"{at}.path", "accounts for each field once")
        disposition = field["disposition"]
        if disposition not in DISPOSITIONS:
            raise _fail(f"{at}.disposition", f"is one of {list(DISPOSITIONS)}")
        carried = disposition in ("exact", "approximated")
        to = field["to"]
        if carried != (to is not None):
            raise _fail(f"{at}.to", "names where a carried field went, and only then")
        if to is not None and (type(to) is not str or _POINTER.fullmatch(to) is None):
            raise _fail(f"{at}.to", "is a JSON pointer into the thing")
        reason = field["reason"]
        if disposition == "exact":
            if reason is not None:
                raise _fail(f"{at}.reason", "an exact field needs no reason")
        else:
            _reason(f"{at}.reason", reason)
        dispositions[path] = str(disposition)
    return TranslationManifest(
        document=MappingProxyType(dict(document)), dispositions=MappingProxyType(dispositions)
    )


def _leaves(value: Any, path: str = "") -> Iterable[str]:
    """Every field ``value`` states, as JSON pointers to its leaves; an empty object or list is a
    leaf of its own."""
    if isinstance(value, Mapping) and value:
        for key, sub in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            yield from _leaves(sub, f"{path}/{escaped}")
    elif isinstance(value, list) and value:
        for index, sub in enumerate(value):
            yield from _leaves(sub, f"{path}/{index}")
    else:
        yield path


def check_accounting(manifest: TranslationManifest, source: Mapping[str, Any]) -> None:
    """Every field ``source`` states is accounted for exactly once, at a path or under one of its
    ancestors, and no accounted path names a field the source does not state."""
    stated = set(_leaves(source))
    accounted = set(manifest.dispositions)
    for leaf in stated:
        covering = [path for path in accounted if leaf == path or leaf.startswith(path + "/")]
        if len(covering) != 1:
            raise ManifestRefused(
                f"source field {leaf} is accounted for {len(covering)} times, not once"
            )
    for path in accounted:
        if not any(leaf == path or leaf.startswith(path + "/") for leaf in stated):
            raise ManifestRefused(f"the manifest accounts for {path}, which the source lacks")
