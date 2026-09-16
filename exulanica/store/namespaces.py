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
"""

from __future__ import annotations

import abc
import os
import uuid
from pathlib import Path
from typing import Final

from exulanica.store.base import ContentAddressedStore
from exulanica.store.local import LocalContentAddressedStore

__all__ = [
    "BLOB_NAMESPACE",
    "MATERIAL_NAMESPACE",
    "LocalWorkspaceStores",
    "WorkspaceStores",
    "material_stores",
]

#: Where the shared, content-addressed evidence store lives under the data directory.
BLOB_NAMESPACE: Final = "blobs"
#: Where each workspace's material bakes live under the data directory.
MATERIAL_NAMESPACE: Final = "materials"


class WorkspaceStores(abc.ABC):
    """One content-addressed store per workspace."""

    @abc.abstractmethod
    def for_workspace(self, workspace_id: uuid.UUID) -> ContentAddressedStore:
        """The store holding this workspace's bytes, and nobody else's."""


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


def material_stores(data_dir: str | os.PathLike[str]) -> LocalWorkspaceStores:
    """The material namespaces under a data directory, beside and never inside the blob store."""
    base = Path(data_dir).resolve()
    root = base / MATERIAL_NAMESPACE
    blobs = base / BLOB_NAMESPACE
    if root.is_relative_to(blobs) or blobs.is_relative_to(root):
        raise ValueError(f"material namespaces at {root} would share the blob store at {blobs}")
    return LocalWorkspaceStores(root)
