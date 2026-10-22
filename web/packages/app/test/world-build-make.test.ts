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

interface Hand {
  hold(kind: unknown, at: unknown): Promise<unknown>;
  ahead(millimetres: number): unknown;
  mark(at: unknown, radiusM: number): unknown;
  head(): unknown;
  showing(now: boolean, key?: (event: KeyboardEvent) => void): void;
}
interface BuildMode { active(): boolean; key(event: KeyboardEvent): boolean; dispose(): void }
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

/** Build mode in a made world with one creature made and a creature maker that keeps what it is handed. */
async function mount(): Promise<{ mode: BuildMode; root: HTMLElement; writes: Write[]; hands: Hand[] }> {
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
    return { body: write.actionId === 'things.place.preview' ? { availability: 'ready', landing: { checked: true } } : {} };
  };
  const notes = { show: () => {}, clear: () => {}, place: () => {} };
  const corners = { mode: () => {}, keys: () => {}, hints: () => {}, back: () => {}, notes };
  const camera = { getPosition: () => new Point(0, 10, 0), forward: new Point(0, 0, -1), camera: { worldToScreen: (_: unknown, out = new Point()) => out.set(0, 0, -1) } };
  const b = { camera, regionRoots: new Map(), authoredSociety: null, __workspaceThings: () => null, __workspacePick: () => null, interactionRay: () => ({ origin: [0, 10, 0], direction: [0, 0, -1] }) };
  const { mountBuildMode } = await build();
  mounted = mountBuildMode({
    b, root, state: { activeWorldEntry: entry }, entry, read, send, binding: () => saved, canvas, corners, inspecting: () => false,
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
});
