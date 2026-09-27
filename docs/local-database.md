# Local database

A world someone builds on their own computer lives in a PostgreSQL database that
`exulanica-local-db` ([`exulanica/db/local/`](../exulanica/db/local/__init__.py)) keeps: durable,
backed up, restored only into an empty directory and upgraded only on request. This guide covers
creating, running, backing up, verifying, restoring and upgrading that database, and taking on or
securing a cluster made another way. The disposable servers the tests and a development API use are
a different thing, described in [development setup](development-setup.md).

## Prerequisites

The same PostgreSQL 18 with pgvector as the tests (`brew install postgresql@18 pgvector` on macOS),
Python 3.11 and [uv](https://docs.astral.sh/uv/). Every command names its directory; none has a
default.

## Commands

```bash
uv run exulanica-local-db init --directory ~/Exulanica/database     # create, migrate, start; prints the URLs
uv run exulanica-local-db start --directory ~/Exulanica/database    # never migrates; says what is pending
uv run exulanica-local-db stop --directory ~/Exulanica/database     # stops, then takes a backup
uv run exulanica-local-db status --directory ~/Exulanica/database
uv run exulanica-local-db backup --directory ~/Exulanica/database
uv run exulanica-local-db verify --directory ~/Exulanica/database   # restores the newest backup to check it
uv run exulanica-local-db upgrade --directory ~/Exulanica/database  # backup, rehearsal, migration, backup
uv run exulanica-local-db restore --directory ~/Exulanica/restored <backup>.pgdump
uv run exulanica-local-db adopt --directory ~/Exulanica/database    # take on a cluster made another way
uv run exulanica-local-db require-passwords --directory ~/Exulanica/database  # a trusting cluster asks for passwords
```

A refusal prints `refused (<name>)` and exits 2; a step that was attempted and failed prints
`failed (<name>)` and exits 1. The names are listed in
[`refusals.py`](../exulanica/db/local/refusals.py).

## Where it lives

The directory holds `data/`, `backups/` and `server.log`. `init` and `restore` refuse a directory
inside the system temporary directory (`TMPDIR`, or the platform's default), `/tmp` or `/var/tmp`,
anything under the test servers' directory, and a directory that already holds files. Durability
settings stay at PostgreSQL's defaults. The server listens on the loopback interface only, over TCP.

The photographs and other files a world cites are in the content-addressed store
(`EXULANICA_DATA_DIR`), which this command does not back up.

## Passwords

A cluster that `init` or `restore` makes asks every connection for a password (`scram-sha-256`),
and so does each scratch copy `verify` and `upgrade` restore into. Each role's password is in
`passwords.pgpass` beside `data/`, mode 0600, in libpq's own password-file format, and every URL the
command prints names that file with libpq's `passfile` parameter, for example
`postgresql://exulanica_app@localhost:5500/exulanica?passfile=<directory>/passwords.pgpass`, where
`<directory>` is the database directory's absolute path.

The application, `pg_dump` and `psql` connect through libpq, which reads the password from the
file, so no password is printed, logged, passed on a command line or put in an environment
variable ([`passwords.py`](../exulanica/db/local/passwords.py)). A role is given its password as a
SCRAM verifier computed on the client, so the server never receives the password itself. Backups
hold no passwords, and a restore gives every role a new one. The boundary is the operating-system
account: another account on the computer cannot connect, and a process running as the same account
can read the file, as it can read `data/`. A command refuses a password file another account could
read, or a directory another account could write, and libpq ignores such a file too. `status` says
which authentication the cluster uses and, when it runs, the methods its `pg_hba.conf` holds as the
server reads them.

## Backups

`stop` takes a backup after the server stops, `backup` takes one on request, and `upgrade` takes one
before and one after. Each is a custom-format `pg_dump` with its SHA-256 (`.pgdump.sha256`, which
`shasum -a 256 -c` reads) and a manifest (`.json`) holding every table's row count and the applied
migrations, read in the dump's own snapshot, and the database's roles without their passwords.
Nothing deletes a backup. They share a disk with the database, so copy `backups/` elsewhere to
survive the loss of that disk.

## Verify and restore

`verify` checks the digest, restores the dump into a scratch server under the system temporary
directory, compares its row counts and migrations with the manifest, and deletes the copy.
`restore` does the same into an empty or absent directory and leaves it running on the port the
backed-up database served, or on `--port`. Both load the schema, give every function the rows'
constraints run a search path of its own, then load the rows
([`load_functions.py`](../exulanica/db/load_functions.py)), so a dump taken before migration 0106,
whose receipt canonicaliser had none, restores too. A plain dump that `psql` loads has no step
between its schema and its rows, so one taken before 0106 stops at its first receipt;
`exulanica-local-db` restores the custom-format backups it takes, not a plain dump.

## Upgrade

`upgrade` refuses while another client is connected, so stop the API and the workers first. It
restarts the server on a private port, backs up, applies the pending migrations and role
provisioning to a scratch copy of that backup with the schema check the API runs at boot, and
migrates the real database only after that rehearsal passes. A failed rehearsal leaves the database
untouched. A migration that fails after a passing rehearsal leaves the server stopped and names the
backup to restore.

## Adopt a cluster made another way

`adopt` takes on a durable cluster another tool made, which carries no marker
([`adopt.py`](../exulanica/db/local/adopt.py)). `--directory` names the directory that holds its
`data/`, and the command's backups begin in `backups/` beside it; backups another tool took
elsewhere stay where they are, because this command can neither verify nor restore a dump without
its own manifest. Before anything is written, it refuses a location the other commands refuse, a
`data/` that is not a data directory or already carries the marker, another PostgreSQL major
version, a directory another account owns, a server running with `fsync` or `full_page_writes` off,
as the test servers run, and settings that turn either off. It connects as the bootstrap superuser
(`--owner-role`) without a password over the loopback interface, and refuses a database
(`--database`) that lacks a migration this code has or records one it lacks. Then it backs up,
proves the backup restores into a scratch server, records the port the cluster serves on in its own
settings when they do not name it (`--port`, or else the port it runs on or was last started on),
and writes the marker last, so a failed step leaves none. It never migrates, changes authentication
or moves the data; a running server keeps running, and a stopped one is started only on a private
port and stopped again. The marker records that the cluster trusts its connections.

## Require passwords

`require-passwords` converts a cluster that trusts every connection from this computer, such as one
made by a version of `init` that did not ask for passwords or one `adopt` took on
([`require_passwords.py`](../exulanica/db/local/require_passwords.py)). It refuses while another
client is connected, so stop the API and the workers first, and runs the server on a private port.
Before anything changes it refuses a directory another account can write, a `pg_hba.conf` that is
not the data directory's own or holds a rule that includes another file, carries options, fails to
parse or has a method other than `trust`, `scram-sha-256` or `reject`, and a role the application
connects as that is absent or may not log in.

Then it backs up and proves the backup restores, writes the password file and gives the bootstrap
superuser and each application role a password, changes the method word of each `trust` rule in
`pg_hba.conf` to `scram-sha-256` and keeps every other byte, reloads, and proves each of those roles
is refused without a password and admitted with its own. The marker is written last. Any failure
after the backup puts back `pg_hba.conf`, each role's previous password, the password file and the
marker, shows the server admits a connection without a password again, and exits with
`failed (authentication-change-failed)`. A run killed part way leaves a password file that every
command already connects through, and running it again finishes the change with the passwords that
file holds. Anything that connected without a password, such as a launcher that builds its own
URLs, needs the printed URLs afterwards.

## Running the API on it

A database this command made is upgraded only by its `upgrade` command, never by an implicit
startup migration. Point the API at the runtime URL `init` or `restore` printed; the owner URL is for
migrations and provisioning, and the API refuses to start on it. [Development setup](development-setup.md#running-the-api)
lists the API's other settings, and [deployment](deployment.md) owns the full configuration.
