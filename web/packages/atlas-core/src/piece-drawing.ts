/**
 * How pieces are drawn: the figures their drawing spends, beside the render budget.
 *
 * A textured piece (`textured-piece.ts`) is drawn instanced: the pieces of one file stand in square
 * cells of the ground, each cell drawn at one level of detail, chosen by its distance from the
 * camera. These are cost figures, the kind a computer that cannot keep its frames in time draws
 * lower, so they are data with a stated default, not constants of the drawing:
 *
 * - `lod1BeyondPerMetre`: a cell draws its second level of detail when the camera stands farther
 *   from it than this many metres for each metre of the tallest piece it holds as placed, so a piece
 *   changes level at about the same size on the screen whatever its own size. At the default 9, a
 *   9 m tree changes at 81 m, about a twelfth of a 70 degree view's height.
 * - `hysteresisPermille`: a cell drawn at one level keeps it until the distance is this share past
 *   the switch, so a camera standing near the switch does not flicker between levels.
 * - `shadowReachM`: a cell casts shadows from its first level only within this distance of the
 *   camera; the second level never casts. Shadows are the costliest part of cut-out leaves.
 * - `cellSizeM`: the side of a cell; each cell is one draw per piece, level and material, culled by
 *   its own bounds in the camera and in each shadow cascade.
 * - `repeatedTrianglesMost`: a palette piece that repeats its bays or storeys to meet a slot
 *   (`repeat_mm`) is baked copy by copy; a slot whose copies would bake more triangles than this
 *   keeps the engine's own primitive, so no box asks the bake for more than a few whole pieces.
 * - `climbShadowReachM`: climbing plants (a look's `climb`) lie flat on their walls, where their own
 *   shadow falls on the wall just behind them; they cast from their first level only within this
 *   distance of the camera, in place of `shadowReachM`.
 *
 * The render budget catalog will state these per scene form (MOTION's version); until it does, a
 * caller passes none and the defaults hold. Pure: no DOM, no renderer.
 */

export interface PieceDrawing {
  readonly lod1BeyondPerMetre: number;
  readonly hysteresisPermille: number;
  readonly shadowReachM: number;
  readonly cellSizeM: number;
  readonly repeatedTrianglesMost: number;
  readonly climbShadowReachM: number;
}

/** Today's figures, each with its reason. */
export const PIECE_DRAWING_DEFAULTS: PieceDrawing = Object.freeze({
  // A 9 m tree at 81 m spans about 8 percent of the view's height, where its second level (a quarter
  // of the triangles, larger and fewer leaf cards) reads as the first does.
  lod1BeyondPerMetre: 9,
  // A tenth past the switch: a camera walking at the switch line steps through it once.
  hysteresisPermille: 100,
  // Within 80 m the cut leaf shadows read under a tree; past it they fall in the far cascades.
  shadowReachM: 80,
  // On a made site with 187 textured trees from 13 piece files, 48 m cells made 141 cells and 770
  // draws at a near view, 128 m 52 cells and 554, 256 m 25 cells and 496 with more triangles near
  // the camera; 128 m holds a site in a few cells and still culls what lies behind the camera.
  cellSizeM: 128,
  // Four structure pieces at their family's budget (20,000 triangles each). A 36 m block of five
  // storeys over a ground storey and nine bays bakes about 4,000; a forty-storey tower about 12,000.
  repeatedTrianglesMost: 80_000,
  // None: on Wall city on 15 October, 282 climbing plants raised the quay view from 2.58 to 4.08
  // million triangles; casting within the trees' 80 m reach was 0.65 million of it and 24 draws, and
  // left out the view's GPU frame fell from 6.05 to 5.37 ms (two runs each), for a shadow lying on
  // the wall a few centimetres behind each leaf.
  climbShadowReachM: 0,
});

/** The range each figure may take. */
export const PIECE_DRAWING_RANGES = Object.freeze({
  lod1BeyondPerMetre: Object.freeze({ least: 2, most: 60 }),
  hysteresisPermille: Object.freeze({ least: 0, most: 500 }),
  shadowReachM: Object.freeze({ least: 0, most: 400 }),
  cellSizeM: Object.freeze({ least: 8, most: 512 }),
  repeatedTrianglesMost: Object.freeze({ least: 0, most: 1_000_000 }),
  climbShadowReachM: Object.freeze({ least: 0, most: 400 }),
});

/**
 * The figures a scene is drawn with: each stated one held to its range, each absent one its default.
 * Refuses an unknown field or a figure out of its range by name.
 */
export function pieceDrawingOf(stated?: Readonly<Partial<Record<keyof PieceDrawing, unknown>>>): PieceDrawing {
  if (stated === undefined) return PIECE_DRAWING_DEFAULTS;
  const out: Record<string, number> = { ...PIECE_DRAWING_DEFAULTS };
  for (const [key, value] of Object.entries(stated)) {
    if (!(key in PIECE_DRAWING_RANGES)) throw new TypeError(`piece drawing: unknown figure ${JSON.stringify(key)}`);
    if (value === undefined) continue;
    const { least, most } = PIECE_DRAWING_RANGES[key as keyof PieceDrawing];
    if (typeof value !== 'number' || !Number.isFinite(value) || value < least || value > most) {
      throw new TypeError(`piece drawing: ${key} is a number from ${least} to ${most}`);
    }
    out[key] = value;
  }
  return Object.freeze(out) as unknown as PieceDrawing;
}
