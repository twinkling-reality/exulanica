import {
  colour,
  commonControls,
  constant,
  equal,
  extent,
  integer,
  lessOrEqual,
  param,
  product,
  sum,
} from '../controls.js';
import { bits16, hash3, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, floorMod, lerp, smoothstep } from '../integer.js';
import type { Maker } from '../maker.js';
import { band, fbm } from '../noise.js';
import { MAKER_PROFILE_V2, type ProceduralMakerManifest, type Recipe, read } from '../recipe.js';
import { type Pattern, heightOfLength, jitter, mixColour, permille, setColour, shade } from '../sample.js';
import { decode } from '../srgb.js';
import { MM, TILE } from '../tile.js';

/**
 * Sign panel: the painted sheet of a shopfront fascia, and nothing written on it.
 *
 * This set is a GROUND, not a sign. A fascia carries a shop's name, and lettering is a record of
 * what that shop is called: it comes from the premises, is laid out by whatever draws the fascia,
 * and is drawn over this. So this surface is deliberately quiet: an even colour, a faint sheen, the
 * joint where one sheet meets the next, and weathering low enough that lettering over it stays
 * legible. A tiling set that carried letters would repeat them along the street, which is why the
 * set holds none.
 *
 * On a vertical surface u runs along the fascia and v down it. Sheets are butted along u, so the
 * joints are vertical lines a whole number of sheets apart, and the tile holds a whole number of
 * sheets by constraint.
 *
 * What the version fixes, each with its reason:
 *
 *   - A joint is a groove with straight sides: its depth rises over half its width to the sheet
 *     face, so the joint reads as a shadow line and not as a bevel.
 *   - The finish is sprayed paint, so its texture is fine and even: two octaves of value noise on
 *     the stated cell, in relief and in tone, which is what orange peel looks like. There is no
 *     brush direction, because a sprayed panel has none.
 *   - Weathering keeps the upper part of broad fractal noise (40000 to 54000, measured), and its
 *     strength is a control whose default is low: a panel that is dirty enough to be interesting on
 *     its own is too dirty to letter.
 *   - The colour varies from sheet to sheet by a hashed amount, because sheets are painted in
 *     batches, and never within a sheet: an even field under lettering is the point.
 *
 * A person sets the colour, the sheets, the joint, the finish and the weathering. Where a
 * particular fascia is dirtiest (its top edge, under a drip) is a fact about that fascia and
 * belongs to its material record, not to this tile.
 */
export const panelManifest: ProceduralMakerManifest = {
  profile: MAKER_PROFILE_V2,
  maker_id: 'loom.panel',
  version: 1,
  kind: 'procedural',
  material_class: 'opaque',
  family: 'panel',
  surface: 'vertical',
  truth: 'invented',
  controls: [
    colour('panel_colour', [42, 46, 54], 'Panel colour', 'The paint on the sheet.'),
    colour('joint_colour', [28, 30, 34], 'Joint colour', 'The shadow line where two sheets meet.'),
    colour('weather_colour', [96, 96, 92], 'Weathering colour',
      'The pale grime that settles on a painted panel.'),
    integer('sheets_across', 'module', 'count', [1, 32], 1, 'Sheets across',
      'How many sheets fit across one tile.'),
    integer('sheet_width_mm', 'module', 'mm', [100, 100000], 1000, 'Sheet width',
      'How wide one sheet is; sheets times width must equal the tile width.'),
    integer('joint_width_mm', 'module', 'mm', [1, 40], 4, 'Joint width',
      'How wide the groove between two sheets is.'),
    integer('joint_depth_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 2048, 'Joint depth',
      'How deep the groove between two sheets is.'),
    integer('finish_cells', 'detail', 'cells_per_tile', [16, 1024], 300, 'Finish size',
      'How many cells of the sprayed finish fit across one tile; more means finer.'),
    integer('finish_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 1024], 260, 'Finish relief',
      'How far the sprayed finish rises and falls.'),
    integer('finish_tone_q16', 'colour', 'q16', [0, 32768], 1600, 'Finish tone',
      'How much the sprayed finish shows as a change of tone.'),
    integer('sheet_variation_q16', 'colour', 'q16', [0, 32768], 1400, 'Sheet variation',
      'How much the paint on one sheet differs in brightness from the next.'),
    integer('weather_percent', 'wear', 'percent', [0, 100], 12, 'Weathering',
      'The most grime lightens the panel, in percent. Low, so lettering over it stays legible.'),
    integer('weather_cells', 'wear', 'cells_per_tile', [1, 64], 6, 'Weathering patches',
      'How many patches of grime fit across one tile; more means smaller patches.'),
    integer('panel_roughness_permille', 'finish', 'permille', [0, 1000], 300, 'Panel roughness',
      'How matte the paint is, in thousandths; a sprayed panel is fairly glossy.'),
    integer('joint_roughness_permille', 'finish', 'permille', [0, 1000], 700, 'Joint roughness',
      'How matte the inside of a joint is, in thousandths.'),
    ...commonControls({
      heightRangeMm: 4,
      occlusionRadiusMm: 4,
      occlusionDepthMm: 1,
      occlusionStrengthPermille: 450,
    }),
  ],
  constraints: [
    equal(product(param('sheets_across'), param('sheet_width_mm')), extent('u'),
      'sheets across times the sheet width must equal the tile width'),
    lessOrEqual(param('joint_width_mm'), param('sheet_width_mm'),
      'a joint is no wider than the sheet it borders'),
    lessOrEqual(
      sum(param('joint_depth_mm_1024ths'), param('finish_relief_mm_1024ths')),
      product(param('height_range_mm'), constant(1024)),
      'the joint and the finish together fit inside the height range',
    ),
  ],
};

/** The broad-noise band weathering keeps, measured as about its upper fifth. */
const WEATHER_LOW = 40000;
const WEATHER_HIGH = 54000;

function pattern(recipe: Recipe): Pattern {
  const seed = recipe.seed;
  const paint = decode(read.colour(recipe, 'panel_colour'));
  const jointColour = decode(read.colour(recipe, 'joint_colour'));
  const weatherColour = decode(read.colour(recipe, 'weather_colour'));
  const sheets = read.integer(recipe, 'sheets_across');
  const jointWidth = read.integer(recipe, 'joint_width_mm');
  const jointDepth = read.integer(recipe, 'joint_depth_mm_1024ths');
  const finishCells = read.integer(recipe, 'finish_cells');
  const finishRelief = read.integer(recipe, 'finish_relief_mm_1024ths');
  const finishTone = read.integer(recipe, 'finish_tone_q16');
  const sheetVariation = read.integer(recipe, 'sheet_variation_q16');
  const weatherPercent = read.integer(recipe, 'weather_percent');
  const weatherCells = read.integer(recipe, 'weather_cells');
  const roughness = permille(read.integer(recipe, 'panel_roughness_permille'));
  const jointRoughness = permille(read.integer(recipe, 'joint_roughness_permille'));
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const finishSeed = stream(seed, 1);
  const weatherSeed = stream(seed, 2);
  const sheetSeed = stream(seed, 3);
  // A sheet's width and half a joint's, in 1/1024 mm.
  const sheetWidth = floorDiv(recipe.extent_mm.u * MM, sheets);
  const halfJoint = Math.max(1, floorDiv(jointWidth * MM, 2));
  // The finish's cells are square: as many down the tile as its extent allows.
  const finishDown = Math.max(1, floorDiv(finishCells * recipe.extent_mm.v, recipe.extent_mm.u));
  const halfSheet = floorDiv(TILE, 2 * sheets);

  return (x, y, out) => {
    // Where this texel sits across its sheet, and how far into the joint beside it.
    // Half a sheet along, so the joint's groove sits inside the tile instead of astride its edge.
    // A V groove centred on the seam has its kink there, and the normal's x flips sign across
    // it: the joints still repeat every sheet width once tiled, just not on the cut.
    const scaled = (x + halfSheet) * sheets;
    const cell = floorDiv(scaled, TILE);
    const sheet = floorMod(cell, sheets);
    const within = floorDiv((scaled - cell * TILE) * sheetWidth, TILE);
    const toJoint = Math.min(within, sheetWidth - within);
    // 0 in the joint, rising to ONE on the sheet's face over half the joint's width.
    const face = smoothstep(0, halfJoint, toJoint);

    const finish = fbm(x, y, finishCells, finishDown, finishSeed, 2);
    out.height = heightOfLength(
      floorDiv(face * jointDepth, ONE) + floorDiv(floorDiv(finish * face, ONE) * finishRelief, FULL),
      rangeMm,
    );

    setColour(out, paint);
    shade(out, jitter(bits16(hash3(sheet, 0, 0, sheetSeed)), sheetVariation));
    shade(out, jitter(finish, finishTone));
    const weather = floorDiv(
      floorDiv(band(fbm(x, y, weatherCells, weatherCells, weatherSeed, 3), WEATHER_LOW, WEATHER_HIGH) * face, ONE)
        * weatherPercent,
      100,
    );
    mixColour(out, weatherColour, weather);
    mixColour(out, jointColour, ONE - face);

    // Matte inside a joint, glossier on the face.
    out.roughness = clamp(lerp(jointRoughness, roughness, face), 0, FULL);
    out.metalness = 0;
    out.occlusion = ONE;
    out.coverage = 0;
    out.transmission = 0;
  };
}

export const panelMaker: Maker = {
  manifest: panelManifest,
  stated(recipe) {
    return {
      panel: 'sprayed sheet panel, no lettering',
      sheet_width_mm: read.integer(recipe, 'sheet_width_mm'),
      joint_width_mm: read.integer(recipe, 'joint_width_mm'),
      joint_depth_mm_1024ths: read.integer(recipe, 'joint_depth_mm_1024ths'),
      finish_cell_mm_1024ths: floorDiv(recipe.extent_mm.u * MM, read.integer(recipe, 'finish_cells')),
    };
  },
  pattern,
};
