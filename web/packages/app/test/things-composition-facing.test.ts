// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { facingOfYaw, type ThingLayerOptions } from '@exulanica/atlas-react/things';
import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import { planSight } from '../src/composition/sight.js';
import { mountThings } from '../src/composition/things.js';
import type { PlacedThing } from '../src/world-objects-api.js';

/*
 * A placed being stands in the crowd as the version placed it: the crowd's figures answer its
 * standing facing from the placement's yaw by the layer's own rule. A resident nobody placed faces
 * the open way where they stand by the world's plan sight, and nobody faces any way without one; the
 * same sight says how much room lies from a crowd point along a way, which keeps the crowd's steps off walls.
 */

const { FakeLayer } = vi.hoisted(() => {
  class Fake {
    readonly maker = { library: { list: { kinds: [], looks: [] } } };
    constructor(readonly options: ThingLayerOptions) {}
    async setLook() {}
    setSociety() {}
    async setPlaced() {}
    setPicked() {}
    get misses() { return []; }
    destroy() {}
  }
  return { FakeLayer: Fake };
});
vi.mock('@exulanica/atlas-react/things', async (original) => ({
  ...(await original<typeof import('@exulanica/atlas-react/things')>()),
  ThingLayer: FakeLayer,
}));

const KNIGHT = { kind: 'knight', version: 1, sha256: 'a'.repeat(64) };

const placed = (thingId: string, yawMicroradians: number): PlacedThing => ({
  thingId, kind: KNIGHT, regionId: 'r', removed: false, origin: { kind: 'authored', role: 'thing' },
  transform: { xMm: 0, yMm: 0, zMm: 0, yawMicroradians, scaleMilli: 1000 } as PlacedThing['transform'],
});

const person = (id: string, placedId: string | null): OwnedSocietyState['inhabitants'][number] =>
  ({ id, synthetic: true, position_mm: [0, 0], kind: KNIGHT, came_by: placedId === null ? 'populated' : 'placed', placed_id: placedId });

describe('a placed being\'s standing facing', () => {
  it('comes from its placement\'s yaw, follows a changed placement, and is none for anyone else', async () => {
    const things = await mountThings({
      app: {} as never, camera: {} as never, shell: document.createElement('div'),
      credentials: { baseUrl: 'https://host.test', token: 'token' },
      regionRoot: () => null, invalidate: () => undefined, reducedMotion: () => false,
      library: async () => ({ list: { kinds: [], looks: [] } }) as never,
    });
    const figures = things.crowdFigures;
    // Before the version's placements are read there is nothing to stand by.
    expect(figures.standingFacingOf(person('p-knight', 'knight-1'))).toBeNull();
    await things.setPlaced([placed('knight-1', 1_900_000), placed('well-1', 0)]);
    expect(figures.standingFacingOf(person('p-knight', 'knight-1'))).toBe(facingOfYaw(1_900_000));
    expect(figures.standingFacingOf(person('villager-1', null))).toBeNull();
    expect(figures.standingFacingOf(person('p-other', 'not-placed'))).toBeNull();
    await things.setPlaced([placed('knight-1', -700_000)]);
    expect(figures.standingFacingOf(person('p-knight', 'knight-1'))).toBe(facingOfYaw(-700_000));
    things.destroy();
  });
});

describe('a resident\'s standing facing', () => {
  // A wall 20 m long whose south face is 19.2 m south of the world's origin: someone at 19.6 m facing
  // north (a crowd's facing 0) stands nose to it, 40 cm off.
  const sight = planSight([[[90_000, 18_000], [110_000, 18_000], [110_000, 19_200], [90_000, 19_200]]], 500);
  const resident = (id: string, east: number, south: number): OwnedSocietyState['inhabitants'][number] =>
    ({ id, synthetic: true, position_mm: [east, south], came_by: 'populated', placed_id: null });
  // The society's root as world matrices, column-major: moved 100 m east, and also turned a quarter.
  const moved = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 100, 0, 0, 1]);
  const turned = new Float32Array([0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 100, 0, 0, 1]);
  const mount = (data: Float32Array | null, withSight = true) => mountThings({
    app: {} as never, camera: {} as never, shell: document.createElement('div'),
    credentials: { baseUrl: 'https://host.test', token: 'token' },
    regionRoot: () => null, invalidate: () => undefined, reducedMotion: () => false,
    library: async () => ({ list: { kinds: [], looks: [] } }) as never,
    society: () => (data === null ? null : { root: { getWorldTransform: () => ({ data }) } }) as never,
    ...(withSight ? { sight: () => sight } : {}),
  });

  it('is the open way where they stand in the world, never the wall 40 cm off, wherever the society is drawn', async () => {
    expect(sight.reach([100, 1.6, 19.6], [0, 0, -1])).toBeCloseTo(0.4, 9);
    // Each root puts the resident at the world's (100, 19.6), 40 cm south of the wall: the moved one at
    // its own (0, 19.6), the turned one at its own (-19.6, 0).
    for (const [data, east, south] of [[moved, 0, 19_600], [turned, -19_600, 0]] as const) {
      const things = await mount(data);
      const ways = new Set<number>();
      for (let n = 0; n < 24; n += 1) {
        const facing = things.crowdFigures.standingFacingOf(resident(`villager-${n}`, east, south))!;
        // The facing is the society's own: its forward carried to the world by the root's axes.
        const [fx, fz] = [-Math.sin(facing), -Math.cos(facing)];
        const ahead = [data[0]! * fx + data[8]! * fz, 0, data[2]! * fx + data[10]! * fz] as const;
        expect(sight.reach([100, 1.6, 19.6], ahead)).toBeGreaterThanOrEqual(3);
        ways.add(Math.round(facing * 1000));
      }
      expect(ways.size).toBeGreaterThan(2);
      things.destroy();
    }
  });

  it('says how much room lies from a crowd point along a way, the wall 40 cm north of it, wherever the society is drawn', async () => {
    // North in the world is the moved society's own north, and the turned one's own east.
    for (const [data, at, north] of [[moved, [0, 19.6], [0, -1]], [turned, [-19.6, 0], [1, 0]]] as const) {
      const things = await mount(data);
      expect(things.crowdFigures.openAlong(at, north, 5)).toBeCloseTo(0.4, 9);
      // Nothing stands south of the wall: as far as asked.
      expect(things.crowdFigures.openAlong(at, [-north[0], -north[1]], 5)).toBe(5);
      things.destroy();
    }
    for (const unsaid of [await mount(moved, false), await mount(null)]) {
      expect(unsaid.crowdFigures.openAlong([0, 19.6], [0, -1], 5)).toBeNull();
      unsaid.destroy();
    }
  });

  it('keeps a placed being at its placement\'s yaw, and is none without a sight or a drawn society', async () => {
    const things = await mount(moved);
    await things.setPlaced([placed('knight-1', 1_900_000)]);
    expect(things.crowdFigures.standingFacingOf({ ...resident('p-knight', 0, 19_600), placed_id: 'knight-1' })).toBe(facingOfYaw(1_900_000));
    things.destroy();
    for (const unsaid of [await mount(moved, false), await mount(null)]) {
      expect(unsaid.crowdFigures.standingFacingOf(resident('villager-1', 0, 19_600))).toBeNull();
      unsaid.destroy();
    }
  });
});
