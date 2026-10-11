// @vitest-environment happy-dom
// One sentence makes a world: the page reads the offer and the draft's answer strictly, asks the
// three routes the contract names, shows what a draft may spend before the words can be sent,
// says each step in words with the server's own count of seconds, shows what was made and what
// the words asked for that was left out, and says a refusal in the words of the closed list the
// answer carries. The box says in one line what happens to the words, and it is the only thing
// the sheet shows.
import { readFileSync } from 'node:fs';
import { ApiError } from '@exulanica/graph-client';
import { describe, expect, it, vi } from 'vitest';
import { NEVER_DRAFTS, attachWorldSentence, sentenceOffered } from '../src/composition/world-sentence.js';
import { fill, say } from '../src/ui/copy.js';
import { buildWorldRecipes } from '../src/ui/world-recipes.js';
import { buildWorldSentence, madeWords, refusedNowWords, spendWords } from '../src/ui/world-sentence.js';
import {
  WorldMakingClient,
  parseWorldDraftOffer,
  parseWorldMakingDraft,
  type WorldDraftOffer,
  type WorldMakingDraft,
} from '../src/world-making-api.js';

// What the server's draft routes answer, written and held by
// tests/test_world_making_postgres.py (the page's fixture is the server's own answer). The
// scenarios below are built by hand over the same members, which a test holds to this file.
const SERVED = JSON.parse(readFileSync('../tests/snapshots/world-drafts.served.json', 'utf8')) as Record<
  'offer' | 'started' | 'offer_while_mine_runs' | 'ready_place' | 'ready_town' | 'refused', Record<string, unknown>>;
const members = (value: unknown): string[] => Object.keys(value as object).sort();

const DRAFT = '77777777-7777-4777-8777-777777777777';
const WORDS = 'a harbour with fishing boats and a lighthouse';
const REFUSALS = [
  { code: 'kind_not_drafted', meaning: 'No kind of place people can live, walk and work in was drafted.' },
  { code: 'world_not_a_place', meaning: 'The words ask for no place where people could live, walk or work.' },
];

// The saved world a draft answers with: the server's own, told apart by its title and kind.
const servedEntry = SERVED.ready_place['entry'] as Record<string, unknown>;
const entry = {
  ...servedEntry,
  world_id: 'world:generated-harbour',
  title: 'A busy harbour',
  generated_site: { ...(servedEntry['generated_site'] as object), kind: 'busy_harbour', kind_label: 'A busy harbour' },
};

const wire = (state: string, extra: Record<string, unknown> = {}) => ({
  draft_id: DRAFT, state, description: state === 'ready' || state === 'refused' ? '' : WORDS,
  started_at: '2026-10-10T12:00:00Z', elapsed_seconds: 4,
  poll_after_seconds: state === 'ready' || state === 'refused' ? null : 3, deadline_seconds: 240,
  tool: null, entry: null, made: [], left_out: [], refusal: null, model_name: null, execution: null,
  refusals: REFUSALS, ...extra,
});

const BOAT = { key: 'boat', label: 'fishing boat', form: 'fixture', look: 'vehicle.fishing_boat', drawn: 4, box_mm: [2400, 6000, 1800] };
const ready = wire('ready', {
  elapsed_seconds: 31, tool: { key: 'place', chosen_by: 'model' }, entry,
  made: [
    { key: 'quay', label: 'quay', form: 'path', look: 'ground.quay', drawn: 1, box_mm: null },
    BOAT,
    { ...BOAT, key: 'boat_far', drawn: 2 },
    { key: 'lighthouse', label: 'lighthouse', form: 'structure', look: 'structure.lighthouse', drawn: 1, box_mm: [5000, 5000, 9000] },
  ],
  left_out: ['gulls overhead'],
});

const offerWire = (extra: Record<string, unknown> = {}) => ({
  offered: true, code: null, detail: null, calls_at_most: 5,
  starts: { an_hour: 12, left: 12, retry_after_seconds: null },
  description_characters: 1000, running_draft_id: null,
  refusals: [...REFUSALS, { code: 'world_limit_reached', meaning: 'The workspace already holds as many worlds as it may.' }],
  ...extra,
});
const OFFER = parseWorldDraftOffer(offerWire());
const SPEND = 'Making a world asks an AI model up to 5 times. Once started it runs to its end, one world at a time. '
  + 'You have 12 of 12 starts left this hour.';

const settle = async (): Promise<void> => {
  for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
};

/** The box in the page, with the answers it is given in order and the polls it schedules held. */
function box(
  answers: readonly (WorldMakingDraft | Error)[],
  startWith: WorldMakingDraft | Error = parseWorldMakingDraft(wire('choosing')),
  offer: WorldDraftOffer = OFFER,
  later: readonly WorldDraftOffer[] = [],
) {
  const waiting: { run: () => void; ms: number }[] = [];
  const offers = [...later];
  const readOffer = vi.fn(async () => offers.shift() ?? offer);
  const reads = [...answers];
  const start = vi.fn(async (_description: string) => {
    if (startWith instanceof Error) throw startWith;
    return startWith;
  });
  const read = vi.fn(async (_draftId: string) => {
    const next = reads.shift();
    if (next === undefined) throw new Error('the test scripted no further answer');
    if (next instanceof Error) throw next;
    return next;
  });
  const open = vi.fn(async () => undefined);
  const recipes = vi.fn();
  const built = buildWorldSentence({
    offer, readOffer, start, read, open, recipes,
    schedule: (run, ms) => {
      const held = { run, ms };
      waiting.push(held);
      return () => { waiting.splice(waiting.indexOf(held), 1); };
    },
  });
  document.body.replaceChildren(built.root);
  const find = <T extends HTMLElement>(selector: string): T => built.root.querySelector<T>(selector)!;
  const field = find<HTMLTextAreaElement>('.world-sentence-input');
  const type = (words: string): void => {
    field.value = words;
    field.dispatchEvent(new Event('input'));
  };
  /** Run the one poll that waits, and let its answer be shown. */
  const tick = async (): Promise<void> => {
    expect(waiting).toHaveLength(1);
    waiting.shift()!.run();
    await settle();
  };
  return {
    built, start, read, open, readOffer, recipes, waiting, field, type, tick,
    toRecipes: find<HTMLButtonElement>('.world-sentence-recipes'),
    spend: find<HTMLElement>('.world-sentence-spend'),
    make: find<HTMLButtonElement>('.world-sentence-make'),
    status: find<HTMLElement>('.world-sentence-status'),
    made: find<HTMLElement>('.world-sentence-made'),
    leftOut: find<HTMLElement>('.world-sentence-left-out'),
    openButton: find<HTMLButtonElement>('.world-sentence-open'),
    follow: find<HTMLButtonElement>('.world-sentence-follow'),
  };
}

describe('what the server\u2019s draft routes answer', () => {
  it('is read whole by the page, each answer the server gives', () => {
    const offer = parseWorldDraftOffer(SERVED.offer);
    expect([offer.offered, offer.code, offer.runningDraftId]).toEqual([true, null, null]);
    expect(offer.callsAtMost).toBeGreaterThan(0);
    expect(offer.starts.left).toBe(offer.starts.anHour);
    const mine = parseWorldDraftOffer(SERVED.offer_while_mine_runs);
    const started = parseWorldMakingDraft(SERVED.started);
    expect([mine.offered, mine.code, mine.runningDraftId]).toEqual([false, 'kind_draft_busy', started.draftId]);
    expect([started.state, started.pollAfterSeconds === null, started.description !== '']).toEqual(['choosing', false, true]);
    const place = parseWorldMakingDraft(SERVED.ready_place);
    expect([place.state, place.tool?.key, place.entry?.generatedSite === null]).toEqual(['ready', 'place', false]);
    expect(place.made.length).toBeGreaterThan(0);
    expect(place.made.some((part) => part.boxMm !== null)).toBe(true);
    const town = parseWorldMakingDraft(SERVED.ready_town);
    expect([town.state, town.tool?.key, town.entry?.generatedGround === null]).toEqual(['ready', 'town', false]);
    expect(town.leftOut).toEqual(['two cafes']);
    expect(town.made.every((part) => part.boxMm === null && part.drawn === null)).toBe(true);
    const refused = parseWorldMakingDraft(SERVED.refused);
    expect([refused.state, refused.entry, refused.description]).toEqual(['refused', null, '']);
    // Every code a draft or an offer names is one its own list has words for.
    expect(refused.refusals.map((one) => one.code)).toContain(refused.refusal!.code);
    expect(mine.refusals.map((one) => one.code)).toContain(mine.code);
  });

  it('has the members the hand-built scenarios of this file have, and no others', () => {
    expect(members(offerWire())).toEqual(members(SERVED.offer));
    expect(members(offerWire().starts)).toEqual(members(SERVED.offer['starts']));
    for (const answer of [SERVED.started, SERVED.ready_place, SERVED.ready_town, SERVED.refused]) {
      expect(members(wire('choosing'))).toEqual(members(answer));
    }
    expect(members(BOAT)).toEqual(members((SERVED.ready_place['made'] as unknown[])[0]));
    expect(members({ code: '', detail: '', check: '', where: '', spending: null })).toEqual(members(SERVED.refused['refusal']));
  });
});

describe('a draft of a world, as the server answers it', () => {
  it('reads a made world with its parts, their boxes and what was left out', () => {
    const draft = parseWorldMakingDraft(ready);
    expect(draft.state).toBe('ready');
    expect(draft.pollAfterSeconds).toBeNull();
    expect(draft.tool).toEqual({ key: 'place', chosenBy: 'model' });
    expect(draft.entry!.title).toBe('A busy harbour');
    expect(draft.entry!.generatedSite!.kind).toBe('busy_harbour');
    expect(draft.made.map((part) => [part.key, part.look, part.drawn, part.boxMm])).toEqual([
      ['quay', 'ground.quay', 1, null],
      ['boat', 'vehicle.fishing_boat', 4, [2400, 6000, 1800]],
      ['boat_far', 'vehicle.fishing_boat', 2, [2400, 6000, 1800]],
      ['lighthouse', 'structure.lighthouse', 1, [5000, 5000, 9000]],
    ]);
    expect(draft.leftOut).toEqual(['gulls overhead']);
    // A town's parts state no slot count and no box.
    const town = parseWorldMakingDraft({ ...ready, made: [{ key: 'street', label: 'street', form: 'path', look: 'ground.street', drawn: null, box_mm: null }] });
    expect(town.made[0]).toMatchObject({ drawn: null, boxMm: null });
  });

  it('refuses an answer that is not one the contract lists', () => {
    expect(() => parseWorldMakingDraft(wire('kept'))).toThrow('draft state');
    expect(() => parseWorldMakingDraft(wire('ready'))).toThrow('made world');
    expect(() => parseWorldMakingDraft(wire('refused'))).toThrow('draft refusal');
    expect(() => parseWorldMakingDraft(wire('choosing', { tool: { key: 'place', chosen_by: 'a person' } }))).toThrow('draft tool');
    expect(() => parseWorldMakingDraft({ ...ready, made: [{ ...BOAT, box_mm: [2400, 6000] }] })).toThrow('part box');
    expect(() => parseWorldMakingDraft(wire('choosing', { elapsed_seconds: 1.5 }))).toThrow('elapsed');
  });

  it('reads what a draft would meet, and refuses an offer that says both yes and why not', () => {
    expect(OFFER).toMatchObject({
      offered: true, code: null, callsAtMost: 5, descriptionCharacters: 1000, runningDraftId: null,
      starts: { anHour: 12, left: 12, retryAfterSeconds: null },
    });
    const spent = parseWorldDraftOffer(offerWire({
      offered: false, code: 'kind_draft_limit', detail: 'As many drafts as one person may start in an hour were started.',
      starts: { an_hour: 12, left: 0, retry_after_seconds: 540 },
    }));
    expect(spent.starts).toEqual({ anHour: 12, left: 0, retryAfterSeconds: 540 });
    expect(() => parseWorldDraftOffer(offerWire({ code: 'kind_draft_busy' }))).toThrow('draft offer');
    expect(() => parseWorldDraftOffer(offerWire({ offered: false }))).toThrow('draft offer');
    expect(() => parseWorldDraftOffer(offerWire({ calls_at_most: 0 }))).toThrow('draft offer');
    expect(() => parseWorldDraftOffer(offerWire({ starts: { an_hour: 12 } }))).toThrow('draft starts');
  });

  it('asks the three routes the contract names', async () => {
    const asked: { method: string; path: string; body: unknown }[] = [];
    const client = new WorldMakingClient({
      baseUrl: 'https://exulanica.test', token: 'private',
      fetch: vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const request = new Request(input, init);
        const path = new URL(request.url).pathname;
        asked.push({ method: request.method, path, body: request.method === 'POST' ? await request.json() : null });
        if (request.method === 'GET' && path === '/worlds/drafts') return Response.json(offerWire());
        return Response.json(wire('choosing'), { status: request.method === 'POST' ? 202 : 200 });
      }),
    });
    expect((await client.offer()).callsAtMost).toBe(5);
    expect((await client.start(WORDS)).draftId).toBe(DRAFT);
    expect((await client.read(DRAFT)).state).toBe('choosing');
    expect(asked).toEqual([
      { method: 'GET', path: '/worlds/drafts', body: null },
      { method: 'POST', path: '/worlds/drafts', body: { description: WORDS } },
      { method: 'GET', path: `/worlds/drafts/${DRAFT}`, body: null },
    ]);
  });
});

describe('the one box', () => {
  it('says in one plain line what happens to the words, where the person types', () => {
    const { built, field, make } = box([]);
    const notice = built.root.querySelector('.world-sentence-notice')!;
    expect(notice.textContent).toBe(say('worldSentence.notice'));
    expect(notice.textContent).toContain('sent to an AI model');
    expect(notice.textContent).toContain('is kept with the world');
    // The line stands between the heading and the field, before anything is typed.
    expect(notice.nextElementSibling).toBe(field);
    // The longest description is the server's own figure.
    expect(field.maxLength).toBe(OFFER.descriptionCharacters);
    // Nothing is sent for no words.
    expect(make.disabled).toBe(true);
  });

  it('shows what a draft may spend, from the served figures, before the words can be sent', () => {
    const h = box([]);
    // The figures are the offer's: the most calls, and the hour's starts left.
    expect(h.spend.textContent).toBe(SPEND);
    expect(spendWords(parseWorldDraftOffer(offerWire({ calls_at_most: 4, starts: { an_hour: 3, left: 1, retry_after_seconds: null } }))))
      .toContain('up to 4 times');
    // The line stands before the press, and says a draft cannot be stopped.
    expect(h.spend.compareDocumentPosition(h.make) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(h.spend.textContent).toContain('runs to its end');
    h.type(WORDS);
    expect(h.make.disabled).toBe(false);
  });

  it('says a start that would be refused now before a word is typed, and never sends', async () => {
    const limit = parseWorldDraftOffer(offerWire({
      offered: false, code: 'kind_draft_limit', detail: 'As many drafts as one person may start in an hour were started.',
      starts: { an_hour: 12, left: 0, retry_after_seconds: 540 },
    }));
    const h = box([], undefined, limit);
    expect(h.status.textContent).toBe('You have started as many worlds this hour as one person may. The next can start in about 9 minutes.');
    expect(h.spend.textContent).toContain('You have 0 of 12 starts left this hour.');
    h.type(WORDS);
    expect(h.make.disabled).toBe(true);
    h.field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await settle();
    expect(h.start).not.toHaveBeenCalled();
    // A code the page has no words of its own for is said in the server's.
    const full = parseWorldDraftOffer(offerWire({ offered: false, code: 'world_limit_reached', detail: 'the workspace holds 6 of 6' }));
    expect(refusedNowWords(full)).toBe('The workspace already holds as many worlds as it may. No world can be started from here now.');
    expect(box([], undefined, full).status.textContent).toBe(refusedNowWords(full));
    // Another person's draft is running: said, with nothing to follow.
    const other = parseWorldDraftOffer(offerWire({ offered: false, code: 'kind_draft_busy', detail: 'A draft is already running in this workspace.' }));
    const busy = box([], undefined, other);
    expect(busy.status.textContent).toBe(say('worldSentence.busy.other'));
    expect(busy.follow.hidden).toBe(true);
  });

  it('never leaves a dead press alone: where no draft can start now, the recipes are one press away', async () => {
    // Offered: the box is the way in and no other press is shown.
    expect(box([]).toRecipes.hidden).toBe(true);
    for (const code of ['budget_exceeded', 'kind_draft_limit', 'kind_draft_busy', 'world_limit_reached']) {
      const h = box([], undefined, parseWorldDraftOffer(offerWire({ offered: false, code, detail: 'why' })));
      expect(h.make.disabled, code).toBe(true);
      expect(h.toRecipes.hidden, code).toBe(false);
      expect(h.toRecipes.textContent).toBe(say('worldSentence.recipes'));
      h.toRecipes.click();
      expect(h.recipes, code).toHaveBeenCalledTimes(1);
    }
    // The last start of the hour: once that draft ends, the press appears beside what was made.
    const spent = parseWorldDraftOffer(offerWire({ offered: false, code: 'kind_draft_limit', detail: 'why', starts: { an_hour: 12, left: 0, retry_after_seconds: 600 } }));
    const last = box([parseWorldMakingDraft(ready)], undefined, OFFER, [spent]);
    last.type(WORDS);
    last.make.click();
    await settle();
    expect(last.toRecipes.hidden).toBe(true);
    await last.tick();
    expect(last.toRecipes.hidden).toBe(false);
    expect(last.openButton.hidden).toBe(false);
    // A person's own draft still running is followed, not turned away to the recipes.
    const mine = parseWorldDraftOffer(offerWire({ offered: false, code: 'kind_draft_busy', detail: 'why', running_draft_id: DRAFT }));
    expect(box([parseWorldMakingDraft(wire('making'))], undefined, mine).toRecipes.hidden).toBe(true);
  });

  it('sends once, however fast Enter is pressed again', async () => {
    const h = box([]);
    h.type(WORDS);
    const enter = (): boolean => h.field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    enter();
    enter();
    h.make.click();
    await settle();
    expect(h.start).toHaveBeenCalledTimes(1);
  });

  it('picks up a draft of the person\u2019s own that is still running', async () => {
    const running = parseWorldDraftOffer(offerWire({
      offered: false, code: 'kind_draft_busy', detail: 'A draft is already running in this workspace.', running_draft_id: DRAFT,
    }));
    const h = box([parseWorldMakingDraft(wire('making', { elapsed_seconds: 40 })), parseWorldMakingDraft(ready)], undefined, running);
    await settle();
    expect(h.read).toHaveBeenCalledWith(DRAFT);
    expect(h.status.textContent).toBe(fill('worldSentence.making', { elapsed: '40 seconds' }));
    expect(h.field.value).toBe(WORDS);
    expect(h.field.readOnly).toBe(true);
    await h.tick();
    expect(h.status.textContent).toBe('Made: A busy harbour.');
  });

  it('reads what is left again when a draft ends', async () => {
    const after = parseWorldDraftOffer(offerWire({ starts: { an_hour: 12, left: 11, retry_after_seconds: null } }));
    const h = box([parseWorldMakingDraft(ready)], undefined, OFFER, [after]);
    h.type(WORDS);
    h.make.click();
    await settle();
    expect(h.readOffer).not.toHaveBeenCalled();
    await h.tick();
    expect(h.readOffer).toHaveBeenCalledTimes(1);
    expect(h.spend.textContent).toContain('You have 11 of 12 starts left this hour.');
    // How the draft ended stays said.
    expect(h.status.textContent).toBe('Made: A busy harbour.');
  });

  it('says why no further world can be started once the one just made was the last', async () => {
    const full = parseWorldDraftOffer(offerWire({
      offered: false, code: 'world_limit_reached', detail: 'the workspace holds 3 of 3',
      starts: { an_hour: 12, left: 11, retry_after_seconds: null },
    }));
    const h = box([parseWorldMakingDraft(ready)], undefined, OFFER, [full]);
    h.type(WORDS);
    h.make.click();
    await settle();
    await h.tick();
    // The made world stays said, and the reason stands where what is left is said.
    expect(h.status.textContent).toBe('Made: A busy harbour.');
    expect(h.spend.textContent).toContain('You have 11 of 12 starts left this hour.');
    expect(h.spend.textContent).toContain('The workspace already holds as many worlds as it may. No world can be started from here now.');
    h.type('a castle');
    expect(h.make.disabled).toBe(true);
    // The world just made still opens.
    expect(h.openButton.hidden).toBe(false);
  });

  it('follows the draft step by step with the time the server counts, then shows what was made', async () => {
    const h = box([
      parseWorldMakingDraft(wire('drafting', { elapsed_seconds: 7, tool: { key: 'place', chosen_by: 'model' } })),
      parseWorldMakingDraft(wire('making', { elapsed_seconds: 28, tool: { key: 'place', chosen_by: 'model' } })),
      parseWorldMakingDraft(ready),
    ]);
    h.type(`  ${WORDS}  `);
    expect(h.make.disabled).toBe(false);
    h.make.click();
    await settle();
    expect(h.start).toHaveBeenCalledWith(WORDS);
    expect(h.status.textContent).toBe(fill('worldSentence.choosing', { elapsed: '4 seconds' }));
    // While it runs the words stay as sent and nothing else is started.
    expect(h.field.readOnly).toBe(true);
    expect(h.make.disabled).toBe(true);
    // The page asks again when the answer says to.
    expect(h.waiting.map((poll) => poll.ms)).toEqual([3000]);
    await h.tick();
    expect(h.status.textContent).toBe(fill('worldSentence.drafting', { elapsed: '7 seconds' }));
    await h.tick();
    expect(h.status.textContent).toBe(fill('worldSentence.making', { elapsed: '28 seconds' }));
    await h.tick();
    expect(h.read).toHaveBeenCalledTimes(3);
    expect(h.waiting).toHaveLength(0);
    expect(h.status.textContent).toBe('Made: A busy harbour.');
    // Each thing once, in the order made; what was left out in the person's own words.
    expect(h.made.hidden).toBe(false);
    expect(h.made.textContent).toBe('In it: quay, fishing boat, lighthouse.');
    expect(h.leftOut.hidden).toBe(false);
    expect(h.leftOut.textContent).toBe('Not in it yet: “gulls overhead”.');
    expect(h.field.value).toBe('');
    expect(h.field.readOnly).toBe(false);
    // One press opens the world that was made.
    expect(h.openButton.hidden).toBe(false);
    h.openButton.click();
    await settle();
    expect(h.open).toHaveBeenCalledTimes(1);
    expect((h.open.mock.calls[0] as unknown[])[0]).toMatchObject({ title: 'A busy harbour', worldId: 'world:generated-harbour' });
  });

  it('shows no line for what was left out when nothing was', async () => {
    const h = box([parseWorldMakingDraft({ ...ready, left_out: [] })]);
    h.type(WORDS);
    h.make.click();
    await settle();
    await h.tick();
    expect(h.leftOut.hidden).toBe(true);
    expect(h.made.hidden).toBe(false);
  });

  it('makes the world on Enter, and starts a new line on Shift with Enter', async () => {
    const h = box([]);
    h.type(WORDS);
    h.field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true, cancelable: true }));
    await settle();
    expect(h.start).not.toHaveBeenCalled();
    h.field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await settle();
    expect(h.start).toHaveBeenCalledTimes(1);
  });

  it('says a refusal in the closed list’s words with the check’s own sentence, and keeps the words', async () => {
    const refused = parseWorldMakingDraft(wire('refused', {
      refusal: { code: 'kind_not_drafted', detail: 'The keep has no way in from the gate.', check: 'reachable', where: 'keep' },
    }));
    const h = box([refused]);
    h.type(WORDS);
    h.make.click();
    await settle();
    await h.tick();
    expect(h.status.textContent).toBe(
      'No kind of place people can live, walk and work in was drafted. The keep has no way in from the gate. Nothing was made.');
    expect(h.field.value).toBe(WORDS);
    expect(h.field.readOnly).toBe(false);
    expect(h.make.disabled).toBe(false);
    expect(h.openButton.hidden).toBe(true);
    expect(h.waiting).toHaveLength(0);
    // Where no check refused, the other sentence only repeats the list's and is not said.
    const unchecked = box([parseWorldMakingDraft(wire('refused', { refusal: { code: 'kind_not_drafted', detail: 'No kind of world was drafted from these words.' } }))]);
    unchecked.type(WORDS);
    unchecked.make.click();
    await settle();
    await unchecked.tick();
    expect(unchecked.status.textContent).toBe('No kind of place people can live, walk and work in was drafted. Nothing was made.');
    // A code the list has no words for is said by its own sentence, once.
    const unlisted = box([parseWorldMakingDraft(wire('refused', { refusal: { code: 'site_too_small', detail: 'The site is too small for its lots.' } }))]);
    unlisted.type(WORDS);
    unlisted.make.click();
    await settle();
    await unlisted.tick();
    expect(unlisted.status.textContent).toBe('The site is too small for its lots. Nothing was made.');
  });

  it('offers a person their own running draft, and follows it from where it is', async () => {
    const busy = new ApiError(409, 'kind_draft_busy', 'a draft is running', { draft_id: DRAFT });
    const h = box([parseWorldMakingDraft(wire('making', { elapsed_seconds: 40 })), parseWorldMakingDraft(ready)], busy);
    h.type('a castle');
    h.make.click();
    await settle();
    expect(h.status.textContent).toBe(say('worldSentence.busy'));
    expect(h.follow.hidden).toBe(false);
    h.follow.click();
    await settle();
    expect(h.read).toHaveBeenCalledWith(DRAFT);
    expect(h.follow.hidden).toBe(true);
    expect(h.status.textContent).toBe(fill('worldSentence.making', { elapsed: '40 seconds' }));
    // The field shows the words that draft was started with.
    expect(h.field.value).toBe(WORDS);
    await h.tick();
    expect(h.status.textContent).toBe('Made: A busy harbour.');
  });

  it('says so without an offer when the running draft is another person’s', async () => {
    const h = box([], new ApiError(409, 'kind_draft_busy', 'a draft is running'));
    h.type(WORDS);
    h.make.click();
    await settle();
    expect(h.status.textContent).toBe(say('worldSentence.busy.other'));
    expect(h.follow.hidden).toBe(true);
    expect(h.make.disabled).toBe(false);
    expect(h.field.value).toBe(WORDS);
  });

  it('says a draft the server no longer holds, and stops', async () => {
    const h = box([new ApiError(404, 'world_draft_unknown', 'no draft')]);
    h.type(WORDS);
    h.make.click();
    await settle();
    await h.tick();
    expect(h.status.textContent).toBe(say('worldSentence.lost'));
    expect(h.waiting).toHaveLength(0);
    expect(h.make.disabled).toBe(false);
  });

  it('asks again after a failed read, and stops after three in a row', async () => {
    const lost = (): Error => new TypeError('Failed to fetch');
    const h = box([lost(), parseWorldMakingDraft(wire('drafting')), lost(), lost(), lost()]);
    h.type(WORDS);
    h.make.click();
    await settle();
    await h.tick();
    // One failure is not said; the next answer is shown and the count starts again.
    expect(h.status.textContent).toBe(fill('worldSentence.choosing', { elapsed: '4 seconds' }));
    await h.tick();
    expect(h.status.textContent).toBe(fill('worldSentence.drafting', { elapsed: '4 seconds' }));
    await h.tick();
    await h.tick();
    expect(h.waiting).toHaveLength(1);
    await h.tick();
    expect(h.waiting).toHaveLength(0);
    expect(h.status.textContent).not.toBe(fill('worldSentence.drafting', { elapsed: '4 seconds' }));
    expect(h.make.disabled).toBe(false);
  });

  it('stops following when the sheet is closed', async () => {
    const h = box([parseWorldMakingDraft(wire('drafting'))]);
    h.type(WORDS);
    h.make.click();
    await settle();
    h.built.root.remove();
    h.waiting.shift()!.run();
    await settle();
    expect(h.read).not.toHaveBeenCalled();
    expect(h.waiting).toHaveLength(0);
  });

  it('names each made thing once', () => {
    expect(madeWords(parseWorldMakingDraft(ready))).toBe('quay, fishing boat, lighthouse');
    expect(madeWords(parseWorldMakingDraft(wire('choosing')))).toBe('');
  });
});

describe('the sheet with the one box', () => {
  it('shows the heading, the box and Close, and nothing to pick or set', async () => {
    const onClose = vi.fn();
    const sheet = buildWorldRecipes({
      specification: () => new Promise(() => undefined), make: vi.fn(), open: vi.fn(async () => undefined), onClose,
    });
    document.body.replaceChildren(sheet.root);
    attachWorldSentence(sheet, {
      credentials: { baseUrl: 'https://exulanica.test', token: 'private', fetch: vi.fn(async () => Response.json(wire('choosing'), { status: 202 })) },
      offer: OFFER,
      open: vi.fn(async () => undefined),
      recipes: vi.fn(),
    });
    expect(sheet.root.dataset['worldRecipes']).toBe('sentence');
    expect(sheet.root.querySelectorAll('.world-sentence')).toHaveLength(1);
    // No recipe, kind, slider or number: the field and two buttons a person can reach.
    expect(sheet.root.querySelectorAll('input, select')).toHaveLength(0);
    expect(sheet.root.querySelectorAll('textarea')).toHaveLength(1);
    const reachable = [...sheet.root.querySelectorAll<HTMLButtonElement>('button')].filter((button) => button.closest('[hidden]') === null);
    expect(reachable.map((button) => button.textContent)).toEqual([say('worldSentence.make'), say('worldRecipes.close')]);
    reachable[1]!.click();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('puts the recipes back whole, Close included, when a person takes the press to them', () => {
    const onClose = vi.fn();
    const sheet = buildWorldRecipes({
      specification: () => new Promise(() => undefined), make: vi.fn(), open: vi.fn(async () => undefined), onClose,
    });
    document.body.replaceChildren(sheet.root);
    const before = [...sheet.root.children];
    const back = vi.fn();
    attachWorldSentence(sheet, {
      credentials: { baseUrl: 'https://exulanica.test', token: 'private', fetch: vi.fn(async () => Response.json(offerWire())) },
      offer: parseWorldDraftOffer(offerWire({ offered: false, code: 'budget_exceeded', detail: 'the allowance is spent' })),
      open: vi.fn(async () => undefined),
      recipes: back,
    });
    expect(sheet.root.dataset['worldRecipes']).toBe('sentence');
    sheet.root.querySelector<HTMLButtonElement>('.world-sentence-recipes')!.click();
    expect(back).toHaveBeenCalledTimes(1);
    expect(sheet.root.dataset['worldRecipes']).toBeUndefined();
    expect([...sheet.root.children]).toEqual(before);
    expect(sheet.root.querySelector('.world-sentence')).toBeNull();
    // Close is back where it stood and still closes.
    const close = [...sheet.root.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === say('worldRecipes.close'))!;
    close.click();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('is shown where a refusal passes, and never where this person cannot draft', () => {
    expect([...NEVER_DRAFTS].sort()).toEqual(['kinds_from_people_not_offered', 'not_authorised', 'provider_credential_absent']);
    expect(sentenceOffered(OFFER)).toBe(true);
    const refusedBy = (code: string): WorldDraftOffer => parseWorldDraftOffer(offerWire({ offered: false, code, detail: 'why' }));
    for (const passing of ['budget_exceeded', 'world_limit_reached', 'worlds_read_only', 'kind_draft_busy', 'kind_draft_limit']) {
      expect(sentenceOffered(refusedBy(passing)), passing).toBe(true);
    }
    // A server that makes nothing from words, or a person who may ask no model, keeps the recipes.
    for (const never of NEVER_DRAFTS) expect(sentenceOffered(refusedBy(never)), never).toBe(false);
  });
});
