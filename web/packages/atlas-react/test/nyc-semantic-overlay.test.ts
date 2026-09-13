import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  crs84IntegerToLocal,
  featureAlongReticle,
  featureAtLocalPoint,
  footprintLineGeometry,
  localizeNYCFeatures,
  type NYCSemanticFeature,
} from '../src/playcanvas/nyc-semantic-overlay.js';
import { NYC_REFERENCE_FRAME } from '../src/playcanvas/nyc-reference-frame.js';

const frame = NYC_REFERENCE_FRAME;
const feature: NYCSemanticFeature = {
  id: '0123456789abcdef0123456789abcdef',
  providerFeatureId: 'doitt_id:2327',
  bbox: [-739_904_139, 407_238_475, -739_902_608, 407_239_894],
  footprint: [[[
    [-739_904_139, 407_238_475],
    [-739_902_608, 407_238_475],
    [-739_902_608, 407_239_894],
    [-739_904_139, 407_239_894],
    [-739_904_139, 407_238_475],
  ]]],
  renderBatchId: 0,
  name: null,
  bin: 'bin:1006070',
};

describe('independent NYC Open Data semantic geometry', () => {
  it('converts pinned CRS84 integers into the reference local east/south frame', () => {
    expect(crs84IntegerToLocal(-739_885_000, 407_220_000, 10_000_000, frame))
      .toEqual([expect.closeTo(0, 5), expect.closeTo(0, 5)]);
    const east = crs84IntegerToLocal(-739_884_000, 407_220_000, 10_000_000, frame);
    const north = crs84IntegerToLocal(-739_885_000, 407_221_000, 10_000_000, frame);
    expect(east[0]).toBeGreaterThan(8);
    expect(north[1]).toBeLessThan(-10);
  });

  it('selects only the independent footprint and its stable identity', () => {
    const [local] = localizeNYCFeatures([feature], 10_000_000, frame);
    expect(local).toBeDefined();
    const ring = local!.localFootprint[0]![0]!;
    const centre: readonly [number, number] = [
      (ring[0]![0] + ring[2]![0]) / 2,
      (ring[0]![1] + ring[2]![1]) / 2,
    ];
    expect(featureAtLocalPoint([local!], centre)?.providerFeatureId).toBe('doitt_id:2327');
    expect(featureAlongReticle(
      [local!],
      [centre[0], 1.68, centre[1]],
      [0, -1, 0],
    )?.bin).toBe('bin:1006070');
    expect(featureAtLocalPoint([local!], [centre[0] + 1000, centre[1]])).toBeNull();
  });

  it('has no Google tile object in its input or selection contract', () => {
    expect(Object.keys(feature).sort()).toEqual([
      'bbox', 'bin', 'footprint', 'id', 'name', 'providerFeatureId', 'renderBatchId',
    ]);
    expect(JSON.stringify(feature).toLowerCase()).not.toContain('google');
    const implementation = readFileSync(
      new URL('../src/playcanvas/nyc-semantic-overlay.ts', import.meta.url),
      'utf8',
    );
    expect(implementation).not.toMatch(/google-tiles|GoogleTile|googleTiles/);
  });

  it('builds only exact closed line edges for a concave exterior and its hole', () => {
    const geometry = footprintLineGeometry([[
      [[0, 0], [4, 0], [4, 4], [2, 2], [0, 4], [0, 0]],
      [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]],
    ]], 0.25);

    expect(geometry.primitive).toBe('lines');
    expect(geometry.indices).toEqual([
      0, 1, 1, 2, 2, 3, 3, 4, 4, 0,
      5, 6, 6, 7, 7, 8, 8, 5,
    ]);
    expect(geometry.positions).toEqual([
      0, 0.25, 0, 4, 0.25, 0, 4, 0.25, 4, 2, 0.25, 2, 0, 0.25, 4,
      1, 0.25, 1, 2, 0.25, 1, 2, 0.25, 2, 1, 0.25, 2,
    ]);
    expect(geometry.indices).toHaveLength(9 * 2);
    const edges = Array.from({ length: geometry.indices.length / 2 }, (_, index) =>
      geometry.indices.slice(index * 2, index * 2 + 2));
    expect(edges).not.toContainEqual([0, 2]);
    expect(edges).not.toContainEqual([0, 3]);
  });
});
