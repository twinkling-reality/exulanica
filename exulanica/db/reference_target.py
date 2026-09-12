"""Resolve the local reference target without granting writes to retained data."""

from __future__ import annotations

import os

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

RETAINED_DATABASE = "exulanica_spine_test"
COPY_DATABASE = "exulanica_inspect_test"
REFERENCE_OVERRIDE = "EXULANICA_REFERENCE_DATABASE_URL"
COPY_URL = f"postgresql://localhost:5433/{COPY_DATABASE}"


def validate_reference_url(url: str | None, *, read_only: bool = False) -> str:
    """Pin the endpoint; retained connections additionally enforce read-only transactions.

    This validator does not select a destination. Writable callers must use
    writable_reference_url, which also requires the explicit reference override.
    """
    if any(os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")):
        raise ValueError("Unset PGHOSTADDR, PGSERVICE and PGSERVICEFILE before this local run.")
    try:
        parts = conninfo_to_dict(url) if url else {}
    except psycopg.Error:
        raise ValueError("Supply a valid local reference connection string.") from None
    names = {COPY_DATABASE, RETAINED_DATABASE} if read_only else {COPY_DATABASE}
    if (
        parts.get("host") not in ("localhost", "127.0.0.1")
        or parts.get("port") != "5433"
        or parts.get("dbname") not in names
        or parts.get("hostaddr") not in (None, "127.0.0.1")
        or parts.get("service")
    ):
        raise ValueError("Use the permitted local reference copy on port 5433 for writes.")
    options = parts.get("options", "-csearch_path=public")
    if read_only:
        options += " -cdefault_transaction_read_only=on"
    return make_conninfo(url, hostaddr="127.0.0.1", options=options)


def writable_reference_url(url: str | None = None) -> str:
    """Require explicit copy selection and reject a caller selecting another database.

    Caller options such as the owned schema search path remain intact. Credentials and
    connection strings never appear in errors. No connection is opened by this module.
    """
    override = os.environ.get(REFERENCE_OVERRIDE)
    if not override:
        raise ValueError(f"Set {REFERENCE_OVERRIDE}={COPY_URL} before a writable rehearsal.")
    selected = validate_reference_url(override)
    return validate_reference_url(url) if url is not None else selected
