import * as pc from 'playcanvas';
import type { SiteInterior } from '@exulanica/atlas-core';
import type { StructuredSiteDrawing, SiteSlot } from './site-drawing.js';

/**
 * The inside of an indoor made place, drawn: a ceiling over its whole extent and the look's sun
 * turned into the light under it (`site-interior.ts` in atlas-core states both).
 *
 * THE CEILING IS NO PART OF THE DRAWING. It is made here from the extent and the height of what
 * the place draws and is never a slot: it is not listed, not walked, not picked, and what hides a
 * being is read from the drawing's slots, which it is none of. It stands beside the site's shapes,
 * under an entity named as a slot's is (`site-ceiling` holding `site-ceiling:shape`).
 */

export const SITE_CEILING = 'site-ceiling';

/**
 * The box a ceiling lies on: the one whose top is the highest among the boxes the place draws (in
 * practice a wall piece), the first of them where several are as high. Null where it draws no box.
 * The ceiling is drawn at that top and, once the place is dressed, in what that box is drawn in.
 */
export function ceilingRests(drawing: StructuredSiteDrawing): SiteSlot | null {
  let highest: SiteSlot | null = null;
  for (const slot of drawing.slots) {
    if (slot.primitive !== 'box') continue;
    if (highest === null || slot.positionMm[2] + slot.boxMm[2] > highest.positionMm[2] + highest.boxMm[2]) highest = slot;
  }
  return highest;
}

export interface DrawnCeiling {
  /** Holds `site-ceiling:shape`. */
  readonly root: pc.Entity;
  /** The top of what it lies on, millimetres over the site's floor. */
  readonly heightMm: number;
  destroy(): void;
}

/**
 * Draw the ceiling of an indoor place: a slab of the interior's thickness lying at `rests`'s top
 * over the whole extent, in the renderer's frame (east, up, south; a site's y is north). It casts
 * no shadow: the light is under it.
 */
export function drawSiteCeiling(drawing: StructuredSiteDrawing, rests: SiteSlot, interior: SiteInterior): DrawnCeiling {
  const heightMm = rests.positionMm[2] + rests.boxMm[2];
  const { widthMm, depthMm } = drawing.extent;
  const colour = new pc.StandardMaterial();
  colour.name = 'site-ceiling-colour';
  colour.diffuse = new pc.Color(0.78, 0.76, 0.72);
  colour.gloss = 0.2;
  colour.useMetalness = true;
  colour.metalness = 0;
  colour.update();
  const root = new pc.Entity(SITE_CEILING);
  const shape = new pc.Entity(`${SITE_CEILING}:shape`);
  shape.addComponent('render', { type: 'box', material: colour, castShadows: false, receiveShadows: false });
  shape.setLocalScale(widthMm / 1000, interior.ceilingThicknessMm / 1000, depthMm / 1000);
  root.addChild(shape);
  root.setLocalPosition(widthMm / 2000, (heightMm + interior.ceilingThicknessMm / 2) / 1000, -depthMm / 2000);
  return {
    root, heightMm,
    destroy(): void {
      root.destroy();
      colour.destroy();
    },
  };
}

/**
 * Turn a look's sun into a room's light: shining from the interior's tilt off straight down, turned
 * about the vertical, at its share of the sun's own strength and in its colour. A directional light
 * shines along its own down, so an unturned one shines straight down.
 */
export function lightFromAbove(sun: pc.Entity, interior: SiteInterior): void {
  const light = sun.light;
  if (!light) return;
  sun.setEulerAngles(interior.lightTiltDegrees, interior.lightTurnDegrees, 0);
  light.intensity = light.intensity * interior.lightSharePermille / 1000;
  const [r, g, b] = interior.lightSrgb8;
  light.color = new pc.Color(r / 255, g / 255, b / 255);
}
