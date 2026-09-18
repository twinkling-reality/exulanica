/**
 * The massing rule, held to what the records state by arithmetic of this test's own:
 *
 *   - WALLS CLOSE EVERY TIER: the wall area of a tier is its ring's perimeter times its height, so
 *     no edge is missed and none is drawn twice, and every wall corner is at a storey the tier
 *     covers.
 *   - THE ROOF IS WHAT IS LEFT: the horizontal area at a tier's top is the tier's ring less the
 *     ring standing on it and less its light wells, to within the carve's own millimetre.
 *   - A PARAPET STANDS ONLY WHERE THE DECK MEETS THE AIR: its length round a tier is that tier's
 *     perimeter less the part the ring above stands on.
 *   - A RIDGE ROOF RISES TO ITS STATED RIDGE: the summit is the wall top plus the rise, and the two
 *     gable triangles stand on the two edges the ridge runs between.
 *
 * The cases are the conformance tile's building, which has two tiers and two light wells, and the
 * shapes the corridor's generated street produces: a flat terrace block and a ridge roof.
 */
import { describe, expect, it } from 'vitest';
import { massingPieces, storeyFloorMm, tierTopMm } from '../src/core/massing.js';
import type { MassingFields, Tier } from '../src/core/massing.js';
import type { Plan } from '../src/core/integer-math.js';
import { fixtureObject, recordsOf } from './support.js';

const ringArea = (ring: readonly Plan[]): number => {
  const twice = ring.reduce((total, here, index) => {
    const next = ring[(index + 1) % ring.length]!;
    return total + (here[0] * next[1] - here[1] * next[0]);
  }, 0);
  return Math.abs(twice) / 2;
};

const perimeter = (ring: readonly Plan[]): number => ring.reduce((total, here, index) => {
  const next = ring[(index + 1) % ring.length]!;
  return total + Math.hypot(next[0] - here[0], next[1] - here[1]);
}, 0);

interface Measured {
  readonly horizontal: number;
  readonly vertical: Map<string, number>;
  readonly heights: number[];
}

/** Every piece's area by role, the horizontal ones in plan and the vertical ones as face area. */
function measure(fields: MassingFields, where: string): Measured {
  const vertical = new Map<string, number>();
  const heights: number[] = [];
  let horizontal = 0;
  for (const piece of massingPieces(fields, [], where)) {
    const surface = piece.surface!;
    for (let triangle = 0; triangle + 2 < piece.triangles.length; triangle += 3) {
      const corners = [0, 1, 2].map((corner) => {
        const vertex = piece.triangles[triangle + corner]!;
        return [piece.vertices[vertex * 3]!, piece.vertices[vertex * 3 + 1]!, piece.vertices[vertex * 3 + 2]!];
      });
      for (const corner of corners) heights.push(corner[2]!);
      const [a, b, c] = corners as [number[], number[], number[]];
      const edge = (from: number[], to: number[]): number[] => [to[0]! - from[0]!, to[1]! - from[1]!, to[2]! - from[2]!];
      const [u, v] = [edge(a, b), edge(a, c)];
      const cross = [
        u[1]! * v[2]! - u[2]! * v[1]!,
        u[2]! * v[0]! - u[0]! * v[2]!,
        u[0]! * v[1]! - u[1]! * v[0]!,
      ];
      const area = Math.hypot(...cross) / 2;
      if (surface.orientation === 'horizontal') {
        horizontal += area;
        continue;
      }
      vertical.set(surface.role, (vertical.get(surface.role) ?? 0) + area);
    }
  }
  return { horizontal, vertical, heights };
}

const conformanceMassing = (): MassingFields => recordsOf(fixtureObject(), 'city.massing')[0].fields as MassingFields;

/** A flat two-tier block, set back from its north edge above the third storey, as the corridor makes. */
function terraceBlock(): MassingFields {
  const low: Tier = {
    first_storey: 0,
    last_storey: 2,
    ring_mm: [[0, 0], [16000, 0], [16000, 24000], [0, 24000]],
    light_wells_mm: [],
    parapet_height_mm: 600,
  };
  const high: Tier = {
    first_storey: 3,
    last_storey: 4,
    ring_mm: [[0, 0], [16000, 0], [16000, 19000], [0, 19000]],
    light_wells_mm: [],
    parapet_height_mm: 900,
  };
  return {
    base_elevation_mm: 200,
    ground_storey_height_mm: 4500,
    upper_storey_height_mm: 3000,
    storeys: 5,
    tiers: [low, high],
    roof_form: 'flat',
    ridge_mm: [],
    roof_rise_mm: 0,
  };
}

describe('the massing rule', () => {
  it('walls every tier round its whole ring, once, between the storeys that tier covers', () => {
    const fields = terraceBlock();
    const measured = measure(fields, 'case');
    let walls = 0;
    for (const tier of fields.tiers) {
      walls += perimeter(tier.ring_mm) * (tierTopMm(fields, tier, 'case') - storeyFloorMm(fields, tier.first_storey, 'case'));
    }
    expect(measured.vertical.get('wall')).toBeCloseTo(walls, 6);
    // The ground storey is 4.5 m from the base, and the two tiers meet at the fourth floor.
    expect(storeyFloorMm(fields, 0, 'case')).toBe(200);
    expect(storeyFloorMm(fields, 1, 'case')).toBe(4700);
    expect(tierTopMm(fields, fields.tiers[0]!, 'case')).toBe(10700);
    expect(tierTopMm(fields, fields.tiers[1]!, 'case')).toBe(16700);
    expect(Math.min(...measured.heights)).toBe(200);
    // Nothing rises above the top tier's parapet.
    expect(Math.max(...measured.heights)).toBe(16700 + 900);
  });

  it('roofs a tier with what is left of it: the terrace, and the deck above', () => {
    const fields = terraceBlock();
    const [low, high] = fields.tiers as [Tier, Tier];
    const terrace = ringArea(low.ring_mm) - ringArea(high.ring_mm);
    expect(measure(fields, 'case').horizontal).toBeCloseTo(terrace + ringArea(high.ring_mm), 6);
    // Which is the whole footprint: a setback moves roof from one height to another, never loses it.
    expect(terrace + ringArea(high.ring_mm)).toBe(ringArea(low.ring_mm));
  });

  it('stands a parapet only where a deck meets the air, and not where the tier above stands', () => {
    const fields = terraceBlock();
    const [low, high] = fields.tiers as [Tier, Tier];
    const measured = measure(fields, 'case');
    // The lower tier's parapet runs round the terrace: its own perimeter less the three sides the
    // tier above stands on, which are the south edge and 19 m of each side.
    const covered = 16000 + 19000 + 19000;
    const parapet = (perimeter(low.ring_mm) - covered) * low.parapet_height_mm
      + perimeter(high.ring_mm) * high.parapet_height_mm;
    expect(measured.vertical.get('parapet')).toBeCloseTo(parapet, 6);
  });

  it('cuts light wells out of the roof and walls them, on the conformance tile\'s building', () => {
    const fields = conformanceMassing();
    const measured = measure(fields, 'case');
    const [low, high] = fields.tiers as [Tier, Tier];
    // A well in each tier, each cut out of that tier's own roof and walled down through it.
    expect(fields.tiers.map((tier) => tier.light_wells_mm.length)).toEqual([1, 1]);
    const height = (tier: Tier): number => tierTopMm(fields, tier, 'case') - storeyFloorMm(fields, tier.first_storey, 'case');
    const wells = fields.tiers.reduce(
      (total, tier) => total + tier.light_wells_mm.reduce((area, well) => area + ringArea(well), 0),
      0,
    );
    // The lower tier's well is under the tier above it, which already takes that ground, so only
    // the part of it outside that ring is missing from the roof. Here the upper ring holds it all.
    expect(measured.horizontal).toBeCloseTo(ringArea(low.ring_mm) - ringArea(high.light_wells_mm[0]!), -1);
    expect(wells).toBeGreaterThan(ringArea(high.light_wells_mm[0]!));
    const faces = fields.tiers.reduce(
      (total, tier) => total + height(tier) * (perimeter(tier.ring_mm)
        + tier.light_wells_mm.reduce((run, well) => run + perimeter(well), 0)),
      0,
    );
    expect(measured.vertical.get('wall')).toBeCloseTo(faces, 6);
  });

  it('rises to its stated ridge, with a gable on each edge the ridge runs between', () => {
    const ring: Plan[] = [[0, 0], [12000, 0], [12000, 8000], [0, 8000]];
    const fields: MassingFields = {
      base_elevation_mm: 0,
      ground_storey_height_mm: 4000,
      upper_storey_height_mm: 3000,
      storeys: 3,
      tiers: [{ first_storey: 0, last_storey: 2, ring_mm: ring, light_wells_mm: [], parapet_height_mm: 0 }],
      roof_form: 'ridge',
      // The floored midpoints of the two long edges: the ridge runs east to west.
      ridge_mm: [[6000, 0], [6000, 8000]],
      roof_rise_mm: 2500,
    };
    const measured = measure(fields, 'case');
    const top = 4000 + 2 * 3000;
    expect(Math.max(...measured.heights)).toBe(top + 2500);
    // The ridge runs north to south between the midpoints of the two 12 m edges, so each plane runs
    // the 8 m length of an eave edge up a slope of 6 m across and 2.5 m of rise.
    const slope = Math.hypot(6000, 2500);
    expect(measured.horizontal).toBeCloseTo(2 * 8000 * slope, 6);
    // A gable stands on each 12 m edge, rising to the ridge point above its midpoint.
    const gables = 2 * (12000 * 2500) / 2;
    expect(measured.vertical.get('wall')).toBeCloseTo(perimeter(ring) * top + gables, 6);
  });
});
