"""A person's own assets: admitted to their workspace, prepared, placed and withdrawn.

Migration 0126 is the schema and ``docs/workspace-asset-admission.md`` the contract. This module is
the half that decides before anything is written, and the one authority every other plane asks.

**Admission writes nothing it has not checked.** :meth:`WorkspaceAssetRepository.admit` validates
the person's declaration (:class:`AssetDeclaration`), holds the uploaded bytes to the digest and
size it declares, and runs the whole static profile admission check
(:func:`exulanica.world.static_glb.inspect_static_glb`) before the first row. A refusal leaves no
row and no stored byte. An admission then records its row, its namespace inventory row and its
first preparation request in one transaction, and only then writes the bytes into the workspace's
own store namespace, under the object lock the purger also takes (0066's order): a crash leaves a
row whose bytes are missing, never bytes no row names.

**The declaration is the person's statement, not a verified fact.** Its rights basis comes from a
closed allowlist (their own work, CC0-1.0 or CC-BY-4.0 with attribution) and it names the rights
statement they affirmed; nothing here can check that the statement is true. What the admission may
be used for is the server's decision, :data:`USE_POLICY`: placement into this workspace's world
versions and delivery to this workspace's readers, and nothing else. A permissive licence widens
none of it.

**Nothing is shared between workspaces.** Ids are allocated here, bytes live in the workspace's own
namespace (``ContentStores.workspace_assets``, :mod:`exulanica.store.configured`), and every read
names the workspace. An upload identical to another workspace's answers exactly as if nobody held
those bytes. Within one workspace identical bytes are stored once, and authority is always the rows,
never the presence of bytes.

**Delivery asks again at the last moment.** Prepared bytes leave only after the 0041 final check
has seen the admission still current, the preparation still prepared with the same output, and the
output still recorded, under the asset read lock, so a withdrawal cannot slip between the check and
the bytes leaving.

:class:`WorkspaceAssetAuthority` is what the object repository and composition ask, inside their own
transaction, whether a pinned preparation may be placed, drawn or read by a society, in the shape of
:class:`exulanica.world.environment_source_authority.EnvironmentSourceAuthority`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Final, Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from exulanica.canonical import canonical_json
from exulanica.db.read_check import lock_asset_reads_until_commit
from exulanica.errors import IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.namespaces import WorkspaceStores, workspace_asset_lock_key
from exulanica.world.asset_import import MAX_ASSET_BYTES
from exulanica.world.static_glb import (
    MEDIA_TYPE,
    PREPARER_ID,
    PREPARER_VERSION,
    StaticGlbRefused,
    inspect_static_glb,
)
from exulanica.world.workspace_preparations import (
    DEFAULT_RETAINED_BYTES,
    PREPARATION_COLUMNS,
    RECEIPT_PROFILE,
    PreparationBlocked,
    PreparationError,
    PreparationFinished,
    PreparationNotReady,
    PreparationRecord,
    PreparedBytesMissing,
    WorkspaceAssetBusy,
    WorkspaceAssetQuotaExceeded,
    WorkspaceAssetsReadOnly,
    WorkspacePreparationRepository,
    object_lock,
    preparation_record,
    refusals,
    retained_bytes_refusal,
    retrying,
)

__all__ = [
    "ADMITTED_LICENCES",
    "DECLARATION_PROFILE",
    "MAX_DECLARATION_BYTES",
    "PARAMETERS_PROFILE",
    "RECEIPT_PROFILE",
    "RIGHTS_STATEMENT",
    "USE_POLICY",
    "AdmissionResult",
    "AssetContentRefused",
    "AssetDeclaration",
    "AssetRecord",
    "AssetTooLarge",
    "AttributionRequired",
    "AuthorizedAssetBytes",
    "ContentDigestMismatch",
    "InvalidDeclaration",
    "LicenceNotAdmitted",
    "PreparationFinished",
    "PreparationNotReady",
    "PreparationRecord",
    "PreparedBytesMissing",
    "ResolvedWorkspaceAsset",
    "UnknownWorkspaceAsset",
    "WorkspaceAssetAuthority",
    "WorkspaceAssetBusy",
    "WorkspaceAssetBytesUnavailable",
    "WorkspaceAssetChanged",
    "WorkspaceAssetError",
    "WorkspaceAssetIncompatible",
    "WorkspaceAssetNotPrepared",
    "WorkspaceAssetQuotaExceeded",
    "WorkspaceAssetRepository",
    "WorkspaceAssetRuntime",
    "WorkspaceAssetWithdrawn",
    "WorkspaceAssetsReadOnly",
    "asset_inputs",
    "object_lock",
    "parse_declaration",
    "preparation_parameters",
]

DECLARATION_PROFILE: Final = "exulanica.workspace-asset-admission/v1"
#: The one use policy an admission is recorded under. The server's decision, never the person's.
USE_POLICY: Final = "exulanica.workspace-asset-use/v1"
#: What :data:`USE_POLICY` permits, stated where a view can say it.
PERMITTED_USES: Final = ("place_in_this_workspace", "deliver_to_this_workspace")
#: The fixed rights statement a person affirms. Its words are the experience owner's to write.
RIGHTS_STATEMENT: Final = "exulanica.workspace-asset-rights-statement/v1"
PARAMETERS_PROFILE: Final = "exulanica.static-glb-preparation-parameters/v1"
ADMISSION_KEY_PROFILE: Final = "exulanica.workspace-asset-admission-key/v1"
ADMITTED_LICENCES: Final = ("CC0-1.0", "CC-BY-4.0")
#: The declaration part of an upload, in bytes. A declaration is a few hundred.
MAX_DECLARATION_BYTES: Final = 64 * 1024

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_Text = Annotated[str, Field(min_length=1, max_length=500)]
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")


# -- refusals ------------------------------------------------------------------------------------


class WorkspaceAssetError(PreparationError):
    """Base class for this plane's refusals. Each maps to one API problem."""


class InvalidDeclaration(WorkspaceAssetError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


class LicenceNotAdmitted(WorkspaceAssetError):
    """The declared licence is not one this workspace may hold assets under."""


class AttributionRequired(WorkspaceAssetError):
    """CC-BY-4.0 is admitted only with the attribution every delivery carries."""


class AssetTooLarge(WorkspaceAssetError):
    """The content is larger than any admitted container."""


class ContentDigestMismatch(WorkspaceAssetError):
    """The uploaded bytes are not the bytes the declaration names."""


class AssetContentRefused(WorkspaceAssetError):
    """The static profile refuses the content. ``reason`` is the stable content reason."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class UnknownWorkspaceAsset(WorkspaceAssetError):
    """No such asset in this workspace: never made, or another workspace's."""


class WorkspaceAssetWithdrawn(WorkspaceAssetError, PreparationBlocked):
    """The asset was withdrawn, or its workspace erased. Final."""


class WorkspaceAssetNotPrepared(WorkspaceAssetError):
    """Placement: the asset has no prepared output yet."""


class WorkspaceAssetIncompatible(WorkspaceAssetError):
    """Placement: the prepared output does not meet the placeable-object profile."""


class WorkspaceAssetChanged(WorkspaceAssetError):
    """Placement: the output named by the request is not the asset's prepared output."""


class WorkspaceAssetBytesUnavailable(WorkspaceAssetError):
    """Placement: the prepared output's bytes are not in the store, or no store was given."""


# -- the declaration -----------------------------------------------------------------------------


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RightsDeclaration(_Body):
    basis: Literal["own_work", "licensed"]
    #: Any text, checked against :data:`ADMITTED_LICENCES` by name, so the refusal says so.
    licence_id: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    attribution: _Text | None = None
    #: Where the person says it came from. Provenance text: never fetched, never followed.
    source_reference: _Text | None = None
    statement: Literal["exulanica.workspace-asset-rights-statement/v1"]


class ExpectedDimensions(_Body):
    width: Annotated[StrictInt, Field(ge=1, le=10_000_000)]
    height: Annotated[StrictInt, Field(ge=1, le=10_000_000)]
    depth: Annotated[StrictInt, Field(ge=1, le=10_000_000)]


class AssetDeclaration(_Body):
    profile: Literal["exulanica.workspace-asset-admission/v1"]
    content_kind: Literal["static_glb"]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    content_sha256: Digest
    byte_size: Annotated[StrictInt, Field(ge=20, le=MAX_ASSET_BYTES)]
    unit: Literal["millimetre", "centimetre", "metre"]
    expected_dimensions_mm: ExpectedDimensions | None = None
    rights: RightsDeclaration

    def document(self) -> dict[str, Any]:
        """The canonical document: every field, absent optionals as null."""
        return self.model_dump(mode="json")


def parse_declaration(raw: bytes) -> AssetDeclaration:
    """The declaration part, checked, or a refusal naming every problem or the rights rule."""
    if not 0 < len(raw) <= MAX_DECLARATION_BYTES:
        raise InvalidDeclaration([f"a declaration is 1 to {MAX_DECLARATION_BYTES} bytes"])
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise InvalidDeclaration(["the declaration is not UTF-8 JSON"]) from None
    try:
        declaration = AssetDeclaration.model_validate(value)
    except ValidationError as error:
        raise InvalidDeclaration(
            [
                f"{'.'.join(str(part) for part in item['loc']) or 'declaration'}: {item['msg']}"
                for item in error.errors(include_url=False, include_input=False)
            ]
        ) from None
    title = declaration.title
    if title != title.strip() or _CONTROL.search(title) is not None:
        raise InvalidDeclaration(["title: trimmed, with no control characters"])
    for name, text in (
        ("attribution", declaration.rights.attribution),
        ("source_reference", declaration.rights.source_reference),
    ):
        if text is not None and (text != text.strip() or _CONTROL.search(text) is not None):
            raise InvalidDeclaration([f"rights.{name}: trimmed, with no control characters"])
    rights = declaration.rights
    if rights.basis == "own_work":
        if rights.licence_id is not None:
            raise InvalidDeclaration(["rights.licence_id: own work names no licence"])
    else:
        if rights.licence_id is None:
            raise InvalidDeclaration(["rights.licence_id: a licensed asset names its licence"])
        if rights.licence_id not in ADMITTED_LICENCES:
            raise LicenceNotAdmitted(
                f"{rights.licence_id!r} is not admitted; a licensed asset is one of "
                f"{', '.join(ADMITTED_LICENCES)}"
            )
        if rights.licence_id == "CC-BY-4.0" and rights.attribution is None:
            raise AttributionRequired("CC-BY-4.0 is admitted with the attribution it requires")
    return declaration


def preparation_parameters(declaration: Mapping[str, Any]) -> dict[str, Any]:
    """What the static preparer is asked to do with one admission, as its canonical document."""
    return {
        "profile": PARAMETERS_PROFILE,
        "unit": declaration["unit"],
        "expected_dimensions_mm": declaration.get("expected_dimensions_mm"),
    }


def asset_inputs(asset_id: uuid.UUID, input_sha256: str) -> dict[str, Any]:
    """The inputs an asset preparation pins: exactly one admission and its exact bytes."""
    return {"asset_id": str(asset_id), "input_sha256": input_sha256}


# -- records -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssetRecord:
    asset_id: uuid.UUID
    content_kind: str
    title: str
    declaration: Mapping[str, Any]
    declaration_sha256: str
    input_sha256: str
    input_byte_size: int
    unit: str
    rights_basis: str
    licence_id: str | None
    use_policy: str
    created_by: uuid.UUID
    created_at: dt.datetime

    @property
    def attribution(self) -> str | None:
        return self.declaration["rights"].get("attribution")


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    asset: AssetRecord
    preparation: PreparationRecord | None
    created: bool


@dataclass(frozen=True, slots=True)
class AuthorizedAssetBytes:
    """Prepared bytes this workspace may be sent now, checked and still current."""

    data: bytes
    content_sha256: str
    asset_id: uuid.UUID
    licence_id: str | None
    attribution: str | None
    media_type: str = MEDIA_TYPE


@dataclass(frozen=True, slots=True)
class WorkspaceAssetRuntime:
    """What a process serving workspace assets holds: each workspace's own store namespace, and the
    retained-bytes limit configuration declares (``retained_bytes_limit``)."""

    stores: WorkspaceStores
    retained_bytes_limit: int = DEFAULT_RETAINED_BYTES


_ASSET_COLUMNS: Final = (
    "a.asset_id, a.content_kind, a.title, a.declaration_document, a.declaration_sha256, "
    "a.input_sha256, a.input_byte_size, a.unit, a.rights_basis, a.licence_id, a.use_policy, "
    "a.created_by, a.created_at"
)


def _asset(row: Mapping[str, Any]) -> AssetRecord:
    return AssetRecord(
        asset_id=row["asset_id"],
        content_kind=row["content_kind"],
        title=row["title"],
        declaration=row["declaration_document"],
        declaration_sha256=bytes(row["declaration_sha256"]).hex(),
        input_sha256=row["input_sha256"],
        input_byte_size=row["input_byte_size"],
        unit=row["unit"],
        rights_basis=row["rights_basis"],
        licence_id=row["licence_id"],
        use_policy=row["use_policy"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def admission_key(declaration_sha256: str, input_sha256: str) -> str:
    """What an identical upload is recognised by: the same declaration over the same bytes."""
    return hashlib.sha256(
        canonical_json(
            {
                "profile": ADMISSION_KEY_PROFILE,
                "declaration_sha256": declaration_sha256,
                "input_sha256": input_sha256,
            }
        )
    ).hexdigest()


# -- the repository ------------------------------------------------------------------------------


class WorkspaceAssetRepository:
    """One workspace's assets, through a connection scoped to that workspace.

    **Lock order.** Every write takes the workspace's lifecycle lock first (the triggers take it
    too), before any row lock, because a tombstone and a withdrawal take it and then update
    preparation rows. A write that also writes bytes holds the stored object's session lock
    outside its transaction, as the purger's claim does.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        actor: uuid.UUID,
        *,
        stores: WorkspaceStores,
        retained_bytes_limit: int = DEFAULT_RETAINED_BYTES,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.actor = actor
        self.stores = stores
        self.retained_bytes_limit = retained_bytes_limit
        self.queue = WorkspacePreparationRepository(connection, workspace_id, actor, stores=stores)

    # -- admission ----------------------------------------------------------------------

    def admit(self, declaration_raw: bytes, content: bytes) -> AdmissionResult:
        """Check everything, then record and store, or refuse having written nothing."""
        declaration = parse_declaration(declaration_raw)
        if len(content) > MAX_ASSET_BYTES:
            raise AssetTooLarge(f"a workspace asset is at most {MAX_ASSET_BYTES} bytes")
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != declaration.byte_size or digest != declaration.content_sha256:
            raise ContentDigestMismatch(
                "the uploaded bytes are not the bytes the declaration names"
            )
        try:
            inspect_static_glb(content)
        except StaticGlbRefused as refused:
            raise AssetContentRefused(refused.reason, str(refused)) from None
        document = declaration.document()
        canonical = canonical_json(document)
        declaration_sha256 = hashlib.sha256(canonical).hexdigest()
        key = admission_key(declaration_sha256, digest)
        with refusals():
            self.queue.may_append("workspace_asset")
            with object_lock(self.connection, workspace_asset_lock_key(self.workspace_id, digest)):
                asset_id, created = retrying(
                    lambda: self._record_admission(
                        document, canonical, declaration_sha256, key, digest, len(content)
                    )
                )
                store = self.stores.for_workspace(self.workspace_id)
                written = store.put_bytes(content)
                if written.blob_id != BlobId.from_hex(digest) or not store.exists(written.blob_id):
                    raise IntegrityError("the admitted bytes were not stored under their digest")
        asset, preparation = self.asset(asset_id)
        return AdmissionResult(asset, preparation, created)

    def _record_admission(
        self,
        document: Mapping[str, Any],
        canonical: bytes,
        declaration_sha256: str,
        key: str,
        digest: str,
        size: int,
    ) -> tuple[uuid.UUID, bool]:
        with self.connection.transaction():
            self.queue.lifecycle_lock()
            existing = self.connection.execute(
                "select a.asset_id from workspace_asset a "
                "where a.workspace_id = %s and a.admission_sha256 = %s "
                "  and not tombstone_blocks_workspace_asset(a.workspace_id, a.asset_id) "
                "order by a.created_at, a.asset_id limit 1",
                (self.workspace_id, key),
            ).fetchone()
            if existing is not None:
                return existing["asset_id"], False
            refusal = retained_bytes_refusal(
                self.connection, self.workspace_id, digest, size, self.retained_bytes_limit
            )
            if refusal is not None:
                raise WorkspaceAssetQuotaExceeded(refusal)
            rights = document["rights"]
            row = self.connection.execute(
                "insert into workspace_asset (workspace_id, content_kind, declaration_canonical, "
                "  declaration_document, declaration_sha256, admission_sha256, input_sha256, "
                "  input_byte_size, unit, rights_basis, licence_id, title, use_policy, created_by) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "returning asset_id",
                (
                    self.workspace_id,
                    document["content_kind"],
                    canonical,
                    Jsonb(json.loads(canonical)),
                    bytes.fromhex(declaration_sha256),
                    key,
                    digest,
                    size,
                    document["unit"],
                    rights["basis"],
                    rights["licence_id"],
                    document["title"],
                    USE_POLICY,
                    self.actor,
                ),
            ).fetchone()
            assert row is not None
            asset_id = row["asset_id"]
            self._record_blob(digest, size)
            self._request_locked(asset_id, document, digest)
        return asset_id, True

    def _request_locked(
        self, asset_id: uuid.UUID, declaration: Mapping[str, Any], input_sha256: str
    ) -> uuid.UUID:
        """The static preparation of one admission, requested in the caller's transaction."""
        return self.queue.request_locked(
            input_kind="workspace_asset",
            preparer_id=PREPARER_ID,
            preparer_version=PREPARER_VERSION,
            parameters=preparation_parameters(declaration),
            inputs=asset_inputs(asset_id, input_sha256),
            asset_id=asset_id,
        )

    def _record_blob(self, digest: str, size: int) -> None:
        self.connection.execute(
            "insert into workspace_asset_blob (workspace_id, content_sha256, byte_size) "
            "values (%s, %s, %s) on conflict (workspace_id, content_sha256) do nothing",
            (self.workspace_id, digest, size),
        )

    # -- reads --------------------------------------------------------------------------

    def _asset_row(self, asset_id: uuid.UUID) -> Mapping[str, Any]:
        row = self.connection.execute(
            f"select {_ASSET_COLUMNS}, "
            "  tombstone_blocks_workspace_asset(a.workspace_id, a.asset_id) as blocked "
            "from workspace_asset a where a.workspace_id = %s and a.asset_id = %s",
            (self.workspace_id, asset_id),
        ).fetchone()
        if row is None:
            raise UnknownWorkspaceAsset(f"no asset {asset_id} in this workspace")
        if row["blocked"]:
            raise WorkspaceAssetWithdrawn(f"asset {asset_id} was withdrawn or deleted")
        return row

    def _preparation_row(self, asset_id: uuid.UUID) -> Mapping[str, Any] | None:
        """The asset's preparation by the current static preparer, if one was ever requested."""
        return self.connection.execute(
            f"select {PREPARATION_COLUMNS} from workspace_preparation p "
            "where p.workspace_id = %s and p.asset_id = %s "
            "  and p.preparer_id = %s and p.preparer_version = %s",
            (self.workspace_id, asset_id, PREPARER_ID, PREPARER_VERSION),
        ).fetchone()

    def asset(self, asset_id: uuid.UUID) -> tuple[AssetRecord, PreparationRecord | None]:
        """One live asset and its current preparation, or 404 / 410 by class."""
        row = self._asset_row(asset_id)
        preparation = self._preparation_row(asset_id)
        return _asset(row), None if preparation is None else preparation_record(preparation)

    def assets(self) -> list[tuple[AssetRecord, PreparationRecord | None]]:
        """Every live asset, oldest first, with its current preparation."""
        rows = self.connection.execute(
            f"select {_ASSET_COLUMNS} from workspace_asset a "
            "where a.workspace_id = %s "
            "  and not tombstone_blocks_workspace_asset(a.workspace_id, a.asset_id) "
            "order by a.created_at, a.asset_id",
            (self.workspace_id,),
        ).fetchall()
        preparations = {
            row["asset_id"]: preparation_record(row)
            for row in self.connection.execute(
                f"select {PREPARATION_COLUMNS} from workspace_preparation p "
                "where p.workspace_id = %s and p.input_kind = 'workspace_asset' "
                "  and p.preparer_id = %s and p.preparer_version = %s",
                (self.workspace_id, PREPARER_ID, PREPARER_VERSION),
            ).fetchall()
        }
        return [(_asset(row), preparations.get(row["asset_id"])) for row in rows]

    def output_present(self, preparation: PreparationRecord) -> bool:
        """Whether a prepared output's bytes are in the namespace now."""
        return self.queue.output_present(preparation)

    def spent(self, *, admission: bool) -> str | None:
        """The count bound a new admission, or a request that queues a run, would meet now, by its
        name in ``workspace_asset_limits()``, or None. The guards that refuse stay the authority."""
        row = self.connection.execute(
            "select workspace_asset_spent(%s, %s) as spent", (self.workspace_id, admission)
        ).fetchone()
        return None if row is None else row["spent"]

    # -- preparation --------------------------------------------------------------------

    def request_preparation(self, asset_id: uuid.UUID) -> PreparationRecord:
        """Queue the asset's preparation under the queue's rules (a waiting, running or present
        preparation and a deterministic failure are answered as they are)."""
        with refusals():
            self.queue.may_append("workspace_preparation_request")

            def request() -> uuid.UUID:
                with self.connection.transaction():
                    self.queue.lifecycle_lock()
                    asset = self._asset_row(asset_id)
                    return self._request_locked(
                        asset_id, asset["declaration_document"], asset["input_sha256"]
                    )

            preparation_id = retrying(request)
        return self.queue.preparation(preparation_id)

    def cancel_preparation(self, asset_id: uuid.UUID) -> PreparationRecord:
        """Stop the asset's preparation if it has not finished; a running one records nothing."""
        with refusals():

            def cancel() -> uuid.UUID:
                with self.connection.transaction():
                    self.queue.lifecycle_lock()
                    self._asset_row(asset_id)
                    row = self._preparation_row(asset_id)
                    if row is None:
                        raise PreparationNotReady(f"asset {asset_id} has no preparation")
                    self.queue.cancel_locked(row["preparation_id"])
                    return row["preparation_id"]

            preparation_id = retrying(cancel)
        return self.queue.preparation(preparation_id)

    # -- withdrawal ---------------------------------------------------------------------

    def withdraw(self, asset_id: uuid.UUID) -> None:
        """End an admission for good. Idempotent. Destroys nothing: see the module docstring."""

        def withdraw() -> None:
            with self.connection.transaction():
                self.queue.lifecycle_lock()
                row = self.connection.execute(
                    "select 1 from workspace_asset where workspace_id = %s and asset_id = %s",
                    (self.workspace_id, asset_id),
                ).fetchone()
                if row is None:
                    raise UnknownWorkspaceAsset(f"no asset {asset_id} in this workspace")
                self.connection.execute(
                    "insert into workspace_asset_withdrawal (workspace_id, asset_id, withdrawn_by) "
                    "values (%s, %s, %s) on conflict (workspace_id, asset_id) do nothing",
                    (self.workspace_id, asset_id, self.actor),
                )

        with refusals():
            self.queue.may_append("workspace_asset_withdrawal")
            retrying(withdraw)

    # -- delivery -----------------------------------------------------------------------

    def read_prepared(self, asset_id: uuid.UUID) -> AuthorizedAssetBytes:
        """The prepared output, hash-checked, released only if still current afterwards."""
        asset = _asset(self._asset_row(asset_id))
        row = self._preparation_row(asset_id)
        if row is None:
            raise PreparationNotReady(f"asset {asset_id} has no prepared output")
        try:
            output = self.queue.read_output(row["preparation_id"])
        except PreparationBlocked as blocked:
            raise WorkspaceAssetWithdrawn(
                f"asset {asset_id}'s prepared output stopped being current"
            ) from blocked
        return AuthorizedAssetBytes(
            data=output.data,
            content_sha256=output.content_sha256,
            asset_id=asset_id,
            licence_id=asset.licence_id,
            attribution=asset.attribution,
        )


# -- the authority other planes ask --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedWorkspaceAsset:
    """One placeable preparation of one admission, as a placement pins it."""

    asset_id: uuid.UUID
    preparation_id: uuid.UUID
    output_sha256: str
    output_byte_size: int
    title: str
    licence_id: str | None
    attribution: str | None
    dimensions_mm: Mapping[str, int]

    @property
    def footprint_half_extents_mm(self) -> tuple[int, int]:
        """Half the prepared width and depth, rounded up, as a reviewed row states its own."""
        return (-(-self.dimensions_mm["width"] // 2), -(-self.dimensions_mm["depth"] // 2))

    def source_view(self) -> dict[str, Any]:
        return {
            "kind": "workspace_asset",
            "asset_id": str(self.asset_id),
            "preparation_id": str(self.preparation_id),
            "content_sha256": self.output_sha256,
            "bytes": "available",
        }


class WorkspaceAssetAuthority:
    """One workspace's assets, asked on the connection an edit or a read already holds.

    It never opens a transaction: :meth:`final_authorization` takes the global asset read lock
    inside the caller's write, after the row is written, so a withdrawal either committed before
    the question and is seen, or waits until the write commits.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        stores: WorkspaceStores | None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.stores = stores

    def _row(self, where: str, parameters: tuple[Any, ...]) -> Mapping[str, Any] | None:
        return self.connection.execute(
            "select p.preparation_id, p.asset_id, p.state, p.output_sha256, p.output_byte_size, "
            "  p.width_mm, p.height_mm, p.depth_mm, p.placeable, a.title, a.licence_id, "
            "  a.declaration_document -> 'rights' ->> 'attribution' as attribution, "
            "  tombstone_blocks_workspace_asset(a.workspace_id, a.asset_id) as blocked, "
            "  (select b.purged_at is null from workspace_asset_blob b "
            "    where b.workspace_id = p.workspace_id "
            "      and b.content_sha256 = p.output_sha256) as recorded "
            "from workspace_asset a "
            "left join workspace_preparation p "
            "  on p.workspace_id = a.workspace_id and p.asset_id = a.asset_id "
            f" and {where} "
            "where a.workspace_id = %s and a.asset_id = %s",
            parameters,
        ).fetchone()

    def resolve(
        self, asset_id: uuid.UUID, prepared_sha256: str | None = None
    ) -> ResolvedWorkspaceAsset:
        """The asset's placeable preparation, or the refusal that names why not, in that order:
        unknown, withdrawn, not prepared, incompatible, changed, bytes."""
        row = self._row(
            "p.preparer_id = %s and p.preparer_version = %s",
            (PREPARER_ID, PREPARER_VERSION, self.workspace_id, asset_id),
        )
        if row is None:
            raise UnknownWorkspaceAsset(f"no asset {asset_id} in this workspace")
        if row["blocked"]:
            raise WorkspaceAssetWithdrawn(f"asset {asset_id} was withdrawn or deleted")
        if row["preparation_id"] is None or row["state"] != "prepared":
            raise WorkspaceAssetNotPrepared(f"asset {asset_id} has no prepared output yet")
        if not row["placeable"]:
            raise WorkspaceAssetIncompatible(
                f"asset {asset_id}'s prepared output is not a placeable object"
            )
        if prepared_sha256 is not None and prepared_sha256 != row["output_sha256"]:
            raise WorkspaceAssetChanged(
                f"asset {asset_id} is prepared as {row['output_sha256']}, not {prepared_sha256}"
            )
        resolved = self._resolved(row)
        self.require_bytes(resolved.output_sha256)
        return resolved

    def pinned(self, preparation_id: uuid.UUID, output_sha256: str) -> ResolvedWorkspaceAsset:
        """The preparation a placed object pins, whatever its state now; unknown if it never was."""
        row = self._row(
            "p.preparation_id = %s",
            (preparation_id, self.workspace_id, self._asset_of(preparation_id)),
        )
        if row is None or row["preparation_id"] is None or row["output_sha256"] != output_sha256:
            raise UnknownWorkspaceAsset(f"no preparation {preparation_id} of that output here")
        return self._resolved(row)

    def _asset_of(self, preparation_id: uuid.UUID) -> uuid.UUID | None:
        row = self.connection.execute(
            "select asset_id from workspace_preparation "
            "where workspace_id = %s and preparation_id = %s",
            (self.workspace_id, preparation_id),
        ).fetchone()
        return None if row is None else row["asset_id"]

    @staticmethod
    def _resolved(row: Mapping[str, Any]) -> ResolvedWorkspaceAsset:
        return ResolvedWorkspaceAsset(
            asset_id=row["asset_id"],
            preparation_id=row["preparation_id"],
            output_sha256=row["output_sha256"],
            output_byte_size=row["output_byte_size"],
            title=row["title"],
            licence_id=row["licence_id"],
            attribution=row["attribution"],
            dimensions_mm={
                "width": row["width_mm"],
                "height": row["height_mm"],
                "depth": row["depth_mm"],
            },
        )

    def require_bytes(self, output_sha256: str) -> None:
        if self.stores is None:
            raise WorkspaceAssetBytesUnavailable("placing a workspace asset needs its store")
        if not self.stores.for_workspace(self.workspace_id).exists(BlobId.from_hex(output_sha256)):
            raise WorkspaceAssetBytesUnavailable("the prepared output's bytes are not in the store")

    def require_current(self, preparation_id: uuid.UUID, output_sha256: str) -> None:
        """The binding trigger's own question, asked first so a refusal keeps its class."""
        row = self.connection.execute(
            "select workspace_asset_placeable(%s, %s, %s) as placeable",
            (self.workspace_id, preparation_id, output_sha256),
        ).fetchone()
        if row is None or not row["placeable"]:
            raise WorkspaceAssetWithdrawn(
                "the workspace asset may not be pinned: withdrawn, erased, or not this asset's "
                "recorded output"
            )

    def final_authorization(self, preparation_id: uuid.UUID, output_sha256: str) -> None:
        lock_asset_reads_until_commit(
            self.connection,
            outside="a workspace asset placement is authorized only inside the write that makes it",
        )
        self.require_current(preparation_id, output_sha256)

    def availability(self, preparation_id: uuid.UUID, output_sha256: str) -> str:
        """Whether a placed object may be drawn now: ``available``, ``withdrawn``,
        ``unavailable_bytes`` or ``unknown`` (no store to look in)."""
        asset_id = self._asset_of(preparation_id)
        if asset_id is None:
            return "withdrawn"
        row = self._row("p.preparation_id = %s", (preparation_id, self.workspace_id, asset_id))
        if row is None or row["blocked"] or row["output_sha256"] != output_sha256:
            return "withdrawn"
        if not row["recorded"]:
            return "unavailable_bytes"
        if self.stores is None:
            return "unknown"
        try:
            self.require_bytes(output_sha256)
        except WorkspaceAssetBytesUnavailable:
            return "unavailable_bytes"
        return "available"
