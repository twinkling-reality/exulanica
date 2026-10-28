export type CapabilityConcept = 'world' | 'agents' | 'model' | 'comparison' | 'connection';

/** Scope follows docs/product-direction.md and its living contracts:
 * saved-world-entry, world-objects, atlas-world-customization, movement-modules,
 * decision-roles, society-experiments, door, and world-memory-package.
 * Outside Python/MCP agents use the door; broader world edits use the world API.
 */
export const PRODUCT_CAPABILITIES = [
  { id: 'configurations', concept: 'world', title: 'Worlds', copy: 'Start from a ready town, reviewed photographs, or an empty starter.', href: '/docs/worlds', action: 'Worldbuilding' },
  { id: 'agents', concept: 'agents', title: 'Agents', copy: 'People follow a routine until you let an open model decide what they do.', href: '/docs/rules', action: 'Simulation Guide' },
  { id: 'models', concept: 'model', title: 'Open Models', copy: 'Choose an open model for a person, a group, or a junction signal.', href: '/docs/models', action: 'Models and Decisions' },
  { id: 'compare', concept: 'comparison', title: 'Experiments', copy: 'Run the same saved hour with two open models, and once with the same model twice. This does not rank them.', href: '/docs/comparisons', action: 'Comparisons and Replay' },
  { id: 'product-source', concept: 'connection', title: 'Your Own Agent', copy: 'A Python or MCP program can answer a turn with a key you can take back.', href: '/docs/agents', action: 'Agent Integration' },
] as const satisfies readonly { id: string; concept: CapabilityConcept; title: string; copy: string; href: string; action: string }[];
