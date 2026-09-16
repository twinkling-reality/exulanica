/**
 * Integer arithmetic for the bake.
 *
 * Every value a texture set is made of is an integer from the first sample to the last byte, and
 * that is a determinism decision rather than a style. The bytes are pinned by a migration, so the
 * bake has to produce them again on any machine, any Node version and any CPU. IEEE-754 addition,
 * subtraction, multiplication and division are correctly rounded everywhere V8 runs, but the
 * transcendental functions (`Math.pow`, `Math.exp`, `Math.sin` and the rest) are only
 * "implementation-approximated" by the language, and V8 has changed their results between
 * releases before. So nothing here calls them, `test/source-hygiene.test.ts` refuses them by
 * name, and the few places that need a curve (smoothstep, the sRGB transfer, a square root) get
 * it from integer arithmetic or from a literal table.
 *
 * Integers live in ordinary JavaScript numbers. Every intermediate product in this package stays
 * below 2^50 by construction, well inside the 2^53 range where a double is an exact integer, and
 * each helper states the bound it relies on.
 */

/** One in Q16 fixed point: the scale every weight, fraction and channel value uses. */
export const ONE = 65536;
/** The largest channel value, which is ONE - 1 so a channel always fits in sixteen bits. */
export const FULL = 65535;

/**
 * Floor division for integers, exact for every pair the bake produces.
 *
 * `Math.floor(a / b)` alone is exact while |a| + b < 2^53, which holds here, and the two
 * comparisons below make the result exact for any safe integer pair regardless. The divisor must
 * be positive; nothing in the bake divides by a negative number, and refusing one keeps the
 * correction steps simple.
 */
export function floorDiv(a: number, b: number): number {
  if (!(b > 0)) throw new RangeError(`floorDiv needs a positive divisor, got ${b}`);
  let q = Math.floor(a / b);
  if (q * b > a) q -= 1;
  else if ((q + 1) * b <= a) q += 1;
  return q;
}

/** The non-negative remainder of floor division: always in [0, b). */
export function floorMod(a: number, b: number): number {
  return a - floorDiv(a, b) * b;
}

/** Round a / b to the nearest integer, halves toward positive infinity. */
export function roundDiv(a: number, b: number): number {
  return floorDiv(2 * a + b, 2 * b);
}

export function clamp(value: number, low: number, high: number): number {
  return value < low ? low : value > high ? high : value;
}

/**
 * The exact integer square root, floor(sqrt(n)), for 0 <= n < 2^52.
 *
 * `Math.sqrt` is only the first guess. The two loops correct it to the exact floor whatever the
 * platform's square root returned, so the result is a property of `n` and not of the machine.
 */
const TWO_TO_52 = 4_503_599_627_370_496;

export function isqrt(n: number): number {
  if (!(n >= 0) || n >= TWO_TO_52 || !Number.isInteger(n)) {
    throw new RangeError(`isqrt needs an integer in [0, 2^52), got ${n}`);
  }
  let r = Math.floor(Math.sqrt(n));
  while (r * r > n) r -= 1;
  while ((r + 1) * (r + 1) <= n) r += 1;
  return r;
}

/**
 * Linear interpolation in Q16: a + (b - a) * t / ONE, with t in [0, ONE].
 *
 * |b - a| is at most 2^17 and t at most 2^16, so the product is below 2^33.
 */
export function lerp(a: number, b: number, t: number): number {
  return a + floorDiv((b - a) * t, ONE);
}

/**
 * The smoothstep curve t^2 (3 - 2t) on a Q16 fraction t in [0, ONE].
 *
 * t * t is at most 2^32, and the second product at most 2^16 * 3 * 2^16, below 2^34.
 */
export function smooth(t: number): number {
  const t2 = floorDiv(t * t, ONE);
  return floorDiv(t2 * (3 * ONE - 2 * t), ONE);
}

/**
 * Smoothstep between two edges, in whatever integer unit the edges and x share. Returns Q16.
 *
 * (x - edge0) * ONE must stay below 2^53, so the unit must keep |x - edge0| below 2^36; every
 * caller passes positions in 1/1024 mm or tile micro-units, far inside that.
 */
export function smoothstep(edge0: number, edge1: number, x: number): number {
  if (x <= edge0) return 0;
  if (x >= edge1) return ONE;
  return smooth(floorDiv((x - edge0) * ONE, edge1 - edge0));
}

/** Scale a Q16 value by a Q16 factor. Both operands below 2^20, so the product is below 2^40. */
export function scale(value: number, factor: number): number {
  return floorDiv(value * factor, ONE);
}
