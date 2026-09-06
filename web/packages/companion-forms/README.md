# @exulanica/companion-forms

The Companion form bake-off. A private development surface that renders one identity three ways so
a depth decision can be made from evidence instead of taste.

`frontier-roadmap.md` gates genuine 3D Companion depth behind four questions, and asks for three
prototypes before the contract is approved:

> treat genuine 3D Companion depth as a new renderer, asset-provenance, performance, and
> accessibility decision rather than relabeling SVG shading as 3D; prototype 2D, bounded relief,
> and world-rendered forms before approving that contract

This package is those three prototypes and those four questions, as columns.

## Running it

```bash
pnpm --dir web forms
```

Then open the printed URL **in a visible, foreground browser window**. This is not a preference.
A hidden or background window throttles `requestAnimationFrame`, so frame times taken there are
not slow results, they are invalid ones, and `measure.ts` refuses rather than reporting a fiction.
The same constraint governs the ADR-0003 renderer harness next door.

`Measure each form for 6s` mounts each candidate alone, lets it settle, and samples it, so the
number belongs to the form rather than to its neighbours. `Write result` posts the summary to a
dev-server middleware that writes `web/companion-form-results/latest.json`. That middleware cannot
exist in a build.

## The candidates

| | Renderer | Assets | Silhouettes |
|---|---|---|---|
| **Flat** | none, inline SVG | none | all nine, exactly |
| **Bounded relief** | none, inline SVG | none, tones mixed from the one body colour | all nine, exactly |
| **World-rendered** | a second renderer surface | none as built, procedural | three exact, two approximate, four impossible |

All three read the same versioned appearance contract, so a difference on screen is a difference of
form and never of content. All three render `working` as the one state with a distinct semantic
render, because `interaction-model.md` says that is the only one.

## What it is not

It decides nothing, and it is not a product surface. Nothing in the app or the landing links here,
it imports only `@exulanica/presentation` (enforced by `pnpm run boundaries`), and it cannot reach
a graph, a session, or the binding. A prototype that could see a graph would be prototyping a
product.

Two things it deliberately does not do. It does not load a character asset, because the binding
registers only `TextureHandler` and `GSplatHandler` and a candidate assuming a container pipeline
would be measuring one that does not exist. And it does not claim the relief candidate is 3D. It
is shading, clipped to the silhouette so it cannot leave the outline, and the point of measuring it
is to find out whether being lit is worth anything on its own.

## The finding that does not need a measurement

The catalog is nine authored 2D paths. A solid has a silhouette only from a given angle, and four
of the nine (`cloud`, `droplet`, `arch`, `lozenge`) have no primitive at all. A depth axis
therefore either forks the catalog or commits to a mesh per silhouette, and that cost lands before
any frame time does. `SOLIDS` in `src/world.ts` records which is which, and a test holds it, so it
cannot be softened later by quietly swapping an unrepresentable shape for a sphere.
