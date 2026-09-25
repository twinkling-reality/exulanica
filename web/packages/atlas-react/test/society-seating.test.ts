import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import {
  PLACE_MATCH_MM,
  SEAT_APPROACH_METRES,
  placeDrawing,
  seatApproach,
  type KindUse,
  type SeatingLayout,
  type SeatingObject,
} from '../src/playcanvas/society/seating.js';

/*
 * Where a person using an object is drawn, checked against places this server turned.
 *
 * `fixtures/society-seating.json` is written by tests/test_society_seating_fixture.py from the
 * server's own `destination_places` and the `use` the registry reads serve, never by hand, and that
 * test fails when the server would write something else. Here the page must find, from each turned
 * place, the catalog place it came from, at every yaw the fixture turns to.
 */

interface WireSeat { readonly position_mm: number[]; readonly faces: string }
interface WirePlace { readonly position_mm: number[]; readonly faces: string; readonly seat: WireSeat | null }
interface Case {
  readonly asset_key: string;
  readonly transform: { x_mm: number; y_mm: number; z_mm: number; yaw_microradians: number; scale_milli: number };
  readonly turned_places_mm: [number, number][];
  readonly use: { affordance: string; places: WirePlace[] | null };
}

const FIXTURE = JSON.parse(readFileSync(new URL('./fixtures/society-seating.json', import.meta.url), 'utf8')) as {
  readonly cases: readonly Case[];
};

const TARGET = 'authored:version:object:it:rest';

function useOf(wire: Case['use']): KindUse {
  return {
    affordance: wire.affordance,
    places: wire.places === null ? null : wire.places.map((place) => ({
      positionMm: place.position_mm as [number, number],
      faces: place.faces as never,
      seat: place.seat === null ? null : { positionMm: place.seat.position_mm as [number, number, number], faces: place.seat.faces as never },
    })),
  };
}

function objectOf(item: Case): SeatingObject {
  const t = item.transform;
  return { objectId: 'object:it', assetKey: item.asset_key, xMm: t.x_mm, yMm: t.y_mm, zMm: t.z_mm, yawMicroradians: t.yaw_microradians, scaleMilli: t.scale_milli };
}

function layoutOf(item: Case): SeatingLayout {
  return { uses: new Map([[item.asset_key, useOf(item.use)]]), objects: [objectOf(item)], targets: new Map([[TARGET, 'object:it']]) };
}

/** Where a full character facing `yaw` looks, in the region's east and south. */
const forward = (yaw: number) => [-Math.sin(yaw), -Math.cos(yaw)] as const;

describe('the place a person holds', () => {
  it('is found from every place the server turned, at every yaw, and from no point farther than rounding', () => {
    expect(FIXTURE.cases.length).toBe(30);
    let found = 0;
    for (const item of FIXTURE.cases) {
      const layout = layoutOf(item);
      item.turned_places_mm.forEach((point, index) => {
        const result = placeDrawing(layout, TARGET, point);
        expect(result.kind, `${item.asset_key} ${item.transform.yaw_microradians} ${index}`).toBe('place');
        if (result.kind === 'place') expect(result.drawing.placeIndex).toBe(index);
        found += 1;
        // Farther than the tolerance from the exact place, which the turned one is within the
        // square root of two of, nobody holds it: 3 mm on each axis is 4.2 mm, over 2.8 mm away.
        const away = placeDrawing(layout, TARGET, [point[0] + 3, point[1] + 3]);
        expect(away).toEqual({ kind: 'miss', reason: 'no-place-within-rounding' });
      });
    }
    // 3 bench, 2 table, 4 tree, 2 stall and 4 ledge places, at six yaws each.
    expect(found).toBe(15 * 6);
    expect(PLACE_MATCH_MM).toBeLessThan(2);
  });

  it('faces the kind across the place, and a seat faces the way the catalog says', () => {
    for (const item of FIXTURE.cases) {
      const layout = layoutOf(item);
      const centre = [item.transform.x_mm, item.transform.z_mm] as const;
      item.turned_places_mm.forEach((point) => {
        const result = placeDrawing(layout, TARGET, point);
        if (result.kind !== 'place') throw new Error('unmatched');
        const [fx, fz] = forward(result.drawing.facing);
        // Standing at a place, the person looks toward the object rather than away from it.
        expect(fx * (centre[0] - point[0]) + fz * (centre[1] - point[1])).toBeGreaterThan(0);
        const seat = result.drawing.seat;
        if (seat === null) return;
        const [sx, sz] = forward(seat.facing);
        const [ex, , ez] = seat.position.map((v) => v * 1000);
        if (item.asset_key === 'cc0.cafe-table') {
          // A chair faces the table.
          expect(sx * (centre[0] - ex!) + sz * (centre[1] - ez!)).toBeGreaterThan(0);
        } else {
          // A bench or a ledge faces out, toward the place in front of it.
          expect(sx * (point[0] - ex!) + sz * (point[1] - ez!)).toBeGreaterThan(0);
        }
      });
    }
  });

  it('puts the seat where the object drawn by the same transform has it', () => {
    // The renderer places an object's mesh by its region pose: position, yaw about +Y and scale,
    // with the part frame's [x, y, z] at the mesh's [x, z, -y].
    for (const item of FIXTURE.cases) {
      const t = item.transform;
      const entity = new pc.GraphNode('object');
      entity.setLocalPosition(t.x_mm / 1000, t.y_mm / 1000, t.z_mm / 1000);
      entity.setLocalEulerAngles(0, (t.yaw_microradians / 1_000_000) * (180 / Math.PI), 0);
      entity.setLocalScale(t.scale_milli / 1000, t.scale_milli / 1000, t.scale_milli / 1000);
      const matrix = entity.getWorldTransform();
      item.turned_places_mm.forEach((point, index) => {
        const result = placeDrawing(layoutOf(item), TARGET, point);
        const wire = item.use.places![index]!.seat;
        if (result.kind !== 'place' || wire === null) return;
        const [x, y, z] = wire.position_mm.map((v) => v / 1000);
        const drawn = matrix.transformPoint(new pc.Vec3(x!, z!, -y!));
        const [ex, ey, ez] = result.drawing.seat!.position;
        expect(Math.abs(drawn.x - ex) + Math.abs(drawn.y - ey) + Math.abs(drawn.z - ez)).toBeLessThan(1e-6);
      });
    }
  });

  it('names why a person is drawn as everyone is', () => {
    const item = FIXTURE.cases.find((held) => held.asset_key === 'cc0.bench')!;
    const layout = layoutOf(item);
    const point = item.turned_places_mm[0]!;
    expect(placeDrawing(layout, 'unknown', point)).toEqual({ kind: 'miss', reason: 'target-unknown' });
    expect(placeDrawing({ ...layout, targets: new Map([[TARGET, null]]) }, TARGET, point))
      .toEqual({ kind: 'miss', reason: 'target-has-no-object' });
    expect(placeDrawing({ ...layout, objects: [] }, TARGET, point)).toEqual({ kind: 'miss', reason: 'object-not-drawn' });
    expect(placeDrawing({ ...layout, uses: new Map() }, TARGET, point)).toEqual({ kind: 'miss', reason: 'kind-has-no-use' });
    const marker = new Map([[item.asset_key, { affordance: 'rest', places: null }]]);
    expect(placeDrawing({ ...layout, uses: marker }, TARGET, point)).toEqual({ kind: 'miss', reason: 'kind-states-no-places' });
  });

  it('is approached from the front when the place is before it, and from the side nearer the place otherwise', () => {
    // A seat at the origin facing -z (yaw 0): a place ahead of it is approached from the front.
    const [ax, az] = seatApproach([0, 0], 0, [0.1, -1]);
    expect(ax).toBeCloseTo(0, 12);
    expect(az).toBeCloseTo(-SEAT_APPROACH_METRES, 12);
    // A chair facing +x (yaw -pi/2) with its place off to its +z side: from that side, not across
    // the front, where the table is.
    const [x, z] = seatApproach([0, 0], -Math.PI / 2, [0.69, 1.14]);
    expect(x).toBeCloseTo(0, 12);
    expect(z).toBeCloseTo(SEAT_APPROACH_METRES, 12);
    const [, other] = seatApproach([0, 0], -Math.PI / 2, [0.69, -1.14]);
    expect(other).toBeCloseTo(-SEAT_APPROACH_METRES, 12);
  });
});
