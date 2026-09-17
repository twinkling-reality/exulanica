import { colour, integer } from '../controls.js';
import { stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, lerp } from '../integer.js';
import type { Maker } from '../maker.js';
import { band, fbm, ridge, valueNoise } from '../noise.js';
import { MAKER_PROFILE_V2, type ProceduralMakerManifest, type Recipe, read } from '../recipe.js';
import { type Pattern, mixColour, permille, setColour } from '../sample.js';
import { decode } from '../srgb.js';

/**
 * Glazing: the clear float glass of a shop window, and the film a street leaves on it.
 *
 * Class `glazing`: the set holds what the glass does to light, not a picture of what is behind it.
 * The base colour is the tint light takes passing through the pane; the transmission map says how
 * much of the light the surface does not reflect passes through; the roughness map says how blurred
 * both reflection and view are. Reflection itself is the renderer's, from the index of refraction
 * the class fixes. What is behind the pane (a vitrine, an interior backing) is geometry the grammar
 * states, never a texture.
 *
 * Clean glass passes everything its reflection does not, and float glass is nearly perfectly
 * smooth. A film of dust, rain streaks and handling marks stops some light, scatters the rest, and
 * has its own colour, so where film lies the texel mixes toward the film's colour, its roughness,
 * and a transmission below full.
 *
 * The set tiles, so it knows nothing of where a pane begins or ends, and it stays mostly clean
 * glass: most texels pass all the light their reflection does not. Glass collects dirt at its edges
 * and along its bottom, where rain runs and hands reach and cleaning misses, and that is a function
 * of position in the pane, which the surface states and the runtime applies, never these texels.
 *
 * What the version fixes: the shape of each kind of film, as the band of its noise field that
 * counts as covered, each band set from where that field's values lie.
 *
 *   - Dust gathers in patches: the top fifth or so of broad fractal noise, a faint haze at a third
 *     of the dust's strength, with fine flecks, the top of a value-noise field, only inside a patch
 *     and more where it lies thick. Between patches the glass is clean.
 *   - A rain streak is a thin line where a field stretched down the pane crosses its middle, kept
 *     only where the top of a second field allows, so streaks are narrow, broken, of unequal length
 *     and occasional, the way running water leaves them, rather than stripes the height of the tile.
 *   - Handling marks keep the top tenth or so of broad fractal noise, faded in over a wide band so a
 *     mark has no edge: a rare smear, never a shape that repeats down a whole street.
 *
 * A person sets how strong each film is and how large its features are.
 *
 * No height field: float glass is flat, and the gentle waviness of a real pane tilts its surface by
 * far less than one step of an eight-bit normal map, so there is no relief to store, and the class
 * layout has no map for it.
 */
export const glazingManifest: ProceduralMakerManifest = {
  profile: MAKER_PROFILE_V2,
  maker_id: 'loom.glazing',
  version: 1,
  kind: 'procedural',
  material_class: 'glazing',
  family: 'glass',
  surface: 'vertical',
  truth: 'invented',
  controls: [
    colour('glass_tint', [246, 250, 247], 'Glass tint',
      'The colour light takes passing through the pane: faintly green, as the iron in soda-lime float glass makes it.'),
    integer('glass_roughness_permille', 'finish', 'permille', [0, 200], 20, 'Glass roughness',
      'How blurred reflections and the view through clean glass are, in thousandths. Float glass is nearly perfectly smooth.'),
    colour('film_colour', [150, 144, 132], 'Film colour',
      'The colour of the dust and grime a street leaves on the glass.'),
    integer('film_roughness_permille', 'wear', 'permille', [0, 1000], 650, 'Film roughness',
      'How rough the glass is where film covers it completely, in thousandths.'),
    integer('dust_percent', 'wear', 'percent', [0, 100], 12, 'Dust',
      'The most light the dust in a patch stops passing through, in percent.'),
    integer('dust_patch_cells', 'detail', 'cells_per_tile', [1, 64], 8, 'Dust patches',
      'How many patches of settled dust fit across one tile; more means smaller patches.'),
    integer('dust_cells', 'detail', 'cells_per_tile', [16, 1024], 320, 'Dust fineness',
      'How many dust flecks fit across one tile; more means finer dust.'),
    integer('streak_percent', 'wear', 'percent', [0, 100], 8, 'Rain streaks',
      'The most light the streaks left by running rain stop passing through, in percent.'),
    integer('streak_cells_across', 'detail', 'cells_per_tile', [4, 512], 80, 'Streak spacing',
      'How many streaks fit side by side across one tile.'),
    integer('streak_cells_along', 'detail', 'cells_per_tile', [1, 64], 4, 'Streak length',
      'How many streak lengths fit down one tile; fewer means longer streaks.'),
    integer('smudge_percent', 'wear', 'percent', [0, 100], 4, 'Handling marks',
      'The most light the faint marks of hands and cleaning stop passing through, in percent.'),
    integer('smudge_cells', 'detail', 'cells_per_tile', [2, 128], 12, 'Mark size',
      'How many handling marks fit across one tile; more means smaller marks.'),
  ],
  constraints: [],
};

function pattern(recipe: Recipe): Pattern {
  const seed = recipe.seed;
  const tint = decode(read.colour(recipe, 'glass_tint'));
  const film = decode(read.colour(recipe, 'film_colour'));
  const glassRoughness = permille(read.integer(recipe, 'glass_roughness_permille'));
  const filmRoughness = permille(read.integer(recipe, 'film_roughness_permille'));
  const dustPercent = read.integer(recipe, 'dust_percent');
  const patchCells = read.integer(recipe, 'dust_patch_cells');
  const dustCells = read.integer(recipe, 'dust_cells');
  const streakPercent = read.integer(recipe, 'streak_percent');
  const streakAcross = read.integer(recipe, 'streak_cells_across');
  const streakAlong = read.integer(recipe, 'streak_cells_along');
  const smudgePercent = read.integer(recipe, 'smudge_percent');
  const smudgeCells = read.integer(recipe, 'smudge_cells');
  const dustSeed = stream(seed, 1);
  const streakSeed = stream(seed, 2);
  const smudgeSeed = stream(seed, 3);
  const hazeSeed = stream(seed, 4);
  const lengthSeed = stream(seed, 5);

  return (x, y, out) => {
    const settled = band(fbm(x, y, patchCells, patchCells, hazeSeed, 3), 38000, 52000);
    const fleck = floorDiv(band(valueNoise(x, y, dustCells, dustCells, dustSeed), 50000, 60000) * settled, ONE);
    const dust = floorDiv(Math.max(fleck, floorDiv(settled, 5)) * dustPercent, 100);
    // A line where a field stretched down the tile (along v, down the pane) crosses its middle,
    // kept only in the lengths a second, longer field allows.
    const line = band(ridge(valueNoise(x, y, streakAcross, streakAlong, streakSeed)), 60000, 64500);
    const lengths = band(valueNoise(x, y, streakAcross, streakAlong * 3, lengthSeed), 46000, 56000);
    const streak = floorDiv(floorDiv(line * lengths, ONE) * streakPercent, 100);
    const smudge = floorDiv(
      band(fbm(x, y, smudgeCells, smudgeCells, smudgeSeed, 3), 44000, 56000) * smudgePercent,
      100,
    );
    const covered = Math.max(dust, streak, smudge);

    setColour(out, tint);
    mixColour(out, film, covered);
    out.transmission = clamp(FULL - covered, 0, FULL);
    out.roughness = lerp(glassRoughness, filmRoughness, covered);
    out.metalness = 0;
    out.height = 0;
    out.occlusion = ONE;
    out.coverage = 0;
  };
}

export const glazingMaker: Maker = {
  manifest: glazingManifest,
  stated(recipe) {
    const { u, v } = recipe.extent_mm;
    return {
      glass: 'clear soda-lime float glass',
      dust_patch_mm: floorDiv(u, read.integer(recipe, 'dust_patch_cells')),
      dust_fleck_mm: floorDiv(u, read.integer(recipe, 'dust_cells')),
      streak_spacing_mm: floorDiv(u, read.integer(recipe, 'streak_cells_across')),
      streak_length_mm: floorDiv(v, read.integer(recipe, 'streak_cells_along')),
      handling_mark_mm: floorDiv(u, read.integer(recipe, 'smudge_cells')),
    };
  },
  pattern,
};
