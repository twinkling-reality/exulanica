/**
 * A site's roofs shaped by what they are made of: a ridge at its material's pitch and overhang, a
 * tent whose sides reach the ground and whose door is left open, a slab with its parapet, and the
 * wall pieces a tent stands in place of. The forms are the committed catalog's; the roofs and the
 * drawing are written by hand in the served shape.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readRoofForms, readSurfaceMaterials } from '@exulanica/atlas-core';
import { parseSiteDrawing, ridgeAxis, roofMesh, shapeRoofs, type RoofInput, type RoofMesh } from '../src/playcanvas/generated-site/index.js';

// Relative to web/, where the suite runs.
const FORMS = readRoofForms(readFileSync('../assets/catalogs/world-kinds/roof-form.v1.json', 'utf8'));
const MATERIALS = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));
const form = (key: string) => FORMS.byMaterial.get(key)!;

const bounds = (mesh: RoofMesh) => {
  const axis = (k: number) => mesh.positions.filter((_, i) => i % 3 === k);
  return { x: [Math.min(...axis(0)), Math.max(...axis(0))], y: [Math.min(...axis(1)), Math.max(...axis(1))], z: [Math.min(...axis(2)), Math.max(...axis(2))] };
};
const near = (pair: number[], low: number, high: number) => {
  expect(pair[0]).toBeCloseTo(low, 6);
  expect(pair[1]).toBeCloseTo(high, 6);
};
/** Whether some triangle of the mesh lying in the plane z = `z` covers the point (x, y) there. */
const coversAt = (mesh: RoofMesh, z: number, x: number, y: number): boolean => {
  const p = mesh.positions;
  for (let i = 0; i < mesh.indices.length; i += 3) {
    const [a, b, c] = [mesh.indices[i]!, mesh.indices[i + 1]!, mesh.indices[i + 2]!].map((n) => [p[n * 3]!, p[n * 3 + 1]!, p[n * 3 + 2]!] as const);
    if ([a!, b!, c!].some((v) => Math.abs(v[2] - z) > 1e-6)) continue;
    const sign = (u: readonly number[], v: readonly number[]) => (x - v[0]!) * (u[1]! - v[1]!) - (u[0]! - v[0]!) * (y - v[1]!);
    const [d1, d2, d3] = [sign(a!, b!), sign(b!, c!), sign(c!, a!)];
    if (!((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0))) return true;
  }
  return false;
};
/** A cottage 8.5 m east to west and 6.5 m deep, walls 3 m, served pitched with its ridge drawn north to south. */
const cottage: RoofInput = { widthM: 8.5, depthM: 6.5, wallM: 3, served: { pitched: true, riseM: 2.275, ridge: 'z' }, doorAxis: 'z', doors: [] };

describe('a ridge in its material\'s form', () => {
  it('rises by its pitch over half its span, overhangs its walls level and at its ends, and is laid as thick as stated', () => {
    const thatch = roofMesh(cottage, form('thatch'))!;
    // Thatch: 45 degrees, 450 mm over the walls, 300 mm thick, its ridge along the longer side (east to west).
    const b = bounds(thatch);
    near(b.x, -(4.25 + 0.45), 4.25 + 0.45);
    near(b.z, -(3.25 + 0.45), 3.25 + 0.45);
    near(b.y, -0.45, 3.25 + 0.3);
    // Slate over the same walls is lower, thinner and reaches less far.
    const slate = bounds(roofMesh(cottage, form('slate'))!);
    near(slate.y, -0.7 * 0.25, 0.7 * 3.25 + 0.08);
    near(slate.z, -(3.25 + 0.25), 3.25 + 0.25);
  });

  it('runs along the longer side, the way the door faces or as served, by its material\'s word', () => {
    const long = form('thatch').ridge!;
    expect(ridgeAxis(cottage, long)).toBe('x');
    expect(ridgeAxis({ ...cottage, widthM: 5, depthM: 9 }, long)).toBe('z');
    expect(ridgeAxis(cottage, { ...long, runs: 'as_served' })).toBe('z');
    expect(ridgeAxis({ ...cottage, served: { ...cottage.served, ridge: 'x' } }, { ...long, runs: 'as_served' })).toBe('x');
    const door = form('canvas').ridge!;
    expect(ridgeAxis({ ...cottage, doorAxis: 'z' }, door)).toBe('z');
    expect(ridgeAxis({ ...cottage, widthM: 5, depthM: 9, doorAxis: 'x' }, door)).toBe('x');
    // A structure with no door has no way it faces: the longer side.
    expect(ridgeAxis({ ...cottage, doorAxis: null }, door)).toBe('x');
  });

  it('closes the walls\' ends up to the ridge, and every face is drawn from both sides', () => {
    const slate = roofMesh({ ...cottage, widthM: 6, depthM: 4 }, form('slate'))!;
    // The end of the walls at the east: covered at its middle below the ridge, open above the slope.
    const rise = 0.7 * 2;
    const p = slate.positions;
    const onEnd = (x: number, y: number, z: number): boolean => {
      for (let i = 0; i < slate.indices.length; i += 3) {
        const t = [slate.indices[i]!, slate.indices[i + 1]!, slate.indices[i + 2]!].map((n) => [p[n * 3]!, p[n * 3 + 1]!, p[n * 3 + 2]!]);
        if (t.every((v) => Math.abs(v[0]! - x) < 1e-6) && Math.min(...t.map((v) => v[1]!)) <= y && Math.max(...t.map((v) => v[1]!)) >= y && Math.min(...t.map((v) => v[2]!)) <= z && Math.max(...t.map((v) => v[2]!)) >= z) return true;
      }
      return false;
    };
    expect(onEnd(3, rise / 2, 0)).toBe(true);
    expect(onEnd(-3, rise / 2, 0)).toBe(true);
    // Both sides: the normals of the whole mesh cancel, and there are as many triangles facing each way.
    const sum = [0, 1, 2].map((k) => slate.normals.filter((_, i) => i % 3 === k).reduce((a, n) => a + n, 0));
    for (const part of sum) expect(part).toBeCloseTo(0, 6);
    expect((slate.indices.length / 3) % 2).toBe(0);
  });
});

describe('a tent', () => {
  /** 5 m east to west, 6 m deep, walls 2.4 m, its door 0.9 m wide and 2 m high in its south end, half a metre east of the middle. */
  const tent: RoofInput = { widthM: 5, depthM: 6, wallM: 2.4, served: { pitched: true, riseM: 1.75, ridge: 'x' }, doorAxis: 'z', doors: [{ x: 0.5, z: 3, widthM: 0.9, topM: 2 }] };

  it('runs from a ridge along the way its door faces down to the ground at its footprint\'s sides', () => {
    const b = bounds(roofMesh(tent, form('canvas'))!);
    // The ridge runs north to south; its apex is 1.2 times half the 5 m span above the ground.
    near(b.x, -2.5, 2.5);
    near(b.z, -3, 3);
    near(b.y, -2.4, 1.2 * 2.5 - 2.4);
  });

  it('leaves its door open in the end it stands in and closes the other end', () => {
    const mesh = roofMesh(tent, form('canvas'))!;
    const ground = -2.4;
    // In the south end: nothing across the doorway, canvas beside it and over its head.
    expect(coversAt(mesh, 3, 0.5, ground + 1)).toBe(false);
    expect(coversAt(mesh, 3, 0.5, ground + 1.7)).toBe(false);
    expect(coversAt(mesh, 3, -1, ground + 0.5)).toBe(true);
    expect(coversAt(mesh, 3, 1.6, ground + 0.3)).toBe(true);
    // The canvas over the door's east jamb is lower than the door's own 2 m head, so the opening stops at the canvas.
    expect(coversAt(mesh, 3, 0.5, ground + 2.2)).toBe(true);
    // The north end has no door: canvas where the doorway would be.
    expect(coversAt(mesh, -3, 0.5, ground + 1)).toBe(true);
    // A tent with no door at all closes both ends.
    const closed = roofMesh({ ...tent, doors: [] }, form('canvas'))!;
    expect(coversAt(closed, 3, 0.5, ground + 1)).toBe(true);
  });
});

describe('a slab in its material\'s form, and a class its material does not shape', () => {
  const flat: RoofInput = { widthM: 8, depthM: 6, wallM: 3, served: { pitched: false, riseM: 0.2, ridge: 'x' }, doorAxis: 'z', doors: [] };

  it('is the served slab with a parapet standing round its edge', () => {
    const adobe = roofMesh(flat, form('adobe'))!;
    const b = bounds(adobe);
    near(b.x, -4, 4);
    near(b.z, -3, 3);
    near(b.y, 0, 0.2 + 0.45);
    // The slab and four lengths of parapet: five boxes of six faces, each from both sides.
    expect(adobe.indices.length / 3).toBe(5 * 6 * 2 * 2);
    // Nothing stands over the middle of the roof: the parapet is at its edge.
    const p = adobe.positions;
    const overMiddle = p.filter((_, i) => i % 3 === 1 && p[i]! > 0.2 + 1e-6 && Math.abs(p[i - 1]!) < 3.5 && Math.abs(p[i + 1]!) < 2.5);
    expect(overMiddle).toEqual([]);
  });

  it('is drawn as served: a pitched roof of a material that shapes only slabs, and a flat roof of one that shapes only ridges', () => {
    expect(roofMesh(cottage, form('adobe'))).toBeNull();
    expect(roofMesh(flat, form('thatch'))).toBeNull();
    expect(roofMesh(flat, form('canvas'))).toBeNull();
  });
});

describe('the roofs of a drawing', () => {
  const slot = (identity: string, lookRole: string, primitive: string, position: number[], yaw: number, box: number[], part = identity.split(':')[0]) =>
    ({ identity, part, label: identity, lookRole, positionMm: position, yawQuarterTurns: yaw, boxMm: box, front: '+y', fit: 'contain', primitive });
  /** Two tents of one part 5 m by 6 m (one roofed in canvas with its door in its south wall, one in glass), a thatched hut, and a palisade. */
  const drawing = parseSiteDrawing({
    profile: 'exulanica.site-drawing/v1', world_id: 'world-1', receipt_sha256: 'a'.repeat(64),
    kind: { kind: 'camp', version: 1, label: 'Camp' }, extent: { widthMm: 40_000, depthMm: 40_000, enclosure: 'open' },
    arrival: { positionMm: [20_000, 2000, 0], facingMm: [0, 1] },
    slots: [
      slot('ground', 'ground.grass', 'plane', [20_000, 20_000, 0], 0, [40_000, 40_000, 0]),
      slot('tent-a', 'structure.tent', 'none', [10_000, 10_000, 0], 2, [5000, 6000, 2400], 'tent'),
      slot('tent-a:roof', 'roof.tent', 'gable', [10_000, 10_000, 2400], 0, [5000, 6000, 1750], 'tent'),
      slot('tent-a-south:wall:0', 'wall.tent', 'box', [8500, 7000, 0], 0, [2000, 100, 2400], 'tent'),
      slot('tent-a-south:wall:1', 'wall.tent', 'box', [11_750, 7000, 0], 0, [1500, 100, 2400], 'tent'),
      slot('tent-a-south:lintel:0', 'wall.tent', 'box', [10_250, 7000, 2000], 0, [900, 100, 400], 'tent'),
      { ...slot('tent-a-south:door:0', 'door.default', 'none', [10_250, 7000, 0], 0, [900, 100, 2000], 'tent'), fit: 'fill' },
      slot('tent-a-west:wall:0', 'wall.tent', 'box', [7500, 10_000, 0], 1, [6000, 100, 2400], 'tent'),
      slot('tent-b', 'structure.tent', 'none', [30_000, 10_000, 0], 2, [5000, 6000, 2400], 'tent'),
      slot('tent-b:roof', 'roof.glass', 'gable', [30_000, 10_000, 2400], 0, [5000, 6000, 1750], 'tent'),
      slot('tent-b-west:wall:0', 'wall.tent', 'box', [27_500, 10_000, 0], 1, [6000, 100, 2400], 'tent'),
      slot('hut', 'structure.hut', 'none', [20_000, 30_000, 0], 0, [8500, 6500, 3000]),
      slot('hut:roof', 'roof.thatched', 'gable', [20_000, 30_000, 3000], 1, [6500, 8500, 2275], 'hut'),
      slot('hut-north:wall:0', 'wall.stone', 'box', [20_000, 33_250, 0], 0, [8500, 200, 3000], 'hut'),
      slot('palisade:wall:0', 'wall.palisade', 'box', [20_000, 0, 0], 0, [40_000, 200, 2500]),
    ],
    walk: { floorMm: [0, 0, 40_000, 40_000], blockersMm: [], keepOutMm: [] }, seats: [],
  });

  it('shapes each roof whose material has a form, and leaves out the wall pieces under a roof that runs to the ground', () => {
    const shaped = shapeRoofs(drawing, MATERIALS, FORMS);
    // The canvas tent and the thatched hut; the tent roofed in glass, a material no form shapes, is drawn as served.
    expect([...shaped.meshes.keys()].sort()).toEqual(['hut:roof', 'tent-a:roof']);
    // Only the first tent's own wall pieces and lintel: not the other tent's, the hut's or the palisade.
    expect([...shaped.undrawn].sort()).toEqual(['tent-a-south:lintel:0', 'tent-a-south:wall:0', 'tent-a-south:wall:1', 'tent-a-west:wall:0']);
    // Its door faces south, so its ridge runs north to south and its south end is open at the doorway.
    const tent = shaped.meshes.get('tent-a:roof')!;
    near(bounds(tent).x, -2.5, 2.5);
    expect(coversAt(tent, 3, 0.25, -2.4 + 1)).toBe(false);
    expect(coversAt(tent, 3, -1.5, -2.4 + 0.4)).toBe(true);
    // The hut is 8.5 m east to west under a roof served turned a quarter: its thatch runs along that longer side.
    near(bounds(shaped.meshes.get('hut:roof')!).x, -(4.25 + 0.45), 4.25 + 0.45);
  });

  it('shapes nothing without both catalogs', () => {
    expect(shapeRoofs(drawing, MATERIALS, null).meshes.size).toBe(0);
    expect(shapeRoofs(drawing, null, FORMS).meshes.size).toBe(0);
    expect(shapeRoofs(drawing, null, FORMS).undrawn.size).toBe(0);
  });
});
