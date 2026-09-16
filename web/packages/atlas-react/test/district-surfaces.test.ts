import { describe, expect, it } from 'vitest';
import { buildingRayDistance, surfaceTriangles } from '../src/playcanvas/district-surfaces.js';
import type { OwnedDistrictBuilding } from '@exulanica/atlas-core';

const polygon = [[[0,0],[1000,0],[1000,1000],[0,1000],[0,0]], [[300,300],[700,300],[700,700],[300,700],[300,300]]] as const;
const building = { id:'doitt_id:1', height_cm:1000, polygons:[polygon] } as unknown as OwnedDistrictBuilding;
const area = (triangles: ReturnType<typeof surfaceTriangles>) => triangles.reduce((sum, [a,b,c]) => sum + Math.abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/2, 0);
describe('source-preserving district surfaces', () => {
  it('preserves courtyard area regardless of winding', () => {
    expect(area(surfaceTriangles(polygon))).toBe(840000);
    expect(area(surfaceTriangles(polygon.map(r => [...r].reverse())))).toBe(840000);
    expect(buildingRayDistance(building, [5,20,5], [0,-1,0])).toBeNull();
    expect(buildingRayDistance(building, [1,20,1], [0,-1,0])).toBe(10);
  });
  it('does not fill a concave missing corner', () => {
    const concave = [[[0,0],[1000,0],[1000,300],[300,300],[300,1000],[0,1000],[0,0]]] as const;
    expect(area(surfaceTriangles(concave))).toBe(510000);
    // Ray enters bbox at x=10 but does not hit the actual wall until x=3.
    expect(buildingRayDistance({...building,polygons:[concave]}, [12,2,5], [-1,0,0])).toBe(9);
  });
  it('hits courtyard walls and rejects rays above the mass', () => {
    expect(buildingRayDistance(building,[5,2,5],[1,0,0])).toBe(2);
    expect(buildingRayDistance(building,[-1,12,5],[1,0,0])).toBeNull();
  });
});
