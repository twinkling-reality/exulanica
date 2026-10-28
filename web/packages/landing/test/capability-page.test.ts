// @vitest-environment happy-dom
import { afterEach, expect, it } from 'vitest';
import { buildProductCapabilities } from '../src/ui/product.js';
import { PRODUCT_CAPABILITIES } from '../src/content/product.js';

afterEach(() => document.body.replaceChildren());

it('lists each capability as its own chapter with a stable address and a real guide', () => {
  const pane = buildProductCapabilities();
  document.body.append(pane);
  expect(pane.querySelector('h1')?.textContent).toBe('Capabilities');
  expect(pane.querySelector('[role="tablist"]')).toBeNull();
  for (const item of PRODUCT_CAPABILITIES) {
    const chapter = pane.querySelector(`#${item.id}`)!;
    expect(chapter.querySelector('h2')?.textContent).toBe(item.title);
    expect(chapter.querySelector('p')?.textContent).toBe(item.copy);
    expect(chapter.querySelector<HTMLAnchorElement>('a')?.getAttribute('href')).toBe(item.href);
  }
});
