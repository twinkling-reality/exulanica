/**
 * DEVELOPMENT ONLY: the painted world's lab page.
 *
 * On a development build, the plain word `?painted=1` draws a gaussian splat over a site world at
 * the frame its layout is drawn in. The layout's opaque surfaces are held undrawn while each frame
 * renders and given back after it, so the walk and picking (a CPU ray test between frames) find
 * them as before while the splat is what is seen: a splat trained to the layout's depth paints its
 * own ground and walls, and people and things test against the depth they write themselves. Water
 * and glass, which are drawn blended, stay as they are. The splat is drawn after the camera frame's
 * tone mapping (`splatsAfterToneMapping`), as its trainer drew it and tested against the scene's
 * depth, so the undrawn ground does not let the world's own water draw over it.
 *
 * `layout=depth` beside the word makes the layout depth-only instead (`layoutDepthOnly`), for a
 * splat not held to the layout: still there for hiding people behind walls the splat paints thinly,
 * drawn only into depth, with the scene's skybox drawn first so it shows where the splat leaves a
 * hole. A splat lies a little behind the surfaces it was trained on, so the depth-only layout is
 * pushed back from the eye (`SPLAT_OCCLUSION`'s `pushMetres`); `push=<metres>` tries another
 * distance, from 0 to 10 m.
 *
 * The splat is the one the development server was started with (`EXULANICA_PAINTED_SPLAT`, served
 * at `PAINTED_SPLAT_ROUTE` by `vite.config.ts`); the page never names a path or a URL. A SOG goes
 * through `createSceneSplatAsset`, which holds it to the trained geometry and bundle checks. A 3DGS
 * `.ply` is not a SOG and is loaded by its file name alone, labelled a stand-in in the page state.
 * Its frame is the layout's (x east, y up, z south, metres) unless the server was also given a
 * frame (`EXULANICA_PAINTED_FRAME`), a rigid row-major transform from the splat to the layout.
 *
 * Nothing here is reachable from a production build: the only importer is
 * `composition/site-world.ts`, behind `import.meta.env.DEV`, and `test/painted-splat.test.ts`
 * builds the app and proves no part of this module or its route is emitted.
 */

import { islandId } from '@exulanica/atlas-core';
import {
  SPLAT_OCCLUSION, createSceneSplatAsset, layoutDepthOnly, splatsAfterToneMapping, validateSogBundle,
  type SplatDisplay, type TrainedSceneGeometry,
} from '@exulanica/atlas-react/playcanvas';
import type { GeneratedTileHost } from '@exulanica/atlas-react/generated-tile';

type Entity = GeneratedTileHost['environmentRoot'];
type App = GeneratedTileHost['app'];
type Asset = NonNullable<ReturnType<App['assets']['get']>>;

/** The development route that answers with the splat the server was started with. */
export const PAINTED_SPLAT_ROUTE = '/__painted-lab/splat';
/** The development route that answers with the splat's frame, when the server was given one. */
export const PAINTED_FRAME_ROUTE = '/__painted-lab/frame.json';
/** The page state's own marker, which no production build carries. */
export const PAINTED_LAB_MARKER = 'painted-lab:splat';

const IDENTITY: readonly number[] = Object.freeze([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);

/** Whether the page asks for the lab: only on a development build, only for exactly `painted=1`. */
export function paintedLabAsked(search: string, development: boolean): boolean {
  if (!development) return false;
  const values = new URLSearchParams(search).getAll('painted');
  return values.length === 1 && values[0] === '1';
}

/** How the layout lies under the splat: held undrawn, unless the page asks for exactly `layout=depth`. */
export function paintedLayout(search: string): 'undrawn' | 'depth' {
  const values = new URLSearchParams(search).getAll('layout');
  return values.length === 1 && values[0] === 'depth' ? 'depth' : 'undrawn';
}

/**
 * How far the page asks the depth-only layout to be pushed back, in metres: exactly one `push` of
 * up to two digits and two decimals, at most 10. Null, meaning the look's own distance, otherwise.
 */
export function paintedPush(search: string): number | null {
  const values = new URLSearchParams(search).getAll('push');
  if (values.length !== 1 || !/^\d{1,2}(?:\.\d{1,2})?$/.test(values[0]!)) return null;
  const metres = Number(values[0]);
  return metres <= 10 ? metres : null;
}

/**
 * The splat-to-layout transform a frame document states: `{ "sceneFromAssetRowMajor": [16 numbers] }`,
 * a rotation and a translation only. Throws on anything else, scale and reflection included.
 */
export function readPaintedFrame(value: unknown): readonly number[] {
  const matrix = typeof value === 'object' && value !== null
    ? (value as { sceneFromAssetRowMajor?: unknown }).sceneFromAssetRowMajor : undefined;
  if (!Array.isArray(matrix) || matrix.length !== 16 || matrix.some((n) => typeof n !== 'number' || !Number.isFinite(n))) {
    throw new TypeError('A painted frame is sixteen finite numbers, row-major');
  }
  const m = matrix as number[];
  if (m[12] !== 0 || m[13] !== 0 || m[14] !== 0 || m[15] !== 1) throw new TypeError('A painted frame is an affine transform');
  for (let left = 0; left < 3; left += 1) {
    for (let right = 0; right < 3; right += 1) {
      const dot = m[left]! * m[right]! + m[4 + left]! * m[4 + right]! + m[8 + left]! * m[8 + right]!;
      if (Math.abs(dot - (left === right ? 1 : 0)) > 1e-6) throw new TypeError('A painted frame is rigid: a rotation without scale');
    }
  }
  const determinant = m[0]! * (m[5]! * m[10]! - m[6]! * m[9]!) - m[1]! * (m[4]! * m[10]! - m[6]! * m[8]!)
    + m[2]! * (m[4]! * m[9]! - m[5]! * m[8]!);
  if (Math.abs(determinant - 1) > 1e-6) throw new TypeError('A painted frame is a proper rotation, without reflection');
  return Object.freeze([...m]);
}

/** The unit quaternion (x, y, z, w) of a rigid row-major transform's rotation. */
function rotationOf(m: readonly number[]): [number, number, number, number] {
  const [r00, r01, r02, r10, r11, r12, r20, r21, r22] = [m[0]!, m[1]!, m[2]!, m[4]!, m[5]!, m[6]!, m[8]!, m[9]!, m[10]!];
  const trace = r00 + r11 + r22;
  if (trace > 0) {
    const s = Math.sqrt(trace + 1) * 2;
    return [(r21 - r12) / s, (r02 - r20) / s, (r10 - r01) / s, s / 4];
  }
  if (r00 > r11 && r00 > r22) {
    const s = Math.sqrt(1 + r00 - r11 - r22) * 2;
    return [s / 4, (r01 + r10) / s, (r02 + r20) / s, (r21 - r12) / s];
  }
  if (r11 > r22) {
    const s = Math.sqrt(1 + r11 - r00 - r22) * 2;
    return [(r01 + r10) / s, s / 4, (r12 + r21) / s, (r02 - r20) / s];
  }
  const s = Math.sqrt(1 + r22 - r00 - r11) * 2;
  return [(r02 + r20) / s, (r12 + r21) / s, s / 4, (r10 - r01) / s];
}

/** The page state `window.__paintedLab` reads, development only. */
export interface PaintedLabState {
  readonly phase: 'loading' | 'drawn' | 'failed' | 'disposed';
  readonly format: 'sog' | 'ply' | null;
  /** A `.ply` is a stand-in for the painted SOG; a SOG is the trained format itself. */
  readonly standIn: boolean;
  /** What the splat is, in words a picture of the page can carry. */
  readonly label: string | null;
  readonly frame: readonly number[];
  readonly pointCount: number | null;
  /** How the layout lies under the splat: held undrawn, or depth-only (`layout=depth`). */
  readonly layout: 'undrawn' | 'depth';
  /** How far a depth-only layout is pushed back from the eye, in metres. */
  readonly pushMetres: number;
  /** Whether the splat is drawn after the camera frame's tone mapping now, rather than in the scene. */
  readonly display: boolean;
  readonly reason: string | null;
}

export interface PaintedLab {
  readonly state: () => PaintedLabState;
  readonly splat: () => Entity | null;
  /** The layout's instances drawn depth-only, or held undrawn in the last frame. */
  readonly depthOnly: () => number;
  readonly undrawn: () => number;
  dispose(): void;
}

/** What a render component holds that the undrawn hold reads; the lab names no engine type. */
interface LayoutDrawing {
  readonly meshInstances: readonly { visible: boolean; readonly material: { readonly transparent: boolean; readonly depthWrite: boolean } | null }[];
}

/**
 * Holds the opaque surfaces under `roots` undrawn while each frame renders (from the app's prerender
 * to its postrender) and gives them back after it. They are found again every frame, because the
 * world's streaming adds pieces and turns render components back on as the camera moves.
 */
export function layoutUndrawn(roots: readonly Entity[], app: Pick<App, 'on' | 'off'>): { readonly instances: number; dispose(): void } {
  let held: LayoutDrawing['meshInstances'][number][] = [];
  const hide = (): void => {
    held = [];
    for (const render of roots.flatMap((root) => root.findComponents('render') as unknown as LayoutDrawing[])) {
      for (const instance of render.meshInstances) {
        const material = instance.material;
        if (material === null || material.transparent || !material.depthWrite || !instance.visible) continue;
        instance.visible = false;
        held.push(instance);
      }
    }
  };
  const show = (): void => { for (const instance of held) instance.visible = true; };
  app.on('prerender', hide);
  app.on('postrender', show);
  return {
    get instances() { return held.length; },
    dispose() {
      app.off('prerender', hide);
      app.off('postrender', show);
      show();
      held = [];
    },
  };
}

/** The splat's asset: a validated SOG from its bytes, or a `.ply` stand-in by its file name. */
async function splatAsset(app: App, frame: readonly number[]): Promise<{ asset: Asset; format: 'sog' | 'ply'; pointCount: number | null }> {
  const head = await fetch(PAINTED_SPLAT_ROUTE, { method: 'HEAD', credentials: 'same-origin' });
  const format = head.headers.get('x-painted-lab-format');
  if (!head.ok || (format !== 'sog' && format !== 'ply')) throw new Error(`The lab's splat is unavailable: HTTP ${head.status}.`);
  if (format === 'ply') {
    const asset = await new Promise<Asset>((resolve, reject) => {
      app.assets.loadFromUrlAndFilename(PAINTED_SPLAT_ROUTE, 'painted-lab-stand-in.ply', 'gsplat', (error, value) => {
        if (error !== null || value === undefined) reject(new Error(String(error ?? 'no asset'))); else resolve(value);
      });
    });
    return { asset, format, pointCount: null };
  }
  const response = await fetch(PAINTED_SPLAT_ROUTE, { credentials: 'same-origin' });
  if (!response.ok) throw new Error(`The lab's splat is unavailable: HTTP ${response.status}.`);
  const bytes = await response.arrayBuffer();
  const geometry: TrainedSceneGeometry = {
    sceneId: 'painted-lab', islandId: islandId('painted-lab'), artifactId: 'painted-lab', bytes,
    sceneFromAssetRowMajor: frame,
    // Bounds feed only residency, which the lab does not take part in.
    bounds: { min: [0, 0, 0], max: [0, 0, 0] },
    pointCount: validateSogBundle(bytes).pointCount,
  };
  return { asset: await createSceneSplatAsset(app, geometry), format, pointCount: geometry.pointCount };
}

/** The frame the server was given for the splat, or the layout's own. */
async function paintedFrame(): Promise<readonly number[]> {
  const response = await fetch(PAINTED_FRAME_ROUTE, { credentials: 'same-origin' });
  if (response.status === 404) return IDENTITY;
  if (!response.ok) throw new Error(`The lab's frame is unavailable: HTTP ${response.status}.`);
  return readPaintedFrame(await response.json());
}

/**
 * Opens the lab over a site just attached: `siteRoots` are the entities its drawing added under the
 * environment root, the layout the splat lies over; people, things and the splat are never among them.
 * Returns null, doing nothing, unless the page asked for the lab on a development build.
 */
export function openPaintedLab(host: GeneratedTileHost, siteRoots: Iterable<object>, search: string): PaintedLab | null {
  if (!paintedLabAsked(search, import.meta.env.DEV)) return null;
  const look = { ...SPLAT_OCCLUSION, pushMetres: paintedPush(search) ?? SPLAT_OCCLUSION.pushMetres };
  const layout = paintedLayout(search);
  let state: PaintedLabState = {
    phase: 'loading', format: null, standIn: false, label: null, frame: IDENTITY, pointCount: null,
    layout, pushMetres: look.pushMetres, display: false, reason: null,
  };
  let splat: Entity | null = null;
  let display: SplatDisplay | null = null;
  let asset: Asset | null = null;
  let disposed = false;
  const roots = [...siteRoots] as Entity[];
  const depthOnly = layout === 'depth' ? layoutDepthOnly(roots, { app: host.app, look }) : null;
  const undrawn = layout === 'undrawn' ? layoutUndrawn(roots, host.app) : null;
  // Pieces and dressing can arrive after the drawing: what the site adds is taken in as it comes.
  const refreshing = setInterval(() => depthOnly?.refresh(), 1_000);
  const giveBack = (): void => {
    clearInterval(refreshing);
    depthOnly?.dispose();
    undrawn?.dispose();
  };
  void (async () => {
    try {
      const frame = await paintedFrame();
      const made = await splatAsset(host.app, frame);
      asset = made.asset;
      if (disposed) throw new Error('The lab closed before its splat arrived.');
      const entity = new (host.environmentRoot.constructor as new (name: string) => Entity)(PAINTED_LAB_MARKER);
      entity.setLocalPosition(frame[3]!, frame[7]!, frame[11]!);
      const [x, y, z, w] = rotationOf(frame);
      entity.setLocalRotation(x, y, z, w);
      host.environmentRoot.addChild(entity);
      entity.addComponent('gsplat', { asset: made.asset });
      splat = entity;
      const camera = host.camera.camera;
      if (camera !== undefined && camera !== null) display = splatsAfterToneMapping(entity, camera);
      state = {
        ...state, phase: 'drawn', format: made.format, standIn: made.format === 'ply', frame, pointCount: made.pointCount,
        label: made.format === 'ply' ? 'A layout-shaped stand-in splat, not paint.' : 'Invented appearance: a SOG held to the trained scene checks.',
      };
    } catch (error) {
      state = { ...state, phase: disposed ? 'disposed' : 'failed', reason: error instanceof Error ? error.message : String(error) };
      console.warn(error);
      // Without its splat the lab would leave nothing to see: the layout is given back as drawn.
      if (!disposed) giveBack();
    }
  })();
  const lab: PaintedLab = {
    state: () => ({ ...state, display: display?.active ?? false }),
    splat: () => splat,
    depthOnly: () => depthOnly?.instances ?? 0,
    undrawn: () => undrawn?.instances ?? 0,
    dispose() {
      disposed = true;
      giveBack();
      display?.dispose();
      display = null;
      splat?.destroy();
      splat = null;
      if (asset !== null) { asset.unload(); host.app.assets.remove(asset); asset = null; }
      state = { ...state, phase: 'disposed' };
      const held = (window as { __paintedLab?: PaintedLab }).__paintedLab;
      if (held === lab) delete (window as { __paintedLab?: PaintedLab }).__paintedLab;
    },
  };
  (window as { __paintedLab?: PaintedLab }).__paintedLab = lab;
  return lab;
}
