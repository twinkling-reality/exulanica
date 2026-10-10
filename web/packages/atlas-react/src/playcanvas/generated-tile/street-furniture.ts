/**
 * A generated town's street furniture, as the town's own tile records state it.
 *
 * A town seats its people on its own furniture (a bench at the kerb), which is a record of a tile and
 * no object of a world's version. A page that draws a person sitting there needs where that
 * furniture stands, which way it faces and what it is made of, and all three are stated by the
 * record a tile container carries: its base point, an integer direction vector, and its parts in the
 * local frame where `+x` is that direction, `+y` is to its left and `+z` is up, each offset placing a
 * part's bottom centre (`exulanica.grammar.grammars.city.common.FormPart`). Nothing here names a
 * kind of furniture: the parts are the geometry, and a reader finds a seat among them by shape.
 *
 * The tile frame is x east, y north, z up in millimetres, and a town's society states positions
 * east and south, so a record's `y` and its direction's `dy` change sign on the way out, as
 * `tileToRenderer` does for the scene.
 */
import { decodeOwd } from '@exulanica/loom-tess/core';

/** The record kind a tile states its street furniture under. */
export const STREET_FURNITURE_KIND = 'city.street_furniture';

/** One part's bounding box in the furniture's own frame, millimetres. */
export interface StatedFurniturePart {
  readonly alongMm: number;
  readonly leftMm: number;
  readonly bottomMm: number;
  readonly sizeAlongMm: number;
  readonly sizeLeftMm: number;
  readonly heightMm: number;
}

/** A piece of street furniture in the society's plan: millimetres east and south. */
export interface StatedStreetFurniture {
  readonly identity: string;
  readonly eastMm: number;
  readonly southMm: number;
  /** Its direction, east and south; its parts' `left` is to the left of it. */
  readonly facing: readonly [number, number];
  readonly parts: readonly StatedFurniturePart[];
}

const whole = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/**
 * The street furniture one tile container states: every record of the kind, its own and the halo
 * copies it carries of its neighbours', each once by identity. A record that states no base point,
 * no direction or a part without its sizes is left out whole, never half read.
 */
export function streetFurnitureOf(bytes: Uint8Array): StatedStreetFurniture[] {
  const furniture = new Map<string, StatedStreetFurniture>();
  for (const record of decodeOwd(bytes).header.records) {
    if (record.kind !== STREET_FURNITURE_KIND || record.identity === '' || furniture.has(record.identity)) continue;
    const fields = record.fields;
    const x = whole(fields['x_mm']), y = whole(fields['y_mm']);
    const dx = whole(fields['facing_dx_mm']), dy = whole(fields['facing_dy_mm']);
    const stated = fields['parts'];
    if (x === null || y === null || dx === null || dy === null || (dx === 0 && dy === 0) || !Array.isArray(stated)) continue;
    const parts: StatedFurniturePart[] = [];
    for (const one of stated) {
      const part = one as { readonly [name: string]: unknown };
      const read = [
        whole(part['offset_x_mm']), whole(part['offset_y_mm']), whole(part['offset_z_mm']),
        whole(part['size_x_mm']), whole(part['size_y_mm']), whole(part['size_z_mm']),
      ];
      if (read.some((value) => value === null)) break;
      const [alongMm, leftMm, bottomMm, sizeAlongMm, sizeLeftMm, heightMm] = read as number[];
      parts.push({ alongMm: alongMm!, leftMm: leftMm!, bottomMm: bottomMm!, sizeAlongMm: sizeAlongMm!, sizeLeftMm: sizeLeftMm!, heightMm: heightMm! });
    }
    if (parts.length !== stated.length) continue;
    // North is the society's negative south, for the point and for the direction alike.
    furniture.set(record.identity, { identity: record.identity, eastMm: x, southMm: -y, facing: [dx, -dy], parts });
  }
  return [...furniture.values()];
}

/** The record kind a tile states a door under: where the footway meets it, and the curb it opens onto. */
export const ENTRANCE_KIND = 'city.entrance';

/** A door a person can reach from a footway, in the society's plan: millimetres east and south. */
export interface StatedDoor {
  readonly identity: string;
  readonly eastMm: number;
  readonly southMm: number;
}

/**
 * The doors one tile container states that open onto a footway: every entrance record's threshold,
 * its own and the halo copies it carries of its neighbours', each once by identity. A town's people
 * go in and come out at these, so walks begin and end there. A door that names no curb opens onto a
 * lot, not a footway, and is left out, as is a record that states no threshold.
 */
export function doorsOf(bytes: Uint8Array): StatedDoor[] {
  return doorsOfRecords(decodeOwd(bytes).header.records);
}

/** The same of a tile's records as read: `doorsOf` is this over a container's own. */
export function doorsOfRecords(
  records: readonly { readonly kind: string; readonly identity: string; readonly fields: { readonly [name: string]: unknown } }[],
): StatedDoor[] {
  const doors = new Map<string, StatedDoor>();
  for (const record of records) {
    if (record.kind !== ENTRANCE_KIND || record.identity === '' || doors.has(record.identity)) continue;
    const x = whole(record.fields['threshold_x_mm']), y = whole(record.fields['threshold_y_mm']);
    const curb = record.fields['approach_curb_identity'];
    if (x === null || y === null || !Array.isArray(curb) || curb.length === 0) continue;
    // North is the society's negative south.
    doors.set(record.identity, { identity: record.identity, eastMm: x, southMm: -y });
  }
  return [...doors.values()];
}

/** The record kind a tile states its street trees under: a base point and parts, facing east. */
export const STREET_TREE_KIND = 'city.street_tree';

/**
 * What a tile's street furniture and trees put in a sight line at a height: the plan rectangle, east
 * and south millimetres, of every part that stands across `heightMm` (its bottom at or below it, its
 * top at or above it), turned as its record faces. A bench, a bin and a tree's canopy do not cross a
 * standing person's eye height and are left out; a lamp post and a trunk do. Heights are read from
 * the parts and above each record's own base, so no kind of furniture is named here.
 */
export function sightBlockersOf(bytes: Uint8Array, heightMm: number): (readonly (readonly [number, number])[])[] {
  return sightBlockersOfRecords(decodeOwd(bytes).header.records, heightMm);
}

/** The same of a tile's records as read: `sightBlockersOf` is this over a container's own. */
export function sightBlockersOfRecords(
  records: readonly { readonly kind: string; readonly identity: string; readonly fields: { readonly [name: string]: unknown } }[],
  heightMm: number,
): (readonly (readonly [number, number])[])[] {
  const rings: (readonly (readonly [number, number])[])[] = [];
  const seen = new Set<string>();
  for (const record of records) {
    if ((record.kind !== STREET_FURNITURE_KIND && record.kind !== STREET_TREE_KIND) || record.identity === '') continue;
    const named = `${record.kind}:${record.identity}`;
    if (seen.has(named)) continue;
    seen.add(named);
    const fields = record.fields;
    const x = whole(fields['x_mm']), y = whole(fields['y_mm']);
    // A tree states no direction: its parts' frame faces east, as the tessellator reads it.
    const dx = fields['facing_dx_mm'] === undefined ? 1 : whole(fields['facing_dx_mm']);
    const dy = fields['facing_dx_mm'] === undefined ? 0 : whole(fields['facing_dy_mm']);
    const stated = fields['parts'];
    if (x === null || y === null || dx === null || dy === null || (dx === 0 && dy === 0) || !Array.isArray(stated)) continue;
    const length = Math.hypot(dx, dy);
    // In east and south: the direction, and to its left (left of (e, s) is (s, -e)).
    const along = [dx / length, -dy / length] as const;
    const left = [along[1], -along[0]] as const;
    for (const one of stated) {
      const part = one as { readonly [name: string]: unknown };
      const ox = whole(part['offset_x_mm']), oy = whole(part['offset_y_mm']), oz = whole(part['offset_z_mm']);
      const sx = whole(part['size_x_mm']), sy = whole(part['size_y_mm']), sz = whole(part['size_z_mm']);
      if (ox === null || oy === null || oz === null || sx === null || sy === null || sz === null) continue;
      if (oz > heightMm || oz + sz < heightMm) continue;
      const corner = (a: number, l: number): readonly [number, number] => [
        x + (ox + a) * along[0] + (oy + l) * left[0],
        -y + (ox + a) * along[1] + (oy + l) * left[1],
      ];
      rings.push([corner(-sx / 2, -sy / 2), corner(sx / 2, -sy / 2), corner(sx / 2, sy / 2), corner(-sx / 2, sy / 2)]);
    }
  }
  return rings;
}
