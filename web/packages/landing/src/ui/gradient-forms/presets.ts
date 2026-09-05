import type { GradientFormsOptions } from './index.js';

export const ARTWORK_PALETTES = {
  daylight: ['#cefa96', '#f4ff91', '#c6e1ff'],
} as const;

/** Deliberately uneven fields: blue washes inward, yellow pools near contact, green follows an arc. */
export const DIAGONAL_COMPOSITION: Pick<GradientFormsOptions, 'forms' | 'materials'> = {
  forms: [
    { id: 'upper', radius: 360, light: 72 },
    { id: 'lower', radius: 330, light: -76, attach: { to: 'upper', angle: 35, gap: 8 } },
  ],
  materials: {
    upper: [
      { color: 2, center: [0.87, 0.45], spread: [0.82, 1.18], rotation: 24, opacity: 0.76,
        falloff: [{ at: 0, opacity: 1 }, { at: 0.36, opacity: 0.58 }, { at: 1, opacity: 0 }] },
      { color: 0, center: [-0.48, 0.91], spread: [0.78, 0.38], rotation: 15, opacity: 0.54,
        falloff: [{ at: 0, opacity: 1 }, { at: 0.5, opacity: 0.25 }, { at: 1, opacity: 0 }] },
      { color: 1, center: [0.04, 1.01], spread: [0.34, 0.44], rotation: -20, opacity: 0.9,
        falloff: [{ at: 0, opacity: 1 }, { at: 0.22, opacity: 0.83 }, { at: 0.75, opacity: 0.15 }, { at: 1, opacity: 0 }] },
    ],
    lower: [
      { color: 2, center: [-0.95, -0.02], spread: [0.43, 0.88], rotation: -12, opacity: 0.74,
        falloff: [{ at: 0, opacity: 1 }, { at: 0.3, opacity: 0.6 }, { at: 1, opacity: 0 }] },
      { color: 0, center: [-0.02, -1.03], spread: [0.74, 0.31], rotation: -8, opacity: 0.84,
        falloff: [{ at: 0, opacity: 1 }, { at: 0.43, opacity: 0.48 }, { at: 1, opacity: 0 }] },
      { color: 1, center: [-0.7, -0.72], spread: [0.38, 0.57], rotation: 42, opacity: 0.76,
        falloff: [{ at: 0, opacity: 1 }, { at: 0.2, opacity: 0.72 }, { at: 1, opacity: 0 }] },
    ],
  },
};

export const ARTWORK_COMPOSITIONS = { diagonal: DIAGONAL_COMPOSITION } as const;

/** Palette selection never changes the material's independent falloff or page theme. */
export function landingArtwork(
  palette: keyof typeof ARTWORK_PALETTES = 'daylight',
  composition: keyof typeof ARTWORK_COMPOSITIONS = 'diagonal',
): GradientFormsOptions {
  return {
    ...ARTWORK_COMPOSITIONS[composition],
    palette: ARTWORK_PALETTES[palette],
    strength: 1,
    texture: 0.18,
    seed: 19,
    motion: 'still',
  };
}

export const HOME_FORMS = landingArtwork();
