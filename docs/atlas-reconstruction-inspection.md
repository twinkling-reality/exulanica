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
register. Each recovered source camera retains its accepted pose/capture identity, position,
forward vector, roll, and actual COLMAP calibration. Cameras are delivered independently
of OPM availability, so a successfully loaded trained scene remains inspectable when
every point map is absent. Intrinsics set both focal scales and the principal point;
vertical coverage fits the canvas and additional horizontal coverage follows its aspect
ratio. Lens distortion models are explicitly labelled pinhole approximations.
Consecutive valid cameras also provide a bounded
midpoint; this is explicitly an unobserved view, without a photograph or a validated
route. Opposing cameras and different scenes are not interpolated. IDs derive from
the scene and capture identities (or legacy artifact identities), so comparisons can
return to the same views.
The canvas aspect ratio and exact calibration are recorded; horizontal image coverage
may differ from the original photograph. Walking input is suspended during inspection,
and **Return to Atlas** restores the previous position, orientation, field of view,
and projection.

Point-map inspection disables point-map atmospheric fog and boundary thinning and
uses full display density. Semantic visibility and source confidence remain part of
the OPM renderer; this is not a promise that every uploaded sample becomes a pixel.
The authored world keeps its established appearance. A splat artifact uses accepted
pose cameras even without
OPM assets. Older records without accepted calibration keep the OPM field-of-view
estimate fallback, and source galleries remain accessible. Camera metadata alone
does not enable reconstruction inspection when no geometry actually loaded.

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

`sourcePresentation` is the one renderer input that decides where originals appear.
The default `world` presentation keeps the source-first grove: each rung-4 region shows
a veil, a flat photograph with softened edges, and the startup and arrival cameras aim
at it. `inspection` omits every veil and that camera targeting while the authoritative
scene, topology, source authorization and inspector stay unchanged, and the app shows a
**No 3D reconstruction is loaded** panel whose count is the inspector's exact inventory.
The panel is hidden as soon as any scene renders point maps or Gaussians, while the
inspector is open, and in Index or Map. It is an unavailable state, never a
reconstruction result. The reference launcher selects inspection through
`VITE_EXULANICA_SOURCE_PRESENTATION=inspection`; without that setting Atlas uses world.

Source cards use authoritative topology region membership, so a scene does not
need detected entities to expose its original photographs. Source descriptors carry
active capture membership resolved from the same workspace and evidence blob.
Deleted/unavailable sources do not expose active capture IDs. The gallery uses
**Photograph N** labels, retains source identity as metadata, and keeps return
navigation above the image in a sticky header. “Grouped photographs” counts graph
membership; additional authorized topology slots may appear in the gallery.

Loading, terminal startup errors, and retry controls remain visible below the
desktop viewport threshold. Service outages and network failures have a plain-language
retry message; authorization and useful contract errors retain their own explanations.
An optional saved interaction policy failing to load
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
