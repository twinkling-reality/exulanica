// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { buildWorldMenu } from '../src/ui/world-menu.js';

describe('World menu', () => {
  it('provides one clickable index while preserving direct command meanings', () => {
    const onResume = vi.fn();
    const onCommand = vi.fn();
    const onWorld = vi.fn();
    const menu = buildWorldMenu({ preview: true, onResume, onWorld, onCommand });
    document.body.append(menu.root);
    menu.setVisible(true);

    expect(menu.root.textContent).toContain('Development preview');
    expect(document.activeElement?.textContent).toContain('World');
    menu.root.dispatchEvent(new KeyboardEvent('keydown', { code: 'ArrowRight', bubbles: true }));
    expect(document.activeElement?.textContent).toContain('Character');
    menu.root.querySelector<HTMLButtonElement>('[data-command=world]')!.click();
    expect(onWorld).toHaveBeenCalledOnce();
    menu.root.querySelector<HTMLButtonElement>('[data-command=character]')!.click();
    menu.root.querySelector<HTMLButtonElement>('[data-command=controls]')!.click();
    menu.root.querySelector<HTMLButtonElement>('.world-menu-rail-action')!.click();

    expect(onCommand).toHaveBeenNthCalledWith(1, 'character');
    expect(onCommand).toHaveBeenNthCalledWith(2, 'controls');
    expect(onResume).toHaveBeenCalledOnce();
  });

  it('does not offer comparison without an active saved-world binding', () => {
    const menu = buildWorldMenu({
      preview: true,
      onResume: vi.fn(),
      onWorld: vi.fn(),
      onCommand: vi.fn(),
    });
    expect(menu.root.querySelector('[data-command=compare]')).toBeNull();
  });

  it('opens the comparisons of the models that ran the open world', () => {
    const onCompare = vi.fn();
    const menu = buildWorldMenu({
      preview: false, onResume: vi.fn(), onWorld: vi.fn(), onCompare, onCommand: vi.fn(),
    });
    const entry = menu.root.querySelector<HTMLButtonElement>('[data-command=compare]')!;
    expect(entry.querySelector('.world-menu-entry-label')?.textContent).toBe('Compare');
    expect(entry.getAttribute('aria-label')).toBe('Compare models');
    entry.click();
    expect(onCompare).toHaveBeenCalledOnce();
  });

  it('names and opens the recipe action as making a world', () => {
    const onMakeWorld = vi.fn();
    const menu = buildWorldMenu({
      preview: false, onResume: vi.fn(), onWorld: vi.fn(), onMakeWorld,
      onCommand: vi.fn(),
    });
    const make = menu.root.querySelector<HTMLButtonElement>('[data-command=make]')!;
    expect(make.querySelector('.world-menu-entry-label')?.textContent).toBe('Create');
    expect(make.querySelector('.world-menu-entry-detail')?.textContent).toBe('Make a world');
    expect(make.getAttribute('aria-label')).toBe('Make a world');
    make.click();
    expect(onMakeWorld).toHaveBeenCalledOnce();
  });

  it('keeps the short menu titles distinct and names each action', () => {
    const menu = buildWorldMenu({
      preview: false, onResume: vi.fn(), onWorld: vi.fn(),
      onCompare: vi.fn(), onMakeWorld: vi.fn(), onCommand: vi.fn(),
    });
    const labels = [...menu.root.querySelectorAll('.world-menu-entry-label')]
      .map((node) => node.textContent);
    expect(labels).toEqual([
      'World', 'Character', 'Library', 'Map', 'Compare', 'Companion', 'Create',
      'Design', 'Settings',
    ]);
    expect(menu.root.querySelector('[data-command=experiment]')).toBeNull();
    expect(menu.root.querySelector('[data-command=options]')?.getAttribute('aria-label'))
      .toBe('Customize world');
    expect([...menu.root.querySelectorAll('.world-menu-entry:has(svg)')]
      .map((node) => node.getAttribute('data-command'))).toEqual([
      'character', 'index', 'map', 'companion', 'options', 'controls',
    ]);
    expect(menu.root.querySelectorAll('.world-menu-entry svg[aria-hidden=true]')).toHaveLength(6);
    expect(menu.root.textContent).toContain('ArrowsMove');
    expect(menu.root.textContent).toContain('EnterOpen');
  });

  it('moves focus through the visible mosaic rather than four fixed list positions', () => {
    const menu = buildWorldMenu({
      preview: false, onResume: vi.fn(), onWorld: vi.fn(),
      onCompare: vi.fn(), onMakeWorld: vi.fn(), onCommand: vi.fn(),
    });
    document.body.append(menu.root);
    const entries = [...menu.root.querySelectorAll<HTMLButtonElement>('.world-menu-entry')];
    const boxes = [
      [0, 0, 200, 200], [200, 0, 400, 100], [200, 100, 300, 200],
      [300, 100, 400, 200], [0, 200, 200, 300], [200, 200, 400, 300],
      [0, 300, 100, 400], [100, 300, 200, 400], [200, 300, 400, 400],
    ];
    entries.forEach((entry, index) => {
      const [left, top, right, bottom] = boxes[index]!;
      vi.spyOn(entry, 'getBoundingClientRect').mockReturnValue({
        left, top, right, bottom, width: right! - left!, height: bottom! - top!,
      } as DOMRect);
    });
    menu.setVisible(true);
    const move = (code: string) => menu.root.dispatchEvent(new KeyboardEvent('keydown', {
      code, bubbles: true,
    }));
    move('ArrowRight');
    expect(document.activeElement).toBe(entries[1]);
    move('ArrowDown');
    expect(document.activeElement).toBe(entries[2]);
    move('ArrowLeft');
    expect(document.activeElement).toBe(entries[0]);
    move('ArrowDown');
    expect(document.activeElement).toBe(entries[4]);
    move('ArrowUp');
    expect(document.activeElement).toBe(entries[0]);
    entries[4]!.focus();
    move('ArrowRight');
    expect(document.activeElement).toBe(entries[5]);
    move('ArrowDown');
    expect(document.activeElement).toBe(entries[8]);
  });

  it('is hidden and inert outside the menu state', () => {
    const opener = document.createElement('button');
    document.body.append(opener);
    opener.focus();
    const onResume = vi.fn();
    const menu = buildWorldMenu({
      preview: false,
      onResume,
      onWorld: vi.fn(),
      onCommand: vi.fn(),
    });
    document.body.append(menu.root);
    menu.setVisible(true);
    menu.root.dispatchEvent(new KeyboardEvent('keydown', { code: 'Escape', bubbles: true }));
    expect(onResume).toHaveBeenCalledOnce();
    menu.setVisible(false);
    expect(menu.root.hidden).toBe(true);
    expect(document.activeElement).toBe(opener);
  });
});
