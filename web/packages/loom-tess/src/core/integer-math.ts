/**
 * EXACT INTEGER ARITHMETIC FOR THE EXPANDERS, AND NOTHING ELSE.
 *
 * Every digested vertex is an integer, and every rule that places one is integer arithmetic on
 * doubles. A double holds every integer up to 2^53 exactly, and addition, subtraction and
 * multiplication of two such integers are exact whenever the true result is also below 2^53 in
 * magnitude, because IEEE 754 rounds correctly and the true result is representable. So each
 * operation here checks its result is a safe integer and refuses otherwise: a result a double
 * would round is never used, on any engine.
 *
 * There is no `Math` here. Floor division is the remainder, which is exact for doubles, taken off
 * before dividing, so the quotient is an exact integer. The square root is the floor square root,
 * Python's `math.isqrt` and `exulanica.grammar.geometry.integer_sqrt`, by Newton's method on
 * integers; `Math.sqrt` is not specified to the last bit across engines.
 *
 * Negative zero never leaves this module: an exact zero is returned as zero.
 */

export class GeometryError extends Error {}

/** A plan point or vector, `(x, y)`, in integer millimetres. */
export type Plan = readonly [number, number];
/** A point, `(x, y, z)`, in integer millimetres. */
export type Space = readonly [number, number, number];

/** `value` if it is a safe integer, as zero if it is either zero, or a refusal naming `where`. */
export function exact(value: number, where: string): number {
  if (!Number.isSafeInteger(value)) {
    throw new GeometryError(`${where} is ${String(value)}, not an integer a double holds exactly`);
  }
  return value === 0 ? 0 : value;
}

export const add = (a: number, b: number, where: string): number => exact(exact(a, where) + exact(b, where), where);
export const subtract = (a: number, b: number, where: string): number => exact(exact(a, where) - exact(b, where), where);
export const multiply = (a: number, b: number, where: string): number => exact(exact(a, where) * exact(b, where), where);

/** The floor of `a / b`, for a positive `b`. */
export function floorDivide(a: number, b: number, where: string): number {
  exact(a, where);
  exact(b, where);
  if (b <= 0) throw new GeometryError(`${where} divides by ${String(b)}, which is not positive`);
  const remainder = a % b;
  // `a - remainder` is a multiple of `b` no larger than `a`, so the quotient is exact; a negative
  // remainder means truncation went up, and the floor is one lower.
  const truncated = exact(exact(a - remainder, where) / b, where);
  return remainder < 0 ? exact(truncated - 1, where) : truncated;
}

/** The floor square root of a non-negative integer: the largest `r` with `r * r <= value`. */
export function floorSquareRoot(value: number, where: string): number {
  exact(value, where);
  if (value < 0) throw new GeometryError(`${where} takes the square root of ${String(value)}`);
  if (value < 2) return value;
  let estimate = value;
  let better = floorDivide(add(estimate, floorDivide(value, estimate, where), where), 2, where);
  while (better < estimate) {
    estimate = better;
    better = floorDivide(add(estimate, floorDivide(value, estimate, where), where), 2, where);
  }
  return estimate;
}

export const absolute = (value: number, where: string): number => (exact(value, where) < 0 ? -value : value);

/**
 * Twice the signed area of the triangle `origin, a, b`: positive when `a` to `b` turns left seen
 * from `origin`, zero when the three are collinear. `exulanica.grammar.geometry._cross`.
 */
export function cross(origin: Plan, a: Plan, b: Plan, where: string): number {
  return subtract(
    multiply(subtract(a[0], origin[0], where), subtract(b[1], origin[1], where), where),
    multiply(subtract(a[1], origin[1], where), subtract(b[0], origin[0], where), where),
    where,
  );
}

/** The cross product of two vectors: positive when `b` is to the left of `a`. */
export const crossVectors = (a: Plan, b: Plan, where: string): number =>
  subtract(multiply(a[0], b[1], where), multiply(a[1], b[0], where), where);

/** The dot product of two vectors. */
export const dot = (a: Plan, b: Plan, where: string): number =>
  add(multiply(a[0], b[0], where), multiply(a[1], b[1], where), where);
