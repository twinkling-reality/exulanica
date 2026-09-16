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
import { type Linear, type Srgb, decode } from '../srgb.js';
import { MM, tileToLength } from '../tile.js';

/**
 * Kerb stone: flame-textured grey granite in 900 mm units with 6 mm joints.
 *
 * A kerb is one run of units, so the tile has head joints across it and no bed joint along it:
 * u runs along the kerb, and the 450 mm v extent is enough for a top and a face at the stated
 * scale. The tile is 1024 x 256 texels over 1800 x 450 mm, which keeps texels square at 1.76 mm,
 * and every cellular field uses periods in the same 4:1 ratio so its cells are round on the stone.
 */
const UNIT_MM = 900;
const JOINT_MM = 6;
const UNITS = 2;
const EXTENT_U = UNITS * UNIT_MM;
const EXTENT_V = 450;
const RANGE_MM = 6;
const FACE_MM_1024THS = 4608;
const JOINT_MM_1024THS = 1024;
const ARRIS_MM = 4;

const SPEC: BondSpec = {
  moduleU: UNIT_MM,
  moduleV: EXTENT_V,
  jointU: JOINT_MM,
  jointV: 0,
  unitsPerCourse: UNITS,
  courses: 1,
  oddCourseShift: 0,
  phaseU: (UNIT_MM * MM) / 2,
  phaseV: 0,
};

/** Minerals, by share of the crystals: feldspar, quartz, biotite, plagioclase. sRGB. */
const FELDSPAR: Srgb = [194, 188, 182];
const QUARTZ: Srgb = [166, 168, 172];
const BIOTITE: Srgb = [48, 48, 52];
const PLAGIOCLASE: Srgb = [214, 210, 204];
const JOINT: Srgb = [78, 76, 72];
const GRIME: Srgb = [96, 92, 86];

function recipe(seed: number): Recipe {
  checkBond(SPEC, EXTENT_U, EXTENT_V);
  const feldspar = decode(FELDSPAR);
  const quartz = decode(QUARTZ);
  const biotite = decode(BIOTITE);
  const plagioclase = decode(PLAGIOCLASE);
  const joint = decode(JOINT);
  const grime = decode(GRIME);
  const units = stream(seed, 1);
  const crystalSeed = stream(seed, 2);
  const fineSeed = stream(seed, 3);
  const dirtSeed = stream(seed, 4);
  const jointSeed = stream(seed, 5);
  const at = newBondSample();
  const crystal: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    bond(tileToLength(x, EXTENT_U), tileToLength(y, EXTENT_V), SPEC, at);
    const arris = at.edge <= 0 ? 0 : smoothstep(0, ARRIS_MM * MM, at.edge);
    const coverage = smoothstep(-MM, MM, at.edge);

    // Crystals about 3 mm across. Flaming pops them proud of the surface by differing amounts.
    cells(x, y, 600, 150, crystalSeed, ONE, crystal);
    const share = pick(crystal.id, 0, 99);
    let mineral: Linear;
    let mineralRough: number;
    if (share < 50) {
      mineral = feldspar;
      mineralRough = permille(740);
    } else if (share < 72) {
      mineral = quartz;
      mineralRough = permille(620);
    } else if (share < 86) {
      mineral = biotite;
      mineralRough = permille(460);
    } else {
      mineral = plagioclase;
      mineralRough = permille(760);
    }
    const boundary = band(ONE - (crystal.second - crystal.nearest), 56000, 65536);
    const fine = fbm(x, y, 1200, 300, fineSeed, 1);
    const lift = pick(hash3(crystal.id, 1, 0, crystalSeed), -500, 500);
    const tiltU = pick(hash3(at.unit, 0, 1, units), -500, 500);
    const face = FACE_MM_1024THS
      + lift
      - floorDiv(boundary * 350, ONE)
      + floorDiv((fine - 32768) * 200, 32768)
      + floorDiv(tiltU * (2 * at.faceU - (UNIT_MM - JOINT_MM) * MM), 2 * (UNIT_MM - JOINT_MM) * MM);
    const gritNoise = valueNoise(x, y, 800, 200, jointSeed);
    const jointLength = JOINT_MM_1024THS + floorDiv((gritNoise - 32768) * 250, 32768);
    out.height = heightOfLength(lerp(jointLength, face, arris), RANGE_MM);

    setColour(out, mineral);
    shade(out, jitter(bits16(hash3(crystal.id, 2, 0, crystalSeed)), 3000));
    shade(out, jitter(bits16(hash3(at.unit, 0, 3, units)), 2000));
    shade(out, ONE - floorDiv(boundary * 12, 100));
    const stoneRed = out.red;
    const stoneGreen = out.green;
    const stoneBlue = out.blue;
    const stoneRough = mineralRough + floorDiv((fine - 32768) * 2600, 32768);

    setColour(out, joint);
    shade(out, jitter(gritNoise, 5000));
    out.red = lerp(out.red, stoneRed, coverage);
    out.green = lerp(out.green, stoneGreen, coverage);
    out.blue = lerp(out.blue, stoneBlue, coverage);
    out.roughness = clamp(lerp(permille(950), stoneRough, coverage), 0, FULL);

    const dirt = band(fbm(x, y, 8, 2, dirtSeed, 3), 28000, 46000);
    mixColour(out, grime, floorDiv(dirt * 22, 100));

    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const kerb = (seed: number, version: number): TextureSetDefinition => ({
  setId: 'cc0.kerb-stone',
  version,
  seed,
  family: 'kerb',
  title: 'Kerb stone',
  summary: 'Flame-textured grey granite kerb units, 900 mm long with 6 mm joints.',
  width: 1024,
  height: 256,
  extentU: EXTENT_U,
  extentV: EXTENT_V,
  surface: 'horizontal',
  heightRangeMm: RANGE_MM,
  cavity: { radiusMm: 4, depthMm: 2, strengthPermille: 450 },
  parameters: {
    stone: 'granite, flame textured',
    unit_length_mm: UNIT_MM,
    head_joint_mm: JOINT_MM,
    units_per_tile: UNITS,
    bed_joint_mm: 0,
    phase_u_mm_1024ths: SPEC.phaseU,
    face_height_mm_1024ths: FACE_MM_1024THS,
    joint_height_mm_1024ths: JOINT_MM_1024THS,
    arris_mm: ARRIS_MM,
    crystal_cell_mm_1024ths: floorDiv(EXTENT_U * MM, 600),
  },
  recipe: () => recipe(seed),
});
