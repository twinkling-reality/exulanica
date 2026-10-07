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

  it('is refused by name when a joint does not hang from its plan parent\'s, or is turned at rest', () => {
    const parent = new pc.Entity('region');
    const flat = sculpted(() => null);
    expect(() => new SkinnedFigure(parent, flat, new Map(), HUMANOID, RIG, 'flat', 1750, 1750)).toThrow(/does not hang from/u);
    expect(() => new SkinnedFigure(parent, sculpted(presentParent, 'leftLowerArm'), new Map(), HUMANOID, RIG, 'turned', 1750, 1750))
      .toThrow(/"bone:leftLowerArm" is turned at rest/u);
  });
});
