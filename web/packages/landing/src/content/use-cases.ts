/** Reader journeys, grounded in docs/product-direction.md and the named living
 * contracts. This catalog owns Use Cases copy and links, not implementation status elsewhere.
 * Claim evidence and the semantic audit live in ignored .exulanica/briefs.
 */
export const USE_CASES = [
  {
    key: 'model-comparison', legacyKey: 'agent-experiments', title: 'Agent Experiments',
    summary: 'Run the same hour with two open models and read what each one did.',
    introduction: 'Same saved world, same hour, two open models. Replay reads the saved record and does not call a model.',
    steps: [
      { title: 'Starting world', copy: 'Pick a saved world, the people in it, and two models you can run.' },
      { title: 'Recorded outcomes', copy: 'Read each run next to a second run of the same model. The runs can match.' },
      { title: 'Decision inspection', copy: 'Open what someone was offered and what the world applied.' },
    ],
    availability: 'Needs a saved world with people, models you can run, and a spending limit. This does not rank models.',
    image: null, alt: null, caption: null,
    href: '/docs/comparisons', action: 'Comparisons and Replay',
    guides: [{ href: '/docs/models', title: 'Models and Decisions' }],
    sources: ['product-direction.md#first-milestone', 'society-experiments.md#comparisons-of-models', 'decision-roles-contract.md'],
  },
  {
    key: 'worldbuilding', legacyKey: 'worldbuilding', title: 'Worldbuilding',
    summary: 'Make a place, put things from the catalog in it, and save it.',
    introduction: 'Start from a ready town, reviewed photographs, or an empty starter. Change what that world allows, and open the saved place again.',
    steps: [
      { title: 'Starting point', copy: 'Use an empty starter, a ready town, or reviewed photographs.' },
      { title: 'Objects and appearance', copy: 'Place things from the catalog, using the controls that world has.' },
      { title: 'Saved changes', copy: 'Accepted edits stay. Open the world again from Your worlds.' },
    ],
    availability: 'What you can make depends on this install and the kind of world. A photo is not a measured model of that place.',
    image: '/worlds/narrow-streets.jpg', alt: 'A generated Exulanica town with narrow streets and rowhouses.',
    caption: 'Narrow Streets, a generated town of rowhouses on narrow cross streets.',
    href: '/docs/worlds#docs-worlds-create', action: 'Worldbuilding Guide',
    guides: [{ href: '/docs/assets', title: 'Assets and Imports' },{ href: '/docs/rules', title: 'World Rules' }],
    sources: ['product-direction.md#saved-world-foundation', 'world-objects-contract.md', 'atlas-world-customization-contract.md', 'world-kinds-contract.md'],
  },
  {
    key: 'agent-development', legacyKey: 'agent-development', title: 'Agent Development',
    summary: 'Let your own program answer turns in a world you allow.',
    introduction: 'A Python or MCP client reads a turn, chooses one offered action, and you can see whether the world applied it.',
    steps: [
      { title: 'World access', copy: 'Connect with the server address and a key the owner issued.' },
      { title: 'Offered actions', copy: 'Read the turn and choose one offered action before the deadline.' },
      { title: 'Recorded results', copy: 'See whether the engine applied the answer. The owner can revoke the key.' },
    ],
    availability: 'Needs a configured server and a valid key. A submitted answer is not the same as the world accepting it.',
    image: null, alt: null, caption: null,
    href: '/docs/agents', action: 'Agent Integration Guide',
    guides: [{ href: '/docs/agents#docs-agents-python', title: 'Python' },{ href: '/docs/agents#docs-agents-mcp', title: 'MCP' }],
    sources: ['product-direction.md#implementation-status', 'capabilities/outside-agents.md', 'door-contract.md', 'decision-roles-contract.md'],
  },
] as const;
export type UseCase = typeof USE_CASES[number];
