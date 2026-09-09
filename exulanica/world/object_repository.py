"""PostgreSQL authority for alternate world versions and the objects a person authored in them.

Three properties are worth stating before the code, because each is a decision rather than an
implementation detail.

**The base is content, not a counter.** Every mutation names the ``state_sha256`` the caller last
read. The repository re-reads the row ``for update`` under the workspace lock and compares. A
counter would make two edits that produce identical state look like different bases; a digest over
the canonical delta makes them the same one, which is the behaviour ``base_topology_digest``
already has on the appearance side.

**The lock seed is the structural plane's, deliberately.** ``_WORKSPACE_LOCK_SEED`` is 880024, the
same value ``WorldStructureRepository`` and ``tg_world_structure_invalidate_on_tombstone`` take.
Minting a fresh seed here would have been tidier and wrong: it is precisely because an object edit
and a tombstone serialize on one lock that an edit cannot commit against a source snapshot that a
concurrent deletion is in the act of invalidating.

**Undo restores a document, not an intention.** Each edit stores the object's canonical document
on both sides. Undo reads ``before_document`` back and writes it, so replaying an inverse operation
is never necessary and an edit whose inverse is ambiguous cannot exist.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.store.base import ContentAddressedStore
from exulanica.world.errors import (
    InvalidatedSourceVersion,
    InvalidObjectData,
    InvalidObjectState,
    StaleObjectBase,
    UnknownWorldResource,
)
from exulanica.world.models import DEFAULT_WORLD_ID
from exulanica.world.objects import (
    AlternateVersion,
    AuthoredObject,
    ElementOverride,
    ObjectBehaviour,
    ObjectOrigin,
    Transform,
    VersionEdit,
    delta_sha256,
    object_document,
    override_document,
    validate_object,
    validate_transform,
)

__all__ = ["ReviewedAssetRow", "WorldObjectRepository"]

#: The structural plane's seed. See the module docstring: sharing it is what serializes an object
#: edit against a structural commit and against tombstone invalidation.
_WORKSPACE_LOCK_SEED: Final = 880_024


class ReviewedAssetRow:
    """One reviewed asset as the registry holds it, plus whether its bytes are actually present."""

    __slots__ = (
        "asset_key",
        "availability",
        "byte_size",
        "content_sha256",
        "licence_id",
        "licence_sha256",
        "media_type",
        "summary",
        "title",
    )

    def __init__(self, row: Mapping[str, Any], availability: str) -> None:
        self.asset_key = row["asset_key"]
        self.title = row["title"]
        self.summary = row["summary"]
        self.media_type = row["media_type"]
        self.content_sha256 = row["content_sha256"]
        self.byte_size = row["byte_size"]
        self.licence_id = row["licence_id"]
        self.licence_sha256 = row["licence_sha256"]
        self.availability = availability


class WorldObjectRepository:
    """One workspace and world's alternate versions, their objects, and the reviewed catalogs."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str = DEFAULT_WORLD_ID,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id

    # -- reviewed catalogs ------------------------------------------------------------------

    def reviewed_assets(
        self, store: ContentAddressedStore | None = None
    ) -> tuple[ReviewedAssetRow, ...]:
        """The reviewed catalog. With a store, each row also reports whether its bytes exist.

        Without a store the availability is ``unknown`` rather than an optimistic ``available``.
        Saying "present" about bytes nobody looked for is the failure the source-media contract
        exists to prevent, and it would be the same failure here.
        """
        rows = self.connection.execute(
            "select asset_key,title,summary,media_type,content_sha256,byte_size,"
            "licence_id,licence_sha256 from world_reviewed_asset order by asset_key"
        ).fetchall()
        return tuple(ReviewedAssetRow(row, self._availability(row, store)) for row in rows)

    def reviewed_asset(
        self, asset_key: str, store: ContentAddressedStore | None = None
    ) -> ReviewedAssetRow:
        row = self.connection.execute(
            "select asset_key,title,summary,media_type,content_sha256,byte_size,"
            "licence_id,licence_sha256 from world_reviewed_asset where asset_key=%s",
            (asset_key,),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such reviewed asset")
        return ReviewedAssetRow(row, self._availability(row, store))

    @staticmethod
    def _availability(row: Mapping[str, Any], store: ContentAddressedStore | None) -> str:
        if store is None:
            return "unknown"
        from exulanica.evidence.blob import BlobId

        return (
            "available"
            if store.exists(BlobId.from_hex(row["content_sha256"]))
            else "unavailable_asset"
        )

    def behaviour_registry(self) -> dict[tuple[str, int], Mapping[str, Any]]:
        rows = self.connection.execute(
            "select behaviour_key,behaviour_version,parameters from world_object_behaviour_registry"
        ).fetchall()
        return {(r["behaviour_key"], r["behaviour_version"]): r["parameters"] for r in rows}

    # -- versions ---------------------------------------------------------------------------

    def create_version(
        self,
        *,
        source_snapshot_id: uuid.UUID | None = None,
        parent_version_id: uuid.UUID | None = None,
        title: str,
        style_version_id: uuid.UUID | None = None,
        created_by: uuid.UUID,
    ) -> AlternateVersion:
        """Branch a new alternate version from a source snapshot or from another version.

        Branching from a version copies its delta, so the two are independent from that point on.
        This is the operation the structural plane cannot express: it has one linear revision
        chain behind one current pointer, and two alternates of one place cannot both exist there.
        """
        if not title or not title.strip():
            raise InvalidObjectData("title is required")
        if (source_snapshot_id is None) == (parent_version_id is None):
            raise InvalidObjectData("name exactly one of source_snapshot_id or parent_version_id")
        with self.connection.transaction():
            self._lock_workspace()
            if parent_version_id is not None:
                parent = self._version_row(parent_version_id)
                source_snapshot_id = parent["source_snapshot_id"]
                objects = self._objects(parent_version_id)
                overrides = self._overrides(parent_version_id)
            else:
                objects, overrides = (), ()
            self._require_snapshot(source_snapshot_id)
            version_id = uuid.uuid4()
            state = delta_sha256(objects, overrides)
            self.connection.execute(
                "insert into world_alternate_version (version_id,workspace_id,world_id,"
                "source_snapshot_id,parent_version_id,title,origin,style_version_id,"
                "state_sha256,edit_seq,created_by) "
                "values (%s,%s,%s,%s,%s,%s,'authored',%s,%s,0,%s)",
                (
                    version_id,
                    self.workspace_id,
                    self.world_id,
                    source_snapshot_id,
                    parent_version_id,
                    title.strip(),
                    style_version_id,
                    state,
                    created_by,
                ),
            )
            # Copied rows carry the parent's edit ids. They record which edit authored the
            # document, which stays true across a branch; the branch itself is the version row.
            for obj in objects:
                self._insert_object(version_id, obj, self._object_edit_ids(parent_version_id, obj))
            for override in overrides:
                self._insert_override(
                    version_id, override, self._override_edit_id(parent_version_id, override)
                )
        return self.version(version_id)

    def versions(self) -> tuple[AlternateVersion, ...]:
        rows = self.connection.execute(
            "select version_id from world_alternate_version "
            "where workspace_id=%s and world_id=%s order by created_at desc, version_id desc",
            (self.workspace_id, self.world_id),
        ).fetchall()
        return tuple(self.version(row["version_id"]) for row in rows)

    def version(self, version_id: uuid.UUID) -> AlternateVersion:
        row = self._version_row(version_id)
        return AlternateVersion(
            version_id=row["version_id"],
            world_id=row["world_id"],
            source_snapshot_id=row["source_snapshot_id"],
            parent_version_id=row["parent_version_id"],
            title=row["title"],
            style_version_id=row["style_version_id"],
            state_sha256=row["state_sha256"],
            edit_seq=row["edit_seq"],
            source_invalidated=self._source_invalidated(row["source_snapshot_id"]),
            created_by=row["created_by"],
            created_at=row["created_at"].isoformat(),
            objects=self._objects(version_id),
            element_overrides=self._overrides(version_id),
            edits=self._edits(version_id),
        )

    # -- object edits -----------------------------------------------------------------------

    def add_object(
        self,
        version_id: uuid.UUID,
        obj: AuthoredObject,
        *,
        base_state_sha256: str,
        actor: uuid.UUID,
    ) -> AlternateVersion:
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            checked = validate_object(
                obj,
                region_ids=self._source_region_ids(row["source_snapshot_id"]),
                asset_keys=frozenset(a.asset_key for a in self.reviewed_assets()),
                registry=self.behaviour_registry(),
            )
            existing = {o.object_id for o in self._objects(version_id)}
            if checked.object_id in existing:
                raise InvalidObjectState(f"{checked.object_id} already exists in this version")
            edit_id = uuid.uuid4()
            self._insert_object(version_id, checked, (edit_id, edit_id))
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="add_object",
                object_id=checked.object_id,
                before=None,
                after=object_document(checked),
                actor=actor,
            )
        return self.version(version_id)

    def move_object(
        self,
        version_id: uuid.UUID,
        object_id: str,
        transform: Transform,
        *,
        base_state_sha256: str,
        actor: uuid.UUID,
    ) -> AlternateVersion:
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            current = self._require_object(version_id, object_id)
            if current.removed:
                raise InvalidObjectState(f"{object_id} is removed in this version")
            checked = validate_transform(transform)
            edit_id = uuid.uuid4()
            self.connection.execute(
                "update world_alternate_object set x_mm=%s,y_mm=%s,z_mm=%s,"
                "yaw_microradians=%s,scale_milli=%s,last_edit_id=%s "
                "where workspace_id=%s and world_id=%s and version_id=%s and object_id=%s",
                (
                    checked.x_mm,
                    checked.y_mm,
                    checked.z_mm,
                    checked.yaw_microradians,
                    checked.scale_milli,
                    edit_id,
                    self.workspace_id,
                    self.world_id,
                    version_id,
                    object_id,
                ),
            )
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="move_object",
                object_id=object_id,
                before=object_document(current),
                after=object_document(self._require_object(version_id, object_id)),
                actor=actor,
            )
        return self.version(version_id)

    def remove_object(
        self,
        version_id: uuid.UUID,
        object_id: str,
        *,
        base_state_sha256: str,
        actor: uuid.UUID,
    ) -> AlternateVersion:
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            current = self._require_object(version_id, object_id)
            if current.removed:
                raise InvalidObjectState(f"{object_id} is already removed in this version")
            edit_id = uuid.uuid4()
            self.connection.execute(
                "update world_alternate_object set removed=true,last_edit_id=%s "
                "where workspace_id=%s and world_id=%s and version_id=%s and object_id=%s",
                (edit_id, self.workspace_id, self.world_id, version_id, object_id),
            )
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="remove_object",
                object_id=object_id,
                before=object_document(current),
                after=object_document(self._require_object(version_id, object_id)),
                actor=actor,
            )
        return self.version(version_id)

    def undo(
        self, version_id: uuid.UUID, *, base_state_sha256: str, actor: uuid.UUID
    ) -> AlternateVersion:
        """Reverse the newest edit by restoring the document it recorded on its own way in."""
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            newest = self.connection.execute(
                "select edit_id,kind,object_id,before_document from world_alternate_version_edit "
                "where workspace_id=%s and world_id=%s and version_id=%s "
                "order by edit_seq desc limit 1",
                (self.workspace_id, self.world_id, version_id),
            ).fetchone()
            if newest is None:
                raise InvalidObjectState("this version has no edit to undo")
            if newest["kind"] == "undo":
                # Undo of an undo would be a redo, and a stack whose one control means two things
                # is a stack nobody can reason about. Refused rather than guessed.
                raise InvalidObjectState("the newest edit is already an undo")
            if newest["kind"] not in {"add_object", "move_object", "remove_object"}:
                raise InvalidObjectState("only object edits can be undone")
            edit_id = uuid.uuid4()
            object_id = newest["object_id"]
            before = newest["before_document"]
            current = self._require_object(version_id, object_id)
            if before is None:
                self.connection.execute(
                    "delete from world_alternate_object where workspace_id=%s and world_id=%s "
                    "and version_id=%s and object_id=%s",
                    (self.workspace_id, self.world_id, version_id, object_id),
                )
                after = None
            else:
                self._restore_object(version_id, before, edit_id)
                after = object_document(self._require_object(version_id, object_id))
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="undo",
                object_id=None,
                before=object_document(current),
                after=after,
                actor=actor,
                undone_edit_id=newest["edit_id"],
            )
        return self.version(version_id)

    # -- element overrides ------------------------------------------------------------------

    def set_element_override(
        self,
        version_id: uuid.UUID,
        override: ElementOverride,
        *,
        base_state_sha256: str,
        actor: uuid.UUID,
    ) -> AlternateVersion:
        """Suppress or move an element of the source snapshot.

        No public route reaches this. Hiding or moving a structural element changes what a person
        can reach, which is a protected-value review rather than an object edit, and the composer
        owns it until that review exists. It is here, stored and digested, because the World state
        contract requires an alternate version to store removals and transforms of its source.
        """
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            if override.element_id not in self._source_element_ids(row["source_snapshot_id"]):
                raise InvalidObjectData(
                    f"{override.element_id} is not an element of the source snapshot"
                )
            if not override.suppressed and override.transform is None:
                raise InvalidObjectData("an override must suppress or move")
            if override.transform is not None:
                validate_transform(override.transform)
            edit_id = uuid.uuid4()
            existing = {o.element_id: o for o in self._overrides(version_id)}
            before = existing.get(override.element_id)
            self.connection.execute(
                "delete from world_alternate_element_override where workspace_id=%s "
                "and world_id=%s and version_id=%s and element_id=%s",
                (self.workspace_id, self.world_id, version_id, override.element_id),
            )
            self._insert_override(version_id, override, edit_id)
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="suppress_element" if override.suppressed else "transform_element",
                object_id=None,
                element_id=override.element_id,
                before=None if before is None else override_document(before),
                after=override_document(override),
                actor=actor,
            )
        return self.version(version_id)

    # -- edit plumbing ----------------------------------------------------------------------

    def _begin_edit(self, version_id: uuid.UUID, base_state_sha256: str) -> Mapping[str, Any]:
        """Lock, re-read, and refuse a stale or invalidated base. Every mutation starts here."""
        self._lock_workspace()
        row = self._version_row(version_id, for_update=True)
        if self._source_invalidated(row["source_snapshot_id"]):
            raise InvalidatedSourceVersion(
                "a committed deletion invalidated this version's source snapshot"
            )
        if row["state_sha256"] != base_state_sha256:
            raise StaleObjectBase(
                "this version moved since the base was read; read it again and re-issue the edit"
            )
        return row

    def _append_edit(
        self,
        row: Mapping[str, Any],
        *,
        edit_id: uuid.UUID,
        kind: str,
        object_id: str | None,
        before: Mapping[str, Any] | None,
        after: Mapping[str, Any] | None,
        actor: uuid.UUID,
        element_id: str | None = None,
        undone_edit_id: uuid.UUID | None = None,
    ) -> None:
        version_id = row["version_id"]
        result = delta_sha256(self._objects(version_id), self._overrides(version_id))
        self.connection.execute(
            "insert into world_alternate_version_edit (edit_id,workspace_id,world_id,version_id,"
            "edit_seq,kind,object_id,element_id,undone_edit_id,base_state_sha256,"
            "result_state_sha256,before_document,after_document,actor) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                edit_id,
                self.workspace_id,
                self.world_id,
                version_id,
                int(row["edit_seq"]) + 1,
                kind,
                object_id,
                element_id,
                undone_edit_id,
                row["state_sha256"],
                result,
                None if before is None else Jsonb(dict(before)),
                None if after is None else Jsonb(dict(after)),
                actor,
            ),
        )
        self.connection.execute(
            "update world_alternate_version set state_sha256=%s,edit_seq=%s "
            "where workspace_id=%s and world_id=%s and version_id=%s",
            (
                result,
                int(row["edit_seq"]) + 1,
                self.workspace_id,
                self.world_id,
                version_id,
            ),
        )

    def _insert_object(
        self, version_id: uuid.UUID, obj: AuthoredObject, edit_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        created_edit_id, last_edit_id = edit_ids
        behaviour = obj.behaviour
        self.connection.execute(
            "insert into world_alternate_object (workspace_id,world_id,version_id,object_id,"
            "asset_key,region_id,x_mm,y_mm,z_mm,yaw_microradians,scale_milli,origin_kind,"
            "origin_role,behaviour_key,behaviour_version,behaviour_parameters,removed,"
            "created_edit_id,last_edit_id) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                self.world_id,
                version_id,
                obj.object_id,
                obj.asset_key,
                obj.region_id,
                obj.transform.x_mm,
                obj.transform.y_mm,
                obj.transform.z_mm,
                obj.transform.yaw_microradians,
                obj.transform.scale_milli,
                obj.origin.kind,
                obj.origin.role,
                None if behaviour is None else behaviour.behaviour_key,
                None if behaviour is None else behaviour.behaviour_version,
                None if behaviour is None else Jsonb(dict(behaviour.parameters)),
                obj.removed,
                created_edit_id,
                last_edit_id,
            ),
        )

    def _restore_object(
        self, version_id: uuid.UUID, document: Mapping[str, Any], edit_id: uuid.UUID
    ) -> None:
        """Write a stored document back, creating the row again if undo had deleted it."""
        obj = _object_from_document(document)
        created = self.connection.execute(
            "select created_edit_id from world_alternate_object where workspace_id=%s "
            "and world_id=%s and version_id=%s and object_id=%s",
            (self.workspace_id, self.world_id, version_id, obj.object_id),
        ).fetchone()
        if created is None:
            self._insert_object(version_id, obj, (edit_id, edit_id))
            return
        behaviour = obj.behaviour
        self.connection.execute(
            "update world_alternate_object set asset_key=%s,region_id=%s,x_mm=%s,y_mm=%s,"
            "z_mm=%s,yaw_microradians=%s,scale_milli=%s,origin_role=%s,behaviour_key=%s,"
            "behaviour_version=%s,behaviour_parameters=%s,removed=%s,last_edit_id=%s "
            "where workspace_id=%s and world_id=%s and version_id=%s and object_id=%s",
            (
                obj.asset_key,
                obj.region_id,
                obj.transform.x_mm,
                obj.transform.y_mm,
                obj.transform.z_mm,
                obj.transform.yaw_microradians,
                obj.transform.scale_milli,
                obj.origin.role,
                None if behaviour is None else behaviour.behaviour_key,
                None if behaviour is None else behaviour.behaviour_version,
                None if behaviour is None else Jsonb(dict(behaviour.parameters)),
                obj.removed,
                edit_id,
                self.workspace_id,
                self.world_id,
                version_id,
                obj.object_id,
            ),
        )

    def _insert_override(
        self, version_id: uuid.UUID, override: ElementOverride, edit_id: uuid.UUID
    ) -> None:
        transform = override.transform
        self.connection.execute(
            "insert into world_alternate_element_override (workspace_id,world_id,version_id,"
            "element_id,suppressed,x_mm,y_mm,z_mm,yaw_microradians,scale_milli,last_edit_id) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                self.world_id,
                version_id,
                override.element_id,
                override.suppressed,
                None if transform is None else transform.x_mm,
                None if transform is None else transform.y_mm,
                None if transform is None else transform.z_mm,
                None if transform is None else transform.yaw_microradians,
                None if transform is None else transform.scale_milli,
                edit_id,
            ),
        )

    # -- reads ------------------------------------------------------------------------------

    def _version_row(self, version_id: uuid.UUID, *, for_update: bool = False) -> Mapping[str, Any]:
        row = self.connection.execute(
            "select version_id,world_id,source_snapshot_id,parent_version_id,title,"
            "style_version_id,state_sha256,edit_seq,created_by,created_at "
            "from world_alternate_version where workspace_id=%s and world_id=%s and version_id=%s"
            + (" for update" if for_update else ""),
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()
        if row is None:
            # Absent and cross-workspace are the same answer. Row-level security already makes
            # another workspace's row invisible; saying "forbidden" here would put the difference
            # back in the response body.
            raise UnknownWorldResource("no such alternate version")
        return row

    def _objects(self, version_id: uuid.UUID) -> tuple[AuthoredObject, ...]:
        rows = self.connection.execute(
            "select object_id,asset_key,region_id,x_mm,y_mm,z_mm,yaw_microradians,scale_milli,"
            "origin_kind,origin_role,behaviour_key,behaviour_version,behaviour_parameters,removed "
            "from world_alternate_object where workspace_id=%s and world_id=%s and version_id=%s "
            "order by object_id",
            (self.workspace_id, self.world_id, version_id),
        ).fetchall()
        return tuple(
            AuthoredObject(
                object_id=r["object_id"],
                asset_key=r["asset_key"],
                region_id=r["region_id"],
                transform=Transform(
                    r["x_mm"],
                    r["y_mm"],
                    r["z_mm"],
                    r["yaw_microradians"],
                    r["scale_milli"],
                ),
                origin=ObjectOrigin(r["origin_kind"], r["origin_role"]),
                behaviour=(
                    None
                    if r["behaviour_key"] is None
                    else ObjectBehaviour(
                        r["behaviour_key"], r["behaviour_version"], r["behaviour_parameters"]
                    )
                ),
                removed=r["removed"],
            )
            for r in rows
        )

    def _overrides(self, version_id: uuid.UUID) -> tuple[ElementOverride, ...]:
        rows = self.connection.execute(
            "select element_id,suppressed,x_mm,y_mm,z_mm,yaw_microradians,scale_milli "
            "from world_alternate_element_override "
            "where workspace_id=%s and world_id=%s and version_id=%s order by element_id",
            (self.workspace_id, self.world_id, version_id),
        ).fetchall()
        return tuple(
            ElementOverride(
                element_id=r["element_id"],
                suppressed=r["suppressed"],
                transform=(
                    None
                    if r["x_mm"] is None
                    else Transform(
                        r["x_mm"],
                        r["y_mm"],
                        r["z_mm"],
                        r["yaw_microradians"],
                        r["scale_milli"],
                    )
                ),
            )
            for r in rows
        )

    def _edits(self, version_id: uuid.UUID) -> tuple[VersionEdit, ...]:
        rows = self.connection.execute(
            "select edit_id,edit_seq,kind,object_id,element_id,undone_edit_id,base_state_sha256,"
            "result_state_sha256,actor,recorded_at from world_alternate_version_edit "
            "where workspace_id=%s and world_id=%s and version_id=%s order by edit_seq",
            (self.workspace_id, self.world_id, version_id),
        ).fetchall()
        return tuple(
            VersionEdit(
                edit_id=r["edit_id"],
                edit_seq=r["edit_seq"],
                kind=r["kind"],
                object_id=r["object_id"],
                element_id=r["element_id"],
                undone_edit_id=r["undone_edit_id"],
                base_state_sha256=r["base_state_sha256"],
                result_state_sha256=r["result_state_sha256"],
                actor=r["actor"],
                recorded_at=r["recorded_at"].isoformat(),
            )
            for r in rows
        )

    def _require_object(self, version_id: uuid.UUID, object_id: str) -> AuthoredObject:
        for obj in self._objects(version_id):
            if obj.object_id == object_id:
                return obj
        raise UnknownWorldResource("no such authored object")

    def _object_edit_ids(
        self, version_id: uuid.UUID, obj: AuthoredObject
    ) -> tuple[uuid.UUID, uuid.UUID]:
        row = self.connection.execute(
            "select created_edit_id,last_edit_id from world_alternate_object "
            "where workspace_id=%s and world_id=%s and version_id=%s and object_id=%s",
            (self.workspace_id, self.world_id, version_id, obj.object_id),
        ).fetchone()
        return (row["created_edit_id"], row["last_edit_id"])

    def _override_edit_id(self, version_id: uuid.UUID, override: ElementOverride) -> uuid.UUID:
        row = self.connection.execute(
            "select last_edit_id from world_alternate_element_override "
            "where workspace_id=%s and world_id=%s and version_id=%s and element_id=%s",
            (self.workspace_id, self.world_id, version_id, override.element_id),
        ).fetchone()
        return row["last_edit_id"]

    # -- the source snapshot ----------------------------------------------------------------

    def _require_snapshot(self, snapshot_id: uuid.UUID | None) -> Mapping[str, Any]:
        row = self.connection.execute(
            "select snapshot_id,topology from world_structure_snapshot "
            "where workspace_id=%s and world_id=%s and snapshot_id=%s",
            (self.workspace_id, self.world_id, snapshot_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such structural snapshot")
        if self._source_invalidated(snapshot_id):
            raise InvalidatedSourceVersion(
                "a committed deletion invalidated this structural snapshot"
            )
        return row

    def _source_invalidated(self, snapshot_id: uuid.UUID) -> bool:
        """Reuse the structural plane's invalidation rows rather than keeping a second record.

        Nothing here writes an invalidation. ``tg_world_structure_invalidate_on_tombstone`` writes
        them when a tombstone covers a snapshot's dependencies, so deleting the source scene
        invalidates every version derived from it with no code on this side at all.
        """
        row = self.connection.execute(
            "select 1 from world_structure_invalidation "
            "where workspace_id=%s and world_id=%s and snapshot_id=%s limit 1",
            (self.workspace_id, self.world_id, snapshot_id),
        ).fetchone()
        return row is not None

    def _source_region_ids(self, snapshot_id: uuid.UUID) -> frozenset[str]:
        rows = self.connection.execute(
            "select region_id from world_structure_snapshot_region "
            "where workspace_id=%s and world_id=%s and snapshot_id=%s",
            (self.workspace_id, self.world_id, snapshot_id),
        ).fetchall()
        return frozenset(row["region_id"] for row in rows)

    def _source_element_ids(self, snapshot_id: uuid.UUID) -> frozenset[str]:
        rows = self.connection.execute(
            "select element_id from world_structure_snapshot_element "
            "where workspace_id=%s and world_id=%s and snapshot_id=%s",
            (self.workspace_id, self.world_id, snapshot_id),
        ).fetchall()
        return frozenset(row["element_id"] for row in rows)

    def _lock_workspace(self) -> None:
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s::text,%s))",
            (self.workspace_id, _WORKSPACE_LOCK_SEED),
        )


def _object_from_document(document: Mapping[str, Any]) -> AuthoredObject:
    transform = document["transform"]
    behaviour = document["behaviour"]
    return AuthoredObject(
        object_id=document["object_id"],
        asset_key=document["asset_key"],
        region_id=document["region_id"],
        transform=Transform(
            transform["x_mm"],
            transform["y_mm"],
            transform["z_mm"],
            transform["yaw_microradians"],
            transform["scale_milli"],
        ),
        origin=ObjectOrigin(document["origin"]["kind"], document["origin"]["role"]),
        behaviour=(
            None
            if behaviour is None
            else ObjectBehaviour(
                behaviour["behaviour_key"],
                behaviour["behaviour_version"],
                behaviour["parameters"],
            )
        ),
        removed=document["removed"],
    )
