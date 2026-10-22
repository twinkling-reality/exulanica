/**
 * A tile's street furniture drawn by its forms instead of as baked.
 *
 * The bake draws a `city.street_furniture` record as its parts: boxes and prisms in the record's own
 * frame, turned by its facing and set on its base point (`loom-tess/src/core/form-parts.ts`). The street
 * furniture form catalog (`street-furniture-form.ts` in atlas-core) draws the same parts as made things,
 * inside the same boxes. This places what a form draws in the tile's payload frame exactly as the bake
 * places a part: `+x` along the facing, `+y` to its left, `+z` up from the base, then metres from the
 * projection's origin, `(mm - origin_mm) / 1000`, which is what a projection's float positions are.
 *
 * Only the drawing changes. The container, its digest, its picking, its walk and every count read
 * from it are the bake's; a record its class has no form for, or whose parts a form does not fit, is
 * left out of the result and drawn as baked.
 */
import { furnitureFormSurfaces, type FurnitureForms, type FurniturePart } from '@exulanica/atlas-core';
import { STREET_FURNITURE_KIND } from './street-furniture.js';

/** One role of a record, as a form draws it: payload metres in the tile frame, `s` and `t` in millimetres. */
export interface MadeFurnitureSurface {
  readonly role: string;
  /** Metres from the projection's origin, x east, y north, z up, three to a vertex. */
  readonly positions: readonly number[];
  readonly st: readonly number[];
  /** The form's own normals turned with it into the tile frame, unit, three to a vertex. */
  readonly normals: readonly number[];
  readonly indices: readonly number[];
}

interface StatedRecord {
  readonly kind: string;
  readonly fields: { readonly [name: string]: unknown };
}

/** What this reads of a drawn range of the tile runtime's: whether it is drawn, its record's kind and index. */
interface StatedRange {
  readonly state: string;
  readonly kind: string;
  readonly record: number;
}

const number = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const SHAPES = new Set(['box', 'prism', 'ellipsoid']);

function partsOf(stated: unknown): FurniturePart[] | null {
  if (!Array.isArray(stated)) return null;
  const parts: FurniturePart[] = [];
  for (const one of stated as readonly { readonly [name: string]: unknown }[]) {
    const shape = one['shape'];
    const role = one['surface_role'];
    const read = ['offset_x_mm', 'offset_y_mm', 'offset_z_mm', 'size_x_mm', 'size_y_mm', 'size_z_mm'].map((name) => number(one[name]));
    if (typeof shape !== 'string' || !SHAPES.has(shape) || typeof role !== 'string' || read.some((value) => value === null)) return null;
    const [offsetXMm, offsetYMm, offsetZMm, sizeXMm, sizeYMm, sizeZMm] = read as number[];
    parts.push({ shape: shape as FurniturePart['shape'], surfaceRole: role, offsetXMm: offsetXMm!, offsetYMm: offsetYMm!, offsetZMm: offsetZMm!, sizeXMm: sizeXMm!, sizeYMm: sizeYMm!, sizeZMm: sizeZMm! });
  }
  return parts;
}

/**
 * Every drawn street furniture range of a tile that its forms draw, with what they draw, keyed by the
 * range. `records` and `ranges` are the tile's own; `originMm` its projection's origin.
 */
export function madeStreetFurniture<Range extends StatedRange>(
  records: readonly StatedRecord[],
  ranges: readonly Range[],
  originMm: readonly number[],
  forms: FurnitureForms,
): Map<Range, MadeFurnitureSurface[]> {
  const made = new Map<Range, MadeFurnitureSurface[]>();
  if (originMm.length !== 3) return made;
  const [ox, oy, oz] = originMm as [number, number, number];
  for (const range of ranges) {
    if (range.state !== 'drawn' || range.kind !== STREET_FURNITURE_KIND) continue;
    const fields = records[range.record]?.fields;
    if (fields === undefined) continue;
    const furnitureClass = fields['furniture_class'];
    const x = number(fields['x_mm']), y = number(fields['y_mm']), z = number(fields['z_mm']);
    // A record that states no facing faces +x, as the bake reads it.
    const dx = fields['facing_dx_mm'] === undefined ? 1 : number(fields['facing_dx_mm']);
    const dy = fields['facing_dx_mm'] === undefined ? 0 : number(fields['facing_dy_mm']);
    const parts = partsOf(fields['parts']);
    if (typeof furnitureClass !== 'string' || x === null || y === null || z === null || dx === null || dy === null || parts === null) continue;
    const length = Math.hypot(dx, dy);
    if (length === 0) continue;
    const surfaces = furnitureFormSurfaces(forms, furnitureClass, parts);
    if (surfaces === null) continue;
    const [ux, uy] = [dx / length, dy / length];
    made.set(range, surfaces.map((surface) => {
      const positions: number[] = [];
      for (let at = 0; at < surface.positions.length; at += 3) {
        const along = surface.positions[at]!;
        const left = surface.positions[at + 1]!;
        const up = surface.positions[at + 2]!;
        positions.push(
          (x + along * ux - left * uy - ox) / 1000,
          (y + along * uy + left * ux - oy) / 1000,
          (z + up - oz) / 1000,
        );
      }
      const normals: number[] = [];
      for (let at = 0; at < surface.normals.length; at += 3) {
        const [along, left, up] = [surface.normals[at]!, surface.normals[at + 1]!, surface.normals[at + 2]!];
        normals.push(along * ux - left * uy, along * uy + left * ux, up);
      }
      return { role: surface.role, positions, st: surface.st, normals, indices: surface.indices };
    }));
  }
  return made;
}
