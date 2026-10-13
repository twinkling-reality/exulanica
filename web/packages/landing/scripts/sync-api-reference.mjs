import { readFileSync, writeFileSync } from 'node:fs';
const source = JSON.parse(readFileSync(new URL('../../../../tests/snapshots/api-openapi.json', import.meta.url), 'utf8'));
const selected = {
  '/worlds': ['get'], '/worlds/recipes': ['get'], '/worlds/generated': ['post'],
  '/world/versions/{version_id}/models': ['get'], '/world/versions/{version_id}/society': ['get'], '/world/versions/{version_id}/society/replay': ['get'],
  '/world-entries': ['get'], '/world/versions/{version_id}': ['get'],
  '/world/versions/{version_id}/capabilities': ['get'], '/world/versions/{version_id}/objects': ['post'],
};
const paths = {}, schemas = {};
function collect(value) {
  if (!value || typeof value !== 'object') return;
  if (value.$ref) {
    const key = value.$ref.split('/').at(-1);
    if (!(key in schemas)) { schemas[key] = source.components.schemas[key]; collect(schemas[key]); }
  }
  Object.values(value).forEach(collect);
}
for (const [path, methods] of Object.entries(selected)) {
  paths[path] = {};
  for (const method of methods) { paths[path][method] = source.paths[path][method]; collect(paths[path][method]); }
}
const data = { paths, schemas };
writeFileSync(new URL('../src/content/api-schema.ts', import.meta.url), '// Generated from tests/snapshots/api-openapi.json. Run scripts/sync-api-reference.mjs.\nimport type { ApiSpec } from "./api-types.js";\nexport const API_SCHEMA: ApiSpec = ' + JSON.stringify(data, null, 2) + ';\n');

// All installed operations remain discoverable, beyond the guided request examples.
const routes = JSON.parse(readFileSync(new URL('../../../../tests/snapshots/api-routes.json', import.meta.url), 'utf8'));
const inventory = Object.entries(source.paths).flatMap(([path, methods]) => Object.entries(methods).map(([method, operation]) => {
  const route = routes.find(item => item.path === path && item.method.toLowerCase() === method);
  if (!route) throw new Error(`Missing authorization contract for ${method} ${path}`);
  return { path, method, id: operation.operationId, title: operation.summary, description: operation.description ?? '', group: operation.tags?.[0] ?? 'other', permission: route.permission, parameters: operation.parameters ?? [], request: operation.requestBody ?? null, responses: operation.responses };
}));
writeFileSync(new URL('../src/content/api-inventory.ts', import.meta.url), '// Generated from the pinned API and route contracts. Run scripts/sync-api-reference.mjs.\nimport type { InventoryOperation } from "./api-types.js";\nexport const API_INVENTORY: readonly InventoryOperation[] = ' + JSON.stringify(inventory, null, 2) + ';\n');
