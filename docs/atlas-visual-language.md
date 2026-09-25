# Atlas visual language: Aeroheart

Status: **DECISION** and **IMPLEMENTED** for the new-user arrival, one source-first encounter, and
the minimal world-native first-use orientation described below. Production media loading,
reconstructed geometry, backend style authority, and validated onboarding language remain out of
scope.

## 1. Visual thesis

Aeroheart governs how a person's own photographs and memories look where they appear in a world.
Those are one feature of a world and one way to build it; the product is a world that open models
run ([product direction](product-direction.md)).

**Aeroheart is source weather.** Atlas is not a low-poly landscape with memories placed on it. It is
one continuous atmospheric field whose light, clarity, and motion change around evidence. A memory
is the sharpest part of that field because it carries exact authorized source media. Relationships
are precise seams through the field. Interface chrome does not provide the composition.

The signature phenomenon is the **source aperture**. An available photograph appears once, at its
true aspect ratio, on a shallow optical curve. Its edge loses registration into air rather than
ending at a frame. At distance the image has slight chromatic separation and diffusion; attention
registers it. Its colour continues below as a low-contrast reflection, so the source affects the
space without pretending to reconstruct the photographed place.

The navigation surface is a **continuity field**, not a floor. **CORRECTED:** it was a deep teal
body until `fac64ac` moved Aeroheart to a light field, and it now reads as near-white paper carrying
directional optical interference. Contrast near the viewer comes from the interference and the
source reflection rather than from a dark ground. At grazing angles and distance it converges to the
exact haze colour used by the sky. Local terrain rises therefore disappear into air instead of
drawing a hard ground/sky cut, and the convergence is now nearly total: the horizon is a change in
structure, not a change in value.

Frutiger Aero contributes optimism, air, water, glass, and familiar optical material. Vectorheart
contributes restraint, exact vector relationships, and graphic contrast. Aeroheart does not borrow
their bubbles, grass, chrome typography, industrial ornaments, or nostalgic interface shapes.

## 2. Semantic visual dictionary

| Concept | Form | Material and colour | Behaviour |
| --- | --- | --- | --- |
| Memory with available source media | One source aperture using the exact primary photograph at its native 4:3 ratio in the fixture. No frame, card, portal ring, or duplicate billboard. | Source colour remains authoritative. Ivory edge light and a source-coloured atmospheric reflection bind it to the field. | Slight colour separation and surface deformation settle as the viewer approaches or focuses. The exact same evidence opens in Index detail. |
| Memory with unavailable evidence | A bounded, hollow, interrupted contour with no sampled image and no generic replacement art. | Cool unresolved violet carried at lower contrast through haze. | It remains navigable at the protected destination but stays smaller and visibly incomplete. It cannot resolve into invented content. |
| Person | Paired vertical presence brackets around a cited occurrence. Never a body model. | Provenance colour plus date in the accessible overlay. | Focus tightens the bracket and exposes its citation. |
| Place | Four open corners defining an absent frame. | Capture hue with squared geometry. | Corners tighten on focus; the empty centre distinguishes it from source media. |
| Object | A compact lozenge. | Provenance hue; edge continuity expresses link state. | Focus increases contrast, not physical reconstruction. |
| Event | Four unequal rays around a centre. | Provenance hue with a warmer centre. | A sequential flare indicates temporal gathering, not a quest or alert. |
| Confirmed relationship | A continuous, fine, gently curved seam within the continuity field. | Warm solar gold. | A restrained travelling glint expresses continuity. Only confirmed topology receives it. |
| Inferred or uncertain relationship | A structurally broken cool-violet seam local to candidate evidence. | Violet with physical gaps, not a low-opacity confirmed line. | Segments remain misregistered and do not become persistent placement authority. The current fixture does not expose a cross-memory inferred trace to the renderer. |
| Region or memory neighbourhood | A broad, low-contrast field response around stable placement, exposed directly in Map. | Nearby field light shifts slightly toward the region/source response. | Slow interference gathers and dissolves without forming an island rim, plinth, or platform. |
| Unresolved material | Missing contour intervals, incomplete entity edges, or broken relationship seams. | Cool violet/graphite. | Asynchronous drift; never alert blinking. |
| User's current focus | One winning aperture or entity glyph, plus the existing reticle/focus projection. | Retains source colour; warm ivory only clarifies its boundary. | Focus sharpens and registers. It never recolours the memory or creates a decorative halo target. |
| Traversal | Movement through one continuous field with near-field optical flow and source parallax. | No road, stepping stone, runway, rail, or dedicated floor marking. | Movement reveals depth while the field remains visually continuous with the atmosphere. |
| Direct travel | The existing validated camera transition through the same live scene. | No portal, ring, loading world, or teleport effect. | Ends at atlas-core's exact safe position. Rung-4 presentation changes orientation only so the source is faced. |
| Growth, change, recovered detail | Increased source registration, another authorized source aperture, a completed evidence contour, or a newly confirmed continuous seam. | Personal source colour and confirmation gold. | More evidence or certainty becomes more legible; decorative density never substitutes for knowledge. |

## 3. Starter spatial architecture

The opening is deliberately world-only. The rejected rounded onboarding panel, CTA, memory caption,
and their show/dismiss navigation state were deleted. First use reuses the restrained bottom-centre
Companion prompt to say what Atlas is, then reveals entry, movement, and Companion actions only as
the user demonstrates the preceding action. A temporary text legend beneath the existing circular
commands explains that Index reads evidence and Map shows relationships. It disappears after a
command is used; the same meaning remains recoverable in Controls. Progress is action-based and
device-local, with no timer, route lock, graph write, or invented completion metric. Once called,
the Companion occupies the upper centre over the memory backdrop. Speech spans the bottom centre
while individual decision pills occupy a fixed right-side rail. The distinguishing mark is
the speaker-name pill physically intersecting the speech lens, not an extra glow, rule, badge, or
gradient. Index, Map, Options, and Controls become four circular icon buttons around the speech band
while the encounter is open. The short laptop stress layout keeps the same centre/right/bottom
reading order without recombining it. The default presence is a geometric SVG avatar: one coloured
silhouette and two slit eyes, with no humanoid anatomy and no second renderer. The rejected robot,
Spline path, source-plane mark, and mote placeholder were deleted rather than restyled.

A world opens in the region holding the most of the person's placements, at that region's own
viewpoint ([`opening-region.ts`](../web/packages/atlas-react/src/playcanvas/opening-region.ts); the
rule is stated under Arrival in [atlas-reconstruction-inspection.md](atlas-reconstruction-inspection.md)).
A reconstructed region opens where its first photograph was taken, looking where that camera
looked; any other region opens level, a few metres from its placement and facing along it, looking
at its own ground. There is no lateral offset reserved for UI.

The continuity field and sky share one horizon value:

- near field: light paper body plus slow low-frequency and crossing interference;
- middle field: lifted mint and source reflection establish scale;
- distance/grazing field: analytic convergence to the sky haze value;
- upper atmosphere: clear cyan-teal with restrained cloud structure and a small warm sun;
- Map: the sky shell is hidden and camera clear colour matches the cartographic field, preventing a
  cyan strip or exposed mesh edge from masquerading as another spatial layer.

This is appearance only. The navigation surface, collision, safe destinations, Map pose stack,
GraphSource boundary, topology identity, evidence references, and versioning contracts are
unchanged.

## 4. Semantic objects versus atmosphere

Semantic objects are source apertures, unavailable evidence contours, entity glyphs, confirmed and
uncertain seams, Map region targets, the saved ground pose, and truthful travel/evidence feedback.
Each derives from graph, evidence, navigation, or reconstruction state.

Atmosphere is limited to the continuity field, sky, sun, horizon volume, low-amplitude optical
motion, and source reflection. Atmosphere establishes scale and dream depth but may not resemble an
additional selectable memory.

Removed or rejected from the user-facing origin profile:

- plants, buds, stones, ridges, stepping paths, glass runways, rails, plinth discs, portals,
  beacon ornaments, and terrain platforms;
- the olive low-poly landscape and its visible stage edge;
- the Blue Hour full-screen treatment and vertical renderer scaffolding;
- the five-billboard held-light experiment;
- the 38-thread/barcode recollection weave;
- the large rounded onboarding card, CTA, compact encounter card, and standing pill chrome;
- blurred side wings that did not read clearly enough to justify their presence.

Survey Relief retains some non-origin geometry only as an internal topology-compatible regression
fixture. It is not a second product identity.

## 5. Composition and interaction rules

1. Exact source media is the largest, sharpest, and highest-local-contrast object in a memory
   encounter.
2. One source appears once. Reflection and atmospheric response may use its light but may not become
   a second readable copy.
3. Source aspect ratio is preserved. Edges may lose registration into air but may not crop people,
   objects, or evidence to create a fashionable silhouette.
4. The ground-to-sky transition may not depend on a distant ridge, decorative prop, or colour wash.
   The field and sky must converge mathematically.
5. Dream motion is slow, low amplitude, and concentrated in one event: source registration.
6. Relationships use lines only when topology supports them. No line may be introduced solely to
   lead the eye or decorate empty ground.
7. Direct travel never changes the validated destination. Presentation may face and angularly
   contain a source.
8. An unavailable source is absence with a bounded location, not a placeholder image, error card,
   pixel wall, or oversized obstruction.
9. Map is the same topology and same ground pose exposed at a different camera state. It is not a
   separate dashboard world.
10. First-use orientation must reuse world-native surfaces. It may explain Atlas, entry, movement,
    Companion, Index, and Map in response to demonstrated actions, but may not cover the world with
    a tour card, lock a route, or imply that memory is ever complete.

## 6. Palette and material

**CORRECTED.** This section published a dark teal palette that the build has not used since
`fac64ac`. The artefact is `packages/presentation/src/world-style-recipes.ts`, which moved
Aeroheart from a world you look into to a world made of light. The palette below is the one the
code actually holds.

The style is **diffuse light**, and it is four rules rather than a look:

1. Colour arrives as large soft fields, never as a fill inside a shape.
2. The ground is light, so the darkest thing on screen is the reading.
3. Structure is carried by type, spacing and one shared margin. A container is drawn only where
   two things would otherwise be mistaken for one.
4. A summoned surface is an object held in the world at an angle, not a page laid over it.

What follows from those: no dividers between rows of the same kind, no filled bands behind
headers and footers, one hairline per surface rather than one per section, no card, no drop
shadow standing in for hierarchy, and no ornament of any kind. Every one of those is something
the interface does and the rules above refuse.

World palette before personal media contributes local colour:

- **open air** `#a8d5df`: upper atmosphere and the interface's structural hue;
- **haze** `#fffaf4`: the shared field/sky convergence colour;
- **field** `#eef7f2`: near-field body, light rather than deep;
- **field lift** `#dcefdc`: optical interference, region response, capture provenance;
- **trace** `#ffac38`: relationship continuity and caution;
- **paper** `#fffdf8`: edge registration and readable optical light;
- **signal** `#f96858`: the one warm root: user-provided provenance and the evidence accent;
- **field shadow** `#b7c8e5`: inferred and uncertain structure;
- **sun** `#fff3bf`: warm light and the Companion's accent.

**The palette is light, so the interface may not be derived by darkening the ground.** Two rules,
both in `packages/presentation/src/world-style-model.ts`, exist because their absence cost the
interface every colour it had:

1. **A role is placed at an authored perceptual lightness, and contrast correction is only a
   floor.** When each role was handed a world colour and left for the contrast corrector to
   darken, all thirteen landed within 0.06 of their own minimum. The interface occupied two
   values, and no component work could build a hierarchy out of that.
2. **Darkening happens in OKLCH, not by mixing toward black in sRGB.** An sRGB mix preserves the
   channel ratio and destroys the channel difference, so a pale tint darkens to grey: `#eef7f2`
   taken to a readable value arrived at `#545756`, four points of chroma out of the twelve it
   started with. Every structural role in the interface is a darkened world colour, so that one
   property decided what the whole interface looked like.

Two further rules follow from the light ground. Structural roles read from the ground and the air
together rather than from the ground alone, so a world that authors a light field still has a hue
to spend. And the reading floor carries a margin above the requirement, because a role corrected
to exactly 4.5 against the lightest theoretical surface is below 4.5 on the paper a held plate is
actually made of.

The Companion encounter is not assigned a second palette. Its deep optical surface, memory text,
accent, evidence, confirmation, and uncertainty roles are derived from the world roots above and
contrast-corrected by the trusted adapter. This keeps every personal variation in the Aeroheart
family while preventing low-contrast generated combinations. Speech and labels use Avenir Next
where installed with a system sans fallback. Number keys and unavailable reasons use the restrained
system monospace role. There are no decorative gradients in the encounter.

ACES tone mapping remains enabled, exposure is reduced to 1.06, the sun disc is smaller, and fog
begins earlier. These values prevent the source from being blown out while retaining warm/cool
depth. Interface surfaces do not reuse the source-aperture material.

## 7. Customization implications

The protected profile remains `origin-landscape@1`; storage and compatibility identifiers are
unchanged.

The profile now owns one shared visual DNA palette plus an interface expression. The renderer uses
the palette roots directly; the interface derives semantic roles from those roots. Typography,
surface blur/saturation, registered texture family, and motion timing remain reviewed profile
capabilities. Control shapes,
hit areas, placement, and reading order remain system-owned, so the circular Atlas commands,
speech lens, and choice silhouettes stay recognizable across worlds. Aeroheart's current skin is
one profile, not a set of component literals. The same Index, Map, Options, Controls, dialogue, and
choices can therefore take on another registered world's material language without forking their
structure or behavior. Arbitrary CSS and remote texture URLs remain outside the contract; new
texture or motion capabilities require a reviewed registry addition.

- `vitality` changes optical/source-light chroma, not plant colour;
- `glass` is presented as aperture clarity and changes transmission/edge definition;
- `relationship-energy` changes confirmed-seam visibility and glint, never relation existence;
- the storage-stable `garden-density` key is presented as source detail and changes bounded
  optical detail, never evidence count or decorative ecology;
- `horizon-softness` changes the convergence band but may not reveal a field edge or hide an
  available destination.
- `surface-finish` selects only a registered finish and applies it across the field and summoned
  interface surfaces;
- `world-tempo` changes ambient field/source time and interface cadence inside a bounded range;
  reduced motion always overrides it.

All changes remain appearance proposals. They cannot add evidence, confirm a relationship, move a
region, change navigation, or widen traversal.

## 8. Deterministic focused fixture

The development preview uses four small source-first regions about Mara, a glasshouse, a blue
bicycle, a planting day, a paper kite, and an unavailable letter. Three synthetic photographs are
development-only and visibly disclosed. One unavailable source exercises absence without invented
evidence. The fixture demonstrates presentation and interaction; it is not a production data model
and does not change `GraphSource`.

## 9. Live validation

The live path was exercised repeatedly at 1012×324, 1280×720, 1366×768, and 1440×900:

1. architecture-only arrival;
2. Map open and exact pose restoration;
3. direct travel to the available glasshouse source;
4. direct travel to unavailable evidence;
5. Index → Mara → first occurrence;
6. exact source opening;
7. Locate in Atlas back to the cited world position.

The composed Companion encounter was additionally exercised with bounded pointer extremes,
fixed centre/right/bottom placement, evidence activation, number-key `Other…`, in-place composer
focus, circular command activation, saved appearance changes, and Escape dismissal. The SVG avatar
was reviewed against the supplied crop and the identified Bloub reference implementation.
The Aeroheart editor was exercised at 1440×900 and 1366×768 with live color/finish/tempo preview,
explicit apply, undo, leave-without-saving restoration, generated control labels, and the visible
protected-value contract. High contrast and reduced transparency remove texture and make reading
surfaces opaque. Reduced motion now freezes the shader time used by the ambient continuity field
and source veils; personalized tempo cannot overrule it. Survey Relief remains a renderer-only
regression fixture and is not presented as a coherent second product family.

Current frames:

- [opening, 1280×720](artifacts/atlas-world/aeroheart-source-weather-opening-1280x720.jpg)
- [opening, 1440×900](artifacts/atlas-world/aeroheart-source-weather-opening-1440x900.jpg)
- [available source encounter](artifacts/atlas-world/aeroheart-source-weather-encounter-1366x768.jpg)
- [Map correspondence](artifacts/atlas-world/aeroheart-source-weather-map-1366x768.jpg)
- [unavailable evidence](artifacts/atlas-world/aeroheart-source-weather-unavailable-1366x768.jpg)
- [Aeroheart interface skin, 1440×900](artifacts/atlas-world/atlas-ui-skin-aeroheart-1440x900.jpg)
- [internal Survey Relief regression frame, same geometry](artifacts/atlas-world/atlas-ui-skin-survey-relief-1440x900.jpg)

Rejected comparisons retained for audit:

- [olive low-poly opening](artifacts/atlas-world/origin-landscape-opening-1366x768.png)
- [Blue Hour treatment](artifacts/atlas-world/celestial-emulsion-blue-hour.png)
- [held-light billboard experiment](artifacts/atlas-world/aeroheart-held-light-opening-1366x768.png)
- [rounded-card/thread-weave experiment](artifacts/atlas-world/aeroheart-memory-tide-opening-1280x720.png)

## 10. Candid assessment and remaining slice

The result no longer reads as an olive game level or a dashboard covering a renderer. The floor
platform, abrupt horizon, decorative prop families, barcode source, and rounded onboarding content
are gone. The source aperture, unavailable contour, continuity field, atmospheric convergence,
confirmed seams, and Map targets now carry specific meanings.

It is more distinctive and dreamlike than the rejected treatments because exact personal media
changes the air and field instead of appearing on scenery. It is not a finished “wow” production
world. The field is analytic rather than ray-traced, source reflection is approximate, the fixture
has only one primary image per memory, Map remains deliberately sparse, and the unavailable contour
needs testing against varied backgrounds and real absence cases. Removing the rejected onboarding
panel no longer removes all first-use instruction: the existing prompt and command cluster now
carry a short action-based orientation, and Controls preserves the meaning after those cues recede.
That implementation closes the documented structural gap; whether the language is sufficient for
new users still requires observation rather than assumption.

A production-shaped vertical slice should use real thumbnail lifecycles and mixed aspect
ratios, test multiple authorized sources per memory, explain focused relationships without a modal
card, validate the new first-use language with people unfamiliar with Atlas, validate large-library
Map density, and add a first-party world selection verb. It should not add plants, monuments,
paths, or new atmosphere until those data and interaction questions are resolved.
