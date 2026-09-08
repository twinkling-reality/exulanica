# Start recipient-checkable World Read evidence work

Ready for dispatch after the asset-read integration; no task for this brief has been started.
See `docs/integration-asset-read-currency-2026-09-08.md` for verified read behavior and remaining
deployment, producer and real-data limits. This brief adds recipient evidence, not activation.
Repository: `/Users/glendonchin/dev/Technology/orimera`; product/package: Exulanica.
Read applicable AGENTS.md, `docs/integration-2026-09-08.md`, `docs/phase-10-tickets.md` P10-1/P10-5,
`exulanica/graph/world_read.py`, `read_consent.py`, and the landed training export implementation.

Create worktree `/Users/glendonchin/dev/Technology/exulanica-world-read-evidence`, branch
`codex/world-read-evidence`, from current main containing `188e20c`.
Migration: NONE. If indispensable persisted evidence is missing, identify the producing seam and
request a separate scoped follow-up; never invent lineage or allocate a migration without an
orchestrator reservation. Migrations 0039 through 0041 are already committed.

Goal: add recipient-checkable recorded person-consent evidence and actual geometry source
lineage to World Read. Current view entries carry camera/capture IDs without photo references;
geometry carries output digests without derivative lineage; release is internal_only. Training
WMP 1.1 is a separate contract, not a completed World Read implementation. Reuse its established
semantics where valid, not its authority claims by analogy.

Writable file set:
- `exulanica/graph/world_read.py` and `exulanica/graph/read_consent.py`.
- New `exulanica/graph/world_read_evidence.py` and `world_read_verification.py`.
- `tests/test_world_read_bundle.py` and `tests/test_world_read_route.py`.
- New `tests/test_world_read_evidence.py`.
- New `scripts/record_world_read_recipient_evidence.py` and
  `scripts/verify_world_read_recipient_evidence.py`.
- New `docs/world-read-recipient-evidence.md`, generated
  `docs/evaluation/*-world-read-recipient-evidence.json`, and its uniquely named artifact directory.

Everything else is read-only, especially frontend/main.ts, API registration, graph payload and
snapshot contracts, ingest/privacy.py, consent writers, world_package/, migration/RLS files,
STAGES and the existing World Read recorder/control scripts. Preserve scene and place addressing.
Do not widen scope just to make a control green; report the exact extension required.

First write the wire/digest contract and its compatibility consequences in the owned design note.
Separate immutable recorded evidence from any evaluation at an explicit time. Presence, naming,
likeness, training permission and authority are distinct. Do not read clock_timestamp-derived
state into recorded digest inputs. Do not claim an offline recipient can discover later
withdrawals. Include all evidence needed to check a recorded conclusion, or return a specific
unavailable reason. Avoid disclosing unneeded names or private evidence in this owning-workspace
contract. Keep release.state internal_only throughout this brief; added provenance does not by
itself establish permission to redistribute.

Trace each geometry entry to its actual persisted source/build manifest. A matching-looking
current mask is not evidence that an old geometry artifact used it. Cover unmasked source bytes,
masked derivatives, trained geometry and missing legacy lineage without guessing. Keep generated
geometry separate. This brief does not serve posed photo bytes, implement entity-addressed reads,
change live media authorization, or solve masked Gaussian training.

Execute a real-database route-to-canonical-bundle-to-clean-process verification path on labelled
fixtures. Check digest stability across elapsed time/expiry without writes, digest movement when
recorded evidence changes, omission/tampering, output-to-source mismatch, stale derivative lineage,
withdrawal, cross-workspace isolation, and scene/place compatibility. A unit test of an unused
projection helper is insufficient. Include negative controls that break the exact consent and
lineage checks and demonstrably fail their named selectors.

Generate the dated evidence envelope with exactly three top-level keys, canonical record_sha256,
no floats and predecessor_record. Never edit old records. Run full gates: backend pytest using
EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test, Ruff, import-linter,
and web typecheck/boundaries/tests. Coordinate suite timing. No public migrations, personal data,
hosted calls or GPU spend. Use coherent one-line imperative commits, no trailers, authorship
notices or em dash characters; stage explicit paths. Report commit tip, contract, executed
recipient path, evidence and unresolved release/real-data limits. Do not merge or push.
