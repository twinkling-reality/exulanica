# @exulanica/landing

The public Exulanica title, Purpose, Capabilities, Research, and Waitlist surfaces. This package
is deliberately not an Atlas shell. It contains no application state, Companion runtime, formation
replay, graph client, or renderer.

The waitlist is the only thing on the page that makes a network request, and only on submit. Every
other surface is static.

```bash
pnpm --dir web landing
pnpm --dir web landing:build
```

`DEPLOYING.md` records where the public site is hosted, the value each build-time variable is set to
there, and the check to run before deploying. Neither variable below reaches the bundle from a file
in `src/`, so this README describes what they mean and that file records what they are.

## Canonical Atlas handoff

The title's **Enter Exulanica** link opens the single application composition root in
`@exulanica/app`.
The destination is deployment-owned:

```bash
VITE_ATLAS_URL=https://atlas.example.com pnpm --dir web landing:build
```

`VITE_ATLAS_URL` may also be a same-origin path such as `/atlas`. A production build without this
value does not guess a domain and does not show the station at all: the waitlist leads the column
instead. See **One way in** below.

There is no development default. An earlier build defaulted to `http://127.0.0.1:5173/?preview=1`,
which put an Enter Exulanica station on every local title screen whether or not anything served
that port, and led nowhere when nothing did. Ask for the handoff by name instead:

```bash
VITE_ATLAS_URL='http://127.0.0.1:5175/?preview=1' pnpm --dir web landing
```

The preview query is only honored by the app's Vite development server. A production app build
does not accept it.

## Waitlist endpoint

The page holds no list. A deployment supplies the endpoint, exactly as it supplies the Atlas
destination:

```bash
VITE_WAITLIST_URL=https://forms.example/f/abc pnpm --dir web landing:build
```

The submitted body is `email=<address>`, sent as `application/x-www-form-urlencoded`, which is what
a hosted form endpoint accepts by default and which the fetch specification counts as a simple
request, so no CORS preflight is issued. A provider wanting JSON needs `encode` in
`src/ui/waitlist.ts` changed and nothing else. The endpoint must answer with a 2xx status and an
`Access-Control-Allow-Origin` header that admits the deployed site, or the surface reports that the
address did not send and hands the field back with the address still in it.

**A build without `VITE_WAITLIST_URL` shows the line and a shut field, and says nothing about
why.** It does not explain that the waitlist is unconnected: that is a fact about the build, not
about the visitor, and reading an apology for it is worse than reading nothing. The cost of that
choice is that a forgotten variable is silent, so check the surface once after deploying.

Two rules differ from the Atlas handoff on purpose. There is no development default, because an
Atlas default points a visitor at their own machine while a waitlist default would post somebody's
address to whatever happened to be listening. And the endpoint must be `https`, since the request
carries an email address; development may use `http` on a loopback host so the form can be
exercised against a local stub. A build without a valid endpoint keeps the station and the surface,
disables the field, and says the waitlist is not connected. It does not present a control that
silently drops an address.

## Boundaries

The landing package's only workspace dependency is `@exulanica/presentation`, and it takes that
package's `/companion` entry rather than its barrel. `web/.dependency-cruiser.cjs` enforces the
dependency, the choice of entry, and separately prevents renderer imports;
`test/bundle-boundary.test.ts` asserts the same property against the build's own sourcemap. What
this keeps inside the canonical application is world-owned visual identity, Atlas navigation, the
geometric Companion, evidence, Map, and Index.

**The sentence that stood here also said the arrangement "keeps the public first paint lightweight",
and that was measured and found false.** A package boundary is not a bundle boundary. The barrel
re-exports `world-profiles.js`, which constructs the world style registry at module scope, and a
module-scope constructor call cannot be dropped as unused, so one named Companion import shipped
that registry and the modules behind it and ran them on every cold load, to draw one small avatar in
the corner of a signed-out screen. When it was measured, 25,600 of 55,898 attributed bundle bytes
were world style, `world-style-model.ts` was larger than any module this package had written, and
taking the narrow entry halved the JavaScript from 62,637 bytes to 31,276. `pnpm run boundaries` was
green throughout: the edge it forbids is a cross-package import and this was not one. The figures
are history rather than a property, which is why the test and the rule are what hold it now.

## Surfaces

- **Title** places the Exulanica wordmark over a field of near-touching gradient forms, with a lower-left
  navigation menu and one explicit entry into Exulanica. It uses no scenic or photographic
  backdrop.
- **Purpose** presents one uninterrupted paragraph about connecting scattered records of a life,
  personal media, and the context a person contributes, and then places that against the
  generative world models of 2026 which imagine a place for a session and forget it. It describes
  the ambition; Capabilities explains the concrete actions that give it substance.
- **Capabilities** presents two named sections: exploring connected memories and powering personal
  agents with context through the World Memory Package. Both use the existing reading measure and
  restrained typography, with space between outcomes and no dividers. Purpose remains a single
  uninterrupted paragraph. Screen readers retain a named heading for each page.
- **Spatial navigation** measures the wordmark and targets the space above its right end for Purpose
  and above its left end for Capabilities. Return reverses that travel; switching reading pages uses
  a shorter lateral movement.
  Direct links open immediately, reduced motion uses an opacity fade, and interrupted transitions
  settle on the latest destination.
- **Research** states the project's position as recorded refusals and recorded measurements rather
  than as ambition: generated geometry refused from the reconstruction ladder, a scene admitted at
  the rung its evidence supports, and one measurement where views agreed with each other while
  sitting well away from the truth. It names an open question rather than resolving it. Reached
  from Resources, so it is not a fourth primary destination.
- **Waitlist** is the one surface that asks the visitor for something. It uses the reading measure
  and a single field, and reports its own connection state rather than presenting a dead control.
- **Resources** is one Companion station that discloses ordinary Documentation, Research, and
  GitHub links.
- **Viewport boundary** states the product's current desktop input requirement rather than showing
  a fake small-screen product.

All surfaces share the same lower-left Companion navigation. The disclosure opens only by
activating its native button and contextually replaces the destinations above Resources with Back,
Documentation, and GitHub. It closes on Back, Escape, or an outside pointer press, restores button
focus after Back or Escape, and keeps the Companion at Resources while focus is inside. The
signed-out surfaces also share a neutral light canvas, visible keyboard focus, and reduced-motion
rules. The landing palette is scoped locally so Atlas world profiles remain independent.

Purpose, Capabilities, Research, Waitlist, and Return are native hash links, so direct URLs and
browser history retain their ordinary meaning.

### One way in

The column leads with exactly one way in, and never both. With `VITE_ATLAS_URL` set, Enter
Exulanica leads and no waitlist station is built. Without it, the waitlist leads and no Enter
station is built. Two ways in when only one of them exists is the thing this replaced.

An earlier build kept Enter Exulanica in place, greyed out, with a line underneath saying the world
was not connected. The sentence was true, but it was attached to the most prominent promise on the
page, and a visitor can act on it in neither version. Offering the thing they can act on is the
honest form of the same fact. Nothing in the column is ever a dead control, so `.entry-status` and
the disabled-entry branch are both gone.

Capabilities describes the intended product experience in present tense, without a development-status
footer. Reconstruction remains conditional on the source images. Current implementation evidence
remains in the repository README and frontier roadmap.

The world-model position lives in Purpose and not in Capabilities, and that placement is a rule
rather than an editorial preference. `frontier-roadmap.md` records that the four capabilities which
would make Exulanica the layer a generative model reads from "are tracked as work, not claimed",
and the World Read API is in progress. Purpose is the surface written in the "is being built"
tense, so it is the only one that can carry a position without asserting a capability. What
Capabilities says about world models is limited to what is true of the package itself: it
describes a real place rather than a plausible one.

## Reusable gradient forms

`src/ui/gradient-forms/` separates circle layout (`geometry.ts`), SVG material rendering and updates
(`index.ts`), color motion (`style.css`), and art direction (`presets.ts`). The home page supplies a
preset and positions the SVG through `.title-artwork`; no page coordinates live in the renderer.

- Each shape has an id, radius, and light direction. Additional shapes attach to an earlier shape
  by angle and edge gap. Layout rejects overlaps, including collisions with non-parent shapes.
- Palette and alternate palette each accept three CSS colors. Strength, directional fade start, radial rim start, texture amount,
  texture frequency, deterministic seed, cycle duration, and still/color motion are configurable.
- SVG viewBox bounds follow the layout. A wrapper controls size, crop, and page placement. Single,
  paired, or larger arrangements use the same API and remain independent when mounted together.
- The home preset is still and uses independent elliptical color fields per form. Each field owns
  its palette slot, center, two-axis spread, rotation, opacity, and ordered falloff stops. Blue,
  yellow, and green therefore do not share a uniform rim mask. Their combined alpha masks the grain.
  Unspecified materials retain the simpler directional/radial fallback for other presets. Optional color motion remains available to other presets. Rims never drift.
  Deterministic vector grain shares the fade masks; no turbulence filter is evaluated during zoom.
  There is no frame loop, image download, or application renderer dependency.
- Title travel takes 600ms. Incoming text starts immediately, with shorter travel, and settles in
  520ms. Reading-page switches skip title measurements. Temporary compositing hints are removed
  after completion or interruption.
- `createGradientForms(options)` returns `{ element, update }`. `update(nextOptions)` validates and
  atomically replaces the material/layout while retaining the same outer SVG. Remove the element
  normally; no listeners, timers, or other external resources need disposal.
- Reduced motion disables the color cycle; forced colors hides decorative art. The SVG is hidden
  from accessibility navigation and cannot capture pointer events.

The landing composition uses one persistent `.landing-landscape` sibling behind all three panes.
`main.ts` moves the title's artwork into that layer once. Both information views use the exact measured camera transform used by the wordmark. The same SVG
moves for 600ms during navigation and stays at that camera position; page-specific crop offsets and
orientation changes are not used. The title pane is transparent, and the
stationary overlay clips the moving art. Reading scroll, navigation, and decorative motion are separate.
Direct hash loads compose immediately, and reduced motion changes position without spatial animation.
There is no ambient color exchange or pulse.

For a separate surface outside this shared landing composition, derive a preset and place the
component's `element` in that surface's decorative wrapper.

## Named visual presets

The UI theme lives in `src/themes.css` (`landing-light`). Artwork colors live in
`ARTWORK_PALETTES.daylight`; shape layout and per-color material geometry live in
`ARTWORK_COMPOSITIONS.diagonal`. `landingArtwork(palette, composition)` combines them without
changing the UI theme. The same selection stays mounted across Title, Purpose, and Capabilities.
The diagonal composition has exactly two dominant forms separated by an eight-unit edge gap.
Their junction is placed above the wordmark in the home view. There is no hidden satellite.
Resize recomputes the camera from the untransformed wordmark, and direct links use the same geometry. Palette changes preserve each
color field's independent position and falloff; there is no automatic page-dependent color change.
