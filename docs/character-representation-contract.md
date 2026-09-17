# Character representation and movement

Updated 2026-09-17. Status: **CATALOG PEOPLE IMPLEMENTED FOR THE PLAYER AND INHABITANTS; SOURCE-LINKED
LIKENESS OPEN**. This contract defines the shared character foundation for the player, synthetic
inhabitants, and people observed in scenes. A committed catalog of fitted, textured people now
supplies the player's default body, every inhabitant's look, the character studio and saved looks,
with near and distant detail levels, planted feet and a measured frame budget. It does not establish
likeness reconstruction, automatic rigging of new source material, or crowd collision avoidance.

## One foundation, distinct subjects

A character is a versioned visual representation bound to an existing subject. Its mesh,
materials, proportions, animation and render detail can change without changing that subject.
Player identity, synthetic inhabitant identity and a scene's person observation remain distinct
binding kinds. Matching appearance never merges people. An unresolved scene observation may be
represented without assigning it to a confirmed person.

The shared foundation must support:

- An individually recognizable human with a smooth silhouette, coherent proportions,
  well-formed head, hands and feet, and compatible hair, clothing and material choices.
- An optional abstract canvas with a featureless face and restrained surface treatment.
- Authored and generated variations in height, build and palette with stable choices per subject.
  Variation must look designed, not like independently randomized body parts.
- Future source-linked face textures, body geometry and proportions, with an abstract presentation
  remaining a deliberate choice. A real face is not required for a complete character.

Appearance is independent of agency. Displaying a remembered person does not create an autonomous
simulation of that person. An explicitly authored fictional derivative has its own simulation
identity and derivation; generated dialogue, actions and history remain fictional. Synthetic people
are never made to resemble a real person: no face recognition, and no likeness from photographs.

## Extensible asset and customization pipeline

Character content is supplied by versioned asset catalogs and generator adapters. A catalog
declares compatible body assets, rigs, shape parameters, garment and hair slots, materials,
animation clips and detail levels. Each entry includes stable asset identity, content digest,
licence, source and compatibility metadata. An asset family defines its supported parameters and
ranges; the application presents controls from that declaration. Adding an asset or hairstyle adds
a catalog entry, never an identity-specific code path, and never changes the core character schema.
Unsupported catalog capabilities remain unavailable.

Evaluate established parametric human assets and animation pipelines before authoring another
custom procedural body. Pretrained reconstruction, fitting and asset-generation models may supply
new catalog entries asynchronously. Generated meshes still require topology, rig, deformation,
material, garment-fit and runtime-budget checks before use. Custom training or fine-tuning is a
conditional response to a demonstrated quality gap, with appropriate data and held-out evaluation.

### Catalog people

`assets/characters/catalog.json` (profile `exulanica.character-catalog/v1`) is the one inventory. Its
`makehuman-people/v1` family holds two fitted adult bodies (feminine and masculine), each with face
parts, eight outfits, six shoes, hairstyles, six skins, five eye colours, brows and lashes, plus a
six-colour hair palette and three integer parameters: height in millimetres and fullness and muscle
morph weights in thousandths. `scripts/prepare_character_people.py --blender PATH --source DIR`
rebuilds every container from the authored `makehuman-people-v1/definition.json`, the pinned
MPFB 2 checkout, the MakeHuman CC0 system assets and Blender 4.5.9; the output is byte-identical
across runs and `preparation-receipt.json` pins every input, script and output digest. `--verify-only`
checks each container's bytes against the catalog and its reviewed import manifest, refuses any
container in a family folder that no entry names, and compares the generated TypeScript modules with
their JSON.

A body container carries the skeleton, body, face parts, morph targets, a per-vertex bitmask of which
worn part covers each body vertex, and the idle, walk, run, interact and wave clips retargeted from
Quaternius CC0 motion through the MakeHuman calibration pose. Every outfit, shoe and hairstyle is its
own skinned container bound to the same bind pose, and every material is a small texture pack. A
renderer composes a person from those pieces: it hides body triangles under worn parts, shares one
skin instance per person, shares containers and materials across people, and verifies every
container's length and SHA-256 before decoding. Colour images decode as sRGB, normal and opacity
images stay linear, and opacity-only images use one channel. Hair images are normalised before tinting
by dividing out their broad shading, so dyed hair reads as one colour from root to tip. The source brown
iris is a saturated rust red; the definition declares a hue, saturation and value adjustment that moves
only its iris texels to a natural brown. Hair is a smooth shell rather than strands, so it is rough
(0.75): at 0.52 it mirrored the bright sky as a pale patch across the fringe.

A look (`exulanica.character-look/v1`) is a recipe over one body: part ids per slot, material ids,
colour keys and the integer parameters. Nothing else describes a person. `assets/characters/looks.json`
holds designed looks, the player's default and one default per body, validated against the catalog in
Python and TypeScript.

### Inhabitant looks and the display function

An inhabitant's look is drawn from a population profile (`street-population/v1`) keyed only by the
inhabitant's stable id and the domain: an exact integer draw over a SHA-256 counter stream, so branch,
position, tick, role and draw order never change it, and a replay draws the same person. The backend
reproduces the browser's draw byte for byte (`exulanica.world.character_appearance.draw_look`);
`tests/vectors/character_draw_v1.json` holds the shared vectors both test suites read. Over a thousand
inhabitants every outfit, shoe, hairstyle, skin and hair colour appears in proportion to its weight and
every look is distinct. Population weights are data; tuning them never changes a saved look's family.

The society display calls one function, from `web/packages/atlas-react/src/playcanvas/character/`:

    inhabitantRenderable(device, parent, identity, detail): CharacterRenderable

with `identity = { societyId, branchId, inhabitantId }` and `detail` `'near'` or `'far'`. The returned
renderable is already a child of `parent`; `pose({ position, yaw?, deltaSeconds, reducedMotion?,
discontinuity? })` places it in the parent's space, and `setDetail`, `setVisible` and `destroy` manage
it. It reports `status` (`pending`, `ready`, `unavailable`), `lookSha256`, `standingHeight` and
`facing`. Appearance never decides simulation state or what an interaction targets.

### Player, studio and saved looks

The player wears the designed default person until the person chooses otherwise. The abstract figure
is a deliberate choice in the studio, and it also stands in whenever the chosen person cannot be
loaded. The studio offers a figure choice, designed starting looks, the two bodies, height, fullness,
muscle, skin, eye colour, brows, hair, hair colour, clothing and shoes, all read from the catalog.
Choosing the other body keeps every choice that body also offers and takes that body's designed
default for the rest. Walking and running preview on a treadmill at the clip's own speed.

Saved looks keep the server's revision rules: every save or reset appends a revision, a write names
the revision it was based on and is refused if another came first, and a reset returns to the body's
designed default or restores an earlier revision. The development preview keeps that history in the
browser. The studio's premade stylized examples (four Quaternius looks, committed as
`assets/characters/stylized-looks.json` and derived from their pinned manifest by
`scripts/prepare_character_preview.py`) and the editable human's committed default remain selectable.

### Authenticated appearance history

Authenticated appearance storage retains validated authored recipes and append-only save/reset
history for an owner's avatar and their existing synthetic inhabitants within a world version.
Recipes pin the configured family, schema, rig, source and producer revisions; declared parameters
use bounded fixed-point values and supported choices. Current subject and source authority are checked
on reads and writes. Unavailable rendering dependencies remain explicit without erasing saved recipes.
Reset appends appearance history and leaves simulation events intact.

The API is rooted at `/world/versions/{version_id}/characters/{subject_kind}/{subject_id}/appearance`
with read/save, reset, history and available-family operations. Avatar IDs match the authenticated
actor; synthetic subjects must belong to a society created by that actor and match its current
authorized membership. Each world version has independent appearance history. This is not an
account-global profile, cross-version identity inheritance, automatic generation or observed-person
likeness fitting.

`exulanica/api/services.py` registers one recipe family per catalog body, derived from the committed
catalog and designed looks (`catalog_recipe_families`); a family is authorized while the instance
serves it, and a catalog and designed looks that disagree stop startup. A family's revision is a digest
of what a look over that body depends on, so population tuning and changes to the other body do not
orphan saved looks. A saved catalog look reports `available` only when every container it composes is
a reviewed asset whose bytes and licence are in the store. `scripts/prepare_character_people.py
--import --apply` publishes all catalog containers through the reviewed asset registry; a signed-in
world fetches them from `/world/assets/<asset key>/bytes`, and the host checks every byte against the
catalog. The development preview reads the same committed containers through the development server
only, and a production build test proves no container is bundled.

### Editable human builder

The earlier MakeHuman/MPFB builder remains in the repository: a loopback-only preparation adapter
(`scripts/parametric_character/preview_server.py`) fits a generated body for a full parameter recipe,
and `scripts/prepare_parametric_character.py` prepares its committed default. The studio's catalog
flow does not use it; generated bodies are development experiments, not saved looks, and they do not
change traversal collision or camera authority.

## Visual direction

The abstract canvas uses a gently sculpted human silhouette and a quiet material hierarchy. Catalog
people use textured skins with authored sclera, iris and pupil, fitted brows and lashes, tinted hair,
and textured garments with baked ambient occlusion and normal detail. The presentation should feel
airy and clean: soft environmental light, gentle color transitions and fine surface texture that
survives close inspection. The neutral face must remain readable at close range, with a restrained
eye opening and expression that does not imply a fixed mood or identity. A continuous transition
through neck and shoulders, coherent limb proportions, shaped hands and feet, and clean deformation
matter more than decorative attachments.

Avoid visible primitive seams, disconnected joints, blocky torsos, toy proportions, random accessories
and glow that obscures the form. The base must remain legible without bloom, from behind in third
person, beside other people, and under both bright and dim world lighting. Street outfit weights favour
distinct palettes (striped shirts, jackets, white tees, suits, skirts, work wear) over repeated blue
tops. Known limits of the fitted assets: long hair can let the back of a jacket show through where
both shells meet; the one idle clip stands with one foot ahead and the arms slightly away from the
body, which an inward correction cannot fix without pushing hands into fuller hips; eight outfits a
body repeat within a crowd, and most casual outfits share blue jeans.

Nearby inhabitants share this language and quality floor. Distant representations simplify
geometry and animation while retaining silhouette, palette, stable selection and subject identity:
a shared smooth figure per body, about 7,600 triangles, coloured by region from the person's own look,
one draw call each, with a step rhythm and a lean into travel. Coarser distant figures opened cracks
at knees and ankles and are not used. Visual detail does not change simulation state or which person
an interaction targets.

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
| Appearance | Abstract material/palette, catalog look, or source-linked asset references and explicit fallback |
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
silently sampled or presented as source points. This does not create an observed-person mapping or a
semantic endpoint for the geometric slider.

## Movement quality

Motion follows actual collision-resolved displacement or the recorded traversable society path.
Held input against a wall does not produce walking in place. Stride advances with distance, and
stance feet remain planted during their contact interval. Knee and elbow bending, pelvis weight
transfer, opposing shoulder rotation and restrained head movement should make the figure read as
a person, including at a slow walk. Smooth acceleration, braking and turn transitions must preserve
balance; run needs a distinct supported gait rather than an exaggerated walk cycle.

Body height and limb proportions affect stance, stride, ground contact and camera eye height.
Changing a visual preset must not silently change authoritative collision clearance or allow
passage through unsupported spaces. Both camera views share one player position; interactions use the
displayed camera ray and the player's reach. Camera motion must not inherit every decorative body
movement. Idle has quiet breathing and weight balance, without constant bouncing. Reduced motion
suppresses nonessential sway and camera transition motion.

A catalog person derives speed and turning from resolved positions. Gait keeps a planted foot moving
backward exactly as fast as the ground: below the walk clip's calibrated speed the whole walk plays at
a slower cadence, down to half, rather than being mixed with standing; only below that does it fade
into standing. Between walk and run the clips blend at full cadence, and beyond the run the cadence
rises. Speed changes ease over about 0.12 seconds, and heading over about 0.14 seconds. A contact lock
then pins whatever touches the ground, the heel from heel strike and the toe from the moment it is down
through push-off, with an analytic two-bone leg solve; the toe inherits the heel's correction so the
handover does not jump, and a correction beyond 25 cm re-plants the foot.

Measured 2026-09-17 in the preview at 1440x900 (headless Chrome 152, Apple M3 Pro), during steady
walking in the crowd evaluation, as the largest horizontal travel of a planted toe during one stance:
without the lock 25 to 30 mm at the median and up to 52 mm at the 90th percentile; with the lock 0 mm
at the median and at most 1 mm at the 90th percentile at 0.7, 1.25, 1.6 and 3.4 m/s. Conversational
gestures, gaze, sitting, reaching, contact-aware interaction and individual motion styles are later
milestones.

## Detail levels and frame budget

A person has two forms behind the one renderable. The near form is the full catalog person: body,
face, fitted parts, material packs, blended clips and the contact lock. The far form is the shared
smooth figure described above, coloured from the same look, with no part asset loaded. The society
display chooses a form per person through `setDetail`, and `NEAR_CHARACTER_BUDGET` (exported beside
`inhabitantRenderable`) says how many people may be drawn in full at once, the player included. The
native character runtime applies that budget to whatever resident set a binding gives it: the nearest
people are drawn in full, everyone beyond keeps their far form, and a full place changes hands only
when the newcomer is at least 2 m nearer than the person it would replace, so someone walking along
the edge of the budget does not switch forms every frame. It no longer refuses a set larger than 24.

The budget is measured. In the development preview at 1440x900 (headless Chrome 152, Apple M3 Pro),
with a crowd of 128 people all inside the camera frustum, 20 seconds a configuration, on a quiet
machine (one-minute load 5.6 to 6.9, both machine-wide slots held):

| Full characters | Frame work p50 | Frame work p95 | Presented frame p95 | Frames over 16.7 ms | Draw calls | Triangles |
| --- | --- | --- | --- | --- | --- | --- |
| 0 (128 far) | 2.6 ms | 3.3 ms | 16.8 ms | 0 of 1200 | 164 | 1.17 M |
| 12 | 4.7 ms | 5.9 ms | 16.7 ms | 0 of 1200 | 318 | 1.81 M |
| 24 | 6.1 ms | 7.5 ms | 16.7 ms | 0 of 1200 | 474 | 2.45 M |
| 36 | 7.7 ms | 9.0 ms | 16.7 ms | 2 of 1197 | 630 | 3.10 M |
| 48 | 9.8 ms | 11.5 ms | 16.8 ms | 0 of 1200 | 784 | 3.75 M |
| 64 | 13.3 ms | 14.6 ms | 16.8 ms | 0 of 1200 | 990 | 4.60 M |

Frame work is the main thread's own time from the engine's frame update to its frame end, which is
what saturates first: presented frames stay at 60 Hz even at 64 full characters, so the interval alone
would say nothing. A full character costs 0.18 ms of that work at the 95th percentile, a far figure
about 0.01 ms. Character texture memory is 145 MB at 24 full characters and 190 MB at 64; a far figure
adds a 5x1 palette and shares one sculpt per body.

A person can also be carried instead of posed: `follow(position)` moves the body to a new ground
contact and keeps the pose it has, the clips still playing, and the caller hands the time it skipped
to the next `pose`, which then reads speed over the whole gap. Measured 2026-09-17 with 24 loaded
people, alternating blocks: a solved pose costs 2.6 microseconds of the renderable's own work per
person and a carried frame at most 0.1, so carrying saves about 2.5 microseconds a person a frame.
That is 1.5 per cent of what a person costs: the other 98 per cent is the engine's animation and
skinning, which runs for every drawn person whether or not anyone posed them. Carrying is therefore
worth offering and is not a lever on the budget; the levers would be fewer instances or bones per
person, or stopping a distant person's animation, each of which changes how a person looks and needs
its own decision. The run is retained as `follow-saving-2026-09-17.log.txt` beside the budget run.

The rule, fixed before the run: the budget is the largest measured count whose work p95 stays within
half a 60 Hz frame, 8.3 ms, with presented frames still at 60 Hz. The other half is left for the city,
the society simulation, the interface and machines slower than this one. That gives 24; 36 is the
first count to break it. The run is retained as
`web/packages/atlas-react/test/character-evidence/frame-budget-2026-09-17.log.txt` with its harness,
and `character-budget.test.ts` reads it and fails if the constant, the rule or the recorded load
disagree. A discarded earlier run at one-minute load 30 to 130 is kept beside it as a record of what a
busy machine measures. A weak-machine measurement is still open.

## Delivery and acceptance

1. **Delivered.** The shared rig and catalog-backed representation model, with catalog people and an
   abstract canvas option, stable subject identity and the one display function inhabitants use.
2. **Delivered, with the limits named above.** Visibly distinct silhouettes, hair, clothing and
   material combinations; studio editing with saved selections, reset and restore; the player from
   behind, beside and close; a crowd of distinct inhabitants; idle, slow walk, walk, run, turn and stop
   captured in the world; planted feet measured; frame pacing recorded with the visible population.
   Still open: signed-in client wiring of the saved-look store to a world version, and a weak-machine
   frame measurement.
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
