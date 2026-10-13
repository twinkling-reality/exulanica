import { apiCatalog } from './api-catalog.js';
import { worlds } from './worlds.js';
import { selfHosting } from './selfHosting.js';
import { overview } from './overview.js';
import { worldApi, errors, apiOperation, ENDPOINTS } from './worldApi.js';
import { agents } from './agents.js';
import { quickstart, worldConcepts, authentication, assets, portability, worldRules } from './foundations.js';
import { models, comparisons } from './models.js';

/** The authoring catalog owns navigation, routes, metadata, article order and exports. */
export const DOCUMENTS = [
  { key: 'index', href: '/docs', label: 'Introduction', group: 'Getting Started', description: 'Build a world, choose open models and inspect their decisions. Find your path through Exulanica.', build: overview },
  { key: 'quickstart', href: '/docs/quickstart', label: 'Quickstart', group: 'Getting Started', description: 'Create a world, shape its content, connect models and inspect their decisions.', build: quickstart },
  { key: 'self-hosting', href: '/docs/self-hosting', label: 'Installation', group: 'Getting Started', description: 'Configure a persistent Exulanica installation with a browser, API, database and model services.', build: selfHosting },
  { key: 'authentication', href: '/docs/authentication', label: 'Authentication', group: 'Getting Started', description: 'Authenticate a workspace client and distinguish browser accounts, API tokens and agent grant keys.', build: authentication },
  { key: 'concepts', href: '/docs/concepts', label: 'World Structure', group: 'Worlds', description: 'Understand world identity, versioned edits, sources, representations and recorded time.', build: worldConcepts },
  { key: 'worlds', href: '/docs/worlds', label: 'Worldbuilding', group: 'Worlds', description: 'Create a durable place, reopen its saved state and edit supported objects.', build: worlds },
  { key: 'assets', href: '/docs/assets', label: 'Assets and Imports', group: 'Worlds', description: 'Build with catalog assets and supported imports while preserving their origin, preparation and permitted uses.', build: assets },
  { key: 'rules', href: '/docs/rules', label: 'World Rules', group: 'Worlds', description: 'Understand movement, supported behavior and the boundaries of configurable simulation.', build: worldRules },
  { key: 'models', href: '/docs/models', label: 'Models and Decisions', group: 'Models and Agents', description: 'Assign open models to supported roles and inspect the engine’s validated decisions.', build: models },
  { key: 'comparisons', href: '/docs/comparisons', label: 'Comparisons and Replay', group: 'Models and Agents', description: 'Run from a shared starting state and read model differences against the same-model control.', build: comparisons },
  { key: 'agents', href: '/docs/agents', label: 'Agent Integration', group: 'Models and Agents', description: 'Connect an outside agent to authorized turns through Python or MCP with an owner-issued grant key.', build: agents },
  { key: 'world-api', href: '/docs/world-api', label: 'World API', group: 'Developer Tools', description: 'Read and edit versioned worlds and inspect models and recorded decisions over HTTP.', build: worldApi },
  { key: 'api-reference', href: '/docs/api-reference', label: 'API Reference', group: 'Developer Tools', description: 'Browse every pinned API operation with its authorization rule, parameters and wire schema.', build: apiCatalog },
  { key: 'errors', href: '/docs/errors', label: 'Errors and Recovery', group: 'Developer Tools', description: 'Resolve availability, permission and state conflicts without duplicating a write.', build: errors },
  { key: 'portability', href: '/docs/portability', label: 'Export and Portability', group: 'Developer Tools', description: 'Carry a signed world projection and understand its coverage, rights and restore limits.', build: portability },
  ...ENDPOINTS.map(operation => ({ key: `world-api-${operation.key}` as const, href: `/docs/world-api/${operation.key}`, label: operation.title, group: 'API Operations', description: operation.description, build: () => apiOperation(operation) })),
] as const;
export type DocumentationKind = typeof DOCUMENTS[number]['key'];
export const documentId = (kind: DocumentationKind): string => kind === 'index' ? 'docs' : `docs-${kind}`;
export const DOCUMENTATION_ROUTES = DOCUMENTS.map(entry => ({ path: entry.href, surface: documentId(entry.key) as 'docs' | `docs-${Exclude<DocumentationKind, 'index'>}`, title: `${entry.key === 'index' ? 'Documentation' : entry.label} | Exulanica` }));

export interface SearchResult { title: string; page: string; group: string; href: string; text: string; excerpt: string; kind: 'page' | 'section' | 'operation'; snippets?: string[] }
let searchIndex: SearchResult[] | undefined;
const normalizeSearch = (text: string) => text.normalize('NFKC').toLocaleLowerCase();
const words = (text: string) => normalizeSearch(text).match(/[\p{L}\p{N}_]+/gu) ?? [];

/** Decorative metadata must not alter identifiers, ranking or contextual excerpts. */
function searchText(node: Node): string {
  if (node instanceof Element && node.getAttribute('aria-hidden') === 'true') return '';
  return node.childNodes.length ? Array.from(node.childNodes, searchText).join('') : node.textContent ?? '';
}

function documentationIndex(): SearchResult[] {
  return DOCUMENTS.flatMap(entry => {
    const page = entry.build();
    const home: SearchResult = { title: entry.label, page: entry.group, group: entry.group, href: entry.href, text: page.introduction, excerpt: entry.description, kind: 'page' };
    return [home, ...page.chapters.flatMap(chapter => {
      const operations = chapter.nodes.filter((node): node is HTMLElement => node instanceof HTMLElement && node.matches('.api-catalog-operation'));
      const prose = chapter.nodes.flatMap(node => node instanceof HTMLElement ? [node.matches('p') ? node : null, ...node.querySelectorAll('p, dd, li')].filter((item): item is HTMLElement => item instanceof HTMLElement).map(searchText) : []);
      const excerpt = prose.find(text => text.trim()) ?? entry.description;
      const section: SearchResult = { title: chapter.title, page: entry.label, group: entry.group, href: `${entry.href}#${documentId(entry.key)}-${chapter.key}`, text: operations.length ? excerpt : chapter.nodes.map(searchText).join(' '), excerpt, snippets: prose, kind: 'section' };
      return [section, ...operations.map(operation => ({ title: operation.dataset.searchTitle!, page: entry.label, group: entry.group, href: `${entry.href}#${operation.id}`, text: searchText(operation), excerpt: operation.dataset.searchExcerpt ?? entry.description, kind: 'operation' as const }))];
    })];
  });
}

/** Match words and code identifiers; punctuation never broadens a query into a common letter. */
export function searchDocumentation(query: string): SearchResult[] {
  const phrase = normalizeSearch(query.trim());
  const terms = words(phrase);
  if (!terms.length) return [];
  searchIndex ??= documentationIndex();
  const literal = /[$@{}<>]/.test(phrase);
  const matches = (text: string, term: string) => words(text).some(word => word === term || (term.length >= 3 && word.startsWith(term)));
  const score = (result: SearchResult) => {
    const title = normalizeSearch(result.title);
    return (title === phrase ? 120 : title.startsWith(phrase) ? 80 : title.includes(phrase) ? 55 : 0)
      + terms.reduce((sum, term) => sum + (matches(result.title, term) ? 16 : 0) + (matches(result.page, term) ? 5 : 0), 0)
      + (result.kind === 'page' ? 40 : result.kind === 'operation' ? 4 : result.page === 'API Reference' ? -30 : 0);
  };
  return searchIndex.filter(result => {
    const content = `${result.title} ${result.page} ${result.text}`;
    return literal ? normalizeSearch(content).includes(phrase) : terms.every(term => matches(content, term));
  }).sort((a, b) => score(b) - score(a) || a.title.localeCompare(b.title)).map(result => {
    const snippet = result.snippets?.find(text => terms.every(term => matches(text, term)));
    return snippet ? { ...result, excerpt: snippet } : result;
  });
}
