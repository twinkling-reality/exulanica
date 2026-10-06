/**
 * Redrawing the open generated world in another style pack, at once.
 *
 * `redrawWorldLook(pack)` draws the world the page has open in `pack`, a pack the host serves named
 * exactly (null: the default look), without opening the world again: the person stays where they
 * stand, and its people and traffic go on. The pack is read and its pieces fetched first, and a pack
 * the page cannot read leaves the world as it was and says why. The world's tiles are then loaded
 * again from the bytes the page already holds, in the new pack's light, and swapped on the same
 * host: the old light, dressing and ink are taken down before the new ones go up, and the traffic
 * draws its vehicles in the new pack's bodies from the next frame. It resolves with what it drew
 * and how long that took. Redraws run one after another, in the order they were asked for.
 *
 * Any part of the page may also ask by dispatching `WORLD_LOOK_REDRAW_EVENT` on the shell with the
 * pack as the event's detail; the shell's `data-world-look` attribute then states the look drawn,
 * and `WORLD_LOOK_REDRAW_ATTRIBUTE` the redraw's own result, its time included.
 * Nothing here changes what the world's appearance names: that is the appearance's own Apply.
 */

import type { WorldStylePackBinding } from '../world-style-api.js';

/** The event a part of the page dispatches on the shell to redraw the open world in a pack. */
export const WORLD_LOOK_REDRAW_EVENT = 'exulanica:world-look-redraw';
/** States, on the shell, what the last redraw an event asked for drew and how long it took. */
export const WORLD_LOOK_REDRAW_ATTRIBUTE = 'data-world-look-redraw';

/** What a redraw drew. */
export interface WorldLookRedraw {
  /** The pack drawn or asked for; null for the tile look. */
  readonly pack: string | null;
  readonly source: 'redraw';
  readonly drawn: boolean;
  /** Why the world was left as it was, or null. */
  readonly reason: string | null;
  /** From the ask to the new look attached, in milliseconds. */
  readonly elapsedMs: number;
}

/** An open world that can be redrawn. */
export interface RedrawableWorld {
  redraw(pack: WorldStylePackBinding | null): Promise<WorldLookRedraw>;
}

let open: RedrawableWorld | null = null;

/** The open world `redrawWorldLook` draws in, set while a generated world is attached. */
export function setRedrawableWorld(world: RedrawableWorld | null): void {
  open = world;
}

/** Whether `world` is the one open now, so taking one world down never clears another's. */
export function isRedrawableWorld(world: RedrawableWorld): boolean {
  return open === world;
}

/** Draw the open generated world in `pack` (null: the default look), at once. */
export async function redrawWorldLook(pack: WorldStylePackBinding | null): Promise<WorldLookRedraw> {
  if (open === null) {
    return { pack: pack?.packId ?? null, source: 'redraw', drawn: false, reason: 'No generated world is open', elapsedMs: 0 };
  }
  return open.redraw(pack);
}
