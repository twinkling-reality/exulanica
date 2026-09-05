import { describe, expect, it } from 'vitest';
import {
  atlasLandscapeSurface, atlasVec3, buildNavigationWorld, composeAtlasWorld,
  islandId, localVec3, makeIsland, makeScene, placement, planResidency,
} from '@exulanica/atlas-core';
import {
  initialAtlasCameraState, pointMapResidencyCost, recoveredCameraState, sourceFirstArrivalPose, sourceGroveScene,
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

describe('arrival at a reconstructed region', () => {
  const reconstructed = makeIsland({
    islandId: islandId('reconstructed'), createdAt: 0,
    placement: placement(atlasVec3(20, 0, -6), Math.PI / 2, 1.5),
    rung: 3, scaleIsMetric: false, footprintRadiusLocal: 6,
    viewpointLocal: localVec3(2, 1.6, 0), viewpointForwardLocal: localVec3(-1, -0.25, 0),
    anchors: [], layoutEntities: new Set(),
  });

  it('starts where the first photograph was taken and looks where that camera looked', () => {
    const scene = makeScene([reconstructed], 1, 1);
    const world = buildNavigationWorld(scene, atlasLandscapeSurface());
    const start = initialAtlasCameraState(scene, world, 'inspection');
    const expected = recoveredCameraState(reconstructed, reconstructed.viewpointLocal, reconstructed.viewpointForwardLocal!);
    expect(start).toEqual(expected);
    expect(initialAtlasCameraState(scene, world, 'world')).toEqual(expected);
    // Position is the viewpoint under the island placement: yaw pi/2 turns local +X into atlas -Z... scaled by 1.5.
    expect([start.x, start.y, start.z].map((v) => Math.round(v * 1000) / 1000)).toEqual([20, 2.4, -9]);
    // The forward points from the camera toward the region centre and slightly down.
    const forward = [-Math.sin(start.yaw), 0, -Math.cos(start.yaw)];
    const toCentre = [reconstructed.placement.position.x - start.x, 0, reconstructed.placement.position.z - start.z];
    const dot = forward[0]! * toCentre[0]! + forward[2]! * toCentre[2]!;
    expect(dot).toBeGreaterThan(0);
    expect(start.pitch).toBeLessThan(0);
  });

  it('keeps the offset framing for regions without a recovered viewing direction', () => {
    const { viewpointForwardLocal: _omitted, ...withoutForward } = reconstructed;
    const scene = makeScene([makeIsland({ ...withoutForward, anchors: [] })], 1, 1);
    const world = buildNavigationWorld(scene, atlasLandscapeSurface());
    const start = initialAtlasCameraState(scene, world, 'inspection');
    expect(start.pitch).toBe(-0.085);
    expect(Math.hypot(start.x - reconstructed.placement.position.x, start.z - reconstructed.placement.position.z)).toBeGreaterThan(3);
  });
});

describe('residency of a region with many placed point maps', () => {
  it('lets one region always afford its full stage while several still compete', () => {
    expect(pointMapResidencyCost(1, 96)).toEqual({ stub: 0, proxy: 4, coarse: 10, full: 24 });
    expect(pointMapResidencyCost(38, 96)).toEqual({ stub: 0, proxy: 24, coarse: 48, full: 96 });
    const id = islandId('bowl');
    const plan = planResidency(
      [{ islandId: id, cost: pointMapResidencyCost(38, 96) }],
      [{ islandId: id, desired: 'full', priority: 203 }],
      { maxCost: 96 },
    );
    expect(plan.allocated.get(id)).toBe('full');
    // Under frame pressure the budget shrinks and the stage steps down without vanishing.
    const squeezed = planResidency(
      [{ islandId: id, cost: pointMapResidencyCost(38, 96) }],
      [{ islandId: id, desired: 'full', priority: 203 }],
      { maxCost: 30 },
    );
    expect(squeezed.allocated.get(id)).toBe('proxy');
  });
});
