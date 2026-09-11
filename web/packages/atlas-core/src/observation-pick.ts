/**
 * Click-to-evidence: turn a click in the reconstruction inspector into a question about one point.
 *
 * Roadmap Phase 10. A visitor selects a surface and asks what it is made of; the answer is the set
 * of photographs whose cameras actually observed that piece of the world. This module is the part
 * of that gesture that belongs in the browser: where a click lands in the source photograph's own
 * pixels, and the sentence the answer is shown with.
 *
 * **Where the pick went.** Selecting the recorded point under the cursor used to happen here, by
 * projecting every sparse point of the scene through the recovered camera. That needed the whole
 * observation graph in the browser, and MEASURED 2026-09-11 the volcanic scene's graph is
 * 1,015,016,928 bytes of JSON, which V8 cannot hold as one string. The pick now runs on the
 * server, term for term, in `exulanica/graph/observations.py`, and its geometry cases moved with
 * it to `tests/test_observation_pick.py`. One implementation, where the points are.
 *
 * **Why this lives in the inspector and not in traverse mode.** Traverse holds Pointer Lock, which
 * freezes `clientX`/`clientY` (`atlas-react/src/playcanvas/controls.ts`), and the focus solver's
 * header states that it must never take a screen-space input: the only direction it reads is the
 * camera forward vector. The inspector already exits pointer lock, already suspends walking input,
 * and already stands on a calibrated recovered camera, so a click there has real coordinates and a
 * real projection to invert.
 *
 * **What the answer is not.** The point returned is the nearest recorded observation to the cursor,
 * not the surface under it. The two coincide when the reconstruction is dense and diverge on a plain
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
  /** How many of those the served answer actually holds. Never larger than `trackLength`. */
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

export interface PickResult {
  readonly point: SparseObservedPoint;
  /** Distance in source-image pixels between the cursor and the point's projection. */
  readonly pixelDistance: number;
  /** Distance along the camera's forward axis, in scene units. Never metres. */
  readonly depth: number;
  /**
   * `pinhole-approximation` means the original camera had a distortion model the projection does
   * not apply. The pick inherits that label rather than discarding it, so a caller can say so.
   */
  readonly projection: 'pinhole' | 'pinhole-approximation';
}

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
