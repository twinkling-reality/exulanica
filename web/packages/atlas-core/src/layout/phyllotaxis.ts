/**
 * The deterministic seed for the layout solver.
 *
 * interaction-model.md 1.4: "A deterministic seed (phyllotaxis) plus a pinned force relaxation,
 * ordered by creation time, run once and persisted with a layout version."
 *
 * Phyllotaxis rather than a random or circular seed for three reasons: it is a closed form so
 * there is no PRNG to seed and no seeded PRNG to depend on across library versions; it produces
 * no two islands at the same radius, so the relaxation never starts from a symmetric
 * configuration it cannot break; and appending an island appends a point without moving the
 * earlier ones, which is exactly the incremental behaviour the drift clamp wants.
 */

/** ~137.5 degrees. The angle that makes successive points maximally non-aligned. */
export const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

export interface SeedPoint {
  readonly x: number;
  readonly z: number;
}

/**
 * @param count number of islands
 * @param spacing arrangement units, not metres; the radius of point i is `spacing * sqrt(i + 0.5)`
 */
export function phyllotaxisSeed(count: number, spacing: number): readonly SeedPoint[] {
  const out: SeedPoint[] = [];
  for (let i = 0; i < count; i += 1) {
    const r = spacing * Math.sqrt(i + 0.5);
    const theta = i * GOLDEN_ANGLE;
    out.push({ x: r * Math.cos(theta), z: r * Math.sin(theta) });
  }
  return out;
}
