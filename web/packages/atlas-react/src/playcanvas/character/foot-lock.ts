/**
 * Planted feet: while a foot is in its stance interval it stays where it touched the ground.
 *
 * Clips play at the resolved ground speed, so the planted foot already moves little; this
 * removes the remainder, and the sliding a turn in place would otherwise cause, with an
 * analytic two-bone solve in the leg's current bending plane. The foot keeps its animated
 * world orientation. Runs after the animation update and before rendering.
 */
import * as pc from 'playcanvas';

const SIDES = ['Left', 'Right'] as const;
const BLEND_SECONDS = 0.08;

interface Leg {
  readonly hip: pc.GraphNode;
  readonly knee: pc.GraphNode;
  readonly ankle: pc.GraphNode;
  locked: pc.Vec3 | null;
  weight: number;
  restHeight: number;
}

const a = new pc.Vec3(), b = new pc.Vec3(), c = new pc.Vec3(), t = new pc.Vec3();
const axis = new pc.Vec3(), pole = new pc.Vec3(), tmp = new pc.Vec3();
const q = new pc.Quat(), footRotation = new pc.Quat();

function rotateBoneTowards(bone: pc.GraphNode, from: pc.Vec3, to: pc.Vec3, origin: pc.Vec3): void {
  const u = tmp.sub2(from, origin);
  const v = axis.sub2(to, origin);
  const lu = u.length(), lv = v.length();
  if (lu < 1e-6 || lv < 1e-6) return;
  u.mulScalar(1 / lu);
  v.mulScalar(1 / lv);
  const dot = Math.max(-1, Math.min(1, u.dot(v)));
  if (dot > 0.999999) return;
  const cross = new pc.Vec3().cross(u, v);
  if (cross.length() < 1e-6) return;
  cross.normalize();
  q.setFromAxisAngle(cross, (Math.acos(dot) * 180) / Math.PI);
  const world = bone.getRotation().clone();
  bone.setRotation(q.mul(world));
}

export class FootLock {
  private readonly legs: Leg[] = [];
  private readonly model: pc.Entity;

  constructor(model: pc.Entity, rootBone: pc.GraphNode) {
    this.model = model;
    for (const side of SIDES) {
      const hip = rootBone.findByName(`mixamorig:${side}UpLeg`);
      const knee = rootBone.findByName(`mixamorig:${side}Leg`);
      const ankle = rootBone.findByName(`mixamorig:${side}Foot`);
      if (!hip || !knee || !ankle) continue;
      this.legs.push({ hip, knee, ankle, locked: null, weight: 0, restHeight: Number.NaN });
    }
  }

  reset(): void {
    for (const leg of this.legs) {
      leg.locked = null;
      leg.weight = 0;
    }
  }

  apply(deltaSeconds: number, speed: number): void {
    const ground = this.model.parent?.getPosition().y ?? 0;
    const scale = this.model.getLocalScale().y;
    for (const leg of this.legs) {
      const ankle = leg.ankle.getPosition();
      const height = ankle.y - ground;
      if (!Number.isFinite(leg.restHeight)) leg.restHeight = height;
      // The lowest ankle height seen is the standing height; a small band above it is stance.
      leg.restHeight = Math.min(leg.restHeight + deltaSeconds * 0.01, height);
      const stance = height < leg.restHeight + 0.025 * scale;
      if (stance && !leg.locked) leg.locked = new pc.Vec3(ankle.x, ankle.y, ankle.z);
      if (!stance) leg.locked = null;
      if (leg.locked && Math.hypot(leg.locked.x - ankle.x, leg.locked.z - ankle.z) > 0.22 * scale) {
        // The body has moved on; re-plant rather than stretching the leg.
        leg.locked.set(ankle.x, ankle.y, ankle.z);
      }
      const goal = leg.locked ? 1 : 0;
      const step = deltaSeconds / BLEND_SECONDS;
      leg.weight = goal > leg.weight ? Math.min(goal, leg.weight + step) : Math.max(goal, leg.weight - step);
      if (leg.weight <= 0 || !leg.locked) continue;
      // Idle feet do not drift, so a planted idle needs no correction.
      if (speed <= 0 && Math.hypot(leg.locked.x - ankle.x, leg.locked.z - ankle.z) < 0.002) continue;
      this.solve(leg, leg.weight);
    }
  }

  private solve(leg: Leg, weight: number): void {
    footRotation.copy(leg.ankle.getRotation());
    a.copy(leg.hip.getPosition());
    b.copy(leg.knee.getPosition());
    c.copy(leg.ankle.getPosition());
    t.lerp(c, leg.locked!, weight);
    const upper = b.distance(a), lower = c.distance(b);
    const reach = Math.max(1e-4, Math.min(upper + lower - 1e-4, t.distance(a)));
    // Knee position in the plane of the hip, target and the current knee.
    const toTarget = new pc.Vec3().sub2(t, a).normalize();
    pole.sub2(b, a);
    const along = pole.dot(toTarget);
    pole.sub(new pc.Vec3().copy(toTarget).mulScalar(along));
    if (pole.length() < 1e-6) return;
    pole.normalize();
    const cosA = (upper * upper + reach * reach - lower * lower) / (2 * upper * reach);
    const angle = Math.acos(Math.max(-1, Math.min(1, cosA)));
    const knee = new pc.Vec3().copy(a)
      .add(new pc.Vec3().copy(toTarget).mulScalar(Math.cos(angle) * upper))
      .add(new pc.Vec3().copy(pole).mulScalar(Math.sin(angle) * upper));
    rotateBoneTowards(leg.hip, b, knee, a);
    const kneeNow = leg.knee.getPosition().clone();
    rotateBoneTowards(leg.knee, leg.ankle.getPosition().clone(), t, kneeNow);
    leg.ankle.setRotation(footRotation);
  }
}
