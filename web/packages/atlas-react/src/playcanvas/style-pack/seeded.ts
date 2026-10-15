/**
 * Seeded draws for what a look scatters (cover on grounds, cover on the land, climbers on walls): the
 * same every time for the same seed and identity, and the same in every browser.
 */

/** A 32-bit hash of a rule's seed and an identity (a slot's, a chunk's): a generator's start. */
export function seedOf(seed: number, identity: string): number {
  let h = (seed ^ 0x9e3779b9) >>> 0;
  for (let i = 0; i < identity.length; i += 1) {
    h = Math.imul(h ^ identity.charCodeAt(i), 0x85ebca6b) >>> 0;
    h = (h ^ (h >>> 13)) >>> 0;
  }
  return h;
}

/** Mulberry32: small, fast and the same in every browser. Draws in [0, 1). */
export function generator(start: number): () => number {
  let state = start >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
