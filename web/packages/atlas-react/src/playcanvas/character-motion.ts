import {
  PLAYER_BIND_BONES,
  playerGaitPose,
  solveKnee,
  type Bone,
} from './player-rig.js';
import type { V3 } from './player-sculpt.js';
import {
  BASE_DIMENSIONS,
  shapeBone,
  shapePoint,
  type CharacterDimensions,
} from './character-shape.js';

export interface CharacterPoseInput {
  readonly x: number;
  readonly z: number;
  readonly yaw: number;
  readonly dx: number;
  readonly dz: number;
  readonly dt: number;
  readonly reduced: boolean;
}
const length = (b: Bone) => Math.hypot(...b.b.map((n, i) => n - b.a[i]!));
export class CharacterMotion {
  readonly bindBones: readonly Bone[];
  private phase = 0;
  private amount = 0;
  private run = 0;
  private facing: number | null = null;
  private time = 0;
  private anchors: (V3 | null)[] = [null, null];
  private contacts = [false, false];
  private contactYaw = [0, 0];
  constructor(readonly body: CharacterDimensions = BASE_DIMENSIONS) {
    this.bindBones = PLAYER_BIND_BONES.map((b) => shapeBone(b, body));
  }
  reset(): void {
    this.anchors = [null, null];
    this.contacts = [false, false];
    this.amount = 0;
    this.facing = null;
  }
  update(input: CharacterPoseInput): {
    bones: readonly Bone[];
    facing: number;
    worldFeet: readonly V3[];
    stance: readonly boolean[];
  } {
    const dt = Math.max(0.001, Math.min(0.05, input.dt)),
      distance = Math.hypot(input.dx, input.dz),
      speed = distance / dt,
      blend = 1 - Math.exp(-dt / 0.16);
    this.time += dt;
    this.facing ??= input.yaw;
    if (distance > 0.0001) {
      const target = Math.atan2(-input.dx, -input.dz),
        delta = Math.atan2(
          Math.sin(target - this.facing),
          Math.cos(target - this.facing),
        );
      this.facing += delta * Math.min(1, dt * 12);
    }
    this.amount += (Math.min(1, speed / 0.9) - this.amount) * blend;
    this.run +=
      (Math.max(0, Math.min(1, (speed - 2) / 2.4)) - this.run) * blend;
    const legScale =
      ((this.body.heightMm / 1820) * this.body.legRatioMilli) / 484;
    this.phase +=
      (distance / ((1.05 + this.run * 0.55) * legScale)) * Math.PI * 2;
    const gait = playerGaitPose(this.phase, this.amount, this.run),
      bones = gait.bones.map((b) => shapeBone(b, this.body));
    const cos = Math.cos(this.facing),
      sin = Math.sin(this.facing);
    const toWorld = (p: V3): V3 => [
      input.x + cos * p[0] + sin * p[2],
      p[1],
      input.z - sin * p[0] + cos * p[2],
    ];
    const toLocal = (p: V3): V3 => [
      cos * (p[0] - input.x) - sin * (p[2] - input.z),
      p[1],
      sin * (p[0] - input.x) + cos * (p[2] - input.z),
    ];
    const worldFeet: V3[] = [],
      stance: boolean[] = [];
    for (let side = 0; side < 2; side++) {
      const offset = 3 + side * 5;
      let desired = shapePoint(gait.feet[side]!, this.body);
      if (distance < 0.0001)
        desired = [desired[0], this.bindBones[offset + 1]!.b[1], desired[2]];
      // At rest retain both feet; during travel keep exact world contacts until toe-off.
      const contact = distance < 0.0001 || gait.stance[side]!;
      if (contact && (!this.contacts[side] || !this.anchors[side])) {
        this.anchors[side] = toWorld(desired);
        this.contactYaw[side] = this.facing;
      }
      let ankle = contact ? toLocal(this.anchors[side]!) : desired;
      // A discontinuous snapshot is a relocation, not a step to fabricate across space.
      if (Math.hypot(ankle[0], ankle[2]) > 0.85 * legScale) {
        this.anchors[side] = toWorld(desired);
        ankle = desired;
      }
      const hip = bones[offset]!.a,
        joint = solveKnee(
          hip,
          ankle,
          length(this.bindBones[offset]!),
          length(this.bindBones[offset + 1]!),
        );
      bones[offset] = { a: hip, b: joint };
      bones[offset + 1] = { a: joint, b: ankle };
      const footYaw = contact ? this.contactYaw[side]! - this.facing : 0;
      bones[offset + 2] = {
        a: ankle,
        b: [
          ankle[0] - 0.1 * legScale * Math.sin(footYaw),
          ankle[1],
          ankle[2] - 0.1 * legScale * Math.cos(footYaw),
        ],
      };
      this.contacts[side] = contact;
      worldFeet.push(toWorld(ankle));
      stance.push(contact);
    }
    if (!input.reduced) {
      const breath = Math.sin(this.time * 1.4) * 0.0025 * (1 - this.amount);
      for (const i of [1, 2]) {
        const b = bones[i]!;
        bones[i] = {
          a: [b.a[0], b.a[1] + breath, b.a[2]],
          b: [b.b[0], b.b[1] + breath, b.b[2]],
        };
      }
    }
    return { bones, facing: this.facing, worldFeet, stance };
  }
}
