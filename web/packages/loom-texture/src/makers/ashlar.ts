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
import { ONE, clamp, floorDiv, lerp, smoothstep } from '../integer.js';
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
 * Coursed stone ashlar: blocks on a stated module, laid half bond or stacked, with fine joints,
 * tooled faces, bedding along the course, and the stone's own specks and shell fragments.
 *
 * The module here includes the joint, as a mason sets it out: a 600 mm module with a 5 mm joint is
 * a 595 mm block face. Bedding runs along the course, as it does in a block cut from a quarry bed
 * and laid the right way up.
 */
const BONDS: Readonly<Record<string, string>> = {
  half: 'half: alternate courses offset by half a module',
  stack: 'stack: no offset between courses',
};

export const ashlarManifest: MakerManifest = {
  profile: MAKER_PROFILE,
  maker_id: 'loom.ashlar',
  version: 1,
  kind: 'procedural',
  family: 'stone',
  surface: 'vertical',
  truth: 'invented',
  controls: [
    choice('bond', 'module', ['half', 'stack'], 'half', 'Bond',
      'Half bond offsets alternate courses by half a block; stack lines every joint up.'),
    integer('module_length_mm', 'module', 'mm', [100, 3000], 600, 'Block module length',
      'One block plus one head joint, along the course.'),
    integer('course_height_mm', 'module', 'mm', [50, 2000], 300, 'Course height',
      'One block plus one bed joint, up the wall.'),
    integer('head_joint_mm', 'module', 'mm', [1, 30], 5, 'Head joint',
      'The vertical joint between blocks.'),
    integer('bed_joint_mm', 'module', 'mm', [1, 30], 5, 'Bed joint',
      'The horizontal joint between courses.'),
    integer('units_per_course', 'module', 'count', [1, 32], 4, 'Blocks per course',
      'Whole blocks along one tile.'),
    integer('courses', 'module', 'count', [1, 64], 8, 'Courses', 'Whole courses down one tile.'),
    palette('palette', [
      [198, 188, 166],
      [192, 183, 163],
      [203, 194, 172],
      [189, 182, 165],
      [196, 185, 161],
    ], [1, 16], 'Stone colours', 'Each block takes one of these tones.'),
    colour('mortar_colour', [204, 198, 184], 'Joint colour', 'The lime mortar in the joints.'),
    colour('shell_light_colour', [224, 216, 198], 'Light fragments',
      'Pale shell and fossil fragments in the stone.'),
    colour('shell_dark_colour', [150, 142, 128], 'Dark fragments',
      'Dark shell and fossil fragments in the stone.'),
    colour('speck_light_colour', [214, 206, 188], 'Light specks', 'The stone\'s pale grain.'),
    colour('speck_dark_colour', [168, 160, 144], 'Dark specks', 'The stone\'s dark grain.'),
    integer('face_height_mm', 'relief', 'mm', [1, 60], 6, 'Face height',
      'How far the block face stands above the bottom of the height range.'),
    integer('joint_recess_mm', 'relief', 'mm', [0, 30], 3, 'Joint recess',
      'How far the joint sits behind the face.'),
    integer('arris_mm', 'relief', 'mm', [0, 20], 2, 'Edge rounding',
      'The width over which a block edge rounds off.'),
    integer('chip_depth_max_mm', 'wear', 'mm', [0, 20], 3, 'Chipping',
      'The deepest a chipped edge eats into a block face.'),
    integer('tooling_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 150, 'Tooling depth',
      'The height of the horizontal drag marks the mason\'s tool left.'),
    integer('face_grain_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 100, 'Face grain',
      'The height of the stone\'s fine surface texture.'),
    integer('face_waviness_mm_1024ths', 'relief', 'mm_1024ths', [0, 4096], 300, 'Face waviness',
      'How far a block face departs from flat over a few hundred millimetres.'),
    integer('joint_grain_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 120, 'Joint grain',
      'The height of sand grains in the joints.'),
    integer('block_brightness_spread_q16', 'colour', 'q16', [0, 32768], 1900,
      'Block-to-block variation', 'How much one block may be lighter or darker than the next.'),
    integer('bedding_spread_q16', 'colour', 'q16', [0, 32768], 1700, 'Bedding',
      'Colour variation in thin layers along the course.'),
    integer('cloud_spread_q16', 'colour', 'q16', [0, 32768], 3000, 'Cloudiness',
      'Soft colour variation within a block.'),
    integer('grain_spread_q16', 'colour', 'q16', [0, 32768], 1600, 'Grain colour',
      'Fine colour variation from the stone\'s grain.'),
    integer('speck_light_percent', 'detail', 'percent', [0, 100], 17, 'Light specks',
      'How often a small cell holds a pale speck.'),
    integer('speck_dark_percent', 'detail', 'percent', [0, 100], 17, 'Dark specks',
      'How often a small cell holds a dark speck.'),
    integer('speck_strength_percent', 'detail', 'percent', [0, 100], 55, 'Speck strength',
      'How strongly a speck shows.'),
    integer('shell_light_percent', 'detail', 'percent', [0, 100], 9, 'Light fragments',
      'How often a cell holds a pale fragment.'),
    integer('shell_dark_percent', 'detail', 'percent', [0, 100], 7, 'Dark fragments',
      'How often a cell holds a dark fragment.'),
    integer('mortar_grain_spread_q16', 'colour', 'q16', [0, 32768], 3000, 'Joint mottling',
      'Fine colour variation across the joints.'),
    integer('stone_roughness_permille', 'finish', 'permille', [0, 1000], 800, 'Stone roughness',
      'How matte a block face is, in thousandths.'),
    integer('mortar_roughness_permille', 'finish', 'permille', [0, 1000], 920,
      'Joint roughness', 'How matte the joints are, in thousandths.'),
    integer('dirt_percent', 'wear', 'percent', [0, 50], 8, 'Dirt',
      'The darkest broad dirt gets, in percent.'),
    integer('low_dirt_percent', 'wear', 'percent', [0, 50], 5, 'Dirt at block bottoms',
      'Extra darkening toward the bottom of each block, where water sits.'),
    ...commonControls({
      heightRangeMm: 8,
      occlusionRadiusMm: 10,
      occlusionDepthMm: 3,
      occlusionStrengthPermille: 450,
    }),
  ],
  constraints: [
    equal(product(param('units_per_course'), param('module_length_mm')), extent('u'),
      'blocks per course times the module length must equal the tile width'),
    equal(product(param('courses'), param('course_height_mm')), extent('v'),
      'courses times the course height must equal the tile height'),
    even(param('courses'), 'half bond repeats every two courses, so the tile holds an even number',
      { param: 'bond', equals: 'half' }),
    less(param('head_joint_mm'), param('module_length_mm'), 'a joint is narrower than its module'),
    less(param('bed_joint_mm'), param('course_height_mm'), 'a joint is narrower than its course'),
    lessOrEqual(sum(param('speck_light_percent'), param('speck_dark_percent')), constant(100),
      'light and dark specks together cannot exceed every cell'),
    lessOrEqual(sum(param('shell_light_percent'), param('shell_dark_percent')), constant(100),
      'light and dark fragments together cannot exceed every cell'),
    lessOrEqual(param('joint_recess_mm'), param('face_height_mm'),
      'the joint cannot sit below the bottom of the height range'),
    lessOrEqual(param('face_height_mm'), param('height_range_mm'),
      'the block face must lie inside the height range'),
    lessOrEqual(sum(param('dirt_percent'), param('low_dirt_percent')), constant(100),
      'dirt cannot darken past black'),
  ],
};

function spec(recipe: Recipe): BondSpec {
  const moduleU = read.integer(recipe, 'module_length_mm');
  const moduleV = read.integer(recipe, 'course_height_mm');
  return {
    moduleU,
    moduleV,
    jointU: read.integer(recipe, 'head_joint_mm'),
    jointV: read.integer(recipe, 'bed_joint_mm'),
    unitsPerCourse: read.integer(recipe, 'units_per_course'),
    courses: read.integer(recipe, 'courses'),
    oddCourseShift: read.choice(recipe, 'bond') === 'half' ? (moduleU * MM) / 2 : 0,
    phaseU: (moduleU * MM) / 4,
    phaseV: (moduleV * MM) / 2,
  };
}

function pattern(recipe: Recipe): Pattern {
  const bondSpec = spec(recipe);
  const extentU = recipe.extent_mm.u;
  const extentV = recipe.extent_mm.v;
  checkBond(bondSpec, extentU, extentV);
  const seed = recipe.seed;
  const stone = read.palette(recipe, 'palette').map(decode);
  const mortar = decode(read.colour(recipe, 'mortar_colour'));
  const shellLight = decode(read.colour(recipe, 'shell_light_colour'));
  const shellDark = decode(read.colour(recipe, 'shell_dark_colour'));
  const speckLight = decode(read.colour(recipe, 'speck_light_colour'));
  const speckDark = decode(read.colour(recipe, 'speck_dark_colour'));
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const faceMm = read.integer(recipe, 'face_height_mm');
  const recessMm = read.integer(recipe, 'joint_recess_mm');
  const arrisMm = read.integer(recipe, 'arris_mm');
  const chipMm = read.integer(recipe, 'chip_depth_max_mm');
  const tooling = read.integer(recipe, 'tooling_mm_1024ths');
  const faceGrain = read.integer(recipe, 'face_grain_mm_1024ths');
  const waviness = read.integer(recipe, 'face_waviness_mm_1024ths');
  const jointGrain = read.integer(recipe, 'joint_grain_mm_1024ths');
  const blockSpread = read.integer(recipe, 'block_brightness_spread_q16');
  const beddingSpread = read.integer(recipe, 'bedding_spread_q16');
  const cloudSpread = read.integer(recipe, 'cloud_spread_q16');
  const grainSpread = read.integer(recipe, 'grain_spread_q16');
  const speckLightPercent = read.integer(recipe, 'speck_light_percent');
  const speckPercent = speckLightPercent + read.integer(recipe, 'speck_dark_percent');
  const speckStrength = read.integer(recipe, 'speck_strength_percent');
  const shellLightPercent = read.integer(recipe, 'shell_light_percent');
  const shellPercent = shellLightPercent + read.integer(recipe, 'shell_dark_percent');
  const mortarSpread = read.integer(recipe, 'mortar_grain_spread_q16');
  const stoneRoughness = permille(read.integer(recipe, 'stone_roughness_permille'));
  const mortarRoughness = permille(read.integer(recipe, 'mortar_roughness_permille'));
  const dirtPercent = read.integer(recipe, 'dirt_percent');
  const lowDirtPercent = read.integer(recipe, 'low_dirt_percent');
  const blocks = stream(seed, 1);
  const toolSeed = stream(seed, 2);
  const grainSeed = stream(seed, 3);
  const waveSeed = stream(seed, 4);
  const bedSeed = stream(seed, 5);
  const shellSeed = stream(seed, 6);
  const dirtSeed = stream(seed, 7);
  const cloudSeed = stream(seed, 8);
  const chipSeed = stream(seed, 9);
  const sandSeed = stream(seed, 10);
  const speckSeed = stream(seed, 11);
  const faceHeight = (bondSpec.moduleV - bondSpec.jointV) * MM;
  const at = newBondSample();
  const shell: CellSample = { nearest: 0, second: 0, id: 0 };
  const speck: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    bond(tileToLength(x, extentU), tileToLength(y, extentV), bondSpec, at);

    const chipField = band(fbm(x, y, 96, 96, chipSeed, 3), 38000, 52000);
    const edge = at.edge - floorDiv(chipField * chipMm * MM, ONE);
    const arris = edge <= 0 ? 0 : smoothstep(0, arrisMm * MM, edge);
    const coverage = smoothstep(-MM, MM, at.edge);

    // Tooling: long horizontal drag marks, 40 mm along and 5 mm across at 2400 mm to a tile.
    const tool = valueNoise(x, y, 60, 480, toolSeed);
    const grain = fbm(x, y, 800, 800, grainSeed, 2);
    const wave = fbm(x, y, 8, 8, waveSeed, 2);
    const sand = valueNoise(x, y, 960, 960, sandSeed);
    const face = faceMm * MM
      + floorDiv((tool - 32768) * tooling, 32768)
      + floorDiv((grain - 32768) * faceGrain, 32768)
      + floorDiv((wave - 32768) * waviness, 32768);
    const joint = (faceMm - recessMm) * MM + floorDiv((sand - 32768) * jointGrain, 32768);
    out.height = heightOfLength(lerp(joint, face, arris), rangeMm);

    const key = hash3(at.unit, at.course, 0, blocks);
    setColour(out, stone[pick(key, 0, stone.length - 1)]!);
    shade(out, jitter(bits16(hash3(at.unit, at.course, 1, blocks)), blockSpread));
    // Bedding: thin layers along the course, and a soft cloudiness within a block.
    shade(out, jitter(valueNoise(x, y, 6, 180, bedSeed), beddingSpread));
    shade(out, jitter(fbm(x, y, 24, 24, cloudSeed, 3), cloudSpread));
    shade(out, jitter(grain, grainSpread));
    // The stone's own grain: light and dark specks about a texel across.
    cells(x, y, 900, 900, speckSeed, ONE, speck);
    const speckPick = pick(speck.id, 0, 99);
    if (speckPick < speckPercent && speck.nearest < 20000) {
      const t = smoothstep(0, 9000, 20000 - speck.nearest);
      mixColour(
        out,
        speckPick < speckLightPercent ? speckLight : speckDark,
        floorDiv(t * speckStrength, 100),
      );
    }
    cells(x, y, 500, 500, shellSeed, ONE, shell);
    const shellPick = pick(shell.id, 0, 99);
    if (shellPick < shellPercent && shell.nearest < 13000) {
      const t = floorDiv((13000 - shell.nearest) * ONE, 13000);
      mixColour(out, shellPick < shellLightPercent ? shellLight : shellDark, t >> 1);
    }
    // Dirt settles toward the bottom of each block, where the joint below holds water.
    const low = smoothstep(faceHeight >> 1, faceHeight, at.faceV);
    const chipped = at.edge >= 0 ? floorDiv((ONE - arris) * chipField, ONE) : 0;
    const stoneRed = out.red;
    const stoneGreen = out.green;
    const stoneBlue = out.blue;
    const stoneRough = stoneRoughness + floorDiv((tool - 32768) * 2600, 32768)
      + floorDiv(chipped * 5, 100);

    setColour(out, mortar);
    shade(out, jitter(sand, mortarSpread));
    out.red = lerp(out.red, stoneRed, coverage);
    out.green = lerp(out.green, stoneGreen, coverage);
    out.blue = lerp(out.blue, stoneBlue, coverage);
    out.roughness = clamp(lerp(mortarRoughness, stoneRough, coverage), 0, ONE - 1);

    const dirt = band(fbm(x, y, 4, 4, dirtSeed, 3), 27000, 45000);
    shade(
      out,
      ONE
        - floorDiv(dirt * dirtPercent, 100)
        - floorDiv(floorDiv(low * coverage, ONE) * lowDirtPercent, 100),
    );

    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const ashlarMaker: Maker = {
  manifest: ashlarManifest,
  stated(recipe) {
    const bondSpec = spec(recipe);
    return {
      bond: BONDS[read.choice(recipe, 'bond')]!,
      module_length_mm: bondSpec.moduleU,
      course_height_mm: bondSpec.moduleV,
      head_joint_mm: bondSpec.jointU,
      bed_joint_mm: bondSpec.jointV,
      block_face_length_mm: bondSpec.moduleU - bondSpec.jointU,
      block_face_height_mm: bondSpec.moduleV - bondSpec.jointV,
      units_per_course: bondSpec.unitsPerCourse,
      courses: bondSpec.courses,
      course_offset_mm_1024ths: bondSpec.oddCourseShift,
      phase_u_mm_1024ths: bondSpec.phaseU,
      phase_v_mm_1024ths: bondSpec.phaseV,
      face_height_mm: read.integer(recipe, 'face_height_mm'),
      joint_recess_mm: read.integer(recipe, 'joint_recess_mm'),
      arris_mm: read.integer(recipe, 'arris_mm'),
      chip_depth_max_mm: read.integer(recipe, 'chip_depth_max_mm'),
    };
  },
  pattern,
};
