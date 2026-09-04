# Deployment

- Status: mixed, labelled per claim. See [README.md](README.md) for the status convention.
- Date: 2026-09-04.
- Relationship to other documents: this expands
  [architecture-overview.md](architecture-overview.md) sections 2, 2.1, 4 and 7 into an operational
  plan. Where a platform fact appears in both, the architecture overview is the source and this
  document does not restate the verification.
  [runtime-verification.md](runtime-verification.md) overrides both on any conflict.

The demonstration has to run without an operator for roughly **46 days** after a release is cut.
This is a single operator project, and that is the longest gap between hands-on attention the
schedule realistically produces. Nobody looks at the application during that window. Every choice in
this document is shaped by that gap rather than by steady-state operations.

---

## 1. What is decided, and what is not

The shape of the deployment is decided. The concrete target is not.

| Question | Status |
| --- | --- |
| Which components exist and what each one does | **DECIDED**, section 2 |
| That the browser client is a static build with no server of its own | **DECIDED**, section 2 |
| That large assets are served from object storage and never from the client bundle | **DECIDED**, section 4 |
| That the database sits in one consistency domain with the API, not in a managed service and not behind a network hop | **DECIDED**, section 3 |
| That the model catalog preflight fails the build on a withdrawn identifier | **DECIDED and implemented**, section 7 |
| That reconstruction never runs in the live request path | **DECIDED**, section 8 |
| Whether the API and database host is a Compute virtual machine or a Serverless endpoint | **Recommendation on record, not locked.** Section 3 and section 10 |
| Which cloud account, project and region placement | **OPEN**, section 10 |
| The domain name | **OPEN**, section 10 |
| Whether the static client host stays on the default choice | **OPEN**, section 10 |
| Who performs the weekly check through the unattended window | **OPEN**, section 9 |
| Whether the health endpoint exists | **DECIDED and implemented.** `/healthz` and `/readyz`, section 6 |
| Whether the redeploy command exists | **OPEN.** Specified in section 9 and not implemented |
| Whether there is a connection pool, a subscriber bound, `blob` reference counting or a decode semaphore | **DECIDED against, on measurement.** Section 12, with the condition that would flip each one |
| How large a host one API process needs, and what it runs out of first | **MEASURED**, section 5.4 |

**The artefacts exist. Nothing has been provisioned.** The distinction is the whole of this
section and it is worth stating precisely, because "there is a Dockerfile" and "there is a
deployment" are different facts and only the first one is true.

What exists in the repository, and is checked by `tests/test_deployment.py`:

*   `Dockerfile`, one reviewed recipe with dependency-specific builds. The default serves the API,
    migrations and pose worker; Compose selects the reconstruction extra for the MoGe derivative
    worker. Both are non-root, have no apt packages, and use liveness on `/healthz`, never
    readiness.
*   `.dockerignore`, an allowlist rather than a denylist, because `credentials.py` walks up from
    the working directory looking for a `.env` and a denylist is one forgotten line away from an
    image that carries a credential.
*   `compose.yaml`, a local composition against `pgvector/pgvector:0.8.6-pg18`, which is the
    documented target matched exactly.
*   `.github/workflows/check.yml`, running ruff, the import contracts, pytest with
    `EXULANICA_REQUIRE_POSTGRES=1`, the web workspace's `pnpm check`, and an image build.

**What is still open, and it is the part that needs a person.** No cloud account, no project, no
region, no domain, no registry and no host. Every one of those is a decision rather than a task,
and nothing in this repository names one: `tests/test_deployment.py` asserts that no artefact
carries a hostname or an account identifier, so a value typed in by accident fails the build.

**The image is built and was run. 2026-08-29, 222 MB.** `docker build .` completes, and the built
image was exercised rather than only weighed:

*   `uvicorn` serves. The container's own `HEALTHCHECK` reaches `/healthz` and gets 200.
*   `exulanica-ingest --help` and `exulanica-db --help` both ran in that image. The current image also
    carries `exulanica-derivative-worker`; its import and command contract are checked in the suite.
*   `POST /intake` accepted a photograph through the container and returned 202, and the
    derivative worker inside it drained the queue: intake and rendition ran, and vision did not,
    because no model credential was passed. That is the correct behaviour and the honest half of
    the test, since a stage reported as done that never ran is the failure this project is
    written against.
*   With a connection string naming a role that does not exist, the container **refuses to start**
    and says which role, rather than starting and failing on the first request. That is section
    5.3's "fail closed at startup", observed rather than asserted.

**CORRECTED and VERIFIED 2026-09-04.** The current default `linux/amd64` image is 428,102,510
bytes, retains the non-root `exulanica` user, excludes torch, and imports pycolmap 4.2.0 plus the
scene worker. The 222 MB measurement above describes the earlier pre-pose image. Compose now
builds the derivative worker from the same recipe with the reconstruction extra, configures MoGe,
and keeps its checkpoint cache on the media volume. A clean `linux/amd64` build of that locked
target completed at 5,483,041,226 bytes and retained the same user. Under Docker x86 emulation it
imported torch 2.13.0+cu130, `utils3d_moge`, `MoGeModel`, and the production worker; both pycolmap
and torch correctly reported CUDA unavailable on the non-GPU host. This verifies the images and
import closures, not model inference: no chosen production host or authorized dense capture was
available, and the 1.3 GB checkpoint was neither fetched nor exercised in this verification.

**VERIFIED 2026-09-04, actual depth forward path.** A later current `linux/amd64` depth image at
commit `4c8a87778af24966bf896906f3ee7d5d323c86ac` is 5,483,317,747 bytes and has image ID
`sha256:b6fe271f7ebc714268806c5513b63453979cc45d5b2445183b56b5e07f479d99`.
The non-root image loaded `Ruicheng/moge-2-vitl` at exact revision
`39c4d5e957afe587e04eec59dc2bcc3be5ecd968` from a read-only cache with network loading disabled,
then executed the production `MoGeDepthModel` adapter on one exact 800 by 600 synthetic campaign
frame. It produced 196,608 points at the production 512 by 384 model size, with 196,583 valid
points, a metric output flag, and a 39.693069 degree vertical field of view. The run used Torch
2.13.0+cu130 on CPU because CUDA was unavailable. Under Apple Silicon instruction emulation it
took 200.25 seconds to load and 93.17 seconds to infer, which is compatibility evidence and not a
production-host performance result. The digest-bound machine record is
[`evaluation/2026-09-04-linux-amd64-depth-forward.json`](evaluation/2026-09-04-linux-amd64-depth-forward.json).

---

## 2. Topology

Five places where code or data lives, and one boundary that matters more than the rest.

```
  Browser (user)
        |
        |  static HTML, JS, CSS                     large derived assets
        |  over HTTPS                               over HTTPS, cacheable
        v                                                    |
  Static host  ------------------------------------>  Edge cache (optional)
        |                                                    |
        |  JSON API calls                                    v
        |                                          Nebius Object Storage
        v                                          (eu-north1, versioned,
  API process ----------------+                     anonymous read on a
  (single host)               |                     narrow prefix)
        |                     |
        |  local socket       |  HTTPS
        v                     v
  PostgreSQL 18          Nebius Token Factory
  + pgvector             (reasoning, vision, embeddings)
  (same host)                 |
                              +--> Tavily (opt-in public entity lookup)

  Out of band, never in a request:
  Nebius Serverless Jobs  -->  ingest, perception, reconstruction
                               write to Object Storage and PostgreSQL, then terminate
```

| Concern | Runs on | Why there |
| --- | --- | --- |
| Browser client | Static host (Vercel Hobby by default), no server side rendering, no serverless functions | The client is a build artifact. Giving it a runtime would add a component that can die during the unattended window in exchange for nothing |
| Derived assets: point maps, splat scenes, image derivatives | Nebius Object Storage, eu-north1, Intelligent class | Section 4 |
| API and PostgreSQL 18 with pgvector | One host, database as a local process, restart policy, nightly dump to Object Storage | Section 3 |
| Asynchronous ingest and perception | Nebius Serverless Jobs, self terminating, per second billing | Failure is retryable and idempotent, which is what makes a self terminating job the right shape |
| Reconstruction (structure from motion plus splat or point map training) | Nebius Serverless Job on a GPU flavour, preemptible, checkpointed | Minutes to hours. **Never in the live path.** Scenes are reconstructed once, ahead of deployment, and the results are static assets |
| Reasoning, vision and embedding models | Nebius Token Factory, global base URL only | The identifiers and their fallbacks are in `exulanica/models/models.manifest.json` |
| Public entity lookup | Tavily, opt in, server constructed query only | Queries are built on the server and never carry corpus content |

**The boundary that matters** is between work that must answer inside a request and work that must
not. Reconstruction, perception and batch ingest take minutes to hours. They run as jobs that
terminate. A job failure is retryable, a database failure is not, and that asymmetry is the only
reason a boundary is drawn at all. Everything in the request path is one process talking to a local
database.

**What one API process demands of the database, measured rather than reasoned about.** A
connection is opened per request by a yield dependency (`scoped_connection` and
`readonly_connection` in `exulanica/api/dependencies.py`) and held for that request's whole
duration. There is no pool. So the number of backends one process wants is the number of
requests currently in flight past that dependency, plus one for each of the two worker threads.

**It is not capped by the ASGI threadpool, and assuming it was is the mistake to avoid.** A
request that is waiting for a worker thread still owns its connection. Measured against the real
application on this cluster: 48 concurrent formation streams held **48** backends while the
threadpool was 40, and the count tracked N exactly at 8, 39, 40 and 48. The cluster is
`max_connections = 100` with `superuser_reserved_connections = 3`, so 97 are usable, and nothing
in this application limits in-flight requests. `uvicorn --limit-concurrency` is the only lever
that would, and nothing sets it. Section 5.4 carries the arithmetic and what to do about it.

**Region pinning.** All GPU work goes to eu-north1, because that is where the GPU quota is non zero.
Token Factory reports its public endpoints as global and warns that the processing location can
change without notice, so only the global base URL is ever used and nothing in the codebase branches
on a region string.

---

## 3. Where the database runs, and why

### 3.1 The decision

**The database runs as a process on the same host as the API, on a small general purpose virtual
machine with a network attached SSD volume and a restart policy, with a nightly dump to object
storage.** It is not a managed service and it is not behind a network hop.

Three separate arguments arrive at the same place, and any one of them would be sufficient.

**Argument one: deletion needs one consistency domain.** This is the reason that is about
correctness rather than money. An embedding derived from a photograph is not a pointer to that
photograph, it is a lossy copy of its contents. When a subject withdraws consent, the embedding has
to be purged in the same transaction as the interval it was derived from. Two storage systems means
a two phase delete, and a two phase delete can be left half done: the source is gone, the derived
vector is not, and the system is now holding biometric data whose provenance record no longer
exists. One PostgreSQL, with embeddings in a table partitioned by workspace, makes that failure mode
unrepresentable rather than merely tested for. This argument also rules out a separate vector
database and a separate graph database, and it is worked through in
[architecture-overview.md](architecture-overview.md) section 3.1.

**Argument two: recovery behaviour across 46 unattended days.** The alternative placement, a
container co-located with the API on a Serverless endpoint, scores marginally better on platform
alignment. It also puts the database on the least reliable component in the stack. The platform
terms for Serverless AI state that there is no service level provided and that it "does not provide
automatic retry, recovery, or redundancy mechanisms", and that "infrastructure failures may result
in workload failure with no automatic recovery". Typical endpoint lifetime is documented as hours to
days. Against a 46 day unattended window that is the wrong component to hold the only copy of the
data. Volume mounting is documented for Serverless **jobs** and is undocumented for endpoints, so the
endpoint variant additionally rests on an undocumented assumption about where the data would even
live.

**Argument three: cost, which turns out not to be a tradeoff at all.** Serverless AI has no pricing
of its own and applies Compute pricing, so a `2vcpu-8gb` shape costs the same either way, about
$35.71 per month. The managed database option is the expensive one: a documented `4vcpu-16gb`
example at $0.28 per hour is roughly $204 per month, about **+$755 across the project period, for a
database that holds under a gigabyte**. That is more than the entire expected AI inference spend, for
a sub-gigabyte database on a single tenant demonstration. Section 8 records it as a named trap for
exactly that reason.

The platform constraint is satisfied identically under both placements, because a Compute virtual
machine is still Nebius AI Cloud. Serverless **Jobs** are retained for reconstruction, perception and
batch ingest, which is where a self terminating per second billing model is a genuine fit and where
failure is retryable, and that use also captures the platform alignment benefit in the one place
where it costs nothing.

### 3.2 The disagreement, preserved

The research streams disagreed about this and the disagreement is real. One stream recommended the
Serverless endpoint placement on platform alignment grounds. That recommendation is not
unreasonable, it is optimising a different variable: alignment with a stated platform preference at
deployment time, rather than survival across an unattended window. This document optimises for
survival. The reasoning is recorded rather than the conclusion alone, so that a reader who weighs
those variables differently can see exactly where they would diverge.

**ASSUMPTION.** That a preview grade service can be relied on for the unattended window at all. This is
being settled by running a canary endpoint continuously and logging every restart, failure and
unexplained outage. That experiment quantifies how right the co-located placement is; it does not
decide it, because arguments one and three stand regardless of the answer.

### 3.3 Rejected alternatives outside Nebius

| Alternative | Why rejected |
| --- | --- |
| Render free tier, whose web services spin down after 15 minutes idle and whose free PostgreSQL expires 30 days after creation | **VERIFIED** and fatal against a 46 day unattended window. The database would expire 30 days in, with nobody present to notice, and the application would be dead before a user ever loaded the page |
| Fly.io, technically fine and cheap | Not Nebius. The project constraint is that the system runs on Nebius Token Factory or Nebius AI Cloud, and that constraint is not negotiable. Kept as an unused break-glass configuration only |
| Cloudflare R2 as the asset origin | Free egress would save roughly $2 to $10 across the project. Rejected because keeping the origin on Nebius keeps the platform constraint literally true. An edge cache in front of the Nebius origin is compatible with this and is recommended |

---

## 4. Static assets and large derived files

### 4.1 What is actually being served

The heavy assets are reconstructed scene data. The delivery format is **streamed SOG**, which is a
`meta.json` manifest plus lossless WebP images, **VERIFIED** as typically 15 to 20 times smaller
than an equivalent PLY and decoded by the browser's native WebP decoder rather than by a per element
JavaScript parse. PLY is a build time archive and is never shipped to a browser. `.spz` is the
interchange format.

Scale, from the renderer measurements in
[adr/0003-renderer-selection.md](adr/0003-renderer-selection.md), taken on the machine that will run
the demonstration:

| Scene load | Peak browser heap | Note |
| --- | --- | --- |
| 3 islands at 1M points | 39 to 75 MB depending on binding | Comfortable |
| 3 islands at 4M points | 137 MB on the three.js binding | The selected renderer uses roughly 1.9x the heap of the measured alternative, so island residency matters more, not less |

The consequence for delivery is that **not every island can be resident at once**, so assets are
requested per island as the camera approaches, and distant islands are served at a lower detail rung.
That is a streaming problem, and streaming is what the rest of this section is about.

### 4.2 Why assets never go in the client bundle

**VERIFIED:** the current default static host, Vercel Hobby, caps a static upload at 100 MB and a
build at 45 minutes. A single scene at full density exceeds the first cap on its own, and putting scene data
through a build step would put it against the second.

More fundamentally, scene assets have a different lifecycle from the client code. Code changes when
the application changes. A reconstructed scene changes when it is re-reconstructed, which during the
unattended window is never. Coupling them means every asset change forces a client redeploy and every
client redeploy re-uploads hundreds of megabytes. They are separated because they change at
different rates.

### 4.3 The origin

Nebius Object Storage, eu-north1, Intelligent storage class, with anonymous read granted on a narrow
prefix.

Four platform facts constrain the design, all **VERIFIED** against the object storage compatibility
documentation and quoted in [architecture-overview.md](architecture-overview.md) section 4:

1. **Anonymous public read exists, but not through S3 `Principal` syntax.** It is granted by a bucket
   policy rule using `"anonymous": {}` with a role limited to `storage.viewer`,
   `storage.object-viewer` or `storage.object-lister`, at most 10 rules per bucket and 10 paths per
   rule. Every S3 tutorial for this step is wrong, and the 10 path limit is a real design constraint:
   the public prefix has to be planned, not accumulated.
2. **`GetObject` and therefore HTTP `Range` are supported.** So are `PutBucketCORS`, versioning,
   lifecycle rules and full multipart upload.
3. **Static website hosting is not supported.** Neither are object ACLs, S3 Select, replication,
   event notifications, bucket inventory, Object Ownership, or write once read many retention. The
   bucket is an origin, not a site, and nothing may be designed around an event notification firing.
4. **ETag is not always an MD5 digest.** Integrity checks use the `X-Amz-Checksum-*` headers. An
   upload verification that compares ETags will produce false failures.

**Bucket setup, in order, and the order matters.** Enable versioning **at bucket creation time**.
Enabling it on an existing bucket takes up to 15 minutes to propagate, and during that window a
bucket that appears versioned is not yet protected. Once enabled, versioning can only be suspended
and never disabled, so this is a one way door taken deliberately.

**Write path.** Originals are written under content addressed keys, the SHA-256 of the original
bytes. The runtime service account is granted write and read and is **denied** `DeleteObject` and
`DeleteObjectVersion` by bucket policy. Deletion, when a person requests it, runs through a separate
privileged path that the request path cannot reach. This is deliberately asymmetric: accidental or
injected deletion is impossible from the request path, while intentional deletion remains real.

**The tension, stated rather than hidden.** Versioning plus delete denial makes genuine deletion
harder, not easier. The deletion design carries that weight, and the required wording carries it
too: this arrangement is **append-only by policy**, which is exactly as strong as the bucket policy.
It is not immutable, not write once read many, and not tamper proof. The platform provides no
guarantee that a sufficiently privileged actor cannot delete a version, and an overclaim here would
discount every other claim this project makes.

### 4.4 Caching, and what makes a CDN safe here

Content addressing is what turns caching from a risk into a free win. A key whose name is the hash
of its contents can never have different contents, so it can be cached forever by anything.

| Object class | Key shape | `Cache-Control` | Reasoning |
| --- | --- | --- | --- |
| Scene payloads: WebP planes, `.spz`, image derivatives | Content addressed, SHA-256 of the bytes | `public, max-age=31536000, immutable` | The key changes when the content changes. There is no such thing as a stale hit |
| Scene manifest (`meta.json`) | Stable path per scene | Short max age, revalidated | This is the mutable pointer that names the immutable payloads. It is the only object whose freshness matters |
| Client bundle | Handled by the static host's own fingerprinting | Host default | Not served from object storage |

**Cross origin configuration.** The client is served from one origin and the assets from another, so
the bucket needs a CORS configuration allowing `GET` and `HEAD` from the client origin, and it must
expose the headers the loader reads, including `Content-Range` and the checksum headers if integrity
is verified client side. `PutBucketCORS` is supported. This is a common first deployment failure:
everything works locally, then every asset request fails in the browser with an opaque CORS error.

**Edge cache.** An optional Cloudflare cache in front of the Nebius origin is recommended, specifically
because users may be a long way from eu-north1 and the first impression of the application is how
fast the first island appears. The origin stays on Nebius. The cache is a proxy, not a second source
of truth, and the application must work correctly with the cache absent.

### 4.5 Range requests, described accurately

`GetObject` support means HTTP `Range` works against the origin, and the design keeps that available
deliberately. What it is worth is narrower than it sounds, and it is worth saying so rather than
listing "range requests" as a feature.

- **Where range genuinely helps:** resumable transfer of the large archival objects (`.spz` and PLY)
  during operational work, and any partial read of a large single file container.
- **Where it does not:** the primary browser path. Streamed SOG is a manifest plus a set of WebP
  images, and the loader fetches each image as a whole object. The size win comes from the format
  being 15 to 20 times smaller than PLY and decoding natively, not from byte ranges. Many small
  cacheable objects and byte ranges into one large object are two different solutions to the same
  problem, and this design took the first.
- **What the edge cache does to it:** a cache in front of the origin must be configured to handle
  range requests correctly or to pass them through. A cache that silently collapses a range request
  into a full object fetch turns a resumable download into a repeated one.

**OPEN.** Whether the renderer's SOG loader issues range requests at all has not been observed. It
is answered by loading a scene with the network panel open and reading the request list. Until that
is done, no claim is made here about range requests being on the browser path.

---

## 5. Environment configuration

### 5.1 What exists today

`.env.example` is committed, `.env` is ignored, and the current variables are:

| Variable | Purpose | Consumed by |
| --- | --- | --- |
| `EXULANICA_DATABASE_URL` | **The connection string the API, ingest command and derivative worker open.** The API and worker must use a non-owner role such as `exulanica_app`; startup refuses a superuser, BYPASSRLS role, or owner of an RLS table. No default: `Database.from_env` raises rather than connecting somewhere nobody chose. | `exulanica/db/session.py` and `exulanica/db/roles.py`. The one-shot migration service deliberately uses the bootstrap owner URL instead |
| `NEBIUS_API_KEY` | Bearer credential for Token Factory | The model client. Named in `models.manifest.json` as `api_key_env`, so even the environment variable name is manifest data rather than a literal in code |
| `TAVILY_API_KEY` | Credential for the public entity lookup | The lookup path only. The feature is opt in and is on the cut list if its egress gate does not hold |
| `EXULANICA_TEST_DATABASE_URL` | Points the database backed tests at a live PostgreSQL 18 server | Tests only. Unset means those tests skip, which is why the suite runs without a database. |
| `EXULANICA_DATA_DIR` | Where the content addressed store lives | The API and the ingest command must agree on it, or a citation resolves against a store the bytes are not in. Defaults to `.exulanica/local`. It does not look at `.orimera/`. |
| `EXULANICA_API_TOKENS` | Bearer token to workspace grant | No default, because a default would be a credential in a repository |
| `EXULANICA_READONLY_DATABASE_URL` | The Selection executor's role | Optional, and `/readyz` says so when it is absent |
| `EXULANICA_DERIVATIVE_WORKER` | Whether this process drains what `POST /intake` queues | Defaults to **on**. Off is for an instance that leaves the queue to somebody else, and `/readyz` reports which it is: a queue nobody drains and a queue drained elsewhere look identical from outside |
| `EXULANICA_WORKSPACE_IDS` | Comma-separated UUIDs the dedicated derivative worker is authorised to drain | Required by the worker command unless one or more `--workspace` flags are supplied. An empty set is a startup failure, not a healthy idle process |
| `EXULANICA_DEPTH_MODEL` | Selects the production depth implementation | Compose sets `moge` on the derivative worker. Other processes leave it unavailable |
| `EXULANICA_DEPTH_MODEL_ID` | Reviewed MoGe repository identifier | Defaults to `Ruicheng/moge-2-vitl`; changing it changes the point-map artifact binding |
| `EXULANICA_DEPTH_MODEL_REVISION` | Full Git commit for the MoGe checkpoint | Defaults to the measured `39c4d5e957afe587e04eec59dc2bcc3be5ecd968`; mutable branches and tags are refused |
| `EXULANICA_DEPTH_DEVICE` | Optional torch device such as `cuda`, `mps`, or `cpu` | The derivative worker; when absent it selects MPS, then CUDA, then CPU |
| `EXULANICA_CODE_REVISION` | Exact 40-character source revision recorded in every production pose manifest | Required by `exulanica-scene-worker`; no inferred checkout or mutable default is accepted |
| `EXULANICA_POSE_RUNTIME_IMAGE` | Digest-pinned image reference recorded in every production pose manifest | Required by `exulanica-scene-worker`; a mutable tag does not provide complete provenance |
| `EXULANICA_APP_ROLE_PASSWORD`, `EXULANICA_EXECUTOR_ROLE_PASSWORD`, `EXULANICA_PURGE_ROLE_PASSWORD` | Passwords for the three roles `exulanica-db` provisions | Optional. Set only when supplied, because a deployment authenticating by certificate or by peer has none, and inventing one would create a credential nobody asked for |
| `EXULANICA_PURGE_DATABASE_URL` | The connection `exulanica-purge` uses | No default and **no fallback to the writer**. The purge role holds a cross-workspace read the runtime role must never have, and the runtime role holds writes the purger must never need. Running as the wrong one either destroys another tenant's photograph or cannot tell that it would |

### 5.1.1 The three roles, and why the purger has its own

`exulanica-db` provisions all three in the one correct order, after the migrations.

| Role | Holds | Why it is separate |
| --- | --- | --- |
| `exulanica_app` | select, insert, update. No delete anywhere. Select only on `predicate` and `schema_migrations` | Row-level security is inert for an owner, and a runtime that could update the vocabulary could disarm the rule that stops a model writing a person's name |
| `exulanica_ro` | select, and nothing else | The Selection executor runs a plan derived from model output. It must not be able to write whatever happened upstream of it |
| `exulanica_purge` | A **cross-workspace read** of the narrow holder columns on `capture`, `artifact`, `reconstruction_scene_member`, and `person_derivative_dependency`; update of purge markers on `blob` and `artifact`; queue and completion updates; **DELETE on `embedding` only** | Stored bytes may be shared across workspaces, so the destroy decision needs every holder. A person vector has no harmless stub representation, so the dedicated purger removes that row while every other table remains outside its DELETE authority |

Every UPDATE in that row is column by column, and a review measured what the full-table version
bought: this role could push a tombstone's `effective_at` a year out, which makes it stop blocking
derivatives and reopens the leak migration 0011 closed, and could set `purge_completed_at` over a
photograph still on disk. Neither table carries an UPDATE trigger, so the grant was the only thing
standing there.

**`EXULANICA_PURGE_DATABASE_URL` is checked, not trusted.** It is a connection string and says
nothing about which role is behind it. `exulanica-purge` asks the database for `current_user` and
whether the cross-workspace policy applies to it, and **refuses to destroy anything** when it does
not, naming the role. Pointed at the writer, it used to purge silently and narrowly: one object
destroyed, the tombstone recorded complete, and another workspace's live photograph gone.

The purge role's UPDATE is still filtered by `ws_isolation`, so it reads across tenants and writes
within one. That asymmetry is the whole of the grant.

### 5.1.2 The request body bound, which the application alone owns today

`POST /intake` is multipart, and **the body is received and parsed before any route function and
before any dependency runs**, so it is parsed before authentication: an anonymous request has
already had its parts spooled to temporary files by the time the bearer token is looked at.
Starlette's `max_part_size` bounds non-file parts only; file parts are unbounded there. So the
checks inside the route bound what reaches the object store and the database, which is what they
exist for, and they cannot bound what reaches the disk.

`exulanica/api/body_limit.py` is pure ASGI middleware, so it is upstream of all of that, and it
applies two bounds:

- a declared `Content-Length` over 512 MiB is refused before a byte is read;
- a request that declares no length, which is what `Transfer-Encoding: chunked` produces, is
  **counted as it arrives** and cut off the moment the running total crosses the limit. The
  overshoot is one chunk rather than the whole body.

The second is what makes the first more than a courtesy: without it, omitting one header walks
past the whole thing.

**Today `body_limit.py` is the whole bound, and there is nothing in front of it to configure.**
D-13 records that the composition has no reverse proxy and no static client host: `compose.yaml`
publishes uvicorn's own port and there is no service in front of it. So the two bounds above are
not a second line of defence behind a proxy's, they are the only line, and the paragraph that
used to sit here read as though a proxy were already part of the deployment.

When D-9 picks a host, whatever terminates TLS should also carry a body size limit:
`client_max_body_size` on nginx, `proxy-body-size` on an ingress. A proxy refuses before the
application is involved at all, which is better than refusing one chunk in, and it is the bound
that still applies when the application itself is the thing under load. **There is nothing to
build for that until D-9 is answered**, because the setting belongs to a component nobody has
chosen yet. It is listed here so the choice comes with the setting attached rather than being
discovered afterwards.

Everything above was read against the code rather than remembered. `MAX_BODY_BYTES` is
`512 * 1024 * 1024`; `BodyLimit.__call__` refuses a declared length over it before calling the
application and wraps `receive` otherwise; `_counted` raises `BodyTooLarge` the moment the
running total crosses the limit and reads nothing further. Starlette 1.6.0's `MultiPartParser`
applies `max_part_size` inside `on_part_data` only when `self._current_part.file is None`, so
file parts really are unbounded there, and the route's own `MAX_PART_BYTES` check at
`exulanica/api/routes/intake.py` runs on `upload.file.read(...)`, which is a part already spooled.
Authentication really is a dependency: `current_session` in `exulanica/api/dependencies.py` is
resolved by `Depends`, and FastAPI resolves dependencies after it has read and parsed the body.

### 5.1.3 Runtime row-level security is active and checked

`compose.yaml` now keeps the bootstrap owner URL in the one-shot `migrate` service. The API,
dedicated derivative worker and reconstruction-scene worker receive `exulanica_app`; the Selection
executor receives `exulanica_ro`.
This order matters: migrate as the owner, provision the roles, then start runtime containers with
credentials that own no table and hold neither SUPERUSER nor BYPASSRLS.

The connection string remains the deployment choice, but it is no longer trusted as proof of the
role behind it. Production startup queries `pg_roles` and the current schema and refuses to serve or
drain when the current role is a superuser, has BYPASSRLS, or owns any row-level-security table.
`tests/test_row_level_security.py` exercises both directions against PostgreSQL: the application
role starts and cannot see another workspace, while the bootstrap owner is rejected. The same
check runs in the API lifespan and the dedicated worker command before either accepts work.

There are now fifty-seven workspace-keyed FORCE RLS tables. The package-export receipt is
append-only and scoped by the same session workspace as the protected world state whose Merkle
root it records. Migration 0029 adds four reconstruction privacy tables under the same enforced
workspace policy. Their authorization, screening, exact-set admission, and admission membership
records are append-only so a later runtime write cannot rewrite why geometry was permitted.


### 5.2 What a deployment additionally needs

**PROPOSED.** None of these is read by code in this repository, because the paths that would read
them are not written: object storage is still a local directory under `EXULANICA_DATA_DIR`, and
there is no reverse proxy or static host to configure origins on. They are listed so that the
shape is settled before the code is written.

This section used to open by saying the *service* that would read them did not exist, and to list
a `DATABASE_URL` as its first row. Both were stale. The service exists, and the variable it reads
is `EXULANICA_DATABASE_URL`, which is now section 5.1's first row and was documented nowhere at all
while a name nothing reads sat here.

| Variable | Purpose | Notes |
| --- | --- | --- |
| `EXULANICA_OBJECT_STORE_ENDPOINT`, `_BUCKET`, `_ACCESS_KEY`, `_SECRET_KEY` | Object storage write path | The runtime credential is the delete denied service account, never an administrative one |
| `EXULANICA_PUBLIC_ASSET_BASE_URL` | The base the client is told to fetch assets from | Points at the edge cache when one exists and at the origin otherwise. Changing it must not require a rebuild of anything but the client |
| `EXULANICA_ALLOWED_ORIGINS` | Cross origin allowlist for the API | Explicit list, never a wildcard |
| `EXULANICA_ENV` | `development`, `staging` or `production` | Selects log verbosity and whether developer surfaces are reachable |

### 5.3 Rules

- **No secret ever reaches the browser.** The Token Factory key and the Tavily key are server side
  only. The client is given public URLs and nothing else. Any design where the browser calls Token
  Factory directly is rejected outright, because a credential in a static bundle is a published
  credential.
- **Fail closed at startup.** A missing required variable makes the process refuse to start, with the
  variable named in the error. A service that starts and then fails on the first request during
  the unattended window is strictly worse than one that never came up, because the monitoring in
  section 9 would have caught the second.
- **Model identifiers are not configuration.** They live in `models.manifest.json` and are not
  overridable by environment variable. Changing an identifier is required to bump `pipeline_version`,
  which is an input to the response cache key, and an environment override would let an identifier
  change without that bump. A cached answer that outlived the model that produced it is a correctness
  bug wearing a cost saving's coat.
- **Secrets are not committed and are not baked into images.** They are injected at run time.

### 5.4 What one instance runs out of, and in which order

None of these is an environment variable, which is exactly why they are written down. They are
properties of the composition that a deployment inherits by default, and every number below was
measured on this machine against this repository rather than read out of a library.

#### 5.4.1 The ASGI threadpool is 40, and nothing here chose it

`anyio.to_thread.current_default_thread_limiter().total_tokens` is 40 (anyio 4.14.2, a
hard-coded default). **Not one of the 23 route handlers in `exulanica/api/routes/` is `async def`**,
so every request occupies one of those 40 worker threads for as long as it runs.

Measured against uvicorn rather than read: 120 concurrent requests to a synchronous handler ran
**40 at a time across 40 distinct threads**, 0 errors. There is no uvicorn flag for it
(`--workers` is processes, `--limit-concurrency` caps connections), and the only place a
deployment could change it is `anyio.to_thread.current_default_thread_limiter().total_tokens`
inside the application's own lifespan. Nothing sets it today.

#### 5.4.2 A formation stream costs one thread and one backend, and the cliff is at 40

`exulanica/api/routes/formation.py` says a subscriber costs a thread. It is now measured, against
the real application on a real database, with the deployment's own command
(`uvicorn --factory exulanica.api.app:create_app`, one process, no flags):

| Concurrent streams | Backends held | Probe pairs completed | `GET /healthz` median | worst |
| --- | --- | --- | --- | --- |
| 8 | 8 | 1228 in 6 s | 1 ms | 3 ms |
| 39 | 39 | 1207 in 8 s | 1 ms | 1493 ms |
| **40** | **40** | **1 in 8 s** | **11,465 ms** | 11,465 ms |
| 48 | 48 | 1 in 5 s | 13,566 ms | 13,566 ms |

Three things to take from that table, and only the first is the obvious one.

**It is a cliff, not a slope, and it sits exactly at the threadpool size.** One extra subscriber
takes a healthy instance from 1207 completed request pairs in eight seconds to one. The worst
case past the cliff is about 14 seconds, which is `_POLL_SECONDS x _HEARTBEAT_EVERY`: once every
token is held, the heartbeat period is what sets the service rate.

**`/healthz` starves with everything else**, because it is a synchronous handler on the same
limiter. The container's own `HEALTHCHECK` runs `urlopen(..., timeout=2)` inside a Docker
`--timeout=3s`, so the operative threshold is two seconds, and a saturated instance exceeds it by
five times. Three failures thirty seconds apart restart the container and kill every stream,
including the ones that were working. That consequence is arithmetic over the measured latency
and the Dockerfile; **no container was built or run to observe the restart**, and it is stated
here as a deduction rather than as an observation.

**A vanished browser keeps its slot for up to a heartbeat.** Sixteen clients aborted at once:
all sixteen backends were still held at t+10.1 s and gone by t+12.6 s. The generator only notices
a disconnect when it next tries to yield.

**No subscriber bound is implemented, deliberately.** One was proposed as
`_MAX_SUBSCRIBERS = 8` and declined for two measured reasons. The number 8 is not derived from
anything in the table above, which says the boundary is 40 and that 39 is indistinguishable from
1. And the counter that would enforce it leaks: `stream()` would increment before constructing
the `StreamingResponse`, but `_events` is a generator function, so its `finally` never runs on
any path where the response is built and never iterated. Each such request would consume a slot
permanently, and after eight of them every watcher is refused with no stream open at all. If a
bound is wanted, the honest lever is `uvicorn --limit-concurrency`, which caps in-flight requests
where they are actually counted.

#### 5.4.3 Connection slots, which are what actually runs out

`max_connections = 100` and `superuser_reserved_connections = 3` on the documented target, so 97
are usable by a role that is not a superuser. Section 5.1.3 records that every runtime process is
now such a role, leaving the three reserved slots available to an administrator. One API process
holds one backend per in-flight request past its connection dependency. The dedicated derivative
worker and purge worker use their own process connections. **The threadpool does not cap
this**: 48 streams held 48 backends against a 40-thread pool, measured. So the real ceiling for a
single-process deployment is about 95 concurrent connection-holding requests, and two API
processes against one cluster share those 97.

An idle connection is cheap to keep and cheap to make. Opening one costs a median of 1.270 ms
over the local unix socket this topology uses and 1.285 ms over TCP loopback, 300 samples each on
a quiet cluster. Section 12.1 is why there is no pool.

#### 5.4.4 Decode memory: the term that sizes the box

One photograph at `MAX_PIXELS` costs about **512 MB at peak**, not the 384 MB
`exulanica/ingest/decode.py` used to claim. Pillow stores mode `RGB` at four bytes per pixel with
the fourth unused, and `ImageOps.exif_transpose` allocates a second buffer of the same size even
at orientation 1. Measured on CPython 3.11.6, Pillow 12.3.0, one fresh process per figure:
4.015 bytes per pixel for the decode (257.0 MB) and 4.003 for the transpose copy (256.2 MB), peak
515.4 MB; repeated, 4.011, 4.003, 514.8 MB. The fourth byte shows up directly in the modes: one
64 megapixel frame is 64.1 MB as `L`, 256.3 MB as `RGB` and 256.2 MB as `RGBA`.

    API worst-case bytes = baseline + T x 67 MB + D x 512 MB

where `T` is the threadpool (40) and `D` is the number of request decodes running at once. The
production composition disables the in-process worker, so it is not part of the API process's
peak. The 67 MB per thread is the
encoded part `_read_and_check` reads into memory before it probes anything
(`MAX_PART_BYTES + 1`). With nothing bounding `D`, `D` is `T`: **20 GiB of decode buffers**
(20,480 MiB), plus about 2.7 GB of encoded parts. The dedicated derivative worker is a separate
process with one delivery thread, so budget about another 512 MB per worker process instead of
silently adding its decode to the API process.

**A semaphore around the decode was proposed and is not implemented.** It bounds the right thing
by the wrong mechanism: acquiring it inside a synchronous handler blocks a thread that is already
holding one of the 40 tokens, so the uploads over the bound do not fail fast, they sit on threads
while waiting, and 5.4.2's measurement says what that does to `/healthz`. The levers that
actually reduce the product are the threadpool size, `MAX_PART_BYTES`, and `MAX_PIXELS`. A
deployment that wants a smaller box should turn those down, in that order, and section 10.1's
shape should be read against the arithmetic above rather than against a peak nobody computed.

---

## 6. Health check

**IMPLEMENTED.** This section was written before the service existed and opened by saying so;
that sentence outlived its subject. `fastapi` and `uvicorn` are runtime dependencies, both
endpoints are in `exulanica/api/routes/health.py`, section 1's own table already said "DECIDED and
implemented", and `tests/test_api.py` and `tests/test_deployment.py` exercise them. What follows
is documentation of behaviour, and where a sentence is still a requirement rather than a
description it says which.

### 6.1 Three signals, not one

Conflating them is the common mistake, and here it would be an expensive one.

| Signal | Path | Cost | Checks |
| --- | --- | --- | --- |
| **Liveness** | `GET /healthz` | Nothing beyond the process itself | The process is running and can serve a request. No dependency is touched |
| **Readiness** | `GET /readyz` | One cheap query and one cheap object storage call | The dependencies a request actually needs are reachable |
| **Catalog integrity** | Not an endpoint. A scheduled run of the preflight command | One public HTTP fetch, no credential, no model call | Every model identifier the application can reach still exists and still declares the capability its role needs |

### 6.2 What readiness actually verifies

| Check | What it proves | What it cannot prove |
| --- | --- | --- |
| `SELECT 1` on a **newly opened** connection | The server accepted a new connection and answered, so it is up and had a free connection slot at that moment | Nothing about schema correctness, and nothing about the *next* request, which needs its own slot. **There is no connection pool**: `exulanica/db/session.py` opens a fresh `psycopg.connect` per session and `psycopg_pool` is in neither `pyproject.toml` nor `uv.lock`. This row used to say the pool was not exhausted, which named a component that does not exist |
| Applied migration version equals the version the code expects | The running code and the running schema agree | Nothing about data integrity |
| A `HEAD` on one known asset key | Object storage is reachable, credentials are valid, and the bucket is where configuration says it is | Nothing about whether any particular scene's assets are complete |
| The model manifest parses and every role resolves to an identifier | The application can name a model | **Nothing about whether that model still exists.** That is section 6.1's third signal |

### 6.3 What the health check must not do

- **It must not call a model.** An external check every 5 minutes for 46 days is about 13,200 checks.
  Every reasoning call on this platform spends roughly 200 reasoning tokens before producing any
  output, and that cannot be disabled, so a model call per health check is pure waste. Worse, it
  makes the health signal depend on the prepaid balance: the day the balance runs out, health goes
  red for a reason that has nothing to do with the service being up.
- **It must not claim more than it checks.** A `200` from `/healthz` says the process is alive. It
  does not say the reasoning model still exists in the catalog. That precise gap, a green health
  check sitting in front of a withdrawn model, is the failure the catalog preflight exists for, and
  it is why the weekly check through the unattended window includes a catalog diff and not only a
  ping.
- **It must not be expensive enough to matter.** Readiness runs on every external probe. If it is not
  cheap it will either be turned off or become the thing that falls over.

---

## 7. Model catalog preflight

**This one is implemented.** `exulanica/models/preflight.py`, exposed as the console script
`exulanica-preflight` and runnable as `python -m exulanica.models.preflight`. Exit status 0 when clean
and 1 on any failure, so a build step and a scheduled check can both call it without parsing output.

### 7.1 The risk it addresses

**VERIFIED:** Nebius removed 11 models from Token Factory Serverless on 2026-06-22 and 10 more on
2026-08-31. That is two rounds in roughly ten weeks, against an unattended window of 46 days.

**ASSUMPTION:** that another round lands between feature freeze and the end of the unattended window.
Two rounds in ten weeks is the observed cadence. This cannot be validated in advance, which is
exactly why it is mitigated structurally rather than watched for.

Without the preflight, the failure looks like this: a user opens the demonstration five weeks into
the window, the application calls a model identifier that was withdrawn three weeks earlier, and the
request returns a 404 class error with nobody present to notice. The demonstration is dead and the
first person to find out is a user.

### 7.2 The three checks

| Check | What it catches | Severity |
| --- | --- | --- |
| **Presence** | Every identifier a role can reach, **primary and fallback alike**, appears in the catalog's `flavors[].model_id`. A fallback that has itself been withdrawn is a failover that fails, which is worse than no failover because it is discovered only under load | Fatal |
| **Capability** | The identifier still declares the `use_cases` its role needs. Asserted on `use_cases` and never on `type`, because a model typed `text2text` was measured to accept an image and describe it correctly. `use_cases` is authoritative and `type` is not | Fatal |
| **Price drift** | The catalog price differs from the manifest price | Warning. A price change breaks the cost report rather than the demonstration, but silent drift is how a cost report becomes fiction |

**Identifier casing is load bearing, and the preflight is where that is enforced.** The catalog's
human readable `name` differs from the callable `model_id`, inconsistently: one identifier doubles
its vendor prefix, another is entirely lowercase, a third uses an underscore where the display name
uses a dot. Both the manifest and the preflight read `flavors[].model_id` and never `name`. Reading
`name` produces a typo that returns a 404 at run time and looks like a deprecation.

The catalog fetch needs no credential. It reads
`https://tokenfactory.nebius.com/api/public/models_info`, which along with the API's OpenAPI
description is treated as the only authoritative source, because **VERIFIED:** the prose
documentation is materially stale in places, still describing a model flavour whose identifiers were
all deleted, and citing vision model identifiers that do not exist in the catalog.

### 7.3 How it is wired in

| Stage | Invocation | On failure |
| --- | --- | --- |
| Build and deploy | `exulanica-preflight` | Non zero exit fails the build. A deployment that cannot reach its models is not deployed |
| Continuous integration, offline | `exulanica-preflight --catalog-file <snapshot>` | Runs against a committed catalog snapshot, so the test suite does not depend on the network |
| Scheduled through the unattended window | `exulanica-preflight --json` | Feeds the weekly catalog diff described in section 9 |

**VERIFIED by execution 2026-08-27:** every model identifier in the manifest resolved against the
live catalog, 30 entries total. No role is pointing at a removed model.

### 7.4 Three honest gaps

1. **A catalog that cannot be reached is reported as a failure, exit 1.** That is correct for a
   build: a preflight that passes when it could not check anything is worthless. It is wrong for a
   scheduled check, where it turns a transient network blip into a page at three in the morning. The
   fix is a retry with backoff before alerting, distinguishing "the catalog says the model is gone"
   from "the catalog did not answer". **OPEN**, not implemented.
2. **The embedding role has no same tier fallback.** It is the only embedding typed model in the
   catalog. The preflight can detect its removal but nothing can recover from it, because
   substituting a model from a different vector space would silently poison every stored vector. The
   candidate mitigation is to precompute and freeze every embedding ahead of deployment so the
   demonstration never calls the embedding endpoint at all. That is probably the right answer and it
   has not been designed. **OPEN**, and it is the weakest point in the plan.
3. **The runtime fallback path is specified and not exercised.** The design calls for continuous
   integration to force the primary identifier to fail on every build so that the fallback is known
   good rather than theoretical. A fallback that has never executed is not a mitigation. **OPEN**,
   not implemented.

**What the mitigations buy, stated honestly:** with fallbacks in place, a deprecation during the
unattended window degrades answer quality rather than killing the demonstration. Degradation, not
death. That is the accurate description and it is the one to use wherever this project is described.

---

## 8. Cost control

Expected total infrastructure cost is roughly **$275 to $600 across 3.7 months**, dominated by
hosting uptime rather than by inference.

### 8.1 Inference spend is bounded by the platform, not by discipline

**VERIFIED from the billing console:** Token Factory is prepaid. API usage is charged against a
balance, top up is a manual action, and no automatic top up is offered. **Token Factory spend
therefore cannot exceed the balance**, which is a structural cap rather than a policy.

Measured against that: ingesting **1,000 photographs costs about $0.83**, and a conversational turn
at 15,000 tokens of context costs roughly $0.001 on the cheap reasoning tier. The prepaid balance on
the account is ample for the corpus and the unattended window at those unit costs. Inference is not
where this project's money goes.

### 8.2 Trap one: a forgotten GPU virtual machine

This is the realistic way the spend goes from small to embarrassing. An on demand L40S is **$32 to
$37 per day**. An H100 is **$92 per day**. Two forgotten weeks on the smaller card exceeds the entire
expected project budget.

**VERIFIED, and it is the non-obvious part:** GPU quotas count a virtual machine from creation to
deletion, **running or stopped**. Stopping the machine does not release the quota, so a stopped GPU
virtual machine both accrues attached storage cost and blocks the next job from starting. "I stopped
it" is not the same as "I deleted it".

Controls:

| Control | What it prevents |
| --- | --- |
| An auto-stop script on every GPU virtual machine | The overnight forget |
| Checkpoint reconstruction every 5,000 iterations | Makes preemptible instances genuinely usable, which is where the price difference is |
| Prefer Serverless **Jobs**, which self terminate, over endpoints, with a conservative timeout | Removes the class of failure entirely for the work that fits the shape |
| Lifecycle rules deleting reconstruction intermediates after 7 days | Silent storage growth from artifacts nobody will open again |
| A billing alert at $300 | The backstop for everything the other four missed |

**Reconstruction is a one time per scene cost.** Three to five scenes reconstructed once ahead of
deployment and cached as static assets is bounded and affordable. Reconstructing on demand during the
unattended window is neither, and it is also forbidden by the boundary in section 2: the hosted
demonstration must not depend on a long lived GPU job.

### 8.3 Trap two: managed PostgreSQL

**Roughly +$755 across the project period**, for a database that holds under a gigabyte, against
**$0 marginal cost** for a process on a host that has to exist anyway. This is the on-brand, obvious,
wrong choice, and it is wrong by more than the entire expected inference spend. The full reasoning is
in section 3.

It is named as a trap rather than merely rejected because it is the choice a reasonable person makes
by default. "Use the managed database" is good advice in almost every other context. It is bad advice
for a single tenant demonstration with a sub-gigabyte database and a fixed 3.7 month lifetime.

### 8.4 Where the money actually goes

| Line | Order of magnitude |
| --- | --- |
| The API and database host, running continuously across the window | Tens of dollars per month, and the largest single line |
| Object storage and egress | Small, and reduced further by an edge cache |
| Reconstruction GPU time, one time ahead of deployment | Bounded by scene count, and the line with the highest variance if the controls in 8.2 are not in place |
| Token Factory inference | Under a dollar for the corpus, capped by a prepaid balance |
| Static client hosting | Zero on the free tier |

---

## 9. Unattended operation

### 9.1 The premise

For 46 days there is no operator watching. Every control below exists to convert a class of silent
failure into either automatic recovery or an alert that reaches a person's phone. A dead URL is not
a degraded experience, it is the entire product gone, because everything the application does sits
behind it and nobody is present to notice.

### 9.2 What is monitored

| Signal | Method | Frequency | On failure |
| --- | --- | --- | --- |
| Process liveness | External check against `/healthz` from outside the deployment | Every 5 minutes | Alert to a phone after two consecutive failures. Two, not one, so a single dropped packet does not page |
| Dependency readiness | External check against `/readyz` | Every 15 minutes | Alert. Distinguishes "the API is up but the database is gone" from "everything is gone", which are different playbooks |
| Model catalog integrity | Scheduled `exulanica-preflight`, diffing the live catalog against the manifest | Daily, and included in the weekly human check | Alert naming the identifier and the role. This is the only signal that catches a withdrawal, and a health ping succeeds right up until the first query hits a removed model |
| Database backup freshness | Age of the newest dump object in storage | Daily | Alert. A backup job that silently stopped is indistinguishable from one that is working, until it is needed |
| Spend | Billing alert at $300 | Continuous | Alert, and investigate for a forgotten GPU machine first, per section 8.2 |
| Everything the automation misses | A named person loading the application, walking one scene and asking one question | Weekly through the unattended window | Judgement |

**OPEN: the person doing the weekly check is not named.** This is the least technical item in the
document and it is not the least likely to be the one that fails. Seven weekends is a long time for
something to drift in a way no automated check was written to notice.

### 9.3 What happens on failure

| Failure | Automatic response | Manual response | Worst case |
| --- | --- | --- | --- |
| API process dies | Host restart policy restarts it | None needed unless it recurs | Minutes of downtime |
| Host dies | None. This is the gap the platform does not fill | Redeploy from the one command path, restore the newest nightly dump | Hours of downtime and up to 24 hours of ingest data loss. Acceptable, because the corpus is static during the window and the dump holds it |
| Database corruption or accidental data loss | None | Restore from the nightly dump | Same as above |
| A model identifier is withdrawn | Runtime failover to the declared fallback for that role, on a 404 class error | Update the manifest and bump the pipeline version | Degraded answer quality. **Except for the embedding role, which has no fallback**, section 7.4 |
| Object storage unreachable | Edge cache continues serving whatever it holds | Investigate | Scenes that were already cached still load. Uncached scenes do not |
| Total backend loss | The static client build works with **zero backend**, serving a clearly labelled recorded tour | Redeploy the backend | The application is still explorable. It is explicitly labelled as a recording, because presenting it as the live application would be dishonest and a user who noticed would rightly discount everything else |

### 9.4 The recovery paths that have to be real

Three of the responses above are only worth writing down if they have actually been executed at least
once.

- **A one command redeploy, run from a clean shell.** A redeploy path that has never been run from
  scratch is not a recovery path, it is a hypothesis. **OPEN**, not written.
- **A restore from the nightly dump, performed once and timed.** An untested backup is a backup with
  an unknown restore time and an unknown success probability. **OPEN**, not performed.
- **The zero backend static build, loaded with the API deliberately switched off.** **OPEN**, not
  built.

Each of these is cheap to do once and worthless to describe without doing.

---

## 10. Choosing the target: options, tradeoffs and the criteria that settle it

The topology in section 2 is settled. The concrete target is not, and pretending otherwise would put
a decision in this document that nobody has made.

### 10.1 The API and database host

| Option | For | Against | Cost |
| --- | --- | --- | --- |
| **Nebius Compute virtual machine, small general purpose shape, network SSD volume, restart policy** (the recommendation on record) | Restart policy gives automatic recovery from process death. Volumes are documented and ordinary. Database and API in one consistency domain with no network hop | Manual host provisioning. No automatic recovery from host death, which is why the backup and redeploy paths in section 9.4 matter | About $36 per month |
| **Nebius Serverless AI endpoint with a co-located database container** | Scores best of these options on platform alignment | Preview grade with no service level, no automatic retry or recovery, and a documented typical lifetime of hours to days. Volume mounting is documented for jobs and **undocumented for endpoints**, so data durability rests on an assumption | Identical, about $36 per month. Serverless AI applies Compute pricing |
| **Nebius Managed PostgreSQL plus a separate API host** | Managed backups, managed upgrades, the professionally normal answer | Roughly +$755 across the project for a sub-gigabyte database. Splits one consistency domain across a network boundary, which section 3 argues against on deletion correctness grounds, not only on cost | +$204 per month |
| **A non-Nebius host such as Fly.io** | Cheap and technically adequate | Does not satisfy the project's platform constraint. Retained only as an unused break-glass configuration | Low |

### 10.2 The static client host

| Option | For | Against |
| --- | --- | --- |
| **Vercel Hobby, static** (the current default) | Zero cost, global edge, no server to die | 100 MB static upload cap and a 45 minute build cap, both **VERIFIED**. Neither binds once assets live in object storage, section 4.2 |
| **Cloudflare Workers Static Assets** | Equivalent, and pairs naturally with a Cloudflare cache in front of the Nebius origin | One more account and one more thing to configure |
| **Serve the client from the API host** | One fewer component | Couples the client's availability to the backend's, which discards the zero backend fallback in section 9.3. Rejected on that ground alone |

### 10.3 The criteria that settle it

In priority order, because they conflict and the order is the decision.

1. **Survives 46 days unattended.** Any option whose documented typical lifetime is shorter than the
   window is disqualified regardless of its other merits. This is the criterion that separates the
   first two rows of 10.1.
2. **The platform constraint stays literally true.** The system must run on Nebius Token Factory or
   Nebius AI Cloud. This disqualifies the non-Nebius row and is why the asset origin stays on Nebius
   even where an alternative would be marginally cheaper.
3. **One consistency domain for the database and the application.** Deletion correctness, section 3.
   This disqualifies the managed database row independently of its price.
4. **Total cost stays inside the $275 to $600 envelope**, with no line item exceeding the expected
   inference spend by an order of magnitude for no capability gain.
5. **Recovery is testable before the window opens.** An option whose failure path cannot be
   rehearsed before the operator stops watching is worth less than one that can, whatever its steady
   state numbers look like.

Applying 1 through 4 leaves the Compute virtual machine, which is why it is the recommendation on
record. It is not recorded as locked, because criterion 5 has not been exercised and because the
canary experiment in section 3.2 is still running.

### 10.4 What has to be settled, and by when

| Question | Settled by | Deadline |
| --- | --- | --- |
| The cloud account and project | Provisioning it | Before the first deployment rehearsal |
| The domain name | Registering it and pointing it | Before the deployment rehearsal, and early enough that DNS and certificate issuance are not on the critical path on the day the window opens |
| Compute virtual machine or Serverless endpoint | The canary experiment's outage log, read against criterion 1 | At the deployment rehearsal, not on the day the window opens |
| Whether the health endpoint, the redeploy command and the zero backend fallback exist | Writing them | Before the deployment rehearsal, since the rehearsal is what tests them |
| Who performs the weekly check | Asking a person and getting a yes | Before the window opens |

**A deployment rehearsal is scheduled before the window opens, not on the day it opens.** The entire
plan above is untested until the application has been deployed once, killed deliberately, and
recovered from the documented path. Everything in sections 6, 9 and 10 is a hypothesis until that
has happened at least once with a stopwatch running.

---

## 11. Consolidated open items

| # | Item | Resolved by |
| --- | --- | --- |
| D-1 | ~~No HTTP service exists~~ **CLOSED.** The service exists and both health endpoints are implemented. What is NOT asserted anywhere is that `/readyz`'s schema check reports a stale schema rather than a missing one; that has no positive test | Writing one |
| D-2 | The one command redeploy has never been run from a clean shell | Running it |
| D-3 | The nightly dump has never been restored | Restoring one and timing it |
| D-4 | The zero backend static fallback has not been built | Building it and loading it with the API off |
| D-5 | Preflight treats an unreachable catalog as a failure, correct for a build and wrong for a scheduled check | Retry with backoff, and distinguish the two outcomes in the alert |
| D-6 | The embedding role has no fallback and no recovery path | Design the precompute and freeze approach, or accept a single point dependency and say so |
| D-7 | The runtime fallback path has never executed | Force the primary to fail in continuous integration |
| D-8 | Whether the renderer's asset loader issues range requests is unobserved | Load a scene with the network panel open |
| D-9 | The cloud account, project, region placement and domain are unchosen | Section 10.4. This is the only thing between the artefacts in section 1 and a running deployment |
| D-12 | ~~The container image has never been built~~ **CLOSED 2026-08-29.** Built, 222 MB, and run: uvicorn serves, the healthcheck passes, both console scripts run, an upload through it returned 202 and its worker drained the queue, and a bad connection string makes it refuse to start. What is still unobserved is the image running anywhere but this machine | Section 10.4, which is D-9 |
| D-13 | There is no reverse proxy and no static client host in the composition | Choosing one, which is D-9 |
| D-10 | Nobody is named for the weekly check through the unattended window | Asking a person |
| D-11 | Whether a preview grade service survives the window at all | The canary endpoint's outage log |
| D-14 | Nothing limits in-flight requests, so a single process can demand more backends than the cluster has slots. Section 5.4.3 measured 48 concurrent streams holding 48 backends against a 40-thread pool and 97 usable slots | Setting `uvicorn --limit-concurrency`, which is the only lever that counts requests where they are actually held. Not set today, and not urgent at one person watching one upload |
| D-15 | Section 5.4.2's container-restart consequence is arithmetic over a measured latency and the Dockerfile. No container was built or run to observe it | Running the image, saturating it, and watching whether Docker restarts it |
| D-16 | ~~The runtime connects as the database owner, bypassing row-level security~~ **CLOSED 2026-08-31.** The owner credential is confined to migrations; API and derivative-worker composition URLs name `orimera_app`, and both processes refuse unsafe roles at startup | PostgreSQL role tests plus deployment text contract |

---

## 12. Scalability: four changes that were measured and declined

Each of the four below looked like the obvious next thing to build. Each was measured before it
was built, and the measurement is why it was not. This section exists so that the next person to
reach for one of them starts from the numbers rather than from the intuition, and so that the
condition under which the answer flips is written down rather than rediscovered.

**Every figure here was taken on this machine** (macOS on arm64, CPython 3.11.6, PostgreSQL 18.6
on port 5433, psycopg 3.3.4, Pillow 12.3.0, anyio 4.14.2, uvicorn 0.52.4, starlette 1.6.0,
fastapi 0.141.1) against scratch databases created and dropped for the purpose. Where a number
comes from an assessment rather than from a run reproduced here, it says so.

### 12.1 No connection pool, and the reason is correctness before it is cost

`exulanica/db/session.py` opens a fresh `psycopg.connect` per session. `psycopg_pool` appears in
neither `pyproject.toml` nor `uv.lock`. **Keep it that way**, and the decisive reason is not the
saving foregone.

**A pooled connection carries the previous borrower's workspace.** Reproduced here with
`psycopg_pool` 3.3.1 side-loaded onto `PYTHONPATH` (so neither manifest was touched), probed as a
throwaway **non-superuser** role against the real `intake_batch` policy, which is FORCE row-level
security on `workspace_id = current_workspace()`. A superuser probe would have proved nothing:
superusers bypass row-level security entirely.

| Pool configuration | What a borrower that declared NO workspace saw |
| --- | --- |
| `psycopg_pool` defaults | Same backend pid across checkouts. After a workspace-A borrower: `current_workspace()` = A, rows = `['workspace A batch']`, `assert_workspace_context(A)` **PASSED**, insert into A **ACCEPTED**. After a workspace-B borrower on the same connection: rows = `['workspace B batch']` |
| `reset=lambda conn: conn.execute("reset all")` | setting `''`, `current_workspace()` NULL, rows `[]`, insert refused with SQLSTATE 42501, and `assert_workspace_context` raises again |

That is a cross-tenant read introduced by the pool, and it falsifies two things the repository
already asserts. `Database.unscoped`'s docstring says a caller reaching for it "would get an empty
result rather than another workspace's rows"; pooled, it gets another workspace's rows.
`assert_workspace_context` exists in migration 0001 precisely to raise rather than fail open, and
it passed for a workspace the borrower had never named. `tests/test_row_level_security.py` now
holds that pair as an assertion.

**Why the default does nothing.** `psycopg_pool` skips its reset when the connection's
transaction status is IDLE, and under the autocommit `session()` deliberately chooses, a returned
connection is always IDLE (measured: `transaction_status` 0 after a SELECT). So no DISCARD, no
RESET, no rollback.

**Two traps in the fix, both measured here.** `DISCARD ALL` is the wrong reset: it deallocates
server-side prepared statements while psycopg's client-side map still believes in them, and the
next execute of an auto-prepared query fails with SQLSTATE 26000,
`prepared statement "_pg3_0" does not exist`. `RESET ALL` does not deallocate and reuse is fine.
But `RESET ALL` also undoes the UTC that `session()` sets: after one reset the time zone was back
to `America/New_York`, the server default. Putting it in the startup packet instead
(`?options=-c timezone=UTC`) survives `RESET ALL`, measured still UTC.

**The saving being declined, with its transport named.** Mixing transports is how this trade gets
oversold, so each figure says which one it is. Medians over 300 samples on a quiet cluster:

| | TCP loopback | unix socket |
| --- | --- | --- |
| `connect` + close | 1.285 ms | 1.270 ms |
| The whole `Database.session` shape plus one workspace-scoped query | 2.009 ms | 1.689 ms |
| That query alone on an already-open connection | 0.052 ms | 0.017 ms |
| The pooled unit of work (`set_config` + query + `reset all`) | not taken | 0.045 ms |

Section 3 puts PostgreSQL on the same host, so the **unix socket** column is the one that
applies. Over it a pool would save about **1.64 ms** per request, on requests whose real work is
a model call measured in seconds. Opening a connection is 75 times the query it enables over that
transport, which sounds decisive and is not: 75 times a very small number is still a very small
number.

**What would change the answer.** Concurrent request rate rising by an order of magnitude, or
workspace count per instance doing the same, at which point the per-request 1.64 ms and the
per-poll connect in each worker stop being noise. If that day comes, the correct pool is exactly
three things and not two: `reset all` on return, the time zone moved into the startup packet
because `reset all` undoes it, and `unscoped()` never drawing from the pool at all.

**On an external pooler: not measured, and flagged as reasoning.** PgBouncer is not installed
here. The mechanism is the one above. `set_workspace` sets a SESSION setting with `is_local`
false, outside any transaction, so under transaction-mode pooling it lands on whichever server
connection is assigned at that instant and the next statement may run on a different one, with no
reset hook to repair it. Session mode would be correct. Settling it needs a probe against a real
PgBouncer, which this machine cannot run.

### 12.2 No subscriber bound on the formation stream

Declined, and the measurement is in section 5.4.2 rather than repeated here. In summary: the
cliff is at 40, which is the threadpool and not a number anyone chose; 39 concurrent streams are
indistinguishable from 1; the proposed bound of 8 is not derived from any of that; and the
counter that would enforce it leaks a slot on every request whose `StreamingResponse` is
constructed and never iterated, because `_events` is a generator function and its `finally` runs
only if the generator is started and closed. The threadpool size and the cliff are recorded as a
deployment setting instead.

### 12.3 No reference counting on `blob`

`blob` is not workspace-scoped (migration 0001), and the purge path works around that with a
cross-workspace SELECT policy on the exact holder relations granted to `exulanica_purge`. Replacing
that with a maintained holder count on `blob` is **not the right change now**.

**CORRECTED 2026-09-03.** The policy now covers a third relation,
`reconstruction_scene_member`, because migration 0024 gave `purge_releases_bytes` a clause that
reads it: a scene artifact is a fact about N photographs and holds its bytes only while every
member is live. `artifact` also gained `scene_id`, so it is three tables and one more column, and
`exulanica.db.roles.PURGE_CROSS_WORKSPACE_TABLES` is the list rather than a sentence. The direction
of a blindness over the new table is the opposite of the one this paragraph is about: it
over-refuses rather than destroying, so the cost of getting it wrong is a deletion that never
completes rather than another tenant's photograph.

**What is reproduced here**: the structural half. `artifact` carries exactly two indexes,
`artifact_pkey` and `artifact_workspace_id_idempotency_key_key`. There is **no index on
`artifact.content_sha256` or on `artifact.source_blob_sha256`**, so `purge_releases_bytes` scans
the artifact table on every purge job. **CORRECTED: it now carries a third**,
`artifact_scene_idx` on `(workspace_id, scene_id) where scene_id is not null`, which the purge
enqueue uses and which does nothing for the scan this paragraph measures.

**What is not reproduced here, and is recorded as the assessment's own measurement**: that the
predicate costs about 30 ms per target at 660,000 artifacts, falls to about 0.144 ms with one
partial index on `artifact (content_sha256) where purged_at is null`, and to about 0.030 ms with
a materialised holder count. If those hold, the index is worth hours across a large workspace
deletion and reference counting on top of it is worth about half a minute.

**The comparison as it stands is one-sided, and that strengthens the conclusion rather than
weakening it.** The 0.030 ms came from a static column on a primary key. The design it stands in
for is a count on `blob` maintained by triggers on `capture` and `artifact`, paid on every
capture insert, every capture soft-delete, every artifact insert and every artifact purge. That
recurring write cost was never measured, and it is precisely the cost the index alternative does
not pay.

**What would change the answer**, each checkable rather than a matter of taste:

- **A-30 falls.** A workspace stops being one user, or workspaces become shared. The partition
  strategy and the row-level security predicate need rework anyway at that point, and this rides
  along with it.
- **The cross-workspace read itself becomes unacceptable.** `exulanica_purge` can answer "which
  workspace holds these exact bytes" across the whole deployment. That is the one argument a
  larger retry budget cannot answer, and if the threat model rules it out, a count replaces the
  read.
- **The measured sharing rate stops being zero.** Count blobs whose distinct holding-workspace
  count exceeds one. While that is zero, the condition this design defends against has never
  occurred.

### 12.4 No semaphore around the decode

Declined. Section 5.4.4 has the arithmetic and the reason: the bound is real, but a
`threading.BoundedSemaphore` acquired inside a synchronous route handler blocks a thread that is
already holding one of the 40 anyio tokens, which converts an out-of-memory into section 5.4.2's
starvation of `/healthz` and the container restart that follows. The aggregate is documented as a
sizing input instead. `exulanica/ingest/decode.py`'s own arithmetic was wrong by a third, in the
direction that made the aggregate look smaller, and that has been corrected.

### 12.5 Poll intervals stay as they are, and one index does not

The derivative worker polls every 2 s and the purge worker every 30 s. Both are cheap at the
workspace counts this deployment has, and neither interval is worth touching.

**The claim index had the wrong columns, and that defect is closed.**
`exulanica/ingest/derivative_queue.py` selects `where workspace_id = ? and kind = ? and state =
'queued' and run_after <= now() order by priority, job_id ... limit 1`, and `job_queue_idx` is
`(state, run_after, priority, job_id) where state = 'queued'`, which carries neither
`workspace_id` nor `kind`. Measured on a scratch database with 5,000 queued jobs in the polled
workspace and 100,000 in two others:

| Index | Plan | Buffers | Time |
| --- | --- | --- | --- |
| old `job_queue_idx` | Bitmap Heap Scan, Rows Removed by Filter: 100000 | 1616 | 4.744 ms |
| `(workspace_id, kind, run_after, priority, job_id) where state = 'queued'` | Bitmap Heap Scan of all 5,000 matches, then a quicksort | 1672 | 1.835 ms |
| `(workspace_id, kind, priority, job_id) where state = 'queued'` | **Index Scan**, `run_after` as a filter | **5** | **0.027 ms** |

**`run_after` must not sit ahead of the ORDER BY keys.** It is a range predicate, so an index
leading with it cannot supply the ordering, and the plan falls back to reading every matching row
and sorting. That defect is invisible against an empty queue, which is the only case an idle-poll
benchmark exercises and also the only case that does no work. The third row is the shape to
build.

Migration 0016 installs the third shape as `job_queue_idx`. The PostgreSQL contract test populates
8,000 mixed workspace/kind rows, requires that index, requires no sort, and caps touched buffers at
eight. `run_after` remains a filter so the index preserves `order by priority, job_id` exactly.
