import { describe, expect, it } from 'vitest';
import {
  atlasVec3,
  buildNavigationWorld,
  islandId,
  localVec3,
  makeIsland,
  makeScene,
  placement,
} from '@exulanica/atlas-core';
import { worldFieldBufferShape } from '../src/playcanvas/world-field.js';

describe('scalable world-field buffers', () => {
  it('allocates every region and relationship trace instead of truncating at a presentation cap', () => {
    const islands = Array.from({ length: 120 }, (_value, index) => makeIsland({
      islandId: islandId(`region-${index}`),
      creationOrdinal: index,
      createdAt: index,
      placement: placement(atlasVec3(index * 12, 0, index % 7), 0, 1),
      rung: 4,
      scaleIsMetric: false,
      footprintRadiusLocal: 3,
      viewpointLocal: localVec3(0, 1.6, 0),
      anchors: [],
      layoutEntities: new Set(index < 2 ? ['shared' as never] : []),
    }));
    const world = buildNavigationWorld(makeScene(islands, 1, 1));
    const shape = worldFieldBufferShape(world);
    expect(shape.regionCapacity).toBe(world.regions.length);
    expect(shape.regionFloats).toBe(world.regions.length * 4);
    expect(shape.traceFloats).toBe(world.traces.length * 8);
    expect(shape.regionCapacity).toBeGreaterThan(5);
  });
});
