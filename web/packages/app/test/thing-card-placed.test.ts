// @vitest-environment happy-dom
// The thing card for a placed thing that is nobody: what it is, that it decides nothing (or that
// nothing runs it yet), how it looks with who made it and its licence, any credit its licence
// asks for, and where it came from. Expected words come from the shipped catalog documents
// (assets/catalogs/things) and the approved design (deliveries CARD design.md section 2), read
// here from the files themselves, never from the card's code.
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import type { ThingLibrary } from '@exulanica/atlas-react/things';
import { mountThingCard } from '../src/composition/thing-card-mount.js';
import { creditOf, kindCameWords } from '../src/composition/thing-origin-words.js';
import { THING_PICK_EVENT, type ThingPickDetail } from '../src/composition/things.js';
import { readOrigin, readThingLooks, type LookReference } from '../src/thing-card-api.js';
import type { SelectedThing } from '../src/composition/environment-selection.js';

/** The repository, from the web workspace the suite runs in. */
const repository = `${process.cwd()}/..`;
const catalog = (path: string): Record<string, unknown> =>
  JSON.parse(readFileSync(`${repository}/assets/catalogs/things/${path}`, 'utf8')) as Record<string, unknown>;

const KNIGHT = catalog('kinds/knight.v2.json');
const WELL = catalog('kinds/well.v1.json');
const LOOKS: Record<string, Record<string, unknown>> = {
  'kaykit-knight': catalog('looks/kaykit-knight.v1.json'),
  'blocky-knight': catalog('looks/blocky-knight.v1.json'),
  'primitive-well': catalog('looks/primitive-well.v1.json'),
};

type Ref = { readonly key: string; readonly version: number; readonly sha256: string };
const kindLooks = (kind: Record<string, unknown>): Ref[] =>
  (kind['looks'] as { look: string; version: number; sha256: string }[]).map((look) => ({ key: look.look, version: look.version, sha256: look.sha256 }));

/** A library that holds the shipped documents read above, answering by key as the host does by digest. */
function library(extraLooks: Record<string, Record<string, unknown>> = {}): ThingLibrary {
  const kinds: Record<string, Record<string, unknown>> = { knight: KNIGHT, well: WELL };
  const looks = { ...LOOKS, ...extraLooks };
  return {
    kindEntry: (named: Ref) => ({ looks: kindLooks(kinds[named.key]!) }),
    kindDocument: async (named: Ref) => kinds[named.key],
    lookDocument: async (named: Ref) => looks[named.key],
  } as unknown as ThingLibrary;
}

const placed = (kind: Record<string, unknown>, thingId: string): SelectedThing => ({
  worldId: 'world:authored:saved', versionId: 'version',
  placed: {
    thingId, kind: { kind: kind['kind'] as string, version: kind['version'] as number, sha256: 'a'.repeat(64) },
    regionId: 'region:starter', removed: false, origin: { kind: 'authored', role: 'fictional' },
    transform: { xMm: 0, yMm: 0, zMm: 0, yawMicroradians: 0, scaleMilli: 1000 } as never,
  },
});

function mount(options: { lib?: ThingLibrary; worn?: ReadonlyMap<string, LookReference>; holds?: Promise<void>[] } = {}) {
  let reads = 0;
  const shell = document.createElement('div');
  document.body.replaceChildren(shell);
  const card = mountThingCard({
    selection: { decide: vi.fn(), models: () => null, openDecides: vi.fn() }, compare: null,
    shell, credentials: { baseUrl: 'https://example.test', token: 't' },
    library: async () => options.lib ?? library(),
    // Each read of the look choices waits for its own hold, so a test can answer them out of order.
    looks: async () => { await options.holds?.[reads++]; return options.worn ?? new Map(); },
  });
  shell.append(card.view.root);
  return { card, shell, root: card.view.root };
}
const settle = async () => { for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); };
const rowText = (root: HTMLElement, heading: string) =>
  [...root.querySelectorAll('.thing-card-row')].find((row) => row.querySelector('h4')?.textContent === heading)?.textContent ?? null;

describe('the thing card for a placed thing', () => {
  it('says what it is, that it decides nothing, how it looks and where it came from', async () => {
    const { card, root } = mount();
    expect(card.view.showThing!(placed(WELL, 'well-1'))).toBe(true);
    await settle();
    expect(root.querySelector('h3')?.textContent).toBe('Well');
    expect(root.querySelector('.thing-card-summary')?.textContent).toBe(WELL['summary']);
    expect(root.querySelector('.thing-card-mark')).toBeNull();
    expect(rowText(root, 'Mind')).toBe('MindNoneIt decides nothing.');
    expect(rowText(root, 'Looks like')).toBe('Looks likeWellMade for Exulanica. CC0, free to use.');
    expect(rowText(root, 'Came from')).toBe('Came fromYou placed it here. A well is one of Exulanica\'s own kinds.');
  });

  it('names who made an imported look, links its source, and owes no credit under CC0', async () => {
    const { card, root } = mount();
    card.view.showThing!(placed(KNIGHT, 'knight-1'));
    await settle();
    // The knight's first look in its kind is the imported KayKit knight.
    const origin = LOOKS['kaykit-knight']!['origin'] as { authors: string[]; sources: { reference: string }[] };
    expect(rowText(root, 'Looks like')).toContain(`Armoured knight`);
    expect(rowText(root, 'Looks like')).toContain(`By ${origin.authors[0]}. CC0, free to use.`);
    const link = root.querySelector<HTMLAnchorElement>('a.thing-card-link');
    expect(link?.href).toBe(origin.sources[0]!.reference);
    expect(link?.textContent).toBe(`From ${new URL(origin.sources[0]!.reference).host}`);
    expect(link?.rel).toBe('noopener noreferrer');
    expect(root.querySelector('.thing-card-credit')).toBeNull();
    // A being placed where nothing runs it yet says so, and offers no mind to change.
    expect(rowText(root, 'Mind')).toBe('MindNothing yetIt stands where you placed it. Nothing runs it in this world yet.');
    expect(root.querySelector('[data-action="card.mind.change"]')).toBeNull();
  });

  it('wears the look the version chose for it, and shows the credit a share-alike licence asks for', async () => {
    const shareAlike = {
      ...LOOKS['blocky-knight'], look: 'shared-look', label: 'shared figure',
      origin: {
        ...(LOOKS['blocky-knight']!['origin'] as Record<string, unknown>), class: 'imported',
        authors: ['Some Maker'], sources: [{ reference: 'https://example.org/figure' }],
        licence: { spdx: 'CC-BY-SA-3.0', verdict: 'SHIP', attribution: null, share_alike: true,
          licence_url: 'https://creativecommons.org/licenses/by-sa/3.0/', licence_text_sha256: null },
      },
    };
    const worn = new Map([['knight-1', { key: 'shared-look', version: 1, sha256: 'b'.repeat(64) }]]);
    const { card, root } = mount({ lib: library({ 'shared-look': shareAlike }), worn });
    card.view.showThing!(placed(KNIGHT, 'knight-1'));
    await settle();
    expect(rowText(root, 'Looks like')).toContain('Shared figure');
    const credit = root.querySelector<HTMLAnchorElement>('.thing-card-credit a');
    expect(credit?.textContent).toBe('Credit: Some Maker, CC-BY-SA-3.0, share alike');
    expect(credit?.href).toBe('https://creativecommons.org/licenses/by-sa/3.0/');
  });

  it('reads a placed thing\'s first look from its kind\'s document, for a kind the shipped list does not hold', async () => {
    const lib = { ...library(), kindEntry: () => { throw new Error('not in the shipped list'); } } as unknown as ThingLibrary;
    const { card, root } = mount({ lib });
    card.view.showThing!(placed(KNIGHT, 'knight-1'));
    await settle();
    expect(rowText(root, 'Looks like')).toContain('Armoured knight');
  });

  it('shows the thing picked last, never an answer that arrives late for another', async () => {
    let releaseKnight!: () => void;
    const knightHeld = new Promise<void>((resolve) => { releaseKnight = resolve; });
    const { card, root } = mount({ holds: [knightHeld, Promise.resolve()] });
    card.view.showThing!(placed(KNIGHT, 'knight-1'));
    card.view.showThing!(placed(WELL, 'well-1'));
    await settle();
    expect(root.querySelector('h3')?.textContent).toBe('Well');
    // The knight's answer arrives after the well's card is shown: it is dropped.
    releaseKnight();
    await settle();
    expect(root.querySelector('h3')?.textContent).toBe('Well');
  });

  it('takes the drawn ring away when Selected\'s panel closes over the card', async () => {
    const { card, shell, root } = mount();
    const panel = document.createElement('section');
    panel.className = 'world-panel';
    shell.append(panel);
    panel.append(root);
    const heard: ThingPickDetail[] = [];
    shell.addEventListener(THING_PICK_EVENT, (event) => heard.push((event as CustomEvent<ThingPickDetail>).detail));
    card.view.showThing!(placed(WELL, 'well-1'));
    await settle();
    panel.hidden = true;
    await settle();
    expect(heard).toEqual([null]);
  });

  it('takes the drawn ring away when it closes on a thing, and not when it closes on nobody', async () => {
    const { card, shell } = mount();
    const heard: ThingPickDetail[] = [];
    shell.addEventListener(THING_PICK_EVENT, (event) => heard.push((event as CustomEvent<ThingPickDetail>).detail));
    card.view.hide();
    expect(heard).toEqual([]);
    card.view.showThing!(placed(WELL, 'well-1'));
    await settle();
    card.view.hide();
    expect(heard).toEqual([null]);
  });
});

describe('origin words', () => {
  const origin = (fields: Record<string, unknown>) => readOrigin({
    profile: 'exulanica.origin/v1', class: 'authored', by: { kind: 'project' }, sources: [], authors: [],
    licence: { spdx: 'CC0-1.0', verdict: 'SHIP', attribution: null, share_alike: false, licence_url: null, licence_text_sha256: null },
    lineage: {}, distribution: 'public', ...fields,
  });
  it('say where a kind came from by its origin class alone', () => {
    expect(kindCameWords('lantern', origin({}))).toBe('A lantern is one of Exulanica\'s own kinds.');
    expect(kindCameWords('dragon', origin({ class: 'drafted', by: { kind: 'model' } }))).toBe('A dragon is a kind a model drafted from words.');
    // A drafted kind's origin names the model that drafted it (the creature drafter's provenance):
    // the card says which open model, by the name the server reads for it where it gave one.
    const drafted = origin({ class: 'drafted', by: { kind: 'model', provider: 'nebius_token_factory', model_id: 'nvidia/nemotron-3-super-120b-a12b' } });
    expect(drafted.model).toEqual({ provider: 'nebius_token_factory', modelId: 'nvidia/nemotron-3-super-120b-a12b' });
    expect(kindCameWords('dragon', drafted)).toBe('A dragon is a kind the open model nvidia/nemotron-3-super-120b-a12b drafted from words.');
    expect(kindCameWords('dragon', drafted, 'Nemotron 3 Super')).toBe('A dragon is a kind the open model Nemotron 3 Super drafted from words.');
    expect(origin({}).model).toBeNull();
    expect(kindCameWords('crate', origin({ class: 'imported', sources: [{ reference: 'https://example.org/crate' }] })))
      .toBe('A crate is a kind imported from example.org.');
  });
  it('owe a credit exactly where the licence asks for attribution or share-alike', () => {
    expect(creditOf(origin({}))).toBeNull();
    expect(creditOf(origin({ licence: { spdx: 'CC-BY-4.0', attribution: 'Pat Maker', share_alike: false, licence_url: null } })))
      .toEqual({ text: 'Credit: Pat Maker, CC-BY-4.0', href: null });
  });
  it('read a version\'s look choices by placed id, or by thing id for a thing no author placed, and refuse another profile', () => {
    const looks = readThingLooks({ profile: 'exulanica.thing-look-choices/v1', version_id: 'v', looks: [
      { thing_id: 't', placed_id: 'knight-1', look: { look: 'blocky-knight', version: 1, sha256: 'c'.repeat(64) }, chosen_by: 'owner', chosen_at: 'x' },
      { thing_id: 'u', placed_id: null, look: { look: 'blocky-knight', version: 1, sha256: 'c'.repeat(64) }, chosen_by: 'crossing', chosen_at: 'x' },
    ] });
    expect([...looks]).toEqual([
      ['knight-1', { key: 'blocky-knight', version: 1, sha256: 'c'.repeat(64) }],
      ['u', { key: 'blocky-knight', version: 1, sha256: 'c'.repeat(64) }],
    ]);
    expect(() => readThingLooks({ profile: 'exulanica.thing-look-choices/v2', looks: [] })).toThrow();
  });
});
