import { describe, expect, it } from 'vitest';
import { atlasVec3, islandId, localVec3, makeIsland, placement } from '@exulanica/atlas-core';
import { sourceMediaForIsland } from '../src/playcanvas/source-media.js';

describe('source-only Atlas regions', () => {
  it('uses explicit authorized topology sources without inventing occurrence anchors', () => {
    const island = makeIsland({ islandId: islandId('region-a'), createdAt: 0,
      placement: placement(atlasVec3(0, 0, 0), 0, 1), rung: 4, scaleIsMetric: false,
      footprintRadiusLocal: 5, viewpointLocal: localVec3(0, 1.6, 0), anchors: [], layoutEntities: new Set(),
    });
    const source = { evidenceRef: 'evidence-a', regionId: 'region-a', captureIds: ['capture-a'],
      title: 'Source', capturedLabel: '', url: 'blob:authorized-a', available: true, accent: '', alt: 'Source' };
    const outside = { ...source, regionId: 'region-b', evidenceRef: 'outside', url: 'blob:other' };
    const catalog = new Map([['slot-a', source], ['evidence-a', source], ['slot-b', outside]]);
    expect(sourceMediaForIsland(island, catalog)).toEqual([source]);
    expect(island.anchors).toEqual([]);
    expect(island.rung).toBe(4);
    expect(sourceMediaForIsland(island, new Map())).toEqual([]);
  });
});
