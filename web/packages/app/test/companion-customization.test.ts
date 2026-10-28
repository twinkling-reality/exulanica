// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest';

import {
  COMPANION_BODY_VARIANTS,
  COMPANION_COLOR_VARIANTS,
  COMPANION_FACE_VARIANTS,
} from '@exulanica/presentation';

import { DEFAULT_PREFERENCES, normalisePreferences } from '../src/preferences.js';

/**
 * The stored preference and the appearance contract must not be able to drift. The axes used to be
 * declared three times, in presentation, in the preference validator, and again as hand-typed
 * option lists, with nothing deriving one from another. A variant added to one of them validated
 * there and reset somewhere else.
 */

describe('Companion customization', () => {
  it('keeps the preference validator agreeing with the catalog', () => {
    for (const body of COMPANION_BODY_VARIANTS) {
      for (const color of COMPANION_COLOR_VARIANTS) {
        for (const face of COMPANION_FACE_VARIANTS) {
          const kept = normalisePreferences({
            ...DEFAULT_PREFERENCES,
            companionBody: body,
            companionColor: color,
            companionFace: face,
          });
          expect(
            [kept.companionBody, kept.companionColor, kept.companionFace],
            `${body}/${color}/${face} was reset`,
          ).toEqual([body, color, face]);
        }
      }
    }
  });
});
