// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { REGISTRY } from '../src/interaction-settings.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import { buildControlsGuide } from '../src/ui/controls-guide.js';

describe('Settings', () => {
  beforeEach(() => {
    document.body.replaceChildren();
  });

  it('uses dedicated categories and only emits implemented preferences', () => {
    const onChange = vi.fn();
    const view = buildControlsGuide({
      preferences: DEFAULT_PREFERENCES,
      onChange,
      onClose: vi.fn(),
      onShowCustomize: vi.fn(),
    });
    view.showSettings([...REGISTRY.values()]);
    document.body.append(view.root);

    expect(view.root.textContent).toContain('Display & accessibility');
    expect(view.root.textContent).toContain('Movement');
    expect(view.root.textContent).toContain('Controls');
    expect(view.root.textContent).not.toContain('Key mapping');

    const contrast = view.root.querySelector<HTMLSelectElement>('[aria-label="Contrast"]')!;
    contrast.value = 'high';
    contrast.dispatchEvent(new Event('change'));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ contrast: 'high' }));

    view.showSection('movement');
    const fieldOfView = view.root.querySelector<HTMLInputElement>('[aria-label="Field of view"]')!;
    fieldOfView.value = '82';
    fieldOfView.dispatchEvent(new Event('input'));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ fieldOfView: 82 }));

    view.showSection('controls');
    expect(view.root.textContent).toContain('Open Index');
    expect(view.root.querySelector<HTMLButtonElement>('.settings-reset')?.hidden).toBe(true);
  });

  it('resets only the active category', () => {
    const onChange = vi.fn();
    const view = buildControlsGuide({
      preferences: {
        ...DEFAULT_PREFERENCES,
        contrast: 'high',
        fieldOfView: 84,
      },
      onChange,
      onClose: vi.fn(),
      onShowCustomize: vi.fn(),
    });
    view.showSettings([...REGISTRY.values()]);
    document.body.append(view.root);

    view.root.querySelector<HTMLButtonElement>('.settings-reset')!.click();
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      contrast: DEFAULT_PREFERENCES.contrast,
      fieldOfView: 84,
    }));

    view.showSection('movement');
    view.root.querySelector<HTMLButtonElement>('.settings-reset')!.click();
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      fieldOfView: DEFAULT_PREFERENCES.fieldOfView,
    }));
  });
});
