// @vitest-environment happy-dom
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { DOCUMENTS, searchDocumentation } from '../src/ui/docs/catalog.js';
import { buildDocumentation } from '../src/ui/documentation.js';
import { resolveRoute, createRouter } from '../src/router.js';
import { readingFiles } from '../src/content/reading-catalog.js';
import { API_INVENTORY } from '../src/content/api-inventory.js';

const root = resolve(__dirname, '../../../..');
describe('documentation source and navigation contracts', () => {
  it('gives every document a source, real route, export and resolving internal links', () => {
    const files = readingFiles();
    const pages = new Map(DOCUMENTS.map(entry => [entry.href, buildDocumentation(entry.key)]));
    for (const entry of DOCUMENTS) {
      expect(existsSync(resolve(root, entry.build().sourcePath))).toBe(true);
      expect(resolveRoute(new URL(entry.href, 'https://exulanica.com')).surface).not.toBe('not-found');
      expect(files.has(`${entry.href}.md`)).toBe(true);
      const page = pages.get(entry.href)!;
      const ids = [...page.querySelectorAll('[id]')].map(node => node.id);
      expect(new Set(ids).size).toBe(ids.length);
      for (const link of page.querySelectorAll<HTMLAnchorElement>('a[href]')) {
        const url = new URL(link.getAttribute('href')!, 'https://exulanica.com');
        if (url.origin !== 'https://exulanica.com' || files.has(url.pathname) || url.pathname === '/openapi.json') continue;
        expect(resolveRoute(url).surface, link.href).not.toBe('not-found');
        if (url.hash && url.pathname.startsWith('/docs')) {
          expect(pages.get(url.pathname)?.querySelector(`[id="${decodeURIComponent(url.hash.slice(1))}"]`), link.href).not.toBeNull();
        }
      }
    }
  });

  it('preserves moved model, comparison and error section addresses', () => {
    for (const [old, path, hash] of [
      ['/docs/worlds#docs-worlds-models', '/docs/models', '#docs-models-models'],
      ['/docs/worlds#docs-worlds-compare', '/docs/comparisons', '#docs-comparisons-compare'],
      ['/docs/world-api#docs-world-api-responses', '/docs/errors', '#docs-errors-responses'],
    ]) {
      window.history.replaceState(null, '', old!);
      const router = createRouter({ onNavigate: () => {}, readScroll: () => 0 });
      expect(window.location.pathname).toBe(path);
      expect(window.location.hash).toBe(hash);
      router.destroy();
    }
  });

  it('derives the complete operation inventory and authorization rules from pinned contracts', () => {
    const spec = JSON.parse(readFileSync(resolve(root, 'tests/snapshots/api-openapi.json'), 'utf8'));
    const routes = JSON.parse(readFileSync(resolve(root, 'tests/snapshots/api-routes.json'), 'utf8'));
    expect(API_INVENTORY.map(operation => `${operation.method} ${operation.path}`).sort()).toEqual(Object.entries(spec.paths).flatMap(([path, methods]) => Object.keys(methods as object).map(method => `${method} ${path}`)).sort());
    for (const operation of API_INVENTORY) {
      const source = spec.paths[operation.path][operation.method];
      expect(operation.responses).toEqual(source.responses);
      expect(operation.parameters).toEqual(source.parameters ?? []);
      expect(operation.request).toEqual(source.requestBody ?? null);
      expect(operation.permission).toEqual(routes.find((route: { path: string; method: string }) => route.path === operation.path && route.method.toLowerCase() === operation.method).permission);
    }
    const page = buildDocumentation('api-reference');
    for (const operation of API_INVENTORY) expect(page.querySelector(`[id="api-${operation.id}"]`)).not.toBeNull();
    expect(searchDocumentation('/workspace-assets').some(result => result.href.startsWith('/docs/api-reference#api-'))).toBe(true);
  });

  it('keeps card exports readable without merging adjacent links', () => {
    const markdown = readingFiles().get('/docs.md')!;
    expect(markdown).toContain('[Worldbuilding](/docs/worlds)');
    expect(markdown).not.toContain('Copy Page');
  });
});
