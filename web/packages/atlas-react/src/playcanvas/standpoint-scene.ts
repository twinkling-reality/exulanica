/**
 * Photographs joined where they were taken: one standpoint, measured turns, one shared print.
 *
 * A scene whose photographs were all taken from about one spot has no recovered camera positions,
 * because pose recovery needs the camera to move. Its server record (the standpoint scene, see
 * `exulanica/reconstruction/standpoint_record.py`) measures instead how each photograph was turned
 * from the others, and gives every member a transform that stands its camera at the scene origin,
 * turns it to face the way it faced, brings its depth to the scene's scale and re-projects its
 * sideways extent onto the photograph's own rays. This module turns those transforms into what the
 * renderer needs to draw the members as ONE view:
 *
 * - **Each direction belongs to one photograph.** Where two overlap, the photograph whose own frame
 *   centre is nearer takes the pixel, measured as a fraction of each frame, so the seams run where
 *   both photographs are least stretched. Decided per fragment in the shader from the rotations
 *   planned here, so a seam is exact rather than stepped at the depth grid's cells.
 * - **One print for all of them.** Walking away from the standpoint, every member flattens towards
 *   the same surface, a dome at the scene's median distance whose floor is the ground the person
 *   stood on, by the same amount. Photographs flattened towards one surface stay joined at their
 *   seams; flattened towards a print each, as an unmeasured arrangement is, they would part.
 * - **Where nothing was captured, the view ends plainly.** No member thins out at its frame edge:
 *   that dissolve is what the first personal place's walk found worse than the gaps it hid. An edge
 *   no other photograph continues is drawn as a thin line in the theme's absence colour instead.
 *
 * The server is the authority for every transform. This module refuses one that is not the shape
 * the record promises and decides nothing about where a photograph stands.
 */

import { singleViewDepths } from './point-cloud.js';
import type { PlacedScenePointMap } from './scene-point-maps.js';
import { standpointTransform, type StandpointTransform } from './standpoint-transform.js';

export { standpointTransform, type StandpointTransform } from './standpoint-transform.js';

/**
 * How many other photographs one member's shader can consult. A uniform array has a fixed length;
 * eight photographs from one spot is a wide turn already, and a member of a larger arrangement
 * consults its nearest `STANDPOINT_MAX_OTHERS` by frame-centre angle and is refused beyond that
 * rather than guessed at (see `planStandpoint`).
 */
export const STANDPOINT_MAX_OTHERS = 7;

/**
 * The not-captured line's width, as a fraction of the half frame. From the standpoint a 67 degree
 * phone frame's half is about 34 degrees, so this is about a fifth of a degree: two pixels on a
 * 1280 pixel, 60 degree view, which reads as a drawn edge and not as a band of the photograph.
 */
export const STANDPOINT_EDGE_FRACTION = 0.006;

/** One member's share of the joined view: its own frame, and the frames it cedes pixels to. */
export interface StandpointMemberPlan {
  readonly artifactId: string;
  readonly transform: StandpointTransform;
  /** Tangent of half the photograph's own frame, horizontal then vertical, on its own rays. */
  readonly frameTan: readonly [number, number];
  /**
   * `STANDPOINT_MAX_OTHERS` blocks of three vec4s: the rows of the rotation from this photograph's
   * camera into another's, with that other's horizontal and vertical frame tangents in the first
   * two rows' fourth lanes. Unused blocks are zero.
   */
  readonly others: Float32Array;
  readonly otherCount: number;
}

export interface StandpointPlan {
  readonly members: ReadonlyMap<string, StandpointMemberPlan>;
  /**
   * Where the shared print stands, in scene units from the standpoint: the median of every
   * member's own depths, each at its scene scale. The first personal place's photographs had their
   * subjects at their medians (2.6 to 5.3 m), and a print there is where the photograph's own
   * subject stood.
   */
  readonly printRadius: number;
  /**
   * Radians of parallax per scene unit a visitor stands from the standpoint, at full relief: the
   * largest of any member, so one flattening holds every member within `RELIEF_PARALLAX_DEG` and
   * all of them flatten together.
   */
  readonly parallaxPerUnit: number;
}

function multiplyTransposed(a: readonly number[], b: readonly number[]): number[] {
  // a^T b, both row major 3x3.
  const out = new Array<number>(9).fill(0);
  for (let i = 0; i < 3; i += 1) {
    for (let j = 0; j < 3; j += 1) {
      out[i * 3 + j] = a[i]! * b[j]! + a[3 + i]! * b[3 + j]! + a[6 + i]! * b[6 + j]!;
    }
  }
  return out;
}

function frameTanOf(map: PlacedScenePointMap['map'], lateral: number, depth: number): [number, number] {
  const { fovYDeg, aspect } = map.header.viewpoint;
  const tanY = Math.tan((fovYDeg * Math.PI) / 360) * (lateral / depth);
  return [tanY * aspect, tanY];
}

/**
 * Everything the members of one joined standpoint share, and what each needs of the others.
 *
 * Refuses (TypeError) a member whose transform is not the promised shape, a member drawn in any
 * other arrangement, and a set in which some member overlaps more photographs than its shader can
 * consult: silently dropping one would let two photographs draw the same direction at a seam.
 */
export function planStandpoint(members: readonly PlacedScenePointMap[]): StandpointPlan {
  if (members.some((member) => member.arrangement !== 'standpoint')) {
    throw new TypeError('a standpoint plan is made only of members drawn in that arrangement');
  }
  const transforms = members.map((member) => standpointTransform(member.sceneFromOpmRowMajor));
  const tans = members.map((member, index) =>
    frameTanOf(member.map, transforms[index]!.lateral, transforms[index]!.depth));
  const axes = transforms.map((transform) => {
    const r = transform.rotationRowMajor;
    return [-r[2]!, -r[5]!, -r[8]!] as const;
  });
  const planned = new Map<string, StandpointMemberPlan>();
  members.forEach((member, index) => {
    const own = transforms[index]!;
    // Every other member, nearest optical axis first, so the ones that can share a seam with this
    // photograph are the ones consulted.
    const order = members
      .map((_, other) => other)
      .filter((other) => other !== index)
      .sort((p, q) => {
        const dp = axes[index]![0] * axes[p]![0] + axes[index]![1] * axes[p]![1] + axes[index]![2] * axes[p]![2];
        const dq = axes[index]![0] * axes[q]![0] + axes[index]![1] * axes[q]![1] + axes[index]![2] * axes[q]![2];
        return dq - dp;
      });
    const reachable = order.filter((other) => overlaps(axes[index]!, tans[index]!, axes[other]!, tans[other]!));
    if (reachable.length > STANDPOINT_MAX_OTHERS) {
      throw new TypeError(
        `a photograph overlaps ${reachable.length} others and its shader can consult ${STANDPOINT_MAX_OTHERS}`,
      );
    }
    const others = new Float32Array(STANDPOINT_MAX_OTHERS * 12);
    reachable.forEach((other, slot) => {
      // Directions in this camera's frame, into the other camera's: R_other^T R_own.
      const q = multiplyTransposed(transforms[other]!.rotationRowMajor, own.rotationRowMajor);
      const base = slot * 12;
      others.set([q[0]!, q[1]!, q[2]!, tans[other]![0], q[3]!, q[4]!, q[5]!, tans[other]![1],
        q[6]!, q[7]!, q[8]!, 0], base);
    });
    planned.set(member.artifactId, Object.freeze({
      artifactId: member.artifactId,
      transform: own,
      frameTan: Object.freeze(tans[index]!) as readonly [number, number],
      others,
      otherCount: reachable.length,
    }));
  });
  let parallaxPerUnit = 0;
  const allDepths: number[] = [];
  members.forEach((member, index) => {
    const depths = singleViewDepths(member.map);
    const scale = transforms[index]!.depth;
    allDepths.push(depths.median * scale);
    parallaxPerUnit = Math.max(parallaxPerUnit, (1 / (depths.nearest * scale) - 1 / (depths.furthest * scale)));
  });
  allDepths.sort((p, q) => p - q);
  const middle = allDepths.length >> 1;
  const printRadius = allDepths.length === 0 ? 1
    : allDepths.length % 2 === 1 ? allDepths[middle]! : (allDepths[middle - 1]! + allDepths[middle]!) / 2;
  return Object.freeze({ members: planned, printRadius, parallaxPerUnit });
}

/**
 * Whether two frames can share a direction at all: their optical axes closer than the sum of their
 * half diagonals. Conservative, so a member is never left without a neighbour it does meet.
 */
function overlaps(
  axisA: readonly number[],
  tanA: readonly [number, number],
  axisB: readonly number[],
  tanB: readonly [number, number],
): boolean {
  const cosine = axisA[0]! * axisB[0]! + axisA[1]! * axisB[1]! + axisA[2]! * axisB[2]!;
  const between = Math.acos(Math.max(-1, Math.min(1, cosine)));
  const halfDiagonal = (tan: readonly [number, number]): number => Math.atan(Math.hypot(tan[0], tan[1]));
  return between < halfDiagonal(tanA) + halfDiagonal(tanB);
}
