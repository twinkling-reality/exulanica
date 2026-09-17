import {
  commonControls,
  constant,
  extent,
  integer,
  lessOrEqual,
  palette,
  param,
  product,
  sum,
} from '../controls.js';
import { bits16, hash3, pick, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, floorMod, isqrt } from '../integer.js';
import type { Maker } from '../maker.js';
import { band, fbm } from '../noise.js';
import { MAKER_PROFILE_V2, type ProceduralMakerManifest, type Recipe, read } from '../recipe.js';
import { type Pattern, heightOfLength, jitter, permille } from '../sample.js';
import { decode } from '../srgb.js';
import { MM, TILE } from '../tile.js';

/**
 * Foliage: the outer leaves of a broadleaf street tree's canopy, and the gaps between them.
 *
 * Class `cutout`: a texel is leaf or gap, and a renderer tests coverage against one cutoff and lights
 * both faces, so a canopy is seen between its leaves and from inside. A gap is not drawn, so its
 * colour and height exist only for what a coarser mip level averages in and what a leaf's edge is
 * measured against: a gap takes the palette's mean shaded as the farthest leaf is, the colour deeper
 * foliage would show, and height 0, the edge of the farthest leaf.
 *
 * Leaves sit on a jittered lattice, one position to a cell, each anywhere in its cell. A leaf has
 * its own direction, depth, colour and brightness, all hashed from its cell, so a leaf is whole
 * wherever the tile is cut and the lattice wraps with the tile. Where leaves overlap, the one
 * nearest the viewer is drawn, and depth ties break on the cell, so no texel's answer depends on the
 * order the neighbouring cells were visited in.
 *
 * What the version fixes, each with its reason:
 *
 *   - One leaf outline, ovate: widest a third of the way from its stalk, `27/4 t (1 - t)^2` of its
 *     half width at `t` along its length, pointed at the tip. It reads as a leaf a few texels across.
 *     There are no veins, stalks or twigs.
 *   - A leaf folds along its midrib: its height falls linearly from the midrib to its edge, so its
 *     two halves catch light differently.
 *   - Coverage is whole or none at each texel's centre. The class tests coverage against one
 *     cutoff, and a point sample keeps the bake the same surface at any resolution.
 *   - Clumps are where broad fractal noise lies in its middle four fifths, measured (20000 to 44000
 *     holds about the tenth to the ninetieth percentile), so both clumps and the gaps between them
 *     occur at any clump size. The field is read at a leaf's centre, so a leaf is kept or dropped
 *     whole.
 *   - A leaf's direction is a hashed vector normalised by an integer square root, redrawn up to
 *     eight times while it falls outside the unit disc or inside a sixteenth of it, so directions
 *     are even around the circle. After eight misses, which happens to about one leaf in 200,000,
 *     it lies along u.
 *   - A leaf is at most four lattice positions long, a manifest constraint, so each texel looks
 *     only at the leaves of the seven by seven cells around it.
 *
 * A person sets the leaves' colours, size, shape and spacing, how thick the foliage is and how
 * it clumps, how deep the leaves lie and how much the deepest darken, and how rough a leaf is.
 */
export const foliageManifest: ProceduralMakerManifest = {
  profile: MAKER_PROFILE_V2,
  maker_id: 'loom.foliage',
  version: 1,
  kind: 'procedural',
  material_class: 'cutout',
  family: 'foliage',
  surface: 'vertical',
  truth: 'invented',
  controls: [
    palette('leaf_colours', [
      [62, 88, 38],
      [78, 102, 44],
      [94, 116, 52],
      [70, 96, 50],
    ], [1, 16], 'Leaf colours', 'Each leaf takes one of these greens.'),
    integer('leaf_cells_across', 'detail', 'cells_per_tile', [4, 256], 36, 'Leaves across',
      'How many leaf positions fit across one tile.'),
    integer('leaf_cells_down', 'detail', 'cells_per_tile', [4, 256], 36, 'Leaves down',
      'How many leaf positions fit down one tile.'),
    integer('leaf_length_mm', 'module', 'mm', [10, 400], 110, 'Leaf length',
      'How long a leaf is, from its stalk to its tip.'),
    integer('leaf_width_percent', 'module', 'percent', [10, 100], 55, 'Leaf width',
      'How wide a leaf is at its widest, as a share of its length.'),
    integer('leaf_percent', 'detail', 'percent', [0, 100], 90, 'Leaf density',
      'The share of leaf positions that hold a leaf where the foliage is thickest.'),
    integer('clump_cells', 'detail', 'cells_per_tile', [1, 64], 10, 'Clump size',
      'How many clumps of leaves fit across one tile; more means smaller clumps.'),
    integer('clumping_percent', 'detail', 'percent', [0, 100], 60, 'Gaps between clumps',
      'How much the foliage thins between clumps: 0 is even foliage, 100 leaves the gaps bare.'),
    integer('layer_depth_mm', 'relief', 'mm', [0, 64], 30, 'Foliage depth',
      'How far the farthest leaf lies behind the nearest.'),
    integer('leaf_fold_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 2048, 'Leaf fold',
      'How far the midrib of a leaf stands above its edges.'),
    integer('depth_shade_percent', 'colour', 'percent', [0, 100], 50, 'Depth shading',
      'How much darker the farthest leaf is than the nearest, in percent.'),
    integer('leaf_variation_q16', 'colour', 'q16', [0, 32768], 9000, 'Leaf variation',
      'How much one leaf differs in brightness from the next.'),
    integer('leaf_roughness_permille', 'finish', 'permille', [0, 1000], 600, 'Leaf roughness',
      'How matte a leaf is, in thousandths.'),
    ...commonControls({
      heightRangeMm: 40,
      occlusionRadiusMm: 12,
      occlusionDepthMm: 8,
      occlusionStrengthPermille: 450,
    }),
  ],
  constraints: [
    lessOrEqual(product(param('leaf_length_mm'), param('leaf_cells_across')), product(extent('u'), constant(4)),
      'a leaf is at most four leaf positions long across the tile, so a texel need look at no farther leaves'),
    lessOrEqual(product(param('leaf_length_mm'), param('leaf_cells_down')), product(extent('v'), constant(4)),
      'a leaf is at most four leaf positions long down the tile, so a texel need look at no farther leaves'),
    lessOrEqual(
      sum(product(param('layer_depth_mm'), constant(1024)), param('leaf_fold_mm_1024ths')),
      product(param('height_range_mm'), constant(1024)),
      'the nearest leaf, fold and all, stays inside the height range',
    ),
  ],
};

/** The fractal noise band a clump keeps, measured as about its tenth to ninetieth percentile. */
const CLUMP_LOW = 20000;
const CLUMP_HIGH = 44000;
/** Direction draws: a vector shorter than this (a sixteenth of the disc's radius) is redrawn. */
const DIRECTION_SHORTEST = 2048;
const DIRECTION_LONGEST = 32768;
const DIRECTION_DRAWS = 8;

function pattern(recipe: Recipe): Pattern {
  const seed = recipe.seed;
  const colours = read.palette(recipe, 'leaf_colours').map(decode);
  const cellsU = read.integer(recipe, 'leaf_cells_across');
  const cellsV = read.integer(recipe, 'leaf_cells_down');
  const length = read.integer(recipe, 'leaf_length_mm') * MM;
  const widthPercent = read.integer(recipe, 'leaf_width_percent');
  const leafPercent = read.integer(recipe, 'leaf_percent');
  const clumpCells = read.integer(recipe, 'clump_cells');
  const clumping = read.integer(recipe, 'clumping_percent');
  const layerDepth = read.integer(recipe, 'layer_depth_mm') * MM;
  const fold = read.integer(recipe, 'leaf_fold_mm_1024ths');
  const depthShade = read.integer(recipe, 'depth_shade_percent');
  const variation = read.integer(recipe, 'leaf_variation_q16');
  const roughness = permille(read.integer(recipe, 'leaf_roughness_permille'));
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const leafSeed = stream(seed, 1);
  const clumpSeed = stream(seed, 2);
  const colourSeed = stream(seed, 3);

  // Lengths in 1/1024 mm. A cell's size is floored, and both a texel's place in its cell and a
  // leaf's are measured with the same size, so they agree exactly.
  const cellU = floorDiv(recipe.extent_mm.u * MM, cellsU);
  const cellV = floorDiv(recipe.extent_mm.v * MM, cellsV);
  const halfLength = floorDiv(length, 2);
  const halfWidth = floorDiv(length * widthPercent, 200);
  const reachU = floorDiv(halfLength, cellU) + 1;
  const reachV = floorDiv(halfLength, cellV) + 1;

  // Every leaf, once, by cell.
  const count = cellsU * cellsV;
  const placeU = new Int32Array(count);
  const placeV = new Int32Array(count);
  const present = new Uint8Array(count);
  const axisU = new Int32Array(count);
  const axisV = new Int32Array(count);
  const order = new Float64Array(count);
  const base = new Float64Array(count);
  const red = new Int32Array(count);
  const green = new Int32Array(count);
  const blue = new Int32Array(count);
  for (let cj = 0; cj < cellsV; cj += 1) {
    for (let ci = 0; ci < cellsU; ci += 1) {
      const index = cj * cellsU + ci;
      const ju = bits16(hash3(ci, cj, 1, leafSeed));
      const jv = bits16(hash3(ci, cj, 2, leafSeed));
      placeU[index] = floorDiv(ju * cellU, ONE);
      placeV[index] = floorDiv(jv * cellV, ONE);
      const x = floorDiv((ci * ONE + ju) * TILE, cellsU * ONE);
      const y = floorDiv((cj * ONE + jv) * TILE, cellsV * ONE);
      const clump = band(fbm(x, y, clumpCells, clumpCells, clumpSeed, 3), CLUMP_LOW, CLUMP_HIGH);
      const density = ONE - floorDiv((ONE - clump) * clumping, 100);
      present[index] = bits16(hash3(ci, cj, 3, leafSeed)) < floorDiv(density * leafPercent, 100) ? 1 : 0;

      axisU[index] = ONE;
      axisV[index] = 0;
      for (let draw = 0; draw < DIRECTION_DRAWS; draw += 1) {
        const h = hash3(ci, cj, 16 + draw, leafSeed);
        const a = (h & 0xffff) - 32768;
        const b = (h >>> 16) - 32768;
        const squared = a * a + b * b;
        if (squared >= DIRECTION_SHORTEST * DIRECTION_SHORTEST && squared <= DIRECTION_LONGEST * DIRECTION_LONGEST) {
          const radius = isqrt(squared);
          axisU[index] = floorDiv(a * ONE, radius);
          axisV[index] = floorDiv(b * ONE, radius);
          break;
        }
      }

      const depthHash = hash3(ci, cj, 5, leafSeed);
      const depth = bits16(depthHash);
      order[index] = depthHash;
      base[index] = floorDiv(depth * layerDepth, FULL);
      const colour = colours[pick(hash3(ci, cj, 6, colourSeed), 0, colours.length - 1)]!;
      const shade = floorDiv(
        jitter(bits16(hash3(ci, cj, 7, colourSeed)), variation) * (ONE - floorDiv((FULL - depth) * depthShade, 100)),
        ONE,
      );
      red[index] = clamp(floorDiv(colour[0] * shade, ONE), 0, FULL);
      green[index] = clamp(floorDiv(colour[1] * shade, ONE), 0, FULL);
      blue[index] = clamp(floorDiv(colour[2] * shade, ONE), 0, FULL);
    }
  }
  const farthest = ONE - floorDiv(FULL * depthShade, 100);
  const mean = [0, 1, 2].map((channel) =>
    floorDiv(colours.reduce((total, colour) => total + colour[channel]!, 0), colours.length));
  const gap = mean.map((value) => clamp(floorDiv(value * farthest, ONE), 0, FULL));

  return (x, y, out) => {
    const scaledU = x * cellsU;
    const scaledV = y * cellsV;
    const cellX = floorDiv(scaledU, TILE);
    const cellY = floorDiv(scaledV, TILE);
    const inU = floorDiv((scaledU - cellX * TILE) * cellU, TILE);
    const inV = floorDiv((scaledV - cellY * TILE) * cellV, TILE);

    let best = -1;
    let bestAcross = 0;
    let bestEdge = 0;
    for (let dj = -reachV; dj <= reachV; dj += 1) {
      const cj = floorMod(cellY + dj, cellsV);
      for (let di = -reachU; di <= reachU; di += 1) {
        const index = cj * cellsU + floorMod(cellX + di, cellsU);
        if (present[index] === 0) continue;
        // The texel's place relative to the leaf's centre.
        const du = inU - di * cellU - placeU[index]!;
        if (du > halfLength || du < -halfLength) continue;
        const dv = inV - dj * cellV - placeV[index]!;
        if (dv > halfLength || dv < -halfLength) continue;
        const along = floorDiv(du * axisU[index]! + dv * axisV[index]!, ONE);
        if (along > halfLength || along < -halfLength) continue;
        const across = Math.abs(floorDiv(dv * axisU[index]! - du * axisV[index]!, ONE));
        const t = floorDiv((along + halfLength) * ONE, 2 * halfLength);
        const rest = ONE - t;
        const edge = floorDiv(halfWidth * floorDiv(27 * floorDiv(t * floorDiv(rest * rest, ONE), ONE), 4), ONE);
        if (edge === 0 || across > edge) continue;
        if (best < 0 || order[index]! > order[best]! || (order[index] === order[best] && index > best)) {
          best = index;
          bestAcross = across;
          bestEdge = edge;
        }
      }
    }

    if (best < 0) {
      out.red = gap[0]!;
      out.green = gap[1]!;
      out.blue = gap[2]!;
      out.height = 0;
      out.coverage = 0;
    } else {
      out.red = red[best]!;
      out.green = green[best]!;
      out.blue = blue[best]!;
      out.height = heightOfLength(base[best]! + floorDiv(fold * (bestEdge - bestAcross), bestEdge), rangeMm);
      out.coverage = FULL;
    }
    out.roughness = roughness;
    out.metalness = 0;
    out.occlusion = ONE;
    out.transmission = 0;
  };
}

export const foliageMaker: Maker = {
  manifest: foliageManifest,
  stated(recipe) {
    const { u, v } = recipe.extent_mm;
    const length = read.integer(recipe, 'leaf_length_mm');
    return {
      leaf: 'ovate broadleaf',
      leaf_length_mm: length,
      leaf_width_mm: floorDiv(length * read.integer(recipe, 'leaf_width_percent'), 100),
      leaf_spacing_across_mm: floorDiv(u, read.integer(recipe, 'leaf_cells_across')),
      leaf_spacing_down_mm: floorDiv(v, read.integer(recipe, 'leaf_cells_down')),
      clump_mm: floorDiv(u, read.integer(recipe, 'clump_cells')),
      layer_depth_mm: read.integer(recipe, 'layer_depth_mm'),
    };
  },
  pattern,
};
