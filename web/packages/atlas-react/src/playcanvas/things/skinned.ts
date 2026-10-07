/**
 * A `skinned` look: a rigged figure that plays its own clips, its rig mapped onto the plan's bones.
 *
 * The container is one self-contained glTF with a skin and the clips its motions use, each in
 * place: no clip moves the figure, which stands only where its pose puts it. The look's rig names a
 * joint for each plan bone it maps (`rig.bones`), a clip for each motion it has (`rig.clips`), the
 * joint each socket holds things at (`rig.sockets`) and the ground speed of its locomotion clips
 * (`rig.ground_speed_mm_per_s`, metres a second at the look's height). Standing, walking and running
 * blend by ground speed; a clip plays faster past its own pace, at most twice, and beyond that its
 * feet slide (named, never hidden by moving the figure). A motion with no clip falls back to idle,
 * as the body plan says. Over a clip, the arm of a socket that reaches is posed procedurally on the
 * mapped arm bones, and the head nods while the thing speaks.
 */

import * as pc from 'playcanvas';
import type { Grip, SkinnedRig } from './documents.js';
import { HALF_TURN, bodyCarry, nodeCarry, placeHeld, quat, quatOf, type PickVolume, type ThingFigure, type ThingPose } from './figures.js';
import { axisAngle, mul, rotate } from './motion.js';
import { dressSkeleton, type BodyPlanEntry, type DressedSkeleton, type Vec3 } from './skeleton.js';

const LOCOMOTION = 'locomotion';
const SPEED = 'speed';
/** The fastest a locomotion clip plays, as a multiple of its own pace. */
export const CLIP_SPEED_LIMIT = 2;
const PICK_HALF_WIDTH = 0.2;

export type SkinnedMiss = 'no_ground_speed' | 'feet_slide';

export class SkinnedFigure implements ThingFigure {
  readonly root: pc.Entity;
  readonly lookKind = 'skinned' as const;
  readonly standingHeight: number;
  readonly pickVolume: PickVolume;
  private readonly figure: pc.Entity;
  private readonly joints = new Map<string, pc.Entity>();
  private readonly restLocal = new Map<string, pc.Quat>();
  private readonly sockets = new Map<string, pc.Entity>();
  private readonly held = new Map<string, { entity: pc.Entity; grip: Grip }>();
  private readonly walkSpeed: number | null;
  private readonly runSpeed: number | null;
  private previous: readonly [number, number, number] | null = null;
  private speed = 0;
  private time = 0;
  private pending: ThingPose | null = null;
  private readonly scale: number;
  /** The plan's bones as this rig dresses them at rest, and the limbs read from them. */
  readonly skeleton: DressedSkeleton;
  /** What this figure drew differently from its state this frame, by name; empty when nothing. */
  readonly misses = new Set<SkinnedMiss>();

  constructor(
    parent: pc.Entity,
    model: pc.Entity,
    tracks: ReadonlyMap<string, pc.AnimTrack>,
    plan: BodyPlanEntry,
    rig: SkinnedRig,
    name: string,
    lookHeightMm: number,
    heightMm: number,
  ) {
    this.root = new pc.Entity(name);
    parent.addChild(this.root);
    this.figure = model;
    this.root.addChild(this.figure);
    this.scale = heightMm / lookHeightMm;
    this.figure.setLocalScale(this.scale, this.scale, this.scale);
    this.figure.setLocalRotation(quat(HALF_TURN));
    this.standingHeight = heightMm / 1000;
    const w = PICK_HALF_WIDTH * this.standingHeight;
    this.pickVolume = { kind: 'box', min: [-w, 0, -w], max: [w, this.standingHeight, w] };
    const planBones = new Set(plan.bones.map((bone) => bone.name));
    for (const [bone, joint] of Object.entries(rig.bones)) {
      if (!planBones.has(bone)) throw new TypeError(`The look's rig maps "${bone}", which ${plan.key}/v${plan.version} has no bone for.`);
      const entity = this.figure.findByName(joint);
      if (!(entity instanceof pc.Entity)) throw new TypeError(`The look's rig names a joint "${joint}" its container lacks.`);
      this.joints.set(bone, entity);
      this.restLocal.set(bone, entity.getLocalRotation().clone());
    }
    for (const [socket, joint] of Object.entries(rig.sockets)) {
      const entity = this.figure.findByName(joint);
      if (entity instanceof pc.Entity) this.sockets.set(socket, entity);
    }
    // The mapped joints at rest (the bind pose, before any clip), in the look's own frame, read by
    // the same rule as a rigid look's joints: limbs come from the skeleton's shape and its sockets.
    const toLook = this.figure.getWorldTransform().clone().invert();
    const rest = new Map<string, Vec3>();
    for (const [bone, entity] of this.joints) {
      const at = toLook.transformPoint(entity.getPosition(), new pc.Vec3());
      rest.set(bone, [at.x, at.y, at.z]);
    }
    this.skeleton = dressSkeleton(plan, rest);
    const walk = rig.groundSpeedMmPerS['walk'];
    const run = rig.groundSpeedMmPerS['run'];
    this.walkSpeed = walk === undefined ? null : walk / 1000;
    this.runSpeed = run === undefined ? null : run / 1000;
    const clip = (motion: string): pc.AnimTrack => {
      const named = rig.clips[motion] ?? rig.clips['idle'];
      const track = named === undefined ? undefined : tracks.get(named);
      if (track === undefined) throw new TypeError(`The look's container has no clip "${String(named)}" for ${motion}.`);
      return track;
    };
    this.figure.addComponent('anim', { activate: true });
    const anim = this.figure.anim!;
    const points: { name: string; point: number }[] = [{ name: 'idle', point: 0 }];
    if (this.walkSpeed !== null && rig.clips['walk'] !== undefined) points.push({ name: 'walk', point: this.walkSpeed });
    if (this.runSpeed !== null && rig.clips['run'] !== undefined && (this.walkSpeed === null || this.runSpeed > this.walkSpeed)) {
      points.push({ name: 'run', point: this.runSpeed });
    }
    anim.loadStateGraph({
      layers: [{
        name: 'Base',
        states: [
          { name: 'START' },
          { name: LOCOMOTION, loop: true, speed: 1, blendTree: { type: pc.ANIM_BLEND_1D, parameter: SPEED, syncAnimations: true, children: points } },
        ],
        transitions: [{ from: 'START', to: LOCOMOTION }],
      }],
      parameters: { [SPEED]: { name: SPEED, type: pc.ANIM_PARAMETER_FLOAT, value: 0 } },
    });
    for (const { name: motion } of points) anim.assignAnimation(`${LOCOMOTION}.${motion}`, clip(motion));
  }

  /** Before the engine's animation step: where it stands, which way it faces, how fast it goes. */
  pose(pose: ThingPose): void {
    const [x, y, z] = pose.position;
    const dt = Math.max(0, pose.deltaSeconds);
    if (this.previous !== null && !pose.discontinuity && dt > 0) {
      const moved = Math.hypot(x - this.previous[0], z - this.previous[2]);
      this.speed += (moved / dt - this.speed) * Math.min(1, dt * 6);
    } else if (pose.discontinuity) {
      this.speed = 0;
    }
    this.previous = pose.position;
    this.time += pose.reducedMotion ? 0 : dt;
    this.root.setLocalPosition(x, y, z);
    this.root.setLocalEulerAngles(0, (pose.facing * 180) / Math.PI, 0);
    const anim = this.figure.anim!;
    const ground = pose.reducedMotion ? 0 : this.speed / this.scale;
    this.misses.clear();
    const fastest = this.runSpeed ?? this.walkSpeed;
    if (fastest === null) {
      if (ground > 0.15) this.misses.add('no_ground_speed');
      anim.setFloat(SPEED, 0);
      anim.speed = 1;
    } else {
      anim.setFloat(SPEED, Math.min(ground, fastest));
      const over = ground > fastest ? ground / fastest : 1;
      anim.speed = pose.reducedMotion ? 0 : Math.min(CLIP_SPEED_LIMIT, over);
      if (over > CLIP_SPEED_LIMIT) this.misses.add('feet_slide');
    }
    this.pending = pose;
  }

  /** After the engine's animation step: the procedural arm over the clip, the nod, held things. */
  afterAnimation(): void {
    const pose = this.pending;
    if (pose === null) return;
    const body = mul(quatOf(this.root.getRotation()), HALF_TURN);
    const reach = pose.reach ?? null;
    for (const socket of pose.holding ?? []) {
      const arm = this.armOf(socket);
      const reaching = reach !== null && reach.socket === socket ? Math.max(0, Math.min(1, reach.amount)) : 0;
      // A rig with a socket joint carries the thing on the clip's own arm; the arm is posed here
      // only to reach, or to carry where the rig names no socket joint.
      if (arm === null || (reaching === 0 && this.sockets.has(socket))) continue;
      const s = arm.side;
      const upper: Vec3 = [s * (0.16 - 0.1 * reaching), -1 + 0.95 * reaching, 0.3 + 0.9 * reaching];
      const lower: Vec3 = [s * 0.04 * (1 - reaching), -0.3 + 0.32 * reaching, 1];
      this.aim(arm.bones[0]!, arm.bones[1]!, rotate(body, upper));
      this.aim(arm.bones[1]!, arm.bones[2]!, rotate(body, lower));
    }
    if (pose.talking && !pose.reducedMotion) {
      const head = this.joints.get(this.headBone());
      if (head !== undefined) head.setLocalRotation(head.getLocalRotation().clone().mul(quat(axisAngle([1, 0, 0], 0.08 * Math.sin(2 * Math.PI * 2.1 * this.time)))));
    }
    for (const [socket, { entity, grip }] of this.held) {
      const node = this.sockets.get(socket);
      const bone = this.planSocketBone(socket);
      const at = node ?? (bone === null ? undefined : this.joints.get(bone));
      if (at === undefined) continue;
      const offering = reach !== null && reach.socket === socket ? reach.amount : 0;
      const carry = node !== undefined ? nodeCarry(grip.axis, quatOf(node.getRotation()), body) : mul(body, bodyCarry(grip.axis, offering));
      placeHeld(entity, grip, at.getPosition(), carry);
    }
  }

  hold(socket: string, entity: pc.Entity, grip: Grip): void {
    this.release(socket)?.destroy();
    this.root.addChild(entity);
    this.held.set(socket, { entity, grip });
  }

  release(socket: string): pc.Entity | null {
    const held = this.held.get(socket);
    if (held === undefined) return null;
    this.held.delete(socket);
    this.root.removeChild(held.entity);
    return held.entity;
  }

  markAnchor(out: pc.Vec3): pc.Vec3 {
    return out.copy(this.root.getPosition()).add(new pc.Vec3(0, this.standingHeight + 0.25, 0));
  }

  setVisible(visible: boolean): void {
    this.root.enabled = visible;
  }

  destroy(): void {
    for (const { entity } of this.held.values()) entity.destroy();
    this.root.destroy();
  }

  private planSocketBone(socket: string): string | null {
    return this.skeleton.socketBones.get(socket) ?? null;
  }

  /** The arm a socket is on: its limb's first three dressed bones, and its side. */
  private armOf(socket: string): { bones: readonly string[]; side: -1 | 1 } | null {
    const limb = this.skeleton.limbs.find((one) => one.role === 'arm' && one.sockets.includes(socket));
    if (limb === undefined || limb.bones.length < 3 || limb.side === 0) return null;
    return { bones: limb.bones.slice(0, 3), side: limb.side };
  }

  private headBone(): string {
    return this.skeleton.limbs.find((limb) => limb.role === 'head')?.bones.at(-1) ?? '';
  }

  /** Point `bone`'s segment toward `next` along world direction `to`, keeping its rest twist. */
  private aim(bone: string, next: string, to: Vec3): void {
    const joint = this.joints.get(bone)!;
    const child = this.joints.get(next)!;
    const parentRotation = (joint.parent as pc.Entity).getRotation();
    const inherited = parentRotation.clone().mul(this.restLocal.get(bone)!);
    // The child's offset from this joint, in this joint's own frame.
    const offset = child.getPosition().clone().sub(joint.getPosition());
    const local = joint.getRotation().clone().invert().transformVector(offset, new pc.Vec3()).normalize();
    const now = inherited.transformVector(local, new pc.Vec3());
    const want = new pc.Vec3(to[0], to[1], to[2]).normalize();
    const d = now.dot(want);
    if (d > 1 - 1e-9) return;
    const c = new pc.Vec3().cross(now, want);
    const turn = new pc.Quat(c.x, c.y, c.z, 1 + d).normalize();
    joint.setRotation(turn.mul(inherited));
  }
}
