// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import { createLayout, REGION_NAMES } from '../src/ui/system/layout.js';

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

function surface(hidden = true): HTMLElement {
  const node = document.createElement('section');
  node.hidden = hidden;
  return node;
}

describe('layout regions', () => {
  it('creates every named region once', () => {
    const shell = document.createElement('div');
    const layout = createLayout(shell);
    expect(Object.keys(layout.regions).sort()).toEqual([...REGION_NAMES].sort());
    for (const name of REGION_NAMES) expect(layout.regions[name].dataset['region']).toBe(name);
  });

  it('keeps the inspector to one visible panel, closing the earlier one through its own handler', async () => {
    const shell = document.createElement('div');
    document.body.append(shell);
    const layout = createLayout(shell);
    const objects = surface();
    const people = surface();
    const closed: string[] = [];
    layout.place('inspector', objects, { close: () => { closed.push('objects'); objects.hidden = true; } });
    layout.place('inspector', people, { close: () => { closed.push('people'); people.hidden = true; } });

    objects.hidden = false;
    await tick();
    expect(layout.visible('inspector')).toEqual([objects]);
    expect(shell.hasAttribute('data-inspector-open')).toBe(true);

    people.hidden = false;
    await tick();
    expect(closed).toEqual(['objects']);
    expect(layout.visible('inspector')).toEqual([people]);

    people.hidden = true;
    await tick();
    expect(layout.visible('inspector')).toEqual([]);
    expect(shell.hasAttribute('data-inspector-open')).toBe(false);
    layout.dispose();
    shell.remove();
  });

  it('never closes an attachment and does not count it as an open panel', async () => {
    const shell = document.createElement('div');
    document.body.append(shell);
    const layout = createLayout(shell);
    const tabs = surface(false);
    const panel = surface();
    layout.place('inspector', tabs, { attachment: true, close: () => { throw new Error('closed an attachment'); } });
    layout.place('inspector', panel);
    expect(shell.hasAttribute('data-inspector-open')).toBe(false);
    panel.hidden = false;
    await tick();
    expect(tabs.hidden).toBe(false);
    expect(shell.hasAttribute('data-inspector-open')).toBe(true);
    layout.dispose();
    shell.remove();
  });

  it('a sheet is exclusive in its own region and leaves the inspector panel open under it', async () => {
    const shell = document.createElement('div');
    document.body.append(shell);
    const layout = createLayout(shell);
    const panel = surface(false);
    const first = surface();
    const second = surface();
    layout.place('inspector', panel);
    layout.place('sheet', first);
    layout.place('sheet', second);
    first.hidden = false;
    await tick();
    second.hidden = false;
    await tick();
    expect(first.hidden).toBe(true);
    expect(layout.visible('sheet')).toEqual([second]);
    expect(layout.visible('inspector')).toEqual([panel]);
    layout.dispose();
    shell.remove();
  });

  it('routes a surface other code appends to the shell into its region', async () => {
    const shell = document.createElement('div');
    document.body.append(shell);
    const layout = createLayout(shell);
    shell.append(...Object.values(layout.regions));
    layout.adopt('.world-traffic-note', 'hud');
    const note = document.createElement('p');
    note.className = 'world-traffic-note';
    shell.append(note);
    await tick();
    expect(note.parentElement).toBe(layout.regions.hud);
    layout.dispose();
    shell.remove();
  });
});
