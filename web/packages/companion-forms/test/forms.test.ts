// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest';

import {
  COMPANION_BODY_VARIANTS,
  COMPANION_COLOR_VARIANTS,
  COMPANION_FACE_VARIANTS,
  companionAppearanceConfiguration,
  companionAvatarBlueprint,
} from '@exulanica/presentation';

import { createFlatForm } from '../src/flat.js';
import { createReliefForm } from '../src/relief.js';
import { SOLIDS } from '../src/world.js';
import type { CompanionForm } from '../src/form.js';

/**
 * The bench is only worth reading if the candidates are actually comparable.
 *
 * Every one of these guards the same thing: that a difference on screen is a difference of form.
 * A candidate that quietly draws a different silhouette, or drops a state, or leaves a column of
 * its dossier blank, turns the comparison into an aesthetic preference, which is exactly what
 * frontier-roadmap.md is trying to avoid by asking for prototypes at all.
 *
 * The world candidate needs a WebGL context and is not constructed here. Its data is, because
 * the claim that matters about it is which silhouettes it can represent, and that is a table.
 */

const drawn: readonly (readonly [string, () => CompanionForm])[] = [
  ['flat', createFlatForm],
  ['relief', createReliefForm],
];

describe('the Companion form bench', () => {
  it.each(drawn)('%s answers every column of the dossier', (_name, create) => {
    const { dossier } = create();
    for (const column of ['renderer', 'assets', 'accessibility', 'silhouettes', 'workingState'] as const) {
      expect(dossier[column].length, `${dossier.id} ${column}`).toBeGreaterThan(20);
    }
    expect(dossier.title).toBeTruthy();
    expect(dossier.summary).toBeTruthy();
  });

  it.each(drawn)('%s draws the catalogued silhouette rather than one of its own', (_name, create) => {
    const form = create();
    for (const body of COMPANION_BODY_VARIANTS) {
      const configuration = companionAppearanceConfiguration({ body, color: 'ink', face: 'neutral' });
      form.setAppearance(configuration);
      const path = form.element.querySelector<SVGPathElement>('[data-role="body"]')!;
      expect(path.getAttribute('d'), body).toBe(companionAvatarBlueprint(configuration).bodyPath);
    }
  });

  it.each(drawn)('%s takes its colours from the contract and never invents one', (_name, create) => {
    const form = create();
    for (const color of COMPANION_COLOR_VARIANTS) {
      const configuration = companionAppearanceConfiguration({ body: 'circle', color, face: 'neutral' });
      form.setAppearance(configuration);
      const eyes = form.element.querySelectorAll<SVGRectElement>('[data-role="eye"]');
      expect(eyes.length, `${color} eyes`).toBe(2);
      for (const eye of eyes) expect(eye.getAttribute('fill')).toBe(configuration.eyeColor);
    }
  });

  it.each(drawn)('%s shows every expression and only marks working as different', (_name, create) => {
    const form = create();
    const poses = new Set<string>();
    for (const face of COMPANION_FACE_VARIANTS) {
      form.setAppearance(companionAppearanceConfiguration({ body: 'circle', color: 'ink', face }));
      const eye = form.element.querySelector<SVGRectElement>('[data-role="eye"]')!;
      poses.add(`${eye.getAttribute('height')}/${eye.getAttribute('width')}/${eye.getAttribute('transform')}`);
    }
    expect(poses.size).toBe(COMPANION_FACE_VARIANTS.length);

    const svg = form.element.querySelector<SVGSVGElement>('svg')!;
    for (const state of ['resting', 'attending', 'uncertain', 'settled'] as const) {
      form.setState(state);
      expect(svg.dataset['state']).toBe(state);
    }
    form.setState('working');
    expect(svg.dataset['state']).toBe('working');
  });

  /*
   * The finding this bench exists to produce, held as a test so it cannot be softened later by
   * quietly swapping an unrepresentable silhouette for a sphere and calling the catalog covered.
   */
  it('says which silhouettes a solid can and cannot be', () => {
    expect(Object.keys(SOLIDS).sort()).toEqual([...COMPANION_BODY_VARIANTS].sort());

    const byFidelity = (wanted: string): string[] =>
      Object.entries(SOLIDS).filter(([, solid]) => solid.fidelity === wanted).map(([name]) => name);

    expect(byFidelity('exact')).toEqual(['circle', 'capsule', 'bead']);
    expect(byFidelity('unrepresentable')).toEqual(['cloud', 'droplet', 'arch', 'lozenge']);
    // Four of nine is the number that makes depth a fork of the catalog rather than a finish on it.
    expect(byFidelity('unrepresentable').length).toBeGreaterThan(0);
  });
});
