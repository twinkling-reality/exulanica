// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import type { DistrictInterpretation, OwnedDistrict } from '@exulanica/atlas-core';
import {
  OWNED_DISTRICT_GROUND_UNAVAILABLE,
  OWNED_DISTRICT_SURFACE_UNAVAILABLE,
  OwnedDistrictRuntime,
} from '../src/playcanvas/owned-district-runtime.js';

/*
 * What the owned district draws where no record says what is there.
 *
 * The district used to pick one of seven invented materials by `doitt_id % 7`, grid every facade
 * with windows, band it with cornices, add rooftop boxes to even-numbered tall buildings, plant a
 * tree and a lamp at every sidewalk centroid, lay an asphalt quad under all of it, and float a cone
 * over anything marked fictional. None of that is in any source record. These tests hold the
 * replacement: one unavailable treatment for every building, a datum grid for the ground, and
 * nothing else.
 */

const square = (x: number, z: number, half: number) =>
  [[[x - half, z - half], [x + half, z - half], [x + half, z + half], [x - half, z + half], [x - half, z - half]]] as const;

function district(): OwnedDistrict {
  return {
    profile: 'exulanica.owned-district/v1',
    district_id: 'test',
    name: 'Test',
    seed: 1,
    bounds_cm: [-5000, -5000, 5000, 5000],
    materials: [
      { name: 'stone', base: '#778899', roughness_milli: 800, metalness_milli: 0 },
      { name: 'brick', base: '#8b5544', roughness_milli: 820, metalness_milli: 10 },
    ],
    buildings: [
      {
        id: 'doitt_id:1', bin: null, name: 'Named landmark', construction_year: null,
        height_cm: 4000, material: 0, render_batch_id: 0,
        bbox_cm: [-2000, -2000, -1000, -1000], polygons: [square(-1500, -1500, 500)],
      },
      {
        id: 'doitt_id:2', bin: null, name: null, construction_year: null,
        height_cm: 1200, material: 1, render_batch_id: 9,
        bbox_cm: [1000, 1000, 2000, 2000], polygons: [square(1500, 1500, 500)],
      },
    ],
    sidewalks: [{
      id: 'sidewalk_geometry_sha256:a', status: null,
      bbox_cm: [-400, -400, 400, 400], polygons: [square(0, 0, 400)],
    }],
    source_records: [],
  } as unknown as OwnedDistrict;
}

function setup(interpretation?: DistrictInterpretation) {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  const runtime = new OwnedDistrictRuntime(device, app.root, district(), 100, interpretation);
  return { runtime, app };
}

const drawn = (root: pc.Entity) => root.children.map((child) => child.name);

const REMOVED = [
  'owned-district-visible-support',
  'owned-building-roofs',
  'owned-building-memory-windows',
  'owned-building-cornices',
  'owned-building-architectural-details',
  'owned-street-tree-trunks',
  'owned-street-tree-canopies',
  'owned-street-lamps',
];

describe('owned district unavailable surfaces', () => {
  it('draws the recorded extent, the datum and the sidewalks, and nothing invented', () => {
    const { runtime, app } = setup();
    const names = drawn(runtime.root);
    expect(names).toEqual([
      'owned-sidewalks',
      'owned-district-ground-datum-unavailable',
      'owned-building-surface-unavailable',
      'owned-building-recorded-extent',
    ]);
    for (const name of REMOVED) expect(names).not.toContain(name);
    expect(names.some((name) => name.startsWith('owned-buildings-'))).toBe(false);
    expect(runtime.metrics.drawCalls).toBe(4);
    runtime.destroy();
    app.destroy();
  });

  it('gives every building the same treatment whatever its material index, name or batch id', () => {
    const { runtime, app } = setup();
    const surfaces = runtime.root.findByName('owned-building-surface-unavailable') as pc.Entity;
    // One mesh instance, one material: two buildings with different indices cannot differ.
    expect(surfaces.render!.meshInstances).toHaveLength(1);
    const material = surfaces.render!.meshInstances[0]!.material as pc.StandardMaterial;
    expect(material.useLighting).toBe(false);
    expect(material.opacityMap).not.toBeNull();
    expect(material.blendType).toBe(pc.BLEND_NORMAL);
    // Walls and roofs of both footprints, at their own source heights and nowhere else.
    const positions: number[] = [];
    surfaces.render!.meshInstances[0]!.mesh.getPositions(positions);
    const heights = new Set<number>();
    for (let index = 1; index < positions.length; index += 3) heights.add(Math.round(positions[index]! * 100));
    expect([...heights].sort((a, b) => a - b)).toEqual([0, 1200, 4000]);
    runtime.destroy();
    app.destroy();
  });

  it('draws the ground as lines, not as a surface', () => {
    const { runtime, app } = setup();
    const datum = runtime.root.findByName('owned-district-ground-datum-unavailable') as pc.Entity;
    const mesh = datum.render!.meshInstances[0]!.mesh;
    expect(mesh.primitive[0]!.type).toBe(pc.PRIMITIVE_LINES);
    const outline = runtime.root.findByName('owned-building-recorded-extent') as pc.Entity;
    expect(outline.render!.meshInstances[0]!.mesh.primitive[0]!.type).toBe(pc.PRIMITIVE_LINES);
    runtime.destroy();
    app.destroy();
  });

  it('names the absence in words a panel can show', () => {
    const { runtime, app } = setup();
    expect(runtime.unavailable).toEqual({
      buildingSurfaces: 2,
      surfaceReason: OWNED_DISTRICT_SURFACE_UNAVAILABLE,
      groundReason: OWNED_DISTRICT_GROUND_UNAVAILABLE,
    });
    expect(OWNED_DISTRICT_SURFACE_UNAVAILABLE).toMatch(/no source record/);
    runtime.destroy();
    app.destroy();
  });

  it('does not draw the interpretation’s generated facade grids or parapets', () => {
    const recipes = {
      district_id: 'test',
      subjects: [
        {
          subject_id: 'test/facade/doitt_id:1', kind: 'facade', permitted_uses: ['render', 'select'],
          recipe: {
            kind: 'facade-grid', feature_id: 'doitt_id:1', height_mm: 40000, bay_width_mm: 4500,
            floor_height_mm: 4200, window_width_mm: 1240, window_height_mm: 1450,
            sill_height_mm: 2700, recess_mm: 55, material_index: 0,
          },
        },
        {
          subject_id: 'test/roof/doitt_id:1', kind: 'roof', permitted_uses: ['render', 'select'],
          recipe: { kind: 'roof-parapet', feature_id: 'doitt_id:1', height_mm: 40000, parapet_height_mm: 600 },
        },
      ],
    } as unknown as DistrictInterpretation;
    const plain = setup();
    const interpreted = setup(recipes);
    expect(drawn(interpreted.runtime.root)).toEqual(drawn(plain.runtime.root));
    const count = (runtime: OwnedDistrictRuntime) => {
      const entity = runtime.root.findByName('owned-building-surface-unavailable') as pc.Entity;
      return entity.render!.meshInstances[0]!.mesh.vertexBuffer!.numVertices;
    };
    expect(count(interpreted.runtime)).toBe(count(plain.runtime));
    for (const held of [plain, interpreted]) {
      held.runtime.destroy();
      held.app.destroy();
    }
  });

  it('places a fictional authored instance without a sky lantern', () => {
    const { runtime, app } = setup();
    runtime.setAuthoredInstances([{
      instanceId: 'probe',
      providerFeatureId: 'doitt_id:1',
      coordinateFrame: 'flatiron-local-mm',
      transform: { xMm: 0, yMm: 0, zMm: 0, yawMicroradians: 0, scaleMilli: 1000 },
      origin: { role: 'fictional' },
      removed: false,
      availability: 'available',
    }]);
    const placed = runtime.authoredRoot.findByName('authored-probe') as pc.Entity;
    expect(placed).not.toBeNull();
    expect(placed.children).toHaveLength(0);
    expect(runtime.authoredRoot.findByName('authored-fantasy-sky-lantern')).toBeNull();
    runtime.destroy();
    app.destroy();
  });
});
