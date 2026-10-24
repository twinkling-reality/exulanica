// @vitest-environment happy-dom
// Build mode's "Make a creature" tile (tools/previews/world-workspace/build-mode.ts): picking it opens the page's
// creature maker and hands it what places what it makes where it was made (unit 9): build mode's hold, the ground
// ahead of the eye, the stand's ring, and whether a creature step shows, which hides the tray meanwhile. The world
// here is a stand-in with no 3D view: the server's answers are written down and each write is kept.
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../atlas-react/src/playcanvas/index.ts', () => ({ pointerRay: () => null, GROUND_RING: {}, createGroundRing: () => null }));
vi.mock('../src/composition/sight.ts', () => ({ pickSiteSlot: () => null }));
vi.mock('../src/composition/site-world.ts', () => ({ currentOpenSite: () => null }));
vi.mock('../src/composition/visitor-notices.ts', () => ({ kindDocumentLabel: () => null }));

interface Placing { readonly placing: boolean; readonly refused: string | null }
interface Hand {
  hold(kind: unknown, at: unknown, told?: (placing: Placing) => void): Promise<unknown>;
  ahead(millimetres: number): unknown;
  mark(at: unknown, radiusM: number): unknown;
  head(): unknown;
  showing(now: boolean, key?: (event: KeyboardEvent) => void): void;
}
interface BuildMode { active(): boolean; key(event: KeyboardEvent): boolean; frame(now: number): void; dispose(): void }
interface Write { readonly actionId: string; readonly path: string; readonly body: Record<string, unknown> }
const build = async (): Promise<{ mountBuildMode(host: Record<string, unknown>): BuildMode }> =>
  import('../../../../tools/previews/world-workspace/' + 'build-mode.ts') as Promise<{ mountBuildMode(host: Record<string, unknown>): BuildMode }>;

const PIP = 'a'.repeat(64);
const entry = { worldId: 'world-1', authoredVersionId: 'version-1', authoredStateSha256: 'b'.repeat(64), generatedGround: { regionId: 'region:generated' } };
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

/**
 * Build mode in a made world with one creature made and a creature maker that keeps what it is handed; `place`
 * answers the place itself where given (else at once).
 */
async function mount(place?: () => Promise<{ body: unknown }>, over: { shown: boolean } = { shown: false }): Promise<{ mode: BuildMode; root: HTMLElement; writes: Write[]; hands: Hand[] }> {
  const writes: Write[] = [], hands: Hand[] = [];
  const root = document.createElement('div'), canvas = document.createElement('canvas');
  document.body.append(root, canvas);
  const read = async (path: string): Promise<unknown> => {
    if (path === '/things/kinds') return { kinds: [{ kind: 'pip', version: 1, sha256: PIP, label: 'Pip' }] };
    if (path.startsWith('/world/versions/version-1?')) return { version_id: 'version-1', world_id: 'world-1', things: [] };
    throw Error(`not read here: ${path}`);
  };
  const send = async (write: Write): Promise<{ body: unknown }> => {
    writes.push(write);
    if (write.actionId === 'things.place' && place) return place();
    return { body: write.actionId === 'things.place.preview' ? { availability: 'ready', landing: { checked: true } } : {} };
  };
  const notes = { show: () => {}, clear: () => {}, place: () => {} };
  const corners = { mode: () => {}, keys: () => {}, hints: () => {}, back: () => {}, notes };
  const camera = { getPosition: () => new Point(0, 10, 0), forward: new Point(0, 0, -1), camera: { worldToScreen: (_: unknown, out = new Point()) => out.set(0, 0, -1) } };
  const b = { camera, regionRoots: new Map(), authoredSociety: null, __workspaceThings: () => null, __workspacePick: () => null, interactionRay: () => ({ origin: [0, 10, 0], direction: [0, 0, -1] }) };
  const { mountBuildMode } = await build();
  mounted = mountBuildMode({
    b, root, state: { activeWorldEntry: entry }, entry, read, send, binding: () => saved, canvas, corners, inspecting: () => over.shown,
    makeCreature: (hand: Hand) => { hands.push(hand); },
  });
  return { mode: mounted, root, writes, hands };
}
const tray = (root: HTMLElement): HTMLElement => root.querySelector<HTMLElement>('.wu-tray')!;
const makeTile = (root: HTMLElement): HTMLButtonElement | null => root.querySelector<HTMLButtonElement>('.wu-tile.wu-make');
const asked = (writes: readonly Write[]): Write | undefined => writes.find((write) => write.actionId === 'things.place.preview');

/** Build mode on and its creatures tab chosen, where the Make tile leads the row. */
async function picked(root: HTMLElement, mode: BuildMode): Promise<void> {
  mode.key(new KeyboardEvent('keydown', { code: 'KeyB', key: 'b', bubbles: true }));
  await vi.waitFor(() => expect(tray(root).hidden).toBe(false));
  [...root.querySelectorAll<HTMLButtonElement>('.wu-tray-tab')].find((tab) => /creature/i.test(tab.textContent ?? ''))?.click();
  await vi.waitFor(() => expect(makeTile(root)).not.toBeNull());
  makeTile(root)!.click();
}

describe('Enter on Make a creature, the tray\'s first tile', () => {
  it('opens the maker straight after B, as the tile\'s click does, with nothing held or chosen', async () => {
    const { mode, root, hands } = await mount();
    mode.key(new KeyboardEvent('keydown', { code: 'KeyB', key: 'b', bubbles: true }));
    await vi.waitFor(() => expect(tray(root).hidden).toBe(false));
    expect(makeTile(root)).not.toBeNull();
    expect(mode.key(new KeyboardEvent('keydown', { code: 'Enter', key: 'Enter', bubbles: true }))).toBe(true);
    expect(hands).toHaveLength(1);
    expect(typeof hands[0]!.hold).toBe('function');
  });

  it('opens nothing while something stands over the world and the tray gives way to it', async () => {
    const over = { shown: false };
    const { mode, root, hands } = await mount(undefined, over);
    mode.key(new KeyboardEvent('keydown', { code: 'KeyB', key: 'b', bubbles: true }));
    await vi.waitFor(() => expect(tray(root).hidden).toBe(false));
    over.shown = true;
    mode.frame(1000);
    expect(tray(root).hidden).toBe(true);
    mode.key(new KeyboardEvent('keydown', { code: 'Enter', key: 'Enter', bubbles: true }));
    expect(hands).toHaveLength(0);
  });
});

describe('build mode handing a creature maker what places what it makes', () => {
  it('opens the maker from the Make tile with hold, the ground ahead, the stand ring and whether a step shows', async () => {
    const { mode, root, hands } = await mount();
    await picked(root, mode);
    expect(hands).toHaveLength(1);
    const [hand] = hands;
    expect(typeof hand!.hold).toBe('function');
    // With no society drawn there is no ground ahead to read, and no stand ring to lay.
    expect(hand!.ahead(8000)).toBeNull();
    expect(hand!.mark({ xMm: 0, zMm: 0 }, 0.6)).toBeNull();
    expect(hand!.mark(null, 0.6)).toBeNull();
    // Nothing held yet: no head to lead to.
    expect(hand!.head()).toBeNull();
  });

  it('hides the tray while a creature step shows and brings it back once it is gone', async () => {
    const { mode, root, hands } = await mount();
    await picked(root, mode);
    hands[0]!.showing(true);
    expect(tray(root).hidden).toBe(true);
    hands[0]!.showing(false);
    await vi.waitFor(() => expect(tray(root).hidden).toBe(false));
  });

  it('hands every key to the creature step while it shows, and keeps its own once the step hands them back', async () => {
    const { mode, root, hands } = await mount();
    await picked(root, mode);
    const seen: string[] = [];
    hands[0]!.showing(true, (event) => { seen.push(event.code); });
    // Esc and B reach the step alone: the world neither leaves building nor goes back to Your worlds.
    expect(mode.key(new KeyboardEvent('keydown', { code: 'Escape', key: 'Escape' }))).toBe(true);
    expect(mode.key(new KeyboardEvent('keydown', { code: 'KeyB', key: 'b' }))).toBe(true);
    expect(seen).toEqual(['Escape', 'KeyB']);
    expect(mode.active()).toBe(true);
    // Handed back (a made creature held at its stand): B is build mode's again, and the step hears nothing.
    hands[0]!.showing(true);
    expect(mode.key(new KeyboardEvent('keydown', { code: 'KeyB', key: 'b' }))).toBe(true);
    expect(seen).toEqual(['Escape', 'KeyB']);
    expect(mode.active()).toBe(false);
  });

  it('holds the made kind at the point the maker names, as a hold from the page does', async () => {
    const { mode, root, writes, hands } = await mount();
    await picked(root, mode);
    // Exactly at the point named (a stand's node): the half-metre snap starts only once the person moves it, and a
    // pointer last seen over the world does not carry it off.
    document.querySelector('canvas')!.dispatchEvent(new MouseEvent('pointermove', { clientX: 10, clientY: 10 }));
    void hands[0]!.hold({ source: 'workspace', sha256: PIP }, { xMm: 4200, zMm: -1800 });
    await vi.waitFor(() => expect(asked(writes)).toBeDefined());
    expect(asked(writes)!.body).toMatchObject({ kind: { source: 'workspace', sha256: PIP }, pose: { x_mm: 4200, z_mm: -1800 } });
  });

  it('tells the maker its creature is placing from Enter until the server answers, and why a place was refused', async () => {
    let answer: { settle: (body: { body: unknown }) => void; refuse: (error: Error) => void } | null = null;
    const { mode, root, writes, hands } = await mount(() => new Promise((settle, refuse) => { answer = { settle, refuse }; }));
    await picked(root, mode);
    const told: Placing[] = [];
    const held = hands[0]!.hold({ source: 'workspace', sha256: PIP }, { xMm: 4200, zMm: -1800 }, (placing) => { told.push(placing); });
    await vi.waitFor(() => expect(told).toEqual([{ placing: false, refused: null }]));
    const enter = () => mode.key(new KeyboardEvent('keydown', { code: 'Enter', key: 'Enter' }));
    enter();
    expect(told.at(-1)).toEqual({ placing: true, refused: null });
    // A second Enter while the server answers places nothing more.
    enter();
    expect(writes.filter((write) => write.actionId === 'things.place')).toHaveLength(1);
    answer!.refuse(new Error('refused'));
    await vi.waitFor(() => expect(told.at(-1)?.placing).toBe(false));
    expect(told.at(-1)?.refused).toEqual(expect.any(String));
    expect(told.at(-1)?.refused).not.toBe('');
    // Refused, Enter places nothing more; Esc puts it back and the hold ends.
    enter();
    expect(writes.filter((write) => write.actionId === 'things.place')).toHaveLength(1);
    mode.key(new KeyboardEvent('keydown', { code: 'Escape', key: 'Escape' }));
    await expect(held).resolves.toMatchObject({ outcome: 'put-back' });
  });

  it('tells the maker its creature is placing while the server still checks where it stands, then places it', async () => {
    let answer: ((body: { body: unknown }) => void) | null = null;
    const { mode, root, hands } = await mount(() => new Promise((settle) => { answer = settle; }));
    await picked(root, mode);
    const told: Placing[] = [];
    const held = hands[0]!.hold({ source: 'workspace', sha256: PIP }, { xMm: 4200, zMm: -1800 }, (placing) => { told.push(placing); });
    // Enter before the check answers lets it go there: placing at once, and placed once it may stand.
    await vi.waitFor(() => expect(mode.active()).toBe(true));
    mode.key(new KeyboardEvent('keydown', { code: 'Enter', key: 'Enter' }));
    expect(told).toEqual([{ placing: true, refused: null }]);
    await vi.waitFor(() => expect(answer).not.toBeNull());
    expect(told.every((placing) => placing.placing)).toBe(true);
    answer!({ body: {} });
    await expect(held).resolves.toMatchObject({ outcome: 'placed' });
  });
});
