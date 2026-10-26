// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildWorldShowcase, WORLD_SCENES } from '../src/ui/world-showcase.js';
import { ORBIT_COUNT } from '../src/ui/world-orbit-geometry.js';
import { retiredWorldDestination } from '../src/ui/world-scenes.js';

afterEach(() => { document.body.replaceChildren(); vi.useRealTimers(); vi.restoreAllMocks(); });
function fixture(atlasHref: string | null = null, portals = false) {
  const root = buildWorldShowcase({ portals, atlasHref });
  document.body.append(root);
  return { root, choices: WORLD_SCENES.map(scene => root.querySelector<HTMLButtonElement>(`#${portals ? 'home' : 'worlds'}-${scene.id}`)!), panel: root.querySelector<HTMLElement>('.world-context')! };
}
describe('contextual world previews', () => {
  it('reserves preview controls for real captures and keeps gradient forms decorative', () => {
    const { root, choices } = fixture(null, true);
    expect(choices).toHaveLength(WORLD_SCENES.length);
    expect(root.querySelectorAll('.orbit-item')).toHaveLength(ORBIT_COUNT);
    const decorative = [...root.querySelectorAll<HTMLElement>('.field-form')];
    expect(decorative.every(form => form.getAttribute('aria-hidden') === 'true' && !form.hasAttribute('tabindex'))).toBe(true);
    expect(new Set(decorative.map(form => form.style.getPropertyValue('--material'))).size).toBe(decorative.length);
    expect(root.querySelectorAll('.field-capture')).toHaveLength(WORLD_SCENES.length);
  });
  it('retains selected identity in its destination and restores focus on Escape', () => {
    const { root, choices, panel } = fixture();
    choices[0]!.focus();
    expect(panel.hidden).toBe(false);
    expect(root.dataset.selected).toBe('0');
    expect(panel.querySelector('a')?.getAttribute('href')).toBe('/docs/self-hosting');
    panel.querySelector('a')!.focus();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(panel.hidden).toBe(true);
    expect(document.activeElement).toBe(choices[0]);
    expect(root.dataset.selected).toBeUndefined();
    // Removing an overlapping panel can expose the trigger to the stationary pointer.
    choices[0]!.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
    expect(panel.hidden).toBe(true);
    choices[0]!.dispatchEvent(new PointerEvent('pointerleave', { pointerType: 'mouse' }));
    choices[0]!.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
    expect(panel.hidden).toBe(false);
    choices[1]!.click();
    expect(panel.querySelector('h2')?.textContent).toBe(WORLD_SCENES[1]!.title);
    expect(panel.querySelector('a')?.getAttribute('href')).toBe('/docs/self-hosting');
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
  it('closes the preview once when its page becomes inert', async () => {
    const pane = document.createElement('section');
    document.body.append(pane);
    const root = buildWorldShowcase();
    pane.append(root);
    const panel = root.querySelector<HTMLElement>('.world-context')!;
    let notifications = 0;
    const observer = new MutationObserver(() => {
      notifications += 1;
      if (notifications > 20) throw new Error('inert observer did not settle');
    });
    observer.observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ['inert'] });
    pane.inert = true;
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(panel.hidden).toBe(true);
    expect(panel.inert).toBe(true);
    expect(notifications).toBeLessThan(5);
    observer.disconnect();
  });
  it('leaves a usable destination when the capture fails', () => {
    const { choices, panel } = fixture();
    choices[0]!.click();
    choices[0]!.querySelector('img')!.dispatchEvent(new Event('error'));
    expect(panel.querySelector('h2')?.textContent).toBe(WORLD_SCENES[0]!.title);
    expect(panel.querySelector('a')?.getAttribute('href')).toBe('/docs/self-hosting');
  });
  it('hands every configuration straight to the app with their recipe, and every showcase world by its key, preserving deployment parameters', () => {
    const { choices, panel } = fixture('https://atlas.example/session?tenant=one#worlds');
    for (const [index, scene] of WORLD_SCENES.entries()) {
      choices[index]!.click();
      const href = panel.querySelector('a')!.href;
      const url = new URL(href);
      expect(url.pathname).toBe('/session');
      expect(url.searchParams.get('tenant')).toBe('one');
      expect(url.hash).toBe('#worlds');
      if (scene.world) {
        // A made world opens as the visitor's own copy, by its key alone: no configuration rides along.
        expect(url.searchParams.get('world')).toBe(scene.world);
        expect(panel.querySelector('a')!.textContent).toBe('Open this world');
        expect(url.searchParams.has('recipe')).toBe(false);
        continue;
      }
      expect(url.searchParams.get('recipe')).toBe(scene.recipe);
      expect(JSON.parse(url.searchParams.get('values')!)).toEqual(scene.values);
      expect(JSON.parse(url.searchParams.get('style_pack')!)).toEqual(scene.stylePack);
      expect(url.hash).toBe('#worlds');
      expect(retiredWorldDestination(`/worlds/${scene.id}`, 'https://atlas.example/session?tenant=one#worlds')).toBe(href);
      expect(retiredWorldDestination(`/worlds/${scene.id}/`, null)).toBe('/docs/self-hosting');
    }
    expect(retiredWorldDestination('/worlds/unknown', null)).toBeNull();
  });
  it('puts exploration on the orb and keeps the center copy free of action controls', () => {
    const { choices, panel } = fixture('https://atlas.example/session?tenant=one', true);
    for (const [index, scene] of WORLD_SCENES.entries()) {
      const orb = choices[index]!;
      expect(orb.tagName).toBe('A');
      const opens = new URL(orb.getAttribute('href')!).searchParams;
      expect(scene.world ? opens.get('world') : opens.get('recipe')).toBe(scene.world ?? scene.recipe);
      orb.focus();
      expect(panel.querySelector('h2')?.textContent).toBe(scene.name);
      expect(panel.querySelector('.preview-description')?.textContent).toBe('');
      expect(panel.querySelector<HTMLElement>('.preview-description')?.hidden).toBe(true);
      // A showcase world's orb opens the visitor's copy, and says so; a configuration's is explored.
      expect(panel.querySelector('.preview-invitation')?.textContent).toBe(scene.world ? 'Open this world' : 'Click to explore');
      expect(orb.getAttribute('aria-label')).toBe(`${scene.world ? 'Open' : 'Explore'} ${scene.title}`);
      expect(panel.querySelector('a,button')).toBeNull();
    }
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(panel.hidden).toBe(true);
    expect(document.activeElement).toBe(choices.at(-1));
  });
});
