import {
  colour,
  commonControls,
  constant,
  integer,
  lessOrEqual,
  palette,
  param,
  product,
  sum,
} from '../controls.js';
import { bits16, hash3, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, isqrt, smoothstep } from '../integer.js';
import type { Maker } from '../maker.js';
import { type CellSample, band, cells, fbm, valueNoise } from '../noise.js';
import { MAKER_PROFILE_V2, type ProceduralMakerManifest, type Recipe, read } from '../recipe.js';
import { type Pattern, heightOfLength, jitter, mixColour, permille, setColour, shade } from '../sample.js';
import { type Linear, decode } from '../srgb.js';
import { MM, TILE } from '../tile.js';

/**
 * Tree pit soil: the dug bed of earth a street tree stands in, with the stones the digging left.
 *
 * A tree pit is a hole in the footway, so the walker sees it from a metre or two away and from
 * above. That is why the published set is 512 over 900 mm, a 1.76 mm texel: 900 mm is the narrowest
 * pit on the walked street, so one tile covers it and no repeat appears inside a pit.
 *
 * What the version fixes, each with its reason:
 *
 *   - Four octaves of fractal noise for the clods. A bed turned with a spade is lumpy at the scale
 *     of the spadeful and of the clod, which is two, but at three octaves the value-noise lattice
 *     showed through the bake as a regular quilt at the tile's scale, and the fourth octave breaks
 *     it up. The crumb, finer than any of them, is its own field below.
 *   - The stones come from a cellular field and not from more fractal noise, because a stone has an
 *     edge and a nearest neighbour, which is what a cellular field has and what a fractal sum has
 *     not. Their points scatter freely (full jitter) because a stone lies where the digging left
 *     it, not on a grid.
 *   - A stone's cap is a dome, `sqrt(1 - (d/r)^2)`, because a stone bedded in soil shows the top of
 *     a rounded body and not a disc.
 *   - The radius that fills the share of the surface a person asks for is `sqrt(fraction / pi)` in
 *     cells, since a cellular field has one point to a cell. Measured over the published tile, that
 *     radius delivers what it promises for the share a pit actually has: 14 per cent asked gives a
 *     radius of 0.211 cells and 13.8 per cent of texels inside a cap, and 4 per cent gives 4.0. It
 *     falls behind further up its range, where caps begin to overlap and to reach past half a cell:
 *     40 per cent asked gives 37.2 and 60 gives 52.5. The count of cells does not change any of
 *     this (8, 26 and 128 cells all measured 13.8 at 14 per cent), because the share is a property
 *     of the radius in cells and not of how many cells there are.
 *   - The soil's tone follows its own height rather than a second field: crests dry lighter and
 *     hollows hold the water darker, which is what a pit watered an hour ago looks like. One field
 *     read twice states a fact about soil; two fields would invent a second one.
 *
 * A person sets the colours, the clods, the stones and how wet the bed is. Whether a particular pit
 * was watered this morning, or is packed hard by people standing in it, is a fact about that pit
 * and belongs to its material record, not to this tile.
 */
export const soilManifest: ProceduralMakerManifest = {
  profile: MAKER_PROFILE_V2,
  maker_id: 'loom.soil',
  version: 1,
  kind: 'procedural',
  material_class: 'opaque',
  family: 'soil',
  surface: 'horizontal',
  truth: 'invented',
  controls: [
    colour('soil_colour', [92, 74, 58], 'Soil colour', 'The earth where it is dry on top.'),
    colour('damp_colour', [52, 40, 31], 'Damp colour', 'What the hollows darken to where water sits.'),
    palette('stone_colours', [
      [104, 100, 94],
      [86, 82, 78],
      [118, 110, 100],
      [98, 78, 68],
    ], [1, 16], 'Stone colours', 'The stones the digging left, chosen per stone.'),
    integer('clod_cells', 'module', 'cells_per_tile', [4, 128], 12, 'Clod size',
      'How many clods of earth fit across one tile; more means finer tilth.'),
    integer('clod_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 5200, 'Clod relief',
      'How far the clods of earth rise and fall.'),
    integer('clod_tone_q16', 'colour', 'q16', [0, 32768], 14000, 'Clod tone',
      'How much a clod shows as a change of tone as well as of height.'),
    integer('crumb_cells', 'detail', 'cells_per_tile', [16, 1024], 220, 'Crumb size',
      'How many crumbs of earth fit across one tile; this is the grain a person sees up close.'),
    integer('crumb_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 520, 'Crumb relief',
      'How far a crumb of earth stands above the one beside it.'),
    integer('crumb_tone_q16', 'colour', 'q16', [0, 32768], 10000, 'Crumb tone',
      'How much the crumbs show as a change of tone.'),
    integer('stone_cells', 'module', 'cells_per_tile', [4, 128], 14, 'Stone spacing',
      'How many stones fit across one tile at most, one to a cell.'),
    integer('stone_fraction_percent', 'module', 'percent', [0, 60], 10, 'Stones',
      'How much of the bed is stone rather than earth, in percent.'),
    integer('stone_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 4096], 2200, 'Stone relief',
      'How far the largest stone stands above the earth around it.'),
    integer('stone_drift_cells', 'module', 'cells_per_tile', [1, 32], 4, 'Stone drifts',
      'How many drifts of stone fit across one tile; the digging leaves them in drifts.'),
    integer('damp_percent', 'wear', 'percent', [0, 100], 45, 'Dampness',
      'How much darker the hollows are than the crests, in percent.'),
    integer('soil_roughness_permille', 'finish', 'permille', [0, 1000], 900, 'Soil roughness',
      'How matte the earth is, in thousandths; soil is nearly wholly diffuse.'),
    integer('stone_roughness_permille', 'finish', 'permille', [0, 1000], 620, 'Stone roughness',
      'How matte a stone is, in thousandths.'),
    ...commonControls({
      heightRangeMm: 10,
      occlusionRadiusMm: 8,
      occlusionDepthMm: 2,
      occlusionStrengthPermille: 500,
    }),
  ],
  constraints: [
    lessOrEqual(
      sum(
        param('clod_relief_mm_1024ths'),
        param('crumb_relief_mm_1024ths'),
        param('stone_relief_mm_1024ths'),
      ),
      product(param('height_range_mm'), constant(1024)),
      'the clods, the crumbs and the stones together fit inside the height range',
    ),
  ],
};

/** Pi in Q16, for the radius that fills a stated share of the surface. */
const PI = 205887;
/**
 * How small and how large one stone is against the even radius, in Q16. A bed of stones all one
 * size reads as confetti, which is what the first pass of this maker drew: the digging leaves
 * pebbles and the odd chunk, so each stone takes its size from its own cell's hash. The spread
 * raises the share of the surface a given radius covers, because area goes as the square, and the
 * maker's note above states what the bake measured against what the control asks for.
 */
const STONE_SMALLEST = 22937;
const STONE_LARGEST = 111411;
/**
 * How far the stone field is warped before it is read, in thousandths of a cell. A cellular field
 * read straight gives circles, and a bed of circles reads as sprinkles however their sizes vary: a
 * stone that came out of the ground is angular. Two fields three times finer than the stones
 * displace the position, which is how `loom.asphalt` breaks up its crack network.
 */
const WARP_PERMILLE = 300;
/**
 * The band the stone drifts keep: three-octave fractal noise, measured over the published tile at
 * 4 by 4 cells, which runs from 10,335 to 58,172 with its median at 34,807. The band runs from
 * below its first decile to about its eighth, so the lowest hollows of the field are bare earth,
 * about a fifth of the bed carries stones at their full size, and the rest is in between. Stones
 * spread evenly over a bed read as terrazzo; the digging leaves them in drifts.
 */
const DRIFT_LOW = 24000;
const DRIFT_HIGH = 42000;

function pattern(recipe: Recipe): Pattern {
  const seed = recipe.seed;
  const soil = decode(read.colour(recipe, 'soil_colour'));
  const damp = decode(read.colour(recipe, 'damp_colour'));
  const stones = read.palette(recipe, 'stone_colours').map(decode);
  const clodCells = read.integer(recipe, 'clod_cells');
  const clodRelief = read.integer(recipe, 'clod_relief_mm_1024ths');
  const clodTone = read.integer(recipe, 'clod_tone_q16');
  const crumbCells = read.integer(recipe, 'crumb_cells');
  const crumbRelief = read.integer(recipe, 'crumb_relief_mm_1024ths');
  const crumbTone = read.integer(recipe, 'crumb_tone_q16');
  const stoneCells = read.integer(recipe, 'stone_cells');
  const stoneFraction = read.integer(recipe, 'stone_fraction_percent');
  const stoneRelief = read.integer(recipe, 'stone_relief_mm_1024ths');
  const driftCells = read.integer(recipe, 'stone_drift_cells');
  const dampPercent = read.integer(recipe, 'damp_percent');
  const soilRoughness = permille(read.integer(recipe, 'soil_roughness_permille'));
  const stoneRoughness = permille(read.integer(recipe, 'stone_roughness_permille'));
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const clodSeed = stream(seed, 1);
  const stoneSeed = stream(seed, 2);
  const crumbSeed = stream(seed, 3);
  const warpSeedU = stream(seed, 4);
  const warpSeedV = stream(seed, 5);
  const driftSeed = stream(seed, 6);
  const rangeLength = rangeMm * MM;
  // A count down v for one across u. The published tile is square, but a pit need not be, and a
  // cellular field measures its distances in cells, so the periods must follow the extents.
  const down = (across: number) =>
    Math.max(1, floorDiv(across * recipe.extent_mm.v, recipe.extent_mm.u));
  const clodDown = down(clodCells);
  const crumbDown = down(crumbCells);
  const stoneDown = down(stoneCells);
  // The radius, in Q16 of a cell, whose disc fills the stated share of a one-point cell.
  const radius = isqrt(floorDiv(ONE * ONE * floorDiv(stoneFraction * ONE, 100), PI));
  const sample: CellSample = { nearest: 0, second: 0, id: 0 };
  // Texels across one stone cell, so a rim can be stated as one texel wherever the pitch lands.
  const texelsPerCell = Math.max(1, floorDiv(recipe.resolution.width, stoneCells));
  const warpCells = stoneCells * 3;
  const warpDown = down(warpCells);
  const warp = floorDiv(floorDiv(TILE, stoneCells) * WARP_PERMILLE, 1000);

  return (x, y, out) => {
    const clod = fbm(x, y, clodCells, clodDown, clodSeed, 4);
    const crumb = valueNoise(x, y, crumbCells, crumbDown, crumbSeed);
    const wx = x + floorDiv((fbm(x, y, warpCells, warpDown, warpSeedU, 2) - 32768) * warp, 32768);
    const wy = y + floorDiv((fbm(x, y, warpCells, warpDown, warpSeedV, 2) - 32768) * warp, 32768);
    cells(wx, wy, stoneCells, stoneDown, stoneSeed, ONE, sample);
    // This stone's own radius, and the cap it shows: 0 where the earth is bare.
    const drift = band(fbm(x, y, driftCells, down(driftCells), driftSeed, 3), DRIFT_LOW, DRIFT_HIGH);
    const sized = floorDiv(floorDiv(drift * radius, ONE) * (STONE_SMALLEST
      + floorDiv(bits16(hash3(sample.id, 1, 0, stoneSeed)) * (STONE_LARGEST - STONE_SMALLEST), FULL)), ONE);
    let cap = 0;
    if (sized > 0 && sample.nearest < sized) {
      const t = floorDiv(sample.nearest * ONE, sized);
      cap = isqrt((ONE - floorDiv(t * t, ONE)) * ONE);
    }
    const relief = floorDiv(clod * clodRelief, FULL) + floorDiv(crumb * crumbRelief, FULL);
    out.height = heightOfLength(relief + floorDiv(cap * stoneRelief, ONE), rangeMm);

    setColour(out, soil);
    shade(out, jitter(clod, clodTone));
    shade(out, jitter(crumb, crumbTone));
    // The hollows of the bed hold the water, so they darken; the crests dry out first.
    const hollow = ONE - floorDiv(relief * ONE, rangeLength);
    mixColour(out, damp, floorDiv(clamp(hollow, 0, ONE) * dampPercent, 100));
    out.roughness = soilRoughness;
    if (cap > 0) {
      // A stone's colour stops at its edge, though its height does not: the cap is a dome, but a
      // stone is not a blur, and mixing by the dome made every stone look like a soft bubble. The
      // rim is one texel of the cell, which is what it takes not to alias.
      const rim = Math.max(1, floorDiv(ONE, stoneCells * texelsPerCell));
      const face = smoothstep(sized - rim, sized, sample.nearest);
      const solid = ONE - face;
      const stone = stones[bits16(hash3(sample.id, 0, 0, stoneSeed)) % stones.length] as Linear;
      mixColour(out, stone, solid);
      out.roughness = clamp(soilRoughness + floorDiv((stoneRoughness - soilRoughness) * solid, ONE), 0, FULL);
    }
    out.metalness = 0;
    out.occlusion = ONE;
    out.coverage = 0;
    out.transmission = 0;
  };
}

export const soilMaker: Maker = {
  manifest: soilManifest,
  stated(recipe) {
    const { u } = recipe.extent_mm;
    return {
      soil: 'dug bed of earth with stones',
      clod_mm: floorDiv(u, read.integer(recipe, 'clod_cells')),
      stone_spacing_mm: floorDiv(u, read.integer(recipe, 'stone_cells')),
      stone_fraction_percent: read.integer(recipe, 'stone_fraction_percent'),
      stone_relief_mm_1024ths: read.integer(recipe, 'stone_relief_mm_1024ths'),
    };
  },
  pattern,
};
