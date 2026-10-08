"""The translation manifest of one crossing: what came across from a game, and what stayed behind.

Every crossing writes a manifest (``exulanica.translation-manifest/v2``,
:mod:`exulanica.things.manifests`), built here from the bridge's mapping file alone, so a thing's
card shows each game's own words and the product holds none. Its source is what the arrival
involves of the game fields the adapter declared at hello: the visitor's own type, each game item
it carries, every action, and every field that never crosses. Each is accounted for once:

*   the visitor's type: ``exact`` or ``approximated`` as the mapping says, to the thing's kind;
*   a carried item: as the mapping says, to the carried thing it became;
*   an action: as the mapping says, to the ability it becomes;
*   a field that never crosses: ``dropped``, with the mapping's reason.

Each field carries the mapping's ``words``, and every field that is not exact its
``reason_words`` as the manifest's ``reason``. The translator is the mapping (its key, version and
digest); the source names the game's type as a lowercase key and the digest of what the bridge
sent. The manifest is checked by THINGS's own reader and its accounting before it is used, so a
manifest the card cannot read is never written.

Pure: no connection.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.things.manifests import MANIFEST_PROFILE, check_accounting, read_manifest

__all__ = ["arrival_manifest", "manifest_key"]

_NOT_KEY: Final = re.compile(r"[^a-z0-9_-]+")


def manifest_key(text: str) -> str:
    """``text`` as the manifest's lowercase key: letters folded, every other run of characters a
    hyphen, starting with a letter, at most 48 characters."""
    key = _NOT_KEY.sub("-", text.lower()).strip("-")
    if not key or not key[0].isalpha():
        key = f"t-{key}"
    return key[:48].rstrip("-") or "t"


def _pointer(name: str) -> str:
    return "/" + name.replace("~", "~0").replace("/", "~1")


def _field(
    path: str, disposition: str, to: str | None, reason: str | None, words: str
) -> dict[str, Any]:
    return {"path": path, "disposition": disposition, "to": to, "reason": reason, "words": words}


def arrival_manifest(
    *,
    mapping: Mapping[str, Any],
    mapping_sha256: str,
    reads: Sequence[str],
    visitor: Mapping[str, Any],
    kind: Mapping[str, Any],
    carried: Sequence[Mapping[str, Any]],
    sent: Mapping[str, Any],
) -> dict[str, Any]:
    """The manifest of one arrival of ``visitor`` carrying ``carried``, as ``mapping`` translates
    it, accounting for each game field the adapter read that the arrival involves."""
    read = set(reads)
    items = {entry["game_item"]: entry for entry in mapping["items"]}
    fields: list[dict[str, Any]] = []
    if visitor["game_type"] in read:
        fields.append(
            _field(
                _pointer(visitor["game_type"]),
                visitor["outcome"],
                "/kind",
                visitor.get("reason_words"),
                visitor["words"],
            )
        )
    first_unit = 0
    for entry in carried:
        item = items[entry["game_item"]]
        if entry["game_item"] in read and all(
            field["path"] != _pointer(entry["game_item"]) for field in fields
        ):
            fields.append(
                _field(
                    _pointer(entry["game_item"]),
                    item["outcome"],
                    f"/carried/{first_unit}",
                    item.get("reason_words"),
                    item["words"],
                )
            )
        first_unit += int(entry["count"])
    for action in mapping["actions"]:
        if action["game_action"] in read:
            fields.append(
                _field(
                    _pointer(action["game_action"]),
                    action["outcome"],
                    _pointer("abilities") + _pointer(action["ability"]),
                    action.get("reason_words"),
                    action["words"],
                )
            )
    for entry in mapping["never_crosses"]:
        if entry["field"] in read:
            fields.append(
                _field(
                    _pointer(entry["field"]), "dropped", None, entry["reason_words"], entry["words"]
                )
            )
    manifest = {
        "profile": MANIFEST_PROFILE,
        "translator": {
            "key": manifest_key(mapping["key"]),
            "version": mapping["version"],
            "sha256": mapping_sha256,
        },
        "source": {
            "format": manifest_key(mapping["key"]),
            "type": manifest_key(visitor["game_type"]),
            "sha256": sha256_of_canonical(dict(sent)).hex(),
        },
        "target": {"kind": dict(kind), "look": None},
        "fields": fields,
    }
    checked = read_manifest(manifest)
    check_accounting(checked, {field["path"][1:]: None for field in fields})
    return manifest
