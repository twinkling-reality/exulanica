// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import type { Named, ThingLayerOptions } from '@exulanica/atlas-react/things';
import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import { LOOKS_READ_INTERVAL_MS, looksReadDue, mountThings } from '../src/composition/things.js';
import type { ThingLookChoice } from '../src/thing-looks-api.js';

/*
 * The looks chosen for a society's things: a person wears theirs in the crowd (the figure the
 * crowd asks for names it), a placed thing in the layer; a choice withdrawn returns a placed thing to
 * its kind's first look. The layer stands in here, recording the looks it is given.
 */

const { FakeLayer, layers } = vi.hoisted(() => {
  const made: InstanceType<typeof Fake>[] = [];
  class Fake {
    readonly looks: [string, Named | null][] = [];
    readonly maker = { library: { list: { kinds: [], looks: [] } } };
    constructor(readonly options: ThingLayerOptions) { made.push(this); }
    async setLook(placedId: string, look: Named | null) { this.looks.push([placedId, look]); }
    setSociety() {}
    async setPlaced() {}
    setPicked() {}
    get misses() { return []; }
    destroy() {}
  }
  return { FakeLayer: Fake, layers: made };
});
vi.mock('@exulanica/atlas-react/things', async (original) => ({
  ...(await original<typeof import('@exulanica/atlas-react/things')>()),
  ThingLayer: FakeLayer,
}));

const LOOK = (key: string): Named => ({ key, version: 1, sha256: 'd'.repeat(64) });
const choice = (thingId: string, placedId: string | null, key: string): ThingLookChoice =>
  ({ thingId, placedId, look: LOOK(key), chosenBy: placedId === null ? 'crossing' : 'owner', chosenAt: '2026-10-09T14:03:11.123456Z' });

async function mount() {
  const shell = document.createElement('div');
  const things = await mountThings({
    app: {} as never, camera: {} as never, shell, credentials: { baseUrl: 'https://host.test', token: 'token' },
    regionRoot: () => null, invalidate: () => undefined, reducedMotion: () => false,
    library: async () => ({ list: { kinds: [], looks: [] } }) as never,
  });
  return { things, layer: layers.at(-1)! };
}

const person = (id: string): OwnedSocietyState['inhabitants'][number] =>
  ({ id, synthetic: true, position_mm: [0, 0], kind: { kind: 'visitor', version: 1, sha256: 'e'.repeat(64) }, came_by: 'crossed' });

describe('the looks chosen for a society\'s things', () => {
  it('dresses a person in the crowd and a placed thing in the layer, and undresses a withdrawn choice', async () => {
    const { things, layer } = await mount();
    // Before any choice the crowd asks for a person's kind's first look (none listed here).
    expect(things.crowdFigures.figureFor(person('visitor-1'))!.key).toContain('|none');
    things.setLooks(new Map([
      ['visitor-1', choice('visitor-1', null, 'kaykit-mannequin')],
      ['well-thing', choice('well-thing', 'well-1', 'stone-well')],
    ]));
    // The visitor's figure is now its chosen look's: the crowd makes it again by that key.
    expect(things.crowdFigures.figureFor(person('visitor-1'))!.key).toContain(`|kaykit-mannequin/1/${'d'.repeat(64)}`);
    // Only a placed thing's choice reaches the layer, by its placed id.
    expect(layer.looks).toEqual([['well-1', LOOK('stone-well')]]);
    things.setLooks(new Map([['visitor-1', choice('visitor-1', null, 'kaykit-mannequin')]]));
    expect(layer.looks.at(-1)).toEqual(['well-1', null]);
  });

  it('reads them when none was read, again for a thing no read covered, and never twice within the interval', () => {
    const covered = new Set(['knight', 'well']);
    // Nothing read yet: read at once.
    expect(looksReadDue(['knight'], new Set(), false, Number.NEGATIVE_INFINITY, 0)).toBe(true);
    // Read, and every thing covered: nothing to read, however long it has been.
    expect(looksReadDue(['knight', 'well'], covered, true, 0, 10 * LOOKS_READ_INTERVAL_MS)).toBe(false);
    // A visitor no read covered: read, but not within the interval of the last ask.
    expect(looksReadDue(['knight', 'visitor'], covered, true, 1000, 1000 + LOOKS_READ_INTERVAL_MS - 1)).toBe(false);
    expect(looksReadDue(['knight', 'visitor'], covered, true, 1000, 1000 + LOOKS_READ_INTERVAL_MS)).toBe(true);
    expect(LOOKS_READ_INTERVAL_MS).toBe(60_000);
  });
});
