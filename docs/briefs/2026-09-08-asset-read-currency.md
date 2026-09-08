# Check current permission at asset reads

Queued; not dispatched. Repository: `/Users/glendonchin/dev/Technology/orimera`.
Product/package: Exulanica. This brief precedes recipient-checkable World Read evidence.
Read applicable AGENTS.md, `docs/integration-screening-currency-2026-09-08.md`,
`docs/screening-currency.md`, and migrations 0037 through 0040, including their actual callees.

Proposed worktree: `/Users/glendonchin/dev/Technology/exulanica-asset-read-currency`.
Proposed branch: `codex/asset-read-currency`, from main containing `53039d4` and this brief.
Migration: NONE initially. A required SQL policy extension needs a concrete checkpoint and a
new migration number from the orchestrator; do not edit 0040 or allocate 0041 silently.

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
