// What the world view gives History and the record pages beyond reading (history.ts's HistoryHost): its writes, H7's
// keep and H12's GitHub question, sent through the workspace's own credentials as the app's other writes are (a
// read-only copy gives none); and their pictures, one source for every page over this world: a still of the view,
// how the world began, each moment's kept picture and each character's portrait (MOTION's renderers).
// The app's modules are named by their paths, which the preview serves as /src/… (one module each) and the tests load.
import { accessHeaders } from '../../../web/packages/app/src/config.ts';
import { frameJpeg, ownWorldPicture, takeFrame, type PictureSource } from '../../../web/packages/app/src/composition/world-pictures.ts';
import { HistoryPicturesClient } from '../../../web/packages/app/src/world-pictures-api.ts';
import type { SavedWorldEntry } from '../../../web/packages/app/src/world-entry-api.ts';
import type { TransportOptions } from '@exulanica/graph-client';
import { inhabitantCatalog, type CharacterCatalog } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';
import { MOMENT_FRAMING } from './moment-framing.mjs';
import { renderBeginningPicture, renderMomentPicture, type MomentForPicture, type MomentPicture } from './moment-pictures.ts';
import type { ThingCrowdFigures, ThingLayer } from '../../../web/packages/atlas-react/src/playcanvas/things/index.ts';
import { lookDigest, lookOfSubject, renderPortrait } from './portrait-pictures.ts';

type Access = Parameters<typeof accessHeaders>[0] & { readonly baseUrl: string };

/** POST or DELETE `path` with an optional JSON body: the answer's status and body (null where it has none). */
export function historyWrite(access: Access, signal: AbortSignal) {
  return async (method: 'POST' | 'DELETE', path: string, body?: unknown): Promise<{ readonly status: number; readonly body: any }> => {
    const response = await fetch(`${access.baseUrl}${path}`, {
      method, credentials: 'same-origin', signal,
      headers: { ...accessHeaders(access, method), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    return { status: response.status, body: await response.json().catch(() => null) };
  };
}

/** What draws a being by its own look: the world's things (MountedThings), its layer and the crowd's figures. */
export interface BeingThings {
  readonly layer: Pick<ThingLayer, 'drawKindPicture'>;
  readonly crowdFigures: Pick<ThingCrowdFigures, 'drawnAs'>;
}

/**
 * A being's portrait (one the world draws by a look of its own: a creature, a knight), never a face:
 * its whole figure, in the kind and look the crowd draws it by, from the build tray's three-quarter
 * view, framed round so it fills the portrait's circle, over a clear ground (the round frame's own
 * shows through), the portrait recipe's `size_px` square, as a PNG data URL. Drawn once a look a page
 * by the world's things; null where it has no look of its own, the world draws no things, or the
 * figure cannot be drawn.
 */
export async function beingPortrait({ being, things }: {
  readonly being: Parameters<ThingCrowdFigures['drawnAs']>[0];
  readonly things: BeingThings | null;
}): Promise<string | null> {
  const drawn = things?.crowdFigures.drawnAs(being) ?? null;
  if (things === null || drawn === null) return null;
  // The society's name for the kind, as a placed thing names it.
  const { kind: named } = drawn;
  const kind = named.source === 'workspace' ? { source: 'workspace' as const, sha256: named.sha256 } : { kind: named.kind, version: named.version, sha256: named.sha256 };
  const side = MOMENT_FRAMING.portrait.size_px;
  return things.layer.drawKindPicture(kind, { width: side, height: side }, { look: drawn.look, round: true }).catch(() => null);
}

/**
 * The world's canvas as the pictures read it: a frame source, asked to draw, a saved world's
 * society, which says who it draws as one of its people (AuthoredRegionSociety.drawnAsPerson) and
 * what the others are (inhabitantOf), and the world's things, which draw those others by their own
 * looks (beingPortrait).
 */
export type StillSource = PictureSource & {
  invalidate?(): void;
  readonly authoredSociety?: {
    drawnAsPerson?(id: string): boolean | null;
    inhabitantOf?(id: string): Parameters<BeingThings['crowdFigures']['drawnAs']>[0] | null;
  } | null;
  __workspaceThings?(): BeingThings | null;
};

export interface RecordPictures {
  /** Takes a still of the world as it is drawn now, in place of the last one; its address, or the last where none. */
  takeStill(): Promise<string | null>;
  /** The last still's address, or null. */
  still(): string | null;
  /** How the world began: its kept picture, else its first view drawn once (MOTION's renderBeginningPicture). */
  beginningPicture(signal?: AbortSignal): Promise<string | null>;
  /** A kept picture's address (read once as bytes: an object address), or null where it cannot be read. */
  pictureAddress(picture: MomentPicture | null | undefined): Promise<string | null>;
  /** A kept picture's address where it is read already; else null, its read starts and `changed` follows. */
  pictureNow(picture: MomentPicture | null | undefined): string | null;
  /** A moment's missing picture, made once and kept (MOTION's renderMomentPicture), one draw at a time. */
  renderMomentPicture(moment: MomentForPicture, signal?: AbortSignal): Promise<MomentPicture | null>;
  /**
   * A moment's picture address where it is known; else null, its picture is read or made and `changed` follows.
   * `lead`: the open page's own picture, drawn ahead of every draw still waiting (never stopping the one drawn now).
   */
  momentNow(moment: MomentForPicture | null | undefined, lead?: boolean): string | null;
  /** A character's round portrait, kept or made once from its look; null where it cannot be made. */
  portrait(subjectId: string, signal?: AbortSignal): Promise<string | null>;
  /** A portrait's address where it is made already; else null, it is made and `changed` follows. */
  portraitNow(subjectId: string): string | null;
  /** A page closed: every address made since is revoked and forgotten, and reads still running are dropped. */
  release(): void;
  /** The world is going: released, and nothing more is read or made. */
  dispose(): void;
}

/**
 * The pictures of one world for its pages. Addresses are object addresses made from the bytes read, or from a
 * moment's picture drawn here that the server did not keep (the preview's
 * reader does not pass an image's bytes to an <img>), each made once per page and kept until the page closes or
 * the world goes (release, dispose); a draw never makes or revokes one. Drawing a moment or a portrait makes a
 * stage of its own, so they are made one at a time. A read that fails answers null and is not asked again until
 * the next page; a portrait waits for the world's people to be served.
 */
export function recordPictures({ entry, credentials, source, changed = () => {} }: {
  readonly entry: SavedWorldEntry;
  readonly credentials: TransportOptions;
  readonly source: StillSource;
  readonly changed?: () => void;
}): RecordPictures {
  let lifetime = new AbortController();
  let disposed = false;
  const made = new Set<string>();
  const addresses = new Map<string, Promise<string | null>>();
  const known = new Map<string, string | null>();
  const rendered = new Map<string, MomentPicture | null>();
  const rendering = new Set<string>();
  const portraits = new Map<string, Promise<string | null>>();
  const portraitKnown = new Map<string, string | null>();
  let still: string | null = null;
  /** The draws waiting their turn (a moment's draw names its moment), and whether one is being drawn now. */
  const waiting: { readonly moment: string | null; readonly start: () => void }[] = [];
  let drawing = false;

  const keep = (address: string) => {
    made.add(address);
    return address;
  };
  const client = (signal: AbortSignal) => new HistoryPicturesClient({ ...credentials, signal });
  /**
   * One draw at a time, each after the one drawn now, whatever that one answered: in the order asked, except the open
   * page's own moment (`lead`), which goes ahead of every draw still waiting, the newest lead first. A decision opened
   * over its day so waits for one draw at most, not for every picture of the day's rows.
   */
  function serial<T>(task: () => Promise<T>, moment: string | null = null, lead = false): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const turn = { moment, start: () => { void Promise.resolve().then(task).then(resolve, reject).finally(nextDraw); } };
      if (lead) waiting.unshift(turn);
      else waiting.push(turn);
      if (!drawing) nextDraw();
    });
  }
  function nextDraw(): void {
    const turn = waiting.shift();
    drawing = turn !== undefined;
    turn?.start();
  }
  /** A moment asked before and still waiting, moved ahead of every other draw waiting: the open page now shows it. */
  function hasten(moment: string): void {
    const at = waiting.findIndex((turn) => turn.moment === moment);
    if (at > 0) waiting.unshift(...waiting.splice(at, 1));
  }
  function people(): CharacterCatalog | null {
    try {
      return inhabitantCatalog(source.app as Parameters<typeof inhabitantCatalog>[0]);
    } catch {
      return null;
    }
  }

  function pictureAddress(picture: MomentPicture | null | undefined): Promise<string | null> {
    if (disposed || !picture?.sha256) return Promise.resolve(null);
    const held = addresses.get(picture.sha256);
    if (held) return held;
    const own = lifetime.signal;
    // A picture drawn here that the server did not keep is shown from its own bytes, for this page only.
    const unkept = picture.unkept;
    const reading = unkept ? Promise.resolve(keep(URL.createObjectURL(unkept)))
      : client(own).picture(entry.worldId, picture.sha256)
        .then((bytes) => (own.aborted ? null : keep(URL.createObjectURL(bytes))), () => null);
    addresses.set(picture.sha256, reading);
    void reading.then((address) => {
      if (own.aborted) return;
      known.set(picture.sha256, address);
      if (address) changed();
    });
    return reading;
  }

  function portrait(subjectId: string): Promise<string | null> {
    if (disposed) return Promise.resolve(null);
    const held = portraits.get(subjectId);
    if (held) return held;
    const own = lifetime.signal;
    const making = serial(async () => {
      if (own.aborted) return null;
      // A face from the people catalog only for one the world draws as one of its people: one drawn by a
      // look of its own (a creature, a knight) is drawn by that look, never with a face, or keeps the
      // quiet circle where it cannot be. A world with no saved society (a generated town) draws everyone so.
      const society = source.authoredSociety;
      const person = society ? society.drawnAsPerson?.(subjectId) ?? null : true;
      if (person === false) {
        const being = society?.inhabitantOf?.(subjectId) ?? null;
        return being === null ? null : beingPortrait({ being, things: source.__workspaceThings?.() ?? null });
      }
      const catalog = person === null ? null : people();
      // Before that is known, or before the people are served, there is no look to draw; asked again by the next draw.
      if (catalog === null) {
        portraits.delete(subjectId);
        return null;
      }
      const look = (() => { try { return lookOfSubject(subjectId, catalog); } catch { return null; } })();
      if (look === null) return null;
      const digest = lookDigest(look);
      const kept = await client(own).portraits(entry.worldId, [digest], MOMENT_FRAMING.portrait.recipe)
        .then((read) => read.get(digest) ?? null, () => null);
      const picture = await renderPortrait({ worldId: entry.worldId, look, catalog, credentials, kept, signal: own });
      return picture && !own.aborted ? pictureAddress(picture) : null;
    });
    portraits.set(subjectId, making);
    void making.then((address) => {
      if (own.aborted || portraits.get(subjectId) !== making) return;
      portraitKnown.set(subjectId, address);
      if (address) changed();
    });
    return making;
  }

  function pictureNow(picture: MomentPicture | null | undefined): string | null {
    if (!picture?.sha256) return null;
    if (known.has(picture.sha256)) return known.get(picture.sha256) ?? null;
    void pictureAddress(picture);
    return null;
  }

  function renderMoment(moment: MomentForPicture, signal?: AbortSignal, lead = false): Promise<MomentPicture | null> {
    if (disposed) return Promise.resolve(null);
    const own = lifetime.signal;
    return serial(() => (own.aborted || signal?.aborted ? Promise.resolve(null)
      : renderMomentPicture({ entry, moment, credentials, signal: signal ?? own })), moment.moment_id, lead);
  }

  function release() {
    lifetime.abort();
    lifetime = new AbortController();
    for (const address of made) URL.revokeObjectURL(address);
    made.clear();
    addresses.clear();
    known.clear();
    rendered.clear();
    rendering.clear();
    portraits.clear();
    portraitKnown.clear();
    still = null;
  }

  return {
    async takeStill() {
      if (disposed) return null;
      const own = lifetime.signal;
      source.invalidate?.();
      const frame = await takeFrame(source, { width: Math.max(1, Math.round(innerWidth)), height: Math.max(1, Math.round(innerHeight)) }).catch(() => null);
      const bytes = frame && !own.aborted ? await frameJpeg(frame, 0.8).catch(() => null) : null;
      if (!bytes || own.aborted) return still;
      if (still) {
        URL.revokeObjectURL(still);
        made.delete(still);
      }
      still = keep(URL.createObjectURL(bytes));
      return still;
    },
    still: () => still,
    async beginningPicture(signal) {
      if (disposed) return null;
      const own = lifetime.signal;
      const address = await renderBeginningPicture({ entry, credentials, signal: signal ?? own }).catch(() => null);
      // The world's own kept picture is the cards' and stays theirs; a first view drawn here is this page's.
      if (address && address !== ownWorldPicture(entry)) {
        if (own.aborted) {
          URL.revokeObjectURL(address);
          return null;
        }
        keep(address);
      }
      return address;
    },
    pictureAddress,
    pictureNow,
    renderMomentPicture: renderMoment,
    momentNow(moment, lead = false) {
      if (!moment) return null;
      if (moment.picture) return pictureNow(moment.picture);
      const id = moment.moment_id;
      if (rendered.has(id)) return pictureNow(rendered.get(id));
      if (rendering.has(id)) {
        if (lead) hasten(id);
      } else if (!disposed) {
        rendering.add(id);
        const own = lifetime.signal;
        void renderMoment(moment, own, lead).then((picture) => {
          if (own.aborted) return;
          rendered.set(id, picture);
          if (picture) void pictureAddress(picture);
        });
      }
      return null;
    },
    portrait: (subjectId) => portrait(subjectId),
    portraitNow(subjectId) {
      if (portraitKnown.has(subjectId)) return portraitKnown.get(subjectId) ?? null;
      void portrait(subjectId);
      return null;
    },
    release,
    dispose() {
      release();
      disposed = true;
    },
  };
}

/** History's picture hooks (history.ts's HistoryHost) from the world's pictures. */
export function historyHooks(pictures: RecordPictures) {
  return {
    still: () => pictures.still(),
    beginningPicture: (signal: AbortSignal) => pictures.beginningPicture(signal),
    pictureAddress: (picture: MomentPicture) => pictures.pictureAddress(picture),
    renderMomentPicture: (moment: MomentForPicture, signal: AbortSignal) => pictures.renderMomentPicture(moment, signal),
    portrait: (subjectId: string, signal: AbortSignal) => pictures.portrait(subjectId, signal),
  };
}
