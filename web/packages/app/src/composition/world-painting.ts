/**
 * A world's painting at its first view.
 *
 * Where a world keeps a painting of its first view (`../world-paintings-api.ts`), the world opens at the camera that
 * painting was painted from, and the painting lies over the live view at that camera, so the first thing a person
 * sees is the world painted from its own words, on its exact layout. A painting is kept under the view `first` only
 * once it is passed as holding that view against the live world there; a world whose painting does not hold opens on
 * the live world and keeps its painting for its card. The first input of any kind that reaches the world (a key, a
 * click or a drag on it, a wheel) makes the painting give way to the live world beneath, which stands exactly where
 * the painting showed it, since that input acts on the live world. For as long as it shows it says what painted it and
 * that it is invented appearance, on a dark pill above everything the page lays over the world.
 *
 * The painting shows only while the live camera stands where it was painted from, looking the same way through the
 * same lens: a world the page opens at a camera of its own (the view a person left it at earlier in the session, a
 * field of view of their choosing) never shows it, and a camera moved by anything but the person's own input (a page,
 * a following) takes it down at once.
 *
 * The camera's lens keeps its vertical field of view whatever the window's shape, so the painting is drawn the
 * height of the canvas and as wide as its own shape makes it, centred: on a wider window the live world shows at its
 * sides, on a narrower one the painting's sides are cut, and either way it lines up with what the camera sees.
 */

import type { GeneratedTileAttachment, GeneratedTileHost, LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';
import { el } from '../ui/dom.js';
import { PAINTING_LABEL, type WorldPainting } from '../world-paintings-api.js';

/** The attribute the painting's layer carries, so a page opening another world takes it down first. */
export const WORLD_PAINTING_ATTRIBUTE = 'data-world-painting';
/** The view a run names a world's first view by. */
export const FIRST_VIEW = 'first';
/** How long the painting takes to give way to the live world. */
export const GIVE_WAY_MS = 700;
/** How near the live camera stands to where the painting was painted from while the painting shows over it. */
export const PAINTING_STANDING = Object.freeze({ metres: 0.1, radians: 0.01, fovDeg: 0.5 });

/** The live camera as the painting checks it: its world transform (column-major) and vertical field of view. */
export interface LiveCamera {
  readonly transform: ArrayLike<number>;
  readonly fovDeg: number;
}

/** Whether `camera` stands where `painting` was painted from, looking the same way through the same lens. */
export function standsAtPainting(painting: WorldPainting, camera: LiveCamera): boolean {
  const painted = painting.camera;
  if (painted === null) return false;
  const m = camera.transform;
  const [x, y, z] = painted.position;
  if (Math.hypot(m[12]! - x, m[13]! - y, m[14]! - z) > PAINTING_STANDING.metres) return false;
  // The camera looks along its -Z axis; the painting's way is its yaw (0 looks north, -Z) and pitch.
  const level = Math.cos(painted.pitch);
  const along = m[8]! * Math.sin(painted.yaw) * level - m[9]! * Math.sin(painted.pitch) + m[10]! * Math.cos(painted.yaw) * level;
  if (Math.acos(Math.min(1, Math.max(-1, along))) > PAINTING_STANDING.radians) return false;
  return Math.abs(camera.fovDeg - painted.fovDeg) <= PAINTING_STANDING.fovDeg;
}

/** The newest painting of the world's first view that states its camera, or none. */
export function firstViewPainting(paintings: readonly WorldPainting[]): WorldPainting | null {
  return paintings.find((painting) => painting.view === FIRST_VIEW && painting.camera !== null) ?? null;
}

/** Where the world opens to stand where its painting was painted from: the renderer's start pose. */
export function paintedStart(painting: WorldPainting): { x: number; y: number; z: number; yaw: number; pitch: number } | null {
  const camera = painting.camera;
  if (camera === null) return null;
  const [x, y, z] = camera.position;
  return { x, y, z, yaw: camera.yaw, pitch: camera.pitch };
}

/**
 * The tile, and the camera it is drawn under once the world has placed it: null before. The camera stands where it was
 * made until the world's first update places it at its start, some frames after the tile is attached, so it counts
 * from the first time it stands anywhere else.
 */
export function placedCamera(tile: LoadedGeneratedTile): { tile: LoadedGeneratedTile; camera: () => LiveCamera | null } {
  let seen: GeneratedTileHost['camera'] | null = null;
  let unplaced: readonly number[] | null = null;
  return {
    tile: {
      ...tile,
      attach(host: GeneratedTileHost): GeneratedTileAttachment {
        seen = host.camera;
        unplaced = Array.from(host.camera.getWorldTransform().data);
        return tile.attach(host);
      },
    },
    camera: () => {
      if (seen?.camera == null) return null;
      const transform = seen.getWorldTransform().data;
      if (unplaced !== null) {
        if (unplaced.every((value, at) => value === transform[at])) return null;
        unplaced = null;
      }
      return { transform, fovDeg: seen.camera.fov };
    },
  };
}

/** What the painting says while it shows. */
export function paintingWords(painting: WorldPainting): string {
  return painting.painter === null
    ? `Painted from this world's words · ${PAINTING_LABEL}`
    : `Painted by ${painting.painter} from this world's words · ${PAINTING_LABEL}`;
}

/**
 * Lay `picture` (the painting's bytes, an object URL, let go of when the painting goes) over `canvas` until the person
 * first moves, for as long as `standing` (`standsAtPainting` against the live camera, null while the world has no
 * camera yet) does not say the camera stands elsewhere. Returns a function that takes it down at once (the world
 * closed, another opened).
 */
export function showWorldPainting(
  canvas: HTMLCanvasElement,
  painting: WorldPainting,
  picture: string,
  reducedMotion: boolean,
  standing: () => boolean | null,
): () => void {
  document.querySelectorAll(`[${WORLD_PAINTING_ATTRIBUTE}]`).forEach((node) => node.remove());
  if (standing() === false) {
    URL.revokeObjectURL(picture);
    return () => undefined;
  }
  const image = el('img', {
    src: picture,
    alt: '',
    style: 'position:absolute;top:0;left:50%;height:100%;width:auto;transform:translateX(-50%);display:block',
  });
  const fade = `transition:opacity ${reducedMotion ? 0 : GIVE_WAY_MS}ms ease`;
  const layer = el('div', {
    [WORLD_PAINTING_ATTRIBUTE]: painting.sha256,
    role: 'img',
    'aria-label': paintingWords(painting),
    style: `position:fixed;inset:0;overflow:hidden;pointer-events:none;opacity:1;${fade}`,
  }, [image]);
  // The words go above the world's own interface, so they stay readable on their own dark pill, and below a page laid
  // over the whole world (Create and Integrations, the world's opening at the overlay's level), which hides the painting
  // too: the dock's level.
  const words = el('p', {
    [WORLD_PAINTING_ATTRIBUTE]: painting.sha256,
    text: paintingWords(painting),
    style: 'position:fixed;right:16px;bottom:72px;z-index:var(--z-dock);margin:0;padding:4px 10px;border-radius:6px;'
      + 'pointer-events:none;background:rgba(0,0,0,0.72);color:#f2efe8;'
      + `font:13px/1.4 var(--ui-font-body, system-ui, sans-serif);opacity:1;${fade}`,
  });
  canvas.after(layer);
  document.body.append(words);
  let gone = false;
  let leaving = false;
  let frame = 0;
  const takeDown = (): void => {
    if (gone) return;
    gone = true;
    cancelAnimationFrame(frame);
    window.removeEventListener('keydown', onKey, true);
    canvas.removeEventListener('pointerdown', giveWay);
    canvas.removeEventListener('wheel', giveWay);
    layer.remove();
    words.remove();
    URL.revokeObjectURL(picture);
  };
  function giveWay(): void {
    if (gone || leaving) return;
    leaving = true;
    if (reducedMotion) {
      takeDown();
      return;
    }
    layer.style.opacity = '0';
    words.style.opacity = '0';
    window.setTimeout(takeDown, GIVE_WAY_MS);
  }
  // A key reaches the world when nothing of the page holds the focus: the page itself or the world's canvas.
  const onKey = (event: KeyboardEvent): void => {
    const target = event.target;
    if (target === document.body || target === canvas || target === document.documentElement || target === window) giveWay();
  };
  window.addEventListener('keydown', onKey, true);
  canvas.addEventListener('pointerdown', giveWay);
  canvas.addEventListener('wheel', giveWay, { passive: true });
  // A camera that leaves where the painting was painted from before any input of the person's takes it down at once:
  // what it shows is no longer there to give way to.
  const watch = (): void => {
    if (gone || leaving) return;
    if (standing() === false) takeDown();
    else frame = requestAnimationFrame(watch);
  };
  frame = requestAnimationFrame(watch);
  return takeDown;
}
