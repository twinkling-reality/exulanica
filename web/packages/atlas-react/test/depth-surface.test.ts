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

  it('fills a ragged band of empty cells with seams between the real samples on either side', () => {
    // A band two to three cells wide whose edges move from row to row, like the one a depth producer
    // leaves round a person. Every empty cell's centre must fall inside some seam triangle.
    const width = 9;
    const height = 5;
    const empty = (c: number, r: number) => (r === 1 && (c === 3 || c === 4))
      || (r === 2 && (c === 4 || c === 5 || c === 6)) || (r === 3 && (c === 3 || c === 4 || c === 5));
    const built = depthSurfaceIndices(grid((c, r) => (empty(c, r) ? null : 5), [0, 0, 0], width, height))!;
    const order: [number, number][] = [];
    for (let r = 0; r < height; r += 1) for (let c = 0; c < width; c += 1) if (!empty(c, r)) order.push([c, r]);
    const inside = (p: [number, number], a: [number, number], b: [number, number], c: [number, number]) => {
      const side = (u: [number, number], v: [number, number]) => (v[0] - u[0]) * (p[1] - u[1]) - (v[1] - u[1]) * (p[0] - u[0]);
      const s1 = side(a, b); const s2 = side(b, c); const s3 = side(c, a);
      return (s1 >= 0 && s2 >= 0 && s3 >= 0) || (s1 <= 0 && s2 <= 0 && s3 <= 0);
    };
    const covered = (p: [number, number]) => {
      for (let k = 0; k < built.seams.length; k += 3) {
        if (inside(p, order[built.seams[k]!]!, order[built.seams[k + 1]!]!, order[built.seams[k + 2]!]!)) return true;
      }
      return false;
    };
    for (let r = 0; r < height; r += 1) {
      for (let c = 0; c < width; c += 1) if (empty(c, r)) expect(covered([c, r]), `cell ${c},${r}`).toBe(true);
    }
  });

  it('leaves a gap wider than the bridge limit empty, as the sky is', () => {
    const wide = MAX_BRIDGED_CELLS + 4;
    const sky = depthSurfaceIndices(grid((c, r) => (c >= 1 && c <= wide - 2 && r >= 1 && r <= wide - 2 ? null : 5),
      [0, 0, 0], wide, wide))!;
    const order: number[] = [];
    for (let r = 0; r < wide; r += 1) for (let c = 0; c < wide; c += 1) {
      if (!(c >= 1 && c <= wide - 2 && r >= 1 && r <= wide - 2)) order.push(c);
    }
    for (let k = 0; k < sky.seams.length; k += 3) {
      const columns = [sky.seams[k]!, sky.seams[k + 1]!, sky.seams[k + 2]!].map((index) => order[index]!);
      expect(Math.max(...columns) - Math.min(...columns)).toBeLessThanOrEqual(MAX_BRIDGED_CELLS + 1);
    }
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
