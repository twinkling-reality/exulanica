/**
 * Where a scene's point maps stand when pose recovery placed none of them: a fan from one
 * standpoint, and the result says it is not measured.
 *
 * Rung 3 in product-specification.md section 5 is per-image monocular point maps, "placed at
 * recovered poses where they exist and on a derived path where they do not". This is that derived
 * path for the case where none exist. Each map keeps its own camera frame, OPM axes (+X right,
 * +Y up, -Z forward); every camera is moved to one shared standpoint and turned about the vertical
 * so each photograph's frustum occupies its own slice of the horizon, in the order given, left to
 * right, with a small gap. A visitor who arrives at the standpoint turns to see each photograph in
 * depth and steps aside for its parallax.
 *
 * Why a fan and not a row. A casual photograph's depth reaches the horizon: the first personal
 * place (MEASURED 2026-09-11) had people at 2.5 m and a ridge at 165 to 215 m in every map. Side by
 * side, frusta that deep overlap within metres and their far fields interleave. Turned apart, they
 * never overlap. Photographs taken minutes apart in one place were usually taken from about one
 * spot, which the fan also says; where they were not, the arrangement is still labelled
 * unmeasured and claims nothing about where anyone stood.
 *
 * Nothing here is a recovered position. The caller must present the arrangement as unmeasured.
 */

export type FanVec3 = readonly [number, number, number];

export interface UnmeasuredFanInput {
  /** The map's own camera position in its local frame, from the OPM viewpoint. */
  readonly position: FanVec3;
  readonly fovYDeg: number;
  /** Width over height of the source photograph. */
  readonly aspect: number;
}

/** The gap between adjacent photographs, so their edges read as two photographs and not one. */
export const UNMEASURED_FAN_GAP_DEG = 6;
/** Beyond this the last photograph would come round behind the first. */
export const UNMEASURED_FAN_MAX_SWEEP_DEG = 330;
/** Used when a map declares a field of view that cannot be a camera's. */
const FALLBACK_HORIZONTAL_FOV_DEG = 60;

/** A map's horizontal field of view in degrees, from its vertical field of view and aspect. */
export function horizontalFovDeg(input: UnmeasuredFanInput): number {
  const { fovYDeg, aspect } = input;
  if (!Number.isFinite(fovYDeg) || !Number.isFinite(aspect) || fovYDeg <= 0 || fovYDeg >= 180
    || aspect <= 0) {
    return FALLBACK_HORIZONTAL_FOV_DEG;
  }
  const half = Math.atan(Math.tan((fovYDeg * Math.PI) / 360) * aspect);
  return (half * 360) / Math.PI;
}

/**
 * One row-major `scene_from_opm` per input, or null for an input the fan has no room for.
 *
 * Every returned matrix is a rotation about +Y and a translation, so it is a rigid transform with
 * unit scale, which `validateSceneTransform` accepts at `localUnitsToSceneUnits` 1.
 */
export function unmeasuredFan(inputs: readonly UnmeasuredFanInput[]): (number[] | null)[] {
  const widths = inputs.map(horizontalFovDeg);
  let fitted = 0;
  let sweep = 0;
  for (const width of widths) {
    const next = sweep + (fitted > 0 ? UNMEASURED_FAN_GAP_DEG : 0) + width;
    if (next > UNMEASURED_FAN_MAX_SWEEP_DEG) break;
    sweep = next;
    fitted += 1;
  }
  let offset = 0;
  return inputs.map((input, index) => {
    if (index >= fitted) return null;
    const width = widths[index]!;
    // Positive yaw turns -Z towards -X, which is left, so the first photograph is leftmost.
    const yaw = ((sweep / 2 - offset - width / 2) * Math.PI) / 180;
    offset += width + UNMEASURED_FAN_GAP_DEG;
    const c = Math.cos(yaw);
    const s = Math.sin(yaw);
    const [px, py, pz] = input.position;
    // scene_from_opm = R_y(yaw) * T(-position): the camera moves to the standpoint, then turns.
    return [
      c, 0, s, -(c * px + s * pz),
      0, 1, 0, -py,
      -s, 0, c, -(-s * px + c * pz),
      0, 0, 0, 1,
    ];
  });
}

/**
 * How far inside one photograph's frame a direction points, in its camera's own axes: 0 at the
 * centre, 1 at the edge, above 1 outside it. Null for a direction behind the camera or a frame
 * the header cannot describe. The larger of the horizontal and vertical fractions, because the
 * frame is a rectangle.
 */
export function frameFraction(direction: FanVec3, input: Pick<UnmeasuredFanInput, 'fovYDeg' | 'aspect'>): number | null {
  const depth = -direction[2];
  const tanY = Math.tan((input.fovYDeg * Math.PI) / 360);
  if (!(depth > 0) || !(tanY > 0) || !(input.aspect > 0) || !Number.isFinite(tanY)) return null;
  return Math.max(
    Math.abs(direction[0] / (depth * tanY * input.aspect)),
    Math.abs(direction[1] / (depth * tanY)),
  );
}
