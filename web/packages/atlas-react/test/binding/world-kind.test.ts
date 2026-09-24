/**
 * The binding asks what kind of world it is drawing in one place, and nowhere else.
 *
 * `describeWorldKind` turns the options into one description: the ground and its data, city
 * scale, where fog is mixed and what is drawn at first.
 * The table below pins it for every combination the app can pass, and the scan below keeps the
 * binding from asking the options again: a kind read written into `atlas-binding.ts` fails here
 * even when every pinned world still builds the same.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  authoredFieldSupport,
  authoredRegionOf,
  describeWorldKind,
  type WorldKindOptions,
} from '../../src/playcanvas/world-kind.js';
import { DISTRICT_DOCUMENT, ENDLESS_REGION, FLAT_REGION, stubTileMount } from './world-kinds.js';

const district = { document: DISTRICT_DOCUMENT as never, residentBytes: 100 };
const flags = (options: WorldKindOptions) => {
  const { ground, ...rest } = describeWorldKind(options);
  return { form: ground.form, ...rest };
};

describe('describeWorldKind', () => {
  it('describes every combination the app passes', () => {
    expect(flags({})).toEqual({ form: 'scene-regions', city: false,
      displaySpaceFog: true, fieldVisible: true, memoryLayerVisible: true });
    expect(flags({ authoredRegion: ENDLESS_REGION })).toEqual({ form: 'authored-endless',
      city: false, displaySpaceFog: true, fieldVisible: true, memoryLayerVisible: true });
    expect(flags({ authoredRegion: FLAT_REGION })).toEqual({ form: 'authored-flat',
      city: false, displaySpaceFog: true, fieldVisible: true, memoryLayerVisible: true });
    expect(flags({ ownedDistrict: district })).toEqual({ form: 'owned-district',
      city: true, displaySpaceFog: true, fieldVisible: false, memoryLayerVisible: false });
    expect(flags({ generatedTile: stubTileMount() })).toEqual({ form: 'generated-tile',
      city: true, displaySpaceFog: false, fieldVisible: false, memoryLayerVisible: false });
  });

  it('carries the ground it names, so nothing downstream reads the options again', () => {
    const tile = stubTileMount();
    const described = describeWorldKind({ generatedTile: tile });
    expect(described.ground).toEqual({ form: 'generated-tile', tile });
    expect(authoredRegionOf(describeWorldKind({ authoredRegion: FLAT_REGION }))).toBe(FLAT_REGION);
    expect(authoredRegionOf(described)).toBeNull();
    expect(authoredFieldSupport(FLAT_REGION, 1200)).toEqual({ halfWidth: 12, halfDepth: 8, elevation: 0 });
    expect(authoredFieldSupport(ENDLESS_REGION, 1200)).toEqual({ kind: 'endless', elevation: 0, reach: 1200 });
    expect(authoredFieldSupport(null, 1200)).toBeUndefined();
  });

  it('refuses the two combinations no world can be, by name', () => {
    expect(() => describeWorldKind({ ownedDistrict: district, generatedTile: stubTileMount() }))
      .toThrow('A generated tile replaces the owned district; pass one or the other');
    expect(() => describeWorldKind({ authoredRegion: ENDLESS_REGION, ownedDistrict: district }))
      .toThrow('An authored starter region cannot replace geographic ground');
    expect(() => describeWorldKind({ authoredRegion: FLAT_REGION, generatedTile: stubTileMount() }))
      .toThrow('An authored starter region cannot replace geographic ground');
  });
});

/** Every way of asking the options, or an authored ground, what kind of world this is. */
const KIND_READ = /options\.(authoredRegion|ownedDistrict|generatedTile)\b|\.ground\.kind\b/g;

describe('where the world kind is read', () => {
  const read = (file: string) => readFileSync(new URL(`../../src/playcanvas/${file}`, import.meta.url), 'utf8');

  it('is never in the binding', () => {
    expect(read('atlas-binding.ts').match(KIND_READ) ?? []).toEqual([]);
  });

  it('is in the one module that decides it (the control: the scan does find a kind read)', () => {
    expect((read('world-kind.ts').match(KIND_READ) ?? []).length).toBeGreaterThan(0);
  });
});
