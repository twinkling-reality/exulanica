/**
 * The pictures on Your worlds' cards.
 *
 * A card shows, first, the picture the server keeps of its world (`exulanica/world/saved_entry_pictures.py`),
 * while that picture shows the world as opening it draws it now, read by its digest and checked
 * against it. Else it shows the picture this browser kept: a frame of the world as this browser last
 * drew it, taken from the renderer's canvas a few seconds after the world opens and again when the
 * person leaves for Your worlds, kept in `localStorage`. Else a world made from a recipe shows a
 * frame of a town made from that recipe, captured from the running application and shipped with the
 * page. Anything else shows the brand's blend in place of one. Storage that is full, blocked or
 * absent only means no picture.
 *
 * The frame taken a few seconds after a world opens is its first view. That one is also put to the
 * server, so every browser shows it, unless the server's is current already. A frame of a world that
 * holds or held a photograph is never sent: the server refuses one, and the page never offers it.
 * The frame kept on leaving is where the person stood, so it stays in this browser.
 */

import type { SavedWorldEntry, SavedWorldEntryPicture } from '../world-entry-api.js';
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

/** The server's pictures this page has read and checked: each entry's digest and object URL. */
const served = new Map<string, { readonly sha256: string; readonly url: string }>();

/** The picture a card shows for `entry`, or null. */
export function worldPicture(entry: SavedWorldEntry): string | null {
  const kept = entry.picture;
  if (kept?.current === true) {
    const read = served.get(entry.entryId);
    if (read?.sha256 === kept.sha256) return read.url;
  }
  const own = stored(entry.entryId);
  if (own !== null) return own;
  const recipe = entry.generatedGround?.recipeKey ?? null;
  return recipe === null ? null : recipePicture(recipe);
}

/** The server's two picture calls (`WorldEntryClient.picture` and `putPicture`). */
export interface PictureServer {
  picture(entryId: string, sha256: string): Promise<Blob>;
  putPicture(entry: SavedWorldEntry, picture: Blob): Promise<SavedWorldEntryPicture>;
}

async function digestOf(bytes: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await bytes.arrayBuffer());
  return [...new Uint8Array(digest)].map((n) => n.toString(16).padStart(2, '0')).join('');
}

function hold(entryId: string, sha256: string, bytes: Blob): void {
  const previous = served.get(entryId);
  served.set(entryId, { sha256, url: URL.createObjectURL(bytes) });
  if (previous !== undefined) URL.revokeObjectURL(previous.url);
}

/**
 * Read the server's current picture of each of `entries` this page does not hold yet, keeping each
 * whose bytes are the digest the entry states. Resolves how many were added, so cards are drawn
 * again when any were. A picture that cannot be read or does not match is not shown.
 */
export async function readServedPictures(
  server: Pick<PictureServer, 'picture'>, entries: readonly SavedWorldEntry[],
): Promise<number> {
  const added = await Promise.all(entries.map(async (entry) => {
    const kept = entry.picture;
    if (kept?.current !== true || served.get(entry.entryId)?.sha256 === kept.sha256) return 0;
    try {
      const bytes = await server.picture(entry.entryId, kept.sha256);
      if (await digestOf(bytes) !== kept.sha256) return 0;
      hold(entry.entryId, kept.sha256, bytes.type === kept.mediaType ? bytes : new Blob([bytes], { type: kept.mediaType }));
      return 1;
    } catch {
      return 0;
    }
  }));
  return added.reduce<number>((sum, one) => sum + one, 0);
}

/**
 * Whether a frame of `entry` may be sent to the server at all: never one of a world that holds or
 * held a photograph (a personal source's, or one with a reference attached now or before), the
 * server's own rule, held here so such a frame never leaves this browser.
 */
export function mayPutPicture(entry: SavedWorldEntry): boolean {
  return entry.sourceKind !== 'personal' && entry.sourceAttachments.length === 0
    && (entry.previousSourceAttachments?.length ?? 0) === 0;
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
 * A frame of the world the renderer draws, read right after its next draw, the only moment its
 * drawing buffer still holds the frame, at the card's size. The renderer draws only frames it is
 * asked for, so one is asked for. Resolves null for a flat frame or none.
 */
function takeFrame(source: PictureSource): Promise<HTMLCanvasElement | null> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (frame: HTMLCanvasElement | null): void => {
      if (settled) return;
      settled = true;
      source.app.off('postrender', onFrame);
      window.clearTimeout(timer);
      resolve(frame);
    };
    const onFrame = (): void => {
      try {
        const canvas = source.app.graphicsDevice.canvas;
        if (canvas.width === 0 || canvas.height === 0) return finish(null);
        const frame = document.createElement('canvas');
        frame.width = WIDTH;
        frame.height = HEIGHT;
        const context = frame.getContext('2d');
        if (context === null) return finish(null);
        // Cover: the middle of the frame at the card's proportions.
        const scale = Math.max(WIDTH / canvas.width, HEIGHT / canvas.height);
        const sw = WIDTH / scale;
        const sh = HEIGHT / scale;
        context.drawImage(canvas, (canvas.width - sw) / 2, (canvas.height - sh) / 2, sw, sh, 0, 0, WIDTH, HEIGHT);
        finish(flat(context) ? null : frame);
      } catch {
        finish(null);
      }
    };
    // A page whose frames are throttled (a background tab) may draw none; never wait on it.
    const timer = window.setTimeout(() => finish(null), 2000);
    source.app.on('postrender', onFrame);
    source.app.renderNextFrame = true;
  });
}

function keepHere(frame: HTMLCanvasElement, entryId: string): boolean {
  try {
    window.localStorage.setItem(storageKey(entryId), frame.toDataURL('image/jpeg', QUALITY));
    return true;
  } catch {
    return false;
  }
}

/**
 * Keep a frame of the world `entryId` names in this browser, as the person leaves it. Resolves
 * true when one was kept.
 */
export async function keepWorldPicture(source: PictureSource, entryId: string): Promise<boolean> {
  const frame = await takeFrame(source);
  return frame !== null && keepHere(frame, entryId);
}

/** The first views this page has put, by entry and what they show, so one is put once. */
/**
 * A JPEG's bytes without its APP1 to APP15 and comment segments. A browser's encoder may write the
 * canvas's colour profile (APP2) or other metadata into the JPEG it makes, and the server keeps a
 * picture only as a bare JFIF frame (exulanica/world/style_pack_preview.py walks it whole and refuses
 * anything else). The scan is copied unchanged. Bytes that are not a JPEG laid out as expected come
 * back as they are, for the server to refuse.
 */
export function jpegWithoutMetadata(bytes: Uint8Array<ArrayBuffer>): Uint8Array<ArrayBuffer> {
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return bytes;
  const parts: Uint8Array<ArrayBuffer>[] = [bytes.subarray(0, 2)];
  let at = 2;
  while (at + 4 <= bytes.length && bytes[at] === 0xff && bytes[at + 1] !== 0xda) {
    const marker = bytes[at + 1]!;
    const length = (bytes[at + 2]! << 8) | bytes[at + 3]!;
    if (marker === 0xff || marker === 0xd8 || length < 2 || at + 2 + length > bytes.length) return bytes;
    const end = at + 2 + length;
    if (!((marker >= 0xe1 && marker <= 0xef) || marker === 0xfe)) parts.push(bytes.subarray(at, end));
    at = end;
  }
  if (at + 2 > bytes.length || bytes[at] !== 0xff || bytes[at + 1] !== 0xda) return bytes;
  parts.push(bytes.subarray(at));
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let written = 0;
  for (const part of parts) { out.set(part, written); written += part.length; }
  return out;
}

const put = new Set<string>();

/**
 * Keep a frame of `entry`'s first view in this browser, and put it to the server unless the
 * server's picture is current already or the world holds or held a photograph. A refusal (a
 * read-only copy refuses every write) leaves this browser's own picture. Resolves the server's
 * record of the picture it kept, or null.
 */
export async function keepFirstViewPicture(
  source: PictureSource, entry: SavedWorldEntry, server: Pick<PictureServer, 'putPicture'>,
): Promise<SavedWorldEntryPicture | null> {
  const frame = await takeFrame(source);
  if (frame === null) return null;
  keepHere(frame, entry.entryId);
  const shows = `${entry.entryId} ${entry.authoredVersionId} ${entry.authoredStateSha256} ${entry.styleVersionId}`;
  if (entry.picture?.current === true || !mayPutPicture(entry) || put.has(shows)) return null;
  put.add(shows);
  const encoded = await new Promise<Blob | null>((resolve) => frame.toBlob(resolve, 'image/jpeg', QUALITY));
  if (encoded === null) return null;
  const bytes = new Blob([jpegWithoutMetadata(new Uint8Array(await encoded.arrayBuffer()))], { type: 'image/jpeg' });
  try {
    const kept = await server.putPicture(entry, bytes);
    if (kept.sha256 === await digestOf(bytes)) hold(entry.entryId, kept.sha256, bytes);
    return kept;
  } catch {
    return null;
  }
}
