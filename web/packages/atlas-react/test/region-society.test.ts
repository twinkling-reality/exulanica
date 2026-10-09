// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { islandId } from '@exulanica/atlas-core';
import { visitorPointInRoot, visitorRayOnRootGround } from '../src/playcanvas/society/authored-society.js';
import { hostRegionSociety } from '../src/playcanvas/society/region-society.js';
import { drawDeclaredFloors } from '../src/playcanvas/declared-floor.js';

/*
 * A made world's people live in one island, whose root the page's layout places and turns, while
 * the render origin follows the visitor. Where the visitor stands and the ray they pick along come
 * in from the visitor's world, so both are carried into the island's own frame; the starter's
 * root, unturned at the world origin, reads exactly as it always did.
 */

function world() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  const island = (id: string, x: number, z: number, yawDegrees: number) => {
    const entity = new pc.Entity(`island:${id}`);
    entity.setLocalPosition(x, 0, z);
    entity.setLocalEulerAngles(0, yawDegrees, 0);
    app.root.addChild(entity);
    return { island: { islandId: islandId(id) }, entity };
  };
  return { app, device, island };
}

/** The binding's region roots: one per drawn region, whether or not it holds a point map. */
const roots = (islands: readonly { readonly island: { readonly islandId: ReturnType<typeof islandId> }; readonly entity: pc.Entity }[]) =>
  new Map(islands.map((item) => [item.island.islandId, item.entity] as const));

describe('a society hung from a made world\'s island', () => {
  it('carries a point of the visitor\'s world into the turned, placed island frame', () => {
    const { app, island } = world();
    const placed = island('region-a', 10, 5, 90);
    const origin = { x: 64, y: 0, z: 0 };
    // The island's local (2, 0, 0) is, turned a quarter to the left, (0, 0, -2) from its origin.
    const worldPoint: [number, number, number] = [10 + origin.x, 0, 5 - 2];
    const local = visitorPointInRoot(placed.entity, origin, worldPoint);
    expect([local.x, local.y, local.z].map((v) => Math.round(v * 1e6) / 1e6)).toEqual([2, 0, 0]);
    // The starter's root, unturned at the origin with no render offset, is only a translation.
    const starter = new pc.Entity('authored-region');
    starter.setLocalPosition(0, 0.5, 0);
    app.root.addChild(starter);
    const same = visitorPointInRoot(starter, { x: 0, y: 0, z: 0 }, [3, 1.5, -4]);
    expect([same.x, same.y, same.z]).toEqual([3, 1, -4]);
    app.destroy();
  });

  it('names where a ray comes down to the island\'s ground in its own frame, in millimetres', () => {
    const { app, island } = world();
    const placed = island('region-a', 10, 5, 90);
    const origin = { x: 64, y: 0, z: 0 };
    // From 2 m over the island's local (2, 0, 0), looking down and a little along world -z, which is
    // the island's +x: the ray reaches its ground 1 m further along it.
    const spot = visitorRayOnRootGround(placed.entity, origin, [10 + origin.x, 2, 5 - 2], [0, -2, -1]);
    expect(spot).toEqual({ xMm: 3000, zMm: 0 });
    // A ray level with the ground or rising, or one starting under it, never comes down to it.
    expect(visitorRayOnRootGround(placed.entity, origin, [10 + origin.x, 2, 3], [1, 0, 0])).toBeNull();
    expect(visitorRayOnRootGround(placed.entity, origin, [10 + origin.x, 2, 3], [0, 1, 0])).toBeNull();
    expect(visitorRayOnRootGround(placed.entity, origin, [10 + origin.x, -1, 3], [0, -1, 0])).toBeNull();
    app.destroy();
  });

  it('is hosted once, under the island it lives in, and never moved to another', () => {
    const { app, device, island } = world();
    const islands = [island('region-a', 0, 0, 0), island('region-b', 20, 0, 45)];
    const host = { device, regionRoots: roots(islands), authoredSociety: null };
    expect(hostRegionSociety(host, islandId('region-z'))).toBeNull();
    const society = hostRegionSociety(host, islandId('region-b'));
    expect(society).not.toBeNull();
    expect(society!.root.parent).toBe(islands[1]!.entity);
    expect(host.authoredSociety).toBe(society);
    expect(hostRegionSociety(host, islandId('region-b'))).toBe(society);
    expect(hostRegionSociety(host, islandId('region-a'))).toBeNull();
    society!.destroy();
    app.destroy();
  });

  it('draws a floor with its edges in every island, at the declared height, and takes it away', () => {
    const { app, device, island } = world();
    const islands = [island('region-a', 0, 0, 0), island('region-b', 20, 0, 45)];
    const floors = drawDeclaredFloors({ device, regionRoots: roots(islands) }, { halfExtentMm: 12_000, elevationMm: 250 });
    expect(floors.islandIds).toEqual([islandId('region-a'), islandId('region-b')]);
    for (const { entity } of islands) {
      const floor = entity.children.find((child) => child.name.startsWith('declared-floor:')) as pc.Entity;
      expect(floor.getLocalPosition().y).toBeCloseTo(0.25);
      const [surface, ...edges] = floor.children as pc.Entity[];
      expect(surface!.name).toBe('declared-floor-surface');
      expect(surface!.getLocalScale().x).toBeCloseTo(24);
      expect(surface!.getLocalScale().z).toBeCloseTo(24);
      expect(edges.map((edge) => edge.name)).toEqual(Array(4).fill('declared-floor-edge'));
    }
    expect(() => drawDeclaredFloors({ device, regionRoots: roots(islands) }, { halfExtentMm: 0, elevationMm: 0 }))
      .toThrow('positive half extent');
    floors.destroy();
    for (const { entity } of islands) {
      expect(entity.children.some((child) => child.name.startsWith('declared-floor:'))).toBe(false);
    }
    app.destroy();
  });
});
