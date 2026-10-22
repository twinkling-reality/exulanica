// A portrait of a look (moment-framing.v2.json's portrait recipe): the look drawn alone on the
// character stage, its head and shoulders cut from the frame and kept by the server under the look's
// digest and the recipe, in the world, so History, cards and the character page show the same one.
// A resident's look is the one the world draws: drawn from the people catalog it serves, by the
// resident's id. Drawn one at a time, on a stage of its own that is destroyed after.
import {
  CharacterPreview, inhabitantLook, lookSha256, type CharacterCatalog, type CharacterLook,
} from '../../../web/packages/atlas-react/src/playcanvas/index.ts';
import type { TransportOptions } from '@exulanica/graph-client';
import { MOMENT_FRAMING } from './moment-framing.mjs';
import { frameJpeg, takeFrame, type PictureSource } from '/src/composition/world-pictures.ts';
import { workspaceCharacterLoader } from '/src/character-catalog.ts';
import { HistoryPicturesClient, type HistoryPicture } from '/src/world-pictures-api.ts';
import type { MomentPicture } from './moment-pictures.ts';

const PORTRAIT = MOMENT_FRAMING.portrait;

/** A resident's look as the world draws them, from the people catalog it serves. */
export function lookOfSubject(subjectId: string, catalog: CharacterCatalog): CharacterLook {
  return inhabitantLook(catalog, { societyId: '', branchId: '', inhabitantId: subjectId });
}

/** The look's digest, the name its portrait is kept under. */
export const lookDigest = (look: CharacterLook): string => lookSha256(look);

/** The look drawn alone, head and shoulders, as the JPEG the server keeps (null where it could not be drawn). */
export async function drawPortrait({ look, catalog, credentials, signal }: {
  readonly look: CharacterLook; readonly catalog: CharacterCatalog; readonly credentials: TransportOptions; readonly signal?: AbortSignal;
}): Promise<Blob | null> {
  const stage = document.createElement('canvas');
  Object.assign(stage.style, {
    position: 'fixed', left: '0', top: '0', width: `${PORTRAIT.stage_px}px`, height: `${PORTRAIT.stage_px}px`,
    opacity: '0', pointerEvents: 'none', zIndex: '-1',
  });
  stage.setAttribute('aria-hidden', 'true');
  document.body.append(stage);
  let preview: CharacterPreview | null = null;
  try {
    preview = await CharacterPreview.create(stage, workspaceCharacterLoader(credentials));
    preview.setReducedMotion(true);
    preview.setZoom(PORTRAIT.zoom);
    await Promise.race([
      preview.showLook(look, catalog),
      new Promise((_, refuse) => setTimeout(() => refuse(new Error('portrait timed out')), PORTRAIT.wait_ms)),
    ]);
    if (signal?.aborted) return null;
    // The stage keeps no drawing buffer, so its frame is read right after a draw, as a world's is.
    const source = (preview as unknown as { readonly app: PictureSource['app'] }).app;
    const whole = await takeFrame({ app: source }, { width: stage.width, height: stage.height });
    if (whole === null) return null;
    // Cut the head and shoulders from the frame on the recipe's ground: a square `crop.side` of the
    // frame wide, its top `crop.above_head` of its side above the top of the head and centred on the
    // head (headOf), or at `crop.top`, `crop.left` of the frame where no head is found.
    const frame = document.createElement('canvas');
    frame.width = frame.height = PORTRAIT.size_px;
    const context = frame.getContext('2d');
    if (context === null) return null;
    context.fillStyle = PORTRAIT.background;
    context.fillRect(0, 0, PORTRAIT.size_px, PORTRAIT.size_px);
    const side = whole.width * PORTRAIT.crop.side;
    const head = headOf(whole, side * 0.4, PORTRAIT.crop.ground_tolerance);
    const top = head === null ? whole.height * PORTRAIT.crop.top : Math.max(0, head.top - side * PORTRAIT.crop.above_head);
    const left = head === null ? whole.width * PORTRAIT.crop.left : head.centre - side / 2;
    context.drawImage(whole, left, top, side, side, 0, 0, PORTRAIT.size_px, PORTRAIT.size_px);
    return await frameJpeg(frame, 0.8);
  } catch {
    return null;
  } finally {
    preview?.destroy();
    stage.remove();
  }
}

/**
 * Where the head is in a frame of a look drawn alone on its stage: the first row from the top that
 * holds anything but the stage's ground (its top left pixel, within `tolerance` on every channel),
 * and the middle, in x, of what is not ground in the `depth` pixels below it; null where the frame is
 * ground all the way down.
 */
export function headOf(frame: HTMLCanvasElement, depth: number, tolerance: number): { top: number; centre: number } | null {
  const context = frame.getContext('2d');
  if (context === null) return null;
  const { data, width, height } = context.getImageData(0, 0, frame.width, frame.height);
  const ground = [data[0]!, data[1]!, data[2]!];
  const figure = (row: number, column: number): boolean => {
    const at = (row * width + column) * 4;
    return ground.some((value, channel) => Math.abs(data[at + channel]! - value) > tolerance);
  };
  let top = -1;
  for (let row = 0; row < height && top < 0; row += 1) {
    for (let column = 0; column < width; column += 1) if (figure(row, column)) { top = row; break; }
  }
  if (top < 0) return null;
  let sum = 0, count = 0;
  for (let row = top; row < Math.min(height, top + depth); row += 1) {
    for (let column = 0; column < width; column += 1) if (figure(row, column)) { sum += column; count += 1; }
  }
  return { top, centre: count > 0 ? sum / count : width / 2 };
}

/**
 * The look's kept portrait in the world: the one kept, else drawn here and kept (or the one another
 * page kept first), else, where the server does not keep it (a read-only page), the one drawn here
 * with its bytes, shown from the page's memory (`MomentPicture.unkept`). Null where none can be drawn.
 */
export async function renderPortrait({ worldId, look, catalog, credentials, kept = null, signal }: {
  readonly worldId: string;
  readonly look: CharacterLook;
  readonly catalog: CharacterCatalog;
  readonly credentials: TransportOptions;
  readonly kept?: HistoryPicture | null;
  readonly signal?: AbortSignal;
}): Promise<MomentPicture | null> {
  if (kept) return kept;
  const picture = await drawPortrait({ look, catalog, credentials, ...(signal ? { signal } : {}) });
  if (picture === null || signal?.aborted) return null;
  try {
    return await new HistoryPicturesClient({ ...credentials, ...(signal ? { signal } : {}) })
      .putPortrait(worldId, lookDigest(look), PORTRAIT.recipe, picture);
  } catch {
    if (signal?.aborted) return null;
    return { sha256: `unkept:portrait:${lookDigest(look)}`, width: PORTRAIT.size_px, height: PORTRAIT.size_px, unkept: picture };
  }
}
