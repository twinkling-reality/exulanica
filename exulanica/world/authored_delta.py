"""An alternate version's authored delta: every kind's section, composed into one digest.

This module sits above every instance kind. :mod:`exulanica.world.objects` holds the object and
element-override documents, :mod:`exulanica.world.environment_instances` and
:mod:`exulanica.world.photo_point_maps` hold their own, and only this module knows all of them.
The composition used to live in ``objects`` and reach up into the two instance modules from inside
a function, so a new kind could be added below without the composer being told: the digest took
each later section as an optional argument defaulting to empty, and a caller that passed fewer
sections produced a token for a world that did not exist. The import-linter contract "An authored
delta composes the instance kinds, and no instance kind composes the delta" keeps the direction.

**Every section is a required keyword.** ``canonical_delta_document`` and ``delta_sha256`` take
one keyword-only argument per section and give none a default, so a caller that forgets a section
fails at the call rather than digesting less than the version holds, and adding a kind adds a
required argument every caller has to answer. A caller holding the whole version uses
:func:`version_delta_sha256`, which reads every section from it.

**The document is unchanged.** Sections are sorted by their subject id; the two version 1 sections
are always written; each later section is written only when it holds something and then selects
its schema version (2 for environment instances, 3 for point maps). That last rule is load-bearing:
the digest is every stored version's compare-and-swap token, so a section that appeared empty
would move the token of every world that has none and refuse the next edit on all of them.
``tests/test_authored_delta.py`` holds golden digests for every schema version.

Pure: no connection and no SQL, so an independent verifier can rebuild the digest.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from operator import attrgetter
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.world.edit_kinds import EditSubject
from exulanica.world.environment_instances import (
    EnvironmentInstance,
    environment_instance_document,
)
from exulanica.world.objects import (
    AuthoredObject,
    ElementOverride,
    VersionEdit,
    object_document,
    override_document,
)
from exulanica.world.photo_point_maps import PointMapInstance, point_map_instance_document

__all__ = [
    "DELTA_SECTIONS",
    "AlternateVersion",
    "DeltaSection",
    "canonical_delta_document",
    "delta_sha256",
    "version_delta_sha256",
]


@dataclass(frozen=True, slots=True)
class AlternateVersion:
    """One alternate version as read: its identity, lineage and token, and every delta section."""

    version_id: uuid.UUID
    world_id: str
    source_snapshot_id: uuid.UUID
    parent_version_id: uuid.UUID | None
    title: str
    style_version_id: uuid.UUID | None
    state_sha256: str
    edit_seq: int
    source_invalidated: bool
    created_by: uuid.UUID
    created_at: str
    objects: tuple[AuthoredObject, ...] = ()
    element_overrides: tuple[ElementOverride, ...] = ()
    environment_instances: tuple[EnvironmentInstance, ...] = ()
    point_map_instances: tuple[PointMapInstance, ...] = ()
    edits: tuple[VersionEdit, ...] = ()


@dataclass(frozen=True, slots=True)
class DeltaSection:
    """One kind's section of the delta: its key, its subject, its document and its order."""

    #: The document key, the keyword argument and the :class:`AlternateVersion` field.
    key: str
    subject: EditSubject
    document: Callable[[Any], dict[str, Any]]
    sort_key: Callable[[Any], str]
    #: The schema version this section's presence selects, or None for a version 1 section, which
    #: is always written.
    schema_version: int | None


#: Every section, one per edit subject. ``tests/test_authored_delta.py`` requires one for every
#: subject the edit-kind registry names and one for every section field of AlternateVersion.
DELTA_SECTIONS: Final[tuple[DeltaSection, ...]] = (
    DeltaSection("objects", EditSubject.OBJECT, object_document, attrgetter("object_id"), None),
    DeltaSection(
        "element_overrides",
        EditSubject.ELEMENT,
        override_document,
        attrgetter("element_id"),
        None,
    ),
    DeltaSection(
        "environment_instances",
        EditSubject.ENVIRONMENT_INSTANCE,
        environment_instance_document,
        attrgetter("instance_id"),
        2,
    ),
    DeltaSection(
        "point_map_instances",
        EditSubject.POINT_MAP_INSTANCE,
        point_map_instance_document,
        attrgetter("instance_id"),
        3,
    ),
)


def canonical_delta_document(
    *,
    objects: Sequence[AuthoredObject],
    element_overrides: Sequence[ElementOverride],
    environment_instances: Sequence[EnvironmentInstance],
    point_map_instances: Sequence[PointMapInstance],
) -> dict[str, Any]:
    """The whole delta, in the one order its digest is defined over.

    Sorting here rather than trusting the caller is the point. The state digest is the concurrency
    token, and a token that depended on the order rows came back in would make two identical
    worlds disagree the first time a query plan changed.
    """
    return _compose(
        {
            "objects": objects,
            "element_overrides": element_overrides,
            "environment_instances": environment_instances,
            "point_map_instances": point_map_instances,
        }
    )


def delta_sha256(
    *,
    objects: Sequence[AuthoredObject],
    element_overrides: Sequence[ElementOverride],
    environment_instances: Sequence[EnvironmentInstance],
    point_map_instances: Sequence[PointMapInstance],
) -> str:
    """The state token: SHA-256 over the canonical delta, hex."""
    document = canonical_delta_document(
        objects=objects,
        element_overrides=element_overrides,
        environment_instances=environment_instances,
        point_map_instances=point_map_instances,
    )
    # Round-trips through canonical_json first so a value the digest could not represent raises
    # here, where the message names this plane, rather than inside the hashing helper.
    canonical_json(document)
    return sha256_of_canonical(document).hex()


def version_delta_sha256(version: AlternateVersion) -> str:
    """The token for everything the version holds, every section read from the version itself."""
    sections = {section.key: getattr(version, section.key) for section in DELTA_SECTIONS}
    return delta_sha256(**sections)


def _compose(sections: Mapping[str, Sequence[Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {"schema_version": 1}
    for section in DELTA_SECTIONS:
        values = sections[section.key]
        if section.schema_version is not None:
            if not values:
                continue
            document["schema_version"] = max(document["schema_version"], section.schema_version)
        document[section.key] = [
            section.document(value) for value in sorted(values, key=section.sort_key)
        ]
    return document
