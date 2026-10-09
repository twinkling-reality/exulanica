"""The style pack check: each piece of an admitted workspace pack read for its colours, off-request.

An upload is admitted on everything that needs no accessor data (:mod:`exulanica.world
.style_pack_admission`). What does, reading every vertex colour of every piece, runs here: the
check worker claims a waiting version's check, reads each listed piece from the workspace's own
namespace, and holds every triangle to one colour of the pack's palette, or of a pack in its base
chain, through :func:`exulanica.world.style_pack_pieces.read_palette_piece`. A version passes and
becomes ready, or fails ``refused`` naming the piece and what it found, or ``interrupted`` when its
time bound ran out, which a repeat of the upload may ask again. It runs in the asset preparation
process (:mod:`exulanica.world.asset_preparation_command`), which holds the runtime role, the
workspaces and the stores it needs.
"""

from __future__ import annotations

import contextlib
import json
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from exulanica.db.session import Database
from exulanica.errors import BlobNotFoundError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.store.namespaces import WorkspaceStores
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.style_pack_pieces import StylePieceRefused, read_palette_piece
from exulanica.world.workspace_style_packs import (
    StylePackNotReady,
    StylePackVersionRecord,
    WorkspaceStylePackError,
    WorkspaceStylePackRepository,
)

__all__ = [
    "CHECK_LEASE_SECONDS",
    "CHECK_SECONDS",
    "CheckOutcome",
    "LibraryPalettes",
    "StylePackCheckWorker",
    "check_version",
    "colour_table",
    "library_palettes",
]

#: A version's check, at most: past it the check stops as ``interrupted``.
CHECK_SECONDS: Final = 120
#: A claim's lease outlasts the check's bound, so a live check is never claimed twice.
CHECK_LEASE_SECONDS: Final = 180

#: The sRGB bytes of every swatch of a library version, by manifest digest.
LibraryPalettes = Callable[[str], frozenset[tuple[int, int, int]] | None]


def library_palettes(digest: str) -> frozenset[tuple[int, int, int]] | None:
    """The swatches of the library version this manifest digest names, or None when the library
    holds no manifest of that digest."""
    item = style_pack_library().content.get(digest)
    if item is None or item.media_type != "application/json":
        return None
    return _swatches(json.loads(item.data))


def colour_table(root: Path) -> tuple[int, ...]:
    """The 256 linear values of ``exulanica.srgb8-linear16/v1``, from the committed table."""
    document = json.loads((root / "assets/colour/srgb8-linear16.v1.json").read_text("utf-8"))
    values = tuple(int(value) for value in document["values"])
    if len(values) != 256:
        raise ValueError("the colour table holds 256 values")
    return values


@dataclass
class CheckOutcome:
    ready: int = 0
    refused: int = 0
    interrupted: int = 0
    base_unavailable: int = 0
    exhausted: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def handled(self) -> int:
        return self.ready + self.refused + self.interrupted + self.base_unavailable


def _swatches(manifest: Mapping[str, Any]) -> frozenset[tuple[int, int, int]]:
    return frozenset(tuple(swatch["srgb8"]) for swatch in manifest["palette"]["swatches"])


def _palette(
    repository: WorkspaceStylePackRepository,
    record: StylePackVersionRecord,
    library: LibraryPalettes,
) -> frozenset[tuple[int, int, int]] | None:
    """Every colour the version may use: its own palette's and each pack's in its base chain.
    None when a pack in the chain cannot be read."""
    colours: set[tuple[int, int, int]] = set()
    current: StylePackVersionRecord | None = record
    for _ in range(9):
        if current is None or current.manifest_canonical is None:
            return None
        manifest = json.loads(current.manifest_canonical)
        colours |= _swatches(manifest)
        base = current.base
        if base is None:
            return frozenset(colours)
        if base.source == "library":
            held = library(base.manifest_sha256)
            if held is None:
                return None
            return frozenset(colours | held)
        try:
            current = repository.version(base.manifest_sha256)
        except WorkspaceStylePackError:
            return None
    return None


def check_version(
    repository: WorkspaceStylePackRepository,
    stores: WorkspaceStores,
    record: StylePackVersionRecord,
    *,
    table: tuple[int, ...],
    library: LibraryPalettes,
    seconds: float = CHECK_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str | None, str | None, dict[str, Any]]:
    """Check one version's pieces: ``(None, None, report)`` when it passes, else its failure class,
    what it found, and the report."""
    started = clock()
    palette = _palette(repository, record, library)
    if palette is None:
        return "base_unavailable", "a pack this one is drawn on could not be read", {}
    report: dict[str, Any] = {"pieces": {}}
    for file in repository.files(record.manifest_sha256):
        if file.media_type != "model/gltf-binary":
            continue
        if clock() - started > seconds:
            return "interrupted", f"the check ran past its {seconds:g} s bound", report
        # A generated version's pieces are read from the shared store of generated pieces, every
        # other file from the workspace's own namespace (``stores``).
        try:
            store = (
                stores.for_workspace(repository.workspace_id)
                if file.source == "workspace"
                else repository.store_for(file)
            )
            data = store.get(BlobId.from_hex(file.content_sha256))
        except (BlobNotFoundError, StylePackNotReady):
            return "interrupted", f"{file.path}: its bytes are missing from their store", report
        try:
            piece = read_palette_piece(data, table)
        except StylePieceRefused as refused:
            return "refused", f"{file.path}: {refused.reason}: {refused}", report
        foreign = sorted(piece.colours - palette)
        if foreign:
            listed = ", ".join("#{:02x}{:02x}{:02x}".format(*colour) for colour in foreign[:4])
            return (
                "refused",
                f"{file.path}: coloured {listed}, which no swatch of the pack's palette is",
                report,
            )
        report["pieces"][file.path] = {
            "triangles": piece.triangles,
            "colours": len(piece.colours),
        }
    report["seconds"] = round(clock() - started, 3)
    return None, None, report


class StylePackCheckWorker:
    """Drains waiting style pack checks for a set of workspaces, one per workspace in turn."""

    def __init__(
        self,
        database: Database,
        stores: WorkspaceStores,
        workspaces: frozenset[uuid.UUID],
        *,
        table: tuple[int, ...],
        library: LibraryPalettes,
        name: str = "style-pack-check",
        max_attempts: int = 3,
        limit_per_pass: int = 16,
        workspace_source: Callable[[], Iterable[uuid.UUID]] | None = None,
        seconds: float = CHECK_SECONDS,
        generated_pieces: ContentAddressedStore | None = None,
    ) -> None:
        self._database = database
        self._stores = stores
        self._generated_pieces = generated_pieces
        self._workspaces = workspaces
        self._table = table
        self._library = library
        self._name = name
        self._max_attempts = max_attempts
        self._limit = limit_per_pass
        self._workspace_source = workspace_source
        self._seconds = seconds

    @property
    def name(self) -> str:
        return self._name

    def workspaces(self) -> frozenset[uuid.UUID]:
        discovered = () if self._workspace_source is None else self._workspace_source()
        return self._workspaces | frozenset(discovered)

    def drain(self) -> CheckOutcome:
        """Check what is waiting, one per workspace in turn, up to the pass limit."""
        outcome = CheckOutcome()
        with contextlib.ExitStack() as sessions:
            active: dict[uuid.UUID, WorkspaceStylePackRepository] = {}
            for workspace_id in sorted(self.workspaces()):
                try:
                    connection = sessions.enter_context(self._database.session(workspace_id))
                    repository = WorkspaceStylePackRepository(
                        connection,
                        workspace_id,
                        uuid.UUID(int=0),
                        stores=self._stores,
                        generated_pieces=self._generated_pieces,
                    )
                    outcome.exhausted += repository.expire_exhausted(
                        max_attempts=self._max_attempts
                    )
                except Exception as error:
                    outcome.errors.append(f"{workspace_id}: {type(error).__name__}: {error}")
                    continue
                active[workspace_id] = repository
            while active and outcome.handled < self._limit:
                for workspace_id, repository in list(active.items()):
                    if outcome.handled >= self._limit:
                        break
                    try:
                        claim = repository.claim(
                            self._name, CHECK_LEASE_SECONDS, max_attempts=self._max_attempts
                        )
                        if claim is None:
                            del active[workspace_id]
                            continue
                        self._check_one(repository, *claim, outcome)
                    except Exception as error:
                        outcome.errors.append(f"{workspace_id}: {type(error).__name__}: {error}")
                        del active[workspace_id]
        return outcome

    def _check_one(
        self,
        repository: WorkspaceStylePackRepository,
        manifest_sha256: str,
        token: uuid.UUID,
        outcome: CheckOutcome,
    ) -> None:
        record = repository.version(manifest_sha256)
        failure, message, report = check_version(
            repository,
            self._stores,
            record,
            table=self._table,
            library=self._library,
            seconds=self._seconds,
        )
        if failure is None:
            repository.finish_ready(manifest_sha256, token, report)
            if repository.version(manifest_sha256).state == "ready":
                outcome.ready += 1
            else:
                outcome.base_unavailable += 1
            return
        repository.finish_failed(manifest_sha256, token, failure, message or failure, report)
        if failure == "refused":
            outcome.refused += 1
        elif failure == "interrupted":
            outcome.interrupted += 1
        else:
            outcome.base_unavailable += 1
