# Check current permission at asset reads

Dispatched to `codex/asset-read-currency`; checkpoint approved below.
Repository: `/Users/glendonchin/dev/Technology/orimera`.
Product/package: Exulanica. This brief precedes recipient-checkable World Read evidence.
Read applicable AGENTS.md, `docs/integration-screening-currency-2026-09-08.md`,
`docs/screening-currency.md`, and migrations 0037 through 0040, including their actual callees.

Proposed worktree: `/Users/glendonchin/dev/Technology/exulanica-asset-read-currency`.
Proposed branch: `codex/asset-read-currency`, from main containing `53039d4` and this brief.
Migration: 0041, assigned at checkpoint `a6ff18b` below. Do not edit old migrations.

Goal: prevent viewer asset paths from serving obsolete privacy derivatives or geometry whose
persisted source lineage cannot support current permission. Admission is already guarded;
delivery is a separate operation. A current mask found for a capture does not prove that an
older geometry artifact used it. Do not infer lineage from timestamps or matching-looking rows.

Writable file set:
- `exulanica/api/routes/evidence.py`, restricted to masked-view delivery and a necessary shared
  read guard. Original/crop/by-URI policy changes require the checkpoint below.
- `exulanica/graph/geometry.py` and `exulanica/graph/scene_geometry.py`, existing descriptor and
  asset-reader seams only.
- `exulanica/world/repository.py`, source availability and mask selection only; preserve review
  capture identity while required bytes are unavailable.
- New `tests/test_asset_read_currency.py`; relevant existing cases in
  `tests/test_world_api.py`, `tests/test_geometry_delivery.py`, and
  `tests/test_evidence_withdrawal.py`.
- New `docs/asset-read-currency.md`, `scripts/record_asset_read_currency_evidence.py`, generated
  `docs/evaluation/*-asset-read-currency.json`, and uniquely named evidence directories.

Everything else is read-only, particularly main.ts/frontend, dependencies, API registration,
stage registry, consent and mask producers, World Read contracts, migrations and RLS policy.
Do not import ingest into graph to reuse a helper; obey the existing architecture boundaries.

First document the read contract and call graph before implementation. Distinguish owning-workspace
original citation resolution, masked viewer images, point maps and trained geometry. Original
citations must retain exact-byte semantics: never substitute masked bytes under an original
digest. Report any required original/crop/by-URI authorization change as a concrete scope/policy
checkpoint. Likewise report missing producer lineage rather than inventing it or silently
regenerating a historical record.

State the authorization instant and read-versus-withdrawal ordering precisely. Check the actual
read-only database role, transaction lifetime and every writer whose lock would establish that
ordering. Migration 0040's admission lock alone is not proof that delivery is serialized with
withdrawal. Do not hold a write transaction across arbitrary streaming/network delivery or promise
to retract bytes already delivered. If a sound contract needs another writable file or migration,
report the smallest extension and evidence before implementing outside the set.

Execute labelled generated-media requests through real authenticated production routes with
real persisted masks and geometry lineage. Cover changed outline, expiry without a write,
withdrawal, required mask absent/stale, rebuilt mask, unchanged input, no-person captures,
deleted capture, missing legacy lineage, byte ranges and cross-workspace refusal. A geometry
artifact with old source inputs must not become valid merely because a new mask now exists.
Show unavailable metadata and withheld bytes agree, while manual review remains reachable.
Exercise controlled read/write interleavings for the stated ordering. Name each unresolved read
surface explicitly; no global disclosure claim from one masked route's tests.

Retain route-to-byte evidence and killed controls whose own exact selectors have FAILED lines.
Generate the canonical three-key digest-bound record with no floats and predecessor_record
pointing to the screening-currency integration record. Preserve accepted historical records.
Run full backend gates with EXULANICA_TEST_DATABASE_URL set to
`postgresql://localhost:5433/exulanica_spine_test`, locked pose/reconstruction extras, Ruff,
import-linter, and web typecheck/boundaries/tests. Reserve the serialized suite slot.

No retained-public migration, real personal media, hosted models, credentials, GPU spend, merge
or push. Stage explicit paths; one-line imperative commits without trailers, authorship notices
or em dash characters. Report tip, scope, executed criteria and remaining activation limits.

## Scope checkpoint approved on 2026-09-08

The orchestrator inspected `a6ff18b`'s contract against original/crop/by-URI routes, source URL
selection, graph/World Read transactions, 0039/0040 locks and the masked-splat refusal. These are
real integration dependencies; the checkpoint's role probe is not executed delivery acceptance.
This approval supersedes the narrower pending restrictions above only as specified here.

Additional writable files:
- New `exulanica/migrations/0041_guard_asset_reads_with_current_permission.sql`: read predicates,
  explicit-time evaluation, lock helpers and dependency mutation triggers on existing tables.
  Replacement function/trigger definitions belong here; keep 0039/0040 bytes unchanged. No new
  workspace table, RLS-count change, table-write grant or BYPASSRLS authority is approved.
- All three original/crop/by-URI authorization seams in `exulanica/api/routes/evidence.py`.
- `exulanica/api/routes/graph.py` and `exulanica/api/routes/world_read.py`, transaction/policy
  composition only. Preserve snapshot consistency, routes, wire schemas and release scope.
- New `exulanica/graph/asset_read_policy.py` if a shared delivery helper is necessary within
  existing architecture boundaries. No graph-to-ingest import or new spine module.
- Relevant regression cases in `tests/test_world_read_route.py`, `tests/test_world_read_bundle.py`
  and `tests/test_training_export_postgres.py` for snapshot compatibility and lock interaction.

Policy decision: existing sessions do not distinguish privileged original review from viewing.
Do not invent a privilege through a query parameter, route name, header or workspace ownership.
For capture-backed person images, original, crop and by-URI delivery must refuse when current
person-presentation policy requires masking or withdrawal/deletion blocks the source. Crops do
not bypass that check on the assumption that a person lies outside the crop. Originals still
return the exact cited bytes when permitted, otherwise refuse; never return a mask under the
original digest. Route all future viewer image references through /masked, including no-person
images. Verify old saved original URLs are refused after permission changes. This does not grant
new training or reconstruction permission and must not apply a geometry-purpose prerequisite to
ordinary citation media. Preserve existing non-person/non-image evidence semantics. Ambiguous
capture mappings must not let one permissive duplicate override a restrictive current mapping.
Document missing legacy identity explicitly and refuse where required authorization cannot be
established. Keep manual review reachable without a new unmasked reviewer bypass.

Transaction decision: preserve REPEATABLE READ READ ONLY graph/World Read snapshots. Introduce
snapshot-compatible explicit-time read predicates rather than invoking 0040's READ COMMITTED
lock inside them or downgrading every query globally. Metadata describes its consistent snapshot
and is not a permission token for later byte delivery. Do not claim freshness after a lock wait
that retains an old snapshot. Byte-serving requests need a fresh final permission evaluation at
one database instant after the policy lock, using the artifact's actual input lineage and a
locally buffered, digest-verified payload. Release locks before network delivery. Each range
request reauthorizes. Writers ordered before that check must be visible; later changes or expiry
affect later requests and do not promise retraction. If any World Read path embeds source bytes,
it also needs this byte-delivery rule; a snapshot label cannot exempt embedded bytes. Do not add
wall-clock values to immutable provenance, relabel receipts or claim offline withdrawal knowledge.

Lock decision: 0041 may coordinate the exact dependency writers within SQL, including the
occurrence/entity/dependency/assertion and stage-registry dependencies found in the checkpoint.
Retain a written table/event dependency inventory and audit old/new workspace moves, cascades,
direct SQL, purge and publication. Establish and test one order across privacy, training, read
and purge locks, including cross-workspace and global stage mutations. Merely naming a trigger
to sort first does not prove transaction-wide ordering when writers already hold another lock.
Do not weaken existing admission/training serialization. If a production Python caller must
change to establish ordering, report that exact file/call site with the failing interleaving;
that is the remaining extension checkpoint, not a reason to pause the already authorized SQL
and read work. Runtime checks must execute as the actual SELECT-only non-owner/non-BYPASSRLS
role, without fallback to the writer connection or SECURITY DEFINER privilege escalation.

Geometry decision: omit policy-refused point-map descriptors using the existing wire contract;
do not label present-but-forbidden bytes as bytes_missing. No geometry API state literal or
frontend schema extension is needed. Test metadata omission and direct-ID byte refusal together.
Masked splat production stays outside this task. Validate real persisted lineage where available;
refuse unsupported or missing lineage. Constructed fixtures cannot prove successful masked
training. A rebuilt mask must never revive geometry built from obsolete original inputs.

Serialized suite reservation: this task exclusively owns Exulanica's isolated database/full-gate
slot from this approval until handoff or explicit release. Other implementation tasks were idle
when assigned. The orchestrator will not run a competing full suite; request handoff before its
independent integration gates. Use only the approved test URL and isolated schemas, clean them
up, and retain intermediate failures. No retained-public migration or runtime activation is
authorized. Record the approval as a successor to the immutable checkpoint evidence; do not
rewrite that record to make the earlier investigation look like executed acceptance.

Fixture assertion extension approved after the first full backend run (2112 passed, 3 skipped,
1 failed): in `tests/test_world_style_postgres.py`, only the expected evidence_path assertion in
`test_available_source_metadata_comes_only_from_authorised_local_evidence` may change from
`/evidence/{span_id}` to `/evidence/{span_id}/masked`. The orchestrator checked the failing log
and production URL selection: this image now uses the viewer route as explicitly required above.
Preserve the availability, media dimensions, local-reference, capture identity and subsequent
privacy assertions and all fixture setup. Retain the first-run failure as intermediate evidence.
The task retains the serialized suite slot through handoff.

Integration evidence repair authorized on 2026-09-08 after candidate `d434fea`, rebased unchanged
to `d4cffba`, failed the independent full backend gate: 2117 passed, 3 skipped, 1 failed.
`test_retained_evaluation_records_contain_no_personal_path_or_credential_material` found fourteen
absolute checkout paths in the executed envelope's commands.argv. The recorder normalized logs
but retained raw sys.executable and mutant script paths in command metadata. Its full suite ran
before emitting the new envelope; the later digest-only verification did not exercise this rule.

The existing recorder file is authorized for a narrow fix: normalize retained argv paths while
executing the real argv, and verify the newly written envelope with the retained-record checks
before declaring success. Do not weaken the test, omit command provenance or claim that canonical
digest verification also checks disclosure rules. Preserve intermediate logs and the independent
failure at `/tmp/exulanica-asset-read-integration-d4cffba/backend.log` with checkout-prefix
normalization in a uniquely named retained artifact directory.

Only the unpublished executed candidate envelope (old record digest
`582004804995515f8635f666d65bb82a879c8ad620190773867c3bfb5174876b`) and its dependent verification
envelope (`9d502d1fee24ae76c0ef646d247096709086396987b089e4243ca85a2649e597`) may be regenerated
through code for corrected command provenance and bindings. Record the replaced hashes and
reason explicitly. No hand-editing JSON; no relocation of defective envelopes to evade the
retained-record rule; no rewrite of the valid checkpoint or any accepted record on main. A
branch-history correction is permitted if needed, with original/replacement tips recorded.
Preserve real executed logs and historical source bindings. This is evidence repair, not a
feature-scope extension or approval to claim runtime defects from an envelope failure.

The owner again holds the exclusive isolated database/full-suite slot until renewed handoff.
Re-run gates appropriate to the corrected recorder and include a post-generation retained-record
check on the actual final candidate. The orchestrator will independently verify the final tree
after handoff. Main remains unmerged; no public migration or push is authorized.
