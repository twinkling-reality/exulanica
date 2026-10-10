/**
 * A `skinned` look: a rigged figure that plays its own clips, its rig mapped onto the plan's bones.
 *
 * The container is one self-contained glTF with a skin and the clips its motions use, each in
 * place: no clip moves the figure, which stands only where its pose puts it. The look's rig names a
 * joint for each plan bone it maps (`rig.bones`), a clip for each motion it has (`rig.clips`), the
 * joint each socket holds things at (`rig.sockets`) and the ground speed of its locomotion clips
 * (`rig.ground_speed_mm_per_s`, metres a second at the look's height). Standing, walking and running
 * blend by ground speed, and the clips' cadence follows it as a catalog person's does (`gaitFor`), so
 * a planted foot moves as fast as the ground: slower than its walk clip's pace the walk plays slower,
 * down to half its cadence, and only below that fades into standing; slower than `STANDING_SPEED` the
 * figure stands. A clip plays faster past its own pace, at most twice, and beyond that its feet
 * slide (named, never hidden by moving the figure). A motion with no clip falls back to idle, as
 * the body plan says. Over a clip, the arm of a socket that reaches is posed procedurally on the
 * mapped arm bones, and the head nods while the thing speaks.
 *
 * A rig with no clips at all (a creature sculpted for its own body plan) is posed as a rigid look is:
 * each frame the same solved gait (`./motion.ts`) turns its joints, and the skin follows them. Such a
 * rig must rest translation-only and hang each joint from its plan parent's joint, so a joint's turn
 * is the solved turn; one that does not is refused by name.
 */

import * as pc from 'playcanvas';
import { STANDING_SPEED, gaitFor } from '../character/person.js';
import type { Grip, SkinnedRig } from './documents.js';
import { HALF_TURN, bodyCarry, nodeCarry, placeHeld, quat, quatOf, type PickVolume, type ThingFigure, type ThingPose } from './figures.js';
import { axisAngle, gaitTravel, mul, rotate, solvePose } from './motion.js';
import { dressSkeleton, type BodyPlanEntry, type DressedSkeleton, type Vec3 } from './skeleton.js';

const LOCOMOTION = 'locomotion';
/** Standing and moving while holding something: the look's hold clip where it has one. */
const CARRYING = 'carrying';
const SPEED = 'speed';
const HOLDING = 'holding';
/** Seconds a figure takes to take up, or put down, its holding stance. */
const HOLD_BLEND_SECONDS = 0.25;
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
  /**
   * The ground speeds the walk and run clips are blended at and paced by, metres a second at the
   * look's height: the walk is the slowest moving clip the rig has and the run its fastest, one clip
   * being both. Null for a rig with no moving clip, or with no clips at all.
   */
  private readonly gait: { readonly walk: number; readonly run: number } | null;
  /**
   * How fast the figure walks at its walk clip's own cadence, metres a second at the size it is
   * drawn: the look's declared walk speed scaled as the figure is. Null where the look declares none.
   */
  readonly walkSpeed: number | null;
  /** Whether the look has a clip for holding, which it then stands in while it holds something. */
  private readonly holdClip: boolean;
  private previous: readonly [number, number, number] | null = null;
  private speed = 0;
  /** A rig with no clips, posed by the solved gait; its root joint's rest, local and in the look's frame. */
  private readonly procedural: { readonly rootLocal: pc.Vec3; readonly rootLook: Vec3 } | null;
  /** The solved gait's clock: metres walked, in the look's own units (`gaitTravel`). */
  private travelled = 0;
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
    const walkSpeed = walk === undefined ? null : walk / 1000;
    const runSpeed = run === undefined ? null : run / 1000;
    this.holdClip = rig.clips['hold'] !== undefined && tracks.has(rig.clips['hold']!);
    if (Object.keys(rig.clips).length === 0) {
      for (const bone of this.skeleton.order) {
        const up = this.skeleton.parentOf.get(bone) ?? null;
        if (up !== null && this.joints.get(bone)!.parent !== this.joints.get(up)) {
          throw new TypeError(`A rig with no clips hangs each joint from its plan parent's, and "${rig.bones[bone]}" does not hang from "${rig.bones[up]}".`);
        }
        if (Math.abs(this.restLocal.get(bone)!.w) < 1 - 1e-6) {
          throw new TypeError(`A rig with no clips rests translation-only, and "${rig.bones[bone]}" is turned at rest.`);
        }
      }
      this.procedural = { rootLocal: this.joints.get(this.skeleton.root)!.getLocalPosition().clone(), rootLook: rest.get(this.skeleton.root)! };
      this.gait = null;
      this.walkSpeed = null;
      this.solve({ position: [0, 0, 0], facing: 0, deltaSeconds: 0 });
      return;
    }
    this.procedural = null;
    const clip = (motion: string): pc.AnimTrack => {
      const named = rig.clips[motion] ?? rig.clips['idle'];
      const track = named === undefined ? undefined : tracks.get(named);
      if (track === undefined) throw new TypeError(`The look's container has no clip "${String(named)}" for ${motion}.`);
      return track;
    };
    this.figure.addComponent('anim', { activate: true });
    const anim = this.figure.anim!;
    const points: { name: string; point: number }[] = [{ name: 'idle', point: 0 }];
    if (walkSpeed !== null && rig.clips['walk'] !== undefined) points.push({ name: 'walk', point: walkSpeed });
    if (runSpeed !== null && rig.clips['run'] !== undefined && (walkSpeed === null || runSpeed > walkSpeed)) {
      points.push({ name: 'run', point: runSpeed });
    }
    const walkPoint = points.find((point) => point.name === 'walk')?.point;
    const runPoint = points.find((point) => point.name === 'run')?.point;
    const slowest = walkPoint ?? runPoint;
    this.gait = slowest === undefined ? null : { walk: slowest, run: runPoint ?? slowest };
    this.walkSpeed = walkPoint === undefined ? null : walkPoint * this.scale;
    const carrying = points.map((point) => (point.name === 'idle' ? { name: 'hold', point: 0 } : point));
    const held = (value: boolean) => [{ parameterName: HOLDING, predicate: pc.ANIM_EQUAL_TO, value }];
    anim.loadStateGraph({
      layers: [{
        name: 'Base',
        states: [
          { name: 'START' },
          { name: LOCOMOTION, loop: true, speed: 1, blendTree: { type: pc.ANIM_BLEND_1D, parameter: SPEED, syncAnimations: true, children: points } },
          ...(this.holdClip
            ? [{ name: CARRYING, loop: true, speed: 1, blendTree: { type: pc.ANIM_BLEND_1D, parameter: SPEED, syncAnimations: true, children: carrying } }]
            : []),
        ],
        transitions: [
          { from: 'START', to: LOCOMOTION },
          ...(this.holdClip
            ? [
              { from: LOCOMOTION, to: CARRYING, time: HOLD_BLEND_SECONDS, conditions: held(true) },
              { from: CARRYING, to: LOCOMOTION, time: HOLD_BLEND_SECONDS, conditions: held(false) },
            ]
            : []),
        ],
      }],
      parameters: {
        [SPEED]: { name: SPEED, type: pc.ANIM_PARAMETER_FLOAT, value: 0 },
        [HOLDING]: { name: HOLDING, type: pc.ANIM_PARAMETER_BOOLEAN, value: false },
      },
    });
    for (const { name: motion } of points) anim.assignAnimation(`${LOCOMOTION}.${motion}`, clip(motion));
    if (this.holdClip) for (const { name: motion } of carrying) anim.assignAnimation(`${CARRYING}.${motion}`, clip(motion));
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
    if (this.procedural !== null && this.previous !== null && !pose.discontinuity && dt > 0) {
      this.travelled += gaitTravel(Math.hypot(x - this.previous[0], z - this.previous[2]) / this.scale, this.speed / this.scale);
    }
    this.previous = pose.position;
    this.time += pose.reducedMotion ? 0 : dt;
    this.root.setLocalPosition(x, y, z);
    this.root.setLocalEulerAngles(0, (pose.facing * 180) / Math.PI, 0);
    if (this.procedural !== null) {
      this.misses.clear();
      this.solve(pose);
      this.pending = pose;
      return;
    }
    const anim = this.figure.anim!;
    // What is left of a speed easing to rest is not a walk: slower than the threshold it stands.
    const ground = pose.reducedMotion || this.speed < STANDING_SPEED ? 0 : this.speed / this.scale;
    this.misses.clear();
    if (this.holdClip) anim.setBoolean(HOLDING, (pose.holding?.size ?? 0) > 0);
    if (this.gait === null) {
      if (ground > 0.15) this.misses.add('no_ground_speed');
      anim.setFloat(SPEED, 0);
      anim.speed = 1;
    } else {
      // The clips' cadence follows the ground, so a planted foot moves as fast as the ground does.
      const gait = gaitFor(ground, this.gait.walk, this.gait.run);
      anim.setFloat(SPEED, gait.blend);
      anim.speed = pose.reducedMotion ? 0 : Math.min(CLIP_SPEED_LIMIT, gait.cadence);
      if (gait.cadence > CLIP_SPEED_LIMIT) this.misses.add('feet_slide');
    }
    this.pending = pose;
  }

  /** A clip-less rig's joints turned by the solved gait, its root joint carried by its bob and crouch. */
  private solve(pose: ThingPose): void {
    const procedural = this.procedural!;
    const solved = solvePose(this.skeleton, {
      travelled: this.travelled,
      speed: pose.reducedMotion ? 0 : this.speed / this.scale,
      time: this.time,
      holding: pose.holding ?? new Set(),
      reach: pose.reach ?? null,
      talking: pose.talking === true,
      ...(pose.reducedMotion ? { reducedMotion: true } : {}),
    });
    for (const bone of this.skeleton.order) this.joints.get(bone)!.setLocalRotation(quat(solved.local.get(bone)!));
    const at = solved.rootPosition, rest = procedural.rootLook, local = procedural.rootLocal;
    this.joints.get(this.skeleton.root)!.setLocalPosition(local.x + at[0] - rest[0], local.y + at[1] - rest[1], local.z + at[2] - rest[2]);
  }

  /** After the engine's animation step: the procedural arm over the clip, the nod, held things. */
  afterAnimation(): void {
    const pose = this.pending;
    if (pose === null) return;
    const body = mul(quatOf(this.root.getRotation()), HALF_TURN);
    const reach = pose.reach ?? null;
    // A clip-less rig's arms, head and hands were all posed by the solved gait.
    for (const socket of this.procedural === null ? pose.holding ?? [] : []) {
      const arm = this.armOf(socket);
      const reaching = reach !== null && reach.socket === socket ? Math.max(0, Math.min(1, reach.amount)) : 0;
      // A rig with a socket joint carries the thing on the clip's own arm (its hold clip where it
      // has one); the arm is posed here only to reach, or to carry where the rig names no socket joint.
      if (arm === null || (reaching === 0 && this.sockets.has(socket))) continue;
      const s = arm.side;
      const upper: Vec3 = [s * (0.16 - 0.1 * reaching), -1 + 0.95 * reaching, 0.3 + 0.9 * reaching];
      const lower: Vec3 = [s * 0.04 * (1 - reaching), -0.3 + 0.32 * reaching, 1];
      this.aim(arm.bones[0]!, arm.bones[1]!, rotate(body, upper));
      this.aim(arm.bones[1]!, arm.bones[2]!, rotate(body, lower));
    }
    if (pose.talking && !pose.reducedMotion && this.procedural === null) {
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
    this.release(socket);
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
    // What it holds is lent (`ThingFigure.hold`): let go, never destroyed.
    for (const socket of [...this.held.keys()]) this.release(socket);
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
