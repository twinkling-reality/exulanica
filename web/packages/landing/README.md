# @exulanica/landing

The public Exulanica title, Purpose, and Capabilities surfaces. This package is deliberately not
an Atlas shell. It contains no application state, Companion runtime, formation replay, graph
client, or renderer.

```bash
pnpm --dir web landing
pnpm --dir web landing:build
```

## Canonical Atlas handoff

The title's **Enter Exulanica** link opens the single application composition root in
`@exulanica/app`.
The destination is deployment-owned:

```bash
VITE_ATLAS_URL=https://atlas.example.com pnpm --dir web landing:build
```

`VITE_ATLAS_URL` may also be a same-origin path such as `/atlas`. A production build without this
value says that the world is not connected instead of guessing a domain or exposing a dead control.

During local development the default is `http://127.0.0.1:5173/?preview=1`, the documented Vite
preview for the canonical app. Override it whenever the app is running elsewhere:

```bash
VITE_ATLAS_URL='http://127.0.0.1:5175/?preview=1' pnpm --dir web landing
```

The preview query is only honored by the app's Vite development server. A production app build
does not accept it.

## Boundaries

The landing package depends only on `@exulanica/presentation` for shared semantic visual tokens.
`web/.dependency-cruiser.cjs` enforces that boundary and separately prevents renderer imports.
This keeps the public first paint lightweight while leaving world-owned visual identity, Atlas
navigation, the geometric Companion, evidence, Map, and Index inside the canonical application.

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
- **Resources** is one Companion station that discloses ordinary Documentation and GitHub links.
- **Viewport boundary** states the product's current desktop input requirement rather than showing
  a fake small-screen product.

All three surfaces share the same lower-left Companion navigation. The disclosure opens only by
activating its native button and contextually replaces the destinations above Resources with Back,
Documentation, and GitHub. It closes on Back, Escape, or an outside pointer press, restores button
focus after Back or Escape, and keeps the Companion at Resources while focus is inside. The
signed-out surfaces also share a neutral light canvas, visible keyboard focus, and reduced-motion
rules. The landing palette is scoped locally so Atlas world profiles remain independent.

Purpose, Capabilities, and Return are native hash links, so direct URLs and browser history retain
their ordinary meaning. A build without `VITE_ATLAS_URL` keeps a disabled Enter Exulanica station
and explains that the destination is not connected; it does not invent a deployment URL.

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
