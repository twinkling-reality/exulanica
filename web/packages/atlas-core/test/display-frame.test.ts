import { describe, expect, it } from 'vitest';

import {
  DISPLAY_EYE_HEIGHT, colmapCameraSample, composeDisplayFrame, displayCameraTransform,
  identityDisplayFrame, opmCameraSample, sceneDisplayFrame, transformDirection, transformPoint,
  transformedBoxCorners, type CameraPoseSample, type Vec3,
} from '../src/display-frame.js';

/** Cameras circling a subject at the origin of a scene whose "up" is the scene's +X axis. */
function circlingCameras(count: number, radius: number, height: number, up: Vec3 = [1, 0, 0]): CameraPoseSample[] {
  // Build an orthonormal basis (e1, e2) perpendicular to `up`.
  const e1: Vec3 = up[0] === 1 ? [0, 1, 0] : [1, 0, 0];
  const e2: Vec3 = up[0] === 1 ? [0, 0, 1] : [0, 0, 1];
  return Array.from({ length: count }, (_, i) => {
    const angle = (2 * Math.PI * i) / count;
    const position: Vec3 = [
      up[0] * height + e1[0] * radius * Math.cos(angle) + e2[0] * radius * Math.sin(angle),
      up[1] * height + e1[1] * radius * Math.cos(angle) + e2[1] * radius * Math.sin(angle),
      up[2] * height + e1[2] * radius * Math.cos(angle) + e2[2] * radius * Math.sin(angle),
    ];
    const toOrigin: Vec3 = [-position[0], -position[1], -position[2]];
    const l = Math.hypot(...toOrigin);
    const forward: Vec3 = [toOrigin[0] / l, toOrigin[1] / l, toOrigin[2] / l];
    // Image up: the component of scene up perpendicular to the viewing direction.
    const d = up[0] * forward[0] + up[1] * forward[1] + up[2] * forward[2];
    const raw: Vec3 = [up[0] - d * forward[0], up[1] - d * forward[1], up[2] - d * forward[2]];
    const rl = Math.hypot(...raw);
    return { position, forward, up: [raw[0] / rl, raw[1] / rl, raw[2] / rl] };
  });
}

const near = (a: readonly number[], b: readonly number[], tolerance = 1e-6): void => {
  expect(a.length).toBe(b.length);
  a.forEach((value, index) => expect(value).toBeCloseTo(b[index]!, Math.round(-Math.log10(tolerance))));
};

describe('the display frame of a recovered scene', () => {
  const cameras = circlingCameras(12, 4, 3);
  const corners: Vec3[] = [[-1, -1, -1], [1, 1, 1], [-1, 1, -1], [1, -1, 1], [1, 1, -1], [-1, -1, 1]];

  it('stands the scene upright on the mean camera up and centres the subject on the vertical axis', () => {
    const frame = sceneDisplayFrame(cameras, corners);
    expect(frame.upMethod).toBe('camera-up-mean');
    expect(frame.upAgreement).toBeGreaterThan(0.5);
    expect(frame.metric).toBe(false);
    near(transformDirection(frame, [1, 0, 0]), [0, 1, 0]);
    const subject = transformPoint(frame, [0, 0, 0]);
    expect(Math.hypot(subject[0], subject[2])).toBeLessThan(1e-6);
    // The cameras keep their circle: same distance from the axis, same height as each other.
    const placed = cameras.map((camera) => transformPoint(frame, camera.position));
    const radii = placed.map((p) => Math.hypot(p[0], p[2]));
    expect(Math.max(...radii) - Math.min(...radii)).toBeLessThan(1e-6);
    expect(Math.max(...placed.map((p) => p[1])) - Math.min(...placed.map((p) => p[1]))).toBeLessThan(1e-6);
  });

  it('puts the median camera at eye height above the low quantile of the displayed bounds', () => {
    const frame = sceneDisplayFrame(cameras, corners);
    const placed = cameras.map((camera) => transformPoint(frame, camera.position));
    expect(placed[0]![1]).toBeCloseTo(DISPLAY_EYE_HEIGHT, 6);
    // Ground: the lowest bound corner along scene +X is x = -1, which lands at display y = 0.
    const lowest = Math.min(...transformedBoxCorners({ min: [-1, -1, -1], max: [1, 1, 1] }, frame.displayFromSceneRowMajor).map((p) => p[1]));
    expect(lowest).toBeCloseTo(0, 6);
    // Cameras were 3 above the origin and 4 above the ground plane at x = -1: scale is 1.6 / 4.
    expect(frame.scale).toBeCloseTo(DISPLAY_EYE_HEIGHT / 4, 6);
  });

  it('is a proper similarity, so composed placements and cameras still pass the renderer checks', () => {
    const frame = sceneDisplayFrame(cameras, corners);
    const m = frame.displayFromSceneRowMajor;
    const columns = [[m[0]!, m[4]!, m[8]!], [m[1]!, m[5]!, m[9]!], [m[2]!, m[6]!, m[10]!]];
    for (const column of columns) expect(Math.hypot(...column)).toBeCloseTo(frame.scale, 9);
    expect(columns[0]![0]! * columns[1]![0]! + columns[0]![1]! * columns[1]![1]! + columns[0]![2]! * columns[1]![2]!).toBeCloseTo(0, 9);
    const sceneFromOpm = [2, 0, 0, 1, 0, 2, 0, 2, 0, 0, 2, 3, 0, 0, 0, 1];
    const composed = composeDisplayFrame(frame, sceneFromOpm);
    expect(Math.hypot(composed[0]!, composed[4]!, composed[8]!)).toBeCloseTo(2 * frame.scale, 9);
    near(composed.slice(12), [0, 0, 0, 1]);
    const camera = displayCameraTransform(frame, [1, 0, 0, 5, 0, 1, 0, 6, 0, 0, 1, 7, 0, 0, 0, 1]);
    expect(Math.hypot(camera[0]!, camera[4]!, camera[8]!)).toBeCloseTo(1, 9);
    near([camera[3]!, camera[7]!, camera[11]!], transformPoint(frame, [5, 6, 7]));
  });

  it('falls back to the negated mean forward for a top-down survey and to scene axes when nothing agrees', () => {
    // Every camera looks straight along -X with image ups spread evenly around the ray.
    const topDown: CameraPoseSample[] = Array.from({ length: 8 }, (_, i) => {
      const a = (2 * Math.PI * i) / 8;
      return { position: [5, Math.cos(a), Math.sin(a)], forward: [-1, 0, 0], up: [0, -Math.sin(a), Math.cos(a)] };
    });
    const frame = sceneDisplayFrame(topDown, []);
    expect(frame.upMethod).toBe('camera-forward-mean');
    near(transformDirection(frame, [1, 0, 0]), [0, 1, 0]);
    const disagreeing: CameraPoseSample[] = [
      { position: [1, 0, 0], forward: [1, 0, 0], up: [0, 1, 0] },
      { position: [-1, 0, 0], forward: [-1, 0, 0], up: [0, -1, 0] },
    ];
    expect(sceneDisplayFrame(disagreeing, []).upMethod).toBe('scene-axes');
    expect(sceneDisplayFrame([], corners)).toEqual(identityDisplayFrame());
  });

  it('reads camera samples in the COLMAP and OPM conventions', () => {
    const identity = [1, 0, 0, 3, 0, 1, 0, 4, 0, 0, 1, 5, 0, 0, 0, 1];
    expect(colmapCameraSample(identity)).toEqual({ position: [3, 4, 5], forward: [0, 0, 1], up: [-0, -1, -0] });
    expect(opmCameraSample(identity)).toEqual({ position: [3, 4, 5], forward: [-0, -0, -1], up: [0, 1, 0] });
    expect(opmCameraSample(identity, [0, 1.5, 0]).position).toEqual([3, 5.5, 5]);
  });
});
