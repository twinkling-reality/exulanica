/**
 * The pictures on Your worlds' cards.
 *
 * A world's own picture is a frame of it as this browser last drew it: taken from the renderer's
 * canvas a few seconds after the world opens and again when the person leaves for Your worlds, kept
 * in this browser only (`localStorage`), never sent anywhere. Until a world has one, a world made
 * from a recipe shows a frame of a town made from that recipe, captured from the running
 * application and shipped with the page. Anything else shows the brand's blend in place of one. Storage that is full, blocked or absent only means no picture.
 */

import type { SavedWorldEntry } from '../world-entry-api.js';
import { recipePicture } from '../ui/recipe-pictures.js';

const KEY_PREFIX = 'exulanica.world-picture.v1.';
/** The size Your worlds draws it at most: behind the page, faded at its edges. */
const WIDTH = 1280;
const HEIGHT = 720;
const QUALITY = 0.7;


const storageKey = (entryId: string): string => `${KEY_PREFIX}${entryId}`;

function stored(entryId: string): string | null {
  try {
    const value = window.localStorage.getItem(storageKey(entryId));
    return value !== null && value.startsWith('data:image/') ? value : null;
  } catch {
    return null;
  }
}

/** The picture a card shows for `entry`, or null. */
export function worldPicture(entry: SavedWorldEntry): string | null {
  const own = stored(entry.entryId);
  if (own !== null) return own;
  const recipe = entry.generatedGround?.recipeKey ?? null;
  return recipe === null ? null : recipePicture(recipe);
}

/** What this reads of the renderer: its draw event, its frame request and its canvas. */
export interface PictureSource {
  readonly app: {
    on(name: 'postrender', handler: () => void): unknown;
    off(name: 'postrender', handler: () => void): unknown;
    renderNextFrame: boolean;
    readonly graphicsDevice: { readonly canvas: HTMLCanvasElement };
  };
}

/** Whether a frame holds a picture at all: a cleared or unlit buffer reads as one flat colour. */
function flat(context: CanvasRenderingContext2D): boolean {
  const { data } = context.getImageData(0, 0, WIDTH, HEIGHT);
  let low = 255;
  let high = 0;
  for (let i = 0; i < data.length; i += 4 * 97) {
    const level = (data[i]! + data[i + 1]! + data[i + 2]!) / 3;
    low = Math.min(low, level);
    high = Math.max(high, level);
  }
  return high - low < 12;
}

/**
 * Keep a frame of the world `entryId` names, read right after the renderer's next draw, the only
 * moment its drawing buffer still holds the frame. The renderer draws only frames it is asked
 * for, so one is asked for. A flat frame is not kept. Resolves true when one was kept.
 */
export function keepWorldPicture(source: PictureSource, entryId: string): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (kept: boolean): void => {
      if (settled) return;
      settled = true;
      source.app.off('postrender', onFrame);
      window.clearTimeout(timer);
      resolve(kept);
    };
    const onFrame = (): void => {
      try {
        const canvas = source.app.graphicsDevice.canvas;
        if (canvas.width === 0 || canvas.height === 0) return finish(false);
        const frame = document.createElement('canvas');
        frame.width = WIDTH;
        frame.height = HEIGHT;
        const context = frame.getContext('2d');
        if (context === null) return finish(false);
        // Cover: the middle of the frame at the card's proportions.
        const scale = Math.max(WIDTH / canvas.width, HEIGHT / canvas.height);
        const sw = WIDTH / scale;
        const sh = HEIGHT / scale;
        context.drawImage(canvas, (canvas.width - sw) / 2, (canvas.height - sh) / 2, sw, sh, 0, 0, WIDTH, HEIGHT);
        if (flat(context)) return finish(false);
        const url = frame.toDataURL('image/jpeg', QUALITY);
        window.localStorage.setItem(storageKey(entryId), url);
        finish(true);
      } catch {
        finish(false);
      }
    };
    // A page whose frames are throttled (a background tab) may draw none; never wait on it.
    const timer = window.setTimeout(() => finish(false), 2000);
    source.app.on('postrender', onFrame);
    source.app.renderNextFrame = true;
  });
}
