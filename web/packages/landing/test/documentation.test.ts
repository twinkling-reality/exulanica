// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildDocumentation } from '../src/ui/documentation.js';

afterEach(() => vi.restoreAllMocks());

describe('public documentation', () => {
  it.each(['index', 'world-api', 'agents'] as const)('provides navigable sections for %s', (kind) => {
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

  it('copies exactly the displayed example and confirms completion', async () => {
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    const page = buildDocumentation('index');
    page.querySelector<HTMLButtonElement>('.docs-copy')!.click();
    await Promise.resolve();
    expect(writeText).toHaveBeenCalledWith(page.querySelector('.docs-code pre code')!.textContent);
    expect(page.querySelector('[role="status"]')!.textContent).toBe('Copied');
  });

  it('offers a manual copy fallback if clipboard access fails', async () => {
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('Denied'));
    const page = buildDocumentation('agents');
    page.querySelector<HTMLButtonElement>('.docs-copy')!.click();
    await Promise.resolve();
    expect(page.querySelector('[role="status"]')!.textContent).toBe('Select the code to copy it.');
  });
});
