// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { REGISTRY, SETTING_WORDS, type InteractionCapability } from '../src/interaction-settings.js';
import { DEFAULT_PREFERENCES } from '../src/preferences.js';
import { buildControlsGuide } from '../src/ui/controls-guide.js';
import { buildOptions } from '../src/ui/options.js';
import { DEVICE_SETTING_WORDS } from '../src/ui/setting-controls.js';

/**
 * The Settings overlay offers the settings the server serves and nothing else, drawn by the same
 * control as Customize: a setting the registry hides (the transition style) is offered by neither,
 * and the device's own settings read the same words on both surfaces.
 */

const guide = () => buildControlsGuide({
  preferences: DEFAULT_PREFERENCES, onChange: vi.fn(), onClose: vi.fn(), onShowCustomize: vi.fn(),
});
const customize = () => buildOptions({
  preferences: DEFAULT_PREFERENCES, onChange: vi.fn(), onClose: vi.fn(), onShowControls: vi.fn(),
});

/** The labels of every served setting a surface draws, by the registry's own words. */
function servedLabels(root: HTMLElement): string[] {
  const words = new Set(Object.values(SETTING_WORDS).map((setting) => setting.label));
  return [...root.querySelectorAll('[aria-label]')]
    .map((node) => node.getAttribute('aria-label')!)
    .filter((label) => words.has(label));
}

const served: readonly InteractionCapability[] = [...REGISTRY.values()];
const shown = served.filter((capability) => capability.shownInSettings);
const hidden = served.filter((capability) => !capability.shownInSettings);

describe('the Settings overlay draws the served settings', () => {
  beforeEach(() => document.body.replaceChildren());

  it('offers exactly the settings the registry shows, as Customize does', () => {
    // A positive control: the registry shows some settings and hides some, the transition style
    // among the hidden, so both halves below can fail.
    expect(shown.length).toBeGreaterThan(0);
    expect(hidden.map((capability) => capability.key)).toContain('navigation.transition-style');

    const overlay = guide();
    overlay.showSettings(served);
    const options = customize();
    options.showSettings(served);
    const expected = shown.map((capability) => SETTING_WORDS[capability.key]!.label);
    expect(servedLabels(overlay.root)).toEqual(expected);
    expect(servedLabels(options.root)).toEqual(expected);
    for (const capability of hidden) {
      expect(overlay.root.querySelector(`[aria-label="${SETTING_WORDS[capability.key]!.label}"]`)).toBeNull();
    }
    expect(overlay.root.textContent).not.toContain('Interface motion');
    expect(overlay.root.textContent).not.toContain('Full motion');
  });

  it('draws a setting the served catalog shows, and none before it arrives', () => {
    const overlay = guide();
    expect(servedLabels(overlay.root)).toEqual([]);
    const shownAll = served.map((capability) => ({ ...capability, shownInSettings: true }));
    overlay.showSettings(shownAll);
    expect(overlay.root.querySelector('[aria-label="Transitions"]')).not.toBeNull();
    overlay.settingsUnavailable('the request failed.');
    expect(servedLabels(overlay.root)).toEqual([]);
    expect(overlay.root.textContent).toContain('could not be read: the request failed.');
  });

  it('words the device settings from one table on both surfaces', () => {
    const overlay = guide();
    const options = customize();
    for (const key of ['contrast', 'transparency'] as const) {
      const words = DEVICE_SETTING_WORDS[key];
      for (const root of [overlay.root, options.root]) {
        const select = root.querySelector<HTMLSelectElement>(`select[aria-label="${words.label}"]`)!;
        expect([...select.options].map((option) => [option.value, option.text]))
          .toEqual(Object.entries(words.choices));
        expect(root.textContent).toContain(words.note);
      }
    }
  });
});
