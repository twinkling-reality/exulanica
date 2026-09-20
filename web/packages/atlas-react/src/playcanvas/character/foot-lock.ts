/**
 * Planted feet: the part of a foot touching the ground stays where it touched down.
 *
 * Clips play at a cadence matched to the resolved ground speed, so a planted foot already moves
 * little; this removes the remainder, and the sliding a turn in place would otherwise cause. The
 * contact point is whatever is on the ground: the heel from heel strike, then the toe from the
 * moment it is down through push-off, when the heel lifts and the foot rolls over it. Pinning the
 * ankle alone let the toe swing through that roll. When contact passes from heel to toe the toe
 * inherits the heel's correction, so nothing jumps. An analytic two-bone solve in the leg's current
 * bending plane moves the ankle; the foot keeps its animated world orientation. Runs after the
 * animation update and before rendering.
 */
import * as pc from 'playcanvas';

const SIDES = ['Left', 'Right'] as const;
const BLEND_SECONDS = 0.08;
/** Height above its lowest recent point at which a heel or toe still counts as on the ground. */
const CONTACT_METRES = 0.02;
/** A correction larger than this means the body has moved on; the foot re-plants instead. */
const REPLANT_METRES = 0.25;

interface Contact {
  locked: pc.Vec3 | null;
  floor: number;
}

interface Leg {
  readonly hip: pc.GraphNode;
  readonly knee: pc.GraphNode;
  readonly ankle: pc.GraphNode;
  readonly toe: pc.GraphNode | null;
  readonly heel: Contact;
  readonly ball: Contact;
  /** Horizontal correction applied to the ankle, blended in and out. */
  readonly offset: pc.Vec3;
  weight: number;
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

function track(contact: Contact, height: number, deltaSeconds: number, scale: number): boolean {
  // The lowest height in this contact's window is the ground for this point; it rises slowly so a sloped or
  // re-posed body does not leave the point stuck below the resting height that follows.
  contact.floor = Number.isFinite(contact.floor) ? Math.min(contact.floor + deltaSeconds * 0.01, height) : height;
  return height < contact.floor + CONTACT_METRES * scale;
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
      const toe = rootBone.findByName(`mixamorig:${side}ToeBase`);
      this.legs.push({
        hip, knee, ankle, toe,
        heel: { locked: null, floor: Number.NaN },
        ball: { locked: null, floor: Number.NaN },
        offset: new pc.Vec3(),
        weight: 0,
      });
    }
  }

  reset(): void {
    for (const leg of this.legs) {
      leg.heel.locked = null;
      leg.ball.locked = null;
      leg.offset.set(0, 0, 0);
      leg.weight = 0;
    }
  }

  apply(deltaSeconds: number, speed: number): void {
    const ground = this.model.parent?.getPosition().y ?? 0;
    const scale = this.model.getLocalScale().y;
    for (const leg of this.legs) {
      const ankle = leg.ankle.getPosition();
      const toe = leg.toe?.getPosition() ?? null;
      const heelDown = track(leg.heel, ankle.y - ground, deltaSeconds, scale);
      const ballDown = toe !== null && track(leg.ball, toe.y - ground, deltaSeconds, scale);
      let correction: pc.Vec3 | null = null;
      if (ballDown && toe) {
        if (!leg.ball.locked) {
          // Contact passes from the heel: the toe starts from where the corrected foot already is.
          const inherited = leg.heel.locked ? new pc.Vec3(leg.heel.locked.x - ankle.x, 0, leg.heel.locked.z - ankle.z) : new pc.Vec3();
          leg.ball.locked = new pc.Vec3(toe.x + inherited.x, toe.y, toe.z + inherited.z);
        }
        correction = new pc.Vec3(leg.ball.locked.x - toe.x, 0, leg.ball.locked.z - toe.z);
        leg.heel.locked = null;
      } else {
        leg.ball.locked = null;
        if (heelDown) {
          leg.heel.locked ??= new pc.Vec3(ankle.x, ankle.y, ankle.z);
          correction = new pc.Vec3(leg.heel.locked.x - ankle.x, 0, leg.heel.locked.z - ankle.z);
        } else {
          leg.heel.locked = null;
        }
      }
      if (correction && correction.length() > REPLANT_METRES * scale) {
        // The body has moved on; re-plant where the foot is rather than stretching the leg.
        leg.heel.locked = heelDown && !ballDown ? new pc.Vec3(ankle.x, ankle.y, ankle.z) : null;
        leg.ball.locked = ballDown && toe ? new pc.Vec3(toe.x, toe.y, toe.z) : null;
        correction.set(0, 0, 0);
      }
      // A correction is zero at the moment of contact, so it applies in full at once; only letting
      // go blends, so a lifting foot eases back to its animation.
      leg.weight = correction ? 1 : Math.max(0, leg.weight - deltaSeconds / BLEND_SECONDS);
      if (correction) leg.offset.copy(correction);
      if (leg.weight <= 0) continue;
      // A standing foot that has not drifted needs no correction.
      if (speed <= 0 && leg.offset.length() < 0.002) continue;
      this.solve(leg, leg.weight);
    }
  }

  private solve(leg: Leg, weight: number): void {
    footRotation.copy(leg.ankle.getRotation());
    a.copy(leg.hip.getPosition());
    b.copy(leg.knee.getPosition());
    c.copy(leg.ankle.getPosition());
    t.copy(leg.offset).mulScalar(weight).add(c);
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
