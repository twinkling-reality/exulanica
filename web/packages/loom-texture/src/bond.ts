import { floorDiv, floorMod } from './integer.js';
import { MM } from './tile.js';

/**
 * Units laid in courses with joints between them: brick, ashlar, paving flags, kerb units.
 *
 * Everything is stated in whole millimetres except the two shifts, which are in 1/1024 mm so a
 * half-unit offset of an odd-length module (112.5 mm for a 225 mm brick module) is still an exact
 * integer. Joints are centred on module boundaries, so a unit's face is the module less one joint.
 *
 * A bond tiles when the tile holds a whole number of modules each way and, if alternate courses
 * are offset, an even number of courses. `checkBond` refuses anything else, because a module that
 * does not divide the extent is a visible seam that no amount of noise hides.
 */
export interface BondSpec {
  /** Module length along u: one unit plus one head joint, mm. */
  readonly moduleU: number;
  /** Module height along v: one course plus one bed joint, mm. */
  readonly moduleV: number;
  /** Head (vertical) joint width, mm. */
  readonly jointU: number;
  /** Bed (horizontal) joint width, mm. Zero means one continuous course with no bed joint. */
  readonly jointV: number;
  /** Units per course across one tile. */
  readonly unitsPerCourse: number;
  /** Courses down one tile. */
  readonly courses: number;
  /** Shift of every odd course along u, 1/1024 mm. */
  readonly oddCourseShift: number;
  /** Shift of the whole pattern, 1/1024 mm, which decides where the tile edge falls. */
  readonly phaseU: number;
  readonly phaseV: number;
}

export function checkBond(spec: BondSpec, extentU: number, extentV: number): void {
  if (spec.unitsPerCourse * spec.moduleU !== extentU) {
    throw new Error(
      `${spec.unitsPerCourse} units of ${spec.moduleU} mm do not span the ${extentU} mm tile`,
    );
  }
  if (spec.courses * spec.moduleV !== extentV) {
    throw new Error(`${spec.courses} courses of ${spec.moduleV} mm do not span ${extentV} mm`);
  }
  if (spec.oddCourseShift !== 0 && spec.courses % 2 !== 0) {
    throw new Error('alternate courses are offset, so the tile must hold an even number of them');
  }
  if (spec.jointU >= spec.moduleU || spec.jointV >= spec.moduleV) {
    throw new Error('a joint cannot be as wide as its module');
  }
}

export interface BondSample {
  /** Course index, reduced into [0, courses). */
  course: number;
  /** Unit index within the course, reduced into [0, unitsPerCourse). */
  unit: number;
  /** Position across the unit's face from its left edge, 1/1024 mm. Negative in a joint. */
  faceU: number;
  /** Position down the unit's face from its top edge, 1/1024 mm. Negative in a joint. */
  faceV: number;
  /** Distance to the nearest face edge, 1/1024 mm. Negative inside a joint. */
  edge: number;
}

/**
 * A distance that no bevel or chip in this package reaches, for an axis with no joint: 2^40,
 * written out. Not a shift, because JavaScript shifts are 32-bit and `1 << 40` is 256.
 */
const FAR = 1_099_511_627_776;

/** Lay the bond at a position given in 1/1024 mm (see `tile.tileToLength`). */
export function bond(u: number, v: number, spec: BondSpec, out: BondSample): BondSample {
  const moduleV = spec.moduleV * MM;
  const y = v + spec.phaseV;
  const courseRaw = floorDiv(y, moduleV);
  const withinV = y - courseRaw * moduleV;

  const moduleU = spec.moduleU * MM;
  const x = u + spec.phaseU - (floorMod(courseRaw, 2) === 1 ? spec.oddCourseShift : 0);
  const unitRaw = floorDiv(x, moduleU);
  const withinU = x - unitRaw * moduleU;

  const halfJointU = (spec.jointU * MM) >> 1;
  const faceWidth = (spec.moduleU - spec.jointU) * MM;
  const faceU = withinU - halfJointU;
  const edgeU = Math.min(faceU, faceWidth - faceU);

  let faceV = withinV;
  let edgeV = FAR;
  if (spec.jointV > 0) {
    const halfJointV = (spec.jointV * MM) >> 1;
    const faceHeight = (spec.moduleV - spec.jointV) * MM;
    faceV = withinV - halfJointV;
    edgeV = Math.min(faceV, faceHeight - faceV);
  }

  out.course = floorMod(courseRaw, spec.courses);
  out.unit = floorMod(unitRaw, spec.unitsPerCourse);
  out.faceU = faceU;
  out.faceV = faceV;
  out.edge = Math.min(edgeU, edgeV);
  return out;
}

export function newBondSample(): BondSample {
  return { course: 0, unit: 0, faceU: 0, faceV: 0, edge: 0 };
}
