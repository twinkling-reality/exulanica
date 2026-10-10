// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { readBodyPlans, type SkinnedRig } from '../src/playcanvas/things/documents.js';
import { RigidOnBonesFigure } from '../src/playcanvas/things/rigid-on-bones.js';
import { SkinnedFigure } from '../src/playcanvas/things/skinned.js';
import { thingsJson } from './things-fixtures.js';

/*
 * A rig with no clips (a creature sculpted for its own body plan) is posed by the same solved gait
 * as a rigid look: its joints are turned each frame and the skin follows them. Expected points come
 * from a rigid look of the same skeleton posed the same way, which its own tests hold.
 */

// An application for the entities to belong to, as the engine expects of every entity.
{
  const canvas = document.createElement('canvas');
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem, pc.AnimComponentSystem];
  app.init(options);
}

const PLANS = readBodyPlans(thingsJson('body-plans.v1.json'));
const HUMANOID = PLANS.get('humanoid/v1')!;

/** A blocky figure's joints at rest (glTF metres, translation only). */
const AT: Record<string, [number, number, number]> = {
  hips: [0, 0.9, 0], spine: [0, 1, 0], chest: [0, 1.15, 0], neck: [0, 1.4, 0], head: [0, 1.45, 0],
  leftUpperLeg: [0.09, 0.86, 0], leftLowerLeg: [0.09, 0.46, 0], leftFoot: [0.09, 0.08, 0],
  rightUpperLeg: [-0.09, 0.86, 0], rightLowerLeg: [-0.09, 0.46, 0], rightFoot: [-0.09, 0.08, 0],
  leftUpperArm: [0.2, 1.35, 0], leftLowerArm: [0.46, 1.35, 0], leftHand: [0.7, 1.35, 0],
  rightUpperArm: [-0.2, 1.35, 0], rightLowerArm: [-0.46, 1.35, 0], rightHand: [-0.7, 1.35, 0],
};
const PARENT = new Map(HUMANOID.bones.map((bone) => [bone.name, bone.parent]));

/** The plan's parent among the joints present: the nearest ancestor that is one of them. */
function presentParent(bone: string): string | null {
  let up = PARENT.get(bone) ?? null;
  while (up !== null && !(up in AT)) up = PARENT.get(up) ?? null;
  return up;
}

/** A clip-less rig's joints, each hung from its plan parent's at its rest offset; `turned` turns one at rest. */
function sculpted(hang: (bone: string) => string | null = presentParent, turned: string | null = null): pc.Entity {
  const model = new pc.Entity('sculpted');
  const nodes = new Map(Object.keys(AT).map((bone) => [bone, new pc.Entity(`bone:${bone}`)]));
  for (const [bone, node] of nodes) {
    const up = hang(bone);
    const at = AT[bone]!, base = up === null ? [0, 0, 0] : AT[up]!;
    (up === null ? model : nodes.get(up)!).addChild(node);
    node.setLocalPosition(at[0] - base[0]!, at[1] - base[1]!, at[2] - base[2]!);
    if (bone === turned) node.setLocalEulerAngles(0, 0, 30);
  }
  return model;
}

function blocky(): pc.Entity {
  const model = new pc.Entity('blocky');
  for (const [bone, at] of Object.entries(AT)) {
    const node = new pc.Entity(`bone:${bone}`);
    node.setLocalPosition(...at);
    model.addChild(node);
  }
  return model;
}

const RIG: SkinnedRig = {
  bones: Object.fromEntries(Object.keys(AT).map((bone) => [bone, `bone:${bone}`])),
  clips: {}, sockets: {}, groundSpeedMmPerS: {},
} as unknown as SkinnedRig;

const world = (figure: { root: pc.Entity }, bone: string): pc.Vec3 => (figure.root.findByName(`bone:${bone}`) as pc.Entity).getPosition().clone();

describe('a rig with no clips', () => {
  it('walks by the same solved gait as a rigid look of its skeleton', () => {
    const parent = new pc.Entity('region');
    const skinned = new SkinnedFigure(parent, sculpted(), new Map(), HUMANOID, RIG, 'sculpted', 1750, 1750);
    const rigid = new RigidOnBonesFigure(parent, blocky(), HUMANOID, 'rigid', 1750, 1750);
    // Both walk the same 1.2 m at 1.2 m/s, a frame at a time.
    for (let frame = 0; frame <= 60; frame += 1) {
      const pose = { position: [frame * 0.02, 0, 0] as [number, number, number], facing: Math.PI / 2, deltaSeconds: 1 / 60 };
      skinned.pose(pose);
      skinned.afterAnimation();
      rigid.pose(pose);
    }
    for (const bone of ['leftFoot', 'rightFoot', 'leftHand', 'head', 'hips']) {
      expect(world(skinned, bone).distance(world(rigid, bone)), bone).toBeLessThan(1e-5);
    }
    // And it does walk: the feet are apart along the way it goes.
    expect(Math.abs(world(skinned, 'leftFoot').x - world(skinned, 'rightFoot').x)).toBeGreaterThan(0.05);
  });

  it('keeps a planted foot where it stands at a slow walk, as a rigid look does: shorter steps, no slower', () => {
    const FRAME = 1 / 60;
    const parent = new pc.Entity('region');
    const figures = {
      sculpted: new SkinnedFigure(parent, sculpted(), new Map(), HUMANOID, RIG, 'slow-sculpted', 1750, 1750),
      rigid: new RigidOnBonesFigure(parent, blocky(), HUMANOID, 'slow-rigid', 1750, 1750),
    };
    /** Walk straight ahead (-Z at facing 0) at `speed`; the left foot's world place on each frame of the last 8 s. */
    const walk = (figure: SkinnedFigure | RigidOnBonesFigure, speed: number, from: number): { trail: { y: number; z: number }[]; to: number } => {
      const trail: { y: number; z: number }[] = [];
      let at = from;
      for (let frame = 1; frame <= 12 * 60; frame += 1) {
        at = from + speed * frame * FRAME;
        figure.pose({ position: [0, 0, -at], facing: 0, deltaSeconds: FRAME });
        const foot = world(figure, 'leftFoot');
        if (frame > 4 * 60) trail.push({ y: foot.y, z: foot.z });
      }
      return { trail, to: at };
    };
    /** The most a foot on the ground moved over the ground between two frames, and how often it was set down. */
    const read = (trail: readonly { y: number; z: number }[]) => {
      const down = trail.map((foot) => foot.y < AT['leftFoot']![1] + 1e-6);
      let slid = 0, plants = 0;
      for (let i = 1; i < trail.length; i += 1) {
        if (down[i] && down[i - 1]) slid = Math.max(slid, Math.abs(trail[i]!.z - trail[i - 1]!.z));
        if (down[i] && !down[i - 1]) plants += 1;
      }
      return { slid, plants };
    };
    for (const [name, figure] of Object.entries(figures)) {
      // 0.5 m/s is the pace the solved walk is fully drawn at; 0.25 m/s is half of it. The ground
      // passes 4.2 mm a frame at the slow walk, and a foot on the ground must not go with it.
      const full = walk(figure, 0.5, 0);
      const slow = walk(figure, 0.25, full.to);
      expect(read(full.trail).slid, `${name} at 0.5 m/s`).toBeLessThan(1e-4);
      expect(read(slow.trail).slid, `${name} at 0.25 m/s`).toBeLessThan(1e-4);
      // The slow walk steps as often as the full one, over half the ground: its steps are half as long.
      expect(read(full.trail).plants, name).toBeGreaterThanOrEqual(3);
      expect(Math.abs(read(slow.trail).plants - read(full.trail).plants), name).toBeLessThanOrEqual(1);
    }
  });

  it('stands on its rest feet when it goes nowhere, however it is turned', () => {
    const FRAME = 1 / 60;
    const parent = new pc.Entity('region');
    const figures = {
      sculpted: new SkinnedFigure(parent, sculpted(), new Map(), HUMANOID, RIG, 'still-sculpted', 1750, 1750),
      rigid: new RigidOnBonesFigure(parent, blocky(), HUMANOID, 'still-rigid', 1750, 1750),
    };
    for (const [name, figure] of Object.entries(figures)) {
      /** A foot in the figure's own frame: where it is whatever way the figure faces. */
      const own = (bone: string) => figure.root.getWorldTransform().clone().invert().transformPoint(world(figure, bone), new pc.Vec3());
      const rest = { left: own('leftFoot'), right: own('rightFoot') };
      // A walk of two seconds, then it stops where it is and the speed it reads eases to nothing.
      for (let frame = 1; frame <= 120; frame += 1) figure.pose({ position: [0, 0, -frame * 0.02], facing: 0, deltaSeconds: FRAME });
      for (let frame = 0; frame < 180; frame += 1) figure.pose({ position: [0, 0, -2.4], facing: 0, deltaSeconds: FRAME });
      // Turned on the spot for four seconds, a quarter turn a frame at first and then slowly.
      for (let frame = 0; frame < 240; frame += 1) {
        figure.pose({ position: [0, 0, -2.4], facing: frame < 4 ? (frame * Math.PI) / 2 : frame * 0.02, deltaSeconds: FRAME });
        expect(own('leftFoot').distance(rest.left), `${name} frame ${frame}`).toBeLessThan(1e-4);
        expect(own('rightFoot').distance(rest.right), `${name} frame ${frame}`).toBeLessThan(1e-4);
      }
    }
  });

  it('is refused by name when a joint does not hang from its plan parent\'s, or is turned at rest', () => {
    const parent = new pc.Entity('region');
    const flat = sculpted(() => null);
    expect(() => new SkinnedFigure(parent, flat, new Map(), HUMANOID, RIG, 'flat', 1750, 1750)).toThrow(/does not hang from/u);
    expect(() => new SkinnedFigure(parent, sculpted(presentParent, 'leftLowerArm'), new Map(), HUMANOID, RIG, 'turned', 1750, 1750))
      .toThrow(/"bone:leftLowerArm" is turned at rest/u);
  });
});
