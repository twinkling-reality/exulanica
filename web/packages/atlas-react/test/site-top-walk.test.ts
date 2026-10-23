/**
 * Walking a sky island's top by the page's own movement rules: a person arriving outside a hamlet's
 * gate walks in through it, and from the yard back out to the rim and no further.
 *
 * The drawing and its top (`fixtures/site-top-walk.v1.json`) are the server's own output for a world
 * made from the served "Hamlet on a sky island" starter: the person arrives 3 m outside the gate in
 * the site's south edge, where the top falls about 10 degrees, so the band where the site's edge eases
 * onto it reads 12 to 16 degrees across the gate.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import {
  DEFAULT_MAXIMUM_SLOPE_DEGREES, atlasVec3, canonicalJson, resolveGroundMovement, type AtlasVec3, type NavigationWorld,
} from '@exulanica/atlas-core';
import { describe, expect, it } from 'vitest';
import { parseStructuredSiteDrawing, readSiteTopLand, siteNavigationWorld, siteStart } from '../src/playcanvas/generated-site/index.js';

const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const FIXTURE = JSON.parse(readFileSync('packages/atlas-react/test/fixtures/site-top-walk.v1.json', 'utf8')) as {
  drawing: Record<string, unknown>; drawing_sha256: string; top: Record<string, unknown>; top_sha256: string;
};
const drawing = parseStructuredSiteDrawing(structuredClone(FIXTURE.drawing));
const islandWorld = (): NavigationWorld =>
  siteNavigationWorld(drawing, undefined, readSiteTopLand(drawing, structuredClone(FIXTURE.top), sha256));
const arrival = (world: NavigationWorld): AtlasVec3 => {
  const start = siteStart(drawing, world);
  return atlasVec3(start.x, start.y, start.z);
};

/**
 * Where a person stands after walking from `from` along `heading` (metres east and south for each
 * metre) for `metres`, a tenth of a metre at a time, each step resolved as the controls resolve a
 * frame's move.
 */
function walk(world: NavigationWorld, from: AtlasVec3, heading: readonly [number, number], metres: number): AtlasVec3 {
  let current = from;
  let lastSafe: AtlasVec3 | null = from;
  for (let step = 0; step < metres * 10; step += 1) {
    const desired = atlasVec3(current.x + heading[0] / 10, current.y, current.z + heading[1] / 10);
    const moved = resolveGroundMovement(world, { current, desired, lastSafe });
    current = moved.position;
    lastSafe = moved.lastSafe;
  }
  return current;
}

describe("walking a sky island's top", () => {
  it("reads the server's drawing and top, the person arriving 3 m outside the gate facing in", () => {
    expect(sha256(new TextEncoder().encode(canonicalJson(FIXTURE.drawing)))).toBe(FIXTURE.drawing_sha256);
    expect(sha256(new TextEncoder().encode(canonicalJson(FIXTURE.top)))).toBe(FIXTURE.top_sha256);
    const start = arrival(islandWorld());
    expect([start.x, start.z]).toEqual([11, 3]);
  });

  it('walks a person arriving outside the gate in through it, and from the yard out to the rim and no further', () => {
    const world = islandWorld();
    const start = arrival(world);
    const inside = walk(world, start, [0, -1], 12);
    // Eight metres north of the site's south edge, among the hamlet's houses.
    expect(inside.z).toBeLessThan(-8);
    const out = walk(world, inside, [0, 1], 30);
    // Back through the gate, past where they arrived, to the rim: no floor half a metre on.
    expect(out.z).toBeGreaterThan(start.z + 3);
    expect(world.surface.sample(out.x, out.z + 0.5)).toBeNull();
  });

  it('keeps them outside the gate at the default 12 degrees, the limit the land walking grade replaces', () => {
    const world = { ...islandWorld(), maximumSlopeDegrees: DEFAULT_MAXIMUM_SLOPE_DEGREES };
    const stopped = walk(world, arrival(world), [0, -1], 12);
    expect(stopped.z).toBeGreaterThan(0);
  });
});
