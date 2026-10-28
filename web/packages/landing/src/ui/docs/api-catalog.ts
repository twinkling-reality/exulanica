import { el } from '../dom.js';
import { p, codeBlock, destinations, onward, type DocumentPage } from './elements.js';
import { API_INVENTORY } from '../../content/api-inventory.js';
import { ENDPOINTS } from './worldApi.js';
import { API_JOBS, jobFor, type ApiJobKey } from './api-jobs.js';

const groupLabel = (key: string) => key.replace(/-/g, ' ').replace(/^./, value => value.toUpperCase());
const cleanProse = (text: string) => text.replace(/:[a-z]+:`([^`]+)`/g, '$1').replace(/``([^`]+)``/g, '$1').replace(/\s+/g, ' ').trim();

function operationNode(operation: (typeof API_INVENTORY)[number]) {
  const explained = ENDPOINTS.find(entry => entry.path === operation.path && entry.method === operation.method);
  const title = explained?.title ?? operation.title;
  const description = explained?.description ?? (operation.description ? cleanProse(operation.description) : '');
  const permission = operation.permission.requires ? `Required permissions: ${operation.permission.requires.join(', ')}` : Object.entries(operation.permission).map(([kind, rule]) => `${groupLabel(kind)}: ${typeof rule === 'string' ? rule : JSON.stringify(rule)}`).join('. ');
  const id = `api-${operation.id}`;
  return el('details', { class: 'api-catalog-operation', id, 'data-search-title': title, 'data-search-excerpt': `${operation.method.toUpperCase()} ${operation.path}. ${description || permission}` }, [el('summary', {}, [el('span', { class: `api-method ${operation.method}`, text: operation.method.toUpperCase() }), el('span', { class: 'api-catalog-name', text: title }), el('code', { text: operation.path })]), el('div', { class: 'api-catalog-body' }, [...(description ? [p(description)] : []), p(permission), el('p', {}, [el('a', { href: `/docs/api-reference#${id}`, text: 'Link to this operation' }), ...(explained ? ['. ', el('a', { href: `/docs/world-api/${explained.key}`, text: 'Request examples and fields' })] : []), '.']), codeBlock('Wire definition', JSON.stringify({ parameters: operation.parameters, ...(operation.request ? { requestBody: operation.request } : {}), responses: operation.responses }, null, 2), 'json', false), p('Schema references resolve in the complete OpenAPI download. This is a contract definition, not example response data.')])]);
}

function sortForJob(operations: readonly (typeof API_INVENTORY)[number][]) {
  return [...operations].sort((a, b) => {
    const aExplained = ENDPOINTS.findIndex(entry => entry.path === a.path && entry.method === a.method);
    const bExplained = ENDPOINTS.findIndex(entry => entry.path === b.path && entry.method === b.method);
    if (aExplained !== -1 || bExplained !== -1) {
      if (aExplained === -1) return 1;
      if (bExplained === -1) return -1;
      return aExplained - bExplained;
    }
    const aDepth = a.path.split('/').length;
    const bDepth = b.path.split('/').length;
    return aDepth - bDepth || a.path.localeCompare(b.path);
  });
}

function guidedLinksForJob(key: ApiJobKey): Node[] {
  const guided = ENDPOINTS.filter(entry => jobFor({ group: '', path: entry.path }) === key);
  if (guided.length === 0) return [];
  return [destinations(guided.map(entry => ({
    label: entry.title,
    detail: `${entry.method.toUpperCase()} ${entry.path}. ${entry.description}`,
    href: `/docs/world-api/${entry.key}`,
  })))];
}

export function apiCatalog(): DocumentPage {
  return {
    title: 'API Reference',
    introduction: 'Look up a pinned route by the job it serves. World API explains the requests a world client writes first.',
    sourcePath: 'tests/snapshots/api-openapi.json',
    chapters: [
      { key: 'using', title: 'The pinned surface', nodes: [
        p('This page is a lookup of every operation in the published OpenAPI contract, grouped by the job a future client is trying to do. Expand a route to read its access rule and wire definition.'),
        p('Use /openapi.json on your own API server to check the contract installed there. Public probes, browser sessions, workspace tokens and outside-agent keys have different access rules; each operation states its own.'),
        el('p', {}, [el('a', { href: '/openapi.json', text: 'Download the pinned OpenAPI schema' }), '.']),
        onward('/docs/world-api', 'World API'),
      ] },
      ...API_JOBS.flatMap(job => {
        const operations = sortForJob(API_INVENTORY.filter(operation => jobFor(operation) === job.key));
        if (operations.length === 0) return [];
        return [{
          key: job.key,
          title: job.title,
          nodes: [p(job.job), ...guidedLinksForJob(job.key), ...operations.map(operationNode)],
        }];
      }),
    ],
  };
}
