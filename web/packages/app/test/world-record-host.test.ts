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
  renderMomentPicture: async () => ({ sha256: 'b'.repeat(64), width: 600, height: 340 }),
}));
vi.mock('../../../../tools/previews/world-workspace/portrait-pictures.ts', () => ({
  lookDigest: () => 'd',
  lookOfSubject: (id: string) => ({ id }),
  renderPortrait: async ({ look }: { look: { id: string } }) => { people.drawn.push(look.id); return { sha256: 'c'.repeat(64), width: 156, height: 156 }; },
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
// Teo met Ines and spoke to her under r1; Marco spoke to Teo under r9 (Marco's decision, Teo only spoken to).
const MOMENTS = [
  { moment_id: 'm1', request_id: 'r1', subjects: ['teo', 'ines'], kind: 'met', tick: 412, scene: { people: [{}] }, picture: KEPT, said: [{ by: 'teo', request_id: 'r1', tick: 412, line: 'Morning, Ines.' }] },
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

afterEach(() => { reads.length = 0; vi.restoreAllMocks(); });

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
    expect(records.dayRow(showing, { requestId: 'r1' })).toEqual({ moment: true, title: 'Teo met Ines', said: '“Morning, Ines.”', picture: 'blob:m1' });
    // Marco's moment never titles or pictures a row of Teo's, whatever request the row names.
    expect(records.dayRow(showing, { requestId: 'r9' })).toEqual({});
    expect(records.dayRow(showing, { requestId: null, heard: true })).toEqual({});
    expect(made.pictures.momentNow.mock.calls.map(([moment]) => moment.moment_id)).toEqual(['m1']);
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
      over: '06:52 · Day 1 · Teo met Ines',
      decided: 'Teo spoke to Ines', said: 'Teo: “Morning, Ines.”', action: null,
      decider: 'model', answered: { latencyMs: 900, costUsd: '0.0003', costKnown: true }, choicesHeading: "Teo's choices",
      picture: 'blob:m1', portraits: [{ name: 'Teo', url: 'blob:portrait-teo' }, { name: 'Ines', url: 'blob:portrait-ines' }],
      ground: 'blob:still', earlier: true, later: false, canCompare: false, toldLabel: "What Teo's model was told",
    });
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

  it('keeps one still, replacing the last when a new one is taken, and makes a missing moment picture once', async () => {
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
    pictures.release();
    expect(revoked).toEqual(['blob:made-1', 'blob:made-2', 'blob:made-3']);
    expect(pictures.still()).toBeNull();
  });

  it("draws a face only for one the world draws as one of its people: a creature keeps the quiet circle", async () => {
    urls();
    people.served = true;
    people.drawn.length = 0;
    // The saved world's society: Teo from the people catalog, the canopy strider by its own look, a newcomer not yet known.
    const asked: string[] = [];
    const drawnAsPerson = (id: string) => { asked.push(id); return id === 'teo' ? true : id === 'strider' ? false : null; };
    const pictures = await (await historyHost()).recordPictures({
      entry: { worldId: 'w1', entryId: 'e1', authoredVersionId: 'v1' }, credentials: { baseUrl: 'http://api.test' },
      source: { ...source, authoredSociety: { drawnAsPerson } },
    });
    expect(await pictures.portrait('strider')).toBeNull();
    expect(await pictures.portrait('teo')).toBe('blob:made-1');
    expect(await pictures.portrait('newcomer')).toBeNull();
    expect(people.drawn).toEqual(['teo']);
    // The strider's answer is kept; the newcomer is asked again by the next draw.
    expect(await pictures.portrait('strider')).toBeNull();
    expect(await pictures.portrait('newcomer')).toBeNull();
    expect(asked).toEqual(['strider', 'teo', 'newcomer', 'newcomer']);
    // A generated town has no saved society: everyone is one of its people.
    const town = await open();
    expect(await town.portrait('marco')).toBe('blob:made-2');
    expect(people.drawn).toEqual(['teo', 'marco']);
    people.served = false;
  });
});
