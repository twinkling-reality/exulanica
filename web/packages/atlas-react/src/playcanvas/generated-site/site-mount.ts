import { materialOfLeaf, unknownSurfaceLeaf, type RoofForms, type SurfaceMaterials } from '@exulanica/atlas-core';
import type * as pc from 'playcanvas';
import type { GeneratedTileAttachment, GeneratedTileHost, GeneratedTileMount } from '../generated-tile/binding-contract.js';
import { applyTileEnvironment } from '../generated-tile/environment.js';
import { TILE_LOOK_V1, type TileLook } from '../generated-tile/look.js';
import type { SiteDrawing, SiteSlot } from './site-drawing.js';
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
 *
 * THE GROUND BEYOND A SITE IS THE SITE'S OWN. A look that states a ground beyond the world draws a
 * plane out to its reach in its own colour, which for a town is the lawn its streets end in. A site
 * that is open to the sky stands on its base ground (the one surface its drawing lays over its
 * whole extent), so that plane is drawn in whatever the base ground is drawn in, once it is dressed
 * (the pack's own surface, its leaf's material or the family's default), and lies just under it:
 * the sand of a desert outpost runs to the horizon. It reads the base ground only, never a zone or
 * an area at the site's edge. An indoor site, and a site whose drawing lays no ground over its
 * whole extent, keep the look's own.
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
  /**
   * The surface material catalog the engine's own colours are read from, leaf by leaf. A dresser
   * carries its own; with no dresser the mount says on the canvas how many slots wear a material
   * and which look roles named none (`data-site-materials`, `data-site-unknown-looks`), as a
   * dresser does.
   */
  readonly materials?: SurfaceMaterials;
  /** The roof form catalog a roof is shaped by, through its material; none draws every roof as served. */
  readonly roofForms?: RoofForms;
}

/**
 * How far under a site's ground the ground beyond it lies, in metres: three of the drawing's own
 * layer steps (6 mm each, `LAYER_MM` in the server's drawing), so the two never share a depth where
 * the site's ground ends, and no step shows at its edge from standing height.
 */
export const SITE_BEYOND_DROP_M = 0.018;

/**
 * The slot a site's base ground is drawn by: the ground plane its drawing lays over its whole
 * extent, at the level of the site's origin. Null where the drawing lays none.
 */
export function baseGroundSlot(drawing: SiteDrawing): SiteSlot | null {
  const { widthMm, depthMm } = drawing.extent;
  return drawing.slots.find((slot) => slot.family === 'ground' && slot.primitive === 'plane'
    && slot.boxMm[0] === widthMm && slot.boxMm[1] === depthMm
    && slot.positionMm[0] * 2 === widthMm && slot.positionMm[1] * 2 === depthMm && slot.positionMm[2] === 0) ?? null;
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
      const materials = options.materials ?? null;
      const slots = drawSiteSlots(host.app.graphicsDevice, drawing, materials, options.roofForms ?? null);
      host.environmentRoot.addChild(slots.root);
      const undress = options.dress?.(host, slots, drawing) ?? null;
      // The ground beyond: the look's own plane, drawn in what the dressed base ground is drawn in.
      const beyond = environment.ground?.render?.meshInstances[0] ?? null;
      const base = drawing.extent.enclosure === 'open' ? baseGroundSlot(drawing) : null;
      const baseShape = base === null ? null : (slots.entities.get(base.identity)?.findByName(`${base.identity}:shape`) as pc.Entity | null);
      const worn = baseShape?.render?.meshInstances[0]?.material ?? null;
      const edged = beyond !== null && worn !== null && environment.ground !== null;
      if (edged) {
        beyond.material = worn;
        const at = environment.ground!.getPosition();
        environment.ground!.setPosition(at.x, -SITE_BEYOND_DROP_M, at.z);
      }
      const canvas = host.app.graphicsDevice.canvas as HTMLCanvasElement | undefined;
      if (edged && canvas?.dataset !== undefined) canvas.dataset['siteGroundBeyond'] = base!.lookRole;
      const said = options.dress === undefined && materials !== null && canvas?.dataset !== undefined;
      if (said) {
        const drawn = drawing.slots.filter((slot) => slots.entities.has(slot.identity));
        canvas.dataset['siteMaterials'] = String(drawn.filter((slot) => slot.leaf !== 'default' && materialOfLeaf(materials, slot.family, slot.leaf) !== null).length);
        canvas.dataset['siteUnknownLooks'] = JSON.stringify([...new Set(drawn.filter((slot) => unknownSurfaceLeaf(materials, slot.lookRole)).map((slot) => slot.lookRole))].sort());
      }
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
          // The look's plane goes with the environment below; only what the canvas said is taken back here.
          if (edged && canvas?.dataset !== undefined) delete canvas.dataset['siteGroundBeyond'];
          if (said) {
            delete canvas.dataset['siteMaterials'];
            delete canvas.dataset['siteUnknownLooks'];
          }
          undress?.();
          slots.destroy();
          environment.dispose();
        },
      };
    },
  });
}
