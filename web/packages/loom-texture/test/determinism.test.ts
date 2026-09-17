import { afterEach, describe, expect, it, vi } from 'vitest';
import { CATALOG, LIBRARY, definitionOf } from '../src/catalog.js';
import { SET_PROFILE_V1 } from '../src/classes.js';
import { encodeContainer, encodeContainerV2 } from '../src/container.js';
import type { TextureSetDefinition } from '../src/definition.js';
import { bakeClassMaps, bakeMaps, sampleFields } from '../src/maps.js';
import { sha256Hex } from '../src/publish.js';
import { FIELD_NAMES } from './support.js';

/**
 * Same inputs, same bytes; and nothing but the stated inputs reaches them.
 *
 * The two-directory `cmp` of a full bake is the operator-level proof and is recorded in
 * docs/texture-package.md; `published.test.ts` rebakes every set and compares with the committed
 * files. These are the fast, local forms of the same claim.
 */
const small = (def: TextureSetDefinition, size = 32): TextureSetDefinition => ({
  ...def,
  width: size,
  height: def.height === def.width ? size : size / 4,
});

/** Every map a set stores, in stored order, whichever container it is baked into. */
function storedMaps(def: TextureSetDefinition, size?: { width: number; height: number }): Uint8Array[] {
  if (def.containerProfile !== SET_PROFILE_V1) return bakeClassMaps(def, size).map((map) => map.bytes);
  const maps = bakeMaps(def, size);
  return [maps.baseColor, maps.normal, maps.orm, maps.relief];
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('a bake is a function of its stated inputs', () => {
  it('produces identical maps twice over, for every set', () => {
    for (const def of CATALOG) {
      const size = { width: 64, height: def.height / (def.width / 64) };
      const a = storedMaps(def, size);
      const b = storedMaps(def, size);
      expect(a.length, def.setId).toBe(b.length);
      a.forEach((map, index) => {
        expect(Buffer.from(map).equals(Buffer.from(b[index]!)), `${def.setId} map ${index}`).toBe(true);
      });
    }
  });

  it('never consults a clock or an ambient random source', () => {
    const refuse = (name: string) => () => {
      throw new Error(`the bake called ${name}`);
    };
    vi.spyOn(Math, 'random').mockImplementation(refuse('Math.random'));
    vi.spyOn(Date, 'now').mockImplementation(refuse('Date.now'));
    vi.spyOn(performance, 'now').mockImplementation(refuse('performance.now'));
    vi.spyOn(process, 'hrtime').mockImplementation(refuse('process.hrtime') as never);
    for (const def of CATALOG) {
      const tiny = small(def);
      expect(() => (tiny.containerProfile === SET_PROFILE_V1
        ? encodeContainer(tiny, bakeMaps(tiny), '0'.repeat(64))
        : encodeContainerV2(tiny, bakeClassMaps(tiny), '0'.repeat(64)))).not.toThrow();
    }
  });

  it('changes the digest, and only the header, when only the version changes', () => {
    const def = small(CATALOG[0]!);
    const maps = bakeMaps(def);
    const first = encodeContainer(def, maps, 'a'.repeat(64));
    const second = encodeContainer({ ...def, version: def.version + 1 }, maps, 'a'.repeat(64));
    expect(sha256Hex(first)).not.toBe(sha256Hex(second));
    // The texels are untouched: the maps are the same bytes at the end of both files.
    const tail = maps.baseColor.length + maps.normal.length + maps.orm.length + maps.relief.length;
    expect(Buffer.from(first.subarray(-tail)).equals(Buffer.from(second.subarray(-tail)))).toBe(true);
  });
});

describe('a different seed is a different surface', () => {
  it('holds for every set', () => {
    for (const source of LIBRARY) {
      const reseeded = (seed: number): TextureSetDefinition =>
        definitionOf({
          ...source,
          entry: { ...source.entry, recipe: { ...source.entry.recipe, seed } },
        });
      const a = reseeded(1);
      const b = reseeded(2);
      const size = { width: 64, height: a.height / (a.width / 64) };
      expect(
        Buffer.from(storedMaps(a, size)[0]!).equals(Buffer.from(storedMaps(b, size)[0]!)),
        a.setId,
      ).toBe(false);
    }
  });
});

describe('changing the resolution does not reshuffle the surface', () => {
  // Texel k of a 64-texel row and texel 3k + 1 of a 192-texel row sample the same point of the
  // tile exactly (see `src/tile.ts`), so every recipe field must agree there to the last unit.
  for (const def of CATALOG) {
    it(`${def.setId} samples the same values at shared points`, () => {
      const coarseWidth = def.width / 16;
      const coarseHeight = def.height / 16;
      const coarse = sampleFields(def, { width: coarseWidth, height: coarseHeight });
      const fine = sampleFields(def, { width: coarseWidth * 3, height: coarseHeight * 3 });
      const disagreements: string[] = [];
      for (const name of FIELD_NAMES) {
        for (let j = 0; j < coarseHeight; j += 1) {
          for (let i = 0; i < coarseWidth; i += 1) {
            const a = coarse[name][j * coarseWidth + i];
            const b = fine[name][(3 * j + 1) * coarseWidth * 3 + 3 * i + 1];
            if (a !== b) disagreements.push(`${name} at (${i}, ${j}): ${a} vs ${b}`);
          }
        }
      }
      expect(disagreements.slice(0, 5)).toEqual([]);
    });
  }
});
