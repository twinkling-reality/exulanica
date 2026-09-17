import {
  choice,
  colour,
  commonControls,
  constant,
  extent,
  integer,
  lessOrEqual,
  param,
  product,
  sum,
} from '../controls.js';
import { bits16, hash3, stream } from '../hash.js';
import { FULL, ONE, floorDiv, floorMod, lerp } from '../integer.js';
import type { Maker } from '../maker.js';
import { band, fbm, valueNoise } from '../noise.js';
import { MAKER_PROFILE_V2, type ProceduralMakerManifest, type Recipe, read } from '../recipe.js';
import { type Pattern, heightOfLength, jitter, mixColour, permille, setColour, shade } from '../sample.js';
import { decode } from '../srgb.js';
import { MM, TILE } from '../tile.js';

/**
 * Painted timber: the painted wood of shopfront doors, frames and stall boards.
 *
 * The grain runs down the tile, along v. A surface whose timber runs across turns the set with its
 * material record's UV rotation, so one set dresses a stile and a rail alike. Paint is a film over
 * primer over wood: where the film is chipped the primer shows, and where a chip goes deeper, the
 * wood. The grain telegraphs through the paint as faint relief, and the brush leaves finer marks
 * along the grain.
 *
 * What the version fixes, each with its reason:
 *
 *   - A joint between boards is a V-groove: its depth falls linearly to the joint's centre line, so a
 *     joint catches light on one side and shades on the other.
 *   - A chip keeps a band 3000 wide of broad fractal noise above the stated rarity: narrow, so a
 *     chip has a crisp edge and the paint is either whole or chipped. Whether a chip reaches the wood
 *     is decided by a second field with the same narrow band, so a chip is mostly primer or mostly
 *     wood rather than a blend of the two.
 *   - Chips gather in patches, and only inside them: a broad field keeps the upper part of its
 *     range (38000 to 52000, measured), and a chip appears where that patch field allows it. Paint
 *     fails where something rubs it, so chipping in patches with clean paint between them reads as
 *     wear, where the same share of chipping spread evenly over the whole surface reads as
 *     speckle. Where a surface is rubbed is a fact about the surface, not about the tile, so how
 *     worn one is belongs to its material record, never here.
 *   - Grime shows at full strength in a joint, where dirt lodges first, and on a face where broad
 *     fractal noise lies in its upper half (30000 to 50000, from about its median to beyond its
 *     ninetieth percentile, measured), so it gathers in patches rather than as an even film.
 *
 * A person sets the colours, whether the timber is boarded and how, the grain and the brush marks,
 * the paint's thickness, the chipping and the grime, and how glossy the paint is.
 */
const BOARDED = { param: 'boards', equals: 'boarded' };

export const timberManifest: ProceduralMakerManifest = {
  profile: MAKER_PROFILE_V2,
  maker_id: 'loom.timber',
  version: 1,
  kind: 'procedural',
  material_class: 'opaque',
  family: 'timber',
  surface: 'vertical',
  truth: 'invented',
  controls: [
    colour('paint_colour', [48, 78, 62], 'Paint colour', 'The top coat.'),
    colour('primer_colour', [178, 172, 160], 'Primer colour',
      'The coat under the paint, where the paint has chipped.'),
    colour('wood_colour', [142, 108, 72], 'Wood colour', 'Bare timber, where a chip goes through the primer.'),
    colour('grime_colour', [58, 54, 48], 'Grime colour', 'The dirt that gathers in joints and on the face.'),
    choice('boards', 'module', ['plain', 'boarded'], 'plain', 'Boards',
      'Plain timber, or boards side by side with a V-groove between each two.'),
    integer('boards_across', 'module', 'cells_per_tile', [1, 64], 10, 'Boards across',
      'How many boards fit across one tile, when the timber is boarded.'),
    integer('joint_width_mm', 'module', 'mm', [1, 20], 5, 'Joint width',
      'How wide the V-groove between two boards is.'),
    integer('joint_depth_mm_1024ths', 'relief', 'mm_1024ths', [0, 8192], 2048, 'Joint depth',
      'How deep the V-groove between two boards is.'),
    integer('grain_cells_across', 'detail', 'cells_per_tile', [16, 1024], 220, 'Grain fineness',
      'How many grain lines fit across one tile.'),
    integer('grain_cells_down', 'detail', 'cells_per_tile', [1, 64], 5, 'Grain length',
      'How many grain streak lengths fit down one tile; fewer means longer streaks.'),
    integer('grain_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 1024], 300, 'Grain relief',
      'How far the grain shows through the paint as relief.'),
    integer('grain_tone_q16', 'colour', 'q16', [0, 32768], 5200, 'Grain tone',
      'How much the grain under the paint shows as a change of tone.'),
    integer('brush_cells_across', 'detail', 'cells_per_tile', [32, 1024], 500, 'Brush mark fineness',
      'How many brush marks fit across one tile.'),
    integer('brush_cells_down', 'detail', 'cells_per_tile', [1, 128], 14, 'Brush mark length',
      'How many brush mark lengths fit down one tile.'),
    integer('brush_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 512], 90, 'Brush marks',
      'How deep the brush marks in the paint are.'),
    integer('brush_tone_q16', 'colour', 'q16', [0, 32768], 2600, 'Brush tone',
      'How much a brush mark shows as a change of tone.'),
    integer('paint_depth_mm_1024ths', 'relief', 'mm_1024ths', [0, 2048], 300, 'Paint thickness',
      'How thick the paint and primer are together, which is how deep a chip is.'),
    integer('chip_rarity_q16', 'wear', 'q16', [0, 80000], 50000, 'Chip rarity',
      'Higher means fewer chips in the paint.'),
    integer('chip_cells', 'wear', 'cells_per_tile', [4, 512], 26, 'Chip size',
      'How many chip-sized cells fit across one tile; more means smaller chips.'),
    integer('chip_patch_cells', 'wear', 'cells_per_tile', [1, 64], 9, 'Chip patches',
      'How many patches of chipped paint fit across one tile; more means smaller patches.'),
    integer('bare_wood_rarity_q16', 'wear', 'q16', [0, 80000], 47000, 'Bare wood rarity',
      'Higher means fewer chips go through the primer to the wood.'),
    integer('grime_percent', 'wear', 'percent', [0, 100], 12, 'Grime',
      'The most grime darkens the timber, in percent.'),
    integer('grime_cells', 'wear', 'cells_per_tile', [1, 64], 6, 'Grime patches',
      'How many patches of grime fit across one tile; more means smaller patches.'),
    integer('board_variation_q16', 'colour', 'q16', [0, 32768], 1200, 'Board variation',
      'How much the paint on one board differs in brightness from the next.'),
    integer('paint_roughness_permille', 'finish', 'permille', [0, 1000], 380, 'Paint roughness',
      'How matte the paint is, in thousandths; gloss paint is low.'),
    integer('chip_roughness_permille', 'finish', 'permille', [0, 1000], 820, 'Chip roughness',
      'How matte primer and bare wood are, in thousandths.'),
    ...commonControls({
      heightRangeMm: 4,
      occlusionRadiusMm: 4,
      occlusionDepthMm: 1,
      occlusionStrengthPermille: 400,
    }),
  ],
  constraints: [
    lessOrEqual(
      sum(
        param('joint_depth_mm_1024ths'),
        param('paint_depth_mm_1024ths'),
        param('grain_relief_mm_1024ths'),
        param('brush_relief_mm_1024ths'),
      ),
      product(param('height_range_mm'), constant(1024)),
      'the deepest joint, the paint and all the relief fit inside the height range',
    ),
    lessOrEqual(product(param('joint_width_mm'), param('boards_across')), extent('u'),
      'a joint is no wider than its board', BOARDED),
  ],
};

/** How wide the band of noise is that makes a chip's edge, in the field's own units. */
const CHIP_EDGE = 3000;
/** The broad-noise band a chipped patch keeps, measured as about its upper third. */
const PATCH_LOW = 36000;
const PATCH_HIGH = 54000;
/** The broad-noise band grime keeps on a face, measured as from about its median upward. */
const GRIME_LOW = 30000;
const GRIME_HIGH = 50000;

function pattern(recipe: Recipe): Pattern {
  const seed = recipe.seed;
  const paint = decode(read.colour(recipe, 'paint_colour'));
  const primer = decode(read.colour(recipe, 'primer_colour'));
  const woodColour = decode(read.colour(recipe, 'wood_colour'));
  const grimeColour = decode(read.colour(recipe, 'grime_colour'));
  const boarded = read.choice(recipe, 'boards') === 'boarded';
  const boardsAcross = read.integer(recipe, 'boards_across');
  const jointWidth = read.integer(recipe, 'joint_width_mm');
  const jointDepth = boarded ? read.integer(recipe, 'joint_depth_mm_1024ths') : 0;
  const grainAcross = read.integer(recipe, 'grain_cells_across');
  const grainDown = read.integer(recipe, 'grain_cells_down');
  const grainRelief = read.integer(recipe, 'grain_relief_mm_1024ths');
  const grainTone = read.integer(recipe, 'grain_tone_q16');
  const brushAcross = read.integer(recipe, 'brush_cells_across');
  const brushDown = read.integer(recipe, 'brush_cells_down');
  const brushRelief = read.integer(recipe, 'brush_relief_mm_1024ths');
  const brushTone = read.integer(recipe, 'brush_tone_q16');
  const paintDepth = read.integer(recipe, 'paint_depth_mm_1024ths');
  const chipRarity = read.integer(recipe, 'chip_rarity_q16');
  const chipCells = read.integer(recipe, 'chip_cells');
  const patchCells = read.integer(recipe, 'chip_patch_cells');
  const woodRarity = read.integer(recipe, 'bare_wood_rarity_q16');
  const grimePercent = read.integer(recipe, 'grime_percent');
  const grimeCells = read.integer(recipe, 'grime_cells');
  const boardVariation = read.integer(recipe, 'board_variation_q16');
  const paintRoughness = permille(read.integer(recipe, 'paint_roughness_permille'));
  const chipRoughness = permille(read.integer(recipe, 'chip_roughness_permille'));
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const grainSeed = stream(seed, 1);
  const brushSeed = stream(seed, 2);
  const chipSeed = stream(seed, 3);
  const woodSeed = stream(seed, 4);
  const grimeSeed = stream(seed, 5);
  const patchSeed = stream(seed, 7);
  const boardSeed = stream(seed, 6);

  // A board's width, and half a joint's, in 1/1024 mm.
  const boardWidth = floorDiv(recipe.extent_mm.u * MM, boardsAcross);
  const halfJoint = Math.max(1, floorDiv(jointWidth * MM, 2));

  return (x, y, out) => {
    // 0 on a board's face, rising linearly to ONE on the centre line of a joint.
    let joint = 0;
    let board = 0;
    if (boarded) {
      const scaled = x * boardsAcross;
      const cell = floorDiv(scaled, TILE);
      board = floorMod(cell, boardsAcross);
      const within = floorDiv((scaled - cell * TILE) * boardWidth, TILE);
      const toJoint = Math.min(within, boardWidth - within);
      joint = toJoint >= halfJoint ? 0 : ONE - floorDiv(toJoint * ONE, halfJoint);
    }
    const grain = fbm(x, y, grainAcross, grainDown, grainSeed, 3);
    const brush = valueNoise(x, y, brushAcross, brushDown, brushSeed);
    // Where the paint is rubbed at all, and then where it has actually chipped.
    const patch = band(fbm(x, y, patchCells, patchCells, patchSeed, 3), PATCH_LOW, PATCH_HIGH);
    const chip = floorDiv(
      band(fbm(x, y, chipCells, chipCells, chipSeed, 3), chipRarity, chipRarity + CHIP_EDGE) * patch,
      ONE,
    );
    const wood = floorDiv(
      chip * band(fbm(x, y, chipCells, chipCells, woodSeed, 2), woodRarity, woodRarity + CHIP_EDGE),
      ONE,
    );
    const whole = ONE - chip;
    out.height = heightOfLength(
      jointDepth - floorDiv(joint * jointDepth, ONE)
        + floorDiv(grain * grainRelief, FULL)
        + floorDiv(whole * paintDepth, ONE)
        + floorDiv(floorDiv(brush * whole, ONE) * brushRelief, FULL),
      rangeMm,
    );

    setColour(out, paint);
    if (boarded) shade(out, jitter(bits16(hash3(board, 0, 0, boardSeed)), boardVariation));
    // The grain and the brush show in the paint's tone as well as in its relief.
    shade(out, jitter(grain, grainTone));
    shade(out, jitter(brush, brushTone));
    mixColour(out, primer, chip);
    mixColour(out, woodColour, wood);
    const grime = Math.max(joint, band(fbm(x, y, grimeCells, grimeCells, grimeSeed, 3), GRIME_LOW, GRIME_HIGH));
    mixColour(out, grimeColour, floorDiv(grime * grimePercent, 100));

    out.roughness = lerp(paintRoughness, chipRoughness, chip);
    out.metalness = 0;
    out.occlusion = ONE;
    out.coverage = 0;
    out.transmission = 0;
  };
}

export const timberMaker: Maker = {
  manifest: timberManifest,
  stated(recipe) {
    const boarded = read.choice(recipe, 'boards') === 'boarded';
    const { u } = recipe.extent_mm;
    return {
      timber: boarded ? 'boarded timber, painted' : 'plain timber, painted',
      grain: 'along v',
      ...(boarded
        ? {
          board_width_mm: floorDiv(u, read.integer(recipe, 'boards_across')),
          joint_width_mm: read.integer(recipe, 'joint_width_mm'),
        }
        : {}),
      chip_cell_mm: floorDiv(u, read.integer(recipe, 'chip_cells')),
    };
  },
  pattern,
};
