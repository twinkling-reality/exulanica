/**
 * A `rigid_on_bones` look: rigid parts on the named bones of any body plan, posed procedurally.
 *
 * The container is one static glTF whose `bone:<name>` nodes stand at the joints of the look's body
 * plan at rest, each a direct child of the scene root with no rotation or scale, its parts its
 * children (the look kinds catalog). Here every joint is hung from its nearest dressed ancestor in
 * the plan's parent table at its rest offset from it (`./skeleton.ts`), so a look may leave optional
 * bones out, and posed every frame by `./motion.ts` from what the thing is doing. A socket's place
 * is the container's `socket:<key>` node under the socket's bone node where it has one (its grip at
 * the node's origin, its axis along the node's slot +z), else the bone node's origin.
 */

import * as pc from 'playcanvas';
import type { BodyExtent, Grip } from './documents.js';
import { HALF_TURN, bodyCarry, nodeCarry, placeHeld, quat, quatOf, type PickVolume, type ThingFigure, type ThingPose } from './figures.js';
import { bodyGround, type BodyMotion, type Footprint } from './body-motion.js';
import { bodyTravel, mul, solvePose, type Pose } from './motion.js';
import { dressSkeleton, type BodyPlanEntry, type DressedSkeleton, type Vec3 } from './skeleton.js';

/** How wide a standing figure is to a pick, as a share of its height on each side. */
const PICK_HALF_WIDTH = 0.2;

export class RigidOnBonesFigure implements ThingFigure {
  readonly root: pc.Entity;
  readonly lookKind = 'rigid_on_bones' as const;
  readonly skeleton: DressedSkeleton;
  readonly standingHeight: number;
  readonly pickVolume: PickVolume;
  readonly footprint: Footprint | null;
  readonly turnRate: number | null;
  private readonly figure: pc.Entity;
  private readonly joints = new Map<string, pc.Entity>();
  private readonly sockets = new Map<string, pc.Entity>();
  private readonly scale: number;
  private readonly held = new Map<string, { entity: pc.Entity; grip: Grip }>();
  private travelled = 0;
  private time = 0;
  private speed = 0;
  private previous: readonly [number, number, number] | null = null;
  private solved: Pose | null = null;
  private offering = 0;

  /**
   * `model` is the look's container instantiated for this figure; `lookHeightMm` the look's natural
   * height and `heightMm` the height it is drawn at (the look's, kept inside its kind's range);
   * `motion` the table a body whose plan states its chains is posed by (`./body-motion.ts`), and
   * `extentMm` the extent its kind states, for a kind that states one.
   */
  constructor(parent: pc.Entity, model: pc.Entity, plan: BodyPlanEntry, name: string, lookHeightMm: number, heightMm: number, private readonly motion: BodyMotion | null = null, extentMm: BodyExtent | null = null) {
    this.root = new pc.Entity(name);
    parent.addChild(this.root);
    this.figure = model;
    this.root.addChild(this.figure);
    const rest = new Map<string, Vec3>();
    for (const node of this.figure.children as pc.Entity[]) {
      if (!node.name.startsWith('bone:')) continue;
      const bone = node.name.slice('bone:'.length);
      const p = node.getLocalPosition();
      rest.set(bone, [p.x, p.y, p.z]);
      this.joints.set(bone, node);
    }
    this.skeleton = dressSkeleton(plan, rest);
    for (const bone of this.skeleton.order) {
      const up = this.skeleton.parentOf.get(bone) ?? null;
      if (up === null) continue;
      const node = this.joints.get(bone)!;
      node.reparent(this.joints.get(up)!);
      const a = rest.get(bone)!, b = rest.get(up)!;
      node.setLocalPosition(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    }
    for (const [socket, bone] of this.skeleton.socketBones) {
      const node = this.joints.get(bone)!.findByName(`socket:${socket}`);
      if (node instanceof pc.Entity) this.sockets.set(socket, node);
    }
    this.scale = heightMm / lookHeightMm;
    this.standingHeight = heightMm / 1000;
    this.figure.setLocalScale(this.scale, this.scale, this.scale);
    this.figure.setLocalRotation(quat(HALF_TURN));
    const w = PICK_HALF_WIDTH * this.standingHeight;
    // A body whose kind states its extent is picked over the ground it covers and turns as fast as its size lets it.
    const ground = extentMm === null ? null : bodyGround(extentMm, this.scale, motion);
    this.footprint = ground?.footprint ?? null;
    this.turnRate = ground?.turnRate ?? null;
    this.pickVolume = ground === null
      ? { kind: 'box', min: [-w, 0, -w], max: [w, this.standingHeight, w] }
      : { kind: 'box', min: [-ground.footprint.halfAcross, 0, -ground.footprint.halfAlong], max: [ground.footprint.halfAcross, this.standingHeight, ground.footprint.halfAlong] };
    this.solve({ position: [0, 0, 0], facing: 0, deltaSeconds: 0 });
  }

  pose(pose: ThingPose): void {
    const [x, y, z] = pose.position;
    const dt = Math.max(0, pose.deltaSeconds);
    if (this.previous !== null && !pose.discontinuity && dt > 0) {
      const moved = Math.hypot(x - this.previous[0], z - this.previous[2]);
      this.speed += (moved / dt / this.scale - this.speed) * Math.min(1, dt * 6);
      this.travelled += bodyTravel(this.skeleton, moved / this.scale, this.speed, this.motion);
    } else if (pose.discontinuity) {
      this.speed = 0;
    }
    this.previous = pose.position;
    this.time += pose.reducedMotion ? 0 : dt;
    this.root.setLocalPosition(x, y, z);
    this.root.setLocalEulerAngles(0, (pose.facing * 180) / Math.PI, 0);
    this.solve(pose);
  }

  private solve(pose: ThingPose): void {
    const reach = pose.reach ?? null;
    this.offering = reach === null ? 0 : Math.max(0, Math.min(1, reach.amount));
    this.solved = solvePose(this.skeleton, {
      travelled: this.travelled,
      speed: pose.reducedMotion ? 0 : this.speed,
      time: this.time,
      holding: pose.holding ?? new Set(),
      reach,
      talking: pose.talking === true,
      ...(pose.reducedMotion ? { reducedMotion: true } : {}),
    }, this.motion);
    for (const bone of this.skeleton.order) this.joints.get(bone)!.setLocalRotation(quat(this.solved.local.get(bone)!));
    const at = this.solved.rootPosition;
    this.joints.get(this.skeleton.root)!.setLocalPosition(at[0], at[1], at[2]);
    this.placeHeld();
  }

  hold(socket: string, entity: pc.Entity, grip: Grip): void {
    this.release(socket);
    this.root.addChild(entity);
    this.held.set(socket, { entity, grip });
    this.placeHeld();
  }

  release(socket: string): pc.Entity | null {
    const held = this.held.get(socket);
    if (held === undefined) return null;
    this.held.delete(socket);
    this.root.removeChild(held.entity);
    return held.entity;
  }

  private placeHeld(): void {
    // The body's frame in the world: the root's facing and the look's half turn.
    const body = mul(quatOf(this.root.getRotation()), HALF_TURN);
    for (const [socket, { entity, grip }] of this.held) {
      const node = this.sockets.get(socket);
      const bone = this.skeleton.socketBones.get(socket);
      const at = node ?? (bone === undefined ? undefined : this.joints.get(bone));
      if (at === undefined) continue;
      const carry = node !== undefined
        ? nodeCarry(grip.axis, quatOf(node.getRotation()), body)
        : mul(body, bodyCarry(grip.axis, this.offering));
      placeHeld(entity, grip, at.getPosition(), carry);
    }
  }

  /** Where a socket holds things now, in the world, or null for a socket this look does not dress. */
  socketPosition(socket: string): pc.Vec3 | null {
    const node = this.sockets.get(socket);
    const bone = this.skeleton.socketBones.get(socket);
    const at = node ?? (bone === undefined ? undefined : this.joints.get(bone));
    return at === undefined ? null : at.getPosition().clone();
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
}
