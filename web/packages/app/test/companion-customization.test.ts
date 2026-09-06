// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  COMPANION_BODY_VARIANTS,
  COMPANION_COLOR_VARIANTS,
  COMPANION_FACE_VARIANTS,
  companionAppearanceConfiguration,
  companionAvatarBlueprint,
} from '@exulanica/presentation';

import { DEFAULT_PREFERENCES, normalisePreferences } from '../src/preferences.js';
import { buildOptions } from '../src/ui/options.js';

/**
 * Customize is the only place a person meets the appearance contract, so the two must not be able
 * to drift. The axes used to be declared three times, in presentation, in the preference
 * validator, and again as hand-typed option lists, with nothing deriving one from another. A
 * variant added to one of them validated there and reset somewhere else.
 */

const options = () => {
  const view = buildOptions({
    preferences: DEFAULT_PREFERENCES,
    onChange: vi.fn(),
    onPreview: vi.fn(),
    onClose: vi.fn(),
    onShowControls: vi.fn(),
  });
  document.body.append(view.root);
  return view;
};

const values = (view: { root: HTMLElement }, label: string): string[] =>
  Array.from(
    view.root.querySelectorAll<HTMLOptionElement>(`[aria-label="${label}"] option`),
    (option) => option.value,
  );

describe('Companion customization', () => {
  beforeEach(() => document.body.replaceChildren());

  it('offers exactly the contract catalog, every entry named', () => {
    const view = options();

    expect(values(view, 'Companion shape')).toEqual([...COMPANION_BODY_VARIANTS]);
    expect(values(view, 'Companion color')).toEqual([...COMPANION_COLOR_VARIANTS]);
    expect(values(view, 'Companion expression')).toEqual([...COMPANION_FACE_VARIANTS]);

    for (const label of ['Companion shape', 'Companion color', 'Companion expression']) {
      for (const option of view.root.querySelectorAll<HTMLOptionElement>(`[aria-label="${label}"] option`)) {
        expect(option.textContent?.trim(), `${label} ${option.value}`).toBeTruthy();
      }
    }
  });

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

  it('draws the chosen Companion where the choice is made', () => {
    const view = options();
    const preview = view.root.querySelector<HTMLElement>('.companion-preview')!;

    expect(preview).not.toBeNull();
    expect(preview.getAttribute('aria-hidden')).toBe('true');
    // The real renderer, not a second drawing that could disagree with the world.
    const body = preview.querySelector<SVGPathElement>('.companion-avatar-body')!;
    expect(preview.querySelectorAll('.companion-avatar-eye')).toHaveLength(2);

    const expected = companionAppearanceConfiguration({
      body: DEFAULT_PREFERENCES.companionBody,
      color: DEFAULT_PREFERENCES.companionColor,
      face: DEFAULT_PREFERENCES.companionFace,
    });
    expect(body.getAttribute('fill')).toBe(expected.bodyColor);
    const startingPath = body.getAttribute('d');

    const shape = view.root.querySelector<HTMLSelectElement>('[aria-label="Companion shape"]')!;
    const colour = view.root.querySelector<HTMLSelectElement>('[aria-label="Companion color"]')!;
    shape.value = 'lozenge';
    shape.dispatchEvent(new Event('change'));
    colour.value = 'iris';
    colour.dispatchEvent(new Event('change'));

    const chosen = companionAppearanceConfiguration({ body: 'lozenge', color: 'iris', face: 'neutral' });
    expect(body.getAttribute('fill')).toBe(chosen.bodyColor);
    expect(body.getAttribute('d')).toBe(companionAvatarBlueprint(chosen).bodyPath);
    expect(body.getAttribute('d')).not.toBe(startingPath);
  });
});
