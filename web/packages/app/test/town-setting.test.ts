// @vitest-environment happy-dom
// The setting a town is made in, in Create a world: the parts a draft's words ask for are shown
// under Describe it, taken only by the person's own press, shown in the Setting row as coming
// from their words, and named in the making for the host to compose.
//
// The named parts are the committed file's, read here as the host lists them (axes in order, each
// part's title and description, never its figures); the draft's setting offer is written here as
// the route serves it.
import { readFileSync } from 'node:fs';
import { URL as FileUrl } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LookLibrary } from '../src/composition/look-library.js';
import { buildTownSetting } from '../src/composition/town-setting.js';
import { buildWorldDescription, settingLine, type DraftSetting, type SpecificationWords } from '../src/ui/world-description.js';
import { parseSettingOffer, parseWorldDraft, type OfferedSetting, type WorldDraft } from '../src/world-draft-api.js';
import { WorldEntryClient } from '../src/world-entry-api.js';

const REPOSITORY = new FileUrl('../../../../', import.meta.url);
const PARTS = JSON.parse(readFileSync(new FileUrl('assets/style-packs/settings/setting-parts.v1.json', REPOSITORY), 'utf8')) as {
  version: number; axes: { key: string; title: string }[]; parts: { axis: string; key: string; title: string; description: string }[];
};
const SETTINGS = {
  axes: PARTS.axes,
  parts: PARTS.parts.map(({ axis, key, title, description }) => ({ axis, key, title, description })),
};
const title = (axis: string, key: string): string => PARTS.parts.find((part) => part.axis === axis && part.key === key)!.title;
/** The host's default look as its list names it, which a setting is asked for with where the person chose none. */
const DEFAULT = { packId: 'exulanica.finished-town', version: 2, manifestSha256: 'd'.repeat(64) };
/** The host's looks as far as a setting reads them: the named parts, and the default look to draw them over. */
const library = (settings: LookLibrary['settings'] = SETTINGS, defaultId: string | null = DEFAULT.packId): LookLibrary => ({
  settings, defaultId, binding: (packId: string) => (packId === DEFAULT.packId ? DEFAULT : null),
} as unknown as LookLibrary);

const call = { role: 'setting_chooser', requested_model: 'example/chooser', served_model: 'example/chooser',
  requested_model_name: 'Chooser Model', served_model_name: 'Chooser Model', used_fallback: false,
  attempts: 1, latency_ms: 900, prompt_tokens: 300, completion_tokens: 30, reasoning_tokens: null,
  usd: '0.0001', served_model_unavailable: null, outcome: 'completed', cost_basis: 'known' };
/** A setting offer as the route serves it (`SettingOfferView`), offered unless overridden. */
const settingOffer = (overrides: Record<string, unknown> = {}) => ({
  state: 'offered', reason: null, parts: { sky: 'dusk', ground: 'sea' }, parts_version: PARTS.version,
  setting_words: ['at dusk', 'by the sea'], prompt_version: 'setting-choosing-1', prompt_sha256: 'e'.repeat(64),
  execution: { prompt_version: 'setting-choosing-1', rejections: [], calls: [call] },
  ...overrides,
});
const NONE = settingOffer({ state: 'none', parts: {}, setting_words: [] });
const NOT_ANSWERED = settingOffer({ state: 'unavailable', reason: 'timed_out', parts: {}, setting_words: [] });
const draftBody = (offer: unknown): Record<string, unknown> => ({
  description: 'A town by the sea at dusk',
  proposal: {
    preset: 'small_town', values: { city_extent_x_mm: 256000 }, set_by_words: [], fit: 'all', valid: true, value_refusal: null,
    sample: { status: 'unavailable', tiles: null, people: null, vehicles: null, vehicles_refused: null, streets: [], premises: [], buildings: null, refused: null },
  },
  not_supported: [], refusal: null, specification_version: 1, specification_sha256: 'a'.repeat(64),
  prompt_version: 'world-drafting-2', prompt_sha256: 'b'.repeat(64), model_id: 'example/drafter', model_name: 'Drafter Model',
  execution: { prompt_version: 'world-drafting-2', rejections: [], calls: [] },
  ...(offer === undefined ? {} : { setting_offer: offer }),
});
const draft = (offer: unknown): WorldDraft => parseWorldDraft(draftBody(offer));
const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
};

afterEach(() => document.body.replaceChildren());

describe('the setting a draft offers', () => {
  it('is read in each state the route serves, and is none where the answer carries none', () => {
    expect(parseSettingOffer(settingOffer())).toEqual({
      state: 'offered', parts: { sky: 'dusk', ground: 'sea' }, settingWords: ['at dusk', 'by the sea'], modelName: 'Chooser Model',
    });
    expect(parseSettingOffer(NONE)).toEqual({ state: 'none' });
    expect(parseSettingOffer(NOT_ANSWERED)).toEqual({ state: 'unavailable' });
    expect(draft(undefined).settingOffer).toBeNull();
    expect(draft(null).settingOffer).toBeNull();
  });

  it('never refuses the draft it came with: an unknown state, no part or no words is no offer', () => {
    for (const offer of [
      settingOffer({ state: 'later' }), settingOffer({ parts: {} }), settingOffer({ setting_words: [] }),
      settingOffer({ parts: { sky: 7 } }), settingOffer({ parts: ['dusk'] }), 'dusk',
    ]) {
      const read = draft(offer);
      expect(read.settingOffer).toBeNull();
      expect(read.proposal?.preset).toBe('small_town');
    }
    // A field this page does not know is passed over.
    expect(parseSettingOffer(settingOffer({ preview: 'later' }))?.state).toBe('offered');
  });

  it('is said in one line: the parts by the host\'s titles, the model that chose them and the words', () => {
    const offered = parseSettingOffer(settingOffer());
    expect(settingLine(offered, [title('sky', 'dusk'), title('ground', 'sea')]))
      .toBe(`Chooser Model suggests the setting ${title('sky', 'dusk')}, ${title('ground', 'sea')}, from your words “at dusk”, “by the sea”.`);
    expect(settingLine(parseSettingOffer(settingOffer({ execution: null })), ['Dusk'])).toContain('An open model suggests the setting Dusk');
    // One calm line when the step did not answer; no line when it offers none or cannot be named.
    expect(settingLine(parseSettingOffer(NOT_ANSWERED), null))
      .toBe('No setting was chosen from your words this time. The town will be drawn as its look has it.');
    expect(settingLine(parseSettingOffer(NONE), null)).toBeNull();
    expect(settingLine(offered, null)).toBeNull();
    expect(settingLine(null, null)).toBeNull();
  });
});

describe('the setting of a town not made yet', () => {
  const offered = parseSettingOffer(settingOffer()) as OfferedSetting;

  it('is the look\'s own until the person takes an offered setting, then its parts in the axes\' order', async () => {
    const setting = buildTownSetting({ library: Promise.resolve(library()) });
    document.body.append(setting.row);
    await settle();
    expect(setting.row.hidden).toBe(false);
    expect(setting.parts()).toBeNull();
    expect(setting.row.textContent).toContain('As the look has it.');
    expect(setting.row.querySelector<HTMLButtonElement>('[data-action="setting.clear"]')!.hidden).toBe(true);

    // The offer states ground before sky; the making and the row follow the host's axes.
    const reversed = { ...offered, parts: { ground: 'sea', sky: 'dusk' } };
    expect(setting.drafted.offered(reversed)).toEqual([title('sky', 'dusk'), title('ground', 'sea')]);
    expect(setting.drafted.holds(reversed)).toBe(false);
    expect(setting.drafted.take(reversed)).toBe(true);
    expect(setting.drafted.holds(reversed)).toBe(true);
    expect(setting.drafted.holds(offered)).toBe(true);
    expect(Object.entries(setting.parts()!)).toEqual([['sky', 'dusk'], ['ground', 'sea']]);
    expect(setting.row.textContent).toContain(`${title('sky', 'dusk')}, ${title('ground', 'sea')}. From your words “at dusk”, “by the sea”.`);
  });

  it('stays the person\'s own until they press back to the look\'s own or take another, and tells its watchers', async () => {
    const setting = buildTownSetting({ library: Promise.resolve(library()) });
    document.body.append(setting.row);
    await settle();
    const changes = vi.fn();
    setting.drafted.watch(changes);
    setting.drafted.take(offered);
    expect(changes).toHaveBeenCalledTimes(1);
    expect(setting.parts()).toEqual({ sky: 'dusk', ground: 'sea' });
    // Another offer taken replaces it.
    const night = { ...offered, parts: { sky: 'night' }, settingWords: ['at night'] };
    expect(setting.drafted.take(night)).toBe(true);
    expect(setting.parts()).toEqual({ sky: 'night' });
    expect(setting.drafted.holds(offered)).toBe(false);
    setting.row.querySelector<HTMLButtonElement>('[data-action="setting.clear"]')!.click();
    expect(setting.parts()).toBeNull();
    expect(setting.drafted.holds(night)).toBe(false);
    expect(setting.row.textContent).toContain('As the look has it.');
    expect(changes).toHaveBeenCalledTimes(3);
  });

  it('neither shows nor takes parts the host does not list, and says nothing on a host that lists none', async () => {
    const setting = buildTownSetting({ library: Promise.resolve(library()) });
    await settle();
    const unknown = { ...offered, parts: { sky: 'aurora', weather: 'rain' } };
    expect(setting.drafted.offered(unknown)).toBeNull();
    expect(setting.drafted.take(unknown)).toBe(false);
    expect(setting.parts()).toBeNull();
    // One part known and one not: the known one alone.
    const mixed = { ...offered, parts: { sky: 'aurora', ground: 'sea' } };
    expect(setting.drafted.offered(mixed)).toEqual([title('ground', 'sea')]);
    expect(setting.drafted.take(mixed)).toBe(true);
    expect(setting.parts()).toEqual({ ground: 'sea' });

    const older = buildTownSetting({ library: Promise.resolve(library(null)) });
    await settle();
    expect(older.row.hidden).toBe(true);
    expect(older.drafted.offered(offered)).toBeNull();
    expect(older.drafted.take(offered)).toBe(false);
  });

  it('is named in the making with the look: the person\'s own, or the host\'s default exactly where they chose none', async () => {
    const setting = buildTownSetting({ library: Promise.resolve(library()) });
    await settle();
    const chosen = { packId: 'exulanica.cozy-town', version: 3, manifestSha256: 'c'.repeat(64) };
    // No part taken: the look as the person left it, a pack or none.
    expect(setting.madeIn(null)).toBeNull();
    expect(setting.madeIn(chosen)).toBe(chosen);
    setting.drafted.take(offered);
    expect(setting.madeIn(chosen)).toEqual({ ...chosen, settingParts: { sky: 'dusk', ground: 'sea' } });
    expect(setting.madeIn(null)).toEqual({ ...DEFAULT, settingParts: { sky: 'dusk', ground: 'sea' } });

    // A host that lists no look has nothing to draw a setting over: none is shown, taken or sent.
    const bare = buildTownSetting({ library: Promise.resolve(library(SETTINGS, null)) });
    document.body.append(bare.row);
    await settle();
    expect(bare.row.hidden).toBe(true);
    expect(bare.drafted.take(offered)).toBe(false);
    expect(bare.madeIn(null)).toBeNull();
  });
});

describe('the Describe it panel with a setting', () => {
  const WORDS: SpecificationWords = {
    values: [{ key: 'city_extent_x_mm', label: 'Length of the town', unit: 'mm', minimum: 256000, maximum: 384000, step: 128000, choices: null }],
    presets: [{ key: 'small_town', label: 'A small town' }],
  };
  const SUGGESTED = `Chooser Model suggests the setting ${title('sky', 'dusk')}, ${title('ground', 'sea')}, from your words “at dusk”, “by the sea”.`;

  async function drafted(answer: WorldDraft, setting?: DraftSetting) {
    const useValues = vi.fn();
    const panel = buildWorldDescription({
      draft: async () => answer, useValues, words: WORDS, maximumCharacters: 1000,
      ...(setting === undefined ? {} : { setting }),
    });
    document.body.append(panel.root);
    panel.root.querySelector('textarea')!.value = answer.description;
    panel.root.querySelector<HTMLButtonElement>('.world-description-draft')!.click();
    await vi.waitFor(() => expect(panel.root.querySelector('.world-description-result p')).not.toBeNull());
    return { panel, useValues };
  }
  const pressUse = (root: HTMLElement) => root.querySelector<HTMLButtonElement>('.world-description-setting-use');

  it('shows the offered setting with its words and never takes it with the values', async () => {
    const setting = buildTownSetting({ library: Promise.resolve(library()) });
    await settle();
    const { panel, useValues } = await drafted(draft(settingOffer()), setting.drafted);
    expect(panel.root.querySelector('.world-description-setting p')!.textContent).toBe(SUGGESTED);
    expect(pressUse(panel.root)!.textContent).toBe('Use this setting');
    expect(setting.parts()).toBeNull();
    // "Use these values" takes the values and nothing of the setting.
    panel.root.querySelector<HTMLButtonElement>('.world-description-use')!.click();
    expect(useValues).toHaveBeenCalledTimes(1);
    expect(setting.parts()).toBeNull();
    expect(panel.root.querySelector('.world-description-status')!.textContent).not.toContain('setting');
    expect(pressUse(panel.root)).not.toBeNull();
  });

  it('takes the offered setting only by its own press, says so, and offers the press again once it is dropped', async () => {
    const setting = buildTownSetting({ library: Promise.resolve(library()) });
    document.body.append(setting.row);
    await settle();
    const { panel } = await drafted(draft(settingOffer()), setting.drafted);
    pressUse(panel.root)!.click();
    expect(setting.parts()).toEqual({ sky: 'dusk', ground: 'sea' });
    expect(panel.root.querySelector('.world-description-status')!.textContent)
      .toBe(`The setting is now ${title('sky', 'dusk')}, ${title('ground', 'sea')}.`);
    // It is the town's now: the line stays, the press is gone.
    expect(panel.root.querySelector('.world-description-setting p')!.textContent).toBe(SUGGESTED);
    expect(pressUse(panel.root)).toBeNull();
    // Dropped in the Setting row: the press is offered again.
    setting.row.querySelector<HTMLButtonElement>('[data-action="setting.clear"]')!.click();
    expect(setting.parts()).toBeNull();
    expect(pressUse(panel.root)).not.toBeNull();
  });

  it('says nothing of a setting where the panel is given none, the draft offers none, or the step did not answer but one calm line', async () => {
    const without = await drafted(draft(settingOffer()));
    expect(without.panel.root.querySelector('.world-description-setting')?.textContent ?? '').toBe('');
    document.body.replaceChildren();
    const setting = buildTownSetting({ library: Promise.resolve(library()) });
    await settle();
    const none = await drafted(draft(NONE), setting.drafted);
    expect(none.panel.root.querySelector('.world-description-setting p')).toBeNull();
    expect(pressUse(none.panel.root)).toBeNull();
    document.body.replaceChildren();
    const unanswered = await drafted(draft(NOT_ANSWERED), setting.drafted);
    expect(unanswered.panel.root.querySelector('.world-description-setting p')!.textContent)
      .toBe('No setting was chosen from your words this time. The town will be drawn as its look has it.');
    expect(pressUse(unanswered.panel.root)).toBeNull();
  });

  it('does not say the town is the usual one, or list as left out the words a shown setting came from', async () => {
    const setting = buildTownSetting({ library: Promise.resolve(library()) });
    await settle();
    // The drafter set nothing and left the setting's words out; the setting step found them.
    const answer = parseWorldDraft({
      ...draftBody(settingOffer()), not_supported: ['by the sea', 'at dusk', 'pastel houses'],
    });
    const shown = await drafted(answer, setting.drafted);
    expect(shown.panel.root.querySelector('.world-description-usual')).toBeNull();
    expect(shown.panel.root.querySelector('.world-description-not-supported')!.textContent)
      .toBe('Not in this town yet: “pastel houses”');
    const order = [...shown.panel.root.querySelector('.world-description-result')!.children].map((node) => node.className);
    expect(order.slice(1, 4)).toEqual(['world-description-look', 'world-description-look world-description-setting', 'world-description-left-out']);
    document.body.replaceChildren();
    // No setting offered: the words reached nothing, and the page says so first.
    const reached = await drafted(parseWorldDraft({ ...draftBody(NONE), not_supported: ['by the sea', 'at dusk'] }), setting.drafted);
    expect(reached.panel.root.querySelector('.world-description-usual')!.textContent)
      .toBe('A small town as it usually is: nothing you typed changes it yet.');
    expect(reached.panel.root.querySelector('.world-description-not-supported')!.textContent)
      .toBe('Not in this town yet: “by the sea”, “at dusk”');
  });
});

describe('making a town in a setting', () => {
  it('names the parts with the look, for the host to compose, and nothing of a setting without them', async () => {
    const bodies: Record<string, unknown>[] = [];
    const fetch = vi.fn(async (_input: string | URL | Request, init: RequestInit = {}) => {
      bodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
      return new Response('{}', { status: 500 });
    });
    const client = new WorldEntryClient({ baseUrl: 'https://exulanica.test', token: 'setting-token', fetch });
    const pack = { packId: 'exulanica.cozy-town', version: 3, manifestSha256: 'c'.repeat(64) };
    await client.makeGenerated('small_town', 'A small town', undefined, { ...pack, settingParts: { sky: 'dusk', ground: 'sea' } }).catch(() => undefined);
    await client.makeGenerated('small_town', 'A small town', undefined, pack).catch(() => undefined);
    expect(bodies.map((body) => body['style_pack'])).toEqual([
      { pack_id: pack.packId, version: 3, manifest_sha256: pack.manifestSha256, setting_parts: { sky: 'dusk', ground: 'sea' } },
      { pack_id: pack.packId, version: 3, manifest_sha256: pack.manifestSha256 },
    ]);
  });
});
