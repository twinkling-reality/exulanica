// @vitest-environment happy-dom
// History (tools/previews/world-workspace/history.ts): what the page reads and says, and what its
// keys do. It only reads (GET through the workspace's reader, every read scoped to the world); a
// project it could not read is never called unlinked; undo and redo are build mode's own and the
// page reads the world again after one; Esc gives the world its keys back.
import { afterEach, describe, expect, it, vi } from 'vitest';

interface HistoryHost {
  readonly root: HTMLElement;
  readonly worldId: string;
  readonly versionId: string;
  readonly title: string;
  read(path: string): Promise<unknown>;
  names(named: { readonly subjects: readonly string[]; readonly placed: readonly string[] }): Promise<{ subject(id: string): string; placed(id: string): string }>;
  readonly build: { undo(): Promise<string | null>; redo(): Promise<string | null> } | null;
  readonly kindLabels: { label(kind: unknown): string | null; listen(listener: () => void): () => void };
  worldTime?(tick: number): string | null;
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

function reads(overrides: Record<string, unknown> = {}) {
  const answers: Record<string, unknown> = {
    [`/world/versions/${VERSION}`]: { version_id: VERSION, world_id: WORLD, things: [{ thing_id: 'bench:1', kind: { kind: 'bench' } }],
      edits: [{ edit_id: 'e1', kind: 'move_thing', thing_id: 'bench:1', recorded_at: at(5) }] },
    [`/world/versions/${VERSION}/society/control/sessions`]: { sessions: [] },
    [`/world/versions/${VERSION}/society/models/history`]: { choices: [{ choice_seq: 1, recorded_at: at(30), subjects: ['teo'], decider: { kind: 'model' },
      model: { provider: 'nvidia', model_id: 'nemotron', name: 'Nemotron 3 Nano 30B' }, ended: false }] },
    [`/world/versions/${VERSION}/things/characters/history`]: { records: [] },
    [`/world/versions/${VERSION}/society/comparisons`]: { comparisons: [] },
    // A world made from words began as its owner's draft, read by the draft's own id.
    '/worlds/drafts/0b0e0c1d-0000-4000-8000-000000000001': { started_at: at(90), accounting: { reported_usd: '0.31' } },
    '/world/github-projects': { projects: [{ version_id: VERSION, link: { repository: 'learner/terraces-on-the-bay', publish: 'automatic' }, last_checkpoint_at: at(1),
      github: { reached: true, visibility: 'PRIVATE', not_sent: 0, sent_through_at: at(1), pull_request: { number: 3, title: 'Moved the bench' }, paused: null } }] },
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

function host(read: HistoryHost['read'], build: HistoryHost['build'] = null, labels = kindLabels()): HistoryHost & { closed: ReturnType<typeof vi.fn>; open: ReturnType<typeof vi.fn>; names: ReturnType<typeof vi.fn> } {
  const root = document.createElement('div');
  document.body.append(root);
  return { root, worldId: WORLD, versionId: VERSION, title: 'Terraces on the bay', read, build, kindLabels: labels,
    names: vi.fn(async () => ({ subject: (id: string) => (id === 'teo' ? 'Teo' : 'the resident'), placed: () => 'the resident' })),
    open: vi.fn(), closed: vi.fn() };
}

const press = (code: string, extra: KeyboardEventInit = {}) => new KeyboardEvent('keydown', { code, key: code, cancelable: true, ...extra });
const rowWords = (root: HTMLElement) => [...root.querySelectorAll('.wu-history-row .wu-what')].map((row) => row.textContent);
const sub = (root: HTMLElement) => root.querySelector('.wu-page-sub')?.textContent;

afterEach(() => { document.body.replaceChildren(); });

describe('History', () => {
  it('reads the world and its project, scoped to the world, and lists the changes newest first', async () => {
    const { read, asked } = reads();
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    const dialog = made.root.querySelector('[role="dialog"]') as HTMLElement;
    expect(dialog.getAttribute('aria-label')).toBe('History');
    // It opens with the focus on its title, so a reader announces it (L18).
    expect(document.activeElement?.textContent).toBe('History');
    expect((document.activeElement as HTMLElement).tabIndex).toBe(-1);
    // Only the characters the rows name are asked for, to be named as the tag and card name them (J20).
    expect(made.names).toHaveBeenCalledWith({ subjects: ['teo'], placed: [] });
    // The spine is drawn in the timeline's own units: a level line has no height for a box-sized gradient.
    expect(made.root.querySelector('#wu-tl-fade')?.getAttribute('gradientUnits')).toBe('userSpaceOnUse');
    expect(rowWords(made.root)).toEqual(['Moved the bench', "Changed Teo's model to Nemotron 3 Nano 30B", 'Created from your words']);
    expect([...made.root.querySelectorAll('.wu-history-row .wu-cost')].map((cost) => cost.textContent)).toEqual(['', '', '$0.31']);
    expect(sub(made.root)).toBe('Terraces on the bay · kept in your GitHub project terraces-on-the-bay, private · up to date');
    expect(made.root.querySelector('.wu-history-row[aria-current="true"] .wu-what')?.textContent).toBe('Moved the bench');
    expect(asked.filter((path) => path.startsWith('/world/')).every((path) => path.endsWith(`?world_id=${encodeURIComponent(WORLD)}`))).toBe(true);
    expect(asked).toContain('/worlds/drafts/0b0e0c1d-0000-4000-8000-000000000001');
    // The arrows choose an earlier change; G opens the pull request the project names.
    expect(history.key(press('ArrowLeft'))).toBe(true);
    expect(made.root.querySelector('.wu-history-row[aria-current="true"] .wu-what')?.textContent).toBe("Changed Teo's model to Nemotron 3 Nano 30B");
    history.key(press('KeyG'));
    expect(made.open).toHaveBeenCalledWith('https://github.com/learner/terraces-on-the-bay/pull/3');
  });

  it("says a building's storeys and a made creature's label as build mode's words do, re-wording when a label lands", async () => {
    const heron = { kind: { source: 'workspace', sha256: 'c'.repeat(64) } };
    const { read } = reads({
      [`/world/versions/${VERSION}`]: { version_id: VERSION, world_id: WORLD, things: [{ thing_id: 'heron:1', ...heron }], edits: [
        { edit_id: 'e1', kind: 'transform_element', element_id: 'part:p1', storeys: { before: null, after: 3 }, recorded_at: at(8) },
        { edit_id: 'e2', kind: 'transform_element', element_id: 'part:p1', recorded_at: at(7) },
        { edit_id: 'e3', kind: 'add_thing', thing_id: 'heron:1', recorded_at: at(6) },
      ] },
      [`/world/versions/${VERSION}/parts`]: { parts: [{ part_id: 'p1', label: 'terrace cafe' }] },
    });
    const labels = kindLabels();
    const made = host(read, null, labels);
    const history = (await module()).mountHistory(made);
    await history.open();
    expect(rowWords(made.root).slice(0, 3)).toEqual(['Placed the creature', 'Moved the terrace cafe', 'Set the terrace cafe to 3 storeys']);
    // The label lands after the page opened: the rows are said again, with no new read.
    const asked = read.mock.calls.length;
    labels.land('c'.repeat(64), 'Long necked marsh heron');
    expect(rowWords(made.root)[0]).toBe('Placed the long necked marsh heron');
    expect(read.mock.calls.length).toBe(asked);
    // Closed, the page is told of no more labels.
    history.close();
    expect(labels.listening()).toBe(0);
  });

  it("keeps an end mark's label inside the page's margins rather than centred over them", async () => {
    // Text measures 200 wide, centred on its x: the first mark (x 40) would start at -60.
    const text = Object.getPrototypeOf(document.createElementNS('http://www.w3.org/2000/svg', 'text')) as object;
    const measured = Object.getOwnPropertyDescriptor(text, 'getBBox');
    Object.defineProperty(text, 'getBBox', { configurable: true, value(this: SVGElement) { return { x: Number(this.getAttribute('x')) - 100, y: 0, width: 200, height: 15 }; } });
    try {
      const { read } = reads();
      const made = host(read);
      await (await module()).mountHistory(made).open();
      const first = made.root.querySelector('.wu-tl-mark .wu-tl-label') as SVGTextElement;
      expect(first.textContent).toBe('Created from your words');
      expect(Number(first.getAttribute('x'))).toBe(100);
    } finally {
      if (measured) Object.defineProperty(text, 'getBBox', measured);
      else delete (text as { getBBox?: unknown }).getBBox;
    }
  });

  it('chooses a focused timeline mark on Enter and keeps the focus on the chosen change as it moves', async () => {
    const { read } = reads();
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    const chosenWords = () => made.root.querySelector('.wu-history-row[aria-current="true"] .wu-what')?.textContent;
    // The world's handler stops every key while the page is open, so the page chooses the focused mark itself.
    const first = made.root.querySelector<SVGGElement>('.wu-tl-mark[data-id="creation"]')!;
    first.focus();
    expect(history.key(Object.defineProperty(press('Enter'), 'target', { value: first }))).toBe(true);
    expect(chosenWords()).toBe('Created from your words');
    // From a focused row, the arrows move the choice and the focus goes with it.
    (made.root.querySelector('.wu-history-row[aria-current="true"]') as HTMLElement).focus();
    history.key(press('ArrowRight'));
    expect(chosenWords()).toBe("Changed Teo's model to Nemotron 3 Nano 30B");
    expect(document.activeElement?.getAttribute('aria-current')).toBe('true');
  });

  it('says only the title where the projects could not be read, never that the world is unlinked', async () => {
    const { read } = reads({ '/world/github-projects': new Error('403') });
    const made = host(read);
    await (await module()).mountHistory(made).open();
    expect(sub(made.root)).toBe('Terraces on the bay');
    const { read: none } = reads({ '/world/github-projects': { projects: [] } });
    const second = host(none);
    await (await module()).mountHistory(second).open();
    expect(sub(second.root)).toBe('Terraces on the bay · not linked to GitHub');
  });

  it('says the world could not be read, and Enter reads it again', async () => {
    const { read } = reads({ [`/world/versions/${VERSION}`]: new Error('503') });
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    expect(made.root.querySelector('.wu-history-list')?.textContent).toBe('This world could not be read. Try again.');
    const before = read.mock.calls.length;
    history.key(press('Enter'));
    await vi.waitFor(() => expect(read.mock.calls.length).toBeGreaterThan(before));
  });

  it('undoes through build mode and reads the world again; offers no undo where the world may not change', async () => {
    const { read } = reads();
    const undo = vi.fn(async () => 'Put the bench back where it was.');
    const made = host(read, { undo, redo: vi.fn(async () => null) });
    const history = (await module()).mountHistory(made);
    await history.open();
    expect(made.root.querySelector('[aria-keyshortcuts="Meta+Z"]')).not.toBeNull();
    const before = read.mock.calls.length;
    expect(history.key(press('KeyZ', { metaKey: true }))).toBe(true);
    expect(undo).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(read.mock.calls.length).toBeGreaterThan(before));

    const { read: other } = reads();
    const watching = host(other);
    await (await module()).mountHistory(watching).open();
    expect(watching.root.querySelector('[aria-keyshortcuts="Meta+Z"]')).toBeNull();
  });

  it('leaves Tab to the page and closes on Esc, giving the world its keys back', async () => {
    const { read } = reads();
    const made = host(read);
    const history = (await module()).mountHistory(made);
    await history.open();
    expect(history.key(press('Tab'))).toBe(false);
    // The old shell's keys do nothing here; a combination the page does not use keeps the browser's own.
    const k = press('KeyK');
    expect(history.key(k)).toBe(true);
    expect(k.defaultPrevented).toBe(true);
    const palette = press('KeyK', { metaKey: true });
    expect(history.key(palette)).toBe(false);
    expect(palette.defaultPrevented).toBe(false);
    expect(history.isOpen).toBe(true);
    const escape = press('Escape');
    expect(history.key(escape)).toBe(true);
    expect(escape.defaultPrevented).toBe(true);
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
