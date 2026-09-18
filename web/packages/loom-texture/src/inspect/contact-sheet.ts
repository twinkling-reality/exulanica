import { SET_PROFILE_V1 } from '../classes.js';
import { readContainer } from '../container.js';
import { isqrt } from '../integer.js';
import type { Publication } from '../publish.js';
import { SRGB_TO_LINEAR, encodeChannel } from '../srgb.js';
import type { RgbImage } from './png.js';

/**
 * Pictures of the baked sets, for a person to look at.
 *
 * These are NOT the product. The shading below is a fixed light over the stored maps, written to
 * make a wrong normal or a seam visible, and it says nothing about how the corridor renderer will
 * draw a set. Everything here reads the published containers through the strict decoder, so the
 * pictures are of the bytes that were pinned and not of an in-memory bake.
 *
 * Contact sheet rows follow the manifest's order. Columns, left to right:
 *   1. base colour, 2 tiles across, 1/8 scale
 *   2. lit preview, 2 tiles across, 1/8 scale
 *   3. normal map, one tile across, 1/4 scale
 *   4. occlusion, roughness, metalness as RGB, one tile across, 1/4 scale
 *   5. the channel the class leaves over as grey, one tile across, 1/4 scale: a v1 set's height, a
 *      glazing set's transmission, a cutout's or a decal's coverage, and nothing for an opaque v2
 *      set, which stores none of those
 *   6. base colour at full scale, 256 x 256 around the corner where four tiles meet
 *   7. lit preview at full scale around the same corner
 *
 * Every cell is square. A set whose tile is not (cc0.kerb-stone is 4 to 1, the road paint too) is
 * repeated more often down its cell than across it, at the same scale on both axes, so the cell is
 * filled without the picture stretching a texel.
 */
const CELL = 256;
const GAP = 8;
const COLUMNS = 7;
const BACKGROUND = 40;

interface Image {
  readonly width: number;
  readonly height: number;
  readonly rgb: Uint8Array;
}

/** Light from the upper left, raking, in tangent space (+Y toward row 0), normalised. */
const LIGHT = [-0.4511, 0.5514, 0.7018] as const;
/** The half vector between that light and a viewer straight on. */
const HALF = [-0.2445, 0.2989, 0.9224] as const;

function linearOf(byte: number): number {
  return SRGB_TO_LINEAR[byte]! / 65535;
}

function toByte(linear: number): number {
  return encodeChannel(Math.round(Math.min(1, Math.max(0, linear)) * 65535));
}

/**
 * Any published set as four planes, whatever its class packs: a colour, a normal with its z, an
 * occlusion, roughness and metalness, and the one channel left over, if the class has one.
 *
 * A v1 set packs all four and is read straight. A set of a class packs what its class needs, so
 * the colour of a cutout or a decal comes out of the first three components of its colour map and
 * its coverage is the channel left over; glazing packs no occlusion, roughness and metalness at
 * all, so its roughness is read from its transmission map and the rest is stated as unoccluded and
 * not metal, with its transmission as the channel left over; and an opaque v2 set stores no height,
 * so it has no channel left over. Until this existed the sheet read v1 alone and threw on every
 * set of a class, which by batch 3 was nine of seventeen.
 */
export interface Planes {
  readonly width: number;
  readonly height: number;
  readonly baseColor: Uint8Array;
  readonly normal: Uint8Array;
  readonly orm: Uint8Array;
  readonly coverage: Uint8Array | null;
  readonly extra: { readonly name: string; readonly bytes: Uint8Array } | null;
}

export function planes(container: Uint8Array): Planes {
  const read = readContainer(container);
  const resolution = read.header.resolution as { width: number; height: number };
  const { width, height } = resolution;
  const texels = width * height;
  const map = (name: string): Uint8Array | undefined => read.maps.get(name);
  const spread = (components: number, pick: (at: number, c: number) => number) => {
    const out = new Uint8Array(texels * 3);
    for (let index = 0; index < texels; index += 1) {
      for (let c = 0; c < 3; c += 1) out[index * 3 + c] = pick(index * components, c);
    }
    return out;
  };
  const colourMap = map('base_color');
  const coverageMap = map('base_color_coverage');
  const baseColor = colourMap ?? spread(4, (at, c) => coverageMap![at + c]!);
  let coverage: Uint8Array | null = null;
  if (coverageMap !== undefined) {
    coverage = new Uint8Array(texels);
    for (let index = 0; index < texels; index += 1) coverage[index] = coverageMap[index * 4 + 3]!;
  }
  const stored = map('normal');
  // Glazing stores no normal at all: a pane is flat, and what a renderer needs from it is its
  // transmission and roughness. Its picture is the flat normal, which is what the class means.
  const normal = stored === undefined
    ? spread(3, (_at, c) => (c === 2 ? 255 : 128))
    : read.profile === SET_PROFILE_V1
      ? stored
      : spread(2, (at, c) => {
        if (c < 2) return stored[at + c]!;
        // z from x and y, the way every reader of a two-channel normal rebuilds it, in integers:
        // with X and Y as the stored bytes about their zero, 255 z is the root of 255^2 - X^2 - Y^2,
        // and `isqrt` is what src may use, because Math.sqrt is the bake's own banned float.
        const x = 2 * stored[at]! - 255;
        const y = 2 * stored[at + 1]! - 255;
        const square = 255 * 255 - x * x - y * y;
        return ((square <= 0 ? 0 : isqrt(square)) + 255) >> 1;
      });
  const ormMap = map('orm');
  const transmission = map('transmission_roughness');
  const orm = ormMap ?? spread(2, (at, c) =>
    (c === 0 ? 255 : c === 1 ? transmission![at + 1]! : 0));
  const heightMap = map('height');
  let extra: Planes['extra'] = null;
  if (heightMap !== undefined) extra = { name: 'height', bytes: heightMap };
  else if (transmission !== undefined) {
    const only = new Uint8Array(texels);
    for (let index = 0; index < texels; index += 1) only[index] = transmission[index * 2]!;
    extra = { name: 'transmission', bytes: only };
  } else if (coverage !== null) extra = { name: 'coverage', bytes: coverage };
  return { width, height, baseColor, normal, orm, coverage, extra };
}

/** The shaded tile, texel for texel. A class with coverage is laid over a mid grey by it. */
export function litTile(container: Uint8Array): Image {
  const { width, height, baseColor, normal, orm, coverage } = planes(container);
  const rgb = new Uint8Array(width * height * 3);
  for (let index = 0; index < width * height; index += 1) {
    const at = index * 3;
    const nx = (2 * normal[at]!) / 255 - 1;
    const ny = (2 * normal[at + 1]!) / 255 - 1;
    const nz = (2 * normal[at + 2]!) / 255 - 1;
    const diffuseLight = Math.max(0, nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]);
    const alignment = Math.max(0, nx * HALF[0] + ny * HALF[1] + nz * HALF[2]);
    const occlusion = orm[at]! / 255;
    const roughness = orm[at + 1]! / 255;
    const metalness = orm[at + 2]! / 255;
    // A power of two chosen from roughness, raised by squaring.
    const steps = 1 + Math.round((1 - roughness) * 7);
    let highlight = alignment;
    for (let step = 0; step < steps; step += 1) highlight *= highlight;
    const exponent = 1 << steps;
    const lobe = (highlight * (exponent + 8)) / 25.13 * diffuseLight * 0.6;
    const covered = coverage === null ? 1 : coverage[index]! / 255;
    for (let c = 0; c < 3; c += 1) {
      const albedo = linearOf(baseColor[at + c]!);
      const f0 = 0.04 * (1 - metalness) + albedo * metalness;
      const diffuse = albedo * (1 - metalness) * (0.22 + 0.9 * diffuseLight);
      const ambientSpecular = 0.35 * f0 * metalness;
      const lit = (diffuse + ambientSpecular + f0 * lobe) * occlusion;
      // What is not covered is the surface underneath, which this picture does not have: a mid grey
      // stands in for it, so a gap reads as a gap and not as black paint.
      rgb[at + c] = toByte(lit * covered + 0.18 * (1 - covered));
    }
  }
  return { width, height, rgb };
}

/**
 * One plane as a picture. `extra` is whatever single channel the set's class leaves over, drawn as
 * grey: a v1 set's height, a glazing set's transmission, a cutout's or a decal's coverage. A class
 * that leaves none, which is an opaque v2 set, has no picture in that column and says so.
 */
function mapImage(container: Uint8Array, name: 'baseColor' | 'normal' | 'orm' | 'extra'): Image | null {
  const read = planes(container);
  const { width, height } = read;
  if (name !== 'extra') return { width, height, rgb: read[name] };
  if (read.extra === null) return null;
  const rgb = new Uint8Array(width * height * 3);
  read.extra.bytes.forEach((value, index) => rgb.fill(value, index * 3, index * 3 + 3));
  return { width, height, rgb };
}

/** Box-average `across` x `down` copies of `image` down by `factor`. */
function tiledDown(image: Image, across: number, down: number, factor: number): Image {
  const width = Math.floor((image.width * across) / factor);
  const height = Math.floor((image.height * down) / factor);
  const rgb = new Uint8Array(width * height * 3);
  const area = factor * factor;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      for (let c = 0; c < 3; c += 1) {
        let sum = 0;
        for (let dy = 0; dy < factor; dy += 1) {
          const sy = (y * factor + dy) % image.height;
          for (let dx = 0; dx < factor; dx += 1) {
            const sx = (x * factor + dx) % image.width;
            sum += image.rgb[(sy * image.width + sx) * 3 + c]!;
          }
        }
        rgb[(y * width + x) * 3 + c] = Math.round(sum / area);
      }
    }
  }
  return { width, height, rgb };
}

/** A full-scale window of the tiled plane, centred where four tiles meet. */
function corner(image: Image, size: number): Image {
  const rgb = new Uint8Array(size * size * 3);
  const left = image.width - (size >> 1);
  const top = image.height - (size >> 1);
  for (let y = 0; y < size; y += 1) {
    const sy = (top + y) % image.height;
    for (let x = 0; x < size; x += 1) {
      const sx = (left + x) % image.width;
      const from = (sy * image.width + sx) * 3;
      rgb.set(image.rgb.subarray(from, from + 3), (y * size + x) * 3);
    }
  }
  return { width: size, height: size, rgb };
}

function blit(target: Image, source: Image, left: number, top: number): void {
  for (let y = 0; y < source.height; y += 1) {
    const from = y * source.width * 3;
    target.rgb.set(
      source.rgb.subarray(from, from + source.width * 3),
      ((top + y) * target.width + left) * 3,
    );
  }
}

export function contactSheet(publication: Publication): RgbImage {
  const width = COLUMNS * CELL + (COLUMNS + 1) * GAP;
  const height = publication.sets.length * CELL + (publication.sets.length + 1) * GAP;
  const sheet: Image = { width, height, rgb: new Uint8Array(width * height * 3).fill(BACKGROUND) };
  const ordered = [...publication.sets].sort((a, b) =>
    a.entry.set_id < b.entry.set_id ? -1 : 1,
  );
  ordered.forEach((set, row) => {
    const top = GAP + row * (CELL + GAP);
    const base = mapImage(set.container, 'baseColor')!;
    const lit = litTile(set.container);
    const scale = base.width / CELL;
    // A cell is square and a tile need not be: cc0.kerb-stone is 1024 by 256 texels and the road
    // paint 256 by 64. One scale is right for both axes, or the picture lies about the shape of a
    // texel, so a short tile is repeated more often DOWN the cell to fill it. Deriving the count of
    // repeats from the width alone left such a set as a strip a quarter of the cell high.
    const down = Math.max(1, Math.round(base.width / base.height));
    const extra = mapImage(set.container, 'extra');
    const cells: (Image | null)[] = [
      tiledDown(base, 2, 2 * down, scale * 2),
      tiledDown(lit, 2, 2 * down, scale * 2),
      tiledDown(mapImage(set.container, 'normal')!, 1, down, scale),
      tiledDown(mapImage(set.container, 'orm')!, 1, down, scale),
      extra === null ? null : tiledDown(extra, 1, down, scale),
      corner(base, CELL),
      corner(lit, CELL),
    ];
    // A cell with no picture is left as the sheet's background: an opaque set of a class stores no
    // height, and an empty cell says that more honestly than a flat grey square would.
    cells.forEach((cell, column) => {
      if (cell !== null) blit(sheet, cell, GAP + column * (CELL + GAP), top);
    });
  });
  return sheet;
}

/** One set, 2 x 2 tiles at half scale, lit: the closest look at a set's appearance offered here. */
export function litPreview(container: Uint8Array): RgbImage {
  return tiledDown(litTile(container), 2, 2, 2);
}
