import {
  colour,
  commonControls,
  constant,
  even,
  integer,
  lessOrEqual,
  palette,
  param,
  product,
  sum,
} from '../controls.js';
import { bits16, hash3, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, floorMod } from '../integer.js';
import type { Maker } from '../maker.js';
import { band, fbm, ridge, valueNoise } from '../noise.js';
import { MAKER_PROFILE_V2, type ProceduralMakerManifest, type Recipe, read } from '../recipe.js';
import { type Pattern, heightOfLength, jitter, mixColour, permille, setColour, shade } from '../sample.js';
import { type Linear, decode } from '../srgb.js';
import { MM, TILE } from '../tile.js';

/**
 * Awning canvas: the striped woven cloth of a shop awning, faded by the sun and streaked by rain.
 *
 * An awning is a horizontal surface in the grammar's frames, so u runs along the shopfront and v
 * across the awning, down its slope. Stripes are bands across u, each one colour down its whole
 * length, which is how an awning is woven and printed. Rain runs down the slope, so its streaks run
 * along v.
 *
 * What the version fixes, each with its reason:
 *
 *   - A plain weave: the tile is divided into threads both ways, and at each crossing either the
 *     warp (a thread down the slope) or the weft (one along the shopfront) is on top, alternating
 *     like a chessboard, which is what a plain weave is. A thread's own profile is a triangle,
 *     highest along its middle, so the cloth reads as threads rather than as a grid of dots. The
 *     count of threads across the tile is even by constraint, or the alternation would not close on
 *     the tile.
 *   - A stripe's colour comes from the palette in order, repeating: a person states the colours and
 *     how many stripes fit across the tile, and nothing here chooses a pattern for them.
 *   - Sun fading keeps the upper part of broad fractal noise (34000 to 50000, measured) on a field
 *     as broad as the person sets, because cloth fades unevenly where its own frame and what stands
 *     near it shade parts of it. It is meant to read as gentle unevenness: patchy bleaching at a
 *     small scale reads as mould, which is a different thing and not this set's.
 *   - Rain streaks are the top of a field stretched along the slope, kept where a second, longer
 *     field allows, so they are narrow, broken and run the way water runs.
 *   - Sag: an awning's rafters are spaced along the shopfront and the cloth spans between them, so
 *     it dips along u, one dip to a rafter, and stays straight down the slope. The dip is a
 *     triangle in height for the same reason a thread is.
 *
 * A person sets the colours, the stripes, the thread size, the sag, the fading, the streaking and
 * how matte the cloth is. Whether a particular awning is faded on one side is a fact about that
 * awning, so it belongs to its material record, not to this tile.
 */
export const canvasManifest: ProceduralMakerManifest = {
  profile: MAKER_PROFILE_V2,
  maker_id: 'loom.canvas',
  version: 1,
  kind: 'procedural',
  material_class: 'opaque',
  family: 'fabric',
  surface: 'horizontal',
  truth: 'invented',
  controls: [
    palette('stripe_colours', [
      [58, 74, 96],
      [214, 208, 194],
    ], [1, 16], 'Stripe colours', 'The stripes, in order across the tile, repeating.'),
    colour('bleached_colour', [226, 220, 206], 'Bleached colour',
      'What the cloth fades toward where the sun has bleached it.'),
    colour('dirt_colour', [104, 98, 88], 'Dirt colour', 'The grime rain leaves running down the slope.'),
    integer('stripes_across', 'module', 'cells_per_tile', [1, 64], 8, 'Stripes across',
      'How many stripes fit across one tile, along the shopfront.'),
    integer('thread_cells_across', 'detail', 'cells_per_tile', [16, 1024], 240, 'Thread size',
      'How many threads fit across one tile; more means finer cloth.'),
    integer('thread_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 4096], 1100, 'Thread relief',
      'How far a thread stands above the crossing beside it.'),
    integer('thread_tone_q16', 'colour', 'q16', [0, 32768], 3000, 'Thread tone',
      'How much a thread on top is lighter than the one beneath it.'),
    integer('ripples_across', 'detail', 'cells_per_tile', [1, 32], 3, 'Sag ripples',
      'How many dips the cloth makes across one tile, one to a rafter.'),
    integer('ripple_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 2400, 'Sag depth',
      'How far the cloth dips between two frame bars.'),
    integer('fade_percent', 'wear', 'percent', [0, 100], 10, 'Sun fading',
      'The most the sun has bleached the cloth, in percent.'),
    integer('fade_cells', 'wear', 'cells_per_tile', [1, 64], 2, 'Fade patches',
      'How many patches of fading fit across one tile; more means smaller patches.'),
    integer('streak_percent', 'wear', 'percent', [0, 100], 14, 'Rain streaks',
      'The most the streaks left by running rain darken the cloth, in percent.'),
    integer('streak_cells_across', 'detail', 'cells_per_tile', [4, 512], 60, 'Streak spacing',
      'How many streaks fit side by side across one tile.'),
    integer('streak_cells_along', 'detail', 'cells_per_tile', [1, 64], 3, 'Streak length',
      'How many streak lengths fit down one tile; fewer means longer streaks.'),
    integer('canvas_roughness_permille', 'finish', 'permille', [0, 1000], 860, 'Canvas roughness',
      'How matte the cloth is, in thousandths.'),
    integer('dirt_roughness_percent', 'finish', 'percent', [0, 50], 6, 'Dirt roughness',
      'How much a streak of dirt dulls the cloth, in percent.'),
    ...commonControls({
      heightRangeMm: 6,
      occlusionRadiusMm: 6,
      occlusionDepthMm: 2,
      occlusionStrengthPermille: 350,
    }),
  ],
  constraints: [
    even(param('thread_cells_across'),
      'the threads alternate warp and weft, so an even number of them closes on the tile'),
    lessOrEqual(
      sum(param('ripple_mm_1024ths'), param('thread_relief_mm_1024ths')),
      product(param('height_range_mm'), constant(1024)),
      'the sag and the threads together fit inside the height range',
    ),
  ],
};

/** The broad-noise band sun fading keeps, measured as about its upper third. */
const FADE_LOW = 34000;
const FADE_HIGH = 50000;
/** The band a rain streak's line keeps, and the band of the field that cuts it into lengths. */
const STREAK_LOW = 58000;
const STREAK_HIGH = 64500;
const LENGTH_LOW = 44000;
const LENGTH_HIGH = 56000;

/** A triangle across one cell of `period` cells to the tile: ONE along the middle, 0 at the edges. */
function acrossCell(position: number, period: number): number {
  const scaled = position * period;
  const cell = floorDiv(scaled, TILE);
  const fraction = floorDiv((scaled - cell * TILE) * ONE, TILE);
  return ONE - 2 * Math.abs(fraction - (ONE >> 1));
}

/** Which cell of `period` cells to the tile a position falls in, wrapped into the tile. */
function cellOf(position: number, period: number): number {
  return floorMod(floorDiv(position * period, TILE), period);
}

function pattern(recipe: Recipe): Pattern {
  const seed = recipe.seed;
  const stripes = read.palette(recipe, 'stripe_colours').map(decode);
  const bleached = decode(read.colour(recipe, 'bleached_colour'));
  const dirt = decode(read.colour(recipe, 'dirt_colour'));
  const stripesAcross = read.integer(recipe, 'stripes_across');
  const threads = read.integer(recipe, 'thread_cells_across');
  const threadRelief = read.integer(recipe, 'thread_relief_mm_1024ths');
  const threadTone = read.integer(recipe, 'thread_tone_q16');
  const ripples = read.integer(recipe, 'ripples_across');
  const rippleDepth = read.integer(recipe, 'ripple_mm_1024ths');
  const fadePercent = read.integer(recipe, 'fade_percent');
  const fadeCells = read.integer(recipe, 'fade_cells');
  const streakPercent = read.integer(recipe, 'streak_percent');
  const streakAcross = read.integer(recipe, 'streak_cells_across');
  const streakAlong = read.integer(recipe, 'streak_cells_along');
  const roughness = permille(read.integer(recipe, 'canvas_roughness_permille'));
  const dirtRoughness = read.integer(recipe, 'dirt_roughness_percent');
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const fadeSeed = stream(seed, 1);
  const streakSeed = stream(seed, 2);
  const lengthSeed = stream(seed, 3);
  const stripeSeed = stream(seed, 4);
  // The threads run in both directions on the same pitch, so the cloth is square-woven.
  const threadsDown = Math.max(2, floorDiv(threads * recipe.extent_mm.v, recipe.extent_mm.u));

  return (x, y, out) => {
    // The weave: at each crossing the warp or the weft is on top, alternating like a chessboard.
    const warpOnTop = ((cellOf(x, threads) + cellOf(y, threadsDown)) & 1) === 0;
    const thread = warpOnTop ? acrossCell(x, threads) : acrossCell(y, threadsDown);
    const sag = acrossCell(x, ripples);
    out.height = heightOfLength(
      floorDiv(sag * rippleDepth, ONE) + floorDiv(thread * threadRelief, ONE),
      rangeMm,
    );

    const stripe = cellOf(x, stripesAcross) % stripes.length;
    setColour(out, stripes[stripe] as Linear);
    // A thread on top catches more light than the one it crosses over.
    shade(out, jitter(warpOnTop ? thread : ONE - thread, threadTone));
    // One stripe is never quite the tone of the next, even where the sun has not reached.
    shade(out, jitter(bits16(hash3(stripe, 0, 0, stripeSeed)), threadTone));

    const fade = band(fbm(x, y, fadeCells, fadeCells, fadeSeed, 3), FADE_LOW, FADE_HIGH);
    mixColour(out, bleached, floorDiv(fade * fadePercent, 100));

    const line = band(ridge(valueNoise(x, y, streakAcross, streakAlong, streakSeed)), STREAK_LOW, STREAK_HIGH);
    const lengths = band(valueNoise(x, y, streakAcross, streakAlong * 3, lengthSeed), LENGTH_LOW, LENGTH_HIGH);
    const streak = floorDiv(floorDiv(line * lengths, ONE) * streakPercent, 100);
    mixColour(out, dirt, streak);

    out.roughness = clamp(roughness + floorDiv(streak * dirtRoughness, 100), 0, FULL);
    out.metalness = 0;
    out.occlusion = ONE;
    out.coverage = 0;
    out.transmission = 0;
  };
}

export const canvasMaker: Maker = {
  manifest: canvasManifest,
  stated(recipe) {
    const { u } = recipe.extent_mm;
    const colours = read.palette(recipe, 'stripe_colours').length;
    return {
      fabric: colours === 1 ? 'woven canvas, plain' : 'woven canvas, striped',
      stripe_width_mm: floorDiv(u, read.integer(recipe, 'stripes_across')),
      thread_mm_1024ths: floorDiv(u * MM, read.integer(recipe, 'thread_cells_across')),
      ripple_mm: floorDiv(u, read.integer(recipe, 'ripples_across')),
      streak_spacing_mm: floorDiv(u, read.integer(recipe, 'streak_cells_across')),
    };
  },
  pattern,
};
