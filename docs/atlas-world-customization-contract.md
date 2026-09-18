# Atlas world customization contract

Status: **DECISION** and **IMPLEMENTED** for global appearance customization. PostgreSQL appearance
transactions, the HTTP lifecycle, exact frontend recipe handshake, generated controls, transient
preview, apply/discard/refine/rollback review, provenance/history, and authenticated source-media
loading exist. The upstream conversational authoring service, regional renderer preview, complete
multi-style library, and structural topology editor do not.

## 1. Protected topology

A proposal may not silently change any of these values:

- world/region/relationship ownership;
- module and recipe identity/version;
- transforms, attachments, sockets, or stable instance IDs;
- collision or navigation contracts;
- required destinations and reachability;
- evidence requirement, evidence binding, reconstruction rung, or provenance;
- streaming identity and minimum accessible labeling contract.

The topology digest is the optimistic concurrency token for those values. The backend persists and
compares the composer-supplied digest but does not claim a non-cryptographic frontend draft is
cryptographic; canonical digest production remains the topology composer's responsibility.

## 2. Appearance proposal

An appearance proposal contains:

```text
proposalId
origin: user | settings | companion
kind: appearance
scope: global | region(islandId)
baseStyleVersionId
baseTopologyDigest
profile: profileId + profileVersion + validated parameter values
referenceIds
modelId + promptVersion (Companion only)
refinesProposalId (optional)
```

Preview creates an isolated candidate style version. It does not change current state. Apply is
valid only if the preview succeeded and its base style version is still current. Discard deletes
the preview only. Rollback appends a new immutable version whose values match a prior version;
history is never rewritten.

## 3. Structural proposal

Moving a region, changing neighborhood membership, or replacing a module with an incompatible
contract is structural. The current controller rejects it with
`structural-preview-unavailable` and marks the issue as protecting a value.

A future structural controller must:

1. compose a candidate topology against an explicit base snapshot;
2. show a protected-value diff including moved identities, reachability, collision, reconstruction,
   evidence, and residency impact;
3. run attachment, bounds, clearance, slope, destination, and accessibility validation;
4. persist only through backend compare-and-swap;
5. leave the current snapshot intact on conflict or failed validation.

## 4. Profile compatibility and programmable controls

Aeroheart (stored under the legacy-stable `origin-landscape` profile ID) and the internal Survey
Relief regression fixture use `atlas-topology-v1`. They may vary silhouette realization,
materials, accents, detail density, and atmospheric response inside authored module bounds. They
may not change sockets, collision, navigation, evidence, or destination positions.

A style descriptor owns a parameter manifest. Each control has a stable key, a renderer capability,
kind, group, label, explanation, safe range/options, and default. Different styles may expose
different manifests. Options renders the active manifest rather than hard-coding Aeroheart sliders.

The frontend recipe contract inspected at `55b1236` is the execution boundary. Its version-one
recipe contains `schemaVersion`, product/developer availability, authored/generated origin, a
versioned visual profile, bounded controls, and reviewed local module IDs. The frontend owns the
visual profile, module implementations, exact capability validation, contrast correction,
protected component geometry, preview rendering, reduced-motion behavior, and accessibility. The
backend does not reproduce that visual source. It returns and persists an inert `recipeBinding`
containing only the exact schema/profile version, module IDs, and control-to-capability mapping.
That is an adapter to the existing client recipe, not a second style language.

Backend proposals can select a registered recipe version and parameter values. They cannot carry
CSS, markup, JavaScript, shaders, renderer programs, remote texture URLs, private media, interface
layout, or new module implementations. A Companion proposal also carries durable reference IDs,
model ID, prompt version, actor/origin, and optional refinement lineage; conversation text and
preview-session state are excluded. Apply records those values on the immutable version. Rejection,
discard, stale closure, refinement, and rollback remain inspectable without turning transient
conversation into a durable preference.

The frontend now stores each style definition as a JSON-serializable version-one recipe with:

```text
schemaVersion
availability: product | developer
origin: authored | generated
profile: profileId + profileVersion + topology-compatible visual source
controls: bounded capability manifest
modules: reviewed local module IDs
```

The recipe contains no functions, selectors, shaders, markup, or remote assets. At startup the
world-style registry validates profile data, the control manifest, module existence, and an exact
one-to-one capability binding. It then compiles the recipe through the selected reviewed modules.
Unknown modules, duplicate capability owners, unmatched controls, invalid defaults, and unsafe
ranges fail closed. The registry itself contains no profile-ID branches, so adding a validated
recipe does not require adding another conditional path through Options or the renderer binding.

A module is trusted application code and is the only executable part of style resolution. Shared
modules cover registered surface finish and bounded tempo; authored response modules
translate Aeroheart and the Survey regression fixture's semantic controls into their own palette,
material, detail, and atmosphere values. The backend persists inert recipe bindings and style
versions, but cannot use recipe data to introduce executable behavior. Adding a genuinely new
capability still requires a reviewed frontend module and capability-registry entry.

The profile contains one shared visual DNA palette. The renderer consumes its sky, field, source,
relationship, and unresolved roots directly. A trusted deterministic adapter derives interface
ground, surface, ink, focus, provenance, uncertainty, and Companion roles from those same roots and
corrects them to minimum contrast. A profile can no longer author a second, unrelated UI palette.

**CORRECTED.** "Corrects them to minimum contrast" was the whole specification of the adapter, and
it was not enough to keep a world recognisable. Four constraints now bind it, all in
`packages/presentation/src/world-style-model.ts` and all profile-agnostic:

1. Each role is placed at an authored perceptual lightness before any correction runs. Contrast
   correction is a floor and never the thing that chooses a colour. Without this every role landed
   on its own minimum and the interface held two values total.
2. Lightness changes happen in OKLCH. Mixing toward black in sRGB preserves the channel ratio and
   destroys the channel difference, so a world with a pale ground lost every hue it authored.
3. Structural roles read from the ground and the air together. Reading from the ground alone was
   correct only while the ground happened to be dark, and it silently failed the moment a world
   authored a light field.
4. The reading floor carries a margin above the requirement, because a role corrected against the
   lightest theoretical surface is below the requirement on the actual surface a component builds
   from it.

A small chroma floor may rescue a hue that a world did author from vanishing at low lightness. It
may never introduce a hue, and it is set low enough that a deliberately desaturated profile such as
the Survey regression fixture still resolves to a desaturated interface. That asymmetry is the
test: the same adapter must make one world colourful and leave the other drab, without knowing
either profile's identity.
Its versioned interface expression may still select reviewed type families, blur/saturation,
registered texture family and blend, and interaction/idle motion. Components own shape, hit area,
layout, reading order, accessibility, and behavior; they consume the derived roles and do not
contain palette literals or world-specific font stacks.

Control geometry is a protected system contract. The circular Atlas commands, choice silhouette,
speech-lens silhouette, panel geometry, placements, and responsive reading order remain recognizable
across worlds. A profile may paint those surfaces with a different material, border treatment, or
registered texture, but it carries no radius, dimensions, coordinates, or hit-area values.

This is not arbitrary CSS injection. Texture families are registered values, profile numbers are
bounded, and a profile cannot supply selectors, markup, remote assets, executable animation code,
or shader code. A new visual capability is a reviewed registry addition. This keeps world identity
expressive while ensuring personal or model-authored style data cannot change evidence behavior,
navigation, accessibility order, or confirmation semantics.

The trusted renderer capability registry is the limit of runtime AI programmability. A model may
select capabilities, rename controls, narrow ranges, choose defaults, and propose values. It may not
invent an executable binding, widen a protected range, or ship generated shader/code into the
runtime. A genuinely new renderer feature remains a reviewed software change. Unknown bindings,
unknown parameters, invalid values, and out-of-range values fail before preview.

Aeroheart is the sole complete user-facing identity and uses the authored daylight exposure. Survey
Relief remains an intentionally extreme internal regression fixture, not a product alternative or
evidence that unrelated styles form one family. The
minimum presentation matrix is therefore:

- Aeroheart × Standard and High contrast;
- Aeroheart × Layered and Reduced transparency;
- Survey Relief × the renderer regression suite only.

Color is never the only semantic carrier. Provenance uses hue + shape, confirmation uses hue +
stroke, and focus uses contrast + outline.

## 5. Failure and fallback rules

- unknown recipe/profile version, module, capability, or parameter in a new proposal or client
  handshake → fail closed before preview;
- unknown or removed profile in immutable historical data → display a warned default/ignored
  regional override, discarding the old parameters rather than reinterpreting them;
- stale style base → reject preview/apply;
- changed topology digest → reject as a protected conflict;
- unknown region → reject;
- missing reconstruction asset → composer resolves the module's honest source-evidence fallback;
- incompatible/invalid attachment → reject composition;
- unreachable required destination → reject composition;
- failed/discarded preview → current style and topology remain unchanged.

Settings and Companion are proposal origins, not separate rule engines. Settings exposes the
active style's generated parameter controls; a different validated style may expose a different
manifest. It does not expose the incomplete Survey fixture as a product choice. Input changes are
live, isolated previews in both the renderer and backend. The person must choose **Apply world design** to persist them, and may use
**Undo preview** or leave Options to restore the saved style. The visible editor names what is
protected and truthfully states that an upstream conversational proposal service is not connected.
The renderer binding exposes the same Companion-origin preview/apply/discard methods; the separately
owned Companion behavior is unchanged while its surrounding interface consumes the active world's
derived semantic roles.

Design references belong to proposal provenance. The intended flow is:

`conversation + reference IDs → capability-backed manifest/values → validation → live preview → apply/refine/discard → immutable version`

The model may explain which reference traits mapped to which capability. Reference images and
conversation text are not renderer instructions and never bypass manifest validation.

The production boundary is `exulanica/world/`, migrations `0017_adaptive_world_styles.sql` and
`0023_frontend_world_recipe_contract.sql`, and the `/world/styles` routes. Durable versions and
current pointers live there; live conversation and isolated preview sessions remain separate. See
[world-style-backend.md](world-style-backend.md).

The production frontend persists the resulting immutable style version through the backend
boundary. The per-device preference is only a render cache for the server-owned current version;
it is not a competing current pointer.

The per-device preference now stores both profile ID and profile version. An unknown pair falls
back to the product default and discards its parameters rather than interpreting old values against
a newer recipe. Product availability also comes from the recipe registry instead of a second
hard-coded profile allowlist.

The expected personal-world lifecycle is:

`authored default → human request or direct controls → model selects registered capabilities and values → validation → live world + UI preview → explicit apply → immutable style version → rollback by appending a new version`

“Generate a custom style” therefore means compose and parameterize existing reviewed capabilities,
not add CSS. Its stored recipe identifies a versioned base profile, complete validated parameter
values, and provenance. Opening that style later regenerates the controls declared by its own
manifest. A genuinely new renderer, texture, shader, or structural capability remains a reviewed
software/module addition before a model may use it.

## 6. Source-media contract

Source bindings are protected topology values, not style parameters. Each registered source slot
either names an evidence span from the same workspace or records why no evidence exists. Reads
distinguish `available`, `unavailable_asset`, and `missing_evidence`; cross-workspace and nonexistent
source IDs are indistinguishable. Available sources expose an authenticated local evidence path
plus a provenance-bearing asset reference naming the protected source slot and evidence span.
Unavailable states expose no asset reference. Private media remains in the evidence store and
never enters a style recipe.

The frontend loads the source list with the workspace bearer token, verifies each asset reference's
local evidence path and source/span provenance, fetches bytes with the same authorization header,
and gives the renderer a bounded-lifetime blob URL. It revokes those URLs when the application
session ends. Missing evidence, unavailable bytes, authorization failure, provenance mismatch, and
network failure remain distinct visible states and never receive replacement imagery.

## 7. Frontend integration boundary

`web/packages/app/src/world-style-api.ts` is the only camel-case/snake-case translation layer. At
startup it verifies the catalog contract commit, exact profile versions, control manifests, module
IDs, and capability mappings against the local recipe registry. Current state and history then
hydrate the renderer from backend values. Unknown or mismatched data fails closed before rendering.

Settings input creates a transient local renderer preview and an isolated backend preview. Apply
uses the preview's exact style and topology bases. If another writer wins, Atlas reads the new
current state, creates a refinement-linked preview on that base, and requires review and Apply
again; it never silently overwrites the competing version. Rollback has the same conflict rule and
appends a new immutable revision on success.

`web/packages/app/src/world-style-proposals.ts` is the typed conversational handoff. It accepts only
an already-structured upstream proposal with profile values and provenance. The browser does not
call a model or translate conversation text. Companion proposals require an origin reference,
reference IDs, model ID, and prompt version, and refinements retain `refinesProposalId`. The same
Options review applies or discards them. A production proposal service is still required to supply
those records.

Regional records remain backend-authoritative and are parsed without reinterpretation, but the
current renderer has only a reviewed global profile preview. The UI therefore refuses to display a
regional proposal as a global change. Shipping regional controls requires a reviewed per-region
renderer path first.

## 8. Companion appearance is a separate version family

Companion appearance is not world appearance and neither is memory-graph state. The versioned V3
shape lives in `packages/presentation/src/companion-appearance.ts` and includes
`companionModelVersion`, one geometric silhouette, colour, two-eye expression, catalog-derived body
and eye colours, `motionProfile`, and `reducedMotionProfile`. Unknown versions fail closed to the
current configuration; V1 and V2 prototype records migrate explicitly instead of being
reinterpreted.

Options exposes six silhouettes, five colours, and five two-eye expressions. The resolved
configuration is applied to the DOM/SVG Companion and persisted only as a device preference. There
are no accessory or humanoid-body controls. No graph assertion, evidence handle, topology digest,
navigation destination, or world style version contains or derives these values.

The world profile may style the Companion's surrounding speech, choices, command buttons, type,
material, texture, and timing through semantic roles. It does not change their protected shapes or
the user's selected Companion
silhouette, colour, or expression. That separation allows one presence identity to remain
recognizable across visually different worlds.
