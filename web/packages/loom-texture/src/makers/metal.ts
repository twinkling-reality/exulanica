import { choice, colour, commonControls, integer } from '../controls.js';
import { stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, lerp } from '../integer.js';
import type { Maker } from '../maker.js';
import { band, fbm, valueNoise } from '../noise.js';
import { MAKER_PROFILE, type MakerManifest, type Recipe, read } from '../recipe.js';
import { type Pattern, heightOfLength, jitter, permille, setColour, shade } from '../sample.js';
import { decode } from '../srgb.js';

/**
 * Brushed metal: the finish of most storefront framing and cladding, clear-anodised aluminium by
 * default.
 *
 * The brushing runs along u. Real hairline brushing is finer than a 1 mm texel, so it is carried
 * mostly by roughness and base colour, with streak fields the texels can actually hold. The base
 * colour is the metal's reflectance at normal incidence, as glTF expects of a metal, and metalness
 * is full except under faint handling marks, which are a thin dielectric film.
 */
const FINISHES = [
  'clear anodised',
  'bronze anodised',
  'black anodised',
  'stainless steel',
  'brass',
] as const;

export const metalManifest: MakerManifest = {
  profile: MAKER_PROFILE,
  maker_id: 'loom.metal',
  version: 1,
  kind: 'procedural',
  family: 'metal',
  surface: 'vertical',
  truth: 'invented',
  controls: [
    choice('finish', 'finish', FINISHES, 'clear anodised', 'Finish',
      'What the metal is; the header states it, so it must match the colour chosen.'),
    colour('metal_colour', [228, 230, 232], 'Metal colour',
      'The metal\'s reflectance: pale grey for aluminium, warmer for bronze or brass.'),
    integer('brush_cells_along', 'finish', 'cells_per_tile', [1, 64], 4, 'Streak length',
      'How many brush streaks fit end to end along one tile; fewer means longer streaks.'),
    integer('brush_cells_across', 'finish', 'cells_per_tile', [16, 1024], 400, 'Streak fineness',
      'How many brush streaks stack across one tile.'),
    integer('hair_cells_along', 'finish', 'cells_per_tile', [1, 256], 16, 'Hairline length',
      'How many hairlines fit end to end along one tile.'),
    integer('hair_cells_across', 'finish', 'cells_per_tile', [16, 1024], 512, 'Hairline fineness',
      'How many hairlines stack across one tile.'),
    integer('surface_height_mm_1024ths', 'relief', 'mm_1024ths', [0, 1024], 512,
      'Surface height', 'Where the metal face sits in the height range.'),
    integer('brush_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 512], 40, 'Streak depth',
      'How deep the brush streaks are.'),
    integer('hair_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 512], 20, 'Hairline depth',
      'How deep the hairlines are.'),
    integer('waviness_mm_1024ths', 'relief', 'mm_1024ths', [0, 512], 120, 'Waviness',
      'How far the sheet departs from flat.'),
    integer('tone_spread_q16', 'colour', 'q16', [0, 32768], 900, 'Tone variation',
      'Broad, faint variation in the metal\'s colour.'),
    integer('brush_spread_q16', 'colour', 'q16', [0, 32768], 1300, 'Streak contrast',
      'How much the brush streaks vary in brightness.'),
    integer('hair_spread_q16', 'colour', 'q16', [0, 32768], 700, 'Hairline contrast',
      'How much the hairlines vary in brightness.'),
    integer('roughness_permille', 'finish', 'permille', [0, 1000], 320, 'Roughness',
      'How blurry reflections are, in thousandths.'),
    integer('brush_roughness_spread_q16', 'finish', 'q16', [0, 32768], 4000,
      'Streak roughness', 'How much the streaks vary in roughness.'),
    integer('hair_roughness_spread_q16', 'finish', 'q16', [0, 32768], 1800,
      'Hairline roughness', 'How much the hairlines vary in roughness.'),
    integer('smudge_threshold_q16', 'wear', 'q16', [0, 65535], 47500, 'Handling-mark rarity',
      'Higher means fewer handling marks.'),
    integer('smudge_darkening_percent', 'wear', 'percent', [0, 100], 3, 'Mark darkening',
      'How much darker a handling mark is.'),
    integer('smudge_roughness_q16', 'wear', 'q16', [0, 65536], 3300, 'Mark dullness',
      'How much a handling mark blurs reflections.'),
    integer('smudge_metalness_permille', 'wear', 'permille', [0, 1000], 950, 'Mark film',
      'How metallic the surface still reads under a mark, in thousandths.'),
    ...commonControls({
      heightRangeMm: 1,
      occlusionRadiusMm: 3,
      occlusionDepthMm: 1,
      occlusionStrengthPermille: 150,
    }),
  ],
  constraints: [],
};

function pattern(recipe: Recipe): Pattern {
  const seed = recipe.seed;
  const metal = decode(read.colour(recipe, 'metal_colour'));
  const brushAlong = read.integer(recipe, 'brush_cells_along');
  const brushAcross = read.integer(recipe, 'brush_cells_across');
  const hairAlong = read.integer(recipe, 'hair_cells_along');
  const hairAcross = read.integer(recipe, 'hair_cells_across');
  const surface = read.integer(recipe, 'surface_height_mm_1024ths');
  const brushRelief = read.integer(recipe, 'brush_relief_mm_1024ths');
  const hairRelief = read.integer(recipe, 'hair_relief_mm_1024ths');
  const waviness = read.integer(recipe, 'waviness_mm_1024ths');
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const toneSpread = read.integer(recipe, 'tone_spread_q16');
  const brushSpread = read.integer(recipe, 'brush_spread_q16');
  const hairSpread = read.integer(recipe, 'hair_spread_q16');
  const roughness = permille(read.integer(recipe, 'roughness_permille'));
  const brushRoughness = read.integer(recipe, 'brush_roughness_spread_q16');
  const hairRoughness = read.integer(recipe, 'hair_roughness_spread_q16');
  const smudgeThreshold = read.integer(recipe, 'smudge_threshold_q16');
  const smudgeDarkening = read.integer(recipe, 'smudge_darkening_percent');
  const smudgeRoughness = read.integer(recipe, 'smudge_roughness_q16');
  const smudgeMetalness = permille(read.integer(recipe, 'smudge_metalness_permille'));
  const brushSeed = stream(seed, 1);
  const hairSeed = stream(seed, 2);
  const waveSeed = stream(seed, 3);
  const smudgeSeed = stream(seed, 4);
  const toneSeed = stream(seed, 5);

  return (x, y, out) => {
    // Long streaks along u, and a finer layer of hairlines.
    const brush = fbm(x, y, brushAlong, brushAcross, brushSeed, 2);
    const hair = valueNoise(x, y, hairAlong, hairAcross, hairSeed);
    const wave = fbm(x, y, 3, 3, waveSeed, 2);
    out.height = heightOfLength(
      surface
        + floorDiv((brush - 32768) * brushRelief, 32768)
        + floorDiv((hair - 32768) * hairRelief, 32768)
        + floorDiv((wave - 32768) * waviness, 32768),
      rangeMm,
    );

    // Handling marks: small and faint. A strong broad smudge would repeat down the whole street.
    const smudge = band(fbm(x, y, 16, 16, smudgeSeed, 3), smudgeThreshold, smudgeThreshold + 5000);
    setColour(out, metal);
    shade(out, jitter(fbm(x, y, 5, 5, toneSeed, 2), toneSpread));
    shade(out, jitter(brush, brushSpread));
    shade(out, jitter(hair, hairSpread));
    shade(out, ONE - floorDiv(smudge * smudgeDarkening, 100));

    out.roughness = clamp(
      roughness
        + floorDiv((brush - 32768) * brushRoughness, 32768)
        + floorDiv((hair - 32768) * hairRoughness, 32768)
        + floorDiv(smudge * smudgeRoughness, ONE),
      0,
      FULL,
    );
    out.metalness = lerp(FULL, smudgeMetalness, smudge);
    out.occlusion = ONE;
  };
}

export const metalMaker: Maker = {
  manifest: metalManifest,
  stated(recipe) {
    return {
      finish: `brushed along u, ${read.choice(recipe, 'finish')}`,
      brush_streak_length_mm: floorDiv(recipe.extent_mm.u, read.integer(recipe, 'brush_cells_along')),
      brush_streak_width_mm_1024ths: floorDiv(
        recipe.extent_mm.v * 1024,
        read.integer(recipe, 'brush_cells_across'),
      ),
      surface_height_mm_1024ths: read.integer(recipe, 'surface_height_mm_1024ths'),
    };
  },
  pattern,
};
