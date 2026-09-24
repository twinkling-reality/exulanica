import { describe, expect, it } from 'vitest';
import { islandId } from '@exulanica/atlas-core';
import { describeWorldKind, type AuthoredRegion, type WorldKind } from '@exulanica/atlas-react/playcanvas';
import type { GeneratedTileMount } from '@exulanica/atlas-react/generated-tile';
import { aboutWorld, aboutWorldLayers } from '../src/world-about.js';

/*
 * What the About panel says the open world is, for every kind of world the app hands the
 * renderer. The kinds are the ones `atlas-react/test/binding/world-kinds.ts` names
 * (WORLD_KINDS), built here from the same kind of options, and each is decided by the renderer's
 * own `describeWorldKind`. A sentence must be true of every world of its kind, so each test
 * reads it for what it claims.
 */

const STARTER = islandId('region:starter');
const ENDLESS: AuthoredRegion = {
  regionId: STARTER,
  module: { key: 'region.authored-ground', version: 2 },
  ground: { kind: 'endless', elevationMm: 0 },
  spawn: { xMm: 0, yMm: 0, zMm: 4000, yawMicroradians: 0 },
};
/** The version-1 starter's ground: 24 m by 24 m, as `exulanica/world/starter.py` states it. */
const FLAT_V1: AuthoredRegion = {
  regionId: STARTER,
  module: { key: 'region.authored-ground', version: 1 },
  ground: { kind: 'flat', halfWidthMm: 12_000, halfDepthMm: 12_000, elevationMm: 0 },
  spawn: { xMm: 0, yMm: 0, zMm: 4000, yawMicroradians: 0 },
};
const DISTRICT = { document: {} as never, residentBytes: 100 };
const TILE = { attach: () => ({}) } as unknown as GeneratedTileMount;

type Options = Parameters<typeof describeWorldKind>[0];
const kind = (options: Options): WorldKind => describeWorldKind(options);

/** What only a district's sentence may claim: the forms its admitted sources give it. */
const DISTRICT_CLAIMS = [/building forms/i, /sidewalk/i, /BUILDING footprints/];
/** A sentence is the table's, never its key, and every placeholder in it is filled. */
function expectPlainSentence(sentence: string): void {
  expect(sentence).not.toMatch(/world\.about\./);
  expect(sentence).not.toMatch(/\{\w+\}/);
}
function expectNoDistrictClaim(sentence: string): void {
  for (const claim of DISTRICT_CLAIMS) expect(sentence).not.toMatch(claim);
}

describe('the About panel says what the open world is, by its kind', () => {
  it('authored-endless: a starter on open ground with no edge, not rebuilt from anything', () => {
    const sentence = aboutWorld(kind({ authoredRegion: ENDLESS }));
    expect(sentence).toBe('An authored starter world on open ground with no edge. The ground is authored, '
      + 'not rebuilt from photographs or map data.');
    expectPlainSentence(sentence);
    expectNoDistrictClaim(sentence);
  });

  it('authored-with-estimate: a placed photo estimate does not change what the ground is', () => {
    // The estimate stands on the starter's ground; the sentence claims nothing about what stands
    // on it, so it stays true with one placed.
    const estimate = { instanceId: 'estimate:test' };
    const withEstimate = kind({ authoredRegion: ENDLESS, ...{ authoredPointMaps: [estimate] } } as Options);
    expect(aboutWorld(withEstimate)).toBe(aboutWorld(kind({ authoredRegion: ENDLESS })));
    expect(aboutWorld(withEstimate)).not.toMatch(/nothing (stands|is placed)|empty/i);
  });

  it('authored-flat: a bounded starter states its own size, read from its ground', () => {
    const sentence = aboutWorld(kind({ authoredRegion: FLAT_V1 }));
    expect(sentence).toBe('An authored starter world on bounded ground, 24 m by 24 m. The ground is authored, '
      + 'not rebuilt from photographs or map data.');
    const oblong = aboutWorld(kind({ authoredRegion: {
      ...FLAT_V1, ground: { kind: 'flat', halfWidthMm: 12_250, halfDepthMm: 8_000, elevationMm: 0 } } }));
    expect(oblong).toContain('24.5 m by 16 m');
    expectPlainSentence(oblong);
    expectNoDistrictClaim(sentence);
  });

  it('personal-regions: laid out from photographs, drawn only as far as they support', () => {
    const sentence = aboutWorld(kind({}));
    expect(sentence).toBe('A world laid out from your photographs. Each region is drawn only as far as its '
      + 'photographs support.');
    expectPlainSentence(sentence);
    expectNoDistrictClaim(sentence);
  });

  it('owned-district: source-backed forms, and its own layer sentences while the memory layer changes', () => {
    const district = kind({ ownedDistrict: DISTRICT });
    expect(aboutWorld(district)).toBe('Source-backed building forms and sidewalks. Surface details are provisional.');
    expect(aboutWorldLayers(district, true)).toBe(
      'City and memory layers are intentionally composed. Purple memory forms are not city semantics.');
    expect(aboutWorldLayers(district, false)).toBe(
      'Official BUILDING footprints. Memory and fantasy layers are separate from the geographic view.');
  });

  it('generated-tile: generated for development evaluation, not recorded from a real place', () => {
    const sentence = aboutWorld(kind({ generatedTile: TILE }));
    expect(sentence).toBe('A generated street tile, opened for development evaluation. Its streets and building '
      + 'forms are generated, not recorded from a real place.');
    expectPlainSentence(sentence);
    expect(sentence).not.toMatch(/sidewalk|BUILDING footprints|source-backed/i);
  });

  it('hiding or showing the memory layer changes no sentence of a ground without a layer of its own', () => {
    for (const options of [{ authoredRegion: ENDLESS }, { authoredRegion: FLAT_V1 }, {}, { generatedTile: TILE }] as Options[]) {
      const world = kind(options);
      expect(aboutWorldLayers(world, true)).toBe(aboutWorld(world));
      expect(aboutWorldLayers(world, false)).toBe(aboutWorld(world));
    }
  });
});
