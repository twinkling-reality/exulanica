# Exulanica front end

pnpm workspace. TypeScript, strict. `pnpm check` runs the three gates:

```
pnpm run typecheck    # tsc --build across every package
pnpm run boundaries   # the forbidden-imports contract
pnpm run test         # vitest
```

## Packages

| Package | Contains | Forbidden |
| --- | --- | --- |
| `@exulanica/atlas-core` | scene graph, island frames, focus resolution, view manifest application, layout solver | React, DOM, any renderer, and any other workspace package |
| `@exulanica/presentation` | the authored Origin Landscape identity, renderer colors, shared CSS tokens and material grammar; internal compatibility fixtures are not product choices | DOM, renderers, and every workspace package except atlas-core |
| `@exulanica/atlas-react` | renderer bindings, anchor overlay, HUD, comfort settings | graph mutations |
| `@exulanica/companion-runtime` | turn generation, option pools, proposal drafting, escape handling, initiative gate | renderer, React, DOM |
| `@exulanica/world-index` | index UI, entity detail, provenance panel | renderer |
| `@exulanica/graph-client` | entity graph reads and writes, assertion log, evidence resolution | all of the above |
| `@exulanica/atlas-three` | the three.js r185 + Spark 2.1.0 renderer binding, ADR-0003 option A | React, and every workspace package except atlas-core |
| `@exulanica/scene-synth` | the synthetic scene generator for the ADR-0003 bake-off | everything except atlas-core; offline only |
| `@exulanica/bakeoff` | the ADR-0003 X-R1 harness page | everything except atlas-core and atlas-three |
| `@exulanica/landing` | the public title, Purpose, and Capabilities surfaces; a configured link opens the real application | every renderer, and every workspace package except presentation |

From `docs/architecture-overview.md` section 1.1, plus four packages that are not among the
five shipped modules: `presentation` owns visual policy without owning a surface, `scene-synth` is a build-time tool, `bakeoff` is a harness,
`atlas-three` is one of the two competing renderer bindings ADR-0003 exists to choose between,
and `landing` is the signed-out surface, which deliberately takes no renderer at all so that the
first paint does not depend on the ADR's outcome. Only `atlas-three`, `atlas-react` and `bakeoff`
may name a renderer, which is what keeps the ADR's outcome to a two-package blast radius.

## How the boundaries are actually enforced

Three mechanisms, because they cover different failure modes and none of them
covers all three:

1. **`.dependency-cruiser.cjs`**, forbidden module imports and cross-package
   edges. Every rule has been probed with a deliberate violation; they fire by
   name, and legal imports pass.
2. **`tsconfig` `lib`**, `atlas-core` and `companion-runtime` compile without
   `lib.dom`, so `document`, `window` and `HTMLElement` are type errors. A global
   is not an import and no lint rule can catch it.
3. **The proposal gate in `graph-client`**, a runtime check that rejects any
   mutation whose proposal id is not in the pending set. Deliberately runtime: a
   lint rule protects code that was linted, and this has to protect code that has
   not been written yet.

Two further guards worth knowing about:

- There is no `atlasToLocal` anywhere, and no distance function over `AtlasVec3`
  in the `atlas-core` barrel. An island's atlas position is a layout artifact,
  and reading it as geometry is risk R-48. The distance functions the layout and
  focus solvers genuinely need live in
  `@exulanica/atlas-core/presentation-metrics`, which the query layer may not
  import.
- The view manifest type has no field that can express a position or a camera
  pose, so a query structurally cannot move the world or the user.

## Fixtures

`pnpm landing` serves the public title, Purpose, and Capabilities surfaces; see
`packages/landing/README.md`. It links to the local app preview on port 5173 by default. If the app
is running elsewhere, start it with an explicit destination, for example
`VITE_ATLAS_URL='http://127.0.0.1:5175/?preview=1' pnpm landing`.

For Atlas UI work while the API is unavailable, run `pnpm app` and open
`http://127.0.0.1:5173/?preview=1`. This is an explicit development preview, not the hosted demo:
everything shown is synthetic, graph changes are refused, source evidence is disabled, and the
normal URL still requires the live API. The preview endpoint exists only in Vite's development
server and cannot be activated in a production build.

`pnpm synth --out ./fixtures` writes the bake-off ladder (250k, 1M, 2M, 3M, 4M)
in about ten seconds. `pnpm bakeoff` then serves the harness; see
`packages/bakeoff/README.md` for the URL parameters and the measured results. See `packages/scene-synth/README.md`. Fixtures are
gitignored; regenerate rather than commit them.
