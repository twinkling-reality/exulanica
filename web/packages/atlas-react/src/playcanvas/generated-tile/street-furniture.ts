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
