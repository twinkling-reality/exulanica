import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readBodyPlans } from '../src/playcanvas/things/documents.js';
import { SkeletonRefused, dressSkeleton, type BodyPlanEntry, type Vec3 } from '../src/playcanvas/things/skeleton.js';
import { DUTY, gaitOf, solvePose, type MotionInput } from '../src/playcanvas/things/motion.js';

// The body plans this repository ships, read as the drawing reads them.
const PLANS = readBodyPlans(JSON.parse(readFileSync(new URL('../../../../assets/catalogs/things/body-plans.v1.json', import.meta.url), 'utf8')));
const HUMANOID = PLANS.get('humanoid/v1')!;

/**
 * A blocky figure's joints, as the things contract states them: a 1,700 mm figure in the T-pose,
 * facing +y with its left at -x (slot frame, millimetres), here in glTF metres (X = -x, Y = z, Z = y).
 * The 15 required bones with chest and neck; no shoulders, no upper chest.
 */
const BLOCKY_SLOT: Record<string, [number, number, number]> = {
  hips: [0, 0, 900], spine: [0, 0, 1000], chest: [0, 0, 1150], neck: [0, 0, 1400], head: [0, 0, 1450],
  leftUpperLeg: [-90, 0, 860], leftLowerLeg: [-90, 0, 460], leftFoot: [-90, 0, 80],
  rightUpperLeg: [90, 0, 860], rightLowerLeg: [90, 0, 460], rightFoot: [90, 0, 80],
  leftUpperArm: [-200, 0, 1350], leftLowerArm: [-460, 0, 1350], leftHand: [-700, 0, 1350],
  rightUpperArm: [200, 0, 1350], rightLowerArm: [460, 0, 1350], rightHand: [700, 0, 1350],
};
const gltf = ([x, y, z]: [number, number, number]): Vec3 => [-x / 1000, z / 1000, y / 1000];
const BLOCKY = new Map(Object.entries(BLOCKY_SLOT).map(([bone, at]) => [bone, gltf(at)]));

/** A body plan with ten legs, written as data a drafter could write: five body segments in a row. */
function tenLegged(): { plan: BodyPlanEntry; joints: Map<string, Vec3> } {
  const bones: { name: string; parent: string | null; required: boolean }[] = [];
  const joints = new Map<string, Vec3>();
  const add = (name: string, parent: string | null, at: Vec3) => { bones.push({ name, parent, required: parent === null }); joints.set(name, at); };
  for (let i = 0; i < 5; i += 1) add(`body${i}`, i === 0 ? null : `body${i - 1}`, [0, 0.62, 0.9 - 0.45 * i]);
  add('neck', 'body0', [0, 0.78, 1.25]);
  add('head', 'neck', [0, 0.92, 1.5]);
  add('tail1', 'body4', [0, 0.62, -1.2]);
  add('tail2', 'tail1', [0, 0.5, -1.65]);
  for (let i = 0; i < 5; i += 1) {
    for (const [side, x] of [['Left', 1], ['Right', -1]] as const) {
      const z = 0.9 - 0.45 * i;
      add(`leg${i}${side}1`, `body${i}`, [x * 0.2, 0.6, z]);
      add(`leg${i}${side}2`, `leg${i}${side}1`, [x * 0.6, 0.86, z + 0.04]);
      add(`leg${i}${side}3`, `leg${i}${side}2`, [x * 0.92, 0.04, z + 0.08]);
    }
  }
  return { plan: { key: 'ten-legged', version: 1, bones, sockets: [] }, joints };
}

describe('a body plan dressed by a look', () => {
  it('reads a person by its shape: two legs, two arms carrying the hand sockets, a head and a trunk', () => {
    const skeleton = dressSkeleton(HUMANOID, BLOCKY);
    const byRole = (role: string) => skeleton.limbs.filter((limb) => limb.role === role).map((limb) => limb.bones.join('>')).sort();
    expect(skeleton.root).toBe('hips');
    expect(byRole('leg')).toEqual(['leftUpperLeg>leftLowerLeg>leftFoot', 'rightUpperLeg>rightLowerLeg>rightFoot']);
    expect(byRole('arm')).toEqual(['leftUpperArm>leftLowerArm>leftHand', 'rightUpperArm>rightLowerArm>rightHand']);
    expect(byRole('head')).toEqual(['neck>head']);
    expect(byRole('trunk')).toEqual(['spine>chest']);
    // The plan's sockets sit on the hands it names.
    expect(Object.fromEntries(skeleton.socketBones)).toEqual(Object.fromEntries(HUMANOID.sockets.map((s) => [s.key, s.bone])));
    // Left is the figure's +X: the left limbs are on side 1.
    for (const limb of skeleton.limbs) {
      if (limb.bones[0]!.startsWith('left')) expect(limb.side).toBe(1);
      if (limb.bones[0]!.startsWith('right')) expect(limb.side).toBe(-1);
    }
  });

  it('hangs a joint from its nearest dressed ancestor when the look leaves bones out', () => {
    const skeleton = dressSkeleton(HUMANOID, BLOCKY);
    // The plan hangs the upper arm from the shoulder and the shoulder from the upper chest; this look
    // dresses neither, so the arm hangs from the chest.
    const planParent = new Map(HUMANOID.bones.map((b) => [b.name, b.parent]));
    expect(planParent.get('leftUpperArm')).toBe('leftShoulder');
    expect(skeleton.parentOf.get('leftUpperArm')).toBe('chest');
    expect(skeleton.parentOf.get('head')).toBe('neck');
  });

  it('steps a person left and right in opposite halves of the cycle', () => {
    const legs = dressSkeleton(HUMANOID, BLOCKY).limbs.filter((limb) => limb.role === 'leg');
    const left = legs.find((leg) => leg.side === 1)!, right = legs.find((leg) => leg.side === -1)!;
    expect(Math.abs(left.phase - right.phase)).toBe(0.5);
  });

  it('reads ten legs from a ten-legged plan, alternating side to side and rank to rank', () => {
    const { plan, joints } = tenLegged();
    const skeleton = dressSkeleton(plan, joints);
    const legs = skeleton.limbs.filter((limb) => limb.role === 'leg');
    expect(legs).toHaveLength(10);
    expect(skeleton.limbs.filter((limb) => limb.role === 'head').map((limb) => limb.bones.at(-1))).toEqual(['head']);
    expect(skeleton.limbs.filter((limb) => limb.role === 'appendage').map((limb) => limb.bones.join('>'))).toEqual(['tail1>tail2']);
    const phase = (rank: number, side: 'Left' | 'Right') => legs.find((leg) => leg.bones[0] === `leg${rank}${side}1`)!.phase;
    for (let rank = 0; rank < 5; rank += 1) {
      expect(Math.abs(phase(rank, 'Left') - phase(rank, 'Right'))).toBe(0.5);
      if (rank > 0) expect(Math.abs(phase(rank, 'Left') - phase(rank - 1, 'Left'))).toBe(0.5);
    }
  });

  it('refuses by name a joint the plan has no bone for, a required bone left out, and two skeletons', () => {
    expect(() => dressSkeleton(HUMANOID, BLOCKY)).not.toThrow();
    const unknown = new Map(BLOCKY);
    unknown.set('tail', [0, 1, -0.2]);
    expect(() => dressSkeleton(HUMANOID, unknown)).toThrow(expect.objectContaining({ reason: 'look_bone_unknown' }));
    const missing = new Map(BLOCKY);
    missing.delete('leftFoot');
    expect(() => dressSkeleton(HUMANOID, missing)).toThrow(expect.objectContaining({ reason: 'look_required_bone_missing' }));
    const { plan, joints } = tenLegged();
    const two: BodyPlanEntry = { ...plan, bones: [...plan.bones, { name: 'moon', parent: null, required: false }] };
    const twoJoints = new Map(joints);
    twoJoints.set('moon', [0, 3, 0]);
    expect(() => dressSkeleton(two, twoJoints)).toThrow(SkeletonRefused);
    expect(() => dressSkeleton(two, twoJoints)).toThrow(expect.objectContaining({ reason: 'look_not_one_skeleton' }));
  });
});

const standing = (over: Partial<MotionInput> = {}): MotionInput => ({
  travelled: 0, speed: 0, time: 0, holding: new Set(), reach: null, talking: false, ...over,
});

describe('procedural motion for any skeleton', () => {
  it('stands a figure on its rest feet when it is not moving', () => {
    const skeleton = dressSkeleton(HUMANOID, BLOCKY);
    const pose = solvePose(skeleton, standing({ reducedMotion: true }));
    for (const foot of ['leftFoot', 'rightFoot']) {
      const at = pose.joints.get(foot)!.position, rest = BLOCKY.get(foot)!;
      for (let i = 0; i < 3; i += 1) expect(at[i]).toBeCloseTo(rest[i]!, 5);
    }
  });

  it('keeps a foot planted while the body walks over it: the gait is clocked by distance', () => {
    const skeleton = dressSkeleton(HUMANOID, BLOCKY);
    const { cycle } = gaitOf(skeleton);
    const left = skeleton.limbs.find((limb) => limb.role === 'leg' && limb.side === 1)!;
    // Walking forward (+Z), the body has moved `travelled` metres; a foot on the ground is fixed in
    // the world, so its world position (body offset plus its place in the figure) does not change.
    const world = (travelled: number) => {
      const foot = solvePose(skeleton, standing({ travelled, speed: 1.2, reducedMotion: true })).joints.get('leftFoot')!.position;
      return [foot[0], foot[1], foot[2] + travelled];
    };
    // A stretch of the cycle inside the left foot's stance (phase 0.05 to 0.5 of its cycle).
    const start = (0.05 - left.phase + 1) % 1 * cycle;
    const a = world(start), b = world(start + 0.45 * cycle);
    expect(DUTY).toBeGreaterThan(0.5);
    for (let i = 0; i < 3; i += 1) expect(Math.abs(a[i]! - b[i]!)).toBeLessThan(0.002);
  });

  it('never lets neighbouring feet of a many-legged body cross', () => {
    const { plan, joints } = tenLegged();
    const skeleton = dressSkeleton(plan, joints);
    const { stride } = gaitOf(skeleton);
    // Ranks hang 0.45 m apart; neighbouring ranks step in opposite halves, each foot sweeping a stride.
    expect(stride).toBeLessThanOrEqual(0.9 * 0.45 + 1e-9);
  });

  it('carries a held thing in front of the body', () => {
    const skeleton = dressSkeleton(HUMANOID, BLOCKY);
    const hand = skeleton.socketBones.get('hand.right')!;
    const empty = solvePose(skeleton, standing({ reducedMotion: true })).joints.get(hand)!.position;
    const holding = solvePose(skeleton, standing({ reducedMotion: true, holding: new Set(['hand.right']) })).joints.get(hand)!.position;
    expect(holding[2]).toBeGreaterThan(empty[2] + 0.15);
  });
});
