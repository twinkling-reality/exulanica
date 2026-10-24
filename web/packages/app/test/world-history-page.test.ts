// @vitest-environment happy-dom
// History as r23 (tools/previews/world-workspace/history.ts): what the page reads and says, and what its keys do.
// It only reads (GET through the workspace's reader, every read scoped to the world); a project it could not read is
// never called unkept; Enter opens a moment on the same page and Esc goes back to the story; the pictures it makes
// stop when it closes; Esc from the story gives the world its keys back.
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';

interface Picture { readonly sha256: string; readonly width: number; readonly height: number }
interface HistoryHost {
  readonly root: HTMLElement;
  readonly worldId: string;
  readonly versionId: string;
  readonly title: string;
  read(path: string): Promise<unknown>;
  names(named: { readonly subjects: readonly string[]; readonly placed: readonly string[] }): Promise<{ subject(id: string): string; placed(id: string): string }>;
  readonly kindLabels: { label(kind: unknown): string | null; listen(listener: () => void): () => void };
  worldClock?(tick: number): { readonly hhmm: string; readonly day: number } | null;
  worldNow?(): number | null;
  readonly entryPicture?: string | null;
  pictureAddress?(picture: Picture, signal: AbortSignal): Promise<string | null>;
  renderMomentPicture?(moment: Record<string, unknown>, signal: AbortSignal): Promise<Picture | null>;
  portrait?(subjectId: string, signal: AbortSignal): Promise<string | null>;
  openDecision?(decision: { readonly momentId: string; readonly requestId: string | null; readonly tick: number; readonly subject: string | null }): void;
  readonly write?: ((method: 'POST' | 'DELETE', path: string, body?: unknown) => Promise<{ readonly status: number; readonly body: unknown }>) | null;
  open(url: string): void;
  closed(): void;
}
interface History { open(): Promise<void>; close(): void; dispose(): void; key(event: KeyboardEvent): boolean; readonly isOpen: boolean }
// A joined path: the test runner still finds the file, and the type checker leaves the preview
// module (outside this package) out of the program.
const module = async (): Promise<{ mountHistory(host: HistoryHost): History }> =>
  import('../../../../tools/previews/world-workspace/' + 'history.ts') as Promise<{ mountHistory(host: HistoryHost): History }>;

// The recipe History draws a moment's picture by, as the preview reads it: its moments read asks by it.
const recipe = async (): Promise<string> =>
  ((await import('../../../../tools/previews/world-workspace/' + 'moment-framing.mjs')) as { MOMENT_FRAMING: { recipe: string } }).MOMENT_FRAMING.recipe;

const WORLD = 'world:generated:0b0e0c1d-0000-4000-8000-000000000001';
const VERSION = '3c4d5e6f-0000-4000-8000-000000000002';
const at = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
const model = (name: string) => ({ kind: 'model', model: { provider: 'nebius', model_id: name, name } });
const person = { kind: 'person', model: null };

/** The moments read as JOURNEY's R1 serves it: a meeting asked again of two models, and an exchange of three lines. */
function moments() {
  return {
    profile: 'exulanica.world-history-moments/v1', version_id: VERSION, now: { tick: 435 }, more: false,
    moments: [
      { moment_id: 'm1', tick: 412, at: at(40), session_id: 's1', kind: 'met', subjects: ['teo', 'ines'], place: { placed_id: 'p1', thing_id: 'bench:1' },
        target: null, with: null, said: [{ tick: 412, by: 'teo', to: ['ines'], line: 'Morning, Ines.', decider: model('Nemotron 3 Nano 30B') }],
        decider: model('Nemotron 3 Nano 30B'), scene: {}, picture: null,
        // Another model would have gone to a placed thing's use: named as build mode names that placed thing.
        branches: [{ ask_id: 'a1', asked_at: at(20), by: 'teo', model: { name: 'Qwen3 235B' }, same_choice: false, kind: 'went', target: { target_id: `authored:${VERSION}:market:1:shop`, activity: null }, with: null, said: null, scene: null, picture: null }] },
      { moment_id: 'm2', tick: 429, at: at(30), session_id: 's1', kind: 'spoke', subjects: ['marco', 'teo'], place: null, target: null, with: null,
        said: [
          { tick: 429, by: 'marco', to: ['teo'], line: 'Did they bring in anything good?', decider: person },
          { tick: 430, by: 'teo', to: ['marco'], line: 'Sardines, mostly.', decider: model('Nemotron 3 Nano 30B'), request_id: 'r430' },
          { tick: 431, by: 'marco', to: ['teo'], line: 'Any for the hotel?', decider: person },
        ],
        decider: person, scene: {}, picture: { sha256: 'f'.repeat(64), width: 600, height: 340 },
        branches: [{ ask_id: 'a2', asked_at: at(10), model: { name: 'Qwen3 235B' }, same_choice: true, kind: 'spoke', target: null, with: null, said: null, scene: null, picture: null }] },
    ],
  };
}

function reads(overrides: Record<string, unknown> = {}) {
  const answers: Record<string, unknown> = {
    [`/world/versions/${VERSION}`]: { version_id: VERSION, world_id: WORLD, things: [{ thing_id: 'bench:1', kind: { kind: 'bench' } }, { thing_id: 'market:1', kind: { kind: 'market' } }],
      edits: [{ edit_id: 'e1', kind: 'move_thing', thing_id: 'bench:1', recorded_at: at(50) }] },
    [`/world/versions/${VERSION}/parts`]: { parts: [] },
    [`/world/versions/${VERSION}/society/control/sessions`]: { sessions: [{ session_id: 's1' }] },
    [`/world/versions/${VERSION}/society/control/sessions/s1`]: { session_id: 's1', opened: { start_tick: 360 }, closed: { end_tick: 435, reason: 'stopped_by_person', words: 'The run was stopped.' }, used: { usd: '0.0042' } },
    [`/world/versions/${VERSION}/society/models/history`]: { choices: [] },
    [`/world/versions/${VERSION}/things/characters/history`]: { records: [] },
    [`/world/versions/${VERSION}/history/moments`]: moments(),
    // A world made from words began as its owner's draft, read by the draft's own id; it keeps the sentence (R4).
    '/worlds/drafts/0b0e0c1d-0000-4000-8000-000000000001': { started_at: at(90), description: 'Glass terraces above the sea' },
    '/world/github-projects': { projects: [{ version_id: VERSION, link: { repository: 'learner/terraces-on-the-bay', publish: 'automatic' },
      github: { reached: true, visibility: 'PRIVATE', not_sent: 0, pull_request: { number: 3, title: 'Moved the bench' }, paused: null } }] },
    ...overrides,
  };
  const asked: string[] = [];
  const read = vi.fn(async (path: string) => {
    asked.push(path);
    const [route, query] = path.split('?');
    const scoped = `world_id=${encodeURIComponent(WORLD)}`;
    // The moments read asks for the line's story alone (H18) and names the recipe each moment's kept picture is asked by.
    const asks = route!.endsWith('/history/moments') ? `${scoped}&story=true&recipe=${encodeURIComponent(await recipe())}` : scoped;
    if (route!.startsWith('/world/') && query !== asks) throw Error('unscoped');
    const answer = answers[route!];
    if (answer === undefined || answer instanceof Error) throw answer ?? Error('404');
    return answer;
  });
  return { read, asked };
}

/** A made kind's labels as build-words' createKindLabels gives them: none until one lands. */
function kindLabels() {
  const known = new Map<string, string>(), listeners = new Set<() => void>();
  return {
    label: (kind: unknown) => known.get((kind as { sha256?: string })?.sha256 ?? '') ?? null,
    listen: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    land(sha256: string, label: string) { known.set(sha256, label); for (const listener of listeners) listener(); },
    listening: () => listeners.size,
  };
}

const NAMES: Record<string, string> = { teo: 'Teo', ines: 'Ines', marco: 'Marco' };

function host(read: HistoryHost['read'], extra: Partial<HistoryHost> = {}, labels = kindLabels()) {
  const root = document.createElement('div');
  // The page lays itself out for the window it is in: r23's own 1920 by 1080.
  Object.defineProperty(root, 'clientWidth', { value: 1920 });
  Object.defineProperty(root, 'clientHeight', { value: 1080 });
  document.body.append(root);
  return {
    root, worldId: WORLD, versionId: VERSION, title: 'Terraces on the bay', read, kindLabels: labels,
    names: vi.fn(async () => ({ subject: (id: string) => NAMES[id] ?? 'the resident', placed: () => 'the resident' })),
    worldClock: (tick: number) => ({ hhmm: `${String(Math.floor(tick / 60) % 24).padStart(2, '0')}:${String(tick % 60).padStart(2, '0')}`, day: 1 }),
    pictureAddress: async (picture: Picture) => `/world/pictures/${picture.sha256}?world_id=${encodeURIComponent(WORLD)}`,
    open: vi.fn(), closed: vi.fn(), openDecision: vi.fn(),
    ...extra,
  };
}

const press = (code: string, extra: KeyboardEventInit = {}) => new KeyboardEvent('keydown', { code, key: code, cancelable: true, ...extra });
const all = (root: HTMLElement, selector: string) => [...root.querySelectorAll(selector)].map((node) => node.textContent);
const chosen = (root: HTMLElement) => root.querySelector('.wu-hr-card[aria-current="true"] .wu-hr-words')?.textContent;
const keys = (root: HTMLElement) => all(root, '.wu-hr-key');

afterEach(() => { document.body.replaceChildren(); });

describe('History', () => {
  it('reads the world, its moments and its project, scoped to the world, and tells the story in its words', async () => {
    const { read, asked } = reads();
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    expect(made.root.querySelector('[role="dialog"]')?.getAttribute('aria-label')).toBe('History');
    // It opens with the focus on its title, so a reader announces it (L18).
    expect(document.activeElement?.textContent).toBe('Terraces on the bay');
    expect(asked.filter((path) => path.startsWith('/world/')).every((path) => path.includes(`?world_id=${encodeURIComponent(WORLD)}`))).toBe(true);
    expect(asked).toContain(`/world/versions/${VERSION}/history/moments?world_id=${encodeURIComponent(WORLD)}&story=true&recipe=${encodeURIComponent(await recipe())}`);
    // Only the characters the moments name are asked for, to be named as the tag and card name them (J20).
    expect(made.names).toHaveBeenCalledWith({ subjects: ['teo', 'ines', 'marco'], placed: [] });
    expect(made.root.querySelector('.wu-hr-kept')?.textContent).toBe('Kept on GitHub in terraces-on-the-bay, private · up to date');
    expect(all(made.root, '.wu-hr-card .wu-hr-words')).toEqual(['Made from your words', 'Teo spoke to Ines at the bench', 'Marco asked Teo']);
    // The creation quotes the sentence the world was made from; a change is the person's, in History's "You" form.
    expect(made.root.querySelector('.wu-hr-card.first .wu-hr-said')?.textContent).toBe('“Glass terraces above the sea”');
    expect(all(made.root, '.wu-hr-change-words')).toEqual(['You moved the bench']);
    // An exchange shows its first two lines and counts the rest; who decided, a same answer on its own small line.
    const exchange = made.root.querySelector('.wu-hr-card[aria-current="true"]') as HTMLElement;
    expect(all(exchange, '.wu-hr-said')).toEqual(['Marco: “Did they bring in anything good?”', 'Teo: “Sardines, mostly.”']);
    expect(all(exchange, '.wu-hr-more')).toEqual(['1 more line']);
    expect(all(exchange, '.wu-hr-who')).toEqual(['By a person playing', 'Qwen3 235B chose the same']);
    // A different answer hangs as a branch; a model's name never breaks.
    expect(all(made.root, '.wu-hr-ghost .wu-hr-text > div')).toEqual(['Asked again with Qwen3 235B', 'Teo would have gone to the market']);
    expect(all(made.root, '.wu-hr-model')).toEqual(['Nemotron 3 Nano 30B', 'Qwen3 235B', 'Qwen3 235B']);
    expect(made.root.querySelector('.wu-hr-run')?.textContent).toBe("Teo's model was deciding · 06:00 to 07:15 · spent $0.0042");
    expect(made.root.querySelector('.wu-hr-now')?.textContent).toBe('Now07:15 · Day 1');
    // A kept picture is read at its address; a missing one is the quiet tile, no words in it.
    await vi.waitFor(() => expect(made.root.querySelector('.wu-hr-card[aria-current="true"] .wu-hr-pic img')?.getAttribute('src')).toBe(`/world/pictures/${'f'.repeat(64)}?world_id=${encodeURIComponent(WORLD)}`));
    expect(made.root.querySelector('.wu-hr-card:not(.first):not([aria-current]) .wu-hr-pic img')).toBeNull();
    expect(keys(made.root)).toEqual(['←→Earlier, later', 'EnterOpen this moment', 'GOpen on GitHub', 'EscBack']);
    history.key(press('KeyG'));
    expect(made.open).toHaveBeenCalledWith('https://github.com/learner/terraces-on-the-bay/pull/3');
    expect(read.mock.calls.every(([path]) => typeof path === 'string')).toBe(true);
  });

  it('moves the choice with the arrows and opens a moment on the same page, every line and every answer in it', async () => {
    const { read } = reads();
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    expect(chosen(made.root)).toBe('Marco asked Teo');
    history.key(press('ArrowLeft'));
    expect(chosen(made.root)).toBe('Teo spoke to Ines at the bench');
    // Every change is a stop (GH3); a single change says itself whole on the line, so Enter opens nothing there.
    history.key(press('ArrowLeft'));
    const [moved] = all(made.root, '.wu-hr-change .wu-hr-change-words');
    expect([chosen(made.root), made.root.querySelector('.wu-hr-change[aria-current="true"] .wu-hr-change-words')?.textContent]).toEqual([undefined, moved]);
    expect(keys(made.root)).toEqual(['←→Earlier, later', 'GOpen on GitHub', 'EscBack']);
    history.key(press('Enter'));
    expect(made.root.querySelector('.wu-hr-moment')).toBeNull();
    history.key(press('ArrowLeft'));
    expect(made.root.querySelector('.wu-hr-change[aria-current="true"] .wu-hr-change-words')?.textContent).toBe(moved);
    history.key(press('ArrowRight'));
    history.key(press('ArrowRight'));
    history.key(press('Enter'));
    const opened = made.root.querySelector('.wu-hr-moment') as HTMLElement;
    expect(made.root.querySelector('.wu-history-r23')?.classList.contains('wu-hr-opened')).toBe(true);
    expect(opened.querySelector('.wu-hr-moment-title')?.textContent).toBe('Marco asked Teo');
    expect([...opened.querySelectorAll('.wu-hr-line')].map((line) => [line.querySelector('.wu-hr-speaker')?.textContent, line.querySelector('.wu-hr-line-said')?.textContent, line.querySelector('.wu-hr-who')?.textContent])).toEqual([
      ['Marco', '“Did they bring in anything good?”', 'By a person playing'],
      ['Teo', '“Sardines, mostly.”', 'By Nemotron 3 Nano 30B'],
      ['Marco', '“Any for the hotel?”', 'By a person playing'],
    ]);
    expect(all(opened, '.wu-hr-answer')).toEqual(['Qwen3 235B chose the same']);
    // The run's small print, and why it ended where it did not end at its own time (H3).
    expect(opened.querySelector('.wu-hr-small')?.textContent).toBe("Teo's model was deciding · 06:00 to 07:15The run was stopped.");
    expect(keys(made.root)).toEqual(['↑↓Choose a line', 'EnterSee the decision', 'EscBack to the story']);
    // The arrows choose a line; Enter sees that line's decision.
    history.key(press('ArrowDown'));
    expect(made.root.querySelector('.wu-hr-line[aria-current="true"] .wu-hr-speaker')?.textContent).toBe('Teo');
    history.key(press('Enter'));
    expect(made.openDecision).toHaveBeenCalledWith({ momentId: 'm2', requestId: 'r430', tick: 430, subject: 'teo' });
    // Esc goes back to the story with the same moment chosen; Esc again closes the page.
    history.key(press('Escape'));
    expect(made.root.querySelector('.wu-hr-moment')).toBeNull();
    expect(history.isOpen).toBe(true);
    expect(chosen(made.root)).toBe('Marco asked Teo');
  });

  it('says a thing turned where it stood as turned, and its undo as turned back (W12.7)', async () => {
    const { read } = reads({
      [`/world/versions/${VERSION}`]: { version_id: VERSION, world_id: WORLD, things: [{ thing_id: 'bench:1', kind: { kind: 'bench' } }],
        edits: [
          // The version read states turned_in_place on a move that kept the bench's place and changed its facing.
          { edit_id: 'e1', kind: 'move_thing', thing_id: 'bench:1', turned_in_place: true, recorded_at: at(50) },
          { edit_id: 'e2', kind: 'undo', undone_edit_id: 'e1', recorded_at: at(48) },
          { edit_id: 'e3', kind: 'move_thing', thing_id: 'bench:1', recorded_at: at(46) },
        ] },
    });
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    for (let step = 0; step < 3; step += 1) history.key(press('ArrowLeft'));
    history.key(press('Enter'));
    const list = made.root.querySelector('.wu-hr-changes') as HTMLElement;
    expect(all(list, '.wu-hr-row-words')).toEqual(['You turned the bench', 'You turned the bench back', 'You moved the bench']);
  });

  it('stops the arrows on a grouped changes dot and opens every change on the same page, oldest first (H15)', async () => {
    const { read } = reads({
      [`/world/versions/${VERSION}`]: { version_id: VERSION, world_id: WORLD, things: [{ thing_id: 'bench:1', kind: { kind: 'bench' } }, { thing_id: 'market:1', kind: { kind: 'market' } }],
        edits: [
          { edit_id: 'e1', kind: 'move_thing', thing_id: 'bench:1', recorded_at: at(50) },
          { edit_id: 'e2', kind: 'remove_thing', thing_id: 'market:1', recorded_at: at(48) },
          { edit_id: 'e3', kind: 'undo', undone_edit_id: 'e1', recorded_at: at(46) },
        ] },
    });
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    const group = () => made.root.querySelector('.wu-hr-change') as HTMLElement;
    // From the newest moment, back past the first moment to the grouped dot, the first stop; no moment is chosen there.
    history.key(press('ArrowLeft'));
    history.key(press('ArrowLeft'));
    history.key(press('ArrowLeft'));
    expect(group().getAttribute('aria-current')).toBe('true');
    expect(made.root.querySelectorAll('.wu-hr-path .ring')).toHaveLength(1);
    expect(chosen(made.root)).toBeUndefined();
    expect(group().querySelector('.wu-hr-change-words')?.textContent).toBe('You made 3 changes');
    expect(keys(made.root)).toEqual(['←→Earlier, later', 'EnterOpen these changes', 'GOpen on GitHub', 'EscBack']);
    history.key(press('Enter'));
    expect(made.root.querySelector('.wu-history-r23')?.classList.contains('wu-hr-opened')).toBe(true);
    const list = made.root.querySelector('.wu-hr-changes') as HTMLElement;
    expect(list.querySelector('.wu-hr-moment-title')?.textContent).toBe('You made 3 changes');
    expect(list.querySelector('.wu-hr-column > .wu-hr-time')?.textContent).toContain(' to ');
    // Each change its own time and You sentence; an undo says what it did, never that a change was undone.
    expect(all(list, '.wu-hr-row-words')).toEqual(['You moved the bench', 'You took out the market', 'You put the bench back where it was']);
    expect(all(list, '.wu-hr-row > .wu-hr-time').every((time) => /\d\d:\d\d$/.test(time ?? ''))).toBe(true);
    // Nothing runs past the column here, so no arrows; Esc goes back to the story with the same dot chosen.
    expect(keys(made.root)).toEqual(['EscBack to the story']);
    history.key(press('Escape'));
    expect(made.root.querySelector('.wu-hr-changes')).toBeNull();
    expect(history.isOpen).toBe(true);
    expect(group().getAttribute('aria-current')).toBe('true');
    // A click on the dot's words opens it as Enter does.
    history.key(press('ArrowRight'));
    expect(group().hasAttribute('aria-current')).toBe(false);
    group().click();
    expect(all(made.root, '.wu-hr-changes .wu-hr-row-words')).toHaveLength(3);
  });

  it("keeps to one line the words of a branch that would reach the band over the key row's caps (H15)", async () => {
    // Laid out as a short page would lay it out: the branch's box ends at 1000, within 85 of the page's 1080 foot;
    // the cards end well above it.
    const tall = vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('wu-hr-ghost') ? 200 : this.classList.contains('wu-hr-card') ? 300 : 0;
    });
    const top = vi.spyOn(HTMLElement.prototype, 'offsetTop', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('wu-hr-ghost') ? 800 : this.classList.contains('wu-hr-card') ? 390 : 0;
    });
    try {
      const { read } = reads();
      const made = host(read);
      await (await module()).mountHistory(made).open();
      expect(made.root.querySelectorAll('.wu-hr-ghost')).toHaveLength(1);
      expect(made.root.querySelector('.wu-hr-ghost')?.classList.contains('wu-hr-clamped')).toBe(true);
      expect(made.root.querySelectorAll('.wu-hr-card.wu-hr-clamped')).toHaveLength(0);
    } finally {
      tall.mockRestore();
      top.mockRestore();
    }
  });

  it("draws a run's bracket over the part of it in view at 1440, with no leg where the window's edge cuts it (H16)", async () => {
    // The run goes on: two more moments after Marco asked Teo, so at 1440 the story does not fit and a view cuts it.
    const longer = moments();
    for (const [id, minutes] of [['m3', 20], ['m4', 10]] as const) {
      longer.moments.push({ ...longer.moments[0]!, moment_id: id, tick: 432, at: at(minutes), kind: 'left', subjects: ['ines'], place: null, said: [], branches: [] } as never);
    }
    const { read } = reads({ [`/world/versions/${VERSION}/history/moments`]: longer });
    const narrow = document.createElement('div');
    Object.defineProperty(narrow, 'clientWidth', { value: 1440 });
    Object.defineProperty(narrow, 'clientHeight', { value: 900 });
    document.body.append(narrow);
    const made = host(read, { root: narrow });
    const history = (await module()).mountHistory(made);
    await history.open();
    const bracket = () => [...made.root.querySelectorAll('.wu-hr-path .bracket')].map((path) => path.getAttribute('d'));
    const words = () => made.root.querySelector<HTMLElement>('.wu-hr-run');
    const slide = () => made.root.querySelector<HTMLElement>('.wu-hr-track')!.style.transform;
    // The newest end: the run began before the view, so its bracket starts at the window's left edge with no leg, and
    // its words stand whole at the page's margin (80 at 1440) above it.
    expect(slide()).toBe('translateX(-796px)');
    expect(bracket()).toEqual(['M 796 254 L 1856 254 L 1856 262']);
    expect([words()?.textContent, Number.parseFloat(words()!.style.left) - 796]).toEqual(["Teo's and Ines's models were deciding · 06:00 to 07:15 · spent $0.0042", 80]);
    // Back at the start: the run goes on past the right edge, so the bracket runs to it with no leg there; its words
    // over its first dot.
    for (let step = 0; step < 4; step += 1) history.key(press('ArrowLeft'));
    expect(slide()).toBe('translateX(0px)');
    expect(bracket()).toEqual(['M 516 262 L 516 254 L 1440 254']);
    expect(words()?.style.left).toBe('516px');
  });

  it('reads the moments before the oldest it holds on demand, when [←] passes it and the read says more lie before', async () => {
    const { read } = reads({ [`/world/versions/${VERSION}/history/moments`]: { ...moments(), more: true } });
    // The page before: one older moment, and the oldest held again (the read is asked from that minute, inclusive).
    const left = { moment_id: 'm0', tick: 400, at: at(45), session_id: 's1', kind: 'left', subjects: ['ines'], place: null, target: null, with: null,
      said: [], decider: model('Nemotron 3 Nano 30B'), scene: {}, picture: { sha256: 'e'.repeat(64), width: 600, height: 340 }, branches: [] };
    const before: string[] = [];
    const paging = vi.fn(async (path: string) => {
      if (!path.includes('&before=')) return read(path);
      before.push(path);
      return { moments: [left, moments().moments[0]], more: false };
    });
    const addresses: string[] = [];
    const made = host(paging, { pictureAddress: async (picture: Picture) => { addresses.push(picture.sha256); return `/pictures/${picture.sha256}`; } });
    const history = (await module()).mountHistory(made);
    await history.open();
    history.key(press('ArrowLeft'));
    expect(chosen(made.root)).toBe('Teo spoke to Ines at the bench');
    // While more lie before it, the line breaks before the oldest moment held: two short slanted strokes (H17).
    expect(made.root.querySelectorAll('.wu-hr-path .break')).toHaveLength(2);
    // At the oldest moment held, with more before it: the earlier page is read, and the choice moves on to it.
    history.key(press('ArrowLeft'));
    await vi.waitFor(() => expect(chosen(made.root)).toBe('Ines left'));
    expect(before).toEqual([`/world/versions/${VERSION}/history/moments?world_id=${encodeURIComponent(WORLD)}&story=true&recipe=${encodeURIComponent(await recipe())}&before=413&limit=51`]);
    // Each moment once, oldest first; with no more before, [←] reads nothing further.
    expect(all(made.root, '.wu-hr-card .wu-hr-words').filter((words) => words !== 'Made from your words')).toEqual(['Ines left', 'Teo spoke to Ines at the bench', 'Marco asked Teo']);
    // Nothing more lies before: the break goes.
    expect(made.root.querySelector('.wu-hr-path .break')).toBeNull();
    // Its picture is made as the others were: read at its address once.
    await vi.waitFor(() => expect(addresses).toContain('e'.repeat(64)));
    // With nothing more before, [←] reads nothing further and goes on to the change before the oldest moment (GH3).
    history.key(press('ArrowLeft'));
    expect(before).toHaveLength(1);
    expect(made.root.querySelector('.wu-hr-change[aria-current="true"] .wu-hr-change-words')?.textContent).toBe(all(made.root, '.wu-hr-change .wu-hr-change-words')[0]);
  });

  it('shows the creation and Now alone with nothing yet, and no arrows with nothing to move to', async () => {
    const { read } = reads({
      [`/world/versions/${VERSION}`]: { version_id: VERSION, world_id: WORLD, things: [], edits: [] },
      [`/world/versions/${VERSION}/history/moments`]: { now: null, moments: [], more: false },
    });
    const made = host(read);
    await (await module()).mountHistory(made).open();
    expect(made.root.querySelector('.wu-hr-note')?.textContent).toBe('Nothing has happened here yet.');
    expect(made.root.querySelector('.wu-hr-note')?.getAttribute('data-refused')).toBe('false');
    expect(made.root.querySelector('.wu-hr-path .now')).not.toBeNull();
    expect(keys(made.root)).toEqual(['GOpen on GitHub', 'EscBack']);
  });

  it("asks for the line's story alone and, where the town has lived with none of it drawn, says how it fills (H18)", async () => {
    const asked: string[] = [];
    const { read } = reads({
      [`/world/versions/${VERSION}`]: { version_id: VERSION, world_id: WORLD, things: [], edits: [] },
      // The town played 49 minutes; its meetings between people nobody touched are left out of the story read.
      [`/world/versions/${VERSION}/history/moments`]: { now: { tick: 49 }, moments: [], more: false },
    });
    const made = host(async (path: string) => { asked.push(path); return read(path); });
    await (await module()).mountHistory(made).open();
    expect(asked.filter((path) => path.includes('/history/moments')).every((path) => path.includes('&story=true'))).toBe(true);
    expect(made.root.querySelector('.wu-hr-note')?.textContent).toBe('When you change this world or give someone an AI model, it shows here.');
    expect(made.root.querySelector('.wu-hr-note')?.getAttribute('data-refused')).toBe('false');
  });

  it('says the moments could not be read in the refusal ink, keeps the rest of the page and Now on the live clock', async () => {
    const { read } = reads({ [`/world/versions/${VERSION}/history/moments`]: new Error('503') });
    const made = host(read, { worldNow: () => 440 });
    await (await module()).mountHistory(made).open();
    const note = made.root.querySelector('.wu-hr-note');
    expect([note?.textContent, note?.getAttribute('data-refused')]).toEqual(["The world's moments could not be read. Try again.", 'true']);
    expect(all(made.root, '.wu-hr-change-words')).toEqual(['You moved the bench']);
    expect(made.root.querySelector('.wu-hr-now')?.textContent).toBe('Now07:20 · Day 1');
  });

  it('says nothing of a project it could not read, never that the world is not kept', async () => {
    const { read } = reads({ '/world/github-projects': new Error('403') });
    const made = host(read);
    await (await module()).mountHistory(made).open();
    expect(made.root.querySelector('.wu-hr-kept')?.textContent).toBe('');
    const { read: none } = reads({ '/world/github-projects': { projects: [] } });
    const second = host(none);
    await (await module()).mountHistory(second).open();
    expect(second.root.querySelector('.wu-hr-kept')?.textContent).toBe('Not kept in a project');
    expect(keys(second.root)).not.toContain('GOpen on GitHub');
  });

  it('keeps a world in a project with K, asking nothing first, and offers it nowhere it could only fail', async () => {
    const { read } = reads({ '/world/github-projects': { projects: [], requests: [], publications: [] } });
    const write = vi.fn(async () => ({ status: 202, body: { request_id: 'k1', version_id: VERSION, refused: null } }));
    const made = host(read, { write });
    const history = (await module()).mountHistory(made);
    await history.open();
    expect(keys(made.root)).toContain('KKeep in a project');
    expect(history.key(press('KeyK'))).toBe(true);
    await vi.waitFor(() => expect(made.root.querySelector('.wu-hr-kept')?.textContent).toBe('Starting a project…'));
    expect(write).toHaveBeenCalledWith('POST', `/world/github-projects?world_id=${encodeURIComponent(WORLD)}`, { version_id: VERSION, readable: false });
    expect(keys(made.root)).not.toContain('KKeep in a project');
    history.close();
    // A read-only copy has no writes: no K.
    const { read: again } = reads({ '/world/github-projects': { projects: [], requests: [], publications: [] } });
    const watching = host(again, { write: null });
    await (await module()).mountHistory(watching).open();
    expect(keys(watching.root)).toEqual(['←→Earlier, later', 'EnterOpen this moment', 'EscBack']);
  });

  it('says a project is starting until it is listed, though the follower took the request first (F13)', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    try {
      const local = { version_id: VERSION, project_id: 'project:demo', link: null, github: null, publications_per_day: 4 };
      // The follower removes the request as it starts the project, and lists the project a scan later.
      let listed: unknown[] = [];
      const { read } = reads({ '/world/github-projects': { get projects() { return listed; }, requests: [], publications: [] } });
      const write = vi.fn(async () => ({ status: 202, body: { request_id: 'k1', version_id: VERSION, refused: null } }));
      const made = host(read, { write });
      const history = (await module()).mountHistory(made);
      await history.open();
      const kept = () => made.root.querySelector('.wu-hr-kept')?.textContent;
      history.key(press('KeyK'));
      await vi.advanceTimersByTimeAsync(0);
      expect(kept()).toBe('Starting a project…');
      // A read with neither the request nor the project: still starting, and read again.
      await vi.advanceTimersByTimeAsync(3_100);
      expect(kept()).toBe('Starting a project…');
      listed = [local];
      await vi.advanceTimersByTimeAsync(3_100);
      expect(kept()).toBe('Kept in a project on this computer, not on GitHub');
      history.close();
      // Where no project is ever listed, the page reads where the world is kept as it stands after two minutes.
      listed = [];
      const again = host(read, { write });
      const second = (await module()).mountHistory(again);
      await second.open();
      second.key(press('KeyK'));
      await vi.advanceTimersByTimeAsync(118_000);
      expect(again.root.querySelector('.wu-hr-kept')?.textContent).toBe('Starting a project…');
      await vi.advanceTimersByTimeAsync(6_100);
      expect(again.root.querySelector('.wu-hr-kept')?.textContent).toBe('Not kept in a project');
      second.close();
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps a run\'s time left and Now true while it is open, reading again only while a run is open', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
    try {
      const running: Record<string, unknown> = { session_id: 's1', opened: { start_tick: 360, ends_by: new Date(Date.now() + 5 * 60_000).toISOString() },
        closed: null, used: { usd: '0.0010' } };
      const { read, asked } = reads({ [`/world/versions/${VERSION}/society/control/sessions/s1`]: running });
      let minute = 435;
      const made = host(read, { worldNow: () => minute });
      const history = (await module()).mountHistory(made);
      await history.open();
      const run = () => made.root.querySelector('.wu-hr-run')?.textContent;
      const now = () => made.root.querySelector('.wu-hr-now')?.textContent;
      expect([run(), now()]).toEqual(["Teo's model is deciding · 06:00 to now · 5:00 left", 'Now07:15 · Day 1']);
      // A minute later the time left and Now have moved with it.
      minute = 436;
      await vi.advanceTimersByTimeAsync(60_000);
      expect([run(), now()]).toEqual(["Teo's model is deciding · 06:00 to now · 4:00 left", 'Now07:16 · Day 1']);
      // The run ends: the next read says so, and once no run is open nothing more is read.
      running['closed'] = { end_tick: 437, reason: 'session_deadline', words: 'The run ended.' };
      await vi.advanceTimersByTimeAsync(10_000);
      expect(run()).toBe("Teo's model was deciding · 06:00 to 07:17 · spent $0.0010");
      const before = asked.length;
      await vi.advanceTimersByTimeAsync(60_000);
      expect(asked.length).toBe(before);
      // Closed, its timers are gone and nothing is read again.
      running['closed'] = null;
      history.close();
      expect(vi.getTimerCount()).toBe(0);
      await vi.advanceTimersByTimeAsync(60_000);
      expect(asked.length).toBe(before);
    } finally {
      vi.useRealTimers();
    }
  });

  it('says a paused project is paused when GitHub no longer answers, never that its changes will be sent (GH6)', async () => {
    const gone = { version_id: VERSION, link: { repository: 'learner/terraces-on-the-bay', publish: 'automatic' },
      github: { reached: false, visibility: 'PRIVATE', not_sent: 0, pull_request: { number: 3, title: 'Moved the bench' }, paused: { at: at(5), reason: 'GitHub refused or failed the request.' } } };
    const made = host(reads({ '/world/github-projects': { projects: [gone] } }).read);
    await (await module()).mountHistory(made).open();
    const kept = made.root.querySelector('.wu-hr-kept');
    expect([kept?.textContent, kept?.getAttribute('data-refused')]).toEqual(['Kept on GitHub in terraces-on-the-bay · sending has stopped. Your changes are kept on this computer.', 'true']);
  });

  it("asks H12's question with G where the project is kept on this computer only, its keys alone in the row", async () => {
    const local = { version_id: VERSION, project_id: 'project:demo', link: null, github: null, publications_per_day: 4 };
    const { read } = reads({ '/world/github-projects': { projects: [local], requests: [], publications: [] } });
    const write = vi.fn(async (method: string) => (method === 'POST'
      ? { status: 202, body: { request_id: 'q1', project_id: 'project:demo', name: null, review: null, refused: null } }
      : { status: 204, body: null }));
    const made = host(read, { write });
    const history = (await module()).mountHistory(made);
    await history.open();
    expect(made.root.querySelector('.wu-hr-kept')?.textContent).toBe('Kept in a project on this computer, not on GitHub');
    expect(keys(made.root)).toContain('GKeep on GitHub');
    history.key(press('KeyG'));
    const card = made.root.querySelector('.wu-hr-keepcard') as HTMLElement;
    expect(card.querySelector('.wu-hr-keep-question')?.textContent).toBe('Keep this world in a new private repository on your GitHub account');
    // Only what works now (GH4): while Create is pale the row offers no Enter.
    expect(keys(made.root)).toEqual(['EscBack']);
    await vi.waitFor(() => expect(write).toHaveBeenCalledWith('POST', `/world/github-projects/publications?world_id=${encodeURIComponent(WORLD)}`, { project_id: 'project:demo', name: null }));
    // Typing a name is the field's own: the page does not take its keys.
    const field = card.querySelector('.wu-hr-keep-field') as HTMLInputElement;
    expect(history.key(Object.defineProperty(press('KeyA'), 'target', { value: field }))).toBe(false);
    // Esc goes back to the story and withdraws the request; the page stays open.
    history.key(press('Escape'));
    expect(made.root.querySelector('.wu-hr-keepcard')).toBeNull();
    expect(history.isOpen).toBe(true);
    await vi.waitFor(() => expect(write).toHaveBeenCalledWith('DELETE', `/world/github-projects/requests/q1?world_id=${encodeURIComponent(WORLD)}`));
    expect(keys(made.root)).toContain('GKeep on GitHub');
  });

  it('reads the sign-in again with Enter or when the page has the focus back, its key row as the card stands (GH4)', async () => {
    const local = { version_id: VERSION, project_id: 'project:demo', link: null, github: null, publications_per_day: 4 };
    let asked = 0;
    const refused = (request_id: string) => ({ request_id, project_id: 'project:demo', name: null, review: null, refused: { code: 'not_signed_in', at: at(0) } });
    const { read } = reads({ '/world/github-projects': { projects: [local], requests: [], get publications() { return [refused(`q${asked}`)]; } } });
    const write = vi.fn(async (method: string) => {
      if (method !== 'POST') return { status: 204, body: null };
      asked += 1;
      return { status: 202, body: { request_id: `q${asked}`, project_id: 'project:demo', name: null, review: null, refused: null } };
    });
    const made = host(read, { write });
    const history = (await module()).mountHistory(made);
    await history.open();
    history.key(press('KeyG'));
    await vi.waitFor(() => expect(keys(made.root)).toEqual(['EnterTry again', 'EscBack']), { timeout: 4000 });
    expect(made.root.querySelector('.wu-hr-keep-status')?.textContent).toBe('Sign in to GitHub on this computer once (gh auth login), then try again.');
    history.key(press('Enter'));
    await vi.waitFor(() => expect(asked).toBe(2));
    await vi.waitFor(() => expect(keys(made.root)).toEqual(['EnterTry again', 'EscBack']), { timeout: 4000 });
    window.dispatchEvent(new Event('focus'));
    await vi.waitFor(() => expect(asked).toBe(3));
    history.key(press('Escape'));
  });

  it('opens at the newest end, a change after the last moment chosen with Now in view, and steps back from it (GH3)', async () => {
    const view = { version_id: VERSION, world_id: WORLD, things: [{ thing_id: 'bench:1', kind: { kind: 'bench' } }, { thing_id: 'market:1', kind: { kind: 'market' } }],
      edits: [{ edit_id: 'e1', kind: 'move_thing', thing_id: 'bench:1', recorded_at: at(50) }, { edit_id: 'e2', kind: 'move_thing', thing_id: 'bench:1', recorded_at: at(5) }] };
    const { read } = reads({ [`/world/versions/${VERSION}`]: view });
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    const newest = all(made.root, '.wu-hr-change .wu-hr-change-words').at(-1);
    expect(made.root.querySelector('.wu-hr-change[aria-current="true"] .wu-hr-change-words')?.textContent).toBe(newest);
    expect(made.root.querySelector('.wu-hr-now')?.textContent).toBe('Now07:15 · Day 1');
    expect(keys(made.root)).toEqual(['←→Earlier, later', 'GOpen on GitHub', 'EscBack']);
    // Among world times a change states no wall clock: none records the world's time it was made (F12b).
    expect(made.root.querySelectorAll('.wu-hr-change .wu-hr-time')).toHaveLength(0);
    history.key(press('ArrowRight'));
    expect(made.root.querySelector('.wu-hr-change[aria-current="true"] .wu-hr-change-words')?.textContent).toBe(newest);
    history.key(press('ArrowLeft'));
    expect(chosen(made.root)).toBe('Marco asked Teo');
    history.key(press('ArrowRight'));
    expect(made.root.querySelector('.wu-hr-now')?.textContent).toBe('Now07:15 · Day 1');
  });

  it('opens at the newest end each time, not where it was left (GH3)', async () => {
    const { read } = reads();
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    history.key(press('ArrowLeft'));
    expect(chosen(made.root)).toBe('Teo spoke to Ines at the bench');
    history.close();
    await history.open();
    expect(chosen(made.root)).toBe('Marco asked Teo');
    expect(made.root.querySelector('.wu-hr-now')?.textContent).toBe('Now07:15 · Day 1');
    history.close();
  });

  it('makes missing pictures and portraits one at a time, and stops making them when it closes', async () => {
    const { read } = reads();
    let release: (value: Picture | null) => void = () => {};
    const signals: AbortSignal[] = [];
    const renderMomentPicture = vi.fn((_moment: Record<string, unknown>, signal: AbortSignal) => {
      signals.push(signal);
      return new Promise<Picture | null>((resolve) => { release = resolve; });
    });
    const portrait = vi.fn(async (subject: string) => `/portraits/${subject}.png`);
    const made = host(read, { renderMomentPicture, portrait });
    const history = (await module()).mountHistory(made);
    await history.open();
    // The exchange has its kept picture: only the meeting's is made, and nothing else waits on it.
    await vi.waitFor(() => expect(renderMomentPicture).toHaveBeenCalledTimes(1));
    expect(renderMomentPicture.mock.calls[0]![0]).toMatchObject({ moment_id: 'm1' });
    await vi.waitFor(() => expect(portrait).toHaveBeenCalledWith('marco', expect.any(AbortSignal)));
    expect([...made.root.querySelectorAll('.wu-hr-card[aria-current="true"] .wu-hr-orb img')].map((image) => image.getAttribute('src'))).toEqual(['/portraits/marco.png', '/portraits/teo.png']);
    history.close();
    expect(signals[0]!.aborted).toBe(true);
    release({ sha256: 'a'.repeat(64), width: 600, height: 340 });
    await Promise.resolve();
    expect(made.root.querySelector('[role="dialog"]')).toBeNull();
    expect(made.closed).toHaveBeenCalledTimes(1);
  });

  it('reads a kept picture in view before it draws a missing one, which takes seconds', async () => {
    const read = moments();
    const kept = { sha256: 'a'.repeat(64), width: 600, height: 340 };
    read.moments = [{ ...read.moments[0]!, picture: kept }, { ...read.moments[1]!, picture: null }] as typeof read.moments;
    const { read: reader } = reads({ [`/world/versions/${VERSION}/history/moments`]: read });
    const renderMomentPicture = vi.fn((_moment: Record<string, unknown>, _signal: AbortSignal) => new Promise<Picture | null>(() => {}));
    const made = host(reader, { renderMomentPicture });
    const history = (await module()).mountHistory(made);
    await history.open();
    // The newest moment is chosen and has no picture: the older one's kept picture is shown while it is drawn.
    await vi.waitFor(() => expect(renderMomentPicture).toHaveBeenCalledTimes(1));
    expect(renderMomentPicture.mock.calls[0]![0]).toMatchObject({ moment_id: 'm2' });
    const pictures = [...made.root.querySelectorAll('.wu-hr-card .wu-hr-pic')].map((box) => box.querySelector('img')?.getAttribute('src') ?? null);
    expect(pictures).toEqual([null, `/world/pictures/${'a'.repeat(64)}?world_id=${encodeURIComponent(WORLD)}`, null]);
    history.close();
  });

  it('draws next the missing picture nearest the moment chosen now, so the arrows move the making with the reader', async () => {
    const read = moments();
    const third = { ...read.moments[1]!, moment_id: 'm3', tick: 433, at: at(20), picture: null, branches: [] };
    read.moments = [read.moments[0]!, { ...read.moments[1]!, picture: null, branches: [] }, third] as typeof read.moments;
    const { read: reader } = reads({ [`/world/versions/${VERSION}/history/moments`]: read });
    const releases: ((picture: Picture | null) => void)[] = [];
    const renderMomentPicture = vi.fn((_moment: Record<string, unknown>, _signal: AbortSignal) => new Promise<Picture | null>((resolve) => { releases.push(resolve); }));
    const made = host(reader, { renderMomentPicture, portrait: async (subject: string) => `/portraits/${subject}.png` });
    const history = (await module()).mountHistory(made);
    await history.open();
    await vi.waitFor(() => expect(renderMomentPicture).toHaveBeenCalledTimes(1));
    expect(renderMomentPicture.mock.calls[0]![0]).toMatchObject({ moment_id: 'm3' });
    // The reader goes back to the oldest moment while the newest is drawn: it is drawn next, not the one between.
    history.key(press('ArrowLeft'));
    history.key(press('ArrowLeft'));
    expect(chosen(made.root)).toBe('Teo spoke to Ines at the bench');
    releases[0]!({ sha256: 'c'.repeat(64), width: 600, height: 340 });
    await vi.waitFor(() => expect(renderMomentPicture).toHaveBeenCalledTimes(2));
    expect(renderMomentPicture.mock.calls[1]![0]).toMatchObject({ moment_id: 'm1' });
    history.close();
  });

  it('draws the cards in view before one as near that the line has slid out of view', async () => {
    const read = moments();
    const exchange = read.moments[1]!;
    // Seven moments a minute apart, none with a picture but the third's, which is kept.
    read.moments = Array.from({ length: 7 }, (_, index) => ({ ...exchange, moment_id: `m${index + 1}`, tick: 412 + index, at: at(40 - index),
      said: [{ ...exchange.said[0]!, line: `Line ${index + 1}` }], branches: [],
      picture: index === 2 ? { sha256: 'b'.repeat(64), width: 600, height: 340 } : null })) as typeof read.moments;
    const { read: reader } = reads({ [`/world/versions/${VERSION}/history/moments`]: read });
    const releases: ((picture: Picture | null) => void)[] = [];
    const renderMomentPicture = vi.fn((_moment: Record<string, unknown>, _signal: AbortSignal) => new Promise<Picture | null>((resolve) => { releases.push(resolve); }));
    const made = host(reader, { renderMomentPicture, portrait: async (subject: string) => `/portraits/${subject}.png` });
    const history = (await module()).mountHistory(made);
    await history.open();
    await vi.waitFor(() => expect(renderMomentPicture).toHaveBeenCalledTimes(1));
    expect(renderMomentPicture.mock.calls[0]![0]).toMatchObject({ moment_id: 'm7' });
    // Back to the third: the line slides so it stands first in view, the two before it out of view.
    for (let press_ = 0; press_ < 4; press_ += 1) history.key(press('ArrowLeft'));
    const shown = () => all(made.root, '.wu-hr-card .wu-hr-said');
    expect(shown().slice(0, 1)).toEqual(['Marco: “Line 3”']);
    const drawn = async (count: number) => {
      releases[count - 1]!({ sha256: String(count).repeat(64), width: 600, height: 340 });
      await vi.waitFor(() => expect(renderMomentPicture).toHaveBeenCalledTimes(count + 1));
      return (renderMomentPicture.mock.calls[count]![0] as { moment_id: string }).moment_id;
    };
    // The fourth and fifth are in view, the second as near as the fifth but out of it.
    expect([await drawn(1), await drawn(2)]).toEqual(['m4', 'm5']);
    history.close();
  });

  it('draws no ring around the title it focuses itself; a ring is only for focus Tab moves', async () => {
    const { read } = reads();
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    const title = made.root.querySelector('.wu-hr-title') as HTMLElement;
    expect([document.activeElement === title, title.tabIndex, title.closest('.wu-record') !== null]).toEqual([true, -1, true]);
    // The test runner loads stylesheets empty, so the rule is read from the file, as the web tests run from web/.
    const css = readFileSync(`${process.cwd()}/../tools/previews/world-workspace/world-ui-record.css`, 'utf8');
    expect(css).toMatch(/\.wu-record \[tabindex="-1"\]:focus \{ outline: none; \}/);
    history.close();
  });

  it('names a range within one day once and keeps each date whole, so it wraps only at "to"', async () => {
    const { personSpan } = await import('../../../../tools/previews/world-workspace/' + 'history-words.mjs') as { personSpan(from: string, to: string, now: Date): string };
    const now = new Date(2026, 9, 16, 12, 0);
    const whole = (words: string) => words.replace(/ /g, '\u00a0');
    expect(personSpan(new Date(2026, 9, 11, 18, 59).toISOString(), new Date(2026, 9, 11, 20, 45).toISOString(), now)).toBe(`${whole('11 October, 18:59')} to 20:45`);
    expect(personSpan(new Date(2026, 9, 11, 23, 50).toISOString(), new Date(2026, 9, 12, 0, 10).toISOString(), now)).toBe(`${whole('11 October at 23:50')} to ${whole('12 October at 00:10')}`);
    expect(personSpan(new Date(2026, 9, 11, 18, 59).toISOString(), new Date(2026, 9, 11, 18, 59).toISOString(), now)).toBe(whole('11 October at 18:59'));
    // The person's own time always names its day, so it never reads as the world's (F12b): today too.
    expect(personSpan(new Date(2026, 9, 16, 8, 17).toISOString(), new Date(2026, 9, 16, 9, 1).toISOString(), now)).toBe(`${whole('Today, 08:17')} to 09:01`);
    expect(personSpan(new Date(2026, 9, 16, 8, 17).toISOString(), new Date(2026, 9, 16, 8, 17).toISOString(), now)).toBe(whole('Today at 08:17'));
    // The day before reads "Yesterday"; an older day names its month whole, never "11 Oct" (DESIGN, "Today at" as built).
    expect(personSpan(new Date(2026, 9, 15, 23, 50).toISOString(), new Date(2026, 9, 15, 23, 50).toISOString(), now)).toBe(whole('Yesterday at 23:50'));
    expect(personSpan(new Date(2026, 9, 15, 18, 59).toISOString(), new Date(2026, 9, 15, 20, 45).toISOString(), now)).toBe(`${whole('Yesterday, 18:59')} to 20:45`);
  });

  it('names a speaker a kind names in its title form, as their tag does', async () => {
    const { read } = reads({ [`/world/versions/${VERSION}/history/moments`]: { ...moments(), moments: [
      { moment_id: 'm7', tick: 420, at: at(20), session_id: 's1', kind: 'spoke', subjects: ['strider', 'teo'], place: null, target: null, with: null,
        said: [{ tick: 420, by: 'strider', to: ['teo'], line: 'Rest in my shade.', decider: person }], decider: person, scene: {}, picture: null, branches: [] },
    ] } });
    const made = host(read, { names: vi.fn(async () => ({ subject: (id: string) => NAMES[id] ?? 'the canopy strider', placed: () => 'the resident', speaker: (id: string) => NAMES[id] ?? 'Canopy strider' })) });
    const history = (await module()).mountHistory(made);
    await history.open();
    expect(made.root.querySelector('.wu-hr-card[aria-current="true"]')?.textContent).toContain('Canopy strider: \u201cRest in my shade.\u201d');
    history.close();
  });

  it('reads kept pictures again after it closes, since the host takes their addresses back as it closes', async () => {
    const { read } = reads();
    let made = 0;
    const pictureAddress = vi.fn(async (picture: Picture) => `blob:picture-${picture.sha256.slice(0, 4)}-${(made += 1)}`);
    const opened = host(read, { pictureAddress });
    const history = (await module()).mountHistory(opened);
    await history.open();
    const shown = () => opened.root.querySelector('.wu-hr-card[aria-current="true"] .wu-hr-pic img')?.getAttribute('src');
    await vi.waitFor(() => expect(shown()).toBe('blob:picture-ffff-1'));
    // Each picture is read once while the page is open, whatever is drawn again.
    history.key(press('ArrowLeft'));
    history.key(press('ArrowRight'));
    expect(pictureAddress).toHaveBeenCalledTimes(1);
    history.close();
    await history.open();
    await vi.waitFor(() => expect(shown()).toBe('blob:picture-ffff-2'));
    expect(pictureAddress).toHaveBeenCalledTimes(2);
    history.close();
  });

  it("names a made creature by its label as build mode does, re-wording when the label lands", async () => {
    const heron = { kind: { source: 'workspace', sha256: 'c'.repeat(64) } };
    const { read } = reads({
      [`/world/versions/${VERSION}`]: { version_id: VERSION, world_id: WORLD, things: [{ thing_id: 'heron:1', ...heron }], edits: [
        { edit_id: 'e1', kind: 'transform_element', element_id: 'part:p1', storeys: { before: 2, after: 3 }, recorded_at: at(80) },
        { edit_id: 'e2', kind: 'add_thing', thing_id: 'heron:1', recorded_at: at(35) },
      ] },
      [`/world/versions/${VERSION}/parts`]: { parts: [{ part_id: 'p1', label: 'terrace cafe' }] },
    });
    const labels = kindLabels();
    const made = host(read, {}, labels);
    const history = (await module()).mountHistory(made);
    await history.open();
    expect(all(made.root, '.wu-hr-change-words')).toEqual(['You raised the terrace cafe to 3 storeys', 'You placed the creature']);
    const asked = read.mock.calls.length;
    labels.land('c'.repeat(64), 'Long necked marsh heron');
    expect(all(made.root, '.wu-hr-change-words')[1]).toBe('You placed the long necked marsh heron');
    expect(read.mock.calls.length).toBe(asked);
    history.close();
    expect(labels.listening()).toBe(0);
  });

  it('leaves Tab to the page and closes on Esc, giving the world its keys back', async () => {
    const { read } = reads();
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    expect(history.key(press('Tab'))).toBe(false);
    // A key the page does not use is taken; a combination it does not use keeps the browser's own.
    const k = press('KeyK');
    expect(history.key(k)).toBe(true);
    expect(k.defaultPrevented).toBe(true);
    const palette = press('KeyK', { metaKey: true });
    expect(history.key(palette)).toBe(false);
    expect(palette.defaultPrevented).toBe(false);
    const escape = press('Escape');
    expect(history.key(escape)).toBe(true);
    expect(history.isOpen).toBe(false);
    expect(made.root.querySelector('[role="dialog"]')).toBeNull();
    expect(made.closed).toHaveBeenCalledTimes(1);
    expect(history.key(press('Escape'))).toBe(false);
  });

  it('goes with its world without giving the world back its keys', async () => {
    const { read } = reads();
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    history.dispose();
    expect(made.root.querySelector('[role="dialog"]')).toBeNull();
    expect(history.isOpen).toBe(false);
    expect(made.closed).not.toHaveBeenCalled();
  });
});
