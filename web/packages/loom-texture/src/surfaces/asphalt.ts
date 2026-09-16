import type { TextureSetDefinition } from '../definition.js';
import { bits16, hash3, pick, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, lerp, smoothstep } from '../integer.js';
import { type CellSample, band, cells, fbm } from '../noise.js';
import {
  type Recipe,
  heightOfLength,
  jitter,
  mixColour,
  mixLinear,
  permille,
  setColour,
  shade,
} from '../sample.js';
import { type Linear, type Srgb, decode } from '../srgb.js';
import { MM } from '../tile.js';

/**
 * Carriageway asphalt: coarse aggregate in a dark binder, worn in places, with oil staining and
 * sparse cracking.
 *
 * Ground surfaces have no up, so u runs along the carriageway and v across it. Nothing in the
 * tile marks either direction, deliberately: lane markings, wheel tracks and ironwork are
 * separate geometry or decals, and a tiling texture that carried them would repeat them.
 */
const EXTENT = 2000;
const RANGE_MM = 6;
const BINDER_MM_1024THS = 1536;
const COARSE_CELLS = 180;
const FINE_CELLS = 520;
const CRACK_CELLS = 6;

const BINDER: Srgb = [58, 58, 60];
const WORN_BINDER: Srgb = [72, 72, 73];
const OIL: Srgb = [36, 36, 39];
const CRACK: Srgb = [30, 30, 32];
const SAND_LIGHT: Srgb = [132, 130, 126];
const SAND_DARK: Srgb = [74, 73, 72];
const AGGREGATE: readonly Srgb[] = [
  [128, 126, 122],
  [112, 112, 114],
  [148, 142, 134],
  [96, 94, 92],
  [138, 136, 138],
  [120, 114, 106],
];

function recipe(seed: number): Recipe {
  const binder = decode(BINDER);
  const wornBinder = decode(WORN_BINDER);
  const oil = decode(OIL);
  const crack = decode(CRACK);
  const sandLight = decode(SAND_LIGHT);
  const sandDark = decode(SAND_DARK);
  const aggregate = AGGREGATE.map(decode);
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
    // Wear varies over about 220 mm. Broad variation is kept weak on purpose: a strong feature
    // larger than a few hundred millimetres is what makes a tiling ground texture read as tiled.
    const wear = band(fbm(x, y, 9, 9, wearSeed, 3), 29000, 45000);

    // Coarse aggregate: a stone in most cells, flat-topped with a narrow rim, so it reads as a
    // stone rather than a soft dot.
    cells(x, y, COARSE_CELLS, COARSE_CELLS, coarseSeed, ONE, coarse);
    const coarseRadius = 19500 + pick(coarse.id, 0, 11000);
    const coarsePresent = pick(hash3(coarse.id, 1, 0, coarseSeed), 0, 99) < 86;
    const coarseInside = coarsePresent && coarse.nearest < coarseRadius;
    const coarseMask = coarseInside ? smoothstep(0, 5200, coarseRadius - coarse.nearest) : 0;
    const coarseDome = coarseInside
      ? smoothstep(0, coarseRadius, coarseRadius - coarse.nearest)
      : 0;
    cells(x, y, FINE_CELLS, FINE_CELLS, fineSeed, ONE, fine);
    const fineRadius = 19000 + pick(fine.id, 0, 9000);
    const fineMask = fine.nearest < fineRadius ? smoothstep(0, 6000, fineRadius - fine.nearest) : 0;

    // Cracks follow cell borders of a warped network, and only inside a sparse mask. The warp
    // moves a point up to about 50 mm, and a periodic warp keeps the network periodic.
    const warpX = x + floorDiv((fbm(x, y, 24, 24, warpSeed, 2) - 32768) * 26000, 32768);
    const warpY = y + floorDiv((fbm(x, y, 24, 24, warpSeed + 1, 2) - 32768) * 26000, 32768);
    cells(warpX, warpY, CRACK_CELLS, CRACK_CELLS, crackSeed, ONE, network);
    const border = network.second - network.nearest;
    const crackMask = band(fbm(x, y, 4, 4, crackMaskSeed, 3), 40000, 45000);
    const crackLine = border < 900 ? floorDiv((900 - border) * ONE, 900) : 0;
    const cracked = floorDiv(crackLine * crackMask, ONE);

    const binderWave = fbm(x, y, 20, 20, binderSeed, 3);
    const length = BINDER_MM_1024THS
      + floorDiv((binderWave - 32768) * 420, 32768)
      + floorDiv(coarseDome * (2000 + floorDiv(wear * 400, ONE)), ONE)
      + floorDiv(fineMask * 700, ONE)
      - floorDiv(cracked * 2 * MM, ONE);
    out.height = heightOfLength(length, RANGE_MM);

    // Binder, a little lighter where traffic has worn it.
    setColour(out, mixLinear(binder, wornBinder, wear));
    // Fine aggregate and sand: light and dark grains in equal measure.
    const grainLight = pick(hash3(fine.id, 1, 0, fineSeed), 0, 1) === 0;
    mixColour(out, grainLight ? sandLight : sandDark, floorDiv(fineMask * 60, 100));
    const tone: Linear = aggregate[pick(coarse.id, 0, aggregate.length - 1)]!;
    const brightness = jitter(bits16(hash3(coarse.id, 2, 0, coarseSeed)), 6500);
    stone[0] = clamp(floorDiv(tone[0] * brightness, ONE), 0, FULL);
    stone[1] = clamp(floorDiv(tone[1] * brightness, ONE), 0, FULL);
    stone[2] = clamp(floorDiv(tone[2] * brightness, ONE), 0, FULL);
    // Stone shows through the binder film more where it is worn.
    const exposure = floorDiv(coarseMask * (permille(560) + floorDiv(wear * 34, 100)), ONE);
    mixColour(out, stone, exposure);
    shade(out, jitter(fbm(x, y, 60, 60, grainSeed, 2), 3000));
    // Oil: small, sparse, and soaked in rather than painted on.
    const oiled = band(fbm(x, y, 14, 14, oilSeed, 3), 43500, 49500);
    mixColour(out, oil, floorDiv(oiled * 45, 100));
    mixColour(out, crack, cracked);

    out.roughness = clamp(
      lerp(lerp(permille(920), permille(780), exposure), permille(640), oiled)
        + floorDiv(cracked * 3, 100),
      0,
      FULL,
    );
    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const asphalt = (seed: number, version: number): TextureSetDefinition => ({
  setId: 'cc0.carriageway-asphalt',
  version,
  seed,
  family: 'asphalt',
  title: 'Carriageway asphalt',
  summary: 'Worn asphalt with exposed coarse aggregate, oil staining and sparse cracking.',
  width: 1024,
  height: 1024,
  extentU: EXTENT,
  extentV: EXTENT,
  surface: 'horizontal',
  heightRangeMm: RANGE_MM,
  cavity: { radiusMm: 5, depthMm: 2, strengthPermille: 500 },
  parameters: {
    mix: 'dense asphalt, coarse aggregate exposed',
    coarse_aggregate_cell_mm_1024ths: floorDiv(EXTENT * MM, COARSE_CELLS),
    fine_aggregate_cell_mm_1024ths: floorDiv(EXTENT * MM, FINE_CELLS),
    crack_network_cell_mm_1024ths: floorDiv(EXTENT * MM, CRACK_CELLS),
    binder_height_mm_1024ths: BINDER_MM_1024THS,
    coarse_stone_height_max_mm_1024ths: 2400,
    crack_depth_mm: 2,
  },
  recipe: () => recipe(seed),
});
