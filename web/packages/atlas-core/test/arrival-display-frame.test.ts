import { describe, expect, it } from 'vitest';
import { sceneDisplayFrame } from '../src/display-frame.js';

describe('the v1 served arrival display frame', () => {
  it('keeps the server and browser projection of a tilted reconstruction aligned', () => {
    const frame = sceneDisplayFrame([
      { position: [3, 2, 4], forward: [-0.5, -0.2, -0.8], up: [0.2, 0.9, -0.1] },
      { position: [-2, 3, 1], forward: [0.6, -0.1, -0.7], up: [0.1, 0.95, -0.2] },
    ], [[-3, -2, -4], [3, 2, 4]]);
    expect(frame.scale).toBeCloseTo(0.4443001948457013, 12);
    expect(frame.displayFromSceneRowMajor.slice(3, 12).filter((_, index) => index % 4 === 0))
      .toEqual([0.15719881199339408, 0.8, 0.3114484346478816]);
    expect(frame.displayFromSceneRowMajor[0]).toBeCloseTo(0.43857550589359445, 12);
    expect(frame.displayFromSceneRowMajor[1]).toBeCloseTo(-0.0708696951040886, 12);
  });
});
