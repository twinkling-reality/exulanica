import { type BondSpec, bond, checkBond, newBondSample } from '../bond.js';
import {
  colour,
  commonControls,
  equal,
  extent,
  integer,
  integers,
  less,
  lessOrEqual,
  param,
  product,
} from '../controls.js';
import { bits16, hash3, pick, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, isqrt, lerp, smoothstep } from '../integer.js';
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
 * Cast-in-place concrete off plywood formwork: stacked form panels on a stated module, a fin at
 * every panel seam, form-tie holes at stated positions on each panel with a run-off stain below,
 * bug holes and a few larger voids, and the pour's own mottling. Each panel keeps its own plywood
 * grain, shifted by the panel's identity, which repeats with the tile.
 */
export const concreteManifest: MakerManifest = {
  profile: MAKER_PROFILE,
  maker_id: 'loom.concrete',
  version: 1,
  kind: 'procedural',
  family: 'concrete',
  surface: 'vertical',
  truth: 'invented',
  controls: [
    integer('panel_length_mm', 'module', 'mm', [200, 4000], 1200, 'Panel length',
      'One form panel along the wall, seam included.'),
    integer('panel_height_mm', 'module', 'mm', [200, 4000], 600, 'Panel height',
      'One form panel up the wall, seam included.'),
    integer('panel_seam_mm', 'module', 'mm', [1, 20], 2, 'Seam width',
      'The gap between form panels that leaves a fin.'),
    integer('panels_per_row', 'module', 'count', [1, 16], 2, 'Panels per row',
      'Whole panels along one tile.'),
    integer('rows', 'module', 'count', [1, 16], 4, 'Panel rows', 'Whole panel rows down one tile.'),
    integers('tie_u_mm', 'module', 'mm', [0, 4000], [1, 8], [299, 899], 'Tie positions across',
      'Where form ties sit along a panel, from its left edge.'),
    integers('tie_v_mm', 'module', 'mm', [0, 4000], [1, 8], [149, 449], 'Tie positions down',
      'Where form ties sit down a panel, from its top edge.'),
    colour('concrete_colour', [160, 158, 152], 'Concrete colour', 'The pour itself.'),
    colour('hole_colour', [96, 94, 90], 'Hole colour', 'Inside tie holes and voids.'),
    colour('stain_colour', [122, 120, 116], 'Stain colour', 'Run-off below each tie.'),
    colour('seam_colour', [124, 122, 118], 'Seam colour', 'The fin at each panel seam.'),
    colour('laitance_colour', [182, 180, 174], 'Cement paste colour',
      'Pale blotches of cement paste at the surface.'),
    integer('surface_height_mm', 'relief', 'mm', [1, 60], 10, 'Surface height',
      'How far the face stands above the bottom of the height range.'),
    integer('seam_fin_height_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 600, 'Fin height',
      'How far the fin at a seam stands proud.'),
    integer('tie_hole_radius_mm', 'relief', 'mm', [1, 60], 14, 'Tie hole radius',
      'The radius of a plugged form-tie hole.'),
    integer('tie_hole_depth_mm', 'relief', 'mm', [0, 60], 8, 'Tie hole depth',
      'How deep a tie hole is.'),
    integer('tie_stain_length_mm', 'wear', 'mm', [1, 2000], 260, 'Stain length',
      'How far the run-off stain reaches below a tie.'),
    integer('waviness_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 600, 'Waviness',
      'How far the face departs from flat over a panel.'),
    integer('ply_grain_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 180, 'Plywood grain',
      'The height of the grain the plywood printed into the face.'),
    integer('fine_grain_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 70, 'Fine grain',
      'The height of the finest surface texture.'),
    integer('bug_hole_percent', 'detail', 'percent', [0, 100], 16, 'Bug holes',
      'How often a small cell holds a bug hole.'),
    integer('bug_hole_depth_mm_1024ths', 'detail', 'mm_1024ths', [0, 8192], 1500,
      'Bug hole depth', 'How deep a bug hole is.'),
    integer('void_percent', 'detail', 'percent', [0, 100], 5, 'Voids',
      'How often a larger cell holds a void.'),
    integer('void_depth_mm_1024ths', 'detail', 'mm_1024ths', [0, 8192], 3000, 'Void depth',
      'How deep a void is.'),
    integer('panel_brightness_spread_q16', 'colour', 'q16', [0, 32768], 2600,
      'Pour-to-pour variation', 'How much one panel may be lighter or darker than the next.'),
    integer('mottle_spread_q16', 'colour', 'q16', [0, 32768], 9000, 'Mottling',
      'The pour\'s cloudy colour variation.'),
    integer('laitance_percent', 'colour', 'percent', [0, 100], 18, 'Cement paste',
      'How strongly the pale paste blotches show.'),
    integer('fine_spread_q16', 'colour', 'q16', [0, 32768], 2300, 'Fine colour',
      'Colour variation from the finest grain.'),
    integer('ply_spread_q16', 'colour', 'q16', [0, 32768], 900, 'Grain colour',
      'Colour variation from the plywood grain.'),
    integer('seam_percent', 'colour', 'percent', [0, 100], 45, 'Seam darkening',
      'How strongly the seam colour shows on a fin.'),
    integer('stain_percent', 'wear', 'percent', [0, 100], 45, 'Stain strength',
      'How strongly a tie stain shows.'),
    integer('hole_percent', 'colour', 'percent', [0, 100], 85, 'Hole darkness',
      'How strongly the hole colour shows inside a hole.'),
    integer('concrete_roughness_permille', 'finish', 'permille', [0, 1000], 880,
      'Concrete roughness', 'How matte the face is, in thousandths.'),
    integer('hole_roughness_permille', 'finish', 'permille', [0, 1000], 950, 'Hole roughness',
      'How matte the inside of a hole is, in thousandths.'),
    integer('laitance_smoothing_percent', 'finish', 'percent', [0, 100], 4, 'Paste smoothness',
      'How much smoother the cement paste blotches are.'),
    ...commonControls({
      heightRangeMm: 12,
      occlusionRadiusMm: 12,
      occlusionDepthMm: 3,
      occlusionStrengthPermille: 500,
    }),
  ],
  constraints: [
    equal(product(param('panels_per_row'), param('panel_length_mm')), extent('u'),
      'panels per row times the panel length must equal the tile width'),
    equal(product(param('rows'), param('panel_height_mm')), extent('v'),
      'rows times the panel height must equal the tile height'),
    less(param('panel_seam_mm'), param('panel_length_mm'), 'a seam is shorter than its panel is long'),
    less(param('panel_seam_mm'), param('panel_height_mm'), 'a seam is shorter than its panel is high'),
    lessOrEqual(param('surface_height_mm'), param('height_range_mm'),
      'the face must lie inside the height range'),
  ],
};

function spec(recipe: Recipe): BondSpec {
  const moduleU = read.integer(recipe, 'panel_length_mm');
  const moduleV = read.integer(recipe, 'panel_height_mm');
  const seam = read.integer(recipe, 'panel_seam_mm');
  return {
    moduleU,
    moduleV,
    jointU: seam,
    jointV: seam,
    unitsPerCourse: read.integer(recipe, 'panels_per_row'),
    courses: read.integer(recipe, 'rows'),
    oddCourseShift: 0,
    phaseU: (moduleU * MM) / 2,
    phaseV: (moduleV * MM) / 2,
  };
}

function nearestOf(value: number, centres: readonly number[]): number {
  let best = Number.POSITIVE_INFINITY;
  for (const centre of centres) {
    const d = value - centre * MM;
    if (Math.abs(d) < Math.abs(best)) best = d;
  }
  return best;
}

function pattern(recipe: Recipe): Pattern {
  const bondSpec = spec(recipe);
  const extentU = recipe.extent_mm.u;
  const extentV = recipe.extent_mm.v;
  checkBond(bondSpec, extentU, extentV);
  const seed = recipe.seed;
  const tieU = read.integers(recipe, 'tie_u_mm');
  const tieV = read.integers(recipe, 'tie_v_mm');
  const concrete = decode(read.colour(recipe, 'concrete_colour'));
  const hole = decode(read.colour(recipe, 'hole_colour'));
  const stain = decode(read.colour(recipe, 'stain_colour'));
  const seam = decode(read.colour(recipe, 'seam_colour'));
  const laitance = decode(read.colour(recipe, 'laitance_colour'));
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const surfaceMm = read.integer(recipe, 'surface_height_mm');
  const finHeight = read.integer(recipe, 'seam_fin_height_mm_1024ths');
  const tieRadius = read.integer(recipe, 'tie_hole_radius_mm') * MM;
  const tieDepthMm = read.integer(recipe, 'tie_hole_depth_mm');
  const stainLength = read.integer(recipe, 'tie_stain_length_mm') * MM;
  const waviness = read.integer(recipe, 'waviness_mm_1024ths');
  const plyGrain = read.integer(recipe, 'ply_grain_mm_1024ths');
  const fineGrain = read.integer(recipe, 'fine_grain_mm_1024ths');
  const bugPercent = read.integer(recipe, 'bug_hole_percent');
  const bugDepth = read.integer(recipe, 'bug_hole_depth_mm_1024ths');
  const voidPercent = read.integer(recipe, 'void_percent');
  const voidDepth = read.integer(recipe, 'void_depth_mm_1024ths');
  const panelSpread = read.integer(recipe, 'panel_brightness_spread_q16');
  const mottleSpread = read.integer(recipe, 'mottle_spread_q16');
  const laitancePercent = read.integer(recipe, 'laitance_percent');
  const fineSpread = read.integer(recipe, 'fine_spread_q16');
  const plySpread = read.integer(recipe, 'ply_spread_q16');
  const seamPercent = read.integer(recipe, 'seam_percent');
  const stainPercent = read.integer(recipe, 'stain_percent');
  const holePercent = read.integer(recipe, 'hole_percent');
  const concreteRoughness = permille(read.integer(recipe, 'concrete_roughness_permille'));
  const holeRoughness = permille(read.integer(recipe, 'hole_roughness_permille'));
  const laitanceSmoothing = read.integer(recipe, 'laitance_smoothing_percent');
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
    bond(tileToLength(x, extentU), tileToLength(y, extentV), bondSpec, at);
    const panelKey = hash3(at.unit, at.course, 0, panels);

    // Each panel of plywood leaves its own grain, so the grain field is shifted per panel. The
    // shift belongs to the panel, which repeats with the tile, so the shifted field still does.
    const grainShift = (panelKey >>> 12) & 0xfffff;
    const ply = valueNoise(x + grainShift, y + (grainShift >> 3), 10, 540, plySeed);
    const wave = fbm(x, y, 6, 6, waveSeed, 2);
    const fine = valueNoise(x, y, 900, 900, fineSeed);
    let length = surfaceMm * MM
      + floorDiv((wave - 32768) * waviness, 32768)
      + floorDiv((ply - 32768) * plyGrain, 32768)
      + floorDiv((fine - 32768) * fineGrain, 32768);
    // The fin: concrete that crept into the panel joint, standing proud of the face.
    const fin = ONE - smoothstep(-MM, MM, at.edge);
    length += floorDiv(fin * finHeight, ONE);

    // Form-tie holes: a cone, and a stain that runs down from each.
    const du = nearestOf(at.faceU, tieU);
    const dv = nearestOf(at.faceV, tieV);
    const radius = isqrt(du * du + dv * dv);
    const tie = radius < tieRadius ? floorDiv((tieRadius - radius) * ONE, tieRadius) : 0;
    // Steep walls within the outer quarter of the radius, then a flat plugged bottom.
    const tieDepth = smoothstep(0, ONE >> 2, tie);
    length -= floorDiv(tieDepth * tieDepthMm * MM, ONE);
    const below = dv > 0 && dv < stainLength && Math.abs(du) < 11 * MM
      ? floorDiv(
        (ONE - smoothstep(0, stainLength, dv))
          * (ONE - smoothstep(6 * MM, 11 * MM, Math.abs(du))),
        ONE,
      )
      : 0;

    // Bug holes, small and common, and a few larger voids.
    cells(x, y, 480, 480, bugSeed, ONE, bug);
    const bugRadius = 10500 + pick(bug.id, 0, 9000);
    const bugHole = pick(hash3(bug.id, 0, 0, bugSeed), 0, 99) < bugPercent && bug.nearest < bugRadius
      ? smoothstep(0, 5000, bugRadius - bug.nearest)
      : 0;
    cells(x, y, 160, 160, voidSeed, ONE, cavity);
    const voidRadius = 8000 + pick(cavity.id, 0, 6000);
    const voidHole = pick(hash3(cavity.id, 0, 0, voidSeed), 0, 99) < voidPercent
      && cavity.nearest < voidRadius
      ? smoothstep(0, 2500, voidRadius - cavity.nearest)
      : 0;
    const pore = Math.max(bugHole, voidHole);
    length -= floorDiv(bugHole * bugDepth, ONE) + floorDiv(voidHole * voidDepth, ONE);
    out.height = heightOfLength(length, rangeMm);

    setColour(out, concrete);
    shade(out, jitter(bits16(hash3(at.unit, at.course, 1, panels)), panelSpread));
    // Mottling at two scales: the pour's own cloudiness, and smaller blotches of cement paste.
    shade(out, jitter(fbm(x, y, 16, 16, mottleSeed, 4), mottleSpread));
    const blotch = band(fbm(x, y, 64, 64, blotchSeed, 3), 30000, 40000);
    mixColour(out, laitance, floorDiv(blotch * laitancePercent, 100));
    shade(out, jitter(fine, fineSpread));
    shade(out, jitter(ply, plySpread));
    mixColour(out, seam, floorDiv(fin * seamPercent, 100));
    mixColour(out, stain, floorDiv(below * stainPercent, 100));
    mixColour(out, hole, floorDiv(Math.max(tieDepth, pore) * holePercent, 100));

    out.roughness = clamp(
      lerp(concreteRoughness, holeRoughness, Math.max(tie, pore))
        + floorDiv((fine - 32768) * 2600, 32768)
        - floorDiv(blotch * laitanceSmoothing, 100),
      0,
      FULL,
    );
    out.metalness = 0;
    out.occlusion = ONE;
  };
}

const spacing = (positions: readonly number[]): number =>
  positions.length >= 2 ? positions[1]! - positions[0]! : 0;

export const concreteMaker: Maker = {
  manifest: concreteManifest,
  stated(recipe) {
    const bondSpec = spec(recipe);
    return {
      formwork: 'plywood panels, stacked',
      panel_length_mm: bondSpec.moduleU,
      panel_height_mm: bondSpec.moduleV,
      panel_seam_mm: bondSpec.jointU,
      panels_per_row: bondSpec.unitsPerCourse,
      rows: bondSpec.courses,
      phase_u_mm_1024ths: bondSpec.phaseU,
      phase_v_mm_1024ths: bondSpec.phaseV,
      surface_height_mm: read.integer(recipe, 'surface_height_mm'),
      seam_fin_height_mm_1024ths: read.integer(recipe, 'seam_fin_height_mm_1024ths'),
      tie_hole_radius_mm: read.integer(recipe, 'tie_hole_radius_mm'),
      tie_hole_depth_mm: read.integer(recipe, 'tie_hole_depth_mm'),
      tie_spacing_u_mm: spacing(read.integers(recipe, 'tie_u_mm')),
      tie_spacing_v_mm: spacing(read.integers(recipe, 'tie_v_mm')),
      tie_stain_length_mm: read.integer(recipe, 'tie_stain_length_mm'),
    };
  },
  pattern,
};
