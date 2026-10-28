import type { InventoryOperation } from '../../content/api-types.js';

export const API_JOBS = [
  { key: 'worldbuilding', title: 'Worldbuilding', job: 'Create or reopen a world.' },
  { key: 'workspace-assets', title: 'Assets and Imports', job: 'Admit content, style packs, and photographs, and prepare them for a world.' },
  { key: 'state', title: 'World Structure', job: 'Read a version, discover supported capabilities, and edit objects or appearance.' },
  { key: 'models', title: 'Models and Decisions', job: 'Assign an open model to a role and run or inspect decisions.' },
  { key: 'replay', title: 'Comparisons and Replay', job: 'Run a controlled model comparison or replay recorded history.' },
  { key: 'agents', title: 'Agent Integration', job: 'Grant an outside agent a turn or ask the Companion.' },
  { key: 'authentication', title: 'Authentication', job: 'Authenticate a browser session or admit a guest.' },
  { key: 'installation', title: 'Installation', job: 'Check server readiness, worker queues, and spending bounds.' },
] as const;

export type ApiJobKey = (typeof API_JOBS)[number]['key'];

export function jobFor(operation: Pick<InventoryOperation, 'group' | 'path'>): ApiJobKey {
  const { group, path } = operation;
  if (group === 'health' || group === 'operations' || group === 'spending' || path.startsWith('/world/github-projects')) {
    return 'installation';
  }
  if (group === 'accounts') return 'authentication';
  if (
    group === 'workspace-assets' || group === 'workspace-style-packs' || group === 'personal-admission'
    || group === 'environment-resources' || group === 'intake' || group === 'formation' || group === 'tiles'
    || group === 'materials' || group === 'character-appearance' || group === 'graph' || group === 'geometry'
    || group === 'evidence' || group === 'identity' || group === 'person-regions' || group === 'place-name-rights'
    || path.startsWith('/world/assets') || path.startsWith('/world/style-packs') || path.startsWith('/world/source-media')
    || path.startsWith('/world/piece-requests') || path.startsWith('/world/paintings') || path.startsWith('/world/character-catalogs')
  ) {
    return 'workspace-assets';
  }
  if (group === 'door' || group === 'companion' || group === 'participation' || group === 'selection' || group === 'integrations') {
    return 'agents';
  }
  if (group === 'history' || path.includes('replay') || path.includes('compar')) return 'replay';
  if (group === 'models' || path.includes('/models')) return 'models';
  if (group === 'society') return 'models';
  if (group === 'world-generation' || group === 'world-entries' || group === 'worlds' || path.startsWith('/worlds') || path.startsWith('/world-entries')) {
    return 'worldbuilding';
  }
  return 'state';
}
