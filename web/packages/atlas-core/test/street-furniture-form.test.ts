import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  furnitureFormEnvelopes, furnitureFormSurfaces, readStreetFurnitureForms, slotFurnitureParts, slotFurnitureSeatTops,
  slotFurnitureSurfaces,
  type FurnitureForm, type FurnitureForms, type FurniturePart, type FurnitureSurface,
} from '../src/street-furniture-form.js';

const TEXT = readFileSync('../assets/catalogs/world-kinds/street-furniture-form.v1.json', 'utf8');
const forms = readStreetFurnitureForms(TEXT);
/** The catalog the page bundles: v1's forms and a timber fence for a boundary run. */
const FORMS2 = readStreetFurnitureForms(readFileSync('../assets/catalogs/world-kinds/street-furniture-form.v2.json', 'utf8'));

/** The parts a record of each class carries: the grammar's own catalog, field for field. */
const GRAMMAR = JSON.parse(readFileSync('../assets/catalogs/street-furniture.v2.json', 'utf8')) as {
  readonly entries: readonly { readonly key: string; readonly parts: readonly Record<string, unknown>[] }[];
};
function partsOf(key: string): FurniturePart[] {
  const entry = GRAMMAR.entries.find((one) => one.key === key)!;
  return entry.parts.map((part) => ({
    shape: part['shape'] as FurniturePart['shape'], surfaceRole: part['surface_role'] as string,
    offsetXMm: part['offset_x_mm'] as number, offsetYMm: part['offset_y_mm'] as number, offsetZMm: part['offset_z_mm'] as number,
    sizeXMm: part['size_x_mm'] as number, sizeYMm: part['size_y_mm'] as number, sizeZMm: part['size_z_mm'] as number,
  }));
}

/** The signed volume a surface's triangles enclose, cubic millimetres: positive when they face outward. */
function volume(surfaces: readonly FurnitureSurface[]): number {
  let total = 0;
  for (const surface of surfaces) {
    const p = (i: number): [number, number, number] => [surface.positions[i * 3]!, surface.positions[i * 3 + 1]!, surface.positions[i * 3 + 2]!];
    for (let t = 0; t < surface.indices.length; t += 3) {
      const [a, b, c] = [p(surface.indices[t]!), p(surface.indices[t + 1]!), p(surface.indices[t + 2]!)];
      total += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6;
    }
  }
  return total;
}

/**
 * Edges, by their corners' positions, crossed more often one way than the other: none when the triangles close
 * a solid and all face the same way (a face turned inward crosses its edges the same way as its neighbours).
 */
function unpairedEdges(surfaces: readonly FurnitureSurface[]): string[] {
  const count = new Map<string, number>();
  for (const surface of surfaces) {
    const at = (i: number): string => [0, 1, 2].map((k) => surface.positions[i * 3 + k]!.toFixed(4)).join(',');
    for (let t = 0; t < surface.indices.length; t += 3) {
      for (let k = 0; k < 3; k += 1) {
        const from = at(surface.indices[t + k]!);
        const to = at(surface.indices[t + ((k + 1) % 3)]!);
        count.set(`${from} ${to}`, (count.get(`${from} ${to}`) ?? 0) + 1);
      }
    }
  }
  return [...count].filter(([edge, n]) => count.get(edge.split(' ').reverse().join(' ')) !== n).map(([edge]) => edge);
}

/** A surface's normals as the page makes them (PlayCanvas `calculateNormals`): each vertex's triangles' unit normals, summed and normalised. */
function pageNormals(surface: FurnitureSurface): number[] {
  const normals = surface.positions.map(() => 0);
  const p = (i: number): number[] => [surface.positions[i * 3]!, surface.positions[i * 3 + 1]!, surface.positions[i * 3 + 2]!];
  for (let t = 0; t < surface.indices.length; t += 3) {
    const corners = [surface.indices[t]!, surface.indices[t + 1]!, surface.indices[t + 2]!];
    const [a, b, c] = corners.map(p) as [number[], number[], number[]];
    const u = [b[0]! - a[0]!, b[1]! - a[1]!, b[2]! - a[2]!];
    const v = [c[0]! - a[0]!, c[1]! - a[1]!, c[2]! - a[2]!];
    const face = [u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!];
    const length = Math.hypot(...face);
    for (const corner of corners) for (let k = 0; k < 3; k += 1) normals[corner * 3 + k] = normals[corner * 3 + k]! + face[k]! / length;
  }
  for (let at = 0; at < normals.length; at += 3) {
    const length = Math.hypot(normals[at]!, normals[at + 1]!, normals[at + 2]!);
    for (let k = 0; k < 3; k += 1) normals[at + k] = normals[at + k]! / length;
  }
  return normals;
}

/** A form of one class with only one of its draws, to hold that draw to its own envelope. */
function onlyDraw(form: FurnitureForm, at: number): FurnitureForms {
  return { version: 1, byClass: new Map([[form.key, { ...form, draws: [form.draws[at]!] }]]), bySlotLeaf: new Map() };
}

const CLASSES = ['bench', 'litter_bin', 'cycle_stand', 'sign_post'];

describe('street furniture form catalog', () => {
  it('reads the shipped catalog: a form for each furniture class the grammar places along a kerb', () => {
    expect([...forms.byClass.keys()].sort()).toEqual([...CLASSES].sort());
    for (const key of CLASSES) {
      expect(forms.byClass.get(key)!.parts).toEqual(partsOf(key).map((part) => part.shape));
    }
  });

  it('refuses a catalog that is not one, and a form that leaves a part undrawn or draws one twice', () => {
    const document = JSON.parse(TEXT) as { catalog_id: string; entries: Record<string, unknown>[] };
    const edited = (change: (copy: typeof document) => void): string => {
      const copy = JSON.parse(TEXT) as typeof document;
      change(copy);
      return JSON.stringify(copy);
    };
    expect(() => readStreetFurnitureForms(edited((copy) => { copy.catalog_id = 'roof-form'; }))).toThrow(/is not the street furniture form catalog/);
    expect(() => readStreetFurnitureForms(edited((copy) => { copy.entries.push(copy.entries[0]!); }))).toThrow(/bench is stated twice/);
    expect(() => readStreetFurnitureForms(edited((copy) => { (copy.entries[0]!['draws'] as unknown[]).pop(); }))).toThrow(/leaves a part undrawn/);
    expect(() => readStreetFurnitureForms(edited((copy) => {
      ((copy.entries[0]!['draws'] as Record<string, unknown>[])[3]!)['parts'] = [2];
    }))).toThrow(/draws a part twice/);
    expect(() => readStreetFurnitureForms(edited((copy) => { copy.entries[0]!['reason'] = ' '; }))).toThrow(/bench gives no reason/);
  });

  it('refuses a form for a shape it cannot draw and a figure out of its range', () => {
    const one = (draw: Record<string, unknown>, parts: string[] = ['box']): string => JSON.stringify({
      catalog_id: 'street-furniture-form', catalog_version: 1, entries: [{ key: 'thing', parts, draws: [draw], reason: 'a test' }],
    });
    expect(() => readStreetFurnitureForms(one({ form: 'lathe', parts: [0], segments: 16, profile_permille: [[0, 1000], [1000, 1000]] }))).toThrow(/turns a box/);
    expect(() => readStreetFurnitureForms(one({ form: 'slats', parts: [0], count: 3, gap_mm: 10 }, ['prism']))).toThrow(/draws a prism as slats/);
    expect(() => readStreetFurnitureForms(one({ form: 'slats', parts: [0], count: 13, gap_mm: 10 }))).toThrow(/count must be a whole number from 1 to 12/);
    expect(() => readStreetFurnitureForms(one({ form: 'lathe', parts: [0], segments: 12, profile_permille: [[0, 1000], [1000, 1000]] }, ['prism']))).toThrow(/must be 8, 16, 32 or 64/);
    expect(() => readStreetFurnitureForms(one({ form: 'lathe', parts: [0], segments: 16, profile_permille: [[0, 1000], [900, 1000]] }, ['prism']))).toThrow(/must run from height 0 to 1000/);
    expect(() => readStreetFurnitureForms(one({ form: 'lathe', parts: [0], segments: 16, profile_permille: [[0, 1000], [600, 1000], [500, 900], [1000, 1000]] }, ['prism']))).toThrow(/must not go down/);
    expect(() => readStreetFurnitureForms(one({ form: 'lathe', parts: [0], segments: 16, profile_permille: [[0, 1001], [1000, 1000]] }, ['prism']))).toThrow(/from 0 to 1000/);
    expect(() => readStreetFurnitureForms(one({ form: 'tube', parts: [0], through: [[1, 'top'], [0, 'top']], radius_permille: 500, bend_mm: 100, segments: 8 }, ['box', 'box']))).toThrow(/does not draw/);
    expect(() => readStreetFurnitureForms(one({ form: 'cone', parts: [0] }))).toThrow(/must be solid, slats, frame, lathe, tube, plate or rails/);
  });
});

describe('street furniture forms drawn', () => {
  it('keeps every vertex of every draw inside the box of the parts it draws', () => {
    for (const key of CLASSES) {
      const form = forms.byClass.get(key)!;
      const parts = partsOf(key);
      const envelopes = furnitureFormEnvelopes(form, parts);
      form.draws.forEach((_, at) => {
        const surfaces = furnitureFormSurfaces(onlyDraw(form, at), key, parts)!;
        expect(surfaces.length).toBeGreaterThan(0);
        const { min, max } = envelopes[at]!;
        for (const surface of surfaces) {
          for (let i = 0; i < surface.positions.length; i += 3) {
            for (let axis = 0; axis < 3; axis += 1) {
              expect(surface.positions[i + axis]!).toBeGreaterThanOrEqual(min[axis]! - 1e-6);
              expect(surface.positions[i + axis]!).toBeLessThanOrEqual(max[axis]! + 1e-6);
            }
          }
        }
      });
    }
  });

  it('stands a sign\'s plate on its pole: the pole ends at the plate\'s foot, and every vertex a form makes is drawn', () => {
    const parts = partsOf('sign_post');
    const plate = parts[1]!;
    const pole = furnitureFormSurfaces(forms, 'sign_post', parts)!.find((surface) => surface.role === parts[0]!.surfaceRole)!;
    const top = Math.max(...pole.indices.map((index) => pole.positions[index * 3 + 2]!));
    // The plate's foot is 2200 mm up the 2800 mm pole, 786 thousandths: the pole's top sits under a millimetre inside it.
    expect(top).toBeGreaterThanOrEqual(plate.offsetZMm);
    expect(top).toBeLessThan(plate.offsetZMm + 1);
    for (const key of CLASSES) {
      for (const surface of furnitureFormSurfaces(forms, key, partsOf(key))!) {
        expect(new Set(surface.indices).size, `${key} ${surface.role}`).toBe(surface.positions.length / 3);
      }
    }
  });

  it('draws no triangle of no area, so every vertex has a normal: a town with a sign on its kerb opens', () => {
    // The page makes normals from the triangles: a vertex whose only triangle has no area gets none (NaN), and the
    // tile's surface batch then refuses to draw at all. The sign's pole once closed its top with such slivers.
    const drawn: [string, FurnitureSurface[]][] = [
      ...CLASSES.map((key): [string, FurnitureSurface[]] => [key, furnitureFormSurfaces(FORMS2, key, partsOf(key))!]),
      ...[...FORMS2.bySlotLeaf.keys()].map((leaf): [string, FurnitureSurface[]] => [`slot ${leaf}`, slotFurnitureSurfaces(FORMS2, leaf, [2000, 500, 450])!]),
    ];
    for (const [what, surfaces] of drawn) {
      for (const surface of surfaces) {
        const p = (i: number): number[] => [surface.positions[i * 3]!, surface.positions[i * 3 + 1]!, surface.positions[i * 3 + 2]!];
        for (let t = 0; t < surface.indices.length; t += 3) {
          const [a, b, c] = [p(surface.indices[t]!), p(surface.indices[t + 1]!), p(surface.indices[t + 2]!)];
          const u = [b[0]! - a[0]!, b[1]! - a[1]!, b[2]! - a[2]!];
          const v = [c[0]! - a[0]!, c[1]! - a[1]!, c[2]! - a[2]!];
          const area = Math.hypot(u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!) / 2;
          expect(area, `${what} ${surface.role} triangle ${t / 3}`).toBeGreaterThan(1e-3);
        }
        expect(new Set(surface.indices).size, `${what} ${surface.role}`).toBe(surface.positions.length / 3);
      }
    }
  });

  it('draws each part as a closed solid facing outward, in the role its part states', () => {
    for (const key of CLASSES) {
      const form = forms.byClass.get(key)!;
      const parts = partsOf(key);
      form.draws.forEach((draw, at) => {
        const surfaces = furnitureFormSurfaces(onlyDraw(form, at), key, parts)!;
        expect(surfaces.map((surface) => surface.role)).toEqual([parts[draw.parts[0]!]!.surfaceRole]);
        const enclosed = volume(surfaces);
        const envelope = furnitureFormEnvelopes(form, parts)[at]!;
        const box = (envelope.max[0] - envelope.min[0]) * (envelope.max[1] - envelope.min[1]) * (envelope.max[2] - envelope.min[2]);
        expect(enclosed, `${key} draw ${at}`).toBeGreaterThan(0);
        expect(enclosed, `${key} draw ${at}`).toBeLessThanOrEqual(box * 1.000001);
        // A face turned inward crosses its edges the same way as its neighbours, so an end of a tube that faced into it
        // (its volume unchanged, the cycle stand's ends lying at height 0) leaves its rim unpaired.
        expect(unpairedEdges(surfaces), `${key} draw ${at}`).toEqual([]);
      });
    }
  });

  it('shades a cycle stand\'s posts level down to the ground: its ends are flat discs facing out on their own vertices', () => {
    // The page makes a vertex's normal from the unit normals of the triangles that use it (calculateNormals). An end
    // sharing the wall's last ring leaned the normals there toward its own, so each post's straight run from the
    // ground to its bend shaded as if it curled toward the sky (or the ground) at its foot.
    const [tube] = furnitureFormSurfaces(forms, 'cycle_stand', partsOf('cycle_stand'))!;
    const normals = pageNormals(tube!);
    // Both posts stand on the ground: every vertex there is a foot's, facing straight down, or a wall's, level.
    let walls = 0, feet = 0;
    for (let at = 0; at < tube!.positions.length / 3; at += 1) {
      if (tube!.positions[at * 3 + 2] !== 0) continue;
      const nz = normals[at * 3 + 2]!;
      if (nz === -1) feet += 1;
      else {
        // Level to a ten-thousandth: the run's top ring tilts a little into the bend; a shared end leaned it 0.7.
        expect(Math.abs(nz), `vertex ${at}`).toBeLessThan(1e-4);
        walls += 1;
      }
    }
    // Each foot a centre and its 12 corners; each wall's ring 13 vertices, its first and last meeting where s wraps.
    expect([feet, walls]).toEqual([2 * 13, 2 * 13]);
  });

  it('states a unit normal at every vertex, facing out of each triangle it bounds', () => {
    const drawn: [string, FurnitureSurface[]][] = [
      ...CLASSES.map((key): [string, FurnitureSurface[]] => [key, furnitureFormSurfaces(FORMS2, key, partsOf(key))!]),
      ...[...FORMS2.bySlotLeaf.keys()].map((leaf): [string, FurnitureSurface[]] => [`slot ${leaf}`, slotFurnitureSurfaces(FORMS2, leaf, [2000, 500, 450])!]),
    ];
    for (const [what, surfaces] of drawn) {
      for (const surface of surfaces) {
        expect(surface.normals.length, `${what} ${surface.role}`).toBe(surface.positions.length);
        const n = (i: number): number[] => [surface.normals[i * 3]!, surface.normals[i * 3 + 1]!, surface.normals[i * 3 + 2]!];
        for (let at = 0; at < surface.normals.length / 3; at += 1) expect(Math.hypot(...n(at)), `${what} vertex ${at}`).toBeCloseTo(1, 12);
        const p = (i: number): number[] => [surface.positions[i * 3]!, surface.positions[i * 3 + 1]!, surface.positions[i * 3 + 2]!];
        for (let t = 0; t < surface.indices.length; t += 3) {
          const corners = [surface.indices[t]!, surface.indices[t + 1]!, surface.indices[t + 2]!];
          const [a, b, c] = corners.map(p) as [number[], number[], number[]];
          const u = [b[0]! - a[0]!, b[1]! - a[1]!, b[2]! - a[2]!];
          const v = [c[0]! - a[0]!, c[1]! - a[1]!, c[2]! - a[2]!];
          const face = [u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!];
          const length = Math.hypot(...face);
          // A corner's normal leans from its triangle's by less than a right angle: the triangle and its corners face one way.
          for (const corner of corners) {
            const lean = (n(corner)[0]! * face[0]! + n(corner)[1]! * face[1]! + n(corner)[2]! * face[2]!) / length;
            expect(lean, `${what} ${surface.role} triangle ${t / 3}`).toBeGreaterThan(0.5);
          }
        }
      }
    }
  });

  it('turns a round body\'s normals with it, the same where a ring\'s first and last vertices meet as anywhere round it', () => {
    // The page once made these from the triangles: a ring's first and last vertices meet where s wraps, each with the
    // triangles of one side only, so the normals there turned 15 degrees off round on the stand (down its broad face),
    // 11 on the sign's pole and 6 on the bin: a line down each, shaded as a crease.
    for (const key of ['litter_bin', 'sign_post']) {
      const form = forms.byClass.get(key)!;
      const parts = partsOf(key);
      form.draws.forEach((draw, at) => {
        if (draw.form !== 'lathe') return;
        const part = parts[draw.parts[0]!]!;
        expect(part.sizeXMm, `${key}: a round part`).toBe(part.sizeYMm);
        const [surface] = furnitureFormSurfaces(onlyDraw(form, at), key, parts)!;
        for (let i = 0; i < surface!.positions.length / 3; i += 1) {
          const [x, y] = [surface!.positions[i * 3]! - part.offsetXMm, surface!.positions[i * 3 + 1]! - part.offsetYMm];
          const [nx, ny] = [surface!.normals[i * 3]!, surface!.normals[i * 3 + 1]!];
          // Level part of the normal straight out from the axis (none on a flat disc or at the axis itself).
          expect(Math.abs(x * ny - y * nx), `${key} vertex ${i}`).toBeLessThan(1e-9);
          expect(x * nx + y * ny, `${key} vertex ${i}`).toBeGreaterThanOrEqual(-1e-9);
        }
      });
    }
    const parts = partsOf('cycle_stand');
    const [hoop] = furnitureFormSurfaces(forms, 'cycle_stand', parts)!;
    const radius = parts[0]!.sizeXMm / 2;
    let checked = 0;
    for (let i = 0; i < hoop!.positions.length / 3; i += 1) {
      const [x, y, z] = [hoop!.positions[i * 3]!, hoop!.positions[i * 3 + 1]!, hoop!.positions[i * 3 + 2]!];
      // On each post's straight run, its foot to below the bend: straight out from the post, or down on its foot.
      const post = parts.slice(0, 2).find((one) => Math.abs(x - one.offsetXMm) <= radius + 1e-9);
      if (post === undefined || z >= 500) continue;
      const normal = [hoop!.normals[i * 3]!, hoop!.normals[i * 3 + 1]!, hoop!.normals[i * 3 + 2]!];
      const out = [(x - post.offsetXMm) / radius, (y - post.offsetYMm) / radius, 0];
      const down = normal[2]! < -0.5;
      (down ? [0, 0, -1] : out).forEach((value, axis) => expect(normal[axis]!, `cycle stand vertex ${i}`).toBeCloseTo(value, 9));
      checked += 1;
    }
    // Both posts' feet: each a ring of 13 (its first and last meeting) and a foot of 13.
    expect(checked).toBe(2 * (13 + 13));
  });

  it('lays slats with their gaps and frames with their bars, as stated', () => {
    const bench = partsOf('bench');
    const seat = furnitureFormSurfaces(onlyDraw(forms.byClass.get('bench')!, 0), 'bench', bench)!;
    // Four slats across the 450 mm seat with three 20 mm gaps: each (450 - 60) / 4 wide, 1800 long, 60 thick.
    expect(volume(seat)).toBeCloseTo(4 * ((450 - 3 * 20) / 4) * 1800 * 60, 0);
    const leg = furnitureFormSurfaces(onlyDraw(forms.byClass.get('bench')!, 2), 'bench', bench)!;
    // Two uprights 50 by 80 by 420, a top rail and a foot rail 350 by 80 by 50 between them.
    expect(volume(leg)).toBeCloseTo(2 * 50 * 80 * 420 + 2 * 350 * 80 * 50, 0);
  });

  it('draws the same triangles from the same record, and draws a record its form does not fit as baked', () => {
    for (const key of CLASSES) {
      expect(furnitureFormSurfaces(forms, key, partsOf(key))).toEqual(furnitureFormSurfaces(forms, key, partsOf(key)));
    }
    expect(furnitureFormSurfaces(forms, 'street_lamp', partsOf('street_lamp'))).toBeNull();
    expect(furnitureFormSurfaces(forms, 'bench', partsOf('bench').slice(0, 3))).toBeNull();
    expect(furnitureFormSurfaces(forms, 'bench', partsOf('litter_bin'))).toBeNull();
    // A seat too small for four slats and their three 20 mm gaps across either short side is drawn as
    // baked, never as slats of no width.
    const narrow = partsOf('bench').map((part, at) => (at === 0 ? { ...part, sizeYMm: 30, sizeZMm: 30 } : part));
    expect(furnitureFormSurfaces(forms, 'bench', narrow)).toBeNull();
  });
});

describe('a boundary run drawn as a timber fence (catalog v2)', () => {
  it('reads v2 as v1 with a timber fence for a boundary run, and v1 still reads as made', () => {
    expect([forms.version, FORMS2.version]).toEqual([1, 2]);
    expect([...FORMS2.byClass]).toEqual([...forms.byClass]);
    expect(FORMS2.bySlotLeaf.get('bench')).toEqual(forms.bySlotLeaf.get('bench'));
    expect([...forms.bySlotLeaf.keys()]).toEqual(['bench']);
    expect([...FORMS2.bySlotLeaf.keys()]).toEqual(['bench', 'fence_wood']);
  });

  it('stands posts at both ends and at most 2 m apart, rails between the end posts, all inside the run\'s box', () => {
    const triangles = (box: readonly [number, number, number]): number | null => {
      const surfaces = slotFurnitureSurfaces(FORMS2, 'fence_wood', box);
      return surfaces === null ? null : surfaces.reduce((sum, surface) => sum + surface.indices.length / 3, 0);
    };
    // Twelve triangles a box: 2 posts and 2 rails for a run up to 2.1 m, a third post past it; a 9.5 m run 6 posts.
    expect(triangles([2100, 100, 1200])).toBe((2 + 2) * 12);
    expect(triangles([2101, 100, 1200])).toBe((3 + 2) * 12);
    expect(triangles([9500, 100, 1200])).toBe((6 + 2) * 12);
    const run = slotFurnitureSurfaces(FORMS2, 'fence_wood', [9500, 100, 1200])!;
    expect(run.map((surface) => surface.role)).toEqual(['object_primary']);
    expect(unpairedEdges(run)).toEqual([]);
    expect(volume(run)).toBeGreaterThan(0);
    const xs: number[] = [];
    for (let at = 0; at < run[0]!.positions.length; at += 3) {
      const [x, y, z] = [run[0]!.positions[at]!, run[0]!.positions[at + 1]!, run[0]!.positions[at + 2]!];
      expect(Math.abs(x)).toBeLessThanOrEqual(4750 + 1e-6);
      expect(Math.abs(y)).toBeLessThanOrEqual(50 + 1e-6);
      expect(z).toBeGreaterThanOrEqual(0);
      expect(z).toBeLessThanOrEqual(1200 + 1e-6);
      if (Math.abs(y) === 50) xs.push(x);
    }
    // The posts are the only boxes as deep as the run: their faces' x, sorted, step at most 2 m between posts.
    const faces = [...new Set(xs.map((x) => x.toFixed(3)))].map(Number).sort((a, b) => a - b);
    expect(faces[0]).toBe(-4750);
    expect(faces.at(-1)).toBe(4750);
    for (let at = 2; at < faces.length; at += 2) expect(faces[at]! - faces[at - 2]!).toBeLessThanOrEqual(2000);
    // A run too short for two posts, or too shallow for its rails, is drawn as its box.
    expect(slotFurnitureSurfaces(FORMS2, 'fence_wood', [150, 100, 1200])).toBeNull();
    expect(slotFurnitureSurfaces(FORMS2, 'fence_wood', [9500, 30, 1200])).toBeNull();
  });
});

/** The catalog the page bundles: v2's forms and a stall for a made place's stall slot. */
const FORMS3 = readStreetFurnitureForms(readFileSync('../assets/catalogs/world-kinds/street-furniture-form.v3.json', 'utf8'));

describe('a stall slot drawn as a counter and a cover on two end frames (catalog v3)', () => {
  // The island hamlet's vegetable stall: 2 m wide, 1 m deep, 2.2 m tall.
  const STALL = [2000, 1000, 2200] as const;

  it('reads v3 as v2 with a stall, and v2 still reads as made', () => {
    expect(FORMS3.version).toBe(3);
    expect([...FORMS3.byClass]).toEqual([...FORMS2.byClass]);
    expect([...FORMS3.bySlotLeaf.keys()]).toEqual(['bench', 'fence_wood', 'stall']);
    for (const leaf of ['bench', 'fence_wood']) expect(FORMS3.bySlotLeaf.get(leaf)).toEqual(FORMS2.bySlotLeaf.get(leaf));
  });

  it('draws a counter at its front, a post at each corner and a cover over it, inside its box, as closed solids facing out', () => {
    const surfaces = slotFurnitureSurfaces(FORMS3, 'stall', STALL)!;
    expect(surfaces.map((surface) => surface.role).sort()).toEqual(['object_primary', 'object_secondary']);
    expect(unpairedEdges(surfaces)).toEqual([]);
    expect(volume(surfaces)).toBeGreaterThan(0);
    const feet = new Set<string>();
    for (const surface of surfaces) {
      expect(pageNormals(surface).every(Number.isFinite)).toBe(true);
      for (let at = 0; at < surface.positions.length; at += 3) {
        const [x, y, z] = [surface.positions[at]!, surface.positions[at + 1]!, surface.positions[at + 2]!];
        expect(Math.abs(x)).toBeLessThanOrEqual(STALL[0] / 2 + 1e-6);
        expect(Math.abs(y)).toBeLessThanOrEqual(STALL[1] / 2 + 1e-6);
        expect(z).toBeGreaterThanOrEqual(-1e-6);
        expect(z).toBeLessThanOrEqual(STALL[2] + 1e-6);
        if (z === 0 && Math.abs(x) === STALL[0] / 2 && Math.abs(y) === STALL[1] / 2) feet.add(`${Math.sign(x)},${Math.sign(y)}`);
      }
    }
    // A post stands on the ground at each of the box's four corners.
    expect([...feet].sort()).toEqual(['-1,-1', '-1,1', '1,-1', '1,1']);
    const [top, front, , , cover] = slotFurnitureParts(FORMS3.bySlotLeaf.get('stall')!, STALL);
    // The counter: a top at 880 mm over the front half, on a panel at the front down to the ground.
    expect([top!.offsetZMm, top!.offsetYMm, top!.sizeYMm]).toEqual([880, 200, 560]);
    expect([front!.offsetZMm, front!.offsetYMm + front!.sizeYMm / 2]).toEqual([0, 480]);
    // The cover: across the whole box from 2.1 m to its top.
    expect([cover!.sizeXMm, cover!.sizeYMm, cover!.offsetZMm + cover!.sizeZMm]).toEqual([2000, 1000, 2200]);
    // A slot too low for the cover's inset panel is drawn as its box.
    expect(slotFurnitureSurfaces(FORMS3, 'stall', [2000, 1000, 150])).toBeNull();
  });
});

describe('a made place\'s fixture slot drawn by its leaf\'s form', () => {
  // A bench slot of Terraces on the bay: 2 m along its front, 500 mm deep, as tall as its seat.
  const BOX = [2000, 500, 450] as const;

  it('draws a bench slot inside its own box, as closed solids facing outward, and anything else as its box', () => {
    const form = forms.bySlotLeaf.get('bench')!;
    expect(form.parts).toEqual(['box', 'box', 'box']);
    const surfaces = slotFurnitureSurfaces(forms, 'bench', BOX)!;
    expect(surfaces.map((surface) => surface.role).sort()).toEqual(['object_primary', 'object_secondary']);
    for (const surface of surfaces) {
      for (let at = 0; at < surface.positions.length; at += 3) {
        expect(Math.abs(surface.positions[at]!)).toBeLessThanOrEqual(BOX[0] / 2 + 1e-6);
        expect(Math.abs(surface.positions[at + 1]!)).toBeLessThanOrEqual(BOX[1] / 2 + 1e-6);
        expect(surface.positions[at + 2]!).toBeGreaterThanOrEqual(-1e-6);
        expect(surface.positions[at + 2]!).toBeLessThanOrEqual(BOX[2] + 1e-6);
      }
    }
    expect(volume(surfaces)).toBeGreaterThan(0);
    // Its seat: four slats across 500 mm with three 20 mm gaps, 2 m long, 60 mm thick (133 thousandths of 450).
    const seat = slotFurnitureParts(form, BOX)[0]!;
    expect([seat.sizeXMm, seat.sizeYMm, seat.sizeZMm, seat.offsetZMm]).toEqual([2000, 500, 59.85, 390.15]);
    expect(slotFurnitureSurfaces(forms, 'rail', BOX)).toBeNull();
    // A slot too shallow for the slats and their gaps is drawn as its box.
    expect(slotFurnitureSurfaces(forms, 'bench', [2000, 40, 30])).toBeNull();
    expect(slotFurnitureSeatTops(forms, 'bench', [2000, 40, 30])).toBeNull();
  });

  it('gives where a body rests on a slatted seat: its whole top across the gaps, at the slats\' top, facing up', () => {
    const tops = slotFurnitureSeatTops(forms, 'bench', BOX)!;
    // One level slatted seat, two triangles, its slats' 2 m by 500 mm footprint at the box's top.
    expect(tops).toHaveLength(18);
    const corners = new Set<string>();
    for (let at = 0; at < tops.length; at += 3) {
      expect(tops[at + 2]).toBeCloseTo(BOX[2], 9);
      corners.add(`${tops[at]},${tops[at + 1]}`);
    }
    expect([...corners].sort()).toEqual(['-1000,-250', '-1000,250', '1000,-250', '1000,250']);
    for (let at = 0; at < tops.length; at += 9) {
      const [ax, ay, , bx, by, , cx, cy] = tops.slice(at, at + 9) as number[];
      expect((bx! - ax!) * (cy! - ay!) - (by! - ay!) * (cx! - ax!)).toBeGreaterThan(0);
    }
    expect(slotFurnitureSeatTops(forms, 'rail', BOX)).toBeNull();
  });

  it('refuses a slot part stated past its slot\'s box', () => {
    const document = JSON.parse(TEXT) as { slot_entries: { parts_permille: { offset_permille: number[]; size_permille: number[] }[] }[] };
    document.slot_entries[0]!.parts_permille[1]!.offset_permille = [-490, 0, 0];
    expect(() => readStreetFurnitureForms(JSON.stringify(document))).toThrow(/bench.parts_permille\[1\] reaches past its slot's box/);
  });
});

