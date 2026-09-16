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
import { bits16, hash3, pick, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, lerp, smoothstep } from '../integer.js';
import type { Maker } from '../maker.js';
import { type CellSample, band, cells, fbm } from '../noise.js';
import { MAKER_PROFILE, type MakerManifest, type Recipe, read } from '../recipe.js';
import {
  type Pattern,
  heightOfLength,
  jitter,
  mixColour,
  mixLinear,
  permille,
  setColour,
  shade,
} from '../sample.js';
import { type Linear, decode } from '../srgb.js';
import { MM } from '../tile.js';

/**
 * Carriageway asphalt: coarse aggregate in a dark binder, worn in places, with oil staining and
 * sparse cracking.
 *
 * Ground surfaces have no up, so u runs along the carriageway and v across it. Nothing here marks
 * either direction, deliberately: lane markings, wheel tracks and ironwork are separate geometry
 * or decals, and a tiling texture that carried them would repeat them. Broad variation is kept
 * weak for the same reason; a strong feature larger than a few hundred millimetres is what makes a
 * tiling ground texture read as tiled.
 */
export const asphaltManifest: MakerManifest = {
  profile: MAKER_PROFILE,
  maker_id: 'loom.asphalt',
  version: 1,
  kind: 'procedural',
  family: 'asphalt',
  surface: 'horizontal',
  truth: 'invented',
  controls: [
    colour('binder_colour', [58, 58, 60], 'Binder colour', 'The bitumen between the stones.'),
    colour('worn_binder_colour', [72, 72, 73], 'Worn binder colour',
      'The binder where traffic has worn it.'),
    colour('oil_colour', [36, 36, 39], 'Oil stain colour', 'Oil soaked into the surface.'),
    colour('crack_colour', [30, 30, 32], 'Crack colour', 'Inside a crack.'),
    colour('sand_light_colour', [132, 130, 126], 'Light grit', 'Pale fine aggregate.'),
    colour('sand_dark_colour', [74, 73, 72], 'Dark grit', 'Dark fine aggregate.'),
    palette('aggregate_palette', [
      [128, 126, 122],
      [112, 112, 114],
      [148, 142, 134],
      [96, 94, 92],
      [138, 136, 138],
      [120, 114, 106],
    ], [1, 16], 'Stone colours', 'Each coarse stone takes one of these tones.'),
    integer('coarse_cells_per_tile', 'detail', 'cells_per_tile', [16, 1024], 180,
      'Stone size', 'How many coarse-stone cells cross one tile; more means smaller stones.'),
    integer('fine_cells_per_tile', 'detail', 'cells_per_tile', [16, 2048], 520, 'Grit size',
      'How many fine-aggregate cells cross one tile.'),
    integer('crack_cells_per_tile', 'wear', 'cells_per_tile', [1, 64], 6, 'Crack spacing',
      'How many crack-network cells cross one tile.'),
    integer('binder_height_mm_1024ths', 'relief', 'mm_1024ths', [0, 32768], 1536,
      'Binder height', 'Where the binder surface sits in the height range.'),
    integer('binder_waviness_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 420,
      'Binder waviness', 'How far the binder surface rises and falls.'),
    integer('coarse_stone_height_mm_1024ths', 'relief', 'mm_1024ths', [0, 16384], 2000,
      'Stone height', 'How far a coarse stone stands above the binder.'),
    integer('wear_stone_lift_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 400,
      'Worn stone lift', 'How much further stones stand out where the binder is worn.'),
    integer('fine_stone_height_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 700,
      'Grit height', 'How far fine aggregate stands above the binder.'),
    integer('crack_depth_mm', 'wear', 'mm', [0, 30], 2, 'Crack depth', 'How deep a crack is.'),
    integer('crack_width_q16', 'wear', 'q16', [0, 16384], 900, 'Crack width',
      'How wide a crack is, as a fraction of the crack-network cell.'),
    integer('crack_threshold_q16', 'wear', 'q16', [0, 65535], 40000, 'Crack rarity',
      'Higher means fewer cracked patches.'),
    integer('coarse_present_percent', 'detail', 'percent', [0, 100], 86, 'Stone density',
      'How many coarse cells hold a stone.'),
    integer('fine_mix_percent', 'colour', 'percent', [0, 100], 60, 'Grit contrast',
      'How strongly the fine aggregate shows against the binder.'),
    integer('aggregate_brightness_spread_q16', 'colour', 'q16', [0, 32768], 6500,
      'Stone-to-stone variation', 'How much one stone may be lighter or darker than the next.'),
    integer('exposure_base_permille', 'wear', 'permille', [0, 1000], 560, 'Stone exposure',
      'How much a stone shows through the binder film where nothing has worn it.'),
    integer('exposure_wear_percent', 'wear', 'percent', [0, 100], 34, 'Wear exposure',
      'How much more a stone shows where traffic has worn the binder.'),
    integer('grain_spread_q16', 'colour', 'q16', [0, 32768], 3000, 'Grain colour',
      'Fine colour variation across the surface.'),
    integer('oil_threshold_q16', 'wear', 'q16', [0, 65535], 43500, 'Oil rarity',
      'Higher means fewer oil stains.'),
    integer('oil_percent', 'wear', 'percent', [0, 100], 45, 'Oil darkness',
      'How dark an oil stain gets.'),
    integer('binder_roughness_permille', 'finish', 'permille', [0, 1000], 920,
      'Binder roughness', 'How matte the binder is, in thousandths.'),
    integer('stone_roughness_permille', 'finish', 'permille', [0, 1000], 780,
      'Stone roughness', 'How matte an exposed stone is, in thousandths.'),
    integer('oil_roughness_permille', 'finish', 'permille', [0, 1000], 640, 'Oil roughness',
      'How matte an oil stain is, in thousandths.'),
    integer('crack_roughness_percent', 'finish', 'percent', [0, 100], 3, 'Crack roughness',
      'How much a crack dulls the surface, in percent.'),
    ...commonControls({
      heightRangeMm: 6,
      occlusionRadiusMm: 5,
      occlusionDepthMm: 2,
      occlusionStrengthPermille: 500,
    }),
  ],
  constraints: [
    lessOrEqual(
      sum(param('exposure_base_permille'), product(param('exposure_wear_percent'), constant(10))),
      constant(1000),
      'a stone cannot show through more than fully, even where the binder is most worn',
    ),
  ],
};

function pattern(recipe: Recipe): Pattern {
  const seed = recipe.seed;
  const binder = decode(read.colour(recipe, 'binder_colour'));
  const wornBinder = decode(read.colour(recipe, 'worn_binder_colour'));
  const oil = decode(read.colour(recipe, 'oil_colour'));
  const crack = decode(read.colour(recipe, 'crack_colour'));
  const sandLight = decode(read.colour(recipe, 'sand_light_colour'));
  const sandDark = decode(read.colour(recipe, 'sand_dark_colour'));
  const aggregate = read.palette(recipe, 'aggregate_palette').map(decode);
  const coarseCells = read.integer(recipe, 'coarse_cells_per_tile');
  const fineCells = read.integer(recipe, 'fine_cells_per_tile');
  const crackCells = read.integer(recipe, 'crack_cells_per_tile');
  const binderHeight = read.integer(recipe, 'binder_height_mm_1024ths');
  const binderWaviness = read.integer(recipe, 'binder_waviness_mm_1024ths');
  const coarseHeight = read.integer(recipe, 'coarse_stone_height_mm_1024ths');
  const wearLift = read.integer(recipe, 'wear_stone_lift_mm_1024ths');
  const fineHeight = read.integer(recipe, 'fine_stone_height_mm_1024ths');
  const crackDepthMm = read.integer(recipe, 'crack_depth_mm');
  const crackWidth = read.integer(recipe, 'crack_width_q16');
  const crackThreshold = read.integer(recipe, 'crack_threshold_q16');
  const coarsePercent = read.integer(recipe, 'coarse_present_percent');
  const fineMix = read.integer(recipe, 'fine_mix_percent');
  const aggregateSpread = read.integer(recipe, 'aggregate_brightness_spread_q16');
  const exposureBase = permille(read.integer(recipe, 'exposure_base_permille'));
  const exposureWear = read.integer(recipe, 'exposure_wear_percent');
  const grainSpread = read.integer(recipe, 'grain_spread_q16');
  const oilThreshold = read.integer(recipe, 'oil_threshold_q16');
  const oilPercent = read.integer(recipe, 'oil_percent');
  const binderRoughness = permille(read.integer(recipe, 'binder_roughness_permille'));
  const stoneRoughness = permille(read.integer(recipe, 'stone_roughness_permille'));
  const oilRoughness = permille(read.integer(recipe, 'oil_roughness_permille'));
  const crackRoughness = read.integer(recipe, 'crack_roughness_percent');
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const coarseSeed = stream(seed, 1);
  const fineSeed = stream(seed, 2);
  const binderSeed = stream(seed, 3);
  const wearSeed = stream(seed, 4);
  const oilSeed = stream(seed, 5);
  const crackSeed = stream(seed, 6);
  const crackMaskSeed = stream(seed, 7);
  const warpSeed = stream(seed, 8);
  const grainSeed = stream(seed, 9);
  const coarse: CellSample = { nearest: 0, second: 0, id: 0 };
  const fine: CellSample = { nearest: 0, second: 0, id: 0 };
  const network: CellSample = { nearest: 0, second: 0, id: 0 };
  const stone: [number, number, number] = [0, 0, 0];

  return (x, y, out) => {
    // Wear varies over about a ninth of the tile, and only weakly.
    const wear = band(fbm(x, y, 9, 9, wearSeed, 3), 29000, 45000);

    // Coarse aggregate: a stone in most cells, flat-topped with a narrow rim, so it reads as a
    // stone rather than a soft dot.
    cells(x, y, coarseCells, coarseCells, coarseSeed, ONE, coarse);
    const coarseRadius = 19500 + pick(coarse.id, 0, 11000);
    const coarsePresent = pick(hash3(coarse.id, 1, 0, coarseSeed), 0, 99) < coarsePercent;
    const coarseInside = coarsePresent && coarse.nearest < coarseRadius;
    const coarseMask = coarseInside ? smoothstep(0, 5200, coarseRadius - coarse.nearest) : 0;
    const coarseDome = coarseInside
      ? smoothstep(0, coarseRadius, coarseRadius - coarse.nearest)
      : 0;
    cells(x, y, fineCells, fineCells, fineSeed, ONE, fine);
    const fineRadius = 19000 + pick(fine.id, 0, 9000);
    const fineMask = fine.nearest < fineRadius ? smoothstep(0, 6000, fineRadius - fine.nearest) : 0;

    // Cracks follow cell borders of a warped network, and only inside a sparse mask. The warp
    // moves a point about a fortieth of the tile, and a periodic warp keeps the network periodic.
    const warpX = x + floorDiv((fbm(x, y, 24, 24, warpSeed, 2) - 32768) * 26000, 32768);
    const warpY = y + floorDiv((fbm(x, y, 24, 24, warpSeed + 1, 2) - 32768) * 26000, 32768);
    cells(warpX, warpY, crackCells, crackCells, crackSeed, ONE, network);
    const border = network.second - network.nearest;
    const crackMask = band(fbm(x, y, 4, 4, crackMaskSeed, 3), crackThreshold, crackThreshold + 5000);
    const crackLine = border < crackWidth ? floorDiv((crackWidth - border) * ONE, crackWidth) : 0;
    const cracked = floorDiv(crackLine * crackMask, ONE);

    const binderWave = fbm(x, y, 20, 20, binderSeed, 3);
    const length = binderHeight
      + floorDiv((binderWave - 32768) * binderWaviness, 32768)
      + floorDiv(coarseDome * (coarseHeight + floorDiv(wear * wearLift, ONE)), ONE)
      + floorDiv(fineMask * fineHeight, ONE)
      - floorDiv(cracked * crackDepthMm * MM, ONE);
    out.height = heightOfLength(length, rangeMm);

    // Binder, a little lighter where traffic has worn it.
    setColour(out, mixLinear(binder, wornBinder, wear));
    // Fine aggregate and sand: light and dark grains in equal measure.
    const grainLight = pick(hash3(fine.id, 1, 0, fineSeed), 0, 1) === 0;
    mixColour(out, grainLight ? sandLight : sandDark, floorDiv(fineMask * fineMix, 100));
    const tone: Linear = aggregate[pick(coarse.id, 0, aggregate.length - 1)]!;
    const brightness = jitter(bits16(hash3(coarse.id, 2, 0, coarseSeed)), aggregateSpread);
    stone[0] = clamp(floorDiv(tone[0] * brightness, ONE), 0, FULL);
    stone[1] = clamp(floorDiv(tone[1] * brightness, ONE), 0, FULL);
    stone[2] = clamp(floorDiv(tone[2] * brightness, ONE), 0, FULL);
    // Stone shows through the binder film more where it is worn.
    const exposure = floorDiv(coarseMask * (exposureBase + floorDiv(wear * exposureWear, 100)), ONE);
    mixColour(out, stone, exposure);
    shade(out, jitter(fbm(x, y, 60, 60, grainSeed, 2), grainSpread));
    // Oil: small, sparse, and soaked in rather than painted on.
    const oiled = band(fbm(x, y, 14, 14, oilSeed, 3), oilThreshold, oilThreshold + 6000);
    mixColour(out, oil, floorDiv(oiled * oilPercent, 100));
    mixColour(out, crack, cracked);

    out.roughness = clamp(
      lerp(lerp(binderRoughness, stoneRoughness, exposure), oilRoughness, oiled)
        + floorDiv(cracked * crackRoughness, 100),
      0,
      FULL,
    );
    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const asphaltMaker: Maker = {
  manifest: asphaltManifest,
  stated(recipe) {
    const extentU = recipe.extent_mm.u;
    return {
      mix: 'dense asphalt, coarse aggregate exposed',
      coarse_aggregate_cell_mm_1024ths: floorDiv(
        extentU * MM,
        read.integer(recipe, 'coarse_cells_per_tile'),
      ),
      fine_aggregate_cell_mm_1024ths: floorDiv(
        extentU * MM,
        read.integer(recipe, 'fine_cells_per_tile'),
      ),
      crack_network_cell_mm_1024ths: floorDiv(
        extentU * MM,
        read.integer(recipe, 'crack_cells_per_tile'),
      ),
      binder_height_mm_1024ths: read.integer(recipe, 'binder_height_mm_1024ths'),
      coarse_stone_height_max_mm_1024ths:
        read.integer(recipe, 'coarse_stone_height_mm_1024ths')
        + read.integer(recipe, 'wear_stone_lift_mm_1024ths'),
      crack_depth_mm: read.integer(recipe, 'crack_depth_mm'),
    };
  },
  pattern,
};
