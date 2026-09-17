/**
 * THE .owd CONTAINER, AND WHY IT IS THIS ONE. This is the only writer of the format, and the
 * decoder below is the only reader any runtime should use.
 *
 * `.owd` (Exulanica World Data, one baked tile): the four magic bytes `OWD1`, a little-endian
 * uint32 header length, the header as canonical JSON, space padding to a 16-byte boundary, then
 * planar typed-array sections packed one after another with no gaps. It is the shape
 * `scene-synth/src/format/opm.ts` proved out and `loom-texture` repeated: one file, one fetch, and
 * every section is a `subarray` a renderer hands to a vertex buffer as it stands.
 *
 * ONLY THE FIRST SECTION IS ALIGNED, AND THAT IS ADR-0010'S CORRECTION, NOT AN OVERSIGHT. OPM once
 * aligned every section to 16 bytes, and the gaps cost PlayCanvas a per-point repack and got the
 * files refused. Every section here holds four-byte elements (int32, float32, uint32), so packing
 * them contiguously after an aligned start keeps every typed-array view legal with no gap. The
 * header states every offset anyway (ADR-0010 D2) and the decoder refuses any other layout.
 *
 * WHAT IS DIGESTED AND WHAT IS PAYLOAD. For each projection the file carries these sections, in
 * this order:
 *
 *   position_mm  int32   x, y, z per vertex: the integer vertex minus `origin_mm`. DIGESTED,
 *                        through the triangle digest, together with `origin_mm`.
 *   position     float32 x, y, z per vertex, in metres from `origin_mm`: `fround(offset / 1000)`.
 *                        PAYLOAD. A renderer wants floats; nothing is ever digested over them.
 *   surface_mm   int32   s, t per vertex, surface millimetres minus `surface_origin_mm`, in a
 *                        projection that carries surfaces (`render_batch`). DIGESTED. The rule
 *                        for s and t is in `triangle-digest.ts`; a texture's physical extent
 *                        scales them, with the material record's own scale and rotation.
 *   index        uint32  three per triangle. PAYLOAD for the digest, which reads triangles
 *                        de-indexed, so vertex sharing cannot move it.
 *
 * The triangle digest (`triangle-digest.ts`) is over the integer records and the integer triangle
 * stream. The container digest, which the bake stage records as the artifact's content hash, is
 * SHA-256 over every byte of the file, and is deterministic for the same reason the payload is:
 * division and float32 rounding are correctly rounded operations in every ECMAScript engine, and
 * nothing in the payload comes from a transcendental function, a clock or a random source.
 *
 * WHAT THE HEADER CARRIES, so a runtime needs nothing else: the tile record and its inputs
 * digest; each grammar's identity, descriptor digest and declared semantics; every record, in the
 * canonical record order, with its digest, the identity it states (or `not-stated`) and its
 * fields; and per projection, its representation contract, the triangle digest, the origins, the
 * counts, and one entry per record. A drawn entry is a contiguous vertex and triangle range with
 * its integer extent (and, where the projection carries surfaces, its material reference and
 * orientation), which answers "which record does this triangle belong to" and "what is that
 * record's extent". Any other entry states why nothing is drawn.
 *
 * REJECTED, with reasons:
 *
 *   glTF / GLB. Standard, and the eventual `export_gltf` projection. Rejected as the bake format
 *   because what this file must carry beyond triangles (a record per range, a stated unavailable
 *   state, a material bound by record digest, per-projection digests) would be `extras`, which no
 *   loader validates, and because an engine's glTF loader builds a scene graph on the way in. The
 *   container is GLB-shaped (magic, length-prefixed JSON header, aligned binary), so writing glTF
 *   later is a re-wrapping.
 *
 *   OPM. A point map, rung 3 of the reconstruction ladder, with no index buffer and a header that
 *   describes a camera. Reusing it would file generated geometry under an observation format.
 *
 *   Draco or meshopt compression. The compressed bytes are whatever the encoder build emits, so
 *   the container digest would depend on a codec version, the argument `loom-texture` makes
 *   against PNG and zlib. The budget is not the constraint: the whole shipped district is 232 KB.
 *
 *   Float-only positions. The digest would then be over lossy floats, or the integers would be
 *   unrecoverable from the file and nobody could check the digest. Integers plus an origin cost
 *   twelve bytes a vertex and make the file self-verifying.
 *
 *   One file per projection, or a JSON sidecar. Each is a second fetch for one tile.
 *
 *   The name. `atlas-core/src/corridor.ts` means a reconstruction corridor; nothing here uses that
 *   word, its profile string or its wire type.
 */
import { AsciiError, ASCII_SPACE, asciiBytes, asciiText } from './ascii.js';
import { CanonicalJsonError, canonicalBytes, canonicalJson, compareCodeUnits, parseCanonical } from './canonical-json.js';
import type { CanonicalValue } from './canonical-json.js';
import { shapeOf, TileDocumentError, validateRecord, validateSemantics } from './document.js';
import type { DeclaredSemantics, RecordPayload } from './document.js';
import { NEEDS, PROJECTION_DEFINITIONS, TESSELLATOR_SOURCE_VERSION } from './expand.js';
import type { Need, ProjectionDefinition } from './expand.js';
import { HEX64_PATTERN, IDENTITY_PATTERN, MATERIAL_RECORD_KIND, TILE_SHAPE } from './record-shapes.js';
import type { ProjectionName } from './record-shapes.js';
import type { Entry, MaterialRef, ProjectionMesh, TessellatedTile, Triple } from './tessellate.js';
import {
  ENTRY_STATES,
  IDENTITY_NOT_STATED,
  MATERIAL_NOT_CARRIED,
  SURFACE_ORIENTATIONS,
  TRIANGLE_DIGEST_PROFILE,
} from './triangle-digest.js';

export const OWD_MAGIC = 'OWD1';
export const OWD_PROFILE = 'exulanica.owd/v1';
/** The string the bake stage's parameters name the container by. */
export const OWD_CONTAINER = 'owd/1';
export const OWD_MEDIA_TYPE = 'application/vnd.exulanica.owd';
export const OWD_GENERATOR = 'exulanica loom-tess';
/** Generated content, never observed, and saying so in the bytes. */
export const OWD_TRUTH = 'invented';
export const COORDINATE_UNIT = 'millimetre';

const ALIGNMENT = 16;
const PREAMBLE_BYTES = 8;
const ELEMENT_BYTES = 4;
const COMPONENTS = 3;
const SURFACE_COMPONENTS = 2;
const MILLIMETRES_PER_METRE = 1000;
/** Offsets from an origin are stored as int32. */
const INT32_MAX = 0x7fffffff;
/** Indices are stored as uint32. */
const UINT32_LIMIT = 0x100000000;

export const COORDINATES = {
  unit: COORDINATE_UNIT,
  plan: 'x and y are the plan axes the records state their millimetres in',
  up: 'z is the height the records state, increasing upward',
  winding: 'counter-clockwise seen from +z, with x to the right and y up',
  payload: 'position is float32 metres from origin_mm: fround((mm - origin_mm) / 1000)',
  surface: 'surface_mm plus surface_origin_mm is s, t in millimetres in the frame of the '
    + 'surface orientation; horizontal: t left of s, terrain s = x and t = y; '
    + 'vertical: s along the run from its start, t = base - z',
} as const;

export type SectionName = 'position_mm' | 'position' | 'surface_mm' | 'index';

interface SectionLayout {
  readonly name: SectionName;
  readonly type: 'int32' | 'float32' | 'uint32';
  readonly components: number;
  readonly per: 'vertex' | 'triangle';
}

const POSITION_MM: SectionLayout = { name: 'position_mm', type: 'int32', components: COMPONENTS, per: 'vertex' };
const POSITION: SectionLayout = { name: 'position', type: 'float32', components: COMPONENTS, per: 'vertex' };
const SURFACE_MM: SectionLayout = { name: 'surface_mm', type: 'int32', components: SURFACE_COMPONENTS, per: 'vertex' };
const INDEX: SectionLayout = { name: 'index', type: 'uint32', components: COMPONENTS, per: 'triangle' };

/** The sections one projection carries, in packing order. */
export function sectionLayout(definition: ProjectionDefinition): readonly SectionLayout[] {
  if (definition.surfaces) return [POSITION_MM, POSITION, SURFACE_MM, INDEX];
  return [POSITION_MM, POSITION, INDEX];
}

export interface OwdSection {
  readonly projection: ProjectionName;
  readonly name: SectionName;
  readonly type: SectionLayout['type'];
  readonly components: number;
  readonly byte_offset: number;
  readonly byte_length: number;
}

export interface OwdRecord extends RecordPayload {
  readonly sha256: string;
  readonly identity: string;
  /** Index into `grammars`: the grammar whose document entry listed the record. */
  readonly grammar: number;
}

export interface OwdGrammar {
  readonly grammar_id: string;
  readonly grammar_version: number;
  readonly descriptor_sha256: string;
  readonly declared_semantics: DeclaredSemantics;
}

export interface OwdProjection {
  readonly name: ProjectionName;
  readonly contract: ProjectionDefinition['contract'];
  readonly triangle_digest: string;
  /** The minimum integer vertex, or empty when the projection draws nothing. */
  readonly origin_mm: Triple | readonly [];
  /** The minimum surface coordinate, in a projection that carries surfaces and draws something. */
  readonly surface_origin_mm?: readonly [number, number] | readonly [];
  readonly vertex_count: number;
  readonly triangle_count: number;
  readonly entries: readonly Entry[];
}

export interface OwdHeader {
  readonly profile: typeof OWD_PROFILE;
  readonly media_type: typeof OWD_MEDIA_TYPE;
  readonly generator: typeof OWD_GENERATOR;
  readonly tessellator_version: number;
  readonly truth: typeof OWD_TRUTH;
  readonly triangle_digest_profile: typeof TRIANGLE_DIGEST_PROFILE;
  readonly coordinates: typeof COORDINATES;
  readonly tile: RecordPayload;
  readonly tile_inputs_digest: string;
  readonly grammars: readonly OwdGrammar[];
  readonly records: readonly OwdRecord[];
  readonly projections: readonly OwdProjection[];
  readonly sections: readonly OwdSection[];
}

/** The digests a bake computed with its host's SHA-256. */
export interface OwdDigests {
  readonly tileInputs: string;
  readonly triangles: ReadonlyMap<ProjectionName, string>;
}

export class OwdError extends Error {}

function fail(why: string): never {
  throw new OwdError(`.owd refused: ${why}`);
}

const align = (value: number): number => value + ((ALIGNMENT - (value % ALIGNMENT)) % ALIGNMENT);

function definitionOf(name: ProjectionName): ProjectionDefinition {
  const definition = PROJECTION_DEFINITIONS.find((candidate) => candidate.name === name);
  if (definition === undefined) throw new OwdError(`${name} is not materialised`);
  return definition;
}

/** The per-axis minimum of flat `values` with `components` per item, or empty for none. */
function minimumOf(values: readonly number[], components: number): number[] {
  const minimum = values.slice(0, components);
  values.forEach((value, index) => {
    if (value < minimum[index % components]!) minimum[index % components] = value;
  });
  return minimum;
}

/** Offsets from `origin` as int32, refusing a span int32 cannot hold. */
function offsetsFrom(values: readonly number[], origin: readonly number[], what: string): Int32Array {
  const out = new Int32Array(values.length);
  values.forEach((value, index) => {
    const offset = value - origin[index % origin.length]!;
    if (offset > INT32_MAX) throw new OwdError(`${what} spans more millimetres than int32 holds from its origin`);
    out[index] = offset;
  });
  return out;
}

interface PackedProjection {
  readonly header: OwdProjection;
  readonly layout: readonly SectionLayout[];
  readonly views: Readonly<Record<SectionName, Int32Array | Float32Array | Uint32Array | undefined>>;
}

function packProjection(mesh: ProjectionMesh, digests: OwdDigests): PackedProjection {
  const definition = definitionOf(mesh.name);
  const triangleDigest = digests.triangles.get(mesh.name);
  if (triangleDigest === undefined) throw new OwdError(`no triangle digest for ${mesh.name}`);
  const vertexCount = mesh.vertices.length / COMPONENTS;
  if (vertexCount >= UINT32_LIMIT) throw new OwdError(`${mesh.name} has more vertices than uint32 indexes`);
  const origin = minimumOf(mesh.vertices, COMPONENTS);
  const positionMm = offsetsFrom(mesh.vertices, origin, mesh.name);
  const position = new Float32Array(positionMm.length);
  positionMm.forEach((offset, index) => {
    position[index] = Math.fround(offset / MILLIMETRES_PER_METRE);
  });
  const base = {
    name: mesh.name,
    contract: definition.contract,
    triangle_digest: triangleDigest,
    origin_mm: origin as unknown as Triple | readonly [],
    vertex_count: vertexCount,
    triangle_count: mesh.indices.length / COMPONENTS,
    entries: mesh.entries,
  };
  const index = Uint32Array.from(mesh.indices);
  if (!definition.surfaces) {
    return {
      header: base,
      layout: sectionLayout(definition),
      views: { position_mm: positionMm, position, surface_mm: undefined, index },
    };
  }
  const coordinates = mesh.surfaceCoordinates;
  if (coordinates === undefined) throw new OwdError(`${mesh.name} carries surfaces and has none`);
  const surfaceOrigin = minimumOf(coordinates, SURFACE_COMPONENTS);
  return {
    header: { ...base, surface_origin_mm: surfaceOrigin as unknown as readonly [number, number] | readonly [] },
    layout: sectionLayout(definition),
    views: {
      position_mm: positionMm,
      position,
      surface_mm: offsetsFrom(coordinates, surfaceOrigin, `${mesh.name} surface`),
      index,
    },
  };
}

function viewOf(projection: PackedProjection, layout: SectionLayout): Int32Array | Float32Array | Uint32Array {
  const view = projection.views[layout.name];
  if (view === undefined) throw new OwdError(`${projection.header.name} has no ${layout.name}`);
  return view;
}

function sectionsFrom(packed: readonly PackedProjection[], start: number): OwdSection[] {
  let cursor = start;
  const sections: OwdSection[] = [];
  for (const projection of packed) {
    for (const layout of projection.layout) {
      const length = viewOf(projection, layout).byteLength;
      sections.push({
        projection: projection.header.name,
        name: layout.name,
        type: layout.type,
        components: layout.components,
        byte_offset: cursor,
        byte_length: length,
      });
      cursor += length;
    }
  }
  return sections;
}

function headerFor(
  tile: TessellatedTile,
  digests: OwdDigests,
  projections: readonly OwdProjection[],
  sections: readonly OwdSection[],
): OwdHeader {
  return {
    profile: OWD_PROFILE,
    media_type: OWD_MEDIA_TYPE,
    generator: OWD_GENERATOR,
    tessellator_version: TESSELLATOR_SOURCE_VERSION,
    truth: OWD_TRUTH,
    triangle_digest_profile: TRIANGLE_DIGEST_PROFILE,
    coordinates: COORDINATES,
    tile: tile.document.tile,
    tile_inputs_digest: digests.tileInputs,
    grammars: tile.document.grammars.map((grammar) => ({
      grammar_id: grammar.grammar_id,
      grammar_version: grammar.grammar_version,
      descriptor_sha256: grammar.descriptor_sha256,
      declared_semantics: grammar.declared_semantics,
    })),
    records: tile.records.map((record) => ({
      kind: record.payload.kind,
      version: record.payload.version,
      fields: record.payload.fields,
      sha256: record.sha256,
      identity: record.identity,
      grammar: record.grammar,
    })),
    projections,
    sections,
  };
}

/** Write the container. The same tessellation and digests give the same bytes, everywhere. */
export function encodeOwd(tile: TessellatedTile, digests: OwdDigests): Uint8Array {
  const packed = tile.projections.map((mesh) => packProjection(mesh, digests));
  const projections = packed.map((projection) => projection.header);
  const build = (start: number): Uint8Array =>
    canonicalBytes(headerFor(tile, digests, projections, sectionsFrom(packed, start)) as unknown as CanonicalValue);

  // The offsets are digits in the header, so the header's length depends on them. Larger offsets
  // only add digits, so the start only moves forward and settles; the reader recomputes the start
  // from the header length, so the two must agree exactly.
  let start = align(PREAMBLE_BYTES + build(0).length);
  let header = build(start);
  for (;;) {
    const needed = align(PREAMBLE_BYTES + header.length);
    if (needed === start) break;
    if (needed < start) throw new OwdError('the header layout did not settle');
    start = needed;
    header = build(start);
  }

  const sections = sectionsFrom(packed, start);
  const last = sections[sections.length - 1];
  const total = last === undefined ? start : last.byte_offset + last.byte_length;
  const out = new Uint8Array(total);
  out.set(asciiBytes(OWD_MAGIC, 'magic'), 0);
  new DataView(out.buffer).setUint32(ELEMENT_BYTES, header.length, true);
  out.set(header, PREAMBLE_BYTES);
  // Spaces, so the header reads cleanly in a hex dump.
  out.fill(ASCII_SPACE, PREAMBLE_BYTES + header.length, start);
  let cursor = start;
  for (const projection of packed) {
    for (const layout of projection.layout) {
      const view = viewOf(projection, layout);
      out.set(new Uint8Array(view.buffer, view.byteOffset, view.byteLength), cursor);
      cursor += view.byteLength;
    }
  }
  return out;
}

export interface DecodedProjection {
  readonly header: OwdProjection;
  readonly positionMm: Int32Array;
  readonly position: Float32Array;
  /** Present exactly in a projection that carries surfaces. */
  readonly surfaceMm?: Int32Array;
  readonly index: Uint32Array;
}

export interface DecodedOwd {
  readonly header: OwdHeader;
  readonly projections: readonly DecodedProjection[];
}

type JsonObject = { readonly [key: string]: unknown };

function objectAt(value: unknown, where: string): JsonObject {
  if (typeof value !== 'object' || value === null) fail(`${where} is not an object`);
  if (Array.isArray(value)) fail(`${where} is not an object`);
  return value as JsonObject;
}

function arrayAt(value: unknown, where: string): readonly unknown[] {
  if (!Array.isArray(value)) fail(`${where} is not an array`);
  return value;
}

function keysAre(value: JsonObject, keys: readonly string[], where: string): void {
  const present = Object.keys(value).sort(compareCodeUnits);
  const wanted = [...keys].sort(compareCodeUnits);
  if (canonicalJson(present) !== canonicalJson(wanted)) {
    fail(`${where} has keys ${canonicalJson(present)}, expected ${canonicalJson(wanted)}`);
  }
}

function countAt(value: unknown, where: string, below: number): number {
  if (typeof value !== 'number') fail(`${where} is not a count`);
  if (!Number.isSafeInteger(value)) fail(`${where} is not a count`);
  if (value < 0) fail(`${where} is negative`);
  if (value >= below) fail(`${where} is ${value}, not below ${below}`);
  return value;
}

function hexAt(value: unknown, where: string): string {
  if (typeof value !== 'string') fail(`${where} is not a digest`);
  if (!HEX64_PATTERN.test(value)) fail(`${where} is not a digest`);
  return value;
}

function integersAt(value: unknown, where: string, length: number): number[] {
  const items = arrayAt(value, where);
  if (items.length !== length) fail(`${where} is not ${length} integers`);
  items.forEach((item) => {
    if (typeof item !== 'number') fail(`${where} is not ${length} integers`);
    if (!Number.isSafeInteger(item)) fail(`${where} is not ${length} integers`);
  });
  return items as number[];
}

function withRefusal<T>(run: () => T): T {
  try {
    return run();
  } catch (error) {
    if (error instanceof TileDocumentError) fail(error.message);
    if (error instanceof CanonicalJsonError) fail(error.message);
    if (error instanceof AsciiError) fail(error.message);
    throw error;
  }
}

function checkMaterial(value: unknown, where: string, records: readonly OwdRecord[]): MaterialRef {
  const material = objectAt(value, where);
  if (material.state === MATERIAL_NOT_CARRIED) {
    keysAre(material, ['state'], where);
    return { state: MATERIAL_NOT_CARRIED };
  }
  if (material.state !== 'record') fail(`${where}.state is neither ${MATERIAL_NOT_CARRIED} nor record`);
  keysAre(material, ['record', 'state'], where);
  const record = countAt(material.record, `${where}.record`, records.length);
  if (records[record]!.kind !== MATERIAL_RECORD_KIND) fail(`${where} cites a record that is not a material`);
  return { state: 'record', record };
}

/** `NEEDS` maps each need to itself, so its sorted keys are its values. */
const NEED_VALUES: readonly string[] = Object.keys(NEEDS).sort(compareCodeUnits);

const DRAWN_KEYS = ['extent_mm', 'first_triangle', 'first_vertex', 'record', 'state', 'triangle_count', 'vertex_count'];

function checkEntries(
  projection: JsonObject,
  definition: ProjectionDefinition,
  where: string,
  records: readonly OwdRecord[],
  vertexCount: number,
  triangleCount: number,
): void {
  const entries = arrayAt(projection.entries, `${where}.entries`);
  if (entries.length !== records.length) fail(`${where} does not have one entry per record`);
  let nextVertex = 0;
  let nextTriangle = 0;
  entries.forEach((value, index) => {
    const at = `${where}.entries[${index}]`;
    const entry = objectAt(value, at);
    if (entry.record !== index) fail(`${at}.record is not ${index}`);
    if (!ENTRY_STATES.some((state) => state === entry.state)) fail(`${at}.state is not an entry state`);
    switch (entry.state) {
      case 'drawn': {
        if (definition.surfaces) {
          keysAre(entry, [...DRAWN_KEYS, 'material', 'surface'], at);
          checkMaterial(entry.material, `${at}.material`, records);
          if (!SURFACE_ORIENTATIONS.some((orientation) => orientation === entry.surface)) {
            fail(`${at}.surface is not an orientation`);
          }
        } else {
          keysAre(entry, DRAWN_KEYS, at);
        }
        if (entry.first_vertex !== nextVertex) fail(`${at}.first_vertex does not follow the range before it`);
        if (entry.first_triangle !== nextTriangle) fail(`${at}.first_triangle does not follow the range before it`);
        const vertices = countAt(entry.vertex_count, `${at}.vertex_count`, vertexCount + 1);
        const triangles = countAt(entry.triangle_count, `${at}.triangle_count`, triangleCount + 1);
        // A drawn range draws something: a triangle needs three vertices.
        if (triangles < 1) fail(`${at} is drawn and has no triangle`);
        if (vertices < COMPONENTS) fail(`${at} is drawn and has fewer than three vertices`);
        nextVertex += vertices;
        nextTriangle += triangles;
        const extent = objectAt(entry.extent_mm, `${at}.extent_mm`);
        keysAre(extent, ['max', 'min'], `${at}.extent_mm`);
        integersAt(extent.min, `${at}.extent_mm.min`, COMPONENTS);
        integersAt(extent.max, `${at}.extent_mm.max`, COMPONENTS);
        return;
      }
      case 'unavailable': {
        keysAre(entry, ['needs', 'record', 'state'], at);
        const needs = arrayAt(entry.needs, `${at}.needs`);
        if (needs.length === 0) fail(`${at}.needs is empty`);
        needs.forEach((need) => {
          if (typeof need !== 'string') fail(`${at}.needs names an unknown need`);
          if (!NEED_VALUES.includes(need)) fail(`${at}.needs names an unknown need`);
        });
        return;
      }
      case 'not_admitted':
      case 'not_in_projection':
        keysAre(entry, ['record', 'state'], at);
        return;
    }
  });
  if (nextVertex !== vertexCount) fail(`${where} ranges do not cover its vertices exactly`);
  if (nextTriangle !== triangleCount) fail(`${where} ranges do not cover its triangles exactly`);
}

function checkProjection(value: unknown, index: number, records: readonly OwdRecord[]): void {
  const at = `projections[${index}]`;
  const projection = objectAt(value, at);
  const definition = PROJECTION_DEFINITIONS[index]!;
  const keys = ['contract', 'entries', 'name', 'origin_mm', 'triangle_count', 'triangle_digest', 'vertex_count'];
  keysAre(projection, definition.surfaces ? [...keys, 'surface_origin_mm'] : keys, at);
  if (projection.name !== definition.name) fail(`${at}.name is not ${definition.name}`);
  if (canonicalJson(projection.contract as CanonicalValue) !== canonicalJson(definition.contract)) {
    fail(`${at}.contract is not the contract this version states`);
  }
  hexAt(projection.triangle_digest, `${at}.triangle_digest`);
  const vertexCount = countAt(projection.vertex_count, `${at}.vertex_count`, UINT32_LIMIT);
  const triangleCount = countAt(projection.triangle_count, `${at}.triangle_count`, UINT32_LIMIT);
  const origins: [string, number][] = [['origin_mm', COMPONENTS]];
  if (definition.surfaces) origins.push(['surface_origin_mm', SURFACE_COMPONENTS]);
  for (const [key, components] of origins) {
    const length = vertexCount === 0 ? 0 : components;
    integersAt(projection[key], `${at}.${key}`, length);
  }
  checkEntries(projection, definition, at, records, vertexCount, triangleCount);
}

function checkHeader(value: unknown): OwdHeader {
  const header = objectAt(value, 'header');
  keysAre(
    header,
    [
      'coordinates', 'generator', 'grammars', 'media_type', 'profile', 'projections', 'records',
      'sections', 'tessellator_version', 'tile', 'tile_inputs_digest', 'triangle_digest_profile', 'truth',
    ],
    'header',
  );
  if (header.profile !== OWD_PROFILE) fail(`profile is not ${OWD_PROFILE}`);
  if (header.media_type !== OWD_MEDIA_TYPE) fail(`media_type is not ${OWD_MEDIA_TYPE}`);
  if (header.generator !== OWD_GENERATOR) fail(`generator is not ${OWD_GENERATOR}`);
  if (header.truth !== OWD_TRUTH) fail(`truth is not ${OWD_TRUTH}`);
  if (header.tessellator_version !== TESSELLATOR_SOURCE_VERSION) {
    fail(`tessellator_version is not ${TESSELLATOR_SOURCE_VERSION}; there is no upgrade on read, rebake the tile`);
  }
  if (header.triangle_digest_profile !== TRIANGLE_DIGEST_PROFILE) {
    fail(`triangle_digest_profile is not ${TRIANGLE_DIGEST_PROFILE}`);
  }
  if (canonicalJson(header.coordinates as CanonicalValue) !== canonicalJson(COORDINATES)) {
    fail('coordinates is not the statement this version writes');
  }
  withRefusal(() => validateRecord(header.tile, 'tile', TILE_SHAPE));
  hexAt(header.tile_inputs_digest, 'tile_inputs_digest');

  const declared = (header.tile as RecordPayload).fields.grammar_versions as readonly (readonly [string, number])[];
  const grammars = arrayAt(header.grammars, 'grammars');
  if (grammars.length !== declared.length) fail('grammars does not match tile.grammar_versions');
  grammars.forEach((entry, index) => {
    const at = `grammars[${index}]`;
    const grammar = objectAt(entry, at);
    keysAre(grammar, ['declared_semantics', 'descriptor_sha256', 'grammar_id', 'grammar_version'], at);
    if (grammar.grammar_id !== declared[index]![0]) fail(`${at}.grammar_id does not match the tile`);
    if (grammar.grammar_version !== declared[index]![1]) fail(`${at}.grammar_version does not match the tile`);
    hexAt(grammar.descriptor_sha256, `${at}.descriptor_sha256`);
    withRefusal(() => validateSemantics(grammar.declared_semantics, `${at}.declared_semantics`));
  });

  const records = arrayAt(header.records, 'records').map((entry, index): OwdRecord => {
    const at = `records[${index}]`;
    const record = objectAt(entry, at);
    keysAre(record, ['fields', 'grammar', 'identity', 'kind', 'sha256', 'version'], at);
    const grammar = countAt(record.grammar, `${at}.grammar`, grammars.length);
    const payload = withRefusal(() =>
      validateRecord({ fields: record.fields, kind: record.kind, version: record.version }, at),
    );
    const sha256 = hexAt(record.sha256, `${at}.sha256`);
    if (typeof record.identity !== 'string') fail(`${at}.identity is not text`);
    const field = shapeOf(payload.kind).identity_field;
    if (field === undefined) {
      if (record.identity !== IDENTITY_NOT_STATED) fail(`${at}.identity is not ${IDENTITY_NOT_STATED}`);
    } else {
      if (record.identity !== payload.fields[field]) fail(`${at}.identity is not the identity the record states`);
      if (!IDENTITY_PATTERN.test(record.identity)) fail(`${at}.identity is not a UUID`);
    }
    return { ...payload, sha256, identity: record.identity, grammar };
  });
  records.forEach((record, index) => {
    if (index > 0) {
      const before = records[index - 1]!;
      const byKind = compareCodeUnits(before.kind, record.kind);
      if (byKind > 0) fail(`records[${index}] is not after records[${index - 1}] in the canonical order`);
      if (byKind === 0) {
        if (compareCodeUnits(before.sha256, record.sha256) >= 0) {
          fail(`records[${index}] is not after records[${index - 1}] in the canonical order`);
        }
      }
    }
  });

  const projections = arrayAt(header.projections, 'projections');
  if (projections.length !== PROJECTION_DEFINITIONS.length) fail('projections is not the materialised set');
  projections.forEach((projection, index) => checkProjection(projection, index, records));
  return header as unknown as OwdHeader;
}

function littleEndian(): boolean {
  return new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;
}

/**
 * The pure decoder: bytes in, typed sections out, refusing anything the writer would not have
 * produced. It proves the layout and every index safe to use; `verifyOwd` in `bake.ts` proves the
 * content, by baking the header's own records again and comparing every byte.
 *
 * The typed arrays are views over the bytes, so no vertex is copied, unless the bytes do not start
 * on a four-byte boundary, in which case they are copied once.
 */
export function decodeOwd(input: Uint8Array): DecodedOwd {
  if (!littleEndian()) fail('this host is big-endian, and the sections are little-endian views');
  // A view must start on a multiple of its element size. Node pools small file reads at arbitrary
  // offsets, so bytes that do not start on one are copied once to a buffer of their own.
  const bytes = input.byteOffset % ELEMENT_BYTES === 0 ? input : input.slice();
  if (bytes.length < PREAMBLE_BYTES) fail('shorter than its preamble');
  if (withRefusal(() => asciiText(bytes.subarray(0, ELEMENT_BYTES), 'magic')) !== OWD_MAGIC) {
    fail(`magic is not ${OWD_MAGIC}`);
  }
  const headerLength = new DataView(bytes.buffer, bytes.byteOffset, PREAMBLE_BYTES).getUint32(ELEMENT_BYTES, true);
  if (PREAMBLE_BYTES + headerLength > bytes.length) fail('the header runs past the end of the file');
  const parsed = withRefusal(() =>
    parseCanonical(bytes.subarray(PREAMBLE_BYTES, PREAMBLE_BYTES + headerLength), '.owd header'),
  );
  const header = checkHeader(parsed);
  const start = align(PREAMBLE_BYTES + headerLength);
  for (let at = PREAMBLE_BYTES + headerLength; at < start; at += 1) {
    if (bytes[at] !== ASCII_SPACE) fail(`padding byte ${at} is not a space`);
  }

  const expected: OwdSection[] = [];
  let cursor = start;
  header.projections.forEach((projection, index) => {
    for (const layout of sectionLayout(PROJECTION_DEFINITIONS[index]!)) {
      const count = layout.per === 'vertex' ? projection.vertex_count : projection.triangle_count;
      const length = count * layout.components * ELEMENT_BYTES;
      expected.push({
        projection: projection.name,
        name: layout.name,
        type: layout.type,
        components: layout.components,
        byte_offset: cursor,
        byte_length: length,
      });
      cursor += length;
    }
  });
  if (canonicalJson(header.sections as unknown as CanonicalValue) !== canonicalJson(expected as unknown as CanonicalValue)) {
    fail('sections are not the contiguous layout the counts imply');
  }
  if (cursor !== bytes.length) fail(`the file is ${bytes.length} bytes and its sections end at ${cursor}`);

  const base = bytes.byteOffset;
  const view = (projection: ProjectionName, name: SectionName): OwdSection | undefined =>
    expected.find((section) => section.projection === projection && section.name === name);
  const ints = (section: OwdSection): Int32Array =>
    new Int32Array(bytes.buffer, base + section.byte_offset, section.byte_length / ELEMENT_BYTES);
  const projections = header.projections.map((projection): DecodedProjection => {
    const positionMm = view(projection.name, 'position_mm')!;
    const position = view(projection.name, 'position')!;
    const triangles = view(projection.name, 'index')!;
    const surface = view(projection.name, 'surface_mm');
    const shared = {
      header: projection,
      positionMm: ints(positionMm),
      position: new Float32Array(bytes.buffer, base + position.byte_offset, position.byte_length / ELEMENT_BYTES),
      index: new Uint32Array(bytes.buffer, base + triangles.byte_offset, triangles.byte_length / ELEMENT_BYTES),
    };
    const decoded: DecodedProjection = surface === undefined ? shared : { ...shared, surfaceMm: ints(surface) };
    checkRanges(decoded);
    return decoded;
  });
  return { header, projections };
}

/** Every index stays inside its own range, and every extent is the range's own. */
function checkRanges(projection: DecodedProjection): void {
  const origin = projection.header.origin_mm;
  for (const entry of projection.header.entries) {
    if (entry.state !== 'drawn') continue;
    const low = entry.first_vertex;
    const high = low + entry.vertex_count;
    const end = (entry.first_triangle + entry.triangle_count) * COMPONENTS;
    for (let corner = entry.first_triangle * COMPONENTS; corner < end; corner += 1) {
      const vertex = projection.index[corner]!;
      if (vertex < low) fail(`${projection.header.name} record ${entry.record} indexes outside its range`);
      if (vertex >= high) fail(`${projection.header.name} record ${entry.record} indexes outside its range`);
    }
    const min = [...entry.extent_mm.max];
    const max = [...entry.extent_mm.min];
    for (let vertex = low; vertex < high; vertex += 1) {
      for (let axis = 0; axis < COMPONENTS; axis += 1) {
        const value = projection.positionMm[vertex * COMPONENTS + axis]! + (origin[axis] as number);
        if (value < min[axis]!) min[axis] = value;
        if (value > max[axis]!) max[axis] = value;
      }
    }
    if (canonicalJson([min, max]) !== canonicalJson([entry.extent_mm.min, entry.extent_mm.max])) {
      fail(`${projection.header.name} record ${entry.record} states an extent its vertices do not have`);
    }
  }
}

/** The absolute integer vertices of a decoded projection, three per vertex. */
export function absoluteVertices(projection: DecodedProjection): Float64Array {
  const out = new Float64Array(projection.positionMm.length);
  const origin = projection.header.origin_mm;
  for (let index = 0; index < out.length; index += 1) {
    out[index] = projection.positionMm[index]! + (origin[index % COMPONENTS] as number);
  }
  return out;
}

/** The absolute surface coordinates of a decoded projection, two per vertex, where it has them. */
export function absoluteSurfaceCoordinates(projection: DecodedProjection): Float64Array | undefined {
  const surface = projection.surfaceMm;
  const origin = projection.header.surface_origin_mm;
  if (surface === undefined) return undefined;
  if (origin === undefined) return undefined;
  const out = new Float64Array(surface.length);
  for (let index = 0; index < out.length; index += 1) {
    out[index] = surface[index]! + (origin[index % SURFACE_COMPONENTS] as number);
  }
  return out;
}

export type { Need };
