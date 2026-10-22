// @vitest-environment happy-dom
// Build mode's click and Enter while the server is asked about a held thing, its drag grip, and the tray's open tab
// (tools/previews/world-workspace/build-mode.ts and world-ui-build.css). The world here is a stand-in with no 3D
// view: the pointer's rays, the ground and the picks are written down, the server's answers wait until a test gives
// them, and each write is kept.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';

type Vec = readonly [number, number, number];
type Ray = { readonly origin: Vec; readonly direction: Vec };
const rays = vi.hoisted(() => new Map<string, unknown>());
vi.mock('../../atlas-react/src/playcanvas/index.ts', () => ({ pointerRay: (_: unknown, x: number, y: number) => rays.get(`${x},${y}`) ?? null }));
vi.mock('../src/composition/sight.ts', () => ({ pickSiteSlot: () => null }));
vi.mock('../src/composition/site-world.ts', () => ({ currentOpenSite: () => null }));
vi.mock('../src/composition/visitor-notices.ts', () => ({ kindDocumentLabel: () => null }));

interface BuildMode {
  hold(kind: unknown, at: unknown): Promise<unknown>;
  key(event: KeyboardEvent): boolean;
  click(x: number, y: number): boolean;
  pointerDown(event: MouseEvent): boolean;
  frame(now: number): void;
  dispose(): void;
}
interface Write { readonly actionId: string; readonly path: string; readonly body: Record<string, unknown> }
const build = async (): Promise<{ mountBuildMode(host: Record<string, unknown>): BuildMode }> =>
  import('../../../../tools/previews/world-workspace/' + 'build-mode.ts') as Promise<{ mountBuildMode(host: Record<string, unknown>): BuildMode }>;

const PIP = 'a'.repeat(64);
const BENCH = { kind: 'bench', version: 2, sha256: 'c'.repeat(64) };
const entry = { worldId: 'world-1', authoredVersionId: 'version-1', authoredStateSha256: 'b'.repeat(64), generatedGround: { regionId: 'region:generated' } };
const saved = { entryId: 'entry-1', revision: 3, authoredStateSha256: 'b'.repeat(64), authoredEditSeq: 7 };
/** The eye stands 1.6 m above the region's ground, which lies at the world's 0. */
const EYE: Vec = [0, 1.6, 0];

class Point {
  constructor(public x = 0, public y = 0, public z = 0) {}
  clone(): Point { return new Point(this.x, this.y, this.z); }
  set(x: number, y: number, z: number): Point { this.x = x; this.y = y; this.z = z; return this; }
  copy(other: Point): Point { return this.set(other.x, other.y, other.z); }
  distance(other: Point): number { return Math.hypot(this.x - other.x, this.y - other.y, this.z - other.z); }
}
/** The ray from the eye through a world point, and how far along it that point is. */
function towards(x: number, y: number, z: number): { ray: Ray; distance: number } {
  const d: Vec = [x - EYE[0], y - EYE[1], z - EYE[2]], length = Math.hypot(d[0], d[1], d[2]);
  return { ray: { origin: EYE, direction: [d[0] / length, d[1] / length, d[2] / length] }, distance: length };
}
/** Where a ray comes down to the flat ground, in millimetres east and south, as the society's ground read answers. */
function groundPoint(origin: Vec, direction: Vec): { xMm: number; zMm: number } | null {
  if (!(direction[1] < 0) || origin[1] <= 0) return null;
  const t = -origin[1] / direction[1];
  return { xMm: Math.round((origin[0] + t * direction[0]) * 1000) + 0, zMm: Math.round((origin[2] + t * direction[2]) * 1000) + 0 };
}

let mounted: BuildMode | null = null;
afterEach(() => { mounted?.dispose(); mounted = null; rays.clear(); document.body.replaceChildren(); });

/** How the eye looks: along `forward`, with `right` and `up` across the picture, a pinhole 500 px to a metre at 1 m. */
interface View { readonly forward: Vec; readonly right: Vec; readonly up: Vec }
const LEVEL: View = { forward: [0, 0, -1], right: [1, 0, 0], up: [0, 1, 0] };
/** Looking down ahead, so a 4 m post 2 m away has its top behind the camera and its foot in view. */
const DOWN: View = { forward: [0, -0.8, -0.6], right: [1, 0, 0], up: [0, 0.6, -0.8] };
const dot = (a: Vec, b: readonly number[]): number => a[0] * b[0]! + a[1] * b[1]! + a[2] * b[2]!;
/** A post 4 m tall standing 2 m ahead: the chosen thing's figure, its box from its foot. */
const post = {
  pickVolume: { kind: 'box', min: [-0.15, 0, -0.15], max: [0.15, 4, 0.15] },
  root: { enabled: true, getWorldTransform: () => ({ transformPoint: (p: Point, out: Point) => out.set(p.x, p.y, p.z - 2) }), getLocalScale: () => ({ x: 1, y: 1, z: 1 }) },
  markAnchor: (out: Point) => out.set(0, 4.25, -2),
};

/**
 * Build mode in a made world with one bench placed 4 m ahead, its back met by `picked`; the server answers every
 * preview only when the test calls `answer` (ready, or a refusal), and keeps every write and every note. With `view`
 * the eye looks that way and the chosen thing is drawn as `post`.
 */
async function mount(picked: { readonly direction: readonly number[]; readonly distance: number } | null = null, view: View | null = null) {
  const writes: Write[] = [], waiting: Array<(body: unknown) => void> = [];
  const root = document.createElement('div'), canvas = document.createElement('canvas');
  document.body.append(root, canvas);
  const read = async (path: string): Promise<unknown> => {
    if (path === '/things/kinds') return { kinds: [{ kind: 'pip', version: 1, sha256: PIP, label: 'Pip' }] };
    if (path.startsWith('/world/versions/version-1?')) {
      return { version_id: 'version-1', world_id: 'world-1', things: [{ thing_id: 'bench:1', kind: BENCH, region_id: 'region:generated', transform: { x_mm: 0, y_mm: 0, z_mm: -4000, yaw_microradians: 0 } }] };
    }
    throw Error(`not read here: ${path}`);
  };
  const send = (write: Write): Promise<{ body: unknown }> => {
    writes.push(write);
    if (write.actionId.endsWith('.preview')) return new Promise((resolve) => { waiting.push((body) => resolve({ body })); });
    return Promise.resolve({ body: {} });
  };
  const shown: Array<{ readonly words: string; readonly prompt: string }> = [];
  const notes = { show: (words: string, options: { prompt?: Element } = {}) => { shown.push({ words, prompt: options.prompt?.textContent ?? '' }); }, clear: () => {}, place: () => {} };
  const corners = { mode: () => {}, keys: () => {}, hints: () => {}, back: () => {}, notes };
  const project = (p: Point, out = new Point()): Point => {
    if (view === null) return out.set(0, 0, -1);
    const relative = [p.x - EYE[0], p.y - EYE[1], p.z - EYE[2]], depth = dot(view.forward, relative);
    return out.set(500 + 500 * dot(view.right, relative) / depth, 300 - 500 * dot(view.up, relative) / depth, depth);
  };
  const forward = view === null ? undefined : new Point(...view.forward);
  const camera = { getPosition: () => new Point(...EYE), forward, camera: { worldToScreen: project } };
  const layer = { figureOf: (id: string) => (view !== null && id === 'bench:1' ? post : null), drawn: [{ placedId: 'bench:1' }], setGhost: () => {}, setBoxGhost: () => {}, setKindGhost: async () => false };
  const authoredSociety = { root: { getPosition: () => new Point(0, 0, 0) }, groundPoint };
  const pick = (_: unknown, direction: unknown) => picked !== null && direction === picked.direction
    ? { thing: { pick: { placedId: 'bench:1' }, distance: picked.distance } } : null;
  const b = { camera, regionRoots: new Map(), authoredSociety, __workspaceThings: () => (view === null ? null : { layer }), __workspacePick: pick };
  const { mountBuildMode } = await build();
  mounted = mountBuildMode({ b, root, state: { activeWorldEntry: entry }, entry, read, send, binding: () => saved, canvas, corners, inspecting: () => false });
  /** The oldest preview still waiting is answered. */
  const answer = async (body: unknown = { availability: 'ready', landing: { checked: true } }): Promise<void> => {
    await vi.waitFor(() => expect(waiting.length).toBeGreaterThan(0));
    waiting.shift()!(body);
    await settled();
  };
  return { mode: mounted, writes, answer, shown, previews: () => writes.filter((write) => write.actionId.endsWith('.preview')).length };
}
const press = (mode: BuildMode, code: string, more: KeyboardEventInit = {}): boolean => mode.key(new KeyboardEvent('keydown', { code, bubbles: true, ...more }));
const settled = (): Promise<void> => new Promise((resolve) => { setTimeout(resolve, 0); });
const placed = (writes: readonly Write[]): Write[] => writes.filter((write) => write.actionId === 'things.place');
const REFUSED = { availability: 'unavailable', blocked_reason: 'thing_overlaps', blocked_detail: '' };

describe('a click or Enter while the server is asked where a held thing may stand', () => {
  it('places it after the server says it may stand there, Enter pressed then: a positive control', async () => {
    const { mode, writes, answer } = await mount();
    void mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 2000, zMm: -6000 });
    await answer();
    expect(press(mode, 'Enter')).toBe(true);
    await vi.waitFor(() => expect(placed(writes)).toHaveLength(1));
    expect(placed(writes)[0]!.body.pose).toMatchObject({ x_mm: 2000, z_mm: -6000 });
  });

  it('lets it go where it stands, and places it there once the answer comes back ready', async () => {
    for (const letGo of [(mode: BuildMode) => press(mode, 'Enter'), (mode: BuildMode) => mode.click(0, 0)]) {
      const { mode, writes, answer, previews } = await mount();
      void mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 2000, zMm: -6000 });
      await vi.waitFor(() => expect(previews()).toBe(1));
      expect(letGo(mode)).toBe(true);
      await settled();
      expect(placed(writes)).toHaveLength(0);
      await answer();
      await vi.waitFor(() => expect(placed(writes)).toHaveLength(1));
      expect(placed(writes)[0]!.body.pose).toMatchObject({ x_mm: 2000, z_mm: -6000 });
      mounted?.dispose(); mounted = null; document.body.replaceChildren();
    }
  });

  it('places nothing when the answer refuses the spot, nor later where the person has not clicked again', async () => {
    const { mode, writes, answer, previews } = await mount();
    void mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 2000, zMm: -6000 });
    await vi.waitFor(() => expect(previews()).toBe(1));
    expect(press(mode, 'Enter')).toBe(true);
    await answer(REFUSED);
    expect(press(mode, 'BracketRight')).toBe(true);
    await answer();
    await settled();
    expect(placed(writes)).toHaveLength(0);
  });

  it('takes the click back when the thing is turned before the answer', async () => {
    const { mode, writes, answer, previews } = await mount();
    void mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 2000, zMm: -6000 });
    await vi.waitFor(() => expect(previews()).toBe(1));
    mode.click(0, 0);
    expect(press(mode, 'BracketLeft')).toBe(true);
    await answer();
    await answer();
    await settled();
    expect(placed(writes)).toHaveLength(0);
  });
});

describe('carrying a chosen thing by the point a press met on it', () => {
  // The bench stands 4 m ahead; the press meets its back 0.8 m above the ground, whose ray reaches the ground 8 m out.
  const back = towards(0, 0.8, -4), down = towards(0, 0, -3);

  it('keeps it where it stands when the press lets go unmoved: a positive control', async () => {
    rays.set('500,300', back.ray);
    const { mode, writes, answer } = await mount({ direction: back.ray.direction, distance: back.distance });
    expect(press(mode, 'KeyB')).toBe(true);
    await vi.waitFor(() => expect(mode.click(500, 300)).toBe(true));
    await settled();
    expect(mode.pointerDown(new MouseEvent('mousedown', { button: 0, clientX: 500, clientY: 300 }))).toBe(true);
    document.dispatchEvent(new MouseEvent('mouseup', { clientX: 500, clientY: 300 }));
    await vi.waitFor(() => expect(writes.find((write) => write.actionId === 'things.move.preview')).toBeDefined());
    expect(writes.find((write) => write.actionId === 'things.move.preview')!.body.pose).toMatchObject({ x_mm: 0, z_mm: -4000 });
    await answer();
  });

  it('keeps the met point under the pointer as it is dragged, not the ground behind the thing', async () => {
    rays.set('500,300', back.ray);
    rays.set('500,400', down.ray);
    const { mode, writes, answer } = await mount({ direction: back.ray.direction, distance: back.distance });
    expect(press(mode, 'KeyB')).toBe(true);
    await vi.waitFor(() => expect(mode.click(500, 300)).toBe(true));
    await settled();
    expect(mode.pointerDown(new MouseEvent('mousedown', { button: 0, clientX: 500, clientY: 300 }))).toBe(true);
    document.dispatchEvent(new MouseEvent('mousemove', { clientX: 500, clientY: 400 }));
    document.dispatchEvent(new MouseEvent('mouseup', { clientX: 500, clientY: 400 }));
    await vi.waitFor(() => expect(writes.find((write) => write.actionId === 'things.move.preview')).toBeDefined());
    // The ray through the new point passes 0.8 m above the ground 1.5 m ahead; the ground behind the bench would
    // have carried it 1 m behind the eye.
    expect(writes.find((write) => write.actionId === 'things.move.preview')!.body.pose).toMatchObject({ x_mm: 0, z_mm: -1500 });
    await answer();
  });
});

describe('the tray marks its open tab in the world', () => {
  // By a file path: a literal URL beside import.meta.url would be served as a module, and the page's URL is not Node's.
  const workspace = join(dirname(fileURLToPath(import.meta.url)), '../../../../tools/previews/world-workspace');
  const sheet = (name: string): string => readFileSync(join(workspace, name), 'utf8');

  it('draws the open tab heavier than the other under the world screen\'s button reset, in either order', () => {
    for (const order of [['contextual-world.css', 'world-ui-build.css'], ['world-ui-build.css', 'contextual-world.css']]) {
      document.body.innerHTML = '<div id="contextual-world"><section class="wu-tray"><div class="wu-tray-tabs" role="tablist">'
        + '<button class="wu-tray-tab" role="tab" aria-selected="true">Things</button>'
        + '<button class="wu-tray-tab" role="tab" aria-selected="false">Creatures</button></div></section></div>';
      for (const name of order) { const style = document.createElement('style'); style.textContent = sheet(name); document.head.append(style); }
      const [open, other] = [...document.querySelectorAll('.wu-tray-tab')].map((tab) => getComputedStyle(tab).fontWeight);
      expect([open, other]).toEqual(['500', '400']);
      document.head.querySelectorAll('style').forEach((style) => style.remove());
    }
  });
});

describe('undo and redo in build mode', () => {
  const bench = (more: Record<string, unknown> = {}) => ({ thing_id: 'bench:1', kind: BENCH, region_id: 'region:generated', transform: { x_mm: 0, y_mm: 0, z_mm: -4000, yaw_microradians: 0 }, ...more });

  it('carries Undo on the note after a change and Redo on the note after an undo (W12.3)', async () => {
    const { mode, writes, answer, shown } = await mount();
    void mode.hold({ source: 'workspace', sha256: PIP }, { xMm: 2000, zMm: -6000 });
    await answer();
    expect(press(mode, 'Enter')).toBe(true);
    await vi.waitFor(() => expect(shown.at(-1)?.prompt).toContain('Undo'));
    expect(shown.at(-1)!.prompt).toContain('⌘Z');
    expect(press(mode, 'KeyZ', { metaKey: true })).toBe(true);
    await answer({ availability: 'ready', would_change: { subject_id: placed(writes)[0]!.body.thing_id, before: bench(), after: bench({ removed: true }), undoes: { kind: 'add_thing' } } });
    await vi.waitFor(() => expect(writes.some((write) => write.actionId === 'things.undo')).toBe(true));
    await vi.waitFor(() => expect(shown.at(-1)?.prompt).toContain('Redo'));
    expect(shown.at(-1)!.prompt).toContain('⇧⌘Z');
  });

  it('chooses a thing a redo places again, and not one a redo moves (W12.8)', async () => {
    for (const [change, chosen] of [[{ before: null, after: bench() }, true], [{ before: bench(), after: bench({ transform: { x_mm: 500, y_mm: 0, z_mm: -4000, yaw_microradians: 0 } }) }, false]] as const) {
      const { mode, writes, answer } = await mount();
      expect(press(mode, 'KeyB')).toBe(true);
      await settled();
      expect(press(mode, 'KeyZ', { metaKey: true, shiftKey: true })).toBe(true);
      await answer({ availability: 'ready', would_change: { subject_id: 'bench:1', ...change } });
      await vi.waitFor(() => expect(writes.some((write) => write.actionId === 'things.redo')).toBe(true));
      await settled();
      const held = document.querySelector<HTMLElement>('.wu-held');
      expect(Boolean(held && !held.hidden && held.textContent?.includes('Bench'))).toBe(chosen);
      mounted?.dispose(); mounted = null; document.body.replaceChildren();
    }
  });
});

describe('a chosen thing\'s marks up close (W12.5)', () => {
  const choose = async (view: View): Promise<SVGElement | null> => {
    const met = towards(0, 1, -2);
    rays.set('500,300', met.ray);
    const { mode } = await mount({ direction: met.ray.direction, distance: met.distance }, view);
    expect(press(mode, 'KeyB')).toBe(true);
    await vi.waitFor(() => expect(mode.click(500, 300)).toBe(true));
    await settled();
    mode.frame(1000);
    return document.querySelector<SVGElement>('svg.wu-outline[data-form="chosen"]');
  };

  it('outlines a chosen post seen level, top and foot in view: a positive control', async () => {
    const outline = await choose(LEVEL);
    expect(outline?.style.display).toBe('');
  });

  it('still outlines it from its footprint when its top is behind the camera', async () => {
    const outline = await choose(DOWN);
    expect(outline?.style.display).toBe('');
    expect(outline?.querySelector('path')?.getAttribute('d')).toBeTruthy();
  });
});

describe('the note after a chosen thing is kept turned or moved (W12.7)', () => {
  // The bench stands 4 m ahead; the press meets its back 0.8 m above the ground, and a drag carries it to 1.5 m ahead.
  const back = towards(0, 0.8, -4), down = towards(0, 0, -3);
  /** What the note says once the bench is chosen, changed by `change` and kept where the server says it may stand. */
  const noted = async (change: (mode: BuildMode) => void): Promise<string | undefined> => {
    rays.set('500,300', back.ray);
    rays.set('500,400', down.ray);
    const { mode, writes, answer, shown } = await mount({ direction: back.ray.direction, distance: back.distance });
    expect(press(mode, 'KeyB')).toBe(true);
    await vi.waitFor(() => expect(mode.click(500, 300)).toBe(true));
    await settled();
    change(mode);
    await answer();
    press(mode, 'Enter');
    await vi.waitFor(() => expect(writes.some((write) => write.actionId === 'things.move')).toBe(true));
    await vi.waitFor(() => expect(shown.at(-1)?.prompt).toContain('Undo'));
    return shown.at(-1)?.words;
  };

  it('says a bench carried to another place was moved: a positive control', async () => {
    expect(await noted((mode) => {
      expect(mode.pointerDown(new MouseEvent('mousedown', { button: 0, clientX: 500, clientY: 300 }))).toBe(true);
      document.dispatchEvent(new MouseEvent('mousemove', { clientX: 500, clientY: 400 }));
      document.dispatchEvent(new MouseEvent('mouseup', { clientX: 500, clientY: 400 }));
    })).toBe('You moved the bench');
  });

  it('says a bench turned where it stood was turned', async () => {
    expect(await noted((mode) => { expect(press(mode, 'BracketRight')).toBe(true); })).toBe('You turned the bench');
  });
});
