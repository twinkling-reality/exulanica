import { colour, commonControls, integer } from '../controls.js';
import { pick, stream } from '../hash.js';
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
import { MM } from '../tile.js';

/**
 * Painted render (stucco) with a dashed finish.
 *
 * No joints and no module, so the extent is a statement about how large the finish's features are:
 * the dash is laid on its own cell and the trowel relief on a coarser one, both counted per tile.
 * Paint flakes from a few raised dashes, which is where a wall is rubbed and weathered first.
 * Anything broader than a few hundred millimetres is kept faint, because a strong broad stain in a
 * tiling texture is a stain the whole street repeats.
 */
export const renderManifest: MakerManifest = {
  profile: MAKER_PROFILE,
  maker_id: 'loom.render',
  version: 1,
  kind: 'procedural',
  family: 'render',
  surface: 'vertical',
  truth: 'invented',
  controls: [
    colour('paint_colour', [210, 198, 172], 'Paint colour', 'The paint over the render.'),
    colour('render_colour', [156, 152, 144], 'Render colour',
      'The bare render that shows where paint has flaked.'),
    colour('grime_colour', [120, 112, 98], 'Grime colour', 'What dirt on the wall looks like.'),
    integer('dash_cells_per_tile', 'detail', 'cells_per_tile', [16, 1024], 300, 'Dash size',
      'How many dash cells cross one tile; more cells make a finer dash.'),
    integer('relief_cells_per_tile', 'detail', 'cells_per_tile', [1, 512], 40, 'Trowel scale',
      'How many trowel-relief cells cross one tile.'),
    integer('base_height_mm_1024ths', 'relief', 'mm_1024ths', [0, 32768], 1536, 'Base height',
      'The render surface before relief and dashes.'),
    integer('relief_amplitude_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 760,
      'Trowel relief', 'How far the trowelled surface rises and falls.'),
    integer('dash_height_max_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 1180, 'Dash height',
      'How far a dash stands proud.'),
    integer('sand_grain_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 90, 'Sand grain',
      'The height of the finest grain.'),
    integer('hue_spread_q16', 'colour', 'q16', [0, 32768], 1300, 'Paint variation',
      'Broad, faint variation in the paint.'),
    integer('sand_spread_q16', 'colour', 'q16', [0, 32768], 900, 'Grain colour',
      'Fine colour variation from the grain.'),
    integer('crown_brighten_percent', 'colour', 'percent', [0, 50], 3, 'Dash highlights',
      'How much lighter the paint is on a dash crown.'),
    integer('flaking_threshold_q16', 'wear', 'q16', [0, 80000], 56000, 'Flaking rarity',
      'Higher means paint flakes from fewer dashes.'),
    integer('flaking_strength_percent', 'wear', 'percent', [0, 100], 80, 'Flaking depth',
      'How completely the paint is gone where it has flaked.'),
    integer('dirt_percent', 'wear', 'percent', [0, 100], 9, 'Grime',
      'The most grime darkens the paint, in percent.'),
    integer('paint_roughness_permille', 'finish', 'permille', [0, 1000], 720, 'Paint roughness',
      'How matte the paint is, in thousandths.'),
    integer('worn_roughness_permille', 'finish', 'permille', [0, 1000], 900,
      'Bare render roughness', 'How matte the exposed render is, in thousandths.'),
    integer('dirt_roughness_percent', 'finish', 'percent', [0, 50], 6, 'Grime roughness',
      'How much grime dulls the surface, in percent.'),
    ...commonControls({
      heightRangeMm: 4,
      occlusionRadiusMm: 6,
      occlusionDepthMm: 1,
      occlusionStrengthPermille: 300,
    }),
  ],
  constraints: [],
};

function pattern(recipe: Recipe): Pattern {
  const seed = recipe.seed;
  const paint = decode(read.colour(recipe, 'paint_colour'));
  const render = decode(read.colour(recipe, 'render_colour'));
  const grime = decode(read.colour(recipe, 'grime_colour'));
  const dashCells = read.integer(recipe, 'dash_cells_per_tile');
  const reliefCells = read.integer(recipe, 'relief_cells_per_tile');
  const base = read.integer(recipe, 'base_height_mm_1024ths');
  const reliefAmplitude = read.integer(recipe, 'relief_amplitude_mm_1024ths');
  const dashHeight = read.integer(recipe, 'dash_height_max_mm_1024ths');
  const sandGrain = read.integer(recipe, 'sand_grain_mm_1024ths');
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const hueSpread = read.integer(recipe, 'hue_spread_q16');
  const sandSpread = read.integer(recipe, 'sand_spread_q16');
  const crown = read.integer(recipe, 'crown_brighten_percent');
  const flakingThreshold = read.integer(recipe, 'flaking_threshold_q16');
  const flakingStrength = read.integer(recipe, 'flaking_strength_percent');
  const dirtPercent = read.integer(recipe, 'dirt_percent');
  const paintRoughness = permille(read.integer(recipe, 'paint_roughness_permille'));
  const wornRoughness = permille(read.integer(recipe, 'worn_roughness_permille'));
  const dirtRoughness = read.integer(recipe, 'dirt_roughness_percent');
  const reliefSeed = stream(seed, 1);
  const dashSeed = stream(seed, 2);
  const sandSeed = stream(seed, 3);
  const wearSeed = stream(seed, 4);
  const hueSeed = stream(seed, 5);
  const dirtSeed = stream(seed, 6);
  const dash: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    const relief = fbm(x, y, reliefCells, reliefCells, reliefSeed, 4);
    cells(x, y, dashCells, dashCells, dashSeed, ONE, dash);
    const size = 30000 + pick(dash.id, 0, 12000);
    const blob = dash.nearest < size ? smoothstep(0, size, size - dash.nearest) : 0;
    const sand = valueNoise(x, y, 1000, 1000, sandSeed);
    const length = base
      + floorDiv((relief - 32768) * reliefAmplitude, 32768)
      + floorDiv(blob * dashHeight, ONE)
      + floorDiv((sand - 32768) * sandGrain, 32768);
    out.height = heightOfLength(length, rangeMm);

    setColour(out, paint);
    shade(out, jitter(fbm(x, y, 9, 9, hueSeed, 2), hueSpread));
    shade(out, jitter(sand, sandSpread));
    // Dashes catch a little more light-coloured paint on their crowns.
    shade(out, ONE + floorDiv(blob * crown, 100));

    // Flaking: small, and only on raised dashes where the flaking field also runs high.
    const raised = clamp(length - base, 0, MM);
    const wearField = fbm(x, y, 24, 24, wearSeed, 3) + floorDiv(raised * 9000, MM);
    const worn = band(wearField, flakingThreshold, flakingThreshold + 3000);
    mixColour(out, render, floorDiv(worn * flakingStrength, 100));

    const dirt = band(fbm(x, y, 12, 12, dirtSeed, 3), 26000, 46000);
    mixColour(out, grime, floorDiv(dirt * dirtPercent, 100));

    out.roughness = clamp(
      lerp(paintRoughness, wornRoughness, worn) + floorDiv(dirt * dirtRoughness, 100),
      0,
      FULL,
    );
    out.metalness = 0;
    out.occlusion = ONE;
  };
}

export const renderMaker: Maker = {
  manifest: renderManifest,
  stated(recipe) {
    return {
      finish: 'dashed render, painted',
      dash_cell_mm_1024ths: floorDiv(
        recipe.extent_mm.u * MM,
        read.integer(recipe, 'dash_cells_per_tile'),
      ),
      relief_cell_mm: floorDiv(recipe.extent_mm.u, read.integer(recipe, 'relief_cells_per_tile')),
      base_height_mm_1024ths: read.integer(recipe, 'base_height_mm_1024ths'),
      relief_amplitude_mm_1024ths: read.integer(recipe, 'relief_amplitude_mm_1024ths'),
      dash_height_max_mm_1024ths: read.integer(recipe, 'dash_height_max_mm_1024ths'),
    };
  },
  pattern,
};
