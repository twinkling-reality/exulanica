// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildDocumentation } from '../src/ui/documentation.js';
import { resolveRoute } from '../src/router.js';
import { ENDPOINTS } from '../src/ui/docs/worldApi.js';
import { DOCUMENTS, documentId, searchDocumentation } from '../src/ui/docs/catalog.js';

afterEach(() => vi.restoreAllMocks());

describe('public documentation', () => {
  it.each(DOCUMENTS.filter(entry => entry.group !== 'API Operations').map(entry => entry.key))('provides navigable sections for %s', (kind) => {
    const page = buildDocumentation(kind);
    expect(page.getAttribute('aria-labelledby')).toBe(page.querySelector('h1')?.id);
    expect(page.getAttribute('tabindex')).toBe('-1');
    const current = page.querySelector('[aria-current="page"]');
    expect(current?.getAttribute('href')).toBe(kind === 'index' ? '/docs' : `/docs/${kind}`);
    for (const link of page.querySelectorAll<HTMLAnchorElement>('.docs-contents a')) {
      expect(page.querySelector(link.hash)).not.toBeNull();
    }
    expect(page.querySelectorAll('.docs-chapter').length).toBeGreaterThan(2);
  });

  it('gives every operation a direct route, preserves old anchors, and switches request languages by keyboard', () => {
    for (const endpoint of ENDPOINTS) {
      const path = `/docs/world-api/${endpoint.key}`;
      expect(resolveRoute(new URL(path, 'https://exulanica.com')).surface).toBe(`docs-world-api-${endpoint.key}`);
      expect(resolveRoute(new URL(`/docs/world-api#docs-world-api-${endpoint.key}`, 'https://exulanica.com')).path).toBe(path);
    }
    const page = buildDocumentation('world-api-generate');
    document.body.append(page);
    const tabs = page.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    tabs[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(document.activeElement).toBe(tabs[1]);
    expect(tabs[1]!.getAttribute('aria-selected')).toBe('true');
    expect(page.querySelectorAll<HTMLElement>('[role="tabpanel"]')[1]!.hidden).toBe(false);
    expect(page.querySelectorAll<HTMLElement>('[role="tabpanel"]')[0]!.hidden).toBe(true);
    page.remove();
  });

  it('keeps guide pagination separate from the operation catalog', () => {
    const guide = buildDocumentation('agents');
    expect(guide.querySelector('.docs-pager .previous')?.getAttribute('href')).toBe('/docs/comparisons');
    expect(guide.querySelector('.docs-pager .previous')?.getAttribute('aria-label')).toBe('Previous: Comparisons and Replay');
    expect(guide.querySelector('.docs-pager .next')?.getAttribute('rel')).toBe('next');
    const operation = buildDocumentation('world-api-objects');
    expect(operation.querySelector('.docs-pager .next')).toBeNull();
    expect(operation.querySelector('.docs-pager .previous')?.getAttribute('href')).toBe('/docs/world-api/replay');
  });

  it('copies exactly the displayed example and confirms completion', async () => {
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    const page = buildDocumentation('world-api');
    page.querySelector<HTMLButtonElement>('.docs-copy')!.click();
    await Promise.resolve();
    expect(writeText).toHaveBeenCalledWith(page.querySelector('.docs-code pre code')!.textContent);
    expect(page.querySelector('.docs-code [role="status"]')!.textContent).toBe('Copied');
  });

  it('offers a manual copy fallback if clipboard access fails', async () => {
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('Denied'));
    const page = buildDocumentation('agents');
    page.querySelector<HTMLButtonElement>('.docs-copy')!.click();
    await Promise.resolve();
    expect(page.querySelector('.docs-code [role="status"]')!.textContent).toBe('Select the code to copy it.');
  });

  it('finds section content across guides and resolves every result to a real anchor', () => {
    expect(searchDocumentation('MCP')[0]?.href).toBe('/docs/agents#docs-agents-mcp');
    expect(searchDocumentation('stale_object_base').map(result => result.href)).toContain('/docs/errors#docs-errors-responses');
    expect(searchDocumentation('   ')).toEqual([]);
    expect(searchDocumentation('not-a-real-topic')).toEqual([]);
    for (const entry of DOCUMENTS) {
      const page = buildDocumentation(entry.key);
      for (const chapter of entry.build().chapters) {
        const href = `${entry.href}#${documentId(entry.key)}-${chapter.key}`;
        expect(searchDocumentation(chapter.title).some(result => result.href === href)).toBe(true);
        expect(page.querySelector(`#${documentId(entry.key)}-${chapter.key}`)).not.toBeNull();
      }
    }
  });

  it('keeps search focus while selecting results and restores the launcher on dismissal', () => {
    const page = buildDocumentation('index');
    document.body.append(page);
    const trigger = page.querySelector<HTMLButtonElement>('.docs-search-trigger')!;
    trigger.click();
    const dialog = document.querySelector<HTMLDialogElement>('#documentation-search')!;
    const input = dialog.querySelector('input')!;
    expect(dialog.open).toBe(true);
    expect(document.activeElement).toBe(input);
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }));
    const close = dialog.querySelector<HTMLButtonElement>('[aria-label="Close search"]')!;
    expect(document.activeElement).toBe(close);
    close.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    expect(document.activeElement).toBe(input);
    input.value = 'MCP';
    input.dispatchEvent(new Event('input'));
    const links = dialog.querySelectorAll<HTMLAnchorElement>('[role="option"]');
    expect(links[0]?.getAttribute('href')).toBe('/docs/agents#docs-agents-mcp');
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(document.activeElement).toBe(input);
    expect(input.getAttribute('aria-activedescendant')).toBe(links[1]!.id);
    expect(links[1]!.getAttribute('aria-selected')).toBe('true');
    dialog.querySelector<HTMLButtonElement>('[aria-label="Clear search"]')!.click();
    expect(input.value).toBe('');
    expect(dialog.textContent).toContain('Suggested Guides');
    dialog.querySelector<HTMLButtonElement>('[aria-label="Close search"]')!.click();
    expect(dialog.open).toBe(false);
    expect(document.activeElement).toBe(trigger);
    dialog.remove(); page.remove();
  });

  it('does not broaden symbols or short queries into unrelated substrings', () => {
    expect(searchDocumentation('f$')).toEqual([]);
    expect(searchDocumentation('$$$')).toEqual([]);
    expect(searchDocumentation('MCP')[0]?.title).toBe('MCP');
    expect(searchDocumentation('Quickstart')[0]?.href).toBe('/docs/quickstart');
    expect(searchDocumentation('/workspace-assets').some(result => result.kind === 'operation')).toBe(true);
  });
});
