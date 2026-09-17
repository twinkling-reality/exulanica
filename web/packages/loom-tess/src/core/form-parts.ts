/**
 * FORM PARTS: an object's solids, turned by its facing vector, as integer triangles.
 *
 * A bench, a litter bin, a bollard, a street tree and the objects on a roof all state their shape
 * the same way: `parts`, each a box, a prism or an ellipsoid in the object's local frame, and a
 * facing vector that turns the frame into the city's. This file is that rule and nothing else. It
 * is written for the tessellator to call and imports nothing, so it can be read and tested on its
 * own; the expander that calls it, and what it does with the triangles, are not here.
 *
 * Everything below comes from the city grammar's own statements. The quotations are from
 * `exulanica/grammar/grammars/city/common.py` and `corners.py`, which are the records' authority:
 *
 * - The frame is `city_local`: "x east, y north, z up, integer millimetres".
 * - "A direction is an integer vector (dx_mm, dy_mm) of any length, never an angle: no record asks
 *   a reader for a sine."
 * - A part sits in a local frame where "+x is the object's direction vector, +y is to its left and
 *   +z is up; the offset places the part's bottom centre".
 * - "A box spans its three sizes. A prism is a regular polygon of `segments` sides inscribed in the
 *   `size_x` by `size_y` ellipse, first vertex on local +x, extruded by `size_z` and scaled at its
 *   top by `top_scale_millionths` (0 makes a cone). An ellipsoid fills its sizes with `segments`
 *   meridians and `rings` bands."
 * - The measure for moving `d` along an integer vector `v`, "the one the tile document's
 *   [corner_radius] check and the tessellator use": `floor(v * d * S / isqrt(|v|^2 * S^2))` on each
 *   axis, with `S = 10**6`. The left normal of `(dx, dy)` is `(-dy, dx)`.
 * - The surface frame for an object part: a side takes "s round the part from its local +x" with
 *   "t = base - z" and the base "the object's z_mm"; a top takes "s = +x and t = +y in plan".
 *
 * NO FLOATING POINT, ANYWHERE. Every number here is an integer, and the intermediate products
 * exceed what a double holds exactly, so the arithmetic is `bigint` and only the results, which are
 * millimetres, come back as numbers. The circle is built by chord bisection, which is why the
 * record shapes allow only powers of two: "segment and ring counts a reader builds by integer chord
 * bisection, so no sine is needed". Starting from the four axis points, each bisection inserts
 * `normalise(p + q)` between neighbours, using the same measure. So the same records give the same
 * triangles on every machine, by construction rather than by argument.
 *
 * THE UNDERSIDE OF A PART takes `s = +x` and `t = -y`, and that is the grammar deciding rather than
 * this file choosing. `common.py` states the invariant "a horizontal face: t is always to the left
 * of s", left being seen from the side the face is seen from. A top's normal is `+z`, where `s = +x`
 * with `t = +y` satisfies it. An underside's normal is `-z`, where the same pair would put `t` to
 * the right as seen from below and a directional material would read mirrored. So `t = -y`. The
 * enumeration in `common.py` names "the top of an object part" and omits the underside, which is
 * what made this look unstated; the lane that owns the grammar is adding the clause, and no record
 * version moves, because no stored container carries an object part underside yet.
 *
 * ONE THING THE GRAMMAR DOES NOT STATE, chosen here and reported as a choice: WHICH FRAME A SLOPING
 * TRIANGLE TAKES. A box or a prism has sides, a top and an underside, which the frames cover. An
 * ellipsoid's surface is none of them. Each triangle therefore takes the frame its own normal leans
 * towards, at 45 degrees exactly: horizontal while `nz^2` is at least `nx^2 + ny^2`, vertical
 * otherwise, and a horizontal one takes the top's frame or the underside's by the sign of `nz`. 45
 * degrees is the one threshold that favours neither frame, since there both stretch a texture by the
 * same factor.
 */

/** The scale the grammar's measure works at: `S = 10**6`. */
const SCALE = 1_000_000n;
/** Proportions are in millionths (`common.py`). */
const MILLIONTHS = 1_000_000n;
/**
 * The counts chord bisection reaches, as doublings of the smallest rather than as written numbers.
 * `common.py`'s POWER_OF_TWO_SEGMENTS is 4, 8, 16, 32, 64, which is the four doublings of 4, and its
 * ellipsoid ring counts stop one doubling earlier, at 32.
 */
const SMALLEST_COUNT = 4;
const SEGMENT_DOUBLINGS = 4;
const RING_DOUBLINGS = 3;

function doublings(from: number, times: number): readonly number[] {
  const out = [from];
  for (let step = 0; step < times; step += 1) out.push(out[out.length - 1]! * 2);
  return out;
}

/** `common.py`: a box has four segments and one ring, which is the smallest count. */
const BOX_SEGMENTS = SMALLEST_COUNT;
const SEGMENT_COUNTS = doublings(SMALLEST_COUNT, SEGMENT_DOUBLINGS);
const RING_COUNTS = doublings(SMALLEST_COUNT, RING_DOUBLINGS);
/** `common.py`, PART_ROLES. A role is a label this rule carries through, never looks a shape up by. */
const PART_ROLES: readonly string[] = [
  'object_primary',
  'object_secondary',
  'object_tertiary',
  'trunk',
  'canopy',
];
/** `common.py`, DIRECTION_LIMIT_MM. */
const DIRECTION_LIMIT_MM = 1_000_000;

export type FormShape = 'box' | 'prism' | 'ellipsoid';
export type Orientation = 'horizontal' | 'vertical';

/** One solid of an object, in the object's local frame: `common.py`'s `FormPart`, field for field. */
export interface FormPart {
  readonly shape: FormShape;
  readonly surfaceRole: string;
  readonly offsetXMm: number;
  readonly offsetYMm: number;
  readonly offsetZMm: number;
  readonly sizeXMm: number;
  readonly sizeYMm: number;
  readonly sizeZMm: number;
  readonly topScaleMillionths: number;
  readonly segments: number;
  readonly rings: number;
}

/** An object that states parts: street furniture, a street tree, a rooftop object, a fitout. */
export interface FormObject {
  /** Where the object stands, in the city frame. A rooftop object's placer supplies it. */
  readonly xMm: number;
  readonly yMm: number;
  readonly zMm: number;
  /** The facing vector, of any length, never an angle. */
  readonly facingDxMm: number;
  readonly facingDyMm: number;
  readonly parts: readonly FormPart[];
}

/** One triangle's vertex: where it is, and what `s` and `t` mean there, all in millimetres. */
export interface FormVertex {
  readonly xMm: number;
  readonly yMm: number;
  readonly zMm: number;
  readonly sMm: number;
  readonly tMm: number;
}

/** A triangle, counter-clockwise seen from outside the solid. */
export interface FormTriangle {
  readonly surfaceRole: string;
  readonly orientation: Orientation;
  readonly vertices: readonly [FormVertex, FormVertex, FormVertex];
}

/** Why a part or an object is refused. One reason, named, never a quiet default. */
export type FormPartsRefusalReason =
  | 'facing'
  | 'parts'
  | 'shape'
  | 'role'
  | 'size'
  | 'counts'
  | 'taper'
  | 'offset'
  | 'range';

export class FormPartsRefusal extends Error {
  constructor(
    readonly reason: FormPartsRefusalReason,
    message: string,
  ) {
    super(`${reason}: ${message}`);
    this.name = 'FormPartsRefusal';
  }
}

function refuse(reason: FormPartsRefusalReason, message: string): never {
  throw new FormPartsRefusal(reason, message);
}

/** The floor of `a / b` for a positive `b`, in exact integers. */
function floorDivide(a: bigint, b: bigint): bigint {
  const quotient = a / b;
  if (a >= 0n) return quotient;
  if (a % b === 0n) return quotient;
  return quotient - 1n;
}

/** The largest `r` with `r * r <= value`, by Newton's method on integers. */
function integerSquareRoot(value: bigint): bigint {
  if (value < 0n) refuse('range', 'a square root of a negative number');
  if (value < 2n) return value;
  let estimate = value;
  let next = (estimate + value / estimate) / 2n;
  while (next < estimate) {
    estimate = next;
    next = (estimate + value / estimate) / 2n;
  }
  return estimate;
}

/** A plan vector in integer millimetres, or in half millimetres where a part's centre needs them. */
interface Plan {
  readonly x: bigint;
  readonly y: bigint;
}

/**
 * The grammar's measure: how far to move on each axis to travel `halves / 2` millimetres along the
 * integer vector `v`. One floor, as `corners.py` states it, with the halving folded into the same
 * division so an odd size keeps its exact centre instead of leaning one way.
 */
function move(v: Plan, halves: bigint): Plan {
  const length = integerSquareRoot((v.x * v.x + v.y * v.y) * SCALE * SCALE);
  if (length === 0n) refuse('facing', 'a direction of zero length has no measure');
  return {
    x: floorDivide(v.x * halves * SCALE, 2n * length),
    y: floorDivide(v.y * halves * SCALE, 2n * length),
  };
}

/**
 * The unit circle at scale `SCALE`, `count` points, first on `+x`, counter-clockwise, built by
 * chord bisection from the four axis points. `count` is a power of two from 4 to 64.
 */
function unitCircle(count: number): readonly Plan[] {
  let points: Plan[] = [
    { x: SCALE, y: 0n },
    { x: 0n, y: SCALE },
    { x: -SCALE, y: 0n },
    { x: 0n, y: -SCALE },
  ];
  while (points.length < count) {
    const bisected: Plan[] = [];
    for (let index = 0; index < points.length; index += 1) {
      const here = points[index]!;
      const next = points[(index + 1) % points.length]!;
      bisected.push(here);
      // The sum points along the bisector of the two, so normalising it halves the arc.
      const sum: Plan = { x: here.x + next.x, y: here.y + next.y };
      const unit = move(sum, 2n * SCALE);
      bisected.push(unit);
    }
    points = bisected;
  }
  return points;
}

/** A point of a part, in the part's own frame: plan in half millimetres, height in half millimetres. */
interface Local {
  readonly plan: Plan;
  readonly heightHalves: bigint;
}

/** The largest integer a double holds exactly, taken from the language rather than written out. */
const LARGEST_EXACT = BigInt(Number.MAX_SAFE_INTEGER);

function safeInteger(value: bigint, what: string): number {
  const beyond = value > LARGEST_EXACT ? true : value < -LARGEST_EXACT;
  if (beyond) {
    refuse('range', `${what} is ${value.toString()}, which a double does not hold exactly`);
  }
  return Number(value);
}

/** What a part needs from its object: where it stands and which way it faces. */
interface Frame {
  readonly xMm: bigint;
  readonly yMm: bigint;
  readonly zMm: bigint;
  readonly facing: Plan;
  readonly left: Plan;
}

/** A local point turned into the city frame, with the measure applied once on each axis. */
function toWorld(frame: Frame, local: Local): { x: bigint; y: bigint; z: bigint } {
  const along = move(frame.facing, local.plan.x);
  const across = move(frame.left, local.plan.y);
  return {
    x: frame.xMm + along.x + across.x,
    y: frame.yMm + along.y + across.y,
    z: frame.zMm + floorDivide(local.heightHalves, 2n),
  };
}

/**
 * A vertex, with `s` and `t` as `common.py` fixes them for an object part.
 *
 * A side takes `s` round the part from its local `+x`, which is the distance walked round the
 * part's plan outline to this vertex, and `t = base - z` with the base the object's own `z_mm`. A
 * top takes `s = +x` and `t = +y` in plan. An underside takes `s = +x` and `t = -y`, which is the
 * same invariant seen from below.
 */
function vertexOf(
  frame: Frame,
  local: Local,
  face: FaceFrame,
  aroundHalves: bigint,
): FormVertex {
  const world = toWorld(frame, local);
  let sMm: bigint;
  let tMm: bigint;
  if (face === 'vertical') {
    sMm = floorDivide(aroundHalves, 2n);
    tMm = frame.zMm - world.z;
  } else {
    sMm = world.x;
    tMm = face === 'top' ? world.y : -world.y;
  }
  return {
    xMm: safeInteger(world.x, 'a vertex x'),
    yMm: safeInteger(world.y, 'a vertex y'),
    zMm: safeInteger(world.z, 'a vertex z'),
    sMm: safeInteger(sMm, 'a vertex s'),
    tMm: safeInteger(tMm, 'a vertex t'),
  };
}

/** The plan distance between two points, floored, for `s` round a part's side. */
function planDistanceHalves(from: Plan, to: Plan): bigint {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  return integerSquareRoot(dx * dx + dy * dy);
}

interface Ring {
  /** The ring's points, counter-clockwise in plan, in half millimetres. */
  readonly points: readonly Plan[];
  /** How far round the part each point sits from local `+x`, in half millimetres. */
  readonly around: readonly bigint[];
  readonly heightHalves: bigint;
}

/** The plan outline of a part at one height, and the walk round it that `s` measures. */
function ringAt(points: readonly Plan[], heightHalves: bigint): Ring {
  const around: bigint[] = [0n];
  for (let index = 1; index < points.length; index += 1) {
    around.push(around[index - 1]! + planDistanceHalves(points[index - 1]!, points[index]!));
  }
  return { points, around, heightHalves };
}

function triangle(
  role: string,
  orientation: Orientation,
  a: FormVertex,
  b: FormVertex,
  c: FormVertex,
): FormTriangle {
  return { surfaceRole: role, orientation, vertices: [a, b, c] };
}

/**
 * Which frame a wall takes, for a surface the grammar's two frames do not cover: horizontal while
 * its normal leans less than 45 degrees from vertical, vertical otherwise. Exact, because the
 * comparison is between squared integer components: nothing is rounded and nothing is an angle. The
 * frame is chosen before the vertices are made, since `s` and `t` depend on it.
 */
function orientationOfLocals(
  frame: Frame,
  corners: readonly [Local, Local, Local, Local],
): FaceFrame {
  const points = corners.map((local) => toWorld(frame, local));
  const first = points[0]!;
  // The diagonals span the quad however its corners collapse, so a pole still gives a normal.
  const ux = points[2]!.x - first.x;
  const uy = points[2]!.y - first.y;
  const uz = points[2]!.z - first.z;
  const vx = points[3]!.x - points[1]!.x;
  const vy = points[3]!.y - points[1]!.y;
  const vz = points[3]!.z - points[1]!.z;
  const nx = uy * vz - uz * vy;
  const ny = uz * vx - ux * vz;
  const nz = ux * vy - uy * vx;
  if (nz * nz < nx * nx + ny * ny) return 'vertical';
  return nz > 0n ? 'top' : 'underside';
}

/**
 * Where `s` is measured round a part, for every height of it.
 *
 * `common.py` says only that a side's `s` "runs round the part from its local +x", which does not
 * say at which height to walk when the part is tapered or curved. Walking each ring separately
 * would give one meridian a different `s` in every band, and a texture would tear between bands.
 * So the walk is taken once, round the ring with the longest plan outline, and every vertex on that
 * meridian takes it. A THIRD CHOICE where the grammar is silent, reported with the other two.
 */
function referenceAround(rings: readonly Ring[]): readonly bigint[] {
  let best = rings[0]!;
  let longest = -1n;
  for (const ring of rings) {
    const perimeter = ring.around[ring.around.length - 1]!
      + planDistanceHalves(ring.points[ring.points.length - 1]!, ring.points[0]!);
    if (perimeter > longest) {
      longest = perimeter;
      best = ring;
    }
  }
  const closing = longest;
  return [...best.around, closing];
}

/** Whether a wall's own normal decides its frame, or it is a side and takes the side's. */
type FramePolicy = 'side' | 'by-normal';

/**
 * Which of the grammar's frames a face takes. Three, not two, because a horizontal face's `t` turns
 * with the side it is seen from: `+y` for a top, `-y` for an underside, so that `t` stays to the
 * left of `s` in both. The record's `orientation` is still one of the grammar's two.
 */
type FaceFrame = 'vertical' | 'top' | 'underside';

const orientationOf = (face: FaceFrame): Orientation =>
  face === 'vertical' ? 'vertical' : 'horizontal';

/**
 * The walls between two rings of the same point count, counter-clockwise seen from outside.
 *
 * Where one ring's pair of points coincide, which happens at a cone's apex and at an ellipsoid's
 * two poles, the quad is already a triangle and only that triangle is emitted: a zero-area triangle
 * is exactly what the ring rule refuses elsewhere.
 */
function sideTriangles(
  frame: Frame,
  role: string,
  lower: Ring,
  upper: Ring,
  around: readonly bigint[],
  policy: FramePolicy,
): FormTriangle[] {
  const out: FormTriangle[] = [];
  const count = lower.points.length;
  for (let index = 0; index < count; index += 1) {
    const next = (index + 1) % count;
    const aroundHere = around[index]!;
    const aroundNext = next === 0 ? around[count]! : around[next]!;
    const corners: readonly [Local, Local, Local, Local] = [
      { plan: lower.points[index]!, heightHalves: lower.heightHalves },
      { plan: lower.points[next]!, heightHalves: lower.heightHalves },
      { plan: upper.points[next]!, heightHalves: upper.heightHalves },
      { plan: upper.points[index]!, heightHalves: upper.heightHalves },
    ];
    const same = (one: Local, two: Local): boolean =>
      one.plan.x === two.plan.x && one.plan.y === two.plan.y
      && one.heightHalves === two.heightHalves;
    const face: FaceFrame = policy === 'side' ? 'vertical' : orientationOfLocals(frame, corners);
    const orientation = orientationOf(face);
    const at = (local: Local, walk: bigint): FormVertex => vertexOf(frame, local, face, walk);
    const a = at(corners[0], aroundHere);
    const b = at(corners[1], aroundNext);
    const c = at(corners[2], aroundNext);
    const d = at(corners[3], aroundHere);
    if (same(corners[0], corners[1])) {
      out.push(triangle(role, orientation, a, c, d));
      continue;
    }
    if (same(corners[2], corners[3])) {
      out.push(triangle(role, orientation, a, b, c));
      continue;
    }
    out.push(triangle(role, orientation, a, b, c));
    out.push(triangle(role, orientation, a, c, d));
  }
  return out;
}

/** A convex ring as a fan, facing up when `up` and down otherwise. */
function capTriangles(frame: Frame, role: string, ring: Ring, up: boolean): FormTriangle[] {
  const out: FormTriangle[] = [];
  const points = ring.points;
  const face: FaceFrame = up ? 'top' : 'underside';
  for (let index = 1; index + 1 < points.length; index += 1) {
    const first = { plan: points[0]!, heightHalves: ring.heightHalves };
    const second = { plan: points[index]!, heightHalves: ring.heightHalves };
    const third = { plan: points[index + 1]!, heightHalves: ring.heightHalves };
    const a = vertexOf(frame, first, face, 0n);
    const b = vertexOf(frame, second, face, 0n);
    const c = vertexOf(frame, third, face, 0n);
    out.push(up ? triangle(role, 'horizontal', a, b, c) : triangle(role, 'horizontal', a, c, b));
  }
  return out;
}

function checkPart(part: FormPart): void {
  if (part.shape !== 'box' && part.shape !== 'prism' && part.shape !== 'ellipsoid') {
    refuse('shape', `${JSON.stringify(part.shape)} is not box, prism or ellipsoid`);
  }
  if (!PART_ROLES.includes(part.surfaceRole)) {
    refuse('role', `${JSON.stringify(part.surfaceRole)} is not one of ${PART_ROLES.join(', ')}`);
  }
  for (const [name, value] of [
    ['size_x_mm', part.sizeXMm],
    ['size_y_mm', part.sizeYMm],
    ['size_z_mm', part.sizeZMm],
  ] as const) {
    const whole = Number.isSafeInteger(value);
    if (!whole) refuse('size', `${name} is ${String(value)}, and a size is an integer of 1 or more`);
    if (value < 1) refuse('size', `${name} is ${String(value)}, and a size is an integer of 1 or more`);
  }
  for (const [name, value] of [
    ['offset_x_mm', part.offsetXMm],
    ['offset_y_mm', part.offsetYMm],
    ['offset_z_mm', part.offsetZMm],
  ] as const) {
    if (!Number.isSafeInteger(value)) refuse('offset', `${name} is ${String(value)}, not an integer`);
  }
  const scale = part.topScaleMillionths;
  const scaleOutside =
    Number.isSafeInteger(scale) ? scale < 0 ? true : scale > Number(MILLIONTHS) : true;
  if (scaleOutside) {
    refuse('taper', `top_scale_millionths is ${String(scale)}, outside zero to a whole`);
  }
  if (part.shape === 'box') {
    const boxCounts = part.segments === BOX_SEGMENTS ? part.rings === 1 : false;
    if (!boxCounts) refuse('counts', 'a box part has four segments and one ring');
    if (part.topScaleMillionths !== Number(MILLIONTHS)) {
      refuse('taper', 'a box is not tapered, so its top scale is 1000000');
    }
    return;
  }
  if (!SEGMENT_COUNTS.includes(part.segments)) {
    refuse('counts', `${String(part.segments)} segments is not one of ${SEGMENT_COUNTS.join(', ')}`);
  }
  if (part.shape === 'prism') {
    if (part.rings !== 1) refuse('counts', 'a prism part has 1 ring');
    return;
  }
  if (!RING_COUNTS.includes(part.rings)) {
    refuse('counts', `${String(part.rings)} rings is not one of ${RING_COUNTS.join(', ')}`);
  }
  if (part.topScaleMillionths !== Number(MILLIONTHS)) refuse('taper', 'an ellipsoid is not tapered');
}

/** The plan outline of a box or a prism at a scale in millionths, in half millimetres. */
function planOutline(part: FormPart, scaleMillionths: bigint): readonly Plan[] {
  const sizeX = BigInt(part.sizeXMm);
  const sizeY = BigInt(part.sizeYMm);
  const offsetX = 2n * BigInt(part.offsetXMm);
  const offsetY = 2n * BigInt(part.offsetYMm);
  const circle = unitCircle(part.segments);
  return circle.map((point) => ({
    // Half millimetres: the ellipse's semi-axes are size / 2, and a size may be odd.
    x: offsetX + floorDivide(sizeX * point.x * scaleMillionths, SCALE * MILLIONTHS),
    y: offsetY + floorDivide(sizeY * point.y * scaleMillionths, SCALE * MILLIONTHS),
  }));
}

/** A box's four corners in plan, in half millimetres: it spans its sizes rather than inscribing them. */
function boxOutline(part: FormPart): readonly Plan[] {
  const halfX = BigInt(part.sizeXMm);
  const halfY = BigInt(part.sizeYMm);
  const offsetX = 2n * BigInt(part.offsetXMm);
  const offsetY = 2n * BigInt(part.offsetYMm);
  return [
    { x: offsetX + halfX, y: offsetY - halfY },
    { x: offsetX + halfX, y: offsetY + halfY },
    { x: offsetX - halfX, y: offsetY + halfY },
    { x: offsetX - halfX, y: offsetY - halfY },
  ];
}

function boxTriangles(frame: Frame, part: FormPart): FormTriangle[] {
  const outline = boxOutline(part);
  const bottom = ringAt(outline, 2n * BigInt(part.offsetZMm));
  const top = ringAt(outline, 2n * BigInt(part.offsetZMm + part.sizeZMm));
  const around = referenceAround([bottom, top]);
  return [
    ...sideTriangles(frame, part.surfaceRole, bottom, top, around, 'side'),
    ...capTriangles(frame, part.surfaceRole, top, true),
    ...capTriangles(frame, part.surfaceRole, bottom, false),
  ];
}

function prismTriangles(frame: Frame, part: FormPart): FormTriangle[] {
  const bottom = ringAt(planOutline(part, MILLIONTHS), 2n * BigInt(part.offsetZMm));
  const topHeight = 2n * BigInt(part.offsetZMm + part.sizeZMm);
  const scale = BigInt(part.topScaleMillionths);
  if (scale === 0n) {
    // A cone: every top point is the axis, so each side is one triangle and there is no top face.
    const apex: Plan = { x: 2n * BigInt(part.offsetXMm), y: 2n * BigInt(part.offsetYMm) };
    const top = ringAt(bottom.points.map(() => apex), topHeight);
    return [
      ...sideTriangles(frame, part.surfaceRole, bottom, top, referenceAround([bottom]), 'side'),
      ...capTriangles(frame, part.surfaceRole, bottom, false),
    ];
  }
  const top = ringAt(planOutline(part, scale), topHeight);
  const around = referenceAround([bottom, top]);
  return [
    ...sideTriangles(frame, part.surfaceRole, bottom, top, around, 'side'),
    ...capTriangles(frame, part.surfaceRole, top, true),
    ...capTriangles(frame, part.surfaceRole, bottom, false),
  ];
}

function ellipsoidTriangles(frame: Frame, part: FormPart): FormTriangle[] {
  const meridians = unitCircle(part.segments);
  // The latitudes are multiples of 180 / rings degrees, which are points of the 2 * rings circle:
  // latitude j is that circle's point j - rings / 2, counting from the bottom pole.
  const latitudes = unitCircle(2 * part.rings);
  const sizeX = BigInt(part.sizeXMm);
  const sizeY = BigInt(part.sizeYMm);
  const sizeZ = BigInt(part.sizeZMm);
  const offsetX = 2n * BigInt(part.offsetXMm);
  const offsetY = 2n * BigInt(part.offsetYMm);
  const centreHalves = 2n * BigInt(part.offsetZMm) + sizeZ;

  const bandPoints = (band: number): Ring => {
    const latitude = latitudes[(band - part.rings / 2 + latitudes.length) % latitudes.length]!;
    const cosine = latitude.x;
    const points = meridians.map((meridian) => ({
      x: offsetX + floorDivide(sizeX * meridian.x * cosine, SCALE * SCALE),
      y: offsetY + floorDivide(sizeY * meridian.y * cosine, SCALE * SCALE),
    }));
    return ringAt(points, centreHalves + floorDivide(sizeZ * latitude.y, SCALE));
  };

  const bands = Array.from({ length: part.rings + 1 }, (_unused, band) => bandPoints(band));
  // One walk for the whole ellipsoid, round its widest band, so a meridian keeps its `s` from
  // pole to pole and a texture does not tear between bands.
  const around = referenceAround(bands);
  const out: FormTriangle[] = [];
  for (let band = 0; band < part.rings; band += 1) {
    out.push(
      ...sideTriangles(frame, part.surfaceRole, bands[band]!, bands[band + 1]!, around, 'by-normal'),
    );
  }
  return out;
}

/**
 * Every triangle an object's parts make, in the city frame, counter-clockwise seen from outside.
 *
 * The object states where it stands and which way it faces; each part states its own solid. A
 * record this rule does not understand is refused by name rather than defaulted.
 */
export function expandFormParts(object: FormObject): readonly FormTriangle[] {
  for (const [name, value] of [
    ['x_mm', object.xMm],
    ['y_mm', object.yMm],
    ['z_mm', object.zMm],
    ['facing_dx_mm', object.facingDxMm],
    ['facing_dy_mm', object.facingDyMm],
  ] as const) {
    if (!Number.isSafeInteger(value)) refuse('offset', `${name} is ${String(value)}, not an integer`);
  }
  if (object.facingDxMm === 0 && object.facingDyMm === 0) {
    refuse('facing', 'a facing is a direction and cannot be zero');
  }
  for (const component of [object.facingDxMm, object.facingDyMm]) {
    const past = component > DIRECTION_LIMIT_MM ? true : component < -DIRECTION_LIMIT_MM;
    if (past) refuse('facing', `a facing component is past ${String(DIRECTION_LIMIT_MM)}`);
  }
  if (object.parts.length === 0) refuse('parts', 'an object with no parts draws nothing');

  const facing: Plan = { x: BigInt(object.facingDxMm), y: BigInt(object.facingDyMm) };
  const frame: Frame = {
    xMm: BigInt(object.xMm),
    yMm: BigInt(object.yMm),
    zMm: BigInt(object.zMm),
    facing,
    // corners.py: the left normal of (dx, dy) is (-dy, dx).
    left: { x: -facing.y, y: facing.x },
  };

  const out: FormTriangle[] = [];
  for (const part of object.parts) {
    checkPart(part);
    if (part.shape === 'box') out.push(...boxTriangles(frame, part));
    else if (part.shape === 'prism') out.push(...prismTriangles(frame, part));
    else out.push(...ellipsoidTriangles(frame, part));
  }
  return out;
}
