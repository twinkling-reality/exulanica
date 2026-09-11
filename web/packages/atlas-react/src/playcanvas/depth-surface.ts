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
 * between two real samples is bridged by triangles between those samples, and every bridge is a
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

  // Each pair of neighbouring rows is zipped into one strip: walk the present samples of both rows
  // together and join the current pair to whichever row's next sample comes first. On a complete
  // grid this is exactly the two triangles per cell a regular triangulation makes. Across a gap it
  // fans between whatever real samples stand on either side, however ragged the gap's edges are,
  // which a quad-per-run bridge cannot do: MEASURED 2026-09-11, bridging only runs whose ends
  // matched in the next row left alternate rows unbridged and drew a comb round every person.
  const surface: number[] = [];
  const seams: number[] = [];
  const rows: number[][] = [];
  for (let r = 0; r < height; r += 1) {
    const present: number[] = [];
    for (let c = 0; c < width; c += 1) if (cell[r * width + c]! >= 0) present.push(c);
    rows.push(present);
  }
  const add = (r0: number, c0: number, r1: number, c1: number, r2: number, c2: number): void => {
    const span = Math.max(c0, c1, c2) - Math.min(c0, c1, c2);
    if (span > MAX_BRIDGED_CELLS + 1) return;
    const a = cell[r0 * width + c0]!;
    const b = cell[r1 * width + c1]!;
    const c = cell[r2 * width + c2]!;
    const da = depth[a]!;
    const db = depth[b]!;
    const dc = depth[c]!;
    const continuous = span <= 1 && Math.max(da, db, dc) <= DEPTH_JUMP_RATIO * Math.min(da, db, dc);
    (continuous ? surface : seams).push(a, b, c);
  };
  // `first` and `second` are the present positions along two neighbouring lines of the grid, and
  // `emit(a, b, c)` receives three [line, position] pairs.
  const zip = (first: number[], second: number[], emit: (a: [0 | 1, number], b: [0 | 1, number], c: [0 | 1, number]) => void): void => {
    if (first.length === 0 || second.length === 0) return;
    let i = 0;
    let j = 0;
    while (i < first.length - 1 || j < second.length - 1) {
      const advanceFirst = j === second.length - 1
        || (i < first.length - 1 && first[i + 1]! <= second[j + 1]!);
      if (advanceFirst) {
        emit([0, first[i]!], [1, second[j]!], [0, first[i + 1]!]);
        i += 1;
      } else {
        emit([0, first[i]!], [1, second[j]!], [1, second[j + 1]!]);
        j += 1;
      }
    }
  };
  for (let r = 0; r + 1 < height; r += 1) {
    zip(rows[r]!, rows[r + 1]!, (a, b, c) => add(r + a[0], a[1], r + b[0], b[1], r + c[0], c[1]));
  }
  // Down the columns as well, for the gaps that run across the photograph: the top of a head, a
  // band of far ground the producer dropped. Only the triangles that bridge such a gap are kept,
  // because every triangle of continuous surface was already made by the rows.
  const columns: number[][] = [];
  for (let c = 0; c < width; c += 1) {
    const present: number[] = [];
    for (let r = 0; r < height; r += 1) if (cell[r * width + c]! >= 0) present.push(r);
    columns.push(present);
  }
  for (let c = 0; c + 1 < width; c += 1) {
    zip(columns[c]!, columns[c + 1]!, (a, b, d) => {
      if (Math.max(a[1], b[1], d[1]) - Math.min(a[1], b[1], d[1]) <= 1) return;
      if (Math.max(a[1], b[1], d[1]) - Math.min(a[1], b[1], d[1]) > MAX_BRIDGED_CELLS + 1) return;
      seams.push(
        cell[a[1] * width + c + a[0]]!,
        cell[b[1] * width + c + b[0]]!,
        cell[d[1] * width + c + d[0]]!,
      );
    });
  }
  if (surface.length + seams.length === 0) return null;
  return { surface: Uint32Array.from(surface), seams: Uint32Array.from(seams) };
}
