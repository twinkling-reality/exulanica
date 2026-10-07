/**
 * A body plan's skeleton as one look dresses it, and the limbs read from it.
 *
 * A body plan is data: bones with parents, and sockets on bones (`assets/catalogs/things/body-plans`).
 * A look that draws on bones (rigid parts on joints, or a rig mapped onto the plan's bones) places
 * some of those bones at rest. This module joins the two and reads what moves how, from the
 * skeleton's shape alone: no bone is named here, so a person's body, a four-legged one and a
 * ten-legged one are read by the same rules.
 *
 * - A dressed bone's parent is its nearest dressed ancestor in the plan, so a look may leave out
 *   optional bones (shoulders, an upper chest) and its parts still hang from the right joint.
 * - Limbs are the chains between branching joints: from a joint with two or more dressed children
 *   (or the root) down a run of single children to a leaf or the next branching joint.
 * - A limb ending near the ground is a leg; one carrying a socket is an arm; the one ending highest is
 *   the head; a chain between two branching joints is the trunk; anything else (a tail, an antenna)
 *   is an appendage.
 * - Legs step in a gait read from where they hang: ranks front to back, alternating sides and ranks,
 *   which is a biped's left-right walk, a four-legged trot, a six-legged tripod and an alternating
 *   wave for any number more.
 *
 * Positions are in the figure's frame, metres: glTF's axes, +Y up, +Z the figure's front, +X its
 * left (the body plans' slot frame met by the style packs' rotation). Pure: no renderer.
 */

export type Vec3 = readonly [number, number, number];

export interface PlanBone {
  readonly name: string;
  readonly parent: string | null;
  readonly required: boolean;
}

export interface PlanSocket {
  readonly key: string;
  readonly bone: string | null;
  readonly holds: number;
  readonly length_mm_maximum: number;
  readonly grip_section_mm_maximum: number | null;
}

/** The part of a body plan catalog entry this module reads. */
export interface BodyPlanEntry {
  readonly key: string;
  readonly version: number;
  readonly bones: readonly PlanBone[];
  readonly sockets: readonly PlanSocket[];
}

export type LimbRole = 'leg' | 'arm' | 'head' | 'trunk' | 'appendage';

export interface Limb {
  readonly role: LimbRole;
  /** Dressed bones from the limb's first joint to its last, each the next one's dressed parent. */
  readonly bones: readonly string[];
  /** The dressed bone the limb hangs from: the root or a branching joint. */
  readonly from: string;
  /** 1 on the figure's left (+X), -1 on its right, 0 on its middle. */
  readonly side: -1 | 0 | 1;
  /** Sockets on the limb's bones, by key. */
  readonly sockets: readonly string[];
  /** A leg's place in the gait cycle, from 0 up to 1; 0 for any other limb. */
  readonly phase: number;
}

export interface DressedSkeleton {
  readonly plan: string;
  readonly root: string;
  /** Dressed bones, every parent before its children, in the plan's order otherwise. */
  readonly order: readonly string[];
  /** Each dressed bone's nearest dressed ancestor; null for the root. */
  readonly parentOf: ReadonlyMap<string, string | null>;
  readonly childrenOf: ReadonlyMap<string, readonly string[]>;
  /** Joint rest positions in the figure's frame. */
  readonly rest: ReadonlyMap<string, Vec3>;
  readonly limbs: readonly Limb[];
  /** Each socket of the plan that sits on a dressed bone, to that bone. */
  readonly socketBones: ReadonlyMap<string, string>;
  /** The highest and lowest joint at rest, metres: the figure's extent the joints reach. */
  readonly top: number;
  readonly bottom: number;
}

export type SkeletonRefusal =
  | 'look_bone_unknown'
  | 'look_required_bone_missing'
  | 'look_not_one_skeleton';

export class SkeletonRefused extends Error {
  override readonly name = 'SkeletonRefused';
  constructor(readonly reason: SkeletonRefusal, message: string) {
    super(message);
  }
}

/** Joints within this share of the figure's height of the lowest are on the ground. */
const GROUND_BAND = 0.12;
/** Joints within this share of the height of the middle are on neither side. */
const MIDDLE_BAND = 0.02;
/** Legs whose hips are within this share of the height front to back step in one rank. */
const RANK_BAND = 0.1;

/**
 * The skeleton `joints` dress of `plan`: every joint a bone of the plan, every required bone dressed,
 * one root. Refused by name otherwise.
 */
export function dressSkeleton(plan: BodyPlanEntry, joints: ReadonlyMap<string, Vec3>): DressedSkeleton {
  const planned = new Map(plan.bones.map((bone) => [bone.name, bone]));
  for (const name of joints.keys()) {
    if (!planned.has(name)) {
      throw new SkeletonRefused('look_bone_unknown', `The look places a joint "${name}" that ${plan.key}/v${plan.version} has no bone for.`);
    }
  }
  for (const bone of plan.bones) {
    if (bone.required && !joints.has(bone.name)) {
      throw new SkeletonRefused('look_required_bone_missing', `The look places no joint for ${plan.key}/v${plan.version}'s required bone "${bone.name}".`);
    }
  }
  const parentOf = new Map<string, string | null>();
  for (const bone of plan.bones) {
    if (!joints.has(bone.name)) continue;
    let up = bone.parent;
    while (up !== null && !joints.has(up)) up = planned.get(up)?.parent ?? null;
    parentOf.set(bone.name, up);
  }
  const roots = [...parentOf].filter(([, parent]) => parent === null).map(([name]) => name);
  if (roots.length !== 1) {
    throw new SkeletonRefused('look_not_one_skeleton', `The look's joints make ${roots.length} skeletons, not one.`);
  }
  const root = roots[0]!;
  const childrenOf = new Map<string, string[]>([...parentOf.keys()].map((name) => [name, []]));
  for (const [name, parent] of parentOf) if (parent !== null) childrenOf.get(parent)!.push(name);
  const order: string[] = [];
  const visit = (name: string) => {
    order.push(name);
    for (const child of childrenOf.get(name)!) visit(child);
  };
  visit(root);

  const ys = [...joints.values()].map((p) => p[1]);
  const top = Math.max(...ys);
  const bottom = Math.min(...ys);
  const height = Math.max(1e-6, top - bottom);
  const socketBones = new Map<string, string>();
  for (const socket of plan.sockets) {
    if (socket.bone !== null && joints.has(socket.bone)) socketBones.set(socket.key, socket.bone);
  }

  // Chains: from each branching joint (or the root) down single children to a leaf or the next
  // branching joint, which ends the chain and starts its own.
  const branching = (name: string) => name === root || childrenOf.get(name)!.length >= 2;
  const chains: { bones: string[]; from: string }[] = [];
  const startChains = (from: string) => {
    for (const child of childrenOf.get(from)!) {
      const bones = [child];
      let at = child;
      while (!branching(at) && childrenOf.get(at)!.length === 1) {
        at = childrenOf.get(at)![0]!;
        bones.push(at);
      }
      chains.push({ bones, from });
      if (branching(at)) startChains(at);
    }
  };
  startChains(root);

  const rootAt = joints.get(root)!;
  const leaves = chains.filter((chain) => childrenOf.get(chain.bones.at(-1)!)!.length === 0);
  const highest = leaves.reduce<string | null>((best, chain) => {
    const end = chain.bones.at(-1)!;
    return best === null || joints.get(end)![1] > joints.get(best)![1] ? end : best;
  }, null);
  const socketKeysOn = (bones: readonly string[]) =>
    [...socketBones].filter(([, bone]) => bones.includes(bone)).map(([key]) => key);
  const sideOf = (point: Vec3): -1 | 0 | 1 => {
    const dx = point[0] - rootAt[0];
    return Math.abs(dx) <= MIDDLE_BAND * height ? 0 : dx > 0 ? 1 : -1;
  };

  const read = chains.map((chain) => {
    const end = chain.bones.at(-1)!;
    const endAt = joints.get(end)!;
    const leaf = childrenOf.get(end)!.length === 0;
    const sockets = socketKeysOn(chain.bones);
    const role: LimbRole = leaf && endAt[1] <= bottom + GROUND_BAND * height
      ? 'leg'
      : sockets.length > 0
        ? 'arm'
        : leaf && end === highest
          ? 'head'
          : !leaf
            ? 'trunk'
            : 'appendage';
    return { role, bones: chain.bones, from: chain.from, side: sideOf(endAt), sockets };
  });

  // The gait: legs ranked front to back by where they hang, alternating by side and by rank.
  const legs = read.filter((limb) => limb.role === 'leg');
  const hips = (limb: (typeof read)[number]) => joints.get(limb.bones[0]!)!;
  const fronts = [...new Set(legs.map((leg) => hips(leg)[2]))].sort((a, b) => b - a);
  const ranks: number[] = [];
  for (const z of fronts) if (ranks.length === 0 || ranks.at(-1)! - z > RANK_BAND * height) ranks.push(z);
  const rankOf = (z: number) => ranks.findIndex((front) => front - z <= RANK_BAND * height);
  const limbs: Limb[] = read.map((limb) => {
    if (limb.role !== 'leg') return { ...limb, phase: 0 };
    const rank = rankOf(hips(limb)[2]);
    const sidePhase = limb.side === -1 ? 0.5 : 0;
    return { ...limb, phase: ((rank % 2) * 0.5 + sidePhase) % 1 };
  });

  return Object.freeze({
    plan: `${plan.key}/v${plan.version}`,
    root,
    order: Object.freeze(order),
    parentOf,
    childrenOf: new Map([...childrenOf].map(([name, children]) => [name, Object.freeze([...children])])),
    rest: joints,
    limbs: Object.freeze(limbs),
    socketBones,
    top,
    bottom,
  });
}
