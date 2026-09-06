import { describe, expect, it } from 'vitest';

import {
  COMPANION_BODY_VARIANTS,
  COMPANION_COLOR_VARIANTS,
  COMPANION_FACE_VARIANTS,
  companionAppearanceConfiguration,
  companionAvatarBlueprint,
  DEFAULT_COMPANION,
  resolveCompanionAppearance,
} from '../src/index.js';

/**
 * The catalogs are the single source of truth for the Companion's appearance axes.
 *
 * The types are derived from these arrays and the geometry and colour tables are total records
 * over those types, so most of this is already a compile error rather than a test. What the
 * compiler cannot say is whether a new entry is actually a different thing to look at, or whether
 * its eyes can be seen on its body. Those are the two ways a catalog grows into a list of
 * choices that are not choices.
 */

const relativeLuminance = (hex: string): number => {
  const channel = (offset: number): number => {
    const value = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
};

const contrast = (a: string, b: string): number => {
  const [high, low] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (high! + 0.05) / (low! + 0.05);
};

describe('the Companion appearance catalog', () => {
  it('gives every silhouette its own geometry', () => {
    const paths = COMPANION_BODY_VARIANTS.map((body) =>
      companionAvatarBlueprint(companionAppearanceConfiguration({
        body,
        color: DEFAULT_COMPANION.colorVariant,
        face: DEFAULT_COMPANION.faceVariant,
      })).bodyPath,
    );
    for (const path of paths) expect(path).toMatch(/^M/);
    expect(new Set(paths).size).toBe(COMPANION_BODY_VARIANTS.length);
  });

  it('gives every expression its own eye pose', () => {
    const poses = COMPANION_FACE_VARIANTS.map((face) => {
      const { eyePose } = companionAvatarBlueprint(companionAppearanceConfiguration({
        body: DEFAULT_COMPANION.bodyVariant,
        color: DEFAULT_COMPANION.colorVariant,
        face,
      }));
      return JSON.stringify([eyePose.left, eyePose.right]);
    });
    expect(new Set(poses).size).toBe(COMPANION_FACE_VARIANTS.length);
  });

  /*
   * Eyes are a graphical object rather than text, so the floor is WCAG 2.2 SC 1.4.11 at 3:1
   * rather than 4.5:1. A colour whose eyes sit under that reads as a blank shape, which is a
   * different Companion from the one the catalog is offering.
   */
  it('keeps every colour a face rather than a blank shape', () => {
    const seen = new Set<string>();
    for (const color of COMPANION_COLOR_VARIANTS) {
      const configuration = companionAppearanceConfiguration({
        body: DEFAULT_COMPANION.bodyVariant,
        color,
        face: DEFAULT_COMPANION.faceVariant,
      });
      expect(configuration.bodyColor, `${color} body`).toMatch(/^#[0-9a-f]{6}$/);
      expect(configuration.eyeColor, `${color} eye`).toMatch(/^#[0-9a-f]{6}$/);
      expect(
        contrast(configuration.bodyColor, configuration.eyeColor),
        `${color} eyes on its own body`,
      ).toBeGreaterThanOrEqual(3);
      seen.add(configuration.bodyColor);
    }
    expect(seen.size).toBe(COMPANION_COLOR_VARIANTS.length);
  });

  it('accepts every catalogued choice and still fails closed on anything else', () => {
    for (const body of COMPANION_BODY_VARIANTS) {
      for (const color of COMPANION_COLOR_VARIANTS) {
        for (const face of COMPANION_FACE_VARIANTS) {
          const resolved = resolveCompanionAppearance(
            companionAppearanceConfiguration({ body, color, face }),
          );
          expect(resolved.issues, `${body}/${color}/${face}`).toEqual([]);
          expect(resolved.configuration.bodyVariant).toBe(body);
          expect(resolved.configuration.colorVariant).toBe(color);
          expect(resolved.configuration.faceVariant).toBe(face);
        }
      }
    }

    const unknown = resolveCompanionAppearance({
      ...DEFAULT_COMPANION,
      bodyVariant: 'lantern',
    });
    expect(unknown.issues).toEqual(['invalid-v3-configuration']);
    expect(unknown.configuration).toBe(DEFAULT_COMPANION);
  });
});
