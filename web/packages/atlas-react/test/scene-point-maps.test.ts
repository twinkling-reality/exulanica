import { describe, expect, it } from 'vitest';
import type { PointMap } from '../src/playcanvas/index.js';
import {
  opmPointInScene,
  scenePointMapFootprint,
  scenePointMapViewpoint,
  validateScenePointMapPlacement,
  type PlacedScenePointMap,
} from '../src/playcanvas/index.js';

const MAP = {
  header: {
    bounds: { min: [-1, -1, -2], max: [1, 2, 2] },
    viewpoint: { position: [0, 1.5, 0] },
  },
} as unknown as PointMap;

const placed = (
  matrix: readonly number[],
  scale = 1,
): PlacedScenePointMap => ({
  sceneId: 'scene',
  artifactId: `artifact:${matrix[3]}`,
  islandId: 'island' as never,
  map: MAP,
  sceneFromOpmRowMajor: matrix,
  localUnitsToSceneUnits: scale,
});

describe('posed scene point maps', () => {
  it('applies local scale, proper rotation and translation in the recorded order', () => {
    const value = placed([
      0, 0, 2, 3,
      0, 2, 0, 0,
      -2, 0, 0, 5,
      0, 0, 0, 1,
    ], 2);
    expect(opmPointInScene(value, [1, 2, 3])).toEqual([9, 4, 3]);
    expect(scenePointMapViewpoint(value)).toEqual([3, 3, 5]);
  });

  it('computes one footprint over every transformed member instead of choosing the first map', () => {
    const first = placed([
      1, 0, 0, 0,
      0, 1, 0, 0,
      0, 0, 1, 0,
      0, 0, 0, 1,
    ]);
    const second = placed([
      1, 0, 0, 20,
      0, 1, 0, 0,
      0, 0, 1, -4,
      0, 0, 0, 1,
    ]);
    expect(scenePointMapFootprint([first, second])).toBeGreaterThan(21);
    expect(scenePointMapFootprint([first])).toBeLessThan(3);
  });

  it('refuses a non-affine or non-finite placement before it reaches the engine', () => {
    const broken = placed([
      1, 0, 0, 0,
      0, 1, 0, 0,
      0, 0, 1, 0,
      0, 0, 1, 1,
    ]);
    expect(() => validateScenePointMapPlacement(broken)).toThrow(/affine/);
    expect(() => validateScenePointMapPlacement(placed(new Array(16).fill(Number.NaN))))
      .toThrow(/finite/);
  });

  it('refuses undeclared scale, shear, and reflection instead of drawing a different GPU transform', () => {
    const matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
    expect(() => validateScenePointMapPlacement(placed(matrix, 2))).toThrow(/declared uniform scale/);
    expect(() => validateScenePointMapPlacement(placed(matrix.map((v, i) => i === 1 ? 0.2 : v))))
      .toThrow(/declared uniform scale/);
    expect(() => validateScenePointMapPlacement(placed(matrix.map((v, i) => i === 0 ? -1 : v))))
      .toThrow(/without reflection/);
  });
});
