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

## Display frame, arrival and residency

MEASURED 2026-09-05 on the first retained real scene (40 bowl photographs, 38 placed maps):
drawn as delivered, the scene stood tilted on its COLMAP axes, off the region centre, about six
times larger than the walking world, 1.2 units under the authored landscape, and its region was
left at the residency stub stage, so the arrival frame showed landscape alone while the
inspector, which bypasses residency, showed the geometry. Four presentation rules now apply to
every drawn scene. None changes a receipt, a rung, or a physical claim, and the status line says
so beside the rung.

- **Display frame.** `sceneDisplayFrame` in atlas-core derives one similarity per scene from
  its recovered cameras: up is the mean camera up (or the negated mean forward for a top-down
  survey, or the scene axes when neither agrees), the point the camera rays converge on sits on
  the region's vertical axis, and the median camera stands at eye height above the low quantile of
  the displayed bounds. The loader composes it into every placed map, the trained asset and every
  recovered camera of that scene, so all three stay consistent, and records it as
  `displayFrames`. The status reads, for example, "Displayed upright at 0.159× nonmetric exhibit
  scale, with the recovered cameras at eye height." When the cameras share no up direction the
  sentence says so instead of claiming an upright: MEASURED 2026-09-05, the 210 volcanic point maps
  have a mean camera up of length 0.34 and 41 percent of cameras point their up against the best
  common axis, because the rock was photographed from all around and turned over between series.
  No gravity axis exists in that recovered frame, so the scene axes stand and the status reads
  "its recovered cameras do not agree on an up direction, so no upright is claimed." The bowl's 51
  recovered cameras agree (mean up length 0.68) and it stands upright.
- **Grounding.** A reconstructed region's placement height is the authored landscape height at
  its centre, so local y = 0 is the ground the visitor stands on. Source-first regions keep the
  solver plane and compensate per veil, as before.
- **Arrival.** A region with recovered cameras arrives where the first photograph was taken,
  looking where that camera looked (`viewpointForwardLocal`). The first frame is the first
  photograph's view of the geometry. Regions without a recovered direction keep the offset framing.
- **Residency.** A region's point-map cost is capped at the residency budget, so one region can
  always afford its full stage while several still compete; the representation pressure controller
  still steps the stage down under frame pressure without dropping the region to stub.

One region displays one scene. When several current scenes overlap the same photographs, the
region shows the one covering the most of them, then trained geometry over point maps; the others
stay in the graph and the status list marked "Not drawn". An exact set whose members exceed the
metadata group joins that group's island rather than splitting into standalone islands.

## The proof lens, and click-to-evidence

MEASURED 2026-09-06 on the retained real trained bowl at 1280x720
(`docs/evaluation/2026-09-06-phase-10-atlas.json`).

**The proof lens** colours each region by what produced the surface in front of you: photographed,
reconstructed, generated, or nothing shown. The tier and its colour are both decided in
`@exulanica/presentation`; what crosses into the renderer is four already-resolved numbers per
region, a colour and a tint strength, and the binding indexes no palette and knows no tier. Point
maps take them through a `uLens` uniform written in the existing per-frame island block; trained
Gaussian geometry takes the same four through a per-component work-buffer modifier, which is the
only hook that is genuinely per region while unified gsplat rendering draws every splat through one
shared buffer. The tint replaces hue and keeps the surface's own brightness, so the geometry stays
readable underneath the answer about where it came from.

The lens changes no scene, no rung and no receipt, and the panel says so beside the switch. The
legend names all four tiers in words, with the swatch the renderer is actually given rather than a
near neighbour of it. **A region showing an original photograph is left exactly as recorded**: a
photograph is the evidence, tinting it would alter what is being offered, and so the `photographed`
tier is named in the legend and paints nothing.

**Click-to-evidence** lives in the reconstruction inspector and nowhere else. Traverse holds Pointer
Lock, which freezes cursor coordinates, and the focus solver may never take a screen-space input;
the inspector has already released the lock and stands on a calibrated recovered camera, so a click
there has real coordinates and an exact projection to invert. A click resolves to the nearest sparse
point COLMAP actually recorded, and the answer is the set of photographs whose observations of that
point the pose receipt holds, each with its consent state. Nothing is reprojected into other cameras
and presented as observation: that would answer which camera *could* have seen a point, which is a
guess about visibility rather than a record of a sighting.

Four things the panel is careful to say. The point is the nearest recorded one, **not the surface
under the pointer**, and the pixel distance is shown. A point whose COLMAP track is longer than the
bounded sample retained here states **both numbers**, because a viewer told "15 photographs" about a
point seventeen photographs observed would be misled by omission. A click that reaches nothing is
shown as the answer it is, with its tolerance in both screen and source pixels; at eight screen
pixels roughly a third of a grid of clicks over the bowl resolved, and the rest genuinely had no
recorded observation nearby. A midpoint between two photographs is refused rather than approximated,
because no camera stood there. Every listed photograph reports `person_consent: unavailable`, and
the sentence says what a screening receipt does and does not establish: a named human reviewed the
whole photograph, and no person in it has agreed to be shown.

The pick projects through the **raw** recovered camera, not the display-frame-composed one the
renderer draws with, because the observation graph's world coordinates are the recovered COLMAP
frame and are composed with nothing. Reprojecting every retained observation of the first photograph
through that transform reproduced COLMAP's own recorded pixel to a median of 2.83 px and a maximum
of 9.88 px on a 3060x4080 original, which is the SIMPLE_RADIAL distortion the camera declares as a
pinhole approximation. The world canvas is `aria-hidden`, so the same question is also askable from
a button inside the inspector, which resolves the centre of the view.

The pick runs on the server. The browser turns a click into a cursor in the photograph's own pixels
and asks `GET /world-read/scenes/{id}/observations/resolve` for the one recorded point it selects;
opening a view asks `.../observations/summary` for the counts the idle sentence shows. It used to
read the whole observation graph and pick in the browser, and that could not survive a large scene:
measured on 2026-09-11 against a frozen copy of the 210-photograph volcanic scene, the whole graph is
1,015,016,928 bytes of JSON, which V8 cannot hold as one string, so the panel failed with
"Unexpected end of JSON input". A resolved click is kilobytes (11,277 bytes for a point eight
photographs observed, 1,784 for a miss) and is bounded by the scene's photograph count rather than
its point count. The server builds an index of the pose receipt on a scene's first read, 6.3 s for
the volcanic scene, and answers in 0.2 to 0.3 s after that. `exulanica/graph/observations.py`
records the rest, including what that index does not hold. None of these reads carries a digest of
its own, unlike the World Read bundle: they are recorded provenance served over an authenticated
route, not a receipt a recipient can verify offline.

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
