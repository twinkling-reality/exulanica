/**
 * THE FACING RULE: A LOCAL OFFSET TURNED BY AN INTEGER DIRECTION VECTOR, WITH NO ANGLE.
 *
 * The city grammar never asks a reader for a sine. An object's direction is an integer vector
 * `(facing_dx_mm, facing_dy_mm)` of any nonzero length, and its parts are placed in a local frame
 * where `+x` is that direction and `+y` is to its left. This rule turns a local offset
 * `(along, left)` into a plan offset, exactly, the same on every engine:
 *
 *   1. SCALE the direction up by `k = floor(LIMIT / max(|dx|, |dy|))`, so its larger component
 *      is more than half of `LIMIT`, the grammar's own bound on a direction component
 *      (`FACING_LIMIT_MM`, read from the table). A short vector such as `(1, 1)` would otherwise
 *      lose most of its length to the floor below; scaled, the floor square root is off by less
 *      than two parts in `LIMIT`.
 *   2. MEASURE its length as the floor square root, `L = isqrt(sx * sx + sy * sy)`.
 *   3. TURN: `x = floor((sx * along - sy * left) / L)` and `y = floor((sy * along + sx * left) / L)`.
 *
 * An axis direction or a Pythagorean one, such as `(3, 4)`, turns exactly. Any other lands within
 * one millimetre plus two parts in `LIMIT` of the offset's length of the true rotation. That
 * is the grammar's own floored normal (`document._check_frontage_line`), with the direction scaled
 * first.
 *
 * Not yet wired into a bake. It changes no container until an expander calls it, which is a new
 * `TESSELLATOR_SOURCE_VERSION`.
 */
import { CITY_V2 } from './city-v2.js';
import { absolute, add, floorDivide, floorSquareRoot, GeometryError, multiply, subtract } from './integer-math.js';
import type { Plan } from './integer-math.js';

/** The two fields a direction vector is stated in. */
const DIRECTION_FIELDS = ['facing_dx_mm', 'facing_dy_mm'];

/** Every direction field in a grammar table, which must all share one bound. */
function facingLimit(): number {
  const bounds = new Set<number>();
  for (const shape of CITY_V2.shapes.records) {
    for (const field of shape.fields) {
      if (DIRECTION_FIELDS.includes(field.name)) {
        if (field.maximum === undefined) throw new GeometryError(`${shape.shape}.${field.name} has no bound`);
        if (field.minimum !== -field.maximum) throw new GeometryError(`${shape.shape}.${field.name} is not symmetric`);
        bounds.add(field.maximum);
      }
    }
  }
  const [limit] = [...bounds];
  if (bounds.size !== 1) throw new GeometryError('the direction fields do not share one bound');
  return limit!;
}

/** The largest direction component the grammar admits: `common.DIRECTION_LIMIT_MM`. */
export const FACING_LIMIT_MM = facingLimit();

/** The direction `(dx, dy)`, scaled so its larger component is more than half the limit. */
function scaled(direction: Plan, where: string): Plan {
  const x = absolute(direction[0], where);
  const y = absolute(direction[1], where);
  const larger = x < y ? y : x;
  if (larger === 0) throw new GeometryError(`${where} is a zero direction`);
  if (larger > FACING_LIMIT_MM) throw new GeometryError(`${where} has a component beyond ${FACING_LIMIT_MM}`);
  const factor = floorDivide(FACING_LIMIT_MM, larger, where);
  return [multiply(direction[0], factor, where), multiply(direction[1], factor, where)];
}

/** The local offset `(along, left)` turned by `direction` into a plan offset, by the facing rule. */
export function turnByFacing(direction: Plan, along: number, left: number, where: string): Plan {
  const [sx, sy] = scaled(direction, where);
  const length = floorSquareRoot(add(multiply(sx, sx, where), multiply(sy, sy, where), where), where);
  return [
    floorDivide(subtract(multiply(sx, along, where), multiply(sy, left, where), where), length, where),
    floorDivide(add(multiply(sy, along, where), multiply(sx, left, where), where), length, where),
  ];
}
