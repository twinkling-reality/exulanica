"""The workspace lock: one advisory lock every plane that changes a workspace's world waits on.

``pg_advisory_xact_lock(hashtextextended(workspace_id::text, 880024))``, held until the end of the
taking transaction. The seed is the structural plane's, and sharing it is the point rather than an
accident: an object edit, a structural commit, a saved-world entry change and the tombstone trigger
``tg_world_structure_invalidate_on_tombstone`` serialize on one lock, so an edit cannot commit
against a source snapshot that a concurrent deletion is in the act of invalidating.

The seed is also restated inside PostgreSQL functions that migrations created, which cannot import
this, and in modules that predate this one. ``tests/test_workspace_lock.py`` requires every one of
those to name this seed and refuses a restatement anywhere it has not already been listed, so the
list of copies can only shrink.
"""

from __future__ import annotations

import uuid
from typing import Final

import psycopg

__all__ = ["WORKSPACE_LOCK_SEED", "lock_workspace"]

#: The second argument of ``hashtextextended`` that makes a workspace id into its lock key.
WORKSPACE_LOCK_SEED: Final = 880_024


def lock_workspace(connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
    """Wait for the workspace lock and hold it until the connection's transaction ends."""
    connection.execute(
        "select pg_advisory_xact_lock(hashtextextended(%s::text,%s))",
        (workspace_id, WORKSPACE_LOCK_SEED),
    )
