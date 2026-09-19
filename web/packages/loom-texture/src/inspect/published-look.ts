import {
  type ManifestEntryRead,
  checkTextureSet,
  readTextureManifest,
} from '../manifest-reader.js';
import { SRGB_TO_LINEAR, encodeChannel } from '../srgb.js';
import { type Planes, planes } from './contact-sheet.js';
import type { RgbImage } from './png.js';

/**
 * Pictures of a PUBLISHED set, drawn from its committed container.
 *
 * The difference from `contact-sheet.ts` is where the bytes come from. The contact sheet is handed a
 * fresh `Publication`, so it can only picture what a bake just produced; this is handed the bytes
 * that are pinned, so what it draws is what a reader will read. That matters twice over. A look
 * check that needs a bake cannot picture a set whose maker has changed since it was published, and
 * a look check written against the draft machinery stops working the moment a draft is published
 * and its entry leaves `library-drafts/`, which is exactly what happened to this lane's own scripts
 * when batch 3 published six of them.
 *
 * Everything here goes through `planes`, so a set of any class works: the colour of a cutout or a
 * decal comes from the first three components of its colour map, a glazing set's roughness from its
 * transmission map, and the channel each class leaves over is drawn as grey.
 *
 * These are NOT the product. Two fixed lights over the stored maps, written to make relief and a
 * seam visible, and they say nothing about how the corridor renderer draws a set. A decal is laid
 * over a flat grey by its coverage, because the surface a decal belongs to is not in this picture.
 */

/**
 * Grazing, so relief shows, and near head on, so a finish does. Tangent space, +y toward row 0,
 * and both stated already normalised: this package refuses the square root and every approximated
 * function outside `integer.ts`, so nothing here normalises a vector or raises a power at runtime.
 */
const LIGHTS = [
  { name: 'lit-from-side', direction: [0.8237, 0.221, 0.5223] },
  { name: 'lit-from-front', direction: [0.1601, 0.3001, 0.9404] },
] as const;
/** How many times the highlight is squared: three, so the lobe is the eighth power. */
const SQUARINGS = 3;
/** What stands in for the surface under a decal where its coverage is nothing. */
const UNDER_A_DECAL = 0.1;

const linearOf = (byte: number): number => SRGB_TO_LINEAR[byte]! / 65535;
const toByte = (linear: number): number =>
  encodeChannel(Math.round(Math.min(1, Math.max(0, linear)) * 65535));

function tiled(read: Planes, tiles: number, fill: (index: number, out: Uint8Array, at: number) => void): RgbImage {
  const width = read.width * tiles;
  const height = read.height * tiles;
  const rgb = new Uint8Array(width * height * 3);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      fill((y % read.height) * read.width + (x % read.width), rgb, (y * width + x) * 3);
    }
  }
  return { width, height, rgb };
}

/**
 * Every picture of one published set, by file name without an extension: its maps at one texel to
 * one pixel, and one lit composite per light over `tiles` by `tiles` tiles, so a repeat shows.
 *
 * The ENTRY is a parameter, not a convenience, and this is the reason. `checkTextureSet` held a
 * container to its manifest entry and nothing in any product path called it: the look command read
 * `blobs/<content_sha256>.ltex`, which uses the digest as a FILE NAME and never as a digest, and
 * drew whatever it found. Measured 2026-09-19 by putting one set's container under another set's
 * name: the command wrote six pictures 256 by 64, printed `cc0.kerb-stone opaque 1024x256` beside
 * them, and exited 0, so the words came from the manifest and the pixels came from somewhere else.
 * `checkTextureSet` refuses that input on its first check. Taking the entry here rather than in the
 * command is what stops the next reader of a published set from forgetting it.
 */
export function publishedLook(
  container: Uint8Array,
  entry: ManifestEntryRead,
  tiles = 3,
): Map<string, RgbImage> {
  checkTextureSet(container, entry);
  const read = planes(container);
  const { baseColor, normal, orm, coverage, extra } = read;
  const pictures = new Map<string, RgbImage>();
  pictures.set('base-colour-1to1', tiled(read, 1, (index, out, at) => {
    for (let c = 0; c < 3; c += 1) out[at + c] = baseColor[index * 3 + c]!;
  }));
  pictures.set('normal-1to1', tiled(read, 1, (index, out, at) => {
    out[at] = normal[index * 3]!;
    out[at + 1] = normal[index * 3 + 1]!;
    out[at + 2] = normal[index * 3 + 2]!;
  }));
  pictures.set('orm-1to1', tiled(read, 1, (index, out, at) => {
    for (let c = 0; c < 3; c += 1) out[at + c] = orm[index * 3 + c]!;
  }));
  if (extra !== null) {
    pictures.set(`${extra.name}-1to1`, tiled(read, 1, (index, out, at) => {
      out[at] = extra.bytes[index]!;
      out[at + 1] = extra.bytes[index]!;
      out[at + 2] = extra.bytes[index]!;
    }));
  }
  for (const light of LIGHTS) {
    const [lx, ly, lz] = light.direction;
    pictures.set(`${light.name}-${tiles}x${tiles}`, tiled(read, tiles, (index, out, at) => {
      // The normal's z is the one `planes` rebuilt, so nothing is rooted here.
      const nx = normal[index * 3]! / 127.5 - 1;
      const ny = normal[index * 3 + 1]! / 127.5 - 1;
      const nz = normal[index * 3 + 2]! / 127.5 - 1;
      const ndotl = Math.max(0, nx * lx + ny * ly + nz * lz);
      const occlusion = orm[index * 3]! / 255;
      const roughness = orm[index * 3 + 1]! / 255;
      let highlight = ndotl;
      for (let squaring = 0; squaring < SQUARINGS; squaring += 1) highlight *= highlight;
      const gloss = (1 - roughness) * highlight * 0.5;
      const covered = coverage === null ? 1 : coverage[index]! / 255;
      for (let c = 0; c < 3; c += 1) {
        const lit = linearOf(baseColor[index * 3 + c]!) * (0.3 * occlusion + ndotl) + gloss;
        // What a decal does not cover is the surface beneath, which this picture does not have.
        out[at + c] = toByte(lit * covered + UNDER_A_DECAL * (1 - covered));
      }
    }));
  }
  return pictures;
}

/** Which sets a published directory holds, by id, from its manifest alone. */
export function publishedSets(manifest: Uint8Array): Map<string, ManifestEntryRead> {
  return new Map(readTextureManifest(manifest).map((entry) => [entry.setId, entry]));
}
