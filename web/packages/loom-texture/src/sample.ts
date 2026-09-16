import { FULL, ONE, clamp, floorDiv, lerp } from './integer.js';
import type { Linear } from './srgb.js';

/**
 * What a recipe says about one point of the tile. Every field is Q16 and every field is set on
 * every call: a recipe that left one alone would leak the previous texel's value into this one.
 */
export interface Sample {
  /** Height as a fraction of the set's stated height range, 0 at the bottom. */
  height: number;
  /** Base colour in linear light. */
  red: number;
  green: number;
  blue: number;
  /** Perceptual roughness, as glTF defines it. */
  roughness: number;
  metalness: number;
  /**
   * Occlusion the recipe knows about and the height field cannot show, ONE for none. The bake
   * multiplies in the cavity term it measures from the height field itself.
   */
  occlusion: number;
}

export function newSample(): Sample {
  return { height: 0, red: 0, green: 0, blue: 0, roughness: 0, metalness: 0, occlusion: ONE };
}

/**
 * A pattern: fill `out` for the tile position (x, y), in micro-units, unwrapped. A maker builds one
 * from a recipe; the pattern is the code, the recipe is the data.
 */
export type Pattern = (x: number, y: number, out: Sample) => void;

/** Height in whole millimetres as a Q16 fraction of the stated range. */
export function heightOf(millimetres: number, rangeMm: number): number {
  return clamp(floorDiv(millimetres * FULL, rangeMm), 0, FULL);
}

/** Height given in 1/1024 mm, for profiles computed in the bond's length unit. */
export function heightOfLength(length: number, rangeMm: number): number {
  return clamp(floorDiv(length * FULL, rangeMm * 1024), 0, FULL);
}

export function setColour(out: Sample, colour: Linear): void {
  out.red = colour[0];
  out.green = colour[1];
  out.blue = colour[2];
}

/** Blend `out`'s colour toward `colour` by t (Q16). */
export function mixColour(out: Sample, colour: Linear, t: number): void {
  out.red = lerp(out.red, colour[0], t);
  out.green = lerp(out.green, colour[1], t);
  out.blue = lerp(out.blue, colour[2], t);
}

/** Multiply `out`'s colour by a Q16 factor, which may exceed ONE to brighten. */
export function shade(out: Sample, factor: number): void {
  out.red = clamp(floorDiv(out.red * factor, ONE), 0, FULL);
  out.green = clamp(floorDiv(out.green * factor, ONE), 0, FULL);
  out.blue = clamp(floorDiv(out.blue * factor, ONE), 0, FULL);
}

/** Blend two colours by t (Q16) without touching a sample. */
export function mixLinear(a: Linear, b: Linear, t: number): Linear {
  return [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
}

/** A Q16 factor from a sixteen-bit field value, spanning [ONE - spread, ONE + spread]. */
export function jitter(value: number, spread: number): number {
  return ONE + floorDiv((value - 32768) * spread, 32768);
}

/** A fraction in thousandths, as the catalog states them, converted to Q16. */
export function permille(value: number): number {
  return floorDiv(value * ONE, 1000);
}
