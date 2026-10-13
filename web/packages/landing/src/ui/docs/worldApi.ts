import { el } from '../dom.js';
import { codeBlock, inline, p, table, routeLink, type DocumentPage } from './elements.js';
import { endpoint, type Endpoint } from './api-endpoint.js';

export const ENDPOINTS = [
  { key: 'list-worlds', title: 'List Worlds', method: 'get', path: '/worlds', description: 'Return the worlds in your workspace and its world-count policy. Use the returned world ID when reading a world’s content.' },
  { key: 'recipes', title: 'List Recipes', method: 'get', path: '/worlds/recipes', description: 'Return the server’s world recipes in catalog order. Each recipe has a key, a display label, and a tile count. Use its key when creating a generated world.' },
  { key: 'generate', title: 'Generate a World', method: 'post', path: '/worlds/generated', description: 'Generate and save a world from a recipe. The response is the saved entry, which identifies the world and the version it reopens.', note: 'Requires a writable deployment and available world capacity. An unknown recipe or unsupported parameter is refused before creating a world. After the world is saved, one tile bake per tile is queued off the request. The world\'s look is named in that same request, not by a separate appearance bake.', body: '{\n    "recipe": "<recipe key>",\n    "title": "My world"\n  }' },
  { key: 'entries', title: 'List Saved Entries', method: 'get', path: '/world-entries', description: 'Read the saved entries your workspace can reopen. An entry carries its title, world ID, and authored version. Use that version when inspecting or editing the world.' },
  { key: 'version', title: 'Read a Version', method: 'get', path: '/world/versions/{version_id}', description: 'Read a world version and its authored state. Retain state_sha256 before editing; it identifies the state your change is based on.' },
  { key: 'capabilities', title: 'Read Capabilities', method: 'get', path: '/world/versions/{version_id}/capabilities', description: 'Discover this version’s regions and supported operations. Descriptors report prerequisites, permission, availability, and reasons an operation cannot run. Use their choices instead of assuming every world supports every edit.' },
  { key: 'models', title: 'List Decision Roles', method: 'get', path: '/world/versions/{version_id}/models', description: 'Read the decision roles registered for a world, the models offered for each role, and the owner’s current choices.', note: 'Read each role’s capability and host_refusal before presenting model control as available. A recorded model choice does not establish that its host is running.' },
  { key: 'society', title: 'Read Society State', method: 'get', path: '/world/versions/{version_id}/society', description: 'Read the society attached to this version, including its current state and the places its inhabitants can visit.', note: 'This operation requires a world with a society. Discover support through the version’s capabilities.' },
  { key: 'replay', title: 'Read Recorded History', method: 'get', path: '/world/versions/{version_id}/society/replay', description: 'Read the society’s history replayed from stored records. Replay uses recorded decisions without making new model calls.' },
  { key: 'objects', title: 'Place an Object', method: 'post', path: '/world/versions/{version_id}/objects', description: 'Place a catalog asset in an authored world. Supply the current state digest, a unique object ID, a supported region, and an asset digest from the catalog.', note: 'The edit advances the authored state under the same version ID. Include saved_entry to update the saved entry’s digest and edit cursor together with the edit. A stale base is refused; reread the state before reconciling your change.', body: '{\n    "base_state_sha256": "<current state digest>",\n    "object_id": "tool:marker",\n    "asset_sha256": "<catalog asset digest>",\n    "region_id": "<region ID>",\n    "transform": {\n      "x_mm": 0, "y_mm": 0, "z_mm": 0,\n      "yaw_microradians": 0, "scale_milli": 1000\n    },\n    "origin_role": "fictional"\n  }' },
] as const satisfies readonly Endpoint[];
export function worldApi(): DocumentPage {
  return {
    title: 'World API', introduction: 'Create and edit persistent worlds. Inspect their state, available models, and recorded decisions over HTTP.', sourcePath: 'docs/capabilities/world-api.md',
    chapters: [
      { key: 'authentication', title: 'Authentication', nodes: [
        el('div', { class: 'api-authentication' }, [el('div', {}, [el('p', {}, ['Requests use ', inline('Authorization: Bearer <token>'), '. Tokens belong to a workspace. Read operations require ', inline('world.read'), '; edits require ', inline('world.write'), '. Use the URL of your Exulanica server. For a local installation:'])]),
        codeBlock('Environment', 'export EXULANICA_API_URL="http://127.0.0.1:8000"\n# Set EXULANICA_TOKEN to the token issued by your server operator.', 'bash')]),
        el('p', {}, ['These references cover world creation, versioned edits, model roles, and society reads. ', el('a', { href: '/openapi.json', text: 'Download the full OpenAPI schema' }), ' for all routes and nested definitions. The ', inline('/openapi.json'), ' on your running server describes that installation.']),
      ] },
      { key: 'operations', title: 'Operations', nodes: [el('nav', { class: 'api-operation-index', 'aria-label': 'API operations' }, ENDPOINTS.map(entry => el('a', { href: `/docs/world-api/${entry.key}` }, [el('span', { class: `api-method ${entry.method}`, text: entry.method.toUpperCase() }), el('strong', { text: entry.title }), el('code', { text: entry.path })])))] },
      { key: 'workflow', title: 'Read Before You Write', nodes: [p('List the workspace’s worlds, read its saved entry and version, then discover capabilities. Retain the state digest before editing. Inspect the saved state after a lost connection before retrying a write.'), el('p', {}, [el('a', { href: '/docs/authentication', text: 'Authentication' }), ' · ', el('a', { href: '/docs/errors', text: 'Errors and Recovery' }), ' · ', el('a', { href: '/docs/portability', text: 'Export and Portability' })])] },
    ],
  };
}

export function apiOperation(entry: Endpoint): DocumentPage {
  return { title: entry.title, introduction: entry.description, sourcePath: 'docs/capabilities/world-api.md', chapters: [
    { key: 'request', title: 'Request and Response', nodes: endpoint(entry, false) },
    { key: 'authentication', title: 'Authentication', nodes: [el('p', {}, ['Send ', inline('Authorization: Bearer <token>'), ' with a token for your workspace. Read operations require ', inline('world.read'), '; writes require ', inline('world.write'), '.']), routeLink('/docs/authentication', 'Authentication and access')] },
  ] };
}

export function errors(): DocumentPage {
  return { title: 'Errors and Recovery', introduction: 'Resolve permission, availability and state conflicts without duplicating a write.', sourcePath: 'docs/capabilities/world-api.md', chapters: [
      { key: 'responses', title: 'Errors and Retries', nodes: [
        table(['Response', 'Meaning', 'Action'], [
          ['403 worlds_read_only', 'The deployment cannot register worlds.', 'Use a writable deployment.'],
          ['404 unknown_reference', 'The reference is unknown or outside this workspace.', 'Check IDs and the token’s workspace.'],
          ['409 stale_object_base', 'The state changed after you read it.', 'Reread, reconcile, and submit against the new digest.'],
          ['422', 'A request field or generated-world parameter is invalid.', 'Read the error detail and correct the input.'],
        ]),
        p('Do not blindly retry a write after a lost connection: first inspect the world or saved entry to determine whether the change was applied. Capability availability and token permission are separate checks.'),
      ] },
    { key: 'availability', title: 'Unavailable Is Not Unsupported', nodes: [table(['State', 'What to do'], [['available', 'The server would attempt the operation. Inputs and state are still validated.'], ['unavailable', 'Read the reason. A dependency or the world\'s state prevents this operation. Permission is separate: an operation can be available and still not permitted to this token.'], ['unsupported', 'This kind of world, engine or role does not support the operation. Choose a supported operation.'], ['unknown', 'A required fact is outside what this caller may read. Do not guess availability.']]), p('Read capability descriptors when your UI needs to decide whether to offer an action. Handle the write’s own refusal too: state can change between discovery and submission.')] },
    { key: 'writes', title: 'Recover a Failed Edit', nodes: [p('For a stale base, read the version again and reconcile your intended change against its new state digest. Do not silently overwrite another client’s edit.'), p('After a network timeout, read the affected world or saved entry first. Submit again only after determining whether the original change took effect. Use a documented idempotency field when the operation offers one; do not invent a global retry key.')] },
    { key: 'configuration', title: 'Check the Installation', nodes: [p('For connection failures, verify the API address and /readyz. Optional workers and model providers have their own prerequisites; a running server does not establish that each service is ready.'), el('p', {}, [el('a', { href: '/docs/self-hosting', text: 'Installation and maintenance' }), ' · ', el('a', { href: '/docs/authentication#docs-authentication-failures', text: 'Access troubleshooting' })])] },
  ] };
}
