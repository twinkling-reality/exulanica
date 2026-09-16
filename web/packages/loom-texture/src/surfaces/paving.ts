import { type BondSpec, bond, checkBond, newBondSample } from '../bond.js';
import type { TextureSetDefinition } from '../definition.js';
import { bits16, hash3, pick, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, lerp, smoothstep } from '../integer.js';
import { type CellSample, band, cells, fbm, valueNoise } from '../noise.js';
import {
  type Recipe,
  heightOfLength,
  jitter,
  mixColour,
  permille,
  setColour,
  shade,
} from '../sample.js';
import { type Srgb, decode } from '../srgb.js';
import { MM, tileToLength } from '../tile.js';

/**
 * Footway paving: precast concrete flags, 600 x 600 mm module, stack bond, 6 mm grit-filled
 * joints, three flags each way to an 1800 mm tile.
 *
 * Each flag sits at its own slight tilt (lippage), has a 3 mm chamfer, and carries exposed fine
 * aggregate. Pavement wear shows as faint staining and as the flat dark spots of trodden-in gum,
 * which is what a city footway actually looks like at walking distance.
 */
const MODULE = 600;
const JOINT_MM = 6;
const FLAGS = 3;
const EXTENT = FLAGS * MODULE;
const RANGE_MM = 8;
const FACE_MM = 6;
const JOINT_FILL_MM_1024THS = 2560;
const CHAMFER_MM = 3;
const CHIP_MM = 2;

const SPEC: BondSpec = {
  moduleU: MODULE,
  moduleV: MODULE,
  jointU: JOINT_MM,
  jointV: JOINT_MM,
  unitsPerCourse: FLAGS,
  courses: FLAGS,
  oddCourseShift: 0,
  phaseU: (MODULE * MM) / 2,
  phaseV: (MODULE * MM) / 2,
};

const FLAG: readonly Srgb[] = [
  [172, 168, 160],
  [164, 162, 158],
  [180, 176, 166],
  [158, 154, 148],
];
const GRIT: Srgb = [84, 80, 74];
const AGGREGATE_DARK: Srgb = [132, 128, 122];
const AGGREGATE_LIGHT: Srgb = [198, 194, 186];
const GUM: Srgb = [92, 90, 88];
const STAIN: Srgb = [118, 112, 104];

function recipe(seed: number): Recipe {
  checkBond(SPEC, EXTENT, EXTENT);
  const flags = FLAG.map(decode);
  const grit = decode(GRIT);
  const aggregateDark = decode(AGGREGATE_DARK);
  const aggregateLight = decode(AGGREGATE_LIGHT);
  const gum = decode(GUM);
  const stain = decode(STAIN);
  const units = stream(seed, 1);
  const textureSeed = stream(seed, 2);
  const aggregateSeed = stream(seed, 3);
  const chipSeed = stream(seed, 4);
  const gumSeed = stream(seed, 5);
  const stainSeed = stream(seed, 6);
  const gritSeed = stream(seed, 7);
  const faceSize = (MODULE - JOINT_MM) * MM;
  const at = newBondSample();
  const stone: CellSample = { nearest: 0, second: 0, id: 0 };
  const spot: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    bond(tileToLength(x, EXTENT), tileToLength(y, EXTENT), SPEC, at);

    const chipField = band(fbm(x, y, 90, 90, chipSeed, 3), 40000, 52000);
    const edge = at.edge - floorDiv(chipField * CHIP_MM * MM, ONE);
    const chamfer = edge <= 0 ? 0 : smoothstep(0, CHAMFER_MM * MM, edge);
    const coverage = smoothstep(-MM, MM, at.edge);

    const texture = fbm(x, y, 300, 300, textureSeed, 2);
    cells(x, y, 700, 700, aggregateSeed, ONE, stone);
    const stoneRadius = 18000 + pick(stone.id, 0, 9000);
    const exposed = pick(hash3(stone.id, 1, 0, aggregateSeed), 0, 99) < 55
      && stone.nearest < stoneRadius
      ? smoothstep(0, 7000, stoneRadius - stone.nearest)
      : 0;
    // Trodden-in gum: sparse, each spot its own size and its own depth of grey.
    cells(x, y, 60, 60, gumSeed, ONE, spot);
    const gumRadius = 10000 + pick(spot.id, 0, 10000);
    const gumShade = 55 + pick(hash3(spot.id, 2, 0, gumSeed), 0, 35);
    const gummed = pick(hash3(spot.id, 1, 0, gumSeed), 0, 999) < 16 && spot.nearest < gumRadius
      ? floorDiv(smoothstep(0, 2600, gumRadius - spot.nearest) * gumShade, 100)
      : 0;

    const tiltU = pick(hash3(at.unit, at.course, 1, units), -800, 800);
    const tiltV = pick(hash3(at.unit, at.course, 2, units), -800, 800);
    const face = FACE_MM * MM
      + floorDiv(tiltU * (2 * at.faceU - faceSize), 2 * faceSize)
      + floorDiv(tiltV * (2 * at.faceV - faceSize), 2 * faceSize)
      + floorDiv((texture - 32768) * 150, 32768)
      + floorDiv(exposed * 200, ONE)
      + floorDiv(gummed * 180, ONE);
    const gritNoise = valueNoise(x, y, 900, 900, gritSeed);
    const joint = JOINT_FILL_MM_1024THS + floorDiv((gritNoise - 32768) * 300, 32768);
    out.height = heightOfLength(lerp(joint, face, chamfer), RANGE_MM);

    const key = hash3(at.unit, at.course, 0, units);
    setColour(out, flags[pick(key, 0, flags.length - 1)]!);
    shade(out, jitter(bits16(hash3(at.unit, at.course, 3, units)), 3300));
    shade(out, jitter(texture, 1800));
    const light = pick(hash3(stone.id, 2, 0, aggregateSeed), 0, 1) === 0;
    mixColour(out, light ? aggregateLight : aggregateDark, floorDiv(exposed * 60, 100));
    mixColour(out, gum, gummed);
    const flagRed = out.red;
    const flagGreen = out.green;
    const flagBlue = out.blue;
    const flagRough = lerp(permille(900), permille(560), gummed)
      + floorDiv((texture - 32768) * 2000, 32768);

    setColour(out, grit);
    shade(out, jitter(gritNoise, 5000));
    out.red = lerp(out.red, flagRed, coverage);
    out.green = lerp(out.green, flagGreen, coverage);
    out.blue = lerp(out.blue, flagBlue, coverage);
    out.roughness = clamp(lerp(permille(960), flagRough, coverage), 0, FULL);

    const stained = band(fbm(x, y, 10, 10, stainSeed, 4), 30000, 46000);
    mixColour(out, stain, floorDiv(stained * 20, 100));
    shade(out, ONE - floorDiv(floorDiv((ONE - chamfer) * coverage, ONE) * 6, 100));

    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const paving = (seed: number, version: number): TextureSetDefinition => ({
  setId: 'cc0.footway-paving',
  version,
  seed,
  family: 'paving',
  title: 'Footway paving',
  summary: 'Precast concrete flags, 600 x 600 mm, stack bond, 6 mm grit joints, gum spotted.',
  width: 1024,
  height: 1024,
  extentU: EXTENT,
  extentV: EXTENT,
  surface: 'horizontal',
  heightRangeMm: RANGE_MM,
  cavity: { radiusMm: 8, depthMm: 3, strengthPermille: 500 },
  parameters: {
    bond: 'stack: no offset between courses',
    flag_module_mm: MODULE,
    flag_face_mm: MODULE - JOINT_MM,
    joint_mm: JOINT_MM,
    flags_per_row: FLAGS,
    rows: FLAGS,
    phase_u_mm_1024ths: SPEC.phaseU,
    phase_v_mm_1024ths: SPEC.phaseV,
    face_height_mm: FACE_MM,
    joint_fill_height_mm_1024ths: JOINT_FILL_MM_1024THS,
    chamfer_mm: CHAMFER_MM,
    lippage_max_mm_1024ths: 800,
    chip_depth_max_mm: CHIP_MM,
  },
  recipe: () => recipe(seed),
});
