/**
 * The layout rule: one line of text in one catalog, placed in integer millimetres, or refused.
 *
 * The TypeScript copy of `exulanica.lettering.layout`. `docs/lettering.md` states the rule once;
 * the shared cases hold the two copies to the same placements and the same refusals.
 *
 * With `C` the catalog's cap height in font units and `H` the cap height in millimetres:
 *
 * - `scale(v) = floor((2 v H + C) / (2 C))`: nearest, halves toward +infinity, which keeps two
 *   points a millimetre apart on either side of zero apart.
 * - The pen advances in exact font units: `pen[0] = 0`, `pen[i + 1] = pen[i] + advance(c[i]) +
 *   kern(c[i], c[i + 1])`. Character `i`'s origin is `scale(pen[i]) + i * tracking`, and its
 *   outline is scaled relative to that origin, so every copy of a letter at one size is the same
 *   geometry.
 * - `left` puts the ink's left edge at 0; `centre` puts it at `floor((width - ink width) / 2)`.
 *   The baseline sits at `floor((height - H) / 2)`, centring the cap height as a sign writer sets
 *   capitals, with descenders below.
 */
import type { GlyphCatalog } from './catalog.js';
import { type Part, type Point, type Ring, glyphsTouch } from './geometry.js';
import { refuse } from './refusal.js';

export const ALIGNMENTS = ['left', 'centre'] as const;
export type Alignment = (typeof ALIGNMENTS)[number];

export interface Placement {
  /** The character's position in the text. */
  readonly index: number;
  readonly character: string;
  /** The glyph origin, in box millimetres. */
  readonly xMm: number;
  readonly baselineMm: number;
}

export interface InkBox {
  readonly leftMm: number;
  readonly bottomMm: number;
  readonly rightMm: number;
  readonly topMm: number;
}

export interface SignRequest {
  readonly text: string;
  readonly capHeightMm: number;
  readonly trackingMm: number;
  readonly alignment: string;
  readonly boxWidthMm: number;
  readonly boxHeightMm: number;
}

export interface SignLayout extends SignRequest {
  readonly catalogId: string;
  readonly catalogVersion: number;
  readonly alignment: Alignment;
  /** One per non-space character, in text order. */
  readonly placements: readonly Placement[];
  readonly ink: InkBox;
}

const isInteger = (value: unknown): boolean => typeof value === 'number' && Number.isSafeInteger(value);

/** The floor of `a / b` for a positive `b`, with no float division. */
function floorDivide(a: number, b: number): number {
  const remainder = a % b;
  const truncated = (a - remainder) / b;
  return remainder < 0 ? truncated - 1 : truncated;
}

/** Font units to whole millimetres: nearest, halves toward +infinity. */
export function scaleToMm(value: number, capHeightMm: number, capHeight: number): number {
  return floorDivide(2 * value * capHeightMm + capHeight, 2 * capHeight);
}

function scaleRing(ring: Ring, capHeightMm: number, capHeight: number, dx: number, dy: number): Ring {
  return ring.map(
    (point): Point => [
      scaleToMm(point[0], capHeightMm, capHeight) + dx,
      scaleToMm(point[1], capHeightMm, capHeight) + dy,
    ],
  );
}

/** A glyph's parts in millimetres relative to its origin on the baseline, at a cap height. */
export function glyphPartsMm(
  catalog: GlyphCatalog,
  character: string,
  capHeightMm: number,
  dx = 0,
  dy = 0,
): readonly Part[] {
  const glyph = catalog.glyphs.get(character);
  if (glyph === undefined) {
    refuse('character', `U+${character.codePointAt(0)!.toString(16).toUpperCase().padStart(4, '0')} `
      + `'${character}' is not in ${catalog.catalogId} v${catalog.catalogVersion}`);
  }
  return glyph.parts.map((part) => ({
    outer: scaleRing(part.outer, capHeightMm, catalog.capHeight, dx, dy),
    holes: part.holes.map((hole) => scaleRing(hole, capHeightMm, catalog.capHeight, dx, dy)),
  }));
}

/** Where each letter of `text` goes in the box, or a `LetteringRefusal`. */
export function layoutSign(catalog: GlyphCatalog, request: SignRequest): SignLayout {
  const { text, capHeightMm, trackingMm, alignment, boxWidthMm, boxHeightMm } = request;
  if (!(ALIGNMENTS as readonly string[]).includes(alignment)) {
    refuse('alignment', `${JSON.stringify(alignment)} is not one of ${JSON.stringify(ALIGNMENTS)}`);
  }
  const low = catalog.minimumCapHeightMm;
  const high = catalog.maximumCapHeightMm;
  if (!isInteger(capHeightMm) || capHeightMm < low || capHeightMm > high) {
    refuse(
      'cap_height',
      `${JSON.stringify(capHeightMm) ?? String(capHeightMm)} mm is outside ${catalog.catalogId} `
        + `v${catalog.catalogVersion}'s promise of ${low} to ${high} mm`,
    );
  }
  if (!isInteger(trackingMm) || trackingMm < 0) {
    refuse('tracking', `${JSON.stringify(trackingMm) ?? String(trackingMm)} is not an integer of zero or more`);
  }
  for (const [name, value] of [['width', boxWidthMm], ['height', boxHeightMm]] as const) {
    if (!isInteger(value) || value < 1) {
      refuse('box', `the box ${name} ${JSON.stringify(value) ?? String(value)} is not an integer of 1 or more`);
    }
  }
  if (
    typeof text !== 'string'
    || text.length === 0
    || text.startsWith(' ')
    || text.endsWith(' ')
    || text.includes('  ')
  ) {
    refuse('text', `${JSON.stringify(text) ?? String(text)} is empty, starts or ends with a space, or has two together`);
  }
  const characters = [...text];
  for (const character of characters) {
    if (!catalog.glyphs.has(character)) {
      refuse(
        'character',
        `U+${character.codePointAt(0)!.toString(16).toUpperCase().padStart(4, '0')} '${character}' `
          + `is not in ${catalog.catalogId} v${catalog.catalogVersion}`,
      );
    }
  }

  const origins: number[] = [];
  let pen = 0;
  characters.forEach((character, index) => {
    origins.push(scaleToMm(pen, capHeightMm, catalog.capHeight) + index * trackingMm);
    pen += catalog.glyphs.get(character)!.advance;
    if (index + 1 < characters.length) {
      pen += catalog.kerning.get(character + characters[index + 1]!) ?? 0;
    }
  });

  const inked = characters
    .map((_character, index) => index)
    .filter((index) => catalog.glyphs.get(characters[index]!)!.parts.length > 0);
  const unplaced = inked.map((index) =>
    glyphPartsMm(catalog, characters[index]!, capHeightMm, origins[index]!, 0),
  );
  const xs = unplaced.flatMap((parts) => parts.flatMap((part) => part.outer.map((point) => point[0])));
  const ys = unplaced.flatMap((parts) => parts.flatMap((part) => part.outer.map((point) => point[1])));
  const left = Math.min(...xs);
  const right = Math.max(...xs);
  const bottom = Math.min(...ys);
  const top = Math.max(...ys);
  const width = right - left;
  const offset = alignment === 'left' ? -left : floorDivide(boxWidthMm - width, 2) - left;
  const baseline = floorDivide(boxHeightMm - capHeightMm, 2);
  if (width > boxWidthMm || baseline + bottom < 0 || baseline + top > boxHeightMm) {
    refuse(
      'fit',
      `${JSON.stringify(text)} inks ${width} by ${top - bottom} mm with the cap height centred, `
        + `which does not fit a ${boxWidthMm} by ${boxHeightMm} mm box`,
    );
  }

  const placed = inked.map((index) =>
    glyphPartsMm(catalog, characters[index]!, capHeightMm, origins[index]! + offset, baseline),
  );
  for (let first = 0; first < inked.length; first += 1) {
    for (let second = first + 1; second < inked.length; second += 1) {
      if (glyphsTouch(placed[first]!, placed[second]!)) {
        refuse(
          'touch',
          `'${characters[inked[first]!]!}' at ${inked[first]!} and '${characters[inked[second]!]!}' at `
            + `${inked[second]!} share a point at ${capHeightMm} mm with tracking ${trackingMm} mm`,
        );
      }
    }
  }

  return {
    ...request,
    alignment: alignment as Alignment,
    catalogId: catalog.catalogId,
    catalogVersion: catalog.catalogVersion,
    placements: inked.map((index) => ({
      index,
      character: characters[index]!,
      xMm: origins[index]! + offset,
      baselineMm: baseline,
    })),
    ink: {
      leftMm: left + offset,
      bottomMm: bottom + baseline,
      rightMm: right + offset,
      topMm: top + baseline,
    },
  };
}
