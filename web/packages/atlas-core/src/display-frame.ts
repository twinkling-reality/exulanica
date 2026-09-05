/**
 * How a recovered reconstruction frame is shown inside its region: upright, centred, and at
 * walking scale. Presentation only, and the module says so in its output.
 *
 * A scene's authoritative frame is the selected COLMAP world. Its axes are whatever the mapper's
 * initial pair happened to be, its origin is arbitrary, and its unit is scale-ambiguous. Drawn as-is
 * inside a region, the first retained real collection (MEASURED 2026-09-05, a bowl photographed
 * from 40 positions) arrived tilted, off the region centre, and roughly ten times larger than the
 * eye-height world around it, so the arrival frame showed empty landscape.
 *
 * The display frame is a similarity transform derived from the recovered cameras alone, the same
 * way a region's placement on the Map is a layout decision: it carries no physical claim and it
 * changes no receipt. Three rules, each one recorded in the result so the status line can say it:
 *
 * - **Up** is the mean of the recovered cameras' up vectors. Handheld photographs are taken
 *   roughly upright, and circling a subject cancels the horizontal parts. When the cameras looked
 *   straight down (a top-down survey), their up vectors cancel instead, and the negated mean
 *   forward direction is used. When neither agrees, the scene axes stand.
 * - **Centre** is the point the camera rays converge on, in least squares, placed on the region's
 *   vertical axis. A circling capture puts its subject there.
 * - **Scale** puts the median recovered camera at eye height above the estimated ground, the
 *   low quantile of the displayed geometry's bounds. Standing where the photographer stood then
 *   shows what the photograph shows, which is what makes the recovered cameras a walking route.
 *
 * None of this is metric. The scale is an exhibit scale and the result says `metric: false`.
 */

export type Vec3 = readonly [number, number, number];

export interface CameraPoseSample {
  /** Camera centre in scene units. */
  readonly position: Vec3;
  /** Unit viewing direction in scene axes. */
  readonly forward: Vec3;
  /** Unit up direction of the image in scene axes. */
  readonly up: Vec3;
}

export type UpMethod = 'camera-up-mean' | 'camera-forward-mean' | 'scene-axes';

export interface SceneDisplayFrame {
  /** Row-major 4x4 similarity: linear part is `scale` times a proper rotation. */
  readonly displayFromSceneRowMajor: readonly number[];
  readonly scale: number;
  readonly upMethod: UpMethod;
  /** Length of the mean camera up vector, 1 when every camera agreed exactly. */
  readonly upAgreement: number;
  readonly cameraCount: number;
  readonly eyeHeight: number;
  readonly metric: false;
}

/** The Atlas walking eye height the recovered cameras are placed at. */
export const DISPLAY_EYE_HEIGHT = 1.6;

const MIN_AGREEMENT = 0.5;
const MIN_SCALE = 0.01;
const MAX_SCALE = 100;
const GROUND_QUANTILE = 0.05;

export function identityDisplayFrame(): SceneDisplayFrame {
  return Object.freeze({
    displayFromSceneRowMajor: Object.freeze([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]),
    scale: 1,
    upMethod: 'scene-axes',
    upAgreement: 0,
    cameraCount: 0,
    eyeHeight: DISPLAY_EYE_HEIGHT,
    metric: false,
  });
}

/**
 * Derive the display frame from recovered camera poses and the displayed geometry's bound corners.
 *
 * Deterministic: the same cameras and corners produce the same frame on every load. With no
 * cameras the scene axes stand and the frame is the identity.
 */
export function sceneDisplayFrame(
  cameras: readonly CameraPoseSample[],
  boundCorners: readonly Vec3[],
  eyeHeight: number = DISPLAY_EYE_HEIGHT,
): SceneDisplayFrame {
  if (cameras.length === 0 || !cameras.every(finiteSample)) return identityDisplayFrame();

  const meanUp = mean(cameras.map((camera) => unit(camera.up)));
  const meanForward = mean(cameras.map((camera) => unit(camera.forward)));
  let up: Vec3;
  let upMethod: UpMethod;
  let upAgreement: number;
  if (length(meanUp) >= MIN_AGREEMENT) {
    up = unit(meanUp);
    upMethod = 'camera-up-mean';
    upAgreement = length(meanUp);
  } else if (length(meanForward) >= MIN_AGREEMENT) {
    up = unit(scaleVec(meanForward, -1));
    upMethod = 'camera-forward-mean';
    upAgreement = length(meanForward);
  } else {
    up = [0, 1, 0];
    upMethod = 'scene-axes';
    upAgreement = length(meanUp);
  }
  const rotation = rotationTakingTo(up, [0, 1, 0]);
  const rotate = (v: Vec3): Vec3 => applyRotation(rotation, v);

  const focus = rotate(convergence(cameras));
  const rotatedCameras = cameras.map((camera) => rotate(camera.position));
  const corners = boundCorners.filter(finiteVec).map(rotate);
  const heights = (corners.length > 0 ? corners : rotatedCameras).map((p) => p[1]);
  const ground = Math.min(quantile(heights, GROUND_QUANTILE), focus[1]);
  const cameraHeights = rotatedCameras.map((p) => p[1] - ground).filter((h) => h > 1e-9);
  const median = cameraHeights.length > 0 ? quantile(cameraHeights, 0.5) : 0;
  const scale = median > 0 ? Math.min(MAX_SCALE, Math.max(MIN_SCALE, eyeHeight / median)) : 1;

  const translation: Vec3 = [-scale * focus[0], -scale * ground, -scale * focus[2]];
  const r = rotation;
  return Object.freeze({
    displayFromSceneRowMajor: Object.freeze([
      scale * r[0]!, scale * r[1]!, scale * r[2]!, translation[0],
      scale * r[3]!, scale * r[4]!, scale * r[5]!, translation[1],
      scale * r[6]!, scale * r[7]!, scale * r[8]!, translation[2],
      0, 0, 0, 1,
    ]),
    scale,
    upMethod,
    upAgreement,
    cameraCount: cameras.length,
    eyeHeight,
    metric: false,
  });
}

/** `display_from_scene * scene_from_x` for a placed map or trained asset; both stay similarities. */
export function composeDisplayFrame(frame: SceneDisplayFrame, sceneFromX: readonly number[]): number[] {
  return multiply4(frame.displayFromSceneRowMajor, sceneFromX);
}

/**
 * A recovered camera transform under the display frame.
 *
 * Camera axes stay unit length: the display scale moves the camera centre and leaves its
 * orientation, so calibrated projection through the camera is unchanged.
 */
export function displayCameraTransform(frame: SceneDisplayFrame, sceneFromCamera: readonly number[]): number[] {
  const d = frame.displayFromSceneRowMajor;
  const s = frame.scale;
  const rotation = [d[0]! / s, d[1]! / s, d[2]! / s, d[4]! / s, d[5]! / s, d[6]! / s, d[8]! / s, d[9]! / s, d[10]! / s];
  const c = sceneFromCamera;
  const linear = multiply3(rotation, [c[0]!, c[1]!, c[2]!, c[4]!, c[5]!, c[6]!, c[8]!, c[9]!, c[10]!]);
  const centre = transformPoint(frame, [c[3]!, c[7]!, c[11]!]);
  return [
    linear[0]!, linear[1]!, linear[2]!, centre[0],
    linear[3]!, linear[4]!, linear[5]!, centre[1],
    linear[6]!, linear[7]!, linear[8]!, centre[2],
    0, 0, 0, 1,
  ];
}

export function transformPoint(frame: SceneDisplayFrame, p: Vec3): Vec3 {
  const m = frame.displayFromSceneRowMajor;
  return [
    m[0]! * p[0] + m[1]! * p[1] + m[2]! * p[2] + m[3]!,
    m[4]! * p[0] + m[5]! * p[1] + m[6]! * p[2] + m[7]!,
    m[8]! * p[0] + m[9]! * p[1] + m[10]! * p[2] + m[11]!,
  ];
}

/** Direction under the frame's rotation only, unit length preserved. */
export function transformDirection(frame: SceneDisplayFrame, v: Vec3): Vec3 {
  const m = frame.displayFromSceneRowMajor;
  const s = frame.scale;
  return unit([
    (m[0]! * v[0] + m[1]! * v[1] + m[2]! * v[2]) / s,
    (m[4]! * v[0] + m[5]! * v[1] + m[6]! * v[2]) / s,
    (m[8]! * v[0] + m[9]! * v[1] + m[10]! * v[2]) / s,
  ]);
}

/** Camera pose read from a row-major `scene_from_camera` matrix in COLMAP convention. */
export function colmapCameraSample(sceneFromCamera: readonly number[]): CameraPoseSample {
  const m = sceneFromCamera;
  // COLMAP cameras look along +Z with +Y down; the image's up is therefore -Y.
  return {
    position: [m[3]!, m[7]!, m[11]!],
    forward: unit([m[2]!, m[6]!, m[10]!]),
    up: unit([-m[1]!, -m[5]!, -m[9]!]),
  };
}

/** Camera pose read from a row-major `scene_from_opm` matrix; OPM cameras look along -Z, +Y up. */
export function opmCameraSample(sceneFromOpm: readonly number[]): CameraPoseSample {
  const m = sceneFromOpm;
  return {
    position: [m[3]!, m[7]!, m[11]!],
    forward: unit([-m[2]!, -m[6]!, -m[10]!]),
    up: unit([m[1]!, m[5]!, m[9]!]),
  };
}

/** The eight corners of an axis-aligned box after an affine row-major transform. */
export function transformedBoxCorners(
  bounds: { readonly min: readonly number[]; readonly max: readonly number[] },
  rowMajor: readonly number[],
): Vec3[] {
  const corners: Vec3[] = [];
  for (const x of [bounds.min[0]!, bounds.max[0]!]) {
    for (const y of [bounds.min[1]!, bounds.max[1]!]) {
      for (const z of [bounds.min[2]!, bounds.max[2]!]) {
        corners.push([
          rowMajor[0]! * x + rowMajor[1]! * y + rowMajor[2]! * z + rowMajor[3]!,
          rowMajor[4]! * x + rowMajor[5]! * y + rowMajor[6]! * z + rowMajor[7]!,
          rowMajor[8]! * x + rowMajor[9]! * y + rowMajor[10]! * z + rowMajor[11]!,
        ]);
      }
    }
  }
  return corners;
}

// -- vector and matrix helpers -----------------------------------------------------------------

function finiteVec(v: Vec3): boolean {
  return v.length === 3 && v.every(Number.isFinite);
}

function finiteSample(sample: CameraPoseSample): boolean {
  return finiteVec(sample.position) && finiteVec(sample.forward) && finiteVec(sample.up)
    && length(sample.forward) > 1e-9 && length(sample.up) > 1e-9;
}

function length(v: Vec3): number {
  return Math.hypot(v[0], v[1], v[2]);
}

function unit(v: Vec3): Vec3 {
  const l = length(v);
  return l < 1e-12 ? [0, 0, 0] : [v[0] / l, v[1] / l, v[2] / l];
}

function scaleVec(v: Vec3, k: number): Vec3 {
  return [v[0] * k, v[1] * k, v[2] * k];
}

function mean(values: readonly Vec3[]): Vec3 {
  const sum = values.reduce<[number, number, number]>((acc, v) => [acc[0] + v[0], acc[1] + v[1], acc[2] + v[2]], [0, 0, 0]);
  const n = Math.max(values.length, 1);
  return [sum[0] / n, sum[1] / n, sum[2] / n];
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

function dot(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

/** Row-major 3x3 rotation taking unit `from` onto unit `to` by the smallest angle. */
function rotationTakingTo(from: Vec3, to: Vec3): readonly number[] {
  const axis = cross(from, to);
  const sine = length(axis);
  const cosine = dot(from, to);
  if (sine < 1e-9) {
    if (cosine > 0) return [1, 0, 0, 0, 1, 0, 0, 0, 1];
    // Opposite: half turn about any axis perpendicular to `to`; X is perpendicular to +Y.
    return [1, 0, 0, 0, -1, 0, 0, 0, -1];
  }
  const [kx, ky, kz] = unit(axis);
  const c = cosine;
  const s = sine;
  const t = 1 - c;
  return [
    t * kx * kx + c, t * kx * ky - s * kz, t * kx * kz + s * ky,
    t * kx * ky + s * kz, t * ky * ky + c, t * ky * kz - s * kx,
    t * kx * kz - s * ky, t * ky * kz + s * kx, t * kz * kz + c,
  ];
}

function applyRotation(r: readonly number[], v: Vec3): Vec3 {
  return [
    r[0]! * v[0] + r[1]! * v[1] + r[2]! * v[2],
    r[3]! * v[0] + r[4]! * v[1] + r[5]! * v[2],
    r[6]! * v[0] + r[7]! * v[1] + r[8]! * v[2],
  ];
}

/** Least-squares point nearest every camera ray; the camera centroid when rays are parallel. */
function convergence(cameras: readonly CameraPoseSample[]): Vec3 {
  const a = [0, 0, 0, 0, 0, 0, 0, 0, 0];
  const b = [0, 0, 0];
  for (const camera of cameras) {
    const f = unit(camera.forward);
    const p = camera.position;
    // Projector onto the plane perpendicular to the ray: I - f f^T.
    const proj = [
      1 - f[0] * f[0], -f[0] * f[1], -f[0] * f[2],
      -f[1] * f[0], 1 - f[1] * f[1], -f[1] * f[2],
      -f[2] * f[0], -f[2] * f[1], 1 - f[2] * f[2],
    ];
    for (let i = 0; i < 9; i += 1) a[i]! += proj[i]!;
    const projected = applyRotation(proj, p);
    for (let i = 0; i < 3; i += 1) b[i]! += projected[i]!;
  }
  const solved = solve3(a, b);
  const centroid = mean(cameras.map((camera) => camera.position));
  if (solved === null) return centroid;
  // A convergence point behind most cameras is a diverging capture, not a subject; centre on the cameras.
  const ahead = cameras.filter((camera) => dot(unit(camera.forward), [
    solved[0] - camera.position[0], solved[1] - camera.position[1], solved[2] - camera.position[2],
  ]) > 0).length;
  return ahead * 2 >= cameras.length ? solved : centroid;
}

function solve3(a: readonly number[], b: readonly number[]): Vec3 | null {
  const det = a[0]! * (a[4]! * a[8]! - a[5]! * a[7]!)
    - a[1]! * (a[3]! * a[8]! - a[5]! * a[6]!)
    + a[2]! * (a[3]! * a[7]! - a[4]! * a[6]!);
  if (!Number.isFinite(det) || Math.abs(det) < 1e-9) return null;
  const inv = [
    (a[4]! * a[8]! - a[5]! * a[7]!) / det, (a[2]! * a[7]! - a[1]! * a[8]!) / det, (a[1]! * a[5]! - a[2]! * a[4]!) / det,
    (a[5]! * a[6]! - a[3]! * a[8]!) / det, (a[0]! * a[8]! - a[2]! * a[6]!) / det, (a[2]! * a[3]! - a[0]! * a[5]!) / det,
    (a[3]! * a[7]! - a[4]! * a[6]!) / det, (a[1]! * a[6]! - a[0]! * a[7]!) / det, (a[0]! * a[4]! - a[1]! * a[3]!) / det,
  ];
  return applyRotation(inv, [b[0]!, b[1]!, b[2]!]);
}

function quantile(values: readonly number[], q: number): number {
  const sorted = [...values].sort((x, y) => x - y);
  if (sorted.length === 0) return 0;
  const index = Math.min(sorted.length - 1, Math.max(0, Math.floor(q * (sorted.length - 1))));
  return sorted[index]!;
}

function multiply3(a: readonly number[], b: readonly number[]): number[] {
  const out = new Array<number>(9).fill(0);
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 3; col += 1) {
      out[row * 3 + col] = a[row * 3]! * b[col]! + a[row * 3 + 1]! * b[3 + col]! + a[row * 3 + 2]! * b[6 + col]!;
    }
  }
  return out;
}

function multiply4(a: readonly number[], b: readonly number[]): number[] {
  const out = new Array<number>(16).fill(0);
  for (let row = 0; row < 4; row += 1) {
    for (let col = 0; col < 4; col += 1) {
      let sum = 0;
      for (let k = 0; k < 4; k += 1) sum += a[row * 4 + k]! * b[k * 4 + col]!;
      out[row * 4 + col] = sum;
    }
  }
  return out;
}
