// @vitest-environment happy-dom
// Build mode's `hold` (tools/previews/world-workspace/build-mode.ts): a page that makes a creature holds
// it at its stand as picking its creatures tile does, and is told how that ended, placed or put back. The
// world here is a stand-in with no 3D view: the server's answers are written down and each write is kept.
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../atlas-react/src/playcanvas/index.ts', () => ({ pointerRay: () => null }));
vi.mock('../src/composition/sight.ts', () => ({ pickSiteSlot: () => null }));
vi.mock('../src/composition/site-world.ts', () => ({ currentOpenSite: () => null }));
vi.mock('../src/composition/visitor-notices.ts', () => ({ kindDocumentLabel: () => null }));

type Outcome = { readonly outcome: 'placed'; readonly thingId: string } | { readonly outcome: 'put-back' } | null;
interface BuildMode {
  hold(kind: unknown, at: unknown): Promise<Outcome>;
  key(event: KeyboardEvent): boolean;
  dispose(): void;
}
interface Write { readonly actionId: string; readonly path: string; readonly body: Record<string, unknown> }
/** A note build mode showed: its words and the second line under them. */
interface Said { readonly words: string; readonly under?: string }
const build = async (): Promise<{ mountBuildMode(host: Record<string, unknown>): BuildMode }> =>
  import('../../../../tools/previews/world-workspace/' + 'build-mode.ts') as Promise<{ mountBuildMode(host: Record<string, unknown>): BuildMode }>;

const PIP = 'a'.repeat(64);
const entry = { worldId: 'world-1', authoredVersionId: 'version-1', authoredStateSha256: 'b'.repeat(64), generatedGround: { regionId: 'region:generated' } };
/** The saved world the page is bound to, which every write names. */
const saved = { entryId: 'entry-1', revision: 3, authoredStateSha256: 'b'.repeat(64), authoredEditSeq: 7 };

/** A point the camera reads and moves as build mode does, enough for marks that are never in view. */
class Point {
  constructor(public x = 0, public y = 0, public z = 0) {}
  clone(): Point { return new Point(this.x, this.y, this.z); }
  set(x: number, y: number, z: number): Point { this.x = x; this.y = y; this.z = z; return this; }
  copy(other: Point): Point { return this.set(other.x, other.y, other.z); }
  distance(other: Point): number { return Math.hypot(this.x - other.x, this.y - other.y, this.z - other.z); }
}

let mounted: BuildMode | null = null;
afterEach(() => { mounted?.dispose(); mounted = null; document.body.replaceChildren(); });

/**
 * Build mode in a made world with one creature made, the server ready for every spot; its writes kept in order and
 * its notes as shown. `previewed(n)` is the n-th place preview's answer beyond ready (from 0), and it answers once
 * `held(n)` lets it (at once by default).
 */
async function mount({ previewed = (_: number): Record<string, unknown> => ({}), held = (_: number): Promise<void> => Promise.resolve() } = {}): Promise<{ mode: BuildMode; writes: Write[]; said: Said[] }> {
  const writes: Write[] = [], said: Said[] = [];
  let previews = 0;
  const root = document.createElement('div'), canvas = document.createElement('canvas');
  document.body.append(root, canvas);
  const read = async (path: string): Promise<unknown> => {
    if (path === '/things/kinds') return { kinds: [{ kind: 'pip', version: 1, sha256: PIP, label: 'Pip' }] };
    if (path.startsWith('/world/versions/version-1?')) return { version_id: 'version-1', world_id: 'world-1', things: [] };
    throw Error(`not read here: ${path}`);
  };
  const send = async (write: Write): Promise<{ body: unknown }> => {
    writes.push(write);
    if (write.actionId !== 'things.place.preview') return { body: {} };
    const n = previews++;
    await held(n);
    return { body: { availability: 'ready', landing: { checked: true }, ...previewed(n) } };
  };
  const notes = { show: (words: string, options: { under?: string } = {}) => { said.push({ words, ...(options.under ? { under: options.under } : {}) }); }, clear: () => {}, place: () => {} };
  const corners = { mode: () => {}, keys: () => {}, hints: () => {}, back: () => {}, notes };
  const camera = { getPosition: () => new Point(0, 10, 0), camera: { worldToScreen: (_: unknown, out = new Point()) => out.set(0, 0, -1) } };
  const b = { camera, regionRoots: new Map(), authoredSociety: null, __workspaceThings: () => null, __workspacePick: () => null };
  const { mountBuildMode } = await build();
  mounted = mountBuildMode({ b, root, state: { activeWorldEntry: entry }, entry, read, send, binding: () => saved, canvas, corners, inspecting: () => false });
  return { mode: mounted, writes, said };
}
const press = (mode: BuildMode, code: string): boolean => mode.key(new KeyboardEvent('keydown', { code, bubbles: true }));
const asked = (writes: readonly Write[]): Write | undefined => writes.find((write) => write.actionId === 'things.place.preview');
/** The server's answers, which arrive at once here, read by build mode. */
const answered = (): Promise<void> => new Promise((resolve) => { setTimeout(resolve, 0); });

describe('build mode holding a made creature for the page that made it', () => {
  it('asks the server about the spot it is held at, by the made kind and the world\'s region: a positive control', async () => {
    const { mode, writes } = await mount();
    void mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 4000, zMm: -8000 });
    await vi.waitFor(() => expect(asked(writes)).toBeDefined());
    expect(asked(writes)!.body).toMatchObject({
      kind: { source: 'workspace', sha256: PIP }, region_id: 'region:generated', pose: { x_mm: 4000, z_mm: -8000 },
    });
  });

  it('says it was placed, by the new thing\'s id, once Enter places it and the server keeps it', async () => {
    const { mode, writes } = await mount();
    const held = mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 4000, zMm: -8000 });
    await vi.waitFor(() => expect(asked(writes)).toBeDefined());
    await answered();
    expect(press(mode, 'Enter')).toBe(true);
    const outcome = await held;
    const placed = writes.find((write) => write.actionId === 'things.place');
    expect(placed!.body.thing_id).toMatch(/^creature:[0-9a-f]{8}$/u);
    expect(outcome).toEqual({ outcome: 'placed', thingId: placed!.body.thing_id });
  });

  it('says it was put back when Esc lets it go, or another hold takes its place, and nothing is placed', async () => {
    const { mode, writes } = await mount();
    const first = mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 0, zMm: 0 });
    await vi.waitFor(() => expect(asked(writes)).toBeDefined());
    const second = mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 2000, zMm: 0 });
    expect(await first).toEqual({ outcome: 'put-back' });
    await vi.waitFor(() => expect(writes.filter((write) => write.actionId === 'things.place.preview')).toHaveLength(2));
    expect(press(mode, 'Escape')).toBe(true);
    expect(await second).toEqual({ outcome: 'put-back' });
    expect(writes.some((write) => write.actionId === 'things.place')).toBe(false);
  });

  it('says what its spot closes to cars on its line while held, then under the placed note (B1)', async () => {
    const elm = { rules: 3, read: true, lanes: 1, streets: [], turns: [{ segment: 'segment:2', street: 'Elm Street' }], widest: 'turn' };
    const { mode, writes, said } = await mount({ previewed: () => ({ closes: elm }) });
    const held = mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 4000, zMm: -8000 });
    await vi.waitFor(() => expect(document.querySelector('.wu-held-line')?.textContent).toBe('Placed here, it closes the turn into Elm Street.'));
    expect(press(mode, 'Enter')).toBe(true);
    await held;
    expect(writes.some((write) => write.actionId === 'things.place')).toBe(true);
    await vi.waitFor(() => expect(said).toHaveLength(1));
    expect(said.at(-1)).toEqual({ words: expect.stringMatching(/^You placed the /u), under: 'Cars can no longer turn into Elm Street here.' });
  });

  it('says only what the preview of the spot it is kept at says: one still on its way at Enter is waited for (B1)', async () => {
    const lane = { rules: 2, read: true, lanes: 1, streets: [], turns: [], widest: 'lane' };
    let answerTurned = (): void => {};
    const turned = new Promise<void>((resolve) => { answerTurned = resolve; });
    // The first spot closes a lane; the roads under the turned one could not be read, which says nothing.
    const { mode, writes, said } = await mount({ previewed: (n) => ({ closes: n === 0 ? lane : { rules: 2, read: false } }), held: (n) => (n === 0 ? Promise.resolve() : turned) });
    const held = mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 4000, zMm: -8000 });
    await vi.waitFor(() => expect(document.querySelector('.wu-held-line')?.textContent).toBe('Placed here, it closes this lane to cars.'));
    expect(press(mode, 'BracketRight')).toBe(true);
    await vi.waitFor(() => expect(writes.filter((write) => write.actionId === 'things.place.preview')).toHaveLength(2));
    expect(document.querySelector('.wu-held-line')).toBeNull();
    expect(press(mode, 'Enter')).toBe(true);
    await answered();
    expect(writes.some((write) => write.actionId === 'things.place')).toBe(false);
    answerTurned();
    await held;
    const placed = writes.find((write) => write.actionId === 'things.place')!;
    expect(placed.body.pose).toEqual(writes.filter((write) => write.actionId === 'things.place.preview')[1]!.body.pose);
    await vi.waitFor(() => expect(said).toHaveLength(1));
    expect(said.at(-1)).toEqual({ words: expect.stringMatching(/^You placed the /u) });
  });

  it('holds nothing for a kind that is not a made one', async () => {
    const { mode } = await mount();
    expect(await mode.hold({ source: 'library', kind: 'bench' }, { xMm: 0, zMm: 0 })).toBeNull();
    expect(await mode.hold({ source: 'workspace', sha256: PIP }, { x: 0, z: 0 })).toBeNull();
  });
});
