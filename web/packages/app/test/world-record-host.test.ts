// @vitest-environment happy-dom
// The record pages' host parts (tools/previews/world-workspace/record-host.ts, and history-host.ts's pictures): a row
// and a decision find only their own character's moment, though the moments read is not filtered by person; a
// decision says what was decided, said and done in the moment words with its time, cost and people; Compare's line
// and its asks' progress; and the pictures' addresses, made once for a page and taken back only when it closes or the
// world goes, never by a draw. The server and MOTION's renderers are stand-ins; nothing here draws a picture.
import { afterEach, describe, expect, it, vi } from 'vitest';

const reads = vi.hoisted(() => [] as string[]);
// Whether the people catalog is served, and whose portraits were drawn from it.
const people = vi.hoisted(() => ({ served: false, drawn: [] as string[] }));
// Every moment and portrait drawn, in the order drawn, and a gate each draw waits at while one is set.
const draws = vi.hoisted(() => ({ order: [] as string[], gate: null as Promise<void> | null }));
vi.mock('../src/decision-record.ts', () => ({ choiceAccount: () => ({ verdict: null }), parseDecisionEvents: () => ({ events: [] }) }));
vi.mock('../src/config.ts', () => ({ accessHeaders: () => ({}) }));
vi.mock('../src/composition/world-pictures.ts', () => ({
  frameJpeg: async () => new Blob(['still'], { type: 'image/jpeg' }),
  ownWorldPicture: () => null,
  takeFrame: async () => document.createElement('canvas'),
}));
vi.mock('../src/world-pictures-api.ts', () => ({
  HistoryPicturesClient: class {
    async picture(_world: string, sha256: string) { reads.push(sha256); return new Blob([sha256], { type: 'image/jpeg' }); }
    async portraits() { return new Map(); }
  },
}));
vi.mock('../../atlas-react/src/playcanvas/index.ts', () => ({ inhabitantCatalog: () => { if (people.served) return {}; throw new Error('the people are not served yet'); } }));
vi.mock('../../../../tools/previews/world-workspace/moment-pictures.ts', () => ({
  renderBeginningPicture: async () => null,
  // A moment the server would not keep (m6) comes back drawn, with its own bytes; any other comes back kept.
  renderMomentPicture: async ({ moment }: { moment: { moment_id: string } }) => {
    draws.order.push(moment.moment_id);
    if (draws.gate) await draws.gate;
    return moment.moment_id === 'm6'
      ? { sha256: 'unkept:m6', width: 600, height: 340, unkept: new Blob(['drawn'], { type: 'image/jpeg' }) }
      : { sha256: 'b'.repeat(64), width: 600, height: 340 };
  },
}));
vi.mock('../../../../tools/previews/world-workspace/portrait-pictures.ts', () => ({
  lookDigest: () => 'd',
  lookOfSubject: (id: string) => ({ id }),
  // A face the server would not keep (Ines's, on a read-only page) comes back drawn, with its own bytes.
  renderPortrait: async ({ look }: { look: { id: string } }) => {
    people.drawn.push(look.id);
    draws.order.push(`portrait ${look.id}`);
    return look.id === 'ines'
      ? { sha256: 'unkept:portrait:ines', width: 156, height: 156, unkept: new Blob(['face'], { type: 'image/jpeg' }) }
      : { sha256: 'c'.repeat(64), width: 156, height: 156 };
  },
}));

type Json = Record<string, any>;
// Joined paths: the test runner still finds the files, and the type checker leaves the preview modules out.
const recordHost = async (): Promise<any> => import('../../../../tools/previews/world-workspace/' + 'record-host.ts');
// The recipe History draws a moment's picture by, as the preview reads it: its moments read asks by it.
const recipe = async (): Promise<string> =>
  ((await import('../../../../tools/previews/world-workspace/' + 'moment-framing.mjs')) as { MOMENT_FRAMING: { recipe: string } }).MOMENT_FRAMING.recipe;
const historyHost = async (): Promise<any> => import('../../../../tools/previews/world-workspace/' + 'history-host.ts');

const NAMES: Record<string, string> = { teo: 'Teo', ines: 'Ines', marco: 'Marco' };
// Named people, and the canopy strider named by its kind (J20's three forms).
const who = (id: string) => (id in NAMES ? { title: NAMES[id], start: NAMES[id], within: NAMES[id], named: true } : { title: 'Canopy strider', start: 'The canopy strider', within: 'the canopy strider', named: false });
const KEPT = { sha256: 'f'.repeat(64), width: 600, height: 340 };
// Teo met Ines and spoke to her under r1, his model's decision, so the moment reads "Teo spoke to Ines" on every page;
// Marco spoke to Teo under r9 (Marco's decision, Teo only spoken to).
const MOMENTS = [
  { moment_id: 'm1', request_id: 'r1', subjects: ['teo', 'ines'], kind: 'met', tick: 412, scene: { people: [{}] }, picture: KEPT, said: [{ by: 'teo', request_id: 'r1', tick: 412, line: 'Morning, Ines.', decider: { kind: 'model', model: null } }] },
  { moment_id: 'm9', request_id: 'r9', subjects: ['marco', 'teo'], kind: 'spoke', tick: 429, scene: { people: [{}] }, picture: KEPT, said: [{ by: 'marco', request_id: 'r9', tick: 429, line: 'Did they bring in anything good?' }] },
  { moment_id: 'm5', request_id: 'r5', subjects: ['teo'], kind: 'left', tick: 391, scene: null, picture: null, said: [] },
  { moment_id: 'm7', request_id: 'r7', subjects: ['strider', 'teo'], kind: 'spoke', tick: 420, scene: null, picture: null, said: [{ by: 'strider', request_id: 'r7', tick: 420, line: 'Rest in my shade.' }] },
];

function fakePictures() {
  return {
    still: () => 'blob:still', momentNow: vi.fn((moment: Json) => `blob:${moment.moment_id}`), portraitNow: vi.fn((id: string) => `blob:portrait-${id}`),
    takeStill: vi.fn(), beginningPicture: vi.fn(), pictureAddress: vi.fn(), pictureNow: vi.fn(), renderMomentPicture: vi.fn(), portrait: vi.fn(), release: vi.fn(), dispose: vi.fn(),
  };
}

function host(extra: Json = {}) {
  const pictures = fakePictures();
  return {
    pictures,
    host: {
      versionPath: '/world/versions/v1', scope: '?world_id=w1', pictures,
      read: vi.fn(async (path: string) => (path.includes('/history/moments') ? { moments: MOMENTS } : { things: [] })),
      subjectView: (row: Json) => ({ who: who(row.scene.id), facts: { startMinute: 0 }, doing: 'Waiting by the bench', decider: null, model: 'Nemotron 3 Nano 30B' }),
      modelOf: () => ({ model: { name: 'Nemotron 3 Nano 30B' } }),
      nameOf: (id: string) => who(id).within,
      personName: (id: string) => NAMES[id] ?? null,
      modelName: () => 'Nemotron 3 Nano 30B',
      latest: () => null,
      compareModels: () => [], modelKey: () => '', comparedDecisions: () => [], boundOf: () => 0,
      label: () => null, run: () => null, assignable: () => true,
      ...extra,
    },
  };
}

const teoPage = () => ({ row: { scene: { id: 'teo' } }, events: [], moments: null, things: null, did: null });

afterEach(() => { reads.length = 0; draws.order.length = 0; draws.gate = null; vi.restoreAllMocks(); });

describe("a record page's moments", () => {
  it("finds a character's own moment by its request, never someone else's that names the same request", async () => {
    const { ownMoment } = await recordHost();
    expect(ownMoment(MOMENTS, 'r1', 'teo')?.moment_id).toBe('m1');
    // Teo is in Marco's moment, spoken to, but the request is Marco's: not Teo's moment.
    expect(ownMoment(MOMENTS, 'r9', 'teo')).toBeNull();
    expect(ownMoment(MOMENTS, 'r9', 'marco')?.moment_id).toBe('m9');
    // A moment that names Teo's request with someone else acting first, and a line someone else said under it.
    const borrowed = [{ moment_id: 'x', request_id: 'r1', subjects: ['ines', 'teo'], kind: 'met', said: [{ by: 'ines', request_id: 'r1', line: 'Hello.' }] }];
    expect(ownMoment(borrowed, 'r1', 'teo')).toBeNull();
    expect(ownMoment(MOMENTS, null, 'teo')).toBeNull();
  });

  it("fills a row of What Teo did from Teo's own moment alone: its title, the line said and its picture", async () => {
    const { recordStates } = await recordHost();
    const made = host();
    const records = recordStates(made.host);
    const showing = teoPage();
    await records.readMoments(showing);
    expect(made.host.read).toHaveBeenCalledWith(`/world/versions/v1/history/moments?world_id=w1&limit=200&recipe=${encodeURIComponent(await recipe())}`);
    expect(records.dayRow(showing, { requestId: 'r1' })).toEqual({ moment: true, title: 'Teo spoke to Ines', said: '“Morning, Ines.”', picture: 'blob:m1' });
    // A row's picture waits its turn among the day's: it is not the open page's own.
    expect(made.pictures.momentNow.mock.calls.map((call: unknown[]) => call[1])).toEqual([undefined]);
    // Marco's moment never titles or pictures a row of Teo's, whatever request the row names.
    expect(records.dayRow(showing, { requestId: 'r9' })).toEqual({});
    expect(records.dayRow(showing, { requestId: null, heard: true })).toEqual({});
    expect(made.pictures.momentNow.mock.calls.map(([moment]) => moment.moment_id)).toEqual(['m1']);
  });

  it("reads the society's runs where the day page asks, each the minutes it played (P2), and keeps them where refused", async () => {
    const { recordStates } = await recordHost();
    const sessions = { sessions: [{ opened: { start_tick: 430 }, closed: null }, { opened: { start_tick: 360 }, closed: { end_tick: 375 } }] };
    const made = host({ read: vi.fn(async (path: string) => (path.includes('/control/sessions') ? sessions : path.includes('/history/moments') ? { moments: MOMENTS } : { things: [] })) });
    const records = recordStates(made.host);
    const showing: Json = teoPage();
    await records.readMoments(showing, true);
    expect(made.host.read).toHaveBeenCalledWith('/world/versions/v1/society/control/sessions?world_id=w1');
    expect(showing.runs).toEqual([{ from: 430, to: null }, { from: 360, to: 375 }]);
    // A decision opened from History reads no runs.
    made.host.read.mockClear();
    await records.readMoments(teoPage());
    expect(made.host.read.mock.calls.map(([path]) => path).filter((path) => path.includes('/control/sessions'))).toEqual([]);
    // A refused read keeps the runs read before, and a page that had none has none.
    const refused = recordStates(host({ read: vi.fn(async (path: string) => {
      if (path.includes('/control/sessions')) throw new Error('refused');
      return path.includes('/history/moments') ? { moments: MOMENTS } : { things: [] };
    }) }).host);
    const quiet: Json = teoPage();
    await refused.readMoments(quiet, true);
    await refused.readMoments(showing, true);
    expect([quiet.runs, showing.runs]).toEqual([undefined, [{ from: 430, to: null }, { from: 360, to: 375 }]]);
  });

  it('says what Teo did at a choice that made no moment, in the past, else keeps the choice as offered (R5e)', async () => {
    const { recordStates } = await recordHost();
    const bench = { thing_id: 'bench:1', kind: { kind: 'bench' } };
    const records = recordStates(host({ read: vi.fn(async (path: string) => (path.includes('/history/moments') ? { moments: MOMENTS } : { things: [bench] })) }).host);
    const showing = teoPage();
    await records.readMoments(showing);
    const use = 'authored:3c4d5e6f-0000-4000-8000-000000000002:bench:1:sit';
    expect(records.dayRow(showing, { requestId: 'w1', did: { kind: 'waited', target: null, with: null } })).toEqual({ title: 'Waited' });
    expect(records.dayRow(showing, { requestId: 'w2', did: { kind: 'went', target: { target_id: use, activity: 'rest' }, with: null } })).toEqual({ title: 'Went to rest at the bench' });
    expect(records.dayRow(showing, { requestId: 'w3', did: { kind: 'talked', target: null, with: 'ines' } })).toEqual({ title: 'Talked with Ines' });
    // A kind the moment rules do not map, no did at all, or a line heard: the row keeps its own words.
    expect([records.dayRow(showing, { requestId: 'w4', did: { kind: null, target: null, with: null } }), records.dayRow(showing, { requestId: 'w5', did: null }),
      records.dayRow(showing, { requestId: null, heard: true, did: { kind: 'waited', target: null, with: null } })]).toEqual([{}, {}, {}]);
    // A choice that made Teo's own moment is titled by the moment, whatever it did.
    expect(records.dayRow(showing, { requestId: 'r1', did: { kind: 'waited', target: null, with: null } }).title).toBe('Teo spoke to Ines');
  });

  it('lets a row fold only where its decision made no moment of Teo\'s and the moments read covers its minute (R5e)', async () => {
    const { recordStates } = await recordHost();
    const records = recordStates(host().host);
    const showing = teoPage();
    // Nothing folds before the moments read answers.
    expect(records.foldable(showing, { requestId: 'w1', tick: 400 })).toBe(false);
    await records.readMoments(showing);
    // The read is whole: a wait with no moment folds; Teo's meeting does not; Marco's moment is not Teo's.
    expect([records.foldable(showing, { requestId: 'w1', tick: 400 }), records.foldable(showing, { requestId: 'r1', tick: 412 }), records.foldable(showing, { requestId: 'r9', tick: 429 })]).toEqual([true, false, true]);
    // A read that stopped short (more to come) covers its oldest moment's minute on: an older choice never folds.
    const short = recordStates(host({ read: vi.fn(async (path: string) => (path.includes('/history/moments') ? { moments: MOMENTS, more: true } : { things: [] })) }).host);
    const cut = teoPage();
    await short.readMoments(cut);
    expect([short.foldable(cut, { requestId: 'w1', tick: 391 }), short.foldable(cut, { requestId: 'w2', tick: 390 }), short.foldable(cut, { requestId: 'w3', tick: null })]).toEqual([true, false, false]);
  });

  it("says who decides for Teo, what Teo is doing, Teo's portrait, and Teo's model deciding while a run is on", async () => {
    const { recordStates } = await recordHost();
    const records = recordStates(host().host);
    const view = { who: who('teo'), doing: 'Waiting by the bench', decider: null, model: 'Nemotron 3 Nano 30B' };
    expect(records.day(teoPage(), view, true)).toEqual({ portrait: 'blob:portrait-teo', doing: 'Waiting by the bench', decider: null, decides: 'Nemotron 3 Nano 30B decides for Teo', running: null });
    // A routine keeps the Run section's own line; until the models are read nothing is said of who decides.
    expect(records.day(teoPage(), { ...view, model: null }, true)).not.toHaveProperty('decides');
    expect(records.day(teoPage(), view, false)).not.toHaveProperty('decides');
    const running = recordStates(host({ run: () => ({ endsBy: new Date(Date.now() + 553_000).toISOString() }) }).host);
    expect(running.day(teoPage(), view, true).running).toMatch(/^Teo's model is deciding · 9:1[23] left$/);
  });
});

describe("the day page's events, read back on demand", () => {
  // Three pages of the society's events, newest first; each event one row of Teo's.
  const pages: Record<string, Json> = {
    '': { events: [{ id: 'e9' }, { id: 'e8' }], next: 'c1' },
    c1: { events: [{ id: 'e7' }, { id: 'e6' }], next: 'c2' },
    c2: { events: [{ id: 'e5' }], next: null },
  };
  const readPage = vi.fn(async (before: string) => pages[before]!);
  const rowsOf = (events: readonly Json[]) => events.length;

  it('reads from the newest until the rows wanted are found, and keeps where it stopped', async () => {
    const { readDayEvents } = await recordHost();
    readPage.mockClear();
    const first = await readDayEvents({ readPage, rowsOf, want: 3, pages: 4 });
    expect([first.events.map((event: Json) => event.id), first.next, readPage.mock.calls.map(([before]) => before)]).toEqual([['e9', 'e8', 'e7', 'e6'], 'c2', ['', 'c1']]);
    // [↓] past the oldest row reads on from there, after what it held, until the read has no more.
    readPage.mockClear();
    const on = await readDayEvents({ readPage, rowsOf, held: first.events, next: first.next, want: 10, pages: 4 });
    expect([on.events.map((event: Json) => event.id), on.next, readPage.mock.calls.map(([before]) => before)]).toEqual([['e9', 'e8', 'e7', 'e6', 'e5'], null, ['c2']]);
  });

  it('reads no more than its pages at a time', async () => {
    const { readDayEvents } = await recordHost();
    readPage.mockClear();
    const capped = await readDayEvents({ readPage, rowsOf, want: 99, pages: 1 });
    expect([capped.events.length, capped.next, readPage.mock.calls.length]).toEqual([2, 'c1', 1]);
  });
});

describe('a day page left open while the world plays (F12)', () => {
  // Held newest first: minute 12 read while e4 alone was recorded in it.
  const held = [{ event_id: 'e4', tick: 12 }, { event_id: 'e3', tick: 11 }, { event_id: 'e2', tick: 11 }];

  it('reads from its newest minute and puts what came since on top, that minute in the read\'s order', async () => {
    const { readNewerEvents } = await recordHost();
    // The window reads oldest first: minute 12 whole (e5 came in it after e4 was read), then 13 over two pages.
    const windows: Record<string, Json> = {
      '': { events: [{ event_id: 'e4', tick: 12 }, { event_id: 'e5', tick: 12 }, { event_id: 'e6', tick: 13 }], next: 'w1' },
      w1: { events: [{ event_id: 'e7', tick: 13 }], next: null },
    };
    const readWindow = vi.fn(async (_from: number, after: string) => windows[after]!);
    const since = await readNewerEvents({ readWindow, held, pages: 4 });
    expect(readWindow.mock.calls).toEqual([[12, ''], [12, 'w1']]);
    expect(since.events.map((event: Json) => event.event_id)).toEqual(['e6', 'e7', 'e4', 'e5', 'e3', 'e2']);
    expect(since.fresh.map((event: Json) => event.event_id)).toEqual(['e5', 'e6', 'e7']);
  });

  it('answers nothing new as no fresh events, and a backlog or an empty page as null', async () => {
    const { readNewerEvents } = await recordHost();
    const quiet = await readNewerEvents({ readWindow: async () => ({ events: [{ event_id: 'e4', tick: 12 }], next: null }), held, pages: 4 });
    expect([quiet.fresh, quiet.events.map((event: Json) => event.event_id)]).toEqual([[], ['e4', 'e3', 'e2']]);
    expect(await readNewerEvents({ readWindow: async () => ({ events: [], next: 'more' }), held, pages: 2 })).toBeNull();
    expect(await readNewerEvents({ readWindow: async () => ({ events: [], next: null }), held: [], pages: 2 })).toBeNull();
  });

  it('keeps the chosen row chosen as rows come on top', async () => {
    const { dayFocus } = await recordHost();
    const before = [{ requestId: 'r2' }, { requestId: null }, { requestId: 'r1' }];
    // Two rows on top: the decision chosen stays chosen, found by its decision; a routine row moves down with it.
    const rows = [{ requestId: 'r4' }, { requestId: null, heard: true }, ...before];
    expect(dayFocus({ rows, focus: 2, before })).toBe(4);
    expect(dayFocus({ rows, focus: 1, before })).toBe(3);
    // A repeat folded into the newest row takes its newest decision: no row came on top, the same place is chosen.
    expect(dayFocus({ rows: [{ requestId: 'r3' }, ...before.slice(1)], focus: 0, before })).toBe(0);
    // A fold further down that split once its moment was read: the decision chosen is found where it now stands.
    expect(dayFocus({ rows: [{ requestId: 'r2' }, { requestId: 'r1' }, { requestId: 'r0' }], focus: 0, before: [{ requestId: 'r2' }, { requestId: 'r1' }] })).toBe(0);
    // At first, the newest row a decision stands behind; read on, the first row past the old oldest that is not heard.
    expect(dayFocus({ rows, focus: null })).toBe(0);
    expect(dayFocus({ rows: [{ requestId: null }, { requestId: 'r1' }, { requestId: null, heard: true }, { requestId: 'r0' }], focus: 1, earlier: true })).toBe(3);
  });

  it('follows the newest decision as rows come on top until the person moves the choice (F12b)', async () => {
    const { dayFocus } = await recordHost();
    const before = [{ requestId: 'r2' }, { requestId: null }, { requestId: 'r1' }];
    // A routine row, a decision and a line heard came on top.
    const rows = [{ requestId: null }, { requestId: 'r4' }, { requestId: null, heard: true }, ...before];
    // Not moved: the choice goes to the newest row a decision stands behind, past the routine row on top.
    expect(dayFocus({ rows, focus: 0, before, moved: false })).toBe(1);
    // With no decision on top, the newest of the character's own.
    expect(dayFocus({ rows: [{ requestId: null, heard: true }, { requestId: null }], focus: 0, before: [{ requestId: null }], moved: false })).toBe(1);
    // Moved, or left unsaid: the row it was on stays chosen.
    expect(dayFocus({ rows, focus: 2, before, moved: true })).toBe(5);
    expect(dayFocus({ rows, focus: 2, before })).toBe(5);
  });
});

describe('a decision, filled', () => {
  const detail = (label: string, provider: Json | null = { latency_ms: 900, cost_usd: '0.0003', cost_known: true }) => ({
    request: { base_tick: 412, provider_config: { provider: 'nvidia', model_id: 'nemotron-3-nano-30b' }, context: { options: [{ label }, { label: 'walk to the bench' }] } },
    decision: { proposal: { label }, provider },
  });

  it('says what Teo decided and said in the moment words, with its time, cost, picture and people', async () => {
    const { recordStates } = await recordHost();
    const made = host();
    const records = recordStates(made.host);
    const showing = teoPage();
    await records.readMoments(showing);
    const state = records.decision(showing, { requestId: 'r1', detail: detail('say something to Ines'), failure: null, record: false }, { earlier: true });
    expect(state).toMatchObject({
      over: '06:52 · Day 1 · Teo spoke to Ines',
      decided: 'Teo spoke to Ines', said: 'Teo: “Morning, Ines.”', action: null,
      decider: 'model', answered: { latencyMs: 900, costUsd: '0.0003', costKnown: true }, choicesHeading: "Teo's choices",
      picture: 'blob:m1', portraits: [{ name: 'Teo', url: 'blob:portrait-teo' }, { name: 'Ines', url: 'blob:portrait-ines' }],
      ground: 'blob:still', earlier: true, later: false, canCompare: false, toldLabel: "What Teo's model was told",
    });
    // The decision's picture is the open page's own, drawn ahead of those its day's rows asked for.
    expect(made.pictures.momentNow).toHaveBeenLastCalledWith(expect.objectContaining({ moment_id: 'm1' }), true);
  });

  it('names the minute the decision applied in, as its row does, not the minute it was asked in', async () => {
    const { recordStates } = await recordHost();
    // Asked in minute 412 (06:52), applied in minute 413 (06:53): the day row says 06:53, so the page does.
    const records = recordStates(host({ latest: (requestId: string) => (requestId === 'r1' ? { consumedTick: 413 } : null) }).host);
    const showing = teoPage();
    await records.readMoments(showing);
    const state = records.decision(showing, { requestId: 'r1', detail: detail('say something to Ines'), failure: null, record: false });
    expect(state.over).toBe('06:53 · Day 1 · Teo spoke to Ines');
    // Not applied yet: the minute it was asked in.
    const pending = recordStates(host().host);
    await pending.readMoments(showing);
    expect(pending.decision(showing, { requestId: 'r1', detail: detail('say something to Ines'), failure: null, record: false }).over).toBe('06:52 · Day 1 · Teo spoke to Ines');
  });

  it("titles a meeting the engine began by the decision whose line is in it, its portraits in that order (DESIGN)", async () => {
    const { recordStates } = await recordHost();
    const records = recordStates(host().host);
    const showing: Json = teoPage();
    await records.readMoments(showing);
    // Ines's routine began the meeting; Teo's decision said its line.
    showing.moments = (showing.moments ?? []).map((moment: Json) => (moment.moment_id === 'm1' ? { ...moment, subjects: ['ines', 'teo'] } : moment));
    const state = records.decision(showing, { requestId: 'r1', detail: detail('say something to Ines'), failure: null, record: false });
    expect(state.over).toBe('06:52 · Day 1 · Teo spoke to Ines');
    expect(state.portraits.map((portrait: Json) => portrait.name)).toEqual(['Teo', 'Ines']);
  });

  it("says a person playing decided where the request was a person's, with no model, time or cost", async () => {
    const { recordStates } = await recordHost();
    const records = recordStates(host({ modelName: () => null }).host);
    const showing = teoPage();
    await records.readMoments(showing);
    const played = { ...detail('say something to Ines', { kind: 'person', answer_sha256: 'a'.repeat(64) }) };
    played.request = { ...played.request, provider_config: { kind: 'person', contract: { sha256: 'c'.repeat(64) } } } as never;
    const state = records.decision(showing, { requestId: 'r1', detail: played, failure: null, record: false });
    expect([state.decider, state.model, state.answered, state.decided]).toEqual(['person', null, null, 'Teo spoke to Ines']);
    // A person playing Teo was shown what the record holds; no model was told it.
    expect(state.toldLabel).toBe('What the person playing Teo was shown');
  });

  it("says an outside program decided where the request was a program's, and that the program was told", async () => {
    const { recordStates } = await recordHost();
    const records = recordStates(host({ modelName: () => null }).host);
    const showing = teoPage();
    await records.readMoments(showing);
    const program = { ...detail('say something to Ines', { kind: 'external', bridge: 'b1', answer_sha256: 'a'.repeat(64), latency_ms: 1300 }) };
    program.request = { ...program.request, provider_config: { kind: 'external', bridge: 'b1', grant_id: 'g1', grant_seq: 1 } } as never;
    const state = records.decision(showing, { requestId: 'r1', detail: program, failure: null, record: false });
    expect([state.decider, state.model, state.answered, state.decided]).toEqual(['external', null, null, 'Teo spoke to Ines']);
    // A machine is told, a person is shown (WORDS.md R5c); the program is named as Teo's, never as a model.
    expect(state.toldLabel).toBe("What Teo's outside program was told");
  });

  it('names a speaker a kind names in its title form, the sentence around them as their tag does', async () => {
    const { recordStates } = await recordHost();
    const records = recordStates(host().host);
    const showing = { ...teoPage(), row: { scene: { id: 'strider' } } };
    await records.readMoments(showing);
    const state = records.decision(showing, { requestId: 'r7', detail: detail('say something to Teo'), failure: null, record: false });
    expect([state.said, state.decided]).toEqual(['Canopy strider: \u201cRest in my shade.\u201d', 'The canopy strider spoke to Teo']);
  });

  it('says the action where nothing was said, and before its record is read only what it has', async () => {
    const { recordStates } = await recordHost();
    const records = recordStates(host().host);
    const showing = teoPage();
    await records.readMoments(showing);
    const left = records.decision(showing, { requestId: 'r5', detail: detail('leave'), failure: null, record: false });
    expect([left.decided, left.said, left.action, left.picture]).toEqual(['Teo left', null, 'Teo left', 'blob:m5']);
    const reading = records.decision(showing, { requestId: 'r5', detail: null, failure: null, record: false });
    expect(reading).not.toHaveProperty('decided');
    expect(reading.ground).toBe('blob:still');
  });

  it("says a model's decision with no usable answer was asked and the routine acted, never that it chose (U3)", async () => {
    const { recordStates } = await recordHost();
    const records = recordStates(host().host);
    const showing = teoPage();
    await records.readMoments(showing);
    // Its answer was not one of the actions, and its second ask was refused for money: one ask sent, no proposal.
    const sent = { latency_ms: 2100, cost_usd: '0.01214400', cost_known: true, calls: [{ outcome: 'reply_refused', usd: '0.01214400' }] };
    const refused = { ...detail('leave', sent), decision: { status: 'unavailable', reason: 'spending_limit_reached', proposal: null, provider: sent } };
    const state = records.decision(showing, { requestId: 'r5', detail: refused, failure: null, record: false });
    expect(state.unanswered).toEqual({ asks: 1, latencyMs: 2100, costUsd: '0.01214400', costKnown: true, reason: 'spending_limit_reached' });
    expect([state.answered, state.late, state.choices.some((choice: Json) => choice.chosen)]).toEqual([null, false, false]);
    expect(state.notes).toMatchObject({
      by: "Its answer was not one of the actions, and asking it again would have gone over the money left, so Teo's routine acted.",
      ring: 'How long its one ask took and what it cost.',
      choices: "The actions the world allowed Teo there. The model's answer was not one of them, so none was taken.",
    });
    // Nothing sent: the receipt names no provider, so it was not asked.
    const unasked = { ...detail('leave', null), decision: { status: 'unavailable', reason: 'spending_limit_reached', proposal: null, provider: null } };
    expect(records.decision(showing, { requestId: 'r5', detail: unasked, failure: null, record: false }).unanswered).toMatchObject({ asks: 0 });
    // An answered decision is as before.
    expect(records.decision(showing, { requestId: 'r5', detail: detail('leave'), failure: null, record: false })).toMatchObject({ unanswered: null, late: false });
  });

  it('says a choice its minute found the world had moved past was made too late, titled by what Teo did (U3)', async () => {
    const { recordStates } = await recordHost();
    const records = recordStates(host().host);
    const showing: Json = teoPage();
    await records.readMoments(showing);
    // The minute found the world changed: the event keeps the choice, disposition stale; the routine acted.
    showing.events = [...(showing.events ?? []), { event_kind: 'decision_applied', tick: 412, subject_id: 'teo',
      document: { request_id: 'r9', chose: 'walk to the bench', disposition: 'stale', reason: 'decision_context_changed' } }];
    showing.did = [{ what: 'Walked to the quay', requestId: 'r9' }];
    const state = records.decision(showing, { requestId: 'r9', rowIndex: 0, detail: detail('walk to the bench'), failure: null, record: false });
    expect([state.late, state.unanswered, state.title]).toEqual([true, null, 'Walked to the quay']);
    // The model picked one: its row stays marked, and its answer's time and cost stand under the ring.
    expect(state.choices.find((choice: Json) => choice.chosen)?.words).toMatch(/bench/i);
    expect(state.answered).toEqual({ latencyMs: 900, costUsd: '0.0003', costKnown: true });
    expect(state.notes).toMatchObject({
      by: "The world had moved on before its choice could be acted on, so Teo's routine acted.",
      choices: 'The actions the world allowed Teo there. The model picked one, but the world had moved on before it could happen.',
    });
  });
});

describe('Compare, filled', () => {
  const decision = (requestId: string, tick: number, chose: string) => ({ requestId, baseTick: tick, chose, line: null, askUsd: { chosen: '0.0005', again: '0.0005' }, model: { provider: 'nvidia', modelId: 'nemotron' } });
  const comparison = (asking: Json | null) => ({
    decisions: [decision('r1', 401, 'walk to the bench'), decision('r2', 403, 'wait a minute'), decision('r3', 406, 'stand here')],
    answers: new Map([['r1', { other: { chose: 'walk to the lower pools', costUsd: '0.0004' } }], ['r2', { other: { chose: 'wait a minute', costUsd: '0.0003' } }]]),
    other: { name: 'Qwen3 235B Instruct' }, single: false, focus: 2, details: new Map(), busy: false, asking, most: 0.003,
    recordedName: 'Nemotron 3 Nano 30B', againRefused: false,
  });

  it('stands the asks in the answer\'s place while they run, and then shows what was asked and spent', async () => {
    const { recordStates } = await recordHost();
    const records = recordStates(host().host);
    const asked = records.comparison({ ...teoPage(), comparison: comparison({ done: 2, total: 6, spent: 0.0007, stop: true }) });
    expect(asked.asking).toMatch(/^Asking 2 of 6 · /);
    expect(asked.use).toBeNull();
    expect(asked.ground).toBe('blob:still');
    // Every moment on the line: two asked (one different, with its words), the third not asked.
    expect(asked.line).toEqual([
      { time: '06:41', asked: true, different: 'Walk to the lower pools' },
      { time: '06:43', asked: true, different: null },
      { time: '06:46', asked: false, different: null },
    ]);
    const ended = records.comparison({ ...teoPage(), comparison: comparison(null) });
    expect(ended.asking).toBeNull();
    expect(ended.spent).toMatch(/0\.0007/);
    expect(ended.use).toBe('Use Qwen3 235B Instruct for Teo');
  });

  it('names each moment by the minute it applied in, as the decision page and the day row do (H1)', async () => {
    const { recordStates } = await recordHost();
    // r1 asked in minute 401 (06:41), applied in 402 (06:42); r2 and r3 not applied yet: the minute each was asked in.
    const records = recordStates(host({ latest: (requestId: string) => (requestId === 'r1' ? { consumedTick: 402 } : null) }).host);
    const state = records.comparison({ ...teoPage(), comparison: comparison(null) });
    expect(state.line.map((point: Json) => point.time)).toEqual(['06:42', '06:43', '06:46']);
    expect(state.over).toBe('Teo · 3 decisions, 06:42 to 06:46 · Day 1');
  });
});

describe("a world's pictures", () => {
  function urls() {
    let made = 0;
    const revoked: string[] = [];
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: () => `blob:made-${(made += 1)}` });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: (address: string) => { revoked.push(address); } });
    return revoked;
  }
  const source = { app: { on() {}, off() {}, renderNextFrame: false, graphicsDevice: { canvas: document.createElement('canvas') } }, invalidate: vi.fn() };
  const open = async (changed = vi.fn()) => (await historyHost()).recordPictures({ entry: { worldId: 'w1', entryId: 'e1', authoredVersionId: 'v1' }, credentials: { baseUrl: 'http://api.test' }, source, changed });

  it('reads a kept picture once for a page, whatever is drawn, and takes its address back only when the page closes', async () => {
    const revoked = urls();
    const changed = vi.fn();
    const pictures = await open(changed);
    expect(pictures.pictureNow(KEPT)).toBeNull();
    await vi.waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    for (let draw = 0; draw < 5; draw += 1) expect(pictures.pictureNow(KEPT)).toBe('blob:made-1');
    expect([reads.length, revoked]).toEqual([1, []]);
    pictures.release();
    expect(revoked).toEqual(['blob:made-1']);
    // The next page reads it again.
    expect(pictures.pictureNow(KEPT)).toBeNull();
    await vi.waitFor(() => expect(pictures.pictureNow(KEPT)).toBe('blob:made-2'));
    expect(reads.length).toBe(2);
    pictures.dispose();
    expect(revoked).toEqual(['blob:made-1', 'blob:made-2']);
    expect(pictures.pictureNow({ ...KEPT, sha256: 'e'.repeat(64) })).toBeNull();
    expect(reads.length).toBe(2);
  });

  it('keeps one still, replacing the last when a new one is taken, and makes a missing moment picture once, shown even where it is not kept', async () => {
    const revoked = urls();
    const pictures = await open();
    expect(await pictures.takeStill()).toBe('blob:made-1');
    expect(source.invalidate).toHaveBeenCalled();
    expect(await pictures.takeStill()).toBe('blob:made-2');
    expect([pictures.still(), revoked]).toEqual(['blob:made-2', ['blob:made-1']]);
    const missing = { moment_id: 'm5', scene: { people: [{}] }, picture: null };
    expect(pictures.momentNow(missing)).toBeNull();
    await vi.waitFor(() => expect(pictures.momentNow(missing)).toBe('blob:made-3'));
    expect(reads).toEqual(['b'.repeat(64)]);
    // Portraits wait for the people to be served, asked again by a later draw.
    expect(await pictures.portrait('teo')).toBeNull();
    expect(pictures.portraitNow('teo')).toBeNull();
    // One the server did not keep shows from the bytes drawn here, read from nowhere, and goes with the page.
    const unkept = { moment_id: 'm6', scene: { people: [{}] }, picture: null };
    expect(pictures.momentNow(unkept)).toBeNull();
    await vi.waitFor(() => expect(pictures.momentNow(unkept)).toBe('blob:made-4'));
    expect(reads).toEqual(['b'.repeat(64)]);
    pictures.release();
    expect(revoked).toEqual(['blob:made-1', 'blob:made-2', 'blob:made-3', 'blob:made-4']);
    expect(pictures.still()).toBeNull();
  });

  it("draws a face only for one the world draws as one of its people: a creature is drawn by its own look", async () => {
    urls();
    people.served = true;
    people.drawn.length = 0;
    // The saved world's society: Teo from the people catalog, the canopy strider and the knight by their own looks, a
    // newcomer not yet known. The things draw the strider in its chosen look; the knight's look cannot be drawn.
    const asked: string[] = [];
    const drawnAsPerson = (id: string) => { asked.push(id); return id === 'teo' ? true : id === 'strider' || id === 'knight' ? false : null; };
    const being = (id: string) => ({ id, kind: { kind: id, version: 1, sha256: id[0]!.repeat(64) } });
    const inhabitantOf = (id: string) => (id === 'strider' || id === 'knight' ? being(id) : null);
    const look = { key: 'strider-dusk', version: 1, sha256: 'e'.repeat(64) };
    const drawn: unknown[][] = [];
    const things = {
      crowdFigures: { drawnAs: (person: { id: string; kind: unknown }) => ({ kind: person.kind, look: person.id === 'strider' ? look : null }) },
      layer: { drawKindPicture: async (...args: unknown[]) => { drawn.push(args); return (args[2] as { look: typeof look | null }).look === look ? 'data:image/png;base64,U1RSSURFUg==' : null; } },
    };
    const pictures = await (await historyHost()).recordPictures({
      entry: { worldId: 'w1', entryId: 'e1', authoredVersionId: 'v1' }, credentials: { baseUrl: 'http://api.test' },
      source: { ...source, authoredSociety: { drawnAsPerson, inhabitantOf }, __workspaceThings: () => things },
    });
    expect(await pictures.portrait('strider')).toBe('data:image/png;base64,U1RSSURFUg==');
    expect(await pictures.portrait('knight')).toBeNull();
    expect(await pictures.portrait('teo')).toBe('blob:made-1');
    expect(await pictures.portrait('newcomer')).toBeNull();
    // Never a face for a being: the strider is its kind in its look, framed round in the recipe's square; the knight keeps the quiet circle.
    expect(people.drawn).toEqual(['teo']);
    expect(drawn).toEqual([[being('strider').kind, { width: 156, height: 156 }, { look, round: true }], [being('knight').kind, { width: 156, height: 156 }, { look: null, round: true }]]);
    // The beings' answers are kept; the newcomer is asked again by the next draw.
    expect(await pictures.portrait('strider')).toBe('data:image/png;base64,U1RSSURFUg==');
    expect(await pictures.portrait('knight')).toBeNull();
    expect(await pictures.portrait('newcomer')).toBeNull();
    expect(asked).toEqual(['strider', 'knight', 'teo', 'newcomer', 'newcomer']);
    expect(drawn).toHaveLength(2);
    // A world that draws no things keeps the quiet circle for its beings.
    const bare = await (await historyHost()).recordPictures({
      entry: { worldId: 'w1', entryId: 'e1', authoredVersionId: 'v1' }, credentials: { baseUrl: 'http://api.test' },
      source: { ...source, authoredSociety: { drawnAsPerson, inhabitantOf } },
    });
    expect(await bare.portrait('strider')).toBeNull();
    expect(people.drawn).toEqual(['teo']);
    // A generated town has no saved society: everyone is one of its people.
    const town = await open();
    expect(await town.portrait('marco')).toBe('blob:made-2');
    expect(people.drawn).toEqual(['teo', 'marco']);
    // A face the server did not keep shows from the bytes drawn here, read from nowhere.
    reads.length = 0;
    expect(await town.portrait('ines')).toBe('blob:made-3');
    expect(reads).toEqual([]);
    people.served = false;
  });

  it("draws the open page's own moment next, after the one drawn now and ahead of every draw still waiting, the newest first", async () => {
    urls();
    people.served = true;
    draws.order.length = 0;
    let letThrough: () => void = () => {};
    draws.gate = new Promise((resolve) => { letThrough = resolve; });
    const pictures = await open();
    const moment = (id: string) => ({ moment_id: id, scene: { people: [{}] }, picture: null });
    // Teo's day asks its rows' pictures and Teo's portrait; the first row's is being drawn.
    for (const id of ['d1', 'd2', 'd3']) expect(pictures.momentNow(moment(id))).toBeNull();
    expect(pictures.portraitNow('teo')).toBeNull();
    await vi.waitFor(() => expect(draws.order).toEqual(['d1']));
    // A decision opens over the day and asks its own moment, then another; then one of the day's rows is opened as one.
    expect(pictures.momentNow(moment('n1'), true)).toBeNull();
    expect(pictures.momentNow(moment('n2'), true)).toBeNull();
    expect(pictures.momentNow(moment('d3'), true)).toBeNull();
    letThrough();
    await vi.waitFor(() => expect(draws.order).toHaveLength(6));
    // The one drawn then is not stopped; the newest lead goes first; the portrait keeps its place among those waiting.
    expect(draws.order).toEqual(['d1', 'd3', 'n2', 'n1', 'd2', 'portrait teo']);
    // Each is drawn once, and shown.
    await vi.waitFor(() => expect(pictures.momentNow(moment('n1'), true)).toMatch(/^blob:made-/));
    expect(draws.order).toHaveLength(6);
    people.served = false;
  });

  it("draws a day's rows newest first, a row that comes on top ahead of the older ones still waiting, never ahead of a lead", async () => {
    urls();
    people.served = true;
    let letThrough: () => void = () => {};
    draws.gate = new Promise((resolve) => { letThrough = resolve; });
    const pictures = await open();
    const row = (id: string, tick: number) => ({ moment_id: id, tick, scene: { people: [{}] }, picture: null });
    // Teo's day, newest row first, and Teo's portrait; the newest row's picture is being drawn.
    for (const [id, tick] of [['r30', 30], ['r20', 20], ['r10', 10]] as const) expect(pictures.momentNow(row(id, tick))).toBeNull();
    expect(pictures.portraitNow('teo')).toBeNull();
    await vi.waitFor(() => expect(draws.order).toEqual(['r30']));
    // The world plays on with the day open: a row comes on top, a decision is opened, another row comes on top, the
    // oldest row is opened as a decision, and one more row comes on top.
    pictures.momentNow(row('r40', 40));
    pictures.momentNow(row('n', 45), true);
    pictures.momentNow(row('r50', 50));
    pictures.momentNow(row('r10', 10), true);
    pictures.momentNow(row('r60', 60));
    letThrough();
    await vi.waitFor(() => expect(draws.order).toHaveLength(8));
    // The leads first, newest lead first; then the rows newest first, whenever they came; the portrait keeps its place.
    expect(draws.order).toEqual(['r30', 'r10', 'n', 'r60', 'r50', 'r40', 'r20', 'portrait teo']);
    people.served = false;
  });
});

describe("the talking scene's top line (T9)", () => {
  // Ines met Teo, then Teo left: the conversation's moment and the going on from it.
  const TALK = [
    { moment_id: 't1', request_id: 'q1', subjects: ['ines', 'teo'], kind: 'met', tick: 5, said: [] },
    { moment_id: 't2', request_id: 'q2', subjects: ['teo'], kind: 'left', tick: 9, said: [] },
  ];
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
  const momentReads = (read: { mock: { calls: unknown[][] } }) => read.mock.calls.filter(([path]) => String(path).includes('/history/moments')).length;

  it('titles the conversation and the going on from it once read, again on a new line, never twice within its wait', async () => {
    const { recordStates, SCENE_MOMENTS } = await recordHost();
    let now = 1000;
    vi.spyOn(performance, 'now').mockImplementation(() => now);
    const read = vi.fn(async (path: string) => (path.includes('/history/moments') ? { moments: TALK } : { things: [] }));
    const records = recordStates(host({ read }).host);
    // Left out until the moments read serves it (the sheet's section 2).
    expect(records.told('teo', 'ines', 'Morning, Ines.')).toEqual([]);
    await settle();
    expect(read).toHaveBeenCalledWith(`/world/versions/v1/history/moments?world_id=w1&limit=${SCENE_MOMENTS.limit}`);
    expect(records.told('teo', 'ines', 'Morning, Ines.')).toEqual(['Ines met Teo', 'Teo left']);
    await settle();
    expect(momentReads(read)).toBe(1);
    now += SCENE_MOMENTS.againMs - 1;
    records.told('teo', 'ines', 'Morning, Ines.');
    await settle();
    expect(momentReads(read)).toBe(1);
    // A new line said reads again at once; the same line, once the wait is over.
    records.told('teo', 'ines', 'Calm water today.');
    await settle();
    expect(momentReads(read)).toBe(2);
    now += SCENE_MOMENTS.againMs;
    records.told('teo', 'ines', 'Calm water today.');
    await settle();
    expect(momentReads(read)).toBe(3);
  });

  it('holds back after a failed read as the page does, and keeps no read made for another conversation', async () => {
    const { recordStates } = await recordHost();
    let now = 1000;
    vi.spyOn(performance, 'now').mockImplementation(() => now);
    const failing = vi.fn(async (path: string) => { if (path.includes('/history/moments')) throw new Error('unreachable'); return { things: [] }; });
    const records = recordStates(host({ read: failing }).host);
    records.told('teo', 'ines', 'a');
    await settle();
    records.told('teo', 'ines', 'b');
    await settle();
    expect(momentReads(failing)).toBe(1);
    now += 1000;
    records.told('teo', 'ines', 'b');
    await settle();
    expect(momentReads(failing)).toBe(2);

    // Teo spoke up to everyone near: a line that would title Teo's talk with anyone, so a kept read would show.
    let release: () => void = () => {};
    const held = vi.fn((path: string) => (path.includes('/history/moments')
      ? new Promise((resolve) => { release = () => resolve({ moments: [{ moment_id: 's', subjects: ['teo'], kind: 'spoke_to_all', tick: 3, said: [] }] }); })
      : Promise.resolve({ things: [] })));
    const switching = recordStates(host({ read: held }).host);
    switching.told('teo', 'ines', 'a');
    expect(switching.told('teo', 'marco', 'b')).toEqual([]);
    release();
    await settle();
    expect(switching.told('teo', 'marco', 'b')).toEqual([]);
    expect(switching.told('teo', 'ines', 'a')).toEqual([]);
  });
});
