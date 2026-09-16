import { type BondSpec, bond, checkBond, newBondSample } from '../bond.js';
import type { TextureSetDefinition } from '../definition.js';
import { bits16, hash3, pick, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, isqrt, lerp, smoothstep } from '../integer.js';
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
 * Cast-in-place concrete, off plywood formwork.
 *
 * Form panels on a 1200 x 600 mm module, stacked, two panels and four courses to a 2400 mm tile.
 * Each panel joint leaves a 2 mm fin, and each panel carries four form-tie holes 28 mm across on a
 * 600 x 300 mm grid, 8 mm deep, with a faint run-off stain below. Bug holes, the small voids air
 * leaves against the form, are scattered across the face.
 */
const PANEL_U = 1200;
const PANEL_V = 600;
const SEAM_MM = 2;
const PANELS_PER_ROW = 2;
const ROWS = 4;
const EXTENT_U = PANELS_PER_ROW * PANEL_U;
const EXTENT_V = ROWS * PANEL_V;
const RANGE_MM = 12;
const SURFACE_MM = 10;
const FIN_MM_1024THS = 600;
const TIE_RADIUS_MM = 14;
const TIE_DEPTH_MM = 8;
/** Tie centres, measured from a panel face's top-left corner. */
const TIE_U_MM = [299, 899] as const;
const TIE_V_MM = [149, 449] as const;
const STAIN_LENGTH_MM = 260;

const SPEC: BondSpec = {
  moduleU: PANEL_U,
  moduleV: PANEL_V,
  jointU: SEAM_MM,
  jointV: SEAM_MM,
  unitsPerCourse: PANELS_PER_ROW,
  courses: ROWS,
  oddCourseShift: 0,
  phaseU: (PANEL_U * MM) / 2,
  phaseV: (PANEL_V * MM) / 2,
};

const CONCRETE: Srgb = [160, 158, 152];
const HOLE: Srgb = [96, 94, 90];
const STAIN: Srgb = [122, 120, 116];
const SEAM: Srgb = [124, 122, 118];
const LAITANCE: Srgb = [182, 180, 174];

function nearestOf(value: number, centres: readonly number[]): number {
  let best = Number.POSITIVE_INFINITY;
  for (const centre of centres) {
    const d = value - centre * MM;
    if (Math.abs(d) < Math.abs(best)) best = d;
  }
  return best;
}

function recipe(seed: number): Recipe {
  checkBond(SPEC, EXTENT_U, EXTENT_V);
  const concrete = decode(CONCRETE);
  const hole = decode(HOLE);
  const stain = decode(STAIN);
  const seam = decode(SEAM);
  const laitance = decode(LAITANCE);
  const panels = stream(seed, 1);
  const waveSeed = stream(seed, 2);
  const plySeed = stream(seed, 3);
  const bugSeed = stream(seed, 4);
  const mottleSeed = stream(seed, 5);
  const fineSeed = stream(seed, 6);
  const voidSeed = stream(seed, 7);
  const blotchSeed = stream(seed, 8);
  const at = newBondSample();
  const bug: CellSample = { nearest: 0, second: 0, id: 0 };
  const cavity: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    bond(tileToLength(x, EXTENT_U), tileToLength(y, EXTENT_V), SPEC, at);
    const panelKey = hash3(at.unit, at.course, 0, panels);

    // Each panel of plywood leaves its own grain, so the grain field is shifted per panel. The
    // shift belongs to the panel, which repeats with the tile, so the shifted field still does.
    const grainShift = (panelKey >>> 12) & 0xfffff;
    const ply = valueNoise(x + grainShift, y + (grainShift >> 3), 10, 540, plySeed);
    const wave = fbm(x, y, 6, 6, waveSeed, 2);
    const fine = valueNoise(x, y, 900, 900, fineSeed);
    let length = SURFACE_MM * MM
      + floorDiv((wave - 32768) * 600, 32768)
      + floorDiv((ply - 32768) * 180, 32768)
      + floorDiv((fine - 32768) * 70, 32768);
    // The fin: concrete that crept into the panel joint, standing proud of the face.
    const fin = ONE - smoothstep(-MM, MM, at.edge);
    length += floorDiv(fin * FIN_MM_1024THS, ONE);

    // Form-tie holes: a cone, and a stain that runs down from each.
    const du = nearestOf(at.faceU, TIE_U_MM);
    const dv = nearestOf(at.faceV, TIE_V_MM);
    const radius = isqrt(du * du + dv * dv);
    const tie = radius < TIE_RADIUS_MM * MM
      ? floorDiv((TIE_RADIUS_MM * MM - radius) * ONE, TIE_RADIUS_MM * MM)
      : 0;
    // Steep walls within the outer quarter of the radius, then a flat plugged bottom.
    const tieDepth = smoothstep(0, ONE >> 2, tie);
    length -= floorDiv(tieDepth * TIE_DEPTH_MM * MM, ONE);
    const below = dv > 0 && dv < STAIN_LENGTH_MM * MM && Math.abs(du) < 11 * MM
      ? floorDiv(
        (ONE - smoothstep(0, STAIN_LENGTH_MM * MM, dv))
          * (ONE - smoothstep(6 * MM, 11 * MM, Math.abs(du))),
        ONE,
      )
      : 0;

    // Bug holes, small and common, and a few larger voids.
    cells(x, y, 480, 480, bugSeed, ONE, bug);
    const bugRadius = 10500 + pick(bug.id, 0, 9000);
    const bugHole = pick(hash3(bug.id, 0, 0, bugSeed), 0, 99) < 16 && bug.nearest < bugRadius
      ? smoothstep(0, 5000, bugRadius - bug.nearest)
      : 0;
    cells(x, y, 160, 160, voidSeed, ONE, cavity);
    const voidRadius = 8000 + pick(cavity.id, 0, 6000);
    const voidHole = pick(hash3(cavity.id, 0, 0, voidSeed), 0, 99) < 5 && cavity.nearest < voidRadius
      ? smoothstep(0, 2500, voidRadius - cavity.nearest)
      : 0;
    const pore = Math.max(bugHole, voidHole);
    length -= floorDiv(bugHole * 1500, ONE) + floorDiv(voidHole * 3000, ONE);
    out.height = heightOfLength(length, RANGE_MM);

    setColour(out, concrete);
    shade(out, jitter(bits16(hash3(at.unit, at.course, 1, panels)), 2600));
    // Mottling at two scales: the pour's own cloudiness, and smaller blotches of cement paste.
    shade(out, jitter(fbm(x, y, 16, 16, mottleSeed, 4), 9000));
    const blotch = band(fbm(x, y, 64, 64, blotchSeed, 3), 30000, 40000);
    mixColour(out, laitance, floorDiv(blotch * 18, 100));
    shade(out, jitter(fine, 2300));
    shade(out, jitter(ply, 900));
    mixColour(out, seam, floorDiv(fin * 45, 100));
    mixColour(out, stain, floorDiv(below * 45, 100));
    mixColour(out, hole, floorDiv(Math.max(tieDepth, pore) * 85, 100));

    out.roughness = clamp(
      lerp(permille(880), permille(950), Math.max(tie, pore))
        + floorDiv((fine - 32768) * 2600, 32768)
        - floorDiv(blotch * 4, 100),
      0,
      FULL,
    );
    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const concrete = (seed: number, version: number): TextureSetDefinition => ({
  setId: 'cc0.cast-concrete',
  version,
  seed,
  family: 'concrete',
  title: 'Cast concrete',
  summary: 'Plywood-formed concrete on 1200 x 600 mm panels, with form-tie holes and bug holes.',
  width: 1024,
  height: 1024,
  extentU: EXTENT_U,
  extentV: EXTENT_V,
  surface: 'vertical',
  heightRangeMm: RANGE_MM,
  cavity: { radiusMm: 12, depthMm: 3, strengthPermille: 500 },
  parameters: {
    formwork: 'plywood panels, stacked',
    panel_length_mm: PANEL_U,
    panel_height_mm: PANEL_V,
    panel_seam_mm: SEAM_MM,
    panels_per_row: PANELS_PER_ROW,
    rows: ROWS,
    phase_u_mm_1024ths: SPEC.phaseU,
    phase_v_mm_1024ths: SPEC.phaseV,
    surface_height_mm: SURFACE_MM,
    seam_fin_height_mm_1024ths: FIN_MM_1024THS,
    tie_hole_radius_mm: TIE_RADIUS_MM,
    tie_hole_depth_mm: TIE_DEPTH_MM,
    tie_spacing_u_mm: TIE_U_MM[1] - TIE_U_MM[0],
    tie_spacing_v_mm: TIE_V_MM[1] - TIE_V_MM[0],
    tie_stain_length_mm: STAIN_LENGTH_MM,
  },
  recipe: () => recipe(seed),
});
