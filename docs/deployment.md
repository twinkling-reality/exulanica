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
  - [5.4 What one instance runs out of, and where each is bounded](#54-what-one-instance-runs-out-of-and-where-each-is-bounded)
    - [5.4.1 Admission](#541-admission)
    - [5.4.2 The request threadpool](#542-the-request-threadpool)
    - [5.4.3 Connection slots](#543-connection-slots)
    - [5.4.4 Decode memory: the term that sizes the box](#544-decode-memory-the-term-that-sizes-the-box)
    - [5.4.5 A formation stream holds a place, not a thread](#545-a-formation-stream-holds-a-place-not-a-thread)
    - [5.4.6 The derivative queue](#546-the-derivative-queue)
    - [5.4.7 The measured envelope](#547-the-measured-envelope)
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
  - [8.1 Serving it over HTTPS from one host](#81-serving-it-over-https-from-one-host)
  - [8.2 The public server](#82-the-public-server)
- [9. Backups and recovery](#9-backups-and-recovery)
  - [9.0 Sizing one host](#90-sizing-one-host)
  - [9.1 Installation profiles and facts](#91-installation-profiles-and-facts)
  - [9.2 Backup sets](#92-backup-sets)
  - [9.3 Unattended maintenance](#93-unattended-maintenance)
  - [9.4 Recovery](#94-recovery)
- [10. Hosting options researched and not built](#10-hosting-options-researched-and-not-built)
- [11. Open items](#11-open-items)
- [12. Changes declined](#12-changes-declined)
  - [12.1 No connection pool](#121-no-connection-pool)
  - [12.2 No reference counting on `blob`](#122-no-reference-counting-on-blob)
  - [12.3 Poll intervals, and the shape of the queue index](#123-poll-intervals-and-the-shape-of-the-queue-index)

</details>

## 1. What the repository holds, and what is not provisioned

| Artefact | What it is |
| --- | --- |
| `Dockerfile` | One image recipe for the backend. The default build serves the API, runs migrations and runs the scene worker; a build argument selects the reconstruction extra for the derivative worker, so torch and pycolmap never share a process. The image runs as the non-root `exulanica` user, and its `HEALTHCHECK` is liveness on `/healthz`, never readiness |
| `.dockerignore` | An allowlist rather than a denylist, because `exulanica/models/credentials.py` reads a `.env` file from the working directory or a parent, and a denylist is one forgotten line away from an image that carries a credential |
| `compose.yaml` | A local composition: PostgreSQL 18 with pgvector 0.8.6 (`pgvector/pgvector:0.8.6-pg18`), the one-shot `migrate` service, the API, the derivative worker and the scene worker. It names no cloud, region, domain or account |
| `deploy/judge/` | The seeded stack for a reviewer, its HTTPS edge overlay and the operator script `stack.sh` (section 8) |
| `deploy/public/` | The public server: an overlay on `compose.yaml` with a TLS edge, the operator script `public.sh` and the host's systemd units (8.2) |
| `deploy/material-bake/Dockerfile` | The image recipe for `exulanica-material-bake`, which `compose.yaml` does not start |
| `deploy/gsplat/` | The CUDA scene-training image and the launcher that runs the scene worker on a GPU host; [scene training](gsplat-scene-jobs.md) owns both |
| `.github/workflows/check.yml` | Continuous integration: `ruff`, the import contracts, the backend suite with `EXULANICA_REQUIRE_POSTGRES=1`, the web workspace's `pnpm check` and an image build. The backend run's skips are held to `tests/expected_skips.toml` by `scripts/run_backend_suite.py --check-skips` |

`tests/test_deployment.py` holds these properties, including that `compose.yaml` and the
`Dockerfile` name no deployment target.

**Not provisioned:** no cloud account, project, region, domain, registry or host. Section 8.1 is
the recipe for serving the reviewer stack from one Nebius AI Cloud virtual machine; nothing has
been provisioned from it (open item D-9, section 11). The [depth image record](evaluation/2026-09-04-linux-amd64-depth-forward.json)
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
| Character catalogs | `exulanica-character-catalog publish --apply` | Publishes the character catalogs the code carries, after `exulanica-db`, into the store the API serves | 5.2.1 |
| Derivative worker | `exulanica-derivative-worker` | Drains the photograph derivative queue | 5.2.2 |
| Playback worker | `exulanica-playback-worker` | Plays the societies the API leaves to it and seals their coupled traffic | 5.1.5, 5.2.12 |
| Scene worker | `exulanica-scene-worker` | Recovers camera poses and publishes scenes for queued scene jobs | 5.2.3 |
| Purge worker | `exulanica-purge` | Destroys stored bytes that committed tombstones ask for | 5.2.4 |
| Material bake worker | `exulanica-material-bake` | Bakes requested material recipes in a Node process | 5.2.5 |
| Piece generation worker | `exulanica-piece-generation` | Serves the operator's GPU session with the workspaces' piece requests and keeps what it made; started only with the `generation` compose profile | 5.2.12 |
| Generated-tile worker | `exulanica-generated-tile-worker` | Bakes the tiles generated towns wait for, in a Node process, and publishes each as the tile role | 9.1 |
| Arrival worlds | `exulanica-arrival-worlds` | Makes the installation's arrival worlds in its own workspace, so their tiles are baked before a visitor's copy | 8.2 |
| Tile faults | `exulanica-tile-fault` | Lists faulted baked tiles, and records the owner's decision to serve one's stored first bake | 9.1 |
| Creator grants | `exulanica-creator-grant` | Grants and revokes the accounts whose browser sessions may upload a style pack or a workspace asset, and lists them | 5.1.4 |
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

Original photographs and every derived file are kept in a content-addressed store keyed by SHA-256,
behind the interface in `exulanica/store/base.py`. `EXULANICA_STORE_KIND` chooses the backend, and
every process builds its stores in one place, `exulanica/store/configured.py`: the API, the
derivative, scene, material and tile workers, `exulanica-purge`, restore replay, and the commands
that publish content (`exulanica-seed`, `exulanica-ingest`, `exulanica-eval`, the character and
reviewed-asset imports, the tile bakes). Every process of one installation must name the same store,
or a citation resolves against a store the bytes are not in.

No runtime role deletes stored bytes. `exulanica-purge` destroys the bytes that committed
tombstones ask for, as the separate `exulanica_purge` role (5.2.4). The store is therefore
**append-only by policy**, which is exactly as strong as that separation. It is not immutable, not
write-once and not tamper-proof: neither a Docker volume nor a bucket without object lock supports
those, and `tests/test_deployment.py` refuses those words in the deployment recipes. Nothing issues a
URL to a stored object: bytes leave through the API's own reads, after its permission and withdrawal
checks, because holding a digest is not permission to read.

### 4.1 Local directories, the default

With `EXULANICA_STORE_KIND` unset or `local`, the store is directories under `EXULANICA_DATA_DIR`
(`exulanica/store/local.py`), one for each namespace:

- `blobs/`: shared by every workspace, so two people who import the same photograph hold one
  object.
- `tiles/`: baked tiles, one store for everybody, because a tile is a pure function of public
  inputs.
- `materials/<workspace>/`: each workspace's material bakes.
- `workspace-assets/<workspace>/`: each workspace's own admitted 3D assets and their prepared
  outputs (migration 0126); never shared between workspaces, and erased only with the workspace.
- `generated-pieces/`: generated pieces, one store for everybody, because a piece is made only from
  catalog content; [generated pieces](generated-pieces-contract.md#53-the-shared-store-of-generated-pieces)
  owns what it takes and its bound.
- `looks/<workspace>/`: the containers of each workspace's own looks, a drafted creature's sketch
  or a traveller's admitted look (`exulanica/world/thing_store.py`); never shared between
  workspaces, served only through a look the workspace holds, and destroyed by `exulanica-purge`
  when the workspace is erased, or when the creature whose looks name it is erased.
- `workspace-style-packs/<workspace>/`: the files of each workspace's own style packs (migration
  0173); never shared between workspaces, and erased only with the workspace.

`<workspace>` is the workspace id as 32 lower-case hex digits. These names are stable: each is a
directory here, a segment of every object key in 4.2 and the name a backup set records, so renaming
one would orphan what is stored under it. `exulanica/store/namespaces.py` registers every namespace
once. The stores a process builds, `ContentStores.namespaces()` (every namespace by these names,
for backup and restore), the sweep of unfinished writes and the object store's check of which
uploads are its own all read that registry, so a new namespace needs no other change to be reached.

The default is `.exulanica/local`; the image sets `/var/lib/exulanica`, and `compose.yaml` mounts
the `media` volume there for the API and both workers. Processes on separate hosts cannot share it.

### 4.2 An S3-compatible bucket for several hosts

With `EXULANICA_STORE_KIND=object`, the same namespaces are key prefixes in one bucket
(`exulanica/store/object.py`), so processes on separate hosts share them. An object's key is the
optional prefix followed by the path the local store would use,
`<prefix>/blobs/sha-256/<aa>/<bb>/<hex>`. Rows record the key without the prefix and namespace,
which is the same on both backends, so moving a store from one backend to the other is a key-for-key
copy and no migration. Wherever section 5 calls `EXULANICA_DATA_DIR` the content store, this backend
replaces it with the bucket, and the directory keeps only host-local files: reconstruction scratch,
caches, and the spool a stream is written to while it is hashed.

| Variable | Purpose | Default, and what refuses |
| --- | --- | --- |
| `EXULANICA_STORE_KIND` | `local` or `object` | `local`. Any other value stops startup |
| `EXULANICA_OBJECT_STORE_ENDPOINT` | The endpoint's origin, `https://host[:port]` | No default with `object`. A path, query or userinfo stops startup. Plain `http` only to a loopback host, or with `EXULANICA_OBJECT_STORE_PLAINTEXT=private-network` on an isolated container network: request signing authenticates a request but does not hide the photographs it carries |
| `EXULANICA_OBJECT_STORE_BUCKET`, `EXULANICA_OBJECT_STORE_REGION` | The bucket and the region requests are signed for | No default with `object` |
| `EXULANICA_OBJECT_STORE_PREFIX` | A key prefix: lower-case segments separated by `/` | None |
| `EXULANICA_OBJECT_STORE_ADDRESSING` | `path`, or `virtual` for the bucket in the host name | `path` |
| `EXULANICA_OBJECT_STORE_CA_FILE` | A CA bundle for an endpoint with a private certificate | The certifi bundle httpx ships with; `SSL_CERT_FILE` and `SSL_CERT_DIR` are ignored |
| `EXULANICA_OBJECT_STORE_ACCESS_KEY_ID`, `EXULANICA_OBJECT_STORE_SECRET_ACCESS_KEY` | The runtime identity: read, write and list | No default with `object` |
| `EXULANICA_OBJECT_STORE_PURGE_ACCESS_KEY_ID`, `EXULANICA_OBJECT_STORE_PURGE_SECRET_ACCESS_KEY` | The purge identity, for `exulanica-purge`, restore replay and maintenance only | Every other process refuses to start when either is set |

Each credential may instead come from a file named by the same variable with `_FILE` appended;
setting both forms stops startup. An error names the variable and never its value, and no credential
appears in a log, an error or readiness. No `AWS_*` variable, `~/.aws` file or proxy setting is read.

**Identities.** An installation creates two identities and a bucket policy. The runtime identity
holds GetObject, PutObject, ListBucket, ListBucketMultipartUploads, AbortMultipartUpload and the
four bucket configuration reads (GetBucketVersioning, GetBucketObjectLockConfiguration,
GetReplicationConfiguration, GetLifecycleConfiguration); the bucket policy denies it DeleteObject
and DeleteObjectVersion. The purge identity holds the same reads plus ListBucketVersions,
DeleteObject and DeleteObjectVersion. The store's code gives the runtime identity no request that
deletes an object, so the code and the policy each hold the line; on an endpoint whose policies
cannot express the denial, only the code does. How a policy names an identity is the provider's own
format, so the verification command below applies the policy file the installation itself uses and
fails unless the endpoint refuses the runtime identity's delete. On SeaweedFS, the shared-store
profile's endpoint, a Deny takes effect only when the principal is written
`arn:aws:iam::000000000000:user/<identity name>`; a policy naming the identity any other way is
accepted and ignored. For a bucket `exulanica` and an identity named `runtime`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "RuntimeNeverDeletes",
      "Effect": "Deny",
      "Principal": {"AWS": ["arn:aws:iam::000000000000:user/runtime"]},
      "Action": ["s3:DeleteObject", "s3:DeleteObjectVersion"],
      "Resource": ["arn:aws:s3:::exulanica/*"]
    }
  ]
}
```

**The bucket check.** A process's first request, every request five minutes after the last check,
and every purge first read the bucket's configuration. Each finding has a stable code, which
`ObjectStoreRefused.code` carries and `ContentStores.describe()` reports for installation facts:

| Code | Found because | A purge still runs |
| --- | --- | --- |
| `object_store_object_lock_enabled` | The bucket reports object lock enabled; a locked version cannot be erased | No |
| `object_store_replication_configured` | A replica is a copy no purge reaches | No |
| `object_store_bucket_unverified` | The identity may not read the versioning, replication or lifecycle configuration | Only when replication was readable |
| `object_store_lifecycle_moves_content` | An enabled lifecycle rule expires or transitions current objects under the prefix | Yes |
| `object_store_publicly_listable` | Anyone can list the bucket, so the digests that citations and ETags carry would open its bytes | Yes |
| `object_store_publicly_readable` | Anyone can read a stored object without credentials | Yes |

Any finding refuses every read and write. A purge refuses only where erasure itself would be
incomplete: deleting from a bucket that is wrongly public, or that a lifecycle rule expires, still
removes the bytes. The anonymous read is tried on one stored object, so an empty bucket records it
as `unchecked` until it holds one. Versioning is allowed. A configuration read the endpoint does not
implement is recorded as `not_exposed` rather than refused. An object lock configuration the
identity may not read, which some endpoints reserve for an administrator, is recorded as
`unverified` rather than refused: a lock shows up as a purge that fails because a version remains,
never as a purge reported complete. A copy made by means no S3 request shows, such as a provider's
own tiering, is outside what the check can see.

**Versioning and overwrite.** The runtime identity holds PutObject, so it can replace a stored
object's bytes. Reads and writes detect that by the hash, and nothing silently serves the result.
An installation that states its originals are append-only by policy creates the bucket with
versioning enabled (the decision in [the domain model](domain-and-evidence-model.md)), so the
original survives such an overwrite as an earlier version; without versioning it survives only in a
backup. `ContentStores.describe()` reports which.

**Erasure.** A purge deletes every version and delete marker of the key and then lists the key again.
A version still present fails the purge job, so a tombstone is never completed over bytes that can
be retrieved, whether or not the bucket keeps versions and whenever versioning was switched on. A
purge reaches this bucket only: backups are section 9's, and the remaining limits are the
[threat model's](privacy-consent-threat-model.md#55-the-honest-limits).

**Integrity.** Every object and part body carries a signed SHA-256 and a Content-MD5; an endpoint
checks at least one of them against the bytes it keeps, and the verification command records which.
Above 64 MiB an object goes up in parts of 16 MiB or more, and the whole object's SHA-256 must equal
its key before the upload is completed. A write to an existing key reads it back and refuses
different content; a read re-hashes what it returns; a read that loses its connection resumes where
it stopped, pinned to the object's ETag.

**Failures.** A request is tried at most four times, with backoff, after a connection error or a
transient status. An unreachable store raises `ObjectStoreUnavailable`, is remembered for five
seconds so requests do not queue behind one another's retries, and `/readyz` reports it through its
store check. A writer abandons its own failed multipart upload. An upload left by a killed process,
and a stale spool or temporary file, holds photograph bytes no key names, and
`sweep_incomplete_writes(stores, older_than=...)` abandons it; the installation's maintenance runs
it on a schedule with an age longer than its longest write. A bucket lifecycle rule
`AbortIncompleteMultipartUpload` bounds abandoned uploads on the endpoint's side as well, and the
bucket check allows it.

**Compatibility.** The store speaks the S3 REST subset above over `httpx`, signing with
`exulanica/store/sigv4.py`, which is tested against the applicable cases of AWS's Signature Version 4
test suite. `scripts/verify_object_store.py` runs the store's contract against a real endpoint with
three identities (runtime, purge and an administrator that creates its buckets) and the
installation's bucket policy, and records each check as passed, failed or not supported; a provider
it has not been run against, Nebius Object Storage among them, is unverified.

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
| `NEBIUS_API_KEY` | The Nebius Token Factory credential, named by the manifest's `api_key_env` | Optional. Without it the API builds no model client, model-dependent endpoints refuse, and `/readyz` warns. With it, `EXULANICA_SPENDING` is required. A checkout may supply it in a `.env` file |
| `EXULANICA_SPENDING` | How the process spends on hosted models: `durable`, admitted by the spending authority every process shares, or `process`, within its own fuse alone ([model spending](model-spending-contract.md#9-configuration-and-composition)) | No default. A process holding a provider's credential refuses to start without it; under `process`, `/readyz` says that a restart or another process starts the fuse again at zero |
| `EXULANICA_SPENDING_WITNESS_DIR` | The spending witness directory: outside the database's backup domain, shared by every spending process on the host, never restored with the database ([model spending](model-spending-contract.md#7-restore-the-spending-witness)) | Optional. A `durable` process without it refuses to spend under a witnessed authority, and `/readyz` says so. The operator commands write its marker (`witness-directory.json`); a process given a directory with no marker, or another installation's, refuses to spend under an authority whose directory is recorded |
| `EXULANICA_EGRESS_ALLOWLIST` | The origins this process may reach, a JSON array ([security floor](security-floor.md#3-egress-allowlist)) | No default. Required when a model client is built or Google sign-in is configured. It must include `https://api.tokenfactory.nebius.com` for the model endpoint, and the three Google origins with sign-in (5.1.4) |
| `EXULANICA_BUDGET_USD` | The process's safety fuse on model spend, in USD. It does not refill while the process runs, and it is not the durable allowance | `5.00`. Person decisions may use all of it but the reserve their contract keeps for other work ([model selection](model-and-service-selection.md#what-a-persons-decisions-may-spend)) |
| `EXULANICA_BUDGET_MAX_CALLS` | The process's ceiling on model calls | `2000` |
| `EXULANICA_DERIVATIVE_WORKER` | Whether this process drains the derivative queue that `POST /intake` fills | On. `0`, `false`, `off` or `no` turns it off, and `/readyz` says which. `compose.yaml` turns it off and runs the dedicated worker. The in-process worker runs vision and caption vectors but no depth model, and drains the account workspaces paced as the dedicated worker does |
| `EXULANICA_TEXTURE_DIRECTORY` | The published material catalog: `manifest.json`, `catalog.json` and `objects/` | A checkout finds its own; the image sets `/app/assets/textures`. Without a catalog the `/materials` routes answer 503 and `/readyz` warns; a catalog that is present but not the reviewed one stops startup |
| `EXULANICA_SOCIETY_AUTHORED_WORLDS` | A JSON file (`exulanica.society-authored-worlds/v1`) of host registrations that bind a saved world's society to a named place | Optional; without it a society binds a place derived from the world itself. A malformed file stops startup |
| `EXULANICA_SOCIETY_OF_THINGS` | `on` (or `true`, `yes`, `1`) lets a world's owner make a society of things (`exulanica-society/v7`) through `POST /world/versions/{version_id}/society`, and gives a saved world holding a thing its author placed a society of things when its people are brought in (the engine table's `creates_holding_things`; its entry states it) | Optional; absent or `off` (`false`, `no`, `0`) leaves it off: that route refuses one as `society_engine_not_offered` and every saved world keeps its ground's engine. A society made while it is on is one every later version of its engine must keep replaying. Any other value stops startup as `society_of_things_not_boolean` |
| `EXULANICA_RESTORE_STATE_PATH` | The restore marker the API checks at startup | Optional. With it, a sealed or replaying database refuses to serve ([ADR-0019](adr/0019-offline-restore-tombstone-replay.md)) |
| `EXULANICA_GOOGLE_CLIENT_ID`, `EXULANICA_GOOGLE_CLIENT_SECRET`, `EXULANICA_GOOGLE_CALLBACK_URI`, `EXULANICA_GOOGLE_RETURN_URIS`, `EXULANICA_ACCOUNT_BROWSER_ORIGINS`, `EXULANICA_ACCOUNT_DATABASE_URL` | Google sign-in and browser accounts (5.1.4) | Optional, all six or none: a partial set stops startup |
| `EXULANICA_SOCIETY_CONTROL_WORKSPACES`, `EXULANICA_SOCIETY_TICK_INTERVAL_MS`, `EXULANICA_SOCIETY_CONTROL_WORKER` | Society playback (5.1.5) | Playback is off by default |
| `EXULANICA_API_THREADS`, `EXULANICA_API_REQUESTS`, `EXULANICA_API_UPLOADS`, `EXULANICA_API_STREAMS`, `EXULANICA_API_WORKSPACE_REQUESTS`, `EXULANICA_API_WORKSPACE_UPLOADS`, `EXULANICA_API_WORKSPACE_STREAMS`, `EXULANICA_API_DECODES`, `EXULANICA_INTAKE_QUEUED_JOBS` | How much work this process accepts at once (5.4) | 40, 24, 2, 128, 12, 1, 8, 2 and 4. A value that is not a whole number, is outside its bounds, gives a workspace more than its class, or leaves fewer than four threads beside the admitted requests stops startup with the setting named |
| `EXULANICA_WORKSPACE_STYLE_PACK_UPLOADS` | Whether `POST /workspace-style-packs` takes a creator's style pack ([style pack contract](style-pack-contract.md#11-a-workspaces-own-packs)) | `off`: the route answers 503 `style_pack_uploads_off`. `on` turns uploads on; any other value stops startup. It switches every pack upload off at once. Where sign-in is open to everyone, a browser session still uploads only with its account's creator grant (5.1.4) |

#### 5.1.1 The database roles

`exulanica-db` provisions `exulanica_app`, `exulanica_ro`, `exulanica_purge` and
`exulanica_accounts` after the migrations, in one order, and the reviewer stack adds
`exulanica_judge` (section 8). What each role holds, and why each is separate, is the
[security floor](security-floor.md#5-database-roles)'s. Each process connects as the role its table
in section 5 names, and the bootstrap owner's connection belongs to `exulanica-db` alone (5.1.3).

#### 5.1.2 The request body bound

`POST /intake` is multipart. The route reads its own body, only after its caller is authenticated
and its workspace's upload share is claimed, and holds no database connection while the body
arrives; a body the multipart parser cannot read is 422 `invalid_intake_body`, with nothing
written. Starlette's `max_part_size` bounds only the parts that are not files, and the route's own
`MAX_PART_BYTES` check in `exulanica/api/routes/intake.py` reads a part that is already spooled,
so neither bounds what reaches the disk.

`exulanica/api/body_limit.py` is pure ASGI middleware upstream of all of that, and applies two
bounds to `MAX_BODY_BYTES` (512 MiB):

- a declared `Content-Length` over it is refused before a byte is read;
- a request that declares no length, which is what `Transfer-Encoding: chunked` produces, is
  counted as it arrives and cut off the moment the running total crosses the limit. The overshoot
  is one chunk rather than the whole body.

A route may declare a lower bound beside itself (`BODY_LIMITS`), which the same middleware applies
the same two ways. `POST /intake` holds at most 256 MiB, framing included, so a person's
photographs arrive in uploads of at most that size. `POST /workspace-assets` holds one asset and one declaration at their bounds with
the framing around them, and reads its own body only after its caller is authenticated and its
workspace's upload share is claimed ([workspace asset admission](workspace-asset-admission.md#admission)).
`POST /workspace-style-packs` likewise holds one pack's files, manifest and declaration at their
bounds with the framing around them (68,485,120 bytes), and reads its own body only after its caller
is authenticated, its workspace's upload share claimed and the attempt counted
([style pack contract](style-pack-contract.md#11-a-workspaces-own-packs)).

In front of the API, each composition's client proxy carries a body cap of its own, set by the
installation profile it serves:

| Profile | Proxy | Body cap | Why |
| --- | --- | --- | --- |
| `single-host`, `single-host-server-only`, `shared-store` | `deploy/installation/client-nginx.conf`, the `client` service of `compose.yaml` | 512 MiB, the API's own limit | People upload photographs, and the browser sends every photograph a person chooses in one `POST /intake`, so the API decides every body it would accept |
| `reviewer` | the web proxy embedded in `deploy/judge/web.Dockerfile` (section 8) | 8 MiB | A reviewer's token cannot upload; a long question is still a POST body. The TLS edge in front of it states the same 8 MiB (8.1) |

A proxy refuses a body over its cap with 413 `body_too_large` (5.4.8) before the API is involved.
Each proxy reads a request's body into its container's temporary directory before passing it on
(nginx's request buffering, left on), so an upload in progress through it holds up to its size on
that container's disk, and the API's upload slot is held only while the proxy passes the whole body
on. The per-address write limit serves a burst of twenty above one write every two seconds, so about
twenty-one writes at once from one address: up to about 10.5 GiB of buffered bodies at the
installation's cap, or 168 MiB at the reviewer's. Nothing in the proxy bounds how many addresses do
that at once; a public host needs an edge that does (D-13). A host that puts its own proxy in front
should carry a body limit of its own (`client_max_body_size` on nginx, `proxy-body-size` on an
ingress) no smaller than the profile's cap here.

#### 5.1.3 Runtime row-level security is checked at startup

`compose.yaml` gives the bootstrap owner URL to the one-shot `migrate` service only. The API,
derivative worker and scene worker receive `exulanica_app`, and the Selection executor receives
`exulanica_ro`. The order is: migrate as the owner, provision the roles, then start the runtime
containers with credentials that own no table and hold neither SUPERUSER nor BYPASSRLS.

A connection string is not proof of the role behind it. Startup queries `pg_roles` and the current
schema and refuses to serve or drain when the current role is a superuser, has BYPASSRLS, or owns
any row-level-security table. The API lifespan, the derivative, scene and material bake workers
and the comparison worker's own process (5.2.12) run this check before they accept work; the purge
worker checks its own role instead (5.1.1). `tests/test_row_level_security.py` exercises both directions against PostgreSQL.

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
connection. An installation's backup sets carry the account tables except the rows of
`account_login_attempt` and `account_browser_session` (9.2). Provider requests run outside database
transactions and are held to
`EXULANICA_EGRESS_ALLOWLIST`, which must include `https://accounts.google.com` (discovery),
`https://oauth2.googleapis.com` (token) and `https://www.googleapis.com` (JWKS), or startup stops
and names the origins it lacks. The endpoint URLs are pinned in `exulanica/api/account_runtime.py`:
if Google moves its token endpoint or JWKS, sign-in fails closed with `503 account_unavailable`, and
the fix is to update the pinned URLs as well as the allowlist. The callback and the session cookie
require HTTPS; a plain HTTP preview is not a sign-in deployment.

`GET /auth/google/start` begins sign-in, `GET /auth/google/callback` completes it,
`GET /auth/session` returns the current membership, the CSRF token and whether the account holds
the creator grant (`creator`), and `POST /auth/logout` revokes the cookie. Cookie-authenticated writes require the matching `X-CSRF-Token` and an exact permitted
`Origin`. An explicit Authorization header uses the bearer path and never falls back to a cookie.
Without accounts configured, the account endpoints answer 503. With accounts configured,
`EXULANICA_API_TOKENS` may be absent, but a token setting that is present and invalid is still
refused. Readiness checks account persistence without contacting Google.

The browser checks `/auth/session` when no development token is built in. A signed-in session opens
the owned workspace with cookie credentials and adds its in-memory CSRF value to writes; a
signed-out session is offered Google sign-in; a host without account configuration shows the
developer-token entry instead. An account starts with an empty workspace of its own, with no world
copied into it and no link inferred to existing bearer data. Derivative workers combine their
configured workspaces with a fresh account-role query for active owner and guest memberships when
accounts are configured; a browser session is never taken as membership authority. Account
revocation keeps historical attribution. Full account-data deletion, invitations and retention
cleanup are not built. Access logs must redact callback query values, cookies and CSRF tokens.

**The creator grant.** Every account that signs in owns a workspace, and an owner holds
`admission.write`. A browser session uploads a style pack (`POST /workspace-style-packs`) or a
workspace asset (`POST /workspace-assets`) only while its account also holds the creator grant,
which the operator gives and revokes; without it the route answers 403 `creator_grant_required`
before it reads the body. A bearer token's `admission.write` is enough, because the token is the
operator's own grant to a program. The person reads their account's id as `user_id` at
`GET /auth/session`, and the operator runs, with `EXULANICA_ACCOUNT_DATABASE_URL`:

```bash
uv run exulanica-creator-grant grant --user <user id> --reason <code> --operator <code>
uv run exulanica-creator-grant revoke --user <user id> --reason <code> --operator <code>
uv run exulanica-creator-grant list
```

A reason and an operator are codes (lower case letters, digits and `_`; and `:._-` for an
operator), never words. Each answers JSON: `recorded` is false when the account already held, or
already lacked, the grant. `list` names every account holding it, with the grant that holds it. The
grants are events in `account_creator_grant_event`, an account table the application roles cannot
read, and a revocation is carried across a restore from an older backup (the withdrawal catalog's
`creator_grant` kind, 5.2.8).

The grant covers those two routes alone: photographs (`POST /intake`) and a world kind's document
(`POST /worlds/kinds`) are not covered by it. A revoke stops new uploads only: what the account
uploaded under the grant stays, and its owner may still prepare it, withdraw it or ask for it to be
published. While a restore checkpoint is sealed, grant and revoke are refused (the command prints
the database's refusal and exits 1). An export carries revocations only through its
`covered_through`, so after a declared recovery from an export run again any revoke made inside the
window the restore command printed, and check the result with `list`.

**The guest entry.** A host may also admit visitors with no account of their own (migration 0139),
with or without Google sign-in beside it:

| Variable | Purpose |
| --- | --- |
| `EXULANICA_GUEST_ENTRY` | `off` (the default), `open`, or `code`. An explicit `off` on a host with the account database and the browser origins and no Google sign-in closes the entry: the API starts, the guests who entered keep their sessions and towns, and nobody new enters |
| `EXULANICA_GUEST_ENTRY_CODE_SHA256` | With `code`: the lowercase SHA-256 of the code visitors are given. The code itself is never configured |
| `EXULANICA_GUEST_ENTRIES_PER_DAY` | Required with a guest entry, no default: how many guests a day (UTC) enters |
| `EXULANICA_GUEST_SESSION_SECONDS` | How long a guest's session lasts: 604800 (seven days) by default, at most thirty days |

It needs `EXULANICA_ACCOUNT_DATABASE_URL` and `EXULANICA_ACCOUNT_BROWSER_ORIGINS`. With a model
credential it also needs `EXULANICA_SPENDING=durable`, and startup refuses otherwise: a guest's
allowance is a grant under the durable authority, and under process spending every visitor would
spend from the fuse the owners share.

`POST /auth/guest` (`{}`, or `{"code": "..."}`) checks the request's `Origin` and the code. Then,
in one transaction on the account role, it counts the day's entries against the limit and makes:
- a user with no identity;
- a workspace;
- a membership in the role `guest`;
- the entry;
- a session with the same `__Host-` cookie and CSRF token a sign-in sets.

After that commits, the workspace is granted its allowance by the spending authority's guest policy
([model spending](model-spending-contract.md#2-authorities-grants-and-bounds)) and given its first
world from the arrival list (8.2), dressed with the scene the list names for it, if any. Any of
these may fail without undoing the entry.

Once the account exists it answers 201 with the session cookie, `role`, `allowance`, `arrival` and
`incomplete`, which names each step that failed: `allowance` with the refusal's code (for instance
`guest_grants_exhausted`) or `allowance_failed`, and `arrival` with `arrival_not_made`. A guest who
holds no allowance on a provider is granted it on a later `GET /auth/session`, on those providers
alone and at most once a minute per workspace, because each ask takes the authority's witness and
state locks that every admission takes. The refusals,
before anything is made, are:
- 403 `guest_entry_code_wrong`;
- 403 `origin_not_permitted`;
- 429 `guest_entries_exhausted` when the day is full, with `Retry-After` the seconds to 00:00 UTC;
- 503 `guest_entry_off` on a host with accounts and no guest entry, or a closed one;
- 503 `guest_entry_unavailable`, with `Retry-After` 30, when the account database does not answer;
- 503 `account_unavailable`, as every account route answers, on a host with no accounts.

**What one address can do.** The client proxies count entries per address, three at once and then
one a minute, so one script from one address takes about 60 entries an hour, and a day of 100 in
under two hours. Every later visitor that day is then refused `guest_entries_exhausted`, and that
script holds the day's allowances. Spending stays within the operator's figures (the day's limit,
the policy's grants a day, the authority); the front door is what is lost. For an event, use
`code` with a code given only to the people invited, at least 20 characters (`public.sh init`
refuses a shorter one): only its unsalted SHA-256 is kept, and a wrong code is answered at once.

A guest holds the journey's permissions and no others
([security floor](security-floor.md#1-route-permissions)). `GET /auth/session` answers a guest's
`role` and `allowance`. A session's last use (`seen_at`) is written at most once a minute. The
client proxies count guest entries per client address, three at once and then one a minute (the
slowest rate nginx states), apart from the write limit (5.4.8), accept an entry's body only up to
1 KiB, and answer their own refusals in the problem shape in that location too; the day's limit is
the cap. They pass the API the host and port the browser used, which the sign-in routes compare
with the configured origin. Nothing a guest made is deleted when their session ends; whoever
holds the cookie holds the workspace, and a lost cookie leaves it reachable by nobody.

#### 5.1.5 Society playback

Automatic playback is off unless the host turns it on. `build_services` reads these settings and
stops startup on a malformed value, with a named code from `SOCIETY_SETTING_REFUSALS` in
`exulanica/api/services.py`:

| Variable | Purpose |
| --- | --- |
| `EXULANICA_SOCIETY_CONTROL_WORKSPACES` | A JSON array of workspace ids whose playing societies this instance advances, with no accounts needed. Absent or `[]` plays none; a malformed or repeated id is refused |
| `EXULANICA_SOCIETY_TICK_INTERVAL_MS` | The base wait between simulated minutes, in whole milliseconds: 1,000 to 60,000 and divisible by 4, so every speed divides it exactly. Absent means the declared default, 8,000 |
| `EXULANICA_SOCIETY_CONTROL_WORKER` | Account-wide discovery. Absent or `off` disables it; `true`, `yes`, `on` or `1` also plays every current account owner's workspace and, where guests enter (5.1.4), each guest's while the guest is there (below), and needs accounts configured |
| `EXULANICA_GUEST_PLAY_SECONDS` | How long after a guest's last request their town keeps playing: 60 to 86,400 seconds, default 900. A session's last use is written at most once a minute |
| `EXULANICA_GUEST_PLAYING_MAXIMUM` | How many guests' towns play at once: 0 to 1,000, default 24. A playing town keeps its place while its guest is there, for `EXULANICA_GUEST_PLAY_SECONDS` at most while another guest waits; a freed place goes to the guest waiting longest |
| `EXULANICA_PLAYBACK_WORKERS` | How many workspaces' claims one playback round runs at once: absent or 1, each in turn (the behaviour before the setting existed); 2 to 8, on a pool, so one workspace's model answers are awaited while another's are. Asks stay bounded by the process's model slots. Anything else stops startup (`playback_workers_out_of_bounds`). Raise it only from a measurement of the host |
| `EXULANICA_PLAYBACK_WORKER` | Who plays the listed and discovered workspaces' societies and seals their coupled traffic. Absent or `on`, this process, in threads; `process`, a process of its own (`exulanica-playback-worker`, 5.2.12), and this one serves the playback controls without playing or sealing; `off`, nothing, and a society advances only a minute at a time when somebody advances it. Any other value stops startup (`playback_worker_not_recognised`) |
| `EXULANICA_COMPARISON_WORKER` | Who plays the comparisons started from the application for the workspaces this host asks models for (below). Absent, this process, in a thread; `process`, a process of its own (5.2.12), and this one only serves starts, refusing them as `comparisons_not_played` where the installation's profile declares the `comparison` component not installed or unavailable (9.1); `off`, nothing, and every start is refused as `comparisons_not_played`. Any other value stops startup (`comparison_worker_not_recognised`) |

Listed and discovered workspaces are played together. A guest's workspace is discovered while one
of its browser sessions, unrevoked and unexpired, was used within `EXULANICA_GUEST_PLAY_SECONDS`.
At most `EXULANICA_GUEST_PLAYING_MAXIMUM` guests' towns play: a playing town keeps its place while
its guest is there (the process remembers which it played and since when), but gives it up after
`EXULANICA_GUEST_PLAY_SECONDS` while another guest waits, and joins the back of the queue. As many
places turn over as guests wait, given up first by the guests who last waited longest ago (one who
never waited first), so every guest takes a turn; a freed place goes to the guest waiting longest
(before any history, the one who entered first). A page
left open keeps its guest there, and a paused town holds its place like a playing one, so the
tenure is what turns places over. A waiting world's `host_playback_code` is `guest_towns_full`,
whose sentence says it waits until another stops. With a maximum of 0, or no guest entry configured, no
guest's town plays and none is told it waits: its code is `workspace_not_played`. A guest who leaves
stops being played within the window, so a town whose people a model runs spends nothing after
them. When a guest's allowance, or the authority all guests share, is spent, the town keeps playing
and its people decide by their routines: the host reserves nothing for a person whose model's
provider admission would refuse, and answers `spending_limit_reached` on the receipt, without
asking admission, for a person whose one attempt (its prompt included) no longer fits the USD
left once the minute's earlier asks are reserved. The control read says so with
`model_minds_code` `spending_cap_reached` and a sentence (synthetic society contract).
Guests' towns are played in the API's own process (`EXULANICA_PLAYBACK_WORKER`
on, as the public overlay sets it, 8.2): the separate playback process is not given the guest
entry's settings, so a host with guests does not use it.

Which workspaces are asked for models. The decision host, comparison starts and model choices ask
models for the listed workspaces, and, only where spending is durable (5.1) and discovery is on,
for the discovered ones (every owner's and the guests' being played), read through the account role
at most every 5 seconds, a failed read tried again no sooner and the last good read used for at
most 60 seconds: each ask is then admitted against the asking workspace's own grant. The door's
outside programs are asked for the same workspaces; a guest holds no `door.grant`, so only an
owner's grant lets one in. Under
`process` spending a discovered workspace is played by its routine alone and its model choices
read `models_not_run_here`, because nothing but a grant bounds what one visitor spends. The
comparison worker visits the watched workspaces every round and every active account workspace once
every five minutes under durable spending: a start is made only while its visitor is watched, and a
comparison a visitor started finishes after they leave, within its own bound and their grant, while
visitors who are not there cost no round.

A person's saved world needs no host
registration, because its society binds a place derived from the world itself. The default base
wait is measured: at it, a person in a saved world walks at an ordinary pace
([record](evaluation/2026-09-24-living-world-pace.json)). The API starts the playback worker only
after schema and restore validation, stops new claims on shutdown and waits for an active batch to
finish or roll back. Readiness reports its thread, its latest round, the base wait, how many
workspaces are listed (never which) and whether account discovery is on; it promises no delivery
rate. Playback controls, speeds, the `host_playback` field and recovery are the
[society contract](synthetic-society-contract.md#persisted-playback-controls-and-bounded-host-progression)'s.

With `EXULANICA_PLAYBACK_WORKER=process` the API plays no society and seals no traffic, so no round
and no traffic minute runs on its interpreter; `exulanica-playback-worker`, started with the same
settings, does both. While it runs that process holds a shared session advisory lock keyed by the
digest of its playback configuration (the listed workspaces, account discovery, the base wait and,
where guests are played, their play window and maximum),
and the API reads `pg_locks` for its own configuration's key, at most every 5 seconds, to answer a
world's `host_playback`: no such lock reads as `playback_worker_stopped`. A process that died holds
no lock; a process whose loop hangs still holds it and reads as running. Readiness stays ready and
reports `played_by` and `process_alive`. Claims and leases decide which host advances a society, so
several playback processes, or one beside an API that also plays, never advance one twice.

In `compose.yaml` the API and the `playback-worker` service take the three playback settings from
one block (`x-society-playback`), so their configuration digests agree. The API plays in threads
(`EXULANICA_PLAYBACK_WORKER`, default `on`). To play in a process of its own, set
`EXULANICA_PLAYBACK_WORKER=process` and start `docker compose --profile playback up`. The worker
starts only with that profile, because it refuses an environment that names no society to play,
and the default composition names none. Its stop grace is 40 seconds, longer than a playback
round's 30 second lease, so a stop lets a running round finish or roll back.

A playing world whose people are run by models asks those models through this process's client, so
the model settings in 5.1 apply; the decision contract's spend bounds are in
[model selection](model-and-service-selection.md#what-a-persons-decisions-may-spend).

### 5.2 Worker and operator commands

#### 5.2.1 Migrations and roles: exulanica-db

| Variable | Purpose |
| --- | --- |
| `EXULANICA_DATABASE_URL` | The bootstrap owner's connection. Migrations and role grants run in one command because there is one correct order |
| `EXULANICA_APP_ROLE_PASSWORD`, `EXULANICA_EXECUTOR_ROLE_PASSWORD`, `EXULANICA_PURGE_ROLE_PASSWORD`, `EXULANICA_ACCOUNT_ROLE_PASSWORD`, `EXULANICA_TILES_ROLE_PASSWORD` | Passwords for `exulanica_app`, `exulanica_ro`, `exulanica_purge`, `exulanica_accounts` and `exulanica_tiles`. Each is optional and set only when supplied, because a role that authenticates by certificate or by peer has none |

The migrations run as a superuser, as `compose.yaml`'s database owner is: migration 0161 creates
`exulanica_definer`, a role that cannot log in, and makes it the owner of every SECURITY DEFINER
function, pinning each one's search path with `pg_catalog` first and `pg_temp` last
([security floor](security-floor.md#5-database-roles)). After provisioning, `exulanica-db` refuses
a database where any such function has another owner or search path or is executable by PUBLIC;
where that role can log in, holds a privileged attribute, belongs to a role or has a member, owns
anything else, can create in the schema or the database, or is named by a default privilege; where
its table, column, sequence or function privileges differ from what the migrations the database
records grant it (`GRANTS_BY_MIGRATION`); or where
another role, neither a superuser nor a member of the schema's owner, can create in the schema. A
migration that recreates a definer, or a restore that loads one without its owner, hands it back
to the migrating role, and a migration that strips or recreates a table takes its grants away;
this check stops the deployment rather than a request. Every process that serves runs the same
check at start once 0161 is recorded, a local restore runs it before offering the copy, and each
maintenance pass reports a drift as `definer_role_unsafe`.

The migration that erases a drafted creature whole holds `tombstone` exclusively until it commits,
so every read of that table waits for it: run it, as the `migrate` jobs do, before any process
serves.

Every path that creates or upgrades a serving database then runs
`exulanica-character-catalog publish --apply`. It uses the same owner connection and the data
directory, or object-store settings, that the API serves its store from.

- **Why it matters.** People are drawn only from catalogs the host published (migration 0131).
  Until the command has run, no person is drawn and every saved look reads as unavailable.
  `/readyz` states `people_catalog_unpublished` under `checks.character_catalogs`, with the
  command.
- **Which paths run it.** `compose.yaml` and `deploy/judge/compose.yaml` each run it as their
  `catalogs` job, after `migrate` and before `api`.
- **Running it again.** It is idempotent: an identical catalog is answered `unchanged`, and an
  image carrying a newer catalog publishes the newer revision. A catalog the host withdrew is
  answered `withdrawn` and stays withdrawn, even after a restore from a backup that never held it.
  Without `--apply` it checks every document and container and writes nothing.

#### 5.2.2 The derivative worker

`exulanica-derivative-worker` drains the queue `POST /intake` fills. Its delivery contract,
progress, shutdown and recovery are in [worker operations](derivative-worker-operations.md).

| Variable | Purpose |
| --- | --- |
| `EXULANICA_DATABASE_URL` | The `exulanica_app` connection |
| `EXULANICA_WORKSPACE_IDS` | Comma-separated workspaces to drain, or repeated `--workspace` flags. An empty set is a startup failure unless `EXULANICA_ACCOUNT_DATABASE_URL` is set |
| `EXULANICA_ACCOUNT_DATABASE_URL` | Optional: also drain the active account-owned workspaces, discovered through the account role: on every pass those whose people are there (every owner's, and each guest's seen within `EXULANICA_GUEST_PLAY_SECONDS`, default 900), and every one once every five minutes, so a guest who is not there costs a pass nothing |
| `EXULANICA_DATA_DIR` | The content store |
| `NEBIUS_API_KEY`, `EXULANICA_EGRESS_ALLOWLIST`, `EXULANICA_BUDGET_USD`, `EXULANICA_BUDGET_MAX_CALLS`, `EXULANICA_SPENDING`, `EXULANICA_SPENDING_WITNESS_DIR` | The vision and caption-vector calls, as in 5.1. Without the credential no model stage runs; with it, `EXULANICA_SPENDING` is required |
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
| `EXULANICA_ACCOUNT_DATABASE_URL` | Optional: also bake for the active account-owned workspaces, paced as the derivative worker's: those whose people are there on every pass, every one once every five minutes |
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

`python -m exulanica.orchestration.restore checkpoint`, `export`, `prepare` and `replay` read
`EXULANICA_DATABASE_URL` (a connection with the complete view: the administrative connection of the
source or restored database, or any role with `BYPASSRLS`), `EXULANICA_PURGE_DATABASE_URL` (replay)
and the content store. The API then reads `EXULANICA_RESTORE_STATE_PATH` (5.1). The procedure is
[ADR-0019](adr/0019-offline-restore-tombstone-replay.md)'s, and
[ADR-0026](adr/0026-a-restore-carries-every-withdrawal.md) states which withdrawals a restore
carries. A checkpoint records the identity of the withdrawal catalog it was sealed under
(`exulanica/deletion/withdrawals.v2.json`), and a replay under another catalog refuses it, so after
deploying a version whose catalog differs, seal or export a fresh checkpoint.

| Action | What it does |
| --- | --- |
| `checkpoint --checkpoint FILE` | Locks and seals a stopped source and writes its complete record, for a planned restore |
| `export --directory DIR [--keep N]` | Writes the same record from a running source to a fresh file in `DIR`, in one read-only snapshot, without a seal, with `covered_through` (the transaction's start), for a crash recovery, then keeps this source's newest `N` exports there (3 by default) and every export a backup set in `EXULANICA_BACKUP_DIRECTORY` names. Refused: `DIR` inside the content store or the backup directories, a standby, a sealed or replaying source, a declared restore (the profile's marker, or `--marker` without a profile) not yet complete, and a database older than the newest export in `DIR`. Its reads make a concurrent checkpoint or schema change wait |
| `prepare --checkpoint FILE --marker FILE` | Writes the pending external marker before anything is restored. A sealed checkpoint takes no declaration. A checkpoint the marker records among its completed restores is refused, while the marker is kept: the marker carries that record forward through every later restore |
| `prepare ... --declaration FILE --max-export-lag-seconds N` | The same for an export, which requires both: the declaration (`exulanica.recovery-declaration/v1`: `declaration_id`, `export_sha256`, `incident_at` with its zone, `reason`) must name that export, and `incident_at` must be after `covered_through` and within the bound of it, and the export must be the newest valid export in `EXULANICA_CUSTODY_DIRECTORY`, which is required, wherever the file given lies. The bound is the profile's `max_export_lag_seconds`, which `N` may lower and never raise; a declared `prepare` without a profile is refused. It is at most 86400, and never the declaration's. A declaration states exactly those five fields, each as text, with a reason. The marker records the declaration and the bound, and the command prints the window that is not restored |
| `replay --checkpoint FILE --marker FILE` | Replays withdrawals and tombstones, purges, and completes the marker. An export replays only when the declaration its marker records validates again; the receipt records the window, and the command prints it. A marker already complete is refused: replaying it again would let a database that has not served since (a set-aside source) serve with every later deletion undone. A marker of an abandoned recovery is refused too |

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
  application for the workspaces `EXULANICA_SOCIETY_CONTROL_WORKSPACES` lists (and, where account
  discovery is on under durable spending, the watched workspaces every round and every account
  workspace once every five minutes), from the settings in 5.1, when the API runs with
  `EXULANICA_COMPARISON_WORKER=process`; each plays within the bound its
  owner stated ([running a comparison](society-experiments.md#running-a-comparison)). Before it
  claims any, it checks the database's recorded migrations against its own and its role as the API
  does (5.1.3).
- `exulanica-playback-worker` plays the societies of the workspaces 5.1.5's settings name and seals
  their coupled traffic, from the settings in 5.1, when the API runs with
  `EXULANICA_PLAYBACK_WORKER=process` (5.1.5). It checks the schema, the runtime role and the
  restore state as the API does, asks people's chosen models through its own client and budget,
  writes one line of JSON per event on standard output, and on `SIGTERM` or `SIGINT` lets a round
  in progress finish or roll back before it exits. It opens the connections the API's playback and
  traffic controller would (5.4.3) and one more, idle, that holds its lock.
- `exulanica-piece-generation` serves the operator's registered generation session with the
  piece requests of the workspaces `EXULANICA_WORKSPACE_IDS`, `--workspace` or
  `EXULANICA_ACCOUNT_DATABASE_URL` name, as `exulanica_app`, under `EXULANICA_SPENDING=durable`
  with `EXULANICA_SPENDING_WITNESS_DIR` on the shared spending witness volume.
  It needs `EXULANICA_GENERATION_BUCKET_KEY_FILE` (the bucket key file the operator creates for it)
  and keeps pieces in the `generated-pieces` namespace up to `EXULANICA_GENERATED_PIECES_MAX_BYTES`
  (two gibibytes by default). The operator registers and closes sessions with
  `python -m exulanica.generation session open|close|status` as the owner;
  [generated pieces](generated-pieces-contract.md#5-who-runs-the-gpu-and-who-pays) owns both.
- `exulanica-wmp` is owned by the [world memory package](world-memory-package.md), and
  `exulanica-gsplat-scene-v1` by [scene training](gsplat-scene-jobs.md).
- `TAVILY_API_KEY`, `EXULANICA_REFERENCE_WORKER`, `EXULANICA_REFERENCE_WORKSPACES` and
  `EXULANICA_REFERENCE_PICTURES` configure reference notes, owned by the [reference notes contract](reference-notes-contract.md#7-configuration).
  Web notes need `https://api.tavily.com` in `EXULANICA_EGRESS_ALLOWLIST`.
- `EXULANICA_CREATURE_WORKER` and `EXULANICA_CREATURE_WORKSPACES` configure creatures drafted from
  words, owned by the [things contract](things-contract.md#drafting-a-creature-from-words): the
  worker runs in the API process unless set off, for the JSON array of workspace ids listed (none
  when absent). Every API process of an installation needs the same values and a model client:
  each ends at startup the drafts of every workspace it knows but does not serve.
- The test suite's settings, such as `EXULANICA_TEST_DATABASE_URL`, `EXULANICA_TEST_POSTGRES`,
  `EXULANICA_TEST_DATABASE_URLS`, `EXULANICA_REQUIRE_POSTGRES` and
  `EXULANICA_REFERENCE_DATABASE_URL`, are in [development setup](development-setup.md).
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` and `EXULANICA_PORT` are read by
  `compose.yaml` itself, and `EXULANICA_SEED_ARCHIVE` and `EXULANICA_JUDGE_PORT` by
  `deploy/judge/compose.yaml`, which also requires `EXULANICA_BUDGET_USD` and
  `EXULANICA_BUDGET_MAX_CALLS` with no default; `EXULANICA_PUBLIC_HOST`, `EXULANICA_TLS`,
  `EXULANICA_EDGE_ADDRESS`, `EXULANICA_EDGE_HTTP_PORT` and `EXULANICA_EDGE_HTTPS_PORT` by
  `deploy/judge/edge.yaml` (section 8.1); `EXULANICA_SYNC_EXTRAS` is an image build argument.

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

### 5.4 What one instance runs out of, and where each is bounded

One API process runs out of request threads, database connections, decode memory and open streams,
and each is taken by work the process has already accepted. `exulanica/api/admission.py` therefore
decides, before any of it is taken, whether the process accepts a request now. **Every number in
this section bounds one API process.** Several API processes behind one database hold several
times each limit, and a workspace can hold its share in each of them; the database's
`max_connections` must cover the sum (5.4.3).
One thing is not shared between API processes: a kind of place being drafted
([world kinds contract](world-kinds-contract.md)) lives in the process that started it, so behind
several processes drafting needs routing that sends each person to the same process, or a poll
another process answers reads the draft as unknown while it still runs.

#### 5.4.1 Admission

Pure ASGI middleware, just inside the body limit (5.1.2), sorts each request by its route into a
class before routing, before the body is parsed, before a thread is taken and before a connection
is opened:

| Class | Routes | Limit | One workspace's share | `Retry-After` |
| --- | --- | --- | --- | --- |
| exempt | `GET /healthz`, `GET /readyz` | none | none | none |
| streams | `GET /formation/{batch_id}` | `EXULANICA_API_STREAMS` (128) | `EXULANICA_API_WORKSPACE_STREAMS` (8) | 5 s |
| uploads | `POST /intake`, `POST /workspace-assets`, `POST /workspace-style-packs` | `EXULANICA_API_UPLOADS` (2) | `EXULANICA_API_WORKSPACE_UPLOADS` (1) | 10 s |
| requests | every other route | `EXULANICA_API_REQUESTS` (24) | `EXULANICA_API_WORKSPACE_REQUESTS` (12) | 1 s |

- `GET /workspace-style-packs/{manifest_sha256}/archive` also bounds itself, in the route: at most 2
  archives a process and 1 a workspace at a time, each holding up to one pack's 64 MiB on the
  request's temporary disk until its response ends, so archives take at most 128 MiB of temporary
  disk a process.
- A class at its limit answers **503 `capacity_exhausted`**, and a workspace at its share **429
  `workspace_capacity_exhausted`**. Both carry `capacity` (the class), `retry_after_seconds` and a
  `Retry-After` header. Nothing of the route ran before either answer, so the same request can
  always be sent again after that wait. A refusal names no other workspace.
- There is no queue in front of the classes: a request over a limit is answered at once.
- A refused request that declares a body is answered at once, and its connection is closed only
  after its body has been read and discarded, so a client that sends its whole body before it
  reads meets the answer rather than a reset (a socket closed with bytes unread is reset). Each
  drain is bounded by the body limit (512 MiB, 5.1.2) and 10 seconds, and at most 64 refusals
  drain at once in one process. A drain holds no slot, no thread and no connection. A refusal
  whose client waits for `100 Continue` has sent no body and is closed at once; so is one past
  those bounds (a client that cannot finish its body within 10 seconds, a body without a declared
  length that passes the limit, a sixty-fifth at once), and a client still sending then reads a
  reset. `GET /operations/capacity` counts how each refusal with a body ended under
  `refusal_drains`: `drained` (read to its end), `left` (the client went first), `cut` (a bound
  reached first) and `closed` (not drained).
- The share is claimed in the permission floor (`authorise_route`) as soon as the caller is known,
  after the permission check and before the tile charge, so a request that is not permitted is
  refused as it would be on an idle server and a refused request is never charged.
- A slot is released where it was taken, around the whole response, a streamed one included.
- The door's held polls (`GET /door/channel/frames`, [door contract](door-contract.md)) are
  streams with bounds of their own: one process holds at most 64, at most four for one workspace
  and at most 32 for one bridge. So one process serves the programs of at most 32 workspaces at a
  time through one bridge; a listed bridge many owners use at once needs more API processes, or
  some of its programs are answered 503 `door_busy` and, once quiet past their hold and ten
  seconds, are reported not connected and their things fall to the routine.
- A body that stops arriving is answered **408 `body_timeout`** and the connection closed: 15
  seconds between pieces, or 60 seconds in total for a request (600 for an upload, which is 512 MB
  at about 0.9 MB/s). A client can hold a slot for at most its class's total; a limit per address
  belongs to a reverse proxy (5.1.2).
- `GET /workspace-assets/{asset_id}/prepared/bytes` and a character body's
  `.../preparations/{preparation_id}/bytes` are in the requests class. Each copies the prepared
  output (a workspace asset's is at most 32 MiB) from the store to a file of its own, checking its
  hash, asks the final read check, closes its database connection and then sends the file 1 MiB
  at a time. A download holds its slot until its last byte is sent; its memory and disk are in
  5.4.4.
- A route missing from the application while `CAPACITY_ROUTES` still names it stops the build, so a
  renamed route cannot fall back to `requests` unnoticed.
- `/readyz` reports each class's limit and share and the decode limit (6.2). The counts (in flight,
  peak, admitted, refused, body timeouts, failed stream polls, and the decode bound's) are an
  operator's read, `GET /operations/capacity` with `operations.read`, because what is in use is other
  workspaces' activity; it names no workspace and adds the caller's own holdings.
- Every request takes its class's slot before it is authenticated, so a flood of unauthenticated or
  refused requests uses the same slots as real work. A public deployment needs a rate limit per
  address at its edge (section 11, D-13); admission bounds the damage, it does not attribute it.

A request that is not permitted, is malformed or names an unknown id is answered as before; a
capacity refusal never replaces one of those answers for a request the process accepted. A
transient database conflict, SQLSTATE 40001 or 40P01 (migration 0041's asset read barrier refuses
a guarded write for the instant a final read check holds it), is answered 409 `busy` with
`Retry-After` on every route, never a bare 500; a route that knows more answers with its own code.

#### 5.4.2 The request threadpool

Synchronous routes and dependencies run on anyio's default thread limiter, which the lifespan sets
to `EXULANICA_API_THREADS` (40). Startup refuses fewer than `EXULANICA_API_REQUESTS +
EXULANICA_API_UPLOADS + 4` threads, so an admitted request never waits for a thread while it holds a
connection; the four are for multipart spooling and for streams resolving their caller. Streams do
not use this limiter between polls (5.4.5), liveness does not use it at all, and readiness runs in
one thread of its own, one evaluation at a time (6.1).

#### 5.4.3 Connection slots

A request opens one database connection through `scoped_connection` or `readonly_connection` in
`exulanica/api/dependencies.py` and holds it for its whole duration, and a browser-session request
opens one more, briefly, to the account store. There is no pool (section 12.1). Admission bounds how
many requests hold connections, so one API process opens at most:

    connections = 2 x (requests + uploads) + 4 stream pollers + 2 for readiness
                  + background: 2 in-process derivative worker, 1 playback, 2 comparisons,
                    2 traffic controller, when each runs in the process

With the defaults and nothing running in the background that is 58, and 5.4.7 gives the peak
measured under load. A PostgreSQL server at its default `max_connections` of 100 keeps 3 slots for
superusers and leaves 97 for every API process and worker on that server, so a second API process at
the defaults needs a larger setting or smaller limits. Section 3 has one server for every process.

#### 5.4.4 Decode memory: the term that sizes the box

One photograph at `MAX_PIXELS` (64 megapixels) costs about 512 MB at peak: Pillow stores `RGB` at
four bytes per pixel, and `ImageOps.exif_transpose` allocates a second buffer of the same size.
`exulanica/corpus/decode.py` holds the measurement and its environment.

The same module bounds how many decodes run at once in a process: `EXULANICA_API_DECODES` (2) in the
API, 2 in every other process. A decode takes a turn before its pixels are loaded and keeps it
through the orientation copy, and `POST /intake` keeps one for the whole part it ingests. A decode
that waits 20 seconds for a turn gives up with nothing decoded: a read answers 503
`capacity_exhausted` for `decodes`, an upload refuses that part as `busy` (nothing of it written),
and the derivative worker retries the capture later.

    API decode bytes <= D x 512 MB + U x 67 MB

`D` is the decode limit and `U` the uploads limit; the 67 MB per upload is the encoded part the
intake route reads into memory before it probes anything (`MAX_PART_BYTES` plus one byte). At the
defaults that is about 1.2 GB. The dedicated derivative worker is a separate process with one
delivery thread, so budget about another 512 MB for each worker process. The levers are the decode
limit, the uploads limit, `MAX_PART_BYTES` and `MAX_PIXELS`.

A prepared output download (5.4.1) adds a 1 MiB chunk of memory and keeps the output on disk
instead: up to its size per download in progress, in a file under `EXULANICA_DATA_DIR` that has no
name and is freed when the download ends or the process does. At the default requests limit,
downloads of 32 MiB workspace assets hold at most 24 x 32 MiB = 768 MiB of that disk.

#### 5.4.5 A formation stream holds a place, not a thread

`GET /formation/{batch_id}` (`exulanica/api/routes/formation.py`) polls the ledger every 2 seconds.
Each poll opens a read-only connection bound to the caller's workspace, reads, and closes it, in one
of four threads the process's streams share; between polls a stream holds only its place in the
streams class. So open streams cost at most four connections and no request thread, and a client
that leaves gives its place back within one poll. A poll has a 5 second statement timeout; a poll
that fails sends nothing and the next one tries again, and three failed polls in a row end the
stream. A stream also ends at 30 minutes. Either end comes without a terminal event, after
`retry: 5000` (the delay a browser `EventSource` reconnects after), and means "reconnect with the last
event id". A heartbeat comment every 7 polls keeps a proxy from closing a quiet stream.

A stream resumes from `Last-Event-ID` (which wins) or `since`. `received` and any well-formed event
id are positions, including an id the stream never sent: event ids are uuidv7 values PostgreSQL
assigns at insert, and a resume reads the events after the token. Resuming from the batch's terminal
id answers 200 with no events once the batch has ended with that status, so a client that already
has the outcome is not sent it twice. A malformed token, another batch's terminal id and a terminal
id the batch has not ended with each answer 422 `invalid_resume_token` before a stream opens. One
batch has one writer at a time except while a derivative job's lease is reclaimed from a claimant
that was silent but alive: events that claimant commits after its lease was taken, at most one
capture's, can be missed by a live stream. Counters and the outcome stay correct, because each is
folded from the whole ledger.

#### 5.4.6 The derivative queue

`POST /intake` refuses an upload with 429 `derivative_queue_full` (and `Retry-After` 30) when its
workspace already has `EXULANICA_INTAKE_QUEUED_JOBS` (4) derivative jobs queued or running, checked
before a batch is opened, so nothing is written. The job is queued at the end of the upload, so
uploads admitted at the same moment each pass the check before either queues: with the default
share of one upload per workspace in one process the bound is exact, and with several API processes
a workspace can pass it by at most the number of processes times the uploads share, minus one. A
batch whose every photograph was withdrawn before its derivatives ran closes `cancelled`, and its
terminal event says `reason: cancelled`; one with some photographs finished closes by those.
`GET /operations/derivative-jobs/{job_id}` reads one job's state and progress, and answers 404
`unknown_reference` for a job the workspace cannot see.

An upload writes the stage registry before it opens a batch, and that write is guarded by migration
0041's barrier, so it can meet a final read check (one runs before every vision call). The route
tries it three times over about 150 milliseconds and then answers 409 `busy` with `Retry-After` 1,
with nothing written. A part whose own intake write meets one is rolled back and refused as `busy`,
not `failed`, and is admitted when it is sent again.

#### 5.4.7 The measured envelope

Measured with `scripts/measure_runtime_capacity.py` and `scripts/runtime_capacity_workload.json` on
one host: an 18-core Apple M5 Max with 64 GiB, PostgreSQL 18 on the same host (`fsync` on,
`max_connections` 100), one API process with the default limits, and the dedicated derivative
worker with a vision model that answers after one second. A local record, not a statement about
another host or about more than one process. The two items on inhabited worlds read their figures
from the [lock-holder record](evaluation/2026-10-02-asset-lock-holders.json):
`scripts/measure_asset_lock_holders.py` running this harness's sharing phases on main 61d99d9a, the
towns played by the API process and then by the playback process
(`tests/test_measured_envelope_record.py` holds each figure to the record).

- **Supported load:** eight workspaces, each holding six progress streams and watching each of its
  uploads to its outcome, reading three times a second and uploading three photographs a minute,
  for three minutes. Small reads answered at 10.4 ms p95 (21 ms p99), every upload was accepted
  (62 ms p95), every watched upload reached its outcome, no subscription received an event twice
  or an event of another workspace's batch, and progress arrived within the two-second poll (1.9 s
  p95). The process peaked at 41 threads, 243 MiB resident and a quarter of one core, the database
  at three client backends, the derivative queue at one job, and `/healthz` answered at 2.1 ms p95.
- **The first constraint is one process's CPU:** cheap reads stop rising at about 760 a second
  between 8 and 16 concurrent requests (p95 15 to 28 ms), and at the requests limit of 24 the p95 is
  about 66 ms while the excess is refused in a few milliseconds. The limit sits above that knee
  because many requests wait on a model, a traffic worker or a lock rather than on the core. More
  API processes behind one database is the boundary that expands it (5.4.3), with each person
  routed to one process while drafting a kind of place (5.4).
- **Faults:** a client killed while holding streams, a request cancelled mid-body, stalled upload
  bodies, a table lock held for twenty seconds, the derivative worker killed or paused past its
  lease, and the API killed mid-stream each gave every slot back. Every watched upload reached one
  outcome, no subscription received an event twice, and where a live stream was compared with a
  full replay (the worker killed, the worker paused) it had missed none.
- **Past the limits:** the same eight workspaces each offering 150 small reads a second (the client
  sent about 730 a second in all), holding 16 progress streams (twice the workspace share) and
  uploading three 12-megapixel photographs every five seconds, for two minutes. Of 87,857 small
  reads, 41,804 were answered (137 ms p95) and 46,053 were refused with 503 `capacity_exhausted` in
  46 ms p95, with no other answer. 2,415 attempts to open a stream past a workspace's share were
  refused with 429, and every watched upload reached its outcome with no event twice and none of
  another workspace's. `/healthz` answered every probe at 27 ms p95. The process peaked at about 1.4
  cores and 760 MiB, the database at 26 client backends and the derivative queue at 20 jobs. Of 176
  uploads, 63 were accepted, 86 answered 409 `busy` (5.4.6) and the server refused 27 for the
  uploads class.
- **Before refusals drained their bodies, a refused upload could arrive as a reset connection.**
  An upload was refused before its body was read and its connection then closed, so a client still
  sending a large body could see the close before the 503: in the run above, 23 of the 27 refused
  uploads reached the client that way. Refusals now drain their bodies (5.4.1), and this load has
  not been measured since. A client treats a reset during an upload as "send it again later",
  which a refusal closed at once still produces. Behind the installation's own
  client proxy (`deploy/installation/client-nginx.conf`), which reads a request's body before
  passing it on, an acceptance run on the same host sent 40 uploads of about 3.35 MB from four
  workspaces at once through a running installation, and none met a reset: the proxy's per-address
  write limit answered 19 with its own HTML 429, the API admitted 2 and refused 19, and the client
  received 18 of those refusals as 503 `capacity_exhausted` and one as the proxy's HTML 502. The run
  kept no proxy log; the likeliest cause of the 502 is the API answering and closing while the proxy
  was still sending it the body. That run predates both the drain and the proxy's own refusals in
  the problem shape (5.4.8), which now answer that 429 as `rate_limited` with `Retry-After` and that
  502 as `upstream_unavailable` with `Retry-After`. A client treats either during an upload as "send
  it again later".
- **Inhabited worlds beside the supported load:** eight towns whose societies the API process plays
  at four times speed, each town's traffic read every five seconds, beside the supported load for
  three minutes. The towns advanced 87 to 88 percent of the ticks their speed sets (96 to 97 ticks),
  and traffic reads took 1.2 s p50, 2.7 s p95 and at most 11 s. Small reads answered at 29 ms p95,
  and 26 of 4,298 were refused when the requests class reached its 24. 24 of 24 uploads were
  accepted and 6 of 72 photographs were refused `busy` (5.4.6): a playback round holds migration
  0041's global asset read lock from its authorization to its commit
  ([asset read currency](asset-read-currency.md#society-inputs-under-the-barrier)), and a guarded
  intake write that meets it is refused. The record's sampler saw the lock held in 3.7 percent of
  its samples, and 13 of the 14 guarded writes refused met a round holding it. No traffic read held
  it. The API process peaked at 531 MiB. The supported figures above therefore hold for an API
  process that plays no towns.
- **The same towns played by the playback process:** with `EXULANICA_PLAYBACK_WORKER=process`
  (5.1.5) and the same load, the towns advanced 85 percent of the ticks their speed sets (104
  ticks), traffic reads took 29 ms p50, 3.7 s p95 and at most 14 s, and small reads answered at 19
  ms p95, with 59 of 4,323 refused at the requests limit. 24 of 24 uploads were accepted and 4 of 72
  photographs were refused `busy`; the lock was held in 5.1 percent of its samples, and 22 of the 23
  guarded writes refused met a round of the playback process. The API process peaked at 289 MiB and
  the playback process at 500 MiB.

Not measured: load past the limits for longer than two minutes, more towns or more traffic than
above or both together with the overload, more than one API process, and any other host.

#### 5.4.8 The client proxy's own refusals

The client proxy (5.1.2) answers some requests itself, without the API. Each such answer takes
the problem shape every API refusal takes, `{"code", "detail"}` as JSON with `Cache-Control:
no-store`, because the browser reads a failure's code and detail and nothing else:

| Status | `code` | When | `Retry-After` |
| --- | --- | --- | --- |
| 413 | `body_too_large` | A body over the profile's cap (5.1.2); `limit_bytes` states the cap | none: the same body is refused again |
| 429 | `rate_limited` | A write past the per-address limit (section 8) | 2 s, the limit's rate, also as `retry_after_seconds` |
| 502 | `upstream_unavailable` | The API could not be reached or closed the connection without an answer | 5 s, also as `retry_after_seconds`; whether the request ran is not known, so only a request that is safe to repeat is sent again |
| 504 | `upstream_timeout` | The API did not answer within the proxy's 300 second read timeout | none: the work may still finish |

An answer the API makes, a 503 `capacity_exhausted` included, passes through the proxy unchanged
(`proxy_intercept_errors` is off). `tests/test_installation_deployment.py` holds each row for both
configurations. The reviewer stack's TLS edge (8.1) answers the refusals it makes itself, a body
over its 8 MiB, and a web proxy it cannot reach or that does not answer in time, as the 413, 502
and 504 rows, through Caddy's `handle_errors`; whatever the web proxy or the API answers passes
through it as sent (`tests/test_judge_edge.py`).

## 6. Health check

`exulanica/api/routes/health.py` serves both endpoints. Neither requires a credential, and neither
returns anything about a workspace's contents.

### 6.1 Three signals, not one

| Signal | Path | Cost | Checks |
| --- | --- | --- | --- |
| Liveness | `GET /healthz` | Nothing beyond the process, and no worker thread | The process is running and can serve a request. No dependency is touched |
| Readiness | `GET /readyz` | A few cheap queries and one store probe, no model call, in a thread of its own | The dependencies a request needs are reachable (6.2) |
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
executor role, no model credential, no material or character catalog, or a spent model budget),
`configuration`, which names each setting as set or missing and never shows a value, and `capacity`,
the declared limit and share of each admission class and the decode limit (5.4.1). What is in use is
not in it: that is other workspaces' activity, read with `operations.read` at
`GET /operations/capacity`. A full instance is serving, so saturation leaves `ready` as it is.

Both endpoints are exempt from admission. Readiness evaluates its checks one at a time: a probe that
arrives while an evaluation runs is answered from the last one when it is at most 2 seconds old, and
otherwise waits for the running one for at most 5 seconds. `checked_at` and `age_ms` say when the
checks ran. A flood of probes therefore holds one thread and one evaluation's connections.

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

The browser client's proxy in `deploy/judge/web.Dockerfile` limits writes per client address: any
`/api` request other than `GET`, `HEAD` and `OPTIONS` is counted at 30 a minute with a burst of 20,
and the excess is refused with 429 `rate_limited` in the problem shape (5.4.8). Every route that can
call a hosted model is a write, so the limit paces a script against the model budget; it is a stated
bound, not a measurement of how fast a person works. The address comes from `X-Forwarded-For` only
when the connection arrives from a private container range.

### 8.1 Serving it over HTTPS from one host

A browser gives `crypto.subtle` only to a secure context, and the client refuses every region
without it, so a judge on another machine needs HTTPS rather than a wider bind.
`deploy/judge/edge.yaml` is an overlay on the reviewer stack that adds one service, a Caddy
reverse proxy (`caddy:2.11.4-alpine`) that terminates TLS and forwards to `web`, never to `api`,
so the `/api` prefix strip and the write limit stay in the path. Its `Caddyfile` takes the host
name from `EXULANICA_PUBLIC_HOST` and the certificate issuer from `EXULANICA_TLS`: an ACME contact
email asks a public certificate authority, and `internal` issues from Caddy's local authority for
a rehearsal. The overlay gives `postgres`, `api`, `web` and the edge `restart: unless-stopped` and
JSON logs capped at ten 10 MB files each; `migrate` and `seed` stay one-shot. The edge's bind
address has no default. Caddy redacts `Authorization` and `Cookie` values in its access log.

`deploy/judge/stack.sh` runs every step. It writes the stack's secrets into a directory it
creates mode 0700 (`EXULANICA_DEPLOY_DIR`), with the database passwords generated into a
`judge.env` created mode 0600 and each judge's token minted by `exulanica-seed token` into a file
of its own, merged into the one directory the API loads. It never writes the model credential:
`up` passes `NEBIUS_API_KEY` through from the calling shell, and without it the model routes answer
that no credential is configured. It never builds on the host, and it starts `migrate` and `seed`
only on the first `up`, because the restore refuses a database that already holds the seed.

| Command | What it does |
| --- | --- |
| `build` | On the build host: builds `exulanica-judge-backend` and `exulanica-judge-web` for `linux/amd64` from the checkout, as `compose.yaml` declares them, and prints their image IDs |
| `images` | Prints the two image IDs, to compare the host with the build host |
| `init` | Writes `judge.env` from `EXULANICA_PUBLIC_HOST`, `EXULANICA_TLS`, `EXULANICA_SEED_ARCHIVE` and `EXULANICA_EDGE_ADDRESS`, leaving `EXULANICA_BUDGET_USD` and `EXULANICA_BUDGET_MAX_CALLS` empty; the stack refuses to start until both are filled in |
| `mint <label>`, `revoke <label>` | Adds or removes one judge's token; the next `up` serves the change |
| `up` | Starts the stack from loaded images; the first run migrates, seeds and verifies |
| `reset` | Returns the world to the archive (section 8, step 4) |
| `status`, `logs [service]` | The containers and the API's readiness from inside the stack; the logs |
| `down`, `destroy --yes-delete-volumes` | Stops the stack, keeping or deleting its volumes |

**On Nebius AI Cloud.** The recipe is one CPU virtual machine: platform `cpu-d3` (AMD EPYC Genoa),
preset `4vcpu-16gb`, a 50 GiB network SSD boot disk with Ubuntu 24.04, a public IP address, and
inbound TCP 22, 80 and 443 only. Run from these images on 2026-09-29 with the Montserrat volcanic
seed, the API peaked at 235 MiB across a graph read and PostgreSQL at 176 MiB (`docker stats`,
sampled each second), so either preset leaves room; `2vcpu-8gb` is the smaller one. The host
needs Docker Engine with the Compose plugin, `python3` and `openssl`; the images are loaded, not
built there, and the host's CPU must be `x86_64`. The steps, with `<placeholders>` for every
value:

1. On the build host, from a checkout of the commit to serve, with Docker running:
   `deploy/judge/stack.sh build`, then
   `docker save exulanica-judge-backend exulanica-judge-web | gzip > judge-images.tar.gz`.
2. Export the seed archive with the same commit's `exulanica-seed` (section 8, step 1), because the
   restore refuses an archive whose schema or registries differ from the images'.
3. Copy the images, the archive and the checkout's `deploy/judge/` directory to the host
   (`scp` or `rsync` over SSH), then on the host
   `gunzip -c judge-images.tar.gz | docker load` and `deploy/judge/stack.sh images`; the two IDs
   must equal the ones `build` printed.
4. Choose the host name. Without a domain, `<address with dashes>.sslip.io` resolves to the
   public address through the third-party sslip.io service, assumed available rather than
   guaranteed; with a domain, an `A` record pointing at the address and that name. Either way,
   the certificate authority must reach the host on port 80 or 443 to issue the certificate.
5. `EXULANICA_DEPLOY_DIR=<secrets directory> EXULANICA_PUBLIC_HOST=<host name>
   EXULANICA_TLS=<contact email> EXULANICA_SEED_ARCHIVE=<archive directory>
   EXULANICA_EDGE_ADDRESS=0.0.0.0 deploy/judge/stack.sh init`, then set `EXULANICA_BUDGET_USD`
   (for example `10.00`) and `EXULANICA_BUDGET_MAX_CALLS` in `<secrets directory>/judge.env`.
6. `deploy/judge/stack.sh mint <label>` once per judge.
7. `read -rs NEBIUS_API_KEY && export NEBIUS_API_KEY`, then `deploy/judge/stack.sh up`. Leaving
   the key unset serves everything except the model routes.
8. From any machine, `uv run python scripts/judge_smoke.py --origin https://<host name>
   --token-file <one judge's token file> --http-origin http://<host name> --rate-limit`; it checks
   the client, liveness, readiness, a refused and an accepted read, the world list, the redirect
   and the write limit through the public origin, and exits 0 when all pass. `--ask "<question>"`
   adds one Companion question, which calls a hosted model.
9. Give each judge the address and their own token, which the client asks for once. The token
   is the key of the one entry in `<secrets directory>/judge-tokens/<label>.json`.
10. When judging ends: `deploy/judge/stack.sh destroy --yes-delete-volumes`, then delete the
    virtual machine, its disk and its public address in the console.

`EXULANICA_BUDGET_USD` is a ceiling for one API process life: a restart of `api`, or of the host,
starts a fresh one, so the model provider's own balance is what bounds spend across restarts. The
stack has no per-judge spend limit, no backup of its volumes (D-3) and no monitoring beyond the
health status Docker records, which nothing acts on, and `status`; a revoked token stays valid
until the next `up`.

### 8.2 The public server

The reviewer stack serves one seeded workspace through a role that registers no world, so it
cannot serve visitors who make worlds, choose the models that run their people and compare them.
The public server is the installation composition instead (`compose.yaml`, profile
`single-host-server-only`, section 9.1), with `deploy/public/public.yaml` layered on it.

**What the overlay changes:**
- **An edge in front.** It adds the reviewer stack's Caddy edge (8.1), configured by
  `deploy/public/Caddyfile`. The edge forwards to the installation's `client` proxy and never to
  `api`.
- **The API's port.** It removes the API's published port (`ports: !reset []`). A published port
  would let a request reach the API around the client proxy's write limit and body cap.
- **Spending.** It sets `EXULANICA_SPENDING=durable` on the API and the playback worker, so every
  model attempt is admitted by the spending authority as well as the process fuse. The fuse
  (`EXULANICA_BUDGET_USD`, `EXULANICA_BUDGET_MAX_CALLS`) has no default here.
- **Images.** It names one image per recipe: `exulanica-public-backend`,
  `exulanica-public-maintenance`, `exulanica-public-client` and `exulanica-public-tiles`, and runs
  the database and the edge as `exulanica-public-postgres` and `exulanica-public-edge`: the
  published pgvector and Caddy versions, which `build` pulls by their index digests (named in
  `public.sh`) for the build platform. A host therefore loads six images. Every service has
  `pull_policy: never` and `up` passes `--pull never`, so the server never resolves a tag.
- **The tile worker.** `public.sh` selects the `public` installation profile and the `tiles` compose
  profile, so the generated-tile worker runs and publishes only as `exulanica_tiles` (9.1).
- **Logs.** It bounds every long-running service's logs to ten 10 MB files.

The edge caps a body at 8 MiB. Nobody on this server uploads photographs; the largest body is a
question, a world's description or a picture to draft from. The reconstruction workers do not run.
`tests/test_public_deployment.py` holds these properties.

**Arrival worlds.** The worlds a newcomer's workspace starts with are a versioned catalog,
`exulanica/world/arrival-worlds.v1.json` (`EXULANICA_ARRIVAL_WORLDS` names another). Each entry is
a recipe, its values, a title and a fixed world identity. A generated town's seed is drawn from its
recipe and its identity, so every workspace's copy of an arrival world is the same town, and a tile
already baked queues no job. `prepare-towns` makes them once in the operator's own workspace, and
the tile worker bakes them there. Identities are keyed by workspace, so one identity in many
workspaces names many worlds, each its workspace's own. An entry may also name a shipped scene
(`assets/catalogs/scenes`) by key, version and digest; the shipped town names
`three-strangers-in-town` v1. Each copy, the operator's included, is then dressed with it through
the scene dressing a server runs ([things](things-contract.md)): its things are placed through the
things route's edit, the version's society is made on the scene's engine, and each being's mind is
recorded as the owner's choice, so a guest's own allowance pays for those minds and the routine
decides once it is spent. That engine is a society of things, which the overlay hands the API
alone, off unless `public.env` sets `EXULANICA_SOCIETY_OF_THINGS=on` (the first one a
non-rehearsal server plays fixes how its engine version must replay). A host that does not offer
it places nothing, so the arrival town opens undressed as it did before, and names the step
`scene` with `society_engine_not_offered` in the entry's `incomplete`; any other refusal is named
there by its code, with what was laid kept.

**Built and not built.**
- Built: the composition, `deploy/public/public.sh`, the tile worker and the arrival worlds, and the
  host's health and preflight timers.
- Built: a visitor's own entry (5.1.4): one request makes a guest's workspace, gives it its
  allowance under the guest policy and its first world from the arrival list.
- Built: a visitor's town plays, and asks the models its people were given, while the visitor is
  there, paid from their own grant (5.1.5): the overlay turns account discovery on and plays in the
  API's process. At most `EXULANICA_GUEST_PLAYING_MAXIMUM` guests' towns play at once; another
  waits, and its page says so. `init` writes `EXULANICA_PLAYBACK_WORKERS=4` unless told otherwise:
  measured with 12 and 24 model-run towns, four workers played a median of 4.2 and 3.7 simulated
  minutes a minute per town against one worker's 2.3 and 1.2, with every answer accepted.

`deploy/public/public.sh` runs every step. Every step but `build`, `images` and `save` reads the
secrets directory `EXULANICA_DEPLOY_DIR`:

| Command | What it does |
| --- | --- |
| `build` | On the build host, from a clean checkout: builds the client bundle with no `VITE_` setting and compiles the tessellator (`tsc --build`), then builds the four images for `EXULANICA_BUILD_PLATFORM` (default `linux/amd64`), pulls the database and edge images for the same platform, each by the digest of that platform's manifest read from the pinned index, names them, and prints the six IDs. `EXULANICA_REHEARSAL_BUILD=1` allows a working tree with changes, for a rehearsal only |
| `images`, `save <file>` | Print each of the six images' ID and architecture; write the six images to one gzip archive and print its sha256 |
| `init` | Writes `public.env` (mode 0600, in a directory created 0700). It holds seven generated role passwords, the `public` profile, the host, issuer, edge address and ports, the backup and custody directories, and the model endpoint's allowlist. It also writes the operator's token, whose grant holds `operations.read` alone. Custody inside the backup directory is refused. The fuse is left empty |
| `mint <label>`, `revoke <label>` | Add or remove a token for a workspace of its own, minted by the image's `exulanica-seed token` with the reviewer's permissions. The next `up` serves the change and plays those workspaces |
| `up` | Starts the server from loaded images, never building. It refuses until the fuse is filled in, and refuses when the merged Compose configuration publishes a port for `api` or `client`: only the edge may. The overlay gives the network a fixed range and the edge, the client proxy and the API fixed addresses: the client proxy trusts `X-Forwarded-For` from the edge's address alone and the API trusts forwarded headers from the client proxy's alone, so a process on the host, which reaches every container at its bridge address from the network's gateway, names neither its counted address nor its scheme. The client proxy finds the API by name once, when it starts, so the API keeps one address through every recreation and host restart. A host that already uses that range changes every place `deploy/public/public.yaml` names. `restore-marker`, `migrate` and `catalogs` run to completion on every start |
| `prepare-towns` | Makes the arrival worlds in the operator's workspace, inside the API's container, and dresses each with the scene the arrival list names (`python -m exulanica.api.arrival_dressing prepare`); prints each tile's state and what each dressing left incomplete, and exits 1 when anything is, except a host that does not offer the scene's engine; run it again to read the tiles once baked |
| `issue-authority`, `guest-policy`, `guest-policy-withdraw`, `grant <label>`, `spending` | Issue the server's spending authority from `EXULANICA_AUTHORITY_USD`, `EXULANICA_AUTHORITY_CALLS` and `EXULANICA_AUTHORITY_VALID_UNTIL`; grant a minted workspace `EXULANICA_GRANT_USD` and `EXULANICA_GRANT_CALLS` under it; set what each guest is granted under it (`EXULANICA_GUEST_USD`, `EXULANICA_GUEST_CALLS`, `EXULANICA_GUEST_DAYS`) and how many guests it grants in a UTC day (`EXULANICA_GUEST_GRANTS_PER_DAY`, the day's entries unless stated); end that policy so no guest is granted anything until another is set; print the authorities' state and each live guest policy, with whether it must be set again. Each runs `python -m exulanica.spending` as the owner in a one-shot container on the server's network, with the witness volume |
| `backup-now` | One maintenance pass now (9.3) |
| `status` | The containers, readiness from inside the client container, Docker's disk use and the backup and custody file systems |
| `watch` | One check of three paths, each counting its failures in a row. The API's own liveness, read from inside the client container: three failures recreate the API container, because Docker restarts a container that exits and never one that only fails its health check (section 9). The path the edge takes, read from inside the edge container through the client proxy: while the API is well, three failures restart the client proxy, which finds the API again (a proxy that lost the API answers 502 for every API path while the API is well). The edge itself, over TLS, resolved to this machine, with readiness: logged, and from the third failure in a row reported as `edge failing` by every check that repaired nothing, never repaired itself, since a failing certificate or edge is fixed by neither restart |
| `preflight` | The catalog preflight (section 7) from the backend image. Its allowlist is the catalog origins the image's manifest declares; the API's allowlist stays the model endpoint |
| `logs`, `down`, `destroy --yes-delete-volumes` | Follow the logs; stop and keep the volumes; stop and delete them, the database, store and spending witness included |

The model credential is never written to a file: `up` passes `NEBIUS_API_KEY` through from the
calling shell.

**On one host.** The machine is section 8.1's: a `cpu-d3` virtual machine with Ubuntu 24.04, a
public address, and inbound TCP 80 and 443, with 22 limited to the operator's address. It also has
a second disk for backups. The layout the systemd units name:
- `/srv/exulanica/app`: `compose.yaml` and `deploy/public/` from the commit served;
- `/srv/exulanica/secrets`: the secrets directory;
- `/srv/exulanica/custody`: custody;
- the second disk for backup sets, mounted apart from Docker's volumes.

1. On the build host, from a clean checkout of the commit to serve:
   `deploy/public/public.sh build`, then `deploy/public/public.sh save public-images.tar.gz`.
   Copy the archive, `compose.yaml` and `deploy/public/` to the host. Then
   `gunzip -c public-images.tar.gz | docker load` and `deploy/public/public.sh images`; the IDs
   must equal the build host's.
2. Run `init` with `EXULANICA_PUBLIC_HOST`, a public DNS name in lower case (the server's own
   name, or its sslip.io name, never its bare address), `EXULANICA_TLS` (`acme` for a certificate
   from a public authority with no contact, or a contact email; `internal`, Caddy's local
   authority, is accepted only with a loopback edge address, for a rehearsal; `init` refuses
   anything else, and a public authority for a name it cannot certify, because Caddy would fall
   back to its local authority without saying so; every compose call derives the edge's
   certificate line from `EXULANICA_TLS` again with the same checks, so a hand edit is checked too),
   `EXULANICA_EDGE_ADDRESS=0.0.0.0`, `EXULANICA_BACKUP_PATH`, `EXULANICA_CUSTODY_PATH` and the
   guest entry (`EXULANICA_GUEST_ENTRY`, `EXULANICA_GUEST_ENTRY_CODE` for `code`,
   `EXULANICA_GUEST_ENTRIES_PER_DAY`, and optionally `EXULANICA_GUEST_PLAY_SECONDS` and
   `EXULANICA_GUEST_PLAYING_MAXIMUM`), a code of at least 20 characters; only the code's SHA-256
   is written. Then fill in the fuse in
   `public.env`.
3. `read -rs NEBIUS_API_KEY && export NEBIUS_API_KEY`, then `up`, then `issue-authority` with the
   allowance the operator approved, then `guest-policy` with each visitor's figures, then
   `prepare-towns`, run again until every tile reads baked: a visitor's arrival world is made only
   once its tiles are.
4. Install the four units in `deploy/public/` into `/etc/systemd/system`, then
   `systemctl enable --now exulanica-public-watch.timer exulanica-public-preflight.timer`. The watch
   timer runs every minute and the preflight daily; both write to the journal.
5. From another machine, run `scripts/judge_smoke.py` against the public origin with one minted
   token's file and `--rate-limit`. It checks the client, liveness, readiness, a refused and an
   accepted read, the world list and the write limit, and exits 0 when all pass.
6. Run `backup-now`, then confirm in `status` that a backup set was taken and verified.

**Rehearsal checklist.** Run this on a development machine before every deployment:
1. `build` with `EXULANICA_BUILD_PLATFORM` set to the machine's own platform.
2. `init` with `EXULANICA_TLS=internal`, `EXULANICA_EDGE_ADDRESS=127.0.0.1` and ports of the
   machine's own.
3. `mint`, `up`, `issue-authority`, `grant` and `prepare-towns`.
4. `scripts/judge_smoke.py`, with `--cafile` naming the edge's local root
   (`/data/caddy/pki/authorities/local/root.crt` in the edge container).
5. A starter world made and read again after `down` and `up`.
6. `backup-now`.
7. `watch` with the API container paused (`docker pause`, never `docker kill`); it must recreate
   the API on the third failure.
8. `preflight`.
9. `destroy --yes-delete-volumes`.

A rehearsal's plain-HTTP redirect names the standard port, not the one the rehearsal published.

**Limits.** A tile's bake is shared by every world whose tiles it is: if the second bake of a tile
ever differs from the first, the stored tile is marked and reads failed for every copy of that
arrival world, not only the one being baked (migration 0072's rule), until the owner records the
decision to serve its stored first bake (`exulanica-tile-fault clear`, 9.1). A visitor's copy of
an arrival world is made only once its tiles are baked. No off-host copy of the backups
is made, so the loss of the host loses both disks. A
restore has not been timed on the host (D-3). After a restore, reconcile the authority, then set
the guest policy again (`guest-policy`): reconciling a restore, or reauthorizing, ends every live
policy, because the restored database may hold one the operator had replaced or withdrawn, and a
policy change is itself a ledger step, so a restore that lost only that is reconciled too. The process fuse starts again at every restart; the authority does not.
Per-address limits do not bound how many addresses write at once. The edge's access log drops
cookies, the authorization header and a session's CSRF token, and keeps a visitor's address only
to its network (/24, /48); it is kept by size (each container's log, ten files of 10 MB), not
for a stated time.

## 9. Backups and recovery

- **Personal install:** `exulanica-local-db` backs up on every stop and around every upgrade, and
  `verify` proves a backup restores (section 3.2).
- **Installation:** `exulanica-installation` takes backup sets, runs unattended maintenance and
  recovers a lost source (9.1 to 9.4). `compose.yaml` runs its maintenance service and holds the
  operator's restore job behind `--profile recovery`; a composed restore has been timed only on a
  small fixture, not at production size (open item D-3).
- **Restarts:** `restart: unless-stopped` restarts a process that exits, within seconds. Docker and
  Compose do not restart a container whose health check fails; they only mark it unhealthy. And
  any `docker kill`, whatever its signal, marks a container as stopped by hand, after which its
  restart policy no longer applies until it is recreated: never send a running installation a
  signal with `docker kill` to diagnose it. A worker killed with queued work leaves that work
  queued, and the work completes once the worker runs again. A worker's shutdown, lease recovery
  and retry are in [worker operations](derivative-worker-operations.md).

### 9.0 Sizing one host

The request limits are the API's own settings, per API process, with measured defaults (the API's
runtime capacity contract owns them). At those defaults one API process holds up to 58 PostgreSQL
connections (twice its request and upload slots, four stream pollers and two readiness checks),
which fits PostgreSQL's default of 100 beside maintenance and the workers; a second API process
does not. Decoding and upload bodies take about 1.2 GB at the defaults, and each worker process
about 512 MB more. The client proxy buffers request bodies on its container's disk: up to about
10.5 GiB from one address at the installation profiles' cap (5.1.2). These were measured on one 18-core, 64 GiB development machine; a smaller host
is not covered. The composition gives uvicorn `--timeout-graceful-shutdown 10`, so a stop does not
wait for open progress streams.

### 9.1 Installation profiles and facts

An installation declares its profile (`EXULANICA_INSTALLATION_PROFILE`, a file under
`deploy/profiles/`, profile `exulanica.installation-profile/v1`): which of thirteen components it
runs, the reason one it runs cannot work here, the queue bound past which a component is reported
degraded, and its recovery bounds (9.4). `reviewer` is the seeded stack of section 8 and is not a
complete installation: it runs the database, schema, API, client, ingestion and simulation.
`single-host` runs on one host the database, schema, API, client, maintenance, ingestion,
derivatives, pose and scene reconstruction (`pose_scene`), workspace asset preparation
(`preparation`), simulation and comparison. No shipped profile installs material bakes
(`materials`), and only `public` (8.2) installs generated tiles (`generated_tiles`). Where generated
tiles are not installed, the creation read (`GET /worlds/capabilities`) lists a generated town
unavailable (`generated_tiles_not_installed`), because nothing would bake its tiles and it would
never be drawn; a town created by calling the route directly still stays "being built". A material
bake request is refused 409 `materials_not_installed` rather than queued for a worker that does not
run.

`public` is `single-host-server-only` with generated tiles installed (a 900 second queue bound).
`compose.yaml`'s `tile-worker` service runs `exulanica-generated-tile-worker` under the compose
profile `tiles`, from `deploy/installation/tiles.Dockerfile`: the backend image with Node 22's binary
and the tessellator compiled to JavaScript (`tsc --build` of `web/packages/loom-tess`), and no
package manager or dependency. It claims each bake job as `exulanica_app`, in the job's workspace,
for the workspaces it is configured with and those active accounts own. It publishes each bake as
`exulanica_tiles`, which may execute `record_baked_tile_bake` and nothing else (migration 0138,
[security floor](security-floor.md#5-database-roles)); `exulanica-db` checks that role as it
provisions it. Wherever the profile installs generated tiles the worker refuses any wider
publisher, the owner included. Elsewhere it accepts one with a `publisher_not_narrow` warning, so
a development checkout that has not provisioned the role keeps baking.

The function stores a bake only for the bake stage the installation runs: its version and
parameter digest are a schema fact, stated by a migration (`baked_tile_stage`, 0144), and a code
change to the stage comes with a migration stating the next one. A key whose stored row is a bake
of another stage or another tile is refused rather than marked. A tile's bake is listed and reused
only under the current stage; a stored bake of any stage stays reachable by its key. A tile whose
bake is already stored under the current stage queues no job when a world is made, so a world
whose tiles another world shares is drawn at once. A tile whose second bake differed from its first
is never served; the owner may record the decision to serve its stored first bake with
`exulanica-tile-fault clear`, which never changes or deletes the stored tile. `list` names every
fault with what a clearance would serve and what disagreed with it: the stored container's
digest, when that bake ran and its receipt, and the differing bake's digest.
`single-host-server-only` is
the same built without the reconstruction and pose extras, whose workers then report unavailable,
and is what `compose.yaml` and `.env.example` select by default (`EXULANICA_PROFILE`);
`shared-store` keeps its bytes in an S3-compatible bucket, composed by adding
`deploy/installation/compose.shared-store.yaml`, which gives the runtime object-store identity to the
API and workers and the purge identity to maintenance and the restore job alone. A process whose
`EXULANICA_STORE_KIND` differs from its profile's store refuses to start (`store_kind_conflict`): its
bytes would be outside the installation's backups. A profile names processes, not features, and
holds no secret, host or account.

`preparation` may also name its preparers one by one (`preparers`, each by `id@version`, installed
or not, with a reason). The three installation profiles install the static GLB preparer and
declare the character body preparer not installed (`preparer_tool_absent`): it needs a pinned
Blender with its parametric inputs, which no image carries. `compose.yaml` starts the `preparation`
service, `exulanica-asset-preparation` from the backend image, which runs the preparers the profile
installs and nothing else, and refuses to start by name when the profile installs one it cannot run
(`declared_preparer_unavailable`, `declared_preparer_unknown`) or does not install preparation at
all (`preparation_not_installed`). Without a profile, or with a profile that names no preparer, it
runs every registered preparer its host can. The facts report each declared preparer's state, a
capability whose effect names a preparer takes that preparer's state, and maintenance observes the
preparation queue per preparer, so a request for a preparer the installation does not run waits
without making the component `degraded`.

The three installation profiles declare `simulation` installed. An API that plays societies itself
reports it `ready`; one that leaves playback to the `playback-worker` service (5.1.5) reports the
profile's declaration, `configured`, and each world's `host_playback` says whether that process
is running.

Every profile names its restore marker
(`recovery.restore_state_path`), which every process of the installation reads, and
`exulanica-installation init` writes it in state `none` only on a first install, a database with
no applied schema, before the API first starts; a marker missing on an installed database is lost
custody, and both `init` and the API refuse.

A database installed without a profile has never had a marker, and `exulanica-installation init
--adopt` gives it one from the database's own restore record, or refuses with nothing written. No
`restore_control` row and no replay receipt is a database no restore was declared on, and the
marker is `none`. A `complete` row whose replay receipt matches it (the same restore id, checkpoint
id and checkpoint digest) is a finished restore, and the marker is `complete` for that attempt. A
receipt is written in the transaction that completes its replay, so the marker records every
restore the database holds a receipt for as completed, and a restore of any of their checkpoints is
refused as reopening it.

Adopting is for a database that never had a marker. A marker that existed and was lost is restored
from custody instead, its newest copy, because the database does not hold everything the marker did:
a declared recovery's declaration (its receipt keeps only the window), the tombstones a replay left
open, a return to the source in progress, an abandoned attempt, and any completed restore whose
receipt the database no longer holds, such as one completed on a database that was replaced since.
Adopting refuses: a marker already at the profile's path, a database with no applied schema (a
first install runs `init`), a schema older than the restore controls (migrate first), a `sealed`
or `replaying` row (finish that restore first), a `complete` row without a matching receipt, and
receipts with no control row. Adopting cannot tell a database that has served all along from a
backup loaded into it without a replay, because both read the same: running it states that the
database is the installation's live one.

`exulanica.api.installation.installation_facts` answers `exulanica.installation-facts/v1` in process
for the capability projection: each component's state (`not_installed`, `unavailable`, `configured`,
`ready`, `degraded` or `refused`) with a stable reason, the model mode and paid admission, the store,
the restore state and the serving gate, and the installation's identity (profile digest, code
revision, image digests, schema, a digest of which settings are set). Database-derived parts are
at most 5 seconds old. `GET /operations/installation` serves the document to an operator holding
`operations.read`; unauthenticated `/readyz` carries only each component's state and reason. Queue
progress across workspaces comes from the maintenance status file (9.3), because the API's role
cannot see other workspaces' queues; a status older than two export intervals is reported, not
trusted. Paid admission states how model spending is bounded: `process` (one process's ceilings,
started again with it) or `durable`, with each spending authority's state and witness and never an
amount; a durable process with no active authority is `blocked`, `spending_suspended` with the
suspension codes when a restored ledger is behind its witness, so a restore never hands spent
allowance back. It also states this process's own witness directory (`process_witness`): a process
whose directory has no witness directory marker, or which has none, cannot spend under a witnessed
authority and is refused alone (`process_refusal`, such as `witness_directory_mismatch`) while the
authority stays active for every other process. The store section states the profile's store, the kind this process built and that
store's own description (kinds and bucket-check codes, never an endpoint, bucket or credential).
Request capacity is not copied into the facts: `/readyz` states the configured limits and
`GET /operations/capacity` the load, for an operator holding `operations.read`.

### 9.2 Backup sets

A backup set (`exulanica.installation-backup/v1`) is a directory under `EXULANICA_BACKUP_DIRECTORY`,
written in this order, each step checked before the next:

1. The database, dumped in one exported snapshot as `exulanica_backup`, after refusing any table
   that role cannot read; the same dump and manifest a personal install takes.
2. The stored bytes of every namespace the store registry lists (`ContentStores.namespaces()`:
   `blobs`, `tiles`, then each workspace's `materials/<workspace hex>`, and any namespace registered
   later), copied key for key into `EXULANICA_BACKUP_STORE_DIRECTORY` under the same names, each
   re-derived from its bytes as it is written; a set records the sorted list of keys it holds. The
   copy is a host directory whether the live store is local or an object store, and one that lies
   inside the live store, or holds it, is refused.
3. A withdrawal export into `EXULANICA_CUSTODY_DIRECTORY`, taken after the dump's snapshot.
   Every export records its source (the database server and database it came from), and refuses a
   database that lacks a tombstone the newest export of any source holds, or still holds a row whose
   withdrawal that export records as applied, as a restored database that has not replayed does. A
   row the database does not hold at all (a sign-in session no backup carries, or a row made after
   the backup) is honoured. Custody keeps this source's newest three exports, every other source's
   newest one (the one the rule above compares with) and every export a retained backup set names.
4. The manifest, last and digest-bound. It binds the dump's digest and the digest of the dump's
   own manifest, whose roles and memberships a restore acts on; a restore and verification refuse a
   set whose dump or dump manifest is another. A directory without it is not a backup set.

`exulanica-installation verify --backup-set DIR` loads the dump into a scratch PostgreSQL server
and compares its rows with the manifest, and re-hashes every listed object; a missing or damaged
object is refused by name, except one that the newest export in `EXULANICA_CUSTODY_DIRECTORY` names
as a completed purge's target, which maintenance erases from the backup copy (9.3). The maintenance image (`deploy/installation/maintenance.Dockerfile`) carries the
PostgreSQL 18 programs this needs, taken from the database's own image. Backup sets, the backup store and custody must be outside the data
directory, and custody outside the backup directory. No password reaches a program's arguments:
`pg_dump` and `pg_restore` read theirs from a temporary private password file of their own, which
matches any host and port.

The dump carries the definitions of `account_login_attempt` and `account_browser_session` and not
their rows, which hold plaintext sign-in nonces, verifiers and CSRF tokens: a restored installation
asks everyone to sign in again. Nor does it carry the rows of `door_secret` and
`door_redemption_refusal` (migration 0149): a restore voids every door invite and channel credential,
so each world's owner opens their grants again ([door contract](door-contract.md)), and a credential
the door prunes after its retention never leaves an older backup unrestorable. The database itself
keeps every revoked door secret for good (migration 0157), and every sealed restore checkpoint
carries them, with the table's indexes: they grow by 2,400 rows a day on average for a workspace
issuing the most grants the door allows (50 in any 24 hours, 48 secrets each), by at most 4,800 in
any 24 hours (a grant may be given its secrets at any time in its own day), and by a few dozen for
an owner who opens a few grants a day.

`exulanica_backup` is provisioned by `exulanica-db` with `EXULANICA_BACKUP_ROLE_PASSWORD`: BYPASSRLS,
SELECT on every table and sequence (and, by default privilege, on those the owner creates later)
and nothing else, no role membership and no SECURITY DEFINER function. Its read-only default is
defense in depth, not a barrier: a session can lift it, and can then create temporary tables and
large objects, which PostgreSQL grants to every role; the product stores no large object, and
maintenance reports any as `backup_role_incomplete`, with any table the role cannot read. The
credential also allows advisory locks, NOTIFY and changing its own password, and it reads every
row: only the maintenance process receives it, and it is protected as a read-all secret.

### 9.3 Unattended maintenance

`exulanica-installation maintenance --loop` runs one bounded pass at a time: a withdrawal export
when a tombstone or catalogued withdrawal may have changed and at least every export interval, a
purge of at most 500 jobs as `exulanica_purge`, a backup set when the newest is older than the backup
interval, the destruction in the backup store of bytes a completed purge destroyed (unless the live
store holds them again, and only once the newest export names that purge, so verification and a
crash recovery accept exactly the same gaps; the local copy is checked first, so a purge already
erased there costs the live store no request), verification of the newest set, removal of sets older than the retention
bound (the newest is always kept), and the age of the oldest queued item of each component. Each
step's failure is a stable code in `failures`, and the rest of the pass still runs, except that a
failed export skips the backup set and the backup-copy purge, which both depend on it. A database
set aside by a planned restore is reported as `set_aside_database_present` until it is discarded,
and the number of keys restores listed as written after their backups (9.4) is stated as
`objects_not_in_backup_listed`, counted from the listings alone, with no store request. The pass writes
`exulanica.maintenance-status/v1` to `EXULANICA_MAINTENANCE_STATUS_PATH`, which the API reads.

Withdrawn content leaves backups by two bounds: stored bytes within one maintenance pass of their
purge, and database rows when their backup set passes the retention bound.

### 9.4 Recovery

A database restored from a backup taken before a deletion must replay every withdrawal before it
serves. The restore command does that (5.2.8), and the API refuses to serve while a declared
restore is sealed or replaying. Two cases are kept apart
([ADR-0028](adr/0028-a-crash-recovery-replays-a-declared-withdrawal-export.md)):

- **Planned restore**, with the source available: stop every writer, then
  `exulanica-installation restore planned --backup-set DIR --checkpoint FILE` seals a checkpoint,
  writes the profile's marker, loads the set into the target and replays. No withdrawal is lost. On
  one host, `--set-aside` renames the sealed source database instead of needing another server. It
  sets aside only the source itself: before sealing, the target's database must be the source by
  the identity every export records (server and database), and after sealing, sealed for this
  checkpoint; anything else is refused and nothing is renamed. Without `--set-aside`, a target that
  already holds the source's name is refused before anything is sealed. Until the restore
  completes, `restore return-to-source --checkpoint FILE [--set-aside]` abandons it and lets the
  source serve again. Without `--set-aside` it replays into the database
  `EXULANICA_SOURCE_DATABASE_URL` names: it refuses while the source is still set aside, refuses a
  database it cannot reach by name, and replays only into a database sealed for this checkpoint,
  or one in which a return of this attempt already began, its replay begun or committed, so it
  refuses a partial copy that took the source's name and the restore's own copy. With
  `--set-aside` it renames back only a set-aside database sealed for this checkpoint, on the
  target server. Before its replay begins, a return writes a one-off token into the source (as its
  database comment) and records in the marker the database it replays into, by server, oid and
  that token, all of which a rename keeps. A stopped return is resumed by running a return again,
  and only in that database: on one host in either form, and for a source on another server
  without `--set-aside`. A return does not resume a replaying database the marker records no
  return into, and refuses it with "do not drop it", except the restore's own copy under the
  source's name while the source is still set aside, which is this attempt's copy whose replay
  never completed: drop it, then return. A database in which a restore completed under the pending
  attempt, as after a marker was put back from an older copy or a replay committed before its
  marker write, is never offered for dropping. A rerun of the restore, or of a return recorded into
  it, completes the marker from that database without replaying again: it checks that the database
  holds this attempt's complete row and receipt for this checkpoint, reads which of the
  checkpoint's tombstones are still open there into the marker, and verifies. The return token replaces any comment the
  source database had, and writing it needs the database owner or a superuser, so
  `EXULANICA_SOURCE_DATABASE_URL` connects as one of them; another role is refused by name before
  anything is replayed. It replays with the installation's own purge connection and
  stores, so it completes a source on the installation's server; a source on another server fails
  closed (its re-queued purges cannot complete there) and is returned with that server's own purge
  connection and stores. Without `--set-aside` it does not need the target server: one it cannot
  connect to is taken as holding no set-aside source. Once it completes, the set-aside source lacks
  every deletion made since and lies outside every deletion path, so it can never serve again:
  `restore discard-set-aside --checkpoint FILE` drops it: the database under the set-aside name
  found through the marker's record of completed restores, and only while it is sealed for that
  checkpoint (the drop checks the seal, not the identity), so it stays discardable after a later
  restore. The marker records every restore that completes and carries the record through
  every later write, and while it is kept, preparing, resuming or replaying a recorded checkpoint
  again is refused; a lost marker loses that record. A rerun classifies the target before it writes
  the marker. With no attempt pending, a database in which a restore completed is refused as live
  ("do not drop it"); under a pending attempt a row completed under another restore id may be one
  the loaded backup carried, so that database is refused as a possible partial copy of this attempt.
- **Crash recovery**, with the source lost: `exulanica-installation restore declared --backup-set DIR
  --export FILE --declaration FILE` writes the marker first, loads the backup set into an empty
  target, copies its bytes back, migrates and reprovisions, and replays the export under the
  operator's recovery declaration. It refuses when the export is not the newest valid export in
  `EXULANICA_CUSTODY_DIRECTORY`, wherever the file given lies, does not match its digest or
  catalog, is older than the backup set's own export, or ends further before the declared incident
  than the profile's `max_export_lag_seconds`;
  there is no override. A withdrawal made after that export is not recovered, and the marker and the
  restore receipt record the window it fell in. The export names its withdrawal catalog, and a replay
  refuses another release's, so a crash recovery runs on the release the export came from and
  upgrades afterwards. A pending declared recovery is abandoned, for example for a newer export, by
  `restore abandon --export FILE`, once the target holds no database of that name: the marker
  becomes `abandoned`, which still refuses serving, as pending did, is never replayed, and accepts
  a new restore; it keeps the record of completed restores.

Both restores check the set's key list, its dump's digest and the target database's name before
anything else, then write the marker before loading anything, and keep the API refusing until
replay completes. A failed restore is resumed by running the same command again: a pending marker
for the same checkpoint or export resumes that attempt without sealing again, and replays only when
the load had completed. The target is classified first: a database left by this attempt resumes;
an empty database is refused with the instruction to drop it and rerun; a sealed source, a database
replaying a restore no pending marker names, and any other database without a pending attempt are
refused with "do not drop it"; with a pending attempt, another database is refused as a possible
partial copy, to be dropped only if it is that copy. A damaged marker is refused by name. Roles already on the target server are kept, the backup's memberships are
granted only to roles the restore creates, and every role is then reprovisioned. A backup copy may
lack objects that a completed purge erased (9.3); a restore accepts a missing object only when the
checkpoint or export it replays names it as a purge target, and refuses any other. Backup,
verification, restore and the backup-copy purge take every namespace from the store registry, so a
namespace registered later needs no change here; the live purge reaches the namespaces the purge
worker is built over (`PurgeWorker.over`), and a stored kind it cannot reach leaves its tombstone
incomplete, which the replay refuses. A tombstone left incomplete only because a record live in the restored
database still holds the same bytes is the exception: the replay completes, leaves that tombstone
open with its jobs queued for the ordinary purger, as normal operation does, keeps the bytes, and
the command's result lists it with those targets under `tombstones_left_open`. The restore marker is always the one the API reads:
`exulanica-installation restore` refuses to run unless the profile (or `EXULANICA_RESTORE_STATE_PATH`)
declares it, a different `--marker` is refused, and `init` writes it only on a first install or,
with `--adopt`, from an installed database's own restore record (9.1).

Bytes written after the backup stay in a store the restore reuses, and the restored database never
references them, so no tombstone will name them and later backup sets would copy them. A restore
counts them (`objects_not_in_backup`) and lists their keys in a private file beside the marker, and
maintenance states how many keys are listed (9.3). The listing is not a list of what may be removed:
keys are content digests, and the restored installation may hold the same bytes again, when a person
uploads what the restore lost or a derivative is made again, so removing a listed key can destroy
bytes in use. Removing them is OPEN: it needs a check that nothing references a key, which does not
exist. A listing that fails is recorded in the result and never fails a completed restore.

The profile states the recovery point: authored data back to the newest backup set (at most one
`backup_interval_seconds`), withdrawals back to the newest export (at most one
`export_interval_seconds` while maintenance runs). The declared recovery's bound is the profile's
`max_export_lag_seconds`; the restore command's `--max-export-lag-seconds` may lower it, never raise
it. Recovery time is measured, not promised.

| Setting | Read by | Purpose |
| --- | --- | --- |
| `EXULANICA_INSTALLATION_PROFILE` | every process | The profile file |
| `EXULANICA_CODE_REVISION`, `EXULANICA_IMAGE_BACKEND`, `EXULANICA_IMAGE_CLIENT` | API | The identity facts report: a 40-character revision and `sha256:` image digests |
| `EXULANICA_MAINTENANCE_STATUS_PATH` | API, maintenance | The maintenance status file |
| `EXULANICA_BACKUP_DATABASE_URL` | maintenance | The `exulanica_backup` connection |
| `EXULANICA_DATABASE_URL` | maintenance (and every runtime process) | In maintenance, the runtime role `exulanica_app`, for the door's sweep alone: before the pass's backups it settles door grants that ran out in the last seven days with nobody reading them, each in its own workspace, at most 32 a pass, and names in the status file (`door_sweep.stuck`) any it could not settle; without it the sweep is reported not configured and only the door's own reads settle such grants |
| `EXULANICA_BACKUP_DIRECTORY`, `EXULANICA_BACKUP_STORE_DIRECTORY`, `EXULANICA_CUSTODY_DIRECTORY` | maintenance, restore | Backup sets, the stored-byte copy, and withdrawal exports |
| `EXULANICA_RESTORE_MAINTENANCE_URL`, `EXULANICA_RESTORE_DATABASE_URL` | restore | A superuser, as the backup's owner, on the empty target server, and the database the restore creates there |
| `EXULANICA_SOURCE_DATABASE_URL` | restore | The source database, which a planned restore seals and `return-to-source` without `--set-aside` replays into; as its owner or a superuser, since a return writes the database comment |
| `EXULANICA_BACKUP_ROLE_PASSWORD` | `exulanica-db` | The backup role's password |

## 10. Hosting options researched and not built

Before any host was chosen, research compared running the API and PostgreSQL together on a Nebius
Compute virtual machine, a Nebius Serverless endpoint with a co-located database, Nebius Managed
PostgreSQL behind a separate API host, and hosts outside Nebius. It also covered Nebius Object
Storage as the origin for large derived files with an optional edge cache, a static host for the
browser client, cost controls, monitoring for unattended operation, and recovery drills. None of it
is configured or built, and its prices and provider facts have not been checked again. The full
text is at revision 47f9f7d3:
[deployment.md at 47f9f7d3](https://github.com/twinkling-reality/exulanica/blob/47f9f7d3/docs/deployment.md).

Section 8.1's host, quoted from the Nebius compute pricing page
(`docs.nebius.com/compute/resources/pricing`, read 2026-09-29) at the rates it lists from
2026-10-01, before tax: a `cpu-d3` vCPU at $0.015 an hour and memory at $0.0045 per GiB-hour make
`4vcpu-16gb` $0.132 an hour ($3.168 a day) and `2vcpu-8gb` $0.066 an hour ($1.584 a day); a network
SSD at $0.071 per GiB-month makes a 50 GiB disk about $0.12 a day. The page lists no price for a
public IP address, and outbound traffic is not quoted. The pricing documentation states that a
stopped virtual machine's compute is not charged.

## 11. Open items

| # | Item | Resolved by |
| --- | --- | --- |
| D-1 | No test asserts that `/readyz`'s schema check reports a stale schema rather than only a missing one | Writing one |
| D-2 | No one-command redeploy exists | Writing it and running it from a clean shell |
| D-3 | Maintenance takes backup sets and a declared recovery restores one (9.2 to 9.4), but a composed restore has been timed only on one development host with a small fixture, not at production size or on a chosen host | Restoring a production-sized backup set on the chosen host |
| D-5 | The preflight treats an unreachable catalog as a failure, which is right for a deployment step and wrong for a scheduled check | Retry with backoff, and distinguish the two outcomes in the report |
| D-6 | The embedding role has no fallback and no recovery path | Precomputing the vectors a deployment needs, or accepting the single dependency and saying so |
| D-7 | The fallback rule has never run against the live platform | Forcing a primary to fail |
| D-9 | No cloud account, project, region, domain or host is provisioned. Section 8.1 is the recipe for one Nebius AI Cloud virtual machine serving the reviewer stack, and 8.2 the public server's | Provisioning it and running the smoke check against the public address |
| D-13 | `compose.yaml` serves the client and proxies `/api` with a per-address write limit and a body cap (5.1.2), bound to loopback, and has nothing bounding how many addresses write at once. The reviewer stack (8.1) and the public server (8.2) add a TLS edge in front of their client proxies | An edge that bounds concurrent addresses, and a provisioned host (D-9) |

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
from it. Opening a connection per request is small beside the model calls most requests make, and
admission bounds how many a process opens (5.4.3); a request rate or workspace count an order of
magnitude higher is what would change the answer.

### 12.2 No reference counting on `blob`

`blob` is not workspace-scoped, and the purge path answers "does anything still hold these bytes"
with the purge role's cross-workspace read of the holder tables (5.1.1). `purge_releases_bytes`
scans the `artifact` table: there is no index on `artifact.content_sha256` or
`artifact.source_blob_sha256`, and a partial index on the first is the change to make if purge time
matters. A maintained holder count on `blob` is declined because it adds a trigger write to every
capture insert, capture soft-delete, artifact insert and artifact purge. It becomes the right change
if a workspace stops being one user (assumption A-30 in the
[domain and evidence model](domain-and-evidence-model.md)), if the cross-workspace read itself
becomes unacceptable, or if bytes are ever found shared between workspaces.

### 12.3 Poll intervals, and the shape of the queue index

The derivative worker polls every 2 seconds (`--poll-seconds`) and `exulanica-purge` makes one pass
per run; neither cadence is worth changing at one workspace per person. The derivative queue's claim filters on workspace,
kind and state and orders by priority and job id. Migration 0016 installs `job_queue_idx` on
`(workspace_id, kind, priority, job_id) where state = 'queued'`, with `run_after` as a filter:
placing a range predicate ahead of the ordering keys would make PostgreSQL read and sort every
eligible row before `limit 1`.
