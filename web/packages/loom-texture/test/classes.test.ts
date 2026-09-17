import { describe, expect, it } from 'vitest';
import { CATALOG } from '../src/catalog.js';
import {
  MATERIAL_CLASSES,
  type MaterialClass,
  SET_PROFILE_V2,
  channelsOf,
  classLayout,
  classParameters,
  coveragePermille,
} from '../src/classes.js';
import { encodeContainer, encodeContainerV2, readContainer } from '../src/container.js';
import type { TextureSetDefinition } from '../src/definition.js';
import { FULL } from '../src/integer.js';
import { bakeClassMaps, bakeMaps, classMaps, sampleFields } from '../src/maps.js';
import { valueNoise } from '../src/noise.js';
import { rollMismatches } from './support.js';

/**
 * The v2 bake of a procedural set, class by class.
 *
 * The pattern here is synthetic and periodic by construction (value noise on whole cells per tile),
 * and sets every field a class can read, so each class's maps are measured against the one bake
 * they share: a relief class keeps exactly the bytes the v1 bake computes for the same fields, and
 * what it adds (coverage) or replaces (transmission) is the field quantised the way every other
 * channel is.
 */
const LICENCE = 'c'.repeat(64);
const SIZE = 32;
const FILM = { srgb: [150, 144, 132], roughnessPermille: 650 } as const;

function definition(materialClass: MaterialClass): TextureSetDefinition {
  const brick = CATALOG.find((def) => def.setId === 'cc0.brick-running-bond')!;
  const relief = materialClass !== 'glazing';
  return {
    ...brick,
    setId: `test.${materialClass}`,
    width: SIZE,
    height: SIZE,
    containerProfile: SET_PROFILE_V2,
    materialClass,
    heightRangeMm: relief ? brick.heightRangeMm : null,
    cavity: relief ? brick.cavity : null,
    film: relief ? null : FILM,
    pattern: () => (x, y, out) => {
      out.height = valueNoise(x, y, 4, 4, 11);
      out.red = valueNoise(x, y, 3, 5, 12);
      out.green = valueNoise(x, y, 5, 3, 13);
      out.blue = valueNoise(x, y, 2, 2, 14);
      out.roughness = valueNoise(x, y, 6, 6, 15);
      out.metalness = valueNoise(x, y, 1, 1, 16);
      out.occlusion = 65536;
      out.coverage = valueNoise(x, y, 8, 8, 17);
      out.transmission = FULL - (valueNoise(x, y, 7, 7, 18) >> 3);
    },
  };
}

const v1Twin = (def: TextureSetDefinition): TextureSetDefinition => {
  const brick = CATALOG.find((set) => set.setId === 'cc0.brick-running-bond')!;
  return { ...def, containerProfile: brick.containerProfile, materialClass: 'opaque' };
};

describe('a v2 procedural set', () => {
  for (const materialClass of MATERIAL_CLASSES) {
    it(`of class ${materialClass} is its class layout, and its reader reads it back`, () => {
      const def = definition(materialClass);
      const maps = bakeClassMaps(def);
      expect(maps.map((map) => map.descriptor)).toEqual(classLayout(materialClass, 'procedural'));
      const bytes = encodeContainerV2(def, maps, LICENCE);
      const read = readContainer(bytes);
      expect(read.profile).toBe(SET_PROFILE_V2);
      expect(read.materialClass).toBe(materialClass);
      expect(read.makerKind).toBe('procedural');
      expect(channelsOf(read.layout)).toEqual(channelsOf(classLayout(materialClass, 'procedural')));
      const colour = read.maps.get('base_color_coverage');
      expect(read.header.class).toEqual(
        classParameters(
          materialClass,
          colour === undefined ? null : coveragePermille(colour),
          materialClass === 'glazing' ? FILM : null,
        ),
      );
      expect('height_range_mm' in read.header).toBe(materialClass !== 'glazing');
      expect('cavity' in read.header).toBe(materialClass !== 'glazing');
      for (const map of maps) {
        expect(Buffer.from(read.maps.get(map.descriptor.name)!).equals(Buffer.from(map.bytes))).toBe(true);
      }
      // Bytes are a function of the definition alone.
      expect(Buffer.from(encodeContainerV2(def, bakeClassMaps(def), LICENCE)).equals(Buffer.from(bytes))).toBe(true);
    });
  }

  for (const materialClass of ['opaque', 'cutout', 'decal'] as const) {
    it(`of class ${materialClass} keeps the v1 bake's colour, normal x and y, and orm exactly`, () => {
      const def = definition(materialClass);
      const fields = sampleFields(def);
      const v1 = bakeMaps(v1Twin(def));
      const maps = new Map(classMaps(fields, def).map((map) => [map.descriptor.name, map.bytes]));
      const colour = maps.get(materialClass === 'opaque' ? 'base_color' : 'base_color_coverage')!;
      const stride = materialClass === 'opaque' ? 3 : 4;
      for (let texel = 0; texel < SIZE * SIZE; texel += 1) {
        expect([...colour.subarray(texel * stride, texel * stride + 3)]).toEqual([...v1.baseColor.subarray(texel * 3, texel * 3 + 3)]);
        expect([...maps.get('normal')!.subarray(texel * 2, texel * 2 + 2)]).toEqual([...v1.normal.subarray(texel * 3, texel * 3 + 2)]);
      }
      expect(Buffer.from(maps.get('orm')!).equals(Buffer.from(v1.orm))).toBe(true);
      if (stride === 4) {
        const coverage = [...Array(SIZE * SIZE).keys()].map((texel) => colour[texel * 4 + 3]);
        expect(coverage).toEqual([...fields.coverage].map((value) => Math.round((value * 255) / FULL)));
      }
    });
  }

  it('of class glazing stores transmission and roughness, and no height field', () => {
    const def = definition('glazing');
    const fields = sampleFields(def);
    const [colour, surface] = classMaps(fields, def);
    expect(colour!.descriptor.name).toBe('base_color');
    expect(surface!.descriptor.name).toBe('transmission_roughness');
    for (let texel = 0; texel < SIZE * SIZE; texel += 1) {
      expect(surface!.bytes[texel * 2]).toBe(Math.round((fields.transmission[texel]! * 255) / FULL));
      expect(surface!.bytes[texel * 2 + 1]).toBe(Math.round((fields.roughness[texel]! * 255) / FULL));
    }
  });

  for (const materialClass of MATERIAL_CLASSES) {
    it(`of class ${materialClass} tiles by construction`, () => {
      const def = definition(materialClass);
      const base = bakeClassMaps(def);
      for (const [du, dv] of [[37, 23], [-3 * SIZE - 5, 2 * SIZE + 11]] as const) {
        const moved = bakeClassMaps(def, { offsetU: du, offsetV: dv });
        const planes = Object.fromEntries(base.map((map, index) => [
          map.descriptor.name,
          [map.bytes, moved[index]!.bytes, map.descriptor.components] as const,
        ]));
        expect(rollMismatches(SIZE, SIZE, planes, du, dv)).toEqual(
          Object.fromEntries(base.map((map) => [map.descriptor.name, 0])),
        );
      }
    });
  }

  it('is never written as v1, and a v1 set is never written as v2', () => {
    const def = definition('cutout');
    expect(() => encodeContainer(def, bakeMaps(v1Twin(def)), LICENCE)).toThrow(/not a v1 set/);
    const v1 = { ...CATALOG[0]!, width: SIZE, height: SIZE };
    expect(() => encodeContainerV2(v1, [], LICENCE)).toThrow(/is a v1 set/);
    expect(() => classMaps(sampleFields(v1), v1)).toThrow(/is a v1 set/);
  });

  it('refuses a preview-sized bake as the set itself', () => {
    const def = definition('decal');
    const preview = bakeClassMaps(def, { width: SIZE / 2, height: SIZE / 2 });
    expect(() => encodeContainerV2(def, preview, LICENCE)).toThrow(/preview/);
  });
});
