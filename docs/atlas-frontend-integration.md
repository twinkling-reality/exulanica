# Atlas frontend integration

Status: **IMPLEMENTED** for the global world-appearance lifecycle, production source-media
loading, and production reconstruction geometry.

## Authority split

The backend owns immutable versions, the current pointer, style and topology compare-and-swap
tokens, proposal status, actor/origin, acceptance and rejection, refinement lineage, rollback,
references, model/prompt versions, authorization, and source-slot provenance.

The frontend owns the reviewed recipe and module implementations, strict capability/parameter
validation, contrast correction, protected component geometry, accessibility, and preview
rendering. Recipe payloads remain inert. No API response can introduce CSS, HTML, JavaScript,
shaders, renderer programs, layout instructions, or a remote texture URL.

`web/packages/app/src/world-style-api.ts` is the one translation layer between the backend's
snake-case persisted records and the frontend's camel-case registry contract. Startup rejects an
unknown catalog version, frontend contract commit, profile version, module list, control manifest,
or capability mapping before applying it. Valid current state hydrates the renderer and Options;
local storage is only a device cache.

## Review lifecycle

Direct Options controls render immediately through the local trusted modules and create an isolated
backend preview after a short input debounce. Undo, leaving Options, or replacing a preview closes
the backend preview without moving the current pointer. Apply posts the exact preview bases and
updates the UI only after the server returns a new immutable version.

For a Settings draft, if preview creation is stale, the client reads current state and creates a
new proposal linked to the rejected proposal through `refinesProposalId`; if Apply becomes stale,
that recovered preview is shown but is not silently applied, and the person reviews and applies
again. A proposal from another origin, such as the Companion's, is never made again: it is refused
in words (see the
[customization contract](atlas-world-customization-contract.md#7-frontend-integration-boundary)).
Rollback similarly refreshes on a conflict and requires the target to be chosen again. Successful
rollback creates a new revision and leaves the target untouched.

Options shows current revision and ID, actor/origin/origin reference, model and prompt provenance,
warnings, proposal refinement/reference information, and immutable history. Loading, unavailable,
failed, checking, saved, and stale states are announced through live regions and remain keyboard
operable inside the existing modal focus boundary.

## Conversational proposals

`web/packages/app/src/world-style-proposals.ts` is an in-process typed inbox for structured
proposals. It does not call a model or convert prose. A caller supplies an already
structured profile proposal. Companion input must include an origin reference, at least one opaque
reference ID, a model ID, and a prompt version. The normal local and backend validation paths then
produce the same preview UI used by Settings. A refinement is another upstream proposal carrying
the prior proposal ID.

The application connects the backend appearance-proposal route to this inbox. The
[Companion question contract](companion-question.md#appearance-proposals) owns request classification
and drafting. The inbox supplies the review boundary, not evidence that every model proposal is
useful or that general structural language editing is supported.

## Source media

`web/packages/app/src/source-media-api.ts` reads protected source slots, verifies the
workspace-bearer authorization declaration, local `/evidence/` path, source ID, and evidence-span
provenance, then fetches bytes with the bearer header. Only an image response becomes a blob URL.
Blob URLs are revoked at session disposal. Available, unavailable asset, missing evidence,
unauthorized, provenance-error, and network-error states remain distinct and visible; no fallback
image is invented.

## Reconstructed geometry

**ADR-0009 D10, and it was the first item of work in that record for a reason.** Until this
shipped there was no production path by which any point map reached the renderer: no route served
artifact bytes, and the only loader in the workspace was the development preview. A posed set, a
corridor and the designed void would all have been built against nothing.

The backend serves scene facts through `GET /graph` and artifact bytes through
`GET /geometry/{artifact_id}`. A reconstruction-scene record carries the immutable ordered member
set, registered and unregistered outcomes, placement and receipt digests, each placed point-map
descriptor and transform, the recorded rung and reasons, the displayed rung and reasons, and the
available substrate. The graph route reads that description inside the same repeatable-read
snapshot as the rest of the world. `GET /geometry` remains the descriptor list for
per-capture maps that have never belonged to a posed scene.

`web/packages/app/src/geometry-api.ts` reads the scene records, checks every reference declares
`workspace-bearer` and a local `/geometry/` path, fetches bytes with the bearer header, computes
SHA-256 over what arrived, and compares it **to the descriptor** rather than to the response's own
`ETag`. Bytes that fail never reach the decoder. A page with no `SubtleCrypto` loads no geometry at
all and says so, rather than decoding what it could not check.

**The container the loader accepts is `opm/2`**, which is a constant in that file and moves with
the decoder in `@exulanica/atlas-react`. ADR-0010 D9 is refuse and regenerate with no upgrade on
read, so a descriptor naming `opm/1` is refused from the list rather than fetched and failed at
the decoder: the region loses its geometry, the reason names the version, and several megabytes
that could not have been read are never transferred. A descriptor whose container is null is
attempted anyway, because null means no stage definition was recorded for that artifact's
parameter digest rather than that the bytes are unreadable, and the decoder is then the check.

`GeometryClient.loadScenes` attempts every placed member declared by the validated scene record.
`AtlasBinding` creates one island root and one transformed point-cloud child for each decoded map.
It uses the receipt's `scene_from_opm` matrix and never reuses Atlas layout as reconstruction
placement. Residency cost, footprint and arrival framing include all loaded maps. One missing,
corrupt, timed-out or unsupported map degrades independently, and an unregistered photograph is
shown through its source-first region rather than treated as a geometric hole. If no map survives,
the scene displays rung 4 source photographs. Every request has its own deadline because `fetch`
has none and `mount()` waits for the result.

The authoritative disclosure names `recordedSceneRung`, `displayedRung` and
`renderingSubstrate` separately. The recorded value comes only from the scene-rung assertion.
Decoded OPM bytes cannot promote it. The disclosure also shows registered member count and every
gate or fallback reason, including the missing scale, coverage, corridor and splat receipts that
hold a production posed scene at rung 3. Its displayed-rung sentence comes from the one
shared `RUNG_COPY` table in `@exulanica/formation`; the app no longer carries a divergent copy.

The load runs on **every** mount, not once at start-up. The graph is re-read and unchanged decoded
maps are carried forward by artifact id. That is what carries deletion to the renderer: deleting
any registered or unregistered member removes the complete scene on the next mount.
`GET /geometry` omits captures that have belonged to a scene, so a surviving member cannot reappear
at an invented origin after the placement is withdrawn. Bytes are served `no-store`, so a deleted
scene is not redrawable from the browser's own disk cache afterwards.

## Deliberate remaining boundary

The backend may hold regional overrides, but the renderer exposes only a reviewed global
profile preview. Atlas parses regional history without reinterpreting it and refuses an upstream
regional proposal rather than painting it globally. Regional controls require a reviewed
per-region renderer implementation. Structural proposals remain outside the appearance API.

## Verification

Focused browser-unit coverage lives in:

- `web/packages/app/test/world-style-api.test.ts`;
- `web/packages/app/test/source-media-api.test.ts`;
- `web/packages/app/test/geometry-api.test.ts`;
- `web/packages/app/test/world-style-proposals.test.ts`;
- `web/packages/app/test/options.test.ts`; and
- `web/packages/app/test/surface.test.ts`.

The backend wire and database guarantees remain covered by `tests/test_world_api.py`,
`tests/test_world_style_contract.py`, and `tests/test_world_style_postgres.py`. The geometry
routes are covered by `tests/test_geometry_delivery.py`, and their authorisation by the
router-generated sweep in `tests/test_api.py`.
