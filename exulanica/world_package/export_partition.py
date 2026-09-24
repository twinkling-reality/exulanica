"""Which alternate versions each requested extension exports, withholds, or cannot hold.

**The rule is an allowlist.** A version is written into an extension only when it and every
version it was branched from fit that extension's format
(:mod:`exulanica.world_package.extension_formats`): every kind in their edit chains is one the
format admits, and every delta section their state holds or their chains change is one it
carries. Which subject a kind changes comes from the edit-kind registry
(:mod:`exulanica.world.edit_kinds`) and which section a subject writes from the authored delta
(:data:`exulanica.world.authored_delta.DELTA_SECTIONS`), so nothing here names a kind. A kind
registered later is in no format, so every version whose lineage carries it is withheld with the
kind named, until an extension version admits it. A kind the registry does not hold at all is
refused by name: nothing can say whether a format admits it.

**Why the lineage and not the version alone.** A branch copies its parent's state and not its
parent's chain, and a parent pointer must resolve in the directory that holds the branch. So a
version fits a format only when its whole lineage does, and every version branched from a withheld
one is withheld with it. A deletion that invalidates a source invalidates every version on it,
which is the same lineage, since a branch shares its parent's source.

**Where a version goes.** Extension families nest: every section an authored-world version may
hold, an environment-instances version may hold too. A version goes to the smallest family whose
sections include every section its lineage needs, and is judged by that family's requested format,
or, when the family is not requested, by that family's format of the same version as what was
requested. A kept version in the environment family brings the versions it was branched from into
that directory as well, so the directory is lineage-closed; those ancestors stay where they belong
too. A kept version only a family that was not requested can hold is reported, and the projector
refuses rather than write a directory that looks complete without it.

**Where a withheld version is counted.** In the requested format of the family its own state and
chain need or, when that family was not requested, in the nearest smaller family that was, so a
receiver of an authored-world directory alone is told about every version it does not get. That is
how the 1.0 formats have always counted.

Pure: reads no database. The projector supplies what it read.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from exulanica.world.authored_delta import DELTA_SECTIONS, DeltaSection
from exulanica.world.edit_kinds import EDIT_KINDS, UNDO, EditKind, EditSubject
from exulanica.world_package.extension_formats import (
    REASON_KIND_NOT_ADMITTED,
    REASON_SECTION_NOT_CARRIED,
    REASON_SOURCE_INVALIDATED,
    ExtensionFormat,
    counterpart,
    families,
)
from exulanica.world_package.package import PackageError

__all__ = [
    "REASON_KIND_NOT_ADMITTED",
    "REASON_SECTION_NOT_CARRIED",
    "REASON_SOURCE_INVALIDATED",
    "ExportPlan",
    "PlaneVersion",
    "WithheldVersion",
    "judging_formats",
    "plan_export",
]


@dataclass(frozen=True, slots=True)
class PlaneVersion:
    """One live alternate version, as much of it as decides where it may be exported."""

    version_id: object
    parent_version_id: object | None
    source_invalidated: bool
    #: Every kind its own edit chain holds.
    chain_kinds: frozenset[str] = frozenset()
    #: Every subject its own chain names in the log's subject columns. An undo repeats the columns
    #: of the edit it reverses, so it is counted with that edit's subject.
    chain_subjects: frozenset[EditSubject] = frozenset()
    #: The delta sections its current state holds anything in.
    state_sections: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class WithheldVersion:
    """A version no requested extension writes, and why, in the words a package may count."""

    version_id: object
    reason: str
    #: The kinds or sections the reason is about, sorted; empty for an invalidated source.
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExportPlan:
    """What each requested extension writes and counts, and what only another one could hold."""

    #: The versions each requested format writes, by its key, in the order they were supplied.
    exported: Mapping[str, tuple[object, ...]]
    #: The withheld versions each requested format counts, by its key.
    withheld: Mapping[str, tuple[WithheldVersion, ...]]
    #: Kept versions that only a family nobody requested can hold, by that family's judging
    #: format's key.
    unrequested: Mapping[str, tuple[object, ...]]


def judging_formats(requested: Sequence[ExtensionFormat]) -> dict[str, ExtensionFormat]:
    """The format each family's versions are judged by: the requested one, or its counterpart.

    A family that was not requested is judged by its format of the version that was requested, so
    authored-world 1.0 alone treats an environment-bearing version exactly as
    environment-instances 1.0 would, and never as a later format would. When the requested formats
    differ in version, the newest decides. Two versions of one extension in one package would
    write the same versions twice under two rules, so that request is refused.
    """
    chosen: dict[str, ExtensionFormat] = {}
    for format_ in requested:
        if chosen.get(format_.family, format_) != format_:
            raise PackageError(
                f"request one version of each extension, not {chosen[format_.family].key} and "
                f"{format_.key}"
            )
        chosen[format_.family] = format_
    newest = max((format_.version for format_ in requested), key=_version_order)
    for family, _ in families():
        chosen.setdefault(family, counterpart(family, newest))
    return chosen


def plan_export(
    versions: Sequence[PlaneVersion],
    requested: Sequence[ExtensionFormat],
    *,
    registry: Iterable[EditKind] | None = None,
    sections: Iterable[DeltaSection] | None = None,
) -> ExportPlan:
    """Decide, for each requested format, what it writes and counts. See the module docstring.

    ``requested`` holds at most one format of each family. ``registry`` and ``sections`` default
    to the edit-kind registry and the delta sections, read when called; a test passes a copy of
    the registry with a kind added and watches it withheld by name.
    """
    if not requested:
        return ExportPlan(exported={}, withheld={}, unrequested={})
    registry = EDIT_KINDS if registry is None else registry
    sections = DELTA_SECTIONS if sections is None else sections
    judges = judging_formats(requested)
    requested_keys = {format_.family: format_.key for format_ in requested}
    subject_of = {kind.name: kind.subject for kind in registry}
    section_of = {section.subject: section.key for section in sections}
    nested = families()
    order = [family for family, _ in nested]
    carried = nested[-1][1]
    by_id = {version.version_id: version for version in versions}

    def needs(version: PlaneVersion) -> frozenset[str]:
        """The sections this version's own state holds or its own chain changes."""
        subjects = set(version.chain_subjects)
        for kind in version.chain_kinds:
            if kind == UNDO:
                continue
            if kind not in subject_of:
                raise PackageError(
                    f"the edit kind {kind!r} is not registered, so no extension can say whether "
                    "it admits it"
                )
            subjects.add(subject_of[kind])
        return version.state_sections | {section_of[subject] for subject in subjects}

    def lineage(version: PlaneVersion) -> list[PlaneVersion]:
        found = [version]
        seen = {version.version_id}
        parent = version.parent_version_id
        while parent is not None and parent not in seen and parent in by_id:
            seen.add(parent)
            found.append(by_id[parent])
            parent = by_id[parent].parent_version_id
        return found

    def family_of(needed: frozenset[str]) -> str:
        """The smallest family carrying every section needed that any family carries.

        One always exists: the families nest, so the largest carries every carried section.
        """
        wanted = needed & carried
        return next(family for family, held in nested if wanted <= held)

    own_family: dict[object, str] = {}
    routed: dict[object, str] = {}
    withheld: list[tuple[WithheldVersion, str]] = []
    kept: list[PlaneVersion] = []
    for version in versions:
        line = lineage(version)
        needed = frozenset().union(*(needs(each) for each in line))
        kinds = frozenset().union(*(each.chain_kinds for each in line))
        family = family_of(needed)
        judge = judges[family]
        own_family[version.version_id] = family_of(needs(version))
        if version.source_invalidated:
            reason = WithheldVersion(version.version_id, REASON_SOURCE_INVALIDATED, ())
        elif not_admitted := kinds - judge.admitted_kinds:
            reason = WithheldVersion(
                version.version_id, REASON_KIND_NOT_ADMITTED, tuple(sorted(not_admitted))
            )
        elif not_carried := needed - judge.sections:
            reason = WithheldVersion(
                version.version_id, REASON_SECTION_NOT_CARRIED, tuple(sorted(not_carried))
            )
        else:
            routed[version.version_id] = family
            kept.append(version)
            continue
        withheld.append((reason, own_family[version.version_id]))

    included: dict[str, set[object]] = {family: set() for family in order}
    for version in kept:
        family = routed[version.version_id]
        included[family].add(version.version_id)
        if family != order[0]:
            # A parent pointer must resolve in the directory that holds the branch.
            included[family].update(
                each.version_id for each in lineage(version)[1:] if each.version_id in routed
            )
    exported = {
        requested_keys[family]: tuple(
            version.version_id for version in kept if version.version_id in included[family]
        )
        for family in order
        if family in requested_keys
    }
    unrequested = {
        judges[family].key: tuple(
            version.version_id
            for version in kept
            if routed[version.version_id] == family and version.version_id in included[family]
        )
        for family in order
        if family not in requested_keys and _smaller_requested(family, order, requested_keys)
    }
    counted: dict[str, list[WithheldVersion]] = {key: [] for key in requested_keys.values()}
    for reason, family in withheld:
        counter = _counting_family(family, order, requested_keys)
        if counter is not None:
            counted[requested_keys[counter]].append(reason)
    return ExportPlan(
        exported=exported,
        withheld={key: tuple(values) for key, values in counted.items()},
        unrequested={key: ids for key, ids in unrequested.items() if ids},
    )


def _version_order(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _smaller_requested(family: str, order: list[str], requested: Mapping[str, str]) -> bool:
    return any(other in requested for other in order[: order.index(family)])


def _counting_family(family: str, order: list[str], requested: Mapping[str, str]) -> str | None:
    """The family that counts a withheld version: its own if requested, else the nearest below."""
    for candidate in reversed(order[: order.index(family) + 1]):
        if candidate in requested:
            return candidate
    return None
