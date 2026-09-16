import { floorDiv } from './integer.js';

/**
 * Where a texel is, in units that do not depend on the resolution.
 *
 * A tile is TILE micro-units along each axis, whatever its physical size and whatever its
 * resolution. Texel `i` of a row `size` texels long samples the tile at its centre,
 * (i + 1/2) / size. In micro-units that is (2i + 1) * 2^19 / size, which is an exact integer for
 * every texel whenever `size` divides 2^19 (every power of two up to 524288), and at any other
 * size exactly where `size` divides (2i + 1) * 2^19. At 768 = 3 * 256 that is every texel
 * i = 3k + 1, which sits on the same point as texel k at 256; the resolution test compares those.
 *
 * `index` is deliberately NOT wrapped into [0, size). A recipe receives the unwrapped position,
 * so a texel one tile to the right arrives as a position one TILE further on, and the recipe has
 * to produce the same value there because its pattern is periodic, not because this function
 * folded the coordinate back. `test/tiling.test.ts` bakes with an offset to hold recipes to that.
 */
export const TILE = 1 << 20;

export function texelToTile(index: number, size: number): number {
  return floorDiv((2 * index + 1) * TILE, 2 * size);
}

/** One millimetre in the Q10 length unit recipes compare positions in (1/1024 mm). */
export const MM = 1024;

/**
 * A tile position as a length in Q10 millimetres, given the tile's extent along that axis in
 * whole millimetres.
 *
 * TILE is 2^20 and MM is 2^10, so the scale is extent / 1024 per micro-unit. A position one TILE
 * further on is exactly extent * MM further on, so a pattern laid out in millimetres with a
 * period that divides the extent is periodic on the tile.
 */
export function tileToLength(position: number, extentMm: number): number {
  return floorDiv(position * extentMm, 1024);
}
