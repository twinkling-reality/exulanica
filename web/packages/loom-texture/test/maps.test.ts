import { describe, expect, it } from 'vitest';
import {
  ACCEPTED_DECODED_ENVELOPE_BYTES,
  CORRIDOR_SET_COUNT,
  corridorDecodedBytes,
  decodedBytes,
  mipChainTexels,
} from '../src/budget.js';
import { CATALOG } from '../src/catalog.js';
import type { TextureSetDefinition } from '../src/definition.js';
import { FULL, floorDiv, isqrt } from '../src/integer.js';
import { type Fields, normalMap } from '../src/maps.js';
import { SRGB_TO_LINEAR, encodeChannel } from '../src/srgb.js';

describe('the sRGB table', () => {
  it('is the IEC 61966-2-1 curve at sixteen bits', () => {
    // Math.pow is fine in a test: the table is what the bake uses, and this only checks it.
    SRGB_TO_LINEAR.forEach((value, byte) => {
      const c = byte / 255;
      const linear = c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
      expect(Math.abs(value - linear * 65535), `byte ${byte}`).toBeLessThanOrEqual(0.5);
    });
  });

  it('is strictly increasing from 0 to 65535, so the encoder search is well defined', () => {
    expect(SRGB_TO_LINEAR).toHaveLength(256);
    expect(SRGB_TO_LINEAR[0]).toBe(0);
    expect(SRGB_TO_LINEAR[255]).toBe(FULL);
    for (let byte = 1; byte < 256; byte += 1) {
      expect(SRGB_TO_LINEAR[byte]!).toBeGreaterThan(SRGB_TO_LINEAR[byte - 1]!);
    }
  });

  it('encodes every decoded byte back to itself, and clamps out-of-range light', () => {
    for (let byte = 0; byte < 256; byte += 1) {
      expect(encodeChannel(SRGB_TO_LINEAR[byte]!)).toBe(byte);
    }
    expect(encodeChannel(-5)).toBe(0);
    expect(encodeChannel(FULL + 900)).toBe(255);
  });
});

describe('integer helpers', () => {
  it('floorDiv floors, including below zero', () => {
    expect(floorDiv(7, 2)).toBe(3);
    expect(floorDiv(-7, 2)).toBe(-4);
    expect(floorDiv(-8, 2)).toBe(-4);
    expect(floorDiv(2 ** 50 + 1, 3)).toBe(Math.floor((2 ** 50 + 1) / 3));
    expect(() => floorDiv(1, 0)).toThrow();
  });

  it('isqrt is the exact floor square root', () => {
    for (const n of [0, 1, 2, 3, 4, 15, 16, 17, 2 ** 40 - 1, 2 ** 40, 2 ** 52 - 1]) {
      const r = isqrt(n);
      expect(r * r <= n && (r + 1) * (r + 1) > n, `isqrt(${n}) = ${r}`).toBe(true);
    }
    expect(() => isqrt(2 ** 52)).toThrow();
    expect(() => isqrt(-1)).toThrow();
  });
});

describe('the normal map follows the glTF convention', () => {
  // One millimetre per texel, so a bump of a few millimetres is a slope the bytes can show.
  const size = 32;
  const def: TextureSetDefinition = {
    ...CATALOG[0]!,
    width: size,
    height: size,
    extentU: size,
    extentV: size,
  };
  const fields = (height: (x: number, y: number) => number): Fields => {
    const relief = new Uint16Array(size * size);
    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) relief[y * size + x] = height(x, y);
    }
    const zero = new Uint16Array(size * size);
    return {
      width: size,
      height: size,
      relief,
      red: zero,
      green: zero,
      blue: zero,
      roughness: zero,
      metalness: zero,
      occlusion: zero,
      coverage: zero,
      transmission: zero,
    };
  };
  const at = (normal: Uint8Array, x: number, y: number) => {
    const i = (y * size + x) * 3;
    return [normal[i]!, normal[i + 1]!, normal[i + 2]!];
  };

  it('points straight out of a flat surface', () => {
    const normal = normalMap(fields(() => 30000), def);
    expect(at(normal, 5, 5)).toEqual([128, 128, 255]);
  });

  it('tilts toward +X on the right flank of a bump and toward +Y on its upper flank', () => {
    // A cone centred at (16, 16). Row 0 is the top of the image, so the upper flank has rows < 16.
    const normal = normalMap(
      fields((x, y) => Math.max(0, 40000 - 2400 * isqrt((x - 16) ** 2 + (y - 16) ** 2))),
      def,
    );
    const right = at(normal, 20, 16);
    const left = at(normal, 12, 16);
    const upper = at(normal, 16, 12);
    const lower = at(normal, 16, 20);
    expect(right[0]).toBeGreaterThan(128);
    expect(left[0]).toBeLessThan(128);
    expect(upper[1]).toBeGreaterThan(128);
    expect(lower[1]).toBeLessThan(128);
    // Every stored normal is close to unit length.
    for (let i = 0; i < normal.length; i += 3) {
      const [nx, ny, nz] = [normal[i]! - 127.5, normal[i + 1]! - 127.5, normal[i + 2]! - 127.5];
      const length = isqrt(Math.round(4 * (nx * nx + ny * ny + nz * nz)));
      expect(Math.abs(length - 255)).toBeLessThanOrEqual(2);
    }
  });

  it('wraps: a slope across the tile edge bends the edge texels as it bends the interior', () => {
    // A ridge on column 0: its left neighbour is column 31.
    const normal = normalMap(fields((x) => (x === 0 ? 50000 : 10000)), def);
    expect(at(normal, 31, 7)[0]).toBeLessThan(128);
    expect(at(normal, 1, 7)[0]).toBeGreaterThan(128);
    // Mirror images of one another, to within rounding.
    expect(Math.abs(at(normal, 31, 7)[0]! + at(normal, 1, 7)[0]! - 255)).toBeLessThanOrEqual(1);
  });
});

describe('the decoded texture budget', () => {
  it('fits the corridor six under the accepted 168 MB envelope, with mips and without', () => {
    expect(mipChainTexels(1024, 1024)).toBe(1_398_101);
    // 1024x256 down to 1x1: 262144 + 65536 + 16384 + 4096 + 1024 + 256 + 64 + 16 + 4 + 2 + 1.
    expect(mipChainTexels(1024, 256)).toBe(349_527);
    expect(CORRIDOR_SET_COUNT).toBe(6);
    const plain = corridorDecodedBytes(CATALOG, false);
    const mipped = corridorDecodedBytes(CATALOG, true);
    // Six sets of four 1024 x 1024 RGBA8 maps: 6 * 4 * 4 MiB = 96 MiB, and 4/3 of that with mips.
    expect(plain).toBe(6 * 4 * 1024 * 1024 * 4);
    expect(plain).toBe(100_663_296);
    expect(mipped).toBe(6 * 4 * 1_398_101 * 4);
    expect(mipped).toBe(134_217_696);
    expect(mipped).toBeLessThan(ACCEPTED_DECODED_ENVELOPE_BYTES);
    expect(ACCEPTED_DECODED_ENVELOPE_BYTES).toBe(168_000_000);
  });

  it('would not fit at 2048, which is why the sets are 1024', () => {
    const doubled = CATALOG.map((def) => ({ ...def, width: def.width * 2, height: def.height * 2 }));
    expect(corridorDecodedBytes(doubled, false)).toBe(402_653_184);
    expect(corridorDecodedBytes(doubled, false)).toBeGreaterThan(ACCEPTED_DECODED_ENVELOPE_BYTES);
  });

  it('charges every set in the catalog no more than a 1024 x 1024 set', () => {
    for (const def of CATALOG) {
      expect(def.width).toBeLessThanOrEqual(1024);
      expect(def.height).toBeLessThanOrEqual(1024);
      expect(decodedBytes(def, true)).toBeLessThanOrEqual(4 * 1_398_101 * 4);
    }
    expect(CATALOG.length).toBeGreaterThanOrEqual(6);
    expect(CATALOG.length).toBeLessThanOrEqual(10);
  });
});
