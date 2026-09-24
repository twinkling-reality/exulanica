"""Workspace authority for reopening a personal world at a saved authored state and style."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Final, Literal

import psycopg

from exulanica.canonical import sha256_of_canonical
from exulanica.epistemics.source_images import selected_image
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.world.errors import InvalidStyleData, StaleStyleVersion, UnknownWorldResource
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.reviewed_sources import reviewed_personal_sources
from exulanica.world.source_membership_events import (
    DetachEvent,
    MembershipEventConflict,
    MembershipEventRefused,
    MembershipLedger,
    OperationKind,
    PinnedMembership,
    RecordedOperation,
    current_memberships,
    detach_request_sha256,
    rebind_request_sha256,
    require_detachable,
    require_rebindable,
)
from exulanica.world.style_structure import (
    AuthoredVersionRef,
    CompatibilityIntent,
    StructuralSnapshotRef,
    StyleVersionRef,
    raise_for_incompatible_structure_style,
)
from exulanica.world.worlds import AUTHORED_STARTER, new_world_id

__all__ = [
    "SavedWorldCandidate",
    "SavedWorldEntry",
    "SavedWorldEntryRepository",
    "SavedWorldPreviousSourceAttachment",
    "SavedWorldSourceAttachment",
    "SourceAttachmentOperationConflict",
    "SourceAttachmentSelection",
    "SourceRebindRequired",
    "StaleSavedWorldEntry",
]

_WORKSPACE_LOCK_SEED: Final = 880_024


class StaleSavedWorldEntry(Exception):
    """The caller tried to replace an entry revision it did not read."""


class SourceAttachmentOperationConflict(Exception):
    """An attachment operation id was reused for a different exact request."""


class SourceRebindRequired(Exception):
    """Attach named a photograph this world used before; adding it back is a rebind."""


@dataclass(frozen=True, slots=True)
class SourceAttachmentSelection:
    capture_id: uuid.UUID
    evidence_span_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class SavedWorldSourceAttachment:
    attachment_id: uuid.UUID
    operation_id: uuid.UUID
    capture_id: uuid.UUID
    evidence_span_id: uuid.UUID
    source_sha256: str
    authorization_id: uuid.UUID
    screening_id: uuid.UUID
    role: Literal["reference"]
    attached_entry_revision: int
    attached_by: uuid.UUID
    attached_at: dt.datetime
    availability: Literal["available", "unavailable"]
    unavailable_reason: str | None
    viewer_sha256: str | None
    evidence_path: str | None


@dataclass(frozen=True, slots=True)
class SavedWorldPreviousSourceAttachment:
    """A photograph removed from this world: its last membership and the detach that ended it.

    ``availability`` says whether the original photograph is still a live source in the
    library, not whether the world may use it. Using it again is a rebind after a new review.
    """

    attachment_id: uuid.UUID
    operation_id: uuid.UUID
    capture_id: uuid.UUID
    evidence_span_id: uuid.UUID
    source_sha256: str
    authorization_id: uuid.UUID
    screening_id: uuid.UUID
    attached_entry_revision: int
    attached_at: dt.datetime
    detach_operation_id: uuid.UUID
    detached_entry_revision: int
    detached_by: uuid.UUID
    detached_at: dt.datetime
    availability: Literal["available", "unavailable"]
    unavailable_reason: Literal["source_unavailable"] | None


@dataclass(frozen=True, slots=True)
class SavedWorldStyleCandidate:
    version_id: uuid.UUID
    revision: int


@dataclass(frozen=True, slots=True)
class SavedWorldCandidate:
    world_id: str
    authored_version_id: uuid.UUID
    title: str
    source_invalidated: bool
    styles: tuple[SavedWorldStyleCandidate, ...]


@dataclass(frozen=True, slots=True)
class SavedWorldEntry:
    entry_id: uuid.UUID
    world_id: str
    title: str
    source_kind: Literal["personal", "authored"]
    source_snapshot_id: uuid.UUID
    source_snapshot_sha256: str
    authored_scene: object | None
    authored_version_id: uuid.UUID
    authored_state_sha256: str
    authored_edit_seq: int
    current_authored_state_sha256: str
    current_authored_edit_seq: int
    style_version_id: uuid.UUID
    revision: int
    availability: Literal["available", "unavailable"]
    unavailable_reason: str | None
    source_attachments: tuple[SavedWorldSourceAttachment, ...]
    previous_source_attachments: tuple[SavedWorldPreviousSourceAttachment, ...]
    created_by: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime


class SavedWorldEntryRepository:
    """Read and update saved entries through one workspace-scoped connection."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        store: ContentAddressedStore | None = None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.store = store

    def entries(self) -> tuple[SavedWorldEntry, ...]:
        rows = self.connection.execute(
            self._select() + " order by e.updated_at desc, e.entry_id",
            (self.workspace_id,),
        ).fetchall()
        return tuple(self._entry(row) for row in rows)

    def candidates(self) -> tuple[SavedWorldCandidate, ...]:
        rows = self.connection.execute(
            "select v.world_id,v.version_id,v.title,"
            "exists(select 1 from world_structure_invalidation i "
            "where i.workspace_id=v.workspace_id and i.world_id=v.world_id "
            "and i.snapshot_id=v.source_snapshot_id) as source_invalidated "
            "from world_alternate_version v "
            "left join saved_world_entry e on e.workspace_id=v.workspace_id "
            "and e.world_id=v.world_id "
            "where v.workspace_id=%s and e.entry_id is null "
            "order by v.world_id,v.created_at,v.version_id",
            (self.workspace_id,),
        ).fetchall()
        styles_by_world: dict[str, tuple[SavedWorldStyleCandidate, ...]] = {}
        for world_id in {row["world_id"] for row in rows}:
            styles = self.connection.execute(
                "select version_id,revision from world_style_version "
                "where workspace_id=%s and world_id=%s order by revision,version_id",
                (self.workspace_id, world_id),
            ).fetchall()
            styles_by_world[world_id] = tuple(
                SavedWorldStyleCandidate(row["version_id"], row["revision"]) for row in styles
            )
        return tuple(
            SavedWorldCandidate(
                world_id=row["world_id"],
                authored_version_id=row["version_id"],
                title=row["title"],
                source_invalidated=row["source_invalidated"],
                styles=styles_by_world[row["world_id"]],
            )
            for row in rows
        )

    def citable_references(self, world_id: str) -> tuple[SavedWorldSourceAttachment, ...]:
        """The reference photographs a world uses now and may show, each available right now.

        The world's saved entry's current collection, every membership evaluated at this
        statement under the authorization and screening it pinned, exactly as an entry read
        reports it. A detached photograph, one whose pinned review or authorization expired, one
        whose source was deleted or withdrawn, and one with no viewer bytes in ``store`` are not
        among them. A world with no saved entry has none.
        """
        row = self.connection.execute(
            "select entry_id from saved_world_entry where workspace_id=%s and world_id=%s",
            (self.workspace_id, world_id),
        ).fetchone()
        if row is None:
            return ()
        return tuple(
            attachment
            for attachment in self._attachments(row["entry_id"])
            if attachment.availability == "available"
        )

    def entry(self, entry_id: uuid.UUID) -> SavedWorldEntry:
        row = self.connection.execute(
            self._select() + " and e.entry_id=%s",
            (self.workspace_id, entry_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such saved world entry")
        return self._entry(row)

    def create(
        self,
        *,
        world_id: str,
        title: str,
        authored_version_id: uuid.UUID,
        style_version_id: uuid.UUID,
        created_by: uuid.UUID,
        source_kind: Literal["personal", "authored"] = "personal",
    ) -> SavedWorldEntry:
        clean_world_id = world_id.strip()
        clean_title = title.strip()
        if not 1 <= len(clean_world_id) <= 200:
            raise ValueError("world_id must contain between 1 and 200 characters")
        if not 1 <= len(clean_title) <= 200:
            raise ValueError("title must contain between 1 and 200 characters")
        try:
            with self.connection.transaction():
                self._lock_workspace()
                authored = self._require_versions(
                    clean_world_id,
                    authored_version_id,
                    style_version_id,
                    lock_authored=True,
                )
                self._require_entry_origin(source_kind, authored)
                row = self.connection.execute(
                    "insert into saved_world_entry "
                    "(workspace_id,world_id,title,source_kind,authored_version_id,"
                    "authored_state_sha256,authored_edit_seq,style_version_id,created_by) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning entry_id",
                    (
                        self.workspace_id,
                        clean_world_id,
                        clean_title,
                        source_kind,
                        authored_version_id,
                        authored["state_sha256"],
                        authored["edit_seq"],
                        style_version_id,
                        created_by,
                    ),
                ).fetchone()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("this world already has a saved entry") from exc
        assert row is not None
        return self.entry(row["entry_id"])

    def create_starter(self, *, title: str, created_by: uuid.UUID) -> SavedWorldEntry:
        """Atomically create or return this workspace's one controlled authored starter."""

        clean_title = title.strip()
        if not 1 <= len(clean_title) <= 200:
            raise ValueError("title must contain between 1 and 200 characters")
        with self.connection.transaction():
            self._lock_workspace()
            existing = self.entries()
            if existing:
                if (
                    len(existing) == 1
                    and existing[0].source_kind == "authored"
                    and existing[0].availability == "available"
                ):
                    if existing[0].title == clean_title:
                        # A retry never renames or adopts a newer cursor. Explicit PUT remains the
                        # only rename/update authority.
                        return existing[0]
                    raise ValueError("the authored starter already exists under a different title")
                raise ValueError("the workspace already has a different saved world entry")

            from exulanica.world.starter import create_starter_authorities

            world_id = new_world_id(AUTHORED_STARTER)
            _, style, authored_version_id = create_starter_authorities(
                self.connection,
                workspace_id=self.workspace_id,
                actor=created_by,
                title=clean_title,
                world_id=world_id,
            )
            return self.create(
                world_id=world_id,
                title=clean_title,
                authored_version_id=authored_version_id,
                style_version_id=style.version_id,
                created_by=created_by,
                source_kind="authored",
            )

    def update(
        self,
        entry_id: uuid.UUID,
        *,
        base_revision: int,
        authored_version_id: uuid.UUID,
        expected_authored_state_sha256: str,
        expected_authored_edit_seq: int,
        style_version_id: uuid.UUID,
        title: str | None = None,
    ) -> SavedWorldEntry:
        with self.connection.transaction():
            self._lock_workspace()
            row = self.connection.execute(
                "select world_id,revision,title,source_kind from saved_world_entry "
                "where workspace_id=%s and entry_id=%s for update",
                (self.workspace_id, entry_id),
            ).fetchone()
            if row is None:
                raise UnknownWorldResource("no such saved world entry")
            if row["revision"] != base_revision:
                raise StaleSavedWorldEntry(
                    f"entry targets revision {base_revision}; current revision is {row['revision']}"
                )
            clean_title = row["title"] if title is None else title.strip()
            if not 1 <= len(clean_title) <= 200:
                raise ValueError("title must contain between 1 and 200 characters")
            authored = self._require_versions(
                row["world_id"],
                authored_version_id,
                style_version_id,
                expected_authored_state_sha256=expected_authored_state_sha256,
                expected_authored_edit_seq=expected_authored_edit_seq,
                lock_authored=True,
            )
            self._require_entry_origin(str(row["source_kind"]), authored)
            self.connection.execute(
                "update saved_world_entry set title=%s,authored_version_id=%s,"
                "authored_state_sha256=%s,authored_edit_seq=%s,style_version_id=%s,"
                "revision=revision+1,updated_at=now() "
                "where workspace_id=%s and entry_id=%s",
                (
                    clean_title,
                    authored_version_id,
                    expected_authored_state_sha256,
                    expected_authored_edit_seq,
                    style_version_id,
                    self.workspace_id,
                    entry_id,
                ),
            )
        return self.entry(entry_id)

    def attach_sources(
        self,
        entry_id: uuid.UUID,
        *,
        operation_id: uuid.UUID,
        base_revision: int,
        authored_version_id: uuid.UUID,
        authored_state_sha256: str,
        authored_edit_seq: int,
        style_version_id: uuid.UUID,
        sources: tuple[SourceAttachmentSelection, ...],
        attached_by: uuid.UUID,
    ) -> SavedWorldEntry:
        """Append exact reviewed references while preserving the complete saved scene cursor.

        A later authorization or screening receipt is not a rebind. A photograph this world
        already uses is refused, including after its pinned receipts expire, and a photograph
        removed from this world is refused with :class:`SourceRebindRequired`: adding it back is
        a rebind after a new human review.
        """

        if not 1 <= len(sources) <= 200:
            raise ValueError("attach between 1 and 200 source photographs")
        identities = [(source.capture_id, source.evidence_span_id) for source in sources]
        if len(set(identities)) != len(identities):
            raise ValueError("each source photograph and evidence span must be unique")
        if len({source.capture_id for source in sources}) != len(sources):
            raise ValueError("a capture can be attached only once in one operation")
        # Unchanged from migration 0086, so a retry of an attachment recorded before 0090 still
        # matches its stored digest.
        request_sha256 = sha256_of_canonical(
            {
                "entry_id": str(entry_id),
                "operation_id": str(operation_id),
                "base_revision": base_revision,
                "authored_version_id": str(authored_version_id),
                "authored_state_sha256": authored_state_sha256,
                "authored_edit_seq": authored_edit_seq,
                "style_version_id": str(style_version_id),
                "sources": [
                    {
                        "capture_id": str(source.capture_id),
                        "evidence_span_id": str(source.evidence_span_id),
                    }
                    for source in sources
                ],
                "attached_by": str(attached_by),
            }
        )
        with self.connection.transaction():
            self._lock_workspace()
            self._lock_entry(entry_id)
            if self._recorded_operation(
                operation_id,
                kind="attach",
                entry_id=entry_id,
                request_sha256=request_sha256,
                conflict=SourceAttachmentOperationConflict(
                    "operation_id already names a different source attachment request"
                ),
            ):
                return self.entry(entry_id)
            self._require_attachable_cursor(
                entry_id,
                base_revision=base_revision,
                authored_version_id=authored_version_id,
                authored_state_sha256=authored_state_sha256,
                authored_edit_seq=authored_edit_seq,
                style_version_id=style_version_id,
                action="attached",
            )
            membership = self._membership_state(entry_id, [source.capture_id for source in sources])
            if any(state == "current" for state in membership.values()):
                raise ValueError("a selected photograph is already attached to this saved world")
            if membership:
                raise SourceRebindRequired(
                    "a selected photograph was removed from this saved world; "
                    "add it back after a new review instead of attaching it again"
                )
            resolved = [self._resolve_attachment(source, attached_by) for source in sources]
            self._insert_attachment_operation(
                entry_id,
                operation_id=operation_id,
                kind="attach",
                request_sha256=request_sha256,
                base_revision=base_revision,
                authored_version_id=authored_version_id,
                authored_state_sha256=authored_state_sha256,
                authored_edit_seq=authored_edit_seq,
                style_version_id=style_version_id,
                actor=attached_by,
                conflict=SourceAttachmentOperationConflict(
                    "operation_id already names a different source attachment request"
                ),
            )
            for source, authority in zip(sources, resolved, strict=True):
                self._insert_attachment(
                    entry_id,
                    operation_id=operation_id,
                    source=source,
                    authority=authority,
                    result_revision=base_revision + 1,
                    actor=attached_by,
                )
            self._advance_revision(entry_id, base_revision, action="attached")
        return self.entry(entry_id)

    def detach_sources(
        self,
        entry_id: uuid.UUID,
        *,
        operation_id: uuid.UUID,
        base_revision: int,
        authored_version_id: uuid.UUID,
        authored_state_sha256: str,
        authored_edit_seq: int,
        style_version_id: uuid.UUID,
        attachment_ids: tuple[uuid.UUID, ...],
        detached_by: uuid.UUID,
    ) -> SavedWorldEntry:
        """Remove references from this world's current collection. Deletes no row and no media.

        The caller proves which resume point it saw: the entry revision and the saved cursor it
        read. The live authored branch and the world's availability are not consulted. A detach
        reads and writes no scene, style or snapshot, so it cannot adopt unseen state, and a
        world whose branch drifted or whose source was deleted can still stop using a photograph.
        Pinned receipts are not consulted either: removing an expired or deleted reference is
        allowed, because detach only reduces use.
        """

        if not 1 <= len(attachment_ids) <= 200:
            raise MembershipEventRefused(
                "invalid_detach", "remove between 1 and 200 reference photographs"
            )
        request_sha256 = detach_request_sha256(
            entry_id=entry_id,
            operation_id=operation_id,
            base_revision=base_revision,
            authored_version_id=authored_version_id,
            authored_state_sha256=authored_state_sha256,
            authored_edit_seq=authored_edit_seq,
            style_version_id=style_version_id,
            attachment_ids=attachment_ids,
            actor=detached_by,
        )
        with self.connection.transaction():
            self._lock_workspace()
            saved = self._lock_entry(entry_id)
            if self._recorded_operation(
                operation_id,
                kind="detach",
                entry_id=entry_id,
                request_sha256=request_sha256,
                conflict=MembershipEventConflict(
                    "operation_id already names a different reference membership request"
                ),
            ):
                return self.entry(entry_id)
            if (
                saved["revision"] != base_revision
                or saved["authored_version_id"] != authored_version_id
                or saved["authored_state_sha256"] != authored_state_sha256
                or saved["authored_edit_seq"] != authored_edit_seq
                or saved["style_version_id"] != style_version_id
            ):
                raise StaleSavedWorldEntry(
                    "the saved world resume point changed before its sources were removed"
                )
            members = require_detachable(self.membership_ledger(entry_id), attachment_ids)
            try:
                self.connection.execute(
                    "insert into saved_world_source_detach_operation "
                    "(workspace_id,operation_id,entry_id,request_sha256,base_entry_revision,"
                    "result_entry_revision,authored_version_id,authored_state_sha256,"
                    "authored_edit_seq,style_version_id,created_by) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.workspace_id,
                        operation_id,
                        entry_id,
                        request_sha256,
                        base_revision,
                        base_revision + 1,
                        authored_version_id,
                        authored_state_sha256,
                        authored_edit_seq,
                        style_version_id,
                        detached_by,
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise MembershipEventConflict(
                    "operation_id already names a different reference membership request"
                ) from exc
            for member in members:
                self.connection.execute(
                    "insert into saved_world_source_detach "
                    "(workspace_id,entry_id,operation_id,attachment_id,capture_id,"
                    "detached_entry_revision,detached_by) values (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.workspace_id,
                        entry_id,
                        operation_id,
                        member.attachment_id,
                        member.capture_id,
                        base_revision + 1,
                        detached_by,
                    ),
                )
            self._advance_revision(entry_id, base_revision, action="removed")
        return self.entry(entry_id)

    def rebind_sources(
        self,
        entry_id: uuid.UUID,
        *,
        operation_id: uuid.UUID,
        base_revision: int,
        authored_version_id: uuid.UUID,
        authored_state_sha256: str,
        authored_edit_seq: int,
        style_version_id: uuid.UUID,
        sources: tuple[SourceAttachmentSelection, ...],
        rebound_by: uuid.UUID,
    ) -> SavedWorldEntry:
        """Add removed photographs back to this world under a new human review.

        Attach-shaped: the complete cursor and the live authored branch must match, the world
        must be available, and each photograph's newest current review is resolved and pinned.
        That review must be one no earlier membership of the photograph on this world pinned.
        Historical rows keep their receipts; the new membership is a new row.
        """

        if not 1 <= len(sources) <= 200:
            raise MembershipEventRefused(
                "invalid_rebind", "add back between 1 and 200 reference photographs"
            )
        identities = [(source.capture_id, source.evidence_span_id) for source in sources]
        if len({source.capture_id for source in sources}) != len(sources):
            raise MembershipEventRefused(
                "invalid_rebind", "each photograph can be added back once per request"
            )
        request_sha256 = rebind_request_sha256(
            entry_id=entry_id,
            operation_id=operation_id,
            base_revision=base_revision,
            authored_version_id=authored_version_id,
            authored_state_sha256=authored_state_sha256,
            authored_edit_seq=authored_edit_seq,
            style_version_id=style_version_id,
            sources=identities,
            actor=rebound_by,
        )
        with self.connection.transaction():
            self._lock_workspace()
            self._lock_entry(entry_id)
            if self._recorded_operation(
                operation_id,
                kind="rebind",
                entry_id=entry_id,
                request_sha256=request_sha256,
                conflict=MembershipEventConflict(
                    "operation_id already names a different reference membership request"
                ),
            ):
                return self.entry(entry_id)
            self._require_attachable_cursor(
                entry_id,
                base_revision=base_revision,
                authored_version_id=authored_version_id,
                authored_state_sha256=authored_state_sha256,
                authored_edit_seq=authored_edit_seq,
                style_version_id=style_version_id,
                action="added back",
            )
            ledger = self.membership_ledger(entry_id)
            known = {member.capture_id for member in ledger.memberships}
            current = {member.capture_id for member in current_memberships(ledger)}
            resolved = []
            for source in sources:
                # Membership before authority, so a photograph still in the world, or never in
                # it, is not reported as needing review.
                if source.capture_id not in known:
                    raise MembershipEventRefused(
                        "membership_unavailable",
                        "this photograph was never part of this world; attach it instead",
                    )
                if source.capture_id in current:
                    raise MembershipEventRefused(
                        "membership_current", "this photograph is already part of this world"
                    )
                try:
                    authority = self._resolve_attachment(source, rebound_by)
                except ValueError as exc:
                    raise MembershipEventRefused("authority_unavailable", str(exc)) from exc
                require_rebindable(
                    ledger,
                    source.capture_id,
                    authorization_id=authority["authorization_id"],
                    screening_id=authority["screening_id"],
                    authorized_at=authority["authorized_at"],
                    screened_at=authority["screened_at"],
                )
                resolved.append(authority)
            self._insert_attachment_operation(
                entry_id,
                operation_id=operation_id,
                kind="rebind",
                request_sha256=request_sha256,
                base_revision=base_revision,
                authored_version_id=authored_version_id,
                authored_state_sha256=authored_state_sha256,
                authored_edit_seq=authored_edit_seq,
                style_version_id=style_version_id,
                actor=rebound_by,
                conflict=MembershipEventConflict(
                    "operation_id already names a different reference membership request"
                ),
            )
            for source, authority in zip(sources, resolved, strict=True):
                self._insert_attachment(
                    entry_id,
                    operation_id=operation_id,
                    source=source,
                    authority=authority,
                    result_revision=base_revision + 1,
                    actor=rebound_by,
                )
            self._advance_revision(entry_id, base_revision, action="added back")
        return self.entry(entry_id)

    def membership_ledger(self, entry_id: uuid.UUID) -> MembershipLedger:
        """This world's complete reference history: every membership, detach and operation."""

        entry = self.connection.execute(
            "select revision from saved_world_entry where workspace_id=%s and entry_id=%s",
            (self.workspace_id, entry_id),
        ).fetchone()
        if entry is None:
            raise UnknownWorldResource("no such saved world entry")
        memberships = tuple(
            PinnedMembership(
                attachment_id=row["attachment_id"],
                operation_id=row["operation_id"],
                kind=row["kind"],
                capture_id=row["capture_id"],
                evidence_span_id=row["evidence_span_id"],
                source_sha256=bytes(row["source_sha256"]).hex(),
                authorization_id=row["authorization_id"],
                screening_id=row["screening_id"],
                attached_entry_revision=row["attached_entry_revision"],
                attached_by=row["attached_by"],
                attached_at=row["attached_at"],
            )
            for row in self.connection.execute(
                "select a.attachment_id,a.operation_id,o.kind,a.capture_id,a.evidence_span_id,"
                "a.source_sha256,a.authorization_id,a.screening_id,a.attached_entry_revision,"
                "a.attached_by,a.attached_at from saved_world_source_attachment a "
                "join saved_world_source_attachment_operation o "
                "on o.workspace_id=a.workspace_id and o.operation_id=a.operation_id "
                "where a.workspace_id=%s and a.entry_id=%s "
                "order by a.attached_entry_revision,a.attachment_id",
                (self.workspace_id, entry_id),
            ).fetchall()
        )
        detach_events = tuple(
            DetachEvent(
                operation_id=row["operation_id"],
                attachment_id=row["attachment_id"],
                capture_id=row["capture_id"],
                detached_entry_revision=row["detached_entry_revision"],
                detached_by=row["detached_by"],
                detached_at=row["detached_at"],
            )
            for row in self.connection.execute(
                "select operation_id,attachment_id,capture_id,detached_entry_revision,"
                "detached_by,detached_at from saved_world_source_detach "
                "where workspace_id=%s and entry_id=%s "
                "order by detached_entry_revision,detach_id",
                (self.workspace_id, entry_id),
            ).fetchall()
        )
        operations = tuple(
            RecordedOperation(
                operation_id=row["operation_id"],
                kind=row["kind"],
                request_sha256=bytes(row["request_sha256"]),
                base_entry_revision=row["base_entry_revision"],
                result_entry_revision=row["result_entry_revision"],
            )
            for row in self.connection.execute(
                "select operation_id,kind,request_sha256,base_entry_revision,"
                "result_entry_revision from saved_world_source_attachment_operation "
                "where workspace_id=%s and entry_id=%s "
                "union all select operation_id,'detach',request_sha256,base_entry_revision,"
                "result_entry_revision from saved_world_source_detach_operation "
                "where workspace_id=%s and entry_id=%s "
                "order by result_entry_revision,operation_id",
                (self.workspace_id, entry_id, self.workspace_id, entry_id),
            ).fetchall()
        )
        return MembershipLedger(
            entry_id=entry_id,
            revision=entry["revision"],
            memberships=memberships,
            detach_events=detach_events,
            operations=operations,
        )

    def _lock_entry(self, entry_id: uuid.UUID) -> dict[str, object]:
        row = self.connection.execute(
            "select world_id,revision,authored_version_id,authored_state_sha256,"
            "authored_edit_seq,style_version_id from saved_world_entry "
            "where workspace_id=%s and entry_id=%s for update",
            (self.workspace_id, entry_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such saved world entry")
        return row

    def _recorded_operation(
        self,
        operation_id: uuid.UUID,
        *,
        kind: OperationKind,
        entry_id: uuid.UUID,
        request_sha256: bytes,
        conflict: Exception,
    ) -> bool:
        """Whether this exact request is already recorded; raise ``conflict`` for any other use.

        Looked up before any cursor or authority check, so an exact retry returns the recorded
        result after the world moved on, a newer review arrived, or the pinned review expired.
        An identity names one request in one workspace whatever its kind or saved world.
        """

        row = self.connection.execute(
            "select kind,entry_id,request_sha256 from saved_world_source_attachment_operation "
            "where workspace_id=%s and operation_id=%s "
            "union all select 'detach',entry_id,request_sha256 "
            "from saved_world_source_detach_operation "
            "where workspace_id=%s and operation_id=%s",
            (self.workspace_id, operation_id, self.workspace_id, operation_id),
        ).fetchone()
        if row is None:
            return False
        if (
            row["kind"] != kind
            or row["entry_id"] != entry_id
            or bytes(row["request_sha256"]) != request_sha256
        ):
            raise conflict
        return True

    def _require_attachable_cursor(
        self,
        entry_id: uuid.UUID,
        *,
        base_revision: int,
        authored_version_id: uuid.UUID,
        authored_state_sha256: str,
        authored_edit_seq: int,
        style_version_id: uuid.UUID,
        action: str,
    ) -> str:
        """The exact saved cursor, the live authored branch and an available world; locks both."""

        row = self.connection.execute(
            "select e.world_id,e.revision,e.authored_version_id,e.authored_state_sha256,"
            "e.authored_edit_seq,e.style_version_id,"
            "exists(select 1 from world_structure_invalidation i "
            "join world_alternate_version v on v.workspace_id=e.workspace_id "
            "and v.world_id=e.world_id and v.version_id=e.authored_version_id "
            "where i.workspace_id=e.workspace_id and i.world_id=e.world_id "
            "and i.snapshot_id=v.source_snapshot_id) as source_invalidated "
            "from saved_world_entry e where e.workspace_id=%s and e.entry_id=%s",
            (self.workspace_id, entry_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such saved world entry")
        if not (
            row["revision"] == base_revision
            and row["authored_version_id"] == authored_version_id
            and row["authored_state_sha256"] == authored_state_sha256
            and row["authored_edit_seq"] == authored_edit_seq
            and row["style_version_id"] == style_version_id
        ):
            raise StaleSavedWorldEntry(
                f"the saved world resume point changed before its sources were {action}"
            )
        if row["source_invalidated"]:
            if action == "attached":
                raise ValueError("sources cannot be attached to an unavailable saved world")
            raise MembershipEventRefused(
                "entry_unavailable", f"sources cannot be {action} on an unavailable saved world"
            )
        authored = self.connection.execute(
            "select state_sha256,edit_seq,source_snapshot_id from world_alternate_version "
            "where workspace_id=%s and world_id=%s and version_id=%s for update",
            (self.workspace_id, row["world_id"], authored_version_id),
        ).fetchone()
        if authored is None:
            raise UnknownWorldResource("no such authored world version")
        if (
            authored["state_sha256"] != authored_state_sha256
            or authored["edit_seq"] != authored_edit_seq
        ):
            raise StaleSavedWorldEntry(
                f"the authored world changed before its sources were {action}"
            )
        style = self.connection.execute(
            "select 1 from world_style_version where workspace_id=%s and world_id=%s "
            "and version_id=%s for update",
            (self.workspace_id, row["world_id"], style_version_id),
        ).fetchone()
        if style is None:
            raise UnknownWorldResource("no such world style version")
        try:
            raise_for_incompatible_structure_style(
                WorldStyleRepository(
                    self.connection, self.workspace_id, world_id=row["world_id"]
                ).classify_structure_style_compatibility(
                    intent=CompatibilityIntent.ATTACH,
                    style=StyleVersionRef(style_version_id),
                    authored=AuthoredVersionRef(authored_version_id),
                    snapshot=StructuralSnapshotRef(authored["source_snapshot_id"]),
                )
            )
        except InvalidStyleData as exc:
            raise ValueError(str(exc)) from exc
        return str(row["world_id"])

    def _membership_state(
        self, entry_id: uuid.UUID, capture_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Literal["current", "removed"]]:
        rows = self.connection.execute(
            "select capture_id,attachment_id from saved_world_source_current_membership "
            "where workspace_id=%s and entry_id=%s and capture_id=any(%s)",
            (self.workspace_id, entry_id, capture_ids),
        ).fetchall()
        return {
            row["capture_id"]: "current" if row["attachment_id"] is not None else "removed"
            for row in rows
        }

    def _insert_attachment_operation(
        self,
        entry_id: uuid.UUID,
        *,
        operation_id: uuid.UUID,
        kind: Literal["attach", "rebind"],
        request_sha256: bytes,
        base_revision: int,
        authored_version_id: uuid.UUID,
        authored_state_sha256: str,
        authored_edit_seq: int,
        style_version_id: uuid.UUID,
        actor: uuid.UUID,
        conflict: Exception,
    ) -> None:
        try:
            self.connection.execute(
                "insert into saved_world_source_attachment_operation "
                "(workspace_id,operation_id,entry_id,kind,request_sha256,base_entry_revision,"
                "result_entry_revision,authored_version_id,authored_state_sha256,"
                "authored_edit_seq,style_version_id,created_by) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    operation_id,
                    entry_id,
                    kind,
                    request_sha256,
                    base_revision,
                    base_revision + 1,
                    authored_version_id,
                    authored_state_sha256,
                    authored_edit_seq,
                    style_version_id,
                    actor,
                ),
            )
        except psycopg.errors.UniqueViolation as exc:
            raise conflict from exc

    def _insert_attachment(
        self,
        entry_id: uuid.UUID,
        *,
        operation_id: uuid.UUID,
        source: SourceAttachmentSelection,
        authority: dict[str, object],
        result_revision: int,
        actor: uuid.UUID,
    ) -> None:
        # The attachment identity is the table's uuidv7 default. The insert trigger moves the
        # current-membership pointer; nothing here writes it.
        self.connection.execute(
            "insert into saved_world_source_attachment "
            "(workspace_id,entry_id,operation_id,capture_id,evidence_span_id,"
            "source_sha256,authorization_id,screening_id,attached_entry_revision,"
            "attached_by) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                entry_id,
                operation_id,
                source.capture_id,
                source.evidence_span_id,
                authority["source_sha256"],
                authority["authorization_id"],
                authority["screening_id"],
                result_revision,
                actor,
            ),
        )

    def _advance_revision(self, entry_id: uuid.UUID, base_revision: int, *, action: str) -> None:
        updated = self.connection.execute(
            "update saved_world_entry set revision=revision+1,updated_at=now() "
            "where workspace_id=%s and entry_id=%s and revision=%s returning entry_id",
            (self.workspace_id, entry_id, base_revision),
        ).fetchone()
        if updated is None:
            raise StaleSavedWorldEntry(
                f"the saved world resume point changed before its sources were {action}"
            )

    def _resolve_attachment(
        self, source: SourceAttachmentSelection, attached_by: uuid.UUID
    ) -> dict[str, object]:
        """The review and authorization to pin, by the one rule every world writer reads."""
        found = reviewed_personal_sources(
            self.connection,
            self.workspace_id,
            reviewed_for=attached_by,
            store=self.store,
            capture_id=source.capture_id,
            evidence_span_id=source.evidence_span_id,
        )
        if not found:
            raise ValueError(
                "source attachment requires an exact current human-reviewed personal photograph"
            )
        [reviewed] = found
        if not reviewed.viewer_available:
            raise ValueError("current authorized viewer bytes are unavailable for a source")
        return {
            "source_sha256": reviewed.source_sha256,
            "authorization_id": reviewed.authorization_id,
            "screening_id": reviewed.screening_id,
            "authorized_at": reviewed.authorized_at,
            "screened_at": reviewed.screened_at,
        }

    def lock_authored_advance_base(
        self,
        entry_id: uuid.UUID,
        *,
        base_revision: int,
        world_id: str,
        authored_version_id: uuid.UUID,
        authored_state_sha256: str,
        authored_edit_seq: int,
        mutation_base_state_sha256: str,
    ) -> None:
        """Lock and validate the saved cursor before an authored mutation takes its branch lock."""

        self._lock_workspace()
        row = self.connection.execute(
            "select world_id,authored_version_id,authored_state_sha256,authored_edit_seq,revision "
            "from saved_world_entry where workspace_id=%s and entry_id=%s for update",
            (self.workspace_id, entry_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such saved world entry")
        expected = (
            world_id,
            authored_version_id,
            authored_state_sha256,
            authored_edit_seq,
            base_revision,
        )
        actual = (
            row["world_id"],
            row["authored_version_id"],
            row["authored_state_sha256"],
            row["authored_edit_seq"],
            row["revision"],
        )
        if actual != expected:
            raise StaleSavedWorldEntry(
                "the saved world resume point changed before the authored edit was recorded"
            )
        if mutation_base_state_sha256 != authored_state_sha256:
            raise StaleSavedWorldEntry(
                "the authored edit does not start from the saved world resume point"
            )
        authored = self.connection.execute(
            "select state_sha256,edit_seq from world_alternate_version "
            "where workspace_id=%s and world_id=%s and version_id=%s for update",
            (self.workspace_id, world_id, authored_version_id),
        ).fetchone()
        if authored is None:
            raise UnknownWorldResource("no such authored world version")
        if (
            authored["state_sha256"] != authored_state_sha256
            or authored["edit_seq"] != authored_edit_seq
        ):
            raise StaleSavedWorldEntry(
                "the authored world changed after the saved resume point was recorded"
            )

    def advance_authored_locked(
        self,
        entry_id: uuid.UUID,
        *,
        base_revision: int,
        world_id: str,
        authored_version_id: uuid.UUID,
        result_state_sha256: str,
        result_edit_seq: int,
    ) -> None:
        """Advance a locked entry to one exact mutation result in the same transaction."""

        current = self.connection.execute(
            "select state_sha256,edit_seq from world_alternate_version "
            "where workspace_id=%s and world_id=%s and version_id=%s for update",
            (self.workspace_id, world_id, authored_version_id),
        ).fetchone()
        if current is None:
            raise UnknownWorldResource("no such authored world version")
        if current["state_sha256"] != result_state_sha256 or current["edit_seq"] != result_edit_seq:
            raise StaleSavedWorldEntry(
                "the authored branch moved before its saved resume point could advance"
            )
        updated = self.connection.execute(
            "update saved_world_entry set authored_state_sha256=%s,authored_edit_seq=%s,"
            "revision=revision+1,updated_at=now() where workspace_id=%s and entry_id=%s "
            "and revision=%s returning entry_id",
            (
                result_state_sha256,
                result_edit_seq,
                self.workspace_id,
                entry_id,
                base_revision,
            ),
        ).fetchone()
        if updated is None:
            raise StaleSavedWorldEntry(
                "the saved world resume point changed before the authored edit was recorded"
            )

    def lock_style_advance_base(
        self,
        entry_id: uuid.UUID,
        *,
        base_revision: int,
        world_id: str,
        authored_state_sha256: str,
        authored_edit_seq: int,
        style_version_id: uuid.UUID,
    ) -> None:
        """Lock an entry and prove a style-only write will not adopt unseen authored state."""

        self._lock_workspace()
        row = self.connection.execute(
            "select world_id,authored_version_id,authored_state_sha256,authored_edit_seq,"
            "style_version_id,revision from saved_world_entry "
            "where workspace_id=%s and entry_id=%s for update",
            (self.workspace_id, entry_id),
        ).fetchone()
        if row is None:
            raise UnknownWorldResource("no such saved world entry")
        if (
            row["world_id"] != world_id
            or row["authored_state_sha256"] != authored_state_sha256
            or row["authored_edit_seq"] != authored_edit_seq
            or row["style_version_id"] != style_version_id
            or row["revision"] != base_revision
        ):
            raise StaleSavedWorldEntry(
                "the saved world resume point changed before the appearance was recorded"
            )
        authored = self.connection.execute(
            "select state_sha256,edit_seq from world_alternate_version "
            "where workspace_id=%s and world_id=%s and version_id=%s for update",
            (self.workspace_id, world_id, row["authored_version_id"]),
        ).fetchone()
        if authored is None:
            raise UnknownWorldResource("no such authored world version")
        if (
            authored["state_sha256"] != authored_state_sha256
            or authored["edit_seq"] != authored_edit_seq
        ):
            raise StaleSavedWorldEntry(
                "the authored world changed before the appearance could be saved"
            )

    def require_saved_style_is_live_write_base(
        self, *, world_id: str, style_version_id: uuid.UUID
    ) -> None:
        """Refuse an appearance edit while this saved style is not the live style.

        The entry lock has already proved ``style_version_id`` is the saved cursor.
        Rollback restores that appearance onto the live authority and does not call this.
        """

        row = self.connection.execute(
            "select current_style_version_id from world_style_state "
            "where workspace_id=%s and world_id=%s for update",
            (self.workspace_id, world_id),
        ).fetchone()
        if row is None or row["current_style_version_id"] != style_version_id:
            raise StaleStyleVersion(
                "restore the visible saved appearance before editing; another appearance is active"
            )

    def advance_style_locked(
        self,
        entry_id: uuid.UUID,
        *,
        base_revision: int,
        world_id: str,
        style_version_id: uuid.UUID,
    ) -> None:
        """Advance a previously locked entry to one exact committed style version."""

        style = self.connection.execute(
            "select 1 from world_style_version where workspace_id=%s and world_id=%s "
            "and version_id=%s for update",
            (self.workspace_id, world_id, style_version_id),
        ).fetchone()
        if style is None:
            raise UnknownWorldResource("no such world style version")
        updated = self.connection.execute(
            "update saved_world_entry set style_version_id=%s,revision=revision+1,"
            "updated_at=now() where workspace_id=%s and entry_id=%s and revision=%s "
            "returning entry_id",
            (style_version_id, self.workspace_id, entry_id, base_revision),
        ).fetchone()
        if updated is None:
            raise StaleSavedWorldEntry(
                "the saved world resume point changed before the appearance was recorded"
            )

    def _require_versions(
        self,
        world_id: str,
        authored_version_id: uuid.UUID,
        style_version_id: uuid.UUID,
        *,
        expected_authored_state_sha256: str | None = None,
        expected_authored_edit_seq: int | None = None,
        lock_authored: bool = False,
    ) -> dict[str, object]:
        authored = self.connection.execute(
            "select v.state_sha256,v.edit_seq,s.composer_key,s.composer_version,"
            "s.topology,s.placement from world_alternate_version v "
            "join world_structure_snapshot s on s.workspace_id=v.workspace_id "
            "and s.world_id=v.world_id and s.snapshot_id=v.source_snapshot_id "
            "where v.workspace_id=%s and v.world_id=%s and v.version_id=%s"
            + (" for update" if lock_authored else ""),
            (self.workspace_id, world_id, authored_version_id),
        ).fetchone()
        if authored is None:
            raise UnknownWorldResource("no such authored world version")
        if expected_authored_state_sha256 is not None and (
            authored["state_sha256"] != expected_authored_state_sha256
            or authored["edit_seq"] != expected_authored_edit_seq
        ):
            raise StaleSavedWorldEntry(
                "the authored world changed after this exact resume point was read"
            )
        style = self.connection.execute(
            "select 1 from world_style_version "
            "where workspace_id=%s and world_id=%s and version_id=%s",
            (self.workspace_id, world_id, style_version_id),
        ).fetchone()
        if style is None:
            raise UnknownWorldResource("no such world style version")
        return authored

    @staticmethod
    def _require_entry_origin(source_kind: str, snapshot: dict[str, object]) -> None:
        from exulanica.world.starter import (
            AUTHORED_STARTER_COMPOSER,
            authored_starter_scene,
        )

        composer_key = str(snapshot["composer_key"])

        if source_kind == "authored":
            if composer_key != AUTHORED_STARTER_COMPOSER:
                raise ValueError("an authored entry must name the controlled starter snapshot")
            authored_starter_scene(
                composer_key=composer_key,
                composer_version=int(snapshot["composer_version"]),
                topology=snapshot["topology"],
                placement=snapshot["placement"],
            )
            return
        if source_kind == "personal":
            if composer_key == AUTHORED_STARTER_COMPOSER:
                raise ValueError("an authored starter cannot be recorded as a personal source")
            return
        raise ValueError("unknown saved world source kind")

    def _lock_workspace(self) -> None:
        self.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s::text,%s))",
            (self.workspace_id, _WORKSPACE_LOCK_SEED),
        )

    def _select(self) -> str:
        return (
            "select e.entry_id,e.world_id,e.title,e.source_kind,e.authored_version_id,"
            "e.authored_state_sha256,e.authored_edit_seq,e.style_version_id,e.revision,"
            "e.created_by,e.created_at,e.updated_at,v.state_sha256 as current_state_sha256,"
            "v.edit_seq as current_edit_seq,v.source_snapshot_id,s.snapshot_sha256,"
            "s.composer_key,s.composer_version,s.topology,s.placement,"
            "exists(select 1 from world_structure_invalidation i "
            "where i.workspace_id=e.workspace_id and i.world_id=e.world_id "
            "and i.snapshot_id=v.source_snapshot_id) as source_invalidated "
            "from saved_world_entry e join world_alternate_version v "
            "on v.workspace_id=e.workspace_id and v.world_id=e.world_id "
            "and v.version_id=e.authored_version_id join world_structure_snapshot s "
            "on s.workspace_id=v.workspace_id and s.world_id=v.world_id "
            "and s.snapshot_id=v.source_snapshot_id where e.workspace_id=%s"
        )

    def _entry(self, row: dict[str, object]) -> SavedWorldEntry:
        from exulanica.world.starter import authored_starter_scene

        source_invalidated = bool(row["source_invalidated"])
        authored_changed = (
            row["authored_state_sha256"] != row["current_state_sha256"]
            or row["authored_edit_seq"] != row["current_edit_seq"]
        )
        unavailable = source_invalidated or authored_changed
        source_kind = row["source_kind"]
        if source_kind not in {"personal", "authored"}:
            raise ValueError("unknown saved world source kind")
        scene = (
            authored_starter_scene(
                composer_key=str(row["composer_key"]),
                composer_version=int(row["composer_version"]),
                topology=row["topology"],
                placement=row["placement"],
            )
            if source_kind == "authored"
            else None
        )
        return SavedWorldEntry(
            entry_id=row["entry_id"],
            world_id=row["world_id"],
            title=row["title"],
            source_kind=source_kind,
            source_snapshot_id=row["source_snapshot_id"],
            source_snapshot_sha256=row["snapshot_sha256"],
            authored_scene=scene,
            authored_version_id=row["authored_version_id"],
            authored_state_sha256=row["authored_state_sha256"],
            authored_edit_seq=row["authored_edit_seq"],
            current_authored_state_sha256=row["current_state_sha256"],
            current_authored_edit_seq=row["current_edit_seq"],
            style_version_id=row["style_version_id"],
            revision=row["revision"],
            availability="unavailable" if unavailable else "available",
            unavailable_reason=(
                "source_deleted"
                if source_invalidated
                else "authored_version_changed"
                if authored_changed
                else None
            ),
            source_attachments=self._attachments(row["entry_id"]),
            previous_source_attachments=self._previous_attachments(row["entry_id"]),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _attachments(self, entry_id: uuid.UUID) -> tuple[SavedWorldSourceAttachment, ...]:
        # Availability is the pinned authorization and screening, not the newest receipts.
        # Current collection membership excludes captures vacated by later detach events.
        rows = self.connection.execute(
            "select a.*,c.blob_sha256 as current_source_sha256,c.deleted_at,"
            "auth.capture_id as authorized_capture_id,auth.source_sha256 as authorized_sha256,"
            "auth.authorized_by,"
            "auth.corpus_class,auth.valid_until as authorization_valid_until,"
            "p.authorization_id as screened_authorization_id,p.capture_id as screened_capture_id,"
            "p.source_sha256 as screened_sha256,p.screening_method,p.reviewed_by,"
            "p.eligibility_state,"
            "p.valid_until as screening_valid_until,"
            "statement_timestamp() as evaluated_at,"
            "asset_capture_live(a.workspace_id,a.capture_id,statement_timestamp()) as source_live,"
            "not tombstone_blocks_span(a.workspace_id,s.blob_sha256,s.track_key,"
            "s.t_start_ns,s.t_end_ns) as span_live "
            "from saved_world_source_current_membership cur "
            "join saved_world_source_attachment a on a.workspace_id=cur.workspace_id "
            "and a.attachment_id=cur.attachment_id "
            "join capture c on c.workspace_id=a.workspace_id and c.capture_id=a.capture_id "
            "join evidence_span s on s.workspace_id=a.workspace_id "
            "and s.span_id=a.evidence_span_id "
            "join capture_reconstruction_authorization auth on auth.workspace_id=a.workspace_id "
            "and auth.authorization_id=a.authorization_id "
            "join reconstruction_privacy_screening p on p.workspace_id=a.workspace_id "
            "and p.screening_id=a.screening_id "
            "where cur.workspace_id=%s and cur.entry_id=%s and cur.attachment_id is not null "
            "order by a.attached_at,a.attachment_id",
            (self.workspace_id, entry_id),
        ).fetchall()
        attachments = []
        for row in rows:
            at = row["evaluated_at"]
            source_matches = (
                row["current_source_sha256"] == row["source_sha256"]
                and row["authorized_capture_id"] == row["capture_id"]
                and row["authorized_sha256"] == row["source_sha256"]
                and row["authorized_by"] == row["attached_by"]
                and row["screened_authorization_id"] == row["authorization_id"]
                and row["screened_capture_id"] == row["capture_id"]
                and row["screened_sha256"] == row["source_sha256"]
                and row["corpus_class"] == "personal"
                and row["screening_method"] == "human_review"
                and row["reviewed_by"] is not None
                and row["eligibility_state"] == "eligible"
            )
            reason = None
            selected = None
            if not row["source_live"] or not row["span_live"] or not source_matches:
                reason = "source_unavailable"
            elif (
                row["authorization_valid_until"] is not None
                and row["authorization_valid_until"] <= at
            ):
                reason = "authorization_expired"
            elif row["screening_valid_until"] is not None and row["screening_valid_until"] <= at:
                reason = "screening_expired"
            else:
                try:
                    selected = selected_image(
                        self.connection, self.workspace_id, bytes(row["source_sha256"]), at
                    )
                    viewer_exists = (
                        selected is not None
                        and self.store is not None
                        and self.store.exists(BlobId(selected.sha256))
                    )
                except (ValueError, BlobNotFoundError, IntegrityError, OSError):
                    # A malformed or ambiguous optional viewer lineage withholds this reference.
                    # It does not make the independently authored world impossible to reopen.
                    selected = None
                    viewer_exists = False
                if not viewer_exists:
                    reason = "viewer_unavailable"
            available = reason is None and selected is not None
            attachments.append(
                SavedWorldSourceAttachment(
                    attachment_id=row["attachment_id"],
                    operation_id=row["operation_id"],
                    capture_id=row["capture_id"],
                    evidence_span_id=row["evidence_span_id"],
                    source_sha256=bytes(row["source_sha256"]).hex(),
                    authorization_id=row["authorization_id"],
                    screening_id=row["screening_id"],
                    role="reference",
                    attached_entry_revision=row["attached_entry_revision"],
                    attached_by=row["attached_by"],
                    attached_at=row["attached_at"],
                    availability="available" if available else "unavailable",
                    unavailable_reason=None if available else reason,
                    viewer_sha256=selected.sha256.hex() if available else None,
                    evidence_path=(
                        f"/evidence/{row['evidence_span_id']}/masked" if available else None
                    ),
                )
            )
        return tuple(attachments)

    def _previous_attachments(
        self, entry_id: uuid.UUID
    ) -> tuple[SavedWorldPreviousSourceAttachment, ...]:
        # A removed photograph appears once, as its latest membership and the detach that ended
        # it. It returns no viewer digest or evidence path: this world no longer uses it, and the
        # library's own authorized viewer is what shows it.
        rows = self.connection.execute(
            "select a.attachment_id,a.operation_id,a.capture_id,a.evidence_span_id,"
            "a.source_sha256,a.authorization_id,a.screening_id,a.attached_entry_revision,"
            "a.attached_at,d.operation_id as detach_operation_id,d.detached_entry_revision,"
            "d.detached_by,d.detached_at,"
            "c.blob_sha256=a.source_sha256 "
            "and asset_capture_live(a.workspace_id,a.capture_id,statement_timestamp()) "
            "and not tombstone_blocks_span(a.workspace_id,s.blob_sha256,s.track_key,"
            "s.t_start_ns,s.t_end_ns) as source_live "
            "from saved_world_source_current_membership cur "
            "join lateral (select * from saved_world_source_attachment h "
            "where h.workspace_id=cur.workspace_id and h.entry_id=cur.entry_id "
            "and h.capture_id=cur.capture_id "
            "order by h.attached_entry_revision desc,h.attachment_id desc limit 1) a on true "
            "join saved_world_source_detach d on d.workspace_id=a.workspace_id "
            "and d.attachment_id=a.attachment_id "
            "join capture c on c.workspace_id=a.workspace_id and c.capture_id=a.capture_id "
            "join evidence_span s on s.workspace_id=a.workspace_id "
            "and s.span_id=a.evidence_span_id "
            "where cur.workspace_id=%s and cur.entry_id=%s and cur.attachment_id is null "
            "order by d.detached_at desc,d.detach_id desc",
            (self.workspace_id, entry_id),
        ).fetchall()
        return tuple(
            SavedWorldPreviousSourceAttachment(
                attachment_id=row["attachment_id"],
                operation_id=row["operation_id"],
                capture_id=row["capture_id"],
                evidence_span_id=row["evidence_span_id"],
                source_sha256=bytes(row["source_sha256"]).hex(),
                authorization_id=row["authorization_id"],
                screening_id=row["screening_id"],
                attached_entry_revision=row["attached_entry_revision"],
                attached_at=row["attached_at"],
                detach_operation_id=row["detach_operation_id"],
                detached_entry_revision=row["detached_entry_revision"],
                detached_by=row["detached_by"],
                detached_at=row["detached_at"],
                availability="available" if row["source_live"] else "unavailable",
                unavailable_reason=None if row["source_live"] else "source_unavailable",
            )
            for row in rows
        )
