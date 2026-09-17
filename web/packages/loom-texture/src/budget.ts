import { SET_PROFILE_V1, V1_LAYOUT, classLayout } from './classes.js';
import type { TextureSetDefinition } from './definition.js';

/**
 * What a set costs a GPU once decoded, and the envelope that cost has to fit.
 *
 * The envelope is the Melbourne street measurement: rejected on looks while passing every
 * mechanical budget, with 168 MB of decoded texture accepted for 127 m of one street. The
 * corridor draws six sets, so six sets must fit under it with room left for everything else.
 *
 * Counted conservatively: every map is taken as uploaded RGBA8, four bytes a texel, even the
 * three-channel and one-channel maps, because RGB8 and R8 uploads are an engine's choice and this
 * package cannot make it. And the envelope is read as 168,000,000 bytes, the smaller reading of
 * "168 MB".
 *
 * The arithmetic that chose 1024 texels: one 1024 x 1024 RGBA8 map is 4 MiB, four maps are
 * 16 MiB a set, six sets are 96 MiB (100,663,296 bytes), and with full mip chains 134,217,696
 * bytes. Both fit. At 2048 x 2048 one set alone is 64 MiB before mips, and six are 402,653,184
 * bytes, well over the envelope, so 2048 does not fit and 1024 is the largest power of two that
 * does.
 */
export const ACCEPTED_DECODED_ENVELOPE_BYTES = 168_000_000;
export const CORRIDOR_SET_COUNT = 6;
export const DECODED_BYTES_PER_TEXEL = 4;

/** Texels in a full mip chain, down to 1 x 1, for a width x height base level. */
export function mipChainTexels(width: number, height: number): number {
  let total = 0;
  let w = width;
  let h = height;
  for (;;) {
    total += w * h;
    if (w === 1 && h === 1) return total;
    w = Math.max(1, w >> 1);
    h = Math.max(1, h >> 1);
  }
}

/**
 * A set's decoded cost: each map it stores, as RGBA8. A v1 set stores its four maps, height
 * included, and is charged for all four as it always was; a set of a material class stores its
 * class's maps and no height map, and is charged for those.
 */
export function decodedBytes(def: TextureSetDefinition, withMips: boolean): number {
  const texels = withMips ? mipChainTexels(def.width, def.height) : def.width * def.height;
  const maps = def.containerProfile === SET_PROFILE_V1 ? V1_LAYOUT : classLayout(def.materialClass, 'procedural');
  return maps.length * texels * DECODED_BYTES_PER_TEXEL;
}

/**
 * The decoded cost of the corridor's six sets. The corridor's choice of six is the grammar's to
 * make, so this charges the six most expensive sets in the catalog, which bounds every choice.
 */
export function corridorDecodedBytes(
  catalog: readonly TextureSetDefinition[],
  withMips: boolean,
): number {
  const costs = catalog.map((def) => decodedBytes(def, withMips)).sort((a, b) => b - a);
  if (costs.length < CORRIDOR_SET_COUNT) {
    throw new Error(`the corridor needs ${CORRIDOR_SET_COUNT} sets and the catalog has ${costs.length}`);
  }
  return costs.slice(0, CORRIDOR_SET_COUNT).reduce((sum, cost) => sum + cost, 0);
}
