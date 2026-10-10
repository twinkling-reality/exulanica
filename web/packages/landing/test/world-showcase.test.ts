// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildWorldShowcase, WORLD_SCENES } from '../src/ui/world-showcase.js';
import { retiredWorldDestination } from '../src/ui/world-scenes.js';

afterEach(() => { document.body.replaceChildren(); vi.useRealTimers(); vi.restoreAllMocks(); });
function fixture(atlasHref: string | null = null) {
  const root = buildWorldShowcase({ portals: true, atlasHref });
  document.body.append(root);
  return { root, choices: [...root.querySelectorAll<HTMLButtonElement>('.world-choice')], panel: root.querySelector<HTMLElement>('.world-context')! };
}
describe('contextual world previews', () => {
  it('retains selected identity in its destination and restores focus on Escape', () => {
    const { root, choices, panel } = fixture();
    choices[0]!.focus();
    expect(panel.hidden).toBe(false);
    expect(root.dataset.selected).toBe('0');
    expect(panel.querySelector('a')?.getAttribute('href')).toBe('/waitlist?world=market-town');
    panel.querySelector('a')!.focus();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(panel.hidden).toBe(true);
    expect(document.activeElement).toBe(choices[0]);
    expect(root.dataset.selected).toBeUndefined();
    choices[1]!.click();
    expect(panel.querySelector('h2')?.textContent).toBe('Small Town');
    expect(panel.querySelector('a')?.getAttribute('href')).toBe('/waitlist?world=small-town');
  });
  it('holds selection across the pointer gap, then dismisses when leaving an unpinned panel', () => {
    vi.useFakeTimers();
    const { choices, panel } = fixture();
    choices[0]!.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
    choices[0]!.dispatchEvent(new PointerEvent('pointerleave', { pointerType: 'mouse' }));
    vi.advanceTimersByTime(300);
    panel.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
    vi.advanceTimersByTime(600);
    expect(panel.hidden).toBe(false);
    panel.dispatchEvent(new PointerEvent('pointerleave', { pointerType: 'mouse' }));
    vi.advanceTimersByTime(500);
    expect(panel.hidden).toBe(true);
  });
  it('opens on touch activation, stays pinned and dismisses on an outside press', () => {
    vi.useFakeTimers();
    const { choices, panel } = fixture();
    choices[1]!.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'touch' }));
    expect(panel.hidden).toBe(true);
    choices[1]!.click();
    choices[1]!.dispatchEvent(new PointerEvent('pointerleave', { pointerType: 'touch' }));
    vi.advanceTimersByTime(1000);
    expect(panel.hidden).toBe(false);
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    expect(panel.hidden).toBe(true);
  });
  it('leaves a usable destination when the capture fails', () => {
    const { choices, panel } = fixture();
    choices[0]!.click();
    panel.querySelector('img')!.dispatchEvent(new Event('error'));
    expect(panel.textContent).toContain('Capture unavailable');
    expect(panel.querySelector('a')?.getAttribute('href')).toBe('/waitlist?world=market-town');
  });
  it('hands both previews straight to the app with their recipe, preserving deployment parameters', () => {
    const { choices, panel } = fixture('https://atlas.example/session?tenant=one#worlds');
    for (const [index, scene] of WORLD_SCENES.entries()) {
      choices[index]!.click();
      const href = panel.querySelector('a')!.href;
      const url = new URL(href);
      expect(url.pathname).toBe('/session');
      expect(url.searchParams.get('tenant')).toBe('one');
      expect(url.searchParams.get('recipe')).toBe(scene.recipe);
      expect(url.hash).toBe('#worlds');
      expect(retiredWorldDestination(`/worlds/${scene.id}`, 'https://atlas.example/session?tenant=one#worlds')).toBe(href);
      expect(retiredWorldDestination(`/worlds/${scene.id}/`, null)).toBe(`/waitlist?world=${scene.id}`);
    }
    expect(retiredWorldDestination('/worlds/unknown', null)).toBeNull();
  });
});
