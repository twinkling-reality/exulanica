"""The extension half of a World Memory Package projection.

:mod:`exulanica.world_package.projector` reads the 1.0 components, signs and receipts. This module
reads the authored plane inside the same REPEATABLE READ snapshot and returns the documents of
every requested extension version: which versions each writes and counts
(:mod:`exulanica.world_package.export_partition`), and the sections each writes them in
(:mod:`exulanica.world_package.authored`, :mod:`exulanica.world_package.environments`).

One projection serves every extension version. What differs between them is data on the
:class:`~exulanica.world_package.extension_formats.ExtensionFormat`: the delta sections it carries,
the edit subjects its chains name, and the section builder of its family. A version's sections
are read through :meth:`exulanica.world.WorldObjectRepository.version`, the path every route
reads, so an environment instance's availability is the one a person sees.

**Invalidated sources are withheld, and that is the decision section 8 of
``docs/world-objects-contract.md`` left open.** A version is invalid exactly when its source
snapshot carries an invalidation row, which a tombstone over that snapshot's dependencies writes.
The projector already withdraws a scene when one of its members is deleted, because a package must
not describe structure whose subject it has dropped; an authored delta posed in the regions of a
withdrawn structure is the same kind of claim. The authored work survives in the database and in
``GET /world/versions``; the package counts what it withheld and names none of it.

**No actor is exported.** ``created_by`` and each edit's ``actor`` are omitted, as tombstones omit
the requesting actor. The digests that make the edit chain checkable are kept.

**Every stored token is checked here.** The delta is built with
:func:`exulanica.world.authored_delta.canonical_delta_document`, the one the product digests, and
the stored ``state_sha256`` must equal its digest inside this snapshot; the offline verifier then
re-derives it independently.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Final

import psycopg
from psycopg import sql

from exulanica.store.base import ContentAddressedStore
from exulanica.world.authored_delta import DELTA_SECTIONS, canonical_delta_document, delta_sha256
from exulanica.world.edit_kinds import EditSubject
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import AuthoredObject
from exulanica.world_package import authored, environments
from exulanica.world_package.export_partition import ExportPlan, PlaneVersion, plan_export
from exulanica.world_package.extension_formats import FORMATS, ExtensionFormat, families
from exulanica.world_package.package import PackageError
from exulanica.world_package.pseudonyms import optional_urn, urn

__all__ = ["project_extensions"]

#: The table each authored delta section's rows live in. The export plan needs to know which
#: sections a version's state holds, and this is the one place a projection names where they are.
#: ``tests/test_world_package_export_partition.py`` holds it to every section of the delta.
_SECTION_TABLES: Final = {
    "objects": "world_alternate_object",
    "element_overrides": "world_alternate_element_override",
    "environment_instances": "world_alternate_environment_instance",
    "point_map_instances": "world_alternate_point_map_instance",
}

#: The section builder of each extension family. A family without one stops the import, since a
#: requested format nothing writes would otherwise be skipped without a word.
_SECTION_BUILDERS: Final = {
    "authored-world": authored.build_sections,
    "environment-instances": environments.build_sections,
}
if {format_.family for format_ in FORMATS} != set(_SECTION_BUILDERS):
    raise ValueError("every extension family needs exactly one section builder")


def project_extensions(
    cursor: psycopg.Cursor,
    world_id: str,
    formats: Sequence[ExtensionFormat],
    *,
    workspace_id: uuid.UUID,
    current_snapshot_id: uuid.UUID | None,
    store: ContentAddressedStore | None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Every requested extension's documents, and the keys of the extensions actually written.

    ``store`` is used only to state environment availability honestly. A kept version that only
    a family nobody requested can hold refuses the whole projection rather than be left out of a
    directory that would look complete without it.
    """
    plan = plan_export(_plane_versions(cursor, world_id, workspace_id=workspace_id), formats)
    for key in plan.unrequested:
        raise PackageError(
            f"{formats[0].key} cannot export versions whose state includes "
            "environment instances or environment edits; request "
            f"{key} rather than omit them or emit "
            f"schema version 2 under the {formats[0].version} extension name"
        )
    worlds = WorldObjectRepository(cursor.connection, workspace_id, world_id=world_id, store=store)
    components: dict[str, Any] = {}
    written: list[str] = []
    for format_ in formats:
        if _nothing_honest_to_declare(format_, formats, plan):
            continue
        # The plan decides what each extension may name whether or not the others are requested,
        # because an edit kind outside a format's closed list would otherwise be signed into a
        # package its verifier refuses.
        components.update(
            _extension_sections(
                cursor,
                worlds,
                world_id,
                format_,
                workspace_id=workspace_id,
                current_snapshot_id=current_snapshot_id,
                version_ids=plan.exported[format_.key],
                withheld=[(each.reason, each.names) for each in plan.withheld[format_.key]],
            )
        )
        written.append(format_.key)
    return components, tuple(written)


def _plane_versions(
    cursor: psycopg.Cursor, world_id: str, *, workspace_id: uuid.UUID
) -> tuple[PlaneVersion, ...]:
    """Every alternate version of the world, with what decides where it may be exported.

    Nothing here names an edit kind. The chain is read whole, with every subject column the
    edit-kind registry defines, and the export plan decides from the registry and each format.
    This is also the one place a projection asks which source snapshots a deletion invalidated.
    """
    invalidated = {
        row["snapshot_id"]
        for row in cursor.execute(
            "select distinct snapshot_id from world_structure_invalidation "
            "where workspace_id=%s and world_id=%s",
            (workspace_id, world_id),
        ).fetchall()
    }
    kinds: dict[uuid.UUID, set[str]] = {}
    subjects: dict[uuid.UUID, set[EditSubject]] = {}
    for row in cursor.execute(
        sql.SQL(
            "select version_id,kind,{} from world_alternate_version_edit "
            "where workspace_id=%s and world_id=%s"
        ).format(sql.SQL(",").join(sql.Identifier(subject.column) for subject in EditSubject)),
        (workspace_id, world_id),
    ).fetchall():
        kinds.setdefault(row["version_id"], set()).add(row["kind"])
        subjects.setdefault(row["version_id"], set()).update(
            subject for subject in EditSubject if row[subject.column] is not None
        )
    sections: dict[uuid.UUID, set[str]] = {}
    for section in DELTA_SECTIONS:
        table = _SECTION_TABLES.get(section.key)
        if table is None:
            raise PackageError(
                f"the delta section {section.key!r} has no table this projector reads, so no "
                "version can be judged for export"
            )
        for row in cursor.execute(
            sql.SQL(
                "select distinct version_id from {} "
                "where workspace_id=%s and world_id=%s and not addition_undone"
            ).format(sql.Identifier(table)),
            (workspace_id, world_id),
        ).fetchall():
            sections.setdefault(row["version_id"], set()).add(section.key)
    return tuple(
        PlaneVersion(
            version_id=row["version_id"],
            parent_version_id=row["parent_version_id"],
            source_invalidated=row["source_snapshot_id"] in invalidated,
            chain_kinds=frozenset(kinds.get(row["version_id"], ())),
            chain_subjects=frozenset(subjects.get(row["version_id"], ())),
            state_sections=frozenset(sections.get(row["version_id"], ())),
        )
        for row in cursor.execute(
            "select version_id,source_snapshot_id,parent_version_id from world_alternate_version "
            "where workspace_id=%s and world_id=%s order by version_id",
            (workspace_id, world_id),
        ).fetchall()
    )


def _extension_sections(
    cursor: psycopg.Cursor,
    worlds: WorldObjectRepository,
    world_id: str,
    format_: ExtensionFormat,
    *,
    workspace_id: uuid.UUID,
    current_snapshot_id: uuid.UUID | None,
    version_ids: Sequence[uuid.UUID],
    withheld: Sequence[tuple[str, Sequence[str]]],
) -> dict[str, Any]:
    """One extension version's four documents, for the versions the plan gave it.

    A section the format does not carry is written empty, and the stored token check below then
    refuses a version that holds one: the plan never sends such a version, and a token is the
    last word on whether it did.
    """
    rows = cursor.execute(
        "select version_id,source_snapshot_id,parent_version_id,title,style_version_id,"
        "state_sha256,edit_seq,created_at from world_alternate_version "
        "where workspace_id=%s and world_id=%s and version_id=any(%s) order by version_id",
        (workspace_id, world_id, list(version_ids)),
    ).fetchall()
    carries_environments = "environment_instances" in format_.sections
    edits = _edit_chains(
        cursor,
        world_id,
        workspace_id=workspace_id,
        version_ids=version_ids,
        subjects=[EditSubject(subject) for subject in format_.edit_kinds],
    )
    versions: list[dict[str, Any]] = []
    every_object: list[AuthoredObject] = []
    for row in rows:
        stored = worlds.version(row["version_id"])
        sections = {
            section.key: getattr(stored, section.key) if section.key in format_.sections else ()
            for section in DELTA_SECTIONS
        }
        if delta_sha256(**sections) != row["state_sha256"]:
            if carries_environments:
                raise PackageError(
                    "an alternate version's stored state token does not describe its "
                    "environment-inclusive delta inside the export snapshot"
                )
            raise PackageError(
                "an alternate version's stored state token does not describe its delta inside "
                "the export snapshot"
            )
        every_object.extend(stored.objects)
        version: dict[str, Any] = {
            "created_at": row["created_at"],
            "delta": canonical_delta_document(**sections),
            "edit_seq": row["edit_seq"],
            "edits": edits.get(row["version_id"], []),
            "origin": "authored",
            "parent_version_id": optional_urn("alternate-version", row["parent_version_id"]),
            "source_snapshot_id": urn("structure", row["source_snapshot_id"]),
            "state_sha256": row["state_sha256"],
            "style_version_id": optional_urn("style", row["style_version_id"]),
            "title": row["title"],
            "version_id": urn("alternate-version", row["version_id"]),
        }
        if carries_environments:
            # Beside the delta and not in it: a blob disappearing must not pretend the person
            # authored a new version.
            version["environment_availability"] = [
                {"availability": instance.availability, "instance_id": instance.instance_id}
                for instance in stored.environment_instances
            ]
        versions.append(version)
    assets, behaviours = _reviewed_references(cursor, every_object)
    return _SECTION_BUILDERS[format_.family](
        format_,
        versions=versions,
        source_snapshots=_source_snapshots(
            cursor,
            world_id,
            workspace_id=workspace_id,
            current_snapshot_id=current_snapshot_id,
            sources=sorted({row["source_snapshot_id"] for row in rows}),
        ),
        assets=assets,
        behaviours=behaviours,
        withheld=withheld,
    )


def _edit_chains(
    cursor: psycopg.Cursor,
    world_id: str,
    *,
    workspace_id: uuid.UUID,
    version_ids: Sequence[uuid.UUID],
    subjects: Sequence[EditSubject],
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Each version's chain without actors, naming the subject columns the format carries."""
    columns = [subject.column for subject in subjects]
    chains: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in cursor.execute(
        sql.SQL(
            "select version_id,edit_id,edit_seq,kind,{},undone_edit_id,base_state_sha256,"
            "result_state_sha256,recorded_at from world_alternate_version_edit "
            "where workspace_id=%s and world_id=%s and version_id=any(%s) "
            "order by version_id,edit_seq"
        ).format(sql.SQL(",").join(sql.Identifier(column) for column in columns)),
        (workspace_id, world_id, list(version_ids)),
    ).fetchall():
        chains.setdefault(row["version_id"], []).append(
            {
                "base_state_sha256": row["base_state_sha256"],
                "edit_id": urn("alternate-edit", row["edit_id"]),
                "edit_seq": row["edit_seq"],
                "kind": row["kind"],
                "recorded_at": row["recorded_at"],
                "result_state_sha256": row["result_state_sha256"],
                "undone_edit_id": optional_urn("alternate-edit", row["undone_edit_id"]),
                **{column: row[column] for column in columns},
            }
        )
    return chains


def _nothing_honest_to_declare(
    format_: ExtensionFormat, requested: Sequence[ExtensionFormat], plan: ExportPlan
) -> bool:
    """Whether this directory would list no version and count none while a larger one exports.

    An empty authored-world directory beside an environment-instances directory that holds every
    kept version would look like a complete world with no alternate versions, so it is not
    written.
    """
    order = [family for family, _ in families()]
    return (
        not plan.exported[format_.key]
        and not plan.withheld[format_.key]
        and any(
            plan.exported[other.key]
            for other in requested
            if order.index(other.family) > order.index(format_.family)
        )
    )


def _source_snapshots(
    cursor: psycopg.Cursor,
    world_id: str,
    *,
    workspace_id: uuid.UUID,
    current_snapshot_id: uuid.UUID | None,
    sources: Sequence[uuid.UUID],
) -> list[dict[str, Any]]:
    """The source snapshots the versions name: identity, digest, regions and elements."""
    regions: dict[uuid.UUID, list[str]] = {}
    for row in cursor.execute(
        "select snapshot_id,region_id from world_structure_snapshot_region "
        "where workspace_id=%s and world_id=%s and snapshot_id=any(%s)",
        (workspace_id, world_id, list(sources)),
    ).fetchall():
        regions.setdefault(row["snapshot_id"], []).append(row["region_id"])
    elements: dict[uuid.UUID, list[str]] = {}
    for row in cursor.execute(
        "select snapshot_id,element_id from world_structure_snapshot_element "
        "where workspace_id=%s and world_id=%s and snapshot_id=any(%s)",
        (workspace_id, world_id, list(sources)),
    ).fetchall():
        elements.setdefault(row["snapshot_id"], []).append(row["element_id"])
    return [
        {
            "current": row["snapshot_id"] == current_snapshot_id,
            "element_ids": sorted(elements.get(row["snapshot_id"], [])),
            "region_ids": sorted(regions.get(row["snapshot_id"], [])),
            "snapshot_id": urn("structure", row["snapshot_id"]),
            "snapshot_sha256": row["snapshot_sha256"],
        }
        for row in cursor.execute(
            "select snapshot_id,snapshot_sha256 from world_structure_snapshot "
            "where workspace_id=%s and world_id=%s and snapshot_id=any(%s)",
            (workspace_id, world_id, list(sources)),
        ).fetchall()
    ]


def _reviewed_references(
    cursor: psycopg.Cursor, objects: Sequence[AuthoredObject]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The reviewed asset and behaviour descriptors these objects name, and nothing else."""
    digests = sorted({obj.asset_sha256 for obj in objects})
    assets = [
        {
            "asset_key": row["asset_key"],
            "byte_size": row["byte_size"],
            "content_sha256": row["content_sha256"],
            "licence_id": row["licence_id"],
            "licence_sha256": row["licence_sha256"],
            "media_type": row["media_type"],
            "ni_uri": authored.ni_uri(row["content_sha256"]),
            "retrieval": authored.ASSET_RETRIEVAL,
            "summary": row["summary"],
            "title": row["title"],
        }
        for row in cursor.execute(
            "select asset_key,title,summary,media_type,content_sha256,byte_size,licence_id,"
            "licence_sha256 from world_reviewed_asset where content_sha256=any(%s)",
            (digests,),
        ).fetchall()
    ]
    named = {
        (obj.behaviour.behaviour_key, obj.behaviour.behaviour_version)
        for obj in objects
        if obj.behaviour is not None
    }
    behaviours = [
        {
            "behaviour_key": row["behaviour_key"],
            "behaviour_version": row["behaviour_version"],
            "parameters": row["parameters"],
            "summary": row["summary"],
        }
        for row in cursor.execute(
            "select behaviour_key,behaviour_version,summary,parameters "
            "from world_object_behaviour_registry"
        ).fetchall()
        if (row["behaviour_key"], row["behaviour_version"]) in named
    ]
    return assets, behaviours
