/** Reader journeys, grounded in docs/product-direction.md and the named living
 * contracts. This catalog owns Use Cases copy and links, not implementation status elsewhere.
 * Claim evidence and the semantic audit live in ignored .exulanica/briefs.
 */
export const USE_CASES = [
  {
    key: 'model-comparison', legacyKey: 'agent-experiments', title: 'Agent Experiments',
    audience: 'Model Builders',
    summary: 'Compare models from the same saved world, then inspect and replay their decisions.',
    introduction: 'See what changes when a different open model decides for the same group of people.',
    workflowTitle: 'Model Comparison',
    steps: [
      { title: 'Starting World', copy: 'Choose a saved world, a group, and two available models. The app runs one simulated hour from the same starting state.' },
      { title: 'Recorded Outcomes', copy: 'Read the verdict beside the same-model control. Routine and waiting runs provide the score’s baselines.' },
      { title: 'Decision Inspection', copy: 'Follow both runs on one timeline. Inspect observations, proposals, and applied actions; replay makes no model calls.' },
    ],
    availability: 'A saved society, configured models, and a spending bound are required. A result can show no measured difference; it applies to this scenario and score.',
    planned: 'Exported-run retraining is planned. The app starts an hour, because its start body leaves the window unset and the route defaults to hour. A day is window day on POST /world/versions/{version_id}/society/comparisons, or python -m exulanica.orchestration.compare --window day. A finished day has a verdict, as an hour does. A purposeful society is not compared over a day.',
    image: null, alt: null, caption: null,
    href: '/docs/comparisons', action: 'Comparisons and Replay',
    guides: [{ href: '/docs/models', title: 'Models and Decisions' }],
    sources: ['product-direction.md#first-milestone', 'society-experiments.md#comparisons-of-models', 'decision-roles-contract.md'],
  },
  {
    key: 'worldbuilding', legacyKey: 'worldbuilding', title: 'Worldbuilding',
    audience: 'Worldbuilders',
    summary: 'Create a setting, place supported objects, and return to your saved changes.',
    introduction: 'Build a place to return to, with its objects, appearance, and saved history intact.',
    workflowTitle: 'Saved Settings',
    steps: [
      { title: 'Starting Point', copy: 'Use an empty authored starter or create a place from a supported recipe and validated values.' },
      { title: 'Objects and Appearance', copy: 'Place available catalog objects. Review the position, appearance, and behavior controls your world supports.' },
      { title: 'Saved Changes', copy: 'Keep accepted edits, reopen the world from Your worlds, and continue building.' },
    ],
    availability: 'Creation and edits depend on your installation and world type. A reference photograph does not supply reconstructed geometry.',
    planned: 'General structural editing and arbitrary world rules remain product targets.',
    image: '/worlds/narrow-streets.jpg', alt: 'A generated Exulanica town with narrow streets and rowhouses.',
    caption: 'A generated town from a supported recipe. Its appearance is a representation of the saved world.',
    href: '/docs/worlds#docs-worlds-create', action: 'Worldbuilding Guide',
    guides: [{ href: '/docs/assets', title: 'Assets and Imports' },{ href: '/docs/rules', title: 'World Rules' }],
    sources: ['product-direction.md#saved-world-foundation', 'world-objects-contract.md', 'atlas-world-customization-contract.md', 'world-kinds-contract.md'],
  },
  {
    key: 'agent-development', legacyKey: 'agent-development', title: 'Agent Development',
    audience: 'Agent Developers',
    summary: 'Connect a Python or MCP client to authorized turns and inspect its action results.',
    introduction: 'Give an outside agent a role in a world through an owner-issued grant.',
    workflowTitle: 'Authorized Turns',
    steps: [
      { title: 'World Access', copy: 'Connect your Python or MCP client using the server address and the key issued by the world’s owner.' },
      { title: 'Offered Actions', copy: 'Read a turn’s observations and choose one offered action before its deadline.' },
      { title: 'Recorded Results', copy: 'Inspect whether the engine applied the answer. A missed turn leaves the decision to the world’s routine.' },
    ],
    availability: 'A configured server and valid grant are required. The owner can revoke access. Outside agents are separate from built-in model comparison arms.',
    planned: null,
    image: null, alt: null, caption: null,
    href: '/docs/agents', action: 'Agent Integration Guide',
    guides: [{ href: '/docs/agents#docs-agents-python', title: 'Python' },{ href: '/docs/agents#docs-agents-mcp', title: 'MCP' }],
    sources: ['product-direction.md#implementation-status', 'capabilities/outside-agents.md', 'door-contract.md', 'decision-roles-contract.md'],
  },
] as const;
export type UseCase = typeof USE_CASES[number];
