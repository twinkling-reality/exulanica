"""Each version of each World Memory Package extension, as data.

An extension version is a frozen contract: the delta sections a version written under it may
hold, and the edit kinds its edit chains may hold, named by the subject each kind changes. The
verifier of a version refuses anything outside those lists, and the projector writes a version
into an extension only when the version and every version it was branched from fit them
(:mod:`exulanica.world_package.export_partition`). A kind the edit-kind registry gains later is in
no list here, so it is withheld by name until a new extension version admits it.

**Why the admitted kinds are written here and not read from the registry.** A verifier must not
open a database, and importing :mod:`exulanica.world.edit_kinds` runs the ``exulanica.world``
package, which loads the database layer (measured: ``exulanica.db`` and ``psycopg`` are imported
after it and not before). A format is also not allowed to move when the registry does: a package
signed under a version stays verifiable after the product gains kinds. So each version's lists
are stated once, here, and ``tests/test_edit_kinds.py`` holds every name to a registered kind of
the subject it is filed under.

Pure: imports nothing that opens a database.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

__all__ = [
    "AUTHORED_WORLD_1_0",
    "AUTHORED_WORLD_1_1",
    "ENVIRONMENT_INSTANCES_1_0",
    "ENVIRONMENT_INSTANCES_1_1",
    "FORMATS",
    "REASON_KIND_NOT_ADMITTED",
    "REASON_SECTION_NOT_CARRIED",
    "REASON_SOURCE_INVALIDATED",
    "UNDO",
    "WITHHELD_REASONS",
    "WITHHELD_RULE",
    "ExtensionFormat",
    "counterpart",
    "families",
    "format_for_key",
]

#: The kind that reverses another edit. Every version admits it, because it changes only the
#: subject of an edit the same chain already holds. It is the registry's
#: ``exulanica.world.edit_kinds.UNDO``, restated because this module cannot import the registry,
#: and ``tests/test_edit_kinds.py`` holds the two equal.
UNDO: Final = "undo"

_PROFILE_BASE: Final = "https://exulanica.local/profiles/world-memory-package/extensions"

#: Why a version is not in a package, in the words a format whose ``withheld`` section counts by
#: reason uses. A package counts versions by these and names none of the versions.
REASON_SOURCE_INVALIDATED: Final = "source_invalidated"
REASON_KIND_NOT_ADMITTED: Final = "edit_kind_not_admitted"
REASON_SECTION_NOT_CARRIED: Final = "section_not_carried"
WITHHELD_REASONS: Final = frozenset(
    {REASON_SOURCE_INVALIDATED, REASON_KIND_NOT_ADMITTED, REASON_SECTION_NOT_CARRIED}
)
#: The sentence a by-reason ``withheld`` section carries, so a person reading the file alone
#: learns what the counts mean.
WITHHELD_RULE: Final = (
    "counted and not named: a version is withheld when a committed deletion invalidated its "
    "source snapshot, when it or a version it was branched from carries an edit kind this "
    "extension version does not admit, or holds a delta section it does not carry; names are "
    "those kinds or sections"
)


@dataclass(frozen=True, slots=True)
class ExtensionFormat:
    """One version of one extension: its names and what a version written under it may hold."""

    #: The family the directory and the command line are named after, such as ``authored-world``.
    family: str
    version: str
    #: The name ``extension.json`` carries.
    name: str
    #: The authored delta sections a version may hold, by their key in the delta document.
    sections: frozenset[str]
    #: The edit kinds a chain may hold, by the subject each changes, named as the registry names
    #: subjects. ``undo`` is admitted besides these.
    edit_kinds: Mapping[str, frozenset[str]]
    #: The profile each section document declares, by section: ``versions``, ``assets``,
    #: ``behaviours``.
    section_profiles: Mapping[str, str]
    #: Whether ``withheld`` counts versions by reason. The 1.0 formats hold one total under a
    #: deletion's reason whatever withheld them; that shape is frozen with them.
    withheld_by_reason: bool
    #: The crate's description of this extension's profile node.
    crate_description: str

    @property
    def key(self) -> str:
        """The command-line name and the directory name under ``extensions/``."""
        return f"{self.family}-{self.version}"

    @property
    def directory(self) -> str:
        return f"extensions/{self.key}"

    @property
    def profile_id(self) -> str:
        return f"{_PROFILE_BASE}/{self.family}/{self.version}"

    @property
    def declaration_path(self) -> str:
        """``extension.json``, which names the extension, its version and what a loader needs."""
        return f"{self.directory}/extension.json"

    def section_path(self, section: str) -> str:
        """The file holding one section: ``versions``, ``assets`` or ``behaviours``."""
        return f"{self.directory}/{section}.json"

    @property
    def paths(self) -> frozenset[str]:
        """Exactly the files the directory holds; any other file there is refused."""
        return frozenset(
            {self.declaration_path, *(self.section_path(name) for name in self.section_profiles)}
        )

    @property
    def capability(self) -> str:
        """The capability a loader declares to say it reads this version."""
        return f"wmp-extension:{self.name}@{self.version}"

    @property
    def crate_name(self) -> str:
        return f"Exulanica WMP {self.family} extension {self.version}"

    @property
    def admitted_kinds(self) -> frozenset[str]:
        return frozenset().union(*self.edit_kinds.values()) | {UNDO}

    def kinds_changing(self, subject: str) -> frozenset[str]:
        """The admitted kinds that change this subject, or none for a subject it does not carry."""
        return self.edit_kinds.get(subject, frozenset())


_OBJECT_EDITS_1_0: Final = frozenset({"add_object", "move_object", "remove_object"})
#: What 1.1 adds: the edit that gives a placed object a behaviour, changes it or takes it away. The
#: object's behaviour and its parameters were already part of every object in the delta.
_OBJECT_EDITS_1_1: Final = _OBJECT_EDITS_1_0 | {"set_object_behaviour"}
_ELEMENT_EDITS: Final = frozenset({"suppress_element", "transform_element"})
_ENVIRONMENT_EDITS: Final = frozenset({"add_environment", "move_environment", "remove_environment"})
_AUTHORED_SECTIONS: Final = frozenset({"objects", "element_overrides"})
_ENVIRONMENT_SECTIONS: Final = _AUTHORED_SECTIONS | {"environment_instances"}
_EXTENSION_OF_1_0: Final = "An optional, separately versioned extension to World Memory Package 1.0"


def _profiles(name: str, versions: int) -> dict[str, str]:
    """Section profiles: the versions document at ``versions``, the others unchanged since 1.0."""
    return {
        "assets": f"{name}-assets-v1",
        "behaviours": f"{name}-behaviours-v1",
        "versions": f"{name}-versions-v{versions}",
    }


AUTHORED_WORLD_1_0: Final = ExtensionFormat(
    family="authored-world",
    version="1.0",
    name="exulanica-wmp-ext-authored-world",
    sections=_AUTHORED_SECTIONS,
    edit_kinds={"object": _OBJECT_EDITS_1_0, "element": _ELEMENT_EDITS},
    section_profiles=_profiles("exulanica-wmp-ext-authored-world", 1),
    withheld_by_reason=False,
    crate_description=(
        f"{_EXTENSION_OF_1_0} carrying alternate versions, authored objects and behaviour "
        "references."
    ),
)

ENVIRONMENT_INSTANCES_1_0: Final = ExtensionFormat(
    family="environment-instances",
    version="1.0",
    name="exulanica-wmp-ext-environment-instances",
    sections=_ENVIRONMENT_SECTIONS,
    edit_kinds={
        "object": _OBJECT_EDITS_1_0,
        "element": _ELEMENT_EDITS,
        "environment_instance": _ENVIRONMENT_EDITS,
    },
    section_profiles=_profiles("exulanica-wmp-ext-environment-instances", 1),
    withheld_by_reason=False,
    crate_description=(
        f"{_EXTENSION_OF_1_0} carrying environment-inclusive authored state and environment "
        "instance availability."
    ),
)

AUTHORED_WORLD_1_1: Final = ExtensionFormat(
    family="authored-world",
    version="1.1",
    name="exulanica-wmp-ext-authored-world",
    sections=_AUTHORED_SECTIONS,
    edit_kinds={"object": _OBJECT_EDITS_1_1, "element": _ELEMENT_EDITS},
    section_profiles=_profiles("exulanica-wmp-ext-authored-world", 2),
    withheld_by_reason=True,
    crate_description=(
        f"{_EXTENSION_OF_1_0} carrying alternate versions, authored objects, behaviour references "
        "and the edits that give a placed object a behaviour, change it or take it away."
    ),
)

ENVIRONMENT_INSTANCES_1_1: Final = ExtensionFormat(
    family="environment-instances",
    version="1.1",
    name="exulanica-wmp-ext-environment-instances",
    sections=_ENVIRONMENT_SECTIONS,
    edit_kinds={
        "object": _OBJECT_EDITS_1_1,
        "element": _ELEMENT_EDITS,
        "environment_instance": _ENVIRONMENT_EDITS,
    },
    section_profiles=_profiles("exulanica-wmp-ext-environment-instances", 2),
    withheld_by_reason=True,
    crate_description=(
        f"{_EXTENSION_OF_1_0} carrying environment-inclusive authored state, environment "
        "instance availability and the edits that give a placed object a behaviour, change it "
        "or take it away."
    ),
)

#: Every extension version this code writes and verifies, the smaller family first.
FORMATS: Final[tuple[ExtensionFormat, ...]] = (
    AUTHORED_WORLD_1_0,
    AUTHORED_WORLD_1_1,
    ENVIRONMENT_INSTANCES_1_0,
    ENVIRONMENT_INSTANCES_1_1,
)


def families(
    formats: tuple[ExtensionFormat, ...] = FORMATS,
) -> tuple[tuple[str, frozenset[str]], ...]:
    """Each family with the sections its versions carry, smallest first."""
    held: dict[str, frozenset[str]] = {}
    for format_ in formats:
        held.setdefault(format_.family, format_.sections)
    return tuple(sorted(held.items(), key=lambda item: (len(item[1]), item[0])))


def _checked(formats: tuple[ExtensionFormat, ...]) -> dict[tuple[str, str], ExtensionFormat]:
    """The formats by family and version, after the rules the export partition relies on.

    Keys are unique; every version of a family carries the same sections; the families nest, so
    each carries every section of the one below it; and every family defines the same versions, so
    a family that was not requested can always be judged by its format of the requested version.
    Broken data stops the import rather than a projection halfway through.
    """
    by_key = {format_.key for format_ in formats}
    if len(by_key) != len(formats):
        raise ValueError("two extension formats share a key")
    ordered = families(formats)
    for format_ in formats:
        if format_.sections != dict(ordered)[format_.family]:
            raise ValueError(f"{format_.key} carries other sections than its family")
    for (_, lower), (family, upper) in itertools.pairwise(ordered):
        if not lower < upper:
            raise ValueError(f"{family} does not carry every section of the family below it")
    versions = {
        family: frozenset(f.version for f in formats if f.family == family) for family, _ in ordered
    }
    if len(set(versions.values())) != 1:
        raise ValueError(f"extension families define different versions: {versions}")
    return {(format_.family, format_.version): format_ for format_ in formats}


_BY_FAMILY_AND_VERSION: Final = _checked(FORMATS)
_BY_KEY: Final = {format_.key: format_ for format_ in FORMATS}


def format_for_key(key: str) -> ExtensionFormat | None:
    """The extension version a command-line name selects, or None for a name nobody defined."""
    return _BY_KEY.get(key)


def counterpart(family: str, version: str) -> ExtensionFormat:
    """This family's format of that version, which every family defines."""
    return _BY_FAMILY_AND_VERSION[(family, version)]
