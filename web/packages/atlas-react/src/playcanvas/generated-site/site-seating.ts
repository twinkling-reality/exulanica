import * as pc from 'playcanvas';
import type { FixtureSeat } from '../society/seating.js';
import type { StructuredSiteDrawing } from './site-drawing.js';
import type { DrawnSiteSlots } from './site-primitives.js';

export interface SeatGeometry { readonly triangles: readonly number[]; readonly normals: readonly number[] }
export function seatGeometry(positions: readonly number[], normals: readonly number[]): SeatGeometry {
  return Object.freeze({ triangles: Object.freeze([...positions]), normals: Object.freeze([...normals]) });
}
const EMPTY: SeatGeometry = seatGeometry([], []);

/** Actual primitive triangles in the site root's frame, after dressing and texture mesh replacement, with a slatted seat's top. */
function primitiveTriangles(drawn: DrawnSiteSlots, identity: string): SeatGeometry {
  const entity = drawn.entities.get(identity);
  if (entity === undefined || !entity.enabled) return EMPTY;
  const shape = entity.findByName(`${identity}:shape`) as pc.Entity | null;
  if (shape === null || !shape.enabled) return EMPTY;
  const rootInverse = new pc.Mat4().copy(drawn.root.getWorldTransform()).invert();
  const transform = new pc.Mat4().mul2(rootInverse, shape.getWorldTransform());
  const point = new pc.Vec3();
  const positions: number[] = [], normals: number[] = [];
  for (const instance of shape.render?.meshInstances ?? []) {
    const vertices: number[] = [], vertexNormals: number[] = [], indices: number[] = [];
    instance.mesh.getPositions(vertices);
    instance.mesh.getNormals(vertexNormals);
    instance.mesh.getIndices(indices);
    for (const index of indices) {
      point.set(vertices[index * 3]!, vertices[index * 3 + 1]!, vertices[index * 3 + 2]!);
      transform.transformPoint(point, point);
      positions.push(point.x, point.y, point.z);
      point.set(vertexNormals[index * 3]!, vertexNormals[index * 3 + 1]!, vertexNormals[index * 3 + 2]!);
      transform.transformVector(point, point).normalize();
      normals.push(point.x, point.y, point.z);
    }
  }
  // A seat drawn as slats rests a body across its gaps, at the slats' own top (`DrawnSiteSlots.seatTops`).
  const tops = drawn.seatTops?.get(identity) ?? [];
  for (let at = 0; at + 2 < tops.length; at += 3) {
    point.set(tops[at]!, tops[at + 1]!, tops[at + 2]!);
    transform.transformPoint(point, point);
    positions.push(point.x, point.y, point.z);
    point.set(0, 1, 0);
    transform.transformVector(point, point).normalize();
    normals.push(point.x, point.y, point.z);
  }
  return seatGeometry(positions, normals);
}

/** Declared seat identity stays present even when its drawn geometry cannot establish contact. */
export function drawnSiteSeats(
  drawing: StructuredSiteDrawing,
  drawn: DrawnSiteSlots,
  modules: ReadonlyMap<string, SeatGeometry> = new Map(),
): readonly FixtureSeat[] {
  return Object.freeze(drawing.seats.map(seat => {
    const slot = drawing.slots.find(one => one.identity === seat.identity);
    return Object.freeze({
      objectId: seat.identity,
      ...(modules.get(seat.identity) ?? primitiveTriangles(drawn, seat.identity)),
      heightHintM: ((slot?.positionMm[2] ?? 0) + seat.seatHeightMm) / 1000,
      // Same human-seat presentation ceiling as site_drawing.SEAT_HEIGHT_MAXIMUM_MM.
      maximumHeightM: ((slot?.positionMm[2] ?? 0) + 460) / 1000,
      facing: (slot?.yawQuarterTurns ?? 0) * Math.PI / 2,
    });
  }));
}
