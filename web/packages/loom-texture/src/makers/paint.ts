import {
  colour,
  commonControls,
  constant,
  extent,
  integer,
  lessOrEqual,
  param,
  product,
  sum,
} from '../controls.js';
import { bits16, hash3, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, floorMod, isqrt, smoothstep } from '../integer.js';
import type { Maker } from '../maker.js';
import { type CellSample, band, cells, fbm, valueNoise } from '../noise.js';
import { MAKER_PROFILE_V2, type ProceduralMakerManifest, type Recipe, read } from '../recipe.js';
import { type Pattern, heightOfLength, jitter, mixColour, permille, setColour, shade } from '../sample.js';
import { decode } from '../srgb.js';
import { MM, TILE, tileToLength } from '../tile.js';

/**
 * Road marking paint: the thermoplastic a lane line, a stop bar or a crossing is painted with.
 *
 * This is the library's first DECAL. A marking is drawn as geometry laid on the carriageway and
 * blended over it, so what this set holds is the paint and nothing else: where the paint has worn
 * away its coverage falls to zero and the road drawn beneath shows through. A decal that painted
 * its own asphalt would draw the road twice, once in this tile and once underneath, and the two
 * would disagree.
 *
 * u runs along the marking and v across it, so one tile is a metre of marking 250 mm wide at the
 * published extent, and the marking's own geometry states how many repeats it carries. The tile is
 * 256 by 64 texels over 1000 by 250 mm, which is the same 3.90625 mm texel both ways: the tile is
 * not square, the texel is. `cc0.kerb-stone` is non-square too (1024 by 256 over 1800 by 450 mm),
 * so the container, the readers and the dataset frames have carried a 4 to 1 tile since 0065; what
 * is new here is a non-square set in the v2 container, where a class states its own layout. Every
 * cell count below is stated along u and scaled to v by the extents, as `noise.ts` requires and as
 * `loom.kerb` does, because a field whose cells are square in tile fractions is elongated in
 * millimetres on a tile that is not.
 *
 * What the version fixes, each with its reason:
 *
 *   - The paint runs to the tile's v edges, and the marking's own geometry is where the paint stops.
 *     A laid line's edge does wander, but by two to five millimetres, which is under the 3.9 mm
 *     texel: a margin that small cannot be drawn, and the first pass of this maker drew it anyway
 *     and produced a one-texel dark line down both sides of every marking, which read as a drawn
 *     border rather than as the edge of paint. So the edge is straight where the paint was laid.
 *   - What is left of that idea is the bites: where something has caught the edge, a chunk of paint
 *     is missing, tens of millimetres across and several texels deep, which does read at this
 *     pitch. A bite is a function of the position along the line alone, so the two edges are bitten
 *     independently, and it eats from whichever edge is nearer. The field is measured (below), and
 *     the band keeps its top fifth, so most of a marking's edge is whole.
 *   - Coverage at a bite rises over 6 mm, about one and a half texels: a decal is blended, not
 *     thresholded, so an edge that crosses more than one texel reads as an edge and not a stair.
 *   - Wear is holes gathered in patches, not an even thinning, because tyres scrub the same tracks
 *     over and over: the bands are measured from the fields themselves (see the constants below).
 *   - Relief and tone are the glass beads the paint is dressed with for retroreflection, which is
 *     why fresh marking paint is a duller, grittier surface than the road it lies on.
 *   - Grime is broad and shallow, because the dirt on a marking arrives from the whole road and
 *     not from the marking's own shape.
 *
 * A person sets the colour, the edge, the wear, the beads, the grime and how matte the paint is.
 * Whether a particular crossing is scrubbed bare in its middle is a fact about that crossing and
 * belongs to its material record, not to this tile.
 */
export const paintManifest: ProceduralMakerManifest = {
  profile: MAKER_PROFILE_V2,
  maker_id: 'loom.paint',
  version: 1,
  kind: 'procedural',
  material_class: 'decal',
  family: 'paint',
  surface: 'horizontal',
  truth: 'invented',
  controls: [
    colour('paint_colour', [236, 234, 226], 'Paint colour', 'The paint itself, where it is unworn.'),
    colour('grime_colour', [96, 94, 88], 'Grime colour', 'The dirt the road leaves on the paint.'),
    integer('edge_bite_mm', 'module', 'mm', [0, 60], 12, 'Edge bites',
      'How deep the deepest chunk missing from the marking edge is.'),
    integer('edge_cells_along', 'detail', 'cells_per_tile', [1, 64], 9, 'Edge bite spacing',
      'How many places along one tile the edge can be bitten; fewer means longer bites.'),
    integer('wear_percent', 'wear', 'percent', [0, 100], 32, 'Wear',
      'How much of the paint is gone, in percent, where the wear is worst.'),
    integer('wear_cells', 'wear', 'cells_per_tile', [4, 256], 26, 'Wear size',
      'How many worn holes fit along one tile; more means smaller holes.'),
    integer('wear_patch_cells', 'wear', 'cells_per_tile', [1, 32], 6, 'Wear patches',
      'How many patches the wear gathers into along one tile, as a tyre track is a patch.'),
    integer('thinning_percent', 'wear', 'percent', [0, 100], 40, 'Thinning',
      'How much the paint greys where it is worn thin but not yet gone, in percent.'),
    integer('bead_cells', 'detail', 'cells_per_tile', [16, 1024], 168, 'Bead size',
      'How many beads of the paint fit along one tile; more means finer.'),
    integer('bead_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 1024], 420, 'Bead relief',
      'How far the beads in the paint stand above it.'),
    integer('bead_tone_q16', 'colour', 'q16', [0, 32768], 3400, 'Bead tone',
      'How much the beads show as a change of tone.'),
    integer('paint_thickness_mm_1024ths', 'relief', 'mm_1024ths', [0, 4096], 1500, 'Paint thickness',
      'How far the paint stands above the road it is laid on.'),
    integer('grime_percent', 'wear', 'percent', [0, 100], 28, 'Grime',
      'The most the road grime darkens the paint, in percent.'),
    integer('grime_cells', 'wear', 'cells_per_tile', [1, 64], 4, 'Grime patches',
      'How many patches of grime fit along one tile; more means smaller patches.'),
    integer('paint_roughness_permille', 'finish', 'permille', [0, 1000], 620, 'Paint roughness',
      'How matte the paint is, in thousandths; beads make it grittier than the road.'),
    integer('grime_roughness_percent', 'finish', 'percent', [0, 50], 12, 'Grime roughness',
      'How much grime dulls the paint further, in percent.'),
    ...commonControls({
      heightRangeMm: 4,
      occlusionRadiusMm: 3,
      occlusionDepthMm: 1,
      occlusionStrengthPermille: 300,
    }),
  ],
  constraints: [
    lessOrEqual(product(param('edge_bite_mm'), constant(4)), extent('v'),
      'a bite at each edge leaves at least half the marking painted'),
    lessOrEqual(
      sum(param('paint_thickness_mm_1024ths'), param('bead_relief_mm_1024ths')),
      product(param('height_range_mm'), constant(1024)),
      'the paint and its beads together fit inside the height range',
    ),
  ],
};

/**
 * The bands the wear and the grime keep, measured over this maker's own fields at the published
 * cell counts, every texel of a 256 by 64 tile over 1000 by 250 mm:
 *
 *   - the patches are three-octave fractal noise on 3 by 1 cells, which runs only from 25,244 to
 *     52,018 because a fractal sum concentrates around its middle. Its median is 37,033, so
 *     PATCH_LOW keeps the upper half of the line as somewhere a tyre track runs, and PATCH_HIGH is
 *     its ninth decile, where a track is at its worst. One cell across the marking is deliberate: a
 *     track runs along a line, not across it, and the extents scale 3 along u to 1 across v anyway;
 *   - the grime is three-octave fractal noise on 4 by 1 cells, from 7,409 to 30,329 with its
 *     median at 19,980, so GRIME_LOW is that median (half the line carries some grime) and
 *     GRIME_HIGH is near its top (the dirtiest patches carry all of it).
 */
const PATCH_LOW = 31000;
const PATCH_HIGH = 48000;
const GRIME_LOW = 20000;
const GRIME_HIGH = 28000;
/** Pi in Q16, for the hole radius that bares a stated share of a cell. */
const PI = 205887;
/**
 * The width of a hole's rim, in Q16 of one wear cell: about one texel at the published pitch, where
 * a cell is 22.7 mm and a texel 3.9 mm. Any narrower and the rim would alias; any wider and a small
 * hole would be all rim and never reach bare road.
 */
const HOLE_RIM = 11000;
/**
 * How small and how large a hole is against the even radius, in Q16, and how far the field is
 * warped before it is read, in thousandths of a wear cell. The spread of sizes is what turns a
 * cellular field into wear; the warp is what stops the holes being circles. Both are measured in
 * their effect on the share of the marking that is bare: see the note above the maker.
 */
const HOLE_SMALLEST = 26214;
const HOLE_LARGEST = 104857;
const WARP_PERMILLE = 340;
/**
 * The band a bite out of the edge keeps: the top fifth of the same value noise the first pass used
 * for its margin, measured over the published tile at 24,442 to 55,136 of 65,535, so most of the
 * edge is whole and a bite reaches its full depth only where the field peaks.
 */
const BITE_LOW = 46000;
const BITE_HIGH = 55000;
/** The length coverage rises over at the paint's edge: about one and a half texels at 3.9 mm. */
const EDGE_SOFT_MM = 6;

function pattern(recipe: Recipe): Pattern {
  const seed = recipe.seed;
  const paint = decode(read.colour(recipe, 'paint_colour'));
  const grimeColour = decode(read.colour(recipe, 'grime_colour'));
  const biteMm = read.integer(recipe, 'edge_bite_mm');
  const edgeCells = read.integer(recipe, 'edge_cells_along');
  const wearPercent = read.integer(recipe, 'wear_percent');
  const wearCells = read.integer(recipe, 'wear_cells');
  const patchCells = read.integer(recipe, 'wear_patch_cells');
  const thinning = read.integer(recipe, 'thinning_percent');
  const beadCells = read.integer(recipe, 'bead_cells');
  const beadRelief = read.integer(recipe, 'bead_relief_mm_1024ths');
  const beadTone = read.integer(recipe, 'bead_tone_q16');
  const thickness = read.integer(recipe, 'paint_thickness_mm_1024ths');
  const grimePercent = read.integer(recipe, 'grime_percent');
  const grimeCells = read.integer(recipe, 'grime_cells');
  const roughness = permille(read.integer(recipe, 'paint_roughness_permille'));
  const grimeRoughness = read.integer(recipe, 'grime_roughness_percent');
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const nearSeed = stream(seed, 1);
  const farSeed = stream(seed, 2);
  const holeSeed = stream(seed, 3);
  const patchSeed = stream(seed, 4);
  const beadSeed = stream(seed, 5);
  const grimeSeed = stream(seed, 6);
  // The marking's width, and the lengths the edge works in, all in 1/1024 mm.
  const acrossLength = recipe.extent_mm.v * MM;
  const bite = biteMm * MM;
  const soft = EDGE_SOFT_MM * MM;
  /**
   * A cell count across v for one along u. The tile is not square, so a period stated along the
   * marking must be scaled by the extents to keep the cells square: at the published extent that
   * is a quarter, and `cells` in `noise.ts` says the same of its own periods.
   */
  const down = (along: number) =>
    Math.max(1, floorDiv(along * recipe.extent_mm.v, recipe.extent_mm.u));
  const hole: CellSample = { nearest: 0, second: 0, id: 0 };
  // The warp: two fields three times finer than the holes, displacing by a third of a cell.
  const warpCells = wearCells * 3;
  const warpDown = down(warpCells);
  const warp = floorDiv(floorDiv(TILE, wearCells) * WARP_PERMILLE, 1000);
  const warpSeedU = stream(seed, 7);
  const warpSeedV = stream(seed, 8);

  return (x, y, out) => {
    // How far across the marking this texel sits, and how far inside the paint's wandering edges.
    // The position is folded into the tile first: a recipe is handed the unwrapped position (see
    // `src/tile.ts`), and the paint's edges are the only thing here that reads a position directly
    // rather than through a noise field, which folds its own. Unfolded, the band would not repeat.
    const across = tileToLength(floorMod(y, TILE), recipe.extent_mm.v);
    const fromEdge = Math.min(across, acrossLength - across);
    // The bite in the edge this texel is nearer to. Beyond the bite's depth the paint is whole,
    // which is why a marking with no bites has no border: its coverage runs to the tile's edge.
    const seedHere = across * 2 <= acrossLength ? nearSeed : farSeed;
    const depth = floorDiv(band(valueNoise(x, 0, edgeCells, 1, seedHere), BITE_LOW, BITE_HIGH) * bite, ONE);
    const edge = smoothstep(depth - soft, depth, fromEdge);

    const patch = band(fbm(x, y, patchCells, down(patchCells), patchSeed, 3), PATCH_LOW, PATCH_HIGH);
    // A hole in a film has an edge and a nearest neighbour, so the holes are a cellular field and
    // not a level set of smooth noise, which draws worms rather than blotches. The radius that
    // bares a stated share of a one-point cell is sqrt(share / pi), and the share here is the
    // patch's own strength: wear spreads from the middle of a tyre track, so the holes are wide
    // enough to merge there and small where the track fades out.
    // The field is warped before it is read and each hole is sized by its own hash, because a hole
    // in a worn film is neither round nor the size of its neighbour: unwarped and unsized, this
    // maker drew a field of even polka dots. `loom.asphalt` warps its crack network the same way.
    const wx = x + floorDiv((fbm(x, y, warpCells, warpDown, warpSeedU, 2) - 32768) * warp, 32768);
    const wy = y + floorDiv((fbm(x, y, warpCells, warpDown, warpSeedV, 2) - 32768) * warp, 32768);
    cells(wx, wy, wearCells, down(wearCells), holeSeed, ONE, hole);
    const even = isqrt(floorDiv(ONE * ONE * floorDiv(patch * wearPercent, 100), PI));
    const radius = floorDiv(even * (HOLE_SMALLEST
      + floorDiv(bits16(hash3(hole.id, 0, 0, holeSeed)) * (HOLE_LARGEST - HOLE_SMALLEST), FULL)), ONE);
    const worn = radius > HOLE_RIM ? ONE - smoothstep(radius - HOLE_RIM, radius, hole.nearest) : 0;
    const bead = valueNoise(x, y, beadCells, down(beadCells), beadSeed);
    // What is left of the paint here: inside its edge, less what has worn away.
    const covered = floorDiv(edge * (ONE - worn), ONE);
    out.coverage = floorDiv(covered * FULL, ONE);
    out.height = heightOfLength(
      floorDiv(covered * thickness, ONE) + floorDiv(floorDiv(bead * covered, ONE) * beadRelief, FULL),
      rangeMm,
    );

    setColour(out, paint);
    shade(out, jitter(bead, beadTone));
    // A film thins before it breaks, so the paint still there in a worn patch shows the road's tone
    // through it. Without this the marking read as a cut-out: pristine paint against bare holes.
    mixColour(out, grimeColour, floorDiv(patch * thinning, 100));
    const grime = floorDiv(
      band(fbm(x, y, grimeCells, down(grimeCells), grimeSeed, 3), GRIME_LOW, GRIME_HIGH) * grimePercent,
      100,
    );
    mixColour(out, grimeColour, grime);

    out.roughness = clamp(roughness + floorDiv(grime * grimeRoughness, 100), 0, FULL);
    out.metalness = 0;
    out.occlusion = ONE;
    out.transmission = 0;
  };
}

export const paintMaker: Maker = {
  manifest: paintManifest,
  stated(recipe) {
    const { u, v } = recipe.extent_mm;
    return {
      paint: 'thermoplastic road marking, dressed with glass beads',
      marking_width_mm: v,
      edge_bite_mm: read.integer(recipe, 'edge_bite_mm'),
      paint_thickness_mm_1024ths: read.integer(recipe, 'paint_thickness_mm_1024ths'),
      bead_mm_1024ths: floorDiv(u * MM, read.integer(recipe, 'bead_cells')),
      wear_mm: floorDiv(u, read.integer(recipe, 'wear_cells')),
    };
  },
  pattern,
};
