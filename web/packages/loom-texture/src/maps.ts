import {
  type FramedMap,
  type MapDescriptor,
  SET_PROFILE_V2,
  classLayout,
} from './classes.js';
import type { TextureSetDefinition } from './definition.js';
import { FULL, ONE, clamp, floorDiv, isqrt, roundDiv } from './integer.js';
import { newSample } from './sample.js';
import { encodeChannel } from './srgb.js';
import { texelToTile } from './tile.js';

/**
 * From a recipe to the four maps a set stores.
 *
 * The recipe is evaluated once per texel into sixteen-bit fields. The normal map and the cavity
 * occlusion are then derived from the height field, with every neighbour index wrapped around the
 * tile. Wrapping there is not the tiling construction (the recipe's periodic fields are that); it
 * is what keeps a derived map as periodic as the field it came from, where clamping at the edge
 * would bend every normal in the outermost row and column.
 */
export interface Fields {
  readonly width: number;
  readonly height: number;
  readonly relief: Uint16Array;
  readonly red: Uint16Array;
  readonly green: Uint16Array;
  readonly blue: Uint16Array;
  readonly roughness: Uint16Array;
  readonly metalness: Uint16Array;
  readonly occlusion: Uint16Array;
  readonly coverage: Uint16Array;
  readonly transmission: Uint16Array;
}

export interface SampleOptions {
  readonly width?: number;
  readonly height?: number;
  /** Texels to shift the sampling window by, without wrapping. Used to test periodicity. */
  readonly offsetU?: number;
  readonly offsetV?: number;
}

const channel = (value: number): number => clamp(value, 0, FULL);

export function sampleFields(def: TextureSetDefinition, options: SampleOptions = {}): Fields {
  const width = options.width ?? def.width;
  const height = options.height ?? def.height;
  const offsetU = options.offsetU ?? 0;
  const offsetV = options.offsetV ?? 0;
  const count = width * height;
  const fields: Fields = {
    width,
    height,
    relief: new Uint16Array(count),
    red: new Uint16Array(count),
    green: new Uint16Array(count),
    blue: new Uint16Array(count),
    roughness: new Uint16Array(count),
    metalness: new Uint16Array(count),
    occlusion: new Uint16Array(count),
    coverage: new Uint16Array(count),
    transmission: new Uint16Array(count),
  };
  const pattern = def.pattern();
  const sample = newSample();
  const columns = new Float64Array(width);
  for (let i = 0; i < width; i += 1) columns[i] = texelToTile(i + offsetU, width);
  for (let j = 0; j < height; j += 1) {
    const y = texelToTile(j + offsetV, height);
    for (let i = 0; i < width; i += 1) {
      pattern(columns[i]!, y, sample);
      const index = j * width + i;
      // Typed arrays wrap out-of-range values modulo 2^16, so every write is clamped first.
      fields.relief[index] = channel(sample.height);
      fields.red[index] = channel(sample.red);
      fields.green[index] = channel(sample.green);
      fields.blue[index] = channel(sample.blue);
      fields.roughness[index] = channel(sample.roughness);
      fields.metalness[index] = channel(sample.metalness);
      fields.occlusion[index] = channel(sample.occlusion);
      fields.coverage[index] = channel(sample.coverage);
      fields.transmission[index] = channel(sample.transmission);
    }
  }
  return fields;
}

/**
 * The tangent-space normal map, glTF convention: +X toward increasing u (right), +Y toward row 0
 * (up in the image), +Z out of the surface, each component stored as round((n + 1) * 255 / 2).
 *
 * Slopes are physical. A height difference in range fractions becomes millimetres through
 * `heightRangeMm`, and a texel step becomes millimetres through the extent, so the same surface
 * baked at another resolution tilts its normals by the same angle.
 */
export function normalMap(fields: Fields, def: TextureSetDefinition): Uint8Array {
  const { width, height, relief } = fields;
  const out = new Uint8Array(width * height * 3);
  const range = def.heightRangeMm;
  if (range === null) throw new Error(`${def.setId} bakes no height field, so it has no normals`);
  const denominatorU = 2 * FULL * def.extentU;
  const denominatorV = 2 * FULL * def.extentV;
  for (let j = 0; j < height; j += 1) {
    const up = (j === 0 ? height - 1 : j - 1) * width;
    const down = (j === height - 1 ? 0 : j + 1) * width;
    const row = j * width;
    for (let i = 0; i < width; i += 1) {
      const left = i === 0 ? width - 1 : i - 1;
      const right = i === width - 1 ? 0 : i + 1;
      const gradientU = relief[row + right]! - relief[row + left]!;
      const gradientV = relief[down + i]! - relief[up + i]!;
      // Slopes in Q12, millimetres of height per millimetre of surface.
      const slopeU = roundDiv(gradientU * range * width * 4096, denominatorU);
      const slopeV = roundDiv(gradientV * range * height * 4096, denominatorV);
      // Height rising toward +u tilts the normal toward -u. Rows run downward, so height rising
      // toward larger rows tilts it toward row 0, which is +Y.
      const nx = -slopeU * 256;
      const ny = slopeV * 256;
      const nz = 4096 * 256;
      const length = isqrt(nx * nx + ny * ny + nz * nz);
      const at = (row + i) * 3;
      out[at] = clamp(roundDiv((nx + length) * 255, 2 * length), 0, 255);
      out[at + 1] = clamp(roundDiv((ny + length) * 255, 2 * length), 0, 255);
      out[at + 2] = clamp(roundDiv((nz + length) * 255, 2 * length), 0, 255);
    }
  }
  return out;
}

/** A box blur that wraps at every edge. Returns a new array. */
function boxBlur(
  source: Uint16Array,
  width: number,
  height: number,
  radiusU: number,
  radiusV: number,
): Uint16Array {
  const across = new Uint16Array(source.length);
  const spanU = 2 * radiusU + 1;
  for (let j = 0; j < height; j += 1) {
    const row = j * width;
    let sum = 0;
    for (let k = -radiusU; k <= radiusU; k += 1) {
      sum += source[row + (((k % width) + width) % width)]!;
    }
    for (let i = 0; i < width; i += 1) {
      across[row + i] = floorDiv(sum, spanU);
      const entering = (i + radiusU + 1) % width;
      const leaving = (((i - radiusU) % width) + width) % width;
      sum += source[row + entering]! - source[row + leaving]!;
    }
  }
  const out = new Uint16Array(source.length);
  const spanV = 2 * radiusV + 1;
  for (let i = 0; i < width; i += 1) {
    let sum = 0;
    for (let k = -radiusV; k <= radiusV; k += 1) {
      sum += across[(((k % height) + height) % height) * width + i]!;
    }
    for (let j = 0; j < height; j += 1) {
      out[j * width + i] = floorDiv(sum, spanV);
      const entering = (j + radiusV + 1) % height;
      const leaving = (((j - radiusV) % height) + height) % height;
      sum += across[entering * width + i]! - across[leaving * width + i]!;
    }
  }
  return out;
}

/**
 * Occlusion measured from the height field: how far each texel sits below its neighbourhood.
 * Returns a Q16 factor per texel, ONE where nothing occludes.
 *
 * The neighbourhood is a physical radius, converted to texels per axis, and blurred twice so its
 * weight falls off rather than stopping at a square edge.
 */
export function cavityFactor(fields: Fields, def: TextureSetDefinition): Uint16Array {
  const { width, height, relief } = fields;
  if (def.cavity === null || def.heightRangeMm === null) {
    throw new Error(`${def.setId} bakes no height field, so it measures no cavity`);
  }
  const { radiusMm, depthMm, strengthPermille } = def.cavity;
  const radiusU = Math.max(1, roundDiv(radiusMm * width, def.extentU));
  const radiusV = Math.max(1, roundDiv(radiusMm * height, def.extentV));
  const blurred = boxBlur(
    boxBlur(relief, width, height, radiusU, radiusV),
    width,
    height,
    radiusU,
    radiusV,
  );
  const strongest = floorDiv(strengthPermille * ONE, 1000);
  const out = new Uint16Array(relief.length);
  for (let index = 0; index < relief.length; index += 1) {
    const cavity = Math.max(0, blurred[index]! - relief[index]!);
    const occluded = Math.min(
      strongest,
      floorDiv(cavity * def.heightRangeMm * strongest, FULL * depthMm),
    );
    out[index] = Math.min(FULL, ONE - occluded);
  }
  return out;
}

/** The four maps a set stores, interleaved within each map, rows top to bottom. */
export interface Maps {
  readonly width: number;
  readonly height: number;
  readonly baseColor: Uint8Array;
  readonly normal: Uint8Array;
  readonly orm: Uint8Array;
  readonly relief: Uint8Array;
}

const toByte = (value: number): number => roundDiv(value * 255, FULL);

export function quantise(fields: Fields, def: TextureSetDefinition): Maps {
  const { width, height } = fields;
  const count = width * height;
  const cavity = cavityFactor(fields, def);
  const baseColor = new Uint8Array(count * 3);
  const orm = new Uint8Array(count * 3);
  const relief = new Uint8Array(count);
  for (let index = 0; index < count; index += 1) {
    const at = index * 3;
    baseColor[at] = encodeChannel(fields.red[index]!);
    baseColor[at + 1] = encodeChannel(fields.green[index]!);
    baseColor[at + 2] = encodeChannel(fields.blue[index]!);
    orm[at] = toByte(floorDiv(fields.occlusion[index]! * cavity[index]!, ONE));
    orm[at + 1] = toByte(fields.roughness[index]!);
    orm[at + 2] = toByte(fields.metalness[index]!);
    relief[index] = toByte(fields.relief[index]!);
  }
  return { width, height, baseColor, normal: normalMap(fields, def), orm, relief };
}

/** Sample, derive and quantise: the whole bake of one set, short of its container. */
export function bakeMaps(def: TextureSetDefinition, options: SampleOptions = {}): Maps {
  return quantise(sampleFields(def, options), def);
}

/**
 * The maps a v2 set of a procedural maker stores, in its class layout's order.
 *
 * Every derivation is the v1 bake's: base colour through the sRGB table, roughness and metalness to
 * a byte, occlusion times the cavity the height field shows, and the normal from the height field.
 * What differs is what is kept. A relief class keeps the normal's x and y, which are the same bytes
 * the v1 normal map holds, and drops z and the height map, which rebake exactly from the recipe;
 * `cutout` and `decal` store coverage beside the colour; glazing stores transmission beside
 * roughness and has no height field at all.
 */
export function classMaps(fields: Fields, def: TextureSetDefinition): FramedMap[] {
  if (def.containerProfile !== SET_PROFILE_V2) {
    throw new Error(`${def.setId} is a v1 set; bakeMaps and encodeContainer make it`);
  }
  const { width, height } = fields;
  const count = width * height;
  const layout = classLayout(def.materialClass, 'procedural');
  const coverage = def.materialClass === 'cutout' || def.materialClass === 'decal';
  const colour = new Uint8Array(count * (coverage ? 4 : 3));
  for (let index = 0; index < count; index += 1) {
    const at = index * (coverage ? 4 : 3);
    colour[at] = encodeChannel(fields.red[index]!);
    colour[at + 1] = encodeChannel(fields.green[index]!);
    colour[at + 2] = encodeChannel(fields.blue[index]!);
    if (coverage) colour[at + 3] = toByte(fields.coverage[index]!);
  }
  const bytes = new Map<string, Uint8Array>([[layout[0]!.name, colour]]);
  if (def.materialClass === 'glazing') {
    const surface = new Uint8Array(count * 2);
    for (let index = 0; index < count; index += 1) {
      surface[index * 2] = toByte(fields.transmission[index]!);
      surface[index * 2 + 1] = toByte(fields.roughness[index]!);
    }
    bytes.set('transmission_roughness', surface);
  } else {
    const cavity = cavityFactor(fields, def);
    const orm = new Uint8Array(count * 3);
    for (let index = 0; index < count; index += 1) {
      const at = index * 3;
      orm[at] = toByte(floorDiv(fields.occlusion[index]! * cavity[index]!, ONE));
      orm[at + 1] = toByte(fields.roughness[index]!);
      orm[at + 2] = toByte(fields.metalness[index]!);
    }
    const full = normalMap(fields, def);
    const normal = new Uint8Array(count * 2);
    for (let index = 0; index < count; index += 1) {
      normal[index * 2] = full[index * 3]!;
      normal[index * 2 + 1] = full[index * 3 + 1]!;
    }
    bytes.set('normal', normal);
    bytes.set('orm', orm);
  }
  return layout.map((descriptor: MapDescriptor) => ({ descriptor, bytes: bytes.get(descriptor.name)! }));
}

/** Sample and derive a v2 procedural set: its maps, in stored order, short of its container. */
export function bakeClassMaps(def: TextureSetDefinition, options: SampleOptions = {}): FramedMap[] {
  return classMaps(sampleFields(def, options), def);
}
