"""The one server-side bake path: claim, bake in a process of its own, check, record, then write.

A person's recipe becomes texels in ``web/packages/loom-texture``, because the makers are
TypeScript and the bytes must be the bytes the published library's bake would produce. The baker
is a pure function with no database, no network and no store (``src/workspace/cli.ts``). This
module is everything around it, and every step is a decision:

1.  **Claim with a lease**, in the 0016 shape: a requested bake, or a running one whose lease
    expired, that no deletion has reached, taken ``for update skip locked`` with a fresh token.
    The lease outlasts the wall-clock limit, so a live bake is never reclaimed from under itself.
2.  **Check the recipe again before spawning anything**: canonical bytes that hash to the row's
    digest, a maker version :data:`PUBLISHED_MAKER_MANIFESTS` pins, and nothing
    :func:`~exulanica.materials.recipe_problems` refuses. A recipe that fails is a failed bake, and
    no process starts.
3.  **Bake under limits.** The baker runs in a new session with a minimal environment, a V8 heap
    ceiling, a wall-clock timeout and a resident-memory ceiling this module measures and enforces
    itself, killing the whole process group on either. Nothing else in the repository limits a
    child process, and macOS enforces no kernel memory limit on one, so the watchdog is the limit
    that holds everywhere; a deployment adds the container's own (``deploy/material-bake/``).
4.  **Believe nothing it prints.** The result is read strictly; the container must have that
    length and hash; :func:`~exulanica.world.texture_assets.verify_container` holds it to the
    request, the recipe and the maker exactly as a published set is held; the package source
    digest it claims must be the one this process computes from the same files; and a re-bake must
    reproduce the digest already recorded.
5.  **Record, then write**, which is the ingest path's ``committed_writes`` order. Under a session
    lock on the object that the purger also takes, the row becomes ``baked`` (the schema refuses
    if a deletion reached the recipe), and only then are the bytes put into the workspace's own
    store namespace. A crash between leaves a row whose bytes are missing, which a new request
    re-bakes; it never leaves bytes no row names, which no deletion could find.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, TypeVar

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.db.session import Database
from exulanica.errors import IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.materials import (
    MaterialCatalog,
    MaterialObjectError,
    canonical_bytes,
    read_object,
    recipe_problems,
    thaw,
)
from exulanica.materials.classes import TEXTURE_SET_PROFILE_V1, V1_LAYOUT
from exulanica.materials.manifest import ManifestEntry
from exulanica.materials.workspace import (
    MAXIMUM_WORKSPACE_TEXELS,
    WORKSPACE_LICENCE_ID,
    WORKSPACE_LICENCE_SHA256,
    WORKSPACE_VERSION,
    bake_receipt,
    bake_request,
    read_bake_result,
)
from exulanica.store.namespaces import WorkspaceStores
from exulanica.world.texture_assets import (
    PUBLISHED_MAKER_MANIFESTS,
    TextureCatalogError,
    load_material_catalog,
    verify_container,
)

__all__ = [
    "BAKE_ENTRY",
    "SOURCE_PROFILE",
    "BakeLimits",
    "BakeOutcome",
    "BakeRun",
    "BakeRuntime",
    "BakeRuntimeUnavailable",
    "MaterialBakeWorker",
    "package_source_sha256",
    "run_baker",
]

_REPOSITORY: Final = Path(__file__).resolve().parents[2]
_WEB: Final = _REPOSITORY / "web"
_PACKAGE: Final = _WEB / "packages" / "loom-texture"
#: The baker's entry point, relative to the package.
BAKE_ENTRY: Final = ("src", "workspace", "cli.ts")
#: The package source digest's profile and roots, as ``src/workspace/source.ts`` states them.
SOURCE_PROFILE: Final = "exulanica.loom-texture-source/v1"
_SOURCE_ROOTS: Final = ("package.json", "src", "library", "licences")
_MIB: Final = 1 << 20
#: The container's fixed cost beyond its texels: magic, length, header, padding. Generous.
_HEADER_ALLOWANCE: Final = 1 * _MIB
#: The baker's exit status for a request it refused rather than failed on.
_REFUSED: Final = 2
_T = TypeVar("_T")


class BakeRuntimeUnavailable(RuntimeError):
    """The baker cannot be run here: no Node, no loader, no package, or no way to limit it."""


@dataclass(frozen=True, slots=True)
class BakeLimits:
    """What one bake may use. Measured: a 1024 x 1024 brick bakes in 2.3 s at 119 MiB resident."""

    timeout_seconds: float = 60.0
    memory_bytes: int = 768 * _MIB
    heap_megabytes: int = 512
    poll_seconds: float = 0.025
    output_bytes: int = MAXIMUM_WORKSPACE_TEXELS * 10 + _HEADER_ALLOWANCE
    result_bytes: int = 4096
    stderr_bytes: int = 16384

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 3600:
            raise ValueError("a bake's timeout is positive and at most an hour")
        if self.memory_bytes < 64 * _MIB or self.heap_megabytes < 16:
            raise ValueError("a bake needs at least 64 MiB and a 16 MiB heap to start")
        if not 0 < self.poll_seconds <= 1:
            raise ValueError("the watchdog looks at least once a second")


@dataclass(frozen=True, slots=True)
class BakeRuntime:
    """How to start the baker: Node, the TypeScript loader, and the package it runs from."""

    node: Path
    loader: Path
    package: Path

    @classmethod
    def from_checkout(cls, node: str | None = None, web: Path = _WEB) -> BakeRuntime:
        """The baker in this checkout, run from source so the source digest names what ran."""
        executable = node or os.environ.get("EXULANICA_NODE") or shutil.which("node")
        if executable is None:
            raise BakeRuntimeUnavailable("no node executable on PATH or in EXULANICA_NODE")
        loader = web / "node_modules" / "tsx" / "dist" / "loader.mjs"
        package = web / "packages" / "loom-texture"
        for path, what in (
            (loader, "the tsx loader"),
            (package.joinpath(*BAKE_ENTRY), "the baker"),
        ):
            if not path.is_file():
                raise BakeRuntimeUnavailable(f"{what} is not at {path}")
        return cls(node=Path(executable), loader=loader, package=package)

    def argv(self, limits: BakeLimits, request: Path, out: Path) -> list[str]:
        return [
            str(self.node),
            f"--max-old-space-size={limits.heap_megabytes}",
            "--import",
            self.loader.as_uri(),
            str(self.package.joinpath(*BAKE_ENTRY)),
            "--request",
            str(request),
            "--out",
            str(out),
        ]


def package_source_sha256(package: Path = _PACKAGE) -> str:
    """The digest ``src/workspace/source.ts`` computes, computed here from the same files."""
    files: list[dict[str, str]] = []

    def walk(relative: str) -> None:
        absolute = package.joinpath(*relative.split("/"))
        if absolute.is_symlink():
            raise IntegrityError(f"{relative} is a link; the source digest follows none")
        if absolute.is_dir():
            for child in absolute.iterdir():
                if not child.name.startswith("."):
                    walk(f"{relative}/{child.name}")
            return
        if not absolute.is_file():
            raise IntegrityError(f"{relative} is not a file")
        files.append(
            {"path": relative, "sha256": hashlib.sha256(absolute.read_bytes()).hexdigest()}
        )

    for root in _SOURCE_ROOTS:
        walk(root)
    files.sort(key=lambda item: item["path"])
    return hashlib.sha256(canonical_json({"profile": SOURCE_PROFILE, "files": files})).hexdigest()


# -- measuring a child's memory without a dependency -------------------------------------------


class _RusageInfoV2(ctypes.Structure):
    _fields_ = [
        ("ri_uuid", ctypes.c_uint8 * 16),
        ("ri_user_time", ctypes.c_uint64),
        ("ri_system_time", ctypes.c_uint64),
        ("ri_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_interrupt_wkups", ctypes.c_uint64),
        ("ri_pageins", ctypes.c_uint64),
        ("ri_wired_size", ctypes.c_uint64),
        ("ri_resident_size", ctypes.c_uint64),
        ("ri_phys_footprint", ctypes.c_uint64),
        ("ri_proc_start_abstime", ctypes.c_uint64),
        ("ri_proc_exit_abstime", ctypes.c_uint64),
        ("ri_child_user_time", ctypes.c_uint64),
        ("ri_child_system_time", ctypes.c_uint64),
        ("ri_child_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_child_interrupt_wkups", ctypes.c_uint64),
        ("ri_child_pageins", ctypes.c_uint64),
        ("ri_child_elapsed_abstime", ctypes.c_uint64),
        ("ri_diskio_bytesread", ctypes.c_uint64),
        ("ri_diskio_byteswritten", ctypes.c_uint64),
    ]


_RUSAGE_INFO_V2: Final = 2


def _memory_reader() -> Any:
    """A function from a pid to its resident bytes, or None where this platform offers none."""
    if sys.platform.startswith("linux"):
        page = os.sysconf("SC_PAGE_SIZE")

        def linux(pid: int) -> int | None:
            try:
                with open(f"/proc/{pid}/statm", encoding="ascii") as handle:
                    return int(handle.read().split()[1]) * page
            except (OSError, ValueError, IndexError):
                return None

        return linux
    if sys.platform == "darwin":
        library = ctypes.util.find_library("proc")
        if library is None:
            return None
        libproc = ctypes.CDLL(library, use_errno=True)
        libproc.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        libproc.proc_pid_rusage.restype = ctypes.c_int

        def darwin(pid: int) -> int | None:
            info = _RusageInfoV2()
            if libproc.proc_pid_rusage(pid, _RUSAGE_INFO_V2, ctypes.byref(info)) != 0:
                return None
            # The footprint counts compressed memory, which the resident size does not.
            return max(int(info.ri_resident_size), int(info.ri_phys_footprint))

        return darwin
    return None


_READ_MEMORY: Final = _memory_reader()


@dataclass(frozen=True, slots=True)
class BakeRun:
    """What one run of the baker did, before anything it produced is believed."""

    returncode: int | None
    stdout: bytes
    stderr: bytes
    container: bytes | None
    peak_memory_bytes: int
    elapsed_seconds: float
    #: ``timed_out`` or ``over_memory`` when the watchdog stopped it, otherwise None.
    stopped: str | None


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)


def _bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(limit + 1)


def run_baker(runtime: BakeRuntime, limits: BakeLimits, request: bytes) -> BakeRun:
    """Run the baker once on ``request``, under the limits, and collect what it left."""
    if _READ_MEMORY is None:
        raise BakeRuntimeUnavailable(
            f"no way to measure a child's memory on {sys.platform}, so no bake runs here"
        )
    with tempfile.TemporaryDirectory(prefix="exulanica-bake-") as scratch:
        work = Path(scratch)
        request_path = work / "request.json"
        out_path = work / "container.ltex"
        request_path.write_bytes(request)
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(work),
            "TMPDIR": str(work),
            "LANG": "C",
            "TZ": "UTC",
        }
        with (work / "stdout").open("w+b") as stdout, (work / "stderr").open("w+b") as stderr:
            started = time.monotonic()
            process = subprocess.Popen(
                runtime.argv(limits, request_path, out_path),
                cwd=runtime.package,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            peak = 0
            stopped: str | None = None
            try:
                while process.poll() is None:
                    resident = _READ_MEMORY(process.pid)
                    if resident is not None:
                        peak = max(peak, resident)
                    if resident is not None and resident > limits.memory_bytes:
                        stopped = "over_memory"
                    elif time.monotonic() - started > limits.timeout_seconds:
                        stopped = "timed_out"
                    if stopped is not None:
                        _kill_group(process)
                        break
                    time.sleep(limits.poll_seconds)
            finally:
                if process.poll() is None:
                    _kill_group(process)
            elapsed = time.monotonic() - started
            stdout.seek(0)
            stderr.seek(0)
            out = stdout.read(limits.result_bytes + 1)
            err = stderr.read(limits.stderr_bytes)
        container = None
        if stopped is None and out_path.is_file():
            container = _bounded(out_path, limits.output_bytes)
        return BakeRun(
            returncode=process.returncode,
            stdout=out,
            stderr=err,
            container=container,
            peak_memory_bytes=peak,
            elapsed_seconds=elapsed,
            stopped=stopped,
        )


# -- the worker ------------------------------------------------------------------------------


class _Failed(Exception):
    """A bake that ends ``failed``, with the class the schema names.

    ``detail`` is for the operator's log and never reaches the row a workspace can read.
    """

    def __init__(self, failure_class: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.detail = detail


@dataclass
class BakeOutcome:
    """What one pass did."""

    baked: int = 0
    failed: int = 0
    lost: int = 0
    exhausted: int = 0
    failures: list[str] = field(default_factory=list)
    #: Workspaces a pass stopped serving because something unexpected happened, and what.
    errors: list[str] = field(default_factory=list)

    @property
    def handled(self) -> int:
        return self.baked + self.failed + self.lost


@dataclass(frozen=True, slots=True)
class _Claim:
    bake_id: uuid.UUID
    recipe_id: uuid.UUID
    set_id: str
    claim_token: uuid.UUID
    recorded_sha256: str | None


_SERIALIZATION_RETRIES: Final = 5


def _printable(text: str) -> str:
    """Only printable ASCII, lines joined, so a refusal can never carry a control byte."""
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


@contextlib.contextmanager
def _session_lock(connection: psycopg.Connection, ref: str) -> Iterator[None]:
    """The session form of ``purge_lock_object``: held across the row commit and the write."""
    connection.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (ref,))
    try:
        yield
    finally:
        row = connection.execute(
            "select pg_advisory_unlock(hashtextextended(%s, 0)) as unlocked", (ref,)
        ).fetchone()
        if row is None or row["unlocked"] is not True:
            raise RuntimeError("a stored-object advisory lock was not held")


class MaterialBakeWorker:
    """Drains ``material_bake`` for a fixed set of workspaces."""

    def __init__(
        self,
        database: Database,
        stores: WorkspaceStores,
        workspaces: frozenset[uuid.UUID],
        *,
        runtime: BakeRuntime,
        catalog: MaterialCatalog | None = None,
        limits: BakeLimits | None = None,
        name: str = "material-bake",
        lease_seconds: float | None = None,
        max_attempts: int = 3,
        poll_seconds: float = 15.0,
        limit_per_pass: int = 16,
        workspace_source: Callable[[], Iterable[uuid.UUID]] | None = None,
    ) -> None:
        self._database = database
        self._stores = stores
        self._workspaces = workspaces
        self._workspace_source = workspace_source
        self._runtime = runtime
        self._catalog = catalog if catalog is not None else load_material_catalog()
        self._limits = limits if limits is not None else BakeLimits()
        self._name = name
        self._lease = (
            lease_seconds if lease_seconds is not None else self._limits.timeout_seconds + 60.0
        )
        if self._lease <= self._limits.timeout_seconds + 5:
            raise ValueError("a bake's lease must outlast its timeout, or a live bake is reclaimed")
        if max_attempts < 1:
            raise ValueError("a bake gets at least one attempt")
        self._max_attempts = max_attempts
        self._poll_seconds = poll_seconds
        self._limit = limit_per_pass
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None

    # -- driving it ---------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def workspaces(self) -> frozenset[uuid.UUID]:
        """The configured workspaces and, when a source is set, the ones it names right now."""
        discovered = () if self._workspace_source is None else self._workspace_source()
        return self._workspaces | frozenset(discovered)

    def drain(self) -> BakeOutcome:
        """Bake what is waiting, one bake per workspace in turn, up to the pass limit.

        In turn, so one busy workspace cannot take every bake a pass allows; and each workspace
        on its own, so an error in one is recorded and the others are still served.
        """
        outcome = BakeOutcome()
        with contextlib.ExitStack() as sessions:
            active: dict[uuid.UUID, psycopg.Connection] = {}
            for workspace_id in sorted(self.workspaces()):
                try:
                    connection = sessions.enter_context(self._database.session(workspace_id))
                    outcome.exhausted += self._expire_exhausted(connection, workspace_id)
                except Exception as error:
                    outcome.errors.append(f"{workspace_id}: {type(error).__name__}: {error}")
                    continue
                active[workspace_id] = connection
            while active and outcome.handled < self._limit and not self._stop.is_set():
                for workspace_id, connection in list(active.items()):
                    if outcome.handled >= self._limit or self._stop.is_set():
                        break
                    try:
                        claim = self._claim(connection, workspace_id)
                        if claim is None:
                            del active[workspace_id]
                            continue
                        self._bake_one(connection, workspace_id, claim, outcome)
                    except Exception as error:
                        outcome.errors.append(f"{workspace_id}: {type(error).__name__}: {error}")
                        del active[workspace_id]
        return outcome

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
        return _retrying(lambda: self._claim_once(connection, workspace_id))

    def _claim_once(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> _Claim | None:
        with connection.transaction():
            # The lifecycle lock before any row lock, the order a tombstone takes them in.
            connection.execute("select material_bake_lifecycle_lock(%s)", (workspace_id,))
            row = connection.execute(
                "update material_bake set state = 'running', attempts = attempts + 1, "
                "  claim_token = gen_random_uuid(), claimed_by = %s, "
                "  lease_expires_at = clock_timestamp() + make_interval(secs => %s) "
                "where workspace_id = %s and bake_id = ("
                "  select b.bake_id from material_bake b "
                "   where b.workspace_id = %s "
                "     and (b.state = 'requested' "
                "          or (b.state = 'running' and b.lease_expires_at < clock_timestamp())) "
                "     and b.attempts < %s "
                "     and not tombstone_blocks_material_bake(b.workspace_id, b.bake_id) "
                "   order by b.requested_at, b.bake_id "
                "   for update skip locked limit 1) "
                "returning bake_id, recipe_id, set_id, claim_token, content_sha256",
                (self._name, self._lease, workspace_id, workspace_id, self._max_attempts),
            ).fetchone()
        if row is None:
            return None
        recorded = row["content_sha256"]
        return _Claim(
            bake_id=row["bake_id"],
            recipe_id=row["recipe_id"],
            set_id=row["set_id"],
            claim_token=row["claim_token"],
            recorded_sha256=None if recorded is None else bytes(recorded).hex(),
        )

    def _expire_exhausted(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
        """A bake whose every attempt died with its lease is failed, visibly, not retried."""
        return _retrying(lambda: self._expire_exhausted_once(connection, workspace_id))

    def _expire_exhausted_once(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID
    ) -> int:
        with connection.transaction():
            cursor = connection.execute(
                "update material_bake set state = 'failed', claim_token = null, "
                "  claimed_by = null, lease_expires_at = null, failure_class = 'exhausted', "
                "  failure_message = 'every attempt ended without finishing' "
                "where workspace_id = %s and state = 'running' "
                "  and lease_expires_at < clock_timestamp() and attempts >= %s",
                (workspace_id, self._max_attempts),
            )
        return cursor.rowcount

    def _finish_failed(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        claim: _Claim,
        failed: _Failed,
    ) -> bool:
        return _retrying(lambda: self._finish_failed_once(connection, workspace_id, claim, failed))

    def _finish_failed_once(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        claim: _Claim,
        failed: _Failed,
    ) -> bool:
        with connection.transaction():
            cursor = connection.execute(
                "update material_bake set state = 'failed', claim_token = null, "
                "  claimed_by = null, lease_expires_at = null, failure_class = %s, "
                "  failure_message = %s "
                "where workspace_id = %s and bake_id = %s and state = 'running' "
                "  and claim_token = %s",
                (
                    failed.failure_class,
                    str(failed)[:2000],
                    workspace_id,
                    claim.bake_id,
                    claim.claim_token,
                ),
            )
        return cursor.rowcount == 1

    # -- one bake -----------------------------------------------------------------------

    def _bake_one(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        claim: _Claim,
        outcome: BakeOutcome,
    ) -> None:
        try:
            request, recipe_sha256, maker_sha256, recipe, manifest = self._request(
                connection, workspace_id, claim
            )
            run = run_baker(self._runtime, self._limits, canonical_bytes(request))
            container, result = self._verified(run, request, recipe, manifest, claim)
            receipt = bake_receipt(
                request=request,
                maker_sha256=maker_sha256,
                recipe_sha256=recipe_sha256,
                result=result,
            )
        except _Failed as failed:
            outcome.failures.append(
                f"{claim.set_id}: {failed.failure_class}: {failed}"
                + (f" ({failed.detail})" if failed.detail else "")
            )
            if self._finish_failed(connection, workspace_id, claim, failed):
                outcome.failed += 1
            else:
                outcome.lost += 1
            return
        if self._record_and_write(connection, workspace_id, claim, container, receipt):
            outcome.baked += 1
        else:
            outcome.lost += 1

    def _request(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, claim: _Claim
    ) -> tuple[dict[str, Any], str, str, Any, Any]:
        row = connection.execute(
            "select recipe_canonical, recipe_sha256, maker_id, maker_version, maker_sha256 "
            "from material_recipe where workspace_id = %s and recipe_id = %s",
            (workspace_id, claim.recipe_id),
        ).fetchone()
        if row is None:
            raise _Failed("invalid_recipe", "the bake names no recipe this workspace holds")
        raw = bytes(row["recipe_canonical"])
        recipe_sha256 = bytes(row["recipe_sha256"]).hex()
        maker_sha256 = bytes(row["maker_sha256"]).hex()
        identity = (row["maker_id"], row["maker_version"])
        try:
            recipe = read_object(raw, "recipe")
        except MaterialObjectError as error:
            raise _Failed("invalid_recipe", str(error)) from error
        published = self._catalog.makers.get(identity)
        if (
            hashlib.sha256(raw).hexdigest() != recipe_sha256
            or PUBLISHED_MAKER_MANIFESTS.get(identity) != maker_sha256
            or published is None
            or published.sha256 != maker_sha256
        ):
            raise _Failed(
                "invalid_recipe",
                "the recipe is not its recorded digest, or its maker is not the published one",
            )
        problems = recipe_problems(recipe, published.manifest)
        if problems:
            raise _Failed("invalid_recipe", "; ".join(problems))
        request = bake_request(recipe_id=claim.recipe_id, recipe=recipe, maker_sha256=maker_sha256)
        if request["set_id"] != claim.set_id:
            raise _Failed("invalid_recipe", "the bake's set id does not name its recipe")
        return request, recipe_sha256, maker_sha256, recipe, published.manifest

    def _verified(
        self,
        run: BakeRun,
        request: dict[str, Any],
        recipe: Any,
        manifest: Any,
        claim: _Claim,
    ) -> tuple[bytes, Any]:
        if run.stopped == "timed_out":
            raise _Failed("timed_out", f"stopped after {self._limits.timeout_seconds:g} s")
        if run.stopped == "over_memory":
            raise _Failed(
                "over_memory",
                f"stopped at {run.peak_memory_bytes} bytes resident, over "
                f"{self._limits.memory_bytes}",
            )
        if run.returncode == _REFUSED:
            # The baker's refusals are its own sentences about the person's own recipe; anything
            # else it printed is kept out of the row, which the workspace can read.
            reasons = _printable(run.stderr.decode("utf-8", "replace"))[:500]
            raise _Failed("invalid_recipe", f"the baker refused the request: {reasons}")
        if run.returncode != 0:
            raise _Failed(
                "bake_failed",
                f"the baker exited {run.returncode}",
                detail=_printable(run.stderr.decode("utf-8", "replace"))[-500:],
            )
        try:
            if len(run.stdout) > self._limits.result_bytes:
                raise MaterialObjectError("the result is longer than any result")
            result = read_bake_result(run.stdout)
            container = run.container
            if container is None or len(container) > self._limits.output_bytes:
                raise MaterialObjectError("no container, or one longer than any set")
            resolution = recipe["resolution"]
            extent = recipe["extent_mm"]
            verify_container(
                container,
                expected=ManifestEntry(
                    set_id=request["set_id"],
                    version=WORKSPACE_VERSION,
                    content_sha256=result.content_sha256,
                    byte_size=result.byte_size,
                    width=resolution["width"],
                    height=resolution["height"],
                    extent_u_mm=extent["u"],
                    extent_v_mm=extent["v"],
                    licence_id=WORKSPACE_LICENCE_ID,
                    licence_sha256=WORKSPACE_LICENCE_SHA256,
                    # The workspace baker writes the published v1 makers' containers only.
                    container_profile=TEXTURE_SET_PROFILE_V1,
                    material_class="opaque",
                    maps=V1_LAYOUT,
                ),
                title=request["title"],
                summary=request["summary"],
                recipe=recipe,
                manifest=manifest,
            )
            source = package_source_sha256(self._runtime.package)
            if result.package_sha256 != source:
                raise MaterialObjectError(
                    f"the baker ran package source {result.package_sha256}, and the files here "
                    f"are {source}"
                )
        except (MaterialObjectError, TextureCatalogError, IntegrityError) as error:
            raise _Failed("unverified_output", str(error)) from error
        if claim.recorded_sha256 is not None and claim.recorded_sha256 != result.content_sha256:
            raise _Failed(
                "nondeterministic",
                f"the recipe baked to {result.content_sha256}, and {claim.recorded_sha256} is "
                "recorded",
            )
        return container, result

    def _record_and_write(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        claim: _Claim,
        container: bytes,
        receipt: dict[str, Any],
    ) -> bool:
        digest = hashlib.sha256(container).digest()
        receipt_raw = canonical_json(receipt)
        with _session_lock(connection, digest.hex()):
            if not self._record(connection, workspace_id, claim, digest, container, receipt_raw):
                return False
            store = self._stores.for_workspace(workspace_id)
            written = store.put_bytes(container)
            if written.blob_id != BlobId(digest) or not store.exists(BlobId(digest)):
                raise IntegrityError(f"{claim.set_id} was not stored under its digest")
        return True

    def _record(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        claim: _Claim,
        digest: bytes,
        container: bytes,
        receipt_raw: bytes,
    ) -> bool:
        """Mark the bake done, in its own transaction, before a byte is written."""
        for attempt in range(_SERIALIZATION_RETRIES):
            try:
                with connection.transaction():
                    connection.execute("select material_bake_lifecycle_lock(%s)", (workspace_id,))
                    if claim.recorded_sha256 is None:
                        cursor = connection.execute(
                            "update material_bake set state = 'baked', claim_token = null, "
                            "  claimed_by = null, lease_expires_at = null, "
                            "  content_sha256 = %s, byte_size = %s, receipt_canonical = %s, "
                            "  receipt_document = %s, receipt_sha256 = %s, "
                            "  baked_at = statement_timestamp() "
                            "where workspace_id = %s and bake_id = %s and state = 'running' "
                            "  and claim_token = %s",
                            (
                                digest,
                                len(container),
                                receipt_raw,
                                Jsonb(thaw(read_object(receipt_raw, "receipt"))),
                                hashlib.sha256(receipt_raw).digest(),
                                workspace_id,
                                claim.bake_id,
                                claim.claim_token,
                            ),
                        )
                    else:
                        # A re-bake keeps the receipt already recorded: the bytes are the same,
                        # and the record of how they were first made is not rewritten.
                        cursor = connection.execute(
                            "update material_bake set state = 'baked', claim_token = null, "
                            "  claimed_by = null, lease_expires_at = null "
                            "where workspace_id = %s and bake_id = %s and state = 'running' "
                            "  and claim_token = %s and content_sha256 = %s",
                            (workspace_id, claim.bake_id, claim.claim_token, digest),
                        )
                return cursor.rowcount == 1
            except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
                # A delivery held the 0041 read lock, or a deletion won a lock race. The write is
                # safe to try again.
                time.sleep(0.05 * (attempt + 1))
            except psycopg.errors.IntegrityConstraintViolation as error:
                if (error.diag.message_primary or "").startswith("tombstoned"):
                    return False
                raise
        raise RuntimeError(f"{claim.set_id}: the record kept meeting deliveries in progress")
