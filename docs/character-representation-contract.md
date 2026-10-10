# Character representation and movement

Status: **PUBLISHED CATALOG PEOPLE AND PARAMETRIC BODIES**. This contract defines the shared
character foundation for the player and a world's synthetic inhabitants, how the app draws a
society's people, and the representation boundary a scene's observed people would bind to, for
which no adapter is built. Character catalogs are published by the host and served to the browser
by digest; nothing about people is compiled into the app. A published catalog of fitted, textured
people supplies the player's default body, the look of every inhabitant of every world that holds
a society, the character studio and saved looks, with near and distant detail levels, planted
feet, a seated rest drawn for the activity a society states, on the ground or on the seat of the
furniture a person uses, and a frame budget measured on a production build. A second family kind,
parametric bodies fitted per recipe, can be saved and worn by the player. It does not establish
likeness reconstruction, automatic rigging of new source material, or crowd collision avoidance.

<details>
<summary>Sections</summary>

- [One foundation, distinct subjects](#one-foundation-distinct-subjects)
- [Extensible asset and customization pipeline](#extensible-asset-and-customization-pipeline)
  - [Catalog people](#catalog-people)
  - [Published catalogs](#published-catalogs)
  - [Inhabitant looks and the display function](#inhabitant-looks-and-the-display-function)
  - [Player, studio and saved looks](#player-studio-and-saved-looks)
  - [Authenticated appearance history](#authenticated-appearance-history)
  - [Parametric bodies](#parametric-bodies)
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

### Published catalogs

The repository's catalog files are what a host publishes, not what an app loads. Publication is
host administration with the owner connection, never a request:
`exulanica-character-catalog publish --directory assets/characters --apply` (which
`scripts/prepare_character_people.py --import --apply` also runs) imports every container a catalog
names as a reviewed asset, checks each one's bytes and licence in the store, and records the catalog
as a publication (migration 0131): one canonical document named by the SHA-256 of its canonical
JSON. Two document profiles exist, each read by a fixed adapter: `exulanica.character-catalog-bundle/v1`
holds `catalog.json` with its designed looks (layered people), and
`exulanica.parametric-character-catalog/v1` holds parametric families
([below](#parametric-bodies)). A catalog's revisions only increase. The newest revision of each
catalog is **current**, older ones stay **retained** until the host withdraws them
(`exulanica-character-catalog withdraw`), and a withdrawal is final. Publishing the same document
again records it, answers `withdrawn` and leaves it withdrawn. A restore from an older backup keeps
it withdrawn, even when the backup holds no publication of it: the restore withdrawal catalog
(`exulanica/deletion/withdrawals.v2.json`, kind `character_catalog`) carries the withdrawal, which
names the digest on its own (migration 0135).

There is no fallback catalog. A serving database that was never given a publication draws nobody,
and every saved look on it reads as unavailable. So every path that creates or upgrades one
publishes right after `exulanica-db`, with the owner connection and the store the API serves:
- the `catalogs` job in `compose.yaml` and in `deploy/judge/compose.yaml` (the judge stack runs it
  again on every start);
- the acceptance launcher, before its API starts;
- the rehearsal's judge-seed restore, since a seed carries no publication: each deployment
  publishes its own;
- the documented development and personal-install steps;
- the installation.

The backend image carries the catalogs it publishes. `/readyz` reports `checks.character_catalogs`:
`served` with the current publications, or the declared state `people_catalog_unpublished` with the
command. It is a named state rather than a 503, because everything else the instance serves still
works.

`GET /world/character-catalogs` lists what the host serves (identity, profile, kind and state) and
`GET /world/character-catalogs/{catalog_sha256}` answers the canonical document itself, cacheable
forever because its address names its bytes; a withdrawn one answers 410 `withdrawn`. The browser
believes a document only when its bytes hash to the digest it asked for and its kind's validators
accept it (`atlas-react/src/playcanvas/character/served.ts`), and holds the served catalogs per
application (`CharacterCatalogs`). The current people catalog that declares the street population is
the one the player's default and every inhabitant are drawn from, so both always agree; a society
snapshot that arrives before it waits and is drawn when it is served. The generated
`catalog-data.ts` and `looks-data.ts` remain test fixtures and verification output only: a test fails
if a production module imports them, and the production build test proves the catalog document is
not in the bundle.

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

The player wears the served people catalog's designed default person until the person chooses
otherwise. The abstract figure is a deliberate choice in the studio, and it also stands in whenever
the chosen person cannot be loaded, whenever no people catalog is served, and whenever a saved look
reads as unavailable, in which case the host's code says why; a designed default never takes the
place of a saved person. The studio offers a figure choice, designed starting looks, the two bodies, and then every
slot and parameter the family declares, on the step, in the order and with the words the catalog
gives it (`ui/character-look-editor.ts`); adding a slot, a parameter or a choice to the catalog adds a
control and no code, and a slot the body offers one choice for is not offered as a choice. Choosing
the other body keeps every choice that body also offers and takes that body's designed default for
the rest. A look saved over an earlier revision of the catalog stays worn as it was saved; the studio
edits recipes over the catalog served now, so when that catalog cannot draw the saved look it opens
on the nearest look it offers, by the same rule, and says so (code
`saved_look_options_not_offered`) until the person chooses again. Walking and running preview on a treadmill at the clip's own speed. A signed-in world opens
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

Families come from the publications the host serves: one recipe family per catalog body
(`catalog_recipe_families`) and one per parametric family, each authorized exactly while a served
publication derives it. A family's revision is a digest of what a look over that body means: the
slots, the part, material and colour ids each may name, the parameter bounds and the rig
(`catalog_base_schema_sha256`). How an id is drawn is not part of it, so rebuilt containers, new clips,
better materials, labels and colour values leave every saved look valid, as do population tuning and
changes to the other body; removing a choice or narrowing a bound changes it. The first publication of
an unchanged catalog derives exactly the family digests looks were saved with before publications
existed.

A saved revision keeps the family document it names and, for revisions written since, the
publication it was authored against (`publication` in the document). It is drawn from the newest
served publication that derives exactly its family digest; every read says which (`render`: the
publication, its kind, whether it is the `authored` one or a later `compatible` one, and the state of
each container or prepared body it needs). When no served publication derives it, as after its only
publication is withdrawn, the read reports `family_source_unavailable` with the recipe and history
intact, and saving or resetting over that family answers 424 `appearance_unavailable`. Publishing a
catalog that removes an option a look uses therefore leaves that look unchanged while its publication
is retained, and explicitly unavailable after it is withdrawn; two worlds may hold looks over two
revisions at once. A saved catalog look reports `available` only when every container it composes is
a reviewed asset whose bytes and licence are in the store. `/families` names each family's kind and
the publication that serves it. `scripts/prepare_character_people.py
--import --apply` publishes all catalog containers through the reviewed asset registry; a signed-in
world fetches them from `/world/assets/<asset key>/bytes`, and the host checks every byte against the
catalog. The development preview reads the same committed containers through the development server
only, and a production build test proves no container is bundled.

### Parametric bodies

`makehuman-parametric/v1` is a family of declared body controls whose body is fitted per recipe
by the pinned Blender 4.5.9 with MPFB 2 and the MakeHuman CC0 system assets
(`makehuman-parametric-v1/source-lock.json`). Its published document is derived from the authored
`family.json` (`exulanica/world/character_parametric.py`): whole centimetres for height and
thousandths of the builder's own value for every fractional control, so the document is a canonical
digest input. A recipe names exactly its controls and choices and, when it is drawn, the prepared
body bound to exactly those values (`representation_id`); a body bound to other values is refused.
The family's revision covers its controls, choices, bounds and rig only, so publishing more prepared
bodies never changes what a saved recipe means. The committed default body is published as a
reviewed asset (`makehuman.parametric.default.v1`) and listed in the document with the render
descriptor measured from its own bytes.

Every prepared body is checked by `exulanica/world/character_bodies.py` with the standard library
before it is believed: one skin with exactly the family's joints, invertible bind matrices, at most
four influences per vertex with weights summing to one, the declared clips with linear or step keys,
skinned positions through idle, walk and run that stay finite, within reach of the hips and within
declared height ratios, an idle pose standing on the ground, a measured gait, and the declared byte,
triangle, vertex, joint and image budgets. On the committed default these measurements reproduce what
the builder recorded. `exulanica/world/character_preparation.py` runs the build as a child process
under a wall-clock and resident-memory watchdog, verifies the pinned inputs before and after it, and
writes an integer receipt; a failure is reported with its class (`preparer_failed`, `timed_out`,
`stale`, `rig_incompatible`, `deformation_invalid`, `over_budget`, `unverified_output`) and no body.
One build of the reviewed default recipe (2026-09-30, one machine at load average 4) reproduced the
committed body byte for byte in 4.8 s of wall time and 347 MiB of peak resident memory; a build may
use at most 180 s and 1 GiB.

Any other recipe is prepared in the workspace's own preparation queue
(`exulanica/world/workspace_preparations.py`, migration 0126), whose worker runs
`CharacterBodyPreparer` (`exulanica.makehuman-parametric-preparer` version 1) where the pinned inputs
verify (`EXULANICA_CHARACTER_PREPARER_BLENDER` and `EXULANICA_CHARACTER_PREPARER_SOURCE`).
`POST .../appearance/preparations` with a recipe records one preparation that pins the recipe, the
publication that served the family, the family as that publication declares it and the verified
preparer identity, and answers 202 while it is requested or running. An identical request in the
same workspace is the same preparation and is answered as it stands, so a body is fitted once; a
recipe whose values the publication already reviews is answered with that body and queues nothing.
The record step asks whether the pinned publication still serves the family, and the build verifies
its inputs before and after it runs; either failing ends the preparation `stale` with no body
written. A prepared body is named `preparation:<preparation id>`, and a look saved with it is bound
to exactly its output digest and receipt. `GET .../preparations/{preparation_id}` reads a
preparation with its render descriptor once prepared, `POST .../cancel` stops one that has not
finished, and `GET .../bytes` delivers the body while its family is served (`ETag` the output
digest). A saved look whose prepared body was cancelled, failed, is being prepared again, or whose
bytes are missing or do not hash to their digest reads `preparation_unavailable`,
`asset_bytes_unavailable` or `asset_integrity_unavailable`, and is never drawn as another body.
Refusals: 409 `representation_not_prepared` (a look names a body still being prepared), 422
`preparation_not_applicable` (not a person's own avatar, or a family that needs no preparation),
503 `preparer_unavailable`, 409 `preparation_not_ready`, `prepared_bytes_missing`,
`prepared_bytes_corrupt` or `preparation_finished`, 410 `withdrawn` and 429
`workspace_asset_quota_exceeded`. A prepared body counts against the workspace's retained bytes as
every output in its asset namespace does, so a body that would cross the limit fails the
preparation with class `quota_exceeded` and that code, and nothing is recorded; the failure classes
are the queue's, passed through as they are. A world's capability read describes requesting a body
and cancelling a preparation as these routes answer: requesting is unavailable with
`appearance_unavailable` where no family is served and with `preparer_unavailable` where this host
has no queue, no preparer or no inputs that verify for a served parametric family. A request needs
the installation's `preparation` component. Where the installation states that component not
installed, unavailable or refused, the read describes requesting as unavailable with the
installation's reason (for example `preparation_not_installed`), after this host's own refusals.
The route itself does not read the installation and still queues such a request, which waits until
a worker runs. Its effect, the body being prepared, is stated `preparation` with that component's
state ([world API](capabilities/world-api.md)); where the process states no installation, or has no
profile to see the worker by, the state is unknown.
A saved parametric look is worn by the player through the native character runtime with the measured
descriptor. Parametric bodies are for the player only: they have no postures, no distant form and no
population draw. The loopback development builder (`scripts/parametric_character/preview_server.py`)
remains for the development preview; it does not save looks.

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
backward exactly as fast as the ground: below the walk clip's calibrated speed the whole walk plays
at a slower cadence, down to half, rather than being mixed with standing; only below that does it
fade into standing. Between walk and run the clips blend at full cadence, and beyond the run the
cadence rises. Speed changes ease over about 0.12 seconds, and heading over about 0.14 seconds;
slower than 0.02 m/s a person stands. A contact lock then pins whatever touches the ground, the heel
from heel strike and the toe from the moment it is down through push-off, with an analytic two-bone
leg solve; the toe inherits the heel's correction so the handover does not jump, and a correction
beyond 25 cm re-plants the foot.

A turn on the spot is stepped: each foot travels 0.18 m, at rest height, for each radian turned, so
feet that the lock holds are lifted and set down again as the body turns. Whoever poses a person
may instead say that a turn is a pivot (`pivot` in `CharacterPose`): the body turns, no step is drawn
for it, and the lock lets the feet turn with the body until the pivot ends. The society's crowd
pivots every turn it makes, along a path's corners and where a person stands, so its people's
stride is the ground's alone and a person with no path to walk is never drawn striding, however the
state turns them.

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
crossing the boundary. Indoor inhabitants are counted, not drawn. A state says where a person is
when its minute ends, so someone whose minute ends indoors is indoors only once the walk that
minute recorded is done: they are drawn walking to the door, and from one door to another, and
counted indoors from the moment they reach it. A saved world's inhabitants hang
from their region's root, the frame their input states positions in and the frame the person's
objects are placed in. While everyone is away the state holds nobody, so the crowd draws nobody.

**Walking the recorded path.** Motion follows the recorded path (`motion_path_mm`) only, and no
position is invented between its points. A v4 inhabitant walks the path at its recorded
`walk_speed_mm_per_tick`, one tick's worth per interval, and stops where the path ends. A state that
records only a bound, `movement_budget_mm_per_tick` (a v2 state, and a society of things), says how
far anybody may walk in a tick and nothing of how fast a person walks, and the bound is usually far
longer than the path a person walks in a tick. Such a person walks what they have left at their own
walking pace, arrives, and stands where their activity is drawn until the next tick is read. Their
pace is the one the figure drawing them declares (a rigged look's declared walk speed, at the height
it is drawn) and otherwise the catalog person's for their id: the walk clip's measured ground speed
at their height, 1.00 to 1.37 m/s across the catalog's bodies (1,051 mm/s at a rest height of 1,591
mm drawn 1,520 to 1,800 mm tall, 1,223 mm/s at 1,729 mm drawn 1,620 to 1,930 mm tall). A walk too
long to finish at that pace by the time the next tick is expected (the interval plus the caller's
start lag) is walked evenly over that time instead, so only a tick's distance makes anybody faster
than a walk, and never faster than 1.5 times the bound's own pace. The pace is metres a second on
the screen at every playback speed: a faster playback shortens the standing and spreads shorter
walks. With 8 s between ticks and a start lag of 2 s, as the page passes at 1x, a person whose pace
is 1.1 m/s walks anything up to 11 m at that pace and a 16 m walk at 1.6 m/s; with 2 s and 1 s, as
at 4x, the same person walks up to 3.3 m at their pace and a 10 m walk at 3.33 m/s. Each later
tick's path is appended to what the person has still to walk when it starts where that ends, so a
person still walking when the next tick is read does not stop between them. A v4 person behind
catches up along the path at most 1.5 times their speed. Anyone moved without walking (a path that
starts elsewhere, minutes not read, more walking waiting than can be caught up, no recorded path, or
an older state) is named with its reason rather than moved silently (`CrowdJump` in
`society/types.ts`). A state without a pace is eased along its path over the interval. Everyone
walks on the ground plane: an inhabitant that states the height of the surface it stands on is
refused rather than drawn under it.

**One clock.** A walk is advanced by the caller's clock, and the seconds handed with each pose are
that clock's time since the crowd was last drawn, on a frame and at a state read alike, however long
the frame took. The speed a figure reads from its poses is therefore the speed it was moved at, and
its steps keep to the ground at ten frames a second as at sixty. The engine itself plays a clip for
at most 0.1 s a frame (`maxDeltaTime`), so below ten frames a second a clip falls behind the ground.

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
activity with no rule is drawn that way and named. Every turn the crowd makes is a pivot: no figure
draws a step for it.

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

**A town's own seats.** A generated town seats its people on its street furniture, which is a record
of its tiles and no object of a version, and a living town's action names a destination, never a
target. The layout therefore also carries the town's street furniture as its tiles' own records
state it (`generated-tile/street-furniture.ts` reads every `city.street_furniture` record of the
containers the page already holds, each once by identity: base point, direction vector and parts,
carried from the tile's east and north into the society's east and south). A person who holds no
object's place is looked for on that furniture by their recorded position (`streetSeatDrawing`),
and sits there when their activity is one the catalog draws on a seat, as at an object's: the seat
is the highest part under their point, they sit at
their own point on it at its top, and they sit with their back to what rises behind it, the nearest
part that stands at least 100 mm above the seat, faced away from across its thin side. Nothing names
a kind of furniture: the parts are the geometry, so a bench of another shape, or a ledge, is sat on
by the same rule, and a seat with nothing rising beside it is sat on facing as the person came.
Where a town's records are not read, or a person rests where no furniture is, the ground rule holds
as before. Sitting down and getting up are drawn as at an object's seat.

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

- a per-world pin of the catalog inhabitants are drawn from: they follow the current people
  publication, so publishing a new population changes how every world's inhabitants look (what they
  do is unaffected);
- parametric bodies for inhabitants, seated parametric bodies, or a distant form for them;
- a studio control for requesting a parametric body; the routes and the queue exist, and the
  control and its words belong to the experience owner;
- a preparation measurement beyond one recipe on one machine, or any claim of preparation capacity;
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
