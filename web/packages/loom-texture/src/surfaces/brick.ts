import { type BondSpec, bond, checkBond, newBondSample } from '../bond.js';
import type { TextureSetDefinition } from '../definition.js';
import { bits16, hash3, pick, stream } from '../hash.js';
import { ONE, clamp, floorDiv, lerp, smoothstep } from '../integer.js';
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
 * Brick in running (stretcher) bond.
 *
 * The module is stated, not implied: a 215 x 65 mm face with 10 mm head and bed joints makes a
 * 225 x 75 mm module, alternate courses are offset by half a module, and the 1800 mm tile holds
 * exactly 8 units per course and 24 courses. The joints are recessed 5 mm behind the face.
 */
const UNIT_LENGTH_MM = 215;
const UNIT_HEIGHT_MM = 65;
const JOINT_MM = 10;
const UNITS_PER_COURSE = 8;
const COURSES = 24;
const MODULE_U = UNIT_LENGTH_MM + JOINT_MM;
const MODULE_V = UNIT_HEIGHT_MM + JOINT_MM;
const EXTENT_U = UNITS_PER_COURSE * MODULE_U;
const EXTENT_V = COURSES * MODULE_V;
const RANGE_MM = 12;
const FACE_MM = 10;
const RECESS_MM = 5;
const ARRIS_MM = 3;
const CHIP_MM = 4;

const SPEC: BondSpec = {
  moduleU: MODULE_U,
  moduleV: MODULE_V,
  jointU: JOINT_MM,
  jointV: JOINT_MM,
  unitsPerCourse: UNITS_PER_COURSE,
  courses: COURSES,
  oddCourseShift: (MODULE_U * MM) / 2,
  // A quarter module and half a course, so the tile edge crosses units rather than joints.
  phaseU: (MODULE_U * MM) / 4,
  phaseV: (MODULE_V * MM) / 2,
};

/** Fired clay, red to brown, with one pale and one dark unit in the mix. sRGB. */
const CLAY: readonly Srgb[] = [
  [146, 66, 48],
  [132, 60, 46],
  [158, 76, 56],
  [120, 56, 44],
  [170, 92, 68],
  [104, 50, 42],
  [150, 82, 64],
];
const MORTAR: Srgb = [184, 176, 162];
const BURNT: Srgb = [72, 42, 36];
const FRESH_CLAY: Srgb = [188, 112, 86];

function recipe(seed: number): Recipe {
  checkBond(SPEC, EXTENT_U, EXTENT_V);
  const clay = CLAY.map(decode);
  const mortar = decode(MORTAR);
  const burnt = decode(BURNT);
  const fresh = decode(FRESH_CLAY);
  const units = stream(seed, 1);
  const grainSeed = stream(seed, 2);
  const chipSeed = stream(seed, 3);
  const sandSeed = stream(seed, 4);
  const sootSeed = stream(seed, 5);
  const streakSeed = stream(seed, 6);
  const pitSeed = stream(seed, 7);
  const claySeed = stream(seed, 8);
  const faceWidth = UNIT_LENGTH_MM * MM;
  const faceHeight = UNIT_HEIGHT_MM * MM;
  const at = newBondSample();
  const pit: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    bond(tileToLength(x, EXTENT_U), tileToLength(y, EXTENT_V), SPEC, at);

    // Chipped arrises: a coarse field eats up to CHIP_MM into the face where it runs high.
    const chipField = band(fbm(x, y, 72, 72, chipSeed, 3), 34000, 50000);
    const edge = at.edge - floorDiv(chipField * CHIP_MM * MM, ONE);
    const arris = edge <= 0 ? 0 : smoothstep(0, ARRIS_MM * MM, edge);
    // Coverage of brick over mortar, about one texel wide, so the joint line is not aliased.
    const coverage = smoothstep(-MM, MM, at.edge);

    // Heights, in 1/1024 mm.
    const sand = valueNoise(x, y, 720, 720, sandSeed);
    const mortarLength = (FACE_MM - RECESS_MM) * MM + floorDiv((sand - 32768) * 180, 32768);
    const tiltU = pick(hash3(at.unit, at.course, 1, units), -600, 600);
    const tiltV = pick(hash3(at.unit, at.course, 2, units), -300, 300);
    const grain = fbm(x, y, 240, 240, grainSeed, 3);
    cells(x, y, 560, 560, pitSeed, ONE, pit);
    const pitDepth = pick(pit.id, 0, 99) < 22 && pit.nearest < 16384
      ? floorDiv((16384 - pit.nearest) * 600, 16384)
      : 0;
    const face = FACE_MM * MM
      + floorDiv(tiltU * (2 * at.faceU - faceWidth), 2 * faceWidth)
      + floorDiv(tiltV * (2 * at.faceV - faceHeight), 2 * faceHeight)
      + floorDiv((grain - 32768) * 350, 32768)
      - pitDepth;
    out.height = heightOfLength(lerp(mortarLength, face, arris), RANGE_MM);

    // The unit's colour: a palette tone, a per-unit brightness, and on some units a darker end.
    const key = hash3(at.unit, at.course, 0, units);
    setColour(out, clay[pick(key, 0, clay.length - 1)]!);
    shade(out, jitter(bits16(hash3(at.unit, at.course, 3, units)), 7200));
    const flashKey = hash3(at.unit, at.course, 4, units);
    if (pick(flashKey, 0, 99) < 30) {
      const along = (flashKey & 1) === 0 ? at.faceU : faceWidth - at.faceU;
      shade(out, ONE - floorDiv(smoothstep(0, faceWidth, faceWidth - along) * 18, 100));
    }
    shade(out, jitter(fbm(x, y, 360, 360, claySeed, 2), 4600));
    if (pitDepth > 0) mixColour(out, burnt, floorDiv(pitDepth * ONE, 900));
    // Fresh clay shows where an arris has chipped away.
    const chipped = at.edge >= 0 ? floorDiv((ONE - arris) * chipField, ONE) : 0;
    mixColour(out, fresh, chipped >> 1);
    const brickRed = out.red;
    const brickGreen = out.green;
    const brickBlue = out.blue;
    const brickRough = permille(840) + floorDiv((grain - 32768) * 3300, 32768)
      + floorDiv(chipped * 6, 100);

    setColour(out, mortar);
    shade(out, jitter(sand, 4000));
    const mortarRough = permille(930);

    out.red = lerp(out.red, brickRed, coverage);
    out.green = lerp(out.green, brickGreen, coverage);
    out.blue = lerp(out.blue, brickBlue, coverage);
    out.roughness = clamp(lerp(mortarRough, brickRough, coverage), 0, ONE - 1);

    // Weathering over both materials: broad soot and narrow vertical run-off streaks.
    const soot = band(fbm(x, y, 3, 3, sootSeed, 3), 26000, 44000);
    const streak = band(valueNoise(x, y, 48, 3, streakSeed), 36000, 56000);
    shade(out, ONE - floorDiv(soot * 9, 100) - floorDiv(streak * 7, 100));

    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const brick = (seed: number, version: number): TextureSetDefinition => ({
  setId: 'cc0.brick-running-bond',
  version,
  seed,
  family: 'brick',
  title: 'Brick, running bond',
  summary:
    'Red to brown fired clay brick in running bond, 215 x 65 mm faces with 10 mm recessed joints.',
  width: 1024,
  height: 1024,
  extentU: EXTENT_U,
  extentV: EXTENT_V,
  surface: 'vertical',
  heightRangeMm: RANGE_MM,
  cavity: { radiusMm: 8, depthMm: 4, strengthPermille: 550 },
  parameters: {
    bond: 'running: alternate courses offset by half a module',
    unit_length_mm: UNIT_LENGTH_MM,
    unit_height_mm: UNIT_HEIGHT_MM,
    head_joint_mm: JOINT_MM,
    bed_joint_mm: JOINT_MM,
    module_length_mm: MODULE_U,
    course_height_mm: MODULE_V,
    units_per_course: UNITS_PER_COURSE,
    courses: COURSES,
    course_offset_mm_1024ths: SPEC.oddCourseShift,
    phase_u_mm_1024ths: SPEC.phaseU,
    phase_v_mm_1024ths: SPEC.phaseV,
    face_height_mm: FACE_MM,
    joint_recess_mm: RECESS_MM,
    arris_mm: ARRIS_MM,
    chip_depth_max_mm: CHIP_MM,
  },
  recipe: () => recipe(seed),
});
