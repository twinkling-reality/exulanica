# Development setup and operations

Commands for installing extras, running the suite, starting the API, and configuring the local
store. Test counts and measurement dates below are historical, not a fresh execution report.

## Setup and running

### Prerequisites

- Python 3.11 (pinned in `.python-version`; the ML stack lags newer interpreters) and
  [uv](https://docs.astral.sh/uv/)
- Node.js 22 or newer, and pnpm 10.7.1
- Optional, for the database-backed tests: PostgreSQL

### Backend

```bash
uv sync --extra reconstruction --extra segmentation --extra pose --extra server
cp .env.example .env         # then fill in the two keys below
uv run ruff check .          # static validation; select behavior-focused tests below
```

The full suite is run with all four extras. A plain `uv sync` installs none of them, and a test
that needs a missing extra then skips instead of failing. Every skip cause the suite accepts is
listed in [`tests/expected_skips.toml`](../tests/expected_skips.toml); continuous integration
installs no extras and fails a skip that file does not accept.

`.env` is gitignored and must never be committed. Two variables:

| Variable | Needed for | Where to get it |
| --- | --- | --- |
| `NEBIUS_API_KEY` | Every model call, and the preflight | https://tokenfactory.nebius.com/ then "Get API key" |
| `TAVILY_API_KEY` | The opt-in public lookup only | https://tavily.com or the Nebius Builders Program |

Neither key is required to run the test suite. Tests do not call external model services or spend
model credits; database tests connect to the explicitly configured local PostgreSQL server.
Model clients use scripted transports and backend image fixtures are generated.

The following is a command reference, not a sequence to run without configuration. API and ingest
commands require the database setup below; live preflight and platform verification use external
services. `--offline` skips vision, but ingest still writes to the configured database and store.

```bash
uv run pytest
uv run ruff check .                 # lints backend, tests and scripts
uv run lint-imports                 # backend layering contracts
uv run exulanica-preflight            # checks every manifest id against the live catalog
uv run uvicorn --factory exulanica.api.app:create_app   # the HTTP API, on port 8000
uv run exulanica-preflight --catalog-file <snapshot.json>   # same check, offline
uv run exulanica-ingest ingest ./photos   # safe to run repeatedly; a second run issues no model calls
uv run exulanica-ingest ingest ./photos --offline           # skip the vision stage entirely
uv run scripts/verify_platform.py      # the runtime verification harness, needs NEBIUS_API_KEY
```

### The tests that need a database

**PostgreSQL is the only data layer.** 1965 of the 4608 backend tests carry the `postgres` marker
(collected 2026-09-16 at 51a09db), and they are the executable proof of everything the database
carries: that a model cannot write a name into canonical state, that one workspace cannot read
another's rows, that a tombstoned address refuses the write, and that the whole ingest path works. A
default run prints a reminder naming the files it skipped rather than reporting green in silence.

The target is PostgreSQL 18 with pgvector, and nothing is substituted for it. On macOS:

```bash
brew install postgresql@18 pgvector
```

#### The full suite: a private server per worker

This is how a full run is done. Each pytest-xdist worker initialises its own PostgreSQL 18 server
in the system temporary directory, on a free loopback port, runs its share of the tests against it
and deletes it when it finishes. No test database needs to exist first, and nothing is shared with
another worktree's run. The reference URL below still needs the shared server on 5433 to be
running, because `test_frontier_dry_run.py` reads the reference copy there.

```bash
EXULANICA_TEST_POSTGRES=private \
EXULANICA_REFERENCE_DATABASE_URL=postgresql://localhost:5433/exulanica_inspect_test \
EXULANICA_REQUIRE_POSTGRES=1 \
uv run pytest -n 6
```

Do not set `EXULANICA_TEST_DATABASE_URL` as well; the suite refuses the combination, and it refuses
`-n` with a single shared database. `EXULANICA_TEST_POSTGRES=private` without `-n` runs serially
on one private server. The servers come from `scripts/test_postgres.py`, which finds the
PostgreSQL 18 binaries through `EXULANICA_POSTGRES_BIN`, then the Homebrew and Debian locations,
then `PATH`, and refuses an older server. Each worker stops its server before it reports itself
finished, and a watcher stops it if the worker dies instead. `uv run python
scripts/test_postgres.py sweep` removes anything left by a machine crash.

Why a server each, rather than a schema or a database each. Both were measured on 2026-09-16:

- **A schema is not enough.** Migration 0041's asset-read barrier is
  `pg_advisory_xact_lock(119622341)`, and advisory locks belong to the whole database. With the
  barrier held in one throwaway schema, a guarded insert in another schema of the same database
  failed at once with "asset delivery in progress; retry mutation".
- **A database is not enough either.** The same insert in a second database succeeded, but
  `provision_runtime_role` from two databases of one server failed 40 times in 80 with "tuple
  concurrently updated". Roles belong to the whole server, and the lock that function takes
  belongs to one database.
- **A server shares its checkpoints.** A `DROP DATABASE` on the shared server waited more than six
  minutes on `CheckpointDone` while other worktrees ran their suites.

A private server costs about a second to create and start. It uses the shared server's locale
(`en_US.UTF-8`), connection limit and buffer size. It turns off `fsync` and `full_page_writes`,
which protect against a machine crash and are pointless for a cluster that is deleted on exit.
The bootstrap role is the operating-system user, a superuser, exactly as on a Homebrew server.
The four runtime roles (`exulanica_app`, `exulanica_ro`, `exulanica_purge`, `exulanica_accounts`)
are created with no privileges before any migration runs, as on a provisioned server, because
migrations 0017, 0021, 0023, 0042 and 0065 grant only to runtime roles that already exist. Without
them, a test that reads those grants passed or skipped depending on what an earlier test on the
same server had done. The tests grant the privileges they need and connect as those roles.

MEASURED 2026-09-16 at 7683a87 on an Apple M3 Pro (6 performance and 6 efficiency cores, 18 GB),
with other worktrees asked to stay idle; load average is given at the start and end of each run.
Every parallel run below failed and skipped exactly the same tests as the serial run, compared
test by test across all 4608:

| Run | Wall time | Load average |
| --- | --- | --- |
| Serial, one database on the shared 5433 server | 1074 s | 9.2 to 4.4 |
| `-n 6`, private servers | 301 s | 7.0 to 9.3 |
| Two worktrees at once, `-n 6` each | 674 s and 666 s | 9.3 to 6.5 |

Earlier the same day, on a busier machine, `-n 4`, `-n 8` and `-n 12` took 407, 468 and 310 to
333 seconds. At comparable load `-n 12` was no faster than `-n 6`, and it takes every core from
the other worktrees, so six workers, one per performance core, is the setting to use. Two
worktrees at once each take a little over twice as long as one alone, which is still well under
the time of running them one after the other.

#### Expected failures

With `EXULANICA_REFERENCE_DATABASE_URL` set as above, exactly three tests fail on any database
except the retained `exulanica_spine_test`, and they fail by design:

- `test_frontier_preflight.py::test_preflight_checks_real_schema_without_ingesting_or_creating_outputs`
  and `test_frontier_demonstration.py::test_frontier_demonstration_names_the_capture_only_and_source_first_fallbacks`
  run the frontier preflight, and `exulanica/orchestration/preflight.py` accepts only the
  reference database on port 5433.
- `test_screening_currency.py::test_shared_stale_screening_end_to_end` builds its scratch URL from
  `EXULANICA_TEST_DATABASE_URL` and then fails at `tests/test_screening_currency.py:211`, where
  `inspect_database` refuses it with "Use the permitted local reference copy on port 5433 for
  writes." (`exulanica/db/reference_target.py`).

With `EXULANICA_REFERENCE_DATABASE_URL` unset, eight fail: those three, both tests in
`test_frontier_dry_run.py`, and the three `PGHOSTADDR`, `PGSERVICE` and `PGSERVICEFILE` cases of
`test_frontier_preflight.py::test_libpq_environment_cannot_redirect_the_permitted_database`. The
five extra refuse with "Set EXULANICA_REFERENCE_DATABASE_URL=postgresql://localhost:5433/exulanica_inspect_test
before a writable rehearsal." A parallel run fails the same tests as a serial run, test by test,
in both configurations.

`EXULANICA_REFERENCE_DATABASE_URL` is the one setting that still reaches the shared server:
`test_frontier_dry_run.py` creates and drops its own schema in `exulanica_inspect_test`. It never
touches `exulanica_spine_test`, and it provisions no roles there.

#### A serial run on a named database

The earlier form still works, one process against a database you created:

```bash
brew services start postgresql@18
createdb -p 5433 exulanica_<name>_test
EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_<name>_test uv run pytest
```

On the shared development server this is the form that collides with other worktrees: two runs
provisioning runtime roles at the same moment fail each other's fixtures, and a run on the same
database fails artifact mutations with "asset delivery in progress". Give each run a fresh
database name rather than dropping and recreating one under load. Port 5433 is this project's
local example; use your server's actual port in both `createdb` and the URL.

Things to know about the harness, whichever form is used:

- **The database name must contain "test".** It refuses to touch anything else. All work happens
  inside throwaway schemas that are dropped afterwards, because each migration carries its own
  `commit;` and cannot be undone by a rollback.
- **A brand-new database needs no preparation.** The harness creates `vector`, `pgcrypto`,
  `pg_trgm` and `btree_gist` in `public` on first use, and every test that needs a runtime role
  provisions it, so the role in the URL must be allowed to create extensions and roles; the
  superuser a Homebrew install gives you is. Build any new scratch connection from
  `EXULANICA_TEST_DATABASE_URL`, as `scratch_role_database` in `tests/conftest.py` does, never from
  a spelled-out URL.
- **A server that cannot run the schema is a loud failure, not a silent substitution.** An earlier
  version of the harness swapped `gen_random_uuid()` for `uuidv7()` and `bytea` for
  `halfvec(4096)` so the suite could run on PostgreSQL 14. Everything passed and the vector path
  had never executed once, which hid a test that wrote raw bytes into a vector column.
- **`EXULANICA_REQUIRE_POSTGRES=1` turns the skip into a failure**, which is how continuous
  integration runs it. With `EXULANICA_TEST_POSTGRES=private`, a server that cannot be started
  stops the run before collection whether or not it is set.
- **Keep pytest's own configuration as it is.** `addopts` already carries `-q`; a second `-q`
  hides the pass and fail counts. Nothing configures `filterwarnings`, and `-p no:warnings` makes
  a Pillow decompression-bomb test fail, so do not pass it.
- **A test that loads torch runs in a child process.** pycolmap and torch each ship an OpenMP
  runtime, and a process that has run COLMAP aborts with exit 134 and no summary when torch
  initialises. `_isolated_torch` in `tests/test_gsplat_runner.py`, `tests/test_scene_run_preflight.py`
  and `tests/test_segmentation_stage.py` runs each such test in its own interpreter. Parallel
  workers do not remove the need: one worker can run both kinds of test.

#### A server for the API

`scripts/test_postgres.py` also keeps one persistent server per worktree for running the API
against a database of its own:

```bash
uv run python scripts/test_postgres.py serve    # start, migrate, provision roles, print URLs
uv run python scripts/test_postgres.py status
uv run python scripts/test_postgres.py stop
```

`serve` creates the database `exulanica` with the four extensions, runs `exulanica-db` as the
bootstrap owner, confirms that `exulanica_app` is not an owner, a superuser or BYPASSRLS, and prints
`EXULANICA_DATABASE_URL`, `EXULANICA_READONLY_DATABASE_URL` and `EXULANICA_PURGE_DATABASE_URL` for
the runtime roles. The application never connects as the superuser; the owner URL it prints is for
migrations and provisioning, and the API refuses to start on it.

This is a test server, and every test server is disposable. It lives in the system temporary
directory beside the per-worker servers, runs with `fsync` and `full_page_writes` off, and `serve`
migrates it on every call without a backup. Keep nothing in it you would miss. `serve`,
`Server.start` and `sweep` refuse a data directory that `exulanica-local-db` made, so a durable
database reached through a link or a copy is never run as a test server.

### A database for a personal install

A world someone builds on their own computer lives in a PostgreSQL database that
`exulanica-local-db` ([`exulanica/db/local/`](../exulanica/db/local/__init__.py)) keeps: durable,
backed up, restored only into an empty directory and upgraded only on request. It needs the same
PostgreSQL 18 with pgvector as the tests. Every command names its directory; none has a default.

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

- **Where it lives.** The directory holds `data/`, `backups/` and `server.log`. `init` and
  `restore` refuse a directory inside the system temporary directory (`TMPDIR`, or the platform's
  default), `/tmp` or `/var/tmp`, anything under the test servers' directory, and a directory
  that already holds files. Durability settings stay at PostgreSQL's defaults. The server listens
  on the loopback interface only, over TCP.
- **Passwords.** A cluster that `init` or `restore` makes asks every connection for a password
  (`scram-sha-256`), and so does each scratch copy `verify` and `upgrade` restore into. Each
  role's password is in `passwords.pgpass` beside `data/`, mode 0600, in libpq's own
  password-file format, and every URL the command prints names that file with libpq's `passfile`
  parameter, for example
  `postgresql://exulanica_app@localhost:5500/exulanica?passfile=<directory>/passwords.pgpass`, where
  `<directory>` is the database directory's absolute path.
  The application, `pg_dump` and `psql` connect through libpq, which reads the password from the
  file, so no password is printed, logged, passed on a command line or put in an environment
  variable ([`passwords.py`](../exulanica/db/local/passwords.py)). A role is given its password as
  a SCRAM verifier computed on the client, so the server never receives the password itself.
  Backups hold no passwords, and a restore gives every role a new one. The boundary is the
  operating-system account: another account on the computer cannot connect, and a process running
  as the same account can read the file, as it can read `data/`. A command refuses a password file
  another account could read, or a directory another account could write, and libpq ignores such a
  file too. `status` says which authentication the cluster uses and, when it runs, the methods its
  `pg_hba.conf` holds as the server reads them.
- **Backups.** `stop` takes one after the server stops, `backup` takes one on request, and
  `upgrade` takes one before and one after. Each is a custom-format `pg_dump` with its SHA-256
  (`.pgdump.sha256`, which `shasum -a 256 -c` reads) and a manifest (`.json`) holding every
  table's row count and the applied migrations, read in the dump's own snapshot, and the
  database's roles without their passwords. Nothing deletes a backup. They share a disk with the
  database, so copy `backups/` elsewhere to survive the loss of that disk.
- **Verify and restore.** `verify` checks the digest, restores the dump into a scratch server
  under the system temporary directory, compares its row counts and migrations with the
  manifest, and deletes the copy. `restore` does the same into an empty or absent directory and
  leaves it running on the port the backed-up database served, or on `--port`.
- **Upgrade.** `upgrade` refuses while another client is connected, so stop the API and the
  workers first. It restarts the server on a private port, backs up, applies the pending
  migrations and role provisioning to a scratch copy of that backup with the schema check the API
  runs at boot, and migrates the real database only after that rehearsal passes. A failed
  rehearsal leaves the database untouched. A migration that fails after a passing rehearsal
  leaves the server stopped and names the backup to restore.
- **Adopt.** `adopt` takes on a durable cluster another tool made, which carries no marker
  ([`adopt.py`](../exulanica/db/local/adopt.py)). `--directory` names the directory that holds its
  `data/`, and the command's backups begin in `backups/` beside it; backups another tool took
  elsewhere stay where they are, because this command can neither verify nor restore a dump
  without its own manifest. Before anything is written, it refuses a location the other commands
  refuse, a `data/` that is not a data directory or already carries the marker, another PostgreSQL
  major version, a directory another account owns, a server running with `fsync` or
  `full_page_writes` off, as the test servers run, and settings that turn either off. It connects
  as the bootstrap superuser (`--owner-role`) without a password over the loopback interface, and
  refuses a database (`--database`) that lacks a migration this code has or records one it lacks.
  Then it backs up, proves the backup restores into a scratch server, records the port the
  cluster serves on in its own settings when they do not name it (`--port`, or else the port it
  runs on or was last started on), and writes the marker last, so a failed step leaves none. It
  never migrates, changes authentication or moves the data; a running server keeps running, and a
  stopped one is started only on a private port and stopped again. The marker records that the
  cluster trusts its connections.
- **Require passwords.** `require-passwords` converts a cluster that trusts every connection from
  this computer, one that `init` made before it asked for passwords or one `adopt` took on
  ([`require_passwords.py`](../exulanica/db/local/require_passwords.py)). It refuses while another
  client is connected, so stop the API and the workers first, and runs the server on a private
  port. Before anything changes it refuses a directory another account can write, a
  `pg_hba.conf` that is not the data directory's own or holds a rule that includes another file,
  carries options, fails to parse or has a method other than `trust`, `scram-sha-256` or
  `reject`, and a role the application connects as that is absent or may not log in. Then it
  backs up and proves the backup restores, writes the password file and gives the bootstrap
  superuser and each application role a password, changes the method word of each `trust` rule in
  `pg_hba.conf` to `scram-sha-256` and keeps every other byte, reloads, and proves each of those
  roles is refused without a password and admitted with its own. The marker is written last. Any
  failure after the backup puts back `pg_hba.conf`, each role's previous password, the password
  file and the marker, shows the server admits a connection without a password again, and exits
  with `failed (authentication-change-failed)`. A run killed part way leaves a password file that
  every command already connects through, and running it again finishes the change with the
  passwords that file holds. Anything that connected without a password, such as a launcher that
  builds its own URLs, needs the printed URLs afterwards.

A refusal prints `refused (<name>)` and exits 2; a step that was attempted and failed prints
`failed (<name>)` and exits 1. The names are listed in
[`refusals.py`](../exulanica/db/local/refusals.py). The photographs and other files a world
cites are in the content-addressed store (`EXULANICA_DATA_DIR`), which this command does not back
up.

### Running the API

For a new, explicitly selected development database, first run `uv run exulanica-db` with
`EXULANICA_DATABASE_URL` set to its bootstrap owner's connection URL. This command applies all
pending migrations and provisions runtime roles; it is not a read-only check. Use the same owner
for migrations and role provisioning. Configure `EXULANICA_APP_ROLE_PASSWORD`,
`EXULANICA_EXECUTOR_ROLE_PASSWORD` and `EXULANICA_PURGE_ROLE_PASSWORD` when password authentication
is used, then switch to the non-owner runtime URL below. See [deployment](deployment.md) for the
full configuration. A database made by `exulanica-local-db` is upgraded only by its `upgrade`
command. Other existing databases, such as a retained reference copy, need a separately reviewed
backup and activation path rather than an implicit startup upgrade; that procedure is not in this
repository.

Three environment variables, and the API refuses to start without the first two rather than
defaulting to something:

```bash
export EXULANICA_DATABASE_URL=postgresql://exulanica_app:<password>@localhost:5433/exulanica
export EXULANICA_API_TOKENS='{"<a long random token>":{"workspace_id":"<uuid>","actor":"<uuid>","permissions":["library.read","library.write","world.read","world.write"]}}'
export EXULANICA_DATA_DIR=.exulanica/local          # where the content-addressed store lives
uv run uvicorn --factory exulanica.api.app:create_app --port 8000
```

If `EXULANICA_DATA_DIR` is unset, the store defaults to `.exulanica/local`. It does not look at
`.orimera/`. ADR-0011 records that the pre-release Orimera names were withdrawn before release.

The token above may read and edit the library and the world and nothing else. Each grant lists
its `permissions` from the closed vocabulary in [security-floor.md](security-floor.md), and a
grant that lists none stops startup. Add `intake.write` to upload, `model.invoke` to ask a
question, and so on.

With `NEBIUS_API_KEY` set, the model client also needs the origins it may reach, and startup
stops without them:

```bash
export EXULANICA_EGRESS_ALLOWLIST='["https://api.tokenfactory.nebius.com"]'
```

Three more are optional and all three are reported by `/readyz`, because a defence that is off and
silent is worse than one that is absent:

- `EXULANICA_READONLY_DATABASE_URL` points the Selection executor at `exulanica_ro`, a role holding
  SELECT and nothing else. Without it the executor runs as the write role.
- `NEBIUS_API_KEY` enables the two endpoints that need a model. Without it they return 503 and
  every other endpoint works.
- `EXULANICA_DERIVATIVE_WORKER=off` leaves `POST /intake` jobs to the dedicated production worker.
  The local composition sets it off and runs that worker as a separately restartable service.

For the production process shape, give both commands the same non-owner database URL and data
directory. The derivative worker produces per-photograph work. The scene worker consumes exact
multi-photograph sets with pycolmap and therefore runs in its own process:

```bash
export EXULANICA_WORKSPACE_IDS=<workspace-uuid>[,<workspace-uuid>...]
uv run exulanica-derivative-worker
export EXULANICA_CODE_REVISION=<exact-40-character-git-revision>
export EXULANICA_POSE_RUNTIME_IMAGE=<registry/image@sha256:digest>
uv run --extra pose exulanica-scene-worker
```

The command refuses an owner, superuser, or BYPASSRLS database role and refuses an empty workspace
set. SIGTERM and SIGINT stop new claims, allow the held claim to finish for the configured grace
period, and record startup, shutdown, claims, lease renewal, retries, reclaim, progress, and the one
terminal result durably. See [the derivative worker runbook](derivative-worker-operations.md).
The scene worker uses renewable leases and checkpointed scratch, but responds to deletion during
pose recovery and removes sensitive work after every terminal outcome. See
[the production reconstruction-scene runbook](scene-reconstruction-operations.md).

### Uploading photographs

```bash
curl -X POST http://localhost:8000/intake -H "Authorization: Bearer <token>" \
     -F "files=@a.jpg" -F "files=@b.jpg"
```

202, with `batch_id`, an `accepted` list carrying a capture id and a content hash each, and a
`refused` list saying which of the eight checks stopped each of the others. `GET /formation/{batch_id}`
then streams the work as it happens.

**The intake stage runs inside the request and the model stages are queued by capture id.** That
split is not about latency. An upload has to put the bytes somewhere before the pipeline can hash
them, and anywhere outside the content-addressed store is outside every tombstone guard and outside
the purger: a deletion arriving while a file sits in a spool directory or a queue payload cascades
to neither, and every test of the cascade still passes, because they look at the database and at
the store. So the staging window collapses to one request. Intake is a hash, an EXIF read, an
orientation transform and a handful of rows; the vision stage is a model call and runs in the
worker, from a capture id, over bytes already in the one place a deletion reaches.

### Erasing what a deletion asked for

A tombstone blocks every read and every derived write the moment it commits. Removing the bytes
it named is a separate step, because the object store is not in the database transaction:

```bash
uv run exulanica-purge --workspace <uuid> --data-dir .exulanica/local
```

It connects as `exulanica_purge`, through `EXULANICA_PURGE_DATABASE_URL`, and refuses to run without
it rather than falling back to the writer. That is not ceremony. `blob` is not workspace-scoped,
so two workspaces that ingest the same photograph share one object, and a purger that could only
see its own workspace would destroy bytes the other one still cites. Measured, and it is what the
separate role is for. A job whose bytes something live still holds is **deferred**, not failed,
and is asked again later; the tombstone is recorded complete only when the bytes are actually
gone, which is a different question from whether the queue went quiet.

`GET /healthz` touches nothing. `GET /readyz` runs one query and one object-store call, reports
each check separately, and never calls a model: a check every five minutes over a 46 day unattended
window is about 13,200 checks, and it must not depend on the prepaid balance.

### Web

```bash
cd web
pnpm install
pnpm check                   # typecheck, then the import-boundary contract, then vitest
```

`pnpm check` runs three gates that catch different failure modes: `tsc --build` across every
package, a dependency-cruiser contract over the forbidden cross-package imports, and 844 vitest
tests. The boundary rules have each been probed with a deliberate violation, so they are known to
fire rather than assumed to.

```bash
pnpm landing                 # the public title, Purpose and Capabilities surfaces
pnpm app                     # the canonical Atlas application
pnpm synth --out ./fixtures  # generates the renderer bake-off ladder, about ten seconds
pnpm bakeoff                 # serves the bake-off harness over those fixtures
```

Generated bake-off fixtures are gitignored. Regenerate those with `pnpm synth`. Explicitly tracked
decoder pins and the migrated courtyard point map are exceptions; preserve their provenance.
The preview also needs its locally supplied synthetic source images. Do not infer a complete
clean-checkout preview from the presence of one tracked geometry file.

### What runs

The API and worker entrypoints above exist; execution requires their stated database, role,
model and artifact prerequisites. This documentation move is not a fresh run of those commands.
The API and application start separately. `?preview=1` selects a development-only, read-only
synthetic fixture, not the authenticated backend or a personal-world acceptance run. Stop the
landing server before starting the application on its default port, or use the port printed by
Vite. There is no single command that starts Exulanica end to end.
See [capability boundaries](README.md#capability-boundaries) and the [product roadmap](product-direction.md).

## Documentation changes

Start with the [documentation standard](documentation-standard.md) and locate the existing owner
in the [catalog](all-documents.md). Edit that owner, update the navigation map if needed and run the
focused documentation checks in the standard. Do not run the full backend or browser suite for
prose-only changes. Historical evaluations remain evidence for their recorded revisions.
