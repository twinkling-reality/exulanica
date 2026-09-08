# Repair two observed development-preview handoffs

Status: proposed, not dispatched. Observed against main ad4acd5 in the in-app browser at
http://127.0.0.1:5178/?preview=1 on 2026-09-08, at a 1280 by 720 viewport. This is a generated-data
development preview with no database, not a live retained-data or consent workflow verification.

## What was observed

The preview opens with its synthetic/read-only document title and displays the courtyard image.
Index opens, Mara's three occurrences appear, Locate in Atlas initiates travel and closes detail,
and Map exposes all four named regions. Selecting Unsent letter initiates travel to that region.

Two reproducible integration failures take priority over visual redesign:

1. Index > Mara > first Open the source returns 'this evidence is not available to this session'.
   graph-client/src/client.ts::evidenceBytes requests /evidence/{handle}/masked. The preview API
   slices everything after /evidence/ as the evidence ID, including /masked, so previewSource
   cannot resolve it. The preview test calls the old /evidence/{id} path directly; it does not
   exercise the current production client against the preview responder. The source image in the
   world is loaded through a different fixture URL and therefore still displays.
2. Browser warning: 'unexpected .opm format field: orimera-point-map'. The preview loader reads
   public/fixtures/memory/glasshouse-courtyard.opm using the production decoder, which requires
   exulanica-point-map. All four grouped-photo controls show reconstruction unavailable. This
   establishes a format rejection, not proof that all remaining container fields are compatible.

Visual observations to revisit after those repairs: the large Proof Lens explanation competes
with arrival before the user enables it; four repeated reconstruction notices add noise. These
are product-review judgments, not measured accessibility defects or permission to redesign.
No responsive/mobile or production-write usability claim was established by this walkthrough.

## Proposed implementation ownership

Repository: /Users/glendonchin/dev/Technology/orimera. Separate worktree:
/Users/glendonchin/dev/Technology/exulanica-preview-handoffs, branch codex/preview-handoffs from
current main. Migration NONE. No database slot, backend full suite or model execution needed.

Writable set only:
- web/packages/app/src/dev/preview-api.ts.
- web/packages/app/test/preview.test.ts.
- web/packages/app/public/fixtures/memory/glasshouse-courtyard.opm, only through a documented,
  validated local format migration retaining the old/new hashes and unchanged point payload.
- New scripts/migrate_preview_point_map.py, if needed for reproducible fixture migration.
- New docs/preview-handoffs.md, recording observed failures, exact conversion and browser results.

All other files are read-only, especially production graph-client behavior, production decoder,
main.ts, API/consent policy, images, README and historical evidence. Do not accept the legacy
format globally to hide a stale fixture. If the current container cannot be established from
existing bytes without fresh inference, report the exact incompatibility and smallest extension;
no model downloads or calls are authorized. A migrated fixture is not a new reconstruction run.

## Acceptance proportional to the change

Exercise the real ExulanicaClient evidenceBytes path against previewApiResponse for an available
source and the intentionally unavailable source. Preserve read-only rejection of mutation
methods and refusal for unknown or malformed paths. Keep original and masked route meanings
explicit within the synthetic fixture; do not weaken the production client to fit the mock.

Decode the checked-in point-map bytes with the actual current decoder after the reproducible
conversion. Check unchanged point payload, dimensions/attributes and any bound metadata rather
than blindly replacing a substring. Leave old evidence records untouched.

Run focused preview/decoder checks plus web typecheck and boundaries. Execute the real browser:
Index > Mara > Open the source shows the expected synthetic photograph; Locate in Atlas and Map
remain usable; Unsent letter stays explicitly unavailable; courtyard reconstruction loads without
the format warning. Report whether any second failure remains. No full backend campaign.

One-line imperative commits, no trailers/authorship notices/em dash characters, explicit staging.
Return tip, exact file set, targeted checks, browser results and limits. Do not merge or push.
