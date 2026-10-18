import { isScenePreview, scenePreviewAddress } from './front-door-routes.mjs';
import { StaticMeshPicker } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';
import { MOMENT_FRAMING, MOMENT_PICTURE_MESSAGE, MOMENT_SCENE_KEY, foregroundShare, framingInSight, momentSociety, overviewDistance } from './moment-framing.mjs';
import { frameJpeg, takeFrame } from '/src/composition/world-pictures.ts';
import type { SavedWorldEntry } from '/src/world-entry-api.ts';

// The front door's live background: the app drawing the chosen saved world in an inert frame, its
// camera turning gently. The camera moves; the world's own time does not.

const READY = 'exulanica.front-door.scene-ready';
const previewPage = isScenePreview(new URL(location.href));
const live = new URLSearchParams(location.search).get('livePreview') === '1';
const momentKey = previewPage ? new URLSearchParams(location.search).get('moment') : null;

/**
 * The moment this preview draws, as the History page left it: the version it belongs to and the
 * scene it recorded, or the world's first view (`first`, no scene). Null on any other preview, or
 * where nothing was left.
 */
const moment: { readonly versionId: string; readonly scene: unknown; readonly first?: boolean } | null = (() => {
  if (!momentKey) return null;
  try {
    const held = JSON.parse(sessionStorage.getItem(MOMENT_SCENE_KEY + momentKey) ?? 'null');
    return held && typeof held.versionId === 'string' ? held : null;
  } catch { return null; }
})();

/** Whether this page is a scene preview. The workspace's world view never mounts in one. */
export function scenePreviewPage(): boolean {
  return previewPage;
}

// A preview has no write path, including during the app's own start-up, and shows the world alone.
if (previewPage) {
  document.body.classList.add('ux-capture-world');
  const original = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (method !== 'GET') {
      console.warn('Read-only world preview refused a ' + method + ' request.');
      return Promise.resolve(new Response(JSON.stringify({ detail: 'The world preview is read-only.' }), { status: 405, headers: { 'Content-Type': 'application/json' } }));
    }
    // A moment's preview reads its version's society as the moment's tick drew it.
    const address = new URL(input instanceof Request ? input.url : String(input), location.href);
    if (moment !== null && address.pathname.endsWith(`/world/versions/${encodeURIComponent(moment.versionId)}/society`)) {
      return original(input, init).then(async (response) => {
        if (!response.ok) return response;
        const drawn = momentSociety(await response.json(), moment.scene);
        return new Response(JSON.stringify(drawn), { status: response.status, headers: { 'Content-Type': 'application/json' } });
      });
    }
    return original(input, init);
  };
}

/**
 * How far a ray (render space, metres, a unit direction) runs before it meets what the scene draws,
 * or Infinity, up to `most` metres. Tested against the triangles of every visible static mesh, a low
 * wall or a bench as much as a building; skinned and instanced meshes (people, scattered plants, a
 * painted splat) are not tested.
 */
function sceneHit(app: any): (origin: readonly [number, number, number], direction: readonly [number, number, number], most?: number) => number {
  const picker = new StaticMeshPicker();
  const instances = new Set<any>();
  for (const layer of app.scene?.layers?.layerList ?? []) {
    if (layer.name === 'UI' || layer.name === 'Skybox' || layer.name === 'Immediate') continue;
    for (const instance of layer.meshInstances ?? []) {
      if (instance.instancingCount > 0 || instance.gsplatInstance || instance.skinInstance) continue;
      instances.add(instance);
    }
  }
  return (origin, direction, most = Infinity) => {
    let nearest = Infinity;
    for (const instance of instances) {
      const hit = picker.pick(instance, origin, direction, Math.min(most, nearest));
      if (hit !== null && hit < nearest) nearest = hit;
    }
    return nearest;
  };
}

/**
 * Whether nothing the scene draws stands between `from` and `to` (render space, metres), short of
 * the last `own` metres before `to`, where the subject's own body is.
 */
function sceneSight(hit: ReturnType<typeof sceneHit>, own: number): (from: { x: number; y: number; z: number }, to: { x: number; y: number; z: number }) => boolean {
  return (from, to) => {
    const along = [to.x - from.x, to.y - from.y, to.z - from.z] as const;
    const length = Math.hypot(...along);
    if (length <= own) return true;
    const limit = length - own;
    return !(hit([from.x, from.y, from.z], [along[0] / length, along[1] / length, along[2] / length], limit) < limit);
  };
}

/** The camera's vertical field of view for a picture, in degrees, set on the preview's own camera. */
function useLens(binding: any, fovDeg: number): void {
  const camera = binding.camera?.camera;
  if (!camera) return;
  camera.horizontalFov = false;
  camera.fov = fovDeg;
}

/**
 * A moment's picture, in the preview's own renderer: once the moment's subjects are drawn, the
 * camera the recipe frames them with, from the first of its sides and heights that sees them whole,
 * then the first frame that holds the world, at the recipe's size, posted to the page that asked as
 * a JPEG (or null where none could be made).
 */
async function drawMoment(renderer: any, key: string): Promise<void> {
  const answer = (picture: Blob | null) => window.parent.postMessage({ type: MOMENT_PICTURE_MESSAGE, key, picture }, location.origin);
  const binding = renderer.atlas?.binding;
  const society = binding?.authoredSociety ?? binding?.ownedDistrict ?? null;
  const people = (moment?.scene as { people?: { id: string }[] } | undefined)?.people ?? [];
  const subjects = people.slice(0, 2).map((one) => one.id);
  const wait = MOMENT_FRAMING.wait_ms;
  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
  // How the world began: the made world seen whole from above (the recipe's `beginning`: its pitch,
  // lens and margin), looking the way its first view looks, at the size a world's picture is kept.
  if (binding && moment?.first === true) {
    const overview = overviewPose(binding, MOMENT_FRAMING.beginning);
    if (overview !== null) { useLens(binding, MOMENT_FRAMING.beginning.fov_deg); binding.controls.setView(overview, 'altitude'); }
    for (let waited = 0; waited < wait.frame; waited += wait.retry) {
      binding.invalidate();
      const frame = await takeFrame(binding);
      if (frame !== null) return answer(await frameJpeg(frame));
      await sleep(wait.retry);
    }
    return answer(null);
  }
  if (!binding || !society || subjects.length === 0) return answer(null);
  const anchors = () => subjects.map((id) => {
    const at = { x: 0, y: 0, z: 0, set(x: number, y: number, z: number) { this.x = x; this.y = y; this.z = z; return this; } };
    return society.groundOf(id, at) ? { x: at.x, y: at.y, z: at.z } : null;
  });
  let drawn = anchors();
  for (let waited = 0; drawn.some((one) => one === null) && waited < wait.people; waited += wait.retry) {
    binding.invalidate();
    await sleep(wait.retry);
    drawn = anchors();
  }
  // The pose is in the visitor's world and the feet in render space, which starts where the world
  // was last re-centred: the camera's own pose and position say by how much.
  const eye = binding.camera.getPosition(), held = binding.controls.state;
  const offset = { x: held.x - eye.x, y: held.y - eye.y, z: held.z - eye.z };
  // Each subject as drawn: how tall, which way it faces (the crowd's heading, which follows the
  // recorded path and a seat or partner), so the camera stands where every face shows, and the
  // outline of the box it is drawn by (its points nearest far points all round), so a subject not
  // framed is never cut by the frame's edge.
  const outlineOf = (id: string) => {
    const points: { x: number; y: number; z: number }[] = [];
    const ground = drawn[subjects.indexOf(id)];
    for (let turn = 0; ground && turn < 16 && society.nearestPointOf; turn += 1) {
      for (const rise of [-1000, 1000]) {
        const from = { x: ground.x + Math.cos((turn * Math.PI) / 8) * 1000, y: ground.y + rise, z: ground.z + Math.sin((turn * Math.PI) / 8) * 1000 };
        const out = { x: 0, y: 0, z: 0, set(x: number, y: number, z: number) { this.x = x; this.y = y; this.z = z; return this; } };
        if (society.nearestPointOf(id, from, out)) points.push({ x: out.x, y: out.y, z: out.z });
      }
    }
    return points;
  };
  const feet = drawn.map((one, at) => (one === null ? null : {
    ...one, height: society.heightOf?.(subjects[at]!) ?? NaN, heading: society.headingOf?.(subjects[at]!) ?? NaN, outline: outlineOf(subjects[at]!),
  })).filter((one): one is { x: number; y: number; z: number; height: number; heading: number; outline: { x: number; y: number; z: number }[] } => one !== null);
  const hit = sceneHit(binding.app);
  const sighted = framingInSight(feet, sceneSight(hit, MOMENT_FRAMING.sight.own_m), MOMENT_FRAMING,
    (pose: { x: number; y: number; z: number; yaw: number; pitch: number }, framed: readonly object[]) => foregroundShare(pose, framed, hit));
  if (sighted === null) return answer(null);
  useLens(binding, MOMENT_FRAMING.fov_deg);
  binding.controls.setView({ ...sighted, x: sighted.x + offset.x, y: sighted.y + offset.y, z: sighted.z + offset.z }, 'altitude');
  const [width, height] = MOMENT_FRAMING.size_px;
  for (let waited = 0; waited < wait.frame; waited += wait.retry) {
    binding.invalidate();
    const frame = await takeFrame(binding, { width, height });
    if (frame !== null) return answer(await frameJpeg(frame));
    await sleep(wait.retry);
  }
  return answer(null);
}

/**
 * The made world seen whole from above: its walkable field's centre on its ground, from `pitch_deg`
 * above the horizon, back until the field and what is round it fit the frame with the recipe's margin
 * (overviewDistance), along the first view's own heading. In the controls' space, as the navigation
 * world is. Null before the world is drawn.
 */
function overviewPose(binding: any, beginning: typeof MOMENT_FRAMING.beginning): { x: number; y: number; z: number; yaw: number; pitch: number } | null {
  const world = binding.navigationWorld, held = binding.controls?.state;
  if (!world || !held || !Number.isFinite(world.fieldRadius)) return null;
  const { x, z } = world.centre;
  const ground = world.surface?.sample(x, z)?.height ?? 0;
  const distance = overviewDistance(world.fieldRadius, beginning, 16 / 9);
  const pitch = (beginning.pitch_deg * Math.PI) / 180;
  const yaw = held.yaw;
  const back = distance * Math.cos(pitch);
  return { x: x + Math.sin(yaw) * back, y: ground + distance * Math.sin(pitch), z: z + Math.cos(yaw) * back, yaw, pitch: -pitch };
}

/** Camera motion in the preview's own renderer, held to the saved world it was asked for. */
export function mountScenePreview({ state, renderer }: { readonly state: { readonly activeWorldEntry?: SavedWorldEntry | null }; readonly renderer: any }): void {
  if (momentKey !== null && window.parent !== window) { void drawMoment(renderer, momentKey); return; }
  if (!live || window.parent === window) return;
  const entry = state.activeWorldEntry, binding = renderer.atlas?.binding;
  if (!entry || !binding) return;
  const pose = { ...binding.controls.state };
  const pins = { entryId: entry.entryId, versionId: entry.authoredVersionId, styleVersionId: entry.styleVersionId, stateSha: entry.authoredStateSha256 };
  let frame = 0;
  const origin = performance.now();
  const tick = (now: number) => {
    if (!document.hidden) {
      const elapsed = (now - origin) / 1000;
      binding.controls.setView({ ...pose, yaw: pose.yaw + Math.sin(elapsed / 13) * .035, pitch: pose.pitch + Math.sin(elapsed / 19) * .006 }, 'altitude');
      binding.invalidate();
    }
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  requestAnimationFrame(() => requestAnimationFrame(() => window.parent.postMessage({ type: READY, ...pins }, location.origin)));
  window.addEventListener('pagehide', () => cancelAnimationFrame(frame), { once: true });
}

/** The background: the chosen world's picture while its live preview loads, then the live preview. */
export function createScenePreview(root: HTMLElement) {
  const field = document.createElement('div'); field.className = 'ux-entry-image'; field.setAttribute('aria-hidden', 'true'); root.prepend(field);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let enabled = !previewPage && !reduced.matches, selected: SavedWorldEntry | null = null;
  let still: HTMLElement | null = null, current: HTMLIFrameElement | null = null, waiting: HTMLIFrameElement | null = null;
  let disposed = false, sequence = 0;
  const retire = (node: HTMLElement | null) => {
    if (!node) return;
    node.style.opacity = '0'; setTimeout(() => node.remove(), 650);
  };
  const stopLive = () => { current?.remove(); waiting?.remove(); current = null; waiting = null; root.dataset.nativePreview = 'paused'; };
  const startLive = () => {
    if (!selected || !enabled || disposed) return;
    waiting?.remove();
    const iframe = document.createElement('iframe'); iframe.className = 'ux-entry-live'; iframe.title = selected.title; iframe.tabIndex = -1; iframe.inert = true;
    iframe.src = scenePreviewAddress(selected.entryId, location.origin); iframe.style.opacity = '0';
    waiting = iframe; field.append(iframe); root.dataset.nativePreview = 'loading';
  };
  const receive = (event: MessageEvent) => {
    if (event.origin !== location.origin || !selected || event.data?.type !== READY) return;
    if (event.source !== waiting?.contentWindow) return;
    const data = event.data;
    if (data.entryId !== selected.entryId || data.versionId !== selected.authoredVersionId || data.styleVersionId !== selected.styleVersionId || data.stateSha !== selected.authoredStateSha256) return;
    const old = current; current = waiting; waiting = null; current!.style.opacity = '1'; retire(old); root.dataset.nativePreview = 'ready';
  };
  window.addEventListener('message', receive);
  const preference = () => { if (reduced.matches) { enabled = false; stopLive(); } };
  reduced.addEventListener('change', preference);
  return {
    get enabled() { return enabled; },
    select(entry: SavedWorldEntry, picture: string | null) {
      selected = entry; const serial = ++sequence;
      const next = document.createElement('div'); next.className = 'ux-entry-still'; next.style.backgroundImage = picture ? `url("${picture}")` : 'none'; next.style.opacity = '0'; field.append(next);
      const prior = still; still = next;
      requestAnimationFrame(() => { if (serial !== sequence || disposed) { next.remove(); return; } next.style.opacity = '1'; retire(prior); });
      if (current) retire(current); current = null;
      startLive();
    },
    toggle() { enabled = !enabled; if (enabled) startLive(); else stopLive(); return enabled; },
    dispose() { disposed = true; ++sequence; stopLive(); window.removeEventListener('message', receive); reduced.removeEventListener('change', preference); field.remove(); },
  };
}
