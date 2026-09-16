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
 * Coursed limestone ashlar.
 *
 * Blocks on a 600 x 300 mm module with 5 mm joints, laid half bond, four blocks and eight courses
 * to a 2400 mm tile. The face carries fine horizontal tooling and the stone's own bedding, which
 * runs along the course as it does in a block cut from a quarry bed and laid the right way up.
 */
const MODULE_U = 600;
const MODULE_V = 300;
const JOINT_MM = 5;
const UNITS_PER_COURSE = 4;
const COURSES = 8;
const EXTENT_U = UNITS_PER_COURSE * MODULE_U;
const EXTENT_V = COURSES * MODULE_V;
const RANGE_MM = 8;
const FACE_MM = 6;
const RECESS_MM = 3;
const ARRIS_MM = 2;
const CHIP_MM = 3;

const SPEC: BondSpec = {
  moduleU: MODULE_U,
  moduleV: MODULE_V,
  jointU: JOINT_MM,
  jointV: JOINT_MM,
  unitsPerCourse: UNITS_PER_COURSE,
  courses: COURSES,
  oddCourseShift: (MODULE_U * MM) / 2,
  phaseU: (MODULE_U * MM) / 4,
  phaseV: (MODULE_V * MM) / 2,
};

/** Buff to grey limestone. sRGB. */
const STONE: readonly Srgb[] = [
  [198, 188, 166],
  [192, 183, 163],
  [203, 194, 172],
  [189, 182, 165],
  [196, 185, 161],
];
const LIME_MORTAR: Srgb = [204, 198, 184];
const SHELL_LIGHT: Srgb = [224, 216, 198];
const SHELL_DARK: Srgb = [150, 142, 128];
const SPECK_LIGHT: Srgb = [214, 206, 188];
const SPECK_DARK: Srgb = [168, 160, 144];

function recipe(seed: number): Recipe {
  checkBond(SPEC, EXTENT_U, EXTENT_V);
  const stone = STONE.map(decode);
  const mortar = decode(LIME_MORTAR);
  const shellLight = decode(SHELL_LIGHT);
  const shellDark = decode(SHELL_DARK);
  const speckLight = decode(SPECK_LIGHT);
  const speckDark = decode(SPECK_DARK);
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
  const faceHeight = (MODULE_V - JOINT_MM) * MM;
  const at = newBondSample();
  const shell: CellSample = { nearest: 0, second: 0, id: 0 };
  const speck: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    bond(tileToLength(x, EXTENT_U), tileToLength(y, EXTENT_V), SPEC, at);

    const chipField = band(fbm(x, y, 96, 96, chipSeed, 3), 38000, 52000);
    const edge = at.edge - floorDiv(chipField * CHIP_MM * MM, ONE);
    const arris = edge <= 0 ? 0 : smoothstep(0, ARRIS_MM * MM, edge);
    const coverage = smoothstep(-MM, MM, at.edge);

    // Tooling: long horizontal drag marks, 40 mm along and 5 mm across, about two texels.
    const tool = valueNoise(x, y, 60, 480, toolSeed);
    const grain = fbm(x, y, 800, 800, grainSeed, 2);
    const wave = fbm(x, y, 8, 8, waveSeed, 2);
    const sand = valueNoise(x, y, 960, 960, sandSeed);
    const face = FACE_MM * MM
      + floorDiv((tool - 32768) * 150, 32768)
      + floorDiv((grain - 32768) * 100, 32768)
      + floorDiv((wave - 32768) * 300, 32768);
    const joint = (FACE_MM - RECESS_MM) * MM + floorDiv((sand - 32768) * 120, 32768);
    out.height = heightOfLength(lerp(joint, face, arris), RANGE_MM);

    const key = hash3(at.unit, at.course, 0, blocks);
    setColour(out, stone[pick(key, 0, stone.length - 1)]!);
    shade(out, jitter(bits16(hash3(at.unit, at.course, 1, blocks)), 1900));
    // Bedding: thin layers along the course, 13 mm thick, and a soft cloudiness within a block.
    shade(out, jitter(valueNoise(x, y, 6, 180, bedSeed), 1700));
    shade(out, jitter(fbm(x, y, 24, 24, cloudSeed, 3), 3000));
    shade(out, jitter(grain, 1600));
    // The limestone's own grain: light and dark specks one to two millimetres across.
    cells(x, y, 900, 900, speckSeed, ONE, speck);
    const speckPick = pick(speck.id, 0, 99);
    if (speckPick < 34 && speck.nearest < 20000) {
      const t = smoothstep(0, 9000, 20000 - speck.nearest);
      mixColour(out, speckPick < 17 ? speckLight : speckDark, floorDiv(t * 55, 100));
    }
    cells(x, y, 500, 500, shellSeed, ONE, shell);
    const shellPick = pick(shell.id, 0, 99);
    if (shellPick < 16 && shell.nearest < 13000) {
      const t = floorDiv((13000 - shell.nearest) * ONE, 13000);
      mixColour(out, shellPick < 9 ? shellLight : shellDark, t >> 1);
    }
    // Dirt settles toward the bottom of each block, where the joint below holds water.
    const low = smoothstep(faceHeight >> 1, faceHeight, at.faceV);
    const chipped = at.edge >= 0 ? floorDiv((ONE - arris) * chipField, ONE) : 0;
    const stoneRed = out.red;
    const stoneGreen = out.green;
    const stoneBlue = out.blue;
    const stoneRough = permille(800) + floorDiv((tool - 32768) * 2600, 32768)
      + floorDiv(chipped * 5, 100);

    setColour(out, mortar);
    shade(out, jitter(sand, 3000));
    out.red = lerp(out.red, stoneRed, coverage);
    out.green = lerp(out.green, stoneGreen, coverage);
    out.blue = lerp(out.blue, stoneBlue, coverage);
    out.roughness = clamp(lerp(permille(920), stoneRough, coverage), 0, ONE - 1);

    const dirt = band(fbm(x, y, 4, 4, dirtSeed, 3), 27000, 45000);
    shade(
      out,
      ONE - floorDiv(dirt * 8, 100) - floorDiv(floorDiv(low * coverage, ONE) * 5, 100),
    );

    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const ashlar = (seed: number, version: number): TextureSetDefinition => ({
  setId: 'cc0.limestone-ashlar',
  version,
  seed,
  family: 'stone',
  title: 'Limestone ashlar',
  summary: 'Buff limestone blocks on a 600 x 300 mm module, half bond, with 5 mm lime joints.',
  width: 1024,
  height: 1024,
  extentU: EXTENT_U,
  extentV: EXTENT_V,
  surface: 'vertical',
  heightRangeMm: RANGE_MM,
  cavity: { radiusMm: 10, depthMm: 3, strengthPermille: 450 },
  parameters: {
    bond: 'half: alternate courses offset by half a module',
    module_length_mm: MODULE_U,
    course_height_mm: MODULE_V,
    head_joint_mm: JOINT_MM,
    bed_joint_mm: JOINT_MM,
    block_face_length_mm: MODULE_U - JOINT_MM,
    block_face_height_mm: MODULE_V - JOINT_MM,
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
