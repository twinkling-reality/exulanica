import * as pc from 'playcanvas';
import type { IslandId } from '@exulanica/atlas-core';
import { AuthoredRegionSociety } from './authored-society.js';

/**
 * A saved world's people, hung from one island of a world made from photographs.
 *
 * The starter's society is built with its authored region (`atlas-binding.ts`). A made world has
 * no authored region: its society lives in one of its islands, the one it was brought into, and
 * is drawn under that island's root, the frame its objects are placed in and its declared floor
 * is drawn in (`../declared-floor.ts`). The binding plays whichever society it holds each frame,
 * so hosting one here is all a made world needs. The island is where the page's layout put it on
 * this open, so its people move with it when that layout changes.
 */

/** What a region's society is hosted by: the binding's device, region roots and one society slot. */
export interface RegionSocietyHost {
  readonly device: pc.GraphicsDevice;
  readonly regionRoots: ReadonlyMap<IslandId, pc.Entity>;
  authoredSociety: AuthoredRegionSociety | null;
}

/**
 * The society drawn under this island, made the first time it is asked for. Null when the binding
 * draws no such island, or already holds a society somewhere else, which it never replaces.
 */
export function hostRegionSociety(host: RegionSocietyHost, islandId: IslandId): AuthoredRegionSociety | null {
  const region = host.regionRoots.get(islandId);
  if (region === undefined) return null;
  const held = host.authoredSociety;
  if (held !== null) return held.root.parent === region ? held : null;
  const society = new AuthoredRegionSociety(host.device, region);
  host.authoredSociety = society;
  return society;
}

/** What a generated world's society is hosted by: the binding's device, the environment root its
 * tiles are drawn under and one society slot. */
export interface GeneratedSocietyHost {
  readonly device: pc.GraphicsDevice;
  readonly environmentRoot: pc.Entity;
  authoredSociety: AuthoredRegionSociety | null;
}

/**
 * A saved generated world's people, hung from its region's frame.
 *
 * A generated world's region is the city's own frame (east the city's x, south its negative y),
 * and the tile runtime draws every tile at its absolute city position under the environment root,
 * so the region's origin is that root's origin and the society's root sits there, at `floorMm`
 * above it. The society states plan positions only, so the page stands its people on one plane:
 * the height of the surface where a person arrives, which the world's entry states, and a person
 * elsewhere may stand a few centimetres above or below the footway beneath them. Null when the
 * binding already holds a society somewhere else, which it never replaces.
 */
export function hostGeneratedSociety(
  host: GeneratedSocietyHost,
  regionId: string,
  floorMm: number,
): AuthoredRegionSociety | null {
  const name = `generated-region:${regionId}`;
  const held = host.authoredSociety;
  if (held !== null) return held.root.parent?.name === name ? held : null;
  const region = new pc.Entity(name);
  region.setLocalPosition(0, floorMm / 1000, 0);
  host.environmentRoot.addChild(region);
  const society = new AuthoredRegionSociety(host.device, region);
  host.authoredSociety = society;
  return society;
}
