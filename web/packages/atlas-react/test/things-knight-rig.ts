/**
 * TEST FIXTURE: the shipped armoured knight's look as the drawing reads it, with a rig to draw it on.
 *
 * The look document and the lengths of its clips are the shipped ones: the document is read as the
 * drawing reads it and the lengths come from the look's own container, whose bytes are held to the
 * digest the look names. The rig is a stand-in with the look's joint names at a person's rest
 * places and clips of those lengths that move nothing, since a test of when and how fast a clip
 * plays needs no mesh.
 */
import * as pc from 'playcanvas';
import { readBodyPlans, readLookDrawing } from '../src/playcanvas/things/documents.js';
import { readThingsFile, sha256, thingsJson } from './things-fixtures.js';

export const KNIGHT_LOOK = readLookDrawing(thingsJson('looks/kaykit-knight.v1.json'));
export const KNIGHT_RIG = KNIGHT_LOOK.rig!;
export const KNIGHT_PLAN = readBodyPlans(thingsJson('body-plans.v1.json')).get(KNIGHT_LOOK.bodyPlan)!;
/** Metres a second at the look's own height, as the look declares them. */
export const KNIGHT_WALK = KNIGHT_RIG.groundSpeedMmPerS['walk']! / 1000;
export const KNIGHT_RUN = KNIGHT_RIG.groundSpeedMmPerS['run']! / 1000;

/** How long each clip of the look's container lasts, seconds, by the clip's name: its last keyframe. */
export const KNIGHT_CLIP_SECONDS: ReadonlyMap<string, number> = (() => {
  const bytes = readThingsFile('../../things/kaykit-adventurers-2/kaykit-knight.glb');
  if (sha256(bytes) !== KNIGHT_LOOK.container!.sha256) throw new Error('the file read is not the look\'s container');
  const json = JSON.parse(bytes.subarray(20, 20 + bytes.readUInt32LE(12)).toString('utf8')) as {
    accessors: { max?: number[] }[];
    animations: { name: string; samplers: { input: number }[] }[];
  };
  return new Map(json.animations.map((clip) => [clip.name, Math.max(...clip.samplers.map((sampler) => json.accessors[sampler.input]!.max![0]!))]));
})();
/** The ground one cycle of the walk clip covers at its own cadence, metres at the look's height. */
export const KNIGHT_STRIDE = KNIGHT_WALK * KNIGHT_CLIP_SECONDS.get(KNIGHT_RIG.clips['walk']!)!;

/** A person's joints at rest by the plan's bone (glTF metres: +Y up, +Z its front, +X its left). */
const AT: Record<string, [number, number, number]> = {
  hips: [0, 0.9, 0], spine: [0, 1, 0], chest: [0, 1.15, 0], head: [0, 1.45, 0],
  leftUpperLeg: [0.09, 0.86, 0], leftLowerLeg: [0.09, 0.46, 0], leftFoot: [0.09, 0.08, 0], leftToes: [0.09, 0.02, 0.12],
  rightUpperLeg: [-0.09, 0.86, 0], rightLowerLeg: [-0.09, 0.46, 0], rightFoot: [-0.09, 0.08, 0], rightToes: [-0.09, 0.02, 0.12],
  leftUpperArm: [0.2, 1.35, 0], leftLowerArm: [0.46, 1.35, 0], leftHand: [0.7, 1.35, 0],
  rightUpperArm: [-0.2, 1.35, 0], rightLowerArm: [-0.46, 1.35, 0], rightHand: [-0.7, 1.35, 0],
};

/** One figure's instance of the stand-in container: the look's joints and its clips by name. */
export function knightContainer(): { model: pc.Entity; tracks: Map<string, pc.AnimTrack> } {
  const model = new pc.Entity('model:kaykit-knight');
  for (const [bone, joint] of Object.entries(KNIGHT_RIG.bones)) {
    const node = new pc.Entity(joint);
    node.setLocalPosition(...AT[bone]!);
    model.addChild(node);
  }
  const tracks = new Map(Object.values(KNIGHT_RIG.clips).map((name) => [name, new pc.AnimTrack(name, KNIGHT_CLIP_SECONDS.get(name)!, [], [], [])]));
  return { model, tracks };
}
