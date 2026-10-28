// @vitest-environment happy-dom
// The reviewed interaction capabilities are the registry the server reads, and nothing here
// restates them. What the page adds (each capability's preference field) is held here to that
// registry.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { preferencesFromInteractionPolicy } from '../src/interaction-policy.js';
import {
  PREFERENCE_BINDINGS,
  preferenceValue,
  readCapabilities,
} from '../src/interaction-settings.js';
import { DEFAULT_PREFERENCES, normalisePreferences } from '../src/preferences.js';

/** The repository, from the web workspace vitest runs in, as the other page tests read it. */
const REGISTRY_FILE = `${process.cwd()}/../exulanica/world/interaction-policy-registry.v1.json`;
const stated = readCapabilities(JSON.parse(readFileSync(REGISTRY_FILE, 'utf8')));

describe('the settings the page holds', () => {
  it('has a preference binding for exactly the capabilities the registry states', () => {
    const keys = stated.map((capability) => capability.key).sort();
    // A positive control: the reading found the registry's capabilities.
    expect(keys).toEqual(expect.arrayContaining(['comfort.vignette', 'disclosure.provenance-detail']));
    expect(Object.keys(PREFERENCE_BINDINGS).sort()).toEqual(keys);
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
});
