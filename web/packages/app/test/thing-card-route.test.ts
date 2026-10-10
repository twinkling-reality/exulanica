// @vitest-environment happy-dom
// The thing card over the server's own card for a thing (exulanica.thing-card/v1, THINGS 4b): what
// it can do here and what others can do with it, in the catalogs' own words; what it holds; and
// its look, changed from the card in two clicks, with the proof that nothing it does changed.
// Served cards here are built from the shipped catalog documents (assets/catalogs/things); the
// words for the swap and its proof come from the approved design (deliveries CARD design.md
// section 4) and package 8's plan (deliveries/CARD/wip/package-8-plan.md), never from the card's code.
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import type { ThingLibrary } from '@exulanica/atlas-react/things';
import { mountThingCard } from '../src/composition/thing-card-mount.js';
import { THING_LOOK_CHOSEN_EVENT } from '../src/composition/things.js';
import type { SelectedBeing, SelectedPerson, SelectedThing } from '../src/composition/environment-selection.js';
import {
  chooseThingLook, fetchThingCardRoute, readThingCardRoute,
  type CardLookReference, type LookChoiceOutcome, type ThingCardRoute,
} from '../src/thing-card-route-api.js';

const repository = `${process.cwd()}/..`;
const read = (path: string): Record<string, unknown> =>
  JSON.parse(readFileSync(`${repository}/assets/catalogs/things/${path}`, 'utf8')) as Record<string, unknown>;
const KNIGHT = read('kinds/knight.v2.json');
const WELL = read('kinds/well.v2.json');
const LOOKS: Record<string, Record<string, unknown>> = {
  'kaykit-knight': read('looks/kaykit-knight.v1.json'),
  'blocky-knight': read('looks/blocky-knight.v1.json'),
  'primitive-well': read('looks/primitive-well.v1.json'),
};
type Entry = { key: string; words: string; module?: string | null };
const ABILITIES = (read('abilities.v1.json')['entries'] as Entry[]);
const OFFERS = (read('offers.v1.json')['entries'] as Entry[]);
const ability = (key: string) => ABILITIES.find((entry) => entry.key === key)!;
const offer = (key: string) => OFFERS.find((entry) => entry.key === key)!;
const kindLook = (kind: Record<string, unknown>, key: string) =>
  (kind['looks'] as { look: string; version: number; sha256: string }[]).find((look) => look.look === key)!;

const BEFORE = '1'.repeat(12) + 'a'.repeat(52);
const KNIGHT_ID = '0b9f3c1e-7a51-4c8e-9d2f-1a2b3c4d5e6f';
const WELL_ID = '5d0c2a8b-3e4f-4a1b-8c9d-0e1f2a3b4c5d';

/** A served card for the knight, as THINGS 4b's route states it, from the catalogs' own documents. */
function knightCard(worn: string, tick = 12, stateSha256 = BEFORE): Record<string, unknown> {
  const look = LOOKS[worn]!;
  const ref = kindLook(KNIGHT, worn);
  return {
    profile: 'exulanica.thing-card/v1',
    thing_id: KNIGHT_ID,
    subject_id: KNIGHT_ID,
    label: 'Knight',
    came_by: 'placed',
    kind: { kind: 'knight', version: KNIGHT['version'], sha256: 'a'.repeat(64), label: KNIGHT['label'], summary: KNIGHT['summary'], class: 'being', body: { plan: 'humanoid/v1' } },
    runs: ['exulanica-ability/purposeful/v1', 'exulanica-ability/hands/v1', 'exulanica-ability/say/v1'],
    abilities: ['talk', 'pick_up', 'give', 'say'].map((key) => ({ key, words: ability(key).words, module: ability(key).module })),
    offers: ['talk_to', 'receive'].map((key) => ({ key, words: offer(key).words, module: 'exulanica-ability/hands/v1' })),
    where: { on_ground: true, held_by: null, socket: null, on: null },
    holding: [{ thing_id: 'c'.repeat(8), label: read('kinds/sword.v3.json')['label'], socket: 'hand.right' }],
    decider: { kind: 'routine', from: null, may_change: true, refusal: null },
    look: { look: worn, version: ref.version, sha256: ref.sha256, label: look['label'], look_kind_words: 'a rigged figure', chosen_by_owner: worn !== 'kaykit-knight', origin: look['origin'] },
    looks: ['kaykit-knight', 'blocky-knight'].map((key) => ({
      look: key, version: kindLook(KNIGHT, key).version, sha256: kindLook(KNIGHT, key).sha256, label: LOOKS[key]!['label'],
      licence: (LOOKS[key]!['origin'] as { licence: unknown }).licence,
      authors: (LOOKS[key]!['origin'] as { authors: string[] }).authors, preview: null,
    })),
    kind_origin: KNIGHT['origin'],
    crossing: null,
    lines: [],
    society: { tick, state_sha256: stateSha256 },
  };
}

function library(): ThingLibrary {
  const kinds: Record<string, Record<string, unknown>> = { knight: KNIGHT, well: WELL };
  return {
    list: { kinds: [], looks: [], bodyPlansSha256: 'c'.repeat(64) },
    kindDocument: async (named: { key: string }) => kinds[named.key],
    lookDocument: async (named: { key: string }) => LOOKS[named.key],
  } as unknown as ThingLibrary;
}

const knightBeing = (): SelectedBeing => ({
  kind: { kind: 'knight', version: KNIGHT['version'] as number, sha256: 'a'.repeat(64) }, cameBy: 'placed', placedId: 'knight-1',
  crossing: null, mark: { running: null }, holding: [], world: { worldId: 'world:authored:saved', versionId: 'version' }, said: [], heard: [],
});
const about = (): SelectedPerson => ({
  note: { title: 'Knight', description: 'A person in this world.', activity: 'Walking to the well.' } as SelectedPerson['note'],
  mind: null, being: knightBeing(),
});

function mount(options: {
  card?: (thingId: string) => Promise<ThingCardRoute | null>;
  chooseLook?: (thingId: string, look: CardLookReference) => Promise<LookChoiceOutcome>;
} = {}) {
  const shell = document.createElement('div');
  document.body.replaceChildren(shell);
  const mounted = mountThingCard({
    selection: { decide: vi.fn(), models: () => null, openDecides: vi.fn() }, compare: null,
    shell, credentials: { baseUrl: 'https://example.test', token: 't' },
    library: async () => library(),
    looks: async () => new Map(),
    manifest: async () => { throw new Error('no manifest'); },
    card: async (_world, _version, thingId) => (options.card === undefined ? null : options.card(thingId)),
    ...(options.chooseLook === undefined ? {} : { chooseLook: async (_world: string, _version: string, thingId: string, look: CardLookReference) => options.chooseLook!(thingId, look) }),
  });
  shell.append(mounted.view.root);
  return { mounted, shell, root: mounted.view.root };
}
const settle = async () => { for (let i = 0; i < 8; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); };
const rowOf = (root: HTMLElement, heading: string) =>
  [...root.querySelectorAll<HTMLElement>('.thing-card-row')].find((row) => row.querySelector('h4')?.textContent === heading) ?? null;
const chips = (root: HTMLElement, heading: string) => [...(rowOf(root, heading)?.querySelectorAll('.thing-card-chips li') ?? [])].map((li) => li.textContent);
const click = (root: HTMLElement, selector: string) => root.querySelector<HTMLButtonElement>(selector)!.click();

describe('the served card, read', () => {
  it('takes what the card shows and refuses another profile or a malformed record', () => {
    const card = readThingCardRoute(knightCard('kaykit-knight'));
    expect(card.can).toEqual(['talk', 'pick_up', 'give', 'say'].map((key) => ability(key).words));
    expect(card.offers).toEqual([offer('talk_to').words, offer('receive').words]);
    expect(card.holding).toEqual([read('kinds/sword.v3.json')['label']]);
    expect(card.look!.ref).toEqual({ source: 'shipped', key: 'kaykit-knight', ...{ version: kindLook(KNIGHT, 'kaykit-knight').version, sha256: kindLook(KNIGHT, 'kaykit-knight').sha256 } });
    expect(card.society).toEqual({ tick: 12, stateSha256: BEFORE });
    expect(() => readThingCardRoute({ ...knightCard('kaykit-knight'), profile: 'exulanica.thing-card/v2' })).toThrow();
    expect(() => readThingCardRoute({ ...knightCard('kaykit-knight'), society: { tick: 12, state_sha256: 'not a digest' } })).toThrow();
  });

  it('reads the open model that drafted a made kind, and none for a shipped one', () => {
    // A shipped kind's card states no drafting model.
    expect(readThingCardRoute(knightCard('kaykit-knight')).draftedBy).toBeNull();
    // A being of a kind its workspace keeps, as the server's card states it (docs/things-contract.md):
    // named by digest alone, with the model its origin records and the name the server reads for it.
    const base = knightCard('kaykit-knight');
    const made = {
      ...base,
      label: 'Four legged creature',
      kind: {
        source: 'workspace', sha256: 'd'.repeat(64), held: true, label: 'street dragon', summary: 'A dragon that walks the streets.', class: 'being',
        body: { plan: null, name: 'four legged creature', summary: 'A creature about 12 m long.' },
        drafted_by: { provider: 'nebius_token_factory', model_id: 'nvidia/nemotron-3-super-120b-a12b', name: 'Nemotron 3 Super' },
      },
    };
    expect(readThingCardRoute(made).draftedBy).toEqual({ provider: 'nebius_token_factory', modelId: 'nvidia/nemotron-3-super-120b-a12b', name: 'Nemotron 3 Super' });
    // Once its workspace erased the creature the card is as the server serves it until the being
    // leaves (docs/things-contract.md, "Its card"): held false, its body's name for a label, no
    // drafting model, no look and no looks to choose. The page reads it and names no model or look.
    const erased = readThingCardRoute({
      ...made,
      kind: { ...made.kind, held: false, label: 'four legged creature', summary: 'A creature about 12 m long.', drafted_by: null },
      look: null, looks: [], kind_origin: null,
    });
    expect(erased.draftedBy).toBeNull();
    expect(erased.look).toBeNull();
    expect(erased.looks).toEqual([]);
    expect(() => readThingCardRoute({ ...made, kind: { ...made.kind, drafted_by: { provider: 'p' } } })).toThrow();
  });

  it('reads a look the workspace keeps by its digest alone', () => {
    const own = { source: 'workspace', sha256: 'd'.repeat(64), label: 'sketched knight', licence: null, authors: [], preview: null };
    const card = readThingCardRoute({ ...knightCard('kaykit-knight'), looks: [own] });
    expect(card.looks[0]).toEqual({ ref: { source: 'workspace', sha256: 'd'.repeat(64) }, label: 'sketched knight', authors: [], licence: null });
  });

  it('asks the society-thing address, answers null for 404, and sends a look as the route takes it', async () => {
    const asked: { url: string; init: RequestInit | undefined }[] = [];
    const answer = (status: number, body: unknown) => async (url: RequestInfo | URL, init?: RequestInit) => {
      asked.push({ url: String(url), init });
      return new Response(JSON.stringify(body), { status });
    };
    const access = { baseUrl: 'https://example.test', token: 't' };
    expect(await fetchThingCardRoute(access, 'world:a', 'version-1', KNIGHT_ID, answer(404, { code: 'not_found' }) as typeof fetch)).toBeNull();
    expect(asked[0]!.url).toBe(`https://example.test/world/versions/version-1/society/things/${KNIGHT_ID}?world_id=world%3Aa`);
    await chooseThingLook(access, 'world:a', 'version-1', KNIGHT_ID, { source: 'workspace', sha256: 'd'.repeat(64) }, answer(200, knightCard('blocky-knight')) as typeof fetch);
    expect(asked[1]!.url).toBe(`https://example.test/world/versions/version-1/society/things/${KNIGHT_ID}/look?world_id=world%3Aa`);
    expect(JSON.parse(String(asked[1]!.init?.body))).toEqual({ look: { source: 'workspace', sha256: 'd'.repeat(64) } });
    const shipped = kindLook(KNIGHT, 'blocky-knight');
    await chooseThingLook(access, 'world:a', 'version-1', KNIGHT_ID, { source: 'shipped', key: 'blocky-knight', version: shipped.version, sha256: shipped.sha256 }, answer(200, knightCard('blocky-knight')) as typeof fetch);
    expect(JSON.parse(String(asked[2]!.init?.body))).toEqual({ look: { look: 'blocky-knight', version: shipped.version, sha256: shipped.sha256 } });
    const refused = await chooseThingLook(access, 'world:a', 'version-1', KNIGHT_ID, { source: 'workspace', sha256: 'd'.repeat(64) }, answer(422, { code: 'look_unfit', detail: '' }) as typeof fetch);
    expect(refused).toEqual({ chosen: false, code: 'look_unfit' });
  });
});

describe('a being\'s card from the served card', () => {
  it('says what it can do, what others can do with it and what it holds, in the catalogs\' words', async () => {
    const { mounted, root } = mount({ card: async () => readThingCardRoute(knightCard('kaykit-knight')) });
    mounted.view.show(KNIGHT_ID, about());
    await settle();
    expect(chips(root, 'Can')).toEqual(['talk', 'pick_up', 'give', 'say'].map((key) => ability(key).words));
    expect(chips(root, 'With it')).toEqual([offer('talk_to').words, offer('receive').words]);
    expect(rowOf(root, 'Holding')?.textContent).toBe(`Holding${'a'} ${read('kinds/sword.v3.json')['label']}`);
    expect(rowOf(root, 'Looks like')?.textContent).toContain('Armoured knight');
  });

  it('without a served card it keeps today\'s rows and offers no look Change', async () => {
    const { mounted, root } = mount({ card: async () => null });
    mounted.view.show(KNIGHT_ID, about());
    await settle();
    expect(rowOf(root, 'Can')).toBeNull();
    expect(rowOf(root, 'With it')).toBeNull();
    expect(rowOf(root, 'Looks like')?.textContent).toContain('Armoured knight');
    expect(root.querySelector('[data-action="card.look.change"]')).toBeNull();
  });

  it('changes its look in two clicks, redraws it at once, and shows the proof under How we know', async () => {
    const sent: CardLookReference[] = [];
    let reads = 0;
    const { mounted, shell, root } = mount({
      // The first read before the swap, then the read after it.
      card: async () => readThingCardRoute(knightCard(reads++ === 0 ? 'kaykit-knight' : 'blocky-knight')),
      chooseLook: async (_thing, look) => { sent.push(look); return { chosen: true, card: readThingCardRoute(knightCard('blocky-knight')) }; },
    });
    const redraws: unknown[] = [];
    shell.addEventListener(THING_LOOK_CHOSEN_EVENT, (event) => redraws.push((event as CustomEvent).detail));
    mounted.view.show(KNIGHT_ID, about());
    await settle();
    click(root, '[data-action="card.look.change"]');
    const options = [...root.querySelectorAll<HTMLButtonElement>('[data-action="card.look.choose"]')];
    expect(options.map((option) => option.querySelector('.thing-card-choice-name')?.textContent)).toEqual(['Armoured knight', 'Blocky knight']);
    // The look it wears is marked Now and cannot be chosen again.
    expect(options[0]!.hasAttribute('data-now')).toBe(true);
    expect(options[0]!.disabled).toBe(true);
    options[1]!.click();
    await settle();
    const blocky = kindLook(KNIGHT, 'blocky-knight');
    expect(sent).toEqual([{ source: 'shipped', key: 'blocky-knight', version: blocky.version, sha256: blocky.sha256 }]);
    expect(redraws).toEqual([{ thingId: KNIGHT_ID }]);
    const row = rowOf(root, 'Looks like')!;
    expect(row.querySelector('.thing-card-outcome')?.textContent)
      .toBe('Now drawn as a blocky knight. Only its look changed: what it does, says and decides is exactly the same.');
    expect(row.querySelector('.thing-card-mind-name')?.textContent).toBe('Blocky knight');
    const proof = row.querySelector('details.thing-card-proof')!;
    expect(proof.hasAttribute('open')).toBe(false);
    expect(proof.querySelector('summary')?.textContent).toBe('How we know');
    expect(proof.querySelector('p')?.textContent).toContain(`minute 12`);
    expect(proof.querySelector('p')?.textContent).toContain(`${BEFORE.slice(0, 12)} and ${BEFORE.slice(0, 12)}, the same`);
    // No record digest anywhere else on the card.
    expect(root.textContent!.replace(proof.textContent!, '')).not.toContain(BEFORE.slice(0, 12));
  });

  it('says plainly when the world moved on between the two reads, and when a record differs at one minute', async () => {
    const other = '2'.repeat(64);
    for (const [after, words] of [
      [knightCard('blocky-knight', 13, other), 'The world moved on from minute 12 to minute 13 between the two reads'],
      [knightCard('blocky-knight', 12, other), `This world's record at minute 12 read ${BEFORE.slice(0, 12)} as the look changed and ${other.slice(0, 12)} after.`],
    ] as const) {
      let reads = 0;
      const { mounted, root } = mount({
        card: async () => readThingCardRoute(reads++ === 0 ? knightCard('kaykit-knight') : after),
        chooseLook: async () => ({ chosen: true, card: readThingCardRoute(knightCard('blocky-knight')) }),
      });
      mounted.view.show(KNIGHT_ID, about());
      await settle();
      click(root, '[data-action="card.look.change"]');
      root.querySelectorAll<HTMLButtonElement>('[data-action="card.look.choose"]')[1]!.click();
      await settle();
      expect(root.querySelector('details.thing-card-proof p')?.textContent).toContain(words);
    }
  });

  it('says why a look was refused, and that only the owner may change one', async () => {
    for (const [code, words] of [
      ['look_unfit', 'That look is made for another body, so it cannot be drawn in it.'],
      ['look_not_shipped', 'That look is no longer offered here. Choose another.'],
      ['http_403', 'Only this world\'s owner can change how its things are drawn.'],
    ] as const) {
      const redraws: unknown[] = [];
      const { mounted, shell, root } = mount({
        card: async () => readThingCardRoute(knightCard('kaykit-knight')),
        chooseLook: async () => ({ chosen: false, code }),
      });
      shell.addEventListener(THING_LOOK_CHOSEN_EVENT, (event) => redraws.push(event));
      mounted.view.show(KNIGHT_ID, about());
      await settle();
      click(root, '[data-action="card.look.change"]');
      root.querySelectorAll<HTMLButtonElement>('[data-action="card.look.choose"]')[1]!.click();
      await settle();
      expect(root.querySelector('.thing-card-outcome')?.textContent).toBe(words);
      expect(root.querySelector('details.thing-card-proof')).toBeNull();
      expect(redraws).toEqual([]);
    }
  });
});

describe('a placed object\'s card from the served card', () => {
  const placed = (societyThingId: string | null): SelectedThing => ({
    worldId: 'world:authored:saved', versionId: 'version', societyThingId,
    placed: {
      thingId: 'well-1', kind: { kind: 'well', version: WELL['version'] as number, sha256: 'a'.repeat(64) },
      regionId: 'region:starter', removed: false, origin: { kind: 'authored', role: 'fictional' },
      transform: { xMm: 0, yMm: 0, zMm: 0, yawMicroradians: 0, scaleMilli: 1000 } as never,
    },
  });
  const wellCard = (): Record<string, unknown> => {
    const own = kindLook(WELL, 'primitive-well');
    const lookDoc = LOOKS['primitive-well']!;
    return {
      ...knightCard('kaykit-knight'), thing_id: WELL_ID, subject_id: null, came_by: 'placed', label: WELL['label'],
      abilities: [], offers: [{ key: 'rest_at', words: offer('rest_at').words, module: 'exulanica-ability/purposeful/v1' }],
      holding: null, decider: null, lines: null,
      look: { look: 'primitive-well', version: own.version, sha256: own.sha256, label: lookDoc['label'], look_kind_words: 'a solid object', chosen_by_owner: false, origin: lookDoc['origin'] },
      looks: [{ look: 'primitive-well', version: own.version, sha256: own.sha256, label: lookDoc['label'], licence: (lookDoc['origin'] as { licence: unknown }).licence, authors: [], preview: null }],
    };
  };

  it('reads it by the id its society gives it: what others can do with it, and no Change with one look', async () => {
    const asked: string[] = [];
    const { mounted, root } = mount({ card: async (thingId) => { asked.push(thingId); return readThingCardRoute(wellCard()); } });
    mounted.view.showThing!(placed(WELL_ID));
    await settle();
    expect(asked).toEqual([WELL_ID]);
    expect(rowOf(root, 'Can')).toBeNull();
    expect(chips(root, 'With it')).toEqual([offer('rest_at').words]);
    expect(rowOf(root, 'Holding')).toBeNull();
    expect(root.querySelector('[data-action="card.look.change"]')).toBeNull();
  });

  it('a placed thing no society holds asks for no served card', async () => {
    const asked: string[] = [];
    const { mounted, root } = mount({ card: async (thingId) => { asked.push(thingId); return null; } });
    mounted.view.showThing!(placed(null));
    await settle();
    expect(asked).toEqual([]);
    expect(rowOf(root, 'Looks like')?.textContent).toContain('Well');
  });
});
