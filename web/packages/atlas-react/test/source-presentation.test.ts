import { describe, expect, it } from 'vitest';
import {
  atlasLandscapeSurface, atlasVec3, buildNavigationWorld, composeAtlasWorld,
  islandId, localVec3, makeIsland, makeScene, placement,
} from '@exulanica/atlas-core';
import {
  initialAtlasCameraState, sourceFirstArrivalPose, sourceGroveScene,
} from '../src/playcanvas/atlas-binding.js';

const island = makeIsland({
  islandId: islandId('reference-source'), createdAt: 0,
  placement: placement(atlasVec3(12, 0, -4), 0.35, 1.2),
  rung: 4, scaleIsMetric: false, footprintRadiusLocal: 7,
  viewpointLocal: localVec3(0, 1.6, 0), anchors: [], layoutEntities: new Set(),
});
const scene = makeScene([island], 1, 1);
const available = new Set<typeof island.islandId>();

describe('source presentation boundary', () => {
  it('omits every source grove island in inspection while preserving authoritative scene and topology', () => {
    const topologyBefore = composeAtlasWorld(scene, { availableReconstruction: available });
    const groveInput = sourceGroveScene(scene, available, 'inspection');
    expect(groveInput.islands).toEqual([]);
    expect(groveInput).not.toBe(scene);
    expect(scene.islands).toEqual([island]);
    expect(scene.islands[0]!.rung).toBe(4);
    expect(composeAtlasWorld(scene, { availableReconstruction: available })).toEqual(topologyBefore);
  });

  it('keeps ordinary world presentation as the default, including unavailable reconstruction fallback', () => {
    expect(sourceGroveScene(scene, available).islands).toEqual([island]);
    expect(sourceGroveScene(scene, available)).toEqual(sourceGroveScene(scene, available, 'world'));
    const reconstructed = { ...island, rung: 3 as const };
    const other = makeScene([reconstructed], 1, 1);
    expect(sourceGroveScene(other, available).islands[0]!.rung).toBe(4);
    expect(sourceGroveScene(other, new Set([island.islandId])).islands[0]).toBe(reconstructed);
    expect(other.islands[0]!.rung).toBe(3);
  });

  it('keeps the same grounded startup position but stops aiming upward at an absent source', () => {
    const world = buildNavigationWorld(scene, atlasLandscapeSurface());
    const ordinary = initialAtlasCameraState(scene, world);
    expect(initialAtlasCameraState(scene, world, 'world')).toEqual(ordinary);
    const inspection = initialAtlasCameraState(scene, world, 'inspection');
    expect([inspection.x, inspection.y, inspection.z, inspection.yaw])
      .toEqual([ordinary.x, ordinary.y, ordinary.z, ordinary.yaw]);
    expect(ordinary.pitch).toBeGreaterThan(0);
    expect(inspection.pitch).toBe(-0.085);
  });

  it('preserves the entire validated arrival pose when the source is inspector-only', () => {
    const arrival = { position: atlasVec3(10, 1.62, 1), yaw: 0.4, pitch: -0.12 };
    expect(sourceFirstArrivalPose(island, arrival, 'inspection')).toBe(arrival);
    expect(sourceFirstArrivalPose(island, arrival).position).toBe(arrival.position);
    expect(sourceFirstArrivalPose(island, arrival).pitch).not.toBe(arrival.pitch);
  });
});
