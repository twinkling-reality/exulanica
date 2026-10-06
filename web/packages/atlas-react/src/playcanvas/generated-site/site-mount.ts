import type { GeneratedTileAttachment, GeneratedTileHost, GeneratedTileMount } from '../generated-tile/binding-contract.js';
import { applyTileEnvironment } from '../generated-tile/environment.js';
import { TILE_LOOK_V1, type TileLook } from '../generated-tile/look.js';
import type { SiteDrawing } from './site-drawing.js';
import { siteNavigationWorld, siteStart } from './site-navigation.js';
import { drawSiteSlots, type DrawnSiteSlots } from './site-primitives.js';

/**
 * A world made from a world kind, ready for the binding: where a person walks, where they open and
 * how its drawing is attached to the scene.
 *
 * It meets the binding through the same seam a generated tile does (`GeneratedTileMount`): the
 * binding stands the person on `navigationWorld`, opens the camera at `start` and hands `attach`
 * the scene, and never reads the drawing. A site is lit by the generated tile's look (its sky,
 * sun, fog and tone mapping), so a site and a town are lit alike.
 */
export interface GeneratedSiteMount extends GeneratedTileMount {
  /** The kind the world was made from, in its own words, which the About panel says. */
  readonly kindLabel: string;
  readonly drawing: SiteDrawing;
}

/**
 * Dresses a drawn site, such as with a style pack: it runs once the slots are drawn and returns a
 * disposer, which runs before the slots are taken away and puts back everything it changed. It
 * never changes a slot, the walk or the seats; the mount stays the one owner of its entities.
 */
export type SiteDresser = (host: GeneratedTileHost, drawn: DrawnSiteSlots, drawing: SiteDrawing) => () => void;

export interface SiteMountOptions {
  /** The bytes the drawing was served as, which the attachment reports as transferred. */
  readonly servedBytes: number;
  readonly look?: TileLook;
  readonly dress?: SiteDresser;
}

/** The mount for a checked site drawing. */
export function siteMount(drawing: SiteDrawing, options: SiteMountOptions): GeneratedSiteMount {
  const look = options.look ?? TILE_LOOK_V1;
  const navigationWorld = siteNavigationWorld(drawing);
  return Object.freeze({
    kindLabel: drawing.kind.label,
    drawing,
    navigationWorld,
    start: siteStart(drawing, navigationWorld),
    attach(host: GeneratedTileHost): GeneratedTileAttachment {
      const environment = applyTileEnvironment(host.app, host.camera, look);
      const slots = drawSiteSlots(host.app.graphicsDevice, drawing);
      host.environmentRoot.addChild(slots.root);
      const undress = options.dress?.(host, slots, drawing) ?? null;
      let disposed = false;
      return {
        metrics: Object.freeze({
          tileName: `site:${drawing.worldId}`,
          triangles: slots.triangles,
          drawBatches: slots.drawn,
          transferredBytes: options.servedBytes,
          decodedTextureBytes: 0,
          unavailableSurfaces: 0,
          neighbours: Object.freeze([]),
          lookId: look.id,
          lookVersion: look.version,
        }),
        dispose(): void {
          if (disposed) return;
          disposed = true;
          undress?.();
          slots.destroy();
          environment.dispose();
        },
      };
    },
  });
}
