import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readBodyMotion } from '../src/playcanvas/things/body-motion.js';
import { readBodyPlanDocument } from '../src/playcanvas/things/documents.js';
import { DUTY, add, gaitOf, rotate, solvePose, type MotionInput } from '../src/playcanvas/things/motion.js';
import { dressSkeleton, type Vec3 } from '../src/playcanvas/things/skeleton.js';

const root = '../../../../assets/things/canopy-strider/';
const read = (path: string) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const motion = readBodyMotion(read('../../../../assets/catalogs/thing-presentation/body-motion.v1.json'));
const input = (over: Partial<MotionInput> = {}): MotionInput => ({ travelled: 0, speed: 0, time: 0, holding: new Set(), reach: null, talking: false, ...over });

function asset(folder: string) {
  const plan = readBodyPlanDocument(read(`${root}${folder}/plan.json`));
  const bytes = readFileSync(new URL(`${root}${folder}/body.glb`, import.meta.url));
  const jsonSize = bytes.readUInt32LE(12);
  const gltf = JSON.parse(bytes.subarray(20, 20 + jsonSize).toString('utf8'));
  const binary = bytes.subarray(28 + jsonSize);
  const rest = new Map<string, Vec3>();
  const geometry = new Map<string, Vec3[]>();
  for (const node of gltf.nodes) {
    if (!node.name?.startsWith('bone:')) continue;
    const bone = node.name.slice(5);
    rest.set(bone, node.translation);
    const points: Vec3[] = [];
    for (const child of node.children ?? []) {
      for (const primitive of gltf.meshes[gltf.nodes[child].mesh].primitives) {
        const accessor = gltf.accessors[primitive.attributes.POSITION];
        const view = gltf.bufferViews[accessor.bufferView];
        for (let i = 0; i < accessor.count; i += 1) {
          const at = view.byteOffset + (accessor.byteOffset ?? 0) + i * 12;
          points.push([binary.readFloatLE(at), binary.readFloatLE(at + 4), binary.readFloatLE(at + 8)]);
        }
      }
    }
    geometry.set(bone, points);
  }
  return { skeleton: dressSkeleton(plan, rest), geometry };
}

// Check visible feet, rather than treating a joint above the sole as contact evidence.
describe.each(['porcelain-v3', 'celadon-v3'])('authored body %s contact', (folder) => {
  const { skeleton, geometry } = asset(folder);
  const legs = skeleton.limbs.filter(limb => limb.role === 'leg');
  it('keeps every visible sole on support through idle, speech and reduced motion', () => {
    for (const over of [{ time: 0 }, { time: 3.3 }, { time: 11.7, talking: true }, { time: 21, reducedMotion: true }]) {
      const pose = solvePose(skeleton, input(over), motion);
      for (const leg of legs) {
        const foot = leg.bones.at(-1)!;
        const joint = pose.joints.get(foot)!;
        const bottom = Math.min(...geometry.get(foot)!.map(v => add(joint.position, rotate(joint.rotation, v))[1]));
        expect(bottom, `${foot} visible sole`).toBeGreaterThanOrEqual(-0.00001);
        expect(bottom, `${foot} visible sole`).toBeLessThan(0.002);
      }
    }
  });

  it('plants and lifts the visible sole at its distance-clocked gait phase', () => {
    const gait = gaitOf(skeleton, motion);
    for (let sample = 0; sample < 16; sample += 1) {
      const travelled = gait.cycle * sample / 16;
      const pose = solvePose(skeleton, input({ travelled, speed: gait.fullSpeed, time: sample / 3 }), motion);
      for (const leg of legs) {
        const foot = leg.bones.at(-1)!;
        const joint = pose.joints.get(foot)!;
        const bottom = Math.min(...geometry.get(foot)!.map(v => add(joint.position, rotate(joint.rotation, v))[1]));
        expect(bottom, `${foot} penetration`).toBeGreaterThanOrEqual(-0.002);
        const phase = (sample / 16 + leg.phase) % 1;
        if (phase < DUTY) expect(bottom, `${foot} planted`).toBeLessThan(0.002);
        if (phase > DUTY + 0.05 && phase < 0.95) expect(bottom, `${foot} raised`).toBeGreaterThan(0.01);
      }
    }
  });
});
