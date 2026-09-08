# Frontier demonstration command

Status: **AUTHORIZED PERSONAL CORPUS AND PRODUCTION SIGNING KEY NOT SUPPLIED; REAL RUN PENDING**.

The local pre-flight and generated-photo rehearsal are executable commands. The personal run
still needs the operator's directory, signing key, manifest, and explicit decisions about model
use. Presence of an arbitrary photo directory on disk is not authorization to use it.

`exulanica-frontier demonstrate` is the Phase 8 source-to-package acceptance path. It starts from
one operator-authorized ordinary photo directory and a versioned manifest, then composes the real
ingest, evidence, Selection, graph, spatial-authority, style-authority, deletion, and World Memory
Package boundaries. It does not contain a second implementation of any of them.

The PostgreSQL acceptance test uses explicitly authorized generated development photographs and an
in-process counting vision fake so that it cannot spend money. That test proves the orchestration contract; it is not a
consented personal-corpus result, reconstruction-quality result, or deployment claim. No authorized
personal directory was supplied while this command was built, so the real-data demonstration
remains an external run rather than a result recorded in this repository.

## 1. Invocation and destructive boundary

```text
uv run exulanica-frontier demonstrate \
  --manifest /outside-git/frontier-build.json \
  --photo-dir /authorized/photos \
  --data-dir /outside-git/exulanica-data \
  --output /outside-git/frontier-run \
  --private-key /secure/location/wmp-ed25519.pem \
  --confirm-source-deletion
```

The command requires `EXULANICA_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test`.
It checks schema history, refuses pending migrations, provisions the manifest workspace, and then
runs the gate. Migration review/application remains an explicit operator operation. Other databases
and libpq routing overrides are refused. The role must own the embedding table and have schema
creation rights because provisioning creates its workspace partition. The signing key must already exist and must be Ed25519;
the command never generates or persists a production secret.

`--confirm-source-deletion` is intentionally required before any work begins. Step 10 writes a
durable capture tombstone for the manifest's `deletion_demo.path`. It does **not** delete or mutate
the original file in `--photo-dir`; the receipt records that distinction. Without the flag, the
command exits nonzero at the named `source_deletion_confirmation_required` terminal gate and does
not create the output directory.

The output path must not exist. This prevents a second run from overwriting signed packages or
mixing receipts from different source sets.

## 2. Build manifest v1

The manifest profile is `exulanica-frontier-build/v1`. Its exact top-level fields are:

```json
{
  "profile": "exulanica-frontier-build/v1",
  "workspace_id": "00000000-0000-0000-0000-000000000000",
  "actor_id": "00000000-0000-0000-0000-000000000000",
  "world_id": "atlas:default",
  "sources": [
    {"path": "a.jpg", "sha256": "<64 lowercase hex>", "bytes": 1},
    {"path": "nested/b.jpg", "sha256": "<64 lowercase hex>", "bytes": 1}
  ],
  "pipeline": {
    "vision": "unavailable",
    "depth": "unavailable",
    "model_manifest_sha256": "<sha256 of exulanica/models/models.manifest.json>"
  },
  "precomputed_artifacts": [],
  "adaptation": {
    "profile_id": "origin-landscape",
    "profile_version": 1,
    "parameters": {"vitality": 1},
    "proposal_provenance": {
      "origin": "companion",
      "origin_reference": "conversation:frontier-style",
      "model_id": "<actual proposing model/version>",
      "prompt_version": "<actual recipe prompt/version>",
      "reference_ids": ["<opaque authorized design reference id>"]
    }
  },
  "deletion_demo": {"path": "a.jpg"}
}
```

The two runtime modes are `vision: configured|unavailable` and `depth: moge|unavailable`.
Configured vision additionally requires `--authorize-hosted-vision` for this invocation. It performs
the live model-catalog preflight and loads the normal role-routed Nebius client. `moge` loads the reviewed optional depth implementation. A requested implementation
that cannot load is a named configuration stop, not an implicit downgrade. An explicit
`unavailable` mode is the honest capture-only or source-first fallback.

The manifest:

- is strict: unknown or missing keys, duplicate JSON keys, floats at any depth, malformed UUIDs,
  and noncanonical relative paths are refused;
- requires two or more unique source byte digests, because removing one source must leave a real
  fallback region rather than an empty world;
- binds every source's exact byte size and SHA-256 digest;
- requires the source list and precomputed declarations in canonical order;
- refuses symbolic links, unsupported files, missing files, unlisted files, and post-manifest byte
  changes anywhere in the recursive directory; and
- binds the pipeline to the checkout's model-manifest SHA-256.

The adaptation block is an already-produced inert conversational proposal input, not evidence that
this command invoked the named style model. Its required model/prompt/reference fields record the
proposal's actual upstream provenance. The command validates that provenance, derives reviewed
module/capability bindings from the closed backend registry, and never stores conversation text,
private media, CSS, markup, scripts, shaders, renderer programs, or layout in the recipe.

Precomputed artifact declarations have exact fields `artifact_id`, `kind`, `sha256`, `bytes`,
`producer`, and `use`. In v1, `use` must be `disclose-only`. There is no reviewed importer for
external COLMAP or splat work at this boundary, so the command records these artifacts as
`disclosed-not-consumed` and never pretends their work occurred in the live formation ledger.

## 3. What the command proves

One successful invocation performs these gates in order:

1. ingests every exact manifest source in a watched batch and projects formation from durable
   pipeline events;
2. reconstructs one stored `EvidenceAddress`, verifies its span digest, opens original bytes from
   the content-addressed store, re-hashes them, and lists their real ledger events;
3. reads the semantic graph, compiles an unconstrained capture Selection, builds an EvidencePacket,
   renders the deterministic answer, and runs the answer validator;
4. deterministically composes one stable region per live manifest source and labels it from the
   current `reconstruction_rung_is` assertion, using named source-first rung 4 when none exists;
5. previews a Companion-origin recipe proposal, creates two provenance-bearing refinements from
   the same base, discards the draft, applies one refinement, verifies stale rejection of the
   other, inspects their durable states, and rolls back to the original semantics;
6. creates two structural previews from one protected base and verifies that compare-and-swap
   rejects the stale one;
7. projects and signs an initial World Memory Package containing an explicit operational
   evaluation report;
8. starts a separate verifier process after removing database URL and common PostgreSQL credential
   variables from its environment;
9. repeats ingest, requires zero model calls and zero recomputed capture stages, reuses the exact
   spatial snapshot, and exports the new provenance state; and
10. tombstones one named capture, recomposes the surviving stable regions, exports again, verifies
    it independently, and records a value-redacted semantic package diff.

The repeat package root is expected to differ. A truthful World Memory Package includes the new
`stage_reused` ledger events, repeat evaluation, and package-parent lineage. Suppressing those facts
to force root equality would turn idempotency into missing provenance. Reuse is proved directly by
`model_calls: 0`, an empty `stages_run`, populated `stages_reused`, and the unchanged spatial
snapshot digest.

## 4. Outputs and fallbacks

The output directory contains:

- `package-initial/`, `package-repeat/`, and `package-after-deletion/`;
- canonical `evaluation-initial.json`, `evaluation-repeat.json`, and
  `evaluation-after-deletion.json`; and
- canonical `frontier-receipt.json`.

If a gate fails after output creation, the CLI also attempts to retain
`frontier-terminal.json` with the named gate and failure detail. Partial artifacts remain available
for diagnosis and are never presented as a successful receipt.

The evaluation documents intentionally mark consented-corpus metrics unavailable. This command has
no OGC-1 gold labels or blind split and does not turn an operational demonstration into an accuracy
claim. Receipt fallbacks separately identify unavailable vision, unavailable reconstruction,
source-first rung 4, absent precomputed work, and the deleted-region omission.

Generated test packages, generated photographs, content-addressed blobs, model responses, signing
keys, and real run receipts belong outside Git.

## 5. Executable evidence

- `tests/test_frontier_manifest.py` covers strict schema, exact inventory, hash changes, symbolic
  links, float refusal, duplicate content, and precomputed substitution refusal.
- `tests/test_frontier_demonstration.py` runs the full lifecycle on PostgreSQL: two initial model
  calls, zero repeat calls, evidence opening, supported answer, rung-4 fallback, structural and
  conversational recipe provenance/refinement/discard/apply, style stale rejection, rollback,
  three independently verified packages, one durable tombstone,
  surviving source preservation, and a semantic diff that names a removed capture.
- `uv run lint-imports` places `exulanica.orchestration` above every reusable boundary, so no product
  package can depend on the acceptance workflow.

The missing final evidence is one user-authorized run with an explicit real photo directory,
credential/hardware choices matching its configured modes, a user-supplied signing key, and outputs
retained outside Git.


## 6. Check before running

Run the same inputs through the pre-flight first:

```sh
EXULANICA_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test \
uv run exulanica-frontier preflight \
  --manifest /outside-git/frontier-build.json \
  --photo-dir /authorized/photos \
  --data-dir /outside-git/exulanica-data \
  --output /outside-git/frontier-run \
  --private-key /secure/location/wmp-ed25519.pem
```

It emits JSON with every independent check and an action for each failure, exits 0 when its local
checks pass, and exits 1 when blocked. It verifies the strict manifest, exact readable source
inventory, owner-only Ed25519 key, database/schema, existing screening needed by selected model
modes, separate input/output/store paths, destination permissions and available disk space. It
creates no directory, key, screening, database row or model cache. The demonstration runs these
checks again before model setup or provisioning.

Disk space uses a stated planning allowance: four times source bytes plus 1 GiB reserve, with
another 2 GiB when depth is selected, on each destination volume. This covers a development run's
store and three exports as a planning floor; it does not predict model output or guarantee that
inference will fit. Live credential validity, catalog availability, model weights and hardware
inference remain runtime checks. No model is loaded or called by this pre-flight.

For configured vision or depth, first intake the exact photographs through the existing intake
workflow and obtain valid authorization and screening in the manifest workspace. Vision alone may
use observation-only permission; geometry requires geometry permission. The demonstration never
creates synthetic exemptions or human screening for supplied photographs. With both modes set to
`unavailable`, capture-only execution remains available and states its fallbacks. The explicit
hosted-vision flag does not replace screening, and screening does not replace per-run permission.

## 7. Rehearse the complete output contract

```sh
uv run exulanica-frontier dry-run --output /outside-git/frontier-rehearsal
```

Choose a new directory. This command accepts no photographs, manifest or signing key. It generates
two deterministic geometric photographs locally, records synthetic authority for the bytes it just
generated, and executes the ordinary lifecycle with vision and depth unavailable. It never loads
a hosted model. The initial lifecycle truthfully reports intake reuse because the generated bytes
were intaken during preparation. Repeat ingest must still recompute no stages.

The new directory holds `photos/`, `frontier-build.json`, `data/`, a `0600` **throwaway-key.pem**,
`dry-run-receipt.json`, and `run/`. The latter has exactly the three packages, three evaluations and
`frontier-receipt.json` described in section 4. The dry-run uses a fresh random schema in the
permitted database, applies migrations only there, and drops that one schema on success or failure.
Required database-wide extensions must already be installed. Original generated photos and all
packages remain on disk for inspection. Do not use this throwaway key to establish production trust.

MEASURED 2026-09-08: the CLI rehearsal passed with declared fallbacks, three clean-process package
verifications, zero model calls, zero recomputed stages on repeat, one remaining region after the
capture tombstone, and its isolated schema removed. The independent tests compare retained capture,
artifact, tombstone, authorization, screening and migration-history rows before and after; all
remain identical. They also verify every original photo's bytes after the full lifecycle and prove
that deliberate failure cleans up only the rehearsal's schema.

## 8. Create and retain your signing key

The package loader accepts an unencrypted Ed25519 PKCS8 PEM. Keep it in an owner-only directory
outside this checkout, the photo directory, the store and all package output directories. Protect
and back it up with the operating system's encrypted storage; an encrypted PEM cannot currently be
loaded by this command. Do not paste the private key into a chat or put it in Git.

Run in a fresh shell, choosing your permanent private directory:

```sh
umask 077
set -o noclobber
frontier_key_dir="$HOME/.config/exulanica/keys"
mkdir -p "$frontier_key_dir"
chmod 700 "$frontier_key_dir"
openssl genpkey -algorithm ED25519 > "$frontier_key_dir/wmp-ed25519.pem"
```

`noclobber` prevents replacing an existing key. The `umask` makes the new file owner-only from the
first byte. Keep the same production key for the trust identity you intend recipients to verify;
key generation is a setup operation, not something to repeat for each export. Validate it with the
pre-flight, which reports its type without printing its contents.

MEASURED 2026-09-08: this exact creation procedure was executed in a fresh temporary directory with
a throwaway key. Its permissions were `0600`; the actual package loader accepted it, and a local
sign/verify round trip passed. No private key material was emitted. No production key was created.

## 9. The write boundary in detail

The personal demonstration writes content-addressed originals and derivatives under `--data-dir`,
model response cache there when vision is enabled, workspace database records (including partition
provisioning, ingest ledger, assertions, spatial/style changes and export records), and packages and
receipts under the new `--output`. It tombstones the one manifest source in that workspace. It does
not delete its original file. Partial run outputs may remain after a runtime failure.

It never rewrites the manifest, original photo files or supplied signing key. Input, store and
output directories must be separate and non-nested; nested symlinks inside an existing store are
refused. Existing output is refused without even adding a terminal receipt to it. The CLI performs
no schema migration. Runtime errors after creating this run's output may write its terminal receipt.
These boundaries are asserted by `test_frontier_preflight.py`, `test_frontier_demonstration.py` and
`test_frontier_dry_run.py`; they are not promises derived from a dry-run flag.

The observation answer is already pageable; the browser continues to require a complete graph.
MEASURED 2026-09-08: retained bowl responses contain 97,633,587 bytes for 15,005 points, or 4,973,392
bytes for a 500-point page. Paging cuts the answer to 5.094% of the whole. It still groups the entire
receipt server-side on every call. Fetching every page would require 31 requests for this scene,
retain the same final browser graph, and could combine different current jobs or consent states
because no snapshot identity binds the pages. The browser now rejects incomplete or inconsistent
answers. Bounded server work and progressive browser interaction remain separate follow-up work;
this change claims neither.
