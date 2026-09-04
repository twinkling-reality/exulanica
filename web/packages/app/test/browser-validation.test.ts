import { describe, expect, it } from 'vitest';

import { summarizeFrameTimes } from '../src/browser-validation.js';

describe('browser reconstruction measurement conventions', () => {
  it('derives the 1 percent low from the 99th percentile frame time', () => {
    const samples = [10, 20, 30, 40, 50];
    const summary = summarizeFrameTimes(samples);

    expect(summary).toEqual({
      frames: 5,
      frameMeanMs: 30,
      frameP50Ms: 30,
      frameP95Ms: 50,
      frameP99Ms: 50,
      framesOver16_7Ms: 4,
      frameOver16_7Fraction: 0.8,
      fpsP1Low: 20,
    });
  });

  it('reports an empty sample as zero instead of fabricating a frame rate', () => {
    expect(summarizeFrameTimes([])).toMatchObject({
      frames: 0,
      frameMeanMs: 0,
      framesOver16_7Ms: 0,
      frameOver16_7Fraction: 0,
      fpsP1Low: 0,
    });
  });
});
