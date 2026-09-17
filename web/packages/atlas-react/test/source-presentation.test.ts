import { describe, expect, it } from 'vitest';
import {
  atlasVec3, buildNavigationWorld,
  islandId, localVec3, makeIsland, makeScene, placement, planResidency,
} from '@exulanica/atlas-core';
import {
  initialAtlasCameraState, pointMapResidencyCost, recoveredCameraState,
} from '../src/playcanvas/atlas-binding.js';

const island = makeIsland({
  islandId: islandId('reference-source'), createdAt: 0,
  placement: placement(atlasVec3(12, 0, -4), 0.35, 1.2),
  rung: 4, scaleIsMetric: false, footprintRadiusLocal: 7,
  viewpointLocal: localVec3(0, 1.6, 0), anchors: [], layoutEntities: new Set(),
});
const scene = makeScene([island], 1, 1);

/*
 * The source photograph no longer stands in the 3D world.
 *
 * What used to be here tested a switch: `sourceGroveScene` emptied the island list so no veil was
 * built, and `sourceFirstArrivalPose` tilted the arrival camera up at the veil unless the switch
 * said the inspector owned the source. Both sides of that switch are gone, because only things
 * with real geometry belong in the 3D world and a photograph has none. What remains worth holding
 * is the consequence: nothing aims the camera upward at a body that is not there.
 */
describe('a session opens looking at the ground, not above it', () => {
  it('never pitches the opening camera up', () => {
    const world = buildNavigationWorld(scene);
    const start = initialAtlasCameraState(scene, world);
    expect(start.pitch).toBe(-0.085);
    // Standing off the region rather than inside it, which is what makes a landmark visible.
    expect(Math.hypot(
      start.x - island.placement.position.x,
      start.z - island.placement.position.z,
    )).toBeGreaterThan(3);
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
    const world = buildNavigationWorld(scene);
    const start = initialAtlasCameraState(scene, world);
    const expected = recoveredCameraState(reconstructed, reconstructed.viewpointLocal, reconstructed.viewpointForwardLocal!);
    expect(start).toEqual(expected);
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
    const world = buildNavigationWorld(scene);
    const start = initialAtlasCameraState(scene, world);
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
