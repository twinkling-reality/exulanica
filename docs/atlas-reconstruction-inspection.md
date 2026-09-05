# Atlas reconstruction inspection

The production Atlas reads scene identity, ordered capture membership, quality gates,
and immutable artifact references from the authenticated graph. This work keeps the
existing Aeroheart authored world and its navigation policy. A reconstructed scene
does not become a measured walking surface because its renderer can display it.

## Coordinates and camera comparisons

Fitted OPM placements use an affine row-major `scene_from_opm` matrix whose linear
part is **sR**. The matrix already includes `local_units_to_scene_units`. CPU point
projection applies the matrix once. PlayCanvas extracts R for the entity quaternion
and applies the scalar once as entity scale. Both reject shear, reflections, invalid
affine rows, and disagreement between the matrix and declared scalar. The backend
requires `colmap-correspondence-fit`; old identity receipts fall back to sources.
These relative scene units are not independently validated physical metres.

In a scene's status panel, **Inspect reconstruction** opens a repeatable camera
register. Each recovered source camera retains its position, forward vector, roll,
and vertical field of view. Consecutive valid cameras also provide a bounded
midpoint; this is explicitly an unobserved view, without a photograph or a validated
route. Opposing cameras and different scenes are not interpolated. IDs derive from
the scene and artifact identities, so comparisons can return to the same views.
The canvas aspect ratio is recorded; horizontal image coverage may differ from the
original photograph. Walking input is suspended during inspection, and **Return to
Atlas** restores the previous position, orientation, and field of view.

Point-map inspection disables point-map atmospheric fog and boundary thinning and
uses full display density. Semantic visibility and source confidence remain part of
the OPM renderer; this is not a promise that every uploaded sample becomes a pixel.
The authored world keeps its established appearance. A splat artifact without any
available fitted OPM camera can still load, but the application does not invent a
recovered viewpoint; its source gallery remains accessible.

## Trained artifact delivery

`trained_geometry` describes the exact current published artifact: SOG container,
SHA-256, byte size, affine scene transform, bounds, availability, and a workspace
bearer reference under `/scene-geometry/<artifact-id>`. The browser:

1. Checks artifact/path identity, same-origin relative route, and bearer requirement.
2. Fetches through the existing authenticated transport with a deadline and verifies
   the complete byte count and SHA-256 using SubtleCrypto.
3. Checks that the SOG ZIP contains every referenced texture, with unique local
   filenames, metadata version 2, and the pinned compressor's STORE representation
   (including streamed size/CRC descriptors). Missing or external texture references
   are rejected before native parsing can attempt an unauthenticated subrequest.
4. Supplies the verified ArrayBuffer directly to PlayCanvas's native GSplat handler.
   Only a successfully loaded native resource creates a trained scene entity.
5. Selects trained geometry in preference to duplicate posed clouds for that scene.
   Byte, archive, or native decoding failure retains posed maps or source evidence
   and produces a visible explanation. Native assets are released on unmount.

The native loader does not promote the recorded quality rung or grant navigation
permissions. SOG availability and successful draw submission are not a visual
quality verdict. The format-only test fixture under `web/test-data` is generated
test material, not a trained reference, and is never loaded by production code.

## Sources and startup

Source cards use authoritative topology region membership, so a scene does not
need detected entities to expose its original photographs. Source descriptors carry
active capture membership resolved from the same workspace and evidence blob.
Deleted/unavailable sources do not expose active capture IDs. The gallery uses
**Photograph N** labels, retains source identity as metadata, and keeps return
navigation above the image in a sticky header. “Grouped photographs” counts graph
membership; additional authorized topology slots may appear in the gallery.

Loading, terminal startup errors, and retry controls remain visible below the
desktop viewport threshold. An optional saved interaction policy failing to load
does not leave the document blank. Native reconstruction decoding has its own
visible loading state.

## Evidence limits

The opt-in production browser recorder (`?validation=1`) records authenticated loads,
uploaded map counts, loaded Gaussian counts, draw submissions, exact camera segments,
canvas aspect, and frame timing. It leaves time-to-full-detail unmeasured and does
not call uploads “rendered points.” Source-only browser screenshots exercise genuine
authorization, source delivery, gallery navigation, and fallback UX; they establish
no 3D coherence, trained scene quality, or GPU native decoding result. Those require
the retained approved photographic scene, the real training run, and direct browser
inspection recorded alongside the separate reconstruction evaluation.
