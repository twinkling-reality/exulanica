// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { URL as FileUrl } from 'node:url';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import { buildWorldRecipes } from '../src/ui/world-recipes.js';
import { elapsedWords } from '../src/ui/kind-draft.js';
import { parseWorldSpecification } from '../src/world-specification.js';
import {
  KIND_DESCRIPTION_CHARACTERS,
  parseKindDraft,
  parseKindLibrary,
  TOWN_KIND,
  type KindDraft,
  type WorldKind,
} from '../src/world-kinds-api.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';
import { servedSpecification } from './world-specification-document.js';

/**
 * Create a world's kinds of place: the kinds the server lists besides the town as cards, a world
 * made of one, and the last card, a kind of place drafted from a person's words and followed until
 * it is ready or refused.
 */

const REPOSITORY = new FileUrl('../../../../', import.meta.url);
const repository = (path: string): string => readFileSync(new FileUrl(path, REPOSITORY), 'utf8');

const REFUSALS = [
  { code: 'kind_not_drafted', meaning: 'No kind of place people can live, walk and work in was drafted.' },
  { code: 'kind_draft_unanswered', meaning: 'The model did not answer in time.' },
  { code: 'kind_draft_busy', meaning: 'The workspace already has a kind of place being drafted.' },
  { code: 'kind_cap_reached', meaning: 'The workspace already keeps as many kinds of place as it may.' },
];

const kindView = (key: string, label: string, extra: Record<string, unknown> = {}) => ({
  kind: key, version: 1, sha256: 'a'.repeat(64), source: key === TOWN_KIND ? 'shipped' : 'workspace',
  label, summary: `${label}, in a line.`, origin: 'drafted', generator: { key: 'site-plan', version: 1 },
  parameters: [], presets: [{ key: 'drafted', label: 'As drafted', values: {} }],
  parts: [{ key: 'counter', label: 'Counter', description: 'Where people order.', form: 'fixture', roles: [], look: 'fixture.counter' },
    { key: 'tables', label: 'Tables', description: 'Where people sit.', form: 'fixture', roles: [], look: 'fixture.table' }],
  zones: [], ...extra,
});

const library = (offered: boolean, kinds = [kindView(TOWN_KIND, 'A town'), kindView('cafe', 'A cafe')], code: string | null = null) => ({
  profile: 'exulanica.world-kinds/v1', kinds, refusals: [],
  drafting: { offered, code: offered ? null : code ?? 'not_authorised', refusals: REFUSALS },
});

const draftView = (state: string, extra: Record<string, unknown> = {}) => ({
  draft_id: 'draft-1', state, description: state === 'drafting' ? 'a quiet vineyard' : '', started_at: '2026-10-08T21:00:00Z',
  elapsed_seconds: 75, poll_after_seconds: state === 'drafting' ? 2 : null, deadline_seconds: 600,
  kind: null, refusal: null, model_id: null, model_name: null, prompt_version: 'kind-drafting-5', execution: null, ...extra,
});

const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 20; turn += 1) await Promise.resolve();
};

function sheet(options: {
  library?: unknown;
  drafts?: unknown[];
  start?: (description: string) => Promise<KindDraft>;
  reads?: (() => Promise<KindDraft>)[];
} = {}) {
  const made: { kind: string; preset: string; values: Record<string, number | string> }[] = [];
  const opened: SavedWorldEntry[] = [];
  const pending: (() => void)[] = [];
  const reads = [...(options.reads ?? [])];
  const start = vi.fn(options.start ?? (async (description: string) => parseKindDraft(draftView('drafting', { description }))));
  const built = buildWorldRecipes({
    specification: async () => parseWorldSpecification(servedSpecification()),
    make: async () => ({ entryId: 'town' } as SavedWorldEntry),
    open: async (entry) => { opened.push(entry); },
    onClose: () => undefined,
    kinds: {
      library: async () => parseKindLibrary(options.library ?? library(true)),
      drafts: async () => (options.drafts ?? []).map(parseKindDraft),
      startDraft: start,
      draft: async () => {
        const next = reads.shift();
        if (next === undefined) throw new Error('no read scripted');
        return next();
      },
      make: async (kind: WorldKind, preset, values) => {
        made.push({ kind: kind.kind, preset, values: { ...values } });
        return { entryId: kind.kind } as SavedWorldEntry;
      },
      maximumCharacters: KIND_DESCRIPTION_CHARACTERS,
      schedule: (run) => { pending.push(run); return () => undefined; },
    },
  });
  document.body.replaceChildren(built.root);
  // Run what the page scheduled, as the clock would.
  const tick = async (): Promise<void> => {
    const due = pending.splice(0);
    for (const run of due) run();
    await settle();
  };
  return { built, made, opened, start, tick };
}

const q = <T extends Element = HTMLElement>(root: Element, selector: string): T | null => root.querySelector<T>(selector);
const statusText = (root: Element): string => q(root, '.world-kinds-status')?.textContent ?? '';

async function typeAndDraft(root: HTMLElement, words: string): Promise<void> {
  q<HTMLButtonElement>(root, '[data-kind-new]')!.click();
  const field = q<HTMLTextAreaElement>(root, '.world-kinds-input')!;
  field.value = words;
  field.dispatchEvent(new Event('input'));
  field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  await settle();
}

describe('the kinds of place in Create a world', () => {
  it('lists every kind but the town, whose presets are the recipes, and makes a world of the one chosen', async () => {
    const { built, made, opened } = sheet();
    await settle();
    const cards = [...built.root.querySelectorAll<HTMLButtonElement>('[data-kind]')];
    expect(cards.map((card) => card.getAttribute('data-kind'))).toEqual(['cafe']);
    expect(q(built.root, '.world-kinds')!.hidden).toBe(false);
    cards[0]!.click();
    expect(q(built.root, '.world-kinds-words')!.textContent).toBe('A cafe: A cafe, in a line.');
    expect(q(built.root, '.world-kinds-holds')!.textContent).toBe('What it holds: Counter, Tables');
    const make = q<HTMLButtonElement>(built.root, '.world-recipes-make')!;
    expect([make.hidden, make.disabled, make.textContent]).toEqual([false, false, 'Create this world']);
    // The town's values and look are not this kind's.
    expect(q(built.root, '.world-recipes-side > .world-recipes-values')!.hidden).toBe(true);
    make.click();
    await settle();
    expect(made).toEqual([{ kind: 'cafe', preset: 'drafted', values: {} }]);
    expect(opened.map((entry) => entry.entryId)).toEqual(['cafe']);
  });

  it('goes back to the town when a recipe is chosen after a kind', async () => {
    const { built } = sheet();
    await settle();
    q<HTMLButtonElement>(built.root, '[data-kind="cafe"]')!.click();
    q<HTMLButtonElement>(built.root, '[data-recipe]')!.click();
    expect(q(built.root, '.world-kinds-side')!.hidden).toBe(true);
    expect(q(built.root, '.world-recipes-make')!.textContent).toBe('Create this town');
    expect(q(built.root, '[data-kind="cafe"]')!.getAttribute('aria-pressed')).toBe('false');
  });

  it('offers a new kind of place only where the server offers this person drafting', async () => {
    const offered = sheet();
    await settle();
    expect(q(offered.built.root, '[data-kind-new]')!.textContent).toBe('A new kind of placeDraft one from your words');
    const refused = sheet({ library: library(false, [kindView(TOWN_KIND, 'A town')], 'provider_credential_absent') });
    await settle();
    expect(q(refused.built.root, '[data-kind-new]')).toBeNull();
    // Nothing to list and nothing to draft: the block stays hidden.
    expect(q(refused.built.root, '.world-kinds')!.hidden).toBe(true);
  });

  it('follows a draft with the time the server counts, then lists and chooses the kind it made', async () => {
    const ready = kindView('vineyard', 'A vineyard');
    const { built, start, tick } = sheet({
      reads: [
        async () => parseKindDraft(draftView('drafting', { elapsed_seconds: 125 })),
        async () => parseKindDraft(draftView('ready', { kind: ready, model_id: 'm', model_name: 'Nemotron 3 Super' })),
      ],
    });
    await settle();
    await typeAndDraft(built.root, '  a quiet vineyard  ');
    expect(start).toHaveBeenCalledWith('a quiet vineyard');
    expect(statusText(built.root)).toBe(
      'Drafting your kind of place, 1 minute 15 seconds so far. It can take a few minutes. You can leave: '
      + 'it keeps going, and it will be among your kinds when it is ready.');
    expect(q(built.root, '[data-kind-new] .world-kinds-choice-detail')!.textContent).toBe('Being drafted');
    expect(q<HTMLTextAreaElement>(built.root, '.world-kinds-input')!.readOnly).toBe(true);
    await tick();
    expect(statusText(built.root)).toContain('2 minutes 5 seconds so far');
    await tick();
    expect(q(built.root, '[data-kind="vineyard"]')!.getAttribute('aria-pressed')).toBe('true');
    expect(q(built.root, '.world-kinds-words')!.textContent).toBe('A vineyard: A vineyard, in a line.');
    expect(q(built.root, '.world-kinds-by')!.textContent).toBe('Drafted from your words by Nemotron 3 Super.');
    // Focus was on the draft field, so it moves to the one next step.
    expect(document.activeElement).toBe(q(built.root, '.world-recipes-make'));
    // Listed before the new kind card, which says it can draft again.
    expect([...built.root.querySelectorAll('.world-kinds-list > button')].map((card) => card.getAttribute('data-kind') ?? 'new'))
      .toEqual(['cafe', 'vineyard', 'new']);
    expect(q(built.root, '[data-kind-new] .world-kinds-choice-detail')!.textContent).toBe('Draft one from your words');
  });

  it('says why in two sentences when the words drafted no kind, and keeps the words', async () => {
    const { built, tick } = sheet({
      reads: [async () => parseKindDraft(draftView('refused', {
        refusal: { code: 'kind_not_drafted', detail: 'The cellar has no door to the yard.', check: 'room_unreachable' },
      }))],
    });
    await settle();
    await typeAndDraft(built.root, 'a cellar');
    await tick();
    expect(statusText(built.root)).toBe(
      'These words did not draft a kind of place people can live, walk and work in: The cellar has no door '
      + 'to the yard. Try describing it another way.');
    const field = q<HTMLTextAreaElement>(built.root, '.world-kinds-input')!;
    expect([field.value, field.readOnly]).toEqual(['a cellar', false]);
    expect(q<HTMLButtonElement>(built.root, '.world-kinds-draft')!.disabled).toBe(false);
  });

  it('says no drafter\'s sentence where no check refused, since it would only repeat the first', async () => {
    const { built, tick } = sheet({
      reads: [async () => parseKindDraft(draftView('refused', {
        refusal: { code: 'kind_not_drafted', detail: 'No kind of world was drafted from these words.', check: null },
      }))],
    });
    await settle();
    await typeAndDraft(built.root, 'nothing at all');
    await tick();
    expect(statusText(built.root)).toBe(
      'These words did not draft a kind of place people can live, walk and work in. Try describing it another way.');
  });

  it('says a refusal that is not the drafted kind\'s in the server\'s closed list\'s words', async () => {
    const { built, tick } = sheet({
      reads: [async () => parseKindDraft(draftView('refused', { refusal: { code: 'kind_draft_unanswered', detail: 'timeout after 300 s' } }))],
    });
    await settle();
    await typeAndDraft(built.root, 'a farm');
    await tick();
    expect(statusText(built.root)).toBe('The model did not answer in time. You can draft it again.');
  });

  it('says a draft the server no longer holds stopped, and offers to draft it again', async () => {
    const { built, tick } = sheet({ reads: [async () => { throw new ApiError(404, 'kind_draft_unknown', 'no draft'); }] });
    await settle();
    await typeAndDraft(built.root, 'a farm');
    await tick();
    expect(statusText(built.root)).toBe('This draft is no longer on the server, so it stopped. Draft it again.');
    expect(q<HTMLButtonElement>(built.root, '.world-kinds-draft')!.disabled).toBe(false);
  });

  it('answers a busy workspace with the person\'s own running draft, and a full server with a minute', async () => {
    const busy = sheet({
      start: async () => { throw new ApiError(409, 'kind_draft_busy', 'busy', { draft_id: 'draft-1' }); },
      reads: [async () => parseKindDraft(draftView('drafting'))],
    });
    await settle();
    await typeAndDraft(busy.built.root, 'a farm');
    expect(statusText(busy.built.root)).toBe('You already have a kind of place being drafted.');
    const seeIt = q<HTMLButtonElement>(busy.built.root, '.world-kinds-see')!;
    expect(seeIt.hidden).toBe(false);
    seeIt.click();
    await settle();
    expect(statusText(busy.built.root)).toContain('Drafting your kind of place');
    const full = sheet({ start: async () => { throw new ApiError(503, 'kind_draft_capacity', 'full'); } });
    await settle();
    await typeAndDraft(full.built.root, 'a farm');
    expect(statusText(full.built.root)).toBe(
      'Many kinds of place are being drafted on this server right now. Try again in a minute.');
  });

  it('finds a draft of this person\'s still running when the sheet opens, and follows it', async () => {
    const { built, start } = sheet({ library: library(false, undefined, 'kind_draft_busy'), drafts: [draftView('drafting')] });
    await settle();
    // Busy is not offered, but their own running draft is shown, never started again.
    const card = q<HTMLButtonElement>(built.root, '[data-kind-new]')!;
    expect(card.textContent).toBe('A new kind of placeBeing drafted');
    card.click();
    expect(statusText(built.root)).toContain('1 minute 15 seconds so far');
    expect(q<HTMLTextAreaElement>(built.root, '.world-kinds-input')!.value).toBe('a quiet vineyard');
    expect(start).not.toHaveBeenCalled();
  });

  it('leaves the field on Escape before the sheet closes', async () => {
    const { built } = sheet();
    await settle();
    q<HTMLButtonElement>(built.root, '[data-kind-new]')!.click();
    const field = q<HTMLTextAreaElement>(built.root, '.world-kinds-input')!;
    expect(document.activeElement).toBe(field);
    field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(document.activeElement).toBe(q(built.root, '[data-kind-new]'));
  });
});

describe('the words of a draft', () => {
  it('says a span of seconds as a person reads it', () => {
    expect([0, 1, 45, 60, 61, 125, 180].map(elapsedWords)).toEqual([
      '0 seconds', '1 second', '45 seconds', '1 minute', '1 minute 1 second', '2 minutes 5 seconds', '3 minutes',
    ]);
  });

  it('holds the description ceiling to the kind drafter\'s prompt document', () => {
    const named = /PROMPT_PATH[^\n]*with_name\("([^"]+)"\)/.exec(repository('exulanica/selection/kind_drafting.py'))?.[1];
    expect(named).toBeDefined();
    const prompt = JSON.parse(repository(`exulanica/selection/${named!}`)) as Record<string, unknown>;
    expect(KIND_DESCRIPTION_CHARACTERS).toBe(prompt['description_characters_maximum']);
  });

  it('reads the town\'s key from the adapter the server lists it through', () => {
    const adapter = JSON.parse(repository('assets/catalogs/world-kinds/library/town.v1.json')) as Record<string, unknown>;
    expect(TOWN_KIND).toBe(adapter['kind']);
  });
});
