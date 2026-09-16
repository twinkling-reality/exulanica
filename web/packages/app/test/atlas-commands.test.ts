// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { buildAtlasCommands } from '../src/ui/atlas-commands.js';

describe('Atlas command strip', () => {
  it('makes every system command clickable and reflects the active surface', () => {
    const onCommand = vi.fn();
    const view = buildAtlasCommands(onCommand);
    document.body.replaceChildren(view.root);
    const options = view.root.querySelector<HTMLButtonElement>('[data-command="options"]')!;
    options.click();
    expect(onCommand).toHaveBeenCalledWith('options');

    view.reflect('options', 'ground');
    expect(options.getAttribute('aria-current')).toBe('page');
    expect(view.root.querySelector('[data-command="map"]')?.hasAttribute('aria-current')).toBe(false);

    view.reflect('world', 'map');
    expect(view.root.querySelector('[data-command="map"]')?.getAttribute('aria-current')).toBe('page');
  });

  it('labels every destination and exposes Companion as a direct action', () => {
    const view = buildAtlasCommands(vi.fn());
    expect(view.root.querySelectorAll('button')).toHaveLength(6);
    expect(view.root.querySelectorAll('.atlas-command-tooltip')).toHaveLength(6);
    expect(view.root.querySelector('.atlas-command-guide')).toBeNull();
    expect(view.root.textContent).toContain('Library');
    expect(view.root.querySelectorAll('.atlas-command-label')).toHaveLength(6);
    expect(view.root.querySelector('[data-command=character]')?.getAttribute('aria-label')).toBe('Character (K)');
    expect(view.root.querySelector('[data-command=companion]')?.getAttribute('aria-label')).toBe('Companion (X)');
    expect(view.root.textContent).toContain('Customize');
    expect(view.root.textContent).toContain('Settings');
  });
});
