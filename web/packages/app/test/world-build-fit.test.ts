// @vitest-environment happy-dom
// Which things the tray offers first (tools/previews/world-workspace/build-mode.ts, B4): every object kind the library
// holds, those that fit the world first in the library's order and the rest after a wider gap, nothing hidden. A kind
// fits any world, or a world in one of the eras it lists; no world states its eras yet, so a kind that lists any era
// fits and one that lists none (a story world's sword) comes after. The world is a stand-in with no 3D view.
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../atlas-react/src/playcanvas/index.ts', () => ({ pointerRay: () => null, GROUND_RING: {}, createGroundRing: () => null }));
vi.mock('../src/composition/sight.ts', () => ({ pickSiteSlot: () => null }));
vi.mock('../src/composition/site-world.ts', () => ({ currentOpenSite: () => null }));
vi.mock('../src/composition/visitor-notices.ts', () => ({ kindDocumentLabel: () => null }));

interface BuildMode { key(event: KeyboardEvent): boolean; dispose(): void }
const build = async (): Promise<{ mountBuildMode(host: Record<string, unknown>): BuildMode }> =>
  import('../../../../tools/previews/world-workspace/' + 'build-mode.ts') as Promise<{ mountBuildMode(host: Record<string, unknown>): BuildMode }>;

const MADE = { worldId: 'world-1', authoredVersionId: 'version-1', authoredStateSha256: 'b'.repeat(64), generatedGround: { regionId: 'region:generated' } };
const saved = { entryId: 'entry-1', revision: 3, authoredStateSha256: 'b'.repeat(64), authoredEditSeq: 7 };
const PRESENT_DAY = ['contemporary', 'interwar', 'postwar', 'prewar_masonry'];

/** A library kind as the library lists it: an object, its latest version, and what it fits where it states it. */
const kind = (key: string, version: number, fits?: 'any' | readonly string[]) => ({
  kind: key, version, sha256: key.padEnd(64, '0').slice(0, 64), label: key.replace('_', ' '), class: 'object', bodyPlan: 'rigid', looks: [],
  ...(fits === undefined ? {} : { fits: { eras: fits } }),
});

class Point {
  constructor(public x = 0, public y = 0, public z = 0) {}
  clone(): Point { return new Point(this.x, this.y, this.z); }
  set(x: number, y: number, z: number): Point { this.x = x; this.y = y; this.z = z; return this; }
  copy(other: Point): Point { return this.set(other.x, other.y, other.z); }
  distance(other: Point): number { return Math.hypot(this.x - other.x, this.y - other.y, this.z - other.z); }
}

let mounted: BuildMode | null = null;
afterEach(() => { mounted?.dispose(); mounted = null; document.body.replaceChildren(); });

async function trayOf(kinds: readonly { readonly kind: string }[]): Promise<HTMLElement> {
  const root = document.createElement('div'), canvas = document.createElement('canvas');
  document.body.append(root, canvas);
  const read = async (path: string): Promise<unknown> => {
    if (path === '/things/kinds') return { kinds: [] };
    if (path.startsWith('/world/versions/version-1?')) return { version_id: 'version-1', world_id: 'world-1', things: [] };
    throw Error(`not read here: ${path}`);
  };
  const send = async (): Promise<{ body: unknown }> => ({ body: {} });
  const notes = { show: () => {}, clear: () => {}, place: () => {} };
  const corners = { mode: () => {}, keys: () => {}, hints: () => {}, back: () => {}, notes };
  const camera = { getPosition: () => new Point(0, 10, 0), forward: new Point(0, 0, -1), camera: { worldToScreen: (_: unknown, out = new Point()) => out.set(0, 0, -1) } };
  const layer = { maker: { library: { list: { kinds } } } };
  const b = { camera, regionRoots: new Map(), authoredSociety: null, __workspaceThings: () => ({ layer }), __workspacePick: () => null, interactionRay: () => ({ origin: [0, 10, 0], direction: [0, 0, -1] }) };
  const { mountBuildMode } = await build();
  mounted = mountBuildMode({ b, root, state: { activeWorldEntry: MADE }, entry: MADE, read, send, binding: () => saved, canvas, corners, inspecting: () => false });
  mounted.key(new KeyboardEvent('keydown', { code: 'KeyB', key: 'b', bubbles: true }));
  await vi.waitFor(() => expect(root.querySelectorAll('.wu-tray .wu-tile').length).toBe(new Set(kinds.map((one) => one.kind)).size));
  return root;
}
const tiles = (root: HTMLElement): string[] => [...root.querySelectorAll<HTMLButtonElement>('.wu-tray .wu-tile')].map((tile) => (tile.dataset.apart === 'true' ? '| ' : '') + (tile.textContent ?? ''));

describe('the things the tray offers first', () => {
  it('offers every kind, those that fit the world first in the library\'s order, the sword after a gap', async () => {
    const root = await trayOf([
      kind('bench', 3, 'any'), kind('lamp_post', 4, PRESENT_DAY), kind('sword', 4, []), kind('well', 3, 'any'),
    ]);
    expect(tiles(root)).toEqual(['Bench', 'Lamp post', 'Well', '| Sword']);
  });

  it('reads the latest version\'s fit, and counts a kind that states none as fitting', async () => {
    // The sword's older version states nothing (so it would fit); its latest fits no era.
    const root = await trayOf([kind('sword', 3), kind('gate', 1), kind('sword', 4, []), kind('bench', 2)]);
    expect(tiles(root)).toEqual(['Gate', 'Bench', '| Sword']);
  });

  it('sets nothing apart where every kind fits', async () => {
    expect(tiles(await trayOf([kind('bench', 2), kind('gate', 1)]))).toEqual(['Bench', 'Gate']);
  });
});
