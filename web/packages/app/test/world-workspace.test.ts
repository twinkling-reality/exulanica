// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildWorldWorkspace } from '../src/ui/world-workspace.js';

const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).forEach(dispose => dispose()); document.body.replaceChildren(); });
function mount() {
  const root = document.createElement('aside');
  const node = () => document.createElement('div');
  const camera = document.createElement('button');
  const action = vi.fn(); camera.addEventListener('click', action);
  const view = buildWorldWorkspace({ root, title: node(), fixture: node(), source: node(), selected: node(), reason: node(), inspector: node(), inhabitants: node(), camera: [camera], tools: [], authoring: node() });
  document.body.append(root); cleanups.push(view.dispose);
  return { view, root, camera, action };
}
describe('world workspace interaction ownership', () => {
  it('opens one panel, closes with Escape, restores focus and preserves camera actions', () => {
    const { root, camera, action } = mount();
    const nearby = root.querySelector<HTMLButtonElement>('[aria-controls=world-panel-nearby]')!;
    nearby.click();
    expect(root.querySelector<HTMLElement>('#world-panel-nearby')!.hidden).toBe(false);
    root.querySelector<HTMLButtonElement>('[aria-controls=world-panel-details]')!.click();
    expect(root.querySelector<HTMLElement>('#world-panel-nearby')!.hidden).toBe(true);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }));
    expect(root.querySelector<HTMLElement>('#world-panel-details')!.hidden).toBe(true);
    expect(document.activeElement?.getAttribute('aria-controls')).toBe('world-panel-details');
    camera.click(); expect(action).toHaveBeenCalledOnce();
  });
  it('focuses inspection and releases its listener on disposal', () => {
    const { root, view } = mount();
    view.inspect();
    expect(document.activeElement?.getAttribute('aria-label')).toBe('Close selected in the world');
    view.close();
    expect(document.activeElement?.getAttribute('aria-controls')).toBe('world-panel-nearby');
    view.inspect(); view.dispose();
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }));
    expect(root.querySelector<HTMLElement>('#world-panel-inspection')!.hidden).toBe(false);
  });

  it('starts the place banner only after the welcome is addressed', () => {
    const { root, view } = mount();
    const arrival = root.querySelector<HTMLElement>('.world-arrival')!;
    view.setPlace('Flatiron and Madison Square');
    expect(arrival.hasAttribute('data-shown')).toBe(false);

    view.setWelcomeVisible(false);
    expect(arrival.hasAttribute('data-shown')).toBe(true);
    expect(arrival.textContent).toContain('Flatiron and Madison Square');

    view.setWelcomeVisible(true);
    expect(arrival.hasAttribute('data-shown')).toBe(false);
  });

  it('waits for first-use guidance to finish, then names the place once', () => {
    const shell = document.createElement('div');
    shell.id = 'shell';
    shell.dataset['firstUse'] = 'new';
    document.body.append(shell);
    const root = document.createElement('aside');
    shell.append(root);
    const node = () => document.createElement('div');
    const view = buildWorldWorkspace({ root, title: node(), fixture: node(), source: node(), selected: node(), reason: node(), inspector: node(), inhabitants: node(), camera: [], tools: [], authoring: node() });
    cleanups.push(view.dispose);
    const arrival = root.querySelector<HTMLElement>('.world-arrival')!;

    // Guidance is on the screen, so the title does not animate underneath it.
    view.setPlace('My world');
    view.setWelcomeVisible(false);
    expect(arrival.hasAttribute('data-shown')).toBe(false);

    // The host reflects every phase change, and by then the guidance has nothing on the screen.
    shell.dataset['firstUse'] = 'done';
    view.setWelcomeVisible(false);
    expect(arrival.hasAttribute('data-shown')).toBe(true);

    // Once, not on every reflection afterwards.
    arrival.removeAttribute('data-shown');
    view.setWelcomeVisible(false);
    expect(arrival.hasAttribute('data-shown')).toBe(false);
  });
});
