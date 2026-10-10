import { readFileSync, writeFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readBodyMotion, type BodyMotion } from '../src/playcanvas/things/body-motion.js';
import { ThingDocumentRefused, readBodyPlanDocument, readBodyPlans } from '../src/playcanvas/things/documents.js';
import { DUTY, bodyTravel, gaitOf, solvePose, type MotionInput, type Pose, type Quat } from '../src/playcanvas/things/motion.js';
import { dressSkeleton, type DressedSkeleton, type Limb, type Vec3 } from '../src/playcanvas/things/skeleton.js';

/*
 * A drafted body is posed from the chains its plan states, one rule a role, by the figures of the
 * body motion catalog. The bodies here are the thirteen hand-written creatures, each as this
 * server assembles it (`scripts/things/creature_plan_fixtures.py` writes the files and
 * `tests/test_creature_plan_fixtures.py` fails when one is stale). What each should be is worked
 * out here from its recipe and from the catalog's own figures, never from the code under test.
 */

const read = (path: string) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));

interface Recipe {
  readonly posture: string;
  readonly spine: number;
  readonly upper_body: string;
  readonly tail: number;
  readonly heads: readonly { readonly neck: number; readonly jaw: boolean }[];
  readonly limbs: readonly { readonly role: string; readonly count: number; readonly segments: number }[];
  readonly extent_mm: { readonly length: number; readonly width: number; readonly height: number; readonly span: number };
}
const RECIPES_FILE = read('../../../../tests/fixtures/creatures/creatures.v1.json') as {
  held_out: Record<string, { recipe: Recipe }>;
  development: Record<string, { recipe: Recipe }>;
};
const RECIPES: Record<string, Recipe> = Object.fromEntries(
  Object.entries({ ...RECIPES_FILE.held_out, ...RECIPES_FILE.development }).map(([name, entry]) => [name, entry.recipe]),
);
const NAMES = Object.keys(RECIPES).sort();

const CATALOG = read('../../../../assets/catalogs/thing-presentation/body-motion.v1.json') as {
  profile: string;
  entries: { key: string; value: number; unit: string; class: string; reason: string }[];
};
/** A figure of the catalog, read from the file by its key: what the tests work their expectations from. */
const stated = (key: string): number => CATALOG.entries.find((entry) => entry.key === key)!.value;
const MOTION: BodyMotion = readBodyMotion(CATALOG);

interface Fixture {
  readonly plan: { limbs: { key: string; role: string; side: string; order: number; bones: string[] }[]; bones: { name: string; parent: string | null }[] };
  readonly kind: { body: { extent_mm: Recipe['extent_mm'] } };
  readonly joints_m: Record<string, Vec3>;
}
const fixture = (name: string): Fixture => read(`./fixtures/creature-plans/${name}.json`) as Fixture;
const dressed = (name: string): DressedSkeleton => {
  const one = fixture(name);
  return dressSkeleton(readBodyPlanDocument(one.plan), new Map(Object.entries(one.joints_m)));
};
const SKELETONS = new Map(NAMES.map((name) => [name, dressed(name)]));
const skeletonOf = (name: string) => SKELETONS.get(name)!;

const input = (over: Partial<MotionInput> = {}): MotionInput => ({ travelled: 0, speed: 0, time: 0, holding: new Set(), reach: null, talking: false, ...over });
const angleOf = (q: Quat) => 2 * Math.atan2(Math.hypot(q[0], q[1], q[2]), Math.abs(q[3]));
const limbsOf = (skeleton: DressedSkeleton, role: string) => skeleton.limbs.filter((limb) => limb.role === role);
const count = (skeleton: DressedSkeleton, role: string) => limbsOf(skeleton, role).length;
const recipeCount = (recipe: Recipe, role: string) => recipe.limbs.filter((group) => group.role === role).reduce((sum, group) => sum + group.count, 0);
/** Every pose of one walk: `samples` moments of one gait cycle at a full walk. */
function walk(skeleton: DressedSkeleton, samples: number, over: Partial<MotionInput> = {}): { travelled: number; pose: Pose }[] {
  const gait = gaitOf(skeleton, MOTION);
  return Array.from({ length: samples + 1 }, (_unused, i) => {
    const travelled = (gait.cycle * i) / samples;
    return { travelled, pose: solvePose(skeleton, input({ travelled, speed: 2 * gait.fullSpeed, time: 0.37 * i, ...over }), MOTION) };
  });
}

describe('the thirteen fixtures', () => {
  it('are the thirteen hand-written creatures', () => {
    expect(NAMES).toHaveLength(13);
  });
});

describe.each(NAMES)('%s, dressed from the chains its plan states', (name) => {
  const recipe = RECIPES[name]!;
  const skeleton = skeletonOf(name);

  it('has the limbs its recipe states, each with its chain\'s role', () => {
    expect(skeleton.stated).toBe(true);
    for (const role of ['leg', 'arm', 'wing', 'fin', 'tentacle']) expect([role, count(skeleton, role)]).toEqual([role, recipeCount(recipe, role)]);
    // One neck for each head that has one, with as many bones as the recipe gives it; one jaw for each jawed head.
    expect(limbsOf(skeleton, 'neck').map((limb) => limb.bones.length).sort()).toEqual(recipe.heads.filter((head) => head.neck > 0).map((head) => head.neck).sort());
    expect(count(skeleton, 'jaw')).toBe(recipe.heads.filter((head) => head.jaw).length);
    // A head is read as one where a neck ends at it or a jaw hangs from it; a head with neither keeps its rest turn.
    expect(count(skeleton, 'skull')).toBe(recipe.heads.filter((head) => head.neck > 0 || head.jaw).length);
    expect(count(skeleton, 'still')).toBe(recipe.heads.filter((head) => head.neck === 0 && !head.jaw).length);
    expect(limbsOf(skeleton, 'tail').map((limb) => limb.bones.length)).toEqual(recipe.tail > 0 ? [recipe.tail] : []);
    // The body's spine, and the risen torso of a body that has one.
    expect(limbsOf(skeleton, 'spine').map((limb) => limb.bones.length)).toEqual(recipe.upper_body === 'none' ? [recipe.spine] : [recipe.spine, expect.any(Number)]);
    // Nothing is read from the shape: none of the shape's own roles appears.
    for (const role of ['head', 'trunk', 'appendage']) expect(count(skeleton, role)).toBe(0);
  });

  it('covers every bone but the root once, each limb hanging from its first bone\'s parent', () => {
    const covered = skeleton.limbs.flatMap((limb) => limb.bones);
    expect([...covered].sort()).toEqual(skeleton.order.filter((bone) => bone !== skeleton.root).sort());
    for (const limb of skeleton.limbs) {
      expect(skeleton.parentOf.get(limb.bones[0]!)).toBe(limb.from);
      limb.bones.slice(1).forEach((bone, i) => expect(skeleton.parentOf.get(bone)).toBe(limb.bones[i]));
    }
  });

  it('steps its legs by rank and side, left and right in turn and each rank against the next', () => {
    const one = fixture(name);
    for (const leg of limbsOf(skeleton, 'leg')) {
      const chain = one.plan.limbs.find((limb) => limb.bones[0] === leg.bones[0])!;
      expect(chain.role).toBe('leg');
      expect(leg.side).toBe(chain.side === 'left' ? 1 : -1);
      // Left is the figure's +X.
      expect(Math.sign(one.joints_m[leg.bones.at(-1)!]![0])).toBe(leg.side);
      const evenRank = chain.order % 2 === 0;
      expect(leg.phase).toBe((chain.side === 'left') === evenRank ? 0 : 0.5);
    }
  });

  it('keeps every planted foot where it stands, at its height, through a walk', () => {
    const gait = gaitOf(skeleton, MOTION);
    if (recipe.posture === 'serpentine') {
      expect(skeleton.steps).toHaveLength(0);
      return;
    }
    expect(skeleton.gait).toBe('steps');
    expect(skeleton.steps.length).toBe(recipeCount(recipe, 'leg') || recipeCount(recipe, 'tentacle'));
    expect(gait.stride).toBeGreaterThan(0);
    const poses = walk(skeleton, 120);
    for (const foot of skeleton.steps) {
      const end = foot.bones.at(-1)!;
      const restHeight = skeleton.rest.get(end)![1];
      let planted: number | null = null;
      let stance = 0;
      for (const { travelled, pose } of poses) {
        const phase = (travelled / gait.cycle + foot.phase) % 1;
        if (phase < 0.02 || phase > DUTY - 0.02) {
          // Between stances the foot is lifted and carried forward: a new stance, a new point.
          planted = null;
          continue;
        }
        stance += 1;
        const at = pose.joints.get(end)!.position;
        // The figure's frame moves with the body: the ground under the foot is the frame's z plus the ground walked.
        const ground = at[2] + travelled;
        planted ??= ground;
        // To a micrometre.
        expect(Math.abs(ground - planted)).toBeLessThan(1e-6);
        expect(Math.abs(at[1] - restHeight)).toBeLessThan(1e-6);
      }
      // Positive control: the walk had stances to hold.
      expect(stance).toBeGreaterThan(40);
    }
  });

  it('turns no head further than a look about and a nod, walking or speaking, and never hangs one as an arm', () => {
    // An upright body leans into its walk by a twentieth of a radian (the solver's own lean); a lying one does not.
    const lean = skeleton.lying ? 0 : 0.05;
    const skulls = limbsOf(skeleton, 'skull').map((limb) => limb.bones[0]!);
    let silent = 0, speaking = 0;
    for (const { pose } of walk(skeleton, 90)) for (const skull of skulls) silent = Math.max(silent, angleOf(pose.joints.get(skull)!.rotation));
    for (const { pose } of walk(skeleton, 90, { talking: true })) for (const skull of skulls) speaking = Math.max(speaking, angleOf(pose.joints.get(skull)!.rotation));
    expect(silent).toBeLessThanOrEqual(stated('look_about_rad') + lean + 1e-9);
    expect(speaking).toBeLessThanOrEqual(Math.hypot(stated('look_about_rad'), stated('nod_rad')) + lean + 1e-9);
    if (skulls.length > 0) {
      // Positive control: the heads do move.
      expect(silent).toBeGreaterThan(0.01);
      expect(speaking).toBeGreaterThan(silent);
    }
  });

  it('opens a jaw on each beat of speech, to the catalog\'s angle, and keeps it shut otherwise and on what it carries', () => {
    const jaws = limbsOf(skeleton, 'jaw');
    const beat = 1 / stated('speech_beats_per_second');
    for (const jaw of jaws) {
      const bone = jaw.bones[0]!;
      const local = (over: Partial<MotionInput>) => angleOf(solvePose(skeleton, input(over), MOTION).local.get(bone)!);
      expect(local({ time: beat / 2, talking: true })).toBeCloseTo(stated('jaw_open_rad'), 9);
      expect(local({ time: beat, talking: true })).toBeCloseTo(0, 9);
      expect(local({ time: beat / 2, talking: false })).toBeCloseTo(0, 9);
      expect(local({ time: beat / 2, talking: true, reducedMotion: true })).toBeCloseTo(0, 9);
      // Its socket is the plan's: holding with it keeps it shut while the being speaks.
      expect(jaw.sockets.length).toBeLessThanOrEqual(1);
      for (const socket of jaw.sockets) expect(local({ time: beat / 2, talking: true, holding: new Set([socket]) })).toBeCloseTo(0, 9);
    }
  });

  it('carries its wings folded inside its width, standing and walking', () => {
    const wings = limbsOf(skeleton, 'wing');
    const half = fixture(name).kind.body.extent_mm.width / 2000;
    for (const wing of wings) {
      // Positive control: the look draws the wing spread, beyond the body's width.
      expect(Math.abs(skeleton.rest.get(wing.bones.at(-1)!)![0])).toBeGreaterThan(half);
    }
    for (const { pose } of [...walk(skeleton, 24), { pose: solvePose(skeleton, input({ time: 5 }), MOTION) }]) {
      for (const wing of wings) for (const bone of wing.bones) expect(Math.abs(pose.joints.get(bone)!.position[0])).toBeLessThan(half);
    }
  });

  it('holds every stated chain but a leg and an arm at rest when no table is handed', () => {
    const pose = solvePose(skeleton, input({ time: 3.3, talking: true }));
    for (const limb of skeleton.limbs) {
      if (limb.role === 'leg' || limb.role === 'arm' || skeleton.steps.includes(limb)) continue;
      for (const bone of limb.bones) expect(angleOf(pose.local.get(bone)!)).toBeCloseTo(0, 9);
    }
  });

  it('does not move with the clock under reduced motion', () => {
    const at = (time: number) => solvePose(skeleton, input({ time, talking: true, reducedMotion: true }), MOTION);
    expect([...at(7.7).local]).toEqual([...at(0).local]);
    // And nothing is held bent mid-wave: a tail, a tentacle, a fin and a jaw are at rest, and so are a
    // neck and a head, but on a body that lies in its wave, whose neck turns its head back to the front.
    const resting = skeleton.gait === 'wave' ? ['tail', 'tentacle', 'fin', 'jaw'] : ['tail', 'tentacle', 'fin', 'neck', 'skull', 'jaw'];
    for (const limb of skeleton.limbs) {
      if (!resting.includes(limb.role)) continue;
      for (const bone of limb.bones) expect(angleOf(at(7.7).local.get(bone)!)).toBeCloseTo(0, 9);
    }
  });
});

describe('a walking body\'s sway', () => {
  it('is turned back along the spine: the shoulders sway against the hips by as much, and the neck returns the head to the front', () => {
    for (const name of ['dragon', 'horse', 'ten_legs']) {
      const skeleton = skeletonOf(name);
      const spine = limbsOf(skeleton, 'spine')[0]!;
      let seen = 0;
      for (const { pose } of walk(skeleton, 40, { time: 0 })) {
        const yaw = (bone: string) => {
          const q = pose.joints.get(bone)!.rotation;
          return 2 * Math.atan2(q[1], q[3]);
        };
        expect(yaw(spine.bones.at(-1)!)).toBeCloseTo(-yaw(skeleton.root), 9);
        for (const neck of limbsOf(skeleton, 'neck')) expect(yaw(neck.bones.at(-1)!)).toBeCloseTo(0, 9);
        seen = Math.max(seen, Math.abs(yaw(skeleton.root)));
      }
      // The hips do sway: by the solver's seven hundredths of a radian at a full walk.
      expect(seen).toBeCloseTo(0.07, 2);
    }
  });
});

describe('a tail and a tentacle that hangs', () => {
  it('bend each joint to the catalog\'s angle, the bend travelling outward a lag a joint', () => {
    const period = stated('wave_period_seconds'), lag = stated('wave_lag_cycles');
    for (const [name, role] of [['dragon', 'tail'], ['crocodile', 'tail'], ['floating_eight', 'tentacle']] as const) {
      const skeleton = skeletonOf(name);
      const chain = limbsOf(skeleton, role)[0]!;
      expect(chain.order).toBe(0);
      const local = (time: number, k: number) => solvePose(skeleton, input({ time }), MOTION).local.get(chain.bones[k]!)!;
      chain.bones.forEach((_bone, k) => {
        // Joint k is at the height of its wave a quarter period in, k lags later.
        expect(angleOf(local(period * (0.25 + k * lag), k))).toBeCloseTo(stated('wave_rad'), 9);
        if (k > 0) local(1.234 + lag * period, k).forEach((value, i) => expect(value).toBeCloseTo(local(1.234, k - 1)[i]!, 9));
      });
    }
  });

  it('swing side to side: a tail along the ground about the upright, a tentacle that hangs about the body\'s length', () => {
    const period = stated('wave_period_seconds');
    const tail = limbsOf(skeletonOf('dragon'), 'tail')[0]!;
    const turn = solvePose(skeletonOf('dragon'), input({ time: period / 4 }), MOTION).local.get(tail.bones[0]!)!;
    // A turn about the upright: its axis is (0, 1, 0), tilted by the tail's droop (0.84 m over 3.6 m).
    expect(Math.abs(turn[1])).toBeGreaterThan(3 * Math.hypot(turn[0], turn[2]));
    const front = limbsOf(skeletonOf('floating_eight'), 'tentacle')[0]!;
    const hung = solvePose(skeletonOf('floating_eight'), input({ time: period / 4 }), MOTION).local.get(front.bones[0]!)!;
    expect(Math.abs(hung[2])).toBeGreaterThan(2 * Math.hypot(hung[0], hung[1]));
  });
});

describe('a body with no leg', () => {
  it('steps on its tentacles, alternate ones together', () => {
    const skeleton = skeletonOf('floating_eight');
    expect(skeleton.gait).toBe('steps');
    const one = fixture('floating_eight');
    for (const tentacle of skeleton.steps) {
      const chain = one.plan.limbs.find((limb) => limb.bones[0] === tentacle.bones[0])!;
      expect(tentacle.phase).toBe(chain.order % 2 === 0 ? 0 : 0.5);
    }
    expect(new Set(skeleton.steps.map((tentacle) => tentacle.phase))).toEqual(new Set([0, 0.5]));
  });

  describe('lying along the ground', () => {
    const skeleton = skeletonOf('serpent');
    const spine = limbsOf(skeleton, 'spine')[0]!;
    const chain = [skeleton.root, ...spine.bones];
    // The spine's length, from the fixture's own joints, and the wave the catalog states for it.
    const spineLength = chain.slice(1).reduce((sum, bone, i) => sum + Math.hypot(...chain.slice(i, i + 1).map((before) => {
      const a = skeleton.rest.get(before)!, b = skeleton.rest.get(bone)!;
      return Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
    })), 0);
    const wavelength = stated('spine_wavelength_share') * spineLength;
    const aside = (stated('spine_wave_rad') * wavelength) / (2 * Math.PI);
    const xs = (travelled: number, speed = 1) => {
      const pose = solvePose(skeleton, input({ travelled, speed }), MOTION);
      return chain.map((bone) => pose.joints.get(bone)!.position[0]);
    };

    it('moves by a wave down its spine: sixteen joints, 7.65 m, swinging about 0.41 m to each side', () => {
      expect(skeleton.gait).toBe('wave');
      expect(spine.bones).toHaveLength(RECIPES['serpent']!.spine);
      expect(spineLength).toBeCloseTo(7.651, 3);
      expect(aside).toBeCloseTo(0.408, 3);
      // The root is over the wave's middle at the start and at its widest a quarter wave on.
      expect(xs(0)[0]).toBeCloseTo(0, 9);
      expect(xs(wavelength / 4)[0]).toBeCloseTo(aside, 9);
      expect(xs((3 * wavelength) / 4)[0]).toBeCloseTo(-aside, 9);
      const widest = Math.max(...xs(0).map(Math.abs));
      expect(widest).toBeGreaterThan(0.9 * aside);
      expect(widest).toBeLessThan(1.05 * aside);
    });

    it('follows itself: each joint comes to where the joint ahead of it was, once the body has covered the gap between them', () => {
      const gap = spineLength / spine.bones.length;
      for (const start of [0, 0.7, 3.1]) {
        const before = xs(start), after = xs(start + gap);
        for (let k = 0; k + 1 < chain.length; k += 1) expect(Math.abs(after[k]! - before[k + 1]!)).toBeLessThan(0.02);
      }
      // Positive control: without covering the gap they are not there.
      expect(Math.abs(xs(0)[0]! - xs(0)[1]!)).toBeGreaterThan(0.1);
    });

    it('is clocked by the ground itself, lies still and curved when it stops, and keeps its head to the front', () => {
      expect(bodyTravel(skeleton, 0.25, 0.01, MOTION)).toBe(0.25);
      // A body that steps counts slow ground for more: its steps shorten.
      expect(bodyTravel(skeletonOf('dragon'), 0.25, 0.01, MOTION)).toBeGreaterThan(0.25);
      expect(xs(2.2, 0)).toEqual(xs(2.2, 1));
      const pose = solvePose(skeleton, input({ travelled: 1.9, speed: 1 }), MOTION);
      for (const skull of limbsOf(skeleton, 'skull')) expect(angleOf(pose.joints.get(skull.bones[0]!)!.rotation)).toBeCloseTo(0, 9);
      // No bob and no lean: nothing of the spine leaves its height.
      for (const bone of chain) expect(pose.joints.get(bone)!.position[1]).toBeCloseTo(skeleton.rest.get(bone)![1], 9);
    });
  });
});

describe('the speed a full walk is drawn from', () => {
  it('is the body\'s own stride at the catalog\'s cadence, and the shipped figures\' one speed for a plan that states no chains', () => {
    for (const name of NAMES) {
      const gait = gaitOf(skeletonOf(name), MOTION);
      if (gait.stride > 0) expect(gait.fullSpeed).toBeCloseTo(stated('full_walk_strides_per_second') * gait.stride, 12);
      expect(gaitOf(skeletonOf(name)).fullSpeed).toBe(0.5);
    }
    // A longer-legged body's full walk is faster: the dragon's against the bat's.
    expect(gaitOf(skeletonOf('dragon'), MOTION).fullSpeed).toBeGreaterThan(20 * gaitOf(skeletonOf('bat'), MOTION).fullSpeed);
  });
});

/* A shipped plan states no chains, and its figure is posed exactly as before chains were read. */
const SHIPPED = readBodyPlans(read('../../../../assets/catalogs/things/body-plans.v1.json'));
const HUMANOID = SHIPPED.get('humanoid/v1')!;
const BLOCKY_SLOT: Record<string, [number, number, number]> = {
  hips: [0, 0, 900], spine: [0, 0, 1000], chest: [0, 0, 1150], neck: [0, 0, 1400], head: [0, 0, 1450],
  leftUpperLeg: [-90, 0, 860], leftLowerLeg: [-90, 0, 460], leftFoot: [-90, 0, 80],
  rightUpperLeg: [90, 0, 860], rightLowerLeg: [90, 0, 460], rightFoot: [90, 0, 80],
  leftUpperArm: [-200, 0, 1350], leftLowerArm: [-460, 0, 1350], leftHand: [-700, 0, 1350],
  rightUpperArm: [200, 0, 1350], rightLowerArm: [460, 0, 1350], rightHand: [700, 0, 1350],
};
const BLOCKY = new Map(Object.entries(BLOCKY_SLOT).map(([bone, [x, y, z]]) => [bone, [-x / 1000, z / 1000, y / 1000] as Vec3]));

describe('a plan that states no chains', () => {
  const skeleton = dressSkeleton(HUMANOID, BLOCKY);

  it('is read from its shape, and a table changes nothing of its pose', () => {
    expect(HUMANOID.limbs).toBeUndefined();
    expect(skeleton.stated).toBe(false);
    expect(skeleton.lying).toBe(false);
    expect(skeleton.limbs.map((limb: Limb) => limb.role).sort()).toEqual(['arm', 'arm', 'head', 'leg', 'leg', 'trunk']);
    const one = input({ travelled: 1.7, speed: 0.8, time: 3.3, talking: true });
    expect([...solvePose(skeleton, one, MOTION).local]).toEqual([...solvePose(skeleton, one).local]);
    expect(gaitOf(skeleton, MOTION).fullSpeed).toBe(0.5);
  });

  it('is posed as it was before chains were read: 128 recorded poses of the 1.7 m figure, number by number', () => {
    // The recorded poses (things-humanoid-poses.json beside this file) were written by this test,
    // run with EXULANICA_POSE_FIXTURE=write, from the solver as it stood when it was compared pose
    // for pose with the solver before it read a plan's chains. Each number is compared within a
    // hundred-millionth: the last bits of a sine or a square root differ between the runtimes this
    // runs on, so nothing here is compared exactly or hashed.
    const poses: number[][] = [];
    for (const speed of [0, 0.2, 0.5, 1.4]) for (const travelled of [0, 0.31, 1.7, 12.9]) for (const time of [0, 3.3]) for (const talking of [false, true]) {
      const moving: MotionInput = { travelled, speed, time, talking, holding: new Set(talking ? ['hand.right'] : []), reach: time > 0 && speed === 0 ? { socket: 'hand.right', target: [0.2, 1.1, 0.5], amount: 0.7 } : null };
      const still: MotionInput = { travelled, speed, time, talking, holding: new Set(), reach: null, reducedMotion: true };
      for (const one of [moving, still]) {
        const pose = solvePose(skeleton, one);
        // For each bone in the skeleton's order: its turn from its parent, then where its joint is.
        poses.push(skeleton.order.flatMap((bone) => [...pose.local.get(bone)!, ...pose.joints.get(bone)!.position]));
      }
    }
    expect(poses).toHaveLength(128);
    const file = new URL('./things-humanoid-poses.json', import.meta.url);
    if (process.env['EXULANICA_POSE_FIXTURE'] === 'write') {
      const rounded = poses.map((pose) => pose.map((value) => Number(value.toFixed(10))));
      writeFileSync(file, `${JSON.stringify({
        profile: 'exulanica.pose-fixture/v1',
        written_by: 'web/packages/atlas-react/test/things-stated-chains.test.ts with EXULANICA_POSE_FIXTURE=write',
        note: 'The 1.7 m blocky figure on the shipped humanoid plan, posed for 128 inputs: for each bone in order, its turn from its parent (x, y, z, w) and its joint (x, y, z, metres), to ten decimals.',
        bones: skeleton.order,
        poses: rounded,
      }).replace('"poses":[', '"poses":[\n').replaceAll('],[', '],\n[')}\n`);
    }
    const recorded = JSON.parse(readFileSync(file, 'utf8')) as { bones: string[]; poses: number[][] };
    expect(recorded.bones).toEqual(skeleton.order);
    expect(recorded.poses).toHaveLength(poses.length);
    let worst = 0;
    let moved = 0;
    poses.forEach((pose, i) => {
      expect(pose).toHaveLength(recorded.poses[i]!.length);
      pose.forEach((value, k) => {
        worst = Math.max(worst, Math.abs(value - recorded.poses[i]![k]!));
        if (i > 0) moved = Math.max(moved, Math.abs(value - poses[0]![k]!));
      });
    });
    expect(worst).toBeLessThan(1e-8);
    // Positive control: the poses differ from one another by far more than that, so a pose that
    // moved would be seen.
    expect(moved).toBeGreaterThan(0.1);
  });

  it('draws its full walk from 0.8 of its own strides a second, which is where the catalog\'s cadence comes from', () => {
    const stride = gaitOf(skeleton).stride;
    expect(stride).toBeCloseTo(0.63, 2);
    expect(0.5 / stride).toBeCloseTo(stated('full_walk_strides_per_second'), 1);
  });
});

describe('a plan document\'s chains', () => {
  const document = () => structuredClone(fixture('dragon').plan) as Fixture['plan'] & Record<string, unknown>;

  it('are read as stated, and a plan with none reads as it did', () => {
    const plan = readBodyPlanDocument(document());
    expect(plan.limbs).toEqual(document().limbs);
    const none = document();
    delete (none as Record<string, unknown>)['limbs'];
    expect(readBodyPlanDocument(none).limbs).toBeUndefined();
    // A plan that states an empty list is read from its shape, as one that states none.
    const empty = { ...document(), limbs: [] };
    expect(dressSkeleton(readBodyPlanDocument(empty), new Map(Object.entries(fixture('dragon').joints_m))).stated).toBe(false);
  });

  it.each([
    ['a role the contract does not state', (plan: Fixture['plan']) => { plan.limbs[0]!.role = 'antenna'; }, 'plan.limbs[0].role'],
    ['a side the contract does not state', (plan: Fixture['plan']) => { plan.limbs[0]!.side = 'middle'; }, 'plan.limbs[0].side'],
    ['an order that is not a whole number', (plan: Fixture['plan']) => { plan.limbs[0]!.order = 0.5; }, 'plan.limbs[0].order'],
    ['a chain with no bone', (plan: Fixture['plan']) => { plan.limbs[0]!.bones = []; }, 'plan.limbs[0].bones'],
    ['a bone the plan does not have', (plan: Fixture['plan']) => { plan.limbs[0]!.bones[0] = 'nowhere'; }, 'plan.limbs[0].bones[0]'],
    ['a bone two chains name', (plan: Fixture['plan']) => { plan.limbs[1]!.bones = [...plan.limbs[0]!.bones]; }, 'plan.limbs[1].bones[0]'],
    ['a bone that is not a child of the one before it', (plan: Fixture['plan']) => { plan.limbs[0]!.bones.reverse(); }, 'plan.limbs[0].bones[1]'],
    ['a chain named twice', (plan: Fixture['plan']) => { plan.limbs[1]!.key = plan.limbs[0]!.key; }, 'plan.limbs[1].key'],
  ])('refuses %s, by its place', (_what, spoil, field) => {
    const plan = document();
    spoil(plan);
    let refused: unknown = null;
    try {
      readBodyPlanDocument(plan);
    } catch (error) {
      refused = error;
    }
    expect(refused).toBeInstanceOf(ThingDocumentRefused);
    expect((refused as ThingDocumentRefused).field).toBe(field);
  });
});

describe('the body motion catalog', () => {
  it('gives every figure a class and a reason, and the page reads each one', () => {
    expect(CATALOG.profile).toBe('exulanica.body-motion/v1');
    expect(CATALOG.entries).toHaveLength(15);
    for (const entry of CATALOG.entries) {
      expect(entry.class).toBe('chosen_default');
      expect(entry.reason.length).toBeGreaterThan(80);
    }
    expect(MOTION.jawOpen).toBe(stated('jaw_open_rad'));
    expect(MOTION.wingFold).toBe(stated('wing_fold_share'));
    // The one figure the file states in millimetres is read in metres.
    expect(MOTION.turnEndSpeed).toBe(stated('turn_end_speed_mm_per_second') / 1000);
  });

  it.each([
    ['another profile', (catalog: typeof CATALOG) => { catalog.profile = 'exulanica.body-motion/v2'; }],
    ['an entry the page does not read', (catalog: typeof CATALOG) => { catalog.entries.push({ ...catalog.entries[0]!, key: 'ear_twitch_rad' }); }],
    ['an entry stated twice', (catalog: typeof CATALOG) => { catalog.entries.push({ ...catalog.entries[0]! }); }],
    ['an entry left out', (catalog: typeof CATALOG) => { catalog.entries.pop(); }],
    ['a figure in another unit', (catalog: typeof CATALOG) => { catalog.entries.find((entry) => entry.key === 'jaw_open_rad')!.unit = 'degree'; }],
    ['a figure outside its range', (catalog: typeof CATALOG) => { catalog.entries.find((entry) => entry.key === 'wing_fold_share')!.value = 1.5; }],
    ['a figure that is not a number', (catalog: typeof CATALOG) => { (catalog.entries[0] as { value: unknown }).value = '0.8'; }],
    ['a figure with no reason', (catalog: typeof CATALOG) => { catalog.entries[0]!.reason = ''; }],
  ])('is refused with %s', (_what, spoil) => {
    const catalog = structuredClone(CATALOG);
    spoil(catalog);
    expect(() => readBodyMotion(catalog)).toThrow(/body motion catalog/u);
  });
});
