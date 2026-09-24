"""PostgreSQL authority for alternate world versions and the objects a person authored in them.

Three properties are worth stating before the code, because each is a decision rather than an
implementation detail.

**The base is content, not a counter.** Every mutation names the ``state_sha256`` the caller last
read. The repository re-reads the row ``for update`` under the workspace lock and compares. A
counter would make two edits that produce identical state look like different bases; a digest over
the canonical delta makes them the same one, which is the behaviour ``base_topology_digest``
already has on the appearance side.

**The lock is the structural plane's, deliberately.** Every edit takes
:func:`exulanica.world.workspace_lock.lock_workspace`, the lock ``WorldStructureRepository`` and
``tg_world_structure_invalidate_on_tombstone`` take. Minting a fresh seed here would have been
tidier and wrong: it is precisely because an object edit and a tombstone serialize on one lock that
an edit cannot commit against a source snapshot that a concurrent deletion is in the act of
invalidating.

**Other planes' sources are asked, not decided, here.** Whether an environment source or a
photograph's depth estimate may be used is the environment source authority's and the point map
source authority's question. This repository asks both inside its own transaction and writes
only its own plane.

**Undo restores a document, not an intention.** Each edit stores the object's canonical document
on both sides. Undo reads ``before_document`` back and writes it, so replaying an inverse operation
is never necessary and an edit whose inverse is ambiguous cannot exist.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, ClassVar, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.world.authored_delta import AlternateVersion, delta_sha256
from exulanica.world.edit_kinds import EditSubject, edit_kind
from exulanica.world.environment_instances import (
    EnvironmentInstance,
    EnvironmentPlacement,
    EnvironmentSelection,
    EnvironmentSourceBinding,
    SourceAnchor,
    environment_instance_document,
    validate_environment_instance,
)
from exulanica.world.environment_source_authority import (
    EnvironmentSourceAuthority,
    ResolvedEnvironmentSource,
)
from exulanica.world.errors import (
    InvalidatedSourceVersion,
    InvalidEnvironmentData,
    InvalidEnvironmentState,
    InvalidObjectData,
    InvalidObjectState,
    InvalidPointMapPlacement,
    StaleObjectBase,
    UnavailableAsset,
    UnknownWorldResource,
)
from exulanica.world.objects import (
    AuthoredObject,
    ElementOverride,
    ObjectBehaviour,
    ObjectOrigin,
    Transform,
    VersionEdit,
    object_document,
    override_document,
    validate_behaviour,
    validate_object,
    validate_transform,
)
from exulanica.world.photo_point_maps import (
    PointMapInstance,
    PointMapModel,
    PointMapPlacement,
    PointMapSourceBinding,
    point_map_instance_document,
    validate_point_map_instance,
)
from exulanica.world.point_map_source_authority import PointMapSourceAuthority
from exulanica.world.reviewed_catalog import ReviewedAssetRow, ReviewedCatalog
from exulanica.world.society_engines import INPUT_ENGINES
from exulanica.world.workspace_lock import lock_workspace

__all__ = ["ResolvedEnvironmentSource", "ReviewedAssetRow", "WorldObjectRepository"]

#: Every subject id column of the edit log, in the order the table declares them.
_SUBJECT_COLUMNS: Final = ",".join(subject.column for subject in EditSubject)


class WorldObjectRepository:
    """One workspace and world's alternate versions, their objects, and the reviewed catalogs."""

    #: Undo's rule for each subject the edit-kind registry names, as the method that restores it.
    #: ``tests/test_edit_kinds.py`` requires one for every subject; a kind the registry does not
    #: name never reaches this table, because ``edit_kind`` refuses it first.
    _UNDO_RULES: ClassVar[Mapping[EditSubject, str]] = MappingProxyType(
        {
            EditSubject.OBJECT: "_undo_object",
            EditSubject.ELEMENT: "_undo_override",
            EditSubject.ENVIRONMENT_INSTANCE: "_undo_environment",
            EditSubject.POINT_MAP_INSTANCE: "_undo_point_map",
        }
    )

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str,
        store: ContentAddressedStore | None = None,
        on_edit: Callable[[uuid.UUID], None] | None = None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id
        self.store = store
        self.on_edit = on_edit

    # -- reviewed catalogs ------------------------------------------------------------------

    def reviewed_assets(
        self, store: ContentAddressedStore | None = None
    ) -> tuple[ReviewedAssetRow, ...]:
        """The reviewed catalog, which is the same for every world; see :class:`ReviewedCatalog`."""
        return ReviewedCatalog(self.connection).assets(store)

    def placeable_assets(
        self, store: ContentAddressedStore | None = None
    ) -> tuple[ReviewedAssetRow, ...]:
        """The reviewed assets a person may place as objects; see :class:`ReviewedCatalog`."""
        return ReviewedCatalog(self.connection).placeable_assets(store)

    def reviewed_asset(
        self, asset_key: str, store: ContentAddressedStore | None = None
    ) -> ReviewedAssetRow:
        return ReviewedCatalog(self.connection).asset(asset_key, store)

    def behaviour_registry(self) -> dict[tuple[str, int], Mapping[str, Any]]:
        return ReviewedCatalog(self.connection).behaviours()

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
                environments = self._environment_instances(parent_version_id)
                # ONLY THE ONES THAT CAN STILL BE DRAWN. A branch is a new version and its rows
                # are new placements, so copying an estimate whose depth right has ended would
                # write a fresh placement of a reading the person has already stopped. The
                # insert trigger would refuse it and take the whole branch with it; leaving it
                # behind lets the branch succeed and states the loss.
                point_maps = tuple(
                    instance
                    for instance in self._point_map_instances(parent_version_id)
                    if instance.availability == "available"
                )
            else:
                objects, overrides, environments, point_maps = (), (), (), ()
            self._require_snapshot(source_snapshot_id)
            self._require_style_version(style_version_id)
            version_id = uuid.uuid4()
            state = delta_sha256(
                objects=objects,
                element_overrides=overrides,
                environment_instances=environments,
                point_map_instances=point_maps,
            )
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
                self._write_override(
                    version_id, override, self._override_edit_id(parent_version_id, override)
                )
            for instance in environments:
                self._require_pinned_environment_current(instance, require_bytes=True)
                self._insert_environment(
                    version_id,
                    instance,
                    self._environment_edit_ids(parent_version_id, instance.instance_id),
                )
            for placed in point_maps:
                self._insert_point_map(
                    version_id,
                    placed,
                    self._point_map_edit_ids(parent_version_id, placed.instance_id),
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
        """One version, with the returned token guaranteed to describe the returned delta.

        The digest is recomputed from the object and override rows this call actually read,
        rather than copied from the version row. Under READ COMMITTED each statement takes its
        own snapshot, so a concurrent writer between two of the reads below would otherwise let a
        body carry a ``state_sha256`` digested over a delta that is not the one beside it, and a
        renderer holding that body would be looking at a token for something it cannot see.

        Recomputing does not weaken the compare-and-swap. The stored digest remains the sole
        authority at edit time, and a caller whose read raced a writer simply presents a token
        that no longer matches and is told to read again, which is the behaviour a stale base has
        anyway.
        """
        objects = self._objects(version_id)
        overrides = self._overrides(version_id)
        environments = self._environment_instances(version_id)
        point_maps = self._point_map_instances(version_id)
        row = self._version_row(version_id)
        return AlternateVersion(
            version_id=row["version_id"],
            world_id=row["world_id"],
            source_snapshot_id=row["source_snapshot_id"],
            parent_version_id=row["parent_version_id"],
            title=row["title"],
            style_version_id=row["style_version_id"],
            state_sha256=delta_sha256(
                objects=objects,
                element_overrides=overrides,
                environment_instances=environments,
                point_map_instances=point_maps,
            ),
            edit_seq=row["edit_seq"],
            source_invalidated=self._source_invalidated(row["source_snapshot_id"]),
            created_by=row["created_by"],
            created_at=row["created_at"].isoformat(),
            objects=objects,
            element_overrides=overrides,
            environment_instances=environments,
            point_map_instances=point_maps,
            edits=self._edits(version_id),
        )

    # -- environment edits ------------------------------------------------------------------

    def add_environment(
        self,
        version_id: uuid.UUID,
        placement: EnvironmentPlacement,
        *,
        base_state_sha256: str,
        actor: uuid.UUID,
    ) -> AlternateVersion:
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            instance = self._validated_environment_placement(row, placement)
            edit_id = uuid.uuid4()
            self._insert_environment(version_id, instance, (edit_id, edit_id))
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="add_environment",
                environment_instance_id=instance.instance_id,
                before=None,
                after=environment_instance_document(instance),
                actor=actor,
            )
            self._final_environment_authorization(instance)
        return self.version(version_id)

    def edit_base_row(self, version_id: uuid.UUID) -> Mapping[str, Any]:
        """The stored version row an edit compares against, read without a lock.

        ``state_sha256`` here is the stored compare-and-swap token, not the digest ``version``
        recomputes. Absent, cross-workspace and other-world ids raise the same
        ``UnknownWorldResource``.
        """
        return self._version_row(version_id)

    def require_edit_base(self, row: Mapping[str, Any], base_state_sha256: str) -> None:
        """The base check every mutation runs under its lock: invalidated source, then stale."""
        self._require_edit_base(row, base_state_sha256)

    def validate_environment_placement(
        self,
        version_id: uuid.UUID,
        placement: EnvironmentPlacement,
        *,
        base_state_sha256: str,
        resolved_source: ResolvedEnvironmentSource | None = None,
    ) -> EnvironmentInstance:
        """Validate exactly what add would validate, without taking a lock or writing.

        Apply repeats this validation under its write transaction and final authorization lock.
        This read-only pass exists so a proposal that could not currently be applied is never shown
        as valid. It is safe for the executor connection: every operation below is a SELECT or a
        content-addressed store read. ``resolved_source``, from ``validate_environment_source`` in
        the same read, stands in for resolving the placement's source again; it must name the
        placement's exact binding.
        """
        row = self._version_row(version_id)
        self._require_edit_base(row, base_state_sha256)
        return self._validated_environment_placement(row, placement, resolved_source)

    def move_environment(
        self,
        version_id: uuid.UUID,
        instance_id: str,
        transform: Transform,
        *,
        base_state_sha256: str,
        actor: uuid.UUID,
    ) -> AlternateVersion:
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            current = self._require_environment(version_id, instance_id)
            if current.removed:
                raise InvalidEnvironmentState(f"{instance_id} is removed in this version")
            try:
                validate_transform(transform)
            except InvalidObjectData as exc:
                raise InvalidEnvironmentData(str(exc)) from exc
            self._require_pinned_environment_current(current, require_bytes=True)
            edit_id = uuid.uuid4()
            self.connection.execute(
                "update world_alternate_environment_instance "
                "set x_mm=%s,y_mm=%s,z_mm=%s,yaw_microradians=%s,scale_milli=%s,last_edit_id=%s "
                "where workspace_id=%s and world_id=%s and version_id=%s and instance_id=%s",
                (
                    transform.x_mm,
                    transform.y_mm,
                    transform.z_mm,
                    transform.yaw_microradians,
                    transform.scale_milli,
                    edit_id,
                    self.workspace_id,
                    self.world_id,
                    version_id,
                    instance_id,
                ),
            )
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="move_environment",
                environment_instance_id=instance_id,
                before=environment_instance_document(current),
                after=environment_instance_document(
                    self._require_environment(version_id, instance_id)
                ),
                actor=actor,
            )
            self._final_environment_authorization(
                self._require_environment(version_id, instance_id)
            )
        return self.version(version_id)

    def remove_environment(
        self,
        version_id: uuid.UUID,
        instance_id: str,
        *,
        base_state_sha256: str,
        actor: uuid.UUID,
    ) -> AlternateVersion:
        """Store a removal even when the immutable source has since been withdrawn."""
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            current = self._require_environment(version_id, instance_id)
            if current.removed:
                raise InvalidEnvironmentState(f"{instance_id} is already removed in this version")
            edit_id = uuid.uuid4()
            self.connection.execute(
                "update world_alternate_environment_instance set removed=true,last_edit_id=%s "
                "where workspace_id=%s and world_id=%s and version_id=%s and instance_id=%s",
                (edit_id, self.workspace_id, self.world_id, version_id, instance_id),
            )
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="remove_environment",
                environment_instance_id=instance_id,
                before=environment_instance_document(current),
                after=environment_instance_document(
                    self._require_environment(version_id, instance_id)
                ),
                actor=actor,
            )
        return self.version(version_id)

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
            checked = self._validated_object(row, obj)
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

    def validate_object_placement(
        self,
        version_id: uuid.UUID,
        obj: AuthoredObject,
        *,
        base_state_sha256: str,
    ) -> AuthoredObject:
        """Validate exactly what add would validate, without taking a lock or writing.

        The object counterpart of ``validate_environment_placement``: the same base, region,
        catalog, behaviour, byte and duplicate checks ``add_object`` runs, in the same order,
        through the same ``_validated_object``. Every operation is a SELECT or a store lookup.
        """
        row = self._version_row(version_id)
        self._require_edit_base(row, base_state_sha256)
        return self._validated_object(row, obj)

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

    def set_object_behaviour(
        self,
        version_id: uuid.UUID,
        object_id: str,
        behaviour: ObjectBehaviour | None,
        *,
        base_state_sha256: str,
        actor: uuid.UUID,
    ) -> AlternateVersion:
        """Give an object that already exists a behaviour, change it, or take it away with ``None``.

        The behaviour is checked by the same ``validate_behaviour`` an addition runs, so an unknown
        key, an unknown version or an out-of-range parameter fails closed before anything is
        written. The edit stores the whole object document on both sides, as a move does, which is
        what lets undo restore the previous behaviour with its parameters rather than a default.

        An edit that leaves the behaviour as it was is refused. It would append a log entry whose
        undo changes nothing a person can see, and "take back the last change" would then appear
        to do nothing.
        """
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            current = self._require_object(version_id, object_id)
            if current.removed:
                raise InvalidObjectState(f"{object_id} is removed in this version")
            checked = validate_behaviour(behaviour, self.behaviour_registry())
            before = object_document(current)
            if before["behaviour"] == (None if checked is None else checked.document()):
                raise InvalidObjectState(
                    f"{object_id} has no behaviour to take away"
                    if checked is None
                    else f"{object_id} already has exactly that behaviour"
                )
            edit_id = uuid.uuid4()
            self.connection.execute(
                "update world_alternate_object set behaviour_key=%s,behaviour_version=%s,"
                "behaviour_parameters=%s,last_edit_id=%s "
                "where workspace_id=%s and world_id=%s and version_id=%s and object_id=%s",
                (
                    None if checked is None else checked.behaviour_key,
                    None if checked is None else checked.behaviour_version,
                    None if checked is None else Jsonb(dict(checked.parameters)),
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
                kind="set_object_behaviour",
                object_id=object_id,
                before=before,
                after=object_document(self._require_object(version_id, object_id)),
                actor=actor,
            )
        return self.version(version_id)

    def undo(
        self, version_id: uuid.UUID, *, base_state_sha256: str, actor: uuid.UUID
    ) -> AlternateVersion:
        """Reverse the newest edit that has not already been reversed.

        Two properties are worth naming, because the obvious implementation has neither.

        **It steps back through history rather than one step.** The candidate is the newest edit
        that no undo names, so a person who added three objects can take all three back. Choosing
        "the newest edit" instead would refuse the second undo, because by then the newest edit is
        an undo, and a control that works once is not an undo.

        **Every edit kind is reversible.** An earlier version reversed only object edits, so one
        element override sat at the head of the log and blocked undo for the whole version
        permanently: the override was newest, it was not an object edit, and nothing could ever
        move past it.

        Undo is still not redo. An undo edit is never itself a candidate, and undoing an undo
        would be a redo, which is a second meaning for one control.

        **A kind with no rule is refused, by name, before anything is written.** The rule is found
        through the edit-kind registry: the kind names its subject and the subject names the
        method that restores it. An edit the registry does not name raises
        :class:`~exulanica.world.edit_kinds.UnregisteredEditKind` rather than being read as some
        other subject's document.
        """
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            newest = self.connection.execute(
                f"select edit_id,kind,{_SUBJECT_COLUMNS},before_document "
                "from world_alternate_version_edit e "
                "where e.workspace_id=%s and e.world_id=%s and e.version_id=%s "
                "and e.kind <> 'undo' "
                "and not exists (select 1 from world_alternate_version_edit u "
                " where u.workspace_id=e.workspace_id and u.world_id=e.world_id "
                " and u.version_id=e.version_id and u.undone_edit_id=e.edit_id) "
                "order by e.edit_seq desc limit 1",
                (self.workspace_id, self.world_id, version_id),
            ).fetchone()
            if newest is None:
                raise InvalidObjectState("this version has no edit left to undo")
            subject_kind = edit_kind(newest["kind"]).subject
            restore = getattr(self, self._UNDO_RULES[subject_kind])
            edit_id = uuid.uuid4()
            subject, after = restore(
                version_id, newest[subject_kind.column], newest["before_document"], edit_id
            )
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="undo",
                before=subject,
                after=after,
                actor=actor,
                undone_edit_id=newest["edit_id"],
                **{each.column: newest[each.column] for each in EditSubject},
            )
        return self.version(version_id)

    def _undo_object(
        self,
        version_id: uuid.UUID,
        object_id: str,
        before: Mapping[str, Any] | None,
        edit_id: uuid.UUID,
    ) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
        current = self._require_object(version_id, object_id)
        if before is None:
            self.connection.execute(
                "update world_alternate_object set removed=true,last_edit_id=%s,"
                "addition_undone=true "
                "where workspace_id=%s and world_id=%s and version_id=%s and object_id=%s",
                (edit_id, self.workspace_id, self.world_id, version_id, object_id),
            )
            return object_document(current), None
        self._restore_object(version_id, before, edit_id)
        return object_document(current), object_document(
            self._require_object(version_id, object_id)
        )

    def _undo_override(
        self,
        version_id: uuid.UUID,
        element_id: str,
        before: Mapping[str, Any] | None,
        edit_id: uuid.UUID,
    ) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
        existing = {o.element_id: o for o in self._overrides(version_id)}
        current = existing.get(element_id)
        if before is None:
            self.connection.execute(
                "update world_alternate_element_override "
                "set addition_undone=true,last_edit_id=%s where workspace_id=%s "
                "and world_id=%s and version_id=%s and element_id=%s",
                (edit_id, self.workspace_id, self.world_id, version_id, element_id),
            )
            return (None if current is None else override_document(current)), None
        self._write_override(version_id, _override_from_document(before), edit_id)
        return (
            None if current is None else override_document(current),
            override_document({o.element_id: o for o in self._overrides(version_id)}[element_id]),
        )

    def _undo_environment(
        self,
        version_id: uuid.UUID,
        instance_id: str,
        before: Mapping[str, Any] | None,
        edit_id: uuid.UUID,
    ) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
        """Restore stored authored state without re-authorizing withdrawn source use."""
        current = self._require_environment(version_id, instance_id)
        if before is None:
            self.connection.execute(
                "update world_alternate_environment_instance "
                "set removed=true,addition_undone=true,last_edit_id=%s "
                "where workspace_id=%s and world_id=%s and version_id=%s and instance_id=%s",
                (edit_id, self.workspace_id, self.world_id, version_id, instance_id),
            )
            return environment_instance_document(current), None
        self._restore_environment(version_id, before, edit_id)
        return environment_instance_document(current), environment_instance_document(
            self._require_environment(version_id, instance_id)
        )

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
            self._write_override(version_id, override, edit_id)
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
        self._require_edit_base(row, base_state_sha256)
        return row

    def _require_edit_base(self, row: Mapping[str, Any], base_state_sha256: str) -> None:
        if self._source_invalidated(row["source_snapshot_id"]):
            raise InvalidatedSourceVersion(
                "a committed deletion invalidated this version's source snapshot"
            )
        if row["state_sha256"] != base_state_sha256:
            raise StaleObjectBase(
                "this version moved since the base was read; read it again and re-issue the edit"
            )

    def _validated_object(self, row: Mapping[str, Any], obj: AuthoredObject) -> AuthoredObject:
        assets = {asset.content_sha256: asset for asset in self.reviewed_assets()}
        checked = validate_object(
            obj,
            region_ids=self._source_region_ids(row["source_snapshot_id"]),
            asset_digests=frozenset(assets),
            registry=self.behaviour_registry(),
        )
        # After the data checks and before the bytes: a component is refused by name even when
        # its bytes are present, and the recovery is choosing another asset, not restoring any.
        assets[checked.asset_sha256].require_placeable()
        self._require_reviewed_asset_bytes(checked.asset_sha256)
        if checked.object_id in {o.object_id for o in self._objects(row["version_id"])}:
            raise InvalidObjectState(f"{checked.object_id} already exists in this version")
        return checked

    def _require_reviewed_asset_bytes(self, asset_sha256: str) -> None:
        """Refuse an addition that could never draw.

        The registry row is the reviewed decision and the store holds the bytes. An object whose
        bytes are absent yields no geometry and no placeholder, so adding one would store an edit
        the person can never see. A repository without a store cannot look, and says so rather
        than adding on trust, the same rule environment composition follows.
        """
        if self.store is None:
            raise UnavailableAsset("object composition requires the content-addressed store")
        if not self.store.exists(BlobId.from_hex(asset_sha256)):
            raise UnavailableAsset("the reviewed asset row exists and its bytes do not")

    def _validated_environment_placement(
        self,
        row: Mapping[str, Any],
        placement: EnvironmentPlacement,
        resolved: ResolvedEnvironmentSource | None = None,
    ) -> EnvironmentInstance:
        # The same id set ``_environment_instances`` reads, without resolving every existing
        # instance's availability, which reads each of their pinned blobs.
        present = self.connection.execute(
            "select 1 from world_alternate_environment_instance where workspace_id=%s "
            "and world_id=%s and version_id=%s and instance_id=%s and not addition_undone",
            (self.workspace_id, self.world_id, row["version_id"], placement.instance_id),
        ).fetchone()
        if present is not None:
            raise InvalidEnvironmentState(f"{placement.instance_id} already exists in this version")
        source = self._resolve_environment_source(placement, resolved)
        return validate_environment_instance(
            EnvironmentInstance(
                instance_id=placement.instance_id,
                source=source,
                region_id=placement.region_id,
                transform=placement.transform,
                origin=placement.origin,
            ),
            region_ids=self._source_region_ids(row["source_snapshot_id"]),
        )

    def _append_edit(
        self,
        row: Mapping[str, Any],
        *,
        edit_id: uuid.UUID,
        kind: str,
        object_id: str | None = None,
        before: Mapping[str, Any] | None,
        after: Mapping[str, Any] | None,
        actor: uuid.UUID,
        element_id: str | None = None,
        environment_instance_id: str | None = None,
        point_map_instance_id: str | None = None,
        undone_edit_id: uuid.UUID | None = None,
    ) -> None:
        version_id = row["version_id"]
        result = delta_sha256(
            objects=self._objects(version_id),
            element_overrides=self._overrides(version_id),
            environment_instances=self._environment_instances(version_id, with_availability=False),
            point_map_instances=self._point_map_instances(version_id, with_availability=False),
        )
        self.connection.execute(
            "insert into world_alternate_version_edit (edit_id,workspace_id,world_id,version_id,"
            "edit_seq,kind,object_id,element_id,environment_instance_id,point_map_instance_id,"
            "undone_edit_id,base_state_sha256,"
            "result_state_sha256,before_document,after_document,actor) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                edit_id,
                self.workspace_id,
                self.world_id,
                version_id,
                int(row["edit_seq"]) + 1,
                kind,
                object_id,
                element_id,
                environment_instance_id,
                point_map_instance_id,
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
        # Each intermediate authored state must reach the society in this same transaction.
        # Reconstructing only the newest state at the next tick loses intervening edits.
        if self.on_edit is not None:
            self.on_edit(version_id)
        elif (
            self.connection.execute(
                "select 1 from world_society where workspace_id=%s and world_id=%s "
                "and version_id=%s and engine_version=any(%s::text[])",
                (self.workspace_id, self.world_id, version_id, list(INPUT_ENGINES)),
            ).fetchone()
            is not None
        ):
            raise InvalidObjectState("purposeful society requires an atomic authored-input adapter")

    def _insert_object(
        self, version_id: uuid.UUID, obj: AuthoredObject, edit_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        created_edit_id, last_edit_id = edit_ids
        behaviour = obj.behaviour
        written = self.connection.execute(
            "insert into world_alternate_object (workspace_id,world_id,version_id,object_id,"
            "asset_sha256,region_id,x_mm,y_mm,z_mm,yaw_microradians,scale_milli,origin_kind,"
            "origin_role,behaviour_key,behaviour_version,behaviour_parameters,removed,"
            "created_edit_id,last_edit_id,addition_undone) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false) "
            "on conflict (workspace_id,world_id,version_id,object_id) do update set "
            "asset_sha256=excluded.asset_sha256,region_id=excluded.region_id,x_mm=excluded.x_mm,"
            "y_mm=excluded.y_mm,z_mm=excluded.z_mm,yaw_microradians=excluded.yaw_microradians,"
            "scale_milli=excluded.scale_milli,origin_kind=excluded.origin_kind,"
            "origin_role=excluded.origin_role,behaviour_key=excluded.behaviour_key,"
            "behaviour_version=excluded.behaviour_version,"
            "behaviour_parameters=excluded.behaviour_parameters,removed=excluded.removed,"
            "created_edit_id=excluded.created_edit_id,last_edit_id=excluded.last_edit_id,"
            "addition_undone=false where world_alternate_object.addition_undone "
            "returning object_id",
            (
                self.workspace_id,
                self.world_id,
                version_id,
                obj.object_id,
                obj.asset_sha256,
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
        ).fetchone()
        if written is None:
            raise InvalidObjectState(f"{obj.object_id} already exists in this version")

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
            "update world_alternate_object set asset_sha256=%s,region_id=%s,x_mm=%s,y_mm=%s,"
            "z_mm=%s,yaw_microradians=%s,scale_milli=%s,origin_role=%s,behaviour_key=%s,"
            "behaviour_version=%s,behaviour_parameters=%s,removed=%s,last_edit_id=%s,"
            "addition_undone=false "
            "where workspace_id=%s and world_id=%s and version_id=%s and object_id=%s",
            (
                obj.asset_sha256,
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

    def _insert_environment(
        self,
        version_id: uuid.UUID,
        instance: EnvironmentInstance,
        edit_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        source = instance.source
        selection = source.selection
        created_edit_id, last_edit_id = edit_ids
        written = self.connection.execute(
            """
            insert into world_alternate_environment_instance(
              workspace_id,world_id,version_id,instance_id,admission_id,render_asset_id,
              publication_id,selection_kind,feature_id,render_batch_id,source_sha256,
              source_receipt_sha256,render_sha256,render_receipt_sha256,index_sha256,
              index_receipt_sha256,publication_receipt_sha256,source_place_id,source_frame,
              source_bounds,source_anchor,region_id,x_mm,y_mm,z_mm,yaw_microradians,scale_milli,
              origin_kind,origin_role,removed,created_edit_id,last_edit_id,addition_undone)
            values(
              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false)
            on conflict (workspace_id,world_id,version_id,instance_id) do update set
              admission_id=excluded.admission_id,render_asset_id=excluded.render_asset_id,
              publication_id=excluded.publication_id,selection_kind=excluded.selection_kind,
              feature_id=excluded.feature_id,render_batch_id=excluded.render_batch_id,
              source_sha256=excluded.source_sha256,
              source_receipt_sha256=excluded.source_receipt_sha256,
              render_sha256=excluded.render_sha256,
              render_receipt_sha256=excluded.render_receipt_sha256,
              index_sha256=excluded.index_sha256,
              index_receipt_sha256=excluded.index_receipt_sha256,
              publication_receipt_sha256=excluded.publication_receipt_sha256,
              source_place_id=excluded.source_place_id,source_frame=excluded.source_frame,
              source_bounds=excluded.source_bounds,source_anchor=excluded.source_anchor,
              region_id=excluded.region_id,x_mm=excluded.x_mm,y_mm=excluded.y_mm,
              z_mm=excluded.z_mm,yaw_microradians=excluded.yaw_microradians,
              scale_milli=excluded.scale_milli,origin_kind=excluded.origin_kind,
              origin_role=excluded.origin_role,removed=excluded.removed,
              created_edit_id=excluded.created_edit_id,last_edit_id=excluded.last_edit_id,
              addition_undone=false
            where world_alternate_environment_instance.addition_undone
            returning instance_id
            """,
            (
                self.workspace_id,
                self.world_id,
                version_id,
                instance.instance_id,
                source.admission_id,
                source.render_asset_id,
                source.publication_id,
                selection.kind,
                selection.feature_id,
                selection.render_batch_id,
                bytes.fromhex(source.source_sha256),
                bytes.fromhex(source.source_receipt_sha256),
                bytes.fromhex(source.render_sha256),
                bytes.fromhex(source.render_receipt_sha256),
                None if source.index_sha256 is None else bytes.fromhex(source.index_sha256),
                None
                if source.index_receipt_sha256 is None
                else bytes.fromhex(source.index_receipt_sha256),
                None
                if source.publication_receipt_sha256 is None
                else bytes.fromhex(source.publication_receipt_sha256),
                source.place_id,
                Jsonb(dict(source.frame)),
                Jsonb(dict(source.bounds)),
                Jsonb(source.anchor.document()),
                instance.region_id,
                instance.transform.x_mm,
                instance.transform.y_mm,
                instance.transform.z_mm,
                instance.transform.yaw_microradians,
                instance.transform.scale_milli,
                instance.origin.kind,
                instance.origin.role,
                instance.removed,
                created_edit_id,
                last_edit_id,
            ),
        ).fetchone()
        if written is None:
            raise InvalidEnvironmentState(f"{instance.instance_id} already exists in this version")

    def _restore_environment(
        self, version_id: uuid.UUID, document: Mapping[str, Any], edit_id: uuid.UUID
    ) -> None:
        current = self._require_environment(version_id, document["instance_id"])
        current_document = environment_instance_document(current)
        if (
            current_document["source"] != document["source"]
            or current_document["origin"] != document["origin"]
        ):
            raise InvalidEnvironmentState("stored undo source binding disagrees with current state")
        transform = document["transform"]
        self.connection.execute(
            "update world_alternate_environment_instance "
            "set region_id=%s,x_mm=%s,y_mm=%s,z_mm=%s,yaw_microradians=%s,scale_milli=%s,"
            "removed=%s,last_edit_id=%s,addition_undone=false "
            "where workspace_id=%s and world_id=%s and version_id=%s and instance_id=%s",
            (
                document["region_id"],
                transform["x_mm"],
                transform["y_mm"],
                transform["z_mm"],
                transform["yaw_microradians"],
                transform["scale_milli"],
                document["removed"],
                edit_id,
                self.workspace_id,
                self.world_id,
                version_id,
                document["instance_id"],
            ),
        )

    def _write_override(
        self, version_id: uuid.UUID, override: ElementOverride, edit_id: uuid.UUID
    ) -> None:
        transform = override.transform
        self.connection.execute(
            "insert into world_alternate_element_override (workspace_id,world_id,version_id,"
            "element_id,suppressed,x_mm,y_mm,z_mm,yaw_microradians,scale_milli,last_edit_id,"
            "addition_undone) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false) "
            "on conflict (workspace_id,world_id,version_id,element_id) do update set "
            "suppressed=excluded.suppressed,x_mm=excluded.x_mm,y_mm=excluded.y_mm,"
            "z_mm=excluded.z_mm,yaw_microradians=excluded.yaw_microradians,"
            "scale_milli=excluded.scale_milli,last_edit_id=excluded.last_edit_id,"
            "addition_undone=false",
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

    # -- photo-derived point map edits -------------------------------------------------------
    #
    # A reviewed photograph's depth estimate, placed in this version by the person whose
    # photograph it is. What resolves (the estimate reached through a current membership, never
    # the attachment), which estimate the pinned screening names, and why availability is read and
    # never stored are the point map source authority's, and its module says so first.

    def add_point_map(
        self,
        version_id: uuid.UUID,
        placement: PointMapPlacement,
        *,
        base_state_sha256: str,
        actor: uuid.UUID,
    ) -> AlternateVersion:
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            instance = self._validated_point_map_placement(row, placement)
            edit_id = uuid.uuid4()
            self._insert_point_map(version_id, instance, (edit_id, edit_id))
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="add_point_map",
                point_map_instance_id=instance.instance_id,
                before=None,
                after=point_map_instance_document(instance),
                actor=actor,
            )
            self._final_point_map_authorization(instance)
        return self.version(version_id)

    def validate_point_map_placement(
        self,
        version_id: uuid.UUID,
        placement: PointMapPlacement,
        *,
        base_state_sha256: str,
        resolved_source: PointMapSourceBinding | None = None,
    ) -> PointMapInstance:
        """Validate exactly what add would validate, without taking a lock or writing.

        The point-map counterpart of ``validate_environment_placement``: the same membership,
        permission, artifact, rung, byte, region and duplicate checks, in the same order, through
        the same ``_validated_point_map_placement``. Every operation is a SELECT or a store read.
        """
        row = self._version_row(version_id)
        self._require_edit_base(row, base_state_sha256)
        return self._validated_point_map_placement(row, placement, resolved_source)

    def move_point_map(
        self,
        version_id: uuid.UUID,
        instance_id: str,
        transform: Transform,
        *,
        base_state_sha256: str,
        actor: uuid.UUID,
    ) -> AlternateVersion:
        """Move a placed estimate, which is refused while it may not be drawn.

        Moving something a person cannot see is an edit they cannot judge the result of, and on an
        estimate whose permission has ended it is an edit to a reading of their home that they
        have already stopped. Remove and undo stay available, because both take it away.
        """
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            current = self._require_point_map(version_id, instance_id)
            if current.removed:
                raise InvalidObjectState(f"{instance_id} is removed in this version")
            validate_transform(transform)
            self._require_point_map_current(current)
            edit_id = uuid.uuid4()
            self.connection.execute(
                "update world_alternate_point_map_instance "
                "set x_mm=%s,y_mm=%s,z_mm=%s,yaw_microradians=%s,scale_milli=%s,last_edit_id=%s "
                "where workspace_id=%s and world_id=%s and version_id=%s and instance_id=%s",
                (
                    transform.x_mm,
                    transform.y_mm,
                    transform.z_mm,
                    transform.yaw_microradians,
                    transform.scale_milli,
                    edit_id,
                    self.workspace_id,
                    self.world_id,
                    version_id,
                    instance_id,
                ),
            )
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="move_point_map",
                point_map_instance_id=instance_id,
                before=point_map_instance_document(current),
                after=point_map_instance_document(self._require_point_map(version_id, instance_id)),
                actor=actor,
            )
            self._final_point_map_authorization(self._require_point_map(version_id, instance_id))
        return self.version(version_id)

    def remove_point_map(
        self,
        version_id: uuid.UUID,
        instance_id: str,
        *,
        base_state_sha256: str,
        actor: uuid.UUID,
    ) -> AlternateVersion:
        """Take it out, whatever has happened to the photograph or the permission behind it.

        Deliberately asks nothing about the source. A person whose right has ended, or whose
        photograph is gone, is exactly the person most likely to want this, and a removal that
        first required the thing being removed to be readable would refuse them.
        """
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            current = self._require_point_map(version_id, instance_id)
            if current.removed:
                raise InvalidObjectState(f"{instance_id} is already removed in this version")
            edit_id = uuid.uuid4()
            self.connection.execute(
                "update world_alternate_point_map_instance set removed=true,last_edit_id=%s "
                "where workspace_id=%s and world_id=%s and version_id=%s and instance_id=%s",
                (edit_id, self.workspace_id, self.world_id, version_id, instance_id),
            )
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="remove_point_map",
                point_map_instance_id=instance_id,
                before=point_map_instance_document(current),
                after=point_map_instance_document(self._require_point_map(version_id, instance_id)),
                actor=actor,
            )
        return self.version(version_id)

    # -- point map source authority ---------------------------------------------------------
    #
    # Whether a placed estimate's source may be used is asked of
    # :class:`~exulanica.world.point_map_source_authority.PointMapSourceAuthority`, on this
    # repository's connection and inside its transaction, through the same-named methods below.

    @property
    def _point_map_sources(self) -> PointMapSourceAuthority:
        return PointMapSourceAuthority(
            self.connection, self.workspace_id, world_id=self.world_id, store=self.store
        )

    def validate_point_map_source(
        self, entry_id: uuid.UUID, attachment_id: uuid.UUID
    ) -> PointMapSourceBinding:
        """The source half of ``validate_point_map_placement``, before a placement exists.

        Runs the membership, permission, artifact, rung and byte checks add would run for this
        exact reference, in the same order and through the same resolver, and returns what a
        placement would pin. Read-only.
        """
        return self._point_map_sources.resolve(entry_id, attachment_id)

    def _resolve_point_map_source(
        self, entry_id: uuid.UUID, attachment_id: uuid.UUID
    ) -> PointMapSourceBinding:
        return self._point_map_sources.resolve(entry_id, attachment_id)

    def _validated_point_map_placement(
        self,
        row: Mapping[str, Any],
        placement: PointMapPlacement,
        resolved: PointMapSourceBinding | None = None,
    ) -> PointMapInstance:
        present = self.connection.execute(
            "select 1 from world_alternate_point_map_instance where workspace_id=%s "
            "and world_id=%s and version_id=%s and instance_id=%s and not addition_undone",
            (self.workspace_id, self.world_id, row["version_id"], placement.instance_id),
        ).fetchone()
        if present is not None:
            raise InvalidObjectState(f"{placement.instance_id} already exists in this version")
        source = resolved
        if source is None:
            source = self._resolve_point_map_source(placement.entry_id, placement.attachment_id)
        elif (source.entry_id, source.attachment_id) != (
            placement.entry_id,
            placement.attachment_id,
        ):
            raise InvalidPointMapPlacement("the resolved source is not this placement's reference")
        try:
            return validate_point_map_instance(
                PointMapInstance(
                    instance_id=placement.instance_id,
                    source=source,
                    region_id=placement.region_id,
                    transform=placement.transform,
                    origin=placement.origin,
                ),
                region_ids=self._source_region_ids(row["source_snapshot_id"]),
            )
        except InvalidObjectData as exc:
            raise InvalidPointMapPlacement(str(exc)) from exc

    def _final_point_map_authorization(self, instance: PointMapInstance) -> None:
        self._point_map_sources.final_authorization(instance)

    def _require_point_map_current(self, instance: PointMapInstance) -> None:
        self._point_map_sources.require_current(instance)

    def _point_map_state(self, instance: PointMapInstance) -> tuple[str, str | None]:
        return self._point_map_sources.state(instance)

    def _insert_point_map(
        self,
        version_id: uuid.UUID,
        instance: PointMapInstance,
        edit_ids: tuple[uuid.UUID, uuid.UUID],
    ) -> None:
        source = instance.source
        created_edit_id, last_edit_id = edit_ids
        written = self.connection.execute(
            """
            insert into world_alternate_point_map_instance(
              workspace_id,world_id,version_id,instance_id,entry_id,attachment_id,capture_id,
              source_sha256,authorization_id,authorization_evidence_sha256,screening_id,
              screening_receipt_sha256,right_id,right_receipt_sha256,model_provider,model_role,
              model_identifier,model_revision,model_destination,artifact_id,point_map_sha256,
              byte_size,container,stage_version,rung,declared_metric,
              declared_fov_y_microdegrees,region_id,x_mm,y_mm,z_mm,yaw_microradians,scale_milli,
              origin_kind,origin_role,removed,created_edit_id,last_edit_id,addition_undone)
            values(
              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false)
            on conflict (workspace_id,world_id,version_id,instance_id) do update set
              entry_id=excluded.entry_id,attachment_id=excluded.attachment_id,
              capture_id=excluded.capture_id,source_sha256=excluded.source_sha256,
              authorization_id=excluded.authorization_id,
              authorization_evidence_sha256=excluded.authorization_evidence_sha256,
              screening_id=excluded.screening_id,
              screening_receipt_sha256=excluded.screening_receipt_sha256,
              right_id=excluded.right_id,right_receipt_sha256=excluded.right_receipt_sha256,
              model_provider=excluded.model_provider,model_role=excluded.model_role,
              model_identifier=excluded.model_identifier,model_revision=excluded.model_revision,
              model_destination=excluded.model_destination,artifact_id=excluded.artifact_id,
              point_map_sha256=excluded.point_map_sha256,byte_size=excluded.byte_size,
              container=excluded.container,stage_version=excluded.stage_version,
              rung=excluded.rung,declared_metric=excluded.declared_metric,
              declared_fov_y_microdegrees=excluded.declared_fov_y_microdegrees,
              region_id=excluded.region_id,x_mm=excluded.x_mm,y_mm=excluded.y_mm,
              z_mm=excluded.z_mm,yaw_microradians=excluded.yaw_microradians,
              scale_milli=excluded.scale_milli,origin_kind=excluded.origin_kind,
              origin_role=excluded.origin_role,removed=excluded.removed,
              created_edit_id=excluded.created_edit_id,last_edit_id=excluded.last_edit_id,
              addition_undone=false
            where world_alternate_point_map_instance.addition_undone
            returning instance_id
            """,
            (
                self.workspace_id,
                self.world_id,
                version_id,
                instance.instance_id,
                source.entry_id,
                source.attachment_id,
                source.capture_id,
                bytes.fromhex(source.source_sha256),
                source.authorization_id,
                bytes.fromhex(source.authorization_evidence_sha256),
                source.screening_id,
                bytes.fromhex(source.screening_receipt_sha256),
                source.right_id,
                bytes.fromhex(source.right_receipt_sha256),
                source.model.provider,
                source.model.role,
                source.model.identifier,
                source.model.revision,
                source.model.destination,
                source.artifact_id,
                bytes.fromhex(source.point_map_sha256),
                source.byte_size,
                source.container,
                source.stage_version,
                source.rung,
                source.declared_metric,
                source.declared_fov_y_microdegrees,
                instance.region_id,
                instance.transform.x_mm,
                instance.transform.y_mm,
                instance.transform.z_mm,
                instance.transform.yaw_microradians,
                instance.transform.scale_milli,
                instance.origin.kind,
                instance.origin.role,
                instance.removed,
                created_edit_id,
                last_edit_id,
            ),
        ).fetchone()
        if written is None:
            raise InvalidObjectState(f"{instance.instance_id} already exists in this version")

    def _point_map_instances(
        self, version_id: uuid.UUID, *, with_availability: bool = True
    ) -> tuple[PointMapInstance, ...]:
        rows = self.connection.execute(
            """
            select instance_id,entry_id,attachment_id,capture_id,source_sha256,authorization_id,
                   authorization_evidence_sha256,screening_id,screening_receipt_sha256,right_id,
                   right_receipt_sha256,model_provider,model_role,model_identifier,model_revision,
                   model_destination,artifact_id,point_map_sha256,byte_size,container,
                   stage_version,rung,declared_metric,declared_fov_y_microdegrees,region_id,
                   x_mm,y_mm,z_mm,yaw_microradians,scale_milli,origin_kind,origin_role,removed
              from world_alternate_point_map_instance
             where workspace_id=%s and world_id=%s and version_id=%s and not addition_undone
             order by instance_id
            """,
            (self.workspace_id, self.world_id, version_id),
        ).fetchall()
        return tuple(self._point_map_from_row(row, with_availability) for row in rows)

    def _point_map_from_row(
        self, row: Mapping[str, Any], with_availability: bool = True
    ) -> PointMapInstance:
        instance = PointMapInstance(
            instance_id=row["instance_id"],
            source=PointMapSourceBinding(
                entry_id=row["entry_id"],
                attachment_id=row["attachment_id"],
                capture_id=row["capture_id"],
                source_sha256=bytes(row["source_sha256"]).hex(),
                authorization_id=row["authorization_id"],
                authorization_evidence_sha256=bytes(row["authorization_evidence_sha256"]).hex(),
                screening_id=row["screening_id"],
                screening_receipt_sha256=bytes(row["screening_receipt_sha256"]).hex(),
                right_id=row["right_id"],
                right_receipt_sha256=bytes(row["right_receipt_sha256"]).hex(),
                model=PointMapModel(
                    provider=row["model_provider"],
                    role=row["model_role"],
                    identifier=row["model_identifier"],
                    revision=row["model_revision"],
                    destination=row["model_destination"],
                ),
                artifact_id=row["artifact_id"],
                point_map_sha256=bytes(row["point_map_sha256"]).hex(),
                byte_size=int(row["byte_size"]),
                container=row["container"],
                stage_version=int(row["stage_version"]),
                rung=int(row["rung"]),
                declared_metric=bool(row["declared_metric"]),
                declared_fov_y_microdegrees=int(row["declared_fov_y_microdegrees"]),
            ),
            region_id=row["region_id"],
            transform=Transform(
                row["x_mm"],
                row["y_mm"],
                row["z_mm"],
                row["yaw_microradians"],
                row["scale_milli"],
            ),
            origin=ObjectOrigin(row["origin_kind"], row["origin_role"]),
            removed=row["removed"],
        )
        if not with_availability:
            return instance
        availability, reason = self._point_map_state(instance)
        return PointMapInstance(
            instance_id=instance.instance_id,
            source=instance.source,
            region_id=instance.region_id,
            transform=instance.transform,
            origin=instance.origin,
            removed=instance.removed,
            availability=availability,  # type: ignore[arg-type]
            unavailable_reason=reason,
        )

    def _require_point_map(self, version_id: uuid.UUID, instance_id: str) -> PointMapInstance:
        for instance in self._point_map_instances(version_id):
            if instance.instance_id == instance_id:
                return instance
        raise UnknownWorldResource(f"no point map instance {instance_id} in this version")

    def _point_map_edit_ids(
        self, version_id: uuid.UUID, instance_id: str
    ) -> tuple[uuid.UUID, uuid.UUID]:
        row = self.connection.execute(
            "select created_edit_id,last_edit_id from world_alternate_point_map_instance "
            "where workspace_id=%s and world_id=%s and version_id=%s and instance_id=%s",
            (self.workspace_id, self.world_id, version_id, instance_id),
        ).fetchone()
        return (row["created_edit_id"], row["last_edit_id"])

    def _undo_point_map(
        self,
        version_id: uuid.UUID,
        instance_id: str,
        before: Mapping[str, Any] | None,
        edit_id: uuid.UUID,
    ) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
        """Restore stored authored state without re-authorizing a permission that has since ended.

        Undo takes an edit back. Taking back an addition always works, because the result is less
        of the person's photograph in the world, not more; taking back a removal restores what was
        already stored, and whether it may be DRAWN is decided on read, where every other change
        of permission is decided too.
        """
        current = self._require_point_map(version_id, instance_id)
        if before is None:
            self.connection.execute(
                "update world_alternate_point_map_instance "
                "set removed=true,addition_undone=true,last_edit_id=%s "
                "where workspace_id=%s and world_id=%s and version_id=%s and instance_id=%s",
                (edit_id, self.workspace_id, self.world_id, version_id, instance_id),
            )
            return point_map_instance_document(current), None
        self._restore_point_map(version_id, before, edit_id)
        return point_map_instance_document(current), point_map_instance_document(
            self._require_point_map(version_id, instance_id)
        )

    def _restore_point_map(
        self, version_id: uuid.UUID, document: Mapping[str, Any], edit_id: uuid.UUID
    ) -> None:
        current = self._require_point_map(version_id, document["instance_id"])
        current_document = point_map_instance_document(current)
        if (
            current_document["source"] != document["source"]
            or current_document["origin"] != document["origin"]
        ):
            raise InvalidObjectState("stored undo source binding disagrees with current state")
        transform = document["transform"]
        self.connection.execute(
            "update world_alternate_point_map_instance set region_id=%s,x_mm=%s,y_mm=%s,z_mm=%s,"
            "yaw_microradians=%s,scale_milli=%s,removed=%s,last_edit_id=%s "
            "where workspace_id=%s and world_id=%s and version_id=%s and instance_id=%s",
            (
                document["region_id"],
                transform["x_mm"],
                transform["y_mm"],
                transform["z_mm"],
                transform["yaw_microradians"],
                transform["scale_milli"],
                document["removed"],
                edit_id,
                self.workspace_id,
                self.world_id,
                version_id,
                document["instance_id"],
            ),
        )

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
            "select object_id,asset_sha256,region_id,x_mm,y_mm,z_mm,yaw_microradians,scale_milli,"
            "origin_kind,origin_role,behaviour_key,behaviour_version,behaviour_parameters,removed "
            "from world_alternate_object where workspace_id=%s and world_id=%s and version_id=%s "
            "and not addition_undone "
            "order by object_id",
            (self.workspace_id, self.world_id, version_id),
        ).fetchall()
        return tuple(
            AuthoredObject(
                object_id=r["object_id"],
                asset_sha256=r["asset_sha256"],
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
            "where workspace_id=%s and world_id=%s and version_id=%s "
            "and not addition_undone order by element_id",
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

    def _environment_instances(
        self, version_id: uuid.UUID, *, with_availability: bool = True
    ) -> tuple[EnvironmentInstance, ...]:
        """The version's environment instances, sorted by id.

        ``with_availability`` resolves each instance's current binding and reads its pinned bytes,
        which is what a reader needs and what a digest must not pay for: availability is not part
        of ``environment_instance_document`` and so not part of ``state_sha256``.
        """
        rows = self.connection.execute(
            """
            select instance_id,admission_id,render_asset_id,publication_id,selection_kind,
                   feature_id,render_batch_id,source_sha256,source_receipt_sha256,render_sha256,
                   render_receipt_sha256,index_sha256,index_receipt_sha256,
                   publication_receipt_sha256,source_place_id,source_frame,source_bounds,
                   source_anchor,region_id,x_mm,y_mm,z_mm,yaw_microradians,scale_milli,
                   origin_kind,origin_role,removed
              from world_alternate_environment_instance
             where workspace_id=%s and world_id=%s and version_id=%s
               and not addition_undone
             order by instance_id
            """,
            (self.workspace_id, self.world_id, version_id),
        ).fetchall()
        return tuple(self._environment_from_row(row, with_availability) for row in rows)

    def _environment_from_row(
        self, row: Mapping[str, Any], with_availability: bool = True
    ) -> EnvironmentInstance:
        source = EnvironmentSourceBinding(
            admission_id=row["admission_id"],
            render_asset_id=row["render_asset_id"],
            publication_id=row["publication_id"],
            source_sha256=bytes(row["source_sha256"]).hex(),
            source_receipt_sha256=bytes(row["source_receipt_sha256"]).hex(),
            render_sha256=bytes(row["render_sha256"]).hex(),
            render_receipt_sha256=bytes(row["render_receipt_sha256"]).hex(),
            index_sha256=(
                None if row["index_sha256"] is None else bytes(row["index_sha256"]).hex()
            ),
            index_receipt_sha256=(
                None
                if row["index_receipt_sha256"] is None
                else bytes(row["index_receipt_sha256"]).hex()
            ),
            publication_receipt_sha256=(
                None
                if row["publication_receipt_sha256"] is None
                else bytes(row["publication_receipt_sha256"]).hex()
            ),
            place_id=row["source_place_id"],
            frame=row["source_frame"],
            bounds=row["source_bounds"],
            anchor=SourceAnchor(
                row["source_anchor"]["frame_name"],
                row["source_anchor"]["coordinate_scale"],
                tuple(row["source_anchor"]["coordinates"]),
            ),
            selection=EnvironmentSelection(
                row["selection_kind"], row["feature_id"], row["render_batch_id"]
            ),
        )
        instance = EnvironmentInstance(
            instance_id=row["instance_id"],
            source=source,
            region_id=row["region_id"],
            transform=Transform(
                row["x_mm"],
                row["y_mm"],
                row["z_mm"],
                row["yaw_microradians"],
                row["scale_milli"],
            ),
            origin=ObjectOrigin(row["origin_kind"], row["origin_role"]),
            removed=row["removed"],
        )
        if not with_availability:
            return instance
        return EnvironmentInstance(
            instance_id=instance.instance_id,
            source=instance.source,
            region_id=instance.region_id,
            transform=instance.transform,
            origin=instance.origin,
            removed=instance.removed,
            availability=self._environment_availability(instance),
        )

    def _edits(self, version_id: uuid.UUID) -> tuple[VersionEdit, ...]:
        rows = self.connection.execute(
            f"select edit_id,edit_seq,kind,{_SUBJECT_COLUMNS},undone_edit_id,base_state_sha256,"
            "result_state_sha256,actor,recorded_at from world_alternate_version_edit "
            "where workspace_id=%s and world_id=%s and version_id=%s order by edit_seq",
            (self.workspace_id, self.world_id, version_id),
        ).fetchall()
        return tuple(
            VersionEdit(
                edit_id=r["edit_id"],
                edit_seq=r["edit_seq"],
                kind=r["kind"],
                undone_edit_id=r["undone_edit_id"],
                base_state_sha256=r["base_state_sha256"],
                result_state_sha256=r["result_state_sha256"],
                actor=r["actor"],
                recorded_at=r["recorded_at"].isoformat(),
                **{each.column: r[each.column] for each in EditSubject},
            )
            for r in rows
        )

    def _require_object(self, version_id: uuid.UUID, object_id: str) -> AuthoredObject:
        for obj in self._objects(version_id):
            if obj.object_id == object_id:
                return obj
        raise UnknownWorldResource("no such authored object")

    def _require_environment(self, version_id: uuid.UUID, instance_id: str) -> EnvironmentInstance:
        for instance in self._environment_instances(version_id):
            if instance.instance_id == instance_id:
                return instance
        raise UnknownWorldResource("no such environment instance")

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

    def _environment_edit_ids(
        self, version_id: uuid.UUID, instance_id: str
    ) -> tuple[uuid.UUID, uuid.UUID]:
        row = self.connection.execute(
            "select created_edit_id,last_edit_id from world_alternate_environment_instance "
            "where workspace_id=%s and world_id=%s and version_id=%s and instance_id=%s",
            (self.workspace_id, self.world_id, version_id, instance_id),
        ).fetchone()
        return (row["created_edit_id"], row["last_edit_id"])

    # -- environment source authority -------------------------------------------------------
    #
    # Whether an exact environment source may be composed is asked of
    # :class:`~exulanica.world.environment_source_authority.EnvironmentSourceAuthority`, on this
    # repository's connection and inside its transaction. The same-named methods below are the
    # only way the repository reaches it, so a test that patches one intercepts every caller.

    @property
    def _environment_sources(self) -> EnvironmentSourceAuthority:
        return EnvironmentSourceAuthority(self.connection, self.workspace_id, self.store)

    def validate_environment_source(
        self,
        admission_id: uuid.UUID,
        render_asset_id: uuid.UUID,
        publication_id: uuid.UUID | None,
        selection: EnvironmentSelection,
    ) -> ResolvedEnvironmentSource:
        """The source half of ``validate_environment_placement``, before a placement exists.

        Runs the binding, withdrawal, compose-rights, byte and publication checks that add would
        run for this exact source, in the same order and through the same resolver, and returns
        the resolution, whose ``render_sha256`` is the digest a placement would pin. Nothing about
        a destination is checked, because there is none yet. Read-only, like
        ``validate_environment_placement``.
        """
        return self._environment_sources.authorize(
            admission_id, render_asset_id, publication_id, selection
        )

    def _resolve_environment_source(
        self,
        placement: EnvironmentPlacement,
        resolved: ResolvedEnvironmentSource | None = None,
    ) -> EnvironmentSourceBinding:
        return self._environment_sources.binding(placement, resolved)

    def _require_pinned_environment_current(
        self,
        instance: EnvironmentInstance,
        *,
        require_bytes: bool,
        validate_feature_bytes: bool = True,
    ) -> None:
        self._environment_sources.require_current(
            instance, require_bytes=require_bytes, validate_feature_bytes=validate_feature_bytes
        )

    def _final_environment_authorization(self, instance: EnvironmentInstance) -> None:
        self._environment_sources.final_authorization(instance)

    def _environment_availability(self, instance: EnvironmentInstance) -> str:
        return self._environment_sources.availability(instance)

    # -- the source snapshot ----------------------------------------------------------------

    def _require_style_version(self, style_version_id: uuid.UUID | None) -> None:
        """Check the appearance reference before the foreign key does.

        The composite key on (workspace_id, world_id, style_version_id) already refuses an
        unknown or cross-workspace value, but it refuses it as a ForeignKeyViolation, which no
        handler on this surface recognises and which therefore reaches the caller as a 500. An
        id the caller supplied is an input, and a bad input is a 404 here like every other
        unknown reference.
        """
        if style_version_id is None:
            return
        row = self.connection.execute(
            "select 1 from world_style_version "
            "where workspace_id=%s and world_id=%s and version_id=%s",
            (self.workspace_id, self.world_id, style_version_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such style version")

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
        lock_workspace(self.connection, self.workspace_id)


def _override_from_document(document: Mapping[str, Any]) -> ElementOverride:
    transform = document["transform"]
    return ElementOverride(
        element_id=document["element_id"],
        suppressed=document["suppressed"],
        transform=(
            None
            if transform is None
            else Transform(
                transform["x_mm"],
                transform["y_mm"],
                transform["z_mm"],
                transform["yaw_microradians"],
                transform["scale_milli"],
            )
        ),
    )


def _object_from_document(document: Mapping[str, Any]) -> AuthoredObject:
    transform = document["transform"]
    behaviour = document["behaviour"]
    return AuthoredObject(
        object_id=document["object_id"],
        asset_sha256=document["asset_sha256"],
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
