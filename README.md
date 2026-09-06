# Exulanica

**A Personal World Memory Model.** Exulanica turns a personal photograph library into separate
navigable 3D memory regions inside one continuous first-person browser space called the Atlas,
connects recurring people, places, objects and events across those regions, and lets a person
explore and query their own lived history under a single rule: every historical factual claim
resolves to the exact original source it came from.

Claims resolve to captured bytes, never to derived geometry. **Reconstruction quality therefore
never participates in the truth guarantee.** A region rendered from thin coverage tells the truth
exactly as reliably as a photoreal one, because neither of them is what the answer cites.

Against the generative world models of 2026, which imagine a plausible world for a session and
forget it, Exulanica is the memory they lack: a persistent world of one person's life (or one
place, family or institution) built from real captures, where every part is traceable to its
original, every pictured person's consent is enforced, and the whole thing is a signed package the
owner keeps. A generative model that renders your kitchen should read it from here and be unable to
deviate from what is real without saying so.

Originally built for the Nebius x NVIDIA Global AI Hackathon.

## Project status

Checked on 2026-08-29 by running the commands in [Setup and running](#setup-and-running).

**Working, and verified by execution.** The evidence spine, the content-addressed store, the
photograph ingest pipeline and the Nebius Token Factory model client are implemented and covered by
912 backend tests, all passing. 426 of those apply the schema migration to a live PostgreSQL 18
server with pgvector, the only executable proof that a model cannot write a person's name into
canonical state. Ingest runs end to end over a directory of photographs and is idempotent: a second
pass recomputes nothing and issues no model calls. The HTTP API serves health, graph, selection,
identity, evidence and intake routes, and an upload's intake stage runs in the request while its
model stages are queued by capture id. The browser packages pass `pnpm check`: a typecheck of every
package, an import-boundary contract, and 371 tests. The renderer was chosen on measurement, against the
earlier lean (PlayCanvas Engine 2.21.4,
[docs/adr/0003-renderer-selection.md](docs/adr/0003-renderer-selection.md)). Real calls to NVIDIA
Nemotron and to Tavily were made and archived on 2026-08-27.

**Assembled for development, but not deployed.** Query planning and answer composition are
implemented in `exulanica/selection/`, and `web/packages/app/src/main.ts` joins the Atlas scene,
Companion runtime and World Index to the API. It has been rendered against synthetic data. The API
and Vite application still need separate commands, so there is no single command that starts
Exulanica end to end. MoGe is the chosen reconstruction method and is not integrated into upload.

**Deliberately not claimed.** No personal photograph library has been ingested, so nothing about
reconstruction quality, identity or retrieval has been measured on real material. No accuracy or
recall figure for cross-capture identity exists, and none will appear until one is measured. Nothing
is deployed. No reconstruction has been produced from a real capture, so the ladder's upper rungs
are specified rather than demonstrated.

The settled product-level limitations are in section 11 of
[docs/product-specification.md](docs/product-specification.md).

## The defining loop

1. A capture becomes a navigable memory region. Originals are retained under an append-only policy.
2. A recurring person, place, object or event is proposed across separate regions.
3. The user confirms or rejects uncertain continuity, and adds context the capture could not know.
4. The Atlas filters and highlights around that continuity, as a view transformation rather than a
   rebuild.
5. Natural language questions retrieve evidence across regions.
6. Every historical claim opens the exact supporting original image, with the world anchor pulsing
   at the same time.
7. A separate, opt-in public lookup connects a remembered public entity to its current state, in a
   panel that is structurally unable to be cited as memory.

## What is honest about it

The differentiator is that the system does not overclaim, and the places where it could overclaim
are the places it is most careful.

- **The reconstruction ladder is visible in the interface.** Four rungs, from a full navigable
  splat down to a spatial arrangement of evidence cards. Each region displays the rung it actually
  earned. No label may imply free movement in a region that does not have it. The floor rung has no
  gate that can fail, and it is built first.
- **Model inference is never presented as fact.** The system may organize on a guess and may never
  assert on one. An automatically proposed identity link can drive layout, filtering and
  highlighting, but it cannot support a historical clause until the account holder confirms it.
  This is forced rather than chosen: published open-set face identification reaches roughly 60%
  identification rate at FAR = 0.01, and cross-domain person re-identification collapses to around
  52% rank-1. At those numbers, autonomous cross-capture identity cannot be shipped.
- **Provenance is banded, not blended.** Update proposals separate what you told me, what the
  captures support, what I inferred, and what I still do not know.
- **Storage is described as "append-only by policy".** Not immutable, not tamper-proof, not WORM.
  The documentation set uses one epistemic status per claim (VERIFIED with a source and retrieval
  date, DECISION, ASSUMPTION, OPEN, CORRECTED), and unverified things stay labelled unverified.
- **Processing shows real pipeline state.** No synthetic progress bar, no invented percentage. If
  remaining time is unknown, none is shown.

## NVIDIA and Nebius usage

Everything below was measured by calling the platform on 2026-08-27, not read from documentation.
The measurements and their method are in [docs/runtime-verification.md](docs/runtime-verification.md),
which overrides every other document in this repository on conflict.

### Models, by role

All inference runs on **Nebius Token Factory**, OpenAI-compatible, at
`https://api.tokenfactory.nebius.com/v1`. Every identifier below is declared in exactly one place,
[`exulanica/models/models.manifest.json`](exulanica/models/models.manifest.json), together with its
price, context window and declared fallback.

| Role | Model | Price in/out per Mtok | Why |
| --- | --- | --- | --- |
| Reasoning, default | `nvidia/Nemotron-3_5-Lightning` | $0.06 / $0.24 | Every Companion turn and every cross-scene continuity decision. 1M context, which is the binding constraint on long shallow reasoning over an evidence packet |
| Reasoning, escalation | `nvidia/nemotron-3-super-120b-a12b` | $0.30 / $0.90 | Entered only where the default tier has been measured to fail a specific task |
| Reasoning, ceiling | `nvidia/Nemotron-3-Ultra-550b-a55b` | $1.00 / $3.00 | Reachable only by asking for it explicitly. Nothing routes here by default, because a 15x price for an unmeasured advantage is a claim this project has committed not to make |
| Vision sensor | `MiniMaxAI/MiniMax-M3` | $0.30 / $1.20 | One structured-extraction pass per photograph at ingest |
| Embeddings | `Qwen/Qwen3-Embedding-8B` | $0.01 / $0.00 | 4096 dimensions. The only embedding-typed model in the catalog, so this role has no same-tier fallback and the client says so loudly rather than degrading into a different vector space |

The NVIDIA Nemotron reasoning core is the decision-making layer of the product. The non-NVIDIA
vision model is a sensor: it converts pixels to structured observations, and every judgement made
from those observations is made by Nemotron. That split is recorded in
[docs/adr/0002-model-routing.md](docs/adr/0002-model-routing.md).

**Evidence of real use.** A call to `nvidia/Nemotron-3_5-Lightning` returned HTTP 200 in 0.52 s with
the model identifier echoed in the response body. The full body and response headers are archived by
`scripts/verify_platform.py`. The archive itself is not committed, because it carries
account-identifying response headers; every field that carries a finding is quoted in
[docs/runtime-verification.md](docs/runtime-verification.md).

### What was measured

- **Ingestion cost: about $0.83 per 1000 photographs** at 768 px on `MiniMaxAI/MiniMax-M3`. Image
  token count is strongly sub-linear in pixel area: 277 prompt tokens at 256 x 256, 772 at
  768 x 768, so 9x the area costs 2.8x the tokens. Higher resolution is cheaper than a per-pixel
  model suggests, which removes the incentive to downscale and lose detail.
- **Nemotron spends roughly 200 reasoning tokens on every call**, including trivial ones, and there
  is no way to switch that off. `chat_template_kwargs: {"thinking": false}` does not disable it.
  The thinking text arrives **inline in `message.content`** while `message.reasoning_content` is
  null, so a naive parser reads the model's scratch work. `max_tokens` must clear roughly 600 or
  responses truncate mid-reasoning with an empty answer. The manifest encodes this as
  `min_max_tokens: 640` per model, and `exulanica/models/reasoning.py` strips the scratch work.
- **Structured output works by exactly one mechanism.** `response_format: {type: "json_schema",
  strict: true}` produces valid JSON. A top-level `guided_json` parameter is **silently ignored**
  and returns prose with HTTP 200. That silent failure is the dangerous one, so canonical memory
  state is only ever populated through the strict json_schema path.
- **The catalog `type` field is not reliable.** `MiniMaxAI/MiniMax-M3` is typed `text2text` and
  labelled "Text-to-text" in the console, yet it accepts an `image_url` content part and describes
  the image correctly. The operating rule is that `use_cases` is authoritative and `type` is not.

### Where Token Factory accelerated the workflow

- **One OpenAI-compatible endpoint for every role**, so swapping a model is a manifest edit rather
  than a client rewrite. The manifest is the only file in the codebase where a model identifier
  appears.
- **A public catalog endpoint**, which makes a preflight check possible: `uv run exulanica-preflight`
  resolves every manifest identifier against the live catalog and exits non-zero if any has been
  withdrawn or no longer declares the `use_cases` its role needs. Nebius removed 11 models from
  Token Factory Serverless on 2026-06-22 and removes 10 more on 2026-08-31, two rounds in roughly
  ten weeks, so this is a live concern rather than a theoretical one. No role in the manifest points
  at a model in either round. The same check runs automatically before the first model call of an
  ingest, so a run that is about to spend money finds out first.
- **Prepaid billing** bounds total exposure to the account balance. There is no automatic top-up,
  so a runaway loop cannot produce an unbounded bill. `exulanica/models/budget.py` adds a local
  ceiling on top of that, described honestly as a development safety rail rather than a limit.
- Combined with the response cache in `exulanica/models/cache.py`, keyed by content hash plus
  pipeline version plus role plus prompt version, a repeated ingest over the same photographs
  issues zero model calls and costs nothing.

### Other Nebius and third-party services

**Tavily** provides the opt-in public lookup for the present-day state of public entities. A real
call returned HTTP 200 in 2.26 s with three sourced results. The request payload is retained
deliberately, as evidence that the query carried public entity text only: no private media, no
person, no private location, no transcript. Tavily results render in a separate panel and may never
rewrite what a memory says happened.

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

Neither key is required to run the test suite. Nothing in `tests/` reaches the network or spends
credits: the model client is exercised through a scripted HTTP transport, and test photographs are
generated rather than committed, so the content of every test image is known exactly.

```bash
uv run pytest                       # 1447 tests; 677 skip without a database
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

**PostgreSQL is the only data layer.** 426 of the 912 backend tests need a real server, and they
are the executable proof of everything the database carries: that a model cannot write a name into
canonical state, that one workspace cannot read another's rows, that a tombstoned address refuses
the write, and that the whole ingest path works. A default run prints a reminder naming the files
it skipped rather than reporting green in silence.

The target is PostgreSQL 18 with pgvector, and nothing is substituted for it. On macOS:

```bash
brew install postgresql@18 pgvector
brew services start postgresql@18
createdb exulanica_spine_test
EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test uv run pytest
```

The port is 5433 only if an older PostgreSQL already holds 5432; use whatever the server is on.

Three things to know about that harness:

- **The database name must contain "test".** It refuses to touch anything else. All work happens
  inside a throwaway schema that is dropped afterwards, because each migration carries its own
  `commit;` and cannot be undone by a rollback.
- **A server that cannot run the schema is a loud failure, not a silent substitution.** An earlier
  version of the harness swapped `gen_random_uuid()` for `uuidv7()` and `bytea` for
  `halfvec(4096)` so the suite could run on PostgreSQL 14. Everything passed and the vector path
  had never executed once, which hid a test that wrote raw bytes into a vector column.
- Set `EXULANICA_REQUIRE_POSTGRES=1` to turn the skip into a failure, which is how continuous
  integration should run it. The suite is safe to run in parallel against one database: verified
  with five concurrent runs.

### Running the API

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
terminal result durably. See [the derivative worker runbook](docs/derivative-worker-operations.md).
The scene worker uses renewable leases and checkpointed scratch, but responds to deletion during
pose recovery and removes sensitive work after every terminal outcome. See
[the production reconstruction-scene runbook](docs/scene-reconstruction-operations.md).

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
package, a dependency-cruiser contract over the forbidden cross-package imports, and 371 vitest
tests. The boundary rules have each been probed with a deliberate violation, so they are known to
fire rather than assumed to.

```bash
pnpm landing                 # the public title, Purpose and Capabilities surfaces
pnpm app                     # the canonical Atlas application
pnpm synth --out ./fixtures  # generates the renderer bake-off ladder, about ten seconds
pnpm bakeoff                 # serves the bake-off harness over those fixtures
```

Fixtures are gitignored. Regenerate them rather than committing them.

### What runs today

Every command above runs now. The HTTP API serves and the assembled Atlas application renders in
development, but they still start with separate commands. There is currently no single command
that starts Exulanica end to end.
[Project status](#project-status) has the rest of the picture.

## Repository layout

| Path | Contains |
| --- | --- |
| `exulanica/evidence/` | The evidence address, content-addressed blobs, memory regions, the time base |
| `exulanica/ingest/` | The photograph ingest pipeline: EXIF, orientation, derivatives, vision, scene grouping, the provenance ledger, the CLI, the derivative queue and the worker that drains it |
| `exulanica/models/` | The Token Factory client, the model manifest, preflight, the budget guard, the response cache, strict json_schema handling, reasoning-token stripping |
| `exulanica/store/` | Content-addressed storage |
| `exulanica/migrations/` | The forward-only PostgreSQL schema history, from `0001_spine.sql` through migration 0018 |
| `exulanica/db/` | Connections carrying the workspace context, the migration runner, the runtime roles |
| `exulanica/epistemics/` | Writing a claim under exactly one of the four provenance classes |
| `exulanica/identity/` | Occurrence keys, the identity tables, and the user decisions that promote an occurrence to a person |
| `exulanica/selection/` | The one Selection primitive: plan, validation, deterministic execution, evidence packet, answer validation |
| `exulanica/api/` | The HTTP surface, including `POST /intake`. Routes validate and delegate; the only unauthenticated ones are the health probes |
| `exulanica/deletion/` | The purge queue a tombstone fills and the worker that empties it. Destroys objects, marks rows, and holds DELETE on nothing |
| `pyproject.toml` | Also the backend layering contract, enforced by `uv run lint-imports` |
| `exulanica/canonical.py`, `exulanica/errors.py` | Canonical JSON and the one rounding rule; the error taxonomy |
| `tests/` | 1447 tests, 677 of which need a PostgreSQL 18 server. No network, no credentials, no committed binary fixtures |
| `scripts/` | The standalone runtime verification harnesses, kept byte-identical so their evidence stays reproducible |
| `web/packages/atlas-core/` | Scene graph, island frames, focus resolution, layout solver. No React, no DOM, no renderer |
| `web/packages/atlas-react/` | Renderer bindings, anchor overlay, HUD, comfort settings |
| `web/packages/companion-runtime/` | Turn generation, option pools, proposal drafting, the initiative gate |
| `web/packages/world-index/` | The non-spatial keyboard-first index, entity detail, the provenance panel |
| `web/packages/graph-client/` | Entity graph reads and writes, the assertion log, evidence resolution |
| `web/packages/atlas-three/`, `web/packages/bakeoff/`, `web/packages/scene-synth/` | The renderer bake-off: a competing binding, the harness, and the synthetic scene generator |
| `web/packages/landing/` | The signed-out landing surface, which deliberately takes no renderer |
| `docs/` | The documentation set below |

## Documentation

[docs/README.md](docs/README.md) is the index and explains the epistemic status labels. Four entry
points, depending on why you are here:

- **Evaluating the project.** [docs/product-specification.md](docs/product-specification.md)
  sections 1 to 5 for what it is, what the demonstration shows, and the reconstruction ladder, then
  section 11 for the known limitations.
- **Writing client code against the platform.**
  [docs/runtime-verification.md](docs/runtime-verification.md) first. It records the behaviours that
  will otherwise cause silent bugs, including the reasoning-token floor and the structured-output
  mechanism that is silently ignored.
- **Understanding the system shape.**
  [docs/architecture-overview.md](docs/architecture-overview.md) sections 1 to 3, then
  [docs/domain-and-evidence-model.md](docs/domain-and-evidence-model.md) sections 1 and 4 for the
  evidence address and the schema.
- **Reviewing the technology choices.** [docs/adr/](docs/adr/) in number order, then
  [docs/model-and-service-selection.md](docs/model-and-service-selection.md) for the full model and
  service matrix.

## License

Apache-2.0. See [LICENSE](LICENSE).

The per-component ship and do-not-ship verdicts, the NVIDIA license distinction, and the NOTICE-file
obligations that third-party components impose are recorded in
[docs/license-matrix.md](docs/license-matrix.md). The consolidated notices that section 7 of that
document specifies are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), read from the packages
themselves on 2026-08-28.
