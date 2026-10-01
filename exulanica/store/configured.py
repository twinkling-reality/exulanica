"""Which content store a process uses, chosen by settings and built in one place.

Every process that reads or writes stored bytes builds its stores here: the API, the derivative,
scene, material and tile workers, the purge command, restore replay, maintenance and the operator
tools that publish content. ``EXULANICA_STORE_KIND`` chooses the backend. Unset it is ``local``,
and the stores are exactly the directories under ``EXULANICA_DATA_DIR`` they have always been.
``object`` names an S3-compatible bucket that processes on separate hosts share
(:mod:`exulanica.store.object`); the data directory then holds only host-local scratch, caches and
the upload spool.

Two constructors, because there are two kinds of process. :func:`content_stores` is for everything
that runs for a request or a queue. Its object stores cannot erase, and it refuses to start in a
process that was handed the purge identity's credentials, so "only the purge command, restore replay
and maintenance hold them" is checked rather than remembered. :func:`purging_content_stores` is for
those three.

Settings for ``object``, each secret also accepted from a file named by the same setting with
``_FILE`` appended (never both):

``EXULANICA_OBJECT_STORE_ENDPOINT``
    ``https://host[:port]``. Plain ``http`` only for a loopback host, or with
    ``EXULANICA_OBJECT_STORE_PLAINTEXT=private-network`` for an isolated container network.
``EXULANICA_OBJECT_STORE_BUCKET``, ``EXULANICA_OBJECT_STORE_REGION``
    Both required; there is no default region.
``EXULANICA_OBJECT_STORE_PREFIX``
    Optional key prefix, lower-case segments separated by ``/``.
``EXULANICA_OBJECT_STORE_ADDRESSING``
    ``path`` (default) or ``virtual``.
``EXULANICA_OBJECT_STORE_ACCESS_KEY_ID``, ``EXULANICA_OBJECT_STORE_SECRET_ACCESS_KEY``
    The runtime identity: read, write and list, never delete.
``EXULANICA_OBJECT_STORE_PURGE_ACCESS_KEY_ID``, ``EXULANICA_OBJECT_STORE_PURGE_SECRET_ACCESS_KEY``
    The purge identity, given only to the purge command, restore replay and maintenance.
``EXULANICA_OBJECT_STORE_CA_FILE``
    Optional CA bundle for an endpoint with a private certificate.

A malformed or missing value stops construction with :class:`ObjectStoreConfigurationError` naming
the setting and never its value.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import threading
import weakref
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from exulanica.env import env_get, env_name, resolve_data_dir
from exulanica.errors import ObjectStoreConfigurationError
from exulanica.store.base import ContentAddressedStore
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import (
    BLOB_NAMESPACE,
    MATERIAL_NAMESPACE,
    TILE_NAMESPACE,
    LocalWorkspaceStores,
    WorkspaceStores,
    material_stores,
    tile_store,
)

if TYPE_CHECKING:
    import httpx

    from exulanica.store.object import ObjectStoreCredentials, ObjectStoreLocation

__all__ = [
    "OBJECT_STORE_SETTINGS",
    "PURGE_CREDENTIAL_SETTINGS",
    "SPOOL_DIRECTORY",
    "STORE_KIND_ENV",
    "ContentStores",
    "IncompleteWritesSwept",
    "content_stores",
    "local_content_stores",
    "object_content_stores",
    "purging_content_stores",
    "store_kind",
    "sweep_incomplete_writes",
]

STORE_KIND_ENV: Final = env_name("STORE_KIND")
#: Under the data directory, the host-local files a stream is spooled to before it is uploaded.
SPOOL_DIRECTORY: Final = "object-spool"
#: The purge identity's settings. A runtime process refuses to start holding any of them.
PURGE_CREDENTIAL_SETTINGS: Final = tuple(
    env_name(f"OBJECT_STORE_PURGE_{name}{suffix}")
    for name in ("ACCESS_KEY_ID", "SECRET_ACCESS_KEY")
    for suffix in ("", "_FILE")
)
#: Every setting this module reads, for an installation profile's settings owners list.
OBJECT_STORE_SETTINGS: Final = (
    STORE_KIND_ENV,
    *(
        env_name(f"OBJECT_STORE_{name}")
        for name in (
            "ENDPOINT",
            "BUCKET",
            "REGION",
            "PREFIX",
            "ADDRESSING",
            "PLAINTEXT",
            "CA_FILE",
            "ACCESS_KEY_ID",
            "ACCESS_KEY_ID_FILE",
            "SECRET_ACCESS_KEY",
            "SECRET_ACCESS_KEY_FILE",
        )
    ),
    *PURGE_CREDENTIAL_SETTINGS,
)
_TEMPORARY_PREFIX: Final = "put-"


#: Each ContentStores replaces its lock in a forked child (see exulanica.store.object).
_FORK_SENSITIVE: weakref.WeakSet[Any] = weakref.WeakSet()


def _reset_in_child() -> None:
    for item in list(_FORK_SENSITIVE):
        item._reset_after_fork()


os.register_at_fork(after_in_child=_reset_in_child)


def _misconfigured(message: str) -> ObjectStoreConfigurationError:
    return ObjectStoreConfigurationError("object_store_misconfigured", message)


@dataclass(frozen=True, slots=True)
class IncompleteWritesSwept:
    """What a sweep abandoned. Counts only: no key, path or id, so nothing about content."""

    uploads_aborted: int
    files_removed: int

    @property
    def total(self) -> int:
        return self.uploads_aborted + self.files_removed


class ContentStores:
    """The three namespaces a process uses: shared blobs, per-workspace materials, one tile store.

    Each is built on first use, so a process touches only what it reads or writes, as the direct
    constructions it replaces did (a local store creates its directory when it is built).
    """

    def __init__(
        self,
        kind: str,
        *,
        blobs: Callable[[], ContentAddressedStore],
        materials: Callable[[], WorkspaceStores],
        tiles: Callable[[], ContentAddressedStore],
        describe: Callable[[], dict[str, Any]],
        sweep: Callable[[datetime], IncompleteWritesSwept],
        location: tuple[str, ...],
        close: Callable[[], None] = lambda: None,
    ) -> None:
        self.kind = kind
        self._location = location
        self._factories: dict[str, Callable[[], Any]] = {
            "blobs": blobs,
            "materials": materials,
            "tiles": tiles,
        }
        self._built: dict[str, Any] = {}
        self._lock = threading.Lock()
        _FORK_SENSITIVE.add(self)
        self._describe = describe
        self._sweep = sweep
        self._close = close

    def __repr__(self) -> str:
        return f"ContentStores(kind={self.kind!r})"

    def _reset_after_fork(self) -> None:
        self._lock = threading.Lock()

    def _get(self, name: str) -> Any:
        with self._lock:
            if name not in self._built:
                self._built[name] = self._factories[name]()
            return self._built[name]

    @property
    def blobs(self) -> ContentAddressedStore:
        store: ContentAddressedStore = self._get("blobs")
        return store

    @property
    def materials(self) -> WorkspaceStores:
        stores: WorkspaceStores = self._get("materials")
        return stores

    @property
    def tiles(self) -> ContentAddressedStore:
        store: ContentAddressedStore = self._get("tiles")
        return store

    def describe(self) -> dict[str, Any]:
        """Facts for readiness reports: codes and kinds, never an endpoint, bucket or credential.

        ``location_sha256`` identifies where the bytes live without naming it: the SHA-256 of the
        resolved data directory, or of the normalised endpoint, bucket and prefix. Two stores with
        the same identifier are the same store.
        """
        return {**self._describe(), "location_sha256": self.location_sha256}

    @property
    def location_sha256(self) -> str:
        document = json.dumps([self.kind, *self._location], separators=(",", ":"))
        return hashlib.sha256(document.encode("utf-8")).hexdigest()

    def overlaps(self, other: ContentStores) -> bool:
        """Whether either store's keys could land inside the other's, as a backup or custody
        location that shares its source's directory, or its bucket under a nested prefix, would.
        Identifier equality alone would miss the nested case."""
        if self.kind != other.kind:
            return False
        if self.kind == "local":
            mine, theirs = Path(self._location[0]), Path(other._location[0])
            return mine.is_relative_to(theirs) or theirs.is_relative_to(mine)
        if self._location[:2] != other._location[:2]:
            return False
        mine_prefix, their_prefix = self._location[2], other._location[2]
        return _nested(mine_prefix, their_prefix) or _nested(their_prefix, mine_prefix)

    def close(self) -> None:
        self._close()


def _nested(inner: str, outer: str) -> bool:
    return outer == "" or inner == outer or inner.startswith(f"{outer}/")


def store_kind(environ: Mapping[str, str] | None = None) -> str:
    kind = env_get("STORE_KIND", environ) or "local"
    if kind not in ("local", "object"):
        raise _misconfigured(f"{STORE_KIND_ENV} is 'local' or 'object'")
    return kind


def content_stores(
    environ: Mapping[str, str] | None = None, *, data_dir: str | os.PathLike[str] | None = None
) -> ContentStores:
    """The stores a runtime process uses. Object stores built here cannot erase.

    ``data_dir`` is an explicit command-line directory, winning over ``EXULANICA_DATA_DIR`` as
    :func:`exulanica.env.resolve_data_dir` decides.
    """
    environ = os.environ if environ is None else environ
    held = [name for name in PURGE_CREDENTIAL_SETTINGS if environ.get(name)]
    if held:
        raise ObjectStoreConfigurationError(
            "object_store_purge_credentials_in_runtime",
            f"this process was given {', '.join(held)}. Only exulanica-purge, restore replay and "
            "maintenance may hold the purge identity; everything else builds stores that cannot "
            "erase and must not carry the credential that can.",
        )
    directory = resolve_data_dir(environ, explicit=None if data_dir is None else Path(data_dir))
    if store_kind(environ) == "local":
        return local_content_stores(directory)
    location, credentials = _object_settings(environ, purging=False)
    return object_content_stores(location, credentials, spool_directory=directory / SPOOL_DIRECTORY)


def purging_content_stores(
    environ: Mapping[str, str] | None = None, *, data_dir: str | os.PathLike[str] | None = None
) -> ContentStores:
    """The stores for the purge command, restore replay and maintenance, which may erase.

    A local store's erasure path is the filesystem's, as it always was. An object store is built
    from the purge identity's credentials and never the runtime identity's.
    """
    environ = os.environ if environ is None else environ
    directory = resolve_data_dir(environ, explicit=None if data_dir is None else Path(data_dir))
    if store_kind(environ) == "local":
        return local_content_stores(directory)
    location, credentials = _object_settings(environ, purging=True)
    return object_content_stores(
        location, credentials, spool_directory=directory / SPOOL_DIRECTORY, purging=True
    )


def local_content_stores(data_dir: str | os.PathLike[str]) -> ContentStores:
    """The local stores under a data directory, built as the processes always built them."""
    base = Path(data_dir)

    def sweep(before: datetime) -> IncompleteWritesSwept:
        cutoff = before.timestamp()
        roots = [base.resolve() / BLOB_NAMESPACE, base.resolve() / TILE_NAMESPACE]
        materials = LocalWorkspaceStores(base.resolve() / MATERIAL_NAMESPACE)
        roots.extend(materials.root / workspace.hex for workspace in materials.iter_workspace_ids())
        return IncompleteWritesSwept(uploads_aborted=0, files_removed=_remove_stale(roots, cutoff))

    return ContentStores(
        "local",
        blobs=lambda: LocalContentAddressedStore(base / BLOB_NAMESPACE),
        materials=lambda: material_stores(base),
        tiles=lambda: tile_store(base),
        describe=lambda: {"kind": "local", "purge_capable": True},
        sweep=sweep,
        location=(str(base.resolve()),),
    )


def object_content_stores(
    location: ObjectStoreLocation,
    credentials: ObjectStoreCredentials,
    *,
    spool_directory: str | os.PathLike[str],
    purging: bool = False,
    transport: httpx.BaseTransport | None = None,
    **request_options: Any,
) -> ContentStores:
    """Stores over one bucket and prefix. ``purging`` says the credentials are the purge
    identity's; the stores built then have an erasure path, and otherwise have none.

    ``transport`` and ``request_options`` (``now``, ``sleep``, ``jitter``) exist for tests; the
    defaults are what runs.
    """
    # Imported here so a process on the local default loads no HTTP client for its store.
    from exulanica.store.object import (
        BucketGuard,
        ObjectContentAddressedStore,
        ObjectPurgeRequests,
        ObjectRequests,
        ObjectWorkspaceStores,
        PurgingObjectContentAddressedStore,
        abort_stale_uploads,
    )

    spool = Path(spool_directory)
    requests: ObjectRequests = (ObjectPurgeRequests if purging else ObjectRequests)(
        location, credentials, transport=transport, **request_options
    )
    guard = BucketGuard(requests, location.prefix)

    def store(namespace: str) -> ContentAddressedStore:
        if purging:
            assert isinstance(requests, ObjectPurgeRequests)
            return PurgingObjectContentAddressedStore(
                requests, location.namespace(namespace), spool=spool, guard=guard
            )
        return ObjectContentAddressedStore(
            requests, location.namespace(namespace), spool=spool, guard=guard
        )

    def describe() -> dict[str, Any]:
        return {
            "kind": "object",
            "transport": location.transport,
            "addressing": location.addressing,
            "purge_capable": purging,
            "bucket_check": guard.describe(),
        }

    def sweep(before: datetime) -> IncompleteWritesSwept:
        root = f"{location.prefix}/" if location.prefix else ""
        aborted = abort_stale_uploads(requests, root, before=before)
        return IncompleteWritesSwept(
            uploads_aborted=aborted, files_removed=_remove_stale_files(spool, before.timestamp())
        )

    return ContentStores(
        "object",
        blobs=lambda: store(BLOB_NAMESPACE),
        materials=lambda: ObjectWorkspaceStores(
            requests, location.namespace(MATERIAL_NAMESPACE), spool=spool, guard=guard
        ),
        tiles=lambda: store(TILE_NAMESPACE),
        describe=describe,
        sweep=sweep,
        location=location.identity,
        close=requests.close,
    )


def sweep_incomplete_writes(
    stores: ContentStores, *, older_than: timedelta, now: datetime | None = None
) -> IncompleteWritesSwept:
    """Abandon writes that never finished: unfinished multipart uploads, and spool or temporary
    files that a killed process left behind. Either can hold bytes of a photograph that no key
    names and no purge reaches.

    ``older_than`` must exceed the longest write this installation performs, since a write still
    running looks exactly like an abandoned one until it ends.
    """
    if older_than <= timedelta(0):
        raise ValueError("a sweep needs a positive age")
    moment = now if now is not None else datetime.now(UTC)
    return stores._sweep(moment - older_than)


def _remove_stale(roots: Iterable[Path], cutoff: float) -> int:
    removed = 0
    for root in roots:
        base = root / "sha-256"
        if base.is_dir():
            candidates = itertools.chain(
                base.glob(f"_incoming/{_TEMPORARY_PREFIX}*"),
                base.glob(f"*/*/{_TEMPORARY_PREFIX}*"),
            )
            removed += sum(_remove_if_older(path, cutoff) for path in candidates)
    return removed


def _remove_stale_files(directory: Path, cutoff: float) -> int:
    if not directory.is_dir():
        return 0
    return sum(_remove_if_older(path, cutoff) for path in directory.glob(f"{_TEMPORARY_PREFIX}*"))


def _remove_if_older(path: Path, cutoff: float) -> int:
    # Temporary names only: a content key is 64 hex characters and never starts with "put-".
    try:
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            return 1
    except FileNotFoundError:
        pass
    return 0


def _setting_or_file(environ: Mapping[str, str], suffix: str) -> str | None:
    direct = env_get(suffix, environ)
    named = env_get(f"{suffix}_FILE", environ)
    if direct and named:
        raise _misconfigured(f"set {env_name(suffix)} or {env_name(suffix + '_FILE')}, not both")
    if named is None:
        return direct
    try:
        value = Path(named).read_text(encoding="utf-8").strip()
    except OSError:
        raise _misconfigured(
            f"{env_name(suffix + '_FILE')} names a file that cannot be read"
        ) from None
    if not value:
        raise _misconfigured(f"{env_name(suffix + '_FILE')} names an empty file")
    return value


def _object_settings(
    environ: Mapping[str, str], *, purging: bool
) -> tuple[ObjectStoreLocation, ObjectStoreCredentials]:
    from exulanica.store.object import ObjectStoreCredentials, ObjectStoreLocation

    required = {
        name: env_get(f"OBJECT_STORE_{name}", environ) for name in ("ENDPOINT", "BUCKET", "REGION")
    }
    missing = [env_name(f"OBJECT_STORE_{name}") for name, value in required.items() if not value]
    if missing:
        raise _misconfigured(f"{STORE_KIND_ENV}=object needs {', '.join(missing)}")
    plaintext = env_get("OBJECT_STORE_PLAINTEXT", environ)
    if plaintext not in (None, "private-network"):
        raise _misconfigured(f"{env_name('OBJECT_STORE_PLAINTEXT')} is 'private-network' or unset")
    location = ObjectStoreLocation(
        endpoint=required["ENDPOINT"] or "",
        bucket=required["BUCKET"] or "",
        region=required["REGION"] or "",
        prefix=env_get("OBJECT_STORE_PREFIX", environ) or "",
        addressing=env_get("OBJECT_STORE_ADDRESSING", environ) or "path",
        ca_file=env_get("OBJECT_STORE_CA_FILE", environ),
        plaintext_network=plaintext == "private-network",
    )
    identity = "OBJECT_STORE_PURGE_" if purging else "OBJECT_STORE_"
    key_id = _setting_or_file(environ, f"{identity}ACCESS_KEY_ID")
    secret = _setting_or_file(environ, f"{identity}SECRET_ACCESS_KEY")
    if not key_id or not secret:
        raise _misconfigured(
            f"{STORE_KIND_ENV}=object needs {env_name(identity + 'ACCESS_KEY_ID')} and "
            f"{env_name(identity + 'SECRET_ACCESS_KEY')} (or their _FILE forms)"
        )
    return location, ObjectStoreCredentials(key_id, secret)
