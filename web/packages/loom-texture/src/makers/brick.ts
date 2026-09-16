import { type BondSpec, bond, checkBond, newBondSample } from '../bond.js';
import {
  choice,
  colour,
  commonControls,
  equal,
  even,
  extent,
  integer,
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
 * Brick in a bond: running (stretcher) bond, alternate courses offset by half a module, or stack
 * bond. The module is stated, not implied: a unit face plus one head joint along a course, a unit
 * height plus one bed joint up the wall, and the tile must hold a whole number of both.
 *
 * Mortar sits behind the face by the stated recess, arrises are rounded and chipped, and units vary
 * in tone, tilt, firing flash and pitting. What stays fixed in this version is the texture of those
 * variations (their noise scales and thresholds); what they are and how strong they are is the
 * recipe's to set.
 */
const BONDS: Readonly<Record<string, string>> = {
  running: 'running: alternate courses offset by half a module',
  stack: 'stack: no offset between courses',
};

const RUNNING = { param: 'bond', equals: 'running' };

export const brickManifest: MakerManifest = {
  profile: MAKER_PROFILE,
  maker_id: 'loom.brick',
  version: 1,
  kind: 'procedural',
  family: 'brick',
  surface: 'vertical',
  truth: 'invented',
  controls: [
    choice('bond', 'module', ['running', 'stack'], 'running', 'Bond',
      'Running offsets alternate courses by half a unit; stack lines every joint up.'),
    integer('unit_length_mm', 'module', 'mm', [50, 600], 215, 'Brick length',
      'The visible length of one brick face.'),
    integer('unit_height_mm', 'module', 'mm', [20, 300], 65, 'Brick height',
      'The visible height of one brick face.'),
    integer('head_joint_mm', 'module', 'mm', [1, 30], 10, 'Head joint',
      'The vertical mortar joint between bricks in a course.'),
    integer('bed_joint_mm', 'module', 'mm', [1, 30], 10, 'Bed joint',
      'The horizontal mortar joint between courses.'),
    integer('units_per_course', 'module', 'count', [1, 64], 8, 'Bricks per course',
      'Whole bricks along one tile.'),
    integer('courses', 'module', 'count', [1, 256], 24, 'Courses',
      'Whole courses down one tile.'),
    palette('palette', [
      [146, 66, 48],
      [132, 60, 46],
      [158, 76, 56],
      [120, 56, 44],
      [170, 92, 68],
      [104, 50, 42],
      [150, 82, 64],
    ], [1, 16], 'Brick colours', 'Each brick takes one of these tones.'),
    colour('mortar_colour', [184, 176, 162], 'Mortar colour', 'The mortar in the joints.'),
    colour('burnt_colour', [72, 42, 36], 'Burnt inclusions',
      'The colour of the dark pits fired into a brick face.'),
    colour('fresh_clay_colour', [188, 112, 86], 'Fresh clay',
      'The colour exposed where an edge has chipped.'),
    integer('face_height_mm', 'relief', 'mm', [1, 60], 10, 'Face height',
      'How far the brick face stands above the bottom of the height range.'),
    integer('joint_recess_mm', 'relief', 'mm', [0, 30], 5, 'Joint recess',
      'How far the mortar sits behind the brick face.'),
    integer('arris_mm', 'relief', 'mm', [0, 20], 3, 'Edge rounding',
      'The width over which a brick edge rounds off.'),
    integer('chip_depth_max_mm', 'wear', 'mm', [0, 20], 4, 'Chipping',
      'The deepest a chipped edge eats into a brick face.'),
    integer('mortar_grain_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 180,
      'Mortar grain', 'The height of sand grains in the mortar surface.'),
    integer('unit_tilt_u_mm_1024ths', 'relief', 'mm_1024ths', [0, 4096], 600, 'Brick tilt across',
      'How far a brick face may lean from one end to the other.'),
    integer('unit_tilt_v_mm_1024ths', 'relief', 'mm_1024ths', [0, 4096], 300, 'Brick tilt up',
      'How far a brick face may lean from bottom to top.'),
    integer('face_grain_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 350, 'Face grain',
      'The height of the clay texture on a brick face.'),
    integer('pit_percent', 'detail', 'percent', [0, 100], 22, 'Pitting',
      'How often a small cell of a brick face holds a burnt pit.'),
    integer('pit_depth_mm_1024ths', 'detail', 'mm_1024ths', [0, 900], 600, 'Pit depth',
      'How deep a pit goes.'),
    integer('unit_brightness_spread_q16', 'colour', 'q16', [0, 32768], 7200,
      'Brick-to-brick variation', 'How much one brick may be lighter or darker than the next.'),
    integer('flash_percent', 'colour', 'percent', [0, 100], 30, 'Firing flash',
      'How many bricks are darker toward one end.'),
    integer('flash_darkening_percent', 'colour', 'percent', [0, 100], 18, 'Flash strength',
      'How much darker the flashed end gets.'),
    integer('clay_grain_spread_q16', 'colour', 'q16', [0, 32768], 4600, 'Clay mottling',
      'Fine colour variation across a brick face.'),
    integer('mortar_grain_spread_q16', 'colour', 'q16', [0, 32768], 4000, 'Mortar mottling',
      'Fine colour variation across the mortar.'),
    integer('brick_roughness_permille', 'finish', 'permille', [0, 1000], 840, 'Brick roughness',
      'How matte a brick face is, in thousandths.'),
    integer('mortar_roughness_permille', 'finish', 'permille', [0, 1000], 930,
      'Mortar roughness', 'How matte the mortar is, in thousandths.'),
    integer('soot_percent', 'wear', 'percent', [0, 50], 9, 'Soot',
      'The darkest broad soot staining gets, in percent.'),
    integer('streak_percent', 'wear', 'percent', [0, 50], 7, 'Run-off streaks',
      'The darkest vertical rain streaks get, in percent.'),
    ...commonControls({
      heightRangeMm: 12,
      occlusionRadiusMm: 8,
      occlusionDepthMm: 4,
      occlusionStrengthPermille: 550,
    }),
  ],
  constraints: [
    equal(
      product(param('units_per_course'), sum(param('unit_length_mm'), param('head_joint_mm'))),
      extent('u'),
      'bricks per course times the brick-and-joint module must equal the tile width',
    ),
    equal(
      product(param('courses'), sum(param('unit_height_mm'), param('bed_joint_mm'))),
      extent('v'),
      'courses times the course-and-joint module must equal the tile height',
    ),
    even(param('courses'), 'running bond repeats every two courses, so the tile holds an even number',
      RUNNING),
    lessOrEqual(param('joint_recess_mm'), param('face_height_mm'),
      'the mortar cannot sit below the bottom of the height range'),
    lessOrEqual(param('face_height_mm'), param('height_range_mm'),
      'the brick face must lie inside the height range'),
  ],
};

function spec(recipe: Recipe): BondSpec {
  const jointU = read.integer(recipe, 'head_joint_mm');
  const jointV = read.integer(recipe, 'bed_joint_mm');
  const moduleU = read.integer(recipe, 'unit_length_mm') + jointU;
  const moduleV = read.integer(recipe, 'unit_height_mm') + jointV;
  return {
    moduleU,
    moduleV,
    jointU,
    jointV,
    unitsPerCourse: read.integer(recipe, 'units_per_course'),
    courses: read.integer(recipe, 'courses'),
    oddCourseShift: read.choice(recipe, 'bond') === 'running' ? (moduleU * MM) / 2 : 0,
    // A quarter module and half a course, so the tile edge crosses units rather than joints.
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
  const clay = read.palette(recipe, 'palette').map(decode);
  const mortar = decode(read.colour(recipe, 'mortar_colour'));
  const burnt = decode(read.colour(recipe, 'burnt_colour'));
  const fresh = decode(read.colour(recipe, 'fresh_clay_colour'));
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const faceMm = read.integer(recipe, 'face_height_mm');
  const recessMm = read.integer(recipe, 'joint_recess_mm');
  const arrisMm = read.integer(recipe, 'arris_mm');
  const chipMm = read.integer(recipe, 'chip_depth_max_mm');
  const mortarGrain = read.integer(recipe, 'mortar_grain_mm_1024ths');
  const tiltUMax = read.integer(recipe, 'unit_tilt_u_mm_1024ths');
  const tiltVMax = read.integer(recipe, 'unit_tilt_v_mm_1024ths');
  const faceGrain = read.integer(recipe, 'face_grain_mm_1024ths');
  const pitPercent = read.integer(recipe, 'pit_percent');
  const pitDepthMax = read.integer(recipe, 'pit_depth_mm_1024ths');
  const unitSpread = read.integer(recipe, 'unit_brightness_spread_q16');
  const flashPercent = read.integer(recipe, 'flash_percent');
  const flashDarkening = read.integer(recipe, 'flash_darkening_percent');
  const claySpread = read.integer(recipe, 'clay_grain_spread_q16');
  const mortarSpread = read.integer(recipe, 'mortar_grain_spread_q16');
  const brickRoughness = permille(read.integer(recipe, 'brick_roughness_permille'));
  const mortarRoughness = permille(read.integer(recipe, 'mortar_roughness_permille'));
  const sootPercent = read.integer(recipe, 'soot_percent');
  const streakPercent = read.integer(recipe, 'streak_percent');
  const units = stream(seed, 1);
  const grainSeed = stream(seed, 2);
  const chipSeed = stream(seed, 3);
  const sandSeed = stream(seed, 4);
  const sootSeed = stream(seed, 5);
  const streakSeed = stream(seed, 6);
  const pitSeed = stream(seed, 7);
  const claySeed = stream(seed, 8);
  const faceWidth = read.integer(recipe, 'unit_length_mm') * MM;
  const faceHeight = read.integer(recipe, 'unit_height_mm') * MM;
  const at = newBondSample();
  const pit: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    bond(tileToLength(x, extentU), tileToLength(y, extentV), bondSpec, at);

    // Chipped arrises: a coarse field eats up to the chip depth into the face where it runs high.
    const chipField = band(fbm(x, y, 72, 72, chipSeed, 3), 34000, 50000);
    const edge = at.edge - floorDiv(chipField * chipMm * MM, ONE);
    const arris = edge <= 0 ? 0 : smoothstep(0, arrisMm * MM, edge);
    // Coverage of brick over mortar, about one texel wide, so the joint line is not aliased.
    const coverage = smoothstep(-MM, MM, at.edge);

    // Heights, in 1/1024 mm.
    const sand = valueNoise(x, y, 720, 720, sandSeed);
    const mortarLength = (faceMm - recessMm) * MM + floorDiv((sand - 32768) * mortarGrain, 32768);
    const tiltU = pick(hash3(at.unit, at.course, 1, units), -tiltUMax, tiltUMax);
    const tiltV = pick(hash3(at.unit, at.course, 2, units), -tiltVMax, tiltVMax);
    const grain = fbm(x, y, 240, 240, grainSeed, 3);
    cells(x, y, 560, 560, pitSeed, ONE, pit);
    const pitDepth = pick(pit.id, 0, 99) < pitPercent && pit.nearest < 16384
      ? floorDiv((16384 - pit.nearest) * pitDepthMax, 16384)
      : 0;
    const face = faceMm * MM
      + floorDiv(tiltU * (2 * at.faceU - faceWidth), 2 * faceWidth)
      + floorDiv(tiltV * (2 * at.faceV - faceHeight), 2 * faceHeight)
      + floorDiv((grain - 32768) * faceGrain, 32768)
      - pitDepth;
    out.height = heightOfLength(lerp(mortarLength, face, arris), rangeMm);

    // The unit's colour: a palette tone, a per-unit brightness, and on some units a darker end.
    const key = hash3(at.unit, at.course, 0, units);
    setColour(out, clay[pick(key, 0, clay.length - 1)]!);
    shade(out, jitter(bits16(hash3(at.unit, at.course, 3, units)), unitSpread));
    const flashKey = hash3(at.unit, at.course, 4, units);
    if (pick(flashKey, 0, 99) < flashPercent) {
      const along = (flashKey & 1) === 0 ? at.faceU : faceWidth - at.faceU;
      shade(out, ONE - floorDiv(smoothstep(0, faceWidth, faceWidth - along) * flashDarkening, 100));
    }
    shade(out, jitter(fbm(x, y, 360, 360, claySeed, 2), claySpread));
    if (pitDepth > 0) mixColour(out, burnt, floorDiv(pitDepth * ONE, 900));
    // Fresh clay shows where an arris has chipped away.
    const chipped = at.edge >= 0 ? floorDiv((ONE - arris) * chipField, ONE) : 0;
    mixColour(out, fresh, chipped >> 1);
    const brickRed = out.red;
    const brickGreen = out.green;
    const brickBlue = out.blue;
    const brickRough = brickRoughness + floorDiv((grain - 32768) * 3300, 32768)
      + floorDiv(chipped * 6, 100);

    setColour(out, mortar);
    shade(out, jitter(sand, mortarSpread));

    out.red = lerp(out.red, brickRed, coverage);
    out.green = lerp(out.green, brickGreen, coverage);
    out.blue = lerp(out.blue, brickBlue, coverage);
    out.roughness = clamp(lerp(mortarRoughness, brickRough, coverage), 0, ONE - 1);

    // Weathering over both materials: broad soot and narrow vertical run-off streaks.
    const soot = band(fbm(x, y, 3, 3, sootSeed, 3), 26000, 44000);
    const streak = band(valueNoise(x, y, 48, 3, streakSeed), 36000, 56000);
    shade(out, ONE - floorDiv(soot * sootPercent, 100) - floorDiv(streak * streakPercent, 100));

    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const brickMaker: Maker = {
  manifest: brickManifest,
  stated(recipe) {
    const bondSpec = spec(recipe);
    return {
      bond: BONDS[read.choice(recipe, 'bond')]!,
      unit_length_mm: read.integer(recipe, 'unit_length_mm'),
      unit_height_mm: read.integer(recipe, 'unit_height_mm'),
      head_joint_mm: bondSpec.jointU,
      bed_joint_mm: bondSpec.jointV,
      module_length_mm: bondSpec.moduleU,
      course_height_mm: bondSpec.moduleV,
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
