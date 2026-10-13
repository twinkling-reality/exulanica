// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { PostureBlend, STANDING, postureFor, readBodyMotion, type BodyMotion } from '../src/playcanvas/things/body-motion.js';
import { readBodyPlanDocument } from '../src/playcanvas/things/documents.js';
import { gaitOf, loweredBy, solvePose, type MotionInput, type Pose } from '../src/playcanvas/things/motion.js';
import { RigidOnBonesFigure } from '../src/playcanvas/things/rigid-on-bones.js';
import { dressSkeleton, type DressedSkeleton, type Vec3 } from '../src/playcanvas/things/skeleton.js';

/*
 * A drafted body is drawn in the posture the body motion table states for what its state says it
 * is doing: resting settles it (hips lowered, feet kept where they stand), talking makes it speak,
 * anything else stands. The bodies are the thirteen hand-written creatures; what each posture should
 * be is read from the catalog's own figures, never from the code under test.
 */

const read = (path: string) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const CATALOG = read('../../../../assets/catalogs/thing-presentation/body-motion.v2.json') as {
  posture_blend: { value: number };
  postures: { key: string; lower_share: number; head_bow_rad: number; speaks: boolean }[];
  activity_postures: { activity: string; posture: string }[];
};
const MOTION: BodyMotion = readBodyMotion(CATALOG);
const FIRST: BodyMotion = readBodyMotion(read('../../../../assets/catalogs/thing-presentation/body-motion.v1.json'));
const posture = (key: string) => CATALOG.postures.find((one) => one.key === key)!;
const REST = posture('rest');

interface Fixture {
  readonly plan: Parameters<typeof readBodyPlanDocument>[0];
  readonly joints_m: Record<string, Vec3>;
}
const NAMES = ['bat', 'centaur', 'crocodile', 'dragon', 'floating_eight', 'four_arms', 'horse', 'raptor', 'serpent', 'spider', 'ten_legs', 'three_heads', 'winged_horse'];
const fixture = (name: string): Fixture => read(`./fixtures/creature-plans/${name}.json`) as Fixture;
const dressed = (name: string): DressedSkeleton => {
  const one = fixture(name);
  return dressSkeleton(readBodyPlanDocument(one.plan), new Map(Object.entries(one.joints_m)));
};
const input = (over: Partial<MotionInput> = {}): MotionInput => ({ travelled: 0, speed: 0, time: 0, holding: new Set(), reach: null, talking: false, ...over });
const resting = { lowerShare: REST.lower_share, headBow: REST.head_bow_rad };
const lowest = (pose: Pose) => Math.min(...[...pose.joints.values()].map((joint) => joint.position[1]));
const apart = (a: Vec3, b: Vec3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
/**
 * How far a foot is from where it stood, metres: all of the way for a leg that bends to reach it,
 * and only its height for a leg of one segment, which swings about its hip and keeps its foot's
 * height by moving it in or out across the body (`./motion.ts`).
 */
const footMoved = (skeleton: DressedSkeleton, bones: readonly string[], a: Vec3, b: Vec3) =>
  (skeleton.stated && bones.length === 2 ? Math.abs(a[1] - b[1]) : apart(a, b));

describe('the posture table', () => {
  it('draws rest settled and talk speaking, each as the catalog states, and an activity it names nowhere standing', () => {
    expect(postureFor(MOTION, 'rest')).toEqual({ lowerShare: REST.lower_share, headBow: REST.head_bow_rad, speaks: false });
    expect(postureFor(MOTION, 'talk').speaks).toBe(true);
    expect(postureFor(MOTION, 'idle')).toBe(STANDING);
    expect(postureFor(MOTION, null)).toBe(STANDING);
    // The first version states no postures: everything is drawn standing, as before.
    expect(FIRST.postures).toBeNull();
    expect(postureFor(FIRST, 'rest')).toBe(STANDING);
    expect(postureFor(null, 'rest')).toBe(STANDING);
  });

  it('refuses a posture out of range, one with no reason, and an activity drawn in a posture it does not state', () => {
    const changed = (edit: (doc: typeof CATALOG) => void) => {
      const doc = JSON.parse(JSON.stringify(CATALOG)) as typeof CATALOG;
      edit(doc);
      return () => readBodyMotion(doc);
    };
    expect(changed((doc) => { doc.postures[1]!.lower_share = 0.9; })).toThrow(/lower_share is not a figure/);
    expect(changed((doc) => { delete (doc.postures[1] as { reason?: string }).reason; })).toThrow(/no class or no reason/);
    expect(changed((doc) => { doc.activity_postures[0]!.posture = 'kneel'; })).toThrow(/a posture it does not state/);
    expect(changed((doc) => { doc.posture_blend.value = 0; })).toThrow(/posture_blend/);
  });

  it('settles from one posture to the next over the blend, eased, and at once when asked', () => {
    const blend = new PostureBlend();
    const rest = postureFor(MOTION, 'rest');
    const seconds = MOTION.postures!.blendSeconds;
    expect(blend.step(rest, 0, seconds).lowerShare).toBe(0);
    const half = blend.step(rest, seconds / 2, seconds);
    expect(half.lowerShare).toBeCloseTo(rest.lowerShare / 2, 6);
    expect(blend.step(rest, seconds / 2, seconds)).toBe(rest);
    // Getting up starts from where it was drawn; reduced motion takes the posture at once.
    expect(blend.step(STANDING, seconds / 4, seconds).lowerShare).toBeGreaterThan(0);
    expect(blend.step(STANDING, 0, seconds, true)).toBe(STANDING);
  });
});

describe.each(NAMES)('%s, resting', (name) => {
  const skeleton = dressed(name);
  const standing = solvePose(skeleton, input(), MOTION);
  const rest = solvePose(skeleton, input({ posture: resting }), MOTION);
  const gait = gaitOf(skeleton, MOTION);
  const lowered = loweredBy(skeleton, REST.lower_share, gait.crouch + gait.bob);

  it('is standing at a posture of none', () => {
    expect(solvePose(skeleton, input({ posture: { lowerShare: 0, headBow: 0 } }), MOTION)).toEqual(standing);
  });

  it('lowers its hips by no more than the catalog\'s share of its legs\' drop, and keeps every foot where it stands', () => {
    const drop = Math.min(...skeleton.steps.map((leg) => skeleton.rest.get(leg.bones[0]!)![1] - skeleton.rest.get(leg.bones.at(-1)!)![1]));
    expect(standing.rootPosition[1] - rest.rootPosition[1]).toBeCloseTo(lowered, 9);
    expect(lowered).toBeLessThanOrEqual(REST.lower_share * Math.max(0, drop) + 1e-9);
    for (const leg of skeleton.steps) {
      const foot = leg.bones.at(-1)!;
      expect([foot, footMoved(skeleton, leg.bones, rest.joints.get(foot)!.position, standing.joints.get(foot)!.position)]).toEqual([foot, expect.closeTo(0, 3)]);
    }
    // No joint goes below the ground the figure stands on, nor lower than the hips went.
    expect(lowest(rest)).toBeGreaterThanOrEqual(0);
    expect(lowest(standing) - lowest(rest)).toBeLessThanOrEqual(lowered + 1e-9);
  });

  it('keeps every foot where it stands while it rises into a walk', () => {
    const walking = solvePose(skeleton, input({ posture: resting, speed: 2 * gait.fullSpeed, travelled: 0.3 * gait.cycle }), MOTION);
    const plain = solvePose(skeleton, input({ speed: 2 * gait.fullSpeed, travelled: 0.3 * gait.cycle }), MOTION);
    for (const leg of skeleton.steps) {
      if (leg.role === 'tentacle') continue;
      const foot = leg.bones.at(-1)!;
      expect(footMoved(skeleton, leg.bones, walking.joints.get(foot)!.position, plain.joints.get(foot)!.position)).toBeLessThan(1e-3);
    }
  });
});

describe('which bodies settle', () => {
  it('is every body that steps on legs it can bend; a body on no legs or on tentacles is not lowered', () => {
    const settled = NAMES.filter((name) => {
      const skeleton = dressed(name);
      const gait = gaitOf(skeleton, MOTION);
      return loweredBy(skeleton, REST.lower_share, gait.crouch + gait.bob) > 1e-3;
    });
    for (const name of NAMES) {
      const skeleton = dressed(name);
      const legs = skeleton.steps.filter((leg) => leg.role === 'leg');
      if (legs.length === 0 || skeleton.steps.some((leg) => leg.role === 'tentacle')) expect(settled).not.toContain(name);
    }
    expect(settled).toEqual(expect.arrayContaining(['raptor', 'horse', 'spider']));
  });
});

describe('a figure of rigid parts on bones', () => {
  function figure(name: string, motion: BodyMotion | null) {
    const canvas = document.createElement('canvas');
    const device = new pc.NullGraphicsDevice(canvas);
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    app.init(options);
    const parent = new pc.Entity('region');
    app.root.addChild(parent);
    const one = fixture(name);
    const model = new pc.Entity('look');
    for (const [bone, at] of Object.entries(one.joints_m)) {
      const node = new pc.Entity(`bone:${bone}`);
      node.setLocalPosition(at[0], at[1], at[2]);
      model.addChild(node);
    }
    const plan = readBodyPlanDocument(one.plan);
    const height = Math.max(...Object.values(one.joints_m).map((at) => at[1])) * 1000;
    const drawn = new RigidOnBonesFigure(parent, model, plan, 'thing:test', height, height, motion);
    const hips = drawn.root.findByName(`bone:${drawn.skeleton.root}`) as pc.Entity;
    return { drawn, hipsHeight: () => hips.getLocalPosition().y, done: () => app.destroy() };
  }
  const pose = (activity: string | null, deltaSeconds: number, more: { reducedMotion?: boolean } = {}) =>
    ({ position: [0, 0, 0] as const, facing: 0, deltaSeconds, activity, ...more });

  it('settles into rest over the catalog\'s blend once its state says it rests, and stands again for anything else', () => {
    const { drawn, hipsHeight, done } = figure('raptor', MOTION);
    drawn.pose(pose('idle', 0.1));
    const stood = hipsHeight();
    drawn.pose(pose('rest', MOTION.postures!.blendSeconds / 2));
    const halfway = hipsHeight();
    drawn.pose(pose('rest', MOTION.postures!.blendSeconds));
    const rested = hipsHeight();
    expect(halfway).toBeLessThan(stood);
    expect(rested).toBeLessThan(halfway);
    drawn.pose(pose('stand', 2 * MOTION.postures!.blendSeconds));
    expect(hipsHeight()).toBeCloseTo(stood, 9);
    done();
  });

  it('takes the posture at once under reduced motion, and never with a table that states none', () => {
    const quiet = figure('raptor', MOTION);
    quiet.drawn.pose(pose('idle', 0.1, { reducedMotion: true }));
    const stood = quiet.hipsHeight();
    quiet.drawn.pose(pose('rest', 0.01, { reducedMotion: true }));
    const gait = gaitOf(quiet.drawn.skeleton, MOTION);
    const scale = 1;
    expect(stood - quiet.hipsHeight()).toBeCloseTo(scale * loweredBy(quiet.drawn.skeleton, REST.lower_share, gait.crouch + gait.bob), 9);
    quiet.done();
    const first = figure('raptor', FIRST);
    first.drawn.pose(pose('idle', 0.1));
    const before = first.hipsHeight();
    first.drawn.pose(pose('rest', 5));
    expect(first.hipsHeight()).toBe(before);
    first.done();
  });

  it('speaks while its state says it talks: a jaw opens on the beat that stays shut standing', () => {
    const name = NAMES.find((one) => dressed(one).limbs.some((limb) => limb.role === 'jaw'))!;
    const jawOf = (activity: string) => {
      const { drawn, done } = figure(name, MOTION);
      const jaw = drawn.skeleton.limbs.find((limb) => limb.role === 'jaw')!.bones[0]!;
      drawn.pose(pose(activity, 0.1));
      // A quarter of a beat on: the jaw is open where the body speaks.
      drawn.pose(pose(activity, 0.25 / MOTION.speechBeats));
      const rotation = (drawn.root.findByName(`bone:${jaw}`) as pc.Entity).getLocalRotation();
      done();
      return 2 * Math.acos(Math.min(1, Math.abs(rotation.w)));
    };
    expect(jawOf('stand')).toBeCloseTo(0, 6);
    expect(jawOf('talk')).toBeGreaterThan(0.05);
  });
});
