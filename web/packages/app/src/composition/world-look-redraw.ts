/**
 * Redrawing the open world (a generated town, or a site made from a world kind) in another style
 * pack, at once.
 *
 * `redrawWorldLook(pack)` draws the world the page has open in `pack`, a pack the host serves named
 * exactly (null: the default look), without opening the world again: the person stays where they
 * stand, and its people and traffic go on. The pack is read and its pieces fetched first, and a pack
 * the page cannot read leaves the world as it was and says why. The world's tiles, as the page
 * loaded them, are then attached again in the new pack's light (nothing is fetched, verified or
 * decoded a second time) and swapped on the same host: the old light, dressing and ink are taken
 * down before the new ones go up, and the traffic draws its vehicles in the new pack's bodies from
 * the next frame. It resolves with what it drew and how long that took. Redraws run one after
 * another, in the order they were asked for.
 *
 * Any part of the page may also ask by dispatching `WORLD_LOOK_REDRAW_EVENT` on the shell with the
 * pack as the event's detail. However a redraw is asked, the shell's `data-world-look` attribute
 * then states the look drawn, and `WORLD_LOOK_REDRAW_ATTRIBUTE` the redraw's own result, its time
 * included.
 * Nothing here changes what the world's appearance names: that is the appearance's own Apply.
 */

import type { GeneratedTileAttachment, GeneratedTileHost } from '@exulanica/atlas-react/generated-tile';
import type { WorldLookChoice } from '../world-look.js';
import type { WorldStylePackBinding } from '../world-style-api.js';

/** States, on the shell, the look the open world is drawn in: the pack asked for, what chose it, whether it was drawn and why not. */
export const WORLD_LOOK_ATTRIBUTE = 'data-world-look';
/** The event a part of the page dispatches on the shell to redraw the open world in a pack. */
export const WORLD_LOOK_REDRAW_EVENT = 'exulanica:world-look-redraw';
/** States, on the shell, what the last redraw drew and how long it took, however it was asked. */
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

/** The open world `redrawWorldLook` draws in, set while a world drawn in packs is attached. */
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

/** The look a world is drawn in: the pack asked for (null for the tile look), what chose it, whether it was drawn and why not. */
export interface WorldLookState {
  readonly pack: string | null;
  readonly source: 'address' | 'world' | 'default' | 'redraw';
  readonly drawn: boolean;
  readonly reason: string | null;
  /** The world's own setting, stated only for a world that has one: whether it was drawn over the pack, and why not. */
  readonly setting?: { readonly drawn: boolean; readonly reason: string | null };
}

/** What can be drawn on a host and taken down again: a generated world's tiles, or a site. */
export interface LookDrawing {
  attach(host: GeneratedTileHost): GeneratedTileAttachment;
}

/**
 * An open world's drawing whose look can be swapped while it stays mounted, as `redrawWorldLook`
 * asks. Each redraw waits for the one before it and reads the pack first (`relook`, which throws
 * when the pack cannot be read, leaving the world as it was); no pack is the default, the one the
 * host lists so. Then the old look is taken down before the new one goes up on the same host (each
 * sets the scene's light, and taking one down after the other went up would undo the new one):
 * `drawingOf` names what to attach, and `swapped` is told once it is up. While attached, the world
 * is the open one, asked by `redrawWorldLook` (the Look sheet) or by `WORLD_LOOK_REDRAW_EVENT` on the
 * shell, and every redraw, however it was asked, puts its result on the shell
 * (`WORLD_LOOK_REDRAW_ATTRIBUTE`).
 */
export function swappableDrawing<T extends { readonly look: WorldLookState }>(
  first: LookDrawing,
  relook: (choice: WorldLookChoice) => Promise<T>,
  drawingOf: (next: T) => LookDrawing,
  swapped: (next: T) => void,
  shell: Element,
): LookDrawing {
  let current = first;
  let host: GeneratedTileHost | null = null;
  let attachment: GeneratedTileAttachment | null = null;
  let queue: Promise<unknown> = Promise.resolve();
  const redrawable: RedrawableWorld = {
    redraw(pack) {
      const run = queue.then(async (): Promise<WorldLookRedraw> => {
        const started = performance.now();
        const { DEFAULT_WORLD_LOOK } = await import('../world-look.js');
        let packId = pack?.packId ?? DEFAULT_WORLD_LOOK;
        const result = (drawn: boolean, reason: string | null): WorldLookRedraw => ({
          pack: packId, source: 'redraw', drawn, reason, elapsedMs: Math.round(performance.now() - started),
        });
        let next: T;
        try {
          next = await relook(pack === null
            ? { packId, manifestSha256: null, source: 'default' }
            : {
              packId: pack.packId, manifestSha256: pack.manifestSha256, source: 'redraw',
              ...(pack.setting === undefined ? {} : { setting: pack.setting.document }),
            });
        } catch (error) {
          return result(false, error instanceof Error ? error.message : String(error));
        }
        packId = next.look.pack;
        if (host === null) return result(false, 'The world was taken down before its new look was ready');
        attachment?.dispose();
        current = drawingOf(next);
        attachment = current.attach(host);
        swapped(next);
        return result(next.look.drawn, null);
      }).then((done) => {
        shell.setAttribute(WORLD_LOOK_REDRAW_ATTRIBUTE, JSON.stringify(done));
        return done;
      });
      queue = run;
      return run;
    },
  };
  const onRedraw = (event: Event): void => {
    const detail = (event as CustomEvent<WorldStylePackBinding | null>).detail ?? null;
    void redrawable.redraw(detail);
  };
  return {
    attach(next: GeneratedTileHost): GeneratedTileAttachment {
      host = next;
      attachment = current.attach(next);
      setRedrawableWorld(redrawable);
      shell.addEventListener(WORLD_LOOK_REDRAW_EVENT, onRedraw);
      let metrics = attachment.metrics;
      return {
        get metrics() {
          metrics = attachment?.metrics ?? metrics;
          return metrics;
        },
        get animating() {
          return attachment?.animating ?? false;
        },
        dispose() {
          shell.removeEventListener(WORLD_LOOK_REDRAW_EVENT, onRedraw);
          if (isRedrawableWorld(redrawable)) setRedrawableWorld(null);
          attachment?.dispose();
          attachment = null;
          host = null;
        },
      };
    },
  };
}
