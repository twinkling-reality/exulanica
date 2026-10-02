// @vitest-environment happy-dom
import { ApiError } from '@exulanica/graph-client';
import { describe, expect, it, vi } from 'vitest';

import { parseWorkspaceCreation, parseWorldCapabilities, type OperationDescriptors, type WorldCapabilities } from '../src/capabilities-api.js';
import { ACTIONS, actionSpec } from '../src/ui/actions/registry.js';
import { buildPalette, buildRail, perform, type ActionBinding, type ActionHost } from '../src/ui/actions/surfaces.js';
import { toastStack } from '../src/ui/system/components.js';
import { commandForKeystroke } from '../src/world-shell.js';

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

function capabilities(states: Readonly<Record<string, [string, string | null, boolean?]>>): WorldCapabilities {
  return parseWorldCapabilities({
    profile: 'exulanica.world-capabilities/v1', world_id: 'world:test', version_id: 'v1', kind: 'authored-starter',
    society: { held: true, engine: 'exulanica-society/v2' },
    operations: Object.entries(states).map(([operation, [state, code, permitted]]) => ({
      operation, bind: { version_id: 'v1' }, permitted: permitted ?? true, state, code, spends: false, writes: true,
      effects: [], dependencies: [], preview: null,
    })),
  });
}

function host(bindings: Record<string, ActionBinding>, read: OperationDescriptors | null): ActionHost & { emit(): void } {
  const listeners = new Set<() => void>();
  return {
    binding: (id) => bindings[id],
    capabilities: () => read,
    onChange: (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
    toasts: toastStack(),
    emit: () => { for (const listener of listeners) listener(); },
  };
}

describe('making a world', () => {
  const creation = (state: string, code: string | null) => parseWorkspaceCreation({
    profile: 'exulanica.world-creation/v1',
    kinds: [{ kind: 'generated', held: 0, limit: 3, create: {
      operation: 'POST /worlds/generated', bind: {}, permitted: true, state, code, spends: false, writes: true,
      effects: [], dependencies: [], preview: null,
    } }],
  });

  it('never opens where the workspace refuses it, and says why in its words', async () => {
    const run = vi.fn();
    const refused = host({ 'world.make': { run } }, creation('unavailable', 'worlds_read_only'));
    await perform(refused, 'world.make');
    expect(run).not.toHaveBeenCalled();
    expect(refused.toasts.root.textContent).toContain('This server does not make new worlds.');
    const open = host({ 'world.make': { run } }, creation('available', null));
    await perform(open, 'world.make');
    expect(run).toHaveBeenCalledOnce();
  });
});

describe('the tool rail', () => {
  it('draws the registry’s rail entries that have a binding, grouped, and marks the open one', () => {
    let open = false;
    const rail = buildRail(host({
      'people.open': { run: () => { open = !open; }, active: () => open },
      'map.open': { run: () => undefined },
    }, null));
    const items = [...rail.root.querySelectorAll<HTMLButtonElement>('.x-rail-item')];
    expect(items.map((item) => item.dataset['action'])).toEqual(['people.open', 'map.open']);
    expect(items[0]!.getAttribute('aria-pressed')).toBe('false');
    expect(rail.root.querySelector('.x-rail-group-label')?.textContent).toBe('People');
  });

  it('leaves out an action the world never supports, and disables one it refuses now', () => {
    const undo = actionSpec('objects.undo').operation!;
    const shown = buildRail(host({ 'objects.undo': { run: () => undefined } }, capabilities({ [undo]: ['unavailable', 'x'] })));
    const control = shown.root.querySelector<HTMLButtonElement>('[data-action="objects.undo"]')!;
    expect(control.disabled).toBe(true);
    expect(control.dataset['state']).toBe('unavailable');
    const hidden = buildRail(host({ 'objects.undo': { run: () => undefined } }, capabilities({ [undo]: ['unsupported', 'x'] })));
    expect(hidden.root.querySelector('[data-action="objects.undo"]')).toBeNull();
  });
});

describe('running an action', () => {
  const advance = actionSpec('clock.advance');

  it('does not run an action the world refuses, and says why in the action’s words', async () => {
    const run = vi.fn();
    const surface = host({ 'clock.advance': { run } }, capabilities({ [advance.operation!]: ['unavailable', 'society_unavailable'] }));
    await perform(surface, 'clock.advance');
    expect(run).not.toHaveBeenCalled();
    expect(surface.toasts.root.textContent).toContain('Nobody lives in this world yet.');
  });

  it('does not run an action whose own precondition holds it back, and says the precondition', async () => {
    const run = vi.fn();
    const surface = host({ 'clock.advance': { run, blocked: () => 'Pause the simulation to advance one minute by hand.' } },
      capabilities({ [advance.operation!]: ['available', null] }));
    await perform(surface, 'clock.advance');
    expect(run).not.toHaveBeenCalled();
    expect(surface.toasts.root.textContent).toContain('Pause the simulation');
  });

  it('shows a refusal it meets as words, with the code only in the technical record', async () => {
    const surface = host({
      'clock.advance': { run: () => Promise.reject(new ApiError(409, 'invalid_society_control', 'tick 3 is not the current tick')) },
    }, capabilities({ [advance.operation!]: ['available', null] }));
    const control = document.createElement('button');
    await perform(surface, 'clock.advance', control);
    const toast = surface.toasts.root.querySelector('.x-toast')!;
    expect(toast.querySelector('.x-toast-message')?.textContent).toBe(
      'The world’s clock did not change. Look at People for what the world is doing now, then try again.');
    expect(toast.querySelector('.x-toast-message')?.textContent).not.toContain('invalid_society_control');
    expect(toast.querySelector('details.x-technical')?.textContent).toContain('code: invalid_society_control');
    expect(control.disabled).toBe(false);
  });
});

describe('the command palette', () => {
  it('finds actions by their words, lists refused ones with why, and runs the chosen one', async () => {
    const run = vi.fn();
    const surface = host({
      'map.open': { run },
      'clock.advance': { run: vi.fn() },
    }, capabilities({ [actionSpec('clock.advance').operation!]: ['unavailable', 'society_unavailable'] }));
    const palette = buildPalette(surface);
    document.body.append(palette.root);
    palette.open();
    const rows = () => [...palette.root.querySelectorAll<HTMLElement>('.x-palette-row')];
    expect(rows().map((row) => row.dataset['action'])).toEqual(['clock.advance', 'map.open']);
    expect(rows()[0]!.getAttribute('aria-disabled')).toBe('true');
    expect(rows()[0]!.textContent).toContain('Nobody lives in this world yet.');
    const input = palette.root.querySelector<HTMLInputElement>('input')!;
    input.value = 'from above';
    input.dispatchEvent(new Event('input'));
    expect(rows().map((row) => row.dataset['action'])).toEqual(['map.open']);
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await tick();
    expect(run).toHaveBeenCalledOnce();
    expect(palette.isOpen()).toBe(false);
    palette.root.remove();
  });
});

describe('one key for one action', () => {
  it('the registry’s shortcuts are the keys the shell answers', () => {
    const shellKeys: Record<string, string> = { H: 'toggle-menu', K: 'toggle-character', I: 'toggle-index', M: 'toggle-map', O: 'toggle-options' };
    for (const spec of ACTIONS) {
      const key = spec.shortcut;
      if (key === undefined || !(key in shellKeys)) continue;
      expect(commandForKeystroke({ code: `Key${key}`, key: key.toLowerCase(), modified: false, typing: false }), spec.id)
        .toBe(shellKeys[key]);
    }
    expect(commandForKeystroke({ code: 'Slash', key: '?', modified: false, typing: false })).toBe('toggle-controls');
    expect(actionSpec('settings.open').shortcut).toBe('?');
  });
});
