// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import type { Named, ThingLayerOptions } from '@exulanica/atlas-react/things';
import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import { LOOKS_READ_INTERVAL_MS, looksReadDue, mountThings } from '../src/composition/things.js';
import type { ThingLookChoice } from '../src/thing-looks-api.js';
import type { PlacedThing } from '../src/world-objects-api.js';

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
    walkEnded: unknown = null;
    setSociety(_state: unknown, _figures: unknown, walkEnded: unknown) { this.walkEnded = walkEnded; }
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

async function mount(walkEnded?: (subjectId: string) => boolean) {
  const shell = document.createElement('div');
  const things = await mountThings({
    app: {} as never, camera: {} as never, shell, credentials: { baseUrl: 'https://host.test', token: 'token' },
    regionRoot: () => null, invalidate: () => undefined, reducedMotion: () => false,
    library: async () => ({ list: { kinds: [], looks: [] } }) as never,
    ...(walkEnded === undefined ? {} : { walkEnded }),
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

  it('dresses a thing with no choice of its own in its workspace kind\'s look, after its own choice, before its kind\'s first', async () => {
    const { things, layer } = await mount();
    const MADE = 'f'.repeat(64);
    const made = { source: 'workspace' as const, sha256: MADE };
    const placed = (thingId: string): PlacedThing => ({
      thingId, kind: made, regionId: 'r', removed: false, origin: { kind: 'authored', role: 'thing' },
      transform: { xMm: 0, yMm: 0, zMm: 0, yawMicroradians: 0, scaleMilli: 1000 } as PlacedThing['transform'],
    });
    const creature = (id: string): OwnedSocietyState['inhabitants'][number] =>
      ({ id, synthetic: true, position_mm: [0, 0], kind: made, came_by: 'populated' }) as never;
    await things.setPlaced([placed('duck-1'), placed('duck-2')]);
    const looks = (choices: [string, ThingLookChoice][], kinds: [string, Named][]) =>
      Object.assign(new Map(choices), { kinds: new Map(kinds) });
    things.setLooks(looks([['thing-2', choice('thing-2', 'duck-2', 'chosen-duck')]], [[MADE, LOOK('made-duck')]]));
    // The placed thing with no choice wears its kind's look; the one with a choice wears its choice.
    expect(new Map(layer.looks)).toEqual(new Map([['duck-1', LOOK('made-duck')], ['duck-2', LOOK('chosen-duck')]]));
    // So does a person of that kind in the crowd.
    expect(things.crowdFigures.figureFor(creature('walker'))!.key).toContain(`|made-duck/1/${'d'.repeat(64)}`);
    // The same looks read again draw nothing again: each look given redraws the layer.
    const given = layer.looks.length;
    things.setLooks(looks([['thing-2', choice('thing-2', 'duck-2', 'chosen-duck')]], [[MADE, LOOK('made-duck')]]));
    expect(layer.looks.length).toBe(given);
    // The kind's look withdrawn: the thing returns to its kind's first look.
    things.setLooks(looks([['thing-2', choice('thing-2', 'duck-2', 'chosen-duck')]], []));
    expect(layer.looks.at(-1)).toEqual(['duck-1', null]);
    expect(things.crowdFigures.figureFor(creature('walker'))!.key).toContain('|none');
  });

  it('reads them at once, then once a minute however settled the things are, never twice within the minute', () => {
    // Nothing asked yet: read at once.
    expect(looksReadDue(Number.NEGATIVE_INFINITY, 0)).toBe(true);
    // Every thing read and nothing new: still read once the minute is out, for a choice made elsewhere or withdrawn.
    expect(looksReadDue(1000, 1000 + LOOKS_READ_INTERVAL_MS - 1)).toBe(false);
    expect(looksReadDue(1000, 1000 + LOOKS_READ_INTERVAL_MS)).toBe(true);
    // One private read a minute per open world page.
    expect(LOOKS_READ_INTERVAL_MS).toBe(60_000);
  });

  it('hands the layer the crowd\'s word on whose walk has ended, which a thing changing hands waits for', async () => {
    const walkEnded = (id: string) => id === 'arrived';
    const { things, layer } = await mount(walkEnded);
    things.setSociety({ profile: 'exulanica-society/v7', tick: 1, inhabitants: [], things: [] });
    expect(layer.walkEnded).toBe(walkEnded);
  });
});
