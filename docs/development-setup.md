# Development setup and operations

Commands and operational notes retained from the previous root README. Test counts and
measurement dates below are historical, not a fresh execution report.

## Setup and running

### Prerequisites

- Python 3.11 (pinned in `.python-version`; the ML stack lags newer interpreters) and
  [uv](https://docs.astral.sh/uv/)
- Node.js 22 or newer, and pnpm 10.7.1
- Optional, for the database-backed tests: PostgreSQL

### Backend

```bash
uv sync                      # creates .venv against the pinned 3.11
cp .env.example .env         # then fill in the two keys below
uv run pytest
```

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
uv run lint-imports                 # the backend layering contract, four rules
uv run exulanica-preflight            # checks every manifest id against the live catalog
uv run uvicorn --factory exulanica.api.app:create_app   # the HTTP API, on port 8000
uv run exulanica-preflight --catalog-file <snapshot.json>   # same check, offline
uv run exulanica-ingest ingest ./photos   # safe to run repeatedly; a second run issues no model calls
uv run exulanica-ingest ingest ./photos --offline           # skip the vision stage entirely
uv run scripts/verify_platform.py      # the runtime verification harness, needs NEBIUS_API_KEY
```

### The tests that need a database

**PostgreSQL is the only data layer.** 849 of the 1902 backend tests need a real server, and they
are the executable proof of everything the database carries: that a model cannot write a name into
canonical state, that one workspace cannot read another's rows, that a tombstoned address refuses
the write, and that the whole ingest path works. A default run prints a reminder naming the files
it skipped rather than reporting green in silence.

The target is PostgreSQL 18 with pgvector, and nothing is substituted for it. On macOS:

```bash
brew install postgresql@18 pgvector
brew services start postgresql@18
createdb -p 5433 exulanica_spine_test
EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test uv run pytest
```

Port 5433 is this project's local example. Use your server's actual port in both `createdb`
and the connection URL; starting PostgreSQL does not automatically select 5433.

Three things to know about that harness:

- **The database name must contain "test".** It refuses to touch anything else. All work happens
  inside throwaway schemas that are dropped afterwards, because each migration carries its own
  `commit;` and cannot be undone by a rollback. Extension setup and some role provisioning are
  database-wide or cluster-wide, so use a dedicated development server and coordinate test runs.
- **A server that cannot run the schema is a loud failure, not a silent substitution.** An earlier
  version of the harness swapped `gen_random_uuid()` for `uuidv7()` and `bytea` for
  `halfvec(4096)` so the suite could run on PostgreSQL 14. Everything passed and the vector path
  had never executed once, which hid a test that wrote raw bytes into a vector column.
- Set `EXULANICA_REQUIRE_POSTGRES=1` to turn the skip into a failure, which is how continuous
  integration should run it. A historical concurrency measurement follows; it does not establish
  that every current role-provisioning test can safely run concurrently. Serialize full database
  campaigns on the shared development machine. MEASURED
  2026-09-07 on the merged tree: two concurrent full runs each produced a failure set byte
  identical to the serial baseline, and three concurrent runs of `tests/test_ingest_cli.py`, the
  file a 2026-09-05 note blamed for six failures under concurrency, all passed. That note does not
  reproduce. Isolation is by throwaway schema (`exulanica_test_<12 hex>`), not by database, so the
  test schemas and `public` share one database and only the schema name separates them.

### Running the API

For a new, explicitly selected development database, first run `uv run exulanica-db` with
`EXULANICA_DATABASE_URL` set to its bootstrap owner's connection URL. This command applies all
pending migrations and provisions runtime roles; it is not a read-only check. Use the same owner
for migrations and role provisioning. Configure `EXULANICA_APP_ROLE_PASSWORD`,
`EXULANICA_EXECUTOR_ROLE_PASSWORD` and `EXULANICA_PURGE_ROLE_PASSWORD` when password authentication
is used, then switch to the non-owner runtime URL below. See [deployment](deployment.md) for the
full configuration. Existing retained databases require the separately reviewed backup and
[activation procedure](briefs/2026-09-08-retained-activation.md), not an implicit startup upgrade.

Three environment variables, and the API refuses to start without the first two rather than
defaulting to something:

```bash
export EXULANICA_DATABASE_URL=postgresql://exulanica_app:<password>@localhost:5433/exulanica
export EXULANICA_API_TOKENS='{"<a long random token>":{"workspace_id":"<uuid>","actor":"<uuid>"}}'
export EXULANICA_DATA_DIR=.exulanica/local          # where the content-addressed store lives
uv run uvicorn --factory exulanica.api.app:create_app --port 8000
```

If `EXULANICA_DATA_DIR` is unset, the store defaults to `.exulanica/local`. It does not look at
`.orimera/`. ADR-0011 records that the pre-release Orimera names were withdrawn before release.

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

### What runs today

The API and worker entrypoints above exist; execution requires their stated database, role,
model and artifact prerequisites. This documentation move is not a fresh run of those commands.
The API and application start separately. `?preview=1` selects a development-only, read-only
synthetic fixture, not the authenticated backend or a personal-world acceptance run. Stop the
landing server before starting the application on its default port, or use the port printed by
Vite. There is currently no single command that starts Exulanica end to end.
See [capability status](README.md#capability-status) and the [product roadmap](product-direction.md).
