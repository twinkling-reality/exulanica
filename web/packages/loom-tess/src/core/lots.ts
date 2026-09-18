/**
 * THE LOT RULE: A RING OF GROUND AT A STATED ELEVATION, IN INTEGERS.
 *
 * Some records are simply a piece of ground: a parcel's boundary at its grade elevation, the block
 * those parcels sit in, and the pit a street tree stands in. Each states a ring and a height, so
 * each is that ring cut into triangles by the ring rule, as one horizontal surface taking `s = x`
 * and `t = y` in plan, which is the frame the grammar fixes for a lot.
 *
 * WHAT A RING GIVES UP. Parcels tile their block exactly: on the corridor's generated street the
 * fifteen parcels of one block add up to its 4,668 m2 to the square millimetre. So a block that
 * drew its whole boundary would draw the same ground twice and the two would fight for the pixel.
 * A block therefore draws its boundary LESS the boundaries of the parcels that name it, by the
 * shared carve, and states `ground_coverage` when its parcels leave nothing, which on that street
 * is every block. This is the same rule the terrain yields by and the same the massing's wall
 * yields by, at a third scale.
 */
import { piecesOf, Surface, HORIZONTAL } from './faces.js';
import type { Plan } from './integer-math.js';
import type { Piece } from './pieces.js';
import { leftTurning, openRegions } from './piece-carve.js';
import { requireSimpleRing, triangulateRing } from './ring-triangulation.js';

/**
 * A ring of ground at one height, less the rings that take it, as one surface in `role`. Empty when
 * what takes it leaves nothing.
 */
export function groundPieces(
  ring: readonly Plan[],
  height: number,
  role: string,
  taken: readonly (readonly Plan[])[],
  where: string,
): Piece[] {
  const turned = leftTurning(requireSimpleRing(ring, where), where);
  const surface = new Surface(role, HORIZONTAL);
  for (const walk of openRegions(turned, taken.map((other) => leftTurning(requireSimpleRing(other, where), where)), where)) {
    const corners = walk.map((point) => surface.corner(point, height, point[0], point[1]));
    for (const index of triangulateRing(walk, where)) surface.triangles.push(corners[index]!);
  }
  return piecesOf([surface]);
}
