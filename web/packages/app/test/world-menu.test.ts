// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { buildWorldMenu } from '../src/ui/world-menu.js';

describe('World menu', () => {
  it('provides one clickable index while preserving direct command meanings', () => {
    const onResume = vi.fn();
    const onCommand = vi.fn();
    const onWorld = vi.fn();
    const onExperiment = vi.fn();
    const menu = buildWorldMenu({ preview: true, onResume, onWorld, onExperiment, onCommand });
    document.body.append(menu.root);
    menu.setVisible(true);

    expect(menu.root.textContent).toContain('Development preview');
    expect(document.activeElement?.textContent).toContain('Place & view');
    menu.root.dispatchEvent(new KeyboardEvent('keydown', { code: 'ArrowRight', bubbles: true }));
    expect(document.activeElement?.textContent).toContain('Character');
    menu.root.querySelector<HTMLButtonElement>('[data-command=world]')!.click();
    expect(onWorld).toHaveBeenCalledOnce();
    menu.root.querySelector<HTMLButtonElement>('[data-command=character]')!.click();
    menu.root.querySelector<HTMLButtonElement>('[data-command=experiment]')!.click();
    menu.root.querySelector<HTMLButtonElement>('[data-command=controls]')!.click();
    menu.root.querySelector<HTMLButtonElement>('.world-menu-rail-action')!.click();

    expect(onCommand).toHaveBeenNthCalledWith(1, 'character');
    expect(onCommand).toHaveBeenNthCalledWith(2, 'controls');
    expect(onExperiment).toHaveBeenCalledOnce();
    expect(onResume).toHaveBeenCalledOnce();
  });

  it('does not offer recorded results without an active saved-world binding', () => {
    const menu = buildWorldMenu({
      preview: true,
      onResume: vi.fn(),
      onWorld: vi.fn(),
      onCommand: vi.fn(),
    });
    expect(menu.root.querySelector('[data-command=experiment]')).toBeNull();
    expect(menu.root.querySelector('[data-command=compare]')).toBeNull();
  });

  it('opens the comparisons of the models that ran the open world', () => {
    const onCompare = vi.fn();
    const menu = buildWorldMenu({
      preview: false, onResume: vi.fn(), onWorld: vi.fn(), onCompare, onCommand: vi.fn(),
    });
    const entry = menu.root.querySelector<HTMLButtonElement>('[data-command=compare]')!;
    expect(entry.textContent).toContain('Compare models');
    entry.click();
    expect(onCompare).toHaveBeenCalledOnce();
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
