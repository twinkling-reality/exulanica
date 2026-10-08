"""A bridge's mapping file: how one game's things become things here, and what never crosses.

A mapping file is data, one per game and content set, kept with its adapter outside the product and
pinned by digest in the deployment's bridge directory. Two profiles are read side by side, the same
but for how a visitor's look is named: ``exulanica.bridge-mapping/v1`` names it by its digest
(``sha256:<digest>``), which the door resolves against the thing library when a visitor arrives, and
``exulanica.bridge-mapping/v2`` by the library's own reference, its key, version and digest. A
pinned mapping of either profile stays valid. It states:

``visitors``
    Each kind of game character that may cross, the thing kind it arrives as here, the words it is
    known by, and the looks it may arrive in, each a look the thing library ships, with its
    licence. A look is chosen by a key the adapter reports; no picture crosses at run time. None
    for a program that brings no visitor and only decides for a world's own things, such as an
    agent.
``items``
    Each game item that may be carried across, the thing kind it becomes, which ways it travels,
    and whether the correspondence is exact or approximated. At most one item of each kind travels
    out, so a thing leaving this world always becomes one known game item.
``actions``
    Which of the game's actions become which abilities here.
``never_crosses``
    Every game field the adapter reads that has no counterpart here, each with the reason it stays
    behind. A player's name is always among them.

Every entry that names a game field also says, in plain words a person reads on a thing's card,
what it is and what it becomes (``words``), and every entry that is not exact says why
(``reason_words``): a crossing's translation manifest copies them field by field, so the card shows
each game's own reasons and the product holds no game's text. Words meet the door's one rule for
text a person reads (:func:`exulanica.door.protocol.words_fault`).

:func:`check_mapping` is the deterministic check every mapping meets before a bridge may use it: the
closed schema, unique keys, bounded sizes and words, whole numbers only, and :func:`check_reads`,
which refuses an adapter that reads a game field its mapping neither maps nor lists as staying
behind, so a crossing's manifest cannot leave out a loss by forgetting it. Whether each named kind
exists, and whether each item's kind can be held, is checked against the kind library by the caller
that has one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.door.protocol import (
    MAPPING_PROFILE_V2,
    MAPPING_PROFILES,
    READS_MAXIMUM,
    WORDS_CHARACTERS_MAXIMUM,
    words_fault,
)

__all__ = [
    "MAPPING_BYTES_MAXIMUM",
    "MappingRefused",
    "check_mapping",
    "check_plain",
    "check_reads",
    "mapped_fields",
]

#: The largest mapping document, in canonical JSON bytes.
MAPPING_BYTES_MAXIMUM: Final = 49152
_KEY: Final = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_KIND_KEY: Final = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_GAME_NAME: Final = re.compile(r"^[A-Za-z0-9_:.-]{1,80}$")
_ABILITY: Final = re.compile(r"^[a-z][a-z0-9 _.-]{0,63}$")
#: A game field or action as an adapter names it: a game's own identifiers may carry capitals and
#: colons, so one grammar serves every game.
_READ: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _:.-]{0,79}$")
_DIGEST_REFERENCE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
#: A shipped look's key, as the thing library names it.
_LOOK_KEY: Final = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
_SPDX: Final = re.compile(r"^[A-Za-z0-9.+-]{1,64}$")
_OUTCOMES: Final = frozenset({"exact", "approximated"})
_WAYS: Final = frozenset({"in", "out", "both"})
#: A field every mapping lists as staying behind, whatever the game: no person's name crosses.
_ALWAYS_BEHIND: Final = "player name"
#: How deep a mapping document nests, which bounds the walk that refuses fractional numbers.
_DEPTH_MAXIMUM: Final = 8


class MappingRefused(ValueError):
    """A mapping file does not meet its profile; the message says where."""

    code: Final = "mapping_refused"


def _require(condition: bool, where: str) -> None:
    if not condition:
        raise MappingRefused(where)


def _words(value: Any, where: str) -> str:
    fault = words_fault(value, maximum=WORDS_CHARACTERS_MAXIMUM)
    _require(fault is None, f"{where}: {fault}")
    return value


def _object(value: Any, fields: Iterable[str], where: str, *, optional: Iterable[str] = ()) -> dict:
    required = frozenset(fields)
    allowed = required | frozenset(optional)
    _require(
        isinstance(value, dict) and required <= set(value) <= allowed,
        f"{where} states exactly {', '.join(sorted(required))}"
        + (f" (and may state {', '.join(sorted(optional))})" if optional else ""),
    )
    return value


def _plain(value: Any, depth: int = 0) -> None:
    """Refuse anything but objects, lists, strings, whole numbers and true or false, so a mapping
    has one canonical form and a fractional number is refused by name."""
    _require(depth <= _DEPTH_MAXIMUM, f"a mapping nests at most {_DEPTH_MAXIMUM} levels")
    if isinstance(value, dict):
        _require(all(isinstance(key, str) for key in value), "a mapping's keys are strings")
        for item in value.values():
            _plain(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _plain(item, depth + 1)
    else:
        _require(
            isinstance(value, (str, bool)) or type(value) is int,
            "a mapping holds strings, whole numbers and true or false, never a fractional number "
            "or null",
        )


def _kind(value: Any, where: str) -> None:
    _object(value, ("key", "version"), where)
    _require(isinstance(value["key"], str) and bool(_KIND_KEY.match(value["key"])), where)
    _require(type(value["version"]) is int and 1 <= value["version"] <= 10_000, where)


def _look(value: Any, where: str) -> None:
    """A look the thing library ships, named as it names one: its key, version and digest."""
    _object(value, ("look", "version", "sha256"), where)
    _require(isinstance(value["look"], str) and bool(_LOOK_KEY.match(value["look"])), where)
    _require(type(value["version"]) is int and 1 <= value["version"] <= 10_000, where)
    _require(isinstance(value["sha256"], str) and bool(_SHA256.match(value["sha256"])), where)


def _licence(value: Any, where: str) -> None:
    _object(value, ("spdx",), where, optional=("attribution", "share_alike", "licence_url"))
    _require(isinstance(value["spdx"], str) and bool(_SPDX.match(value["spdx"])), where)
    if "attribution" in value:
        _words(value["attribution"], f"{where} attribution")
    if "share_alike" in value:
        _require(type(value["share_alike"]) is bool, f"{where} share_alike")
    if "licence_url" in value:
        _require(
            isinstance(value["licence_url"], str)
            and value["licence_url"].startswith("https://")
            and len(value["licence_url"]) <= 200,
            f"{where} licence_url",
        )


def _outcome(entry: Mapping[str, Any], where: str) -> None:
    """An entry's outcome, exact or approximated, with reason words exactly when approximated."""
    _require(entry["outcome"] in _OUTCOMES, f"{where} outcome is exact or approximated")
    _require(
        (entry["outcome"] == "approximated") == ("reason_words" in entry),
        f"{where} states reason_words exactly when it is approximated",
    )
    _words(entry["words"], f"{where} words")
    if "reason_words" in entry:
        _words(entry["reason_words"], f"{where} reason_words")


def _unique(keys: list[str], where: str) -> None:
    _require(len(set(keys)) == len(keys), f"{where} names each once")


def check_plain(document: Any) -> None:
    """Refuse a mapping that is not one JSON object of strings, whole numbers and true or false,
    nesting a bounded number of levels: run before anything digests a presented mapping, so a
    fractional number or a deep nest is refused by name rather than failing the digest."""
    _require(isinstance(document, dict), "a mapping is one JSON object")
    _plain(document)


def check_mapping(document: Any) -> dict[str, Any]:
    """``document`` if it is a well-formed mapping file, or :class:`MappingRefused` naming where."""
    check_plain(document)
    _require(
        len(canonical_json(document)) <= MAPPING_BYTES_MAXIMUM,
        f"a mapping is at most {MAPPING_BYTES_MAXIMUM} bytes",
    )
    _object(
        document,
        ("profile", "key", "version", "game", "visitors", "items", "actions", "never_crosses"),
        "the mapping",
    )
    _require(
        document["profile"] in MAPPING_PROFILES,
        f"the mapping's profile is one of {', '.join(MAPPING_PROFILES)}",
    )
    by_reference = document["profile"] == MAPPING_PROFILE_V2
    _require(isinstance(document["key"], str) and bool(_KEY.match(document["key"])), "its key")
    _require(type(document["version"]) is int and 1 <= document["version"] <= 10_000, "version")
    game = _object(document["game"], ("label",), "its game", optional=("content",))
    _words(game["label"], "its game's label")
    if "content" in game:
        _words(game["content"], "its game's content")

    visitors = document["visitors"]
    _require(isinstance(visitors, list) and len(visitors) <= 16, "at most 16 visitors")
    for index, visitor in enumerate(visitors):
        where = f"visitor {index + 1}"
        _object(
            visitor,
            ("game_type", "kind", "label", "words", "outcome", "looks"),
            where,
            optional=("reason_words",),
        )
        _require(
            isinstance(visitor["game_type"], str) and bool(_GAME_NAME.match(visitor["game_type"])),
            f"{where} game_type",
        )
        _kind(visitor["kind"], f"{where} kind")
        _words(visitor["label"], f"{where} label")
        _outcome(visitor, where)
        looks = visitor["looks"]
        _require(isinstance(looks, list) and 1 <= len(looks) <= 8, f"{where} has 1 to 8 looks")
        for number, look in enumerate(looks):
            spot = f"{where} look {number + 1}"
            _object(
                look,
                ("look_key", "look", "licence"),
                spot,
                optional=("source_sha256", "reason_words"),
            )
            _require(
                isinstance(look["look_key"], str) and bool(_KEY.match(look["look_key"])),
                f"{spot} look_key",
            )
            if by_reference:
                _look(look["look"], f"{spot} names a shipped look by its key, version and sha256")
            else:
                _require(
                    isinstance(look["look"], str) and bool(_DIGEST_REFERENCE.match(look["look"])),
                    f"{spot} names its look by sha256:<digest>",
                )
            _licence(look["licence"], f"{spot} licence")
            if "source_sha256" in look:
                _require(
                    isinstance(look["source_sha256"], str)
                    and bool(re.fullmatch(r"[0-9a-f]{64}", look["source_sha256"])),
                    f"{spot} source_sha256",
                )
            if "reason_words" in look:
                _words(look["reason_words"], f"{spot} reason_words")
        _unique([look["look_key"] for look in looks], f"{where}'s looks")
    _unique([visitor["game_type"] for visitor in visitors], "the visitors")

    items = document["items"]
    _require(isinstance(items, list) and len(items) <= 256, "at most 256 items")
    for index, item in enumerate(items):
        where = f"item {index + 1}"
        _object(
            item,
            ("game_item", "kind", "ways", "words", "outcome"),
            where,
            optional=("reason_words",),
        )
        _require(
            isinstance(item["game_item"], str) and bool(_GAME_NAME.match(item["game_item"])),
            f"{where} game_item",
        )
        _kind(item["kind"], f"{where} kind")
        _require(item["ways"] in _WAYS, f"{where} ways is in, out or both")
        _outcome(item, where)
    _unique([item["game_item"] for item in items], "the items")
    _unique(
        [item["kind"]["key"] for item in items if item["ways"] in ("out", "both")],
        "the items travelling out, by kind,",
    )

    actions = document["actions"]
    _require(isinstance(actions, list) and 1 <= len(actions) <= 64, "1 to 64 actions")
    for index, action in enumerate(actions):
        where = f"action {index + 1}"
        _object(
            action,
            ("game_action", "ability", "words", "outcome"),
            where,
            optional=("reason_words",),
        )
        _require(
            isinstance(action["game_action"], str) and bool(_READ.match(action["game_action"])),
            f"{where} game_action",
        )
        _require(
            isinstance(action["ability"], str) and bool(_ABILITY.match(action["ability"])),
            f"{where} ability",
        )
        _outcome(action, where)
    _unique([action["game_action"] for action in actions], "the actions")

    behind = document["never_crosses"]
    _require(isinstance(behind, list) and 1 <= len(behind) <= 64, "1 to 64 fields never crossing")
    for index, entry in enumerate(behind):
        where = f"never_crosses {index + 1}"
        _object(entry, ("field", "words", "reason_words"), where)
        _require(isinstance(entry["field"], str) and bool(_READ.match(entry["field"])), where)
        _words(entry["words"], f"{where} words")
        _words(entry["reason_words"], f"{where} reason_words")
    fields = [entry["field"] for entry in behind]
    _unique(fields, "never_crosses")
    # A person's name never crosses with a visitor; a program that brings none names no person.
    _require(
        not document["visitors"] or _ALWAYS_BEHIND in fields,
        f"never_crosses lists {_ALWAYS_BEHIND!r} for a mapping with visitors",
    )
    return document


def mapped_fields(document: Mapping[str, Any]) -> frozenset[str]:
    """Every game field a checked mapping accounts for: what it maps and what stays behind."""
    return frozenset(
        [visitor["game_type"] for visitor in document["visitors"]]
        + [item["game_item"] for item in document["items"]]
        + [action["game_action"] for action in document["actions"]]
        + [entry["field"] for entry in document["never_crosses"]]
    )


def check_reads(document: Mapping[str, Any], reads: Any) -> frozenset[str]:
    """The fields an adapter declares it reads, each accounted for by its mapping, or refuse.

    A field the mapping neither maps nor lists as staying behind is a loss the manifest could not
    state, so the adapter is refused until its mapping names it.
    """
    _require(
        isinstance(reads, list)
        and 1 <= len(reads) <= READS_MAXIMUM
        and all(isinstance(field, str) and _READ.match(field) for field in reads)
        and len(set(reads)) == len(reads),
        f"an adapter declares 1 to {READS_MAXIMUM} distinct game fields it reads",
    )
    unaccounted = sorted(set(reads) - mapped_fields(document))
    _require(
        not unaccounted,
        f"the mapping does not account for: {', '.join(unaccounted)}",
    )
    return frozenset(reads)
