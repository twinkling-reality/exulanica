/**
 * A drawn surface's samples for the data view, taken for the eye. Pure, so verify-data-view-things.mjs checks it in
 * Node; world-data-view.ts draws them.
 *
 * Every surface carries about as many points to the square pixel as the next, near or far: the ground at the eye's
 * feet as many as the street further out, a near trunk as many as a far wall. A surface needs samples where it is
 * near the eye and faces it, so samples are taken for an eye: each triangle of a surface (split, once, until no side
 * is long for its distance) carries its own fixed sequence of samples, the R2 sequence from its own seed, and the
 * i-th of them is first drawn at the density (i + u) / area, u its triangle's own offset in (0, 1]. An eye takes as
 * many of the sequence as the triangle's distance and angle to it ask for, and the point shader draws each sample
 * once its density is reached where the eye then stands (point-shader.ts, uDataViewScreen). A sample's place and
 * density are its triangle's, never the eye's, so samples taken for one eye are the same samples for any other, and
 * a set taken again as the eye moves draws exactly what the set before it drew where both reach.
 */

/** The R2 sequence's steps: the most even spread of a sequence over the unit square, at every length. */
const R2 = Object.freeze([0.7548776662466927, 0.5698402909980532]);

/** An unsigned 32-bit hash (lowbias32): the seed of every triangle's sequence and offset. */
export function mix32(value) {
  let x = value >>> 0;
  x ^= x >>> 16; x = Math.imul(x, 0x7feb352d) >>> 0;
  x ^= x >>> 15; x = Math.imul(x, 0x846ca68b) >>> 0;
  x ^= x >>> 16;
  return x >>> 0;
}

/** A hash as a number in (0, 1). */
const unit = (value) => (mix32(value) + 0.5) / 4294967296;
const length3 = (x, y, z) => Math.sqrt(x * x + y * y + z * z);

/**
 * How a session splits its surfaces' triangles: each until no side is longer than `fraction` of its distance from
 * `at` (the eye the data view opened at), and never below `least` metres. Fixed for the session, so a triangle's
 * pieces, and with them its samples, never depend on where the eye goes.
 */
export const SPLIT = Object.freeze({ fraction: 0.2, least: 0.75 });

/**
 * The density, in samples to the square metre, that a part of a surface needs for an eye that may stand up to
 * `slack` metres nearer, and turned up to `slack` metres' worth further toward it, than `distance` and `facing` say:
 * `density` points to the square pixel at `pixels` pixels to the radian, the part counted as facing the eye by at
 * least `facingFloor` and as no nearer than `nearest` metres, and as seen at the edge of the view's cone (`cone` its
 * cosine), where the screen spreads it furthest, since the eye may turn any way.
 */
export function neededDensity({ distance, facing, slack, pixels, density, facingFloor, nearest, cone }) {
  const near = Math.max(nearest, distance - slack);
  // An eye `slack` metres away from here sees the part from at most asin(slack / distance) further round.
  const swing = distance > slack ? Math.asin(slack / distance) : Math.PI / 2;
  const turned = Math.min(1, Math.max(facingFloor, Math.cos(Math.max(0, Math.acos(Math.min(1, facing)) - swing))));
  return (density * pixels * pixels * turned) / (near * near * cone * cone * cone);
}

/** How many of a triangle's sequence a density takes: those first drawn at or below it. */
export function takenCount(area, offset, density) {
  const reach = area * density;
  return reach >= offset ? Math.floor(reach - offset) + 1 : 0;
}

/**
 * The samples an eye needs of one drawn surface, grouped by the kind of record each stands on.
 * `surface`: { positions, indices (empty for an unindexed list), matrix (column-major, local to world), key (an
 * integer naming the surface, for its triangles' seeds), kind(x, y, z) (the kind a world point stands on), hidden(x,
 * y, z) (optional: true where a part no wider than 64 m centred there is never seen) }.
 * `eye`: { at (world), slack, pixels, density, facingFloor, nearest, cone, within (only triangles nearer than this,
 * in metres, Infinity for all), fixed (a moving thing's: every part sampled as if facing the eye from `nearest`) }. `split`: { at, fraction, least } (SPLIT and the eye the session opened at).
 * `triangles`: the triangle indices to look at, or null for every one. `most`: the most samples any one triangle
 * gives. Answers a Map of kind to { positions (local, three to a sample), normals (local, unit), densities } and the
 * count of samples taken.
 */
export function surfaceSamples(surface, eye, split, triangles = null, most = 60_000) {
  const { positions, indices, matrix: m, key, kind, hidden = null } = surface;
  const groups = new Map();
  let count = 0;
  const vertexCount = Math.floor(positions.length / 3);
  const triangleCount = Math.floor((indices.length > 0 ? indices.length : vertexCount) / 3);
  const corner = indices.length > 0 ? (at) => indices[at] : (at) => at;
  const [ex, ey, ez] = eye.at;
  const [sx, sy, sz] = split.at;
  const world = (x, y, z, out) => {
    out[0] = m[0] * x + m[4] * y + m[8] * z + m[12];
    out[1] = m[1] * x + m[5] * y + m[9] * z + m[13];
    out[2] = m[2] * x + m[6] * y + m[10] * z + m[14];
    return out;
  };
  const wa = [0, 0, 0], wb = [0, 0, 0], wc = [0, 0, 0];
  const groupOf = (name) => {
    let group = groups.get(name);
    if (group === undefined) { group = { positions: [], normals: [], densities: [] }; groups.set(name, group); }
    return group;
  };

  /** One piece of a triangle (local corners), its seed, and how far it may still be split. */
  const piece = (ax, ay, az, bx, by, bz, cx, cy, cz, seed, depth) => {
    world(ax, ay, az, wa); world(bx, by, bz, wb); world(cx, cy, cz, wc);
    const gx = (wa[0] + wb[0] + wc[0]) / 3, gy = (wa[1] + wb[1] + wc[1]) / 3, gz = (wa[2] + wb[2] + wc[2]) / 3;
    const ab = length3(wb[0] - wa[0], wb[1] - wa[1], wb[2] - wa[2]);
    const bc = length3(wc[0] - wb[0], wc[1] - wb[1], wc[2] - wb[2]);
    const ca = length3(wa[0] - wc[0], wa[1] - wc[1], wa[2] - wc[2]);
    const longest = Math.max(ab, bc, ca);
    // A part the surface says nothing sees (the land's backdrop under the town's own land) has no samples.
    if (hidden !== null && longest <= 2 * split.least + 64 && hidden(gx, gy, gz)) return;
    // Split, at the middle of its longest side, while that side is long for its distance from where the session opened.
    if (depth > 0 && longest > Math.max(split.least, split.fraction * length3(gx - sx, gy - sy, gz - sz))) {
      const first = mix32(seed ^ 0x68e31da4), second = mix32(seed ^ 0xb5297a4d);
      if (longest === ab) {
        const mx = (ax + bx) / 2, my = (ay + by) / 2, mz = (az + bz) / 2;
        piece(ax, ay, az, mx, my, mz, cx, cy, cz, first, depth - 1);
        piece(mx, my, mz, bx, by, bz, cx, cy, cz, second, depth - 1);
      } else if (longest === bc) {
        const mx = (bx + cx) / 2, my = (by + cy) / 2, mz = (bz + cz) / 2;
        piece(ax, ay, az, bx, by, bz, mx, my, mz, first, depth - 1);
        piece(ax, ay, az, mx, my, mz, cx, cy, cz, second, depth - 1);
      } else {
        const mx = (cx + ax) / 2, my = (cy + ay) / 2, mz = (cz + az) / 2;
        piece(ax, ay, az, bx, by, bz, mx, my, mz, first, depth - 1);
        piece(mx, my, mz, bx, by, bz, cx, cy, cz, second, depth - 1);
      }
      return;
    }
    // Its distance from the eye: no nearer than its middle less its reach.
    const reach = Math.max(length3(wa[0] - gx, wa[1] - gy, wa[2] - gz), length3(wb[0] - gx, wb[1] - gy, wb[2] - gz), length3(wc[0] - gx, wc[1] - gy, wc[2] - gz));
    const toEye = length3(ex - gx, ey - gy, ez - gz);
    const distance = eye.fixed ? 0 : Math.max(0, toEye - reach);
    if (distance >= eye.within) return;
    const ux = wb[0] - wa[0], uy = wb[1] - wa[1], uz = wb[2] - wa[2];
    const vx = wc[0] - wa[0], vy = wc[1] - wa[1], vz = wc[2] - wa[2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const twice = length3(nx, ny, nz);
    if (!(twice > 1e-12)) return;
    const area = twice / 2;
    const facing = !eye.fixed && toEye > 1e-6 ? Math.abs(nx * (ex - gx) + ny * (ey - gy) + nz * (ez - gz)) / (twice * toEye) : 1;
    const offset = unit(seed ^ 0x3c6ef372);
    const taken = Math.min(most, takenCount(area, offset, neededDensity({ distance, facing, ...eye })));
    if (taken === 0) return;
    // Its normal in the surface's own frame, for the shader to turn as the surface's node turns.
    const lux = bx - ax, luy = by - ay, luz = bz - az, lvx = cx - ax, lvy = cy - ay, lvz = cz - az;
    let lnx = luy * lvz - luz * lvy, lny = luz * lvx - lux * lvz, lnz = lux * lvy - luy * lvx;
    const ln = length3(lnx, lny, lnz) || 1;
    lnx /= ln; lny /= ln; lnz /= ln;
    // One kind for the whole piece when it is small and its corners and middle agree; else each sample asks.
    const whole = longest <= 2 ? kind(gx, gy, gz) : null;
    const same = whole !== null && kind(wa[0], wa[1], wa[2]) === whole && kind(wb[0], wb[1], wb[2]) === whole && kind(wc[0], wc[1], wc[2]) === whole;
    const s1 = unit(seed ^ 0x1b873593), s2 = unit(seed ^ 0xcc9e2d51);
    let group = same ? groupOf(whole) : null;
    for (let i = 0; i < taken; i += 1) {
      let p = (s1 + (i + 1) * R2[0]) % 1, q = (s2 + (i + 1) * R2[1]) % 1;
      if (p + q > 1) { p = 1 - p; q = 1 - q; }
      const x = ax + p * lux + q * lvx, y = ay + p * luy + q * lvy, z = az + p * luz + q * lvz;
      if (!same) {
        world(x, y, z, wa);
        group = groupOf(kind(wa[0], wa[1], wa[2]));
      }
      group.positions.push(x, y, z);
      group.normals.push(lnx, lny, lnz);
      group.densities.push((i + offset) / area);
    }
    count += taken;
  };

  const each = triangles ?? { length: triangleCount };
  for (let n = 0; n < each.length; n += 1) {
    const t = triangles === null ? n : triangles[n];
    const a = corner(t * 3), b = corner(t * 3 + 1), c = corner(t * 3 + 2);
    if (a >= vertexCount || b >= vertexCount || c >= vertexCount) continue;
    piece(positions[a * 3], positions[a * 3 + 1], positions[a * 3 + 2], positions[b * 3], positions[b * 3 + 1], positions[b * 3 + 2],
      positions[c * 3], positions[c * 3 + 1], positions[c * 3 + 2], mix32(Math.imul(key, 0x9e3779b1) ^ mix32(t)), 24);
  }
  return { groups, count };
}

/**
 * Where a surface's triangles are, for asking which lie near an eye: each triangle's middle and reach in world metres,
 * the triangles of each square of the ground `cell` metres across that its middle stands in, and apart from them the
 * few wider than a square (the land's backdrop), each asked on its own.
 */
export function surfaceIndex({ positions, indices, matrix: m }, cell = 8) {
  const vertexCount = Math.floor(positions.length / 3);
  const triangleCount = Math.floor((indices.length > 0 ? indices.length : vertexCount) / 3);
  const corner = indices.length > 0 ? (at) => indices[at] : (at) => at;
  const middles = new Float32Array(triangleCount * 4);
  const cells = new Map();
  const xs = [0, 0, 0], ys = [0, 0, 0], zs = [0, 0, 0];
  const wide = [];
  let widest = 0;
  for (let t = 0; t < triangleCount; t += 1) {
    for (let k = 0; k < 3; k += 1) {
      const v = Math.min(vertexCount - 1, corner(t * 3 + k));
      const x = positions[v * 3], y = positions[v * 3 + 1], z = positions[v * 3 + 2];
      xs[k] = m[0] * x + m[4] * y + m[8] * z + m[12];
      ys[k] = m[1] * x + m[5] * y + m[9] * z + m[13];
      zs[k] = m[2] * x + m[6] * y + m[10] * z + m[14];
    }
    const gx = (xs[0] + xs[1] + xs[2]) / 3, gy = (ys[0] + ys[1] + ys[2]) / 3, gz = (zs[0] + zs[1] + zs[2]) / 3;
    const reach = Math.max(length3(xs[0] - gx, ys[0] - gy, zs[0] - gz), length3(xs[1] - gx, ys[1] - gy, zs[1] - gz), length3(xs[2] - gx, ys[2] - gy, zs[2] - gz));
    middles[t * 4] = gx; middles[t * 4 + 1] = gy; middles[t * 4 + 2] = gz; middles[t * 4 + 3] = reach;
    if (reach > cell) { wide.push(t); continue; }
    if (reach > widest) widest = reach;
    const at = cellKey(Math.floor(gx / cell), Math.floor(gz / cell));
    let list = cells.get(at);
    if (list === undefined) { list = []; cells.set(at, list); }
    list.push(t);
  }
  return { cell, middles, cells, widest, wide };
}

const cellKey = (i, k) => (i + 32768) * 65536 + (k + 32768);

/** The triangles of an indexed surface whose nearest point may lie within `radius` metres of `at` (world). */
export function trianglesNear(index, at, radius) {
  const { cell, middles, cells, widest, wide } = index;
  const out = [];
  for (const t of wide) {
    if (length3(middles[t * 4] - at[0], middles[t * 4 + 1] - at[1], middles[t * 4 + 2] - at[2]) - middles[t * 4 + 3] < radius) out.push(t);
  }
  const span = radius + widest;
  const [x, y, z] = at;
  for (let i = Math.floor((x - span) / cell); i <= Math.floor((x + span) / cell); i += 1) {
    for (let k = Math.floor((z - span) / cell); k <= Math.floor((z + span) / cell); k += 1) {
      const list = cells.get(cellKey(i, k));
      if (list === undefined) continue;
      for (const t of list) {
        const d = length3(middles[t * 4] - x, middles[t * 4 + 1] - y, middles[t * 4 + 2] - z) - middles[t * 4 + 3];
        if (d < radius) out.push(t);
      }
    }
  }
  return out;
}
