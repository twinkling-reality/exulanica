# Manual person-region authoring

Implementation branch: `codex/manual-person-review`, based on main `1353a21`.
Migration: none. Browser acceptance: **executed on integrated `2af3049`**.
The implementation branch keeps main.ts unchanged; the orchestrator owns integration.

The inspector review panel accepts an editor even when the detector inventory is empty.
The editor uses only the existing authorized source descriptor. Missing or failed media disables
submission and explains why. It never requests an original through a separate endpoint.

Drag between two corners inside the photograph or enter Left, Top, Right and Bottom with the
keyboard. Coordinates are integers in millionths of normalized display space. The editor reports
`shape: box` with a four-point polygon, not a measured silhouette. Letterboxes are excluded;
image dimensions and current layout are read for each gesture, and the overlay follows resizing.
The box must cover an area. Cancel clears the draft explicitly without deleting stored regions.

Save posts to the existing authenticated `/person-regions/{capture_id}/edits` route. It sends
only an add action, region key, box shape and outline. No subject, consent or screening receipt
for another photograph is manufactured. The reviewer remains the account holder; this does not
establish that the photographed person authenticated or consented.

Drafts and save outcomes live in a session-owned map keyed by capture. Switching photographs
retains them; leaving the app loses unsaved drafts, as the panel discloses. Pending and successful
submissions disable repeat saves. A failed save keeps its draft and key. The proposed main adapter
reads the current inventory before a retry so an uncertain successful response is not written
again. Reload review reads the server inventory; it does not mark any photograph reviewed.

Manual region keys are random 32-byte identifiers accepted by the existing route. They are not
the detector's 16-by-16 occurrence key, because the authorized media descriptor does not expose
all inputs to that derivation and this scope does not authorize a new backend contract. This
preserves distinct manually drawn regions but does not automatically reconcile them with future
detector proposals. Drawing the same region as a new draft can create a second region. Draft
memory grows with photographs actually opened in this session, not the whole capture inventory.

## Reserved integration

The orchestrator applied `docs/patches/manual-person-review-main.patch` in serialized integration. The patch adds
session draft ownership, generation checks for asynchronous review loads, immediate clearing on
capture changes, explicit reload, and the existing authorized `sourceForCapture` descriptor.
The onAdd adapter uses the existing API and checks whether the same draft key already landed.
It does not alter backend routes or consent policy. The implementation commits leave main.ts
unchanged. `git apply --check` passed against the branch's base main.ts.

## Executed checks and remaining acceptance

Focused tests cover pointer gesture through the authenticated transport payload from an empty
detector inventory, letterboxing and resizing, keyboard fields, invalid outline, cancellation,
HTTP refusal, repeated submission, retained key on retry, unavailable source, and a capture
switch while a response is pending. The executed negative control removes editor mounting and
fails `draws a missed person from an empty detector inventory through the authenticated API
payload`. It is a component control, not the still-pending mounted-browser control.

The mounted browser was exercised against real authenticated routes in two disposable generated
workspaces. The accepted replay is `artifacts/2026-09-08-manual-person-review/reload-fixed`,
at integrated head `2af30493fab6a50757e0f6571d1bf14cee525e57`. It draws on a labelled 800x400 image,
saves once, reloads the entire app, reopens the saved region with identical coordinates and key,
and verifies the authenticated owner actor in PostgreSQL. There are zero subjects and zero
presentation consent receipts. The other photograph remains unreviewed. The displayed normalized
coordinates are independently recomputed from the actual image layout and pointer endpoints.

The named browser control is `mounted-empty-detector-person-authoring`. Its selector is the button
with exact accessible name `Save person region`. The intact empty-detector path passes. Removing
only the editor mount makes that path fail with `Save person region is missing`. Exact source
restoration restores the passing path. Both scratch schemas were dropped, both service ports
closed, and the integration checkout was clean after the experiment. Screenshots and stored rows
are bound by `2026-09-08-manual-person-review.json`, produced by the recorder.

The first run at `098ae51` is retained separately from the accepted `reload-fixed` replay. It saved
and reloaded the review successfully, but a full app reload exposed a metadata gap: privacy-withheld
source media dropped its capture IDs, so the source-only inspector could not reopen the review.
The orchestrator explicitly extended ownership to `_source_from_row` in `exulanica/world/repository.py`
and the relevant cases in `tests/test_world_api.py` and `tests/test_world_style_postgres.py`.
That correction retains IDs only for a live, otherwise-resolvable source withheld for a pending
mask. State stays unavailable; evidence paths and asset references stay absent. Deleted, missing,
purged and foreign-workspace behavior is unchanged. Existing citation resolver policy is unchanged.

The full backend suite at `358be0b` passed 2058 tests with 3 skips. Import contracts passed.
Initial Ruff and web failures caught fixture formatting and palette literals; corrected runs pass.
At corrected frontend tip `7af8ee2`, typecheck, boundaries and all 876 web tests pass. At `f3a601f`,
20 focused backend tests verify pending-mask identity, unavailable byte references, masked-route
refusal, deletion and workspace isolation; Ruff and import-linter pass. Per orchestrator scheduling,
the final independent full backend suite after that narrow correction is the orchestrator's gate.
No final full-backend result is inferred from the earlier run.
