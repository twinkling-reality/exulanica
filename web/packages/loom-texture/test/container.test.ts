import { describe, expect, it } from 'vitest';
import { canonicalBytes, canonicalJson } from '../src/canonical-json.js';
import { CATALOG } from '../src/catalog.js';
import { SET_PROFILE_V1, SET_PROFILE_V2, classLayout } from '../src/classes.js';
import {
  CONTAINER_MAGIC,
  MAP_LAYOUT,
  SET_PROFILE,
  TRUTH,
  decodeContainer,
  encodeContainer,
  encodeContainerV2,
  readContainer,
} from '../src/container.js';
import type { TextureSetDefinition } from '../src/definition.js';
import { LICENCE_ID } from '../src/licence.js';
import { bakeClassMaps, bakeMaps } from '../src/maps.js';

const LICENCE = 'b'.repeat(64);
const tiny = (def: TextureSetDefinition): TextureSetDefinition => ({
  ...def,
  width: 16,
  height: def.height === def.width ? 16 : 4,
});

function everyNumber(value: unknown, path: string, out: string[]): void {
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) out.push(`${path} = ${value}`);
  } else if (Array.isArray(value)) {
    value.forEach((item, index) => everyNumber(item, `${path}[${index}]`, out));
  } else if (value !== null && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) everyNumber(item, `${path}.${key}`, out);
  }
}

describe('a published set of material class', () => {
  for (const def of CATALOG.filter((candidate) => candidate.containerProfile === SET_PROFILE_V2)) {
    it(`${def.setId} round-trips as its class's container and states everything it holds`, () => {
      const small = tiny(def);
      const bytes = encodeContainerV2(small, bakeClassMaps(small), LICENCE);
      expect(new TextDecoder().decode(bytes.subarray(0, 4))).toBe(CONTAINER_MAGIC);
      const read = readContainer(bytes);
      expect(read.profile).toBe(SET_PROFILE_V2);
      expect(read.materialClass).toBe(def.materialClass);
      expect(read.makerKind).toBe('procedural');
      expect(read.header.set_id).toBe(def.setId);
      expect(read.header.version).toBe(def.version);
      expect(read.header.seed).toBe(def.seed);
      expect(read.header.truth).toBe(TRUTH);
      expect(read.header.licence).toEqual({ id: LICENCE_ID, sha256: LICENCE });
      expect(read.header.extent_mm).toEqual({ u: def.extentU, v: def.extentV });
      // A class whose bake has a height field states its range; glazing states none.
      expect(read.header.height_range_mm).toBe(def.heightRangeMm ?? undefined);
      const floats: string[] = [];
      everyNumber(read.header, '$', floats);
      expect(floats).toEqual([]);
      expect(read.layout.map((map) => map.name)).toEqual(
        classLayout(def.materialClass, 'procedural').map((map) => map.name),
      );
    });
  }
});

describe('the container', () => {
  for (const def of CATALOG.filter((candidate) => candidate.containerProfile === SET_PROFILE_V1)) {
    it(`${def.setId} round-trips and states everything it holds`, () => {
      const small = tiny(def);
      const maps = bakeMaps(small);
      const bytes = encodeContainer(small, maps, LICENCE);
      expect(new TextDecoder().decode(bytes.subarray(0, 4))).toBe(CONTAINER_MAGIC);

      const { header, maps: decoded } = decodeContainer(bytes);
      expect(header.profile).toBe(SET_PROFILE);
      expect(header.set_id).toBe(def.setId);
      expect(header.version).toBe(def.version);
      expect(header.seed).toBe(def.seed);
      expect(header.truth).toBe(TRUTH);
      expect(header.licence).toEqual({ id: LICENCE_ID, sha256: LICENCE });
      // The load-bearing field: a physical extent, whole millimetres, both axes.
      expect(header.extent_mm).toEqual({ u: def.extentU, v: def.extentV });
      expect(Number.isSafeInteger(def.extentU) && def.extentU > 0).toBe(true);
      expect(Number.isSafeInteger(def.extentV) && def.extentV > 0).toBe(true);
      expect(header.height_range_mm).toBe(def.heightRangeMm);

      // Integers only, anywhere in the header.
      const floats: string[] = [];
      everyNumber(header, '$', floats);
      expect(floats).toEqual([]);

      // The packing is stated map by map, with an explicit sRGB flag on each.
      expect(header.maps.map((m) => [m.name, m.components, m.holds, m.srgb])).toEqual([
        ['base_color', 3, ['red', 'green', 'blue'], true],
        ['normal', 3, ['normal_x', 'normal_y', 'normal_z'], false],
        ['orm', 3, ['occlusion', 'roughness', 'metalness'], false],
        ['height', 1, ['height'], false],
      ]);

      // Only the first map is aligned, and the rest follow with no gap.
      const first = header.maps[0]!;
      expect(first.byte_offset % 16).toBe(0);
      expect(first.byte_offset).toBe(Math.ceil((8 + new DataView(bytes.buffer).getUint32(4, true)) / 16) * 16);
      header.maps.forEach((entry, index) => {
        if (index > 0) {
          const previous = header.maps[index - 1]!;
          expect(entry.byte_offset).toBe(previous.byte_offset + previous.byte_length);
        }
        expect(entry.byte_length).toBe(small.width * small.height * entry.components);
      });
      const last = header.maps.at(-1)!;
      expect(last.byte_offset + last.byte_length).toBe(bytes.length);

      expect(Buffer.from(decoded.base_color).equals(Buffer.from(maps.baseColor))).toBe(true);
      expect(Buffer.from(decoded.normal).equals(Buffer.from(maps.normal))).toBe(true);
      expect(Buffer.from(decoded.orm).equals(Buffer.from(maps.orm))).toBe(true);
      expect(Buffer.from(decoded.height).equals(Buffer.from(maps.relief))).toBe(true);
    });
  }

  it('refuses a preview-sized bake as the set itself', () => {
    const def = CATALOG[0]!;
    expect(() => encodeContainer(def, bakeMaps(tiny(def)), LICENCE)).toThrow(/preview/);
  });

  describe('the reader refuses what the writer would not have written', () => {
    const def = tiny(CATALOG[0]!);
    const good = encodeContainer(def, bakeMaps(def), LICENCE);
    const headerLength = new DataView(good.buffer).getUint32(4, true);

    it('a wrong magic', () => {
      const bad = good.slice();
      bad[0] = 0x58;
      expect(() => decodeContainer(bad)).toThrow(/magic/);
    });

    it('a truncated file', () => {
      expect(() => decodeContainer(good.subarray(0, good.length - 1))).toThrow();
      expect(() => decodeContainer(good.subarray(0, 6))).toThrow();
    });

    it('trailing bytes', () => {
      const bad = new Uint8Array(good.length + 1);
      bad.set(good);
      expect(() => decodeContainer(bad)).toThrow(/end/);
    });

    it('a header that is valid JSON but not canonical', () => {
      // The same members, the same length, one key moved to the front.
      const text = new TextDecoder().decode(good.subarray(8, 8 + headerLength));
      const parsed = JSON.parse(text) as Record<string, unknown>;
      const reordered = JSON.stringify({ version: parsed.version, ...parsed });
      expect(reordered).not.toBe(text);
      expect(reordered.length).toBe(text.length);
      const bad = good.slice();
      bad.set(new TextEncoder().encode(reordered), 8);
      expect(() => decodeContainer(bad)).toThrow(/canonical/);
    });

    it('padding that is not spaces', () => {
      const start = first(good);
      if (start > 8 + headerLength) {
        const bad = good.slice();
        bad[8 + headerLength] = 0;
        expect(() => decodeContainer(bad)).toThrow(/padding/);
      }
    });
  });
});

function first(bytes: Uint8Array): number {
  return decodeContainer(bytes).header.maps[0]!.byte_offset;
}

describe('canonical JSON', () => {
  it('matches exulanica.canonical.canonical_json byte for byte', () => {
    // Produced by the Python function from the same value; see docs/texture-package.md.
    const value = {
      z: 1,
      a: [3, -2, 0, { y: true, b: null, a: false }],
      m: 'quote " and back\\\\slash',
      extent_mm: { v: 1800, u: 1800 },
      big: 9007199254740991,
      neg: -9007199254740991,
      empty: {},
      list: [],
    };
    expect(canonicalJson(value)).toBe(
      '{"a":[3,-2,0,{"a":false,"b":null,"y":true}],"big":9007199254740991,"empty":{},'
        + '"extent_mm":{"u":1800,"v":1800},"list":[],"m":"quote \\" and back\\\\\\\\slash",'
        + '"neg":-9007199254740991,"z":1}',
    );
    expect(canonicalBytes({ b: 1, a: 2 })).toEqual(new TextEncoder().encode('{"a":2,"b":1}'));
  });

  it.each([
    ['a float', { x: 0.5 }],
    ['NaN', { x: Number.NaN }],
    ['infinity', { x: Number.POSITIVE_INFINITY }],
    ['an unsafe integer', { x: 2 ** 53 }],
    ['a non-ASCII string', { x: 'café' }],
    ['a control character', { x: 'a\nb' }],
    ['undefined', { x: undefined }],
    ['a class instance', { x: new Map() }],
    ['a bigint', { x: 1n }],
  ])('refuses %s', (_name, value) => {
    expect(() => canonicalJson(value as never)).toThrow();
  });

  it('declares the four maps in packing order', () => {
    expect(MAP_LAYOUT.map((m) => m.name)).toEqual(['base_color', 'normal', 'orm', 'height']);
  });
});
