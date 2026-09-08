# Start personal admission and re-screening work

Status: completed and integrated on 2026-09-08. This is the original dispatch brief, retained for
scope review. See `docs/integration-personal-review-2026-09-08.md`; do not restart this worktree.

You are implementing one bounded Exulanica workflow. Repository:
`/Users/glendonchin/dev/Technology/orimera`. The product and package are Exulanica.
Read AGENTS.md wherever applicable, `docs/integration-2026-09-08.md`,
`docs/frontier-demonstration.md`, and the existing privacy/admission code before editing.

Create worktree `/Users/glendonchin/dev/Technology/exulanica-personal-admission` on branch
`codex/personal-admission-rescreen` from current main, which must contain `1353a21`.
Migration: NONE. Migration 0039 exists in code; do not allocate 0040 or apply migrations to public.
Use isolated schemas on `postgresql://localhost:5433/exulanica_spine_test` for execution.

Goal: an operator can admit exact personal capture bytes, record the appropriately scoped
screening, run the permitted ingest pass, review/mask, re-screen, and retry without fabricating
benchmark provenance or asserting that an empty inventory means no people. Build a runnable
command through `python -m exulanica.ingest.personal_admission_command`, with a strict input
manifest and an explicit actor, workspace, authority basis and purpose. It must be a real caller,
not a new helper exercised only by tests. Do not duplicate existing receipt storage or policy.

Existing seams: `authorize_personal_capture`, `record_person_detection_screening`, and
`record_human_screening` in `ingest/privacy.py`; person review and mask stages; the frontier
preflight consumes already-persisted exact-capture screenings. The benchmark route is not a
personal admission route. Human review already has a benchmark production caller. A detection-only
receipt permits observation and does not permit geometry. Account authority is not subject consent.

Writable file set:
- New `exulanica/ingest/personal_admission.py` and `personal_admission_command.py`.
- `exulanica/ingest/privacy.py` and `exulanica/ingest/pipeline.py`, only if needed for the
  admission/re-screen/retry path. Preserve existing callers and avoid a general pipeline refactor.
- New `tests/test_personal_admission_command.py` and `tests/test_personal_admission_flow.py`.
- `tests/test_person_detection_screening.py` for relevant regression coverage.
- New `docs/personal-admission.md`, `scripts/record_personal_admission_evidence.py`, and generated
  `docs/evaluation/*-personal-admission-flow.json` with its uniquely named artifact directory.

All other source is read-only. In particular: no frontend, orchestration changes, API registration,
STAGES changes, spine modules, migrations, shared RLS counts, dependency files or world-package
changes. If an existing seam makes this file set incoherent, report the exact smallest extension
to the orchestrator before editing it. Do not work around it with duplicated policy.

Execute the command in an isolated schema against labelled generated images, then execute the
existing frontier preflight against its persisted receipts. Exercise missing/expired authority,
wrong source bytes, cross-workspace capture, detection-only geometry refusal, manual no-person
review, a person requiring masking, stale mask after a changed decision, retry and idempotency.
Use the real receipt and database policy path; any scripted detector must be labelled as such.
Show the exact successful command and the exact refusal commands. No personal photos, credentials,
external model calls or GPU expenditure are authorized by this brief. Pending migration must
produce an actionable refusal, never an implicit public migration.

Record evidence with exactly three top-level keys, a recomputable record_sha256, no floats and
an explicit predecessor_record. Generate it with the recorder; never hand-edit historical records.
Include at least one executed negative control that fails the named end-to-end invariant.

Before reporting ready, run full gates: `EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test uv run pytest`,
`uv run ruff check .`, `uv run lint-imports`, `pnpm --dir web run typecheck`,
`pnpm --dir web run boundaries`, and `pnpm --dir web run test`. Coordinate full-suite timing with
the orchestrator. If the known slow-stage lease test fails under load, rerun that test alone.
Do not impose a twenty-commit quota. Make coherent one-line imperative commits, no trailers,
authorship notices or em dash characters. Stage explicit paths. Report tip, scope, executed
criteria, retained evidence, tradeoffs and what has not run on real data. Do not merge or push;
the orchestrator will rebase, independently verify and integrate.
