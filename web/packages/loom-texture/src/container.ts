import { canonicalBytes, canonicalJson } from './canonical-json.js';
import type { TextureSetDefinition } from './definition.js';
import { LICENCE_ID } from './licence.js';
import type { Maps } from './maps.js';

/**
 * THE CONTAINER, AND WHY IT IS THIS ONE.
 *
 * `.ltex`: four magic bytes, a little-endian uint32 header length, the header as canonical JSON,
 * space padding to a 16-byte boundary, then the four maps packed one after another with no gaps.
 * Each map is 8-bit texels, interleaved within the map (RGB for the three-channel maps), rows top
 * to bottom. It is the shape `scene-synth/src/format/opm.ts` proved out: self-describing, one
 * fetch, and a map is a `subarray` a renderer can hand to `texImage2D` as it stands.
 *
 * ONLY THE FIRST MAP IS ALIGNED, which is ADR-0010's correction to OPM carried over. Every texel
 * is one byte wide, so nothing after the first map needs alignment, and a gap would only be bytes
 * a loader has to know to skip. The header states every offset anyway (ADR-0010 D2), and the
 * decoder below refuses a file whose maps are not exactly contiguous.
 *
 * WHY NOT PNG. A PNG's bytes are whatever the deflate implementation emitted, so pinning a PNG
 * digest would make Node's bundled zlib a digest input: the same pixels baked on a machine with a
 * different zlib build would hash differently, and the migration that names these bytes would
 * quietly stop being reproducible from source. The texels here are stored raw, so the bytes are a
 * function of the texels and the header alone. PNG is still written, by `inspect/`, as a picture
 * for people to look at; it goes outside the output directory, and nothing pins or digests it.
 *
 * WHY THE HEADER IS CANONICAL JSON. The Python backend re-serialises it with
 * `exulanica.canonical.canonical_json`, which refuses floats, and compares the bytes. Every number
 * in it is therefore an integer in a stated unit: millimetres, texels, bytes, thousandths.
 */
export const CONTAINER_MAGIC = 'LTX1';
export const SET_PROFILE = 'exulanica.texture-set/v1';
export const MEDIA_TYPE = 'application/vnd.exulanica.texture-set';
export const GENERATOR = 'exulanica loom-texture';
/** The plane these sets live on. Generated content, never observed, and saying so in the bytes. */
export const TRUTH = 'invented';
const ALIGNMENT = 16;

/** The maps every set stores, in the order they are packed. The packing is stated, not implied. */
export const MAP_LAYOUT = [
  {
    name: 'base_color',
    components: 3,
    holds: ['red', 'green', 'blue'],
    srgb: true,
    decode: 'sRGB transfer function to linear reflectance',
  },
  {
    name: 'normal',
    components: 3,
    holds: ['normal_x', 'normal_y', 'normal_z'],
    srgb: false,
    decode: 'n = 2 * b / 255 - 1 per component, then normalise',
    space: 'tangent',
    convention: 'glTF: +X toward increasing u, +Y toward row 0, +Z out of the surface',
  },
  {
    name: 'orm',
    components: 3,
    holds: ['occlusion', 'roughness', 'metalness'],
    srgb: false,
    decode: 'b / 255, linear; occlusion 255 is unoccluded; roughness is perceptual',
  },
  {
    name: 'height',
    components: 1,
    holds: ['height'],
    srgb: false,
    decode: 'mm = b * height_range_mm / 255, above the lowest point the set can hold',
  },
] as const;

export type MapName = (typeof MAP_LAYOUT)[number]['name'];

export interface MapEntry {
  readonly name: MapName;
  readonly components: number;
  readonly holds: readonly string[];
  readonly srgb: boolean;
  readonly byte_offset: number;
  readonly byte_length: number;
}

const align = (value: number): number => Math.ceil(value / ALIGNMENT) * ALIGNMENT;

function placement(surface: TextureSetDefinition['surface']): Record<string, string> {
  return surface === 'vertical'
    ? { surface: 'vertical', u: 'horizontal, along the wall', v: 'downward: world up is row 0' }
    : { surface: 'horizontal', u: 'along the run of the surface', v: 'across the run' };
}

/** The header, less the map offsets, which depend on the header's own length. */
function headerBody(
  def: TextureSetDefinition,
  licenceSha256: string,
): Record<string, unknown> {
  return {
    profile: SET_PROFILE,
    media_type: MEDIA_TYPE,
    generator: GENERATOR,
    set_id: def.setId,
    version: def.version,
    seed: def.seed,
    family: def.family,
    title: def.title,
    summary: def.summary,
    truth: TRUTH,
    licence: { id: LICENCE_ID, sha256: licenceSha256 },
    resolution: { width: def.width, height: def.height },
    extent_mm: { u: def.extentU, v: def.extentV },
    placement: placement(def.surface),
    layout: {
      origin: 'row 0, column 0 is the top-left texel; glTF uv (0, 0) is its top-left corner',
      rows: 'top to bottom',
      texels: 'interleaved within each map, one byte per component',
    },
    tiling: 'torus: both axes wrap, every field periodic by construction',
    height_range_mm: def.heightRangeMm,
    cavity: {
      radius_mm: def.cavity.radiusMm,
      depth_mm: def.cavity.depthMm,
      strength_permille: def.cavity.strengthPermille,
    },
    parameters: def.parameters,
  };
}

function mapBytes(maps: Maps, name: MapName): Uint8Array {
  switch (name) {
    case 'base_color':
      return maps.baseColor;
    case 'normal':
      return maps.normal;
    case 'orm':
      return maps.orm;
    case 'height':
      return maps.relief;
  }
}

export function encodeContainer(
  def: TextureSetDefinition,
  maps: Maps,
  licenceSha256: string,
): Uint8Array {
  if (maps.width !== def.width || maps.height !== def.height) {
    throw new Error(
      `${def.setId} is ${def.width}x${def.height}; a ${maps.width}x${maps.height} bake is a preview, `
        + 'not the set',
    );
  }
  const body = headerBody(def, licenceSha256);
  const texels = def.width * def.height;
  const build = (start: number): Uint8Array => {
    let cursor = start;
    const entries: MapEntry[] = MAP_LAYOUT.map((layout) => {
      const length = texels * layout.components;
      const entry = { ...layout, byte_offset: cursor, byte_length: length };
      cursor += length;
      return entry;
    });
    return canonicalBytes({ ...body, maps: entries });
  };

  // The offsets are digits inside the header, so the header's length depends on them. Starting
  // from the shortest possible header, larger offsets only ever add digits, so the data start
  // only moves forward and settles within a step or two. The reader recomputes the start from
  // the header length, so the two must agree exactly, not merely leave room.
  let start = align(8 + build(0).length);
  let header = build(start);
  for (;;) {
    const needed = align(8 + header.length);
    if (needed === start) break;
    if (needed < start) throw new Error(`${def.setId}: the header layout did not settle`);
    start = needed;
    header = build(start);
  }

  let total = start;
  for (const layout of MAP_LAYOUT) total += texels * layout.components;
  const out = new Uint8Array(total);
  out.set(new TextEncoder().encode(CONTAINER_MAGIC), 0);
  new DataView(out.buffer).setUint32(4, header.length, true);
  out.set(header, 8);
  // Spaces, so the header still reads cleanly in a hex dump.
  out.fill(0x20, 8 + header.length, start);
  let cursor = start;
  for (const layout of MAP_LAYOUT) {
    const bytes = mapBytes(maps, layout.name);
    if (bytes.length !== texels * layout.components) {
      throw new Error(`${def.setId} ${layout.name} holds ${bytes.length} bytes, not ${texels * layout.components}`);
    }
    out.set(bytes, cursor);
    cursor += bytes.length;
  }
  return out;
}

export interface DecodedContainer {
  readonly header: Record<string, unknown> & {
    readonly set_id: string;
    readonly version: number;
    readonly resolution: { readonly width: number; readonly height: number };
    readonly extent_mm: { readonly u: number; readonly v: number };
    readonly height_range_mm: number;
    readonly maps: readonly MapEntry[];
  };
  readonly maps: Readonly<Record<MapName, Uint8Array>>;
}

/**
 * The reference reader, and a strict one: it refuses anything the writer would not have produced,
 * because a lenient reader is how a second, slightly different container format starts.
 */
export function decodeContainer(bytes: Uint8Array): DecodedContainer {
  if (bytes.length < 8) throw new Error('not a texture set: shorter than its preamble');
  const magic = new TextDecoder().decode(bytes.subarray(0, 4));
  if (magic !== CONTAINER_MAGIC) {
    throw new Error(`not a texture set: magic was ${JSON.stringify(magic)}`);
  }
  const headerLength = new DataView(bytes.buffer, bytes.byteOffset, 8).getUint32(4, true);
  if (8 + headerLength > bytes.length) throw new Error('the header runs past the end of the file');
  const headerText = new TextDecoder('utf-8', { fatal: true }).decode(
    bytes.subarray(8, 8 + headerLength),
  );
  const header = JSON.parse(headerText) as DecodedContainer['header'];
  if (canonicalJson(header) !== headerText) {
    throw new Error('the header is not canonical JSON, so its bytes are not the ones it describes');
  }
  if (header.profile !== SET_PROFILE) {
    throw new Error(`unsupported texture set profile ${JSON.stringify(header.profile)}`);
  }
  const start = align(8 + headerLength);
  for (let at = 8 + headerLength; at < start; at += 1) {
    if (bytes[at] !== 0x20) throw new Error(`padding byte ${at} is not a space`);
  }
  const { width, height } = header.resolution;
  const texels = width * height;
  if (header.maps.length !== MAP_LAYOUT.length) throw new Error('the map list is not the layout');
  const maps: Partial<Record<MapName, Uint8Array>> = {};
  let cursor = start;
  MAP_LAYOUT.forEach((layout, index) => {
    const entry = header.maps[index]!;
    const expected = { ...layout, byte_offset: cursor, byte_length: texels * layout.components };
    if (canonicalJson(entry) !== canonicalJson(expected)) {
      throw new Error(
        `map ${index} is ${canonicalJson(entry)}, expected ${canonicalJson(expected)}`,
      );
    }
    if (cursor + entry.byte_length > bytes.length) {
      throw new Error(`map ${layout.name} runs past the end of the file`);
    }
    maps[layout.name] = bytes.subarray(cursor, cursor + entry.byte_length);
    cursor += entry.byte_length;
  });
  if (cursor !== bytes.length) {
    throw new Error(`the maps end at byte ${cursor} and the file at byte ${bytes.length}`);
  }
  return { header, maps: maps as Record<MapName, Uint8Array> };
}
