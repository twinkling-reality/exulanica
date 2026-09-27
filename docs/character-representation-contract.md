# Character representation and movement

Status: **CATALOG PEOPLE FOR THE PLAYER AND INHABITANTS**. This contract defines the shared
character foundation for the player and a world's synthetic inhabitants, how the app draws a
society's people, and the representation boundary a scene's observed people would bind to, for
which no adapter is built. A committed catalog of fitted, textured people supplies the player's
default body, the look of every inhabitant of every world that holds a society, the character
studio and saved looks, with near and distant detail levels, planted feet, a seated rest drawn for
the activity a society states, on the ground or on the seat of the furniture a person uses, and a
frame budget measured on a production build. It does not establish likeness reconstruction,
automatic rigging of new source material, or crowd collision avoidance.

<details>
<summary>Sections</summary>

- [One foundation, distinct subjects](#one-foundation-distinct-subjects)
- [Extensible asset and customization pipeline](#extensible-asset-and-customization-pipeline)
  - [Catalog people](#catalog-people)
  - [Inhabitant looks and the display function](#inhabitant-looks-and-the-display-function)
  - [Player, studio and saved looks](#player-studio-and-saved-looks)
  - [Authenticated appearance history](#authenticated-appearance-history)
  - [Editable human builder](#editable-human-builder)
- [Visual direction](#visual-direction)
- [Representation boundary](#representation-boundary)
- [Movement quality](#movement-quality)
- [Detail levels and frame budget](#detail-levels-and-frame-budget)
- [Drawing a society's people](#drawing-a-societys-people)
- [Limits](#limits)

</details>

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
- Source-linked face textures, body geometry and proportions, with an abstract presentation
  remaining a deliberate choice. A real face is not required for a complete character. Those
  source-linked bindings are not established.

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
worn part covers each body vertex, the idle, walk, run, interact and wave clips retargeted from
Quaternius CC0 motion through the MakeHuman calibration pose, and one clip per declared posture
(below). Every outfit, shoe and hairstyle is its
own skinned container bound to the same bind pose, and every material is a small texture pack. A
renderer composes a person from those pieces: it hides body triangles under worn parts, shares one
skin instance per person, shares containers and materials across people, and verifies every
container's length and SHA-256 before decoding. Colour images decode as sRGB, normal and opacity
images stay linear, and opacity-only images use one channel. Hair images are normalised before tinting
by dividing out their broad shading, so dyed hair reads as one colour from root to tip. The source brown
iris is a saturated rust red; the definition declares a hue, saturation and value adjustment that moves
only its iris texels to a natural brown. Hair is a smooth shell rather than strands, so it is rough
(0.75): at 0.52 it mirrored the bright sky as a pale patch across the fringe.

Worlds light people with a flat ambient colour and one sun and no environment map
(`atlas-binding.ts`), so without occlusion every fold, armpit and hair layer would be lit alike. The
body, every garment, shoe and hairstyle therefore carries its ambient occlusion at rest, baked by the
preparation into the vertex colour (`COLOR_0`, normalized bytes): for each vertex, the share of 48
fixed rays over its hemisphere that travel 8 per cent of the rest height unobstructed against that
mesh and the body, never below 0.4. Forearms and hands hang beside the hips only in the rest pose, so
they shade nothing but themselves. A material whose meshes carry it (`vertexOcclusion` in the catalog)
reads it for ambient and specular light, and every double-sided material (hair, brows, lashes) lights
a back face with its own normal (`host.ts`). The settings are data in the definition's `occlusion`.

Containers are revision 2 (`assetRevisions` in the definition): their bytes changed when the seated
clip and occlusion were added, so their reviewed asset keys end `.v2`; the two bases are revision 3,
because they carry the perched clip as well (each about 57 KB more), while the worn parts kept their
bytes and their `.v2` keys, and material packs kept their bytes and their `.v1` keys.

A look (`exulanica.character-look/v1`) is a recipe over one body: part ids per slot, material ids,
colour keys and the integer parameters. Nothing else describes a person. Every slot and parameter also
states how the studio offers it (`studio` in the definition): the step it appears on (body, face or
style), its order there, a slider's step, the words for a signed morph weight and whether choices
show as swatches. `assets/characters/looks.json`
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
discontinuity?, activity? })` places it in the parent's space, and `setDetail`, `setVisible` and
`destroy` manage it. It reports `status` (`pending`, `ready`, `unavailable`), `lookSha256`,
`standingHeight` and `facing`. Appearance never decides simulation state or what an interaction
targets.

`activity` is what the person is doing where they stand as the simulation states it: the kind of an
action under way, such as `rest`, or null. The catalog family maps activities to postures
(`activityPostures`, `rest` to `seated`); both forms draw the mapped posture, and an activity the
catalog maps to nothing is drawn standing. A caller that draws the person at a seat says so
(`seated`), and the family's seat posture for the activity is drawn instead where it declares one
(`seatPostures`, `rest` to `perched`). The renderable never infers an activity from motion.

The society display draws every inhabitant this way
([drawing a society's people](#drawing-a-societys-people)). The abstract figure is a factory a
caller can name (`society/near-character.ts`); it has no seated posture, so it stands at a place
rather than being lifted onto a seat.

### Player, studio and saved looks

The player wears the designed default person until the person chooses otherwise. The abstract figure
is a deliberate choice in the studio, and it also stands in whenever the chosen person cannot be
loaded. The studio offers a figure choice, designed starting looks, the two bodies, and then every
slot and parameter the family declares, on the step, in the order and with the words the catalog
gives it (`ui/character-look-editor.ts`); adding a slot, a parameter or a choice to the catalog adds a
control and no code, and a slot the body offers one choice for is not offered as a choice. Choosing
the other body keeps every choice that body also offers and takes that body's designed default for
the rest. Walking and running preview on a treadmill at the clip's own speed. A signed-in world opens
the same studio, loading people through the session's reviewed assets.

Saved looks keep the server's revision rules: every save or reset appends a revision, a write names
the revision it was based on and is refused if another came first, and a reset returns to the body's
designed default or restores an earlier revision. The development preview keeps that history in the
browser. A saved or starter world keeps it in the authenticated history of its version, as the avatar
of the account the session belongs to (the actor `GET /auth/session` names), and the player wears the
saved look when the world opens (`composition/character.ts`). The server keeps catalog people only;
the abstract figure is worn without being saved. A session opened with an operator token names no
account, and the owned district holds no version the client can name, so there looks last for the
visit and the studio says which. The studio's premade stylized examples (four Quaternius looks, committed as
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
with read/save, reset, history and available-family operations, and every operation names the world
the version belongs to with a required `world_id` query parameter: a workspace holds several worlds,
a saved starter world among them, and the repository reads and writes only that world's history. Avatar IDs match the authenticated
actor; synthetic subjects must belong to a society created by that actor and match its current
authorized membership. Each world version has independent appearance history. This is not an
account-global profile, cross-version identity inheritance, automatic generation or observed-person
likeness fitting.

`exulanica/api/services.py` registers one recipe family per catalog body, derived from the committed
catalog and designed looks (`catalog_recipe_families`); a family is authorized while the instance
serves it, and a catalog and designed looks that disagree stop startup. A family's revision is a digest
of what a look over that body means: the slots, the part, material and colour ids each may name, the
parameter bounds and the rig (`catalog_base_schema_sha256`). How an id is drawn is not part of it, so
rebuilt containers, new clips, better materials, labels and colour values leave every saved look
valid, as do population tuning and changes to the other body; removing a choice or narrowing a bound
changes it. A saved catalog look reports `available` only when every container it composes is
a reviewed asset whose bytes and licence are in the store. `scripts/prepare_character_people.py
--import --apply` publishes all catalog containers through the reviewed asset registry; a signed-in
world fetches them from `/world/assets/<asset key>/bytes`, and the host checks every byte against the
catalog. The development preview reads the same committed containers through the development server
only, and a production build test proves no container is bundled.

### Editable human builder

A MakeHuman/MPFB builder is also in the repository: a loopback-only preparation adapter
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
person, beside other people, and under both bright and dim world lighting. Occlusion is baked in the
rest pose, so a surface the pose holds close to another keeps that shade when a limb moves away, and a
swinging upper arm does not shade the torso; hair stays a textured shell whose alpha-tested edge is
hard where the world draws without multisampling. Street outfit weights favour
distinct palettes (striped shirts, jackets, white tees, suits, skirts, work wear) over repeated blue
tops. Known limits of the fitted assets: long hair can let the back of a jacket show through where
both shells meet; the one idle clip stands with one foot ahead and the arms slightly away from the
body, which an inward correction cannot fix without pushing hands into fuller hips; eight outfits a
body repeat within a crowd, and most casual outfits share blue jeans.

Nearby inhabitants share this language and quality floor. Distant representations simplify
geometry and animation while retaining silhouette, palette, stable selection and subject identity:
a shared smooth figure per body and posture, about 7,600 triangles, built to the shoulder and hip
widths the preparation measures on the fitted body (`farForm` in the catalog) and coloured by region
from the person's own look, one draw call each, with a step rhythm and a lean into travel. Coarser
distant figures opened cracks at knees and ankles and are not used. Visual detail does not change simulation state or which person
an interaction targets.

The renderer never moves a canonical person to an unrecorded position for presentation, and it
does not steer walkers around each other. Keeping people apart is the simulation's rule: a
purposeful society over an input that states places holds one person to a place and keeps people
standing still a standing spacing apart, and the living society holds one person to a standing
spot ([synthetic society contract](synthetic-society-contract.md)). Where a society puts two people
on one point, both are drawn there. The crowd reports the bodies it draws separately from the
nearby subjects and the total population.

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

The generic **World to data** representation inspector is a separate renderer lens. It
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

Measured 2026-09-17 in the development preview (debug engine) at 1440x900 (headless Chrome 152, Apple
M3 Pro), during steady
walking in the crowd evaluation, as the largest horizontal travel of a planted toe during one stance:
without the lock 25 to 30 mm at the median and up to 52 mm at the 90th percentile; with the lock 0 mm
at the median and at most 1 mm at the 90th percentile at 0.7, 1.25, 1.6 and 3.4 m/s.

A person resting sits on the ground: knees up, feet flat in front, forearms across the knees and a
slow breath in the chest. The posture is data (`postures.seated` in the definition: where the feet and
hands go as shares of the rest height, the pelvis and trunk angles, the breath), fitted to each body
by the preparation (`scripts/character_catalog/posture.py`): each limb reaches its target with a
two-bone solve, the feet stand flat at the idle clip's floor, and the pelvis is lowered until the
lowest point of the skinned seat rests a declared depth into that same floor. The receipt records the
reach errors and seat heights, and `tests/test_character_postures.py` holds them to a millimetre. A
full person settles into the posture and rises from it over 0.8 s, and one first drawn already
resting appears seated; the contact lock rests while seated. The far form sits too: the shared sculpt
bent by the abstract rig along the baked clip's joints. That is the rest at a place with no seat.

A person resting on a seat sits upright on it (`postures.perched`): the seat 0.27 of the rest height
above the floor, the ankles 0.29 in front of the pelvis, the wrists over the thighs, the pelvis lowered
until the lowest point of the skinned buttocks (`seatBones`) rests at that height, because on a seat the
thighs slope down to the knees. The catalog states each base posture's measured seat height
(`seatMillimetres`), and the crowd lifts the person so that point rests on the seat their place has,
scaled to their height. The full form then plants its feet on the ground below with the contact lock's
two-bone solve, so a person taller or shorter than the seat suits is drawn with the knees a little more
or less bent; the far form is lifted without planting. The perched clip, like the seated one, is
generated by this repository's own posture script from the definition's numbers, and is CC0 under the
family's licence; the bases' reviewed import summary says so. Postures are baked in the order the
definition declares them, the order is part of the build's cache stamp, and adding `perched` left the
seated clip's keyed bytes as they were (`tests/test_character_postures.py`).

## Detail levels and frame budget

A person has two forms behind the one renderable. The near form is the full catalog person: body,
face, fitted parts, material packs, blended clips and the contact lock. The far form is the shared
smooth figure described above, coloured from the same look, with no part asset loaded. The society
display chooses a form per person through `setDetail`, and `NEAR_CHARACTER_BUDGET` (exported beside
`inhabitantRenderable`) says how many people may be drawn in full at once, the player included;
`NEAR_INHABITANT_BUDGET` is what a society display may give its inhabitants, the budget less
`PLAYER_NEAR_PLACES`, the one place the player's own body holds. The native character runtime applies
the budget to whatever resident set a binding gives it: the nearest people are drawn in full,
everyone beyond keeps their far form, and a full place changes hands only when the newcomer is at
least 2 m nearer than the person it would replace, so someone walking along the edge of the budget
does not switch forms every frame. A resident set of any size is accepted.

The budget is per this machine's release build. It was measured on 2026-09-23 on a production bundle
of the character catalog work on base e9dee3c2 (script `index-Bdu_k0ox.js`,
sha256 `3127a8cb3106376b...`), which carries PlayCanvas's release engine (`playcanvas`, as the bundle's
own engine-build record states), in headless Chrome 153 on an Apple M5 Max at 1440x900. The harness
mounts the real Atlas over the Flatiron owned district in third person, with the player drawn in full as
the designed default person, and a crowd of 128 catalog people from `inhabitantRenderable`, 8 of them
walking, all inside the camera frustum. Each configuration draws a number of the crowd in full and the
rest in the far form, and records 20 seconds of frames. Every configuration passed the machine-wide
timing gate (at least 70 per cent CPU idle over 10 seconds before it and a mean of at least 50 per cent
while it ran, both machine-wide slots held), and each count was measured twice, in opposite orders:

| Full characters | Frame work p95, repeat A / B | Presented frame p95 | Frames over 16.7 ms | Draw calls | Character textures |
| --- | --- | --- | --- | --- | --- |
| 24 of the crowd and the player | 3.9 / 3.5 ms | 16.7 ms | 0 of 1200 | 457 | 139 MB |
| 48 and the player | 6.6 / 6.6 ms | 16.7 ms | 0 of 1200 | 767 | 175 MB |
| 56 and the player | 6.8 / 7.6 ms | 16.8 / 16.7 ms | 0 of 1200 | 871 | 182 MB |
| 60 and the player | 7.5 / 7.6 ms | 16.7 ms | 0 of 1200 | 921 | 182 MB |
| 64 and the player | 8.8 / 7.6 ms | 16.8 / 16.7 ms | 0 of 1200 | 973 | 182 MB |
| 72 and the player | 9.1 / 8.7 ms | 16.7 ms | 0 of 1200 | 1,077 | 182 MB |
| 80 and the player | 10.2 / 10.5 ms | 16.7 ms | 0 of 1200 | 1,181 | 182 MB |

Frame work is the main thread's own time from the engine's frame update to its frame end, which is what
saturates first: presented frames stay at 60 Hz beyond the budget, so the interval alone would say
nothing. Draw calls count the whole scene, district included; the release engine keeps no triangle
count. Character texture memory is 139 MB at 24 full characters and 182 MB from 56 through 80; a far
figure adds a palette of five texels shared by everyone of the same colours, and one sculpt per body
and posture.

The rule, fixed before the run: the budget is the largest count every accepted repeat of which keeps
frame work p95 within half a 60 Hz frame, 8.3 ms, with presented frames still at 60 Hz, and the next
count measured above it must break it. The other half is left for the city, the society simulation, the
interface and machines slower than this one. That gives 60 of the crowd beside the player, so
`NEAR_INHABITANT_BUDGET` is 60 and `NEAR_CHARACTER_BUDGET` is 61; at 64, repeat A measured 8.8 ms. The two
repeats of one count differ by up to 1.2 ms, which is why every repeat must fit. The run is retained as
`web/packages/atlas-react/test/character-evidence/frame-budget-production-2026-09-23.log.txt` beside
the harness that produced it (page, Vite configuration, driver, idle gate and runner, each with its
digest in the log), and `character-budget.test.ts` reads it and fails if the constants, the rule, the
gate, the engine build or the retained harness disagree.

A development server serves the debug engine (`playcanvas.dbg`) instead, so a measurement there does
not state this budget; the development-preview runs of 2026-09-17 retained beside the production run
(`frame-budget-2026-09-17.log.txt`) state none. No weaker machine has been measured.

A person can also be carried instead of posed: `follow(position)` moves the body to a new ground
contact and keeps the pose it has, the clips still playing, and the caller hands the time it skipped
to the next `pose`, which then reads speed over the whole gap. Measured 2026-09-17 in the development
preview (debug engine, Apple M3 Pro) with 24 loaded people, alternating blocks: a solved pose costs
2.6 microseconds of the renderable's own work per person and a carried frame at most 0.1, so
carrying saves about 2.5 microseconds a person a frame.
That is 1.5 per cent of what a person costs: the other 98 per cent is the engine's animation and
skinning, which runs for every drawn person whether or not anyone posed them. Carrying is therefore
worth offering and is not a lever on the budget; the levers would be fewer instances or bones per
person, or stopping a distant person's animation, each of which changes how a person looks and needs
its own decision. The run is retained as `follow-saving-2026-09-17.log.txt` beside the 2026-09-17
budget run.

## Drawing a society's people

The society display (`web/packages/atlas-react/src/playcanvas/society/crowd.ts`) draws the whole
population of every world that holds a society, by distance, and never truncates it: the
population is canonical state. The nearest inhabitants within 60 m are catalog people, up to
`NEAR_INHABITANT_BUDGET` (60, the measured budget less the player's own place,
[above](#detail-levels-and-frame-budget)), and every other outdoor inhabitant within 700 m is drawn
in the far form of their own look (`society/far-figures.ts`, `farAppearance`), one draw call each,
the same form a catalog person shows while its parts load, so nobody changes colour or build
crossing the boundary. Indoor inhabitants are counted, not drawn. A saved world's inhabitants hang
from their region's root, the frame their input states positions in and the frame the person's
objects are placed in. While everyone is away the state holds nobody, so the crowd draws nobody.

**Walking the recorded path.** Motion follows the recorded path (`motion_path_mm`) only, and no
position is invented between its points. A v4 inhabitant walks the path at its recorded
`walk_speed_mm_per_tick`, one tick's worth per interval, and stops where the path ends. A v2 state
records only a bound, `movement_budget_mm_per_tick`, usually far longer than the path a person walks
in a tick, so a v2 person walks what they have left evenly until the next tick is expected (the
interval plus the caller's start lag), never faster than 1.5 times the bound's own pace, so nobody
sprints and then stands. A v2 person whose newly read tick adds nothing to walk finishes what is
left at no slower than their own walking pace, the walk clip's measured ground speed at their
height; a remainder spread again at every tick would never end. Each later tick's path is appended
to what the person has still to walk when it starts where that ends, so a walk through several
minutes does not stop between them. A v4 person behind catches up along the path at most 1.5 times
their speed. Anyone moved without walking (a path that starts elsewhere, minutes not read, more
walking waiting than can be caught up, no recorded path, or an older state) is named with its reason
rather than moved silently (`CrowdJump` in `society/types.ts`). A state without a pace is eased
along its path over the interval. Everyone walks on the ground plane: an inhabitant that states the
height of the surface it stands on is refused rather than drawn under it.

**Facing and activity.** Everyone faces the way their recorded path last took them and keeps that
facing when they stop, in either form, so a person first drawn in full after arriving, or again
after a spell in the far form, faces as their far figure did. What a person is doing comes from the
state, never from how they move: the crowd hands the kind of an action under way (`action.kind`
with `action.status` `active`) to whatever draws the person, as `activity` in `CrowdPose`, once the
path recorded for the tick has been walked, so a person asked to rest walks there and then sits.
They face as their activity's rule says (`society/activity-facing.ts`): `rest` and `visit` face the
object across the place, so a visitor at the market stall faces its counter and one at the tree
faces the tree, also in the minute after a visit completes while the visitor still stands there;
`talk` faces the partner the goal names; standing and walking keep the way they last walked, and an
activity with no rule is drawn that way and named.

**Seats.** With each state the page hands the crowd a seating layout (`society/seating.ts`): each
kind's use as `GET /world/assets` serves it from the world object catalog, the drawn version's
objects, and the object each target of the consumed input belongs to. A person whose action, under
way or just completed, names a target holds the catalog place whose position, carried into the
object's frame, lies within the turn's outward rounding of their recorded position
(`PLACE_MATCH_MM`, the square root of two millimetres and a micrometre). Where the place has a seat
and the catalog declares a seat posture for the activity (`seatPostures`, `rest` to `perched`), the
person sits on it: they walk at their own pace to stand before the seat (in front of it, or beside
it when their place is off to its side, as at the cafe chairs, so the walk does not pass through the
table), then turn and lower onto it over the posture's 0.8 s blend, pelvis on the seat at its height
and facing: a full character with its feet planted on the ground below, a far figure lifted to the
same height. Getting up runs the same way back, feet planted as they rise, before they walk on.
Moved without walking (a named jump), they leave the seat at once rather than glide from it. After
an object is moved or taken away the page hands the crowd a new layout at once, so a person whose
seat is gone gets up without waiting for the next minute. The move from the place to the seat is
presentation, and the person's recorded position stays the place. A place with no seat, such as a
marker plate's, keeps the ground rule: resting is drawn sitting on the ground in front of it. A
person matched to no place, or performing an activity with no facing rule, is drawn as everyone else
is and named with its reason (`seatingMisses`, which the page records on the canvas as
`data-society-seating-misses`); the owned district hands no layout. An activity with no declared
posture, such as making room, is drawn standing, and so is everybody drawn by a renderable with no
postures, which also stays standing at its place rather than being lifted onto a seat.

**Posing by distance.** Every drawn inhabitant is placed at its recorded point every frame, but only
the nearest full characters are posed every frame: the nearest 4 every frame, the next 8 every
second frame and the rest every third (`POSE_INTERVAL` in `society/crowd.ts`), each carried to its
recorded point in between. A selected inhabitant, and anyone whose snapshot jumped, is posed at once.
The cadence is what makes the abstract figure affordable, whose pose costs about 0.53 ms of
main-thread time in the development preview, almost all of it CPU skinning; a catalog person's pose
costs about 2.6 microseconds, since the engine animates and skins every drawn catalog person whether
or not it is posed ([carrying](#detail-levels-and-frame-budget) above).

## Limits

Built: the shared rig and catalog-backed representation model, catalog people and the abstract
figure, stable subject identity and the one display function inhabitants use; visibly distinct
silhouettes, hair, clothing and material combinations; studio editing with saved selections, reset
and restore, in the preview and in signed-in worlds, a saved or starter world keeping an account's
looks per world version; the player from behind, beside and close; catalog people as the
inhabitants of every world that holds a society, seated when resting; idle, slow walk, walk, run,
turn and stop; planted feet, measured; and the frame budget, measured on one machine's release
build.

Not built, and not claimed:

- a frame measurement on a weaker machine, and saved looks for a session that names no account;
- a scene-person adapter that represents a confirmed or unresolved observation from a photograph,
  starting from a source-linked abstract character, without requiring a photoreal likeness;
- reviewed source-to-character fitting (selected source references, uncertainty-aware body
  fitting, a compatible rig and retargeting, face and body textures, editing, dependency withdrawal
  and undo), which must be shown on authorized material before any claim of personal likeness;
- conversational gestures, gaze, reaching, contact-aware interaction and individual motion styles;
- automatic identity recognition, complete body recovery from one image and faithful personality
  simulation.

Scope and delivery order are owned by [product direction](product-direction.md). See also the
[interaction model](interaction-model.md), [synthetic society contract](synthetic-society-contract.md)
and [world composition contract](world-composition-contract.md).
