/**
 * Click-to-evidence: turn a click in the reconstruction inspector into a recorded sparse point.
 *
 * Roadmap Phase 10. A visitor selects a surface and asks what it is made of; the answer is the set
 * of photographs whose cameras actually observed that piece of the world. The backend serves that
 * observation graph; this module is the geometry that gets from a cursor to one of its points.
 *
 * **Why this lives in the inspector and not in traverse mode.** Traverse holds Pointer Lock, which
 * freezes `clientX`/`clientY` (`atlas-react/src/playcanvas/controls.ts`), and the focus solver's
 * header states that it must never take a screen-space input: the only direction it reads is the
 * camera forward vector. The inspector already exits pointer lock, already suspends walking input,
 * and already stands on a calibrated recovered camera, so a click there has real coordinates and a
 * real projection to invert. Building this for traverse would mean either breaking pointer lock or
 * inventing a screen-space path into the focus solver, and neither is worth it for a gesture whose
 * whole point is careful inspection.
 *
 * **Why a sparse point and not a raycast.** `atlas-three/src/containment.ts` already records why a
 * point map is not a surface: the nearest point lets you stand inside a wall, and a per-frame kNN
 * over four million points is ruinous. But the question here is not "what surface is under the
 * cursor", it is "which photographs observed this part of the world", and the recorded answer is
 * attached to COLMAP's sparse points rather than to any drawn geometry. Projecting a few thousand
 * sparse points forward is exact, cheap, and answers the question that was actually asked.
 *
 * **What this is not.** The point returned is the nearest recorded observation to the cursor, not
 * the surface under it. The two coincide when the reconstruction is dense and diverge on a plain
 * surface, which the 2026-09-05 bowl run measured directly: a plain table around a densely matched
 * bowl carries almost no sparse points. A caller must show the pixel distance, or refuse when it
 * exceeds a tolerance, rather than presenting a distant point as though the visitor had clicked it.
 */

/** One sparse point from the observation graph, in scene (recovered COLMAP) coordinates. */
export interface SparseObservedPoint {
  readonly pointId: number;
  readonly world: readonly [number, number, number];
  /** How many photographs observed this point, from COLMAP before any truncation. */
  readonly trackLength: number;
  /** How many of those the served graph actually holds. Never larger than `trackLength`. */
  readonly observationsRetained: number;
}

export interface PickCalibration {
  readonly width: number;
  readonly height: number;
  readonly fx: number;
  readonly fy: number;
  readonly cx: number;
  readonly cy: number;
}

export interface PickCamera {
  /**
   * Row-major 4x4 renderer-camera-to-scene transform at unit scale, exactly as the graph delivers
   * it. Renderer convention: +X right, +Y up, -Z forward.
   */
  readonly sceneFromCameraRowMajor: readonly number[];
  readonly calibration: PickCalibration;
  /**
   * `pinhole-approximation` means the original camera had a distortion model this projection does
   * not apply. The pick inherits that label rather than discarding it, so a caller can say so.
   */
  readonly projection: 'pinhole' | 'pinhole-approximation';
}

export interface PickResult {
  readonly point: SparseObservedPoint;
  /** Distance in source-image pixels between the cursor and the point's projection. */
  readonly pixelDistance: number;
  /** Distance along the camera's forward axis, in scene units. Never metres. */
  readonly depth: number;
  readonly projection: 'pinhole' | 'pinhole-approximation';
}

export interface PickOptions {
  /**
   * How far from the cursor, in source-image pixels, a point may be and still count as clicked.
   *
   * A real limit rather than a nicety: sparse points are sparse, and without one the nearest point
   * to a click on a blank wall is whatever happens to be nearest in the whole frame.
   */
  readonly tolerancePx?: number;
  /**
   * Points whose pixel distance is within this much of the best candidate are treated as being on
   * the same ray, and the nearest one wins. Without it a background point a fraction of a pixel
   * closer to the cursor beats the foreground surface actually occluding it.
   */
  readonly occlusionBandPx?: number;
}

const DEFAULT_TOLERANCE_PX = 24;
const DEFAULT_OCCLUSION_BAND_PX = 4;

/**
 * Where a canvas click lands in the source photograph's own pixel coordinates.
 *
 * This inverts the inspector's calibrated frustum exactly (`calibratedCameraFrustum` in
 * `atlas-react`): vertical coverage is fitted to the full image height, and a canvas wider than
 * the source aspect ratio exposes more of the world horizontally rather than stretching it. The
 * returned `u` therefore falls outside `[0, width]` for a click in that extra horizontal margin,
 * which is a real place in the world that the photograph does not cover. That is returned rather
 * than clamped, because clamping would report a click outside the frame as a click at its edge.
 */
export function canvasToSourcePixel(
  calibration: PickCalibration,
  canvas: { readonly width: number; readonly height: number },
  cursor: { readonly x: number; readonly y: number },
): { readonly u: number; readonly v: number } {
  if (canvas.width <= 0 || canvas.height <= 0) {
    throw new RangeError('canvas dimensions must be positive');
  }
  const halfWidth = ((canvas.width / canvas.height) * calibration.height) / 2;
  return {
    u: calibration.width / 2 - halfWidth + (cursor.x / canvas.width) * 2 * halfWidth,
    v: (cursor.y / canvas.height) * calibration.height,
  };
}

/** Rigid inverse: the scene point, expressed in the camera's own frame. */
function inCameraFrame(
  m: readonly number[],
  world: readonly [number, number, number],
): readonly [number, number, number] {
  const dx = world[0] - m[3]!;
  const dy = world[1] - m[7]!;
  const dz = world[2] - m[11]!;
  // Transpose of the rotation block, which is the inverse only because the delivered transform is
  // unit-scale and rejects shear and reflection upstream (`validateSceneTransform`).
  return [
    m[0]! * dx + m[4]! * dy + m[8]! * dz,
    m[1]! * dx + m[5]! * dy + m[9]! * dz,
    m[2]! * dx + m[6]! * dy + m[10]! * dz,
  ];
}

/**
 * Where a scene point lands in the source photograph, or `null` when it is behind the camera.
 *
 * The renderer camera looks down -Z, and COLMAP's image axes are +X right, +Y down, so the sign of
 * the vertical term flips on the way across. Getting that wrong produces a vertically mirrored pick
 * that looks plausible on a symmetric subject, which is why the round trip is tested rather than
 * reasoned about.
 */
export function projectToSourcePixel(
  camera: PickCamera,
  world: readonly [number, number, number],
): { readonly u: number; readonly v: number; readonly depth: number } | null {
  const [x, y, z] = inCameraFrame(camera.sceneFromCameraRowMajor, world);
  const depth = -z;
  if (!(depth > 1e-6)) return null;
  const c = camera.calibration;
  return { u: c.cx + (c.fx * x) / depth, v: c.cy - (c.fy * y) / depth, depth };
}

/**
 * The sparse point a click selects, or `null` when nothing recorded is near enough.
 *
 * `null` is a real answer and callers must show it as one: it means no photograph's recorded
 * observations reach this part of the view, which is the honest state for a plain surface the
 * reconstruction matched few features on.
 */
export function pickObservedPoint(
  camera: PickCamera,
  points: readonly SparseObservedPoint[],
  cursor: { readonly u: number; readonly v: number },
  options: PickOptions = {},
): PickResult | null {
  const tolerance = options.tolerancePx ?? DEFAULT_TOLERANCE_PX;
  const band = options.occlusionBandPx ?? DEFAULT_OCCLUSION_BAND_PX;

  const candidates: PickResult[] = [];
  for (const point of points) {
    const projected = projectToSourcePixel(camera, point.world);
    if (projected === null) continue;
    const pixelDistance = Math.hypot(projected.u - cursor.u, projected.v - cursor.v);
    if (pixelDistance > tolerance) continue;
    candidates.push({
      point,
      pixelDistance,
      depth: projected.depth,
      projection: camera.projection,
    });
  }
  if (candidates.length === 0) return null;

  const nearestToCursor = Math.min(...candidates.map((item) => item.pixelDistance));
  const onTheSameRay = candidates.filter((item) => item.pixelDistance <= nearestToCursor + band);
  // The nearest surface occludes the ones behind it. Ties break on point id so the same click on
  // the same scene always selects the same point.
  return onTheSameRay.reduce((best, item) =>
    item.depth < best.depth || (item.depth === best.depth && item.point.pointId < best.point.pointId)
      ? item
      : best,
  );
}

/**
 * The sentence shown beside a pick, which must never let a bounded sample read as a complete one.
 *
 * A viewer told "3 photographs" for a point that forty photographs observed would be misled by
 * omission, so the retained count and the true track length both appear whenever they differ.
 */
export function observationSentence(result: PickResult): string {
  const { trackLength, observationsRetained } = result.point;
  const held =
    observationsRetained === 1
      ? '1 photograph'
      : `${String(observationsRetained)} photographs`;
  if (trackLength === observationsRetained) {
    return `${held} observed this point.`;
  }
  return (
    `${String(trackLength)} photographs observed this point. ` +
    `${held} of them are retained here, because each photograph keeps a bounded sample of its ` +
    'recorded observations.'
  );
}
