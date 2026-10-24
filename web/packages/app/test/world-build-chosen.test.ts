// @vitest-environment happy-dom
// Build mode starting while the page has someone chosen (tools/previews/world-workspace/build-mode.ts; DESIGN's "B
// never opens on nothing"): the tray hides only while something stands over it, so building starts by letting go of
// whoever is chosen (`onStart`), and a world with nowhere to place a thing does not open build mode at all. The world
// here is a stand-in with no 3D view, as in world-build-make.test.ts.
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../atlas-react/src/playcanvas/index.ts', () => ({ pointerRay: () => null, GROUND_RING: {}, createGroundRing: () => null }));
vi.mock('../src/composition/sight.ts', () => ({ pickSiteSlot: () => null }));
vi.mock('../src/composition/site-world.ts', () => ({ currentOpenSite: () => null }));
vi.mock('../src/composition/visitor-notices.ts', () => ({ kindDocumentLabel: () => null }));

interface BuildMode { active(): boolean; key(event: KeyboardEvent): boolean; hold(kind: unknown, at: unknown): Promise<unknown>; frame(now: number): void; dispose(): void }
const build = async (): Promise<{ mountBuildMode(host: Record<string, unknown>): BuildMode }> =>
  import('../../../../tools/previews/world-workspace/' + 'build-mode.ts') as Promise<{ mountBuildMode(host: Record<string, unknown>): BuildMode }>;

const PIP = 'a'.repeat(64);
const MADE = { worldId: 'world-1', authoredVersionId: 'version-1', authoredStateSha256: 'b'.repeat(64), generatedGround: { regionId: 'region:generated' } };
/** A world drawn otherwise: no region to place new things in. */
const DRAWN_OTHERWISE = { worldId: 'world-1', authoredVersionId: 'version-1', authoredStateSha256: 'b'.repeat(64) };
const saved = { entryId: 'entry-1', revision: 3, authoredStateSha256: 'b'.repeat(64), authoredEditSeq: 7 };

class Point {
  constructor(public x = 0, public y = 0, public z = 0) {}
  clone(): Point { return new Point(this.x, this.y, this.z); }
  set(x: number, y: number, z: number): Point { this.x = x; this.y = y; this.z = z; return this; }
  copy(other: Point): Point { return this.set(other.x, other.y, other.z); }
  distance(other: Point): number { return Math.hypot(this.x - other.x, this.y - other.y, this.z - other.z); }
}

let mounted: BuildMode | null = null;
afterEach(() => { mounted?.dispose(); mounted = null; document.body.replaceChildren(); });

/** The page's side: whether someone is chosen, whether a page stands over the world, and how often building started. */
interface Page { chosen: boolean; pageShown: boolean; starts: number }

/**
 * Build mode in `entry` with one creature made; the page has someone chosen when `chosen`, and lets go of them as
 * building starts unless `letsGo` is false (as the page did before). Every note shown is kept.
 */
async function mount({ chosen = false, letsGo = true, entry = MADE }: { chosen?: boolean; letsGo?: boolean; entry?: Record<string, unknown> } = {}) {
  const page: Page = { chosen, pageShown: false, starts: 0 };
  const root = document.createElement('div'), canvas = document.createElement('canvas');
  document.body.append(root, canvas);
  const read = async (path: string): Promise<unknown> => {
    if (path === '/things/kinds') return { kinds: [{ kind: 'pip', version: 1, sha256: PIP, label: 'Pip' }] };
    if (path.startsWith('/world/versions/version-1?')) return { version_id: 'version-1', world_id: 'world-1', things: [] };
    throw Error(`not read here: ${path}`);
  };
  const send = async (write: { actionId: string }): Promise<{ body: unknown }> =>
    ({ body: write.actionId === 'things.place.preview' ? { availability: 'ready', landing: { checked: true } } : {} });
  const said: string[] = [];
  const notes = { show: (words: string) => { said.push(words); }, clear: () => {}, place: () => {} };
  const corners = { mode: () => {}, keys: () => {}, hints: () => {}, back: () => {}, notes };
  const camera = { getPosition: () => new Point(0, 10, 0), forward: new Point(0, 0, -1), camera: { worldToScreen: (_: unknown, out = new Point()) => out.set(0, 0, -1) } };
  const b = { camera, regionRoots: new Map(), authoredSociety: null, __workspaceThings: () => null, __workspacePick: () => null, interactionRay: () => ({ origin: [0, 10, 0], direction: [0, 0, -1] }) };
  const { mountBuildMode } = await build();
  mounted = mountBuildMode({
    b, root, state: { activeWorldEntry: entry }, entry, read, send, binding: () => saved, canvas, corners,
    inspecting: () => page.pageShown || page.chosen, makeCreature: () => {},
    onStart: letsGo ? () => { page.starts += 1; page.chosen = false; } : null,
  });
  return { mode: mounted, root, page, said };
}
const pressB = (mode: BuildMode): boolean => mode.key(new KeyboardEvent('keydown', { code: 'KeyB', key: 'b', bubbles: true }));
const tray = (root: HTMLElement): HTMLElement | null => root.querySelector<HTMLElement>('.wu-tray');
const trayShown = (root: HTMLElement): boolean => tray(root)?.hidden === false;
/** The tray's tiles in order, Make a creature marked "make". */
const tiles = (root: HTMLElement): string[] => [...root.querySelectorAll<HTMLButtonElement>('.wu-tray .wu-tile')].map((tile) => (tile.classList.contains('wu-make') ? 'make' : tile.textContent ?? ''));
const settled = (): Promise<void> => new Promise((resolve) => { setTimeout(resolve, 0); });

describe('B with nobody chosen', () => {
  it('opens build mode with its tray, Make a creature first: a positive control', async () => {
    const { mode, root, page } = await mount();
    expect(pressB(mode)).toBe(true);
    expect(mode.active()).toBe(true);
    await vi.waitFor(() => expect(trayShown(root)).toBe(true));
    await vi.waitFor(() => expect(tiles(root)[0]).toBe('make'));
    expect(page.starts).toBe(1);
  });
});

describe('B with someone still chosen', () => {
  it('opens on nothing where the page keeps them chosen: the dress rehearsal\'s dead end', async () => {
    const { mode, root, page } = await mount({ chosen: true, letsGo: false });
    pressB(mode);
    expect(mode.active()).toBe(true);
    await settled(); mode.frame(1000); await settled();
    expect(trayShown(root)).toBe(false);
    expect(page.chosen).toBe(true);
  });

  it('lets go of them as building starts, so the tray shows with Make a creature first', async () => {
    const { mode, root, page } = await mount({ chosen: true });
    pressB(mode);
    expect(page).toMatchObject({ chosen: false, starts: 1 });
    await vi.waitFor(() => expect(trayShown(root)).toBe(true));
    await vi.waitFor(() => expect(tiles(root)[0]).toBe('make'));
  });

  it('lets go only as building starts: leaving it calls nothing, and B again starts it again', async () => {
    const { mode, page } = await mount({ chosen: true });
    pressB(mode);
    await settled();
    expect(page.starts).toBe(1);
    pressB(mode);
    expect(mode.active()).toBe(false);
    expect(page.starts).toBe(1);
    page.chosen = true;
    pressB(mode);
    expect(page).toMatchObject({ chosen: false, starts: 2 });
  });

  it('lets go of them when a hold turns building on, as a creature placed from its tab does', async () => {
    const { mode, page } = await mount({ chosen: true });
    void mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 0, zMm: -2000 });
    await vi.waitFor(() => expect(mode.active()).toBe(true));
    expect(page).toMatchObject({ chosen: false, starts: 1 });
  });
});

describe('the tray while something stands over it', () => {
  it('hides while a page is open over the world and comes back when it closes', async () => {
    const { mode, root, page } = await mount();
    pressB(mode);
    await vi.waitFor(() => expect(trayShown(root)).toBe(true));
    page.pageShown = true;
    mode.frame(1000);
    expect(trayShown(root)).toBe(false);
    page.pageShown = false;
    mode.frame(1100);
    await vi.waitFor(() => expect(trayShown(root)).toBe(true));
  });

  it('gives way to someone chosen while building only while their card is in view, and comes back when they walk out of it', async () => {
    const { mode, root, page } = await mount();
    pressB(mode);
    await vi.waitFor(() => expect(trayShown(root)).toBe(true));
    // Chosen with E: their card stands over the tray.
    page.chosen = true;
    mode.frame(1000);
    expect(trayShown(root)).toBe(false);
    // They walk out of view, still chosen: the page says nothing stands over it now (contextual-world.ts).
    page.chosen = false;
    mode.frame(1100);
    await vi.waitFor(() => expect(trayShown(root)).toBe(true));
    page.chosen = true;
    mode.frame(1200);
    expect(trayShown(root)).toBe(false);
  });
});

describe('B in a world with nowhere to place a thing', () => {
  it('does not open build mode, says so, and leaves whoever is chosen', async () => {
    const { mode, root, page, said } = await mount({ entry: DRAWN_OTHERWISE, chosen: true });
    expect(pressB(mode)).toBe(true);
    await settled();
    expect(mode.active()).toBe(false);
    expect(said).toEqual(['Nothing can be placed in this world.']);
    expect(page).toMatchObject({ chosen: true, starts: 0 });
    expect(trayShown(root)).toBe(false);
  });

  it('holds nothing there either', async () => {
    const { mode } = await mount({ entry: DRAWN_OTHERWISE });
    await expect(mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 0, zMm: -2000 })).resolves.toBeNull();
    expect(mode.active()).toBe(false);
  });
});
