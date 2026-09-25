import type { AtlasScene, Island } from '@exulanica/atlas-core';

/*
 * WHICH REGION A WORLD OF SCENE REGIONS OPENS IN.
 *
 * The rule: the drawn region holding the most of the person's placements (objects, environment
 * pieces and depth estimates the opened version holds and has not removed); a tie goes to the
 * region earlier in the scene's order; with no placement in any drawn region, the scene's first
 * region.
 *
 * Why placements: they are the only things in a world the person put there by hand, so they are
 * where the person's things are. Photographs are not placements, so adding photographs never moves
 * the opening, however many there are. Every placement in a version is the person's own (each
 * placement table admits only `origin_kind = 'authored'`), so one count serves, with no tier.
 *
 * Why the scene's order stays as it is: island order also decides the layout (the solver places
 * islands in creation order), which islands survive the `MAX_ISLANDS` cut, and what several other
 * readers of `islands[0]` stand on. Choosing only where the camera opens moves none of that. A
 * region beyond the cut is not in `scene.islands`, so a placement there counts for nothing.
 */

/** What the opening rule reads, handed to the binding with the scene it applies to. */
export interface OpeningPlacements {
  /**
   * The region id of each placement the person made in the opened version and has not removed,
   * one entry per placement. Omitted or empty means none is known, and the world opens in the
   * scene's first region.
   */
  readonly placementRegionIds?: readonly string[];
}

/** The region a world of scene regions opens in, or undefined for a scene with no region. */
export function openingIsland(
  scene: AtlasScene,
  placementRegionIds: readonly string[] = [],
): Island | undefined {
  const counts = new Map<string, number>();
  for (const regionId of placementRegionIds) counts.set(regionId, (counts.get(regionId) ?? 0) + 1);
  let chosen = scene.islands[0];
  let most = 0;
  for (const island of scene.islands) {
    const count = counts.get(island.islandId) ?? 0;
    // Strictly more, so the earlier region keeps a tie.
    if (count > most) {
      chosen = island;
      most = count;
    }
  }
  return chosen;
}
