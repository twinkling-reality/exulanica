// @vitest-environment happy-dom
// History as r23 (tools/previews/world-workspace/history.ts): what the page reads and says, and what its keys do.
// It only reads (GET through the workspace's reader, every read scoped to the world); a project it could not read is
// never called unkept; Enter opens a moment on the same page and Esc goes back to the story; the pictures it makes
// stop when it closes; Esc from the story gives the world its keys back.
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
  picture?(picture: Picture): string;
  renderMomentPicture?(moment: Record<string, unknown>, signal: AbortSignal): Promise<Picture | null>;
  portrait?(subjectId: string, signal: AbortSignal): Promise<string | null>;
  openDecision?(decision: { readonly momentId: string; readonly requestId: string | null; readonly tick: number; readonly subject: string | null }): void;
  open(url: string): void;
  closed(): void;
}
interface History { open(): Promise<void>; close(): void; dispose(): void; key(event: KeyboardEvent): boolean; readonly isOpen: boolean }
// A joined path: the test runner still finds the file, and the type checker leaves the preview
// module (outside this package) out of the program.
const module = async (): Promise<{ mountHistory(host: HistoryHost): History }> =>
  import('../../../../tools/previews/world-workspace/' + 'history.ts') as Promise<{ mountHistory(host: HistoryHost): History }>;

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
    if (route!.startsWith('/world/') && query !== `world_id=${encodeURIComponent(WORLD)}`) throw Error('unscoped');
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
    picture: (picture: Picture) => `/world/pictures/${picture.sha256}?world_id=${encodeURIComponent(WORLD)}`,
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
    expect(asked.filter((path) => path.startsWith('/world/')).every((path) => path.endsWith(`?world_id=${encodeURIComponent(WORLD)}`))).toBe(true);
    expect(asked).toContain(`/world/versions/${VERSION}/history/moments?world_id=${encodeURIComponent(WORLD)}`);
    // Only the characters the moments name are asked for, to be named as the tag and card name them (J20).
    expect(made.names).toHaveBeenCalledWith({ subjects: ['teo', 'ines', 'marco'], placed: [] });
    expect(made.root.querySelector('.wu-hr-kept')?.textContent).toBe('Kept on GitHub in terraces-on-the-bay, private · up to date');
    expect(all(made.root, '.wu-hr-card .wu-hr-words')).toEqual(['Made from your words', 'Teo met Ines at the bench', 'Marco asked Teo']);
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
    expect(exchange.querySelector('.wu-hr-pic img')?.getAttribute('src')).toBe(`/world/pictures/${'f'.repeat(64)}?world_id=${encodeURIComponent(WORLD)}`);
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
    expect(chosen(made.root)).toBe('Teo met Ines at the bench');
    history.key(press('ArrowLeft'));
    expect(chosen(made.root)).toBe('Teo met Ines at the bench');
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
