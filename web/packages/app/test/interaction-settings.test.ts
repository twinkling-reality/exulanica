// @vitest-environment happy-dom
// The settings page draws the reviewed interaction capabilities from the catalog the server serves,
// and restates none of them. What the page adds (each capability's preference field and words) is
// held here to the registry the server reads.
import { readFileSync } from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { preferencesFromInteractionPolicy } from '../src/interaction-policy.js';
import {
  PREFERENCE_BINDINGS,
  REGISTRY,
  SETTING_WORDS,
  preferenceValue,
  readCapabilities,
  type InteractionCapability,
} from '../src/interaction-settings.js';
import { DEFAULT_PREFERENCES, normalisePreferences } from '../src/preferences.js';
import { buildOptions } from '../src/ui/options.js';

/** The repository, from the web workspace vitest runs in, as the other page tests read it. */
const REGISTRY_FILE = `${process.cwd()}/../exulanica/world/interaction-policy-registry.v1.json`;
const stated = readCapabilities(JSON.parse(readFileSync(REGISTRY_FILE, 'utf8')));

function options() {
  const onChange = vi.fn();
  const view = buildOptions({
    preferences: DEFAULT_PREFERENCES, onChange, onPreview: vi.fn(), onClose: vi.fn(), onShowControls: vi.fn(),
  });
  document.body.append(view.root);
  return { view, onChange };
}

const labels = (root: HTMLElement): string[] =>
  [...root.querySelectorAll('.view-settings [aria-label]')].map((control) => control.getAttribute('aria-label')!);

describe('the settings the page offers', () => {
  beforeEach(() => document.body.replaceChildren());

  it('has a preference binding and words for exactly the capabilities the registry states', () => {
    const keys = stated.map((capability) => capability.key).sort();
    // A positive control: the reading found the registry's capabilities.
    expect(keys).toEqual(expect.arrayContaining(['comfort.vignette', 'disclosure.provenance-detail']));
    expect(Object.keys(PREFERENCE_BINDINGS).sort()).toEqual(keys);
    expect(Object.keys(SETTING_WORDS).sort()).toEqual(keys);
    for (const capability of stated.filter((each) => each.kind === 'choice')) {
      expect(Object.keys(SETTING_WORDS[capability.key]!.choices ?? {}).sort(), capability.key)
        .toEqual([...capability.choices].sort());
    }
  });

  it('holds each bound preference\'s default to the registry\'s', () => {
    for (const capability of stated) {
      const binding = PREFERENCE_BINDINGS[capability.key];
      if (binding === null || binding === undefined) continue;
      const own = (DEFAULT_PREFERENCES as unknown as Readonly<Record<string, unknown>>)[binding.field];
      // The one device value of its own: `system` follows the operating system's setting.
      if (binding.followsSystem !== undefined && own === binding.followsSystem.value) continue;
      expect(own, capability.key).toBe(preferenceValue(capability.key, capability.default));
    }
  });

  it('checks stored and served values against the registry, never a copy of its ranges', () => {
    expect(normalisePreferences({ fieldOfView: 91 }).fieldOfView).toBe(DEFAULT_PREFERENCES.fieldOfView);
    expect(normalisePreferences({ fieldOfView: 90 }).fieldOfView).toBe(90);
    expect(normalisePreferences({ mouseSensitivity: 2.1 }).mouseSensitivity).toBe(DEFAULT_PREFERENCES.mouseSensitivity);
    expect(normalisePreferences({ vignette: 'blurry' }).vignette).toBe(DEFAULT_PREFERENCES.vignette);
    const applied = preferencesFromInteractionPolicy(DEFAULT_PREFERENCES, {
      'comfort.look-sensitivity-milli': 1500, 'comfort.vignette': 'blurry', 'initiative.mode': 'minimal',
    });
    expect(applied.mouseSensitivity).toBe(1.5);
    expect(applied.vignette).toBe(DEFAULT_PREFERENCES.vignette);
    expect(applied.companionInitiative).toBe('minimal');
  });

  it('draws one control for each capability the served catalog offers, and none for another', () => {
    const { view } = options();
    expect(labels(view.root)).toEqual([]);
    view.showSettings(stated);
    const shown = stated.filter((capability) => capability.shownInSettings);
    expect(labels(view.root)).toEqual(shown.map((capability) => SETTING_WORDS[capability.key]!.label));
    // Which capabilities are offered is data: a catalog that offers camera bob draws it, unchanged code.
    const offered: InteractionCapability[] = stated.map((capability) =>
      capability.key === 'comfort.camera-bob' ? { ...capability, shownInSettings: true } : capability);
    view.showSettings(offered);
    expect(labels(view.root)).toContain('Camera bob');
    const fieldOfView = view.root.querySelector<HTMLInputElement>('[aria-label="Field of view"]')!;
    const registered = REGISTRY.get('comfort.field-of-view-degrees')!;
    expect([Number(fieldOfView.min), Number(fieldOfView.max)]).toEqual([registered.minimum, registered.maximum]);
  });

  it('says so when the served settings cannot be read, rather than drawing a guess', () => {
    const { view } = options();
    view.settingsUnavailable('the request failed.');
    expect(labels(view.root)).toEqual([]);
    expect(view.root.querySelector('.view-settings')!.textContent)
      .toBe('The settings this world offers could not be read: the request failed.');
  });

  it('commits a choice to its preference', () => {
    const { view, onChange } = options();
    view.showSettings(stated);
    const vignette = view.root.querySelector<HTMLSelectElement>('[aria-label="Comfort vignette"]')!;
    vignette.value = 'strong';
    vignette.dispatchEvent(new Event('change'));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ vignette: 'strong' }));
  });
});
