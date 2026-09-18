/**
 * Route obstruction rings, from the tile's own records into the navigation world.
 *
 * WHAT THESE ARE, and the sentence matters more than the code. They are ROUTE obstruction rings from
 * the navigation side: plan regions with no height, which drop everything above head height by
 * design, and NOTHING IN THEM STOPS A BODY. They decide which way a walk faces. They are not
 * collision solids and must never be promoted to any: this runtime still stops nothing horizontally,
 * because no tile materialises a `collision_proxy`, and the arrival of these rings does not change
 * that. A reader meeting them for the first time will assume otherwise, which is why it is written
 * here rather than in a note beside the code.
 *
 * WHY THE RUNTIME COMPUTES THEM RATHER THAN READING THEM. The rings are a bake-time intermediate:
 * `obstructionsOf` runs inside tessellation, its output feeds the support carve, and nothing writes
 * it into the container. So there is nothing in an `.owd` to carry. The runtime therefore builds
 * them from the container's OWN records with tess's OWN function, which is not a second derivation
 * of the same thing but the same code over the same inputs.
 *
 * THE CONDITION THAT MAKES THAT SAFE, AND WHAT BREAKS IT. `verifyOwd` REFUSES a container whose
 * `tessellator_version` is not the version this build was made against: "there is no upgrade on
 * read, rebake the tile". So the expander computing rings here is necessarily the expander that
 * baked the container, and the two cannot silently disagree about a bench, because a container from
 * another tessellator does not load at all. IF THAT PIN EVER LOOSENS, this becomes exactly the
 * re-derivation a route rule must not do: two ring sets that were guaranteed identical become two
 * that merely usually agree, and nothing in a record would say which one a walk was scored against.
 * Whoever loosens the pin owns this file too.
 */

import type { AtlasVec3, PolygonObstacle } from '@exulanica/atlas-core';
import { atlasVec3 } from '@exulanica/atlas-core';
import { tileToRenderer } from './tile-navigation.js';

/**
 * One region as tess states it: the record kind that obstructs, the identity of the record it came
 * from, and a closed plan ring in integer millimetres of the tile frame.
 *
 * Structural on purpose. Tess's `ObstructionRegion` satisfies it, and stating the shape here rather
 * than importing it keeps this mapping testable against rings written by hand.
 */
export interface StatedObstructionRing {
  readonly kind: string;
  readonly identity: string;
  readonly ring: readonly (readonly [number, number])[];
}

/** Where a ring was refused, with the reason, so a caller can state what it dropped rather than thin the set silently. */
export interface RefusedObstructionRing {
  readonly kind: string;
  readonly identity: string;
  readonly reason: string;
}

export interface ObstructionRings {
  readonly obstacles: readonly PolygonObstacle[];
  readonly refused: readonly RefusedObstructionRing[];
}

/** A plan ring needs three distinct corners to bound anything; fewer states no region. */
const RING_MINIMUM = 3;

/**
 * The navigation world's polygon obstacles for these rings, and the rings this refused.
 *
 * A ring is refused rather than repaired. A region with fewer than three corners bounds nothing, and
 * a runtime that quietly dropped it would leave a route rule choosing a heading through a bench with
 * no record of why. The identity is carried into the obstacle's id because the gate's run record
 * binds the record identities a walk passed, and an id that does not name a record cannot be bound.
 */
export function obstructionRings(regions: readonly StatedObstructionRing[]): ObstructionRings {
  const obstacles: PolygonObstacle[] = [];
  const refused: RefusedObstructionRing[] = [];
  for (const region of regions) {
    if (region.identity === '') {
      refused.push({ kind: region.kind, identity: region.identity, reason: 'the region names no record identity' });
      continue;
    }
    if (region.ring.length < RING_MINIMUM) {
      refused.push({
        kind: region.kind,
        identity: region.identity,
        reason: `a plan ring needs ${RING_MINIMUM} corners to bound anything and this states ${region.ring.length}`,
      });
      continue;
    }
    const ring: AtlasVec3[] = region.ring.map(([xMm, yMm]) => {
      // The tile frame is x east, y north, z up in millimetres; the renderer is x east, y up, z
      // south in metres. A plan ring has no height, so it is carried at the datum and the navigation
      // rule reads only its x and z.
      const [x, , z] = tileToRenderer(xMm, yMm, 0);
      return atlasVec3(x, 0, z);
    });
    obstacles.push({ id: `${region.kind}:${region.identity}`, rings: [ring] });
  }
  return { obstacles: Object.freeze(obstacles), refused: Object.freeze(refused) };
}
