"""The one preparation worker: claim, prepare, check, record, then write.

Every preparation of a workspace's own content (migration 0126) is made here and nowhere else.
A preparation pins its preparer (id and version), its parameters and its inputs, and this module
runs the preparer registered in code under that pin. :data:`PREPARERS` is a fixed tuple in code:
catalog data and requests never choose code. The static GLB preparer
(:mod:`exulanica.world.static_glb`) is registered here; the character plane registers its own
preparer beside it rather than a second queue (the A2/C7 lifecycle note in
``docs/workspace-asset-admission.md``). Requesting, retrying and cancelling are
:mod:`exulanica.world.workspace_preparations`'s; claiming, the lease and finishing are this
module's.

The shape is the material bake worker's (:mod:`exulanica.world.material_bakes`), step for step:

1.  **Claim with a lease**, in the 0016 shape, one preparer at a time with that preparer's own
    lease: a requested preparation, or a running one whose lease expired, that no withdrawal or
    deletion has reached, taken ``for no key update skip locked`` under the workspace's
    lifecycle lock with a fresh token.
2.  **Read the input.** An asset preparation reads its admission's exact bytes from the workspace's
    own namespace, hash-checked; missing or corrupt input is a failed preparation, never a guess.
    Any other input kind is read by its preparer from what the preparation pins.
3.  **Prepare.** A preparer is deterministic and writes nothing. The static preparer runs in this
    process, after admission bounded everything it allocates; one that declares
    ``runs_child_process`` runs its own bounded child. A run past its preparer's
    ``timeout_seconds`` is failed ``timed_out`` and its output discarded. A worker that dies
    mid-run leaves a lease that expires; a later pass takes it again, and an attempt that dies
    every time is failed ``exhausted``.
4.  **Believe the output only as the checks and the recorded digest allow.** A re-run of a
    preparation whose output was recorded must reproduce that digest or fail ``nondeterministic``.
5.  **Record, then write**, under a session lock on the output the purger also takes: inside the
    record's transaction the preparer may ask again whether its own inputs still hold (a character
    family revision still served; ``stale`` when not), and the row becomes ``prepared`` only if its
    claim is still this worker's and the schema finds its admission and workspace current. Only
    then are the bytes put into the namespace. A cancellation or a withdrawal that commits first
    makes the record fail, and nothing is written.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol, TypeVar

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.corpus.decode import open_sensor
from exulanica.db.session import Database
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store.namespaces import WorkspaceStores, workspace_asset_lock_key
from exulanica.world import asset_import, static_glb
from exulanica.world.character_preparation import CharacterBodyPreparer
from exulanica.world.workspace_preparations import (
    DEFAULT_RETAINED_BYTES,
    RECEIPT_PROFILE,
    object_lock,
    retained_bytes_refusal,
)

__all__ = [
    "PREPARERS",
    "USE_POLICY",
    "AssetPreparationWorker",
    "PreparationInput",
    "PreparationOutcome",
    "PreparationOutput",
    "PreparationRefused",
    "Preparer",
    "StaticGlbPreparer",
    "decode_texture",
    "preparer_source_sha256",
]

#: The use policy an asset preparation's receipt repeats, the one
#: :data:`exulanica.world.workspace_assets.USE_POLICY` records on the admission.
USE_POLICY: Final = "exulanica.workspace-asset-use/v1"
_T = TypeVar("_T")
_SERIALIZATION_RETRIES: Final = 5


class PreparationRefused(Exception):
    """The input cannot be prepared. ``failure_class`` is the schema's; ``code`` the preparer's
    stable reason. A refusal is deterministic for its pinned inputs, so a request answers it."""

    def __init__(self, code: str, message: str, *, failure_class: str = "invalid_content") -> None:
        super().__init__(message)
        self.code = code
        self.failure_class = failure_class


@dataclass(frozen=True, slots=True)
class PreparationInput:
    """What a preparer is given: the preparation's pins and, for an asset, its admitted bytes."""

    workspace_id: uuid.UUID
    preparation_id: uuid.UUID
    input_kind: str
    parameters: Mapping[str, Any]
    inputs: Mapping[str, Any]
    #: The admission's exact bytes for an asset preparation; None for any other input kind.
    input_bytes: bytes | None


@dataclass(frozen=True, slots=True)
class PreparationOutput:
    """What a preparer made, and every fact its receipt states about making it."""

    output: bytes
    output_sha256: str
    dimensions_mm: Mapping[str, int]
    placeable: bool
    steps: tuple[Mapping[str, Any], ...]
    compatibility: tuple[Mapping[str, Any], ...]
    #: What a consumer renders the output by (a character's rig, clips and standing height), when
    #: the preparer states one. The static preparer states none.
    descriptor: Mapping[str, Any] | None = None


class Preparer(Protocol):
    """One preparer a preparation row can pin. Deterministic, and writes nothing."""

    preparer_id: str
    preparer_version: int
    input_kind: str
    timeout_seconds: float
    #: How long a claim is believed; longer than ``timeout_seconds``, or a live run is reclaimed.
    lease_seconds: float
    runs_child_process: bool

    def source_sha256(self) -> str: ...

    def available(self) -> bool:
        """Whether this process can run the preparer at all: its host tools present and their
        pins verified. Asked once, when a worker is built; a worker claims only the rows of the
        preparers it can run, so a row waits for one that can rather than failing here."""
        ...

    def prepare(self, request: PreparationInput) -> PreparationOutput: ...

    def recheck(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, request: PreparationInput
    ) -> str | None:
        """Asked inside the record's transaction: None when the preparer's own inputs still hold,
        else the sentence the preparation fails ``stale`` with. Reads rows only."""
        ...


def decode_texture(data: bytes) -> tuple[int, int]:
    """Decode one embedded texture through the one decode site, and return its size."""
    with open_sensor(data) as image:
        return image.size


def preparer_source_sha256(*modules: Any) -> str:
    """The digest of the source files a preparer runs, recorded in its receipt as provenance."""
    files = sorted(
        (
            {
                "path": Path(module.__file__).name,
                "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
            }
            for module in modules
        ),
        key=lambda item: item["path"],
    )
    return hashlib.sha256(
        canonical_json({"profile": "exulanica.preparer-source/v1", "files": files})
    ).hexdigest()


class StaticGlbPreparer:
    """The static GLB profile's preparer: validate, measure, and normalize the JSON chunk."""

    preparer_id: Final = static_glb.PREPARER_ID
    preparer_version: Final = static_glb.PREPARER_VERSION
    input_kind: Final = "workspace_asset"
    #: The evidence report measures preparation at the largest accepted inputs, well under this.
    timeout_seconds: Final = 60.0
    lease_seconds: Final = 120.0
    runs_child_process: Final = False

    def __init__(
        self,
        decode_image: Callable[[bytes], tuple[int, int]] = decode_texture,
        limits: static_glb.StaticGlbLimits = static_glb.LIMITS,
    ) -> None:
        self._decode = decode_image
        self._limits = limits

    def source_sha256(self) -> str:
        return preparer_source_sha256(static_glb, asset_import)

    def available(self) -> bool:
        # Pure Python and the one image decode site: nothing outside this process.
        return True

    def prepare(self, request: PreparationInput) -> PreparationOutput:
        if request.input_bytes is None:
            raise PreparationRefused("malformed_container", "an asset preparation reads bytes")
        parameters = request.parameters
        try:
            prepared = static_glb.prepare_static_glb(
                request.input_bytes,
                unit=parameters["unit"],
                expected_dimensions_mm=parameters.get("expected_dimensions_mm"),
                decode_image=self._decode,
                limits=self._limits,
            )
        except static_glb.StaticGlbRefused as refused:
            raise PreparationRefused(refused.reason, str(refused)) from None
        return PreparationOutput(
            output=prepared.output,
            output_sha256=prepared.output_sha256,
            dimensions_mm=prepared.dimensions_mm,
            placeable=prepared.placeable,
            steps=prepared.steps,
            compatibility=tuple(item.document() for item in prepared.compatibility),
        )

    def recheck(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, request: PreparationInput
    ) -> str | None:
        # An admission's currency is the schema's own question (its withdrawal and its workspace),
        # asked by the record's guard; the static profile adds none.
        del connection, workspace_id, request
        return None


#: Every preparer a worker may run, keyed by the pin a preparation row carries. Fixed in code.
PREPARERS: Final[Mapping[tuple[str, int], Preparer]] = MappingProxyType(
    {
        (StaticGlbPreparer.preparer_id, StaticGlbPreparer.preparer_version): StaticGlbPreparer(),
        (
            CharacterBodyPreparer.preparer_id,
            CharacterBodyPreparer.preparer_version,
        ): CharacterBodyPreparer(),
    }
)


class _Failed(Exception):
    """A preparation that ends ``failed``, with the class the schema names."""

    def __init__(self, failure_class: str, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.code = code


class _Lost(Exception):
    """The claim this record was for is no longer this worker's."""


@dataclass
class PreparationOutcome:
    """What one pass did."""

    prepared: int = 0
    failed: int = 0
    lost: int = 0
    exhausted: int = 0
    failures: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def handled(self) -> int:
        return self.prepared + self.failed + self.lost


@dataclass(frozen=True, slots=True)
class _Claim:
    preparation_id: uuid.UUID
    input_kind: str
    asset_id: uuid.UUID | None
    preparer: tuple[str, int]
    parameters: Mapping[str, Any]
    parameters_sha256: str
    inputs: Mapping[str, Any]
    inputs_sha256: str
    claim_token: uuid.UUID
    recorded_sha256: str | None


def _printable(text: str) -> str:
    return " ".join(
        "".join(character if " " <= character <= "~" else " " for character in line).strip()
        for line in text.splitlines()
        if line.strip()
    )


def _retrying(operation: Callable[[], _T]) -> _T:
    """Run a write again when a delivery held the 0041 read lock; the last failure propagates."""
    for attempt in range(_SERIALIZATION_RETRIES):
        try:
            return operation()
        except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
            if attempt == _SERIALIZATION_RETRIES - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise AssertionError("unreachable")


def canonical_receipt(raw: bytes) -> Any:
    """The receipt's canonical bytes as the document the schema holds equal to them."""
    return json.loads(raw)


class AssetPreparationWorker:
    """Drains ``workspace_preparation`` for a set of workspaces, one preparation at a time."""

    def __init__(
        self,
        database: Database,
        stores: WorkspaceStores,
        workspaces: frozenset[uuid.UUID],
        *,
        preparers: Mapping[tuple[str, int], Preparer] = PREPARERS,
        name: str = "asset-preparation",
        max_attempts: int = 3,
        poll_seconds: float = 5.0,
        limit_per_pass: int = 16,
        workspace_source: Callable[[], Iterable[uuid.UUID]] | None = None,
        retained_bytes_limit: int = DEFAULT_RETAINED_BYTES,
        also: tuple[Callable[[], object], ...] = (),
    ) -> None:
        if not preparers:
            raise ValueError("a preparation worker runs at least one preparer")
        for key, preparer in preparers.items():
            if key != (preparer.preparer_id, preparer.preparer_version):
                raise ValueError(f"{key} is registered under another preparer's pin")
            if preparer.lease_seconds <= preparer.timeout_seconds:
                raise ValueError(f"{key}: a lease must outlast its timeout")
        if max_attempts < 1:
            raise ValueError("a preparation gets at least one attempt")
        runnable = {key: preparer for key, preparer in preparers.items() if preparer.available()}
        if not runnable:
            raise ValueError(
                "no registered preparer can run in this process; a worker that claims nothing "
                "is not healthy"
            )
        self._database = database
        self._stores = stores
        self._workspaces = workspaces
        self._workspace_source = workspace_source
        self._preparers: Mapping[tuple[str, int], Preparer] = MappingProxyType(runnable)
        self._name = name
        self._max_attempts = max_attempts
        self._poll_seconds = poll_seconds
        self._limit = limit_per_pass
        self._retained_bytes_limit = retained_bytes_limit
        #: Further passes this process runs after each of its own, such as the style pack checks.
        self._also = also
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None

    # -- driving it ---------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def preparers(self) -> tuple[str, ...]:
        """The preparers this worker runs, as ``id@version``, sorted."""
        return tuple(sorted(f"{key[0]}@{key[1]}" for key in self._preparers))

    def workspaces(self) -> frozenset[uuid.UUID]:
        discovered = () if self._workspace_source is None else self._workspace_source()
        return self._workspaces | frozenset(discovered)

    def drain(self) -> PreparationOutcome:
        """Prepare what is waiting, one per workspace in turn, up to the pass limit."""
        outcome = PreparationOutcome()
        # A workspace's session is open only while one of its claims is served (and, on its first
        # visit, while its exhausted work is expired), so a pass holds one connection at a time
        # however many workspaces it visits.
        active: list[uuid.UUID] = []
        for workspace_id in sorted(self.workspaces()):
            try:
                with self._database.session(workspace_id) as connection:
                    outcome.exhausted += self._expire_exhausted(connection, workspace_id)
            except Exception as error:
                outcome.errors.append(f"{workspace_id}: {type(error).__name__}: {error}")
                continue
            active.append(workspace_id)
        while active and outcome.handled < self._limit and not self._stop.is_set():
            for workspace_id in list(active):
                if outcome.handled >= self._limit or self._stop.is_set():
                    break
                try:
                    with self._database.session(workspace_id) as connection:
                        claim = self._claim(connection, workspace_id)
                        if claim is None:
                            active.remove(workspace_id)
                            continue
                        self._prepare_one(connection, workspace_id, claim, outcome)
                except Exception as error:
                    outcome.errors.append(f"{workspace_id}: {type(error).__name__}: {error}")
                    active.remove(workspace_id)
        return outcome

    def drain_also(self) -> None:
        """Run the further passes once, as the daemon runs them after each of its own."""
        for drain in self._also:
            drain()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=self._name, daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 30.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.drain()
                for drain in self._also:
                    drain()
                self._last_error = None
            except Exception as error:  # a pass that throws must not end the loop in silence
                self._last_error = f"{type(error).__name__}: {error}"
            self._stop.wait(self._poll_seconds)

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    # -- the queue ----------------------------------------------------------------------

    def _claim(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> _Claim | None:
        """The oldest claimable preparation of the first preparer, in pin order, that has one."""
        for key in sorted(self._preparers):
            claim = _retrying(
                lambda key=key: self._claim_once(connection, workspace_id, key)  # type: ignore[misc]
            )
            if claim is not None:
                return claim
        return None

    def _claim_once(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, key: tuple[str, int]
    ) -> _Claim | None:
        preparer = self._preparers[key]
        with connection.transaction():
            # The lifecycle lock before any row lock, the order a tombstone takes them in.
            connection.execute("select workspace_asset_lifecycle_lock(%s)", (workspace_id,))
            row = connection.execute(
                "update workspace_preparation set state = 'running', "
                "  attempts = attempts + 1, claim_token = gen_random_uuid(), claimed_by = %s, "
                "  lease_expires_at = clock_timestamp() + make_interval(secs => %s) "
                "where workspace_id = %s and preparation_id = ("
                "  select p.preparation_id from workspace_preparation p "
                "   where p.workspace_id = %s "
                "     and (p.state = 'requested' "
                "          or (p.state = 'running' and p.lease_expires_at < clock_timestamp())) "
                "     and p.attempts < %s "
                "     and p.preparer_id = %s and p.preparer_version = %s "
                "     and p.input_kind = %s "
                "     and not tombstone_blocks_workspace_preparation(p.workspace_id, p.asset_id) "
                "   order by p.requested_at, p.preparation_id "
                "   for no key update skip locked limit 1) "
                "returning preparation_id, input_kind, asset_id, preparer_id, preparer_version, "
                "  parameters_document, parameters_sha256, inputs_document, inputs_sha256, "
                "  claim_token, output_sha256",
                (
                    self._name,
                    preparer.lease_seconds,
                    workspace_id,
                    workspace_id,
                    self._max_attempts,
                    key[0],
                    key[1],
                    preparer.input_kind,
                ),
            ).fetchone()
        if row is None:
            return None
        return _Claim(
            preparation_id=row["preparation_id"],
            input_kind=row["input_kind"],
            asset_id=row["asset_id"],
            preparer=(row["preparer_id"], row["preparer_version"]),
            parameters=row["parameters_document"],
            parameters_sha256=bytes(row["parameters_sha256"]).hex(),
            inputs=row["inputs_document"],
            inputs_sha256=bytes(row["inputs_sha256"]).hex(),
            claim_token=row["claim_token"],
            recorded_sha256=row["output_sha256"],
        )

    def _expire_exhausted(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
        """A preparation whose every attempt died with its lease is failed, visibly."""

        def expire() -> int:
            with connection.transaction():
                connection.execute("select workspace_asset_lifecycle_lock(%s)", (workspace_id,))
                cursor = connection.execute(
                    "update workspace_preparation set state = 'failed', "
                    "  claim_token = null, claimed_by = null, lease_expires_at = null, "
                    "  failure_class = 'exhausted', failure_code = null, "
                    "  failure_message = 'every attempt ended without finishing' "
                    "where workspace_id = %s and state = 'running' "
                    "  and lease_expires_at < clock_timestamp() and attempts >= %s",
                    (workspace_id, self._max_attempts),
                )
            return cursor.rowcount

        return _retrying(expire)

    def _finish_failed(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        claim: _Claim,
        failed: _Failed,
    ) -> bool:
        def finish() -> bool:
            with connection.transaction():
                connection.execute("select workspace_asset_lifecycle_lock(%s)", (workspace_id,))
                cursor = connection.execute(
                    "update workspace_preparation set state = 'failed', "
                    "  claim_token = null, claimed_by = null, lease_expires_at = null, "
                    "  failure_class = %s, failure_code = %s, failure_message = %s "
                    "where workspace_id = %s and preparation_id = %s and state = 'running' "
                    "  and claim_token = %s",
                    (
                        failed.failure_class,
                        failed.code,
                        _printable(str(failed))[:2000],
                        workspace_id,
                        claim.preparation_id,
                        claim.claim_token,
                    ),
                )
            return cursor.rowcount == 1

        return _retrying(finish)

    # -- one preparation ----------------------------------------------------------------

    def _prepare_one(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        claim: _Claim,
        outcome: PreparationOutcome,
    ) -> None:
        try:
            request, made, receipt = self._made(connection, workspace_id, claim)
            recorded = self._record_and_write(
                connection, workspace_id, claim, request, made, receipt
            )
        except _Failed as failed:
            outcome.failures.append(f"{claim.preparation_id}: {failed.failure_class}: {failed}")
            if self._finish_failed(connection, workspace_id, claim, failed):
                outcome.failed += 1
            else:
                outcome.lost += 1
            return
        if recorded:
            outcome.prepared += 1
        else:
            outcome.lost += 1

    def _made(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, claim: _Claim
    ) -> tuple[PreparationInput, PreparationOutput, dict[str, Any]]:
        input_bytes: bytes | None = None
        if claim.input_kind == "workspace_asset":
            asset = connection.execute(
                "select input_sha256, input_byte_size, declaration_sha256 from workspace_asset "
                "where workspace_id = %s and asset_id = %s",
                (workspace_id, claim.asset_id),
            ).fetchone()
            if asset is None or asset["input_sha256"] != claim.inputs.get("input_sha256"):
                raise _Failed("input_bytes_missing", "the preparation names no admission here")
            try:
                input_bytes = self._stores.for_workspace(workspace_id).get(
                    BlobId.from_hex(asset["input_sha256"])
                )
            except (BlobNotFoundError, IntegrityError) as error:
                raise _Failed(
                    "input_bytes_missing",
                    f"the admitted bytes cannot be read: {type(error).__name__}",
                ) from None
            if len(input_bytes) != asset["input_byte_size"]:
                raise _Failed(
                    "input_bytes_missing", "the admitted bytes are not the length recorded"
                )
            receipt_input: dict[str, Any] = {
                "content_sha256": asset["input_sha256"],
                "byte_size": asset["input_byte_size"],
                "declaration_sha256": bytes(asset["declaration_sha256"]).hex(),
            }
        else:
            receipt_input = dict(claim.inputs)
        request = PreparationInput(
            workspace_id=workspace_id,
            preparation_id=claim.preparation_id,
            input_kind=claim.input_kind,
            parameters=claim.parameters,
            inputs=claim.inputs,
            input_bytes=input_bytes,
        )
        preparer = self._preparers[claim.preparer]
        started = time.monotonic()
        try:
            made = preparer.prepare(request)
        except PreparationRefused as refused:
            raise _Failed(refused.failure_class, str(refused), code=refused.code) from None
        elapsed = time.monotonic() - started
        if elapsed > preparer.timeout_seconds:
            raise _Failed(
                "timed_out",
                f"preparation took {elapsed:.1f} s, over {preparer.timeout_seconds:g} s",
            )
        if hashlib.sha256(made.output).hexdigest() != made.output_sha256:
            raise _Failed("unverified_output", "the output is not the digest the preparer stated")
        if claim.recorded_sha256 is not None and claim.recorded_sha256 != made.output_sha256:
            raise _Failed(
                "nondeterministic",
                f"the preparation made {made.output_sha256}, and {claim.recorded_sha256} is "
                "recorded",
            )
        receipt: dict[str, Any] = {
            "profile": RECEIPT_PROFILE,
            "asset_id": None if claim.asset_id is None else str(claim.asset_id),
            "input_kind": claim.input_kind,
            "preparer": {
                "id": claim.preparer[0],
                "version": claim.preparer[1],
                "source_sha256": preparer.source_sha256(),
            },
            "parameters_sha256": claim.parameters_sha256,
            "inputs_sha256": claim.inputs_sha256,
            "input": receipt_input,
            "steps": [dict(step) for step in made.steps],
            "output": {"content_sha256": made.output_sha256, "byte_size": len(made.output)},
            "compatibility": [dict(item) for item in made.compatibility],
        }
        if claim.input_kind == "workspace_asset":
            receipt["use_policy"] = USE_POLICY
        if made.descriptor is not None:
            receipt["descriptor"] = dict(made.descriptor)
        return request, made, receipt

    def _record_and_write(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        claim: _Claim,
        request: PreparationInput,
        made: PreparationOutput,
        receipt: Mapping[str, Any],
    ) -> bool:
        raw = canonical_json(receipt)
        with object_lock(connection, workspace_asset_lock_key(workspace_id, made.output_sha256)):
            if not self._record(connection, workspace_id, claim, request, made, raw):
                return False
            store = self._stores.for_workspace(workspace_id)
            written = store.put_bytes(made.output)
            digest = BlobId.from_hex(made.output_sha256)
            if written.blob_id != digest or not store.exists(digest):
                raise IntegrityError(f"{claim.preparation_id} was not stored under its digest")
        return True

    def _record(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        claim: _Claim,
        request: PreparationInput,
        made: PreparationOutput,
        raw: bytes,
    ) -> bool:
        """Mark the preparation done, in its own transaction, before a byte is written.

        Raises :class:`_Failed` ``stale`` when the preparer's own inputs no longer hold; the
        transaction is rolled back and nothing is written.
        """
        dimensions = made.dimensions_mm
        preparer = self._preparers[claim.preparer]
        for attempt in range(_SERIALIZATION_RETRIES):
            try:
                with connection.transaction():
                    connection.execute("select workspace_asset_lifecycle_lock(%s)", (workspace_id,))
                    stale = preparer.recheck(connection, workspace_id, request)
                    if stale is not None:
                        raise _Failed("stale", stale)
                    over = retained_bytes_refusal(
                        connection,
                        workspace_id,
                        made.output_sha256,
                        len(made.output),
                        self._retained_bytes_limit,
                    )
                    if over is not None:
                        raise _Failed("quota_exceeded", over, code="workspace_asset_quota_exceeded")
                    connection.execute(
                        "insert into workspace_asset_blob (workspace_id, content_sha256, "
                        "  byte_size) values (%s, %s, %s) "
                        "on conflict (workspace_id, content_sha256) do nothing",
                        (workspace_id, made.output_sha256, len(made.output)),
                    )
                    if claim.recorded_sha256 is None:
                        cursor = connection.execute(
                            "update workspace_preparation set state = 'prepared', "
                            "  claim_token = null, claimed_by = null, lease_expires_at = null, "
                            "  output_sha256 = %s, output_byte_size = %s, width_mm = %s, "
                            "  height_mm = %s, depth_mm = %s, placeable = %s, "
                            "  receipt_canonical = %s, receipt_document = %s, "
                            "  receipt_sha256 = %s, prepared_at = statement_timestamp() "
                            "where workspace_id = %s and preparation_id = %s "
                            "  and state = 'running' and claim_token = %s",
                            (
                                made.output_sha256,
                                len(made.output),
                                dimensions["width"],
                                dimensions["height"],
                                dimensions["depth"],
                                made.placeable,
                                raw,
                                Jsonb(canonical_receipt(raw)),
                                hashlib.sha256(raw).digest(),
                                workspace_id,
                                claim.preparation_id,
                                claim.claim_token,
                            ),
                        )
                    else:
                        # A re-run keeps the receipt already recorded: the bytes are the same, and
                        # the record of how they were first made is not rewritten.
                        cursor = connection.execute(
                            "update workspace_preparation set state = 'prepared', "
                            "  claim_token = null, claimed_by = null, lease_expires_at = null "
                            "where workspace_id = %s and preparation_id = %s "
                            "  and state = 'running' and claim_token = %s and output_sha256 = %s",
                            (
                                workspace_id,
                                claim.preparation_id,
                                claim.claim_token,
                                made.output_sha256,
                            ),
                        )
                    if cursor.rowcount != 1:
                        # The claim was cancelled, withdrawn or reclaimed: publish nothing, and
                        # let the transaction's inventory row go with it.
                        raise _Lost
                return True
            except _Lost:
                return False
            except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
                time.sleep(0.05 * (attempt + 1))
            except psycopg.errors.IntegrityConstraintViolation as error:
                if (error.diag.message_primary or "").startswith("tombstoned"):
                    return False
                raise
        raise RuntimeError(
            f"{claim.preparation_id}: the record kept meeting deliveries in progress"
        )
