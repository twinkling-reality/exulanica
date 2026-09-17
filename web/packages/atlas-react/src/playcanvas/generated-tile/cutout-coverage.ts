/**
 * Mip levels for a `cutout` set that keep its coverage.
 *
 * A cutout surface is drawn by testing each sample's coverage against the class cutoff: covered or
 * not, never blended. Ordinary mip levels average coverage, and an average of leaves and gaps falls
 * below the cutoff more often than the leaves did, so a canopy seen from 30 m thins out and then
 * vanishes. The texture proposal's contract is that every level keeps the share of texels at or above
 * the cutoff equal to the set's `coverage_permille`. So each level here is built from the level above
 * it, and its coverage is then scaled by the one factor that puts exactly that share of its texels at
 * or above the cutoff (the method of Castano, "Computing alpha mipmaps", 2010). It does not depend on
 * multisampling, and the shadow pass, which has none, tests the same levels.
 *
 * Colour is averaged in linear light and weighted by coverage, so the colour of empty texels (often
 * black) does not darken the leaves at a distance. Level 0 is the set's own bytes, unchanged.
 *
 * Pure arithmetic over bytes: no renderer, no DOM. Nothing here enters a digest.
 */

const SRGB_TO_LINEAR = Float64Array.from({ length: 256 }, (_, byte) => {
  const value = byte / 255;
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
});

function linearToSrgbByte(value: number): number {
  const clamped = Math.min(1, Math.max(0, value));
  const encoded = clamped <= 0.0031308 ? clamped * 12.92 : 1.055 * clamped ** (1 / 2.4) - 0.055;
  return Math.round(encoded * 255);
}

/** The share of texels whose coverage (the fourth byte) is at least `cutoff`. */
export function coverageShare(rgba: Uint8Array, cutoff: number): number {
  const texels = rgba.length / 4;
  let covered = 0;
  for (let at = 3; at < rgba.length; at += 4) if (rgba[at]! >= cutoff) covered += 1;
  return covered / texels;
}

/**
 * The factor that, applied to a level's averaged coverage and floored to a byte, puts `wanted` of its
 * texels at or above `cutoff`. Texels that tie with the last one wanted are covered together, so a
 * level can hold a few more than `wanted`; texels with no coverage at all stay uncovered.
 */
function coverageScale(alpha: Float64Array, wanted: number, cutoff: number): number {
  const sorted = Float64Array.from(alpha).sort().reverse();
  const largest = sorted[0] ?? 0;
  if (wanted <= 0) return largest > 0 ? (cutoff - 1) / largest : 1;
  const last = sorted[Math.min(wanted, sorted.length) - 1]!;
  // Nothing scales an empty texel into coverage; cover every texel that has any.
  if (last <= 0) return 255 * 256;
  return (cutoff / last) * (1 + 1e-9);
}

/**
 * Every mip level of a cutout set's colour and coverage map, level 0 first, each keeping the share of
 * texels at or above `cutoff` equal to `coveragePermille` thousandths (to the nearest texel).
 */
export function coveragePreservingMips(
  rgba: Uint8Array,
  width: number,
  height: number,
  cutoff: number,
  coveragePermille: number,
): Uint8Array[] {
  if (rgba.length !== width * height * 4) throw new Error('A cutout colour map needs four bytes a texel');
  const target = coveragePermille / 1000;
  const levels = [rgba];
  let previous = rgba;
  let w = width;
  let h = height;
  while (w > 1 || h > 1) {
    const nw = Math.max(1, w >> 1);
    const nh = Math.max(1, h >> 1);
    const next = new Uint8Array(nw * nh * 4);
    const alpha = new Float64Array(nw * nh);
    for (let y = 0; y < nh; y += 1) {
      for (let x = 0; x < nw; x += 1) {
        let weight = 0;
        let count = 0;
        const weighted = [0, 0, 0];
        const plain = [0, 0, 0];
        for (let dy = 0; dy < 2; dy += 1) {
          for (let dx = 0; dx < 2; dx += 1) {
            const sx = Math.min(w - 1, x * 2 + dx);
            const sy = Math.min(h - 1, y * 2 + dy);
            const at = (sy * w + sx) * 4;
            const a = previous[at + 3]!;
            for (let channel = 0; channel < 3; channel += 1) {
              const linear = SRGB_TO_LINEAR[previous[at + channel]!]!;
              weighted[channel]! += linear * a;
              plain[channel]! += linear;
            }
            weight += a;
            count += 1;
          }
        }
        const out = (y * nw + x) * 4;
        for (let channel = 0; channel < 3; channel += 1) {
          next[out + channel] = linearToSrgbByte(weight > 0 ? weighted[channel]! / weight : plain[channel]! / count);
        }
        alpha[y * nw + x] = weight / count;
      }
    }
    const scale = coverageScale(alpha, Math.round(target * nw * nh), cutoff);
    for (let texel = 0; texel < nw * nh; texel += 1) {
      next[texel * 4 + 3] = Math.min(255, Math.floor(alpha[texel]! * scale));
    }
    levels.push(next);
    previous = next;
    w = nw;
    h = nh;
  }
  return levels;
}
