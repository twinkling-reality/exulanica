/**
 * A single photograph's depth as a surface: the triangles joining neighbouring samples of the
 * grid the depth model unprojected, with those across a depth jump kept apart as seams.
 *
 * A point map from one photograph is a grid in disguise. MEASURED 2026-09-11 on the first personal
 * place: every one of 144,141 points reprojected through the header's own viewpoint onto a model
 * grid cell within 0.0001 of a cell centre, one point per cell, in row-major order, with the sky's
 * cells simply absent. So the grid can be rebuilt exactly from the points and the header, and the
 * surface needs nothing the file does not already say.
 *
 * Drawn as points, that grid reads as dots with holes between them, most visibly up close and at
 * grazing angles. Drawn as triangles between neighbours it reads as the surface the photograph
 * showed. The one thing a surface must not do is join a person to the ridge two hundred metres
 * behind them, which is what a naive triangulation does at every silhouette: those triangles are
 * long, thin sheets that point at the camera and exist nowhere.
 *
 * Except from exactly where the photograph was taken, where they are not sheets at all: seen down
 * the camera's own rays each covers one cell of the photograph. So triangles whose three depths
 * agree to within `DEPTH_JUMP_RATIO` are the surface, and the rest are returned separately as
 * seams, for the renderer to draw only while the visitor looks down nearly the camera's own line of
 * sight.
 *
 * The same holds for the band the depth producer leaves empty at a silhouette, which it drops as
 * unreliable. MEASURED 2026-09-11 on the first personal place: only 4 of 282,643 triangles crossed
 * a depth jump, and the pale outline round every person and the pale bars across the far snowfield
 * were runs of cells with no sample at all, a few cells wide. A run of at most `MAX_BRIDGED_CELLS`
 * between two real samples is bridged by triangles between those samples, and the bridge is a
 * seam. Nothing is invented: every bridge vertex is a measured sample, and what fills the band from
 * the camera is the interpolation between the edge of the person and the ground just behind them,
 * which is what the photograph's own soft edge was. A wider gap, such as the sky, stays empty.
 *
 * Null, meaning "draw points", whenever the file is not a grid in this sense: a producer that does
 * not unproject a regular grid, a header without a usable camera, or points that do not land on
 * cells. Refusing is always safe here, because points were what was drawn before.
 */

export interface DepthGridInput {
  readonly position: Float32Array;
  readonly header: {
    readonly pointCount: number;
    readonly modelImage: { readonly width: number; readonly height: number };
    readonly viewpoint: {
      readonly position: readonly [number, number, number];
      readonly forward: readonly [number, number, number];
      readonly up: readonly [number, number, number];
      readonly fovYDeg: number;
      readonly aspect: number;
    };
  };
}

/** Neighbouring depths further apart than this ratio are a silhouette, not a surface. */
export const DEPTH_JUMP_RATIO = 1.12;
/** The longest run of empty cells bridged between two real samples; see the module comment. */
export const MAX_BRIDGED_CELLS = 6;
/** How far from a cell centre, in cells, a point may reproject and still be that cell's sample. */
const CELL_TOLERANCE = 0.05;

/** Triangle indices into the point order, three per triangle. */
export interface DepthSurface {
  /** Neighbours whose depths agree: the surface the photograph showed. */
  readonly surface: Uint32Array;
  /** Neighbours across a depth jump: correct only when seen from the camera's own position. */
  readonly seams: Uint32Array;
}

/** The surface and its seams, or null to draw points instead. */
export function depthSurfaceIndices(map: DepthGridInput): DepthSurface | null {
  const { width, height } = map.header.modelImage;
  const { position: eye, forward, up, fovYDeg, aspect } = map.header.viewpoint;
  const count = map.header.pointCount;
  // The grid is only rebuilt in the camera frame the format declares for a single photograph.
  if (forward[0] !== 0 || forward[1] !== 0 || forward[2] !== -1) return null;
  if (up[0] !== 0 || up[1] !== 1 || up[2] !== 0) return null;
  const tanY = Math.tan((fovYDeg * Math.PI) / 360);
  const tanX = tanY * aspect;
  if (!(tanY > 0) || !(tanX > 0) || !Number.isFinite(tanX) || !(width > 1) || !(height > 1)) return null;
  if (map.position.length < count * 3) return null;

  const cell = new Int32Array(width * height).fill(-1);
  const depth = new Float32Array(count);
  for (let i = 0; i < count; i += 1) {
    const x = map.position[i * 3]! - eye[0];
    const y = map.position[i * 3 + 1]! - eye[1];
    const d = -(map.position[i * 3 + 2]! - eye[2]);
    if (!(d > 0)) return null;
    const column = ((x / (d * tanX) + 1) / 2) * width - 0.5;
    const row = ((1 - y / (d * tanY)) / 2) * height - 0.5;
    const c = Math.round(column);
    const r = Math.round(row);
    if (Math.abs(column - c) > CELL_TOLERANCE || Math.abs(row - r) > CELL_TOLERANCE) return null;
    if (c < 0 || c >= width || r < 0 || r >= height) return null;
    const at = r * width + c;
    if (cell[at] !== -1) return null;
    cell[at] = i;
    depth[i] = d;
  }

  const surface: number[] = [];
  const seams: number[] = [];
  const add = (a: number, b: number, c: number): void => {
    if (a < 0 || b < 0 || c < 0) return;
    const da = depth[a]!;
    const db = depth[b]!;
    const dc = depth[c]!;
    (Math.max(da, db, dc) <= DEPTH_JUMP_RATIO * Math.min(da, db, dc) ? surface : seams).push(a, b, c);
  };
  for (let r = 0; r + 1 < height; r += 1) {
    for (let c = 0; c + 1 < width; c += 1) {
      const a = cell[r * width + c]!;
      const b = cell[r * width + c + 1]!;
      const below = cell[(r + 1) * width + c]!;
      const diagonal = cell[(r + 1) * width + c + 1]!;
      add(a, below, b);
      add(b, below, diagonal);
    }
  }
  // Bridges across short empty runs, along rows and then along columns. Each needs the same two
  // endpoint samples in the neighbouring row (or column) so the bridge is a quad of real samples.
  const at = (r: number, c: number): number => cell[r * width + c]!;
  const nextPresent = (from: number, limit: number, present: (k: number) => boolean): number => {
    for (let k = from; k <= limit; k += 1) if (present(k)) return k;
    return -1;
  };
  for (let r = 0; r + 1 < height; r += 1) {
    for (let c = 0; c + 2 < width; c += 1) {
      if (at(r, c) < 0 || at(r, c + 1) >= 0) continue;
      const end = nextPresent(c + 2, Math.min(width - 1, c + 1 + MAX_BRIDGED_CELLS), (k) => at(r, k) >= 0);
      if (end < 0 || at(r + 1, c) < 0 || at(r + 1, end) < 0) continue;
      seams.push(at(r, c), at(r + 1, c), at(r, end), at(r, end), at(r + 1, c), at(r + 1, end));
    }
  }
  for (let c = 0; c + 1 < width; c += 1) {
    for (let r = 0; r + 2 < height; r += 1) {
      if (at(r, c) < 0 || at(r + 1, c) >= 0) continue;
      const end = nextPresent(r + 2, Math.min(height - 1, r + 1 + MAX_BRIDGED_CELLS), (k) => at(k, c) >= 0);
      if (end < 0 || at(r, c + 1) < 0 || at(end, c + 1) < 0) continue;
      seams.push(at(r, c), at(end, c), at(r, c + 1), at(r, c + 1), at(end, c), at(end, c + 1));
    }
  }
  if (surface.length + seams.length === 0) return null;
  return { surface: Uint32Array.from(surface), seams: Uint32Array.from(seams) };
}
