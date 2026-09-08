# Start manual person-region authoring work

Status: completed and integrated on 2026-09-08, including the documented narrow backend extension.
This original dispatch brief is retained for scope review. See
`docs/integration-personal-review-2026-09-08.md`; do not restart this worktree.

Implement a bounded Exulanica browser workflow in repository
`/Users/glendonchin/dev/Technology/orimera`. Read applicable AGENTS.md,
`docs/integration-2026-09-08.md`, `docs/person-presentation-consent.md`, the person-consent route,
and the currently mounted review flow before editing.

Create worktree `/Users/glendonchin/dev/Technology/exulanica-manual-person-review`, branch
`codex/manual-person-review`, from current main containing `1353a21`.
Migration: NONE. The existing authenticated region-edit route already accepts `add` plus an
outline. Do not create a replacement API or change consent policy.

Goal: a reviewer can identify a person that no detector proposed, draw a region on the correct
photograph, persist it through the existing route, reload it and continue review. Current browser
code only offers confirm/delete for existing regions. An account-holder review is not proof that
the photographed subject personally authenticated or consented.

Writable file set:
- `web/packages/app/src/person-review-api.ts`.
- `web/packages/app/src/ui/person-review.ts` and `ui/reconstruction-inspector.ts`.
- New `web/packages/app/src/ui/person-region-editor.ts`.
- `web/packages/app/src/style.css`, only styles for this editor.
- `web/packages/app/test/person-review-api.test.ts` and `person-review.test.ts`.
- New `web/packages/app/test/person-region-editor.test.ts`.
- New `docs/manual-person-region-review.md` and
  `docs/patches/manual-person-review-main.patch` for the reserved integration patch.
- New `scripts/record_manual_person_review_evidence.py`, generated
  `docs/evaluation/*-manual-person-review.json`, and its uniquely named artifact directory.

`web/packages/app/src/main.ts` is RESERVED for serialized integration. Read its
`loadPersonReview`, `sourceForCapture` and inspector setup. Produce an exact minimal patch in the
owned patch file for the orchestrator to review and integrate; do not modify main.ts in your
implementation commits. Report this dependency early. Do not claim the browser feature is done
until that patch has been integrated and the real mounted flow has been exercised. This scope
does not authorize backend, graph-client, presentation, migrations, stage registries or package
dependency changes. Ask the orchestrator for an exact extension if needed, not the operator for
routine design choices.

Follow the existing visual language. Use image coordinates consistent with the server's outline
contract, including resizing and letterboxing. Provide a keyboard-usable way to author a region,
clear cancel/submit behavior, error feedback and no silent loss. Never offer an old photograph's
controls against a newly selected capture. Do not fetch protected originals through a new bypass;
reuse the existing authorized media path and disclose when an editable view is unavailable.
Adding a region must not manufacture consent or mark unseen photographs reviewed.

Execute tests from the editor gesture through the API payload, including an empty detector
inventory, resizing, invalid outline, cancellation, server refusal, repeat submission and a
capture switch while a response is pending. After serialized main.ts integration, exercise the
actual browser against the real authenticated route in an isolated test workspace: add, reload,
and verify the stored region. Use clearly labelled generated images. Record screenshot/evidence
bindings and an executed negative control that removes the add wiring and fails the named path.
If browser integration is still pending, report that as pending, not as a passed exit.

Evidence records require exactly three top-level keys, canonical record_sha256, no floats and
predecessor_record; use the recorder, never rewrite old dated records. No real personal data,
hosted model calls or GPU spend is authorized. Run full backend pytest against
`postgresql://localhost:5433/exulanica_spine_test` using EXULANICA_TEST_DATABASE_URL, Ruff,
import-linter, and web typecheck, boundaries and tests before handoff. Coordinate full suites
with the orchestrator rather than saturating the machine.

Use one-line imperative commits, no trailers, authorship notices or em dash characters; stage
explicit paths. Report the commit tip, reserved patch, actual executed path, evidence, limitations
and any modularity/scalability tradeoff. Do not merge or push. The orchestrator integrates and
independently verifies the complete flow.
