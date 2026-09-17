import { describe, expect, it } from 'vitest';
import {
  DEFAULT_CAMERA_RADIUS_AU,
  atlasMapPose,
  atlasVec3,
  buildNavigationWorld,
  isNavigationPositionClear,
  classifySpatialPhase,
  constrainRegionTraversal,
  enterAtlasMap,
  entityId,
  exitAtlasMap,
  isNavigationLineVisible,
  mapTierState,
  makeIsland,
  resolveGroundMovement,
  type NavigationSurface,
} from '../src/index.js';
import { island, scene } from './fixture.js';

const baseIsland = (key = 'memory') => island({
  key,
  createdAt: 1,
  footprint: 10,
  anchors: [],
  entities: ['confirmed'],
});

describe('the grounded memory field', () => {
  it('stands on the flat datum when no surface is supplied', () => {
    const world = buildNavigationWorld(scene([baseIsland()]));
    for (const [x, z] of [[0, 0], [-180, 90], [37.5, -12.25]] as const) {
      expect(world.surface.sample(x, z)).toEqual({ height: 0, normal: { x: 0, y: 1, z: 0 } });
    }
  });

  it('derives eye height from the navigation surface rather than preserving an arbitrary camera Y', () => {
    const sloped: NavigationSurface = {
      sample: (x, z) => ({ height: x * 0.15 + z * 0.05, normal: { x: -0.15, y: 1, z: -0.05 } }),
    };
    const world = buildNavigationWorld(scene([baseIsland()]), sloped);
    const result = resolveGroundMovement(world, {
      current: atlasVec3(0, 99, 0),
      desired: atlasVec3(5, -40, 2),
      lastSafe: atlasVec3(0, world.eyeHeight, 0),
    });
    expect(result.position.y).toBeCloseTo(5 * 0.15 + 2 * 0.05 + world.eyeHeight, 12);
  });

  it('uses one footprint for approach, dissolve, and interior phases', () => {
    const world = buildNavigationWorld(scene([baseIsland()]));
    expect(classifySpatialPhase(world, atlasVec3(35, 0, 0)).phase).toBe('between');
    expect(classifySpatialPhase(world, atlasVec3(20, 0, 0)).phase).toBe('approaching');
    expect(classifySpatialPhase(world, atlasVec3(9, 0, 0)).phase).toBe('dissolve');
    expect(classifySpatialPhase(world, atlasVec3(3, 0, 0)).phase).toBe('inside');
  });

  /*
   * Circle blockers still sweep and slide. No region declares one any more, so the obstacle is
   * supplied here rather than taken from a built world: the capability is still reached by the
   * owned district and by anything that declares a body, and losing the source-first card must not
   * quietly take the collision path with it.
   */
  it('sweeps and slides around a circle blocker instead of tunnelling through it', () => {
    const base = buildNavigationWorld(scene([makeIsland({ ...baseIsland(), rung: 4 })]));
    const obstacle = { id: 'body', centre: atlasVec3(3, 0, 0), radius: 1.75 };
    const world = { ...base, obstacles: [obstacle] };
    const result = resolveGroundMovement(world, {
      current: atlasVec3(obstacle.centre.x - 2, world.eyeHeight, obstacle.centre.z),
      desired: atlasVec3(obstacle.centre.x + 2, world.eyeHeight, obstacle.centre.z),
      lastSafe: atlasVec3(obstacle.centre.x - 2, world.eyeHeight, obstacle.centre.z),
    });
    expect(result.collided).toBe(true);
    expect(Math.hypot(
      result.position.x - obstacle.centre.x,
      result.position.z - obstacle.centre.z,
    )).toBeGreaterThanOrEqual(obstacle.radius + DEFAULT_CAMERA_RADIUS_AU - 1e-3);
  });

  it('sweeps a capsule against exact building rings without tunnelling', () => {
    const base = buildNavigationWorld(scene([baseIsland()]));
    const world = {
      ...base,
      obstacles: [],
      polygonObstacles: [{
        id: 'building',
        rings: [[
          atlasVec3(-1, 0, -3),
          atlasVec3(1, 0, -3),
          atlasVec3(1, 0, 3),
          atlasVec3(-1, 0, 3),
          atlasVec3(-1, 0, -3),
        ]],
      }],
    };
    const result = resolveGroundMovement(world, {
      current: atlasVec3(-5, world.eyeHeight, 0),
      desired: atlasVec3(5, world.eyeHeight, 0),
      lastSafe: atlasVec3(-5, world.eyeHeight, 0),
    });
    expect(result.collided).toBe(true);
    expect(result.position.x).toBeLessThanOrEqual(-1 - DEFAULT_CAMERA_RADIUS_AU + 0.01);
  });

  it('preserves the unblocked component of diagonal movement along a building', () => {
    const base = buildNavigationWorld(scene([baseIsland()]));
    const world = {
      ...base,
      obstacles: [],
      polygonObstacles: [{
        id: 'building',
        rings: [[
          atlasVec3(-1, 0, -3),
          atlasVec3(1, 0, -3),
          atlasVec3(1, 0, 3),
          atlasVec3(-1, 0, 3),
          atlasVec3(-1, 0, -3),
        ]],
      }],
    };
    const result = resolveGroundMovement(world, {
      current: atlasVec3(-3, world.eyeHeight, -2),
      desired: atlasVec3(0, world.eyeHeight, 2),
      lastSafe: atlasVec3(-3, world.eyeHeight, -2),
    });
    expect(result.collided).toBe(true);
    expect(result.position.x).toBeLessThanOrEqual(-1 - DEFAULT_CAMERA_RADIUS_AU + 0.01);
    expect(result.position.z).toBeGreaterThan(0.5);
  });

  it('stops at a polygon corner without reversing either movement axis', () => {
    const base = buildNavigationWorld(scene([baseIsland()]));
    const world = {
      ...base,
      obstacles: [],
      polygonObstacles: [{
        id: 'corner',
        rings: [[
          atlasVec3(0, 0, 0),
          atlasVec3(4, 0, 0),
          atlasVec3(4, 0, 4),
          atlasVec3(0, 0, 4),
          atlasVec3(0, 0, 0),
        ]],
      }],
    };
    const current = atlasVec3(-2, world.eyeHeight, -2);
    const result = resolveGroundMovement(world, {
      current,
      desired: atlasVec3(2, world.eyeHeight, 2),
      lastSafe: current,
    });
    expect(result.collided).toBe(true);
    expect(result.position.x).toBeGreaterThanOrEqual(current.x);
    expect(result.position.z).toBeGreaterThanOrEqual(current.z);
    expect(Math.hypot(result.position.x, result.position.z))
      .toBeGreaterThanOrEqual(DEFAULT_CAMERA_RADIUS_AU - 0.01);
  });

  it('uses a circle blocker for focus visibility as well as locomotion', () => {
    const base = buildNavigationWorld(scene([makeIsland({ ...baseIsland(), rung: 4 })]));
    const obstacle = { id: 'body', centre: atlasVec3(3, 0, 0), radius: 1.75 };
    const world = { ...base, obstacles: [obstacle] };
    expect(isNavigationLineVisible(
      world,
      atlasVec3(obstacle.centre.x, world.eyeHeight, obstacle.centre.z - 3),
      atlasVec3(obstacle.centre.x, 0, obstacle.centre.z + 3),
    )).toBe(false);
    expect(isNavigationLineVisible(
      world,
      atlasVec3(obstacle.centre.x + 3, world.eyeHeight, obstacle.centre.z - 3),
      atlasVec3(obstacle.centre.x + 3, 0, obstacle.centre.z + 3),
    )).toBe(true);
  });

  it('recovers deterministically to the last safe pose beyond the hard envelope', () => {
    const world = buildNavigationWorld(scene([baseIsland()]));
    const safe = atlasVec3(4, world.eyeHeight, 3);
    const result = resolveGroundMovement(world, {
      current: safe,
      desired: atlasVec3(world.recoveryRadius + 100, 0, 0),
      lastSafe: safe,
    });
    expect(result.recovered).toBe(true);
    expect(result.recoveryReason).toBe('outside-field');
    expect(result.position).toEqual(safe);
  });

  it('samples the full movement path and refuses holes, cliffs, and excessive slope', () => {
    const hole: NavigationSurface = {
      sample: (x) => x > 1 && x < 2 ? null : ({ height: 0, normal: { x: 0, y: 1, z: 0 } }),
    };
    const holeWorld = buildNavigationWorld(scene([baseIsland()]), hole);
    const holeResult = resolveGroundMovement(holeWorld, {
      current: atlasVec3(0, holeWorld.eyeHeight, 0),
      desired: atlasVec3(3, holeWorld.eyeHeight, 0),
      lastSafe: atlasVec3(0, holeWorld.eyeHeight, 0),
    });
    expect(holeResult.recovered).toBe(true);
    expect(holeResult.recoveryReason).toBe('no-surface');

    const cliff: NavigationSurface = {
      sample: (x) => ({
        height: x >= 1.5 ? 1 : 0,
        normal: { x: 0, y: 1, z: 0 },
      }),
    };
    const cliffWorld = buildNavigationWorld(scene([baseIsland()]), cliff);
    expect(resolveGroundMovement(cliffWorld, {
      current: atlasVec3(0, cliffWorld.eyeHeight, 0),
      desired: atlasVec3(3, cliffWorld.eyeHeight, 0),
      lastSafe: atlasVec3(0, cliffWorld.eyeHeight, 0),
    }).recoveryReason).toBe('unsafe-surface');

    const steep: NavigationSurface = {
      sample: () => ({ height: 0, normal: { x: -1, y: 1, z: 0 } }),
    };
    const steepWorld = buildNavigationWorld(scene([baseIsland()]), steep);
    expect(resolveGroundMovement(steepWorld, {
      current: atlasVec3(0, steepWorld.eyeHeight, 0),
      desired: atlasVec3(1, steepWorld.eyeHeight, 0),
      lastSafe: atlasVec3(0, steepWorld.eyeHeight, 0),
    }).recoveryReason).toBe('unsafe-surface');
  });
});

describe('reconstruction-rung constraints', () => {
  it('keeps corridor traversal inside the authored lateral envelope', () => {
    const position = constrainRegionTraversal(
      {
        movement: 'corridor',
        centreline: [atlasVec3(0, 0, 0), atlasVec3(20, 0, 0)],
        halfWidth: 2,
      },
      atlasVec3(5, 1.62, 0),
      atlasVec3(8, 1.62, 9),
    );
    expect(position.x).toBeCloseTo(8, 12);
    expect(position.z).toBeCloseTo(2, 12);
  });

  it('lets free traversal pass while panel/card policies respect their blockers', () => {
    const obstacle = { id: 'panel', centre: atlasVec3(2, 0, 0), radius: 0.7 };
    const desired = atlasVec3(5, 1.62, 0);
    expect(constrainRegionTraversal(
      { movement: 'free', obstacles: [] },
      atlasVec3(0, 1.62, 0),
      desired,
    )).toEqual(desired);
    const blocked = constrainRegionTraversal(
      { movement: 'panels', obstacles: [obstacle] },
      atlasVec3(0, 1.62, 0),
      desired,
    );
    expect(blocked.x).toBeLessThan(2);
  });
});

describe('semantic traces and Atlas Map correspondence', () => {
  it('derives one trace from the same confirmed sets that place the regions', () => {
    const a = baseIsland('a');
    const b0 = baseIsland('b');
    const b = makeIsland({ ...b0, layoutEntities: new Set([entityId('confirmed')]) });
    const world = buildNavigationWorld(scene([a, b]));
    expect(world.traces).toHaveLength(1);
    expect(world.traces[0]!.strength).toBe(1);
  });

  it('restores the exact ground pose after Map input changes only the active pose', () => {
    const atlas = scene([baseIsland()]);
    const ground = Object.freeze({
      position: atlasVec3(7.25, 1.62, -3.5),
      yaw: 1.234,
      pitch: -0.321,
    });
    const state = enterAtlasMap(atlas, ground);
    expect(state.active).toEqual(atlasMapPose(atlas));
    expect(state.active).not.toEqual(ground);
    expect(exitAtlasMap(state)).toEqual(ground);
  });

  it('keeps all regions at one overview density regardless of Map altitude', () => {
    const atlas = scene([baseIsland('a'), baseIsland('b')]);
    expect([...mapTierState(atlas).tier.values()]).toEqual([1, 1]);
  });

  /*
   * A collider with nothing drawn at it stops a walk for no visible reason.
   *
   * There used to be one per no-geometry region: a 1.75 unit circle standing in for the source
   * photograph that hung over it. The photograph is gone from the 3D world, so the circle has to
   * go with it, and this is the assertion that keeps them from drifting apart again.
   */
  it('leaves no blocker where nothing is drawn', () => {
    const cards = island({
      key: 'cards', createdAt: 1, footprint: 9, position: [6, 0, -3],
      anchors: [{ key: 'object', local: [1, 1, -2], radius: 0.4 }],
    });
    const world = buildNavigationWorld(scene([cards]));
    expect(world.regions.map((region) => region.islandId)).toEqual([cards.islandId]);
    expect(world.obstacles).toEqual([]);
    // And nothing near the region refuses a standing position on that account.
    expect(isNavigationPositionClear(world, atlasVec3(6, world.eyeHeight, -3))).toBe(true);
  });
});
