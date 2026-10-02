"""The one preparation queue of a workspace's own content: request, read, cancel and deliver.

Migration 0126 is the schema; the A2/C7 lifecycle note in ``docs/workspace-asset-admission.md``
is the agreement this module keeps. A preparation pins one preparer (its id and version, one of
the preparers registered in code in :data:`exulanica.world.asset_preparation.PREPARERS`), its
parameters and its inputs, and it reads one of two kinds of input:

- ``workspace_asset``: an admission's exact bytes (:mod:`exulanica.world.workspace_assets`);
- ``character_recipe``: a recipe of a served character family revision, the character plane's
  own input, which names no admission.

**One queue, one claim path, one publication.** This module owns requesting, retrying and
cancelling; :class:`exulanica.world.asset_preparation.AssetPreparationWorker` owns claiming, the
lease and finishing. A consumer (placement for an asset, a saved look for a character) calls this
module and never writes the table.

**A request is the same preparation or a new one, never a second run of a lost cause.** The
preparation key is a digest of the preparer, the parameters and the pinned inputs, unique within
one workspace, so an identical request answers the existing row. A row waiting or running is left
alone; a prepared row whose output bytes are present is answered; one whose bytes went missing is
queued again and must reproduce its recorded digest. A failure whose class a second run cannot
change (:data:`DETERMINISTIC_FAILURES`) is answered as it is; any other failure, and a person's
cancellation, is queued again. Every queueing is counted against the workspace's quota.

**Nothing is shared between workspaces**, rows or bytes: an identical request in another workspace
is another preparation, run and stored in that workspace alone.

**Delivery asks again at the last moment** (:meth:`WorkspacePreparationRepository.read_output`):
under the 0041 asset read lock the preparation is still prepared with the same output, not
blocked, its output not purged, and whatever the consumer asks of its own rows still holds.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import IO, Any, Final, TypeVar

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.db.read_check import final_read_check
from exulanica.env import env_get, env_name
from exulanica.errors import BlobNotFoundError, ExulanicaError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import VERIFY_CHUNK_BYTES
from exulanica.store.namespaces import WorkspaceStores, workspace_asset_lock_key

__all__ = [
    "DEFAULT_RETAINED_BYTES",
    "DELIVERY_CHUNK_BYTES",
    "DETERMINISTIC_FAILURES",
    "INPUT_KINDS",
    "MEDIA_TYPE",
    "RECEIPT_PROFILE",
    "RETAINED_BYTES_BOUNDS",
    "RETAINED_BYTES_SETTING",
    "AuthorizedOutput",
    "PreparationBlocked",
    "PreparationError",
    "PreparationFinished",
    "PreparationNotReady",
    "PreparationRecord",
    "PreparedBytesMissing",
    "UnknownPreparation",
    "WorkspaceAssetBusy",
    "WorkspaceAssetQuotaExceeded",
    "WorkspaceAssetSettingRefused",
    "WorkspaceAssetsReadOnly",
    "WorkspacePreparationRepository",
    "cancel_refusal",
    "cancelled_by_removal",
    "canonical_document",
    "object_lock",
    "preparation_key",
    "queues_a_run",
    "refusals",
    "retained_bytes_limit",
    "retained_bytes_refusal",
    "retrying",
]

RECEIPT_PROFILE: Final = "exulanica.workspace-preparation-receipt/v1"
MEDIA_TYPE: Final = "model/gltf-binary"
#: How much of a prepared output a delivery holds in memory at once, as it reads or sends it.
DELIVERY_CHUNK_BYTES: Final = VERIFY_CHUNK_BYTES
INPUT_KINDS: Final = ("workspace_asset", "character_recipe")
#: Failures a second run of the same preparation cannot change: a request answers them as they
#: are rather than spending another run.
DETERMINISTIC_FAILURES: Final = frozenset(
    {
        "invalid_content",
        "rig_incompatible",
        "deformation_invalid",
        "over_budget",
        "nondeterministic",
        "stale",
    }
)
#: The failure classes a preparation cancelled by its admission's withdrawal or its workspace's
#: erasure carries; such a preparation is blocked, never queued again.
_BLOCKED_CANCELLATIONS: Final = frozenset({"withdrawn", "deleted"})
_TOMBSTONED: Final = "tombstoned: write refused"
_ATTEMPTS: Final = 5
_T = TypeVar("_T")


# -- refusals ------------------------------------------------------------------------------------


class PreparationError(ExulanicaError):
    """Base class for the preparation queue's refusals. Each maps to one API problem."""


class UnknownPreparation(PreparationError):
    """No such preparation in this workspace: never requested, or another workspace's."""


class PreparationBlocked(PreparationError):
    """The preparation's admission was withdrawn or its workspace erased, or its consumer's own
    rows no longer hold. Final for this preparation."""


class PreparationNotReady(PreparationError):
    """The preparation has no prepared output: waiting, running, failed or cancelled."""


class PreparedBytesMissing(PreparationError):
    """The prepared output is recorded and its bytes are not in the store. Re-request it."""


class PreparationFinished(PreparationError):
    """A prepared preparation cannot be cancelled."""


class WorkspaceAssetQuotaExceeded(PreparationError):
    """The workspace holds as many assets, bytes or preparation requests as it may."""


#: The setting naming every unpurged byte one workspace's asset namespace may hold, and its bounds.
RETAINED_BYTES_SETTING: Final = "WORKSPACE_ASSET_RETAINED_BYTES"
#: The default: admitted originals and prepared outputs, withdrawn ones included until a purge
#: erases them. Live admissions may hold 512 MiB of input, and preparation writes about as much
#: again, so 2 GiB keeps that whole live bound twice over: as much again for withdrawn assets,
#: whose bytes stay until the workspace is erased because per-asset erasure is later work.
DEFAULT_RETAINED_BYTES: Final = 2 * 1024**3
#: Below one largest admission and its output nothing could ever be admitted; above 1 TiB the
#: bound stops bounding anything a single host holds.
RETAINED_BYTES_BOUNDS: Final = (64 * 1024**2, 1024**4)


class WorkspaceAssetSettingRefused(ValueError):
    """The retained-bytes setting is not a whole number of bytes within its bounds."""


def retained_bytes_limit(environ: Mapping[str, str] | None = None) -> int:
    """``EXULANICA_WORKSPACE_ASSET_RETAINED_BYTES``, or the default; refused outside its bounds."""
    raw = env_get(RETAINED_BYTES_SETTING, environ)
    if raw is None or not raw.strip():
        return DEFAULT_RETAINED_BYTES
    text = raw.strip()
    low, high = RETAINED_BYTES_BOUNDS
    if not text.isascii() or not text.isdigit() or not low <= int(text) <= high:
        raise WorkspaceAssetSettingRefused(
            f"{env_name(RETAINED_BYTES_SETTING)} is a whole number of bytes from {low} to {high}"
        )
    return int(text)


def retained_bytes_refusal(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    digest: str,
    byte_size: int,
    limit: int,
) -> str | None:
    """Why recording these bytes would cross the workspace's retained-bytes limit, or None.

    Every unpurged object in the namespace counts, withdrawn admissions included. Bytes the
    namespace already holds add nothing. Asked under the workspace's lifecycle lock, which every
    record takes, so two records cannot both fit the last room.
    """
    row = connection.execute(
        "select coalesce(sum(byte_size) filter (where content_sha256 <> %s), 0) as held, "
        "  bool_or(content_sha256 = %s) as present "
        "from workspace_asset_blob where workspace_id = %s and purged_at is null",
        (digest, digest, workspace_id),
    ).fetchone()
    if row is None or row["present"]:
        return None
    if int(row["held"]) + byte_size <= limit:
        return None
    return (
        f"the workspace's assets would hold {int(row['held']) + byte_size} bytes, over its "
        f"retained-bytes limit of {limit} bytes (admitted and prepared, withdrawn ones included "
        "until the workspace is erased)"
    )


class WorkspaceAssetsReadOnly(PreparationError):
    """This deployment's database role may read these tables and not append to them."""


class WorkspaceAssetBusy(PreparationError):
    """A delivery held the 0041 read lock through every retry. Asking again shortly succeeds."""


# -- records -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreparationRecord:
    preparation_id: uuid.UUID
    input_kind: str
    asset_id: uuid.UUID | None
    preparer_id: str
    preparer_version: int
    parameters: Mapping[str, Any]
    inputs: Mapping[str, Any]
    state: str
    attempts: int
    requested_at: dt.datetime
    output_sha256: str | None
    output_byte_size: int | None
    dimensions_mm: Mapping[str, int] | None
    placeable: bool | None
    receipt: Mapping[str, Any] | None
    prepared_at: dt.datetime | None
    failure_class: str | None
    failure_code: str | None
    failure_message: str | None


@dataclass(frozen=True, slots=True)
class AuthorizedOutput:
    """A prepared output this workspace may be sent now, checked and still current.

    ``body`` holds the exact bytes that were hash-checked before the final read check, in a file of
    this delivery's own with no name on disk (``ContentAddressedStore.open_verified``), so a
    delivery holds one chunk of an output in memory, never the whole of it. Close it once it is
    sent, or use the output as a context manager.
    """

    body: IO[bytes]
    byte_size: int
    content_sha256: str
    preparation_id: uuid.UUID
    media_type: str = MEDIA_TYPE

    def chunks(self) -> Iterator[bytes]:
        """The bytes from their start, :data:`DELIVERY_CHUNK_BYTES` at a time."""
        self.body.seek(0)
        while chunk := self.body.read(DELIVERY_CHUNK_BYTES):
            yield chunk

    def read(self) -> bytes:
        """The whole output in memory, for a reader that wants it so."""
        self.body.seek(0)
        return self.body.read()

    def close(self) -> None:
        self.body.close()

    def __enter__(self) -> AuthorizedOutput:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


PREPARATION_COLUMNS: Final = (
    "p.preparation_id, p.input_kind, p.asset_id, p.preparer_id, p.preparer_version, "
    "p.parameters_document, p.inputs_document, p.state, p.attempts, p.requested_at, "
    "p.output_sha256, p.output_byte_size, p.width_mm, p.height_mm, p.depth_mm, p.placeable, "
    "p.receipt_document, p.prepared_at, p.failure_class, p.failure_code, p.failure_message"
)


def preparation_record(row: Mapping[str, Any]) -> PreparationRecord:
    dimensions = (
        None
        if row["width_mm"] is None
        else {"width": row["width_mm"], "height": row["height_mm"], "depth": row["depth_mm"]}
    )
    return PreparationRecord(
        preparation_id=row["preparation_id"],
        input_kind=row["input_kind"],
        asset_id=row["asset_id"],
        preparer_id=row["preparer_id"],
        preparer_version=row["preparer_version"],
        parameters=row["parameters_document"],
        inputs=row["inputs_document"],
        state=row["state"],
        attempts=row["attempts"],
        requested_at=row["requested_at"],
        output_sha256=row["output_sha256"],
        output_byte_size=row["output_byte_size"],
        dimensions_mm=dimensions,
        placeable=row["placeable"],
        receipt=row["receipt_document"],
        prepared_at=row["prepared_at"],
        failure_class=row["failure_class"],
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
    )


def canonical_document(value: Mapping[str, Any]) -> tuple[bytes, dict[str, Any], str]:
    """A document's canonical bytes, the same document as the schema holds it, and its digest."""
    raw = canonical_json(value)
    return raw, json.loads(raw), hashlib.sha256(raw).hexdigest()


def queues_a_run(state: str, failure_class: str | None, output_present: Callable[[], bool]) -> bool:
    """Whether requesting an existing preparation in this state puts a run in the queue.

    A failure a second run cannot change, a waiting or running preparation, a present output and a
    cancellation by a withdrawal or a deletion are answered as they are. ``output_present`` is asked
    only of a prepared one. The request path and the capability read both ask this.
    """
    return (
        (state == "failed" and failure_class not in DETERMINISTIC_FAILURES)
        or (state == "cancelled" and failure_class not in _BLOCKED_CANCELLATIONS)
        or (state == "prepared" and not output_present())
    )


def cancelled_by_removal(state: str, failure_class: str | None) -> bool:
    """Whether a withdrawal or a deletion cancelled this preparation, which nothing revives."""
    return state == "cancelled" and failure_class in _BLOCKED_CANCELLATIONS


def cancel_refusal(state: str) -> str | None:
    """The code cancelling a preparation in this state is refused with, or None."""
    return "preparation_finished" if state == "prepared" else None


def preparation_key(
    preparer_id: str, preparer_version: int, parameters_sha256: str, inputs_sha256: str
) -> str:
    """One preparer version, one set of parameters, one set of pinned inputs: one preparation."""
    return hashlib.sha256(
        canonical_json(
            {
                "inputs_sha256": inputs_sha256,
                "parameters_sha256": parameters_sha256,
                "preparer": {"id": preparer_id, "version": preparer_version},
            }
        )
    ).hexdigest()


@contextmanager
def refusals() -> Iterator[None]:
    """The schema's refusals, as this plane's own."""
    try:
        yield
    except psycopg.errors.ProgramLimitExceeded as error:
        raise WorkspaceAssetQuotaExceeded(error.diag.message_primary or "quota exceeded") from error
    except psycopg.errors.IntegrityConstraintViolation as error:
        if (error.diag.message_primary or "").startswith(_TOMBSTONED):
            raise PreparationBlocked("a deletion or a withdrawal reached this") from error
        raise
    except psycopg.errors.InsufficientPrivilege as error:
        if (error.diag.message_primary or "").startswith("permission denied for"):
            raise WorkspaceAssetsReadOnly(
                "this deployment keeps workspace assets read-only"
            ) from error
        raise


def retrying(operation: Callable[[], _T]) -> _T:
    """Run a write again when a delivery held the 0041 read lock, which fails it fast."""
    for attempt in range(_ATTEMPTS):
        try:
            return operation()
        except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected) as error:
            if attempt == _ATTEMPTS - 1:
                raise WorkspaceAssetBusy(
                    "a delivery or a deletion was in progress; ask again"
                ) from error
            time.sleep(0.05 * (attempt + 1))
    raise AssertionError("unreachable")


@contextmanager
def object_lock(connection: psycopg.Connection, key: str) -> Iterator[None]:
    """The session form of ``purge_lock_object``, held across a row's commit and its write.

    ``key`` is :func:`~exulanica.store.namespaces.workspace_asset_lock_key`, the key the purger
    takes for the same object.
    """
    connection.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (key,))
    try:
        yield
    finally:
        row = connection.execute(
            "select pg_advisory_unlock(hashtextextended(%s, 0)) as unlocked", (key,)
        ).fetchone()
        if row is None or row["unlocked"] is not True:
            raise RuntimeError("a stored-object advisory lock was not held")


# -- the repository ------------------------------------------------------------------------------


class WorkspacePreparationRepository:
    """One workspace's preparations, through a connection scoped to that workspace.

    **Lock order.** Every write takes the workspace's lifecycle lock first (the triggers take it
    too), before any row lock: a tombstone and a withdrawal take it and then update preparation
    rows, so taking a row lock first could deadlock against either.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        actor: uuid.UUID,
        *,
        stores: WorkspaceStores,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.actor = actor
        self.stores = stores

    # -- plumbing -----------------------------------------------------------------------

    def lifecycle_lock(self) -> None:
        self.connection.execute("select workspace_asset_lifecycle_lock(%s)", (self.workspace_id,))

    def may_append(self, table: str) -> None:
        row = self.connection.execute(
            "select has_table_privilege(%s, 'INSERT') as allowed", (table,)
        ).fetchone()
        if row is None or not row["allowed"]:
            raise WorkspaceAssetsReadOnly("this deployment keeps workspace assets read-only")

    def _row(self, where: str, parameters: tuple[Any, ...], *, lock: bool = False) -> Any:
        return self.connection.execute(
            f"select {PREPARATION_COLUMNS}, "
            "  tombstone_blocks_workspace_preparation(p.workspace_id, p.asset_id) as blocked "
            f"from workspace_preparation p where p.workspace_id = %s and {where}"
            # No key update: a pin's foreign key holds this row FOR KEY SHARE, and a requeue or a
            # cancellation changes no key column, so neither waits for the other.
            + (" for no key update" if lock else ""),
            (self.workspace_id, *parameters),
        ).fetchone()

    def _count_request(self, preparation_id: uuid.UUID) -> None:
        self.connection.execute(
            "insert into workspace_preparation_request "
            "(workspace_id, preparation_id, requested_by) values (%s, %s, %s)",
            (self.workspace_id, preparation_id, self.actor),
        )

    # -- requesting ---------------------------------------------------------------------

    def request(
        self,
        *,
        input_kind: str,
        preparer_id: str,
        preparer_version: int,
        parameters: Mapping[str, Any],
        inputs: Mapping[str, Any],
        asset_id: uuid.UUID | None = None,
    ) -> PreparationRecord:
        """Request one preparation, in its own transaction; see the module docstring's rules."""
        with refusals():
            self.may_append("workspace_preparation_request")

            def request() -> PreparationRecord:
                with self.connection.transaction():
                    self.lifecycle_lock()
                    preparation_id = self.request_locked(
                        input_kind=input_kind,
                        preparer_id=preparer_id,
                        preparer_version=preparer_version,
                        parameters=parameters,
                        inputs=inputs,
                        asset_id=asset_id,
                    )
                return self.preparation(preparation_id)

            return retrying(request)

    def request_locked(
        self,
        *,
        input_kind: str,
        preparer_id: str,
        preparer_version: int,
        parameters: Mapping[str, Any],
        inputs: Mapping[str, Any],
        asset_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """The request's rules inside the caller's transaction, which holds the lifecycle lock."""
        if input_kind not in INPUT_KINDS:
            raise ValueError(f"{input_kind!r} is not an input kind")
        if (input_kind == "workspace_asset") != (asset_id is not None):
            raise ValueError("an asset preparation, and only one, names its admission")
        parameters_raw, parameters_document, parameters_sha256 = canonical_document(parameters)
        inputs_raw, inputs_document, inputs_sha256 = canonical_document(inputs)
        key = preparation_key(preparer_id, preparer_version, parameters_sha256, inputs_sha256)
        row = self._row("p.preparation_key = %s", (key,), lock=True)
        if row is None:
            created = self.connection.execute(
                "insert into workspace_preparation (workspace_id, input_kind, asset_id, "
                "  preparer_id, preparer_version, parameters_canonical, parameters_document, "
                "  parameters_sha256, inputs_canonical, inputs_document, inputs_sha256, "
                "  preparation_key, requested_by) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "returning preparation_id",
                (
                    self.workspace_id,
                    input_kind,
                    asset_id,
                    preparer_id,
                    preparer_version,
                    parameters_raw,
                    Jsonb(parameters_document),
                    bytes.fromhex(parameters_sha256),
                    inputs_raw,
                    Jsonb(inputs_document),
                    bytes.fromhex(inputs_sha256),
                    key,
                    self.actor,
                ),
            ).fetchone()
            assert created is not None
            self._count_request(created["preparation_id"])
            return created["preparation_id"]
        if row["blocked"]:
            raise PreparationBlocked("this preparation's admission or workspace is gone")
        state, failure = row["state"], row["failure_class"]
        requeue = queues_a_run(state, failure, lambda: self._output_present_now(row))
        if cancelled_by_removal(state, failure):
            raise PreparationBlocked("this preparation was cancelled by a withdrawal or deletion")
        if requeue:
            self.connection.execute(
                "update workspace_preparation set state = 'requested', attempts = 0, "
                "  failure_class = null, failure_code = null, failure_message = null "
                "where workspace_id = %s and preparation_id = %s",
                (self.workspace_id, row["preparation_id"]),
            )
            self._count_request(row["preparation_id"])
        return row["preparation_id"]

    def _output_present_now(self, row: Mapping[str, Any]) -> bool:
        """Whether a prepared row's output is there, counting a write in progress as there.

        Asked holding the lifecycle lock, so the object lock is only tried, never waited for: the
        worker takes the object lock first and the lifecycle lock second (0066's reasoning).
        """
        digest = row["output_sha256"]
        if digest is None:
            return False
        if self.stores.for_workspace(self.workspace_id).exists(BlobId.from_hex(digest)):
            return True
        free = self.connection.execute(
            "select pg_try_advisory_xact_lock(hashtextextended(%s, 0)) as free",
            (workspace_asset_lock_key(self.workspace_id, digest),),
        ).fetchone()
        return not (free is not None and free["free"])

    # -- reading ------------------------------------------------------------------------

    def preparation(self, preparation_id: uuid.UUID) -> PreparationRecord:
        """One preparation by id, whatever its state; 404-shaped when this workspace has none."""
        row = self._row("p.preparation_id = %s", (preparation_id,))
        if row is None:
            raise UnknownPreparation(f"no preparation {preparation_id} in this workspace")
        return preparation_record(row)

    def blocked(self, preparation_id: uuid.UUID) -> bool:
        row = self._row("p.preparation_id = %s", (preparation_id,))
        if row is None:
            raise UnknownPreparation(f"no preparation {preparation_id} in this workspace")
        return bool(row["blocked"])

    def output_present(self, record: PreparationRecord) -> bool:
        """Whether a prepared output's bytes are in the namespace now."""
        if record.output_sha256 is None:
            return False
        store = self.stores.for_workspace(self.workspace_id)
        return store.exists(BlobId.from_hex(record.output_sha256))

    # -- cancelling ---------------------------------------------------------------------

    def cancel(self, preparation_id: uuid.UUID) -> PreparationRecord:
        """Stop a preparation that has not finished. A running one records nothing afterwards."""
        with refusals():

            def cancel() -> PreparationRecord:
                with self.connection.transaction():
                    self.lifecycle_lock()
                    self.cancel_locked(preparation_id)
                return self.preparation(preparation_id)

            return retrying(cancel)

    def cancel_locked(self, preparation_id: uuid.UUID) -> None:
        row = self._row("p.preparation_id = %s", (preparation_id,), lock=True)
        if row is None:
            raise UnknownPreparation(f"no preparation {preparation_id} in this workspace")
        if cancel_refusal(row["state"]) is not None:
            raise PreparationFinished(f"preparation {preparation_id} finished")
        if row["state"] in ("requested", "running"):
            self.connection.execute(
                "update workspace_preparation set state = 'cancelled', "
                "  claim_token = null, claimed_by = null, lease_expires_at = null, "
                "  failure_class = 'cancelled', failure_code = null, "
                "  failure_message = 'cancelled before it finished' "
                "where workspace_id = %s and preparation_id = %s",
                (self.workspace_id, preparation_id),
            )

    # -- delivery -----------------------------------------------------------------------

    def read_output(
        self,
        preparation_id: uuid.UUID,
        *,
        still_current: Callable[[psycopg.Connection], bool] | None = None,
    ) -> AuthorizedOutput:
        """The prepared output, hash-checked, released only if still current afterwards.

        ``still_current`` is the consumer's own question about its rows (a character family
        revision still served, say), asked inside the final check at the same instant. The output
        holds its bytes in a file of its own until the caller closes it; a refusal closes it first.
        """
        row = self._row("p.preparation_id = %s", (preparation_id,))
        if row is None:
            raise UnknownPreparation(f"no preparation {preparation_id} in this workspace")
        if row["blocked"]:
            raise PreparationBlocked(f"preparation {preparation_id} was withdrawn or deleted")
        if row["state"] != "prepared" or row["output_sha256"] is None:
            raise PreparationNotReady(f"preparation {preparation_id} has no prepared output")
        digest = row["output_sha256"]
        # An output is recorded before its bytes are written, under the object's lock. Waiting
        # for that lock, holding nothing else, turns "missing" into "a moment later".
        with self.connection.transaction():
            self.connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (workspace_asset_lock_key(self.workspace_id, digest),),
            )
        # Read and hash-checked before the final check, into a file of this delivery's own, so the
        # bytes sent are the bytes checked and the whole output is never held in memory.
        try:
            body = self.stores.for_workspace(self.workspace_id).open_verified(
                BlobId.from_hex(digest)
            )
        except BlobNotFoundError as error:
            raise PreparedBytesMissing(
                f"preparation {preparation_id}'s bytes are missing; request it again"
            ) from error
        output = AuthorizedOutput(
            body=body,
            byte_size=body.seek(0, io.SEEK_END),
            content_sha256=digest,
            preparation_id=preparation_id,
        )
        try:
            body.seek(0)
            if output.byte_size != row["output_byte_size"]:
                raise IntegrityError(
                    f"preparation {preparation_id}'s bytes are not the length recorded"
                )
            with final_read_check(
                self.connection,
                not_idle="a final preparation authorization needs an idle connection",
            ):
                current = self.connection.execute(
                    "select p.output_sha256, p.state, "
                    "  tombstone_blocks_workspace_preparation(p.workspace_id, p.asset_id) "
                    "    as blocked, "
                    "  (select b.purged_at from workspace_asset_blob b "
                    "    where b.workspace_id = p.workspace_id "
                    "      and b.content_sha256 = p.output_sha256) as purged_at "
                    "from workspace_preparation p "
                    "where p.workspace_id = %s and p.preparation_id = %s",
                    (self.workspace_id, preparation_id),
                ).fetchone()
                consumer_holds = True if still_current is None else still_current(self.connection)
            if (
                current is None
                or current["blocked"]
                or current["purged_at"] is not None
                or current["state"] != "prepared"
                or current["output_sha256"] != digest
                or not consumer_holds
            ):
                raise PreparationBlocked(f"preparation {preparation_id} stopped being current")
        except BaseException:
            output.close()
            raise
        return output
