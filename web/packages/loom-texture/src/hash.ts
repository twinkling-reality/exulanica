/**
 * Deterministic hashing, and nothing else that could be called random.
 *
 * Every stochastic decision in a texture set is a HASH of integer coordinates plus a seed, never a
 * stateful generator stepped in scan order. `scene-synth/src/rng.ts` states why and the reasons
 * carry over unchanged: output is byte-identical across machines, Node versions and thread
 * counts, and changing the resolution does not reshuffle the noise, because a lattice value
 * depends on where it is on the tile rather than on how many texels were drawn before it.
 *
 * The finalizer is the one scene-synth uses. It is repeated here rather than imported because the
 * dependency-cruiser fence lets loom-texture reach no workspace package but atlas-core, and a
 * bake tool that imported another bake tool would couple two pinned outputs to one edit.
 */

/** 32-bit integer hash (Murmur-style finalizer). Avalanches well and holds no state. */
export function hashU32(x: number): number {
  let h = x | 0;
  h = Math.imul(h ^ (h >>> 16), 0x21f0aaad);
  h = Math.imul(h ^ (h >>> 15), 0x735a2d97);
  h ^= h >>> 15;
  return h >>> 0;
}

/** Hash of three integers and a seed. Inputs are reduced to 32 bits, which is all they use. */
export function hash3(x: number, y: number, z: number, seed: number): number {
  return hashU32(
    Math.imul(x | 0, 0x27d4eb2d)
      ^ Math.imul(y | 0, 0x165667b1)
      ^ Math.imul(z | 0, 0x9e3779b1)
      ^ hashU32(seed),
  );
}

/** A sixteen-bit value, 0 to 65535, from a hash. */
export const bits16 = (h: number): number => h >>> 16;

/** An integer in [low, high] from a hash. The span must be below 2^16. */
export function pick(h: number, low: number, high: number): number {
  const span = high - low + 1;
  return low + Math.floor(((h >>> 16) * span) / 65536);
}

/**
 * A named sub-seed. Each field of a recipe draws from its own stream, so adding a field to one
 * surface never moves the values another field already had.
 */
export function stream(seed: number, tag: number): number {
  return hashU32(Math.imul(seed | 0, 0x2545f491) ^ Math.imul(tag | 0, 0x5bd1e995));
}
