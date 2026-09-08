# Development preview handoff repair

Source: local main `d2234f8818650958d7cfcd0c2b22e70796a20cfb`. Branch:
`codex/preview-handoffs`, separate worktree `exulanica-preview-handoffs`.
Migration: NONE (no database schema change). This is synthetic, read-only development
preview acceptance, not retained-data, consent, reconstruction-quality or world-model validation.

## Source route

The production ExulanicaClient requests `/evidence/{id}/masked`. The old preview
interpreted `/masked` as part of the ID. The responder now accepts the exact original
and masked routes; both serve the same catalogued synthetic photograph. It has no
consent resolver or masked derivative. Production client, original citation semantics
and permission policy are unchanged. Mutation methods remain forbidden; malformed,
unknown and extra path segments remain unavailable. Unsent letter has no source bytes.

## Reproducible retained-file conversion

The original OPM was ignored/untracked in the orchestrator checkout, so creating this
worktree did not copy it. That original file is untouched. The migrated file is explicitly
tracked here. Existing bytes established OPM/2 compatibility: magic OPM1, version 2,
190570 points, local frame +Y/-Z, metric metres, source 1280x960, model 512x384,
position float32x3, color normalized uint8x4 with support alpha, tags uint16x2.

Only the raw format token changes from `orimera-point-map` to `exulanica-point-map`.
Header length grows from 1191 to 1193; existing ASCII-space padding shrinks from 97 to
95 bytes. All section offsets, all other raw metadata, and bytes from offset 1296 onward
are identical; total length remains 3812696. Current validate_opm validates every point,
bounds, tags, dimensions and container metadata. The actual frontend decodeOpm accepts
this file. Its test restores the old token, length and padding and matches the full old
hash, proving that no other bytes changed. It also confirms the legacy format still fails.

SHA-256:

- Original: `3d6712872eb05bd8b012b3f1e1ddf90cce17fe669fcd8b4360354d1909d096e2`
- Migrated: `939ebd1b36d49bc0f6a2f190bfa4030c8f91cf2f59276ed48c13f62a339f5f27`
- Unchanged position: `4231851ec87daa844efe70041732f1c76da0da28f54d00184b686193390eecda`
- Unchanged color: `e55e42effbd72208ec41ec77a757c07f0f4d0dd1904a3bfc26be56d086f78fe9`
- Unchanged tags: `3a966de1231ebcac93e52104a772cf057df2f585037c5f111d074dfabfd8daa7`

From this worktree, using the existing project Python environment:

```sh
PYTHONPATH=. /Users/glendonchin/dev/Technology/exulanica-posed-view-bytes/.venv/bin/python scripts/migrate_preview_point_map.py /Users/glendonchin/dev/Technology/orimera/web/packages/app/public/fixtures/memory/glasshouse-courtyard.opm web/packages/app/public/fixtures/memory/glasshouse-courtyard.opm
```

The script pins the exact original hash, validates before writing, refuses unrelated
existing destination bytes and is reproducible against the untouched source. Repeated
conversion matched the checked-in output. Three negative controls (already migrated,
truncated and one-bit-changed input) each refused the unreviewed hash.
No inference, model download or model execution occurred.

## Executed acceptance on 2026-09-08

- `pnpm --dir web exec vitest run packages/app/test/preview.test.ts packages/atlas-react/test/opm.test.ts`: 31/31 pass.
- Real client test requests available and unavailable `/masked` paths, compares returned
  photograph bytes exactly, checks JPEG type and the unavailable API error.
- Route negative controls cover bad percent encoding, encoded slash, unknown ID,
  extra suffix, region path, trailing slash and invalid URL; mutation verbs refuse each.
- `pnpm --dir web run typecheck`: pass.
- `pnpm --dir web run boundaries`: pass, 370 modules and 1177 dependencies.
- `git diff --check`: pass.
- Actual in-app browser at `http://127.0.0.1:5181/?preview=1`: synthetic read-only title;
  Index > Mara > first Open the source displays the expected courtyard photograph
  (person, glasshouse and blue bicycle), visually inspected. Locate in Atlas closes
  detail and announces travel. Map exposes four named regions; selecting Unsent letter
  announces travel. Its Index occurrence has a disabled Source unavailable control.
- Browser console warning/error capture was empty after load and navigation. The
  startup awaits the courtyard loader, whose catch logs failures: the old format warning
  is absent. This plus the current decoder test establishes loading, not visual quality.

## Remaining second failure and scope

All four grouped-photo controls still label reconstruction unavailable, including the
loaded courtyard. Read-only tracing identifies main.ts:1656: sourceRegions excludes only
islands in current.reconstructionScenes. The preview graph has no reconstruction scenes,
while its legacy pointMaps_ is loaded separately and passed to scene construction and the
renderer. The smallest prospective extension is that main.ts status classification and
focused status coverage; it was reported to the orchestrator before any such modification.
No unowned file was changed. This repair does not claim that the remaining labels are fixed,
that all four regions have geometry, or that rendered reconstruction quality is established.
No responsive/mobile or production-write acceptance was performed.

Exact changed set: preview-api.ts, preview.test.ts, glasshouse-courtyard.opm,
scripts/migrate_preview_point_map.py and this document, under the brief's listed paths.
No database, full backend suite, hosted models, merge, push or retained-data activation.
The orchestrator-owned port 5178 was not touched.

## Failed attempts retained as evidence

The first conversion guard incorrectly expected zero padding and refused the source before
writing. Inspection established ASCII spaces, and the guard now requires that exact padding.
The first focused test run had 29 pass and 2 fail: import.meta.url resolved under the browser-like
test environment, causing file URL/path errors. Tests now load fixture paths from the web
workspace test root; the subsequent run passed all 31. These failures were test/migration
harness issues, not hidden successful acceptance runs. Historical evidence was not rewritten.

## Orchestrator-owned follow-up patch

The orchestrator subsequently authorized `docs/preview-handoffs-main.patch` as a sixth
owned output, leaving main.ts itself unchanged. It records renderer-accepted preview
island IDs only after atlas.binding.islands exists, gated to preview and its loaded legacy
maps. Initial status and failed/missing renderer geometry retain unavailable classification.
The post-mount status refresh then suppresses that region's false unavailable row. This
uses actual renderer binding acceptance, not decode success, and invents no reconstruction
scene, calibration, receipt or rung disclosure. It does not assert continuous visibility
while distance/residency changes. `git apply --check` passes against the source main.ts.
The patch is not applied or browser-accepted here; the orchestrator will execute integration
acceptance. It addresses the grouped-region status mode used in this walkthrough only.
The separate `ui/status.ts:137` sourceOnly branch in inspection presentation also ignores
legacy maps and can still say no reconstruction is loaded. That file remains unmodified;
this distinct limitation was reported rather than silently included in the patch.

### Integration type correction

The orchestrator applied the initial patch in its separate integration worktree and reported
41 focused preview/OPM/status tests and boundaries passing, but typecheck failed at
main.ts:1658 (TS2345): the snapshot island ID is a string, not branded IslandId. The initial
patch's Set<IslandId> was too narrow for this cross-projection equality comparison. The
owner-approved correction is exactly `new Set<string>()` in place of `new Set<IslandId>()`.
Renderer IslandId values remain valid string keys; matching remains exact with no coercion
or casts. Only the patch and this history were updated here. The corrected patch passes
`git apply --check`; integration typecheck and browser acceptance remain with the
orchestrator. No new server or test campaign was started by this owner.
