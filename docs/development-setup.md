# Development setup and operations

Commands for installing extras, running the suites, starting the API and its workers, and
configuring the local store. A personal install's durable database is the
[local database](local-database.md) guide's; [deployment](deployment.md) owns the full configuration.

## Setup and running

### Prerequisites

- Python 3.11 (pinned in `.python-version`; the ML stack lags newer interpreters) and
  [uv](https://docs.astral.sh/uv/)
- Node.js 22 or newer, and pnpm 10.7.1
- Optional, for the database-backed tests: PostgreSQL

### Backend

```bash
uv sync --extra reconstruction --extra segmentation --extra pose --extra server
cp .env.example .env         # then fill in what you need; see below
uv run ruff check .          # static validation; select behavior-focused tests below
```

The full suite is run with all four extras. A plain `uv sync` installs none of them, and a test
that needs a missing extra then skips instead of failing. Every skip cause the suite accepts is
listed in [`tests/expected_skips.toml`](../tests/expected_skips.toml); continuous integration
installs no extras and fails a skip that file does not accept.

`.env` is gitignored and must never be committed. `.env.example` lists every variable the local
composition reads, each with a comment. Two of them are credentials for outside services:

| Variable | Needed for | Where to get it |
| --- | --- | --- |
| `NEBIUS_API_KEY` | Every model call, and the preflight | https://tokenfactory.nebius.com/ then "Get API key" |
| `TAVILY_API_KEY` | Web notes for drafting, for the workspaces `EXULANICA_REFERENCE_WORKSPACES` lists ([reference notes](reference-notes-contract.md)), and `scripts/verify_web_lookup.py`, a one-off credential check | https://tavily.com or the Nebius Builders Program |

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
uv run exulanica-preflight --catalog-file <provider>=<snapshot.json>   # same check, offline
uv run exulanica-ingest ingest ./photos   # safe to run repeatedly; a second run issues no model calls
uv run exulanica-ingest ingest ./photos --offline           # skip the vision stage entirely
uv run scripts/verify_platform.py      # the provider verification harness, needs NEBIUS_API_KEY
```

### The tests that need a database

**PostgreSQL is the only data layer.** The tests that carry the `postgres` marker are the
executable proof of everything the database carries: that a model cannot write a name into
canonical state, that one workspace cannot read another's rows, that a tombstoned address refuses
the write, and that the whole ingest path works. A default run prints a reminder naming the files
it skipped rather than reporting green in silence.

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

A server each, rather than a schema or a database each, because neither of those isolates one run
from another: migration 0041's asset-read barrier is an advisory lock, and advisory locks belong
to a whole database; roles belong to a whole server, so provisioning them from two databases of one
server collides; and a shared server's checkpoints make one run's `DROP DATABASE` wait on another's
work.

A private server costs about a second to create and start. It uses the shared server's locale
(`en_US.UTF-8`), connection limit and buffer size. It turns off `fsync` and `full_page_writes`,
which protect against a machine crash and are pointless for a cluster that is deleted on exit. It
allows 256 locks per transaction rather than 64, because a session ends by dropping its scratch
schema in one transaction, which locks every object in it, and a freshly migrated schema alone
takes most of what the default allows.
The bootstrap role is the operating-system user, a superuser, exactly as on a Homebrew server.
The four runtime roles (`exulanica_app`, `exulanica_ro`, `exulanica_purge`, `exulanica_accounts`)
are created with no privileges before any migration runs, as on a provisioned server, because
migrations 0017, 0021, 0023, 0042 and 0065 grant only to runtime roles that already exist. Without
them, a test that reads those grants passed or skipped depending on what an earlier test on the
same server had done. The tests grant the privileges they need and connect as those roles.

MEASURED 2026-09-16 at 7683a87 on an Apple M3 Pro with six performance cores: the serial run on one
shared database took 1074 s, and `-n 6` with private servers took 301 s, failing and skipping
exactly the same tests. More workers were no faster at comparable load and take every core from
other work, so six, one per performance core, is the setting to use.

#### The guards: checks a change anywhere can break

Some tests read the whole source tree, every route or every table: every route refuses an anonymous
caller, a stranger cannot tell a foreign id from an invented one, every table is isolated by
workspace and reached by an erasure, no product module names a game. A change anywhere can break
one, so choosing tests by the files a change touches never picks them, and a run of the whole tree
without a database skips the ones keyed on routes and tables. `tests/guard_selection.py` lists
them, and `--guards` runs exactly that list; a test file it does not name is not imported.

```bash
uv run pytest --guards -m "not postgres" -n 2
EXULANICA_TEST_POSTGRES=private uv run pytest --guards -n 2
```

The first needs no database; run it before any change lands. The second runs every guard on
private servers; run it for any change to a route, a table, a migration, SQL or a catalog. A new
test that reads the whole tree, iterates every route or inspects every table joins the list, with
one line on what it holds; `tests/test_guard_selection.py` holds every entry to a test that exists.

MEASURED 2026-10-14 at fd57f9d8 on an Apple M5 Max with 18 cores, while a full suite ran beside
it: the first command ran 2,229 guards and skipped 23 in 162 s.

#### Servers you started: one per worker

A machine without PostgreSQL's server binaries cannot initialise private servers. Continuous
integration is one: it has the client programs only, so it starts a `pgvector/pgvector:0.8.6-pg18`
container for each worker and names them, separated by whitespace, in
`EXULANICA_TEST_DATABASE_URLS`. The same on a workstation, on ports no local server claims (5433 is
the shared server, which these runs must not touch):

```bash
for port in 55432 55433; do
  docker run --detach --rm --name "exulanica-test-$port" --publish "127.0.0.1:$port:5432" \
    --env POSTGRES_HOST_AUTH_METHOD=trust pgvector/pgvector:0.8.6-pg18
done
for port in 55432 55433; do
  until pg_isready --quiet --host localhost --port "$port" --username postgres; do sleep 1; done
  psql "postgresql://postgres@localhost:$port/postgres" --command 'create database exulanica_spine_test'
done
EXULANICA_TEST_DATABASE_URLS="postgresql://postgres@localhost:55432/exulanica_spine_test
  postgresql://postgres@localhost:55433/exulanica_spine_test" \
EXULANICA_REQUIRE_POSTGRES=1 \
uv run pytest -n 2 -m "not reference_copy"
```

Worker `gw0` takes the first URL, `gw1` the second and so on, and a serial run takes the first.
Each URL must name a different server, for the reason a private server is a whole server, so the
suite refuses a list that names one server twice, a database whose name lacks "test", a list
shorter than the workers started, and the list beside `EXULANICA_TEST_DATABASE_URL` or
`EXULANICA_TEST_POSTGRES`. Before any test runs, each worker creates the four runtime roles on its
server if they are missing, as a private server has them. Preparation creates nothing else: each
database must already exist, and the server's settings are its own.

Continuous integration also splits phase 1 into parts, one per runner, with `--part K/N`: each test
belongs to exactly one part, by a digest of its node id. To replay a part of a run on a
workstation, add the same `--part` to the command above.

#### Expected failures

With `EXULANICA_REFERENCE_DATABASE_URL` set as above, these fail on any database except the
retained `exulanica_spine_test`, by design:

- `test_frontier_preflight.py::test_preflight_checks_real_schema_without_ingesting_or_creating_outputs`
  and `test_frontier_demonstration.py::test_frontier_demonstration_names_the_capture_only_and_source_first_fallbacks`
  run the frontier preflight, and `exulanica/orchestration/preflight.py` accepts only the
  reference database on port 5433.
- `test_screening_currency.py::test_shared_stale_screening_end_to_end` builds its scratch URL from
  `EXULANICA_TEST_DATABASE_URL` and then fails at `tests/test_screening_currency.py:211`, where
  `inspect_database` refuses it with "Use the permitted local reference copy on port 5433 for
  writes." (`exulanica/db/reference_target.py`).

With `EXULANICA_REFERENCE_DATABASE_URL` unset, both tests in `test_frontier_dry_run.py` and the
`PGHOSTADDR`, `PGSERVICE` and `PGSERVICEFILE` cases of
`test_frontier_preflight.py::test_libpq_environment_cannot_redirect_the_permitted_database` fail as
well, refusing with "Set EXULANICA_REFERENCE_DATABASE_URL=postgresql://localhost:5433/exulanica_inspect_test
before a writable rehearsal." A parallel run fails the same tests as a serial run, test by test,
in both configurations.

`EXULANICA_REFERENCE_DATABASE_URL` is the one setting that still reaches the shared server:
`test_frontier_dry_run.py` creates and drops its own schema in `exulanica_inspect_test`. It never
touches `exulanica_spine_test`. Its role must be a superuser (the dry run refuses any other before
it makes a schema), because migration 0161 creates the server-wide role `exulanica_definer` and
hands it the definers; a role belongs to the server, so the dry run leaves `exulanica_definer` on
the shared server after it drops its schema. It provisions no other role there.

#### A serial run on a named database

One process can run against a database you created:

```bash
brew services start postgresql@18
createdb -p 5433 exulanica_<name>_test
EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_<name>_test uv run pytest
```

On a shared development server this is the form that collides with other worktrees: two runs
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
- **A server that cannot run the schema is a loud failure, not a silent substitution.**
  Substituting types so the suite runs on an older PostgreSQL would let it pass without ever
  executing the vector path.
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
migrations and provisioning, and the API refuses to start on it. `serve` does not publish the
character catalogs: run the publication below with that owner URL and the API's data directory, or
no person is drawn.

This is a test server, and every test server is disposable. It lives in the system temporary
directory beside the per-worker servers, runs with `fsync` and `full_page_writes` off, and `serve`
migrates it on every call without a backup. Keep nothing in it you would miss. `serve`,
`Server.start` and `sweep` refuse a data directory that `exulanica-local-db` made, so a durable
database reached through a link or a copy is never run as a test server.

### A database for a personal install

A world someone builds on their own computer lives in a durable PostgreSQL database that
`uv run exulanica-local-db` keeps: created with `init`, backed up on every `stop`, restored only into
an empty directory and upgraded only by its own `upgrade`, after a rehearsal on a scratch copy. The
[local database](local-database.md) guide covers every command, its refusals and its password file.

### Running the API

For a new, explicitly selected development database, first run `uv run exulanica-db` with
`EXULANICA_DATABASE_URL` set to its bootstrap owner's connection URL. This command applies all
pending migrations and provisions runtime roles; it is not a read-only check. Use the same owner
for migrations and role provisioning. Configure `EXULANICA_APP_ROLE_PASSWORD`,
`EXULANICA_EXECUTOR_ROLE_PASSWORD` and `EXULANICA_PURGE_ROLE_PASSWORD` when password authentication
is used, then switch to the non-owner runtime URL below. See [deployment](deployment.md) for the
full configuration.

Then publish the character catalogs, with the same owner connection and the data directory the API
will serve its store from. People are drawn only from published catalogs; until this has run nobody
is drawn and `/readyz` says `people_catalog_unpublished`. It is safe to run again: an identical
catalog is answered `unchanged`.

```bash
EXULANICA_DATABASE_URL=<owner URL> EXULANICA_DATA_DIR=.exulanica/local \
  uv run exulanica-character-catalog publish --apply
```

A database made by `exulanica-local-db` is upgraded only by its `upgrade`
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
question or choose a model for a world's people, `being.act` to play one of a world's beings, and
so on.

With `NEBIUS_API_KEY` set, the model client also needs the origins it may reach, and how the
process spends, and startup stops without either:

```bash
export EXULANICA_EGRESS_ALLOWLIST='["https://api.tokenfactory.nebius.com"]'
export EXULANICA_SPENDING=process
```

`process` spends within `EXULANICA_BUDGET_USD` alone, which a restart starts again. `durable` admits
every call by the spending authority every process shares, which an operator issues and grants with
`python -m exulanica.spending` ([model spending](model-spending-contract.md)); a workspace with no
grant then spends nothing.

Three more are optional and all three are reported by `/readyz`, because a defence that is off and
silent is worse than one that is absent:

- `EXULANICA_READONLY_DATABASE_URL` points the Selection executor at `exulanica_ro`, a role holding
  SELECT and nothing else. Without it the executor runs as the write role.
- `NEBIUS_API_KEY` enables the Companion's model routes and lets the decision host ask the models a
  world's owner chose. Without it those routes answer 503, the host asks nobody and says why, and
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

### Seeing people and models locally

A world's people move when playback advances their society. The API instance advances the playing
societies of the workspaces `EXULANICA_SOCIETY_CONTROL_WORKSPACES` lists, or, when
`EXULANICA_SOCIETY_CONTROL_WORKER` is on, of every active owner's workspace and the guests' who
are there and hold a playing place ([deployment](deployment.md)).
A person's own install says so with `EXULANICA_PERSONAL_INSTALL=on`, which the acceptance launcher
sets with `--personal`: with no list it plays every workspace its tokens may write, so Run works from
the workspace page, and people brought into a world that holds a placed thing join a society of
things, where a being can say something to someone near it, unless `EXULANICA_SOCIETY_OF_THINGS`
is `off`.
For a model to decide for a person, the owner's token needs `model.invoke`, and the API needs
`NEBIUS_API_KEY` and the egress allowlist above; the owner then chooses the model in the
application's Who decides panel. A comparison of models runs from
`uv run python -m exulanica.orchestration.compare` with `EXULANICA_BUDGET_USD` set
([people and models in a world](capabilities/simulation.md#comparing-models)).

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
each check separately, and never calls a model, so a health check never spends model budget.

### Web

```bash
cd web
pnpm install
pnpm check                   # typecheck, then the import-boundary contract, then vitest
```

`pnpm check` runs three gates that catch different failure modes: `tsc --build` across every
package, a dependency-cruiser contract over the forbidden cross-package imports, and the vitest
suites.

```bash
pnpm landing                 # the public landing pages
pnpm app                     # the application
pnpm synth --out ./fixtures  # generates the renderer bake-off ladder, about ten seconds
```

Generated bake-off fixtures are gitignored. Regenerate those with `pnpm synth`. Explicitly tracked
decoder pins and the migrated courtyard point map are exceptions; preserve their provenance.
The preview also needs its locally supplied synthetic source images. Do not infer a complete
clean-checkout preview from the presence of one tracked geometry file.

### Running your own install

A person runs Exulanica on their own computer as a personal install: one command starts its database, API, workers
and the world workspace, and keeps everything they make in `~/Exulanica`. Install the [prerequisites](#prerequisites),
the [backend](#backend) and [web](#web) dependencies and PostgreSQL 18 with pgvector
([local database](local-database.md)), then work in a terminal at the root of the checkout.

For open models to decide for a world's people and to make a world from a sentence, the install needs your own Nebius
Token Factory key. Type it so that it neither shows nor enters your shell's history:

```bash
read -rs "NEBIUS_API_KEY?Nebius key: "; export NEBIUS_API_KEY      # zsh
read -rsp "Nebius key: " NEBIUS_API_KEY; echo; export NEBIUS_API_KEY  # bash
```

Then say where model requests may go and how the install spends:

```bash
export EXULANICA_EGRESS_ALLOWLIST='["https://api.tokenfactory.nebius.com"]'
export EXULANICA_SPENDING=durable
export EXULANICA_BUDGET_USD=5
export EXULANICA_BUDGET_MAX_CALLS=2000
```

The allowlist names the only origin the API may send a model request to. `durable` spends only within an allowance
granted to the install (below), which stays open across restarts. The two budget figures are a limit on each start of
the API: it stops asking after that many US dollars or calls and counts from zero at the next start. Choose your own
figures.

Start the install:

```bash
python3 scripts/acceptance/launch.py up --worktree . --personal --model --tiles
```

- `--personal` makes it your own install, kept in `~/Exulanica`.
- `--model` hands the five settings above to the API, and refuses to start, naming the first one that is missing.
- `--local-models`, optional with `--model`, offers the models this computer's runner holds beside the provider's: the
  servers the model manifest names are added after your `EXULANICA_EGRESS_ALLOWLIST`, and each model is checked once
  on this computer the first time a list shows it, which loads it into memory
  ([every model a person's runner holds](model-and-service-selection.md#every-model-a-persons-runner-holds)). A
  personal install without `--model` offers them already.
- `--tiles` lets the install bake the tiles a made town is drawn from. It compiles the tessellator first, offline,
  as the tile worker's image carries it, so each bake starts one Node process rather than compiling it again.
- `--creatures`, optional, lets the install draft creatures from words.
- `--door-bridges bridges/agents/examples/bridge-entry.json`, optional, lets AI agents built outside
  Exulanica into your worlds ([outside agents](capabilities/outside-agents.md#on-your-own-install)).
- Without `--model`, a personal install asks the free models on this computer and nothing else: the API is given an
  egress allowlist naming the servers on this computer that the model manifest names (an Ollama server, made with
  `scripts/laptop_model_recipe.py`), whose models are offered while that server answers.
- `--no-ask-again`, optional, asks no person's recorded decisions again of another model, so the pages offer no
  Compare, for a recording where no model may be scored against another; a restart keeps it.
- `--slot N` (0 to 6) moves the install to another set of ports when one is taken.

The install keeps everything the person makes in `~/Exulanica`, a folder of theirs that no other account can write:
the durable [local database](local-database.md) in `database/` (made on the first run, started on every later one, and
upgraded first when this checkout has migrations it lacks, after a file copy of the stopped data), the workspace's
identity and token in `install/`, the content store in `store/`, the world projects in `projects/` and the spending
witness in `spending-witness/`, the same directory on every run, so an allowance granted to the install stays open
across `down` and `up`. It then starts the API with a personal install's settings and its workers, and the world
workspace on the slot's app port, and prints that page's address. `down` stops the database through
`exulanica-local-db stop`, which takes a backup. Worlds played before this checkout kept their moments get them from
`python3 scripts/acceptance/launch.py moments-backfill --worktree .`, run once while the install is up and before its
worlds play on: it reports what it would write, and writes it with `--apply`
([a world's moments](synthetic-society-contract.md#a-worlds-moments)).

The launcher never writes the key to a file, a log or a record: it hands it to the API process, which holds it in
memory and sends model requests only to the allowlist's origins. Each later `up` needs the five settings again in its
terminal. Stop the install with `python3 scripts/acceptance/launch.py down --worktree .`.

#### Opening spending

A durable install spends nothing until it is granted an allowance. Grant one once, after the first `up` and while the
install runs, from a second terminal at the checkout. First read the database's owner address and the install's
workspace:

```bash
OWNER=$(uv run exulanica-local-db status --directory ~/Exulanica/database | sed -n 's/^owner (migrations and provisioning only; the API refuses it): //p')
WS=$(python3 -c 'import json, os; print(json.load(open(os.path.expanduser("~/Exulanica/install/workspace.json")))["workspace_id"])')
export EXULANICA_DATABASE_URL=$OWNER EXULANICA_SPENDING_WITNESS_DIR=~/Exulanica/spending-witness
```

Then issue the install's spending authority (the most it may ever spend, until an end date you choose), grant the
workspace an allowance under it (no larger than the authority) and check it:

```bash
uv run python -m exulanica.spending issue --provider nebius_token_factory --ceiling-usd 10 --max-calls 4000 --valid-until <YYYY-MM-DDT00:00:00Z> --operator owner --reason "own install"
uv run python -m exulanica.spending grant --authority <authority_id> --workspace "$WS" --ceiling-usd 10 --max-calls 4000 --valid-until <YYYY-MM-DDT00:00:00Z> --operator owner --reason "own install"
uv run python -m exulanica.spending status --workspace "$WS"
```

`issue` prints the `authority_id` the grant names. The running install sees the grant at once, and it stays open across
`down` and `up`. The [spending contract](model-spending-contract.md#10-operator-commands) owns these commands and
their refusals. The owner address is needed only for them, so close the second terminal afterwards.

### What runs

The API and worker entrypoints above exist; execution requires their stated database, role,
model and artifact prerequisites. The API and application start separately. `?preview=1` selects a
development-only, read-only synthetic fixture, not the authenticated backend or a personal-world
acceptance run. Stop the landing server before starting the application on its default port, or use
the port printed by Vite.

See [capability boundaries](README.md#capability-boundaries) and [product direction](product-direction.md).

### The world workspace and the product preview

The world workspace ([`tools/previews/world-workspace`](../tools/previews/world-workspace/)) is the page a personal
install serves: `--personal` starts it on its slot's app port ([running your own install](#running-your-own-install)).
The product preview ([`tools/previews/product-uiux`](../tools/previews/product-uiux/)) is a preview of a landing page
and a chooser. Both are source adapters: they transform the native application's source and use authenticated world
reads, rather than replace the production application's entry point, and their source transformations refuse changed
bootstrap seams. The app's production build makes the world workspace's transformations too
(`web/packages/app/src/dev/world-workspace-build.ts`), so a hosted deployment's client serves the workspace; its reads
go through `/api` with the page's own credentials (a personal install's bearer, a guest's session). `?preview=1` is the
read-only fixture [above](#what-runs), separate from both.

Run by hand against an existing runtime, both launchers require `EXULANICA_REVIEW_RUNTIME_STATE_FILE`, the path to a private JSON descriptor
with `ports.api` and an absolute `token_file` path. The descriptor and bearer file must stay outside
Git. Use an existing authorized runtime; the preview never creates replacement worlds. Do not log
the injected browser environment or raw transformed source, which can contain credentials.

```bash
EXULANICA_REVIEW_RUNTIME_STATE_FILE=/absolute/private/runtime.json \
  node tools/previews/world-workspace/serve.mjs

node tools/previews/product-uiux/build-home.mjs
EXULANICA_REVIEW_RUNTIME_STATE_FILE=/absolute/private/runtime.json \
  node tools/previews/product-uiux/serve.mjs
```

The world workspace uses loopback port 19974, or the port `EXULANICA_WORKSPACE_PORT` names, which
the acceptance launcher's `--personal` sets to its slot's app port. Its start page is the front door: the chosen saved world
drawn live behind its title, a filmstrip of saved worlds, Details (the world's kind, size and look) and
Open, which goes to the workspace's world view of that world at `?entry=<entry-id>`; Esc in the world
returns to the front door with that world still chosen. The live background is the same saved world in
an inert frame that only reads; the page refuses its other requests, and the development server refuses them too. An
optional private `EXULANICA_REVIEW_PREVIEWS_DIRECTORY` supplies captures for the filmstrip on the development server,
bound to matching entry, version, style and state identities; without one, and in a build, each card shows the picture
this browser kept of its world. The world view shows center aiming,
limited object-relative discovery, proximity-gated Inspect, declared entity data, and separate
behavior/activity and selected-record Companion flows. Model offers come from the server's role
catalog; an assigned model does not prove a connected provider or a recorded decision. These
adapters do not provide whole-world semantic selection, a global Companion, or renderer performance
acceptance. Their initial 6 m and 7 m inspect thresholds are prototype presentation settings.

The product preview uses 19972: `/home` serves its rebuildable landing output and `/?workspace=1`
opens the chooser. Ordinary saved-entry navigation forwards to 19974. Native camera previews stay
on 19972 and refuse writes. The tracked capture catalog is empty; live previews use actual saved
worlds. An optional private `EXULANICA_REVIEW_PREVIEWS_DIRECTORY` can supply a capture catalog and
images bound to matching entry/version/style/state identities. Keep captures and runtime data
private. The source adapters have browser/esbuild and focused boundary checks; they are outside the
production packages' strict TypeScript project graph.

The workspace's isolated observer mode requires an explicitly supplied descriptor for API 20031,
`EXULANICA_REVIEW_PORT=20032` and `EXULANICA_REVIEW_OBSERVER_ONLY=1`. It has a separate cache, permits
only GET/HEAD on its native API proxy and hides assignment, playback and Companion POST controls.
The backend must also enforce read-only authorization. This viewer reads stored activity; it does
not claim its process is a credentialed executor. It does not launch a model pilot.

### Offline entity-model pilot guards

[`tools/prototypes/entity-model-pilot`](../tools/prototypes/entity-model-pilot/) contains opt-in
guard and cleanup prototypes using the production playback, model-accounting and spending
interfaces. Run their isolated fake-interface checks explicitly:

```bash
uv run pytest -q tools/prototypes/entity-model-pilot
node tools/previews/world-workspace/verify-discovery.mjs
node tools/previews/world-workspace/verify-observer-requests.mjs
```

The tests deny real network connections, PostgreSQL connections and service construction. They
cover identity/scope fencing, bounded one-tick execution, decision/deadline/retry stopping, retained
accounting, and committed pause/revocation readback. They do not prove an actual copied runtime,
exclusive execution, live model quality, or a provider invoice ceiling. A live integration still
requires truthful copied-state/resource readers, an explicit execution allowance, and real
observer/bootstrap and cleanup preflight. These source files contain no credentials or saved-world
fixtures and are not an automatic paid launcher.

## Documentation changes

Start with the [documentation standard](documentation-standard.md) and locate the existing owner
in the [catalog](all-documents.md). Edit that owner, update the navigation map if needed and run the
focused documentation checks in the standard. Do not run the full backend or browser suite for
prose-only changes. Historical evaluations remain evidence for their recorded revisions.
