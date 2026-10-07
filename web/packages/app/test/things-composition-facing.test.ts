// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { facingOfYaw, type ThingLayerOptions } from '@exulanica/atlas-react/things';
import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import { mountThings } from '../src/composition/things.js';
import type { PlacedThing } from '../src/world-objects-api.js';

/*
 * A placed being stands in the crowd as the version placed it: the crowd's figures answer its
 * standing facing from the placement's yaw by the layer's own rule, and nobody else has one.
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
