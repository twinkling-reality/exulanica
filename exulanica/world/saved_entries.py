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
from exulanica.world.errors import InvalidStyleData, UnknownWorldResource
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.style_structure import (
    AuthoredVersionRef,
    CompatibilityIntent,
    StructuralSnapshotRef,
    StyleVersionRef,
    raise_for_incompatible_structure_style,
)

__all__ = [
    "SavedWorldCandidate",
    "SavedWorldEntry",
    "SavedWorldEntryRepository",
    "SavedWorldSourceAttachment",
    "SourceAttachmentOperationConflict",
    "SourceAttachmentSelection",
    "StaleSavedWorldEntry",
]

_WORKSPACE_LOCK_SEED: Final = 880_024


class StaleSavedWorldEntry(Exception):
    """The caller tried to replace an entry revision it did not read."""


class SourceAttachmentOperationConflict(Exception):
    """An attachment operation id was reused for a different exact request."""


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
                    raise ValueError(
                        "the authored starter already exists under a different title"
                    )
                raise ValueError("the workspace already has a different saved world entry")

            from exulanica.world.starter import create_starter_authorities

            world_id = f"world:authored:{uuid.uuid4()}"
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

        A later authorization or screening receipt is not a rebind. A capture that already
        has a membership row is refused, including after those pinned receipts expire.
        """

        if not 1 <= len(sources) <= 200:
            raise ValueError("attach between 1 and 200 source photographs")
        identities = [(source.capture_id, source.evidence_span_id) for source in sources]
        if len(set(identities)) != len(identities):
            raise ValueError("each source photograph and evidence span must be unique")
        if len({source.capture_id for source in sources}) != len(sources):
            raise ValueError("a capture can be attached only once in one operation")
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
            row = self.connection.execute(
                "select e.world_id,e.revision,e.authored_version_id,e.authored_state_sha256,"
                "e.authored_edit_seq,e.style_version_id,"
                "exists(select 1 from world_structure_invalidation i "
                "join world_alternate_version v on v.workspace_id=e.workspace_id "
                "and v.world_id=e.world_id and v.version_id=e.authored_version_id "
                "where i.workspace_id=e.workspace_id and i.world_id=e.world_id "
                "and i.snapshot_id=v.source_snapshot_id) as source_invalidated "
                "from saved_world_entry e where e.workspace_id=%s and e.entry_id=%s for update",
                (self.workspace_id, entry_id),
            ).fetchone()
            if row is None:
                raise UnknownWorldResource("no such saved world entry")
            prior = self.connection.execute(
                "select entry_id,request_sha256 from saved_world_source_attachment_operation "
                "where workspace_id=%s and operation_id=%s",
                (self.workspace_id, operation_id),
            ).fetchone()
            if prior is not None:
                if (
                    prior["entry_id"] != entry_id
                    or bytes(prior["request_sha256"]) != request_sha256
                ):
                    raise SourceAttachmentOperationConflict(
                        "operation_id already names a different source attachment request"
                    )
                return self.entry(entry_id)
            exact_cursor = (
                row["revision"] == base_revision
                and row["authored_version_id"] == authored_version_id
                and row["authored_state_sha256"] == authored_state_sha256
                and row["authored_edit_seq"] == authored_edit_seq
                and row["style_version_id"] == style_version_id
            )
            if not exact_cursor:
                raise StaleSavedWorldEntry(
                    "the saved world resume point changed before its sources were attached"
                )
            if row["source_invalidated"]:
                raise ValueError("sources cannot be attached to an unavailable saved world")
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
                    "the authored world changed before its sources were attached"
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
            # Unique (workspace, entry, capture): a later receipt does not replace this row.
            duplicate = self.connection.execute(
                "select capture_id from saved_world_source_attachment "
                "where workspace_id=%s and entry_id=%s and capture_id=any(%s)",
                (self.workspace_id, entry_id, [source.capture_id for source in sources]),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("a selected photograph is already attached to this saved world")

            resolved = [self._resolve_attachment(source, attached_by) for source in sources]
            result_revision = base_revision + 1
            self.connection.execute(
                "insert into saved_world_source_attachment_operation "
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
                    result_revision,
                    authored_version_id,
                    authored_state_sha256,
                    authored_edit_seq,
                    style_version_id,
                    attached_by,
                ),
            )
            for source, authority in zip(sources, resolved, strict=True):
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
                        attached_by,
                    ),
                )
            updated = self.connection.execute(
                "update saved_world_entry set revision=revision+1,updated_at=now() "
                "where workspace_id=%s and entry_id=%s and revision=%s returning entry_id",
                (self.workspace_id, entry_id, base_revision),
            ).fetchone()
            if updated is None:
                raise StaleSavedWorldEntry(
                    "the saved world resume point changed before its sources were attached"
                )
        return self.entry(entry_id)

    def _resolve_attachment(
        self, source: SourceAttachmentSelection, attached_by: uuid.UUID
    ) -> dict[str, object]:
        row = self.connection.execute(
            "select c.blob_sha256 as source_sha256,a.authorization_id,p.screening_id,"
            "statement_timestamp() as evaluated_at "
            "from capture c join evidence_span s on s.workspace_id=c.workspace_id "
            "and s.span_id=%s and s.blob_sha256=c.blob_sha256 "
            "and s.modality='still_image' and s.track_key='img' "
            "and s.t_start_ns=0 and s.t_end_ns=1 and s.region is null and s.text_anchor is null "
            "join blob b on b.blob_sha256=c.blob_sha256 and b.media_type like 'image/%%' "
            "join capture_reconstruction_authorization a on a.workspace_id=c.workspace_id "
            "and a.capture_id=c.capture_id and a.source_sha256=c.blob_sha256 "
            "and a.corpus_class='personal' and a.authorized_by=%s "
            "join reconstruction_privacy_screening p on p.workspace_id=c.workspace_id "
            "and p.authorization_id=a.authorization_id and p.capture_id=c.capture_id "
            "and p.source_sha256=c.blob_sha256 and p.screening_method='human_review' "
            "and p.eligibility_state='eligible' and p.reviewed_by is not null "
            "where c.workspace_id=%s and c.capture_id=%s and c.deleted_at is null "
            "and not tombstone_blocks_capture(c.workspace_id,c.capture_id) "
            "and not tombstone_blocks_span(c.workspace_id,s.blob_sha256,s.track_key,"
            "s.t_start_ns,s.t_end_ns) "
            "and privacy_screening_allows_capture(c.workspace_id,c.capture_id,p.screening_id) "
            "order by p.screened_at desc,p.screening_id,a.authorized_at desc,a.authorization_id "
            "limit 1",
            (
                source.evidence_span_id,
                attached_by,
                self.workspace_id,
                source.capture_id,
            ),
        ).fetchone()
        if row is None:
            raise ValueError(
                "source attachment requires an exact current human-reviewed personal photograph"
            )
        selected = selected_image(
            self.connection,
            self.workspace_id,
            bytes(row["source_sha256"]),
            row["evaluated_at"],
        )
        if selected is None or self.store is None or not self.store.exists(BlobId(selected.sha256)):
            raise ValueError("current authorized viewer bytes are unavailable for a source")
        return row

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
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _attachments(self, entry_id: uuid.UUID) -> tuple[SavedWorldSourceAttachment, ...]:
        # Availability is the pinned authorization and screening, not the newest receipts.
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
            "from saved_world_source_attachment a "
            "join capture c on c.workspace_id=a.workspace_id and c.capture_id=a.capture_id "
            "join evidence_span s on s.workspace_id=a.workspace_id "
            "and s.span_id=a.evidence_span_id "
            "join capture_reconstruction_authorization auth on auth.workspace_id=a.workspace_id "
            "and auth.authorization_id=a.authorization_id "
            "join reconstruction_privacy_screening p on p.workspace_id=a.workspace_id "
            "and p.screening_id=a.screening_id "
            "where a.workspace_id=%s and a.entry_id=%s "
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
            elif row["authorization_valid_until"] is not None and row[
                "authorization_valid_until"
            ] <= at:
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
