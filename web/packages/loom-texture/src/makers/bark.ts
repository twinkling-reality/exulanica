import {
  colour,
  commonControls,
  constant,
  integer,
  lessOrEqual,
  palette,
  param,
  product,
  sum,
} from '../controls.js';
import { bits16, pick, stream } from '../hash.js';
import { FULL, ONE, clamp, floorDiv, smoothstep } from '../integer.js';
import type { Maker } from '../maker.js';
import { type CellSample, band, cells, fbm, valueNoise } from '../noise.js';
import { MAKER_PROFILE_V2, type ProceduralMakerManifest, type Recipe, read } from '../recipe.js';
import { type Pattern, heightOfLength, jitter, mixColour, permille, setColour, shade } from '../sample.js';
import { decode } from '../srgb.js';
import { MM, TILE } from '../tile.js';

/**
 * Bark: the furrowed bark of a mature broadleaf street tree's trunk.
 *
 * On a vertical surface u runs around the trunk and v down it. Bark splits as a trunk grows wider,
 * so its furrows run along the trunk and its plates are longer than they are wide. The plates are
 * the cells of a cellular field whose cells are longer down the tile than across it, and the furrows
 * are where two cells meet. A broad field shifts the whole network sideways by up to the stated
 * sway, so furrows wander and meet at shallow angles, the way the ridges of real bark interlace,
 * rather than running as straight grooves. Each column of plates sways on its own: the sway field
 * has as many cells across the tile as there are plates. A second network, of cells wider than they
 * are long, crosses the plates with shallow cracks that break them into blocks.
 *
 * What the version fixes, each with its reason:
 *
 *   - A furrow's profile: a floor as wide as its two walls together, and walls that rise smoothly
 *     to a plate's top, so a furrow is a narrow channel with steep sides and a plate is not a
 *     dome. A crack is a groove over its own width.
 *   - Where a furrow's depth varies, it varies along the trunk: the depth field has the plates' own
 *     cells, so a furrow is shallower beside one plate and deeper beside the next. Plate tops stay
 *     level and only the floor moves, and a shallow furrow is less dark than a deep one.
 *   - A furrow's width is measured across the trunk and a crack's down it. The cellular field
 *     measures distance in cells, so a furrow running straight along the trunk, or a crack straight
 *     around it, has the stated width, and one at a slant is wider.
 *   - A crack cuts into a plate by a share of the furrow depth, so it is never deeper than a
 *     furrow, and bark darkens toward the furrow colour by how deep it lies below a plate face.
 *   - A plate's top carries fibrous relief, two octaves of fractal noise, only on the plate. Its
 *     cells are stretched down the trunk as the plates are, because both come from the trunk
 *     splitting as it widens, so the texture runs in fibres along the trunk.
 *   - Lichen keeps the top of broad fractal noise (40000 to 52000, about its upper fifth, measured)
 *     and grows only on plate faces, never in a furrow.
 *
 * A person sets the colours, the plates' size, the furrows' width and depth, how far the furrows
 * sway, the cracks, the lichen, how much plates differ in tone, and how rough the bark is.
 */
export const barkManifest: ProceduralMakerManifest = {
  profile: MAKER_PROFILE_V2,
  maker_id: 'loom.bark',
  version: 1,
  kind: 'procedural',
  material_class: 'opaque',
  family: 'bark',
  surface: 'vertical',
  truth: 'invented',
  controls: [
    palette('plate_colours', [
      [116, 108, 98],
      [102, 94, 86],
      [128, 120, 110],
      [94, 88, 82],
    ], [1, 16], 'Plate colours', 'Each plate of bark takes one of these tones.'),
    colour('furrow_colour', [54, 46, 40], 'Furrow colour', 'The darker bark deep in a furrow.'),
    colour('lichen_colour', [132, 138, 108], 'Lichen colour', 'The pale green-grey of lichen on the plates.'),
    integer('plate_cells_across', 'module', 'cells_per_tile', [2, 128], 16, 'Plates across',
      'How many plates fit across one tile, around the trunk.'),
    integer('plate_cells_down', 'module', 'cells_per_tile', [1, 64], 2, 'Plates down',
      'How many plate lengths fit down one tile, along the trunk.'),
    integer('furrow_width_mm', 'module', 'mm', [1, 60], 8, 'Furrow width',
      'How wide a furrow is, measured across the trunk.'),
    integer('furrow_depth_mm', 'relief', 'mm', [0, 48], 12, 'Furrow depth',
      'How far the deepest furrow sinks below the plates beside it.'),
    integer('furrow_depth_variation_percent', 'relief', 'percent', [0, 100], 60, 'Furrow depth variation',
      'How much shallower a furrow can be in places than the deepest, as a share of the furrow depth.'),
    integer('sway_mm', 'module', 'mm', [0, 200], 30, 'Furrow sway',
      'How far a furrow wanders sideways as it runs down the trunk.'),
    integer('sway_cells', 'detail', 'cells_per_tile', [1, 32], 3, 'Sway length',
      'How many sideways wanders fit down one tile; more means tighter wanders.'),
    integer('crack_cells_across', 'detail', 'cells_per_tile', [1, 64], 6, 'Crack length',
      'How many crack lengths fit across one tile; more means shorter cracks.'),
    integer('crack_cells_down', 'detail', 'cells_per_tile', [1, 128], 8, 'Cracks down',
      'How many cracks fit down one tile.'),
    integer('crack_width_mm', 'module', 'mm', [1, 60], 8, 'Crack width',
      'How wide a crack is, measured down the trunk.'),
    integer('crack_depth_percent', 'relief', 'percent', [0, 100], 20, 'Crack depth',
      'How deep a crack cuts into a plate, as a share of the furrow depth.'),
    integer('plate_relief_mm_1024ths', 'relief', 'mm_1024ths', [0, 4096], 3072, 'Plate texture',
      'How far the fine texture on a plate face rises and falls.'),
    integer('plate_texture_cells', 'detail', 'cells_per_tile', [4, 512], 160, 'Plate texture size',
      'How many bumps of the fine texture fit across one tile; more means finer texture.'),
    integer('plate_variation_q16', 'colour', 'q16', [0, 32768], 4000, 'Plate variation',
      'How much one plate differs in brightness from the next.'),
    integer('lichen_percent', 'wear', 'percent', [0, 100], 25, 'Lichen',
      'How completely lichen covers a plate where it grows, in percent.'),
    integer('lichen_cells', 'detail', 'cells_per_tile', [1, 64], 7, 'Lichen patches',
      'How many patches of lichen fit across one tile; more means smaller patches.'),
    integer('bark_roughness_permille', 'finish', 'permille', [0, 1000], 900, 'Bark roughness',
      'How matte the bark is, in thousandths.'),
    ...commonControls({
      heightRangeMm: 20,
      occlusionRadiusMm: 10,
      occlusionDepthMm: 6,
      occlusionStrengthPermille: 650,
    }),
  ],
  constraints: [
    lessOrEqual(
      sum(product(param('furrow_depth_mm'), constant(1024)), param('plate_relief_mm_1024ths')),
      product(param('height_range_mm'), constant(1024)),
      'a plate face, texture and all, stays inside the height range above the deepest furrow',
    ),
  ],
};

/** The broad-noise band lichen keeps, measured as about its upper fifth. */
const LICHEN_LOW = 40000;
const LICHEN_HIGH = 52000;

function pattern(recipe: Recipe): Pattern {
  const seed = recipe.seed;
  const plateColours = read.palette(recipe, 'plate_colours').map(decode);
  const furrowColour = decode(read.colour(recipe, 'furrow_colour'));
  const lichenColour = decode(read.colour(recipe, 'lichen_colour'));
  const platesAcross = read.integer(recipe, 'plate_cells_across');
  const platesDown = read.integer(recipe, 'plate_cells_down');
  const furrowWidth = read.integer(recipe, 'furrow_width_mm');
  const furrowDepth = read.integer(recipe, 'furrow_depth_mm') * MM;
  const depthVariation = read.integer(recipe, 'furrow_depth_variation_percent');
  const swayMm = read.integer(recipe, 'sway_mm');
  const swayCells = read.integer(recipe, 'sway_cells');
  const cracksAcross = read.integer(recipe, 'crack_cells_across');
  const cracksDown = read.integer(recipe, 'crack_cells_down');
  const crackWidth = read.integer(recipe, 'crack_width_mm');
  const crackPercent = read.integer(recipe, 'crack_depth_percent');
  const crackDepth = floorDiv(furrowDepth * crackPercent, 100);
  const plateRelief = read.integer(recipe, 'plate_relief_mm_1024ths');
  const textureAcross = read.integer(recipe, 'plate_texture_cells');
  const variation = read.integer(recipe, 'plate_variation_q16');
  const lichenPercent = read.integer(recipe, 'lichen_percent');
  const lichenCells = read.integer(recipe, 'lichen_cells');
  const roughness = permille(read.integer(recipe, 'bark_roughness_permille'));
  const rangeMm = read.integer(recipe, 'height_range_mm');
  const { u: extentU, v: extentV } = recipe.extent_mm;
  // The fine texture's cells have the plates' proportions, as many down the tile as that allows.
  const textureDown = Math.max(1, floorDiv(textureAcross * platesDown, platesAcross));
  const plateSeed = stream(seed, 1);
  const swaySeed = stream(seed, 2);
  const crackSeed = stream(seed, 3);
  const reliefSeed = stream(seed, 4);
  const lichenSeed = stream(seed, 5);
  const depthSeed = stream(seed, 6);

  // Widths in cells across (Q16), and the sway in tile micro-units along u.
  const furrowCells = Math.max(1, floorDiv(furrowWidth * platesAcross * ONE, extentU));
  const crackCells = Math.max(1, floorDiv(crackWidth * cracksDown * ONE, extentV));
  const sway = floorDiv(swayMm * TILE, extentU);
  const plates: CellSample = { nearest: 0, second: 0, id: 0 };
  const cracks: CellSample = { nearest: 0, second: 0, id: 0 };

  return (x, y, out) => {
    const shift = floorDiv((fbm(x, y, platesAcross, swayCells, swaySeed, 2) - 32768) * sway, 32768);
    cells(x + shift, y, platesAcross, platesDown, plateSeed, ONE, plates);
    // 0 across a furrow's floor, rising up its wall to ONE on the flat top of a plate.
    const face = smoothstep(floorDiv(furrowCells, 2), furrowCells, plates.second - plates.nearest);

    cells(x + shift, y, cracksAcross, cracksDown, crackSeed, ONE, cracks);
    const crack = ONE - smoothstep(0, crackCells, cracks.second - cracks.nearest);

    // How deep the furrow is here: the full depth, less up to the stated variation.
    const deep = furrowDepth - floorDiv(
      floorDiv(valueNoise(x + shift, y, platesAcross, platesDown, depthSeed) * depthVariation, 100) * furrowDepth,
      FULL,
    );
    const groove = floorDiv((ONE - face) * deep, ONE);
    const relief = fbm(x, y, textureAcross, textureDown, reliefSeed, 2);
    const cracked = floorDiv(crack * face, ONE);
    const length = furrowDepth - groove
      - floorDiv(cracked * crackDepth, ONE)
      + floorDiv(floorDiv(relief * face, ONE) * plateRelief, FULL);
    out.height = heightOfLength(clamp(length, 0, rangeMm * MM), rangeMm);

    setColour(out, plateColours[pick(plates.id, 0, plateColours.length - 1)]!);
    shade(out, jitter(bits16(plates.id), variation));
    const lichen = floorDiv(
      floorDiv(band(fbm(x, y, lichenCells, lichenCells, lichenSeed, 3), LICHEN_LOW, LICHEN_HIGH) * face, ONE)
        * lichenPercent,
      100,
    );
    mixColour(out, lichenColour, lichen);
    // Darker the deeper below a plate's top: all the way at the floor of the deepest furrow, a
    // shallower furrow's share of that, and a crack's share in a crack.
    mixColour(
      out,
      furrowColour,
      clamp(floorDiv(groove * ONE, Math.max(1, furrowDepth)) + floorDiv(cracked * crackPercent, 100), 0, ONE),
    );

    out.roughness = roughness;
    out.metalness = 0;
    out.occlusion = ONE;
    out.coverage = 0;
    out.transmission = 0;
  };
}

export const barkMaker: Maker = {
  manifest: barkManifest,
  stated(recipe) {
    const { u, v } = recipe.extent_mm;
    return {
      bark: 'furrowed broadleaf bark',
      plate_width_mm: floorDiv(u, read.integer(recipe, 'plate_cells_across')),
      plate_length_mm: floorDiv(v, read.integer(recipe, 'plate_cells_down')),
      furrow_width_mm: read.integer(recipe, 'furrow_width_mm'),
      furrow_depth_mm: read.integer(recipe, 'furrow_depth_mm'),
      crack_spacing_mm: floorDiv(v, read.integer(recipe, 'crack_cells_down')),
      crack_width_mm: read.integer(recipe, 'crack_width_mm'),
    };
  },
  pattern,
};
