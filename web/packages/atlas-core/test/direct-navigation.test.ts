import { describe, expect, it } from 'vitest';
import {
  atlasVec3,
  buildNavigationWorld,
  islandId,
  makeIsland,
  navigationRegionForIsland,
  planDirectNavigationTransition,
  resolveDirectNavigation,
  sampleDirectNavigationTransition,
} from '../src/index.js';
import type { NavigationWorld, PolygonObstacle } from '../src/index.js';
import { anchor, island, scene } from './fixture.js';

describe('direct navigation', () => {
  const memory = island({
    key: 'memory',
    createdAt: 1,
    footprint: 12,
    position: [8, 0, -4],
    anchors: [{ key: 'object', local: [1, 1, -2], radius: 0.4 }],
  });
  const atlas = scene([memory]);
  const world = buildNavigationWorld(atlas);

  it('resolves a safe interior region pose that looks toward the region', () => {
    const result = resolveDirectNavigation(
      atlas,
      world,
      { kind: 'island', islandId: islandId('memory') },
      atlasVec3(0, world.eyeHeight, 0),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.islandId).toBe(islandId('memory'));
    expect(result.pose.position.y).toBe(world.eyeHeight);
    expect(Math.hypot(
      result.pose.position.x - memory.placement.position.x,
      result.pose.position.z - memory.placement.position.z,
    )).toBeLessThan(memory.footprintRadiusLocal);
  });

  it('resolves an exact anchor vantage with line of sight', () => {
    const target = memory.anchors[0]!;
    const result = resolveDirectNavigation(
      atlas,
      world,
      { kind: 'anchor', anchorId: target.anchorId },
      atlasVec3(0, world.eyeHeight, 0),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.targetPosition).toEqual(atlasVec3(9, 1, -6));
  });

  it('rejects a target outside the resident scene instead of fabricating a pose', () => {
    expect(resolveDirectNavigation(
      atlas,
      world,
      { kind: 'island', islandId: islandId('not-resident') },
      atlasVec3(0, world.eyeHeight, 0),
    )).toEqual({
      ok: false,
      target: { kind: 'island', islandId: islandId('not-resident') },
      reason: 'unknown-target',
    });
  });

  it('rejects direct travel when a missing surface lies between two valid endpoints', () => {
    const discontinuous = buildNavigationWorld(atlas, {
      sample: (x) => x > 0.5 && x < 1.3
        ? null
        : { height: 0, normal: { x: 0, y: 1, z: 0 } },
    });
    expect(resolveDirectNavigation(
      atlas,
      discontinuous,
      { kind: 'island', islandId: islandId('memory') },
      atlasVec3(0, discontinuous.eyeHeight, 0),
    )).toEqual({
      ok: false,
      target: { kind: 'island', islandId: islandId('memory') },
      reason: 'no-safe-surface',
    });
  });

  it('samples exact transition endpoints and honors reduced motion', () => {
    const result = resolveDirectNavigation(
      atlas,
      world,
      { kind: 'anchor', anchorId: memory.anchors[0]!.anchorId },
      atlasVec3(0, world.eyeHeight, 0),
    );
    if (!result.ok) throw new Error('fixture should resolve');
    const from = { position: atlasVec3(0, world.eyeHeight, 0), yaw: Math.PI - 0.1, pitch: 0 };
    const transition = planDirectNavigationTransition(result, from, false);
    expect(sampleDirectNavigationTransition(transition, 0)).toEqual(from);
    expect(sampleDirectNavigationTransition(transition, transition.durationMs)).toBe(result.pose);
    const reduced = planDirectNavigationTransition(result, from, true);
    expect(sampleDirectNavigationTransition(reduced, 0)).toBe(result.pose);
  });

  it('does not depend on the source array order', () => {
    const second = island({ key: 'second', createdAt: 2, anchors: [] });
    const target = anchor('memory', { key: 'other', local: [0, 1, 0] });
    const withTarget = { ...memory, anchors: [...memory.anchors, target] };
    const a = scene([withTarget, second]);
    const b = scene([second, withTarget]);
    expect(resolveDirectNavigation(a, buildNavigationWorld(a), {
      kind: 'anchor', anchorId: target.anchorId,
    }, atlasVec3(0, 1.62, 0))).toEqual(resolveDirectNavigation(b, buildNavigationWorld(b), {
      kind: 'anchor', anchorId: target.anchorId,
    }, atlasVec3(0, 1.62, 0)));
  });
});

/**
 * A city-shaped world: flat ground everywhere inside a rectangle, and solid blocks standing on it.
 *
 * The archipelago fixture above cannot show what an owned district does, because it has at most one
 * coarse blocker per island and a straight line to a region almost never meets it. A block grid is
 * the case that matters: over the real Flatiron district every single candidate standing point that
 * had ground and was outside a building was still refused, because a straight line of 200-plus
 * metres across a city always crosses something.
 */
function cityWorld(blocks: readonly PolygonObstacle[], half = 200): NavigationWorld {
  return Object.freeze({
    surface: {
      sample: (x: number, z: number) =>
        Math.abs(x) > half || Math.abs(z) > half
          ? null
          : Object.freeze({ height: 0, normal: Object.freeze({ x: 0, y: 1, z: 0 }) }),
    },
    eyeHeight: 1.62,
    cameraRadius: 0.34,
    centre: atlasVec3(0, 0, 0),
    fieldRadius: half * Math.SQRT2,
    recoveryRadius: half * Math.SQRT2 + 2,
    maximumSlopeDegrees: 12,
    maximumStepHeight: 0.18,
    surfaceSampleSpacing: 0.25,
    regions: Object.freeze([]),
    obstacles: Object.freeze([]),
    polygonObstacles: Object.freeze(blocks),
    traces: Object.freeze([]),
  });
}

const block = (id: string, west: number, north: number, east: number, south: number): PolygonObstacle =>
  Object.freeze({
    id,
    rings: Object.freeze([Object.freeze([
      atlasVec3(west, 0, north),
      atlasVec3(east, 0, north),
      atlasVec3(east, 0, south),
      atlasVec3(west, 0, south),
      atlasVec3(west, 0, north),
    ])]),
  });

describe('direct navigation over built ground', () => {
  const far = island({
    key: 'far',
    createdAt: 1,
    footprint: 5,
    position: [90, 0, 0],
    anchors: [{ key: 'object', local: [0, 1, 0], radius: 0.4 }],
  });
  const atlas = scene([far]);
  const regions = [far].map(navigationRegionForIsland);

  it('reaches a region with a block standing between here and there', () => {
    const world = { ...cityWorld([block('mid', 30, -40, 50, 40)]), regions };
    const result = resolveDirectNavigation(
      atlas,
      world,
      { kind: 'island', islandId: islandId('far') },
      atlasVec3(0, world.eyeHeight, 0),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    // Still inside the region it was asked for, and still on ground that is genuinely clear.
    expect(Math.hypot(
      result.pose.position.x - far.placement.position.x,
      result.pose.position.z - far.placement.position.z,
    )).toBeLessThan(far.footprintRadiusLocal);
  });

  it('steps out from under a block that covers the whole region', () => {
    // The region centre sits inside a block wider than its own footprint, which is the Flatiron
    // case: one region stands inside a 29.5 by 33.4 metre building.
    const world = { ...cityWorld([block('over', 78, -12, 102, 12)]), regions };
    const result = resolveDirectNavigation(
      atlas,
      world,
      { kind: 'island', islandId: islandId('far') },
      atlasVec3(0, world.eyeHeight, 0),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const standoff = Math.hypot(
      result.pose.position.x - far.placement.position.x,
      result.pose.position.z - far.placement.position.z,
    );
    // Outside the block, and no further out than the region's own approach ring.
    expect(result.pose.position.x).toBeLessThan(78);
    expect(standoff).toBeLessThanOrEqual(regions[0]!.approachRadius);
  });

  it('refuses a region sealed under ground nothing nearby is clear of', () => {
    // A block covering the region and every standing distance the search is allowed to try.
    const world = { ...cityWorld([block('sealed', 40, -60, 140, 60)]), regions };
    expect(resolveDirectNavigation(
      atlas,
      world,
      { kind: 'island', islandId: islandId('far') },
      atlasVec3(0, world.eyeHeight, 0),
    )).toEqual({
      ok: false,
      target: { kind: 'island', islandId: islandId('far') },
      reason: 'occluded',
    });
  });
});

/*
 * A world that declares only places, like an owned district, leaves arranged regions out. Travel
 * to one of those is refused for that reason, not as a region outside the ground, and the Atlas
 * world, which declares its arrangement, still travels to it.
 */
describe('direct navigation to a region with no known place', () => {
  const arranged = makeIsland({
    ...island({
      key: 'arranged',
      createdAt: 1,
      footprint: 12,
      position: [8, 0, -4],
      anchors: [{ key: 'object', local: [1, 1, -2], radius: 0.4 }],
    }),
    placementLocated: false,
  });
  const located = island({ key: 'located', createdAt: 2, footprint: 12, position: [-30, 0, 10], anchors: [] });
  const atlas = scene([arranged, located]);
  const placesOnly: NavigationWorld = { ...buildNavigationWorld(atlas), regions: [] };
  const here = atlasVec3(0, 1.62, 0);

  it('says the region has no known place when this world declares only places', () => {
    for (const target of [
      { kind: 'island', islandId: islandId('arranged') },
      { kind: 'anchor', anchorId: arranged.anchors[0]!.anchorId },
    ] as const) {
      expect(resolveDirectNavigation(atlas, placesOnly, target, here))
        .toEqual({ ok: false, target, reason: 'unlocated-placement' });
    }
  });

  it('still calls a located region missing from this world outside it', () => {
    const target = { kind: 'island', islandId: islandId('located') } as const;
    expect(resolveDirectNavigation(atlas, placesOnly, target, here))
      .toEqual({ ok: false, target, reason: 'outside-resident-field' });
  });

  it('travels to the arranged region in the Atlas world exactly as before', () => {
    const world = buildNavigationWorld(atlas);
    const result = resolveDirectNavigation(
      atlas, world, { kind: 'island', islandId: islandId('arranged') }, atlasVec3(0, world.eyeHeight, 0),
    );
    expect(result.ok).toBe(true);
  });
});
