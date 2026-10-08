"""The generation queue's format: its layout in the bucket and its strict records.

The format is :mod:`exulanica_pieces.queue`, shared with the product's generation worker so both
read one definition; it is named here for the session and the operator's tooling.
"""

from __future__ import annotations

from exulanica_pieces.queue import (
    BEAT_PROFILE,
    CLAIM_PROFILE,
    DONE_PROFILE,
    ENTRY_PROFILE,
    IDLE_SECONDS_DEFAULT,
    MAX_FILE_BYTES,
    MAX_REQUESTS,
    SESSION_PROFILE,
    SESSION_ROUTES,
    STOP_SECONDS_MAXIMUM,
    build_ready,
    build_session,
    charges_from_done,
    entry_files,
    instant,
    read_done,
    read_entry,
    read_ready,
    read_session,
    uncached_requests,
)

__all__ = [
    "BEAT_PROFILE",
    "CLAIM_PROFILE",
    "DONE_PROFILE",
    "ENTRY_PROFILE",
    "IDLE_SECONDS_DEFAULT",
    "MAX_FILE_BYTES",
    "MAX_REQUESTS",
    "SESSION_PROFILE",
    "SESSION_ROUTES",
    "STOP_SECONDS_MAXIMUM",
    "build_ready",
    "build_session",
    "charges_from_done",
    "entry_files",
    "instant",
    "read_done",
    "read_entry",
    "read_ready",
    "read_session",
    "uncached_requests",
]
