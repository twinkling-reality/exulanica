import { canonicalBytes, canonicalJson } from './canonical-json.js';
import {
  type FramedMap,
  type GlazingFilm,
  MATERIAL_CLASSES,
  MAKER_KINDS,
  type MakerKind,
  type MapDescriptor,
  type MaterialClass,
  RELIEF_CLASSES,
  SET_PROFILE_V1,
  SET_PROFILE_V2,
  type SetProfile,
  V1_LAYOUT,
  classLayout,
  classParameters,
  coveragePermille,
  declaredFilm,
  isMakerKind,
  isMaterialClass,
} from './classes.js';
import type { TextureSetDefinition } from './definition.js';
import type { Maps } from './maps.js';

/**
 * THE CONTAINER, AND WHY IT IS THIS ONE.
 *
 * `.ltex`: four magic bytes, a little-endian uint32 header length, the header as canonical JSON,
 * space padding to a 16-byte boundary, then the maps packed one after another with no gaps. Each
 * map is 8-bit texels, interleaved within the map, rows top to bottom. It is the shape
 * `scene-synth/src/format/opm.ts` proved out: self-describing, one fetch, and a map is a
 * `subarray` a renderer can hand to `texImage2D` as it stands.
 *
 * TWO PROFILES, ONE FRAMING. `exulanica.texture-set/v1` holds the four-map opaque layout every set
 * published before material classes uses. `exulanica.texture-set/v2` states its material class and
 * its maker's kind, and holds exactly the layout `classes.ts` gives that pair. The framing did not
 * change, so the magic did not; the profile did, so a reader written for v1 refuses v2 rather than
 * reading it as something it is not.
 *
 * ONLY THE FIRST MAP IS ALIGNED, which is ADR-0010's correction to OPM carried over. Every texel
 * is one byte wide, so nothing after the first map needs alignment, and a gap would only be bytes
 * a loader has to know to skip. The header states every offset anyway (ADR-0010 D2), and the
 * reader below refuses a file whose maps are not exactly contiguous.
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
/** The profile every set published before material classes declares. */
export const SET_PROFILE = SET_PROFILE_V1;
export const MEDIA_TYPE = 'application/vnd.exulanica.texture-set';
export const GENERATOR = 'exulanica loom-texture';
/** The plane these sets live on. Generated content, never observed, and saying so in the bytes. */
export const TRUTH = 'invented';
const ALIGNMENT = 16;
const PREAMBLE = 8;

/** The maps every v1 set stores, in the order they are packed. The packing is stated, not implied. */
export const MAP_LAYOUT = V1_LAYOUT;
export type MapName = 'base_color' | 'normal' | 'orm' | 'height';

export interface MapEntry {
  readonly name: string;
  readonly components: number;
  readonly holds: readonly string[];
  readonly srgb: boolean;
  readonly byte_offset: number;
  readonly byte_length: number;
}

/** Whether a refusal is about the file's framing or about what its header says. */
export type ContainerRefusalReason = 'container' | 'header';

/** A container the reader will not read, and which of the two kinds of reason refused it. */
export class ContainerRefusal extends Error {
  constructor(
    readonly reason: ContainerRefusalReason,
    message: string,
  ) {
    super(message);
    this.name = 'ContainerRefusal';
  }
}

function refuse(reason: ContainerRefusalReason, message: string): never {
  throw new ContainerRefusal(reason, message);
}

const align = (value: number): number => Math.ceil(value / ALIGNMENT) * ALIGNMENT;

export function placement(surface: TextureSetDefinition['surface']): Record<string, string> {
  return surface === 'vertical'
    ? { surface: 'vertical', u: 'horizontal, along the wall', v: 'downward: world up is row 0' }
    : { surface: 'horizontal', u: 'along the run of the surface', v: 'across the run' };
}

/** How rows and texels lie, which every profile states in the same words. */
export const TEXEL_LAYOUT = {
  origin: 'row 0, column 0 is the top-left texel; glTF uv (0, 0) is its top-left corner',
  rows: 'top to bottom',
  texels: 'interleaved within each map, one byte per component',
} as const;
export const TILING = 'torus: both axes wrap, every field periodic by construction';

/** The header of a v1 set, less the map offsets, which depend on the header's own length. */
function headerBody(
  def: TextureSetDefinition,
  licenceSha256: string,
): Record<string, unknown> {
  if (def.containerProfile !== SET_PROFILE_V1 || def.heightRangeMm === null || def.cavity === null) {
    throw new Error(`${def.setId} is not a v1 set; encodeContainerV2 writes a set that states its class`);
  }
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
    licence: { id: def.licenceId, sha256: licenceSha256 },
    resolution: { width: def.width, height: def.height },
    extent_mm: { u: def.extentU, v: def.extentV },
    placement: placement(def.surface),
    layout: TEXEL_LAYOUT,
    tiling: TILING,
    height_range_mm: def.heightRangeMm,
    cavity: {
      radius_mm: def.cavity.radiusMm,
      depth_mm: def.cavity.depthMm,
      strength_permille: def.cavity.strengthPermille,
    },
    parameters: def.parameters,
  };
}

function mapBytes(maps: Maps, name: string): Uint8Array {
  switch (name) {
    case 'base_color':
      return maps.baseColor;
    case 'normal':
      return maps.normal;
    case 'orm':
      return maps.orm;
    case 'height':
      return maps.relief;
    default:
      throw new Error(`a v1 set has no ${name} map`);
  }
}

export type { FramedMap } from './classes.js';

/**
 * Frame a header body and its maps: preamble, canonical header, space padding, contiguous maps.
 * The body is everything but `maps`, which this writes with each map's offset and length.
 */
export function frameContainer(body: Record<string, unknown>, maps: readonly FramedMap[]): Uint8Array {
  const build = (start: number): Uint8Array => {
    let cursor = start;
    const entries = maps.map(({ descriptor, bytes }) => {
      const entry = { ...descriptor, byte_offset: cursor, byte_length: bytes.length };
      cursor += bytes.length;
      return entry;
    });
    return canonicalBytes({ ...body, maps: entries });
  };

  // The offsets are digits inside the header, so the header's length depends on them. Starting
  // from the shortest possible header, larger offsets only ever add digits, so the data start
  // only moves forward and settles within a step or two. The reader recomputes the start from
  // the header length, so the two must agree exactly, not merely leave room.
  let start = align(PREAMBLE + build(0).length);
  let header = build(start);
  for (;;) {
    const needed = align(PREAMBLE + header.length);
    if (needed === start) break;
    if (needed < start) throw new Error(`${String(body.set_id)}: the header layout did not settle`);
    start = needed;
    header = build(start);
  }

  let total = start;
  for (const map of maps) total += map.bytes.length;
  const out = new Uint8Array(total);
  out.set(new TextEncoder().encode(CONTAINER_MAGIC), 0);
  new DataView(out.buffer).setUint32(4, header.length, true);
  out.set(header, PREAMBLE);
  // Spaces, so the header still reads cleanly in a hex dump.
  out.fill(0x20, PREAMBLE + header.length, start);
  let cursor = start;
  for (const map of maps) {
    out.set(map.bytes, cursor);
    cursor += map.bytes.length;
  }
  return out;
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
  const texels = def.width * def.height;
  const framed = MAP_LAYOUT.map((layout) => {
    const bytes = mapBytes(maps, layout.name);
    if (bytes.length !== texels * layout.components) {
      throw new Error(`${def.setId} ${layout.name} holds ${bytes.length} bytes, not ${texels * layout.components}`);
    }
    return { descriptor: layout, bytes };
  });
  return frameContainer(headerBody(def, licenceSha256), framed);
}

/**
 * A v2 set of a procedural maker: the header states its class, its maker's kind and what its class
 * fixes, and the maps are its class layout. The writer reads back what it wrote, so it never writes
 * a container its own reader would refuse.
 */
export function encodeContainerV2(
  def: TextureSetDefinition,
  maps: readonly FramedMap[],
  licenceSha256: string,
): Uint8Array {
  if (def.containerProfile !== SET_PROFILE_V2) {
    throw new Error(`${def.setId} is a v1 set; encodeContainer writes it`);
  }
  const texels = def.width * def.height;
  for (const map of maps) {
    if (map.bytes.length !== texels * map.descriptor.components) {
      throw new Error(
        `${def.setId} is ${def.width}x${def.height}; its ${map.descriptor.name} holds ${map.bytes.length} bytes, `
          + 'so the bake is a preview, not the set',
      );
    }
  }
  const colour = maps.find((map) => map.descriptor.name === 'base_color_coverage');
  const relief = def.heightRangeMm !== null && def.cavity !== null
    ? {
      height_range_mm: def.heightRangeMm,
      cavity: {
        radius_mm: def.cavity.radiusMm,
        depth_mm: def.cavity.depthMm,
        strength_permille: def.cavity.strengthPermille,
      },
    }
    : {};
  const bytes = frameContainer(
    {
      profile: SET_PROFILE_V2,
      media_type: MEDIA_TYPE,
      generator: GENERATOR,
      set_id: def.setId,
      version: def.version,
      seed: def.seed,
      family: def.family,
      title: def.title,
      summary: def.summary,
      truth: TRUTH,
      licence: { id: def.licenceId, sha256: licenceSha256 },
      resolution: { width: def.width, height: def.height },
      extent_mm: { u: def.extentU, v: def.extentV },
      placement: placement(def.surface),
      layout: TEXEL_LAYOUT,
      tiling: TILING,
      parameters: def.parameters,
      material_class: def.materialClass,
      maker_kind: 'procedural',
      class: classParameters(def.materialClass, colour === undefined ? null : coveragePermille(colour.bytes), def.film),
      ...relief,
    },
    maps,
  );
  readContainer(bytes);
  return bytes;
}

/** Every key a v2 header holds whatever its class and maker. */
export const V2_HEADER_KEYS = [
  'class',
  'extent_mm',
  'family',
  'generator',
  'layout',
  'licence',
  'maker_kind',
  'maps',
  'material_class',
  'media_type',
  'parameters',
  'placement',
  'profile',
  'resolution',
  'seed',
  'set_id',
  'summary',
  'tiling',
  'title',
  'truth',
  'version',
] as const;

/**
 * The keys a v2 header holds beyond {@link V2_HEADER_KEYS}. A procedural set whose class bakes a
 * height field states the field's range and how its cavity was measured, because its normals and
 * occlusion were derived from them; a model-made set states the range only when it ships the height
 * map that range decodes.
 */
export function v2ReliefKeys(
  materialClass: MaterialClass,
  makerKind: MakerKind,
  shipsHeight: boolean,
): string[] {
  if (makerKind === 'procedural') {
    return RELIEF_CLASSES.includes(materialClass) ? ['cavity', 'height_range_mm'] : [];
  }
  return shipsHeight ? ['height_range_mm'] : [];
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

/** Any container this reader can read: its profile, class, maker kind, header and maps. */
export interface ReadContainer {
  readonly profile: SetProfile;
  readonly materialClass: MaterialClass;
  readonly makerKind: MakerKind;
  readonly header: Readonly<Record<string, unknown>>;
  readonly layout: readonly MapDescriptor[];
  /** In stored order, each a view over the bytes. */
  readonly maps: ReadonlyMap<string, Uint8Array>;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const positive = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const nonNegative = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;

function sameKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const present = Object.keys(value).sort();
  const wanted = [...keys].sort();
  return present.length === wanted.length && present.every((key, index) => key === wanted[index]);
}

/**
 * The reference reader, and a strict one: it refuses anything the writer would not have produced,
 * because a lenient reader is how a second, slightly different container format starts. Each
 * refusal is a {@link ContainerRefusal} saying whether the framing or the header refused it.
 */
export function readContainer(bytes: Uint8Array): ReadContainer {
  if (bytes.length < PREAMBLE) refuse('container', 'not a texture set: shorter than its preamble');
  const magic = String.fromCharCode(bytes[0]!, bytes[1]!, bytes[2]!, bytes[3]!);
  if (magic !== CONTAINER_MAGIC) {
    refuse('container', `not a texture set: magic was ${JSON.stringify(magic)}`);
  }
  const headerLength = new DataView(bytes.buffer, bytes.byteOffset, PREAMBLE).getUint32(4, true);
  if (PREAMBLE + headerLength > bytes.length) {
    refuse('container', 'the header runs past the end of the file');
  }
  let headerText: string;
  let parsed: unknown;
  try {
    headerText = new TextDecoder('utf-8', { fatal: true }).decode(
      bytes.subarray(PREAMBLE, PREAMBLE + headerLength),
    );
    parsed = JSON.parse(headerText);
  } catch {
    return refuse('header', 'the header is not JSON');
  }
  let canonical: string | null;
  try {
    canonical = canonicalJson(parsed as object);
  } catch {
    canonical = null;
  }
  if (canonical !== headerText) {
    refuse('header', 'the header is not canonical JSON, so its bytes are not the ones it describes');
  }
  if (!isRecord(parsed)) refuse('header', 'the header is not an object');
  const header = parsed;
  const profile = header.profile;
  if (profile !== SET_PROFILE_V1 && profile !== SET_PROFILE_V2) {
    refuse('header', `unsupported texture set profile ${JSON.stringify(profile)}`);
  }
  const start = align(PREAMBLE + headerLength);
  if (start > bytes.length) refuse('container', 'the padding runs past the end of the file');
  for (let at = PREAMBLE + headerLength; at < start; at += 1) {
    if (bytes[at] !== 0x20) refuse('container', `padding byte ${at} is not a space`);
  }
  const resolution = header.resolution;
  if (!isRecord(resolution) || !sameKeys(resolution, ['height', 'width'])
    || !positive(resolution.width) || !positive(resolution.height)) {
    refuse('header', 'resolution is a positive width and height');
  }
  const texels = resolution.width * resolution.height;
  const declared = header.maps;
  if (!Array.isArray(declared)) refuse('header', 'the map list is not the layout');

  let materialClass: MaterialClass = 'opaque';
  let makerKind: MakerKind = 'procedural';
  let layout: readonly MapDescriptor[] = V1_LAYOUT;
  if (profile === SET_PROFILE_V2) {
    if (!isMaterialClass(header.material_class)) {
      refuse('header', `material_class is one of ${MATERIAL_CLASSES.join(', ')}`);
    }
    if (!isMakerKind(header.maker_kind)) {
      refuse('header', `maker_kind is one of ${MAKER_KINDS.join(', ')}`);
    }
    materialClass = header.material_class;
    makerKind = header.maker_kind;
    const named = (name: string): boolean =>
      declared.some((entry: unknown) => isRecord(entry) && entry.name === name);
    const produced = { normal: named('normal'), height: named('height') };
    layout = classLayout(materialClass, makerKind, produced);
    const keys = [...V2_HEADER_KEYS, ...v2ReliefKeys(materialClass, makerKind, produced.height)];
    if (!sameKeys(header, keys)) {
      refuse('header', `a header of maker kind ${makerKind} and class ${materialClass} has exactly ${[...keys].sort().join(', ')}`);
    }
  }

  if (declared.length !== layout.length) refuse('header', 'the map list is not the layout');
  const maps = new Map<string, Uint8Array>();
  let cursor = start;
  layout.forEach((descriptor, index) => {
    const entry: unknown = declared[index];
    const expected = { ...descriptor, byte_offset: cursor, byte_length: texels * descriptor.components };
    if (!isRecord(entry) || canonicalJson(entry) !== canonicalJson(expected)) {
      refuse('header', `map ${index} is ${JSON.stringify(entry)}, expected ${canonicalJson(expected)}`);
    }
    if (cursor + expected.byte_length > bytes.length) {
      refuse('container', `map ${descriptor.name} runs past the end of the file`);
    }
    maps.set(descriptor.name, bytes.subarray(cursor, cursor + expected.byte_length));
    cursor += expected.byte_length;
  });
  if (cursor !== bytes.length) {
    refuse('container', `the maps end at byte ${cursor} and the file at byte ${bytes.length}`);
  }

  if (profile === SET_PROFILE_V2) {
    const colour = maps.get('base_color_coverage');
    const measured = colour === undefined ? null : coveragePermille(colour);
    let film: GlazingFilm | null = null;
    if (materialClass === 'glazing') {
      film = declaredFilm(header.class);
      if (film === null) {
        refuse('header', 'a glazing set declares film_srgb, three integers from 0 to 255, and film_roughness_permille, an integer from 0 to 1000');
      }
    }
    const stated = classParameters(materialClass, measured, film);
    if (!isRecord(header.class) || canonicalJson(header.class) !== canonicalJson(stated)) {
      refuse('header', `class is ${JSON.stringify(header.class)}, but a set of class ${materialClass} with these maps states ${canonicalJson(stated)}`);
    }
    if ('height_range_mm' in header && !positive(header.height_range_mm)) {
      refuse('header', 'height_range_mm is a positive integer');
    }
    if ('cavity' in header) {
      const cavity = header.cavity;
      if (!isRecord(cavity) || !sameKeys(cavity, ['depth_mm', 'radius_mm', 'strength_permille'])
        || !positive(cavity.radius_mm) || !positive(cavity.depth_mm)
        || !nonNegative(cavity.strength_permille)) {
        refuse('header', 'cavity is a positive radius_mm and depth_mm and a strength_permille');
      }
    }
  }
  return { profile, materialClass, makerKind, header, layout, maps };
}

/**
 * Read a v1 container, the only profile the published v1 pipeline bakes. A v2 container is refused
 * here by profile; {@link readContainer} reads both.
 */
export function decodeContainer(bytes: Uint8Array): DecodedContainer {
  const read = readContainer(bytes);
  if (read.profile !== SET_PROFILE_V1) {
    refuse('header', `unsupported texture set profile ${JSON.stringify(read.profile)}`);
  }
  return {
    header: read.header as DecodedContainer['header'],
    maps: {
      base_color: read.maps.get('base_color')!,
      normal: read.maps.get('normal')!,
      orm: read.maps.get('orm')!,
      height: read.maps.get('height')!,
    },
  };
}
