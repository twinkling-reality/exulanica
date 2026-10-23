// A History moment's picture (moment-framing.v3.json): drawn once, by the first page that shows the
// moment without one, and kept by the server under the moment and the framing recipe, so every
// later view on any computer reads the same picture. The moment is drawn in its own hidden scene
// preview of the saved world, never in the world this page shows: a moment may belong to another
// version, and drawing it must not move this page's camera or people. The preview reads the world as
// any preview does (GET only), its society as the moment recorded it, and answers with the frame;
// this page keeps it. Where the server does not keep it (a read-only page, a copy that refuses the
// write), the picture drawn is still shown, from the page's memory, for as long as the page is open.
// A moment of a world that holds or held a photograph, a moment without a recorded scene or of
// another version than the saved world opens, and a draw that never held the world make no picture
// (null): the page shows its quiet tile. Loading the preview is most of a picture's time (the app,
// its textures, the town and its people's looks: about 13 s of 14), so one preview of a version is
// kept while its moments are drawn and each next moment is asked of it (the stage, below).
import { MOMENT_ASK_MESSAGE, MOMENT_FRAMING, MOMENT_PICTURE_MESSAGE, MOMENT_SCENE_KEY } from './moment-framing.mjs';
import { momentPreviewAddress } from './front-door-routes.mjs';
import { FIRST_VIEW_SIZE, mayPutPicture, ownWorldPicture, readServedPictures } from '../../../web/packages/app/src/composition/world-pictures.ts';
import { HistoryPicturesClient, type HistoryPicture } from '../../../web/packages/app/src/world-pictures-api.ts';
import type { TransportOptions } from '@exulanica/graph-client';
import { WorldEntryClient, type SavedWorldEntry } from '../../../web/packages/app/src/world-entry-api.ts';

/**
 * A moment's picture as the page shows it: the one kept by the server, or one drawn here that the
 * server did not keep, which carries its own bytes (`unkept`) and is named by its moment.
 */
export type MomentPicture = HistoryPicture & { readonly unkept?: Blob };

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
 * How long a kept preview waits for its version's next moment before it is let go: long enough for
 * a page's moments, asked one after another, to reach it; short enough that a second copy of the
 * world does not stay loaded behind a page that has stopped asking.
 */
export const STAGE_IDLE_MS = 15_000;

/** A hidden preview frame at `size`: under the page, drawn, and never seen or reached. */
function previewFrame(size: readonly [number, number]): HTMLIFrameElement {
  const [width, height] = size;
  const frame = document.createElement('iframe');
  frame.title = 'A view of this world, drawn for its picture';
  frame.tabIndex = -1;
  frame.inert = true;
  frame.setAttribute('aria-hidden', 'true');
  Object.assign(frame.style, {
    position: 'fixed', left: '0', top: '0', width: `${width}px`, height: `${height}px`, border: '0',
    opacity: '0', pointerEvents: 'none', zIndex: '-1',
  });
  return frame;
}

/** How a preview answered an ask: its picture or null, and whether it asks to be replaced by a new one. */
interface Answer { readonly picture: Blob | null; readonly fresh: boolean }

/**
 * The answer `frame` gives to the ask named `key`; null where `signal` aborts or it outlasts its
 * bound. `start` sends the ask once the answer is listened for.
 */
function answerOf(frame: HTMLIFrameElement, key: string, start: () => void, signal?: AbortSignal): Promise<Answer | null> {
  return new Promise<Answer | null>((resolve) => {
    let settled = false;
    const finish = (answer: Answer | null): void => {
      if (settled) return;
      settled = true;
      window.removeEventListener('message', receive);
      signal?.removeEventListener('abort', aborted);
      window.clearTimeout(timer);
      try { sessionStorage.removeItem(MOMENT_SCENE_KEY + key); } catch { /* Nothing kept. */ }
      resolve(answer);
    };
    const receive = (event: MessageEvent): void => {
      if (event.origin !== location.origin || event.source !== frame.contentWindow) return;
      const data = event.data as { type?: unknown; key?: unknown; picture?: unknown; fresh?: unknown } | null;
      if (!data || data.type !== MOMENT_PICTURE_MESSAGE || data.key !== key) return;
      finish({ picture: data.picture instanceof Blob ? data.picture : null, fresh: data.fresh === true });
    };
    const aborted = (): void => finish(null);
    const timer = window.setTimeout(() => finish(null), DRAW_BOUND_MS);
    window.addEventListener('message', receive);
    signal?.addEventListener('abort', aborted, { once: true });
    start();
  });
}

/** The first ask of a new preview, left where its frame reads it as it loads; false where it cannot be. */
function leaveAsk(key: string, held: PreviewAsk): boolean {
  try {
    sessionStorage.setItem(MOMENT_SCENE_KEY + key, JSON.stringify(held));
    return true;
  } catch { return false; }
}

/**
 * A picture drawn in a hidden preview of `entry` loaded for it alone (the world's first view, at its
 * own size), answered as a JPEG or null. Resolves null if `signal` aborts or the draw outlasts its
 * bound.
 */
async function drawInPreview(entry: SavedWorldEntry, held: PreviewAsk, size: readonly [number, number], signal?: AbortSignal): Promise<Blob | null> {
  if (signal?.aborted) return null;
  const key = crypto.randomUUID();
  if (!leaveAsk(key, held)) return null;
  const frame = previewFrame(size);
  const answer = await answerOf(frame, key, () => {
    frame.src = momentPreviewAddress(entry.entryId, key, location.origin);
    document.body.append(frame);
  }, signal);
  frame.remove();
  return answer?.picture ?? null;
}

/**
 * The kept preview: one hidden frame of one version of one saved world (`name`), loaded by its first
 * ask and asked each next moment of that version by message. It is let go after STAGE_IDLE_MS without
 * an ask, when an ask is aborted or outlasts its bound, when it answers that it cannot draw another
 * (`fresh`), and before another world or version, or a first view, is drawn; the next ask loads a new
 * one.
 */
interface Stage {
  readonly name: string;
  readonly frame: HTMLIFrameElement;
  loaded: boolean;
  idle: number | undefined;
}
let stage: Stage | null = null;
/** Every hidden preview's draws, one at a time, so at most one preview is loaded and drawing. */
let draws: Promise<unknown> = Promise.resolve();

/** `draw` after every draw asked before it, whatever that one answered. */
function inTurn<T>(draw: () => Promise<T>): Promise<T> {
  const run = draws.then(draw, draw);
  draws = run.catch(() => null);
  return run;
}

function letGo(held: Stage): void {
  window.clearTimeout(held.idle);
  held.frame.remove();
  if (stage === held) stage = null;
}

/** One ask of the kept preview: its first loads it; a later one is posted to it. */
async function askStage(held: Stage, entry: SavedWorldEntry, ask: PreviewAsk, signal?: AbortSignal): Promise<Answer | null> {
  window.clearTimeout(held.idle);
  const key = crypto.randomUUID();
  const first = !held.loaded;
  if (first && !leaveAsk(key, ask)) return null;
  const answer = await answerOf(held.frame, key, () => {
    if (first) {
      held.loaded = true;
      held.frame.src = momentPreviewAddress(entry.entryId, key, location.origin);
      document.body.append(held.frame);
    } else {
      held.frame.contentWindow?.postMessage({ type: MOMENT_ASK_MESSAGE, key, held: ask }, location.origin);
    }
  }, signal);
  if (answer === null || answer.fresh) letGo(held);
  else held.idle = window.setTimeout(() => letGo(held), STAGE_IDLE_MS);
  return answer;
}

/**
 * A moment's picture drawn in the kept preview of its version, a new one where none is kept for it,
 * and once more in a new one where the kept one answers that it cannot draw another.
 */
async function drawInStage(entry: SavedWorldEntry, ask: PreviewAsk, signal?: AbortSignal, again = true): Promise<Blob | null> {
  if (signal?.aborted) return null;
  const name = `${entry.entryId} ${ask.versionId}`;
  if (stage !== null && stage.name !== name) letGo(stage);
  const held = stage ?? (stage = { name, frame: previewFrame(MOMENT_FRAMING.size_px as unknown as readonly [number, number]), loaded: false, idle: undefined });
  const answer = await askStage(held, entry, ask, signal);
  if (answer?.fresh && again && !signal?.aborted) return drawInStage(entry, ask, signal, false);
  return answer?.picture ?? null;
}

/** What the History page leaves its hidden preview: the version, and a moment's scene or the first view. */
interface PreviewAsk { readonly versionId: string; readonly scene: MomentForPicture['scene']; readonly first?: true }

/** The moment drawn as a JPEG, in the kept hidden preview of `entry`'s version (null where it cannot be drawn). */
export function drawMomentPicture({ entry, moment, signal }: {
  readonly entry: SavedWorldEntry; readonly moment: MomentForPicture; readonly signal?: AbortSignal;
}): Promise<Blob | null> {
  const versionId = moment.version_id ?? entry.authoredVersionId;
  if (!moment.scene || !Array.isArray(moment.scene.people) || moment.scene.people.length === 0) return Promise.resolve(null);
  if (versionId !== entry.authoredVersionId) return Promise.resolve(null);
  return inTurn(() => drawInStage(entry, { versionId, scene: moment.scene }, signal));
}

/**
 * The moment's picture: the one it has, else drawn here and kept by the server (or the one another
 * page kept first), else, where the server does not keep it, the one drawn here with its bytes
 * (`MomentPicture.unkept`). Null where none can be made: the page shows its quiet tile and does not
 * ask again in this view.
 */
export async function renderMomentPicture({ entry, moment, credentials, signal }: {
  readonly entry: SavedWorldEntry;
  readonly moment: MomentForPicture;
  readonly credentials: TransportOptions;
  readonly signal?: AbortSignal;
}): Promise<MomentPicture | null> {
  if (moment.picture) return moment.picture;
  if (!mayPutPicture(entry)) return null;
  const picture = await drawMomentPicture({ entry, moment, ...(signal ? { signal } : {}) });
  if (picture === null || signal?.aborted) return null;
  try {
    return await new HistoryPicturesClient({ ...credentials, ...(signal ? { signal } : {}) }).putMomentPicture(
      entry.worldId, moment.version_id ?? entry.authoredVersionId, moment.moment_id, MOMENT_FRAMING.recipe, picture,
    );
  } catch {
    if (signal?.aborted) return null;
    const [width, height] = MOMENT_FRAMING.size_px as unknown as readonly [number, number];
    return { sha256: `unkept:${moment.moment_id}`, width, height, unkept: picture };
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
  // Its own preview, at a first view's size, with no kept one beside it.
  const frame = await inTurn(() => {
    if (stage !== null) letGo(stage);
    return drawInPreview(entry, { versionId: entry.authoredVersionId, scene: null, first: true }, FIRST_VIEW_SIZE, signal);
  });
  if (frame === null || signal?.aborted) return null;
  if (mayPutPicture(entry)) {
    try { await server.putPicture(entry, frame); } catch { /* Shown here; kept by the next page that can. */ }
  }
  return URL.createObjectURL(frame);
}

