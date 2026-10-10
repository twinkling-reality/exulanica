// @vitest-environment happy-dom
// The look a town is made in, in Create a world: the look a draft's words ask for is said under
// Describe it, taken with the draft, shown in the Look row as coming from the person's words, and
// named exactly in the making; a look the person chose themselves is never replaced, and a look
// that came with a draft follows the next draft taken.
//
// The pieces are the page's own, wired as Create a world wires them: the description panel
// (attachWorldDescription), the recipes panel, the town's look and the saved-world client, over one
// fetch that answers as the server does. The packs are the committed library's, read from their
// manifests, and the draft's look offer is written here as the contract states it.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { URL as FileUrl } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Credentials } from '../src/config.js';
import type { ListedStylePack } from '../src/world-look.js';
import { servedSpecification } from './world-specification-document.js';

const listed = vi.hoisted(() => ({ packs: [] as ListedStylePack[] }));
vi.mock('../src/world-look.js', async (original) => ({
  ...await original<typeof import('../src/world-look.js')>(),
  listedStylePacks: async () => listed.packs,
  stylePackContent: async () => new Uint8Array([1, 2, 3]),
}));
const { readLookLibrary } = await import('../src/composition/look-library.js');
const { buildTownLook } = await import('../src/composition/town-look.js');
const { attachWorldDescription } = await import('../src/composition/world-description.js');
const { buildWorldRecipes } = await import('../src/ui/world-recipes.js');
const { WorldEntryClient } = await import('../src/world-entry-api.js');
const { parseWorldSpecification } = await import('../src/world-specification.js');

const REPOSITORY = new FileUrl('../../../../', import.meta.url);
const committed = (path: string): Buffer => readFileSync(new FileUrl(path, REPOSITORY));

/**
 * A committed pack as the host lists it: its manifest's own words, named by the digest of its
 * canonical bytes, which the committed file holds before its one closing newline.
 */
function listedPack(packId: string, isDefault: boolean): ListedStylePack {
  const file = committed(`assets/style-packs/packs/${packId}/manifest.json`);
  const manifest = JSON.parse(file.toString('utf8')) as {
    pack_id: string; version: number; title: string; description: string; authors: string[];
  };
  return {
    pack_id: manifest.pack_id, version: manifest.version, title: manifest.title,
    description: manifest.description, authors: manifest.authors,
    manifest_sha256: createHash('sha256').update(file.subarray(0, file.length - 1)).digest('hex'),
    licence: { id: 'CC0-1.0', attribution: null }, default: isDefault,
  };
}
const DEFAULT_PACK = (JSON.parse(committed('assets/style-packs/library.v1.json').toString('utf8')) as { default: string }).default;
const PACKS = ['exulanica.cozy-town', 'exulanica.finished-town', 'exulanica.toon-town']
  .map((packId) => listedPack(packId, packId === DEFAULT_PACK));
const pack = (packId: string): ListedStylePack => PACKS.find((one) => one.pack_id === packId)!;
const TOON = pack('exulanica.toon-town');
const FINISHED = pack('exulanica.finished-town');

const DESCRIPTION = 'A bright cartoon town like a toy box, with lofts, cafes and restaurants.';
/**
 * The look offer a draft of DESCRIPTION carries. Its version and digest are not the ones the page's
 * list holds for the pack, as when the library moved after the page read it: only the offer says
 * them, so a making that names them took them from the offer.
 */
const OFFERED = { pack_id: TOON.pack_id, version: TOON.version + 1, manifest_sha256: '7'.repeat(64) };
const lookOffer = (overrides: Record<string, unknown> = {}) => ({
  state: 'offered', reason: null, ...OFFERED, look_words: ['bright cartoon', 'toy box'],
  prompt_version: 'look-choosing-1', prompt_sha256: 'e'.repeat(64),
  execution: { prompt_version: 'look-choosing-1', rejections: [], calls: [{
    role: 'look_chooser', requested_model: 'example/chooser', served_model: 'example/chooser',
    requested_model_name: 'Chooser Model', served_model_name: 'Chooser Model', used_fallback: false,
    attempts: 1, latency_ms: 900, prompt_tokens: 210, completion_tokens: 24, reasoning_tokens: null,
    usd: '0.0001', served_model_unavailable: null, outcome: 'completed', cost_basis: 'known',
  }] },
  ...overrides,
});
/** A later sentence in the same sitting, with none of the words that chose a look before. */
const LATER = 'A quiet town with short blocks and a grocery on the corner.';
/** Offers that name no look: the words ask for none, or the step did not answer. */
const NO_LOOK = lookOffer({ state: 'none', pack_id: null, version: null, manifest_sha256: null, look_words: [] });
const NOT_ANSWERED = lookOffer({
  state: 'unavailable', reason: 'timed_out', pack_id: null, version: null, manifest_sha256: null, look_words: [],
});
const draftAnswer = (offer: unknown, description: string) => ({
  description,
  proposal: {
    preset: 'small_town', values: { city_extent_x_mm: 256000, block_length_mm: 100000 },
    set_by_words: ['block_length_mm'], fit: 'all', valid: true, value_refusal: null,
    sample: { status: 'unavailable', tiles: null, people: null, vehicles: null, vehicles_refused: null,
      streets: [], premises: [], buildings: null, refused: null },
  },
  not_supported: [], refusal: null, specification_version: 1, specification_sha256: 'a'.repeat(64),
  prompt_version: 'world-drafting-2', prompt_sha256: 'b'.repeat(64), model_id: 'example/drafter',
  model_name: 'Drafter Model',
  execution: { prompt_version: 'world-drafting-2', rejections: [], calls: [] },
  ...(offer === undefined ? {} : { look_offer: offer }),
});

/** A saved entry as `POST /worlds/generated` answers, cut to what the client reads. */
const madeEntry = {
  entry_id: '11111111-1111-4111-8111-111111111111', world_id: 'world:made', title: 'A small town',
  source_kind: 'generated', source_snapshot_id: '55555555-5555-4555-8555-555555555555',
  source_snapshot_sha256: 'c'.repeat(64), authored_scene: null,
  authored_version_id: '22222222-2222-4222-8222-222222222222', authored_state_sha256: 'a'.repeat(64),
  authored_edit_seq: 0, current_authored_state_sha256: 'a'.repeat(64), current_authored_edit_seq: 0,
  style_version_id: '33333333-3333-4333-8333-333333333333', revision: 1, availability: 'available',
  unavailable_reason: null, source_attachments: [], created_by: '44444444-4444-4444-8444-444444444444',
  created_at: '2026-10-09T12:00:00Z', updated_at: '2026-10-09T12:00:00Z', takes_photographs: false,
  generated_ground: {
    recipe_key: 'small_town', recipe_label: 'A small town', region_id: 'region:generated',
    arrival_mm: [64000, 99, -58700], arrival_facing_mm: [0, 3400],
    tiles: [{ tile_x: 0, tile_y: 0, tile_inputs_digest: 'f'.repeat(64), baked_tile_id: null, state: 'baking' }],
  },
};

const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 20; turn += 1) await Promise.resolve();
};

/**
 * Create a world as the page builds it, over a server that drafts `offer` (then `later`, for every
 * draft after the first, where one is given) and makes or refuses. A draft answers the words it was
 * sent, as the route does. `requests` holds every body sent to `POST /worlds/generated`.
 */
async function createWorld(offer: unknown, options: { making?: () => Response; later?: unknown } = {}) {
  const making = options.making ?? (() => Response.json(madeEntry, { status: 201 }));
  const offers = 'later' in options ? [offer, options.later] : [offer];
  let drafts = 0;
  const requests: Record<string, unknown>[] = [];
  const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = String(input);
    if (url.endsWith('/worlds/specification/drafts')) {
      const asked = JSON.parse(String(init.body)) as { description: string };
      const answer = draftAnswer(offers[Math.min(drafts, offers.length - 1)], asked.description);
      drafts += 1;
      return Response.json(answer);
    }
    if (url.endsWith('/worlds/generated')) {
      requests.push(JSON.parse(String(init.body)) as Record<string, unknown>);
      return making();
    }
    throw new Error(`the page asked for ${url}`);
  });
  const credentials: Credentials = { baseUrl: 'https://exulanica.test', token: 'look-token' };
  const access = { ...credentials, fetch };
  const client = new WorldEntryClient(access);
  const opened: string[] = [];
  const host = document.createElement('div');
  document.body.replaceChildren(host);
  const look = buildTownLook({ library: readLookLibrary(credentials), host });
  const panel = buildWorldRecipes({
    specification: async () => parseWorldSpecification(servedSpecification()),
    make: (preset, values) => client.makeGenerated(preset.key, preset.label, values, look.binding()),
    open: async (entry) => { opened.push(entry.entryId); },
    onClose: () => undefined,
  });
  host.append(panel.root);
  panel.lookSlot.append(look.row);
  attachWorldDescription(panel, {
    credentials: access, specification: async () => parseWorldSpecification(servedSpecification()), look: look.drafted,
  });
  await vi.waitFor(() => expect(panel.root.querySelector('.world-description-input')).not.toBeNull());
  await vi.waitFor(() => expect(look.row.hidden).toBe(false));

  const text = (selector: string): string | null => host.querySelector(selector)?.textContent ?? null;
  const click = (selector: string): void => host.querySelector<HTMLButtonElement>(selector)!.click();
  return {
    host, look, requests, opened, text, click,
    row: () => ({ title: text('.look-row-title'), line: text('.look-row-line') }),
    lookLine: () => text('.world-description-look p'),
    async draft(words = DESCRIPTION) {
      host.querySelector<HTMLTextAreaElement>('.world-description-input')!.value = words;
      click('.world-description-draft');
      // The press says it is drafting at once; the draft is there when that is gone and it can be used.
      await vi.waitFor(() => {
        expect(text('.world-description-status')).toBe('');
        expect(text('.world-description-result')).toContain(`You asked for: “${words}”`);
        expect(host.querySelector('.world-description-use')).not.toBeNull();
      });
    },
    /** Change look, a pack's card, Choose this look: the person's own choice in the Look sheet. */
    async choose(packId: string) {
      click('[data-action="look.change"]');
      click(`.look-sheet-card[data-pack-id="${packId}"]`);
      click('[data-action="look.use"]');
      await vi.waitFor(() => expect(host.querySelector('section.look-sheet')).toBeNull());
    },
    /** Use these values: the controls take them a moment later, as a person's own edit is checked. */
    async use() {
      click('.world-description-use');
      await settle();
    },
    async make() {
      click('.world-recipes-make');
      await settle();
    },
  };
}

beforeEach(() => {
  listed.packs = [...PACKS];
});
afterEach(() => document.body.replaceChildren());

describe('the look of a town drafted from words', () => {
  it('starts as the host\'s default, and a town made then names no pack', async () => {
    const page = await createWorld(lookOffer());
    expect(page.row()).toEqual({
      title: pack(DEFAULT_PACK).title,
      line: 'The look this server draws new towns in. You can change it now, or any time later in Design.',
    });
    page.click('[data-recipe="small_town"]');
    await page.make();
    expect(page.requests).toEqual([{
      recipe: 'small_town', title: 'A small town', values: { city_extent_x_mm: 256000, block_length_mm: 90000 },
    }]);
  });

  it('is said under the words, taken with the draft, marked as from the words, and named exactly in the making', async () => {
    const page = await createWorld(lookOffer());
    await page.draft();
    expect(page.lookLine()).toBe(
      `Chooser Model chose the look ${TOON.title} from your words “bright cartoon”, “toy box”.`);
    // Nothing is taken by the draft arriving: the row still shows the default.
    expect(page.row().title).toBe(pack(DEFAULT_PACK).title);
    await page.use();
    expect(page.row()).toEqual({
      title: TOON.title,
      line: 'From your words “bright cartoon”, “toy box”. You can change it now, or any time later in Design.',
    });
    expect(page.text('[data-action="look.change"]')).toBe('Change look');
    expect(page.text('.world-description-status')).toBe(
      `These values are in the controls below, and the look is ${TOON.title}. Change any of them, then make the town.`);
    // Nothing is made until the person makes the town.
    expect(page.requests).toEqual([]);
    await page.make();
    expect(page.requests).toEqual([{
      recipe: 'small_town', title: 'A small town', values: { city_extent_x_mm: 256000, block_length_mm: 100000 },
      style_pack: OFFERED,
    }]);
    expect(page.opened).toEqual([madeEntry.entry_id]);
  });

  it('is made in what the person chose when they change the look after taking the draft', async () => {
    const page = await createWorld(lookOffer());
    await page.draft();
    await page.use();
    // The sheet opens on the look taken from the words, marked Chosen.
    page.click('[data-action="look.change"]');
    expect(page.host.querySelector(`.look-sheet-card[data-pack-id="${TOON.pack_id}"] .look-sheet-caption`)!.textContent).toBe('Chosen');
    page.click('[data-action="look.keep"]');
    await page.choose(FINISHED.pack_id);
    expect(page.row()).toEqual({
      title: FINISHED.title, line: 'Your choice. You can change it any time later in Design.',
    });
    await page.make();
    expect(page.requests.map((request) => request['style_pack'])).toEqual([{
      pack_id: FINISHED.pack_id, version: FINISHED.version, manifest_sha256: FINISHED.manifest_sha256,
    }]);
  });

  it('never replaces a look the person chose before drafting, and offers the other with one press', async () => {
    const page = await createWorld(lookOffer());
    await page.choose(FINISHED.pack_id);
    await page.draft();
    expect(page.lookLine()).toBe(
      `Chooser Model chose the look ${TOON.title} from your words “bright cartoon”, “toy box”. `
      + `You chose ${FINISHED.title} yourself, so it stays.`);
    expect(page.text('.world-description-look-instead')).toBe(`Use ${TOON.title} instead`);
    await page.use();
    expect(page.row()).toEqual({
      title: FINISHED.title, line: 'Your choice. You can change it any time later in Design.',
    });
    expect(page.text('.world-description-status')).toBe(
      'These values are in the controls below. Change any of them, then make the town.');
    await page.make();
    expect(page.requests.map((request) => request['style_pack'])).toEqual([{
      pack_id: FINISHED.pack_id, version: FINISHED.version, manifest_sha256: FINISHED.manifest_sha256,
    }]);
  });

  it('takes the offered look in place of the person\'s own on its one press', async () => {
    const page = await createWorld(lookOffer());
    await page.choose(FINISHED.pack_id);
    await page.draft();
    page.click('.world-description-look-instead');
    await settle();
    expect(page.row().title).toBe(TOON.title);
    expect(page.row().line).toContain('From your words “bright cartoon”, “toy box”.');
    expect(page.text('.world-description-status')).toBe(`The look is now ${TOON.title}.`);
    // The line no longer says a choice of theirs stays, and offers nothing more to press.
    expect(page.lookLine()).toBe(
      `Chooser Model chose the look ${TOON.title} from your words “bright cartoon”, “toy box”.`);
    expect(page.host.querySelector('.world-description-look-instead')).toBeNull();
    await page.use();
    await page.make();
    expect(page.requests.map((request) => request['style_pack'])).toEqual([OFFERED]);
  });

  it('keeps a look the person chooses after the draft is shown, and its line says so at once', async () => {
    const page = await createWorld(lookOffer());
    await page.draft();
    await page.choose(FINISHED.pack_id);
    expect(page.lookLine()).toContain(`You chose ${FINISHED.title} yourself, so it stays.`);
    await page.use();
    expect(page.row().title).toBe(FINISHED.title);
    // Choosing the offered look themselves leaves nothing to offer, and it stays their choice.
    await page.choose(TOON.pack_id);
    expect(page.lookLine()).toBe(
      `Chooser Model chose the look ${TOON.title} from your words “bright cartoon”, “toy box”.`);
    await page.use();
    await page.make();
    expect(page.row().line).toBe('Your choice. You can change it any time later in Design.');
    expect(page.requests.map((request) => request['style_pack'])).toEqual([{
      pack_id: TOON.pack_id, version: TOON.version, manifest_sha256: TOON.manifest_sha256,
    }]);
  });

  it('leaves the look shown when the step did not answer or offers none', async () => {
    for (const [offer, line] of [
      [NOT_ANSWERED, 'No look was chosen from your words this time. The town will be drawn in the look shown.'],
      [NO_LOOK, null],
      [undefined, null],
      [lookOffer({ state: 'suggested' }), null],
    ] as const) {
      const page = await createWorld(offer);
      await page.draft();
      expect(page.lookLine()).toBe(line);
      await page.use();
      await page.make();
      expect(page.row().title).toBe(pack(DEFAULT_PACK).title);
      expect(page.requests).toEqual([{
        recipe: 'small_town', title: 'A small town', values: { city_extent_x_mm: 256000, block_length_mm: 100000 },
      }]);
    }
  });

  it('goes back to the server\'s look when a later draft whose words ask for no look is taken', async () => {
    const page = await createWorld(lookOffer(), { later: NO_LOOK });
    await page.draft();
    await page.use();
    expect(page.row().line).toBe(
      'From your words “bright cartoon”, “toy box”. You can change it now, or any time later in Design.');
    await page.draft(LATER);
    // Nothing is taken by the later draft arriving: it says no look, and the row is as it was.
    expect(page.lookLine()).toBeNull();
    expect(page.row().title).toBe(TOON.title);
    await page.use();
    // The look followed the draft taken: the server's look, in its own words, no earlier words quoted.
    expect(page.row()).toEqual({
      title: pack(DEFAULT_PACK).title,
      line: 'The look this server draws new towns in. You can change it now, or any time later in Design.',
    });
    expect(page.text('.world-description-status')).toBe(
      'These values are in the controls below. Change any of them, then make the town.');
    expect(page.text('[data-action="look.change"]')).toBe('Change look');
    await page.make();
    // The making names no pack, so the server makes the town in its own look.
    expect(page.requests).toEqual([{
      recipe: 'small_town', title: 'A small town', values: { city_extent_x_mm: 256000, block_length_mm: 100000 },
    }]);
  });

  it('keeps a look the person chose in the sheet when a later draft asks for no look', async () => {
    const page = await createWorld(lookOffer(), { later: NO_LOOK });
    await page.choose(FINISHED.pack_id);
    await page.draft();
    await page.use();
    await page.draft(LATER);
    await page.use();
    expect(page.row()).toEqual({
      title: FINISHED.title, line: 'Your choice. You can change it any time later in Design.',
    });
    await page.make();
    expect(page.requests.map((request) => request['style_pack'])).toEqual([{
      pack_id: FINISHED.pack_id, version: FINISHED.version, manifest_sha256: FINISHED.manifest_sha256,
    }]);
  });

  it('keeps a look the person took by their own press when a later draft asks for no look', async () => {
    const page = await createWorld(lookOffer(), { later: NO_LOOK });
    await page.choose(FINISHED.pack_id);
    await page.draft();
    page.click('.world-description-look-instead');
    await page.draft(LATER);
    await page.use();
    expect(page.row().title).toBe(TOON.title);
    await page.make();
    expect(page.requests.map((request) => request['style_pack'])).toEqual([OFFERED]);
  });

  it('keeps that look theirs when they also take the values of the draft that offered it', async () => {
    const page = await createWorld(lookOffer(), { later: NO_LOOK });
    await page.choose(FINISHED.pack_id);
    await page.draft();
    page.click('.world-description-look-instead');
    await page.use();
    expect(page.text('.world-description-status')).toBe(
      `These values are in the controls below, and the look is ${TOON.title}. Change any of them, then make the town.`);
    await page.draft(LATER);
    await page.use();
    expect(page.row().title).toBe(TOON.title);
    await page.make();
    expect(page.requests.map((request) => request['style_pack'])).toEqual([OFFERED]);
  });

  it('keeps the look shown when a later draft\'s look step did not answer', async () => {
    const page = await createWorld(lookOffer(), { later: NOT_ANSWERED });
    await page.draft();
    await page.use();
    await page.draft(LATER);
    expect(page.lookLine()).toBe(
      'No look was chosen from your words this time. The town will be drawn in the look shown.');
    await page.use();
    // The calm line stays true as written: the look shown is the one the town is made in.
    expect(page.row().title).toBe(TOON.title);
    await page.make();
    expect(page.requests.map((request) => request['style_pack'])).toEqual([OFFERED]);
  });

  it('changes nothing when a later draft\'s answer carries no offer', async () => {
    const page = await createWorld(lookOffer(), { later: undefined });
    await page.draft();
    await page.use();
    await page.draft(LATER);
    expect(page.lookLine()).toBeNull();
    await page.use();
    expect(page.row().title).toBe(TOON.title);
    await page.make();
    expect(page.requests.map((request) => request['style_pack'])).toEqual([OFFERED]);
  });

  it('neither shows nor takes an offered look the host\'s list does not hold', async () => {
    const page = await createWorld(lookOffer({ pack_id: 'exulanica.unlisted-town' }));
    await page.draft();
    expect(page.lookLine()).toBeNull();
    await page.use();
    // Asked directly, the row refuses it too: a look it cannot name is never the town's.
    const unlisted = { state: 'offered', packId: 'exulanica.unlisted-town', version: 1,
      manifestSha256: '7'.repeat(64), lookWords: ['toy box'], modelName: null } as const;
    expect(page.look.drafted.offered(unlisted)).toBeNull();
    expect(page.look.drafted.take(unlisted)).toBe(false);
    expect(page.look.drafted.takeInstead(unlisted)).toBe(false);
    expect(page.look.binding()).toBeNull();
    await page.make();
    expect(page.row().title).toBe(pack(DEFAULT_PACK).title);
    expect(page.requests[0]).not.toHaveProperty('style_pack');
  });

  it('says the making\'s own words when the server refuses the offered version, and keeps the draft', async () => {
    const page = await createWorld(lookOffer(), { making: () => Response.json(
      { code: 'invalid_style_data', detail: 'the library holds no such version of that pack' }, { status: 422 }) });
    await page.draft();
    await page.use();
    await page.make();
    expect(page.requests.map((request) => request['style_pack'])).toEqual([OFFERED]);
    expect(page.text('.world-recipes-status')).toBe(
      'The world was not created: That could not be done just now, so nothing was changed. '
      + 'Try again, or look at the technical details.');
    expect(page.opened).toEqual([]);
    // The draft, its look line, the values and the look taken are all still there to change.
    expect(page.text('.world-description-result')).toContain(`You asked for: “${DESCRIPTION}”`);
    expect(page.lookLine()).toContain(TOON.title);
    expect(page.row().title).toBe(TOON.title);
    expect(page.host.querySelector<HTMLInputElement>('[data-parameter="block_length_mm"]')!.value).toBe('100000');
    expect(page.host.querySelector<HTMLButtonElement>('.world-recipes-make')!.disabled).toBe(false);
  });
});
