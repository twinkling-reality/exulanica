// @vitest-environment happy-dom

import { afterEach, describe, expect, it } from 'vitest';
import { DAWN_THEME, ORIGIN_LANDSCAPE, SURVEY_RELIEF } from '@exulanica/presentation';
import { DEFAULT_PREFERENCES, normalisePreferences } from '../src/preferences.js';
import {
  applyDocumentAppearance,
  applyDocumentTheme,
  applyDocumentWorldStyle,
  themeForPreferences,
} from '../src/theme.js';

afterEach(() => {
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.removeAttribute('data-contrast');
  document.documentElement.removeAttribute('data-ui-scheme');
  document.documentElement.removeAttribute('data-transparency');
  document.documentElement.removeAttribute('data-world-style');
  document.documentElement.removeAttribute('data-ui-texture');
  document.documentElement.removeAttribute('style');
});

describe('Atlas presentation theme', () => {
  it('selects one shared token exposure before the document paints', () => {
    applyDocumentTheme(DAWN_THEME);
    const root = document.documentElement;
    expect(root.dataset['theme']).toBe('dawn');
    expect(root.style.colorScheme).toBe('light');
  });

  it('migrates legacy System preferences to the one authored daylight exposure', () => {
    const system = normalisePreferences({ ...DEFAULT_PREFERENCES, appearance: 'system' });
    expect(themeForPreferences(system, false)).toBe(DAWN_THEME);
    expect(themeForPreferences(system, true)).toBe(DAWN_THEME);
    expect(themeForPreferences(DEFAULT_PREFERENCES, false)).toBe(DAWN_THEME);
    expect(themeForPreferences(DEFAULT_PREFERENCES, true)).toBe(DAWN_THEME);
  });

  it('applies exposure, contrast and transparency as one document decision', () => {
    const preferences = normalisePreferences({
      ...DEFAULT_PREFERENCES,
      appearance: 'dawn',
      contrast: 'high',
      transparency: 'reduced',
    });
    expect(applyDocumentAppearance(preferences, true)).toBe(DAWN_THEME);
    expect(document.documentElement.dataset['theme']).toBe('dawn');
    expect(document.documentElement.dataset['contrast']).toBe('high');
    expect(document.documentElement.dataset['transparency']).toBe('reduced');
  });

  it('writes the interface scheme, light unless one was chosen or stored', () => {
    applyDocumentAppearance(DEFAULT_PREFERENCES, true);
    expect(document.documentElement.dataset['uiScheme']).toBe('light');
    applyDocumentAppearance(normalisePreferences({ ...DEFAULT_PREFERENCES, scheme: 'system' }), false);
    expect(document.documentElement.dataset['uiScheme']).toBe('system');
    applyDocumentAppearance(normalisePreferences({ ...DEFAULT_PREFERENCES, scheme: 'sepia' }), false);
    expect(document.documentElement.dataset['uiScheme']).toBe('light');
  });

  it('replaces the world-owned skin while restoring protected system geometry', () => {
    const root = document.documentElement;
    for (const [property, legacyValue] of [
      ['--radius-label', '0px'],
      ['--radius-control', '2px'],
      ['--radius-panel', '0px'],
      ['--radius-pill', '2px'],
      ['--ui-choice-radius', '2px'],
      ['--ui-speech-radius', '2px'],
    ] as const) root.style.setProperty(property, legacyValue);

    applyDocumentWorldStyle(ORIGIN_LANDSCAPE);
    expect(root.dataset['worldStyle']).toBe('origin-landscape');
    expect(root.dataset['uiTexture']).toBe('paper-grain');
    expect(root.style.getPropertyValue('--ui-companion-surface')).toBe(
      ORIGIN_LANDSCAPE.ui.colors.companionSurface,
    );
    expect(root.style.getPropertyValue('--ui-spectrum-rose')).toBe(
      ORIGIN_LANDSCAPE.ui.chromatic.rose,
    );
    expect(root.style.getPropertyValue('--ui-font-body')).toBe(ORIGIN_LANDSCAPE.ui.typography.body);
    expect(root.style.getPropertyValue('--radius-panel')).toBe('');
    expect(root.style.getPropertyValue('--ui-choice-radius')).toBe('');
    expect(root.style.getPropertyValue('--ui-speech-radius')).toBe('');
    expect(root.style.getPropertyValue('--motion-idle-cycle')).toBe('5200ms');

    applyDocumentWorldStyle(SURVEY_RELIEF);
    expect(root.dataset['worldStyle']).toBe('survey-relief');
    expect(root.dataset['uiTexture']).toBe('contour-grid');
    expect(root.style.getPropertyValue('--ui-companion-surface')).toBe(
      SURVEY_RELIEF.ui.colors.companionSurface,
    );
    expect(root.style.getPropertyValue('--ui-spectrum-rose')).toBe(
      SURVEY_RELIEF.ui.chromatic.rose,
    );
    expect(root.style.getPropertyValue('--ui-font-body')).toBe(SURVEY_RELIEF.ui.typography.body);
    expect(root.style.getPropertyValue('--radius-panel')).toBe('');
    expect(root.style.getPropertyValue('--ui-choice-radius')).toBe('');
    expect(root.style.getPropertyValue('--ui-speech-radius')).toBe('');
    expect(root.style.getPropertyValue('--profile-ui-companion-blur')).toBe('0px');
    expect(root.style.getPropertyValue('--motion-idle-cycle')).toBe('4000ms');
  });
});
