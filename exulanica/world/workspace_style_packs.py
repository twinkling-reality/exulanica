"""A workspace's own style packs: what migration 0173 keeps, through one repository.

A creator's pack version is admitted to their workspace (its manifest, declaration and files),
checked by a preparation, worn by their worlds while it is ready, withdrawn by them, and erased with
the workspace. ``docs/style-pack-contract.md`` section 11 is the contract. This module is the
storage half: it records an admitted version and its bytes, reads versions back, withdraws one,
counts upload attempts, and moves a version's check through its states. What is admitted (the
body, the declaration, the manifest's reading, the pieces and the preview) is decided before
:meth:`WorkspaceStylePackRepository.record` is called, and the database refuses what breaks its own
rules whatever the caller decided.

**Lock order.** A write that records bytes holds the workspace's style pack write key
(:func:`~exulanica.store.namespaces.workspace_style_pack_write_key`) as a session lock across its
rows' commit and its byte writes, as the purger takes the same key before it destroys any of the
workspace's style pack objects; inside it, every write takes the workspace's lifecycle lock first
(the triggers take it too), then row locks. A version becoming ready takes the write key, then the
lifecycle lock, and asks its base chain again, taking no asset read barrier (``finish_ready``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import tarfile
import tempfile
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Final

import psycopg
from exulanica_pieces.budgets import PieceBudgets, read_budgets
from psycopg.types.json import Jsonb

from exulanica.db.read_check import final_read_check
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.namespaces import WorkspaceStores, workspace_style_pack_write_key
from exulanica.world.style_packs import StylePackContext, load_context
from exulanica.world.workspace_preparations import (
    DEFAULT_RETAINED_BYTES,
    DELIVERY_CHUNK_BYTES,
    PreparationBlocked,
    PreparationError,
    object_lock,
    retained_bytes_held,
    retrying,
)

__all__ = [
    "ARCHIVE_MEDIA_TYPE",
    "BASE_SOURCES",
    "DEFAULT_INSTALLATION_BYTES",
    "DEFAULT_INSTALLATION_DAY_ATTEMPTS",
    "DEFAULT_WORKSPACE_DAY_ATTEMPTS",
    "FAILURE_CLASSES",
    "USE_POLICY",
    "AdmittedStylePack",
    "AuthorizedPackFile",
    "PackBase",
    "PackFile",
    "StylePackAttemptsExceeded",
    "StylePackExists",
    "StylePackIsABase",
    "StylePackNotCreator",
    "StylePackNotReady",
    "StylePackPublishLicenceNotHeld",
    "StylePackQuotaExceeded",
    "StylePackVersionExists",
    "StylePackVersionRecord",
    "StylePackWithdrawn",
    "UnknownStylePack",
    "WorkspaceStylePackError",
    "WorkspaceStylePackRepository",
    "WorkspaceStylePackRuntime",
    "WorkspaceStylePacksReadOnly",
    "carry_style_pack_withdrawal",
]

#: The server's decision about what a workspace pack may be used for, recorded on each version:
#: worn in its own workspace's worlds and nowhere else.
USE_POLICY: Final = "exulanica.workspace-style-pack-use/v1"
BASE_SOURCES: Final = ("library", "workspace")
#: An archive of a version is an uncompressed POSIX tar file.
ARCHIVE_MEDIA_TYPE: Final = "application/x-tar"
#: Why a check ended other than ready (migration 0173). ``interrupted`` alone may be asked again.
FAILURE_CLASSES: Final = ("interrupted", "refused", "base_unavailable", "withdrawn", "deleted")
#: A workspace's upload attempts in one UTC day, and the installation's.
DEFAULT_WORKSPACE_DAY_ATTEMPTS: Final = 32
DEFAULT_INSTALLATION_DAY_ATTEMPTS: Final = 512
#: Every workspace's retained style pack bytes together, at most.
DEFAULT_INSTALLATION_BYTES: Final = 16 * 1024 * 1024 * 1024

_VERSION_COLUMNS: Final = (
    "v.manifest_sha256, v.pack_id, v.version, v.manifest_canonical, v.manifest_byte_size, "
    "v.rights_basis, v.licence_id, v.base_source, v.base_pack_id, v.base_version, "
    "v.base_manifest_sha256, v.file_count, v.file_byte_size, v.preview_sha256, "
    "v.declaration_sha256, v.created_by, v.created_at, v.erased_at, "
    "p.state, p.failure_class, p.failure_message, p.attempts, "
    "exists (select 1 from workspace_style_pack_withdrawal w "
    "  where w.workspace_id = v.workspace_id and w.manifest_sha256 = v.manifest_sha256) "
    "  as withdrawn"
)


class WorkspaceStylePackError(PreparationError):
    """A workspace style pack refused by name."""


class UnknownStylePack(WorkspaceStylePackError):
    """No version of that digest in this workspace: another workspace's answers the same."""


class StylePackExists(WorkspaceStylePackError):
    """These manifest bytes are held under another declaration."""


class StylePackVersionExists(WorkspaceStylePackError):
    """This workspace holds another manifest at that pack id and version."""

    def __init__(self, message: str, held_manifest_sha256: str) -> None:
        super().__init__(message)
        self.held_manifest_sha256 = held_manifest_sha256


class StylePackWithdrawn(WorkspaceStylePackError, PreparationBlocked):
    """The creator withdrew this version, or the workspace was erased."""


class StylePackIsABase(WorkspaceStylePackError):
    """A live version of this workspace is drawn on the one being withdrawn."""


class StylePackQuotaExceeded(WorkspaceStylePackError):
    """The workspace's or the installation's room for style packs is full."""


class StylePackAttemptsExceeded(WorkspaceStylePackError):
    """The workspace's or the installation's upload attempts for the day are spent."""

    def __init__(self, message: str, bound: str) -> None:
        super().__init__(message)
        self.bound = bound


class StylePackNotCreator(WorkspaceStylePackError):
    """Only the creator of a version may ask for it to be published."""


class StylePackPublishLicenceNotHeld(WorkspaceStylePackError):
    """A licensed version passes on only the licence it came under."""


class StylePackNotReady(WorkspaceStylePackError):
    """The version has not passed its check, or a file it lists is missing."""


class WorkspaceStylePacksReadOnly(WorkspaceStylePackError):
    """This deployment's database role may read these tables and not append to them."""


def _tar_entry(path: str, size: int) -> tarfile.TarInfo:
    """A regular file's header with every field fixed but its name and size."""
    entry = tarfile.TarInfo(path)
    entry.size = size
    entry.mode = 0o644
    entry.uid = entry.gid = 0
    entry.uname = entry.gname = ""
    entry.mtime = 0
    entry.type = tarfile.REGTYPE
    return entry


@dataclass(frozen=True, slots=True)
class AuthorizedPackFile:
    """A file this workspace may be sent now: the exact bytes verified before the final check, in
    a file of the delivery's own with no name on disk. Close it once sent."""

    body: IO[bytes]
    byte_size: int
    media_type: str

    def chunks(self) -> Iterator[bytes]:
        """The bytes from their start, :data:`DELIVERY_CHUNK_BYTES` at a time."""
        self.body.seek(0)
        while chunk := self.body.read(DELIVERY_CHUNK_BYTES):
            yield chunk

    def close(self) -> None:
        self.body.close()


@dataclass(frozen=True, slots=True)
class PackFile:
    """One file a manifest lists, as recorded."""

    path: str | None
    content_sha256: str
    byte_size: int
    media_type: str


@dataclass(frozen=True, slots=True)
class PackBase:
    """The pack a version is drawn on: a library version or one of the workspace's own."""

    source: str
    pack_id: str
    version: int
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class AdmittedStylePack:
    """Everything an admission decided, ready to be recorded.

    ``manifest_canonical`` and ``declaration_canonical`` are the exact bytes admitted; ``files``
    are the manifest's listed files in its order, and ``contents`` holds each file's bytes by its
    digest. ``receipt`` is what the admission checked, each check with its verdict.
    """

    manifest_canonical: bytes
    pack_id: str
    version: int
    declaration_canonical: bytes
    rights_basis: str
    licence_id: str
    base: PackBase | None
    files: tuple[PackFile, ...]
    contents: Mapping[str, bytes]
    preview_sha256: str | None
    receipt: Mapping[str, Any]
    #: The attribution a licensed CC-BY pack came under; None for any other licence.
    attribution: str | None = None

    @property
    def documents_byte_size(self) -> int:
        """The manifest's, the declaration's and the receipt's bytes, as the database counts
        them (the receipt as PostgreSQL writes a ``jsonb`` value out)."""
        receipt = json.dumps(dict(self.receipt), ensure_ascii=False).encode("utf-8")
        return len(self.manifest_canonical) + len(self.declaration_canonical) + len(receipt)

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.manifest_canonical).hexdigest()

    @property
    def declaration_sha256(self) -> bytes:
        return hashlib.sha256(self.declaration_canonical).digest()


@dataclass(frozen=True, slots=True)
class StylePackVersionRecord:
    """One version as the workspace holds it, with its check's state."""

    manifest_sha256: str
    pack_id: str
    version: int
    manifest_canonical: bytes | None
    manifest_byte_size: int
    rights_basis: str
    licence_id: str
    base: PackBase | None
    file_count: int
    file_byte_size: int
    preview_sha256: str | None
    declaration_sha256: str
    created_by: uuid.UUID
    created_at: dt.datetime
    erased: bool
    state: str
    failure_class: str | None
    failure_message: str | None
    attempts: int
    withdrawn: bool

    @property
    def ready(self) -> bool:
        return self.state == "ready" and not self.withdrawn and not self.erased


def _record(row: Mapping[str, Any]) -> StylePackVersionRecord:
    base = (
        PackBase(
            row["base_source"],
            row["base_pack_id"],
            row["base_version"],
            row["base_manifest_sha256"],
        )
        if row["base_source"] is not None
        else None
    )
    manifest = row["manifest_canonical"]
    return StylePackVersionRecord(
        manifest_sha256=row["manifest_sha256"],
        pack_id=row["pack_id"],
        version=row["version"],
        manifest_canonical=bytes(manifest) if manifest is not None else None,
        manifest_byte_size=row["manifest_byte_size"],
        rights_basis=row["rights_basis"],
        licence_id=row["licence_id"],
        base=base,
        file_count=row["file_count"],
        file_byte_size=row["file_byte_size"],
        preview_sha256=row["preview_sha256"],
        declaration_sha256=bytes(row["declaration_sha256"]).hex(),
        created_by=row["created_by"],
        created_at=row["created_at"],
        erased=row["erased_at"] is not None,
        state=row["state"],
        failure_class=row["failure_class"],
        failure_message=row["failure_message"],
        attempts=row["attempts"],
        withdrawn=row["withdrawn"],
    )


#: The tree this module is part of, whose catalogs and budgets an upload is read against.
_TREE: Final = Path(__file__).resolve().parents[2]
#: How the schema refuses a write a tombstone or a withdrawal reached (``tombstone_refuse``, 0001).
_TOMBSTONED: Final = "tombstoned: write refused"


def _refused(error: psycopg.Error) -> Exception:
    """The schema's refusals, as this plane's own; anything else unchanged."""
    message = (error.diag.message_primary or "") if error.diag else ""
    if isinstance(error, psycopg.errors.ProgramLimitExceeded):
        return StylePackQuotaExceeded(message or "this workspace's style packs are at their limit")
    if isinstance(error, psycopg.errors.IntegrityConstraintViolation) and message.startswith(
        _TOMBSTONED
    ):
        return StylePackWithdrawn("a deletion or a withdrawal reached this style pack")
    if isinstance(error, psycopg.errors.CheckViolation) and message.startswith(
        "style_pack_is_a_base"
    ):
        return StylePackIsABase(message.removeprefix("style_pack_is_a_base: "))
    if isinstance(error, psycopg.errors.CheckViolation) and message.startswith(
        "publish_licence_not_held"
    ):
        return StylePackPublishLicenceNotHeld(message.removeprefix("publish_licence_not_held: "))
    if isinstance(error, psycopg.errors.CheckViolation) and message.startswith(
        "a style pack version is published only while it may be worn"
    ):
        return StylePackNotReady(message)
    if isinstance(error, psycopg.errors.InsufficientPrivilege) and message.startswith(
        "only the creator"
    ):
        return StylePackNotCreator(message)
    if isinstance(error, psycopg.errors.InsufficientPrivilege) and message.startswith(
        "permission denied for"
    ):
        return WorkspaceStylePacksReadOnly("this deployment keeps style packs read-only")
    return error


@dataclass(frozen=True, slots=True)
class WorkspaceStylePackRuntime:
    """What a process serving workspace style packs holds: each workspace's own style pack
    namespace, the bounds configuration declares, and the tree's look families, texture sets and
    piece budgets an upload is read against, read once when the process starts."""

    stores: WorkspaceStores
    context: StylePackContext
    budgets: PieceBudgets
    retained_bytes_limit: int = DEFAULT_RETAINED_BYTES
    installation_bytes_limit: int = DEFAULT_INSTALLATION_BYTES
    workspace_day_attempts: int = DEFAULT_WORKSPACE_DAY_ATTEMPTS
    installation_day_attempts: int = DEFAULT_INSTALLATION_DAY_ATTEMPTS

    @classmethod
    def over(
        cls, stores: WorkspaceStores, root: Path = _TREE, **bounds: Any
    ) -> WorkspaceStylePackRuntime:
        """A runtime reading the look families, texture sets and budgets from the tree at
        ``root``: this tree unless another is named."""
        return cls(stores=stores, context=load_context(root), budgets=read_budgets(root), **bounds)


def carry_style_pack_withdrawal(connection: psycopg.Connection, row: Mapping[str, Any]) -> None:
    """Write a withdrawal a restore carries, as the product would have: in the carried row's own
    workspace session, the versions drawn on it that the restored database still holds unfinished
    (requested, running or interrupted) and unwithdrawn are first cancelled as ``base_unavailable``,
    as their checks would have ended had they run after the withdrawal; then the row is written as
    the checkpoint records it. A ready dependent is not touched: the catalog replays this kind in
    ``withdrawn_at`` order, so a dependent withdrawn before its base was withdrawn first, and one
    still ready means the checkpoint and this database disagree, which the guard then refuses.
    """
    workspace_id = uuid.UUID(str(row["workspace_id"]))
    manifest_sha256 = str(row["manifest_sha256"])
    connection.execute("select workspace_asset_lifecycle_lock(%s)", (workspace_id,))
    connection.execute(
        "update workspace_style_pack_preparation p set state = 'cancelled', claim_token = null, "
        "  claimed_by = null, lease_expires_at = null, failure_class = 'base_unavailable', "
        "  failure_message = 'a pack this one is drawn on was withdrawn', "
        "  finished_at = statement_timestamp() "
        "from workspace_style_pack_version v "
        "where v.workspace_id = %s and v.base_source = 'workspace' "
        "  and v.base_manifest_sha256 = %s "
        "  and p.workspace_id = v.workspace_id and p.manifest_sha256 = v.manifest_sha256 "
        "  and (p.state in ('requested', 'running') "
        "       or (p.state = 'failed' and p.failure_class = 'interrupted')) "
        "  and not exists (select 1 from workspace_style_pack_withdrawal w "
        "                   where w.workspace_id = v.workspace_id "
        "                     and w.manifest_sha256 = v.manifest_sha256)",
        (workspace_id, manifest_sha256),
    )
    connection.execute(
        "insert into workspace_style_pack_withdrawal (workspace_id, manifest_sha256, "
        "  withdrawn_by, withdrawn_at) values (%s, %s, %s, %s)",
        (workspace_id, manifest_sha256, uuid.UUID(str(row["withdrawn_by"])), row["withdrawn_at"]),
    )


class WorkspaceStylePackRepository:
    """One workspace's style packs, through a connection scoped to that workspace."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        actor: uuid.UUID,
        *,
        stores: WorkspaceStores,
        retained_bytes_limit: int = DEFAULT_RETAINED_BYTES,
        installation_bytes_limit: int = DEFAULT_INSTALLATION_BYTES,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.actor = actor
        self.stores = stores
        self.retained_bytes_limit = retained_bytes_limit
        self.installation_bytes_limit = installation_bytes_limit

    # -- attempts ------------------------------------------------------------------------------

    def count_attempt(
        self,
        *,
        workspace_limit: int = DEFAULT_WORKSPACE_DAY_ATTEMPTS,
        installation_limit: int = DEFAULT_INSTALLATION_DAY_ATTEMPTS,
    ) -> None:
        """Count one upload attempt for this workspace and the installation, or refuse it.

        Counted in its own transaction, so the count stands whatever the attempt does next.
        """
        with self.connection.transaction():
            row = self.connection.execute(
                "select style_pack_attempt(%s, %s) as verdict",
                (workspace_limit, installation_limit),
            ).fetchone()
        verdict = None if row is None else row["verdict"]
        if verdict == "counted":
            return
        if verdict == "workspace_quota":
            raise StylePackAttemptsExceeded(
                f"this workspace has made {workspace_limit} style pack uploads today, its limit",
                "workspace",
            )
        raise StylePackAttemptsExceeded(
            f"this installation has taken {installation_limit} style pack uploads today, its limit",
            "installation",
        )

    # -- recording -----------------------------------------------------------------------------

    def record(self, admitted: AdmittedStylePack) -> tuple[StylePackVersionRecord, bool]:
        """Record an admitted version and store its files, or refuse having stored nothing new.

        The same manifest under the same declaration answers the version already held, and writes
        again any of its files the namespace lost; under another declaration it is
        :class:`StylePackExists`. Another manifest at a held pack id and version is
        :class:`StylePackVersionExists`; a withdrawn one is :class:`StylePackWithdrawn`.
        """
        listed = {file.content_sha256 for file in admitted.files}
        if set(admitted.contents) != listed:
            raise IntegrityError("an admitted pack's contents are not exactly its listed files")
        for digest, content in admitted.contents.items():
            if hashlib.sha256(content).hexdigest() != digest:
                raise IntegrityError("an admitted file's bytes are not the digest it is listed by")
        self._may_append()
        with object_lock(self.connection, workspace_style_pack_write_key(self.workspace_id)):
            try:
                created = retrying(lambda: self._record_rows(admitted))
            except psycopg.Error as error:
                raise _refused(error) from error
            store = self.stores.for_workspace(self.workspace_id)
            for digest, content in sorted(admitted.contents.items()):
                blob_id = BlobId.from_hex(digest)
                if store.exists(blob_id):
                    continue
                written = store.put_bytes(content)
                if written.blob_id != blob_id or not store.exists(blob_id):
                    raise IntegrityError("a style pack file was not stored under its digest")
        return self.version(admitted.manifest_sha256), created

    def _record_rows(self, admitted: AdmittedStylePack) -> bool:
        manifest_sha256 = admitted.manifest_sha256
        with self.connection.transaction():
            self.connection.execute(
                "select workspace_asset_lifecycle_lock(%s)", (self.workspace_id,)
            )
            held = self.connection.execute(
                "select v.manifest_sha256, v.declaration_sha256, v.pack_id, v.version, "
                "  tombstone_blocks_workspace_style_pack(v.workspace_id, v.manifest_sha256) "
                "    as blocked "
                "from workspace_style_pack_version v "
                "where v.workspace_id = %s "
                "  and (v.manifest_sha256 = %s or (v.pack_id = %s and v.version = %s))",
                (self.workspace_id, manifest_sha256, admitted.pack_id, admitted.version),
            ).fetchall()
            for row in held:
                if row["manifest_sha256"] != manifest_sha256:
                    raise StylePackVersionExists(
                        f"{admitted.pack_id} version {admitted.version} is held with another "
                        "manifest",
                        row["manifest_sha256"],
                    )
                if row["blocked"]:
                    raise StylePackWithdrawn("this style pack version was withdrawn")
                if bytes(row["declaration_sha256"]) != admitted.declaration_sha256:
                    raise StylePackExists("this manifest is held under another declaration")
                return False
            new_bytes = self._unheld_bytes(admitted.contents)
            held = retained_bytes_held(self.connection, self.workspace_id)
            adding = new_bytes + admitted.documents_byte_size
            if held + adding > self.retained_bytes_limit:
                raise StylePackQuotaExceeded(
                    f"the workspace's own content would hold {held + adding} bytes, over its "
                    f"retained-bytes limit of {self.retained_bytes_limit} bytes (admitted and "
                    "prepared assets and style packs, withdrawn ones included until the "
                    "workspace is erased)"
                )
            room = self.connection.execute(
                "select style_pack_installation_bytes_admit(%s, %s) as admitted",
                (adding, self.installation_bytes_limit),
            ).fetchone()
            if room is None or not room["admitted"]:
                raise StylePackQuotaExceeded(
                    "this installation's style packs are at their retained-bytes limit"
                )
            base = admitted.base
            self.connection.execute(
                "insert into workspace_style_pack_version (workspace_id, manifest_sha256, pack_id, "
                "  version, manifest_canonical, manifest_byte_size, declaration_canonical, "
                "  declaration_sha256, rights_basis, licence_id, licence_attribution, base_source, "
                "  base_pack_id, "
                "  base_version, base_manifest_sha256, file_count, file_byte_size, "
                "  preview_sha256, receipt_document, use_policy, created_by) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "  %s, %s, %s)",
                (
                    self.workspace_id,
                    manifest_sha256,
                    admitted.pack_id,
                    admitted.version,
                    admitted.manifest_canonical,
                    len(admitted.manifest_canonical),
                    admitted.declaration_canonical,
                    admitted.declaration_sha256,
                    admitted.rights_basis,
                    admitted.licence_id,
                    admitted.attribution,
                    None if base is None else base.source,
                    None if base is None else base.pack_id,
                    None if base is None else base.version,
                    None if base is None else base.manifest_sha256,
                    len(admitted.files),
                    sum(file.byte_size for file in admitted.files),
                    admitted.preview_sha256,
                    Jsonb(dict(admitted.receipt)),
                    USE_POLICY,
                    self.actor,
                ),
            )
            for ordinal, file in enumerate(admitted.files):
                self.connection.execute(
                    "insert into workspace_style_pack_file (workspace_id, manifest_sha256, "
                    "  ordinal, path, content_sha256, byte_size, media_type) "
                    "values (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        self.workspace_id,
                        manifest_sha256,
                        ordinal,
                        file.path,
                        file.content_sha256,
                        file.byte_size,
                        file.media_type,
                    ),
                )
            for digest, content in sorted(admitted.contents.items()):
                self.connection.execute(
                    "insert into workspace_style_pack_blob (workspace_id, content_sha256, "
                    "  byte_size) values (%s, %s, %s) "
                    "on conflict (workspace_id, content_sha256) do nothing",
                    (self.workspace_id, digest, len(content)),
                )
            self.connection.execute(
                "insert into workspace_style_pack_preparation (workspace_id, manifest_sha256) "
                "values (%s, %s)",
                (self.workspace_id, manifest_sha256),
            )
        return True

    def _unheld_bytes(self, contents: Mapping[str, bytes]) -> int:
        """The bytes these files add to the namespace: those it does not hold unpurged already."""
        held = {
            row["content_sha256"]
            for row in self.connection.execute(
                "select content_sha256 from workspace_style_pack_blob "
                "where workspace_id = %s and content_sha256 = any(%s) and purged_at is null",
                (self.workspace_id, sorted(contents)),
            ).fetchall()
        }
        return sum(len(content) for digest, content in contents.items() if digest not in held)

    def _may_append(self) -> None:
        row = self.connection.execute(
            "select has_table_privilege('workspace_style_pack_version', 'INSERT') as allowed"
        ).fetchone()
        if row is None or not row["allowed"]:
            raise WorkspaceStylePacksReadOnly("this deployment keeps style packs read-only")

    # -- reads ---------------------------------------------------------------------------------

    def version(self, manifest_sha256: str) -> StylePackVersionRecord:
        row = self.connection.execute(
            f"select {_VERSION_COLUMNS} from workspace_style_pack_version v "
            "join workspace_style_pack_preparation p "
            "  on p.workspace_id = v.workspace_id and p.manifest_sha256 = v.manifest_sha256 "
            "where v.workspace_id = %s and v.manifest_sha256 = %s",
            (self.workspace_id, manifest_sha256),
        ).fetchone()
        if row is None:
            raise UnknownStylePack(f"no style pack version {manifest_sha256[:12]} here")
        return _record(row)

    def versions(self) -> list[StylePackVersionRecord]:
        """Every version this workspace holds, by pack id and then version."""
        rows = self.connection.execute(
            f"select {_VERSION_COLUMNS} from workspace_style_pack_version v "
            "join workspace_style_pack_preparation p "
            "  on p.workspace_id = v.workspace_id and p.manifest_sha256 = v.manifest_sha256 "
            "where v.workspace_id = %s order by v.pack_id, v.version",
            (self.workspace_id,),
        ).fetchall()
        return [_record(row) for row in rows]

    def files(self, manifest_sha256: str) -> list[PackFile]:
        """The files a version lists, in its manifest's order."""
        rows = self.connection.execute(
            "select path, content_sha256, byte_size, media_type from workspace_style_pack_file "
            "where workspace_id = %s and manifest_sha256 = %s order by ordinal",
            (self.workspace_id, manifest_sha256),
        ).fetchall()
        return [
            PackFile(row["path"], row["content_sha256"], row["byte_size"], row["media_type"])
            for row in rows
        ]

    def wearable(self, manifest_sha256: str) -> bool:
        """Whether a world may wear this version and its files be served, as of now. A write or a
        delivery that acts on the answer asks it again under the asset read lock."""
        row = self.connection.execute(
            "select workspace_style_pack_wearable(%s, %s) as wearable",
            (self.workspace_id, manifest_sha256),
        ).fetchone()
        return bool(row is not None and row["wearable"])

    def read_file(self, manifest_sha256: str, content_sha256: str) -> AuthorizedPackFile:
        """One file of a ready version, checked and still current, in a file of this delivery's own.

        The file is served only through the version in the address, and only if that version or a
        workspace version in its base chain lists it. The bytes are copied and verified first;
        then the final read check (0041) asks whether the version may be worn now, and only after
        it ends are the bytes handed over. No write key is waited for: only a ready version is
        served, and a version's files are written before it becomes ready.
        """
        record = self.version(manifest_sha256)
        if record.withdrawn or record.erased:
            raise StylePackWithdrawn(
                "this style pack version was withdrawn or its workspace erased"
            )
        if record.state != "ready":
            raise StylePackNotReady("this style pack version has not passed its check")
        listed = self.connection.execute(
            "select f.media_type, f.byte_size from workspace_style_pack_file f "
            "join workspace_style_pack_chain(%s, %s) c on c.manifest_sha256 = f.manifest_sha256 "
            "where f.workspace_id = %s and f.content_sha256 = %s limit 1",
            (self.workspace_id, manifest_sha256, self.workspace_id, content_sha256),
        ).fetchone()
        if listed is None:
            raise UnknownStylePack("this style pack version lists no such file")
        try:
            body = self.stores.for_workspace(self.workspace_id).open_verified(
                BlobId.from_hex(content_sha256)
            )
        except BlobNotFoundError as error:
            raise StylePackNotReady("this file's bytes are missing from the namespace") from error
        output = AuthorizedPackFile(body, int(listed["byte_size"]), listed["media_type"])
        try:
            if body.seek(0, io.SEEK_END) != output.byte_size:
                raise IntegrityError("a style pack file's bytes are not the length recorded")
            with final_read_check(
                self.connection, not_idle="a style pack delivery needs an idle connection"
            ):
                row = self.connection.execute(
                    "select workspace_style_pack_wearable(%s, %s) as wearable",
                    (self.workspace_id, manifest_sha256),
                ).fetchone()
            if row is None or not row["wearable"]:
                raise StylePackWithdrawn("this style pack version may not be served now")
        except BaseException:
            output.close()
            raise
        return output

    def write_archive(self, manifest_sha256: str) -> AuthorizedPackFile:
        """A ready version as one uncompressed POSIX tar archive, in a file of this delivery's own.

        ``manifest.json`` (the canonical manifest and one newline, as the library keeps it) and
        every file the version lists, at its manifest path, each copied from the namespace and
        verified first; then the final read check asks whether the version may be worn now, and
        only after it ends is the archive handed over. Every header field but the name and size is
        fixed (mode 0644, owner 0, no user or group name, time 0, a regular file), and a path past
        100 bytes takes a pax header, so the archive is a pure function of the version's bytes.
        """
        record = self.version(manifest_sha256)
        if record.withdrawn or record.erased:
            raise StylePackWithdrawn(
                "this style pack version was withdrawn or its workspace erased"
            )
        if record.state != "ready" or record.manifest_canonical is None:
            raise StylePackNotReady("this style pack version has not passed its check")
        store = self.stores.for_workspace(self.workspace_id)
        body = tempfile.TemporaryFile()  # noqa: SIM115 - handed to the response, closed by it
        output = AuthorizedPackFile(body, 0, ARCHIVE_MEDIA_TYPE)
        try:
            with tarfile.open(fileobj=body, mode="w", format=tarfile.PAX_FORMAT) as archive:
                manifest = record.manifest_canonical + b"\n"
                archive.addfile(_tar_entry("manifest.json", len(manifest)), io.BytesIO(manifest))
                for file in self.files(manifest_sha256):
                    assert file.path is not None
                    try:
                        source = store.open_verified(BlobId.from_hex(file.content_sha256))
                    except BlobNotFoundError as error:
                        raise StylePackNotReady(
                            "a file of this version is missing from the namespace"
                        ) from error
                    with source:
                        archive.addfile(_tar_entry(file.path, file.byte_size), source)
            size = body.seek(0, io.SEEK_END)
            output = AuthorizedPackFile(body, size, ARCHIVE_MEDIA_TYPE)
            with final_read_check(
                self.connection, not_idle="a style pack archive needs an idle connection"
            ):
                row = self.connection.execute(
                    "select workspace_style_pack_wearable(%s, %s) as wearable",
                    (self.workspace_id, manifest_sha256),
                ).fetchone()
            if row is None or not row["wearable"]:
                raise StylePackWithdrawn("this style pack version may not be served now")
        except BaseException:
            output.close()
            raise
        return output

    # -- publishing ----------------------------------------------------------------------------

    def request_publish(
        self,
        manifest_sha256: str,
        *,
        licence_id: str,
        attribution: str | None,
        statement: str,
    ) -> uuid.UUID:
        """Record the creator's request that a ready version join the shared library, under the
        licence they grant the project. Only a host command publishes, and only on such a request.

        Refused unless the session's actor created the version (:class:`StylePackNotCreator`), the
        version may be worn, and a licensed version passes on only its own licence
        (:class:`StylePackPublishLicenceNotHeld`).
        """
        self.version(manifest_sha256)

        def request() -> uuid.UUID:
            with self.connection.transaction():
                self.connection.execute(
                    "select workspace_asset_lifecycle_lock(%s)", (self.workspace_id,)
                )
                row = self.connection.execute(
                    "insert into workspace_style_pack_publish_request (workspace_id, "
                    "  manifest_sha256, licence_id, attribution, statement, requested_by) "
                    "values (%s, %s, %s, %s, %s, %s) returning request_id",
                    (
                        self.workspace_id,
                        manifest_sha256,
                        licence_id,
                        attribution,
                        statement,
                        self.actor,
                    ),
                ).fetchone()
            assert row is not None
            return row["request_id"]

        try:
            return retrying(request)
        except psycopg.Error as error:
            raise _refused(error) from error

    # -- withdrawal ----------------------------------------------------------------------------

    def withdraw(self, manifest_sha256: str) -> bool:
        """Withdraw a version; True when this call withdrew it, False when it already was.

        Refused with :class:`StylePackIsABase` while a live version of the workspace is drawn on
        it, naming those versions.
        """
        self.version(manifest_sha256)

        def withdraw() -> bool:
            with self.connection.transaction():
                self.connection.execute(
                    "select workspace_asset_lifecycle_lock(%s)", (self.workspace_id,)
                )
                inserted = self.connection.execute(
                    "insert into workspace_style_pack_withdrawal (workspace_id, manifest_sha256, "
                    "  withdrawn_by) values (%s, %s, %s) "
                    "on conflict (workspace_id, manifest_sha256) do nothing",
                    (self.workspace_id, manifest_sha256, self.actor),
                )
                return inserted.rowcount == 1

        try:
            return retrying(withdraw)
        except psycopg.Error as error:
            raise _refused(error) from error

    # -- the check -----------------------------------------------------------------------------

    def claim(
        self, worker: str, lease_seconds: int, *, max_attempts: int = 3
    ) -> tuple[str, uuid.UUID] | None:
        """Claim the oldest waiting check of this workspace, or one whose lease ran out, that has
        not used its attempts."""

        def claim() -> tuple[str, uuid.UUID] | None:
            with self.connection.transaction():
                self.connection.execute(
                    "select workspace_asset_lifecycle_lock(%s)", (self.workspace_id,)
                )
                token = uuid.uuid4()
                row = self.connection.execute(
                    "update workspace_style_pack_preparation p "
                    "set state = 'running', attempts = attempts + 1, claim_token = %s, "
                    "  claimed_by = %s, lease_expires_at = clock_timestamp() "
                    "    + make_interval(secs => %s) "
                    "where (p.workspace_id, p.manifest_sha256) = ("
                    "  select q.workspace_id, q.manifest_sha256 "
                    "  from workspace_style_pack_preparation q "
                    "  where q.workspace_id = %s and q.attempts < %s and (q.state = 'requested' "
                    "    or (q.state = 'running' and q.lease_expires_at < clock_timestamp())) "
                    "  order by q.requested_at, q.manifest_sha256 "
                    "  for update skip locked limit 1) "
                    "returning p.manifest_sha256",
                    (token, worker, lease_seconds, self.workspace_id, max_attempts),
                ).fetchone()
            return None if row is None else (row["manifest_sha256"], token)

        try:
            return retrying(claim)
        except psycopg.Error as error:
            raise _refused(error) from error

    def finish_ready(
        self, manifest_sha256: str, token: uuid.UUID, report: Mapping[str, Any]
    ) -> None:
        """Mark a claimed check ready: under the write key and the lifecycle lock, the base chain is
        asked again by the schema, so a base withdrawn while the check ran refuses this write and
        the check is failed as ``base_unavailable`` instead.

        No asset read barrier (0041) is taken. A base's withdrawal and a tombstone both take the
        lifecycle lock this write holds, so neither can commit between the question and the
        commit; and waiting for the barrier's exclusive side while holding the lifecycle lock would
        deadlock against a tombstone, which takes the barrier's shared side first and the lifecycle
        lock second (the cycle migration 0137 removed for the 0020 lock).
        """
        with object_lock(self.connection, workspace_style_pack_write_key(self.workspace_id)):

            def ready() -> None:
                with self.connection.transaction():
                    self.connection.execute(
                        "select workspace_asset_lifecycle_lock(%s)", (self.workspace_id,)
                    )
                    self._finish(manifest_sha256, token, "ready", None, None, report)

            try:
                retrying(ready)
            except psycopg.errors.CheckViolation as error:
                if "becomes ready only while its base" not in (error.diag.message_primary or ""):
                    raise
                self.finish_failed(
                    manifest_sha256,
                    token,
                    "base_unavailable",
                    "a pack this one is drawn on was withdrawn or is not ready",
                    report,
                )

    def finish_failed(
        self,
        manifest_sha256: str,
        token: uuid.UUID,
        failure_class: str,
        message: str,
        report: Mapping[str, Any],
    ) -> None:
        """End a claimed check other than ready, with its class and what it found."""
        if failure_class not in ("interrupted", "refused", "base_unavailable"):
            raise ValueError(
                f"a check ends interrupted, refused or base_unavailable, not {failure_class}"
            )

        def failed() -> None:
            with self.connection.transaction():
                self.connection.execute(
                    "select workspace_asset_lifecycle_lock(%s)", (self.workspace_id,)
                )
                self._finish(manifest_sha256, token, "failed", failure_class, message, report)

        retrying(failed)

    def expire_exhausted(self, *, max_attempts: int = 3) -> int:
        """Fail as interrupted every check whose lease ran out after its last attempt: its worker
        stopped each time, and a repeat of the upload may ask again."""

        def expire() -> int:
            with self.connection.transaction():
                self.connection.execute(
                    "select workspace_asset_lifecycle_lock(%s)", (self.workspace_id,)
                )
                expired = self.connection.execute(
                    "update workspace_style_pack_preparation set state = 'failed', "
                    "  claim_token = null, claimed_by = null, lease_expires_at = null, "
                    "  failure_class = 'interrupted', finished_at = statement_timestamp(), "
                    "  failure_message = 'the check stopped before it finished, '"
                    "    || attempts || ' times', report_document = '{}'::jsonb "
                    "where workspace_id = %s and state = 'running' and attempts >= %s "
                    "  and lease_expires_at < clock_timestamp()",
                    (self.workspace_id, max_attempts),
                )
                return expired.rowcount

        return retrying(expire)

    def request_again(self, manifest_sha256: str) -> bool:
        """Ask again for a check that was interrupted; True when it now waits."""

        def again() -> bool:
            with self.connection.transaction():
                self.connection.execute(
                    "select workspace_asset_lifecycle_lock(%s)", (self.workspace_id,)
                )
                updated = self.connection.execute(
                    "update workspace_style_pack_preparation set state = 'requested', "
                    "  failure_class = null, failure_message = null, finished_at = null, "
                    "  report_document = null, attempts = 0, requested_at = statement_timestamp() "
                    "where workspace_id = %s and manifest_sha256 = %s "
                    "  and state = 'failed' and failure_class = 'interrupted'",
                    (self.workspace_id, manifest_sha256),
                )
                return updated.rowcount == 1

        try:
            return retrying(again)
        except psycopg.Error as error:
            raise _refused(error) from error

    def _finish(
        self,
        manifest_sha256: str,
        token: uuid.UUID,
        state: str,
        failure_class: str | None,
        message: str | None,
        report: Mapping[str, Any],
    ) -> None:
        updated = self.connection.execute(
            "update workspace_style_pack_preparation set state = %s, claim_token = null, "
            "  claimed_by = null, lease_expires_at = null, failure_class = %s, "
            "  failure_message = %s, report_document = %s, finished_at = statement_timestamp() "
            "where workspace_id = %s and manifest_sha256 = %s and state = 'running' "
            "  and claim_token = %s",
            (
                state,
                failure_class,
                message,
                Jsonb(dict(report)),
                self.workspace_id,
                manifest_sha256,
                token,
            ),
        )
        if updated.rowcount != 1:
            raise StylePackWithdrawn(
                "this check no longer holds its claim: it was withdrawn, deleted or claimed again"
            )
