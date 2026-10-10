import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { streetSeatDrawing, type StreetFurniture, type StreetFurniturePart } from '../src/playcanvas/society/seating.js';

/*
 * A town seats its people on its own street furniture. The bench here is the one the city grammar
 * ships (assets/catalogs/street-furniture.v2.json), part for part, so what a seat's height is and
 * which side its back stands on are read from that catalog and from the grammar's frame rule
 * (local +x the way it faces, +y to its left, +z up, an offset placing a part's bottom centre),
 * never from the code under test. A town's society puts a bench's two sitters 350 mm either side of
 * its base point along its direction (exulanica/world/society_city_place.py: half the 700 mm
 * standing spacing).
 */
interface CatalogPart {
  readonly offset_x_mm: number; readonly offset_y_mm: number; readonly offset_z_mm: number;
  readonly size_x_mm: number; readonly size_y_mm: number; readonly size_z_mm: number;
}
// Tests run from web/.
const CATALOG = JSON.parse(readFileSync(resolve('../assets/catalogs/street-furniture.v2.json'), 'utf8')) as {
  entries: { key: string; parts: CatalogPart[] }[];
};
const BENCH_PARTS: StreetFurniturePart[] = CATALOG.entries.find((entry) => entry.key === 'bench')!.parts.map((part) => ({
  alongMm: part.offset_x_mm, leftMm: part.offset_y_mm, bottomMm: part.offset_z_mm,
  sizeAlongMm: part.size_x_mm, sizeLeftMm: part.size_y_mm, heightMm: part.size_z_mm,
}));
/** The catalog's seat board is 60 mm thick on 420 mm legs: its top is 480 mm up. */
const SEAT_TOP_METRES = 0.48;
const SEAT_ASIDE_MM = 350;

const bench = (eastMm: number, southMm: number, facing: readonly [number, number]): StreetFurniture => ({
  identity: 'bench-1', eastMm, southMm, facing, parts: BENCH_PARTS,
});
/** Which way a yaw looks in the plan, east and south: forward is (-sin, -cos). */
const looks = (yaw: number) => [-Math.sin(yaw), -Math.cos(yaw)] as const;

describe('a seat on a town\'s street furniture', () => {
  it('reads the catalog bench as the catalog states it', () => {
    // Positive control for everything below: a seat board with a back standing behind it, to the right.
    const tops = BENCH_PARTS.map((part) => part.bottomMm + part.heightMm);
    expect(Math.max(...tops)).toBe(900);
    expect(BENCH_PARTS.filter((part) => part.bottomMm + part.heightMm === 480)).toHaveLength(1);
    expect(BENCH_PARTS.find((part) => part.bottomMm + part.heightMm === 900)!.leftMm).toBe(-200);
  });

  it('sits a person at the seat board\'s top, where they are, with their back to the backrest', () => {
    // Facing east: left of east is north, so the back, 200 mm to the right, stands to the south.
    const found = streetSeatDrawing([bench(10_000, -20_000, [1, 0])], [10_000 + SEAT_ASIDE_MM, -20_000])!;
    expect(found.seat!.position[0]).toBeCloseTo(10.35, 9);
    expect(found.seat!.position[1]).toBeCloseTo(SEAT_TOP_METRES, 9);
    expect(found.seat!.position[2]).toBeCloseTo(-20, 9);
    const [east, south] = looks(found.seat!.facing);
    expect(east).toBeCloseTo(0, 9);
    expect(south).toBeCloseTo(-1, 9);
    expect(found.facing).toBe(found.seat!.facing);
    expect(found.facesAsHeld).toBeUndefined();
  });

  it('turns with the bench: facing north its sitters look west, facing west they look south', () => {
    // North is negative south. Left of north is west; left of west is south.
    const north = streetSeatDrawing([bench(0, 0, [0, -7])], [0, SEAT_ASIDE_MM])!;
    expect(looks(north.seat!.facing)[0]).toBeCloseTo(-1, 9);
    expect(looks(north.seat!.facing)[1]).toBeCloseTo(0, 9);
    const west = streetSeatDrawing([bench(0, 0, [-3, 0])], [-SEAT_ASIDE_MM, 0])!;
    expect(looks(west.seat!.facing)[0]).toBeCloseTo(0, 9);
    expect(looks(west.seat!.facing)[1]).toBeCloseTo(1, 9);
  });

  it('holds on a bench that faces no axis', () => {
    // A 3-4-5 direction, east and south: its left is (4, -3) / 5.
    const found = streetSeatDrawing([bench(1_000, 2_000, [3, 4])], [1_000 + 0.6 * SEAT_ASIDE_MM, 2_000 + 0.8 * SEAT_ASIDE_MM])!;
    expect(found.seat!.position[1]).toBeCloseTo(SEAT_TOP_METRES, 9);
    expect(looks(found.seat!.facing)[0]).toBeCloseTo(0.8, 9);
    expect(looks(found.seat!.facing)[1]).toBeCloseTo(-0.6, 9);
  });

  it('tells two sitters on one bench apart and finds neither off it', () => {
    const town = [bench(0, 0, [1, 0])];
    const one = streetSeatDrawing(town, [-SEAT_ASIDE_MM, 0])!;
    const other = streetSeatDrawing(town, [SEAT_ASIDE_MM, 0])!;
    expect(one.objectId).toBe('street-furniture:bench-1');
    expect(other.objectId).toBe(one.objectId);
    expect(one.placeIndex).not.toBe(other.placeIndex);
    // The board is 1.8 m by 0.45 m: a metre past its end, and half a metre in front, are the footway.
    expect(streetSeatDrawing(town, [1_900, 0])).toBeNull();
    expect(streetSeatDrawing(town, [0, -500])).toBeNull();
    expect(streetSeatDrawing([], [0, 0])).toBeNull();
  });

  it('sits a person on a seat with no back facing as they already did', () => {
    const ledge: StreetFurniture = {
      identity: 'ledge', eastMm: 0, southMm: 0, facing: [1, 0],
      parts: [{ alongMm: 0, leftMm: 0, bottomMm: 0, sizeAlongMm: 2_000, sizeLeftMm: 500, heightMm: 450 }],
    };
    const found = streetSeatDrawing([ledge], [300, 0])!;
    expect(found.seat!.position[1]).toBeCloseTo(0.45, 9);
    expect(found.facesAsHeld).toBe(true);
  });

  it('takes the highest part under a person as the seat', () => {
    // Over a leg (700 mm along) the board above it is the seat, not the leg's own top at 420 mm.
    const found = streetSeatDrawing([bench(0, 0, [1, 0])], [700, 0])!;
    expect(found.seat!.position[1]).toBeCloseTo(SEAT_TOP_METRES, 9);
  });
});
