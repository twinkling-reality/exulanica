import * as pc from 'playcanvas';
import type { TileLook } from './look.js';

/**
 * The stated unavailable surface.
 *
 * A surface whose texture set does not resolve, or whose range carries no facade record, is still
 * a place in the tile, and leaving a hole there would read as a cut. Drawing it in a flat colour
 * would read as architecture, which is worse: it is exactly the seven flat fills the shipped
 * district used. So it is drawn in a pattern nobody could take for a building material, unlit, with
 * the word UNAVAILABLE written into the pattern itself, so a screenshot states the fact without the
 * page around it.
 *
 * The pattern is computed here, from integers, with no canvas and no font file, so it exists on
 * every device the renderer runs on.
 */

/** 5 by 7 glyphs, one row per string, `#` lit. Only the letters the word needs. */
const GLYPHS: Readonly<Record<string, readonly string[]>> = {
  U: ['#...#', '#...#', '#...#', '#...#', '#...#', '#...#', '.###.'],
  N: ['#...#', '##..#', '#.#.#', '#..##', '#...#', '#...#', '#...#'],
  A: ['.###.', '#...#', '#...#', '#####', '#...#', '#...#', '#...#'],
  V: ['#...#', '#...#', '#...#', '#...#', '#...#', '.#.#.', '..#..'],
  I: ['#####', '..#..', '..#..', '..#..', '..#..', '..#..', '#####'],
  L: ['#....', '#....', '#....', '#....', '#....', '#....', '#####'],
  B: ['####.', '#...#', '#...#', '####.', '#...#', '#...#', '####.'],
  E: ['#####', '#....', '#....', '####.', '#....', '#....', '#####'],
};
const WORD = 'UNAVAILABLE';
const GLYPH_SCALE = 2;
const SIZE = 128;

/** RGBA texels of the pattern, row 0 first. Exposed so the pattern itself can be tested. */
export function unavailablePatternTexels(look: TileLook): Uint8Array {
  const { ink, ground, stripeTexels } = look.unavailable;
  const byte = (value: number): number => Math.round(Math.min(1, Math.max(0, value)) * 255);
  const inkBytes = ink.map(byte);
  const groundBytes = ground.map(byte);
  const out = new Uint8Array(SIZE * SIZE * 4);
  const put = (x: number, y: number, colour: readonly number[]): void => {
    const at = (y * SIZE + x) * 4;
    out[at] = colour[0]!;
    out[at + 1] = colour[1]!;
    out[at + 2] = colour[2]!;
    out[at + 3] = 255;
  };
  for (let y = 0; y < SIZE; y += 1) {
    for (let x = 0; x < SIZE; x += 1) {
      put(x, y, (x + y) % stripeTexels < stripeTexels / 2 ? inkBytes : groundBytes);
    }
  }
  // A band across the middle, and the word on it in the stripe ink.
  // Five columns and one spacing texel per letter: eleven letters fit in 121 of the 128 texels.
  const glyphWidth = 5 * GLYPH_SCALE + 1;
  const bandTop = SIZE / 2 - 6 * GLYPH_SCALE;
  const bandBottom = SIZE / 2 + 6 * GLYPH_SCALE;
  for (let y = bandTop; y < bandBottom; y += 1) for (let x = 0; x < SIZE; x += 1) put(x, y, groundBytes);
  const left = Math.max(0, Math.floor((SIZE - WORD.length * glyphWidth) / 2));
  [...WORD].forEach((letter, index) => {
    const rows = GLYPHS[letter]!;
    rows.forEach((row, gy) => {
      [...row].forEach((cell, gx) => {
        if (cell !== '#') return;
        for (let sy = 0; sy < GLYPH_SCALE; sy += 1) {
          for (let sx = 0; sx < GLYPH_SCALE; sx += 1) {
            const x = left + index * glyphWidth + gx * GLYPH_SCALE + sx;
            const y = SIZE / 2 - 7 * GLYPH_SCALE / 2 + gy * GLYPH_SCALE + sy;
            if (x < SIZE) put(x, y, inkBytes);
          }
        }
      });
    });
  });
  return out;
}

/** The unlit material every unavailable surface in a tile shares. */
export function createUnavailableMaterial(device: pc.GraphicsDevice, look: TileLook): {
  readonly material: pc.StandardMaterial;
  readonly texture: pc.Texture;
} {
  const texture = new pc.Texture(device, {
    name: 'generated-tile-unavailable-pattern',
    width: SIZE,
    height: SIZE,
    format: pc.PIXELFORMAT_SRGBA8,
    mipmaps: true,
    addressU: pc.ADDRESS_REPEAT,
    addressV: pc.ADDRESS_REPEAT,
    minFilter: pc.FILTER_LINEAR_MIPMAP_LINEAR,
    magFilter: pc.FILTER_NEAREST,
    levels: [unavailablePatternTexels(look)],
  });
  const material = new pc.StandardMaterial();
  material.name = 'generated-tile-unavailable';
  material.useLighting = false;
  material.useSkybox = false;
  material.diffuse = new pc.Color(0, 0, 0);
  material.emissive = new pc.Color(1, 1, 1);
  material.emissiveMap = texture;
  material.cull = pc.CULLFACE_NONE;
  material.update();
  return { material, texture };
}
