# Manual person-region authoring

Implementation branch: `codex/manual-person-review`, based on main `1353a21`.
Migration: none. Browser acceptance: **pending serialized main.ts integration**.

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

Apply `docs/patches/manual-person-review-main.patch` in serialized integration. The patch adds
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

After integration, use an isolated generated-image test workspace against the real authenticated
route. Open the actual app inspector, add a region, reload, verify the stored region and owner
receipt, and confirm another capture stays unreviewed. Bind screenshots to the generated image,
capture, request and stored row. Execute a negative control removing the integrated add wiring
and require that same browser path to fail. No browser screenshot or persistence result is
claimed here. Full-suite logs will be retained after the orchestrator assigns a machine slot.
