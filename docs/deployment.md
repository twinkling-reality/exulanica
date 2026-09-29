# Deployment

This guide owns how Exulanica is configured and run: its processes, the environment each one
reads, the database roles, the health signals, the model catalog preflight, the seeded stack for a
reviewer, and backups and recovery. [Architecture](architecture-overview.md) owns the system's
shape, [security](security-floor.md) owns route permissions, quotas and outbound access, and
[worker operations](derivative-worker-operations.md) owns running the photograph derivative
worker. The repository holds the recipes; no cloud account, host or domain is provisioned
(section 1).

<details>
<summary>Sections</summary>

- [1. What the repository holds, and what is not provisioned](#1-what-the-repository-holds-and-what-is-not-provisioned)
- [2. Processes](#2-processes)
- [3. The database](#3-the-database)
  - [3.1 One PostgreSQL for the API and its workers](#31-one-postgresql-for-the-api-and-its-workers)
  - [3.2 A personal install on one computer](#32-a-personal-install-on-one-computer)
- [4. The content store](#4-the-content-store)
- [5. Environment configuration](#5-environment-configuration)
  - [5.1 The API process](#51-the-api-process)
    - [5.1.1 The database roles](#511-the-database-roles)
    - [5.1.2 The request body bound](#512-the-request-body-bound)
    - [5.1.3 Runtime row-level security is checked at startup](#513-runtime-row-level-security-is-checked-at-startup)
    - [5.1.4 Browser accounts](#514-browser-accounts)
    - [5.1.5 Society playback](#515-society-playback)
  - [5.2 Worker and operator commands](#52-worker-and-operator-commands)
    - [5.2.1 Migrations and roles: exulanica-db](#521-migrations-and-roles-exulanica-db)
    - [5.2.2 The derivative worker](#522-the-derivative-worker)
    - [5.2.3 The scene worker](#523-the-scene-worker)
    - [5.2.4 The purge worker](#524-the-purge-worker)
    - [5.2.5 The material bake worker](#525-the-material-bake-worker)
    - [5.2.6 The ingest command](#526-the-ingest-command)
    - [5.2.7 The catalog preflight](#527-the-catalog-preflight)
    - [5.2.8 The restore command](#528-the-restore-command)
    - [5.2.9 The reviewer seed command](#529-the-reviewer-seed-command)
    - [5.2.10 The personal database command](#5210-the-personal-database-command)
    - [5.2.11 The browser client](#5211-the-browser-client)
    - [5.2.12 Other commands and settings](#5212-other-commands-and-settings)
  - [5.3 Rules](#53-rules)
  - [5.4 What one instance runs out of](#54-what-one-instance-runs-out-of)
    - [5.4.1 The request threadpool](#541-the-request-threadpool)
    - [5.4.2 A formation stream holds a thread for its whole life](#542-a-formation-stream-holds-a-thread-for-its-whole-life)
    - [5.4.3 Connection slots](#543-connection-slots)
    - [5.4.4 Decode memory: the term that sizes the box](#544-decode-memory-the-term-that-sizes-the-box)
- [6. Health check](#6-health-check)
  - [6.1 Three signals, not one](#61-three-signals-not-one)
  - [6.2 What readiness reports](#62-what-readiness-reports)
  - [6.3 What the health check must not do](#63-what-the-health-check-must-not-do)
- [7. Model catalog preflight](#7-model-catalog-preflight)
  - [7.1 What it checks](#71-what-it-checks)
  - [7.2 Identifier casing and the catalog source](#72-identifier-casing-and-the-catalog-source)
  - [7.3 How it is run](#73-how-it-is-run)
  - [7.4 Limits](#74-limits)
- [8. A seeded deployment for a reviewer](#8-a-seeded-deployment-for-a-reviewer)
- [9. Backups and recovery](#9-backups-and-recovery)
- [10. Hosting options researched and not built](#10-hosting-options-researched-and-not-built)
- [11. Open items](#11-open-items)
- [12. Changes declined](#12-changes-declined)
  - [12.1 No connection pool](#121-no-connection-pool)
  - [12.2 No subscriber bound on the formation stream](#122-no-subscriber-bound-on-the-formation-stream)
  - [12.3 No reference counting on `blob`](#123-no-reference-counting-on-blob)
  - [12.4 No semaphore around the decode](#124-no-semaphore-around-the-decode)
  - [12.5 Poll intervals, and the shape of the queue index](#125-poll-intervals-and-the-shape-of-the-queue-index)

</details>

## 1. What the repository holds, and what is not provisioned

| Artefact | What it is |
| --- | --- |
| `Dockerfile` | One image recipe for the backend. The default build serves the API, runs migrations and runs the scene worker; a build argument selects the reconstruction extra for the derivative worker, so torch and pycolmap never share a process. The image runs as the non-root `exulanica` user, and its `HEALTHCHECK` is liveness on `/healthz`, never readiness |
| `.dockerignore` | An allowlist rather than a denylist, because `exulanica/models/credentials.py` reads a `.env` file from the working directory or a parent, and a denylist is one forgotten line away from an image that carries a credential |
| `compose.yaml` | A local composition: PostgreSQL 18 with pgvector 0.8.6 (`pgvector/pgvector:0.8.6-pg18`), the one-shot `migrate` service, the API, the derivative worker and the scene worker. It names no cloud, region, domain or account |
| `deploy/judge/` | The seeded stack for a reviewer (section 8) |
| `deploy/material-bake/Dockerfile` | The image recipe for `exulanica-material-bake`, which `compose.yaml` does not start |
| `deploy/gsplat/` | The CUDA scene-training image and the launcher that runs the scene worker on a GPU host; [scene training](gsplat-scene-jobs.md) owns both |
| `.github/workflows/check.yml` | Continuous integration: `ruff`, the import contracts, the backend suite with `EXULANICA_REQUIRE_POSTGRES=1`, the web workspace's `pnpm check` and an image build. The backend run's skips are held to `tests/expected_skips.toml` by `scripts/run_backend_suite.py --check-skips` |

`tests/test_deployment.py` holds these properties, including that `compose.yaml` and the
`Dockerfile` name no deployment target.

**Not provisioned:** no cloud account, project, region, domain, registry or host. Choosing them
is open item D-9 (section 11). The [depth image record](evaluation/2026-09-04-linux-amd64-depth-forward.json)
shows a `linux/amd64` image of the derivative worker loading the manifest's MoGe checkpoint with
network loading disabled and running the production depth adapter on a CPU under emulation. That is
compatibility evidence, not a performance result on a chosen host.

## 2. Processes

Every backend process is a command of this package. Each connects to one PostgreSQL database and
reads the content-addressed store under `EXULANICA_DATA_DIR`. Work that takes minutes (photograph
derivatives, camera-pose recovery, scene training, material bakes and purges) runs in a process of
its own and never inside a request. Hosted model calls go to Nebius Token Factory, the one provider
the [model manifest](../exulanica/models/models.manifest.json) declares, through one policy
boundary ([security floor](security-floor.md)).

| Process | Command | What it does | Settings |
| --- | --- | --- | --- |
| API | `uvicorn --factory exulanica.api.app:create_app`, the image's `CMD` | Serves the HTTP API. When configured it also drains the derivative queue and plays societies in background threads | 5.1 |
| Migrations and roles | `exulanica-db` | Applies migrations, then provisions the four application roles | 5.2.1 |
| Derivative worker | `exulanica-derivative-worker` | Drains the photograph derivative queue | 5.2.2 |
| Scene worker | `exulanica-scene-worker` | Recovers camera poses and publishes scenes for queued scene jobs | 5.2.3 |
| Purge worker | `exulanica-purge` | Destroys stored bytes that committed tombstones ask for | 5.2.4 |
| Material bake worker | `exulanica-material-bake` | Bakes requested material recipes in a Node process | 5.2.5 |
| Ingest | `exulanica-ingest` | Ingests a directory of photographs from the command line | 5.2.6 |
| Catalog preflight | `exulanica-preflight` | Checks every model identifier against its provider's catalog | 5.2.7, 7 |
| Restore | `python -m exulanica.orchestration.restore` | Replays every withdrawal into a restored database | 5.2.8 |
| Reviewer seed | `exulanica-seed` | Exports, restores and resets the seeded reviewer stack | 5.2.9, 8 |
| Personal database | `exulanica-local-db` | Creates, backs up, upgrades and restores a personal install's PostgreSQL | 5.2.10 |

## 3. The database

### 3.1 One PostgreSQL for the API and its workers

The API and every worker use one PostgreSQL 18 database with pgvector. The reason is deletion. A
vector or a caption derived from a photograph is a copy of what it was derived from, so a
withdrawal has to remove it in the transaction that records the withdrawal. A second store would
make that a two-phase delete that can be left half done, so there is no separate vector or graph
database. Caption vectors live in the `embedding` table, which is partitioned by workspace.
`compose.yaml` runs the database as its own container beside the API; no deployment host is chosen
(section 10).

### 3.2 A personal install on one computer

A person running Exulanica on their own computer runs the same PostgreSQL 18 with pgvector as a
deployment, in a cluster `exulanica-local-db` creates and keeps; the
[local database](local-database.md) guide owns its commands. The deployment's rules hold there too:
the API connects as `exulanica_app` and refuses the owner, migrations run only on request and as the
owner, every connection presents a password, and a backup is trusted once it has been restored. The
command backs up on every stop and around every upgrade, rehearses pending migrations on a scratch
copy before it migrates, and restores only into an empty directory.

The servers `scripts/test_postgres.py` starts, for the test suite and for `serve`, are disposable:
they run with `fsync` off in the system temporary directory and refuse a data directory the personal
database command made ([development setup](development-setup.md)). Nothing that should be kept
belongs on one.

## 4. The content store

Original photographs and every derived file are kept in the local content-addressed store
(`exulanica/store/local.py`) under `EXULANICA_DATA_DIR`, keyed by SHA-256. The default is
`.exulanica/local`; the image sets `/var/lib/exulanica`, and `compose.yaml` mounts the `media`
volume there for the API and both workers. Every process that reads or writes bytes must name the
same directory, or a citation resolves against a store the bytes are not in.

No runtime role deletes stored bytes. `exulanica-purge` destroys the bytes that committed
tombstones ask for, as the separate `exulanica_purge` role (5.2.4). The store is therefore
**append-only by policy**, which is exactly as strong as that separation. It is not immutable, not
write-once and not tamper-proof: a Docker volume supports none of those, and
`tests/test_deployment.py` refuses those words in the deployment recipes.

No shared object store is built. A hosted deployment needs an object-store implementation behind
`exulanica/store/base.py`; the researched design is part of section 10.

## 5. Environment configuration

Every setting is read as `EXULANICA_<NAME>` through `exulanica/env.py`, and an empty value counts as
unset. The exception is a model provider's credential, whose variable the manifest names
(`NEBIUS_API_KEY` for Nebius Token Factory). `.env.example` lists the settings with empty values.
Where a table says "no default", the process refuses to start without the setting and names it.

### 5.1 The API process

| Variable | Purpose | Default, and what refuses |
| --- | --- | --- |
| `EXULANICA_DATABASE_URL` | The connection the API opens, as `exulanica_app` | No default: `Database.from_env` raises. Startup refuses a superuser, a BYPASSRLS role or the owner of a row-level-security table (5.1.3) |
| `EXULANICA_READONLY_DATABASE_URL` | The Selection executor's connection, as `exulanica_ro` | Optional. Without it the executor runs as the write role and `/readyz` warns |
| `EXULANICA_DATA_DIR` | The content store (section 4) | `.exulanica/local`; the image sets `/var/lib/exulanica`. It does not look at `.orimera/` |
| `EXULANICA_API_TOKENS` | Bearer-token grants: a JSON object mapping each token to its workspace, actor and `permissions` ([security floor](security-floor.md#1-route-permissions)) | No default. A grant that names no permissions, or one outside the vocabulary, stops startup. May be absent when browser accounts are configured (5.1.4) |
| `NEBIUS_API_KEY` | The Nebius Token Factory credential, named by the manifest's `api_key_env` | Optional. Without it the API builds no model client, model-dependent endpoints refuse, and `/readyz` warns. A checkout may supply it in a `.env` file |
| `EXULANICA_EGRESS_ALLOWLIST` | The origins this process may reach, a JSON array ([security floor](security-floor.md#3-egress-allowlist)) | No default. Required when a model client is built or Google sign-in is configured. It must include `https://api.tokenfactory.nebius.com` for the model endpoint, and the three Google origins with sign-in (5.1.4) |
| `EXULANICA_BUDGET_USD` | The process's ceiling on model spend, in USD. It does not refill while the process runs | `5.00`. Person decisions may use all of it but the reserve their contract keeps for other work ([model selection](model-and-service-selection.md#what-a-persons-decisions-may-spend)) |
| `EXULANICA_BUDGET_MAX_CALLS` | The process's ceiling on model calls | `2000` |
| `EXULANICA_DERIVATIVE_WORKER` | Whether this process drains the derivative queue that `POST /intake` fills | On. `0`, `false`, `off` or `no` turns it off, and `/readyz` says which. `compose.yaml` turns it off and runs the dedicated worker. The in-process worker runs vision and caption vectors but no depth model |
| `EXULANICA_TEXTURE_DIRECTORY` | The published material catalog: `manifest.json`, `catalog.json` and `objects/` | A checkout finds its own; the image sets `/app/assets/textures`. Without a catalog the `/materials` routes answer 503 and `/readyz` warns; a catalog that is present but not the reviewed one stops startup |
| `EXULANICA_CHARACTER_DIRECTORY` | The character catalog behind saved looks | A checkout finds `assets/characters`. The image does not copy it, so an image-served API answers 424 to saving a look unless this names a catalog. A catalog and designed looks that disagree stop startup |
| `EXULANICA_SOCIETY_AUTHORED_WORLDS` | A JSON file (`exulanica.society-authored-worlds/v1`) of host registrations that bind a saved world's society to a named place | Optional; without it a society binds a place derived from the world itself. A malformed file stops startup |
| `EXULANICA_RESTORE_STATE_PATH` | The restore marker the API checks at startup | Optional. With it, a sealed or replaying database refuses to serve ([ADR-0019](adr/0019-offline-restore-tombstone-replay.md)) |
| `EXULANICA_GOOGLE_CLIENT_ID`, `EXULANICA_GOOGLE_CLIENT_SECRET`, `EXULANICA_GOOGLE_CALLBACK_URI`, `EXULANICA_GOOGLE_RETURN_URIS`, `EXULANICA_ACCOUNT_BROWSER_ORIGINS`, `EXULANICA_ACCOUNT_DATABASE_URL` | Google sign-in and browser accounts (5.1.4) | Optional, all six or none: a partial set stops startup |
| `EXULANICA_SOCIETY_CONTROL_WORKSPACES`, `EXULANICA_SOCIETY_TICK_INTERVAL_MS`, `EXULANICA_SOCIETY_CONTROL_WORKER` | Society playback (5.1.5) | Playback is off by default |

#### 5.1.1 The database roles

`exulanica-db` provisions `exulanica_app`, `exulanica_ro`, `exulanica_purge` and
`exulanica_accounts` after the migrations, in one order, and the reviewer stack adds
`exulanica_judge` (section 8). What each role holds, and why each is separate, is the
[security floor](security-floor.md#5-database-roles)'s. Each process connects as the role its table
in section 5 names, and the bootstrap owner's connection belongs to `exulanica-db` alone (5.1.3).

#### 5.1.2 The request body bound

`POST /intake` is multipart, and the body is received and parsed before any route function and any
dependency runs, so before authentication. Starlette's `max_part_size` bounds only the parts that
are not files, and the route's own `MAX_PART_BYTES` check in `exulanica/api/routes/intake.py` reads
a part that is already spooled, so neither bounds what reaches the disk.

`exulanica/api/body_limit.py` is pure ASGI middleware upstream of all of that, and applies two
bounds to `MAX_BODY_BYTES` (512 MiB):

- a declared `Content-Length` over it is refused before a byte is read;
- a request that declares no length, which is what `Transfer-Encoding: chunked` produces, is
  counted as it arrives and cut off the moment the running total crosses the limit. The overshoot
  is one chunk rather than the whole body.

The composition has no reverse proxy and no static client host (open item D-13), so these are the
only bounds. Whatever terminates TLS for a chosen host should carry a body limit of its own
(`client_max_body_size` on nginx, `proxy-body-size` on an ingress), because a proxy refuses before
the application is involved at all.

#### 5.1.3 Runtime row-level security is checked at startup

`compose.yaml` gives the bootstrap owner URL to the one-shot `migrate` service only. The API,
derivative worker and scene worker receive `exulanica_app`, and the Selection executor receives
`exulanica_ro`. The order is: migrate as the owner, provision the roles, then start the runtime
containers with credentials that own no table and hold neither SUPERUSER nor BYPASSRLS.

A connection string is not proof of the role behind it. Startup queries `pg_roles` and the current
schema and refuses to serve or drain when the current role is a superuser, has BYPASSRLS, or owns
any row-level-security table. The API lifespan and the derivative, scene and material bake
workers run this check before they accept work; the purge worker checks its own role instead
(5.1.1). `tests/test_row_level_security.py` exercises both directions against PostgreSQL.

Every table under FORCE row-level security is keyed on `current_workspace()`.
`tests/test_migration.py` lists those tables from a migrated schema and fails when one is keyed on
anything else. The authorization, screening and admission records behind reconstruction
(migration 0029) are append-only under the same policy, so a later runtime write cannot rewrite
why geometry was permitted.

#### 5.1.4 Browser accounts

Google sign-in is optional, and its six settings are required together:

| Variable | Purpose |
| --- | --- |
| `EXULANICA_GOOGLE_CLIENT_ID` | The registered Google web OAuth client |
| `EXULANICA_GOOGLE_CLIENT_SECRET` | The server-only client credential |
| `EXULANICA_GOOGLE_CALLBACK_URI` | The exact HTTPS `/auth/google/callback` URL registered with Google |
| `EXULANICA_GOOGLE_RETURN_URIS` | A JSON array of the exact permitted post-login URLs |
| `EXULANICA_ACCOUNT_BROWSER_ORIGINS` | A JSON array of the permitted HTTPS browser origins |
| `EXULANICA_ACCOUNT_DATABASE_URL` | The `exulanica_accounts` connection to the same database |

The account tables (migration 0058) sit outside workspace scope. `exulanica-db` provisions
`exulanica_accounts`, a non-owner NOINHERIT role that reaches them and no world record, and the
application roles cannot read them. Startup checks that separation against the application's own
connection. Provider requests run outside database transactions and are held to
`EXULANICA_EGRESS_ALLOWLIST`, which must include `https://accounts.google.com` (discovery),
`https://oauth2.googleapis.com` (token) and `https://www.googleapis.com` (JWKS), or startup stops
and names the origins it lacks. The endpoint URLs are pinned in `exulanica/api/account_runtime.py`:
if Google moves its token endpoint or JWKS, sign-in fails closed with `503 account_unavailable`, and
the fix is to update the pinned URLs as well as the allowlist. The callback and the session cookie
require HTTPS; a plain HTTP preview is not a sign-in deployment.

`GET /auth/google/start` begins sign-in, `GET /auth/google/callback` completes it,
`GET /auth/session` returns the current membership and CSRF token, and `POST /auth/logout` revokes
the cookie. Cookie-authenticated writes require the matching `X-CSRF-Token` and an exact permitted
`Origin`. An explicit Authorization header uses the bearer path and never falls back to a cookie.
Without accounts configured, the account endpoints answer 503. With accounts configured,
`EXULANICA_API_TOKENS` may be absent, but a token setting that is present and invalid is still
refused. Readiness checks account persistence without contacting Google.

The browser checks `/auth/session` when no development token is built in. A signed-in session opens
the owned workspace with cookie credentials and adds its in-memory CSRF value to writes; a
signed-out session is offered Google sign-in; a host without account configuration shows the
developer-token entry instead. An account starts with an empty workspace of its own, with no world
copied into it and no link inferred to existing bearer data. Derivative workers combine their
configured workspaces with a fresh account-role query for active owner memberships when accounts
are configured; a browser session is never taken as membership authority. Account revocation keeps
historical attribution. Full account-data deletion, invitations, retention cleanup and request rate
limits are not built. Access logs must redact callback query values, cookies and CSRF tokens.

#### 5.1.5 Society playback

Automatic playback is off unless the host turns it on. `build_services` reads these settings and
stops startup on a malformed value, with a named code from `SOCIETY_SETTING_REFUSALS` in
`exulanica/api/services.py`:

| Variable | Purpose |
| --- | --- |
| `EXULANICA_SOCIETY_CONTROL_WORKSPACES` | A JSON array of workspace ids whose playing societies this instance advances, with no accounts needed. Absent or `[]` plays none; a malformed or repeated id is refused |
| `EXULANICA_SOCIETY_TICK_INTERVAL_MS` | The base wait between simulated minutes, in whole milliseconds: 1,000 to 60,000 and divisible by 4, so every speed divides it exactly. Absent means the declared default, 8,000 |
| `EXULANICA_SOCIETY_CONTROL_WORKER` | Account-wide discovery. Absent or `off` disables it; `true`, `yes`, `on` or `1` also plays every current account-owned workspace, and needs accounts configured |
| `EXULANICA_COMPARISON_WORKER` | Who plays the comparisons started from the application for the listed workspaces. Absent, this process, in a thread; `process`, a process of its own (5.2.12), and this one only serves starts; `off`, nothing, and every start is refused as `comparisons_not_played`. Any other value stops startup (`comparison_worker_not_recognised`) |

Listed and discovered workspaces are played together. A person's saved world needs no host
registration, because its society binds a place derived from the world itself. The default base
wait is measured: at it, a person in a saved world walks at an ordinary pace
([record](evaluation/2026-09-24-living-world-pace.json)). The API starts the playback worker only
after schema and restore validation, stops new claims on shutdown and waits for an active batch to
finish or roll back. Readiness reports its thread, its latest round, the base wait, how many
workspaces are listed (never which) and whether account discovery is on; it promises no delivery
rate. Playback controls, speeds, the `host_playback` field and recovery are the
[society contract](synthetic-society-contract.md#persisted-playback-controls-and-bounded-host-progression)'s.

A playing world whose people are run by models asks those models through this process's client, so
the model settings in 5.1 apply; the decision contract's spend bounds are in
[model selection](model-and-service-selection.md#what-a-persons-decisions-may-spend).

### 5.2 Worker and operator commands

#### 5.2.1 Migrations and roles: exulanica-db

| Variable | Purpose |
| --- | --- |
| `EXULANICA_DATABASE_URL` | The bootstrap owner's connection. Migrations and role grants run in one command because there is one correct order |
| `EXULANICA_APP_ROLE_PASSWORD`, `EXULANICA_EXECUTOR_ROLE_PASSWORD`, `EXULANICA_PURGE_ROLE_PASSWORD`, `EXULANICA_ACCOUNT_ROLE_PASSWORD` | Passwords for `exulanica_app`, `exulanica_ro`, `exulanica_purge` and `exulanica_accounts`. Each is optional and set only when supplied, because a role that authenticates by certificate or by peer has none |

#### 5.2.2 The derivative worker

`exulanica-derivative-worker` drains the queue `POST /intake` fills. Its delivery contract,
progress, shutdown and recovery are in [worker operations](derivative-worker-operations.md).

| Variable | Purpose |
| --- | --- |
| `EXULANICA_DATABASE_URL` | The `exulanica_app` connection |
| `EXULANICA_WORKSPACE_IDS` | Comma-separated workspaces to drain, or repeated `--workspace` flags. An empty set is a startup failure unless `EXULANICA_ACCOUNT_DATABASE_URL` is set |
| `EXULANICA_ACCOUNT_DATABASE_URL` | Optional: also drain every active account-owned workspace, discovered through the account role |
| `EXULANICA_DATA_DIR` | The content store |
| `NEBIUS_API_KEY`, `EXULANICA_EGRESS_ALLOWLIST`, `EXULANICA_BUDGET_USD`, `EXULANICA_BUDGET_MAX_CALLS` | The vision and caption-vector calls, as in 5.1. Without the credential no model stage runs |
| `EXULANICA_DEPTH_MODEL` | `moge` or `unavailable`, the default. `compose.yaml` sets `moge`; the checkpoint is the one the manifest pins as `local_roles.depth` |
| `EXULANICA_DEPTH_DEVICE` | Optional torch device such as `cuda`, `mps` or `cpu`; absent, the depth model selects MPS, then CUDA, then CPU |
| `EXULANICA_DEPTH_MODEL_ID`, `EXULANICA_DEPTH_MODEL_REVISION` | Retired. The worker refuses to start while either is set |
| `EXULANICA_PERSON_DETECTOR` | `recorded-observation` or `unavailable`, the default: whether the worker proposes person regions from the vision observation |
| `EXULANICA_SEGMENTATION_MODEL` | `local` or `unavailable`, the default. `local` needs the `segmentation` extra and loads the checkpoints the manifest's `local_roles` pin; startup fails if either is missing |
| `EXULANICA_SEGMENTATION_DEVICE` | Optional torch device for the segmenter; absent, it selects MPS, then the CPU |

`compose.yaml` keeps the model cache on the media volume (`HF_HOME`), so a restart does not download
the checkpoint again.

#### 5.2.3 The scene worker

`exulanica-scene-worker` claims scene jobs, recovers camera poses and publishes scenes;
[scene reconstruction operations](scene-reconstruction-operations.md#7-running-the-worker) owns how
it is run.

| Variable | Purpose |
| --- | --- |
| `EXULANICA_DATABASE_URL` | The `exulanica_app` connection |
| `EXULANICA_WORKSPACE_IDS` | Comma-separated workspaces, or `--workspace` flags; required |
| `EXULANICA_DATA_DIR` | The content store; scratch work goes under `reconstruction-scratch` |
| `EXULANICA_CODE_REVISION` | Required: the exact 40-character source revision recorded in every pose manifest |
| `EXULANICA_POSE_RUNTIME_IMAGE` | Required: the digest-pinned image reference recorded in every pose manifest; a mutable tag is not provenance |
| `EXULANICA_SCENE_JOB_IDS` | Optional: comma-separated scene jobs to claim, or `--job` flags. Without either, the worker drains every eligible job in its workspaces |
| `EXULANICA_COMPRESSOR_GPU` | `cpu`, the default, or a WebGPU adapter index for the SOG compressor's k-means. It is recorded in each compression attempt |

The scene-training image (`deploy/gsplat/Dockerfile`) sets `EXULANICA_BUILD_REVISION` from its
`CODE_REVISION` build argument, and the trainer refuses to run when it differs from the build
manifest's code revision (`exulanica/reconstruction/gsplat_runner.py`).

**Checking a scene before compute is allocated.**
`uv run python scripts/prepare_scene_run.py --workspace WORKSPACE_UUID --scene SCENE_UUID` inspects a
published scene through `EXULANICA_DATABASE_URL` and the local store, reads its current source
permissions and pose receipts, and reports stage-specific blockers. It does not modify the scene or
queue work. For an eligible scene, `--manifest`, `--source-manifest`, `--dataset`, `--pose-receipt`,
`--run-output` and `--resources` bind the source set, held-out split, pose, runtime, seed and
checkpoint identity to the run; resources declare hardware, time and storage allowances, and absent
values block a complete plan. Completed training or conversion artifacts are checked for reuse
before another run is recommended, and checkpoint inspection, which needs the optional PyTorch
dependency, validates complete optimizer and random-generator state on the CPU. Exit code 0 and
`plan_ready` mean the specification is ready for review; execution still goes through source
admission, the job lease, stage checks and container cleanup, and a saved report is not a standing
authorization.

#### 5.2.4 The purge worker

| Variable | Purpose |
| --- | --- |
| `EXULANICA_PURGE_DATABASE_URL` | Required: the `exulanica_purge` connection. There is no fallback to the writer, because the purge role holds a cross-workspace read the runtime role must never have and the runtime role holds writes the purger must never need |
| `EXULANICA_DATA_DIR` | The content store, or `--data-dir` |

The workspaces to drain are named with `--workspace`, repeatably, and never discovered. Each run
makes one pass over at most `--limit` jobs (500 by default). The command is idempotent and safe to
run repeatedly; `compose.yaml` does not schedule it.

#### 5.2.5 The material bake worker

| Variable | Purpose |
| --- | --- |
| `EXULANICA_DATABASE_URL` | The `exulanica_app` connection |
| `EXULANICA_WORKSPACE_IDS` | Comma-separated workspaces, or `--workspace` flags. With none of these and no account discovery, startup fails |
| `EXULANICA_ACCOUNT_DATABASE_URL` | Optional: also bake for every active account-owned workspace |
| `EXULANICA_DATA_DIR` | Bakes are written to the material namespace beside the blob store, and `exulanica-purge` destroys them from there |
| `EXULANICA_TEXTURE_DIRECTORY` | The published material catalog, as in 5.1 |
| `EXULANICA_WEB_DIRECTORY` | Where the web package and its installed dependencies are |
| `EXULANICA_NODE` | The Node executable; absent, `node` on `PATH` |

Nothing is downloaded at run time: the worker refuses to start without Node, the tsx loader and the
baker. Each bake runs under a timeout and a memory ceiling (`--timeout-seconds`, `--memory-mib`).

#### 5.2.6 The ingest command

`exulanica-ingest ingest <path>` reads `EXULANICA_DATABASE_URL` and the content store
(`EXULANICA_DATA_DIR` or `--data-dir`). Unless `--offline` is given, it runs the catalog preflight
before its vision stage (skipped only with `--skip-preflight`), so it also needs `NEBIUS_API_KEY`
and an `EXULANICA_EGRESS_ALLOWLIST` that includes the catalog origin. Its model client retries the
same model with backoff and caches responses under the data directory; the budget settings of 5.1
apply.

#### 5.2.7 The catalog preflight

`exulanica-preflight` fetches each provider's public catalog, which needs no credential but passes
the egress allowlist: `EXULANICA_EGRESS_ALLOWLIST` must include each provider's catalog origin,
`https://tokenfactory.nebius.com` for Nebius Token Factory, a different host from its endpoint.
`--catalog-file PROVIDER=PATH` checks against a saved snapshot and reaches no network. Section 7
says what it checks.

#### 5.2.8 The restore command

`python -m exulanica.orchestration.restore checkpoint`, `prepare` and `replay` read
`EXULANICA_DATABASE_URL` (the administrative connection of the source or restored database),
`EXULANICA_PURGE_DATABASE_URL` (replay) and the content store. The API then reads
`EXULANICA_RESTORE_STATE_PATH` (5.1). The procedure is [ADR-0019](adr/0019-offline-restore-tombstone-replay.md)'s,
and [ADR-0026](adr/0026-a-restore-carries-every-withdrawal.md) states which withdrawals a restore
carries.

#### 5.2.9 The reviewer seed command

`exulanica-seed` (`export`, `verify`, `describe`, `restore`, `reset`, `role`, `token`) reads
`EXULANICA_DATABASE_URL`, the content store (`EXULANICA_DATA_DIR` or `--data-dir`), and, for `role`,
`EXULANICA_JUDGE_ROLE_PASSWORD`. Section 8 describes the stack it serves.

#### 5.2.10 The personal database command

`exulanica-local-db` finds the PostgreSQL 18 binaries in `EXULANICA_POSTGRES_BIN`, then in the
usual Homebrew and Debian locations, then on `PATH`. It prints the four connection settings the
application reads (`EXULANICA_DATABASE_URL`, `EXULANICA_READONLY_DATABASE_URL`,
`EXULANICA_PURGE_DATABASE_URL` and `EXULANICA_ACCOUNT_DATABASE_URL`) as `export` lines, each naming
its own role. The [local database](local-database.md) guide owns its steps.

#### 5.2.11 The browser client

| Variable | Read by | Purpose |
| --- | --- | --- |
| `VITE_EXULANICA_TOKEN` | a development build of `web/packages/app` | A bearer token built into a development build. A production build carries none and asks for a token, or uses the account session |
| `VITE_NYC_OPEN_DATA_ADMISSION_ID` | `web/packages/app` at build time | The one admitted NYC Open Data source the semantic workflow reads; absent, that workflow is unavailable |
| `EXULANICA_API_URL` | the Vite development and preview servers | Where `/api` is proxied; default `http://127.0.0.1:8000` |
| `EXULANICA_CHARACTER_BUILDER_URL` | the Vite development server | Where `/__character` is proxied for the character builder; default `http://127.0.0.1:5196` |

#### 5.2.12 Other commands and settings

- `exulanica-eval` reads `EXULANICA_EVALUATION_OWNER_DATABASE_URL`; the
  [evaluation corpus contract](evaluation-corpus-contract.md) owns it.
- `python -m exulanica.orchestration.compare` builds the API's services from the settings in 5.1 and
  refuses to start without `EXULANICA_BUDGET_USD`, which bounds that comparison;
  [society experiments](society-experiments.md#comparisons-of-models) owns it.
- `python -m exulanica.orchestration.comparison_worker` plays the comparisons started from the
  application for the workspaces `EXULANICA_SOCIETY_CONTROL_WORKSPACES` lists, from the settings in
  5.1, when the API runs with `EXULANICA_COMPARISON_WORKER=process`; each plays within the bound its
  owner stated ([running a comparison](society-experiments.md#running-a-comparison)).
- `exulanica-wmp` is owned by the [world memory package](world-memory-package.md), and
  `exulanica-gsplat-scene-v1` by [scene training](gsplat-scene-jobs.md).
- `EXULANICA_LENS_BUDGETS` configures the per-lens guard in `exulanica/models/lens_budget.py`, which
  no command constructs ([security floor](security-floor.md#4-model-spend-budgets)).
- `TAVILY_API_KEY` is read only by `scripts/verify_web_lookup.py`, a one-off credential check. No
  product code calls a web-lookup provider.
- The test suite's settings, such as `EXULANICA_TEST_DATABASE_URL`, `EXULANICA_TEST_POSTGRES`,
  `EXULANICA_REQUIRE_POSTGRES` and `EXULANICA_REFERENCE_DATABASE_URL`, are in
  [development setup](development-setup.md).
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` and `EXULANICA_PORT` are read by
  `compose.yaml` itself, and `EXULANICA_SEED_ARCHIVE` and `EXULANICA_JUDGE_PORT` by
  `deploy/judge/compose.yaml`; `EXULANICA_SYNC_EXTRAS` is an image build argument.

### 5.3 Rules

- **No model credential reaches the browser.** The Token Factory key is server-side only. A design
  where the browser calls a model provider directly is rejected, because a credential in a static
  bundle is a published credential. A development build may carry `VITE_EXULANICA_TOKEN`; a
  production build carries none.
- **Fail closed at startup.** A missing or malformed required setting stops the process with the
  setting named. A service that starts and then fails on its first request is harder to notice than
  one that never came up.
- **Model identifiers are not configuration.** They live in `exulanica/models/models.manifest.json`
  and no environment variable overrides them. Changing an identifier bumps the manifest's
  `pipeline_version`, which stored vectors and records are keyed by, and the response cache key names
  the provider and the model, so a cached answer is never served for another model.
- **Secrets are not committed and are not baked into images.** They are injected at run time.

### 5.4 What one instance runs out of

These are properties of the composition that a deployment inherits; none is an environment variable.
The order below is the order in which one API process runs out.

#### 5.4.1 The request threadpool

None of the route handlers under `exulanica/api/routes/` is `async def`, so every request occupies a
worker thread of the ASGI threadpool for as long as it runs. The threadpool is anyio's default
limiter of 40 tokens. Nothing in the application sets it, and uvicorn has no flag for it: the only
place to change it is `anyio.to_thread.current_default_thread_limiter().total_tokens` inside the
application's own lifespan.

#### 5.4.2 A formation stream holds a thread for its whole life

`GET /formation/{batch_id}` (`exulanica/api/routes/formation.py`) streams one intake batch's
progress. It polls every `_POLL_SECONDS` (2 seconds) and sends a heartbeat every
`_HEARTBEAT_EVERY` (7) polls, holding its thread and its connection throughout. Once every thread is held, every other request waits for one, `/healthz`
included, because it is a synchronous handler on the same limiter. The container's health check
allows two seconds (`urlopen(..., timeout=2)` in the `Dockerfile`), so a saturated instance fails it
and Docker restarts it; that consequence is deduced, not observed (open item D-15). A browser that
disappears keeps its slot until the stream next tries to send. Section 12.2 says why there is no
subscriber bound.

#### 5.4.3 Connection slots

A request opens one database connection through `scoped_connection` or `readonly_connection` in
`exulanica/api/dependencies.py` and holds it for the request's whole duration. There is no pool
(section 12.1). The threadpool does not cap connections: a request waiting for a thread already
holds its connection, so one API process can demand as many backends as it has requests in flight.
A PostgreSQL server at its default `max_connections` of 100 with 3 superuser slots leaves 97 for the
runtime roles, shared by every API process and worker on that server. `uvicorn --limit-concurrency`
is the only lever that counts requests where they are held, and nothing sets it (open item D-14).

#### 5.4.4 Decode memory: the term that sizes the box

One photograph at `MAX_PIXELS` (64 megapixels) costs about 512 MB at peak: Pillow stores `RGB` at
four bytes per pixel, and `ImageOps.exif_transpose` allocates a second buffer of the same size.
`exulanica/corpus/decode.py` holds the measurement and its environment.

    API worst-case bytes = baseline + T x 67 MB + D x 512 MB

`T` is the threadpool (40) and `D` the number of request decodes running at once. The 67 MB per
thread is the encoded part the intake route reads into memory before it probes anything
(`MAX_PART_BYTES` plus one byte). Nothing bounds `D`, so `D` is `T`: about 20 GiB of decode buffers
plus about 2.7 GB of encoded parts. The composition turns the in-process derivative worker off; the
dedicated worker is a separate process with one delivery thread, so budget about another 512 MB for
each worker process. The levers that reduce the product are the threadpool size, `MAX_PART_BYTES`
and `MAX_PIXELS`, in that order. Section 12.4 says why there is no decode semaphore.

## 6. Health check

`exulanica/api/routes/health.py` serves both endpoints. Neither requires a credential, and neither
returns anything about a workspace's contents.

### 6.1 Three signals, not one

| Signal | Path | Cost | Checks |
| --- | --- | --- | --- |
| Liveness | `GET /healthz` | Nothing beyond the process | The process is running and can serve a request. No dependency is touched |
| Readiness | `GET /readyz` | A few cheap queries and one store probe, no model call | The dependencies a request needs are reachable (6.2) |
| Catalog integrity | Not an endpoint: a scheduled `exulanica-preflight` | One public catalog fetch per provider, no credential, no model call | Every model identifier the application can reach still exists and declares the use cases its role needs (section 7) |

### 6.2 What readiness reports

`/readyz` answers 503 when any check fails, and reports each check separately with what it proves:

| Check | What it proves | What it cannot prove |
| --- | --- | --- |
| `database` | A newly opened connection answered `select 1`, so the server is up and had a free connection slot at that moment | Anything about the next request, which needs a slot of its own (5.4.3) |
| `schema` | The applied migrations equal the ones this code expects | Anything about data integrity |
| `object_store` | The content store answers an existence probe for a key that cannot exist | Whether any scene's bytes are complete |
| `model_manifest` | The manifest parses and every role it binds resolves to an identifier | Whether that model still exists in the catalog; that is the third signal |
| `derivative_worker` | A worker this process was asked to run is alive, or the process says it was not asked to run one | Whether the queue is empty |
| `accounts` | The account store is reachable, when accounts are configured | Live Google sign-in, which is not probed |
| `society_playback` | The playback worker's thread is alive and its last round did not fail, when playback is configured | Any simulation delivery rate |

It also returns `warnings`, what this instance is running without (for example no read-only
executor role, no model credential, no material or character catalog, or a spent model budget), and
`configuration`, which names each setting as set or missing and never shows a value.

### 6.3 What the health check must not do

- **It must not call a model.** A probe that runs every few minutes would spend on every run, and
  health would go red the day the prepaid balance ran out, for a reason unrelated to the service
  being up.
- **It must not claim more than it checks.** A 200 from `/healthz` says the process is alive. It does
  not say the reasoning model still exists; a green health check in front of a withdrawn model is
  the failure the catalog preflight exists for.
- **It must not be expensive enough to matter.** Readiness runs on every external probe; a costly
  check gets turned off or becomes the thing that falls over.

## 7. Model catalog preflight

`exulanica/models/preflight.py` holds the check, and the console script `exulanica-preflight` runs
it through `exulanica/orchestration/catalog_preflight.py` (also runnable as
`python -m exulanica.orchestration.catalog_preflight`), which gives it the roles the decision role
registry declares, so every model a role is offered is held to that role's use cases. It exits 0
when clean and 1 on any failure, so a build step and a scheduled check can both call it without
parsing output.

### 7.1 What it checks

Nebius Token Factory has withdrawn models from its serverless catalog (11 on 2026-06-22 and 10 on
2026-08-31). A withdrawn identifier fails at the first request that names it, so the check runs
before that request can happen.

| Check | What it catches | Severity |
| --- | --- | --- |
| Presence | Every identifier a role can reach, primary and fallback alike, and every model verified to answer a choice, appears in the catalog's `flavors[].model_id`. A fallback that has itself been withdrawn is a failover that fails | Fatal |
| Capability | The identifier still declares the `use_cases` its role needs. Asserted on `use_cases` and never on `type`, because a model typed `text2text` was measured to accept an image and describe it correctly | Fatal |
| Price drift | The catalog price differs from the manifest price | Warning: a price change breaks the cost report rather than the service |

### 7.2 Identifier casing and the catalog source

The catalog's human-readable `name` differs from the callable `model_id`, inconsistently. Both the
manifest and the preflight read `flavors[].model_id` and never `name`; reading `name` produces an
identifier that fails at run time and looks like a withdrawal. The catalog each provider's
`catalog_url` names, for Nebius Token Factory
`https://tokenfactory.nebius.com/api/public/models_info`, is the authoritative source together with
the API's OpenAPI description, because the provider's prose documentation has described identifiers
that are not in the catalog.

### 7.3 How it is run

| When | Invocation | On failure |
| --- | --- | --- |
| Before a deployment starts | `exulanica-preflight` | A non-zero exit stops the deployment. No deployment pipeline in the repository runs it |
| Continuous integration, offline | `exulanica-preflight --catalog-file <provider>=<snapshot>`, one flag per provider a checked model is served by | The backend suite runs it against committed catalog snapshots (`tests/test_models_manifest.py`), so the suite does not depend on the network |
| On a schedule, against a running deployment | `exulanica-preflight --json` | The report names each identifier and role that failed |
| Before the ingest command's vision stage | Run by `exulanica-ingest` unless `--skip-preflight` or `--offline` | The command refuses to run the vision stage |

### 7.4 Limits

1. An unreachable catalog is reported as a failure, exit 1. That is right for a deployment step and
   wrong for a scheduled check, where a transient network failure should be retried before anyone
   is alerted (open item D-5).
2. The embedding role has no fallback. It is the only embedding-typed model in the catalog, and
   substituting a model from another vector space would silently poison every stored vector. The
   preflight detects its removal; nothing recovers from it (open item D-6).
3. The fallback rule (fall back on a 404-class error only) is exercised by
   `tests/test_models_client.py` through a scripted transport. No run has forced a live primary to
   fail (open item D-7).

With a fallback declared, a withdrawn primary degrades answer quality rather than failing the call;
the embedding role and a model a world chose for a person have no fallback.

## 8. A seeded deployment for a reviewer

`deploy/judge/compose.yaml` is a standalone composition that starts from a versioned seed archive
rather than an empty database. It runs five services: PostgreSQL, the one-shot migration, a
one-shot seeding job (`exulanica-seed role`, then `exulanica-seed restore --archive /seed`, which
verifies every row file and blob against the archive's manifest before loading it), the API, and
the browser client behind a same-origin proxy on `127.0.0.1` (port `EXULANICA_JUDGE_PORT`, default
8080). It runs no derivative or scene worker, because the seed is already reconstructed and
reconstruction never runs in a request.

Its API connects as `exulanica_judge`, which may read every table, may insert and update only an
allowlist of tables, and may delete nothing, so "may read, may not write a source or a deletion" is
enforced by the database rather than intended. The reviewer's bearer token holds the permissions
`JUDGE_PERMISSIONS` names in `exulanica/orchestration/judge_seed.py`: reads, the authored world and
its appearance, the Companion, deleting a memory the reviewer made, and the model calls those need;
intake, admission, consent writes, operations writes and tile materialisation are absent.

1. On the source database, `exulanica-seed export --workspace <uuid> --into <new directory>` writes
   the workspace's rows and bytes; `exulanica-seed verify --archive <directory>` re-hashes an archive
   against its own manifest.
2. `exulanica-seed token --workspace <uuid> --out <file>` writes the reviewer's token directory with
   mode 0600 and prints only the token's digest; load it with `EXULANICA_API_TOKENS="$(cat <file>)"`.
3. Start the stack with `POSTGRES_PASSWORD`, `EXULANICA_APP_ROLE_PASSWORD`,
   `EXULANICA_EXECUTOR_ROLE_PASSWORD`, `EXULANICA_JUDGE_ROLE_PASSWORD`, `EXULANICA_API_TOKENS` and
   `EXULANICA_SEED_ARCHIVE` set, and `NEBIUS_API_KEY` with `EXULANICA_EGRESS_ALLOWLIST` for model
   calls.
4. `exulanica-seed reset --archive <directory>` returns a used stack to the archive's rows. A reset
   never touches the store: keys are content-addressed, and deleting them would delete the evidence
   every citation resolves to ([demonstration integrity](demo-integrity.md#22-reset)).

The archive is not a backup and not a World Memory Package: it carries no signature, so it proves
integrity against its own manifest and nothing else. The stack runs on one machine; no host is
provisioned for it.

## 9. Backups and recovery

- **Personal install:** `exulanica-local-db` backs up on every stop and around every upgrade, and
  `verify` proves a backup restores (section 3.2).
- **Composed deployment:** no backup job exists for the database or the media volume, and no restore
  of a composed deployment has been timed (open item D-3). No one-command redeploy exists (D-2).
- **Restoring over withdrawals:** a database restored from a backup taken before a deletion must
  replay every withdrawal before it serves. The restore command does that (5.2.8), and the API
  refuses to serve while a declared restore is sealed or replaying.
- **Workers:** `compose.yaml` restarts the derivative and scene workers (`restart: unless-stopped`).
  A worker's shutdown, lease recovery and retry are in
  [worker operations](derivative-worker-operations.md).

## 10. Hosting options researched and not built

Before any host was chosen, research compared running the API and PostgreSQL together on a Nebius
Compute virtual machine, a Nebius Serverless endpoint with a co-located database, Nebius Managed
PostgreSQL behind a separate API host, and hosts outside Nebius. It also covered Nebius Object
Storage as the origin for large derived files with an optional edge cache, a static host for the
browser client, cost controls, monitoring for unattended operation, and recovery drills. None of it
is configured or built, and its prices and provider facts have not been checked again. The full
text is at revision 47f9f7d3:
[deployment.md at 47f9f7d3](https://github.com/twinkling-reality/exulanica/blob/47f9f7d3/docs/deployment.md).

## 11. Open items

| # | Item | Resolved by |
| --- | --- | --- |
| D-1 | No test asserts that `/readyz`'s schema check reports a stale schema rather than only a missing one | Writing one |
| D-2 | No one-command redeploy exists | Writing it and running it from a clean shell |
| D-3 | No backup job exists for a composed deployment's database and media volume, and no restore of one has been timed | Building both and restoring once |
| D-5 | The preflight treats an unreachable catalog as a failure, which is right for a deployment step and wrong for a scheduled check | Retry with backoff, and distinguish the two outcomes in the report |
| D-6 | The embedding role has no fallback and no recovery path | Precomputing the vectors a deployment needs, or accepting the single dependency and saying so |
| D-7 | The fallback rule has never run against the live platform | Forcing a primary to fail |
| D-9 | No cloud account, project, region, domain or host is chosen | A human decision; section 10 holds the research |
| D-13 | The composition has no reverse proxy and no static client host | Choosing a host (D-9) |
| D-14 | Nothing limits in-flight requests, so one process can demand more backends than the server has slots | Setting `uvicorn --limit-concurrency` |
| D-15 | The container restart under thread saturation (5.4.2) is deduced from the health check's timeout, not observed | Running the image, saturating it and watching whether Docker restarts it |

## 12. Changes declined

Each of these looks like the obvious next thing to build and was declined for a stated reason. Each
says what would change the answer.

### 12.1 No connection pool

`exulanica/db/session.py` opens a fresh `psycopg.connect` per session, and `psycopg_pool` is in
neither `pyproject.toml` nor `uv.lock`. The reason is correctness: a pooled connection keeps the
previous borrower's workspace. `psycopg_pool` resets nothing when a returned connection is idle, and
under the autocommit `Database.session` chooses, a returned connection is always idle, so a
borrower that declared no workspace would read the previous one's rows. `exulanica/db/session.py`
records the probe. A pool would need `reset all` on return, the time zone set in the startup packet
(because `reset all` undoes the UTC `Database.session` sets), and `Database.unscoped` never drawing
from it. Opening a connection per request is small beside the model calls most requests make; a
request rate or workspace count an order of magnitude higher is what would change the answer.

### 12.2 No subscriber bound on the formation stream

A counter incremented in `stream()` before its `StreamingResponse` is built would leak a slot for
every response that is built and never iterated, because `_events` is a generator whose `finally`
runs only once iteration starts. The bound that counts requests where they are held is
`uvicorn --limit-concurrency` (open item D-14).

### 12.3 No reference counting on `blob`

`blob` is not workspace-scoped, and the purge path answers "does anything still hold these bytes"
with the purge role's cross-workspace read of the holder tables (5.1.1). `purge_releases_bytes`
scans the `artifact` table: there is no index on `artifact.content_sha256` or
`artifact.source_blob_sha256`, and a partial index on the first is the change to make if purge time
matters. A maintained holder count on `blob` is declined because it adds a trigger write to every
capture insert, capture soft-delete, artifact insert and artifact purge. It becomes the right change
if a workspace stops being one user (assumption A-30 in the
[domain and evidence model](domain-and-evidence-model.md)), if the cross-workspace read itself
becomes unacceptable, or if bytes are ever found shared between workspaces.

### 12.4 No semaphore around the decode

A semaphore acquired inside a synchronous route handler blocks a thread that already holds one of
the threadpool's tokens, so uploads over the bound wait on threads instead of failing fast, and
`/healthz` starves with them (5.4.2). The aggregate in 5.4.4 is a sizing input instead.

### 12.5 Poll intervals, and the shape of the queue index

The derivative worker polls every 2 seconds (`--poll-seconds`) and `exulanica-purge` makes one pass
per run; neither cadence is worth changing at one workspace per person. The derivative queue's claim filters on workspace,
kind and state and orders by priority and job id. Migration 0016 installs `job_queue_idx` on
`(workspace_id, kind, priority, job_id) where state = 'queued'`, with `run_after` as a filter:
placing a range predicate ahead of the ordering keys would make PostgreSQL read and sort every
eligible row before `limit 1`.
