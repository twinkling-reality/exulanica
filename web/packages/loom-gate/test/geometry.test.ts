import { describe, expect, it } from 'vitest';
import {
  closestPointOnTriangle,
  heightOnTriangle,
  pointInRing,
  pointTriangleDistance,
  ringEdgeDistance,
  segmentIntersectsTriangle,
  segmentSegmentDistance,
  segmentTriangleDistance,
  triangleNormal,
} from '../src/index.js';

const square = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]] as const;

describe('planar predicates agree with the product collision rule', () => {
  it('contains points inside a ring and not outside', () => {
    expect(pointInRing(5, 5, square)).toBe(true);
    expect(pointInRing(-1, 5, square)).toBe(false);
    expect(pointInRing(11, 5, square)).toBe(false);
  });

  it('measures distance to the nearest ring edge', () => {
    expect(ringEdgeDistance(5, 5, square)).toBeCloseTo(5);
    expect(ringEdgeDistance(-3, 5, square)).toBeCloseTo(3);
    expect(ringEdgeDistance(13, 14, square)).toBeCloseTo(5);
  });
});

describe('spatial distances', () => {
  const a = [0, 0, 0] as const;
  const b = [10, 0, 0] as const;
  const c = [0, 0, 10] as const;

  it('finds the closest point on each region of a triangle', () => {
    expect(closestPointOnTriangle([2, 5, 2], a, b, c)).toEqual([2, 0, 2]);
    expect(closestPointOnTriangle([-1, 0, -1], a, b, c)).toEqual(a);
    expect(pointTriangleDistance([2, 5, 2], a, b, c)).toBeCloseTo(5);
    expect(pointTriangleDistance([20, 0, 0], a, b, c)).toBeCloseTo(10);
  });

  it('returns zero for a segment through a triangle and the gap otherwise', () => {
    expect(segmentIntersectsTriangle([1, -1, 1], [1, 1, 1], a, b, c)).toBe(true);
    expect(segmentTriangleDistance([1, -1, 1], [1, 1, 1], a, b, c)).toBe(0);
    expect(segmentTriangleDistance([1, 0.5, 1], [1, 2, 1], a, b, c)).toBeCloseTo(0.5);
    expect(segmentTriangleDistance([12, 0.3, -1], [12, 0.3, 1], a, b, c)).toBeCloseTo(Math.hypot(2, 0.3));
  });

  it('measures segment to segment distance', () => {
    expect(segmentSegmentDistance([0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0])).toBeCloseTo(1);
    expect(segmentSegmentDistance([0, 0, 0], [1, 0, 0], [0.5, -1, 1], [0.5, 1, 1])).toBeCloseTo(1);
    expect(segmentSegmentDistance([0, 0, 0], [0, 0, 0], [3, 4, 0], [3, 4, 0])).toBeCloseTo(5);
  });

  it('gives the winding normal and refuses a degenerate triangle', () => {
    expect(triangleNormal([0, 0, 0], [0, 0, 1], [1, 0, 1])).toEqual([0, 1, 0]);
    expect(triangleNormal([0, 0, 0], [1, 0, 0], [2, 0, 0])).toBeNull();
  });

  it('reads a height inside a triangle projection and nothing outside it', () => {
    const tilted = [[0, 0, 0], [10, 1, 0], [0, 2, 10]] as const;
    expect(heightOnTriangle(2, 2, ...tilted)).toBeCloseTo(0.6);
    expect(heightOnTriangle(-1, 2, ...tilted)).toBeNull();
  });
});
