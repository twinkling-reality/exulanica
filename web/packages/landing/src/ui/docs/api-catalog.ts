import { el } from '../dom.js';
import { p, codeBlock, type DocumentPage } from './elements.js';
import { API_INVENTORY } from '../../content/api-inventory.js';
import { ENDPOINTS } from './worldApi.js';
const groupLabel = (key: string) => key.replace(/-/g, ' ').replace(/^./, value => value.toUpperCase());
export function apiCatalog(): DocumentPage {
  const groups = [...new Set(API_INVENTORY.map(operation => operation.group))];
  return { title: 'API Reference', introduction: 'Browse the pinned API contract by responsibility, including authorization, parameters and schema references.', sourcePath: 'tests/snapshots/api-openapi.json', chapters: [
    { key: 'using', title: 'Use the contract', nodes: [p('This catalog includes every operation in the published OpenAPI contract. Expand an operation to read its access rule and wire definition. World API guides provide explained requests for common workflows; the complete schema defines the nested types.'), el('p', {}, [el('a', { href: '/openapi.json', text: 'Download OpenAPI' }), ' · ', el('a', { href: '/docs/world-api', text: 'Guided World API reference' })]), p('Use /openapi.json on your own API server to check the contract installed there. Public probes, browser sessions, workspace tokens and outside-agent keys have different access rules; each operation below states its own.')] },
    ...groups.map(group => ({ key: group, title: groupLabel(group), nodes: API_INVENTORY.filter(operation => operation.group === group).map(operation => {
      const explained = ENDPOINTS.find(entry => entry.path === operation.path && entry.method === operation.method);
      const permission = operation.permission.requires ? `Required permissions: ${operation.permission.requires.join(', ')}` : Object.entries(operation.permission).map(([kind, rule]) => `${groupLabel(kind)}: ${typeof rule === 'string' ? rule : JSON.stringify(rule)}`).join('. ');
      const id = `api-${operation.id}`;
      return el('details', { class: 'api-catalog-operation', id, 'data-search-title': `${operation.method.toUpperCase()} ${operation.path}`, 'data-search-excerpt': `${operation.title}. ${operation.description || permission}` }, [el('summary', {}, [el('span', { class: `api-method ${operation.method}`, text: operation.method.toUpperCase() }), el('code', { text: operation.path })]), el('div', { class: 'api-catalog-body' }, [el('h3', { text: operation.title }), ...(operation.description ? [p(operation.description)] : []), p(permission), el('p', {}, [el('a', { href: `/docs/api-reference#${id}`, text: 'Link to this operation' }), ...(explained ? [' · ', el('a', { href: `/docs/world-api/${explained.key}`, text: 'Request examples and fields' })] : [])]), codeBlock('Wire definition', JSON.stringify({ parameters: operation.parameters, ...(operation.request ? { requestBody: operation.request } : {}), responses: operation.responses }, null, 2), 'json', false), p('Schema references resolve in the complete OpenAPI download. This is a contract definition, not example response data.')])]);
    }) })),
  ] };
}
