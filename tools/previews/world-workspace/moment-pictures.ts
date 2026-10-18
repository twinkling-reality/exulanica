// A History moment's picture (moment-framing.v3.json): drawn once, by the first page that shows the
// moment without one, and kept by the server under the moment and the framing recipe, so every
// later view on any computer reads the same picture. The moment is drawn in its own hidden scene
// preview of the saved world, never in the world this page shows: a moment may belong to another
// version, and drawing it must not move this page's camera or people. The preview reads the world as
// any preview does (GET only), its society as the moment recorded it, and answers with the frame;
// this page keeps it. A moment of a world that holds or held a photograph, a moment without a
// recorded scene or of another version than the saved world opens, and a draw that never held the
// world make no picture (null): the page shows its quiet tile.
import { MOMENT_FRAMING, MOMENT_PICTURE_MESSAGE, MOMENT_SCENE_KEY } from './moment-framing.mjs';
import { momentPreviewAddress } from './front-door-routes.mjs';
import { FIRST_VIEW_SIZE, mayPutPicture, ownWorldPicture, readServedPictures } from '/src/composition/world-pictures.ts';
import { HistoryPicturesClient, type HistoryPicture } from '/src/world-pictures-api.ts';
import type { TransportOptions } from '@exulanica/graph-client';
import { WorldEntryClient, type SavedWorldEntry } from '/src/world-entry-api.ts';

/** What a moment carries for its picture, as the moments read serves it. */
export interface MomentForPicture {
  readonly moment_id: string;
  readonly version_id?: string;
  readonly scene: { readonly people?: readonly unknown[] } | null;
  readonly picture?: HistoryPicture | null;
}

/** How long a moment's draw may take in all: the frame's load, its people and its frame. */
const DRAW_BOUND_MS = 30_000 + MOMENT_FRAMING.wait_ms.people + MOMENT_FRAMING.wait_ms.near + MOMENT_FRAMING.wait_ms.frame;

/**
 * A picture drawn in a hidden preview of `entry`: what `held` asks the preview for (a moment's scene,
 * or the world's first view), answered as a JPEG or null. Resolves null if `signal` aborts or the
 * draw outlasts its bound.
 */
function drawInPreview(entry: SavedWorldEntry, held: PreviewAsk, size: readonly [number, number], signal?: AbortSignal): Promise<Blob | null> {
  if (signal?.aborted) return Promise.resolve(null);
  const key = crypto.randomUUID();
  try {
    sessionStorage.setItem(MOMENT_SCENE_KEY + key, JSON.stringify(held));
  } catch { return Promise.resolve(null); }
  const [width, height] = size;
  const frame = document.createElement('iframe');
  frame.title = 'A view of this world, drawn for its picture';
  frame.tabIndex = -1;
  frame.inert = true;
  frame.setAttribute('aria-hidden', 'true');
  // Under the page, at the picture's size: drawn, and never seen or reached.
  Object.assign(frame.style, {
    position: 'fixed', left: '0', top: '0', width: `${width}px`, height: `${height}px`, border: '0',
    opacity: '0', pointerEvents: 'none', zIndex: '-1',
  });
  return new Promise<Blob | null>((resolve) => {
    let settled = false;
    const finish = (picture: Blob | null): void => {
      if (settled) return;
      settled = true;
      window.removeEventListener('message', receive);
      signal?.removeEventListener('abort', aborted);
      window.clearTimeout(timer);
      frame.remove();
      try { sessionStorage.removeItem(MOMENT_SCENE_KEY + key); } catch { /* Nothing kept. */ }
      resolve(picture);
    };
    const receive = (event: MessageEvent): void => {
      if (event.origin !== location.origin || event.source !== frame.contentWindow) return;
      const data = event.data as { type?: unknown; key?: unknown; picture?: unknown } | null;
      if (!data || data.type !== MOMENT_PICTURE_MESSAGE || data.key !== key) return;
      finish(data.picture instanceof Blob ? data.picture : null);
    };
    const aborted = (): void => finish(null);
    const timer = window.setTimeout(() => finish(null), DRAW_BOUND_MS);
    window.addEventListener('message', receive);
    signal?.addEventListener('abort', aborted, { once: true });
    frame.src = momentPreviewAddress(entry.entryId, key, location.origin);
    document.body.append(frame);
  });
}

/** What the History page leaves its hidden preview: the version, and a moment's scene or the first view. */
interface PreviewAsk { readonly versionId: string; readonly scene: MomentForPicture['scene']; readonly first?: true }

/** The moment drawn as a JPEG, in a hidden preview of `entry` (null where it cannot be drawn). */
export function drawMomentPicture({ entry, moment, signal }: {
  readonly entry: SavedWorldEntry; readonly moment: MomentForPicture; readonly signal?: AbortSignal;
}): Promise<Blob | null> {
  const versionId = moment.version_id ?? entry.authoredVersionId;
  if (!moment.scene || !Array.isArray(moment.scene.people) || moment.scene.people.length === 0) return Promise.resolve(null);
  if (versionId !== entry.authoredVersionId) return Promise.resolve(null);
  return drawInPreview(entry, { versionId, scene: moment.scene }, MOMENT_FRAMING.size_px as unknown as readonly [number, number], signal);
}

/**
 * The moment's kept picture: the one it has, else drawn here and kept by the server (or the one
 * another page kept first). Null where none can be made or kept: the page shows its quiet tile and
 * does not ask again in this view.
 */
export async function renderMomentPicture({ entry, moment, credentials, signal }: {
  readonly entry: SavedWorldEntry;
  readonly moment: MomentForPicture;
  readonly credentials: TransportOptions;
  readonly signal?: AbortSignal;
}): Promise<HistoryPicture | null> {
  if (moment.picture) return moment.picture;
  if (!mayPutPicture(entry)) return null;
  const picture = await drawMomentPicture({ entry, moment, ...(signal ? { signal } : {}) });
  if (picture === null || signal?.aborted) return null;
  try {
    return await new HistoryPicturesClient({ ...credentials, ...(signal ? { signal } : {}) }).putMomentPicture(
      entry.worldId, moment.version_id ?? entry.authoredVersionId, moment.moment_id, MOMENT_FRAMING.recipe, picture,
    );
  } catch {
    return null;
  }
}

/**
 * How the world began, as a picture's address: the world's kept picture (the one its cards show,
 * read from the server where it holds a current one, else the one this browser kept); else its
 * first view drawn here once in a hidden preview and kept by the server as the world's picture, so
 * its cards show it too. Null where none can be shown: the page shows its quiet tile. A stock
 * picture of the world's kind is not its picture and is not used.
 */
export async function renderBeginningPicture({ entry, credentials, signal }: {
  readonly entry: SavedWorldEntry;
  readonly credentials: TransportOptions;
  readonly signal?: AbortSignal;
}): Promise<string | null> {
  const server = new WorldEntryClient({ ...credentials, ...(signal ? { signal } : {}) });
  if (entry.picture?.current === true) await readServedPictures(server, [entry]);
  const kept = ownWorldPicture(entry);
  if (kept !== null) return kept;
  const frame = await drawInPreview(entry, { versionId: entry.authoredVersionId, scene: null, first: true }, FIRST_VIEW_SIZE, signal);
  if (frame === null || signal?.aborted) return null;
  if (mayPutPicture(entry)) {
    try { await server.putPicture(entry, frame); } catch { /* Shown here; kept by the next page that can. */ }
  }
  return URL.createObjectURL(frame);
}

