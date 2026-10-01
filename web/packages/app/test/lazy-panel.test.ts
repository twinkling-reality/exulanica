// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { lazyPanel, type PanelSurface } from '../src/composition/lazy-panel.js';

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

function surface(): PanelSurface & { shown: boolean[] } {
  const shown: boolean[] = [];
  return { root: document.createElement('aside'), shown, setVisible: (next) => { shown.push(next); }, dispose: vi.fn() };
}

describe('a panel that loads when first opened', () => {
  it('loads nothing until opened, says it is opening, then puts the surface in the stand-in’s place', async () => {
    const loaded = surface();
    const load = vi.fn(() => Promise.resolve(loaded));
    const panel = lazyPanel('Compare', load);
    document.body.append(panel.root);
    panel.setVisible(false);
    expect(load).not.toHaveBeenCalled();
    panel.setVisible(true);
    expect(load).toHaveBeenCalledOnce();
    expect(document.body.querySelector('.lazy-panel [role="status"]')?.textContent).toBe('Opening Compare.');
    await tick();
    expect(panel.root).toBe(loaded.root);
    expect(loaded.root.isConnected).toBe(true);
    expect(document.body.querySelector('.lazy-panel')).toBeNull();
    expect(loaded.shown).toEqual([true]);
    panel.setVisible(false);
    expect(loaded.shown).toEqual([true, false]);
    loaded.root.remove();
  });

  it('leaves a surface closed when it was closed while loading, and disposes one that arrives after dispose', async () => {
    const closed = surface();
    const first = lazyPanel('Compare', () => Promise.resolve(closed));
    first.setVisible(true);
    first.setVisible(false);
    await tick();
    expect(closed.shown).toEqual([]);

    const late = surface();
    const second = lazyPanel('Compare', () => Promise.resolve(late));
    second.setVisible(true);
    second.dispose();
    await tick();
    expect(late.dispose).toHaveBeenCalledOnce();
    expect(late.shown).toEqual([]);
  });

  it('says a failed load in words, keeps the error for the technical record, and tries again on request', async () => {
    const loaded = surface();
    const load = vi.fn()
      .mockImplementationOnce(() => Promise.reject(new Error('Failed to fetch dynamically imported module')))
      .mockImplementationOnce(() => Promise.resolve(loaded));
    const panel = lazyPanel('Compare', load);
    document.body.append(panel.root);
    panel.setVisible(true);
    await tick();
    const error = document.body.querySelector('.lazy-panel .x-error')!;
    expect(error.querySelector('.x-error-title')?.textContent).toBe('Compare did not open.');
    expect(error.querySelector('.x-error-next')?.textContent).toBe('Check the connection, then try again.');
    expect(error.querySelector('details.x-technical')?.textContent).toContain('Failed to fetch');
    error.querySelector<HTMLButtonElement>('button.x-btn')!.click();
    await tick();
    expect(load).toHaveBeenCalledTimes(2);
    expect(panel.root).toBe(loaded.root);
    expect(loaded.shown).toEqual([true]);
    loaded.root.remove();
  });
});
