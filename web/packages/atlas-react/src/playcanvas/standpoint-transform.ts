/**
 * A standpoint member's transform, taken apart: the one shape the server's standpoint record
 * gives a member (see `standpoint-scene.ts`), checked, and split into what the renderer sets.
 *
 * Its own module because both the placement check (`scene-point-maps.ts`) and the standpoint plan
 * (`standpoint-scene.ts`) read it, and the plan reads the placement's types.
 */

/** How far a transform's columns may be from the promised shape and still be read as it. */
const SHAPE_TOLERANCE = 1e-5;

export interface StandpointTransform {
  /** Scene from camera, as a unit quaternion x, y, z, w. */
  readonly rotation: readonly [number, number, number, number];
  /** The rotation itself, row major, for the ownership planning below. */
  readonly rotationRowMajor: readonly number[];
  /** Scale on the camera's own x and y: depth scale times lateral re-projection. */
  readonly lateral: number;
  /** Scale on the camera's own z: the member's depth scale. */
  readonly depth: number;
}

/**
 * The server's row-major `scene_from_opm` for one member, taken apart into rotation and scales.
 *
 * The promised shape is `R diag(a, a, b)` with no translation beyond the camera's own: a proper
 * rotation after a scale that is the same on the camera's two sideways axes. Anything else is
 * refused with a TypeError, as `validateSceneTransform` refuses a similarity that lost its shape.
 */
export function standpointTransform(matrix: readonly number[]): StandpointTransform {
  if (matrix.length !== 16 || matrix.some((value) => !Number.isFinite(value))) {
    throw new TypeError('a standpoint transform must be a finite 4x4 matrix');
  }
  if (matrix[12] !== 0 || matrix[13] !== 0 || matrix[14] !== 0 || matrix[15] !== 1) {
    throw new TypeError('a standpoint transform must be affine');
  }
  const column = (index: number): [number, number, number] =>
    [matrix[index]!, matrix[4 + index]!, matrix[8 + index]!];
  const [c0, c1, c2] = [column(0), column(1), column(2)];
  const length = (v: readonly number[]): number => Math.hypot(v[0]!, v[1]!, v[2]!);
  const a = length(c0);
  const b = length(c2);
  if (!(a > 0) || !(b > 0) || Math.abs(length(c1) - a) > SHAPE_TOLERANCE * a) {
    throw new TypeError('a standpoint transform scales its two sideways axes alike');
  }
  const r = [
    c0[0] / a, c1[0] / a, c2[0] / b,
    c0[1] / a, c1[1] / a, c2[1] / b,
    c0[2] / a, c1[2] / a, c2[2] / b,
  ];
  for (let i = 0; i < 3; i += 1) {
    for (let j = 0; j < 3; j += 1) {
      const dot = r[i]! * r[j]! + r[3 + i]! * r[3 + j]! + r[6 + i]! * r[6 + j]!;
      if (Math.abs(dot - (i === j ? 1 : 0)) > SHAPE_TOLERANCE) {
        throw new TypeError('a standpoint transform must contain a rotation');
      }
    }
  }
  const determinant = r[0]! * (r[4]! * r[8]! - r[5]! * r[7]!)
    - r[1]! * (r[3]! * r[8]! - r[5]! * r[6]!)
    + r[2]! * (r[3]! * r[7]! - r[4]! * r[6]!);
  if (Math.abs(determinant - 1) > SHAPE_TOLERANCE) {
    throw new TypeError('a standpoint transform must be a proper rotation without reflection');
  }
  return Object.freeze({
    rotation: quaternionOf(r),
    rotationRowMajor: Object.freeze(r),
    lateral: a,
    depth: b,
  });
}

/** Shepperd's method: the unit quaternion of a proper rotation, x y z w. */
function quaternionOf(r: readonly number[]): [number, number, number, number] {
  const trace = r[0]! + r[4]! + r[8]!;
  let x: number;
  let y: number;
  let z: number;
  let w: number;
  if (trace > 0) {
    const s = Math.sqrt(trace + 1) * 2;
    w = s / 4;
    x = (r[7]! - r[5]!) / s;
    y = (r[2]! - r[6]!) / s;
    z = (r[3]! - r[1]!) / s;
  } else if (r[0]! > r[4]! && r[0]! > r[8]!) {
    const s = Math.sqrt(1 + r[0]! - r[4]! - r[8]!) * 2;
    w = (r[7]! - r[5]!) / s;
    x = s / 4;
    y = (r[1]! + r[3]!) / s;
    z = (r[2]! + r[6]!) / s;
  } else if (r[4]! > r[8]!) {
    const s = Math.sqrt(1 + r[4]! - r[0]! - r[8]!) * 2;
    w = (r[2]! - r[6]!) / s;
    x = (r[1]! + r[3]!) / s;
    y = s / 4;
    z = (r[5]! + r[7]!) / s;
  } else {
    const s = Math.sqrt(1 + r[8]! - r[0]! - r[4]!) * 2;
    w = (r[3]! - r[1]!) / s;
    x = (r[2]! + r[6]!) / s;
    y = (r[5]! + r[7]!) / s;
    z = s / 4;
  }
  const n = Math.hypot(x, y, z, w);
  return [x / n, y / n, z / n, w / n];
}
