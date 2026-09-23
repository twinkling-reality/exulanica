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

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.reconstruction.validation import (
    OpmIntegrityError,
    OpmIntegrityReport,
    validate_opm,
)
from exulanica.store.base import ContentAddressedStore
from exulanica.world.environment_instances import (
    EnvironmentInstance,
    EnvironmentPlacement,
    EnvironmentSelection,
    EnvironmentSourceBinding,
    SourceAnchor,
    environment_instance_document,
    validate_environment_instance,
)
from exulanica.world.errors import (
    EnvironmentBindingDrift,
    EnvironmentCompositionDenied,
    EnvironmentSourceWithdrawn,
    InvalidatedSourceVersion,
    InvalidEnvironmentData,
    InvalidEnvironmentState,
    InvalidObjectData,
    InvalidObjectState,
    InvalidPointMapPlacement,
    PointMapNotPermitted,
    PointMapNotProduced,
    PointMapNotReadable,
    PointMapReviewDiffers,
    PointMapTooSparse,
    SourceAuthorityExpired,
    SourceNotCurrentMembership,
    StaleObjectBase,
    UnavailableAsset,
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
    validate_behaviour,
    validate_object,
    validate_transform,
)
from exulanica.world.photo_point_maps import (
    DEPTH_ROLE,
    PLACEABLE_RUNG,
    POINT_MAP_CONTAINER,
    PointMapInstance,
    PointMapModel,
    PointMapPlacement,
    PointMapSourceBinding,
    point_map_instance_document,
    validate_point_map_instance,
)

__all__ = ["ResolvedEnvironmentSource", "ReviewedAssetRow", "WorldObjectRepository"]

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


@dataclass(frozen=True, slots=True)
class ResolvedEnvironmentSource:
    """One authorized resolution of an exact environment source, before any destination.

    ``validate_environment_source`` returns it so a placement check in the same read can reuse it
    rather than resolving the source, and reading every pinned blob, a second time.
    """

    admission_id: uuid.UUID
    render_asset_id: uuid.UUID
    publication_id: uuid.UUID | None
    selection: EnvironmentSelection
    row: Mapping[str, Any]
    publication: Mapping[str, Any] | None
    bounds: Mapping[str, Any]

    @property
    def render_sha256(self) -> str:
        return bytes(self.row["render_sha256"]).hex()


class WorldObjectRepository:
    """One workspace and world's alternate versions, their objects, and the reviewed catalogs."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str = DEFAULT_WORLD_ID,
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
            state = delta_sha256(objects, overrides, environments, point_maps)
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
            state_sha256=delta_sha256(objects, overrides, environments, point_maps),
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
        """
        with self.connection.transaction():
            row = self._begin_edit(version_id, base_state_sha256)
            newest = self.connection.execute(
                "select edit_id,kind,object_id,element_id,environment_instance_id,"
                "point_map_instance_id,before_document "
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
            edit_id = uuid.uuid4()
            before = newest["before_document"]
            if newest["kind"] in {
                "add_object",
                "move_object",
                "remove_object",
                "set_object_behaviour",
            }:
                subject, after = self._undo_object(version_id, newest["object_id"], before, edit_id)
            elif newest["kind"] in {
                "add_environment",
                "move_environment",
                "remove_environment",
            }:
                subject, after = self._undo_environment(
                    version_id, newest["environment_instance_id"], before, edit_id
                )
            elif newest["kind"] in {"add_point_map", "move_point_map", "remove_point_map"}:
                subject, after = self._undo_point_map(
                    version_id, newest["point_map_instance_id"], before, edit_id
                )
            else:
                subject, after = self._undo_override(
                    version_id, newest["element_id"], before, edit_id
                )
            self._append_edit(
                row,
                edit_id=edit_id,
                kind="undo",
                object_id=newest["object_id"],
                element_id=newest["element_id"],
                environment_instance_id=newest["environment_instance_id"],
                point_map_instance_id=newest["point_map_instance_id"],
                before=subject,
                after=after,
                actor=actor,
                undone_edit_id=newest["edit_id"],
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
        checked = validate_object(
            obj,
            region_ids=self._source_region_ids(row["source_snapshot_id"]),
            asset_digests=frozenset(a.content_sha256 for a in self.reviewed_assets()),
            registry=self.behaviour_registry(),
        )
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
            self._objects(version_id),
            self._overrides(version_id),
            self._environment_instances(version_id, with_availability=False),
            self._point_map_instances(version_id, with_availability=False),
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
                "and version_id=%s and engine_version in "
                "('exulanica-society/v2','exulanica-society/v3','exulanica-society/v4')",
                (self.workspace_id, self.world_id, version_id),
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
    # photograph it is. Three things separate this from the environment kind above and are worth
    # reading before the methods.
    #
    # WHAT RESOLVES IS NOT THE ATTACHMENT. An attachment is membership, and composing one is
    # refused (``attachment_is_not_composition``). What is placed is the depth artifact reached
    # THROUGH a current membership, and the membership is recorded so a detach can reach what it
    # produced.
    #
    # THE PINNED SCREENING DECIDES WHICH ESTIMATE. The attachment pins the human review the
    # photograph was added under. The derivative worker builds from the NEWEST eligible screening.
    # A photograph reviewed twice therefore has an estimate the current reference does not name,
    # and that is ``PointMapReviewDiffers`` rather than "not produced": nothing is wrong, the
    # reference is simply older than the estimate, and the recovery is to add it back under the
    # newer review.
    #
    # AVAILABILITY IS READ, NEVER STORED. Whether a person may see a placed estimate changes when
    # a right ends, a review expires, a photograph is deleted or a membership is detached, none of
    # which is an edit to their world. It is computed on read and kept out of the state digest.

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
                after=point_map_instance_document(
                    self._require_point_map(version_id, instance_id)
                ),
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
                after=point_map_instance_document(
                    self._require_point_map(version_id, instance_id)
                ),
                actor=actor,
            )
        return self.version(version_id)

    # -- point map source resolution ---------------------------------------------------------

    def validate_point_map_source(
        self, entry_id: uuid.UUID, attachment_id: uuid.UUID
    ) -> PointMapSourceBinding:
        """The source half of ``validate_point_map_placement``, before a placement exists.

        Runs the membership, permission, artifact, rung and byte checks add would run for this
        exact reference, in the same order and through the same resolver, and returns what a
        placement would pin. Read-only.
        """
        return self._resolve_point_map_source(entry_id, attachment_id)

    def _resolve_point_map_source(
        self, entry_id: uuid.UUID, attachment_id: uuid.UUID
    ) -> PointMapSourceBinding:
        """Membership, then permission, then the estimate. Each step raises its own refusal.

        The order is the order a person would ask the questions in, and it decides which sentence
        they read: a detached photograph is not "no estimate exists", and a stopped depth right is
        not "your review expired".
        """
        row = self.connection.execute(
            """
            select a.attachment_id,a.capture_id,a.source_sha256,a.authorization_id,a.screening_id,
                   a.attached_by,cur.attachment_id as current_attachment_id,
                   auth.corpus_class,auth.capture_id as authorized_capture_id,
                   auth.source_sha256 as authorized_sha256,auth.authorized_by,
                   auth.valid_until as authorization_valid_until,auth.evidence_digest,
                   p.capture_id as screened_capture_id,p.source_sha256 as screened_sha256,
                   p.authorization_id as screened_authorization_id,p.screening_method,
                   p.reviewed_by,p.eligibility_state,p.valid_until as screening_valid_until,
                   p.receipt_digest as screening_receipt_digest,
                   c.blob_sha256 as current_source_sha256,
                   asset_capture_live(a.workspace_id,a.capture_id,statement_timestamp())
                     as source_live,
                   statement_timestamp() as evaluated_at
              from saved_world_source_attachment a
              join saved_world_entry e
                on e.workspace_id=a.workspace_id and e.entry_id=a.entry_id
              left join saved_world_source_current_membership cur
                on cur.workspace_id=a.workspace_id and cur.entry_id=a.entry_id
               and cur.capture_id=a.capture_id
              join capture c on c.workspace_id=a.workspace_id and c.capture_id=a.capture_id
              join capture_reconstruction_authorization auth
                on auth.workspace_id=a.workspace_id and auth.authorization_id=a.authorization_id
              join reconstruction_privacy_screening p
                on p.workspace_id=a.workspace_id and p.screening_id=a.screening_id
             where a.workspace_id=%s and a.entry_id=%s and a.attachment_id=%s
               and e.world_id=%s
            """,
            (self.workspace_id, entry_id, attachment_id, self.world_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such attachment on a saved world of this world")
        if row["current_attachment_id"] != attachment_id:
            raise SourceNotCurrentMembership(
                "this photograph is not currently a reference of this world"
            )
        at = row["evaluated_at"]
        if (
            not row["source_live"]
            or row["current_source_sha256"] != row["source_sha256"]
            or row["authorized_capture_id"] != row["capture_id"]
            or row["authorized_sha256"] != row["source_sha256"]
            or row["corpus_class"] != "personal"
            or row["screened_capture_id"] != row["capture_id"]
            or row["screened_sha256"] != row["source_sha256"]
            or row["screened_authorization_id"] != row["authorization_id"]
            or row["screening_method"] != "human_review"
            or row["reviewed_by"] is None
            or row["eligibility_state"] != "eligible"
        ):
            raise UnknownWorldResource(
                "this reference's photograph, authority and review no longer agree"
            )
        if (
            row["authorization_valid_until"] is not None
            and row["authorization_valid_until"] <= at
        ) or (row["screening_valid_until"] is not None and row["screening_valid_until"] <= at):
            raise SourceAuthorityExpired(
                "this reference's authority or review has expired; review the photograph again"
            )
        right = self._current_depth_right(row["capture_id"], at)
        artifact = self._point_map_artifact(row, right)
        return PointMapSourceBinding(
            entry_id=entry_id,
            attachment_id=attachment_id,
            capture_id=row["capture_id"],
            source_sha256=bytes(row["source_sha256"]).hex(),
            authorization_id=row["authorization_id"],
            authorization_evidence_sha256=bytes(row["evidence_digest"]).hex(),
            screening_id=row["screening_id"],
            screening_receipt_sha256=bytes(row["screening_receipt_digest"]).hex(),
            right_id=right["right_id"],
            right_receipt_sha256=bytes(right["receipt_sha256"]).hex(),
            model=PointMapModel(
                provider=right["model_provider"],
                role=right["model_role"],
                identifier=right["model_id"],
                revision=right["model_revision"],
                destination=right["destination"],
            ),
            artifact_id=artifact["artifact_id"],
            point_map_sha256=bytes(artifact["content_sha256"]).hex(),
            byte_size=int(artifact["byte_size"]),
            container=POINT_MAP_CONTAINER,
            stage_version=int(artifact["stage_version"]),
            rung=int(artifact["rung"]),
            declared_metric=bool(artifact["declared_metric"]),
            declared_fov_y_microdegrees=int(artifact["fov_y_microdegrees"]),
        )

    def _current_depth_right(self, capture_id: uuid.UUID, at: Any) -> Mapping[str, Any]:
        """The newest depth right that stands for this photograph right now, or a refusal.

        A role, not a checkpoint: which checkpoint ran is a property of the estimate, and the
        estimate's own binding is checked against this right afterwards. Asking for a named
        checkpoint here would refuse a person who granted the right again after the pin moved.
        """
        row = self.connection.execute(
            "select right_id,model_provider,model_role,model_id,model_revision,destination,"
            "receipt_sha256 from personal_model_right r "
            "where r.workspace_id=%s and r.capture_id=%s and r.model_role=%s "
            "and personal_model_right_allows(r.workspace_id,r.right_id,r.capture_id,"
            "r.model_provider,r.model_role,r.model_id,r.model_revision,r.destination,%s) "
            "order by r.granted_at desc,r.right_id desc limit 1",
            (self.workspace_id, capture_id, DEPTH_ROLE, at),
        ).fetchone()
        if row is None:
            raise PointMapNotPermitted(
                "no current permission lets a 3D estimate from this photograph be used"
            )
        return row

    def _point_map_artifact(
        self, reference: Mapping[str, Any], right: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """The estimate for these exact bytes under the review this reference pins.

        The rung comes from the recorded assertion and NOT from the container, which is the one
        place those two disagree and it matters. ``encode_opm`` writes ``rung: 3`` as a format
        constant on every map it produces, including one the quality gate decided was rung 4, so a
        reader that trusted the header would place a handful of points and call it somebody's
        kitchen. What ``decide_rung`` measured is the assertion the depth stage recorded beside
        the artifact, and that is what is read here.

        The field of view and the metric flag come from the container, because those are what a
        renderer places the camera from; a second copy in a row could disagree with what is drawn.
        """
        row = self.connection.execute(
            """
            select a.artifact_id,a.content_sha256,a.byte_size,a.stage_version,
                   a.privacy_screening_id,
                   (s.object_value->>'rung')::int as rung,
                   asset_point_allows(a.workspace_id,a.artifact_id,statement_timestamp())
                     as readable,
                   exists(select 1 from point_map_model_right b
                          where b.workspace_id=a.workspace_id and b.artifact_id=a.artifact_id
                            and b.right_id=%(right)s) as bound
              from artifact a
              join assertion s on s.workspace_id=a.workspace_id and s.status='active'
               and s.object_value->>'point_map_artifact'=a.artifact_id::text
              join predicate pr on pr.predicate_id=s.predicate_id
               and pr.key='reconstruction_rung_is'
             where a.workspace_id=%(w)s and a.kind='point_map'
               and a.source_blob_sha256=%(source)s
               and a.purged_at is null and not a.needs_repair and a.superseded_by is null
               and a.content_sha256 is not null and a.byte_size is not null
             order by a.privacy_screening_id=%(screening)s desc,a.stage_version desc,
                      s.asserted_at desc,a.artifact_id
             limit 1
            """,
            {
                "w": self.workspace_id,
                "source": reference["source_sha256"],
                "screening": reference["screening_id"],
                "right": right["right_id"],
            },
        ).fetchone()
        if row is None:
            raise PointMapNotProduced("no 3D estimate has been made from this photograph yet")
        if row["privacy_screening_id"] != reference["screening_id"]:
            raise PointMapReviewDiffers(
                "the estimate for this photograph was made under a different review than this "
                "world's reference names"
            )
        if not row["bound"]:
            raise PointMapNotPermitted(
                "this estimate was not made under the permission that stands now"
            )
        if row["rung"] is None or int(row["rung"]) != PLACEABLE_RUNG:
            raise PointMapTooSparse(
                "too little of this photograph could be placed to stand in front of"
            )
        if not row["readable"]:
            raise PointMapNotReadable("this estimate may not be read right now")
        report = self._read_point_map(bytes(row["content_sha256"]))
        return {
            **row,
            "declared_metric": report.metric,
            "fov_y_microdegrees": round(report.fov_y_degrees * 1_000_000),
        }

    def _read_point_map(self, content_sha256: bytes) -> OpmIntegrityReport:
        """The stored container, validated. Refuses bytes a renderer would refuse anyway."""
        if self.store is None:
            raise UnavailableAsset("point map composition requires the content-addressed store")
        try:
            data = self.store.get(BlobId(content_sha256))
        except (BlobNotFoundError, IntegrityError, OSError) as exc:
            raise PointMapNotReadable(
                "this estimate's row survived and its stored bytes did not"
            ) from exc
        try:
            return validate_opm(data)
        except OpmIntegrityError as exc:
            raise PointMapNotReadable(f"this estimate's bytes are not placeable: {exc}") from exc

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
        """Ask again under the global asset read lock, after the row is written.

        The same discipline ``_final_environment_authorization`` follows and the same one
        ``require_model_right`` follows before a hand-over: a withdrawal cannot commit while this
        runs, so it is either seen here or it waits, and an edit that committed against a
        permission that ended mid-transaction cannot exist.
        """
        self.connection.execute("select asset_read_lock()")
        self._require_point_map_current(instance)

    def _require_point_map_current(self, instance: PointMapInstance) -> None:
        current = self._point_map_availability(instance)
        if current != "available":
            raise PointMapNotPermitted(
                f"this estimate cannot be used right now ({current})"
            )

    def _point_map_availability(self, instance: PointMapInstance) -> str:
        return self._point_map_state(instance)[0]

    def _point_map_state(self, instance: PointMapInstance) -> tuple[str, str | None]:
        """Why a placed estimate can or cannot be drawn, computed now and never stored.

        Every branch names a state a person can act on. ``withdrawn`` carries which end of
        permission it was, because a stopped right, an expired review, a deleted photograph and a
        withdrawn person are four different situations with four different recoveries.
        """
        source = instance.source
        row = self.connection.execute(
            """
            select personal_model_right_allows(%(w)s,r.right_id,r.capture_id,r.model_provider,
                     r.model_role,r.model_id,r.model_revision,r.destination,
                     statement_timestamp()) as right_stands,
                   r.withdrawn_at is not null as right_withdrawn,
                   asset_point_allows(%(w)s,%(artifact)s,statement_timestamp()) as readable,
                   asset_capture_live(%(w)s,%(capture)s,statement_timestamp()) as source_live,
                   (select c.deleted_at is null from capture c
                     where c.workspace_id=%(w)s and c.capture_id=%(capture)s) as capture_present,
                   asset_screening_allows(%(w)s,%(capture)s,%(screening)s,statement_timestamp())
                     as review_stands,
                   (select cur.attachment_id from saved_world_source_current_membership cur
                     where cur.workspace_id=%(w)s and cur.entry_id=%(entry)s
                       and cur.capture_id=%(capture)s) as current_attachment_id
              from personal_model_right r
             where r.workspace_id=%(w)s and r.right_id=%(right)s
            """,
            {
                "w": self.workspace_id,
                "right": source.right_id,
                "capture": source.capture_id,
                "artifact": source.artifact_id,
                "screening": source.screening_id,
                "entry": source.entry_id,
            },
        ).fetchone()
        if not row["capture_present"] or not row["source_live"]:
            return "withdrawn", "source_deleted"
        if row["right_withdrawn"] or not row["right_stands"]:
            return "withdrawn", "model_right_withdrawn"
        if not row["review_stands"]:
            return "withdrawn", "review_expired"
        if row["current_attachment_id"] != source.attachment_id:
            # DETACHED, and rebinding never brings this back. A later attachment is a new
            # membership under a new review, and the placement pins the one it was made through.
            return "detached", None
        if not row["readable"]:
            # The permission terms above all stood, so what is left is the bytes or a person
            # whose likeness was withdrawn from this derivative.
            return "unavailable_bytes", None
        if self.store is not None and not self.store.exists(
            BlobId.from_hex(source.point_map_sha256)
        ):
            return "unavailable_bytes", None
        return "available", None

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
            "select edit_id,edit_seq,kind,object_id,element_id,environment_instance_id,"
            "undone_edit_id,base_state_sha256,"
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
                environment_instance_id=r["environment_instance_id"],
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

    # -- environment source authorization ---------------------------------------------------

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
        return self._authorized_environment_source(
            admission_id, render_asset_id, publication_id, selection
        )

    def _resolve_environment_source(
        self,
        placement: EnvironmentPlacement,
        resolved: ResolvedEnvironmentSource | None = None,
    ) -> EnvironmentSourceBinding:
        if resolved is None:
            resolved = self._authorized_environment_source(
                placement.admission_id,
                placement.render_asset_id,
                placement.publication_id,
                placement.selection,
            )
        elif (
            resolved.admission_id,
            resolved.render_asset_id,
            resolved.publication_id,
            resolved.selection,
        ) != (
            placement.admission_id,
            placement.render_asset_id,
            placement.publication_id,
            placement.selection,
        ):
            raise ValueError("the resolved source names a different binding than the placement")
        row, publication, bounds = resolved.row, resolved.publication, resolved.bounds
        return EnvironmentSourceBinding(
            admission_id=placement.admission_id,
            render_asset_id=placement.render_asset_id,
            publication_id=None if publication is None else publication["publication_id"],
            source_sha256=bytes(row["source_sha256"]).hex(),
            source_receipt_sha256=bytes(row["source_receipt_sha256"]).hex(),
            render_sha256=bytes(row["render_sha256"]).hex(),
            render_receipt_sha256=bytes(row["render_receipt_sha256"]).hex(),
            index_sha256=(
                None if publication is None else bytes(publication["index_sha256"]).hex()
            ),
            index_receipt_sha256=(
                None if publication is None else bytes(publication["index_receipt_sha256"]).hex()
            ),
            publication_receipt_sha256=(
                None
                if publication is None
                else bytes(publication["publication_receipt_sha256"]).hex()
            ),
            place_id=row["place_id"],
            frame=row["geographic_frame"],
            bounds=bounds,
            anchor=placement.source_anchor,
            selection=placement.selection,
        )

    def _authorized_environment_source(
        self,
        admission_id: uuid.UUID,
        render_asset_id: uuid.UUID,
        publication_id: uuid.UUID | None,
        selection: EnvironmentSelection,
    ) -> ResolvedEnvironmentSource:
        if self.store is None:
            raise UnavailableAsset("environment composition requires the content-addressed store")
        row = self.connection.execute(
            """
            select s.place_id,s.source_sha256,s.receipt_sha256 as source_receipt_sha256,
                   s.withdrawn_at as source_withdrawn_at,
                   r.content_sha256 as render_sha256,r.receipt_sha256 as render_receipt_sha256,
                   s.geographic_frame,s.geographic_bounds,
                   r.withdrawn_at as render_withdrawn_at,
                   environment_resource_allows(
                     %s,'source',s.admission_id,'compose',statement_timestamp()) source_compose,
                   environment_resource_allows(
                     %s,'asset',r.asset_id,'compose',statement_timestamp()) render_compose
              from environment_source_admission s
              join derived_environment_asset r
                on r.workspace_id=s.workspace_id and r.admission_id=s.admission_id
             where s.workspace_id=%s and s.admission_id=%s and r.asset_id=%s
            """,
            (
                self.workspace_id,
                self.workspace_id,
                self.workspace_id,
                admission_id,
                render_asset_id,
            ),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such environment source and render binding")
        if row["source_withdrawn_at"] is not None or row["render_withdrawn_at"] is not None:
            raise EnvironmentSourceWithdrawn("the environment source or render asset is withdrawn")
        if not row["source_compose"] or not row["render_compose"]:
            raise EnvironmentCompositionDenied(
                "compose is not permitted for the source and render asset"
            )
        self._require_environment_bytes(row["source_sha256"], row["render_sha256"], None)

        bounds = row["geographic_bounds"]
        publication = None
        if selection.kind == "feature":
            publication = self._current_publication(
                admission_id,
                render_asset_id,
                publication_id,
                require_rights=True,
            )
            index = self._read_feature(publication, selection.feature_id, selection.render_batch_id)
            bounds = {
                "kind": "bbox",
                "frame_name": row["geographic_frame"]["name"],
                "coordinate_scale": row["geographic_bounds"]["coordinate_scale"],
                "coordinates": index["bbox"],
            }
        elif selection.kind != "whole_asset" or publication_id is not None:
            raise InvalidEnvironmentData("whole-asset placement cannot name a publication")

        return ResolvedEnvironmentSource(
            admission_id=admission_id,
            render_asset_id=render_asset_id,
            publication_id=publication_id,
            selection=selection,
            row=row,
            publication=publication,
            bounds=bounds,
        )

    def _current_publication(
        self,
        admission_id: uuid.UUID,
        render_asset_id: uuid.UUID,
        publication_id: uuid.UUID | None,
        *,
        require_rights: bool,
    ) -> Mapping[str, Any]:
        row = self.connection.execute(
            """
            select p.publication_id,p.admission_id,p.render_asset_id,
                   p.source_sha256,p.source_receipt_sha256,
                   p.render_sha256,p.render_receipt_sha256,p.index_sha256,
                   p.index_receipt_sha256,p.receipt_sha256 as publication_receipt_sha256,
                   p.index_asset_id,i.withdrawn_at as index_withdrawn_at,
                   s.place_id,s.geographic_frame,s.geographic_bounds,
                   (select newest.publication_id
                      from environment_feature_index_publication newest
                     where newest.workspace_id=p.workspace_id
                       and newest.admission_id=p.admission_id
                     order by newest.published_at desc,newest.publication_id desc limit 1)
                     as current_publication_id,
                   environment_resource_allows(
                     %s,'source',p.admission_id,'index',statement_timestamp()) source_index,
                   environment_resource_allows(
                     %s,'asset',p.render_asset_id,'index',statement_timestamp()) render_index,
                   environment_resource_allows(
                     %s,'asset',p.index_asset_id,'index',statement_timestamp()) index_index,
                   environment_resource_allows(
                     %s,'asset',p.index_asset_id,'compose',statement_timestamp()) index_compose
              from environment_feature_index_publication p
              join environment_source_admission s
                on s.workspace_id=p.workspace_id and s.admission_id=p.admission_id
              join derived_environment_asset i
                on i.workspace_id=p.workspace_id and i.asset_id=p.index_asset_id
             where p.workspace_id=%s and p.admission_id=%s and p.publication_id=%s
            """,
            (
                self.workspace_id,
                self.workspace_id,
                self.workspace_id,
                self.workspace_id,
                self.workspace_id,
                admission_id,
                publication_id,
            ),
        ).fetchone()
        if row is None or row["render_asset_id"] != render_asset_id:
            raise UnknownWorldResource("no such environment feature publication")
        if row["index_withdrawn_at"] is not None:
            raise EnvironmentSourceWithdrawn("the environment feature index is withdrawn")
        if row["publication_id"] != row["current_publication_id"]:
            raise EnvironmentBindingDrift("the named feature publication is no longer current")
        if require_rights and not all(
            row[key] for key in ("source_index", "render_index", "index_index", "index_compose")
        ):
            raise EnvironmentCompositionDenied(
                "feature placement requires index and compose rights on its exact binding"
            )
        return row

    def _read_feature(
        self,
        publication: Mapping[str, Any],
        feature_id: str | None,
        render_batch_id: int | None,
    ) -> Mapping[str, Any]:
        if self.store is None:
            raise UnavailableAsset("environment composition requires the content-addressed store")
        try:
            data = self.store.get(BlobId(bytes(publication["index_sha256"])))
            document = json.loads(data)
            payload = document["index"]
            if (
                (document.get("profile"), payload.get("profile"))
                not in (
                    (
                        "exulanica.environment-feature-index-envelope/v1",
                        "exulanica.environment-feature-index/v1",
                    ),
                    (
                        "exulanica.environment-feature-index-envelope/v2",
                        "exulanica.environment-feature-index/v2",
                    ),
                )
                or document.get("payload_sha256")
                != hashlib.sha256(canonical_json(payload)).hexdigest()
                or payload.get("admission_id") != str(publication["admission_id"])
                or payload.get("place_id") != str(publication["place_id"])
                or payload.get("source")
                != {
                    "content_sha256": bytes(publication["source_sha256"]).hex(),
                    "receipt_sha256": bytes(publication["source_receipt_sha256"]).hex(),
                }
                or payload.get("render_asset")
                != {
                    "asset_id": str(publication["render_asset_id"]),
                    "content_sha256": bytes(publication["render_sha256"]).hex(),
                    "receipt_sha256": bytes(publication["render_receipt_sha256"]).hex(),
                }
                or payload.get("geographic_frame") != publication["geographic_frame"]
                or payload.get("geographic_bounds") != publication["geographic_bounds"]
            ):
                raise IntegrityError("the pinned environment feature index binding is malformed")
            features = payload["features"]
        except BlobNotFoundError as exc:
            raise UnavailableAsset("the pinned environment index bytes are unavailable") from exc
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise IntegrityError("the pinned environment feature index is malformed") from exc
        matches = [
            feature
            for feature in features
            if isinstance(feature, dict) and feature.get("id") == feature_id
        ]
        if len(matches) != 1 or matches[0].get("render_batch_id") != render_batch_id:
            raise InvalidEnvironmentData(
                "the feature and render batch do not match the exact publication"
            )
        return matches[0]

    def _require_environment_bytes(
        self, source_sha256: bytes, render_sha256: bytes, index_sha256: bytes | None
    ) -> None:
        if self.store is None:
            raise UnavailableAsset("environment composition requires the content-addressed store")
        try:
            for digest in (source_sha256, render_sha256, index_sha256):
                if digest is not None:
                    self.store.get(BlobId(bytes(digest)))
        except BlobNotFoundError as exc:
            raise UnavailableAsset("the exact pinned environment bytes are unavailable") from exc

    def _require_pinned_environment_current(
        self,
        instance: EnvironmentInstance,
        *,
        require_bytes: bool,
        validate_feature_bytes: bool = True,
    ) -> None:
        source = instance.source
        row = self.connection.execute(
            """
            select s.place_id,s.source_sha256,s.receipt_sha256 as source_receipt_sha256,
                   s.withdrawn_at as source_withdrawn_at,
                   r.content_sha256 as render_sha256,r.receipt_sha256 as render_receipt_sha256,
                   s.geographic_frame,s.geographic_bounds,
                   r.withdrawn_at as render_withdrawn_at,
                   environment_resource_allows(
                     %s,'source',s.admission_id,'compose',statement_timestamp()) source_compose,
                   environment_resource_allows(
                     %s,'asset',r.asset_id,'compose',statement_timestamp()) render_compose
              from environment_source_admission s
              join derived_environment_asset r
                on r.workspace_id=s.workspace_id and r.admission_id=s.admission_id
             where s.workspace_id=%s and s.admission_id=%s and r.asset_id=%s
            """,
            (
                self.workspace_id,
                self.workspace_id,
                self.workspace_id,
                source.admission_id,
                source.render_asset_id,
            ),
        ).fetchone()
        if row is None:
            raise EnvironmentBindingDrift("the pinned environment binding no longer resolves")
        if row["source_withdrawn_at"] is not None or row["render_withdrawn_at"] is not None:
            raise EnvironmentSourceWithdrawn("the pinned environment source is withdrawn")
        if not row["source_compose"] or not row["render_compose"]:
            raise EnvironmentCompositionDenied("compose is no longer permitted")
        expected = (
            source.place_id,
            source.source_sha256,
            source.source_receipt_sha256,
            source.render_sha256,
            source.render_receipt_sha256,
            dict(source.frame),
            dict(source.bounds) if source.selection.kind == "whole_asset" else None,
        )
        actual = (
            row["place_id"],
            bytes(row["source_sha256"]).hex(),
            bytes(row["source_receipt_sha256"]).hex(),
            bytes(row["render_sha256"]).hex(),
            bytes(row["render_receipt_sha256"]).hex(),
            row["geographic_frame"],
            row["geographic_bounds"] if source.selection.kind == "whole_asset" else None,
        )
        if actual != expected:
            raise EnvironmentBindingDrift("the pinned environment source binding drifted")
        index_digest = None
        if source.publication_id is not None:
            publication = self._current_publication(
                source.admission_id,
                source.render_asset_id,
                source.publication_id,
                require_rights=True,
            )
            published = (
                bytes(publication["source_sha256"]).hex(),
                bytes(publication["source_receipt_sha256"]).hex(),
                bytes(publication["render_sha256"]).hex(),
                bytes(publication["render_receipt_sha256"]).hex(),
                bytes(publication["index_sha256"]).hex(),
                bytes(publication["index_receipt_sha256"]).hex(),
                bytes(publication["publication_receipt_sha256"]).hex(),
            )
            pinned = (
                source.source_sha256,
                source.source_receipt_sha256,
                source.render_sha256,
                source.render_receipt_sha256,
                source.index_sha256,
                source.index_receipt_sha256,
                source.publication_receipt_sha256,
            )
            if published != pinned:
                raise EnvironmentBindingDrift("the pinned feature publication binding drifted")
            if validate_feature_bytes:
                feature = self._read_feature(
                    publication,
                    source.selection.feature_id,
                    source.selection.render_batch_id,
                )
                feature_bounds = {
                    "kind": "bbox",
                    "frame_name": row["geographic_frame"]["name"],
                    "coordinate_scale": row["geographic_bounds"]["coordinate_scale"],
                    "coordinates": feature["bbox"],
                }
                if feature_bounds != dict(source.bounds):
                    raise EnvironmentBindingDrift("the pinned feature bounds drifted")
            index_digest = publication["index_sha256"]
        if require_bytes:
            self._require_environment_bytes(
                row["source_sha256"], row["render_sha256"], index_digest
            )

    def _final_environment_authorization(self, instance: EnvironmentInstance) -> None:
        self.connection.execute("select asset_read_lock()")
        self._require_pinned_environment_current(
            instance, require_bytes=False, validate_feature_bytes=False
        )

    def _environment_availability(self, instance: EnvironmentInstance) -> str:
        try:
            self._require_pinned_environment_current(instance, require_bytes=False)
        except EnvironmentSourceWithdrawn:
            return "withdrawn"
        except UnavailableAsset:
            return "unavailable_bytes"
        except (EnvironmentBindingDrift, EnvironmentCompositionDenied, UnknownWorldResource):
            return "binding_drift"
        if self.store is None:
            return "unknown"
        try:
            source = instance.source
            self._require_environment_bytes(
                bytes.fromhex(source.source_sha256),
                bytes.fromhex(source.render_sha256),
                None if source.index_sha256 is None else bytes.fromhex(source.index_sha256),
            )
        except UnavailableAsset:
            return "unavailable_bytes"
        return "available"

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
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s::text,%s))",
            (self.workspace_id, _WORKSPACE_LOCK_SEED),
        )


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
