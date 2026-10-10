/**
 * Procedural motion for any dressed skeleton: standing, walking, holding, reaching and talking.
 *
 * A look that has clips for a motion plays them; a look of rigid parts on bones, or a rig with no
 * clip for a motion, is posed here, from the skeleton's limbs (`./skeleton.ts`) and nothing else:
 * legs step in the skeleton's gait with two-joint reaching for each foot, arms hang and swing
 * against the legs, carry what their sockets hold in front of the body and reach toward a point,
 * the head nods while the thing speaks, and anything else sways. No bone is named, so a body plan
 * with ten legs steps all ten.
 *
 * The gait is clocked by distance walked, never by time, so feet stay planted while a figure moves:
 * one cycle covers the stride divided by the share of the cycle a foot is on the ground.
 *
 * Positions are in the figure's frame (`./skeleton.ts`): metres, +Y up, +Z front, +X the figure's
 * left. Rotations are quaternions `[x, y, z, w]`. Pure: no renderer.
 */

import type { DressedSkeleton, Limb, Vec3 } from './skeleton.js';

export type Quat = readonly [number, number, number, number];

export const IDENTITY: Quat = [0, 0, 0, 1];

export function mul(a: Quat, b: Quat): Quat {
  const [ax, ay, az, aw] = a;
  const [bx, by, bz, bw] = b;
  return [
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
    aw * bw - ax * bx - ay * by - az * bz,
  ];
}

export const conjugate = (q: Quat): Quat => [-q[0], -q[1], -q[2], q[3]];

export function rotate(q: Quat, v: Vec3): Vec3 {
  const [x, y, z, w] = q;
  const [vx, vy, vz] = v;
  // t = 2 q.xyz x v; v' = v + w t + q.xyz x t
  const tx = 2 * (y * vz - z * vy);
  const ty = 2 * (z * vx - x * vz);
  const tz = 2 * (x * vy - y * vx);
  return [vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx)];
}

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const scale = (a: Vec3, s: number): Vec3 => [a[0] * s, a[1] * s, a[2] * s];
export const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const length = (a: Vec3): number => Math.hypot(a[0], a[1], a[2]);
export function normalise(a: Vec3): Vec3 {
  const n = length(a);
  return n < 1e-9 ? [0, 0, 0] : [a[0] / n, a[1] / n, a[2] / n];
}

export function axisAngle(axis: Vec3, angle: number): Quat {
  const [x, y, z] = normalise(axis);
  const s = Math.sin(angle / 2);
  return [x * s, y * s, z * s, Math.cos(angle / 2)];
}

/** The shortest turn taking unit direction `a` to unit direction `b`. */
export function fromTo(a: Vec3, b: Vec3): Quat {
  const d = dot(a, b);
  if (d > 1 - 1e-9) return IDENTITY;
  if (d < -1 + 1e-9) {
    const side = Math.abs(a[0]) < 0.9 ? cross(a, [1, 0, 0]) : cross(a, [0, 1, 0]);
    return axisAngle(side, Math.PI);
  }
  const c = cross(a, b);
  const w = 1 + d;
  const n = Math.hypot(c[0], c[1], c[2], w);
  return [c[0] / n, c[1] / n, c[2] / n, w / n];
}

export function slerp(a: Quat, b: Quat, t: number): Quat {
  let [bx, by, bz, bw] = b;
  let cos = a[0] * bx + a[1] * by + a[2] * bz + a[3] * bw;
  if (cos < 0) {
    cos = -cos;
    bx = -bx; by = -by; bz = -bz; bw = -bw;
  }
  if (cos > 0.9995) {
    const q: Quat = [a[0] + (bx - a[0]) * t, a[1] + (by - a[1]) * t, a[2] + (bz - a[2]) * t, a[3] + (bw - a[3]) * t];
    const n = Math.hypot(...q);
    return [q[0] / n, q[1] / n, q[2] / n, q[3] / n];
  }
  const angle = Math.acos(cos);
  const sa = Math.sin(angle);
  const wa = Math.sin((1 - t) * angle) / sa;
  const wb = Math.sin(t * angle) / sa;
  return [a[0] * wa + bx * wb, a[1] * wa + by * wb, a[2] * wa + bz * wb, a[3] * wa + bw * wb];
}

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
const smoothstep = (t: number) => t * t * (3 - 2 * t);
const frac = (x: number) => x - Math.floor(x);

/** What the figure is doing this frame, as the drawing read it from the state. */
export interface MotionInput {
  /**
   * The gait's clock, metres: the ground walked since the figure was made, each metre counted for
   * more where the walk is drawn with a shorter stride (`gaitTravel`).
   */
  readonly travelled: number;
  /** Ground speed, metres a second, as the drawing smoothed it. */
  readonly speed: number;
  /** Seconds since the figure was made: the clock of breathing, swaying and nodding. */
  readonly time: number;
  /** Sockets holding something now, by key. */
  readonly holding: ReadonlySet<string>;
  /** A socket's limb reaching toward a point of the figure's frame, from 0 (not) to 1 (there). */
  readonly reach: { readonly socket: string; readonly target: Vec3; readonly amount: number } | null;
  /** Whether the figure is saying a line now. */
  readonly talking: boolean;
  /** Reduced motion: stand, carry and reach without breathing, swaying or nodding. */
  readonly reducedMotion?: boolean;
}

export interface JointPose {
  readonly position: Vec3;
  readonly rotation: Quat;
}

export interface Pose {
  /** Each dressed bone's rotation relative to its dressed parent; the root's relative to the figure. */
  readonly local: ReadonlyMap<string, Quat>;
  /** Where the root joint stands, in the figure's frame (its rest position plus the walk's bob). */
  readonly rootPosition: Vec3;
  /** Every dressed joint in the figure's frame. */
  readonly joints: ReadonlyMap<string, JointPose>;
}

/** The share of a gait cycle a foot is on the ground. */
export const DUTY = 0.6;
/** A stride, as a share of the legs' mean length. */
const STRIDE_PER_LEG = 0.85;
/** Walking speed at which the walk is fully drawn, metres a second; slower blends from standing. */
const FULL_WALK_SPEED = 0.5;
/**
 * The shortest stride the gait's clock is kept true to, as a share of the full one. A stride
 * shorter than this is a few centimetres of a person's, and a clock true to it would spin at the
 * first frame of a walk, when the speed read from the ground has barely risen.
 */
const SHORTEST_CLOCKED_STRIDE = 0.1;

/**
 * How far the gait's clock advances for `moved` metres of ground walked at ground speed `speed`,
 * metres a second. At a full walk it is the ground itself. Slower, the stride is drawn shorter by
 * the same share (`FULL_WALK_SPEED`), so each metre counts for more: the steps come as often as at a
 * full walk and each is shorter, and a planted foot stays where it stands instead of being dragged
 * over the ground at the full stride's slower beat.
 */
export function gaitTravel(moved: number, speed: number): number {
  return moved / clamp(speed / FULL_WALK_SPEED, SHORTEST_CLOCKED_STRIDE, 1);
}

function chainLength(skeleton: DressedSkeleton, bones: readonly string[]): number {
  let total = 0;
  for (let i = 1; i < bones.length; i += 1) total += length(sub(skeleton.rest.get(bones[i]!)!, skeleton.rest.get(bones[i - 1]!)!));
  return total;
}

/** How far the hips sink while walking, and how far they bob, as shares of the legs' drop. */
const CROUCH = 0.07;
const BOB = 0.03;
/** The share of a leg's reach a planted foot may use at either end of its stance. */
const REACH_USED = 0.92;

/** Gait figures for a skeleton: the stride, the distance one cycle covers, the lift of a step. */
export function gaitOf(skeleton: DressedSkeleton): {
  readonly stride: number;
  readonly cycle: number;
  readonly lift: number;
  /** How far the hips sink while walking, and their bob's depth, metres at full walk. */
  readonly crouch: number;
  readonly bob: number;
} {
  const legs = skeleton.limbs.filter((limb) => limb.role === 'leg');
  if (legs.length === 0) return { stride: 0, cycle: 0, lift: 0, crouch: 0, bob: 0 };
  const lengths = legs.map((leg) => chainLength(skeleton, leg.bones));
  const mean = lengths.reduce((sum, value) => sum + value, 0) / legs.length;
  const drops = legs.map((leg) => skeleton.rest.get(leg.bones[0]!)![1] - skeleton.rest.get(leg.bones.at(-1)!)![1]);
  const drop = Math.min(...drops);
  const crouch = CROUCH * drop;
  const bob = BOB * drop;
  // A planted foot must stay within its leg's reach at both ends of its stance, with the hips at
  // their lowest there: the stride is no longer than the reach left once the leg spans the drop.
  const reach = Math.min(...legs.map((leg, i) => {
    const first = skeleton.rest.get(leg.bones[0]!)!, last = skeleton.rest.get(leg.bones.at(-1)!)!;
    const lateral = Math.abs(last[0] - first[0]);
    const vertical = Math.max(0, drops[i]! - crouch - bob);
    return Math.sqrt(Math.max(0, lengths[i]! ** 2 - vertical ** 2 - lateral ** 2));
  }));
  // Neighbouring ranks step in opposite phases, so a stride longer than the gap between where
  // they hang would cross their feet: many legs take short steps.
  const hung = [...new Set(legs.map((leg) => skeleton.rest.get(leg.bones[0]!)![2]))].sort((a, b) => a - b);
  const gaps = hung.slice(1).map((z, i) => z - hung[i]!).filter((gap) => gap > 1e-3);
  const room = gaps.length === 0 ? Number.POSITIVE_INFINITY : 0.9 * Math.min(...gaps);
  const stride = Math.min(STRIDE_PER_LEG * mean, room, 2 * REACH_USED * reach);
  return { stride, cycle: stride > 0 ? stride / DUTY : 0, lift: 0.14 * mean, crouch, bob };
}

/**
 * The way a chain bends at rest: from the line between its first and last joints toward its middle
 * joint. A chain straight at rest (a person's leg in the T-pose) bends forward, as a knee does.
 */
function restBend(skeleton: DressedSkeleton, bones: readonly string[]): Vec3 {
  const first = skeleton.rest.get(bones[0]!)!;
  const middle = skeleton.rest.get(bones[Math.max(1, Math.floor((bones.length - 1) / 2))]!)!;
  const last = skeleton.rest.get(bones.at(-1)!)!;
  const u = normalise(sub(last, first));
  const toMiddle = sub(middle, first);
  const off = sub(toMiddle, scale(u, dot(toMiddle, u)));
  return length(off) < 1e-4 ? [0, 0, 1] : normalise(off);
}

/** Where a leg's foot is in its cycle, from its rest point: forward offset and lift, metres. */
function footStep(phase: number, stride: number, lift: number): { forward: number; up: number } {
  if (phase < DUTY) return { forward: stride / 2 - (stride * phase) / DUTY, up: 0 };
  const s = (phase - DUTY) / (1 - DUTY);
  return { forward: -stride / 2 + stride * smoothstep(s), up: lift * Math.sin(Math.PI * s) };
}

/** Solve one pose of `skeleton` for `input`. */
export function solvePose(skeleton: DressedSkeleton, input: MotionInput): Pose {
  const quiet = input.reducedMotion === true;
  const walk = clamp(input.speed / FULL_WALK_SPEED, 0, 1);
  const { stride, cycle, lift, crouch, bob: bobDepth } = gaitOf(skeleton);
  const legs = skeleton.limbs.filter((limb) => limb.role === 'leg');
  const phaseOf = (leg: Limb) => (cycle > 0 ? frac(input.travelled / cycle + leg.phase) : leg.phase);
  const lead = legs[0];
  const leadPhase = lead === undefined ? 0 : phaseOf(lead);
  const steps = new Map(legs.map((leg) => [leg, footStep(phaseOf(leg), stride * walk, lift * walk)]));

  // The hips sink into the walk and bob twice a cycle, lowest with the feet apart and highest over a
  // planted foot; the body leans into the walk and its yaw sways with the legs.
  const bob = -walk * (crouch + bobDepth * Math.abs(Math.cos(2 * Math.PI * leadPhase)));
  const lean = axisAngle([1, 0, 0], 0.05 * walk);
  const sway = axisAngle([0, 1, 0], 0.07 * walk * Math.sin(2 * Math.PI * leadPhase));
  const rootRest = skeleton.rest.get(skeleton.root)!;
  const rootPosition = add(rootRest, [0, bob, 0]);

  const figure = new Map<string, JointPose>();
  figure.set(skeleton.root, { position: rootPosition, rotation: mul(sway, lean) });
  const limbOf = new Map<string, Limb>();
  for (const limb of skeleton.limbs) limbOf.set(limb.bones[0]!, limb);

  const childPosition = (bone: string, parent: string) => {
    const p = figure.get(parent)!;
    return add(p.position, rotate(p.rotation, sub(skeleton.rest.get(bone)!, skeleton.rest.get(parent)!)));
  };
  /** The turn of `bone`, inheriting its parent's twist, that points its rest segment to `next` along `to`. */
  const aim = (bone: string, next: string, parentRotation: Quat, to: Vec3): Quat => {
    const restDirection = normalise(sub(skeleton.rest.get(next)!, skeleton.rest.get(bone)!));
    return mul(fromTo(normalise(rotate(parentRotation, restDirection)), normalise(to)), parentRotation);
  };

  const solveChain = (limb: Limb) => {
    const parent = figure.get(limb.from)!;
    const bones = limb.bones;
    const at = (i: number) => figure.get(bones[i]!)!;
    const place = (i: number, rotation: Quat) => {
      const position = i === 0 ? childPosition(bones[0]!, limb.from) : add(at(i - 1).position, rotate(at(i - 1).rotation, sub(skeleton.rest.get(bones[i]!)!, skeleton.rest.get(bones[i - 1]!)!)));
      figure.set(bones[i]!, { position, rotation });
    };
    /** Two-joint reach: the chain's first joint, its middle, its end toward `target`, bending toward `pole`. */
    const reachTo = (target: Vec3, pole: Vec3): Quat[] => {
      const startAt = childPosition(bones[0]!, limb.from);
      const middle = Math.max(1, Math.floor((bones.length - 1) / 2));
      const end = bones.length - 1;
      const a = chainLength(skeleton, bones.slice(0, middle + 1));
      const b = chainLength(skeleton, bones.slice(middle));
      const toTarget = sub(target, startAt);
      const d = clamp(length(toTarget), Math.abs(a - b) + 1e-6, a + b - 1e-6);
      const u = normalise(toTarget);
      const cosA = clamp((a * a + d * d - b * b) / (2 * a * d), -1, 1);
      const v = normalise(sub(pole, scale(u, dot(pole, u))));
      const knee = add(startAt, add(scale(u, a * cosA), scale(v, a * Math.sqrt(1 - cosA * cosA))));
      const reached = add(startAt, scale(u, d));
      const turns: Quat[] = [];
      let parentRotation = parent.rotation;
      for (let i = 0; i < end; i += 1) {
        const to = i < middle ? sub(knee, startAt) : sub(reached, knee);
        const turn = aim(bones[i]!, bones[i + 1]!, parentRotation, to);
        turns.push(turn);
        parentRotation = turn;
      }
      return turns;
    };

    if (limb.role === 'leg' && bones.length >= 2) {
      const step = steps.get(limb)!;
      const restEnd = skeleton.rest.get(bones.at(-1)!)!;
      const target: Vec3 = [restEnd[0], restEnd[1] + step.up, restEnd[2] + step.forward];
      const turns = reachTo(target, rotate(parent.rotation, restBend(skeleton, bones)));
      turns.forEach((turn, i) => place(i, turn));
      // The foot stays level with the ground, turned only with the body.
      place(bones.length - 1, sway);
      return;
    }
    if (limb.role === 'arm' && bones.length >= 2) {
      const s = limb.side;
      const holding = limb.sockets.some((key) => input.holding.has(key));
      const sameSide = legs.find((leg) => leg.side === s) ?? legs[0];
      const swing = sameSide === undefined ? 0 : -(steps.get(sameSide)!.forward / Math.max(1e-6, stride / 2)) * 0.55 * walk;
      const upper: Vec3 = holding ? [s * 0.16, -1, 0.3 + 0.15 * swing] : [s * 0.2, -1, swing];
      const lower: Vec3 = holding ? [s * 0.04, -0.3, 1] : [s * 0.08, -1, swing + 0.3];
      let turns: Quat[] = [];
      let parentRotation = parent.rotation;
      for (let i = 0; i < bones.length - 1; i += 1) {
        const turn = aim(bones[i]!, bones[i + 1]!, parentRotation, i === 0 ? upper : lower);
        turns.push(turn);
        parentRotation = turn;
      }
      const reach = input.reach !== null && limb.sockets.includes(input.reach.socket) ? input.reach : null;
      if (reach !== null && reach.amount > 0) {
        const solved = reachTo(reach.target, [s * 0.6, -1, -0.4]);
        turns = turns.map((turn, i) => slerp(turn, solved[i]!, smoothstep(clamp(reach.amount, 0, 1))));
      }
      turns.forEach((turn, i) => place(i, turn));
      place(bones.length - 1, turns.at(-1) ?? parent.rotation);
      return;
    }
    // A head nods while it speaks; a trunk breathes; anything else sways.
    const t = quiet ? 0 : input.time;
    bones.forEach((_bone, i) => {
      const before = i === 0 ? parent.rotation : at(i - 1).rotation;
      let turn: Quat = IDENTITY;
      if (limb.role === 'head') {
        const nod = input.talking && !quiet ? 0.09 * Math.sin(2 * Math.PI * 2.1 * t) : 0;
        turn = mul(axisAngle([0, 1, 0], quiet ? 0 : 0.06 * Math.sin(0.37 * t)), axisAngle([1, 0, 0], nod));
      } else if (limb.role === 'trunk') {
        turn = mul(axisAngle([0, 1, 0], -0.6 * 0.07 * walk * Math.sin(2 * Math.PI * leadPhase)), axisAngle([1, 0, 0], quiet ? 0 : 0.012 * Math.sin(2 * Math.PI * 0.24 * t)));
      } else if (!quiet) {
        turn = axisAngle([1, 0, 0], 0.12 * Math.sin(2 * Math.PI * (0.5 * t) - i * 0.6));
      }
      place(i, mul(before, turn));
    });
  };

  for (const bone of skeleton.order) {
    if (bone === skeleton.root) continue;
    const limb = limbOf.get(bone);
    if (limb !== undefined) solveChain(limb);
  }

  const local = new Map<string, Quat>();
  for (const bone of skeleton.order) {
    const parent = skeleton.parentOf.get(bone) ?? null;
    const rotation = figure.get(bone)!.rotation;
    local.set(bone, parent === null ? rotation : mul(conjugate(figure.get(parent)!.rotation), rotation));
  }
  return { local, rootPosition, joints: figure };
}
