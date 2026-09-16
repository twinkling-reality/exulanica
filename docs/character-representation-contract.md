# Character representation and movement

Updated 2026-09-14. Status: **FOUNDATION IMPLEMENTED; PRODUCTION CONFIGURATION, VISUAL/MOVEMENT
ACCEPTANCE AND SOURCE-LINKED LIKENESS OPEN**. This contract defines the shared character foundation
for the player, synthetic inhabitants, and people observed in scenes. The versioned subject model,
native rig runtime, development catalog/studio and authenticated appearance history exist. They do
not establish an existing likeness reconstruction, automatic rigging pipeline, production character
family or accepted in-world visual quality.

## One foundation, distinct subjects

A character is a versioned visual representation bound to an existing subject. Its mesh,
materials, proportions, animation and render detail can change without changing that subject.
Player identity, synthetic inhabitant identity and a scene's person observation remain distinct
binding kinds. Matching appearance never merges people. An unresolved scene observation may be
represented without assigning it to a confirmed person.

The shared foundation must support:

- An individually recognizable stylized human with a smooth silhouette, coherent proportions,
  well-formed head, hands and feet, and compatible hair, clothing and material choices.
- An optional abstract canvas with a featureless face and restrained surface treatment.
- Authored and generated variations in height, build and palette with stable choices per subject.
  Variation must look designed, not like independently randomized body parts.
- Future source-linked face textures, body geometry and proportions, with an abstract presentation
  remaining a deliberate choice. A real face is not required for a complete character.

Appearance is independent of agency. Displaying a remembered person does not create an autonomous
simulation of that person. An explicitly authored fictional derivative has its own simulation
identity and derivation; generated dialogue, actions and history remain fictional.

## Extensible asset and customization pipeline

Character content is supplied by versioned asset catalogs and generator adapters. A catalog
declares compatible body assets, rigs, shape parameters, garment and hair slots, materials,
animation clips and detail levels. Each entry includes stable asset identity, content digest,
origin, permitted uses and compatibility metadata. An asset family defines its supported
parameters and ranges; the application presents controls from that declaration. Adding an
asset or hairstyle must not require adding an identity-specific code path or changing the
core character schema. Unsupported catalog capabilities remain unavailable.

Defaults select coherent, visibly distinct combinations across body shape, height, head,
hair, clothing and materials. Sampling uses versioned compatibility rules and a retained
seed; saved selections and overrides preserve the person's look across reload, animation
and rendering detail changes. Each character can be edited or randomized independently.
Color changes alone do not establish population diversity. A shared rig supports different
appearances without binding a person's identity or behavior to a wardrobe choice.

Evaluate established parametric human assets and animation pipelines before authoring
another custom procedural body. Pretrained reconstruction, fitting and asset-generation
models may supply new catalog entries asynchronously. Generated meshes still require
topology, rig, deformation, material, garment-fit and runtime-budget checks before use.
Custom training or fine-tuning is a conditional response to a demonstrated quality gap,
with appropriate data and held-out evaluation; it is not required merely to expose more
customization options. Expensive outputs are retained and reused.

The procedural figure remains an implemented fallback. A reproducible preparation pipeline
now exports four Quaternius CC0 modular character assets as self-contained GLB files, with
smoothed complete geometry, separate garment components, named materials and Idle/Walk/Run
clips, plus original Interact and Wave actions. Source Mirror modifiers are realized before
export; preparation checks bilateral surfaces and the corresponding left/right skin influences.
The maintained preparation commands target the v2 bundle.
The bundle retains exact source, licence, toolchain and output digests, actual rig hierarchies
and clip calibration metadata. Prepared assets pass the reviewed-asset importer and existing
authenticated byte-delivery path; withdrawal removes delivery authority even when the stored
bytes remain. See the [reviewed asset contract](world-objects-contract.md).

These assets supply two source rig families and do not provide body or facial morphs,
independent hair geometry, image textures or lower-detail variants. Material colors and existing
components are usable building blocks, not evidence of complete customization or final visual
quality. Native rig playback now uses independently animated skin and material instances over shared
asset data. The display runtime keeps the existing nearby-subject budget, checks current
authority and falls back or hides the representation when a dependency becomes unavailable.
The development preview includes a character studio for catalog looks, supported material
colors, rotation, zoom and locomotion review, with session-only application to the player.
Nearby fictional inhabitants use the same catalog. Their versioned seed selects a stable look
and varies declared garment colors while retaining source head and hair materials; residency
and branch changes do not reroll the selection. These display choices do not change society
state or assign appearance to observed people. Authenticated appearance storage is implemented
as described below; client integration, broader asset assembly, retargeting and movement/visual
acceptance remain implementation milestones.

### Authenticated appearance history

Authenticated appearance storage retains validated authored recipes and append-only save/reset
history for an owner's avatar and their existing synthetic inhabitants within a world version.
Recipes pin the configured family, schema, rig, source and producer revisions; declared parameters
use bounded fixed-point values and supported choices. Prepared representations bind to exact
recipe inputs and reviewed assets. Current subject and source authority are checked on reads
and writes. Unavailable rendering dependencies remain explicit without erasing saved recipes.
Reset appends appearance history and leaves simulation events intact.

The API is rooted at `/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance`
with read/save, reset, history and available-family operations. Avatar IDs match the authenticated
actor; synthetic subjects must belong to a society created by that actor and match its current
authorized membership. Each world version has independent appearance history. This is not an
account-global profile, cross-version identity inheritance, automatic generation or observed-person
likeness fitting. A host must explicitly configure pinned families and their current source
authorizer. Production family configuration and client integration remain separate from the
development character studio. PostgreSQL persistence, concurrent-save rejection, version isolation,
source withdrawal and authenticated API behavior are tested.

The application does not currently connect that API to the development studio. Studio edits and
**Use in world** remain session state, while authenticated history is available only to a host that
explicitly supplies reviewed family definitions, current source authorization and compatible
prepared assets. A stored recipe with no prepared representation reports that state; it does not
trigger generation or certify a body.

### Editable human preview

The development character studio now includes an adult MakeHuman/MPFB family with declared
height, fullness, muscle, body-shape, shoulder, hip, limb and limited face controls. These are
shape parameters, not inferred measurements or a likeness reconstruction. Fullness has no
kilogram interpretation. The supplied hair and clothing choices are separate fitted assets;
the sculpture option exposes the underlying human surface.

The studio follows Body, Face, Style and Review steps for one character. Family-declared
female, male and androgynous starting shapes set the body's shape parameter while retaining
other measurements, face settings and wardrobe choices. They are editable starting points,
not separate fixed people. The fitted anatomical face and eyes inherit the selected body shape,
rather than swapping to a separate identity. Face controls expose the supported manual
adjustments; photo and camera likeness fitting are explicitly unavailable. Hair, clothing and
colors are grouped under Style. Body regeneration retains supported color choices, and moving
between steps retains pending edits. Complete premade example characters remain in a collapsed section
under Review, separate from the editable body's clothing choices.

Body, face and style edits automatically submit the latest complete recipe to a loopback-only
preparation adapter after a 400ms pause. Only one request runs at a time; further edits replace
the queued recipe. Older completions cannot replace newer drafts or become applicable.
Controls remain usable, colors update immediately, and the previous character stays visible
while fitting. Closing the studio or selecting an example invalidates queued and late UI
results; it does not cancel work already running in the synchronous preparation worker.
Reopening reuses the same request coordinator so a new request waits for any outstanding one.
A failed update retains edits and offers retry. Fitting still takes seconds, rather than
providing continuous mesh deformation while dragging.

The inspection camera keeps fixed metric framing across generated bodies, preserving the
chosen zoom and rotation. Default framing accommodates the supported 145–205 cm range, while
close zoom raises its target so the head remains inside the inspection frame.
A status beside the controls and an indeterminate stage overlay distinguish the previous body
shown during fitting from an up-to-date preview. Busy state is exposed to assistive technology;
completion, failure or choosing an example clears the fitting overlay. Softer front and rim
lighting reveal facial form without changing the asset. This camera behavior does not change
world traversal authority.

Pinned MPFB
targets produce the body, its skeleton is fitted to that body, and clothing is fitted using
its source correspondence data. The adapter transfers existing Quaternius motion through the
MakeHuman family's authored calibration pose. It samples the fitted foot paths for locomotion
speed estimates and exports an independent skinned GLB. The renderer still verifies asset
length and digest before decoding. No generated body requires a person-specific renderer path.

Preparation results and recipes are cached by input and preparation version. Transient assets
remain outside the web development server's watched directory, so rebuilding does not reload
the studio. The prepared default is distributable CC0 content and remains viewable without
the builder. The optional preparation environment and source programs are not bundled into
the web application. `scripts/prepare_parametric_character.py --install --blender PATH` installs
the pinned inputs and prepares that default; `scripts/prepare_character_preview.py` includes it
in the disposable catalog. `scripts/parametric_character/preview_server.py --blender PATH
--source .exulanica/briefs/parametric-human` serves the development adapter on loopback port 5196.
The preparation scripts also read an existing legacy briefs tree if that source has not been copied yet.

Before cache lookup and after generation, the adapter verifies the clean pinned MPFB source
and its source-tree digest, the extracted system asset tree, motion bytes, license/import
receipts, and the Blender executable digest plus version/build. These verified inputs,
family definition and preparation scripts form the cache identity and accompany generated
results as a preparation receipt. The current tool receipt pins Blender 4.5.9 LTS for macOS
arm64; another tool build requires an explicit receipt update and validation.

The default worker accepts browser requests from `http://127.0.0.1:5192` and
`http://localhost:5192`. For a separate workspace, pass `--port 5197 --allow-origin
http://127.0.0.1:5194 --allow-origin http://localhost:5194`, and start that workspace's Vite
server with `EXULANICA_CHARACTER_BUILDER_URL=http://127.0.0.1:5197`. Explicit origins replace
the defaults; only HTTP loopback addresses with a port are accepted. Each workspace keeps
its own preparation source and cache. No wildcard origin is supported.

The latest successfully fitted edits take effect automatically in the inspection stage.
Use in world waits until the current recipe is ready and applies it to the existing player.
Player application is session-only. This adapter is not an authenticated
production generation or appearance-save API. Rendered dimensions do not change the existing
traversal collision envelope or camera authority. Source-linked face/body fitting, detailed
facial customization, independently assembled wardrobe layers, persistent account appearance,
and complete deformation/contact acceptance remain further work. Hand gestures remain
available on the original exemplar family; they are not yet exposed on the fitted human.

## Visual direction

The abstract canvas uses a gently sculpted human silhouette and a quiet material hierarchy:
a warm sculptural skin surface, restrained satin clothing, and subtle light response. The default
fitted human preserves its authored sclera, iris and pupil texture plus fitted eyebrow and eyelash
layers; these details follow the generated head rather than replacing it with a separate face. Styled characters
use individually chosen surfaces, hair and garments within a coherent visual family. The presentation should
feel airy, ethereal and clean: soft environmental light, gentle color transitions and fine surface
texture that survives close inspection. Material detail should remain continuous across body
regions, with soft contact shading and sufficient environmental light to reveal the silhouette.
The neutral face must remain readable at close range, with a restrained eye opening and expression
that does not imply a fixed mood or identity.
A continuous transition through neck and shoulders, coherent limb proportions, shaped hands and
feet, and clean deformation matter more than decorative attachments.

Full-body anatomy, back silhouette, hand/foot design and motion require explicit design and
live review. Avoid visible primitive seams, disconnected joints, blocky torsos, toy proportions,
random accessories and glow that obscures the form. The base must remain legible without bloom,
from behind in third person, beside other people, and under both bright and dim world lighting.

Nearby inhabitants share this language and quality floor. Distant representations may simplify
geometry and animation while retaining silhouette, palette, stable selection and subject identity.
The existing population and visible-character budgets remain separate. Visual detail does not
change simulation state or which person an interaction targets.

People sharing an exact simulated position must not render as intersecting skins. Until the society
supports personal space, destination capacity and queueing, exact co-location may use an explicitly
counted group with a stable visible representative and access to each member. This is a display
fallback, not crowd avoidance. Report drawn bodies separately from nearby subjects and total
population. Genuine spacing and collision-aware crowd motion require planner support; do not move
canonical people to unrecorded positions for presentation.

## Representation boundary

The model separates the following concerns:

| Concern | Required meaning |
| --- | --- |
| Subject binding | Existing player, inhabitant, or scene observation/person reference |
| Representation | Stable representation ID, version, visual profile and compatible rig |
| Body | Height and supported proportions, units, and per-trait origin |
| Appearance | Abstract material/palette or source-linked asset references and explicit fallback |
| Motion | Rig compatibility and locomotion presentation driven by resolved movement |
| Evidence | References supporting observed traits, distinct from authored or generated choices |
| Availability | Current authority for presence and for each source-derived appearance dependency |

Missing height or hidden body regions are unknown. Generic or generated completion may fill a
visual representation, but must be labeled as a choice rather than a measurement. A source image,
an observed crop, a fitted mesh and a textured character are different artifacts with recorded
lineage. Preserve the source observation when introducing an animated representation.

Unavailable likeness assets must not remain in a texture cache or continue influencing body
proportions. If presence is still authorized, use the explicit abstract fallback with generic or
independently authorized traits. If presence itself is withdrawn, remove the representation;
a blank character must not bypass that decision. These checks reuse existing identity and source
permission authority rather than creating an independent identity database.

The generic **World to data** representation inspector is a separate renderer lens. It currently
operates on declared static mesh/point draws and district groups; skinned character meshes are not
silently sampled or presented as source points. Native characters expose subject, asset, rig, gait,
resolved speed and mutable residency diagnostics through their own bounded runtime inspection. This
does not create an observed-person mapping or a semantic endpoint for the geometric slider.

## Movement quality

Motion follows actual collision-resolved displacement or the recorded traversable society path.
Held input against a wall does not produce walking in place. Stride advances with distance, and
stance feet remain planted during their contact interval. Knee and elbow bending, pelvis weight
transfer, opposing shoulder rotation and restrained head movement should make the figure read as
a person, including at a slow walk. Smooth acceleration, braking and turn transitions must preserve
balance; run needs a distinct supported gait rather than an exaggerated walk cycle.

Body height and limb proportions affect stance, stride, ground contact and camera eye height.
Changing a visual preset must not silently change authoritative collision clearance or allow
passage through unsupported spaces. Rig dimensions, traversal dimensions and their compatibility
must be explicit. Both camera views share one player position; interactions use the displayed
camera ray and the player's reach. Camera motion must not inherit every decorative body movement.

Idle has quiet breathing and weight balance, without constant bouncing. Reduced motion suppresses
nonessential sway and camera transition motion. Initial delivery requires idle, walk, run, start,
stop and turn. Conversational gestures, gaze, sitting, reaching, contact-aware interaction and
individual motion styles are later milestones with corresponding geometry and behavior support.
A resting planner state alone does not imply a chair or a seated animation.

The current native runtime validates the source rig and exact idle/walk/run clip names, calibrates
gait speed from the descriptor, selects gait from resolved horizontal displacement, strips only
declared horizontal root motion and preserves the stable subject/picking fallback. Reduced motion
settles to idle. These mechanics do not prove planted contacts, proportion-aware retargeting,
turn/start/stop quality, collision-safe crowds or camera comfort; those remain live acceptance
requirements above.

## Delivery and acceptance

1. Deliver the shared rig and catalog-backed representation model, with styled characters and
   an abstract canvas option. Preserve stable picking and independent subject identity.
2. Demonstrate visibly distinct silhouettes, hair, clothing and material combinations,
   independent editing/randomization, saved selections and proportion-aware movement. Capture close face,
   front/side/back full body, idle, slow walk, run, turn and stop in the actual world. Check foot
   sliding, body intersections, deformation, camera obstruction and first/third-person switching.
   Record frame pacing with the visible population; a still image cannot establish motion quality.
3. Add an explicit scene-person adapter using existing confirmed or unresolved observation IDs.
   Start with a source-linked abstract character. Do not require a complete photoreal likeness to
   map an observed person into world representation.
4. Add reviewed source-to-character fitting: selected source references, uncertainty-aware body
   fitting, compatible rig/retargeting, face/body textures, editing, dependency withdrawal and undo.
   Demonstrate this on authorized material before claiming personal likeness support.

The first showcase should prove character variety, movement quality and the living world's behavior.
A source-linked character demonstration may show the mapping extension when available, with the
observed source and generated completion distinguishable. Automatic identity recognition, complete
body recovery from one image and faithful personality simulation are not claims of this milestone.

Scope and delivery order are owned by [product direction](product-direction.md). See also the
[interaction model](interaction-model.md), [synthetic society contract](synthetic-society-contract.md)
and [world composition contract](world-composition-contract.md).
