import { describe, expect, it } from 'vitest';
import { sampleMotionPath } from '../src/playcanvas/society-presentation.js';

describe('persisted society path display', () => {
  it('follows a corner instead of cutting through the enclosed building', () => {
    const route = [[0,0],[0,10],[20,10]] as const;
    expect(sampleMotionPath(route, .5)).toEqual([5,10]);
    expect(sampleMotionPath(route, 1/6)).toEqual([0,5]);
  });
  it('handles stationary, repeated and bounded endpoints', () => {
    expect(sampleMotionPath([[3,4]], .5)).toEqual([3,4]);
    expect(sampleMotionPath([[3,4],[3,4],[5,4]], .5)).toEqual([4,4]);
    expect(sampleMotionPath([[0,0],[5,0]], 2)).toEqual([5,0]);
    expect(() => sampleMotionPath([],0)).toThrow();
  });
});
