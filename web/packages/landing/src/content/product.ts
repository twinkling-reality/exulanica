export type CapabilityConcept = 'world' | 'agents' | 'model' | 'comparison' | 'connection';

/** Scope follows docs/product-direction.md and its living contracts:
 * saved-world-entry, world-objects, atlas-world-customization, movement-modules,
 * decision-roles, society-experiments, door, and world-memory-package.
 * Outside Python/MCP agents use the door; broader world edits use the world API.
 */
export const PRODUCT_CAPABILITIES = [
  { id: 'configurations', concept: 'world', title: 'Worlds', copy: 'Build from recipes, reviewed photographs, or an empty space. Place permitted content, shape its appearance, and save the world.', href: '/docs/worlds', action: 'Worldbuilding' },
  { id: 'agents', concept: 'agents', title: 'Agents', copy: 'Give inhabitants routines and usable objects. Walking, bird flight, and town traffic follow the world’s movement rules.', href: '/docs/rules', action: 'Simulation Guide' },
  { id: 'models', concept: 'model', title: 'Open Models', copy: 'Choose an open model for a person, group, or junction signal. Inspect its observations, proposals, and accepted actions.', href: '/docs/models', action: 'Models and Decisions' },
  { id: 'compare', concept: 'comparison', title: 'Experiments', copy: 'Run different models from the same saved world. Compare outcomes against a same-model control, then inspect and replay decisions.', href: '/docs/comparisons', action: 'Comparisons and Replay' },
  { id: 'product-source', concept: 'connection', title: 'Integrations', copy: 'Connect outside agents through Python or MCP. Use the world API for permitted edits, or export signed snapshots with declared coverage.', href: '/docs/agents', action: 'Agent Integration' },
] as const satisfies readonly { id: string; concept: CapabilityConcept; title: string; copy: string; href: string; action: string }[];
