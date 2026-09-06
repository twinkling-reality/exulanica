/**
 * The forbidden-imports contract from docs/architecture-overview.md section 1.1, as an
 * enforced rule set rather than a table in a document.
 *
 * A boundary nobody checks is not a boundary. `pnpm run boundaries` fails the build.
 *
 * Three layers of enforcement exist in this workspace and they cover different things:
 *
 *   1. This file          - forbidden MODULE imports (React, renderers, cross-package edges).
 *   2. tsconfig `lib`     - forbidden AMBIENT globals. atlas-core and companion-runtime compile
 *                           without lib.dom, so `document`, `window` and `HTMLElement` are type
 *                           errors, not review comments. A lint rule cannot catch a global.
 *   3. graph-client       - the runtime proposal-id check on every mutation. Documented as a
 *                           runtime check on purpose: it must hold for code that was never linted.
 */

/** Renderer packages, and the two candidates in ADR-0003 specifically. */
const RENDERER = String.raw`^(?:node_modules/)?(?:three|@react-three/[^/]+|@sparkjsdev/spark|playcanvas|@playcanvas/[^/]+)(?:$|/)`;
/** React itself. Not "anything that renders": React specifically, per the section 1.1 table. */
const REACT = String.raw`^(?:node_modules/)?(?:react|react-dom|react/[^/]+|react-dom/[^/]+)(?:$|/)`;
/** The mutation gate, as both a source path and the subpath specifier callers actually write. */
const MUTATIONS = String.raw`^packages/graph-client/src/mutations/|^(?:node_modules/)?@exulanica/graph-client/mutations$`;

const pkg = (name) => String.raw`^packages/${name}/`;

/**
 * Match a workspace package BOTH as a resolved source path and as a bare specifier.
 *
 * This matters more than it looks. If someone writes a forbidden cross-package import without
 * adding the dependency to package.json, pnpm never symlinks it and dependency-cruiser reports
 * the module as unresolvable rather than as the package it names. The violation is still caught,
 * but by the wrong rule and with the wrong message, and it stops being caught by the right rule
 * the moment somebody "fixes" it by adding the dependency. Matching both forms means the rule
 * that should fire is the rule that fires, installed or not.
 */
const pkgRef = (...names) => {
  const alt = names.join('|');
  return String.raw`^packages/(?:${alt})/|^(?:node_modules/)?@exulanica/(?:${alt})(?:$|/)`;
};
const notPkgRef = (...names) => {
  const alt = names.join('|');
  return String.raw`^packages/(?!(?:${alt})/)|^(?:node_modules/)?@exulanica/(?!(?:${alt})(?:$|/))`;
};

module.exports = {
  forbidden: [
    // ---- atlas-core: "React, DOM, any renderer" -------------------------------------------
    {
      name: 'atlas-core-no-react',
      severity: 'error',
      comment:
        'atlas-core is pure TypeScript. It is the module a renderer switch must NOT touch beyond ' +
        'its own internals, so it may not depend on a view layer.',
      from: { path: pkg('atlas-core') },
      to: { path: REACT },
    },
    {
      name: 'atlas-core-no-renderer',
      severity: 'error',
      comment:
        'ADR-0003 is unresolved. atlas-core must compile identically under either outcome, which ' +
        'is only true if it never names an engine.',
      from: { path: pkg('atlas-core') },
      to: { path: RENDERER },
    },
    {
      name: 'atlas-core-is-self-contained',
      severity: 'error',
      comment:
        'atlas-core imports no other workspace package, including graph-client. Graph data is ' +
        'adapted into atlas-core types by the caller. This keeps the scene graph testable with ' +
        'no transport and makes the two-package rewrite in ADR-0003 genuinely two packages.',
      from: { path: pkg('atlas-core') },
      to: { path: notPkgRef('atlas-core') },
    },

    // ---- presentation: one world identity, shared by every visual consumer -----------------
    {
      name: 'presentation-imports-atlas-core-only',
      severity: 'error',
      comment:
        'Presentation owns atmosphere, material and exposure policy. It may read the canonical ' +
        'provenance vocabulary from atlas-core and must remain independent of DOM and renderers.',
      from: { path: pkg('presentation') },
      to: { path: notPkgRef('presentation', 'atlas-core') },
    },

    // ---- companion-runtime: "renderer, React, DOM" ----------------------------------------
    {
      name: 'companion-runtime-no-view-layer',
      severity: 'error',
      comment:
        'The Companion turn generator must be runnable headless in a test, and a renderer switch ' +
        'must not reach it (architecture-overview.md 1.1).',
      from: { path: pkg('companion-runtime') },
      to: { path: `${REACT}|${RENDERER}` },
    },
    {
      name: 'companion-runtime-no-ui-packages',
      severity: 'error',
      from: { path: pkg('companion-runtime') },
      to: { path: pkgRef('atlas-react', 'world-index', 'scene-synth') },
    },

    // ---- world-index: "renderer" ----------------------------------------------------------
    {
      name: 'world-index-no-renderer',
      severity: 'error',
      comment:
        'The World Index is the accessibility route and the default entry on touch devices. It ' +
        'must work with no canvas at all (interaction-model.md 2.5, 2.6).',
      from: { path: pkg('world-index') },
      to: { path: `${RENDERER}|${pkgRef('atlas-react', 'scene-synth')}` },
    },

    // ---- graph-client: "all of the above" -------------------------------------------------
    {
      name: 'graph-client-is-the-base',
      severity: 'error',
      comment:
        'graph-client sits under everything. It may not import atlas-core, atlas-react, ' +
        'companion-runtime or world-index (architecture-overview.md 1.1).',
      from: { path: pkg('graph-client') },
      to: { path: notPkgRef('graph-client') },
    },

    // ---- atlas-react: "graph mutations" ---------------------------------------------------
    {
      name: 'atlas-react-no-graph-mutations',
      severity: 'error',
      comment:
        'atlas-react may READ the graph and may render its state. It may not write it. The ' +
        'mutation gate is a separate entry point (@exulanica/graph-client/mutations) so that ' +
        '"forbidden: graph mutations" is a path this rule can name.',
      from: { path: pkg('atlas-react') },
      to: { path: MUTATIONS },
    },
    {
      name: 'only-proposal-holders-may-mutate',
      severity: 'error',
      comment:
        'Mutations are reachable from companion-runtime (which drafts proposals), world-index ' +
        '(which confirms them), and ONE named file in the app: packages/app/src/session.ts, ' +
        'which is the composition root and has to construct the gate before it can hand a commit ' +
        'function to anything. The exception is a FILE and not a package on purpose. A ' +
        'package-level exception would let any future module in the app reach the gate directly ' +
        'and go around the confirmation surface, which is exactly what the runtime check exists ' +
        'to stop; naming the file means a second importer fails this contract.',
      from: {
        path: String.raw`^packages/`,
        pathNot: String.raw`^packages/(graph-client|companion-runtime|world-index)/|^packages/app/src/session\.ts$`,
      },
      to: { path: MUTATIONS },
    },

    // ---- the atlas-position guard (interaction-model.md 1.2, risk R-48) --------------------
    {
      name: 'no-atlas-distance-outside-presentation',
      severity: 'error',
      comment:
        'interaction-model.md 1.2: no distance function over AtlasVec3 may be reachable from the ' +
        'query layer, because a region\'s atlas position carries no real-world meaning. The ' +
        'distance functions the layout and focus solvers need live behind ' +
        '@exulanica/atlas-core/presentation-metrics, which only atlas-core internals and the ' +
        'renderer binding may import.',
      from: {
        path: String.raw`^packages/`,
        pathNot: String.raw`^packages/(atlas-core|atlas-react)/`,
      },
      to: { path: String.raw`^packages/atlas-core/src/presentation-metrics\.ts$` },
    },

    // ---- atlas-three: the ADR-0003 option A binding ----------------------------------------
    {
      name: 'atlas-three-no-react',
      severity: 'error',
      comment:
        'atlas-three is the engine half of the binding and is deliberately framework-free: the ' +
        'anchor overlay writes into pre-allocated DOM nodes inside the render loop, which is ' +
        'exactly what a React tree must not do (interaction-model.md 3.4). React integration ' +
        'belongs in atlas-react, on top of this.',
      from: { path: pkg('atlas-three') },
      to: { path: REACT },
    },
    {
      name: 'atlas-three-imports-atlas-core-only',
      severity: 'error',
      comment:
        'The bake-off has to be able to end by deleting a package. atlas-three may name three.js ' +
        'and Spark and it may call atlas-core, and it may reach nothing else in the workspace.',
      from: { path: pkg('atlas-three') },
      to: { path: notPkgRef('atlas-three', 'atlas-core') },
    },
    {
      name: 'engine-specific-code-stays-behind-the-binding',
      severity: 'error',
      comment:
        'Only the binding layer and the two harnesses may name an engine. If ADR-0003 flips ' +
        'to PlayCanvas, this rule is what guarantees the blast radius stays small. ' +
        'companion-forms is on the list because the roadmap requires a world-rendered Companion ' +
        'prototype before a depth contract can be approved, and a prototype that could not name ' +
        'a renderer would be prototyping something else.',
      from: {
        path: String.raw`^packages/`,
        pathNot: String.raw`^packages/(atlas-three|atlas-react|bakeoff|companion-forms)/`,
      },
      to: { path: `${RENDERER}|${pkgRef('atlas-three')}` },
    },

    // ---- bakeoff: the ADR-0003 X-R1 harness -------------------------------------------------
    {
      name: 'bakeoff-imports-the-binding-and-the-core-only',
      severity: 'error',
      comment:
        'The harness measures the binding. It may not reach into graph-client, world-index or ' +
        'companion-runtime, because a number that included them would not be a renderer number. ' +
        'It also may not import scene-synth: the fixture crosses as bytes over HTTP.',
      from: { path: pkg('bakeoff') },
      to: { path: notPkgRef('bakeoff', 'atlas-core', 'atlas-three') },
    },

    // ---- companion-forms: the Companion depth prototypes -------------------------------------
    {
      name: 'companion-forms-imports-presentation-only',
      severity: 'error',
      comment:
        'The bench compares presentations of one identity, so it reads the versioned appearance ' +
        'contract and nothing else. It may not reach the app, the binding, graph-client or ' +
        'companion-runtime: a prototype that could see a graph would be prototyping a product.',
      from: { path: pkg('companion-forms') },
      to: { path: notPkgRef('companion-forms', 'presentation') },
    },

    // ---- formation: the contract two surfaces share ------------------------------------------
    {
      name: 'formation-imports-atlas-core-only',
      severity: 'error',
      comment:
        'The formation contract sits under both surfaces that use it: the signed-out page shows ' +
        'a scripted demonstration and the app watches a real pipeline, and neither package may ' +
        'import the other. So this one may reach atlas-core, for the rung ladder its labels are ' +
        'written from, and nothing else in the workspace. It must never learn about graph-client: ' +
        'its transport takes a fetch by injection precisely so that watching an ingest costs no ' +
        'dependency on the graph.',
      from: { path: pkg('formation') },
      to: { path: notPkgRef('formation', 'atlas-core') },
    },

    // ---- landing: the signed-out surface -----------------------------------------------------
    {
      name: 'landing-imports-presentation-only',
      severity: 'error',
      comment:
        'The landing page is the signed-out title and Method surface. It links to the canonical ' +
        'app instead of composing another Atlas, so its only workspace dependency is the shared ' +
        'semantic presentation contract. The renderer ban is already covered by ' +
        'engine-specific-code-stays-behind-the-binding, which does not list landing among the ' +
        'packages allowed to name an engine.',
      from: { path: pkg('landing') },
      to: { path: notPkgRef('landing', 'presentation') },
    },

    // ---- app: the composition root ---------------------------------------------------------
    {
      name: 'app-imports-the-product-packages-only',
      severity: 'error',
      comment:
        'The app is the composition root: it is the one place that knows a transport, a scene ' +
        'graph, a renderer binding, an index and a Companion all exist at once. It may reach ' +
        'the six product packages and nothing else in the workspace. Not atlas-three, which is ' +
        'the retained second renderer binding and would be a second engine in the product; not ' +
        'bakeoff, which is a measurement harness; not scene-synth, which writes files with ' +
        'node:fs; and not landing, which is the signed-out surface and must keep paying for no ' +
        'renderer.',
      from: { path: pkg('app') },
      to: {
        path: notPkgRef(
          'app',
          'graph-client',
          'atlas-core',
          'atlas-react',
          'companion-runtime',
          'formation',
          'presentation',
          'world-index',
        ),
      },
    },

    // ---- the synthetic scene generator is a build-time tool --------------------------------
    {
      name: 'scene-synth-is-offline-only',
      severity: 'error',
      comment:
        'scene-synth writes fixture files with node:fs. Nothing that ships to a browser may ' +
        'import it. It depends on atlas-core for types only.',
      from: { path: String.raw`^packages/(?!scene-synth/)` },
      to: { path: pkgRef('scene-synth') },
    },
    {
      name: 'scene-synth-imports-atlas-core-only',
      severity: 'error',
      from: { path: pkg('scene-synth') },
      to: { path: notPkgRef('scene-synth', 'atlas-core') },
    },

    // ---- general hygiene -------------------------------------------------------------------
    { name: 'no-circular', severity: 'error', from: {}, to: { circular: true } },
    {
      name: 'not-to-unresolvable',
      severity: 'error',
      from: {},
      to: { couldNotResolve: true },
    },
  ],

  options: {
    doNotFollow: { path: 'node_modules' },
    exclude: { path: '(^|/)(node_modules|dist)/' },
    tsPreCompilationDeps: true,
    tsConfig: { fileName: 'tsconfig.base.json' },
    enhancedResolveOptions: {
      exportsFields: ['exports'],
      conditionNames: ['types', 'import', 'require', 'node', 'default'],
      extensions: ['.ts', '.tsx', '.js', '.mjs', '.cjs', '.json'],
      mainFields: ['module', 'main', 'types'],
    },
    reporterOptions: { text: { highlightFocused: true } },
  },
};
