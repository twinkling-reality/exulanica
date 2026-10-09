"""Stores with one namespace per workspace, for bytes no two workspaces may ever share.

``blob`` is shared: two people who import the same photograph hold one object, which is why the
purger needs a cross-workspace read before it destroys anything. Bytes a workspace generated for
itself need no such sharing, and are safer without it. A workspace's material bakes live in a
namespace of their own, so destroying them is a question about one workspace's rows and never a
question about anyone else's.

A namespace is an ordinary :class:`~exulanica.store.base.ContentAddressedStore`: no delete on the
normal interface, erasure only through ``privileged_purger`` with a tombstone's authorisation.
The local layout is ``<root>/<workspace hex>/sha-256/<aa>/<bb>/<digest>``, a prefix an
S3-compatible backend serves unchanged. The root must lie outside the shared blob store, and
:func:`material_stores` places it beside that store under the data directory.

**Every namespace is registered here, once.** :data:`SHARED_NAMESPACES` hold one store for
everybody; :data:`WORKSPACE_NAMESPACES` hold one per workspace, under ``<name>/<workspace hex>``.
The stores a process builds (:mod:`exulanica.store.configured`), their listing for backup and
restore, the sweep of unfinished writes and the object store's check of which keys are its own all
read these two tuples, so a namespace added to one of them is built, listed, swept and recognised
with no other change. The names are stable: each is a directory under the data directory, a segment
of every object key and the name a backup set records, so renaming one would orphan everything
stored under it. A name is one lower-case segment of letters, digits and ``-``.
"""

from __future__ import annotations

import abc
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from exulanica.store.base import ContentAddressedStore
from exulanica.store.local import LocalContentAddressedStore

__all__ = [
    "BLOB_NAMESPACE",
    "GENERATED_PIECE_NAMESPACE",
    "LOOK_NAMESPACE",
    "MATERIAL_NAMESPACE",
    "SHARED_NAMESPACES",
    "TILE_NAMESPACE",
    "WORKSPACE_ASSET_NAMESPACE",
    "WORKSPACE_NAMESPACES",
    "WORKSPACE_STYLE_PACK_NAMESPACE",
    "LocalWorkspaceStores",
    "WorkspaceStores",
    "look_lock_key",
    "material_stores",
    "tile_store",
    "workspace_asset_lock_key",
    "workspace_style_pack_write_key",
]

#: Where the shared, content-addressed evidence store lives under the data directory.
BLOB_NAMESPACE: Final = "blobs"
#: Where each workspace's material bakes live under the data directory.
MATERIAL_NAMESPACE: Final = "materials"
#: Where baked tiles live under the data directory. One store, not one per workspace: a baked
#: tile is a pure function of public inputs, so the same key names the same bytes for everyone
#: (migration 0072).
TILE_NAMESPACE: Final = "tiles"
#: Where generated pieces live: one store, not one per workspace. A generated piece is made only
#: from catalog content (a shipped thing kind, a recipe catalog's words, a committed pack's palette,
#: a pinned model and a seed drawn from the request), refused otherwise at the store's own write
#: path (exulanica.generation.pieces), so the same digest names the same bytes for everyone, like a
#: baked tile, and no workspace's erasure reaches it; the workspace rows naming a piece are erased.
GENERATED_PIECE_NAMESPACE: Final = "generated-pieces"
#: Where each workspace's own admitted assets and their prepared outputs live (migration 0126).
#: One namespace per workspace, like the material bakes, so erasing a workspace's assets is a
#: question about its own rows and never about anyone else's.
WORKSPACE_ASSET_NAMESPACE: Final = "workspace-assets"
#: Where each workspace's own looks keep their containers, by digest (migration 0159): a creature's
#: sketch, a sculpted look and an imported traveller's look. One namespace per workspace, so a
#: look is served only to the workspace that holds its row.
LOOK_NAMESPACE: Final = "looks"
#: Where each workspace's own style packs' files live (migration 0173): one namespace per workspace,
#: apart from its assets, so each namespace's inventory accounts for exactly its own bytes.
WORKSPACE_STYLE_PACK_NAMESPACE: Final = "workspace-style-packs"

#: The namespaces holding one store for every workspace, in the order they are listed.
SHARED_NAMESPACES: Final[tuple[str, ...]] = (
    BLOB_NAMESPACE,
    TILE_NAMESPACE,
    GENERATED_PIECE_NAMESPACE,
)
#: The namespaces holding one store per workspace, each under ``<name>/<workspace hex>``.
WORKSPACE_NAMESPACES: Final[tuple[str, ...]] = (
    MATERIAL_NAMESPACE,
    WORKSPACE_ASSET_NAMESPACE,
    LOOK_NAMESPACE,
    WORKSPACE_STYLE_PACK_NAMESPACE,
)


class WorkspaceStores(abc.ABC):
    """One content-addressed store per workspace."""

    @abc.abstractmethod
    def for_workspace(self, workspace_id: uuid.UUID) -> ContentAddressedStore:
        """The store holding this workspace's bytes, and nobody else's."""

    @abc.abstractmethod
    def iter_workspace_ids(self) -> Iterator[uuid.UUID]:
        """The workspaces that have a namespace here. For backup, verification and restore, which
        must copy every namespace; never for deciding which workspaces exist."""


class LocalWorkspaceStores(WorkspaceStores):
    """Workspace namespaces as directories under one root on the local filesystem."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def for_workspace(self, workspace_id: uuid.UUID) -> LocalContentAddressedStore:
        if not isinstance(workspace_id, uuid.UUID):
            raise TypeError(
                f"a workspace namespace is named by a uuid, not {type(workspace_id).__name__}"
            )
        return LocalContentAddressedStore(self._root / workspace_id.hex)

    def iter_workspace_ids(self) -> Iterator[uuid.UUID]:
        if not self._root.is_dir():
            return
        for path in sorted(self._root.iterdir()):
            try:
                workspace_id = uuid.UUID(hex=path.name)
            except ValueError:
                continue
            if path.is_dir() and workspace_id.hex == path.name:
                yield workspace_id


def material_stores(data_dir: str | os.PathLike[str]) -> LocalWorkspaceStores:
    """The material namespaces under a data directory, beside and never inside the blob store."""
    base = Path(data_dir).resolve()
    root = base / MATERIAL_NAMESPACE
    blobs = base / BLOB_NAMESPACE
    if root.is_relative_to(blobs) or blobs.is_relative_to(root):
        raise ValueError(f"material namespaces at {root} would share the blob store at {blobs}")
    return LocalWorkspaceStores(root)


def workspace_asset_lock_key(workspace_id: uuid.UUID, digest: str) -> str:
    """The advisory lock key of one object in one workspace's asset namespace.

    The workspace and the digest, never the digest alone: identical bytes admitted in two
    workspaces are two objects, so a lock one workspace holds must neither delay nor be seen by
    another. Admission, preparation, delivery and the purger all take this key.
    """
    return f"workspace-asset:{workspace_id}:{digest}"


def look_lock_key(workspace_id: uuid.UUID, digest: str) -> str:
    """The advisory lock key of one container in one workspace's looks namespace.

    Keyed as an asset object is, by workspace and digest. The store holds it from recording a
    container until the rows naming it commit, and the purger takes it before destroying one.
    """
    return f"look:{workspace_id}:{digest}"


def workspace_style_pack_write_key(workspace_id: uuid.UUID) -> str:
    """The advisory lock key one workspace's style pack writes hold: an admission's rows and bytes,
    a version becoming ready, and the purger's destruction of any of its style pack objects.

    One key per workspace rather than one per object, so an admission of up to 513 objects holds
    one lock. Always taken before the workspace's lifecycle lock and before the asset read lock.
    """
    return f"workspace-style-packs:{workspace_id}"


def tile_store(data_dir: str | os.PathLike[str]) -> LocalContentAddressedStore:
    """The one store baked tiles live in, beside the blob store and never inside it."""
    base = Path(data_dir).resolve()
    root = base / TILE_NAMESPACE
    blobs = base / BLOB_NAMESPACE
    if root.is_relative_to(blobs) or blobs.is_relative_to(root):
        raise ValueError(f"the tile store at {root} would share the blob store at {blobs}")
    return LocalContentAddressedStore(root)
