import { type BondSpec, bond, checkBond, newBondSample } from '../bond.js';
import {
  choice,
  colour,
  commonControls,
  constant,
  equal,
  even,
  extent,
  integer,
  less,
  lessOrEqual,
  palette,
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
import { decode } from '../srgb.js';
import { MM, tileToLength } from '../tile.js';

/**
 * Footway paving: square precast concrete flags on a stated module, with grit-filled joints.
 *
 * Each flag sits at its own slight tilt (lippage), has a chamfer, and carries exposed fine
 * aggregate. Pavement wear shows as faint staining and as the flat dark spots of trodden-in gum,
 * which is what a city footway actually looks like at walking distance. Flags are laid in stack
 * bond or running bond; the noise scales that give the concrete its texture are fixed in this
 * version, and everything a person would name is a control.
 */
const BONDS: Readonly<Record<string, string>> = {
  running: 'running: alternate courses offset by half a module',
  stack: 'stack: no offset between courses',
};

const RUNNING = { param: 'bond', equals: 'running' };

export const pavingManifest: MakerManifest = {
  profile: MAKER_PROFILE,
  maker_id: 'loom.paving',
  version: 1,
  kind: 'procedural',
  family: 'paving',
  surface: 'horizontal',
  truth: 'invented',
  controls: [
    choice('bond', 'module', ['running', 'stack'], 'stack', 'Bond',
      'Stack lines every joint up; running offsets alternate rows by half a flag.'),
    integer('flag_module_mm', 'module', 'mm', [100, 1500], 600, 'Flag size',
      'One flag plus one joint, each way.'),
    integer('joint_mm', 'module', 'mm', [1, 30], 6, 'Joint width',
      'The grit-filled gap between flags.'),
    integer('flags_per_row', 'module', 'count', [1, 64], 3, 'Flags per row',
      'Whole flags across one tile.'),
    integer('rows', 'module', 'count', [1, 64], 3, 'Rows', 'Whole rows of flags along one tile.'),
    palette('flag_palette', [
      [172, 168, 160],
      [164, 162, 158],
      [180, 176, 166],
      [158, 154, 148],
    ], [1, 16], 'Flag colours', 'Each flag takes one of these tones.'),
    colour('joint_grit_colour', [84, 80, 74], 'Joint colour', 'The grit in the joints.'),
    colour('aggregate_dark_colour', [132, 128, 122], 'Dark aggregate',
      'Dark stone exposed in a flag face.'),
    colour('aggregate_light_colour', [198, 194, 186], 'Light aggregate',
      'Pale stone exposed in a flag face.'),
    colour('gum_colour', [92, 90, 88], 'Gum colour', 'Trodden-in chewing gum at its darkest.'),
    colour('stain_colour', [118, 112, 104], 'Stain colour', 'Broad, faint staining.'),
    integer('face_height_mm', 'relief', 'mm', [1, 60], 6, 'Face height',
      'How far a flag face stands above the bottom of the height range.'),
    integer('joint_fill_height_mm_1024ths', 'relief', 'mm_1024ths', [0, 61440], 2560,
      'Joint fill height', 'Where the grit in the joints sits.'),
    integer('chamfer_mm', 'relief', 'mm', [0, 20], 3, 'Chamfer',
      'The width over which a flag edge bevels down.'),
    integer('chip_depth_max_mm', 'wear', 'mm', [0, 20], 2, 'Chipping',
      'The deepest a chipped edge eats into a flag face.'),
    integer('lippage_max_mm_1024ths', 'relief', 'mm_1024ths', [0, 4096], 800, 'Lippage',
      'How far a flag may lean from one side to the other.'),
    integer('face_texture_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 150, 'Face texture',
      'The height of the fine texture on a flag face.'),
    integer('aggregate_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 200,
      'Aggregate relief', 'How far exposed stone stands proud of the face.'),
    integer('gum_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 180, 'Gum relief',
      'How far a gum spot stands proud of the face.'),
    integer('joint_grain_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 300, 'Joint grain',
      'The height of the grit grains in a joint.'),
    integer('aggregate_percent', 'detail', 'percent', [0, 100], 55, 'Aggregate density',
      'How many small cells of a flag face show a stone.'),
    integer('aggregate_mix_percent', 'colour', 'percent', [0, 100], 60, 'Aggregate contrast',
      'How strongly an exposed stone shows against the flag.'),
    integer('gum_permille', 'wear', 'permille', [0, 1000], 16, 'Gum',
      'How many gum-sized cells hold a spot, in thousandths.'),
    integer('gum_shade_percent', 'wear', 'percent', [0, 100], 55, 'Gum darkness',
      'How far the lightest gum spot goes toward the gum colour.'),
    integer('gum_shade_spread_percent', 'wear', 'percent', [0, 100], 35, 'Gum variation',
      'How much darker than that a spot may be.'),
    integer('flag_brightness_spread_q16', 'colour', 'q16', [0, 32768], 3300,
      'Flag-to-flag variation', 'How much one flag may be lighter or darker than the next.'),
    integer('face_texture_spread_q16', 'colour', 'q16', [0, 32768], 1800, 'Face mottling',
      'Fine colour variation across a flag face.'),
    integer('joint_grit_spread_q16', 'colour', 'q16', [0, 32768], 5000, 'Joint mottling',
      'Fine colour variation across the joints.'),
    integer('flag_roughness_permille', 'finish', 'permille', [0, 1000], 900, 'Flag roughness',
      'How matte a flag face is, in thousandths.'),
    integer('gum_roughness_permille', 'finish', 'permille', [0, 1000], 560, 'Gum roughness',
      'How matte a gum spot is, in thousandths.'),
    integer('face_roughness_spread_q16', 'finish', 'q16', [0, 32768], 2000,
      'Roughness variation', 'How much the face texture varies the roughness.'),
    integer('joint_roughness_permille', 'finish', 'permille', [0, 1000], 960,
      'Joint roughness', 'How matte the joints are, in thousandths.'),
    integer('stain_percent', 'wear', 'percent', [0, 100], 20, 'Staining',
      'How far the heaviest staining goes toward the stain colour.'),
    integer('chamfer_darkening_percent', 'colour', 'percent', [0, 100], 6, 'Edge darkening',
      'How much darker a chamfer is than the face.'),
    ...commonControls({
      heightRangeMm: 8,
      occlusionRadiusMm: 8,
      occlusionDepthMm: 3,
      occlusionStrengthPermille: 500,
    }),
  ],
  constraints: [
    equal(
      product(param('flags_per_row'), param('flag_module_mm')),
      extent('u'),
      'flags per row times the flag module must equal the tile width',
    ),
    equal(
      product(param('rows'), param('flag_module_mm')),
      extent('v'),
      'rows times the flag module must equal the tile length',
    ),
    even(param('rows'), 'running bond repeats every two rows, so the tile holds an even number',
      RUNNING),
    less(param('joint_mm'), param('flag_module_mm'),
      'a joint cannot be as wide as the flag module'),
    lessOrEqual(param('face_height_mm'), param('height_range_mm'),
      'the flag face must lie inside the height range'),
    lessOrEqual(
      param('joint_fill_height_mm_1024ths'),
      product(param('face_height_mm'), constant(MM)),
      'the joint fill cannot stand above the flag face',
    ),
    lessOrEqual(
      sum(param('gum_shade_percent'), param('gum_shade_spread_percent')),
      constant(100),
      'the darkest gum spot cannot go past the gum colour',
    ),
  ],
};

function spec(recipe: Recipe): BondSpec {
  const module = read.integer(recipe, 'flag_module_mm');
  const joint = read.integer(recipe, 'joint_mm');
  return {
    moduleU: module,
    moduleV: module,
    jointU: joint,
    jointV: joint,
    unitsPerCourse: read.integer(recipe, 'flags_per_row'),
    courses: read.integer(recipe, 'rows'),
    oddCourseShift: read.choice(recipe, 'bond') === 'running' ? (module * MM) / 2 : 0,
    // Half a module each way, so the tile edge crosses flags rather than running down a joint.
    phaseU: (module * MM) / 2,
    phaseV: (module * MM) / 2,
  };
}

function pattern(recipe: Recipe): Pattern {
  const bondSpec = spec(recipe);
  const extentU = recipe.extent_mm.u;
  const extentV = recipe.extent_mm.v;
  checkBond(bondSpec, extentU, extentV);
  const seed = recipe.seed;
  const flags = read.palette(recipe, 'flag_palette').map(decode);
  const grit = decode(read.colour(recipe, 'joint_grit_colour'));
  const aggregateDark = decode(read.colour(recipe, 'aggregate_dark_colour'));
  const aggregateLight = decode(read.colour(recipe, 'aggregate_light_colour'));
  const gum = decode(read.colour(recipe, 'gum_colour'));
  const stain = decode(read.colour(recipe, 'stain_colour'));
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const faceMm = read.integer(recipe, 'face_height_mm');
  const jointFill = read.integer(recipe, 'joint_fill_height_mm_1024ths');
  const chamferMm = read.integer(recipe, 'chamfer_mm');
  const chipMm = read.integer(recipe, 'chip_depth_max_mm');
  const lippage = read.integer(recipe, 'lippage_max_mm_1024ths');
  const faceTexture = read.integer(recipe, 'face_texture_mm_1024ths');
  const aggregateRelief = read.integer(recipe, 'aggregate_relief_mm_1024ths');
  const gumRelief = read.integer(recipe, 'gum_relief_mm_1024ths');
  const jointGrain = read.integer(recipe, 'joint_grain_mm_1024ths');
  const aggregatePercent = read.integer(recipe, 'aggregate_percent');
  const aggregateMix = read.integer(recipe, 'aggregate_mix_percent');
  const gumPermille = read.integer(recipe, 'gum_permille');
  const gumShadeMin = read.integer(recipe, 'gum_shade_percent');
  const gumShadeSpread = read.integer(recipe, 'gum_shade_spread_percent');
  const flagSpread = read.integer(recipe, 'flag_brightness_spread_q16');
  const textureSpread = read.integer(recipe, 'face_texture_spread_q16');
  const gritSpread = read.integer(recipe, 'joint_grit_spread_q16');
  const flagRoughness = permille(read.integer(recipe, 'flag_roughness_permille'));
  const gumRoughness = permille(read.integer(recipe, 'gum_roughness_permille'));
  const roughnessSpread = read.integer(recipe, 'face_roughness_spread_q16');
  const jointRoughness = permille(read.integer(recipe, 'joint_roughness_permille'));
  const stainPercent = read.integer(recipe, 'stain_percent');
  const chamferDarkening = read.integer(recipe, 'chamfer_darkening_percent');
  const units = stream(seed, 1);
  const textureSeed = stream(seed, 2);
  const aggregateSeed = stream(seed, 3);
  const chipSeed = stream(seed, 4);
  const gumSeed = stream(seed, 5);
  const stainSeed = stream(seed, 6);
  const gritSeed = stream(seed, 7);
  const faceSize = (bondSpec.moduleU - bondSpec.jointU) * MM;
  const at = newBondSample();
  const stone: CellSample = { nearest: 0, second: 0, id: 0 };
  const spot: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    bond(tileToLength(x, extentU), tileToLength(y, extentV), bondSpec, at);

    const chipField = band(fbm(x, y, 90, 90, chipSeed, 3), 40000, 52000);
    const edge = at.edge - floorDiv(chipField * chipMm * MM, ONE);
    const chamfer = edge <= 0 ? 0 : smoothstep(0, chamferMm * MM, edge);
    const coverage = smoothstep(-MM, MM, at.edge);

    const texture = fbm(x, y, 300, 300, textureSeed, 2);
    cells(x, y, 700, 700, aggregateSeed, ONE, stone);
    const stoneRadius = 18000 + pick(stone.id, 0, 9000);
    const exposed = pick(hash3(stone.id, 1, 0, aggregateSeed), 0, 99) < aggregatePercent
      && stone.nearest < stoneRadius
      ? smoothstep(0, 7000, stoneRadius - stone.nearest)
      : 0;
    // Trodden-in gum: sparse, each spot its own size and its own depth of grey.
    cells(x, y, 60, 60, gumSeed, ONE, spot);
    const gumRadius = 10000 + pick(spot.id, 0, 10000);
    const gumShade = gumShadeMin + pick(hash3(spot.id, 2, 0, gumSeed), 0, gumShadeSpread);
    const gummed = pick(hash3(spot.id, 1, 0, gumSeed), 0, 999) < gumPermille
      && spot.nearest < gumRadius
      ? floorDiv(smoothstep(0, 2600, gumRadius - spot.nearest) * gumShade, 100)
      : 0;

    const tiltU = pick(hash3(at.unit, at.course, 1, units), -lippage, lippage);
    const tiltV = pick(hash3(at.unit, at.course, 2, units), -lippage, lippage);
    const face = faceMm * MM
      + floorDiv(tiltU * (2 * at.faceU - faceSize), 2 * faceSize)
      + floorDiv(tiltV * (2 * at.faceV - faceSize), 2 * faceSize)
      + floorDiv((texture - 32768) * faceTexture, 32768)
      + floorDiv(exposed * aggregateRelief, ONE)
      + floorDiv(gummed * gumRelief, ONE);
    const gritNoise = valueNoise(x, y, 900, 900, gritSeed);
    const joint = jointFill + floorDiv((gritNoise - 32768) * jointGrain, 32768);
    out.height = heightOfLength(lerp(joint, face, chamfer), rangeMm);

    const key = hash3(at.unit, at.course, 0, units);
    setColour(out, flags[pick(key, 0, flags.length - 1)]!);
    shade(out, jitter(bits16(hash3(at.unit, at.course, 3, units)), flagSpread));
    shade(out, jitter(texture, textureSpread));
    const light = pick(hash3(stone.id, 2, 0, aggregateSeed), 0, 1) === 0;
    mixColour(out, light ? aggregateLight : aggregateDark, floorDiv(exposed * aggregateMix, 100));
    mixColour(out, gum, gummed);
    const flagRed = out.red;
    const flagGreen = out.green;
    const flagBlue = out.blue;
    const flagRough = lerp(flagRoughness, gumRoughness, gummed)
      + floorDiv((texture - 32768) * roughnessSpread, 32768);

    setColour(out, grit);
    shade(out, jitter(gritNoise, gritSpread));
    out.red = lerp(out.red, flagRed, coverage);
    out.green = lerp(out.green, flagGreen, coverage);
    out.blue = lerp(out.blue, flagBlue, coverage);
    out.roughness = clamp(lerp(jointRoughness, flagRough, coverage), 0, FULL);

    const stained = band(fbm(x, y, 10, 10, stainSeed, 4), 30000, 46000);
    mixColour(out, stain, floorDiv(stained * stainPercent, 100));
    shade(out, ONE - floorDiv(floorDiv((ONE - chamfer) * coverage, ONE) * chamferDarkening, 100));

    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const pavingMaker: Maker = {
  manifest: pavingManifest,
  stated(recipe) {
    const bondSpec = spec(recipe);
    return {
      bond: BONDS[read.choice(recipe, 'bond')]!,
      flag_module_mm: bondSpec.moduleU,
      flag_face_mm: bondSpec.moduleU - bondSpec.jointU,
      joint_mm: bondSpec.jointU,
      flags_per_row: bondSpec.unitsPerCourse,
      rows: bondSpec.courses,
      phase_u_mm_1024ths: bondSpec.phaseU,
      phase_v_mm_1024ths: bondSpec.phaseV,
      face_height_mm: read.integer(recipe, 'face_height_mm'),
      joint_fill_height_mm_1024ths: read.integer(recipe, 'joint_fill_height_mm_1024ths'),
      chamfer_mm: read.integer(recipe, 'chamfer_mm'),
      lippage_max_mm_1024ths: read.integer(recipe, 'lippage_max_mm_1024ths'),
      chip_depth_max_mm: read.integer(recipe, 'chip_depth_max_mm'),
    };
  },
  pattern,
};
