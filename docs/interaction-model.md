# Interaction and spatial model

Status: mixed. Every claim carries exactly one label, per the convention in
[README.md](README.md): **VERIFIED** (primary source URL and retrieval date), **DECISION** (with the
alternative rejected), **ASSUMPTION** (with the experiment that settles it), **OPEN**.

Retrieval date for every VERIFIED claim on this page: **2026-08-27**.
Scope, corpus and product claims live in
[product-specification.md](product-specification.md) and are not restated here.

**Read section 2.1 first.** Two verified platform facts remove design freedom that a reader would
otherwise assume exists, and most of this document is downstream of them.

---

## 1. The Atlas is the whole application

### 1.1 One scene, for the whole session

**DECISION.** Once the Atlas application opens, there is exactly one scene graph, one camera and one
render loop for the lifetime of that application session. There is no scene loading between Map,
World Index and region interiors. The public landing site is a separate lightweight document that
links to the application; it does not imitate an empty Atlas or mount mock application state.

Rejected alternative: discrete scenes with transitions between an overview map and region interiors,
which is the conventional structure. Rejected because it forces a loading boundary exactly where the
product's central claim lives (this person is in both places), and because it makes recomposition a
rebuild rather than a uniform change.

Five consequences follow mechanically and are not separately decided:

- What changes as the user moves is representation density, never scene identity (1.4).
- The Atlas Map is a camera pose, not a different view (6.2).
- Recomposition is a per-object uniform change, not a rebuild (7).
- Processing is visible in the world where the region will be, not in a separate progress panel (8).
- First run inside the application is a camera movement, not a second scene load.

### 1.2 Three coordinate frames, one of which is presentation only

**DECISION.**

| Frame | Meaning | May answer a question? |
| --- | --- | --- |
| `AtlasFrame` | The world root, in "atlas units". Purely presentational. Y is up and shared by every region | **No** |
| `RegionFrame_i` | Per region: position, yaw and scale within `AtlasFrame`. Regions are never pitched or rolled, so the up vector stays globally shared | **No** |
| `LocalFrame_i` | The reconstruction-native frame of that capture. Metric only if the reconstruction produced metric scale | Only when metric, and only within one region |

**The hard rule: a region's atlas position carries no real-world meaning and must never be read by
anything that answers a question.** Two regions being adjacent means their entity sets overlap. It
does not mean the photographs were taken near each other.

Enforcement is in the type system, not in code review: branded vector types (`AtlasVec3`,
`LocalVec3`, `MetricVec3`), one legal one-way conversion from local to atlas, deliberately no
`atlasToLocal` export and no distance function over `AtlasVec3` exported from the query layer, plus a
lint rule banning distance computation over atlas positions outside the layout module.

Query-layer rule: a spatial question ("how far apart were they", "was she behind him") may be
answered only from metric coordinates inside a single region whose scale is metric. Across regions,
and inside non-metric regions, the correct answer is a refusal with a stated reason, never an
estimate.

**RISK (high, R-48).** If any answer ever silently uses atlas placement as geometry, the product's
central honesty claim collapses. This is why the guard is a compile error rather than a convention.

### 1.3 The one legitimate exception: the user's own captures of the same place

**DECISION.** Pooling several of the user's **own** captures of the same physical place into one
shared coordinate frame is legitimate, because in that case the shared geometry is real rather than
presentational. Distances measured inside such a pooled frame are true measurements, not layout
artifacts.

Support: metric output from the reconstruction stack is what "lets two captures of the same room be
compared" (reconstruction stream). Metric scale is therefore not an aesthetic preference; it is the
precondition for this exception.

Three conditions, all required, none optional:

1. Both captures belong to the same user and the same workspace.
2. Both reconstructions are metric.
3. The two captures were actually co-registered by the reconstruction pipeline, not merely labelled
   with the same place entity by a proposal.

Condition 3 is the one that will be tempting to skip. A confirmed place link is a semantic statement,
not a geometric one, and it does not license a shared frame.

**OPEN (I-1).** No experiment in the research plan measures the success rate of co-registering two
separate captures of the same place. The plan measures per-scene structure-from-motion yield, not
cross-capture registration. Until that experiment exists, this exception is architecturally
permitted and **should not be shipped**. The experiment that settles it: take two photo sets of one
place from the corpus, run them through the pose pipeline jointly, and measure the fraction of images
that register into a single model.

### 1.4 Layout and representation tiers

**DECISION.** Layout is a stored artifact, never recomputed at runtime. A deterministic seed
(phyllotaxis) plus a pinned force relaxation, ordered by creation time, run once and persisted with a
layout version. Target separation is derived from shared **confirmed** entities. A confidence band is
still a model judgement: speculative links must never move the world, otherwise the layout twitches
every time the pipeline guesses.

Pre-existing regions are pinned during relaxation and then hard clamped inside a small drift radius,
so adding a fourth capture cannot scramble the user's spatial memory of the first three. When layout
does change it is never a cut: regions glide over about 1.2 s and the Companion states the reason in
one line. Under reduced motion the move is instant and the line becomes mandatory, because the
explanation now carries the information the animation would have.

**UNRESOLVED EXPERIMENT.** At three regions a force layout is close to degenerate and a hand-placed
triangle may look better. Compare the algorithmic and hand-placed result on the three real captures
before committing. Roughly two hours. **The research did not pick a winner and neither does this
document.**

Four representation tiers per region, cross-faded on distance, all resident in the same scene:

| Tier | Distance to footprint boundary | Drawn |
| --- | --- | --- |
| 0 | beyond 180 au | One instanced silhouette impostor, a name plate, an occurrence-count glyph |
| 1 | 180 to 90 au | Low-poly proxy hull plus entity motes as one instanced mesh |
| 2 | 90 to 25 au | Decimated mesh or coarse point subset; anchors become interactable |
| 3 | inside the footprint | Full capture fidelity; all anchors live; the Companion may materialize |

Distance is measured to the footprint boundary rather than the centre, promotion and demotion use
asymmetric hysteresis (promote at `d`, demote at `1.25d`), and the cross-fade is dither-blended over
about 400 ms with both tiers drawn. A hard tier swap is not used because it pops and has no
asymmetric hysteresis. At most two regions are at tier 3 at once.

**The world never blocks. It degrades and it labels.** If a tier 3 asset is not ready on arrival, the
region stays at tier 2 with an inline caption saying so, and the user keeps walking, keeps
interacting and keeps talking. There is no state in which the application shows a spinner instead of
the world.

Regions have no edges, walls or platform rims. Each carries a dissolve band over its outer fifth,
where its own fog ramps up and the between-space particle field ramps up inversely. Standing in the
band you see two partially resolved regions at once, which is where cross-region identity threads
render at full strength. The between-space is not empty: its mote density is proportional to the
number of cross-region entity links whose thread passes overhead, so walking between two tightly
linked regions is visibly denser than walking toward an unrelated one.

**VERIFIED, and it is a comfort requirement rather than a taste preference.** Locomotion comfort
guidance recommends "art styles that make heavy use of more solid textures, and minimize the number
of visible edges and noisy textures", and describes vignettes that "darken or completely occlude the
edges of the screen when movement occurs" in order "to limit the amount of visible optic flow".
https://developers.meta.com/horizon/resources/locomotion-design-reduce-optic-flow/
The between-space must therefore be low frequency: large soft gradients, sparse motes, no
high-contrast tiling ground texture.

---

## 2. Navigation

### 2.1 Two verified platform facts that force the architecture

**VERIFIED FACT 1: there is no cursor position during pointer lock.** The Pointer Lock 2.0
specification states that while locked, `clientX`/`clientY` and `screenX`/`screenY` "must hold
constant values as if the pointer did not move at all once pointer lock was entered", while
`movementX`/`movementY` have no limit. https://w3c.github.io/pointerlock/

> **Consequence: cursor-hover UI cannot exist while locked. All world targeting is reticle-based, at
> fixed screen centre. This is forced by the specification, not chosen.** Any design that hovers a
> world object with the mouse pointer is unimplementable in this product.

The same specification states that "a default unlock gesture must always be available that will exit
pointer lock", recommends Escape as that gesture, and exits lock when the window or tab loses focus.
The Pointer Lock API documentation adds that an engagement gesture is required before re-locking
after a user-initiated unlock.
https://developer.mozilla.org/en-US/docs/Web/API/Pointer_Lock_API

> **Consequence: while pointer lock is active, the application can never own Escape and can never
> auto-relock.** Once lock has already been released for an open Companion exchange, Escape may
> dismiss that converse-mode surface. It is never prevented while the browser still owns unlock.

**VERIFIED FACT 2: pointer lock does not exist on the dominant mobile browsers.** Support data lists
iOS Safari 3.2 through 26.6 as Not supported, Android Chrome 151 as Not supported, and Samsung
Internet 4 through 30 as Not supported. Firefox for Android 153 is listed as supported.
https://caniuse.com/pointerlock

> **Consequence: mouse-look first-person navigation is impossible on iOS Safari and Android Chrome.
> The current prototype is therefore desktop/laptop only and stops at a viewport boundary rather
> than inventing a second navigation mode.** This is a hard platform limit with no workaround.

### 2.2 Two explicit input modes

**DECISION.**

| Mode | Pointer | Reticle | Movement keys | Panel |
| --- | --- | --- | --- | --- |
| `traverse` | locked | live | active | summon hint only; no open conversation |
| `converse` | unlocked, cursor visible | dimmed | disabled | interactive |

- `traverse` to `converse` on: Summon Companion, Interact on an anchor that opens a panel, opening
  the World Index, or the user pressing Escape (which the browser handles while locked; the
  application merely observes the pointer lock change event and follows).
- `converse` to `traverse` on: clicking the world surface when no conversation or system surface is
  open, or a persistent resume affordance. Because transient activation is required, resume must be
  a real click target and never an automatic retry.
- The world keeps rendering and animating in `converse`. Nothing pauses. That is what makes live
  consequence previews behind a panel possible (5.3).

### 2.3 Controls

**Camera direction, updated 2026-09-13; implementation absent.** A person can switch between
first-person and third-person views of the same controllable player. Provide a visible camera
control and a keyboard binding that does not fire while typing. Switching preserves the player's
position, grounded collision state and interaction context. The player avatar is distinct from the
synthetic population; its visibility does not create a simulated inhabitant or a new personal
identity. Simultaneous split-screen rendering is outside this camera milestone.

Third-person camera placement must shorten its follow distance around obstructions and avoid
clipping through ground or buildings. Picking begins at the displayed camera, while interaction
reach and traversal authority remain with the player. Character facing and movement animation
must follow actual resolved motion, including blocked movement. Camera transitions respect reduced
motion. Optional appearance customization can extend the player representation later without
changing navigation or identity authority.

Tune pedestrian walk/run speeds, acceleration, braking and turning against the actual street
scale. Verify diagonal speed, frame-rate behavior, collision sliding, focus loss, camera switching,
input in panels and recovery at coverage boundaries in the live experience. The existing city
speed override is not an accepted pedestrian movement target. Keep first-person inspection and
third-person movement legible in the same geometry.

The [character representation contract](character-representation-contract.md) extends this quality
requirement to every represented person: shared continuous human form, distance-driven stride,
planted stance feet, proportion-aware gait, and appearance independent of subject identity.

Mouse-look with raw input requested where the browser offers it, falling back silently rather than
surfacing an error. Pitch range is nearly full (a small epsilon short of straight up and straight
down) because the user must be able to look up at overhead connection threads. Mouse sensitivity is a
user setting.

Movement is WASD with a short critically damped acceleration ramp and a sprint modifier. Vertical
camera height follows terrain through a short spring and steps up automatically over small
obstacles.

**DECISION: no jump verb.** Rejected because nothing in the information architecture requires
vertical reach (all anchors are authored into an eye-height band), because jump signals platforming
affordances the world cannot honour, because airborne camera motion is uncontrolled vertical optic
flow at zero information gain, and because it consumes the space bar, which is worth far more as
Interact. The one legitimate use case, getting a vantage point on the layout, is served better by the
Atlas Map, which additionally shows semantic structure that height alone would not reveal.
Replacement: automatic step assist, near-full pitch, and the Atlas Map.

**Glide** raises speed in the between-space only, after sustained forward movement away from every
region, while narrowing field of view and ramping the vignette. Rationale: optic flow is generated by
nearby geometry, and the between-space has almost none, so it is the one place where speed is
comfortable and also the one place where nothing is happening. Fast where empty, slow where there is
content. **UNRESOLVED EXPERIMENT:** whether the chosen glide speed is comfortable, or needs a lower
cap. Half a day with three testers. Glide is out of the MVP cut, so this is not on the critical path.

### 2.4 Comfort settings

All persisted, all initialized from `prefers-reduced-motion`. **VERIFIED:** the media feature detects
"if a user has enabled a setting on their device to minimize the amount of non-essential motion", and
"animations such as scaling or panning large objects can be vestibular motion triggers".
https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion

| Setting | Values | Default |
| --- | --- | --- |
| Field of view | 60 to 90 | 70 |
| Vignette on move | off / subtle / strong | subtle |
| Camera bob | on / off | **off** |
| Turn mode | smooth / snap (30 degree increments) | smooth |
| Transition style | motion / fade | from `prefers-reduced-motion` |
| Companion initiative | normal / minimal / off | normal |

### 2.5 Supported viewport

**DECISION, see [ADR-0006](adr/0006-desktop-viewport-boundary.md).** The current prototype supports
laptop and desktop windows only. Its existing `60rem` layout breakpoint is a hard viewport boundary:
below it, the product shows one factual boundary notice and does not expose a mobile Index, mobile
commands, touch traversal, a virtual joystick or a rearranged Companion.

The World Index remains the non-spatial desktop accessibility route. It is not a device fallback.
Mobile delivery requires a separate product decision, implementation and validation pass; none is
implied by responsive CSS in this prototype.

### 2.6 Keyboard-only, and the accessibility route

**VERIFIED.** WCAG 2.2 SC 2.1.1 (Level A) requires all functionality to be keyboard operable, except
where the underlying function "requires input that depends on the path of the user's movement and not
just the endpoints". https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html

Free camera movement is path-dependent, but **none of Exulanica's actual functionality is**. Finding an
entity, inspecting its occurrences, opening the exact source image, confirming continuity, naming a
person, merging and reviewing are all reachable without moving the camera at all, through the World
Index. That is the compliance route, and it is also a better interface for a user in a hurry.

Inside the Atlas: arrow keys turn, W/S move, `Tab` cycles anchors in the current region by distance
and focuses each exactly as the reticle would, `Enter` interacts, `X` summons, `M` opens the Atlas
Map, `I` opens the World Index, `Backspace` pops the view manifest stack. Escape releases pointer
lock in traversal and dismisses the Companion only after its converse-mode exchange is open (2.1).

**System surfaces use a small, stable command vocabulary.** A quiet command strip makes it visible:
`I` opens the World Index, `M` changes only the camera into Atlas Map presentation, `O` opens
Options, and `?` opens the complete controls guide. Options and Controls are the only centred system
surfaces and only one major surface may own the cursor at a time. Closing either returns to the exact
surface and detail from which it was opened. Neither binds Escape.

**DECISION: Atlas opens as one living archival landscape, not a list of unfinished themes.**
Aeroheart is the sole complete user-facing identity: bright living terrain with optical memory
lenses, water-glass approaches, growth forms, and vector relationship signals. Blue Hour and the former
Celestial scaffolding are not exposed in the app. The atmosphere has its own non-semantic colours;
evidence and provenance colours are never reused as decoration.

The physical landscape uses chalk daylight, moss and mineral ground, dark stone, paper, and brass.
It is a real world shader and geometry composition rather than a viewport-wide CSS gradient.
Colour is never the only carrier of provenance or confirmation state.

Options exposes Standard/High contrast, Layered/Reduced transparency, and the active style's
manifest-generated world controls. It does not expose an incomplete style as a product choice.
Style controls preview physical terrain/material changes through the same protected transaction
boundary used by future Companion proposals. Presentation updates keep DOM legibility, point
provenance tints, and anchor motes coherent.

Three material roles exist: archive sheets for evidence and summoned reading, system sheets for
Options and Controls, and instrument strips for compact persistent chrome. Only instrument strips may
use a pill silhouette. The implementation lives in `@exulanica/presentation`, so landing, DOM chrome and
the renderer consume one versioned visual contract rather than copying theme values.

**Canvas content is invisible to screen readers**, so the DOM overlay is the accessibility surface
and must contain real focusable labelled elements. Every entity, every evidence item and every source
image must be reachable from a flat keyboard-navigable list.

---

### Default desktop application workspace

The application presents labeled Character, Library, Companion, Map, Customize and Settings controls.
Geographic exploration uses a place heading, a compact camera strip and separate Nearby,
Create and World details panels. Opening one contextual panel closes the previous one;
selecting a subject opens its inspection. Person activity and source/fiction distinctions
remain in the foreground, while identifiers, event references and provenance details use
explicit disclosures. Recorded preview controls and their limitations remain in World details.
Background simulation refreshes update an existing inspection without reopening a dismissed one.

Character opens with K; C retains the first/third-person camera toggle. The development preview
provides a full-body character studio backed by a pinned asset catalogue. People can rotate and
zoom the model, choose an available look, edit its supported material colors and inspect its
standing, walking and running animations. Controls follow the selected asset's capabilities;
the screen does not invent garment combinations, morph targets or equipment statistics.
Use in world applies the selected look to the existing player presentation and opens third person.
This is session appearance, explicitly not an account save. An authenticated character catalogue
and durable character customization are not connected to this application composition.

The native character renderer validates the pinned GLB container, rig joints, idle/walk/run clips,
material slots and optional variants before instantiation. It drives gait from collision-resolved
distance, keeps shared asset data separate from mutable skin/material instances, caps the displayed
synthetic set at 24 and rechecks current presence/source authority. Source withdrawal restores the
abstract fallback; denied presence hides both forms. These are renderer and fixture contracts, not
visual acceptance of garment fit, foot contact, crowd spacing or a production character family.

When enabled, opening a contextual tool in first person plays the selected character's original
right-hand reach once in a camera-relative presentation. The panel is usable immediately and
remains stable after the gesture ends. The gesture changes no world pose, collision, identity,
simulation or write authority. It is not a held palm-up pose or a physical interaction with a
world object. Movement, camera/surface changes, Escape and reduced motion interrupt or skip it;
unavailable gesture assets leave ordinary controls usable. Character provides a session toggle
for hand gestures. The independent preview and gesture stages release their resources on remount.

Library search is visible by default. Original-photo intake is inside the library and groups
its existing operations into choosing originals, authorizing processing, inspecting people,
and confirming review. These groups describe the workflow, not completed processing states.
The development preview disables upload and review and explains that an authenticated workspace
is required. Authenticated operations retain their existing authorization, exact-request retry,
consent, review and eligibility checks. File identifiers remain available through disclosure.

The Companion reads as one panel with the question, response choices and evidence actions in
order. Closing it retains the existing conversation lifecycle. Confirmation keeps its staged
proposal boundary; Escape cancels through the same handler as Cancel and returns focus to the
opening control. World panels release pointer lock before focusing their controls.

Application sheets apply a fixed cool-neutral reading palette and consistent control
geometry. This does not alter world materials, scene identity or the versioned world-profile
schema. High contrast and reduced-motion overrides remain authoritative. Broader theme authority
across world profiles still needs visual acceptance; this application pass does not establish
arbitrary user-supplied interface themes. The desktop viewport restriction remains in force.

The object catalog is reachable from Create. Availability is determined by the existing placement
contract: the geographic street does not itself establish a reconstructed region on which an
object can be placed. Development-preview objects, where placement is supported, are
session state and are not saved. A refusal must remain visible rather than claiming placement.

World details includes a bounded **World to data** inspector for renderer subjects that actually
declare a compatible surface/point pair. It preserves camera and selection, samples only existing
mesh triangles or borrows retained points, identifies generated samples as presentation rather than
measurement, and disables the slider for unsupported surfaces. Its record is a resident display
descriptor, not source artifact bytes. Current source availability and parent/residency visibility
remain authoritative and can remove both geometry and the record.

In an authenticated configured world, the same panel can read persisted society state and controls,
show saved play/pause and 1x/2x/4x settings, advance one simulated minute while paused, and inspect
recorded activity/event references. The development preview instead plays an explicitly labeled
recording and is not persistence or model evidence. The backend also accepts typed user requests for
an inhabitant to go to or perform a canonical target, but no browser control issues those
requests. Selecting a destination or inhabitant for inspection must not be described as directing it.

## 3. Two verbs, and the contextual affordance system

The entire verb set is `Interact` (contextual, acts on the focused anchor) and `Summon Companion`
(global, always available). Interact is visibly bound to `E`, with space and `Enter` retained as
keyboard alternatives. Left click is reserved for entering and maintaining camera look. Summon/dismiss
is bound to `X`, right click, and a persistent low-opacity affordance at bottom centre. The binding
lives in the shared controls layer so disabled system surfaces cannot summon behind themselves.

### 3.1 The problem, stated precisely

If every interactable object carries a label, the world becomes an inventory screen with a skybox. If
nothing carries a label, the world is a museum with no placards. **DECISION: labels are a function of
attention, not of existence, and attention is single-valued.**

### 3.2 The attention ladder

Four stages, driven by one focus solver that returns at most one target.

| Stage | Trigger | What is drawn |
| --- | --- | --- |
| 0 Ambient | none | A very low amplitude specular "breathing" on the anchor's surface region, period 4 to 6 s, phase randomized. Not UI, a material property. At most `ceil(sqrt(anchorCount))` anchors breathe at once on a rotating schedule, so a region with 60 detections shimmers with about 8 at a time |
| 1 Proximity | within a notice radius scaled by anchor importance | Breathing amplitude rises about threefold, a faint ground-contact ring appears. **Still no text** |
| 2 Focus | the reticle intersects the anchor's focus volume | The reticle ring expands instantly (targeting feedback that eases feels laggy) and **exactly one** compact label appears, offset to the lower right so it never occludes the centre. Three lines maximum: display name or an honest placeholder, a provenance and confidence chip, and the verb hint |
| 3 Engaged | Interact pressed | Focus latches, the Companion may materialize, the dialogue panel opens, the anchor gains a persistent selection outline |

**At most one label exists at any time.** That single constraint is the whole answer to "how do we
avoid covering the world in glowing labels".

### 3.3 Focus solver

One solver, scoring candidates within an interact radius and an aim cone by a weighted sum of aim
(0.60), distance (0.25) and importance (0.15). The cone widens for very close anchors, which is what
makes small nearby objects selectable without pixel-precise aim. A short dwell (about 90 ms) before a
winner becomes focused is what stops the label strobing while sweeping the view, and an incumbent
keeps focus unless a challenger beats it by a margin. Occlusion tests run against a coarse collision
proxy at reduced rate, never against the point cloud.

`importance` is derived rather than authored: unresolved status, current view emphasis, and
normalized occurrence count. A recomposition therefore automatically makes the relevant things easier
to aim at, which is a real ergonomic payoff for free.

### 3.4 Anchors to screen space

Anchors are projected manually each frame from world space into normalized device coordinates and
written as direct transform updates into pre-allocated DOM nodes inside the render loop. **No React
re-render per frame**; React re-renders only when the *set* of overlay elements changes, which is a
transition event rather than a frame event.

**DECISION: do not mount a per-anchor DOM helper component.** **VERIFIED:** the common React helper
for placing DOM in a 3D scene mounts a real DOM element with a wrapper per instance and, in transform
mode, a CSS `matrix3d`, with documented blurriness in that mode. https://drei.docs.pmnd.rs/misc/html
That is correct for one or two elements and wrong for hundreds of anchors.

Hard caps on the overlay: **1 focus label, 6 pinned callouts, 4 edge chevrons.** Pinned callouts get
a screen-space collision pass that pushes overlapping labels down and right in fixed increments with
a leader line back to the true projected point; overflow collapses into "+N more, open World Index".
Edge chevrons clamp off-screen anchors to an inset rounded rect, rotated toward the true direction.

**Evidence references adapt to the corpus.** The research defined an evidence reference as capture,
media, start and end milliseconds, track, and an optional normalized bounding box. With a photograph
corpus the interval is degenerate: per
[domain-and-evidence-model.md](domain-and-evidence-model.md) section 1.5, a photograph is a
single-sample track carrying the interval `[0, 1)` nanoseconds, refined by a normalized display space
region. The interaction layer treats an evidence reference as an **opaque handle** and never
constructs or parses one; it passes it to the evidence resolver and renders what comes back.

---

## 4. The Companion

### 4.1 Three-part encounter, deliberately separated

**DECISION.** The Companion encounter is a **presence in the world**, a **speech lens in the view**,
and a **separate decision rail**. The presence remains a rendered object. Speech, evidence, choices,
and custom reply remain accessible DOM. They use one fixed visual-novel composition and one optical
material language, not one generic card or a mirrored dashboard layout.

**DECISION, updated 2026-08-31: SVG geometric avatar.** The geometric silhouette and
two slit eyes draw on the visual grammar documented by the MIT-licensed Bloub project.
The product path is an original DOM/SVG implementation.
Shape, colour, and two-eye expression are saved device preferences resolved through a versioned
presentation contract. The implementation has no Spline runtime dependency.

Resting, attending, uncertain, working, and settled remain operational states, not an emotional
performance. Only `working` has a distinct semantic render: three pulsing dots. Expression
selection is appearance only and never changes confidence, intent, or what the Companion may do.

**Exchange, corrected from live review 2026-08-30.** The question occupies one dark optical-glass
speech squircle across the bottom centre. A small speaker-name pill physically bisects its top
boundary; the component accepts a name and receives `Companion`, so identity is not
hard-coded as permanent product chrome. Evidence actions stay in this lens because they support
what was said. Individual numbered answer pills occupy a fixed right-side rail. The next
numbered answer is `Other…`; opening it replaces that pill in place with an unlined composer and an
arrow icon rather than turning the encounter back into a form card. Unnumbered uncertainty, skip,
and correction responses remain in the decision rail. Escape dismisses the complete encounter and
has the same no-penalty meaning as Later.

**Association.** The presence occupies the upper centre over the current memory backdrop. Speech
anchors the bottom and decisions remain on the right. The presence is the Companion; the lens is
its accessible utterance and evidence; the right rail is what the person can decide. Index, Map,
Options, and Controls become circular icon controls around the speech band while an encounter is
open, maintaining a consistent control rhythm.

SVG supports the geometric design without an additional scene renderer.

Rejected alternative: putting the text inside the body or tethering a speech bubble to it. The
separate glass surface can still hold evidence and multi-select without turning the body into a
window frame.

### 4.2 Spatial placement

**DECISION, CORRECTED 2026-08-29.** The Companion is a screen-space overlay, not an entity in the
Atlas coordinate frame. It occupies the stable upper centre of the view. The presence does not
trail the camera, travel to anchors, or use inferred geometry for placement.

On ordinary laptop and desktop viewports the presence occupies upper centre, speech spans the lower
centre, and decisions remain right. The short 1012 × 324 stress layout preserves that same reading
order with a smaller character and shallower speech band rather than mirroring or recombining it.

`companion-placement.ts` reports `reference-fixed`. The current memory is intentionally backdrop,
so its projected rectangle does not reorder answers or move the question. Choices remain on
the right and dialogue remains below, preserving a stable reading order.

The screen-space presence does not use an in-world home or errand solver. One placement
model determines where the Companion appears.

Attention now happens inside the stable silhouette. A local gather marks an open question, and the world
anchor itself carries any required focus or evidence highlight. This keeps the presence findable and
lets the actual memory point at what the question concerns.

Under `prefers-reduced-motion`, blink and working-dot pulses stop on a settled frame. No
semantic information is lost because conversation content and evidence remain ordinary DOM text.

Implemented in `web/packages/app/src/ui/companion-stage.ts`.

#### SVG default; no character fallback renderer

The DOM/SVG avatar is the only Companion renderer. There is no Spline query path and no PlayCanvas
character entity. A future rights-cleared VRM or GLB character would require a separate design,
asset-provenance, licensing, performance, and accessibility decision; it is not implied by the
current geometric-avatar reference.

#### CORRECTED 2026-08-30: summon owns the mode transition

**DECISION, CORRECTED.** An open Companion conversation is always `converse`. Summoning releases
pointer lock because choices need a real cursor position; Pointer Lock freezes that position by
specification. WASD movement remains available relative to the last heading, while clicking the
world cannot recapture pointer lock until the conversation is dismissed. With lock already absent,
Escape dismisses the Companion even when the
custom reply has focus. Choice-set options keep their number bindings as an efficient keyboard
route, and the next number opens `Other…`; they no longer imply that an open panel may remain in
`traverse`.

Two properties this must keep. An unavailable option's key does nothing at all rather than falling
through to the next available option, because a key that silently selects something adjacent
commits a claim nobody chose. And the escapes are deliberately unnumbered: they are not answers to
the question, and giving them digits would put "skip" one keystroke away from an assertion about a
person.

### 4.3 The dialogue system

The architecture is taken from two verified game dialogue runtimes, as an architectural reference
only. No code from either is included; both are C#.

**VERIFIED.** The ink runtime documents that "a single ChoicePoint in the Story could potentially
generate different Choices dynamically dependent on state, so they're separated".
https://github.com/inkle/ink/blob/master/ink-engine-runtime/Choice.cs
This is exactly the semantics needed: the *place* a question is asked is stable, the *options offered*
are generated from current state each time.

**VERIFIED.** The Yarn Spinner runtime hands the host an option set whose options carry a line, an
id and an availability flag, and the host returns a selection then continues. On the availability
flag: "If this value is false, this option had a line condition on it that failed. The option will
still be delivered to the game, but, depending on the needs of the game, the game may decide to not
allow the player to select it, or not offer it to the player at all."
https://github.com/YarnSpinnerTool/YarnSpinner/blob/main/YarnSpinner/Dialogue.cs

That shape is adopted exactly. The difference is that the story is not authored text; it is generated
per turn from the entity graph.

A turn carries: an utterance with its evidence, an optional choice set (single or multi select, with
an explicit submit in multi mode), a free input affordance exposed as the next numbered option, an always-present set of
escapes, the subject anchor that connects the question to the world, and the graph state version
that invalidates it. Each choice carries an id, text, an availability flag with a reason shown when
unavailable, a kind, an optional update proposal that is previewed on focus, and a consequence tier.

**Choice mode rules.** Single select when the answers are logically exclusive or when the choice
carries a tier 2 or higher consequence; it commits on click. Multi select for attribute gathering,
always with an explicit submit. **Never mix a destructive or tier 2 option into a multi-select set**,
because a blast-radius preview cannot be rendered for a set.

**Escapes, always present, never penalized:**

| Escape | Recorded as | Effect |
| --- | --- | --- |
| Not sure | An explicit `uncertain` assertion, which is data rather than a null | Lowers re-ask priority on this entity for 14 days |
| Skip | The question is marked deferred | 7 day re-ask cooldown; initiative cooldown doubles |
| Later / Escape while open | The conversation is dismissed | Closes the thread, no penalty |
| That is the wrong question | A negative signal on (intent, entity) | The only channel by which a user can tell the system its framing is off |

The fourth escape is the underrated one and it is cheap to build. Without it, a user whose situation
the system has mis-modelled has no move except to keep skipping, and skip is indistinguishable from
disinterest.

Free text input is always available. It is parsed into the same update proposal draft that a choice
would produce and goes through the identical confirmation flow. **No path writes to the graph without
a proposal.**

### 4.4 How options evolve rather than being a form

Each turn is produced by a policy over the entity graph snapshot plus the conversation transcript, in
four stages:

1. **Select an intent** from a small closed set, by priority: resolve identity, confirm continuity,
   enrich relation, disambiguate claim, acknowledge.
2. **Build a candidate option pool from the graph.** For confirm-continuity the pool is
   {same person, different people, show me both moments} plus the escapes.
3. **Prune with hard deterministic rules before any model sees it.** Never offer an option targeting
   a deleted entity. Never offer merge for two clusters already asserted distinct. Where the reason is
   informative, mark the option unavailable with a reason rather than hiding it, following the
   availability semantics above.
4. **Only the phrasing is model-generated.** The id, kind, consequence tier and proposed update are
   constructed by deterministic code.

**DECISION, and the single most important safety boundary in the interaction layer: the model writes
words, the code writes consequences.** A model that hallucinates a sentence produces an awkward
question. A model that could author a proposed update could silently merge two people. The latter is
unacceptable, so the model is never in that path.

After a selection the graph patch is staged, the transcript appends, the state version increments,
and the generator runs again. Because the option pool is derived from current state, options genuinely
differ turn to turn. Worked example:

- **T1.** "I have seen this person in three captures but I do not have a name."
  `[Give a name] [They are someone I already named] [Not a person] | [Not sure] [Skip]`
- The user types a name and a relationship.
- **T2**, options now derived from that parse and from what it left uncertain: "I have a name and a
  relationship. Is she also the person in the harbour set?"
  `[Yes, the same person] [No, different person] [Show me that photo] | [Not sure] [Skip]`
- **T3**, after Yes, because the link changed the graph and made a new question reachable: "She now
  links four captures across two regions. Use that as her display name everywhere?"
  `[Yes] [Use a different display name] [Keep her name private to me] | [Skip]`

---

## 5. Update proposals and confirmation

### 5.1 The invariant

**No free-text answer and no choice ever mutates the graph directly.** Every path, including a single
click on "Yes, the same person", produces an update proposal, which is rendered, and only an explicit
confirmation commits it. This is a runtime check in the graph client, which rejects any mutation whose
proposal id is not in the pending set. It is not a convention.

A proposal carries: its id, the turn that produced it, its origin (user utterance, user choice, or
system inference), the **verbatim raw utterance, always retained and never paraphrased away**, its
operations, a provenance summary, the maximum consequence tier over its operations, whether it is
reversible, and the state version it expires on.

### 5.2 The confirmation surface

Four bands in fixed order, top to bottom. This is **one component with two mount points** (the
dialogue panel and the World Index entity detail view), so the two can never diverge.

1. **What you told me.** Warm accent. Quotes the user verbatim. Rows are inline-editable and
   removable.
2. **What the captures support.** Neutral. Rows carry evidence chips.
3. **What I inferred.** Cool and dimmed. Rows show method and confidence and carry an explicit Reject
   control.
4. **What I still do not know.** A plain list. **Never omitted, even when short.**

Clicking an evidence chip does not leave the Atlas. It opens the source image inline, docked to the
panel, and simultaneously the corresponding anchor in the world pulses. The written claim and the
spatial world point at the same evidence at the same time. That simultaneity is the product's central
promise made visible in one gesture.

### 5.3 Consequence tiers

Different consequences warrant different confirmation weight. Naming a person is not merging two
people, and merging is not deleting.

| Tier | Examples | Confirmation weight |
| --- | --- | --- |
| **0 silent** | Focus, emphasis, camera movement, opening the index | No proposal, no record |
| **1 light** | Naming, adding a relationship, adding a note, rejecting one inference | A single Save control, commits immediately, short undo toast, fully reversible from history. No typing |
| **2 heavy** | Merge, split, or any operation affecting more than six anchors or spanning more than one region | See below |
| **3 destructive** | Delete entity, delete region, forget a person | See below |

**Tier 2 requires**, all of them:

- A stated blast radius in counts: how many anchors, in which regions.
- **A live preview in the Atlas behind the panel.** The proposal generates a view manifest assigned to
  the preview slot (section 7), so the anchors that would join are highlighted and threaded **before**
  commit, in the actual world. Cancel restores instantly because nothing was mutated. This makes a
  structural consequence spatially legible instead of textual, which is the entire reason for having a
  3D interface.
- Two distinct controls, cancel and confirm, with the confirm control deliberately not under the
  cursor's resting position and enabled after a short delay, to defeat double-click carry-through from
  the option that opened the panel.
- Reversibility stated in words, and true: the merge is stored as an assertion and a split restores
  the original partition exactly.

**Tier 3 requires**, all of them:

- Typed confirmation of the entity's display name.
- An explicit statement, rendered **every single time**, that original media is not deleted by this
  action. Deleting an entity removes the index over the media, not the media. The retention guarantee
  is restated at the exact moment the user is most likely to doubt it.
- A named consequence: how many existing answers cite this entity and will lose their citation.
- **Never offered as a dialogue option and never offered by Companion initiative. Reachable only from
  the World Index entity detail view. The Companion may never propose a deletion, in any phrasing,
  under any circumstance.**

Tier 3 is out of the MVP cut. The rule stands regardless, so that adding it later cannot smuggle it
into the dialogue.

### 5.4 Audit

Every committed proposal appends to an immutable assertion log carrying the raw utterance, the
operations, the actor (user or system) and the state version. The entity detail view renders this as
History. Nothing is ever silently rewritten, including by the system's own later inferences: a system
inference that contradicts a user assertion is recorded as a contradiction and surfaced as a
question, never applied.

### 5.5 Companion initiative

Ambient channel, always on, never interrupting: an unresolved entity's anchor swaps its breathing for
a slower, cooler pulse and its ground ring becomes dashed. **No text.** One global counter sits in the
persistent HUD ("7 open questions", as a number and a word, at low opacity) and opens the review
queue when clicked. **It never grows a badge, never animates, never pops, never changes colour. It is
allowed to read 7 forever. There is no completion metric anywhere in the product.**

Spontaneous speech is gated hard: never in the first 90 seconds of a session, never while a capture
is forming, never while the user is moving, never about a subject that is not present, never more than
a small number of times per session and per hour, never within 7 days of a Skip or 14 days of a Not
sure on the same entity, never chained beyond a single follow-up, and never for a tier 3 operation.
Before speaking, the Companion **materializes silently** near the subject: an offer, not a question,
which dissolves if ignored. **The user never has to dismiss a modal, because there is never a modal.**
Ignoring is a first-class response and costs zero input.

**RISK (medium).** Initiative tuning is the most likely thing to feel wrong and cannot be validated
without real users. The initiative setting is the escape hatch, and "minimal" means ambient only with
no spontaneous speech at all. Spontaneous initiative is out of the MVP cut for this reason; the
ambient channel and the counter ship.

---

## 6. World Index, Atlas Map, review queue

### 6.1 World Index

Non-spatial, keyboard-first, and the desktop accessibility equivalent path (2.6). One entity table
under four facets:

- **Kind:** person / place / object / event / region. A region is an entity too. (The research listed
  voice and conversation here; both are deferred, see the product specification.)
- **Status:** confirmed / needs review / inferred only / user asserted / rejected / merged away.
- **Presence:** which regions, occurrence count, first and last seen.
- **Source of knowledge:** user provided / capture supported / inferred. Multi-select.

The fourth facet deliberately reuses the same trichotomy as the confirmation panel. One vocabulary
everywhere, so "what do you actually know about this" is answered identically in every surface.

Layout is a left facet rail, a centre virtualized list and a right detail pane. Search is one input
with prefix operators falling through to semantic search.
A row shows a kind glyph, a display name or an honest placeholder ("Unnamed person, 4 occurrences"),
a three-mark provenance triad, an occurrence count, the regions present, and a confidence bar only for
inferred entities.

Entity detail has a fixed section order: identity, the four-band provenance panel (the same component
as 5.2), occurrences (a chronological evidence list, each opening the exact source image: this list is
the mechanical answer to "every claim resolves to a source"), relations, and history.

Actions and their tiers: Locate (0), Inspect (0), Edit (1), Review (0, produces 1 or 2), Merge (2),
Split (2), Delete (3, and the only place delete exists).

The index is a route with URL-encoded facets, so a filtered state is linkable and browser navigation
works. **It renders as an overlay above the still-live Atlas canvas, not as a separate page.** The
Atlas keeps rendering behind it and reflects the current selection's view manifest. Opening the index
enters `converse` mode.

### 6.2 Atlas Map

**DECISION.** The map is not a different data structure, a different scene, or a minimap. It is **the
same scene with a different camera pose plus a representation tier override.** Pressing `M` animates
the camera to a high vantage over the atlas centroid, tilted roughly 55 degrees from horizontal (never
straight down, because a plan view destroys the sense that this is one continuous space), and forces
every region to tier 0 or 1. The user's ground position is drawn as a marker with a view cone.
Returning is the reverse animation to the identical pose.

It shows region sigils with name, date range and count; cross-region threads whose thickness is
proportional to shared confirmed entities, drawn as catenary curves that read from above; the current
view manifest emphasis, applied identically to the ground view; a per-region unresolved count; and the
user's position.

It carries a persistent, never dismissible caption:

> "Positions show how these memories relate, not where they happened."

Because it is literally the same space, it cannot lie about being geographic in a way the first-person
view does not. This caption is the user-facing half of the coordinate rule in 1.2; the branded types
are the machine-facing half.

**Locate** targets a **vantage pose, never the anchor position** (standing inside a person is not a
view of a person): a standoff distance scaled by the focus volume, at eye height, looking at the
anchor, with an occlusion raycast that rotates the preferred view direction and retries. Travel is a
spline with the vignette ramped across the middle of the move and field of view narrowed, which is
precisely the case vignetting exists for: enforced movement the user did not steer. Under reduced
motion, travel becomes a short cross-fade with an arrival caption, **ending at the identical pose so
no other subsystem branches on which path ran.**

### 6.3 Review queue

**DECISION: the review queue is not a feature, it is a preset.** It is the World Index filtered to
"needs review", sorted by the **same value function that drives Companion initiative**, with review as
the default detail action. Same component tree, same runtime, same proposal flow.

Two consequences. First, the review path and the browse path can never diverge in behaviour or in
provenance display, because they are the same code. Second, the queue cannot become a completion-driven
chore surface, because it is a filter over an inventory: there is a count, there is no "0 of 12
complete", no progress ring, no streak, and the empty state says that nothing needs attention rather
than congratulating the user.

Sharing the value function means the ambient counter, the Companion's choice of what to raise, and the
queue order all agree on what matters. If they disagreed, the product would feel like two systems
arguing.

Batch operations are permitted for tier 1 only. **Prohibited at tier 2 and above**, because a blast
radius cannot be previewed meaningfully for a set, and merge is exactly the operation where the user
most needs to see the consequence before committing.

---

## 7. Dynamic recomposition as a view transformation

### 7.0 One Selection, many entry points

**DECISION, see [adr/0005-unified-selection-model.md](adr/0005-unified-selection-model.md).**

Filtering by a person, an object, a place, a time range, or a trip is **one mechanism**, not five.
Every surface produces the same structure, and nothing downstream knows which surface produced it.

A **Selection** carries five dimensions:

| Dimension | Contents | Notes |
| --- | --- | --- |
| Entities | people, objects, places | ANY or ALL. ALL requires a shared evidence window, not co-presence in one capture |
| Time | one or more capture-time intervals | From EXIF. Covers every photograph, including ones that can never be reconstructed |
| Place | place entities or spatial clusters | From EXIF GPS, user labels, and capture-supported signage |
| Capture | reconstruction rung, processing state | Lets a user ask for what is actually explorable |
| Epistemic | confirmed only, or include proposals | The user chooses whether they are looking at what is known or what is guessed |

It resolves deterministically to evidence spans, the islands those spans touch, and a view manifest.

**Time and place are the most reliable dimensions in the system.** They come from EXIF, cost no
model calls, and are correct for effectively every photograph. Identity is a probabilistic proposal
awaiting confirmation; a timestamp is not. For a library of a few thousand travel photographs, time
and place filtering is what makes the Atlas navigable at all.

Four entry points, all equal:

1. **The Companion**, which proposes a Selection from a natural-language turn and shows it before
   applying it.
2. **The World Index**, through clicking an entity, a date range, or a place.
3. **The Atlas Map**, through selecting a region or an island.
4. **Direct `Interact`** on a person or object in the Atlas.

**The Companion has no privileged path.** It emits the same validated plan the interface emits and
passes the same server-side validation. It cannot express a filter the interface cannot, and the
interface cannot express one it cannot reach. This is the existing query-safety rule (the model
emits a restricted declarative plan, never an executable query) applied consistently rather than a
new constraint.

The practical test: anything the Companion does must be inspectable and repeatable by clicking, and
a user who ignores the Companion entirely loses no capability. That matters for a product whose
thesis is that the user stays in control of what gets asserted.

**OPEN: an island may be a cluster rather than a single capture.** With five curated captures, one
island is one capture. With a few thousand travel photographs that is thousands of islands and the
Atlas is noise. The likely answer is that an island is a place-on-a-trip cluster with individual
photographs as shards inside it, but this stays open until the real distribution of the corpus is
measured. The Selection model must not assume one island per capture.


### 7.1 The key structural decision

**DECISION, identified in the research as the key structural decision of the interaction layer:
recomposition is a pure view transformation over an unchanged, never-reloaded scene graph.** Geometry,
region placements and anchor positions never change in response to a query. What changes is a
per-object emphasis scalar plus a set of derived overlay elements: threads, captions, chevrons.

Rejected alternative: rebuilding or re-laying out the scene per query, which is the obvious reading of
"the Atlas reorganizes around that continuity". Rejected because it is slow, not previewable, not
cheaply reversible, and disorienting: it destroys the user's spatial memory on every query.

This decision is what makes recomposition fast (one typed-array write), reversible (pop a stack),
previewable (assign to a preview slot), and non-disorienting (the world's shape is invariant).

### 7.2 The view manifest

The manifest is the data structure the whole feature turns on:

| Field | Meaning |
| --- | --- |
| `manifestId`, `createdAt` | Identity |
| `stateVersion` | The graph version this was computed against |
| `query` | What produced it. Drives the caption and undo. Kinds: entity, conjunction, disjunction, temporal, natural language |
| `emphasis` | Sparse maps of anchor id and region id to an emphasis level, plus a default level (muted while a query is active, normal otherwise) |
| `threads` | From and to anchor references (may span regions), entity id, strength, style, and dashed flag |
| `captions` | At most 6, screen-space, projected each frame, each with its evidence |
| `focusCandidates` | Ordered; drives Tab cycling and edge chevrons |
| `summary` | Text, counts, evidence |
| `transition` | Duration and style (cross-fade or instant) |

Emphasis levels are `primary`, `secondary`, `normal`, `muted`, `hidden`, and every renderable reads
one float uniform derived from them, controlling opacity, saturation, bloom, fog boost, and whether
the object is interactable and labelable.

Client state holds a manifest **stack** (push on refine, pop on `Backspace`), an active manifest, a
pinned manifest that survives navigation and shows as a HUD chip, and an ephemeral **preview** slot.
Hovering or keyboard-focusing a dialogue option whose proposed update would change the world sets the
preview slot; blur clears it. That is exactly the mechanism behind the tier 2 blast-radius preview
(5.3), and it costs nothing extra because it is the same code path as a query.

### 7.3 Four anti-disorientation rules

1. **Never use `hidden` for query results. Mute, do not hide.** The world's shape must stay constant
   so spatial memory survives across queries. `hidden` is reserved for content the user deleted.
2. **Never move geometry in response to a query.** Semantic proximity as a recomposition signal is
   expressed through threads and brightness, not translation. Regions move only when the persisted
   layout changes, which is rare, announced and slow.
3. **The camera does not move on a recomposition** unless the user explicitly asked to Locate. A query
   changes what the world looks like, not where the user is standing. Conflating those two is the
   fastest way to make a spatial interface nauseating.
4. All emphasis transitions are a single cross-fade on the uniform. Under reduced motion the
   transition is instant and **the summary caption becomes mandatory**, because the change now has to
   be carried verbally.

**UNRESOLVED EXPERIMENT.** Whether muting rather than hiding stays legible when most anchors are
muted, and whether the chosen cross-fade duration is right. Half a day, tunable in a debug panel.

### 7.4 AND and OR must look different, not merely count differently

| Query | Primary | Secondary | Threads | Caption |
| --- | --- | --- | --- | --- |
| One entity | That entity's anchors | Anchors of co-occurring entities | Solid identity threads linking it across regions | "Appears in 14 occurrences across 3 regions." |
| A OR B | Both sets | none | Per-entity threads in two distinguishable hues | "14 with A. 9 with B." |
| A AND B (together) | Only anchors where **both** are present within the co-presence window in the same capture | Anchors with exactly one of them | **Solid** for co-presence, **dashed** for single presence | "3 with both. 11 with A only. 6 with B only." Each count clickable to swap the manifest |

This is easy to get wrong and it matters: solid means "these two were together here", dashed means
"only one of them was here". A user can then read the answer off the world instead of off a sentence,
which is the reason for having a 3D interface at all.

### 7.5 Performance contract

Emphasis must never cause per-object material changes or scene graph mutation. Anchors are drawn as
one instanced mesh per region with a per-instance emphasis attribute, so a manifest change writes one
typed array and flags it. Region body materials read a single uniform. Threads are one line object per
manifest, rebuilt only on manifest change. Zero React re-renders on emphasis change. Applying a
manifest is a tight numeric loop over anchors, safe to run on every hover for previewing.

If the graph changes underneath (a merge commits), a stale manifest is recomputed, and if
recomputation materially changes the result **the caption says so** rather than the world silently
rearranging.

---

## 8. Processing as spatial formation

### 8.1 The rule

**Every visual formation state is paired with a factual label naming the real pipeline stage and the
real unit of progress. There is no synthetic progress bar and no invented percentage.** If remaining
time is unknown, no remaining time is displayed; what is displayed is the count that is actually
known.

### 8.2 Stage map, for a photograph corpus

The research's stage map was written for video. The audio stage is removed and the frame extraction
stage becomes image ingest, per the corpus decision in the product specification. Everything else
carries over.

| Real pipeline stage | Visual state in the Atlas | Honest label pattern |
| --- | --- | --- |
| Upload received | A dim unlit void volume appears at the region's future placement; sparse motes drift inward | "Received 148 photographs. Not yet processed." |
| Decode and metadata read | Motes begin aligning onto a faint horizontal disc, the future ground plane | "Reading images: 62 of 148." |
| Pose estimation | Thin wireframe camera frusta appear along the estimated trajectory; the disc gains real extent | "Estimating camera positions: 91 of 148 registered." |
| Dense reconstruction | Motes migrate onto surfaces; the region resolves silhouette to structure **in the order the reconstruction actually converges**, not uniformly | Shown only when a real fraction exists |
| Entity detection and embedding | Anchors light up as small motes at detection positions, one per detection, appearing as each is actually written | "Found 12 people, 4 objects, 2 places." |
| Cross-capture linking | Threads reach toward existing regions, one per candidate link, dim while uncertain | "Comparing with 2 existing regions." |
| Ready, with open questions | The region reaches tier 1 or better, unresolved anchors take the dashed ring, the global counter increments | "This region is ready. 7 things I am unsure about." |
| Failure at any stage | Formation visibly **stops**; motes settle and dim; the partial region remains and is enterable if poses exist | "Reconstruction failed after 91 images. The photographs are available." plus details and retry |

### 8.3 Honesty rules

- **A stage's visual must never run ahead of the data.** Anchors appear only as real detections land.
  If the backend delivers in a burst, motes appear in a burst. Never animate a fake trickle to look
  smooth.
- **If progress is not measurable, the visual breathes rather than advances**, and the label shows
  elapsed time. A non-advancing breathing state is more honest, and in practice less anxiety-inducing,
  than a bar frozen at 94%.
- **Partial usability is the point.** The label always states what is already usable, not only what is
  pending.
- **Failure leaves the partial region in place.** A failed reconstruction with good source images is
  still a useful memory region, and deleting it to keep the world tidy would be a lie about what we
  have.
- The region also displays **which reconstruction rung it earned** (product specification section 5).
  Formation labels and the rung label are the same honesty mechanism at two timescales.
- Under reduced motion, mote animation becomes discrete cross-faded state changes and **the label set
  is byte-identical**. No information ever lives only in the animation.

### 8.4 Transport, and the caveat that gates this whole section

Progress arrives as server-sent events per capture, each carrying stage, stage index, counters, a
message, a timestamp and an event id. The client maps events to visual state and resumes from the last
event id on reconnect. If the stream drops, the visual **freezes** rather than continuing to animate
optimistically, and the label says contact was lost.

**ASSUMPTION (A-29), and it is the caveat the research attached to this entire design: this section is
only buildable to the extent the pipeline emits real per-stage counters.** If it cannot, the
counter-bearing stages degrade to breathing plus elapsed time, which is still honest and still better
than a fake bar, but is a materially smaller design. Experiment: inspect the pipeline stage boundaries
for available counters, roughly two hours. **The research says explicitly that this should be checked
first, because everything else in this section depends on the answer.** Verification is first.

---

## 9. Accessibility and reduced motion

**VERIFIED.** WCAG 2.2 SC 2.3.3 Animation from Interactions (Level AAA): "Motion animation triggered
by interaction can be disabled, unless the animation is essential to the functionality or the
information being conveyed."
https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html

**DECISION.** Every non-essential motion has a non-motion equivalent that carries the same
information. Directly user-driven first-person camera motion is the essential function and is exempt,
and section 2.6 provides the equivalent non-spatial path for all of it.

| Motion | Reduced-motion alternative | What replaces the lost information |
| --- | --- | --- |
| Recomposition emphasis cross-fade | Instant | The summary caption becomes **mandatory** |
| Locate travel | A short cross-fade cut, ending at the identical pose | An arrival caption |
| Layout reflow | Instant | The Companion's one-line explanation becomes mandatory |
| Formation animation | Discrete state changes | Nothing: the label set is identical in both modes |
| Glide | Disabled | Nothing lost; glide carries no information |
| Companion materialization | Cross-fade instead of assembly | Nothing lost |

Other accessibility commitments:

- **The DOM overlay is the accessibility surface**, because canvas content is invisible to screen
  readers. Every entity, every evidence item and every source image is reachable from a flat
  keyboard-navigable list.
- Full keyboard operation of every function without moving the camera (2.6).
- Snap turning in fixed increments for keyboard-only and comfort-sensitive users.
- Field of view and vignette are user settings, not fixed values (2.4).
- **The reduced-motion default is read from the platform**, not asked for in an onboarding step.

**RISK (medium).** Reduced-motion users lose information that lives only in animation. The mitigation
is structural rather than procedural: every animated state change has a mandatory textual equivalent,
and formation labels are identical in both modes.

---

## 10. Renderer decision

Every interaction mechanism above is described in engine-neutral terms except where a verified source
is quoted. **CLOSED:** [ADR-0003](adr/0003-renderer-selection.md) selected PlayCanvas Engine
2.21.4 through the matched-resolution bake-off. The application, owned district, native
characters and representation runtime use the PlayCanvas binding. Three.js/Spark remains a
separate implementation and is not the production browser path.

The interaction contracts retain these engine-independent requirements:

- All world targeting is reticle-based, because that is forced by the Pointer Lock specification
  (2.1), not by any engine.
- The DOM overlay is the primary UI and accessibility layer, with manual projection into
  pre-allocated nodes and the caps in 3.4.
- Emphasis is a per-instance numeric attribute plus a uniform, never a per-object material change
  (7.5).

The implementation is not portable for free. A renderer change would require a new measured
decision and replacement bindings.

---

## 11. Open items owned by this document

| # | Item | Settled by |
| --- | --- | --- |
| I-1 | Cross-capture co-registration success rate, which gates the shared-frame exception in 1.3 | An experiment that is absent from the plan. Until it exists, do not ship pooled frames |
| I-2 | Renderer (section 10) | Closed by [ADR-0003](adr/0003-renderer-selection.md): PlayCanvas Engine 2.21.4 |
| I-3 | Per-stage counters, which gate section 8 | A-29, two hours, do it first |
| I-4 | Layout at three regions: algorithmic or hand-placed (1.4) | Side-by-side comparison on the three real captures, two hours |
| I-5 | The Companion uses the fixed centre/right/bottom encounter composition and needs no tether (4.1) | Closed |
| I-6 | Whether muting stays legible at high mute ratios, and the right cross-fade duration (7.3) | Debug-panel tuning, half a day |
| I-7 | Nothing further. The evidence reference shape for stills, previously open here, is settled in [domain-and-evidence-model.md](domain-and-evidence-model.md) section 1.5 | Closed |
