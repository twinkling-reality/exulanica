/**
 * A body plan's skeleton as one look dresses it, and the limbs read from it.
 *
 * A body plan is data: bones with parents, and sockets on bones (`assets/catalogs/things/body-plans`).
 * A look that draws on bones (rigid parts on joints, or a rig mapped onto the plan's bones) places
 * some of those bones at rest. This module joins the two and reads what moves how: from the chains
 * the plan states where it states them, and from the skeleton's shape alone where it states none.
 * No bone is named here, so a person's body, a four-legged one and a ten-legged one are read by
 * the same rules.
 *
 * - A dressed bone's parent is its nearest dressed ancestor in the plan, so a look may leave out
 *   optional bones (shoulders, an upper chest) and its parts still hang from the right joint.
 *
 * A plan that states chains (a drafted body's, `limbs` in the things contract):
 *
 * - Each chain is a limb with the chain's own role, side and order: a spine, a neck, a jaw, a tail,
 *   a leg, an arm, a wing, a fin or a tentacle. Nothing is guessed from where a chain ends or what
 *   it carries, so a head that holds with its jaws is a neck, a head and a jaw, never an arm.
 * - A bone outside every chain is a limb of its own: a head where a neck chain ends at its parent
 *   or a jaw chain hangs from it, and otherwise a bone that keeps its rest turn.
 * - A leg's place in the gait is its chain's order and side. A body with no leg steps on its
 *   tentacles, alternate ones together; one with neither, whose spine lies along the ground, moves
 *   by a wave down that spine.
 *
 * A plan that states none (every shipped plan):
 *
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

/** The roles a plan's chain may state, and the sides (the things contract, "Chains"). */
export const CHAIN_ROLES = ['spine', 'neck', 'tail', 'jaw', 'leg', 'arm', 'wing', 'fin', 'tentacle'] as const;
export const CHAIN_SIDES = ['left', 'right', 'centre'] as const;
export type ChainRole = (typeof CHAIN_ROLES)[number];
export type ChainSide = (typeof CHAIN_SIDES)[number];

/** A chain a plan states: its bones from the body outward, each the child of the one before. */
export interface PlanChain {
  readonly key: string;
  readonly role: ChainRole;
  readonly side: ChainSide;
  /** Its place among the chains of its role, counting from the front. */
  readonly order: number;
  readonly bones: readonly string[];
}

/** The part of a body plan catalog entry this module reads. */
export interface BodyPlanEntry {
  readonly key: string;
  readonly version: number;
  readonly bones: readonly PlanBone[];
  readonly sockets: readonly PlanSocket[];
  /** The chains the plan states; absent or empty for a plan whose limbs are read from its shape. */
  readonly limbs?: readonly PlanChain[];
}

/**
 * What a limb is. Read from a skeleton's shape: a leg, an arm, a head (its neck and head as one
 * chain), a trunk or an appendage. Stated by a plan's chain: the chain's own role, with `skull` for
 * a head bone outside the chains and `still` for any other bone outside them.
 */
export type LimbRole = 'leg' | 'arm' | 'head' | 'trunk' | 'appendage' | 'spine' | 'neck' | 'skull' | 'jaw' | 'tail' | 'wing' | 'fin' | 'tentacle' | 'still';

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
  /** A stepping limb's place in the gait cycle, from 0 up to 1; 0 for any other limb. */
  readonly phase: number;
  /** A stated chain's place among the chains of its role, from the front; 0 for any other limb. */
  readonly order: number;
}

/**
 * How a body covers ground: on the limbs it steps with, by a wave down a spine that lies along
 * the ground, or (a body with neither, and every body standing still) with no walk drawn.
 */
export type Gait = 'steps' | 'wave' | 'none';

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
  /** Whether the limbs are the plan's stated chains (true) or were read from the shape (false). */
  readonly stated: boolean;
  /** The limbs the body steps on: its legs, or tentacles where a stated body has no leg. */
  readonly steps: readonly Limb[];
  /** Whether a stated spine lies along the ground: it runs further forward or back than up or down. */
  readonly lying: boolean;
  readonly gait: Gait;
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
  const socketKeysOn = (bones: readonly string[]) =>
    [...socketBones].filter(([, bone]) => bones.includes(bone)).map(([key]) => key);
  const finish = (limbs: readonly Limb[], stated: boolean): DressedSkeleton => {
    const legs = limbs.filter((limb) => limb.role === 'leg');
    const steps = legs.length > 0 ? legs : limbs.filter((limb) => limb.role === 'tentacle' && limb.bones.length >= 2);
    const lying = limbs.some((limb) => {
      if (limb.role !== 'spine' || limb.from !== root) return false;
      const a = joints.get(limb.from)!, b = joints.get(limb.bones.at(-1)!)!;
      return Math.abs(b[2] - a[2]) > Math.abs(b[1] - a[1]);
    });
    return Object.freeze({
      plan: `${plan.key}/v${plan.version}`,
      root,
      order: Object.freeze(order),
      parentOf,
      childrenOf: new Map([...childrenOf].map(([name, children]) => [name, Object.freeze([...children])])),
      rest: joints,
      limbs: Object.freeze(limbs),
      stated,
      steps: Object.freeze(steps),
      lying,
      gait: steps.length > 0 ? 'steps' : lying ? 'wave' : 'none',
      socketBones,
      top,
      bottom,
    });
  };

  // A plan that states chains: each is a limb as stated, and a bone outside them a limb of its own.
  const statedChains = (plan.limbs ?? [])
    .map((chain) => ({ chain, bones: chain.bones.filter((bone) => joints.has(bone) && bone !== root) }))
    .filter(({ bones }) => bones.length > 0);
  if (statedChains.length > 0) {
    const sides = { left: 1, right: -1, centre: 0 } as const;
    const legless = !statedChains.some(({ chain }) => chain.role === 'leg');
    const limbs: Limb[] = statedChains.map(({ chain, bones }) => {
      const side = sides[chain.side];
      // Legs alternate by side and by rank; tentacles a legless body steps on, alternate ones together.
      const phase = chain.role === 'leg'
        ? (((chain.order % 2) * 0.5 + (side === -1 ? 0.5 : 0)) % 1)
        : chain.role === 'tentacle' && legless ? (chain.order % 2) * 0.5 : 0;
      return { role: chain.role, bones, from: parentOf.get(bones[0]!)!, side, sockets: socketKeysOn(bones), phase, order: chain.order };
    });
    const chained = new Set(limbs.flatMap((limb) => limb.bones));
    const neckEnds = new Set(limbs.filter((limb) => limb.role === 'neck').map((limb) => limb.bones.at(-1)!));
    const jawRoots = new Set(limbs.filter((limb) => limb.role === 'jaw').map((limb) => limb.from));
    for (const bone of order) {
      if (bone === root || chained.has(bone)) continue;
      const from = parentOf.get(bone)!;
      const skull = neckEnds.has(from) || jawRoots.has(bone);
      limbs.push({ role: skull ? 'skull' : 'still', bones: [bone], from, side: 0, sockets: socketKeysOn([bone]), phase: 0, order: 0 });
    }
    return finish(limbs, true);
  }

  const leaves = chains.filter((chain) => childrenOf.get(chain.bones.at(-1)!)!.length === 0);
  const highest = leaves.reduce<string | null>((best, chain) => {
    const end = chain.bones.at(-1)!;
    return best === null || joints.get(end)![1] > joints.get(best)![1] ? end : best;
  }, null);
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
    if (limb.role !== 'leg') return { ...limb, phase: 0, order: 0 };
    const rank = rankOf(hips(limb)[2]);
    const sidePhase = limb.side === -1 ? 0.5 : 0;
    return { ...limb, phase: ((rank % 2) * 0.5 + sidePhase) % 1, order: 0 };
  });

  return finish(limbs, false);
}
