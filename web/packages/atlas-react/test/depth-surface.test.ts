import { describe, expect, it } from 'vitest';
import { DEPTH_JUMP_RATIO, MAX_BRIDGED_CELLS, depthSurfaceIndices, type DepthGridInput, type DepthSurface } from '../src/playcanvas/depth-surface.js';

const W = 4;
const H = 3;
const FOV_Y = 60;
const ASPECT = 0.75;

/** A grid unprojected exactly as the depth stage does it: one sample per cell centre, row-major. */
function grid(
  depthAt: (column: number, row: number) => number | null,
  eye: [number, number, number] = [0, 0, 0],
  width = W,
  height = H,
): DepthGridInput {
  const tanY = Math.tan((FOV_Y * Math.PI) / 360);
  const tanX = tanY * ASPECT;
  const points: number[] = [];
  for (let r = 0; r < height; r += 1) {
    for (let c = 0; c < width; c += 1) {
      const d = depthAt(c, r);
      if (d === null) continue;
      const u = ((c + 0.5) / width) * 2 - 1;
      const v = 1 - ((r + 0.5) / height) * 2;
      points.push(eye[0] + u * d * tanX, eye[1] + v * d * tanY, eye[2] - d);
    }
  }
  return {
    position: Float32Array.from(points),
    header: {
      pointCount: points.length / 3,
      modelImage: { width, height },
      viewpoint: { position: eye, forward: [0, 0, -1], up: [0, 1, 0], fovYDeg: FOV_Y, aspect: ASPECT },
    },
  };
}

const triangles = (built: DepthSurface | null) => (built === null ? null : built.surface.length / 3);
const seams = (built: DepthSurface | null) => (built === null ? null : built.seams.length / 3);

describe('depthSurfaceIndices', () => {
  it('joins every neighbouring cell of a continuous surface into two triangles', () => {
    expect(triangles(depthSurfaceIndices(grid(() => 5)))).toBe((W - 1) * (H - 1) * 2);
    expect(triangles(depthSurfaceIndices(grid(() => 5, [0.3, 1.5, -2])))).toBe((W - 1) * (H - 1) * 2);
  });

  it('never lets a near sample and a far one share surface, keeping them as seams instead', () => {
    const built = depthSurfaceIndices(grid((c, r) => (c === 1 && r === 1 ? 50 : 5)))!;
    const far = 1 + W; // row 1, column 1, in row-major order
    expect(Array.from(built.surface)).not.toContain(far);
    // Six triangles touch an interior cell's sample; all six become seams, and nothing else does.
    expect(triangles(built)).toBe((W - 1) * (H - 1) * 2 - 6);
    expect(seams(built)).toBe(6);
    expect(Array.from(built.seams).filter((index) => index === far)).toHaveLength(6);
  });

  it('keeps a gentle slope and cuts just past the documented ratio', () => {
    const slope = (ratio: number) => grid((c) => 5 * ratio ** c);
    expect(triangles(depthSurfaceIndices(slope(DEPTH_JUMP_RATIO * 0.99)))).toBe((W - 1) * (H - 1) * 2);
    const steep = depthSurfaceIndices(slope(DEPTH_JUMP_RATIO * 1.01));
    expect(triangles(steep)).toBe(0);
    expect(seams(steep)).toBe((W - 1) * (H - 1) * 2);
  });

  it('leaves a hole where the model gave no sample, such as the sky', () => {
    const built = depthSurfaceIndices(grid((c, r) => (r === 0 && c === 0 ? null : 5)))!;
    expect(triangles(built)).toBe((W - 1) * (H - 1) * 2 - 1);
    expect(seams(built)).toBe(0);
  });

  it('bridges a short empty run between two real samples as a seam, and leaves a wide one empty', () => {
    // Row 1, columns 1 and 2 empty: a two-cell band like the one a producer leaves at a silhouette.
    const band = depthSurfaceIndices(grid((c, r) => (r === 1 && (c === 1 || c === 2) ? null : 5)))!;
    const left = 0 + W; // row 1, column 0
    const right = 3 + W - 2; // row 1, column 3, after two absent cells
    expect(Array.from(band.seams)).toContain(left);
    expect(Array.from(band.seams)).toContain(right);
    // One quad along the rows (row 1 to 2, column 0 to 3) and one along each empty column
    // (row 0 to 2): three quads, six seam triangles, covering the hole between them.
    expect(seams(band)).toBe(6);
    // A gap wider than the bridge limit in both directions, like the sky, stays empty.
    const wide = MAX_BRIDGED_CELLS + 4;
    const sky = depthSurfaceIndices(grid((c, r) => (c >= 1 && c <= wide - 2 && r >= 1 && r <= wide - 2 ? null : 5),
      [0, 0, 0], wide, wide))!;
    expect(seams(sky)).toBe(0);
  });

  it('draws points instead for a file that is not a single photograph’s grid', () => {
    const shifted = grid(() => 5);
    shifted.position[0] = shifted.position[0]! + 0.3;
    expect(depthSurfaceIndices(shifted)).toBeNull();
    const turned = grid(() => 5);
    expect(depthSurfaceIndices({ ...turned, header: { ...turned.header,
      viewpoint: { ...turned.header.viewpoint, forward: [1, 0, 0] } } })).toBeNull();
    const doubled = grid(() => 5);
    const twice = new Float32Array(doubled.position.length + 3);
    twice.set(doubled.position);
    twice.set(doubled.position.subarray(0, 3), doubled.position.length);
    expect(depthSurfaceIndices({ position: twice, header: { ...doubled.header,
      pointCount: doubled.header.pointCount + 1 } })).toBeNull();
  });
});
