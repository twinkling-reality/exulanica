"""Content-addressed storage for original bytes.

The normal interface cannot delete. Erasure exists, is real, and is reached only through
``privileged_purger`` with an explicit ``PurgeAuthorization``.
"""

from __future__ import annotations

from exulanica.store.base import (
    ContentAddressedStore,
    PrivilegedPurger,
    PurgeAuthorization,
    PutResult,
    privileged_purger,
)
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import LocalWorkspaceStores, WorkspaceStores, material_stores

__all__ = [
    "ContentAddressedStore",
    "LocalContentAddressedStore",
    "LocalWorkspaceStores",
    "PrivilegedPurger",
    "PurgeAuthorization",
    "PutResult",
    "WorkspaceStores",
    "material_stores",
    "privileged_purger",
]
