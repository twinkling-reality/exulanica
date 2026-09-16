import { decodeContainer } from '../container.js';
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
 *   1. base colour, 2 x 2 tiles, 1/8 scale
 *   2. lit preview, 2 x 2 tiles, 1/8 scale
 *   3. normal map, one tile, 1/4 scale
 *   4. occlusion, roughness, metalness as RGB, one tile, 1/4 scale
 *   5. height as grey, one tile, 1/4 scale
 *   6. base colour at full scale, 256 x 256 around the corner where four tiles meet
 *   7. lit preview at full scale around the same corner
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

/** The shaded tile, texel for texel. */
export function litTile(container: Uint8Array): Image {
  const { header, maps } = decodeContainer(container);
  const { width, height } = header.resolution;
  const rgb = new Uint8Array(width * height * 3);
  for (let index = 0; index < width * height; index += 1) {
    const at = index * 3;
    const nx = (2 * maps.normal[at]!) / 255 - 1;
    const ny = (2 * maps.normal[at + 1]!) / 255 - 1;
    const nz = (2 * maps.normal[at + 2]!) / 255 - 1;
    const diffuseLight = Math.max(0, nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]);
    const alignment = Math.max(0, nx * HALF[0] + ny * HALF[1] + nz * HALF[2]);
    const occlusion = maps.orm[at]! / 255;
    const roughness = maps.orm[at + 1]! / 255;
    const metalness = maps.orm[at + 2]! / 255;
    // A power of two chosen from roughness, raised by squaring.
    const steps = 1 + Math.round((1 - roughness) * 7);
    let highlight = alignment;
    for (let step = 0; step < steps; step += 1) highlight *= highlight;
    const exponent = 1 << steps;
    const lobe = (highlight * (exponent + 8)) / 25.13 * diffuseLight * 0.6;
    for (let c = 0; c < 3; c += 1) {
      const albedo = linearOf(maps.base_color[at + c]!);
      const f0 = 0.04 * (1 - metalness) + albedo * metalness;
      const diffuse = albedo * (1 - metalness) * (0.22 + 0.9 * diffuseLight);
      const ambientSpecular = 0.35 * f0 * metalness;
      rgb[at + c] = toByte((diffuse + ambientSpecular + f0 * lobe) * occlusion);
    }
  }
  return { width, height, rgb };
}

function mapImage(container: Uint8Array, name: 'base_color' | 'normal' | 'orm' | 'height'): Image {
  const { header, maps } = decodeContainer(container);
  const { width, height } = header.resolution;
  if (name !== 'height') return { width, height, rgb: maps[name] };
  const rgb = new Uint8Array(width * height * 3);
  maps.height.forEach((value, index) => rgb.fill(value, index * 3, index * 3 + 3));
  return { width, height, rgb };
}

/** Box-average `tiles` x `tiles` copies of `image` down by `factor`. */
function tiledDown(image: Image, tiles: number, factor: number): Image {
  const width = Math.floor((image.width * tiles) / factor);
  const height = Math.floor((image.height * tiles) / factor);
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
    const base = mapImage(set.container, 'base_color');
    const lit = litTile(set.container);
    const scale = base.width / CELL;
    const cells: Image[] = [
      tiledDown(base, 2, scale * 2),
      tiledDown(lit, 2, scale * 2),
      tiledDown(mapImage(set.container, 'normal'), 1, scale),
      tiledDown(mapImage(set.container, 'orm'), 1, scale),
      tiledDown(mapImage(set.container, 'height'), 1, scale),
      corner(base, CELL),
      corner(lit, CELL),
    ];
    cells.forEach((cell, column) => blit(sheet, cell, GAP + column * (CELL + GAP), top));
  });
  return sheet;
}

/** One set, 2 x 2 tiles at half scale, lit: the closest look at a set's appearance offered here. */
export function litPreview(container: Uint8Array): RgbImage {
  return tiledDown(litTile(container), 2, 2);
}
