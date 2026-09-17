/**
 * TEST-ONLY GEOMETRY. Never shipped, never a placeholder for a tile.
 *
 * A few metres of street built by hand so the materials and the look can be seen and measured
 * before the tessellator's first tile exists: a carriageway, a 150 mm kerb, a footway, and a wall
 * with a stone plinth, a recessed doorway with a metal door, and a projecting cornice. The three
 * junctions the architecture table names (kerb, doorway, cornice) are all here, which is the whole
 * reason for the shape.
 *
 * Coordinates: metres, +Y up, the street runs along X, the wall faces -Z. Surface coordinates are
 * millimetres in each set's placement convention: vertical surfaces measure `s` along the wall and
 * `t` downward from a datum; horizontal surfaces measure `s` along X and `t` across the run.
 */

export interface TestSurface {
  readonly name: string;
  readonly setId: string;
  readonly positions: number[];
  readonly normals: number[];
  readonly surfaceMm: number[];
  readonly indices: number[];
}

type V3 = readonly [number, number, number];

class Builder {
  readonly surfaces = new Map<string, TestSurface>();

  private surface(name: string, setId: string): TestSurface {
    let found = this.surfaces.get(name);
    if (found === undefined) {
      found = { name, setId, positions: [], normals: [], surfaceMm: [], indices: [] };
      this.surfaces.set(name, found);
    }
    return found;
  }

  /** A quad a b c d (counter-clockwise seen from the front) with its four surface coordinates. */
  quad(name: string, setId: string, corners: readonly [V3, V3, V3, V3], normal: V3, st: readonly [number, number][]): void {
    const target = this.surface(name, setId);
    const first = target.positions.length / 3;
    corners.forEach((corner, index) => {
      target.positions.push(...corner);
      target.normals.push(...normal);
      target.surfaceMm.push(...st[index]!);
    });
    target.indices.push(first, first + 1, first + 2, first, first + 2, first + 3);
  }

  /** A horizontal rectangle at height `y`, facing up. */
  floor(name: string, setId: string, x0: number, x1: number, z0: number, z1: number, y: number): void {
    const mm = (v: number): number => Math.round(v * 1000);
    this.quad(name, setId, [[x0, y, z1], [x1, y, z1], [x1, y, z0], [x0, y, z0]], [0, 1, 0],
      [[mm(x0), mm(z1)], [mm(x1), mm(z1)], [mm(x1), mm(z0)], [mm(x0), mm(z0)]]);
  }

  /** A vertical rectangle in the plane z = `z`, facing `facing` (-1 toward the street). */
  wallZ(name: string, setId: string, x0: number, x1: number, y0: number, y1: number, z: number, facing: 1 | -1): void {
    const mm = (v: number): number => Math.round(v * 1000);
    // Seen from -Z, +X is to the viewer's left, so s runs along -X there and the texture reads
    // left to right from the street. The corners wind counter-clockwise as seen from the front.
    const s = (x: number): number => (facing === -1 ? -mm(x) : mm(x));
    const t = (y: number): number => -mm(y);
    const a: V3 = facing === -1 ? [x1, y0, z] : [x0, y0, z];
    const b: V3 = facing === -1 ? [x0, y0, z] : [x1, y0, z];
    const c: V3 = facing === -1 ? [x0, y1, z] : [x1, y1, z];
    const d: V3 = facing === -1 ? [x1, y1, z] : [x0, y1, z];
    this.quad(name, setId, [a, b, c, d], [0, 0, facing],
      [[s(a[0]), t(y0)], [s(b[0]), t(y0)], [s(c[0]), t(y1)], [s(d[0]), t(y1)]]);
  }

  /** A vertical rectangle in the plane x = `x`, facing `facing`. */
  wallX(name: string, setId: string, z0: number, z1: number, y0: number, y1: number, x: number, facing: 1 | -1): void {
    const mm = (v: number): number => Math.round(v * 1000);
    const s = (z: number): number => (facing === 1 ? -mm(z) : mm(z));
    const t = (y: number): number => -mm(y);
    const a: V3 = facing === 1 ? [x, y0, z1] : [x, y0, z0];
    const b: V3 = facing === 1 ? [x, y0, z0] : [x, y0, z1];
    const c: V3 = facing === 1 ? [x, y1, z0] : [x, y1, z1];
    const d: V3 = facing === 1 ? [x, y1, z1] : [x, y1, z0];
    this.quad(name, setId, [a, b, c, d], [facing, 0, 0],
      [[s(a[2]), t(y0)], [s(b[2]), t(y0)], [s(c[2]), t(y1)], [s(d[2]), t(y1)]]);
  }

  /** A horizontal rectangle facing down (a soffit). */
  soffit(name: string, setId: string, x0: number, x1: number, z0: number, z1: number, y: number): void {
    const mm = (v: number): number => Math.round(v * 1000);
    this.quad(name, setId, [[x0, y, z0], [x1, y, z0], [x1, y, z1], [x0, y, z1]], [0, -1, 0],
      [[mm(x0), mm(z0)], [mm(x1), mm(z0)], [mm(x1), mm(z1)], [mm(x0), mm(z1)]]);
  }
}

export const KERB_HEIGHT_M = 0.15;
export const KERB_FACE_Z = -0.3;
export const WALL_Z = 3;
export const DOOR = { x0: 0.6, x1: 1.8, height: 2.4, depth: 0.4 } as const;
export const CORNICE = { y0: 6.7, y1: 7.0, projection: 0.5 } as const;
export const PLINTH_TOP_M = 0.9;
export const WALL = { x0: -6, x1: 6, top: 8 } as const;

export interface TestStreetSets {
  readonly wall: string;
  readonly plinth: string;
  readonly door: string;
  readonly cornice: string;
  readonly footway: string;
  readonly kerb: string;
  readonly carriageway: string;
}

/** The test street, one surface list per set. */
export function testStreet(sets: TestStreetSets): readonly TestSurface[] {
  const b = new Builder();
  const k = KERB_HEIGHT_M;
  // Road and kerb.
  b.floor('carriageway', sets.carriageway, -30, 30, -8, KERB_FACE_Z, 0);
  b.wallZ('kerb-face', sets.kerb, -30, 30, 0, k, KERB_FACE_Z, -1);
  b.floor('kerb-top', sets.kerb, -30, 30, KERB_FACE_Z, 0, k);
  b.floor('footway', sets.footway, -30, 30, 0, WALL_Z, k);
  // Wall with plinth, split around the doorway.
  const { x0: dx0, x1: dx1, height: dh, depth } = DOOR;
  for (const [x0, x1] of [[WALL.x0, dx0], [dx1, WALL.x1]] as const) {
    b.wallZ('plinth', sets.plinth, x0, x1, k, PLINTH_TOP_M, WALL_Z, -1);
    b.wallZ('wall', sets.wall, x0, x1, PLINTH_TOP_M, CORNICE.y0, WALL_Z, -1);
  }
  b.wallZ('wall', sets.wall, dx0, dx1, k + dh, CORNICE.y0, WALL_Z, -1);
  b.wallZ('wall', sets.wall, WALL.x0, WALL.x1, CORNICE.y1, WALL.top, WALL_Z, -1);
  // Doorway: reveals, head, threshold and the door itself.
  b.wallX('reveal', sets.plinth, WALL_Z, WALL_Z + depth, k, k + dh, dx0, 1);
  b.wallX('reveal', sets.plinth, WALL_Z, WALL_Z + depth, k, k + dh, dx1, -1);
  b.soffit('reveal', sets.plinth, dx0, dx1, WALL_Z, WALL_Z + depth, k + dh);
  b.floor('threshold', sets.plinth, dx0, dx1, WALL_Z, WALL_Z + depth, k);
  b.wallZ('door', sets.door, dx0, dx1, k, k + dh, WALL_Z + depth, -1);
  // Cornice: front, soffit, top.
  const cz = WALL_Z - CORNICE.projection;
  b.wallZ('cornice', sets.cornice, WALL.x0, WALL.x1, CORNICE.y0, CORNICE.y1, cz, -1);
  b.soffit('cornice', sets.cornice, WALL.x0, WALL.x1, cz, WALL_Z, CORNICE.y0);
  b.floor('cornice', sets.cornice, WALL.x0, WALL.x1, cz, WALL_Z, CORNICE.y1);
  b.wallX('cornice', sets.cornice, cz, WALL_Z, CORNICE.y0, CORNICE.y1, WALL.x0, -1);
  b.wallX('cornice', sets.cornice, cz, WALL_Z, CORNICE.y0, CORNICE.y1, WALL.x1, 1);
  return [...b.surfaces.values()];
}

/** One flat wall of one set, exactly one texture repeat square, facing -Z at z = 0. */
export function calibrationWall(setId: string, extentUMm: number, extentVMm: number): TestSurface {
  const b = new Builder();
  b.wallZ('calibration', setId, 0, extentUMm / 1000, 0, extentVMm / 1000, 0, -1);
  return [...b.surfaces.values()][0]!;
}

/** A row of unlit targets at the given distances for the fog measurement, each 2 m square. */
export function fogTargets(distances: readonly number[]): readonly TestSurface[] {
  const b = new Builder();
  for (const distance of distances) {
    b.wallZ(`fog-${distance}`, 'fog-target', -1, 1, 0.62, 2.62, distance, -1);
  }
  return [...b.surfaces.values()];
}
