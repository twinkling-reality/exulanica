import { type BondSpec, bond, checkBond, newBondSample } from '../bond.js';
import {
  colour,
  commonControls,
  constant,
  equal,
  extent,
  integer,
  less,
  lessOrEqual,
  param,
  product,
  sum,
} from '../controls.js';
import { bits16, hash3, pick, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, lerp, smoothstep } from '../integer.js';
import type { Maker } from '../maker.js';
import { type CellSample, band, cells, fbm, valueNoise } from '../noise.js';
import { MAKER_PROFILE, type MakerManifest, type Recipe, read } from '../recipe.js';
import {
  type Pattern,
  heightOfLength,
  jitter,
  mixColour,
  permille,
  setColour,
  shade,
} from '../sample.js';
import { type Linear, decode } from '../srgb.js';
import { MM, tileToLength } from '../tile.js';

/**
 * Kerb stone: flame-textured granite in units with head joints between them.
 *
 * A kerb is one run of units, so the tile has head joints across it and no bed joint along it:
 * u runs along the kerb, and the v extent is enough for a top and a face. The tile is a whole
 * number of times longer than it is wide, and every cellular field is stated as a count across
 * the kerb and laid that many times more often along it, so crystals stay round on the stone.
 * Baked at the same proportion in texels, the texels are square too.
 *
 * The granite is four minerals by share of the crystals: feldspar, quartz, biotite, and
 * plagioclase for the remainder. Flaming pops crystals proud of the surface by differing amounts.
 */
export const kerbManifest: MakerManifest = {
  profile: MAKER_PROFILE,
  maker_id: 'loom.kerb',
  version: 1,
  kind: 'procedural',
  family: 'kerb',
  surface: 'horizontal',
  truth: 'invented',
  controls: [
    integer('unit_module_mm', 'module', 'mm', [100, 3000], 900, 'Unit length',
      'One kerb unit plus one joint, along the kerb.'),
    integer('head_joint_mm', 'module', 'mm', [1, 30], 6, 'Joint width',
      'The gap between kerb units.'),
    integer('units_per_tile', 'module', 'count', [1, 64], 2, 'Units per tile',
      'Whole kerb units along one tile.'),
    integer('tile_proportion', 'module', 'count', [1, 16], 4, 'Tile proportion',
      'How many times longer the tile is than it is wide.'),
    colour('feldspar_colour', [194, 188, 182], 'Feldspar', 'The commonest crystal.'),
    integer('feldspar_percent', 'colour', 'percent', [0, 100], 50, 'Feldspar share',
      'How many crystals are feldspar.'),
    integer('feldspar_roughness_permille', 'finish', 'permille', [0, 1000], 740,
      'Feldspar roughness', 'How matte a feldspar crystal is, in thousandths.'),
    colour('quartz_colour', [166, 168, 172], 'Quartz', 'The glassy grey crystal.'),
    integer('quartz_percent', 'colour', 'percent', [0, 100], 22, 'Quartz share',
      'How many crystals are quartz.'),
    integer('quartz_roughness_permille', 'finish', 'permille', [0, 1000], 620,
      'Quartz roughness', 'How matte a quartz crystal is, in thousandths.'),
    colour('biotite_colour', [48, 48, 52], 'Biotite', 'The dark mica.'),
    integer('biotite_percent', 'colour', 'percent', [0, 100], 14, 'Biotite share',
      'How many crystals are biotite.'),
    integer('biotite_roughness_permille', 'finish', 'permille', [0, 1000], 460,
      'Biotite roughness', 'How matte a biotite crystal is, in thousandths.'),
    colour('plagioclase_colour', [214, 210, 204], 'Plagioclase',
      'The pale crystal that makes up the remainder.'),
    integer('plagioclase_roughness_permille', 'finish', 'permille', [0, 1000], 760,
      'Plagioclase roughness', 'How matte a plagioclase crystal is, in thousandths.'),
    colour('joint_colour', [78, 76, 72], 'Joint colour', 'The mortar between units.'),
    colour('grime_colour', [96, 92, 86], 'Grime colour', 'What dirt on the kerb looks like.'),
    integer('face_height_mm_1024ths', 'relief', 'mm_1024ths', [0, 61440], 4608, 'Face height',
      'Where the stone face sits in the height range.'),
    integer('joint_height_mm_1024ths', 'relief', 'mm_1024ths', [0, 61440], 1024,
      'Joint height', 'Where the mortar in a joint sits.'),
    integer('arris_mm', 'relief', 'mm', [0, 20], 4, 'Edge rounding',
      'The width over which a unit edge rounds off.'),
    integer('crystal_cells_across', 'detail', 'cells_per_tile', [1, 512], 150, 'Crystal size',
      'How many crystals fit across the tile; more means smaller crystals.'),
    integer('grain_cells_across', 'detail', 'cells_per_tile', [1, 512], 300, 'Grain size',
      'How many cells of the fine flamed texture fit across the tile.'),
    integer('joint_grit_cells_across', 'detail', 'cells_per_tile', [1, 512], 200,
      'Joint grit size', 'How many grit cells fit across the tile.'),
    integer('grime_cells_across', 'wear', 'cells_per_tile', [1, 64], 2, 'Grime scale',
      'How many grime patches fit across the tile.'),
    integer('crystal_lift_mm_1024ths', 'relief', 'mm_1024ths', [0, 4096], 500, 'Crystal lift',
      'How far flaming may raise or lower a crystal.'),
    integer('crystal_boundary_mm_1024ths', 'relief', 'mm_1024ths', [0, 4096], 350,
      'Crystal boundary depth', 'How deep the boundaries between crystals are.'),
    integer('grain_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 200, 'Grain relief',
      'The height of the fine flamed texture.'),
    integer('unit_tilt_mm_1024ths', 'relief', 'mm_1024ths', [0, 4096], 500, 'Unit tilt',
      'How far a unit may lean from one end to the other.'),
    integer('joint_grain_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 250, 'Joint grain',
      'The height of the grit in a joint.'),
    integer('crystal_brightness_spread_q16', 'colour', 'q16', [0, 32768], 3000,
      'Crystal-to-crystal variation', 'How much one crystal may be lighter or darker.'),
    integer('unit_brightness_spread_q16', 'colour', 'q16', [0, 32768], 2000,
      'Unit-to-unit variation', 'How much one unit may be lighter or darker than the next.'),
    integer('boundary_darkening_percent', 'colour', 'percent', [0, 100], 12,
      'Boundary darkening', 'How much darker a crystal boundary is.'),
    integer('stone_roughness_spread_q16', 'finish', 'q16', [0, 32768], 2600,
      'Roughness variation', 'How much the flamed texture varies the roughness.'),
    integer('joint_grit_spread_q16', 'colour', 'q16', [0, 32768], 5000, 'Joint mottling',
      'Fine colour variation across the joints.'),
    integer('joint_roughness_permille', 'finish', 'permille', [0, 1000], 950,
      'Joint roughness', 'How matte the joints are, in thousandths.'),
    integer('grime_percent', 'wear', 'percent', [0, 100], 22, 'Grime',
      'How far the heaviest grime goes toward the grime colour.'),
    ...commonControls({
      heightRangeMm: 6,
      occlusionRadiusMm: 4,
      occlusionDepthMm: 2,
      occlusionStrengthPermille: 450,
    }),
  ],
  constraints: [
    equal(
      product(param('units_per_tile'), param('unit_module_mm')),
      extent('u'),
      'units per tile times the unit module must equal the tile length',
    ),
    equal(
      product(param('tile_proportion'), extent('v')),
      extent('u'),
      'the tile is the stated number of times longer than it is wide',
    ),
    less(param('head_joint_mm'), param('unit_module_mm'),
      'a joint cannot be as long as the unit module'),
    lessOrEqual(
      sum(param('feldspar_percent'), param('quartz_percent'), param('biotite_percent')),
      constant(100),
      'the mineral shares cannot add up to more than every crystal',
    ),
    lessOrEqual(
      param('face_height_mm_1024ths'),
      product(param('height_range_mm'), constant(MM)),
      'the stone face must lie inside the height range',
    ),
  ],
};

function spec(recipe: Recipe): BondSpec {
  const module = read.integer(recipe, 'unit_module_mm');
  return {
    moduleU: module,
    moduleV: recipe.extent_mm.v,
    jointU: read.integer(recipe, 'head_joint_mm'),
    jointV: 0,
    unitsPerCourse: read.integer(recipe, 'units_per_tile'),
    courses: 1,
    oddCourseShift: 0,
    // Half a unit, so the tile edge crosses a unit rather than a joint.
    phaseU: (module * MM) / 2,
    phaseV: 0,
  };
}

function pattern(recipe: Recipe): Pattern {
  const bondSpec = spec(recipe);
  const extentU = recipe.extent_mm.u;
  const extentV = recipe.extent_mm.v;
  checkBond(bondSpec, extentU, extentV);
  const seed = recipe.seed;
  const along = read.integer(recipe, 'tile_proportion');
  const feldspar = decode(read.colour(recipe, 'feldspar_colour'));
  const quartz = decode(read.colour(recipe, 'quartz_colour'));
  const biotite = decode(read.colour(recipe, 'biotite_colour'));
  const plagioclase = decode(read.colour(recipe, 'plagioclase_colour'));
  const joint = decode(read.colour(recipe, 'joint_colour'));
  const grime = decode(read.colour(recipe, 'grime_colour'));
  const feldsparBelow = read.integer(recipe, 'feldspar_percent');
  const quartzBelow = feldsparBelow + read.integer(recipe, 'quartz_percent');
  const biotiteBelow = quartzBelow + read.integer(recipe, 'biotite_percent');
  const feldsparRough = permille(read.integer(recipe, 'feldspar_roughness_permille'));
  const quartzRough = permille(read.integer(recipe, 'quartz_roughness_permille'));
  const biotiteRough = permille(read.integer(recipe, 'biotite_roughness_permille'));
  const plagioclaseRough = permille(read.integer(recipe, 'plagioclase_roughness_permille'));
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const faceHeight = read.integer(recipe, 'face_height_mm_1024ths');
  const jointHeight = read.integer(recipe, 'joint_height_mm_1024ths');
  const arrisMm = read.integer(recipe, 'arris_mm');
  const crystalCells = read.integer(recipe, 'crystal_cells_across');
  const grainCells = read.integer(recipe, 'grain_cells_across');
  const gritCells = read.integer(recipe, 'joint_grit_cells_across');
  const grimeCells = read.integer(recipe, 'grime_cells_across');
  const liftMax = read.integer(recipe, 'crystal_lift_mm_1024ths');
  const boundaryDepth = read.integer(recipe, 'crystal_boundary_mm_1024ths');
  const grainRelief = read.integer(recipe, 'grain_relief_mm_1024ths');
  const tiltMax = read.integer(recipe, 'unit_tilt_mm_1024ths');
  const jointGrain = read.integer(recipe, 'joint_grain_mm_1024ths');
  const crystalSpread = read.integer(recipe, 'crystal_brightness_spread_q16');
  const unitSpread = read.integer(recipe, 'unit_brightness_spread_q16');
  const boundaryDarkening = read.integer(recipe, 'boundary_darkening_percent');
  const roughnessSpread = read.integer(recipe, 'stone_roughness_spread_q16');
  const gritSpread = read.integer(recipe, 'joint_grit_spread_q16');
  const jointRoughness = permille(read.integer(recipe, 'joint_roughness_permille'));
  const grimePercent = read.integer(recipe, 'grime_percent');
  const units = stream(seed, 1);
  const crystalSeed = stream(seed, 2);
  const fineSeed = stream(seed, 3);
  const dirtSeed = stream(seed, 4);
  const jointSeed = stream(seed, 5);
  const faceSize = (bondSpec.moduleU - bondSpec.jointU) * MM;
  const at = newBondSample();
  const crystal: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    bond(tileToLength(x, extentU), tileToLength(y, extentV), bondSpec, at);
    const arris = at.edge <= 0 ? 0 : smoothstep(0, arrisMm * MM, at.edge);
    const coverage = smoothstep(-MM, MM, at.edge);

    cells(x, y, crystalCells * along, crystalCells, crystalSeed, ONE, crystal);
    const share = pick(crystal.id, 0, 99);
    let mineral: Linear;
    let mineralRough: number;
    if (share < feldsparBelow) {
      mineral = feldspar;
      mineralRough = feldsparRough;
    } else if (share < quartzBelow) {
      mineral = quartz;
      mineralRough = quartzRough;
    } else if (share < biotiteBelow) {
      mineral = biotite;
      mineralRough = biotiteRough;
    } else {
      mineral = plagioclase;
      mineralRough = plagioclaseRough;
    }
    const boundary = band(ONE - (crystal.second - crystal.nearest), 56000, 65536);
    const fine = fbm(x, y, grainCells * along, grainCells, fineSeed, 1);
    const lift = pick(hash3(crystal.id, 1, 0, crystalSeed), -liftMax, liftMax);
    const tiltU = pick(hash3(at.unit, 0, 1, units), -tiltMax, tiltMax);
    const face = faceHeight
      + lift
      - floorDiv(boundary * boundaryDepth, ONE)
      + floorDiv((fine - 32768) * grainRelief, 32768)
      + floorDiv(tiltU * (2 * at.faceU - faceSize), 2 * faceSize);
    const gritNoise = valueNoise(x, y, gritCells * along, gritCells, jointSeed);
    const jointLength = jointHeight + floorDiv((gritNoise - 32768) * jointGrain, 32768);
    out.height = heightOfLength(lerp(jointLength, face, arris), rangeMm);

    setColour(out, mineral);
    shade(out, jitter(bits16(hash3(crystal.id, 2, 0, crystalSeed)), crystalSpread));
    shade(out, jitter(bits16(hash3(at.unit, 0, 3, units)), unitSpread));
    shade(out, ONE - floorDiv(boundary * boundaryDarkening, 100));
    const stoneRed = out.red;
    const stoneGreen = out.green;
    const stoneBlue = out.blue;
    const stoneRough = mineralRough + floorDiv((fine - 32768) * roughnessSpread, 32768);

    setColour(out, joint);
    shade(out, jitter(gritNoise, gritSpread));
    out.red = lerp(out.red, stoneRed, coverage);
    out.green = lerp(out.green, stoneGreen, coverage);
    out.blue = lerp(out.blue, stoneBlue, coverage);
    out.roughness = clamp(lerp(jointRoughness, stoneRough, coverage), 0, FULL);

    const dirt = band(fbm(x, y, grimeCells * along, grimeCells, dirtSeed, 3), 28000, 46000);
    mixColour(out, grime, floorDiv(dirt * grimePercent, 100));

    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const kerbMaker: Maker = {
  manifest: kerbManifest,
  stated(recipe) {
    const bondSpec = spec(recipe);
    return {
      stone: 'granite, flame textured',
      unit_length_mm: bondSpec.moduleU,
      head_joint_mm: bondSpec.jointU,
      units_per_tile: bondSpec.unitsPerCourse,
      bed_joint_mm: bondSpec.jointV,
      phase_u_mm_1024ths: bondSpec.phaseU,
      face_height_mm_1024ths: read.integer(recipe, 'face_height_mm_1024ths'),
      joint_height_mm_1024ths: read.integer(recipe, 'joint_height_mm_1024ths'),
      arris_mm: read.integer(recipe, 'arris_mm'),
      crystal_cell_mm_1024ths: floorDiv(
        recipe.extent_mm.u * MM,
        read.integer(recipe, 'crystal_cells_across') * read.integer(recipe, 'tile_proportion'),
      ),
    };
  },
  pattern,
};
