"""A durable PostgreSQL database for a personal install, kept on the person's own computer.

``exulanica-local-db`` (:mod:`exulanica.db.local.cli`) is the command. A personal install needs
the same PostgreSQL 18 with pgvector that a deployment does, and it needs it to outlive every
setup mistake a person can make on their own machine. So the rules are these:

*   **The data directory is stated and durable.** It is never inside a temporary directory and
    never under the directory where test servers live (:mod:`~exulanica.db.local.locations`),
    and its durability settings are PostgreSQL's defaults: ``fsync`` and ``full_page_writes`` on.
*   **Test servers and real data are kept apart by construction.** Every data directory this
    command creates carries a marker, and ``scripts/test_postgres.py`` refuses to serve, start or
    sweep a directory that holds one. This command refuses the test servers' base directory.
*   **Backups are proven, not assumed.** Each backup is a ``pg_dump`` with its SHA-256 and a
    manifest of row counts taken in the dump's own snapshot (:mod:`~exulanica.db.local.backup`).
    ``stop`` takes one. ``verify`` restores one into a scratch server and compares the counts.
*   **A restore only ever creates.** It refuses a location that holds anything.
*   **Starting never migrates.** ``upgrade`` is the only path to a newer schema, and it backs up,
    rehearses the pending migrations on a scratch copy of that backup, migrates, and backs up again
    (:mod:`~exulanica.db.local.upgrade`).

Every refusal and failed step names a member of
:class:`~exulanica.db.local.refusals.Refusal`. There is no command that deletes a data directory
or a backup.
"""
