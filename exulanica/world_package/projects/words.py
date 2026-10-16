"""The words a world's project says to a person: what its things are called, money, times and
the names of models.

One place for them, so the pull request, the commit messages and the history read say each thing
one way, in the workspace's own words: a run (never a session), a model by the name the
workspace gives it, dollars to four places under a cent, a character by the name its owner wrote
or else by its kind. Nothing here reads the network or a project folder.

A name a person wrote appears only where the project kept it, which is only where it keeps
readable text; such a project publishes only to a private repository
(:mod:`exulanica.world_package.projects.rights`). There a being of a made kind is called by its
kind's label, drafted from its maker's words (ruling J20); without it, a character is called by
its kind, and a being of a made kind "the creature made in this world". A town's resident is
called by the name its society gives it where the project kept it, else by its role ("the
baker"), else "the resident".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from exulanica.models.manifest import load_manifest
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.placed_things import ThingKindReference, shipped_kind

#: What a being of a kind its workspace made is called where no name is kept.
MADE_BEING: Final = "creature made in this world"
#: What a town's resident is called where neither its name nor its role is kept.
RESIDENT: Final = "resident"
#: What a part a world was made with is called where its label is not kept, by its kind: a Part
#: is made with the world, as a Thing is placed by a person (WORDS.md).
PART_NOUNS: Final = {
    "building": "building",
    "fixture": "part",
    "area": "area",
}
#: The smallest amount said in dollars and cents to four places.
SMALLEST: Final = Decimal("0.0001")
_ORDINALS: Final = (
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
)


def plural(count: int, noun: str, many: str | None = None) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {many or noun + 's'}"


def capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def money(usd: str | Decimal) -> str:
    """Dollars as the workspace writes them: "$0.05", under a cent "$0.0042", under that "less
    than $0.0001", and "$0" for nothing."""
    value = Decimal(usd)
    if value == 0:
        return "$0"
    if value < SMALLEST:
        return f"less than ${SMALLEST}"
    places = Decimal("0.01") if value >= Decimal("0.01") else SMALLEST
    return f"${value.quantize(places, rounding=ROUND_HALF_UP)}"


def seconds(milliseconds: int) -> str:
    """A time to answer in seconds: "0.09 s", "1.4 s"; under a hundredth "under 0.01 s"."""
    value = Decimal(milliseconds) / 1000
    if value < Decimal("0.01"):
        return "under 0.01 s"
    places = Decimal("0.01") if value < 1 else Decimal("0.1")
    return f"{value.quantize(places, rounding=ROUND_HALF_UP)} s"


def model_name(model_id: str) -> str:
    """The name the workspace calls a model by (`Manifest.model_name`), its identifier where this
    install's manifest does not know it."""
    return load_manifest().model_name(model_id)


def in_sentence(label: str) -> str:
    """A label as a sentence says it: its first letter lowered, unless its first word is all
    capitals (as build mode's words say it)."""
    first = label.split()[0] if label.split() else label
    return label if len(first) > 1 and first == first.upper() else label[:1].lower() + label[1:]


def _kind_noun(kind: Mapping[str, Any], label: str | None = None) -> str:
    """A thing's kind as a noun: a shipped kind's label; a made kind's own label (its maker's
    words, ruling J20) where the project keeps it, else fixed words."""
    if kind.get("source") == "workspace":
        return in_sentence(label.strip()) if label and label.strip() else MADE_BEING
    try:
        reference = ThingKindReference(kind["kind"], kind["version"], kind["sha256"])
        label = str(shipped_kind(reference).document["label"])
    except (InvalidThingPlacement, KeyError, TypeError):
        label = str(kind.get("kind", "thing")).replace("_", " ")
    return label[:1].lower() + label[1:]


def role_noun(role: str | None) -> str:
    """A resident's role as a noun, from the town's key for it ("ferry_keeper": "ferry keeper"),
    or "resident" where none is kept."""
    words = " ".join((role or "").replace("_", " ").replace("-", " ").split())
    return words.lower() if words else RESIDENT


def written_name(character: Mapping[str, Any] | None) -> str | None:
    """The name a character's owner wrote, where the project kept it."""
    words = (character or {}).get("words") or {}
    return words.get("name")


def names(worlds: Iterable[Mapping[str, Any] | None]) -> dict[str, str]:
    """What each thing and resident of these checkpoints is called, the later checkpoint's words
    first: the name its owner wrote (a resident's, the name its society gives it), else "the" and
    its kind (a made creature's kind's label where the project keeps it) or a resident's role,
    with "the second ..." where several of one kind or role are unnamed (in the order of their
    identities, which are never shown). A made kind's label is said only for a thing the newest
    checkpoint still holds: once its thing has left (its kind erased, or no longer selected), the
    label is never written again."""
    things: dict[str, Mapping[str, Any]] = {}
    characters: dict[str, Mapping[str, Any]] = {}
    residents: dict[str, Mapping[str, Any]] = {}
    newest: set[str] = set()
    for world in worlds:
        if world is None:
            continue
        things.update({thing["thing_id"]: thing for thing in world["things"]})
        characters.update({c["thing_id"]: c for c in world.get("characters") or []})
        residents.update({r["resident_id"]: r for r in world.get("residents") or []})
        newest = {thing["thing_id"] for thing in world["things"]}
    called: dict[str, str] = {}
    unnamed: dict[str, list[str]] = {}
    for thing_id in sorted(things):
        name = written_name(characters.get(thing_id))
        if name is not None:
            called[thing_id] = name
        else:
            thing = things[thing_id]
            label = thing.get("label") if thing_id in newest else None
            unnamed.setdefault(_kind_noun(thing["kind"], label), []).append(thing_id)
    for resident_id in sorted(residents):
        resident = residents[resident_id]
        if resident.get("name"):
            called[resident_id] = resident["name"]
        else:
            unnamed.setdefault(role_noun(resident.get("role")), []).append(resident_id)
    for noun, ids in unnamed.items():
        for index, thing_id in enumerate(ids):
            if index == 0:
                called[thing_id] = f"the {noun}"
            else:
                called[thing_id] = f"the {_ordinal(index + 1)} {noun}"
    return called


def part_names(worlds: Iterable[Mapping[str, Any] | None]) -> dict[str, str]:
    """What each made part of these checkpoints is called: "the" and its label where the project
    keeps it, else its kind ("the building", "the second area"); an earlier checkpoint names a
    part a later one keeps as removed."""
    parts: dict[str, Mapping[str, Any]] = {}
    for world in worlds:
        for part in (world or {}).get("parts") or []:
            known = parts.get(part["part_id"])
            parts[part["part_id"]] = part if part["kind"] is not None or known is None else known
    called: dict[str, str] = {}
    by_noun: dict[str, list[str]] = {}
    for part_id in sorted(parts):
        part = parts[part_id]
        label = part.get("label")
        noun = (
            label[:1].lower() + label[1:] if label else PART_NOUNS.get(part["kind"] or "", "part")
        )
        by_noun.setdefault(noun, []).append(part_id)
    for noun, ids in by_noun.items():
        for index, part_id in enumerate(ids):
            called[part_id] = f"the {noun}" if index == 0 else f"the {_ordinal(index + 1)} {noun}"
    return called


def _ordinal(number: int) -> str:
    if 2 <= number <= len(_ORDINALS) + 1:
        return _ORDINALS[number - 2]
    tail = "th" if 11 <= number % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{tail}"


def possessive(name: str) -> str:
    return f"{name}'s"


def listed(items: Iterable[str]) -> str:
    """ "A", "A and B", "A, B and C"."""
    values = list(items)
    if len(values) < 2:
        return "".join(values)
    return f"{', '.join(values[:-1])} and {values[-1]}"


def quoted(text: str) -> str:
    return f"\N{LEFT DOUBLE QUOTATION MARK}{text}\N{RIGHT DOUBLE QUOTATION MARK}"


def without_words(world: Mapping[str, Any]) -> dict[str, Any]:
    """A checkpoint with every word a person wrote left out (its title, its characters' names
    and personalities, its made parts' labels, its made creatures' kinds' labels, its residents'
    names), as a repository that is not private is told it."""
    kept = {key: value for key, value in world.items() if key != "title"}
    kept["things"] = [
        {key: value for key, value in thing.items() if key != "label"} for thing in world["things"]
    ]
    if world.get("characters") is not None:
        kept["characters"] = [
            {key: value for key, value in c.items() if key != "words"} for c in world["characters"]
        ]
    if world.get("parts") is not None:
        kept["parts"] = [
            {key: value for key, value in part.items() if key != "label"} for part in world["parts"]
        ]
    if world.get("residents") is not None:
        kept["residents"] = [
            {key: value for key, value in r.items() if key != "name"} for r in world["residents"]
        ]
    return kept
