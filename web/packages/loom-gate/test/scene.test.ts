import { describe, expect, it } from 'vitest';
import {
  SupportSamples,
  TriangleTable,
  classify,
  componentQueryPoints,
  components,
  drawnSupport,
  integrity,
} from '../src/index.js';
import { box, flatSupport, mesh, quad, street } from './fixtures.js';

async function prepared(options: Parameters<typeof street>[0]) {
  const scene = street(options);
  const table = new TriangleTable(scene.meshes);
  const parts = components(table);
  const centroids = table.centroidQueryPoints();
  const lowest = componentQueryPoints(parts.list);
  const points = new Float64Array(centroids.length + lowest.length);
  points.set(centroids);
  points.set(lowest, centroids.length);
  const support = new SupportSamples(points, await flatSupport(points));
  const classification = classify(table, scene.prisms, support);
  return { scene, table, parts, support, classification };
}

describe('classification by position and facing, never by name', () => {
  it('counts ground as walking surface and walls as facade', async () => {
    const { classification, table } = await prepared({});
    // 2 ground triangles; 20 buildings x 4 walls x 2 triangles.
    expect(classification.walkingTriangles).toBe(2);
    expect(classification.facadeTriangles).toBe(160);
    expect(classification.untexturedWalkingTriangles).toBe(2);
    expect(classification.untexturedFacadeTriangles).toBe(160);
    expect(table.count).toBe(162);
  });

  it('counts nothing untextured once every mesh binds a texture with a UV channel', async () => {
    const { classification } = await prepared({ textured: true });
    expect(classification.untexturedWalkingTriangles + classification.untexturedFacadeTriangles).toBe(0);
  });

  it('ignores a floor that faces down under back-face culling', async () => {
    const floor: number[] = [];
    quad(floor, [0, 0, 0], [10, 0, 0], [10, 0, 10], [0, 0, 10]);
    const table = new TriangleTable([mesh('downward', floor)]);
    const points = table.centroidQueryPoints();
    const support = new SupportSamples(points, await flatSupport(points));
    const classification = classify(table, [], support);
    expect(classification.walkingTriangles).toBe(0);
    expect(drawnSupport(table, classification, 5, 5, 2)).toBeNull();
  });
});

describe('the drawn support is the highest walking surface under the eye', () => {
  it('finds the ground and reports a hole as no support', async () => {
    const whole = await prepared({});
    expect(drawnSupport(whole.table, whole.classification, 42, 0, 1.62)).toBe(0);
    const holed = await prepared({ groundHole: true });
    expect(drawnSupport(holed.table, holed.classification, 42, 0, 1.62)).toBeNull();
    expect(drawnSupport(holed.table, holed.classification, 46, 0, 1.62)).toBe(0);
  });
});

describe('integrity', () => {
  it('joins box faces into one closed component', async () => {
    const out: number[] = [];
    box(out, [0, 0, 0], [1, 1, 1]);
    const table = new TriangleTable([mesh('box', out)]);
    const { list } = components(table);
    expect(list).toHaveLength(1);
    expect(list[0]!.closed).toBe(true);
    expect(list[0]!.vertices).toHaveLength(8);
  });

  it('finds nothing wrong with a clean street', async () => {
    const { table, classification, scene, parts, support } = await prepared({});
    const result = integrity(table, classification, scene.prisms, parts, support);
    expect(result.componentsDetachedFromSupport).toBe(0);
    expect(result.trianglesInsideBuildings).toBe(0);
    expect(result.ringEdgesWithoutDrawnFacade).toBe(0);
    expect(result.ringEdges).toBe(80);
  });

  it('reports a decal hanging 0.2 m off its wall as detached', async () => {
    const { table, classification, scene, parts, support } = await prepared({ floatingDecal: true });
    const result = integrity(table, classification, scene.prisms, parts, support);
    expect(result.componentsDetachedFromSupport).toBe(1);
    expect(result.detachedByMesh).toEqual({ decal: 1 });
  });

  it('reports a solid standing inside a building', async () => {
    const { table, classification, scene, parts, support } = await prepared({ treeInsideBuilding: true });
    const result = integrity(table, classification, scene.prisms, parts, support);
    expect(result.componentsDetachedFromSupport).toBe(0);
    // Ten of its twelve triangles: the two in its base lie on the building's own support.
    expect(result.trianglesInsideBuildings).toBe(10);
    expect(result.buildingsWithDrawnGeometryInside).toEqual(['b2n']);
  });

  it('reports a collision wall with nothing drawn on it', async () => {
    const scene = street({});
    scene.prisms.push({ id: 'invisible', ring: [[100, 40], [100, 50], [110, 50], [110, 40], [100, 40]], baseY: 0, topY: 5 });
    const table = new TriangleTable(scene.meshes);
    const parts = components(table);
    const points = new Float64Array([...table.centroidQueryPoints(), ...componentQueryPoints(parts.list)]);
    const support = new SupportSamples(points, await flatSupport(points));
    const classification = classify(table, scene.prisms, support);
    const result = integrity(table, classification, scene.prisms, parts, support);
    expect(result.ringEdgesWithoutDrawnFacade).toBe(4);
  });

  it('keeps a canopy that the trunk passes through attached', async () => {
    const trunk: number[] = [];
    box(trunk, [4.9, 0, 4.9], [5.1, 2.1, 5.1]);
    const canopy: number[] = [];
    box(canopy, [4, 1.8, 4], [6, 3.5, 6]);
    const ground: number[] = [];
    quad(ground, [0, 0, 0], [0, 0, 10], [10, 0, 10], [10, 0, 0]);
    const table = new TriangleTable([mesh('ground', ground), mesh('trunk', trunk), mesh('canopy', canopy)]);
    const parts = components(table);
    const points = new Float64Array([...table.centroidQueryPoints(), ...componentQueryPoints(parts.list)]);
    const support = new SupportSamples(points, await flatSupport(points));
    const classification = classify(table, [], support);
    const result = integrity(table, classification, [], parts, support);
    expect(result.componentsDetachedFromSupport).toBe(0);
  });
});
