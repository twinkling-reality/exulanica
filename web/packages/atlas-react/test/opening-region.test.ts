import { describe, expect, it } from 'vitest';
import {
  atlasVec3, buildNavigationWorld, islandId, localVec3, makeIsland, makeScene, placement,
  type Island,
} from '@exulanica/atlas-core';
import { initialAtlasCameraState, recoveredCameraState } from '../src/playcanvas/camera-views.js';
import { openingIsland } from '../src/playcanvas/opening-region.js';

/*
 * Which region a world of scene regions opens in: the one holding the most of the person's
 * placements, ties to the earlier region, and the scene's first region when no placement is in
 * any drawn region.
 */

function region(id: string, x: number, options: { rung?: 1 | 2 | 3 | 4; forward?: boolean } = {}): Island {
  return makeIsland({
    islandId: islandId(id), createdAt: 0,
    placement: placement(atlasVec3(x, 0, -4), 0.35, 1.2),
    rung: options.rung ?? 4, scaleIsMetric: false, footprintRadiusLocal: 7,
    viewpointLocal: localVec3(2, 1.6, 0),
    ...(options.forward === true ? { viewpointForwardLocal: localVec3(-1, -0.25, 0) } : {}),
    anchors: [], layoutEntities: new Set(),
  });
}

const NEWEST = region('region:newest', 0);
const KEPT = region('region:kept', 40);
const THIRD = region('region:third', 80);
const SCENE = makeScene([NEWEST, KEPT, THIRD], 1, 1);

describe('the region a world opens in', () => {
  it('is the region holding the most placements', () => {
    expect(openingIsland(SCENE, ['region:kept'])).toBe(KEPT);
    expect(openingIsland(SCENE, ['region:newest', 'region:third', 'region:third'])).toBe(THIRD);
  });

  it('goes to the earlier region in scene order on a tie', () => {
    expect(openingIsland(SCENE, ['region:third', 'region:kept'])).toBe(KEPT);
    expect(openingIsland(SCENE, ['region:kept', 'region:newest'])).toBe(NEWEST);
  });

  it('counts nothing for a region the scene does not draw, as one past the island cut', () => {
    const cut = ['region:omitted', 'region:omitted', 'region:omitted'];
    expect(openingIsland(SCENE, [...cut, 'region:third'])).toBe(THIRD);
    expect(openingIsland(SCENE, cut)).toBe(NEWEST);
  });

  it('is the scene first region with no placement, and nothing in a scene with no region', () => {
    expect(openingIsland(SCENE, [])).toBe(NEWEST);
    expect(openingIsland(SCENE)).toBe(NEWEST);
    expect(openingIsland(makeScene([], 1, 1), ['region:kept'])).toBeUndefined();
  });
});

describe('the opening camera stands in that region', () => {
  const world = buildNavigationWorld(SCENE);

  it('frames the chosen region the way it framed the first one', () => {
    const start = initialAtlasCameraState(SCENE, world, ['region:kept']);
    const alone = initialAtlasCameraState(makeScene([KEPT], 1, 1), world);
    expect(start).toEqual(alone);
    expect(Math.hypot(start.x - KEPT.placement.position.x, start.z - KEPT.placement.position.z))
      .toBeLessThan(Math.hypot(start.x - NEWEST.placement.position.x, start.z - NEWEST.placement.position.z));
  });

  it('opens where it always did when the person placed nothing', () => {
    const scene = makeScene([NEWEST], 1, 1);
    expect(initialAtlasCameraState(SCENE, world, [])).toEqual(initialAtlasCameraState(scene, world));
  });

  it('keeps the recovered-camera arrival for a reconstructed region chosen by the rule', () => {
    const reconstructed = region('region:kept', 40, { rung: 3, forward: true });
    const scene = makeScene([NEWEST, reconstructed], 1, 1);
    const start = initialAtlasCameraState(scene, buildNavigationWorld(scene), ['region:kept']);
    expect(start).toEqual(recoveredCameraState(
      reconstructed, reconstructed.viewpointLocal, reconstructed.viewpointForwardLocal!,
    ));
  });
});
