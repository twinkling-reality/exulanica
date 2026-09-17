/**
 * From a validated tile document to one integer mesh per materialised projection.
 *
 * Every record gets exactly one entry in every materialised projection, in the canonical record
 * order `triangle-digest.ts` defines: drawn, unavailable (with what it lacks), not admitted (its
 * grammar's declared semantics do not admit the projection), or not a surface. A drawn entry is a
 * contiguous range of vertices and triangles, so "which record does this triangle belong to" is
 * one lookup, and the range carries its own integer extent, so "what is that record's extent" is
 * another. An entry that is not drawn has no extent: an extent nobody measured is not written.
 */
import { canonicalBytes, compareCodeUnits } from './canonical-json.js';
import type { RecordPayload, TileDocument } from './document.js';
import { shapeOf } from './document.js';
import { MATERIALISED_PROJECTIONS, ruleFor } from './expand.js';
import type { Need } from './expand.js';
import type { ProjectionName } from './record-shapes.js';
import { COORDINATES_PER_TRIANGLE, IDENTITY_NOT_STATED, MATERIAL_NOT_CARRIED } from './triangle-digest.js';
import type { DigestEntry } from './triangle-digest.js';

export interface PlacedRecord {
  readonly payload: RecordPayload;
  /** Lowercase hex SHA-256 of `recordBytes(payload)`. */
  readonly sha256: string;
  /** The identity the record states, or `not-stated`. */
  readonly identity: string;
  /** Index into the document's grammars. */
  readonly grammar: number;
}

export type MaterialRef =
  | { readonly state: 'not-carried' }
  | { readonly state: 'record'; readonly record: number };

export type Triple = readonly [number, number, number];

export type Entry =
  | {
      readonly record: number;
      readonly state: 'drawn';
      readonly material: MaterialRef;
      readonly first_vertex: number;
      readonly vertex_count: number;
      readonly first_triangle: number;
      readonly triangle_count: number;
      readonly extent_mm: { readonly min: Triple; readonly max: Triple };
    }
  | { readonly record: number; readonly state: 'unavailable'; readonly needs: readonly Need[] }
  | { readonly record: number; readonly state: 'not_admitted' }
  | { readonly record: number; readonly state: 'not_a_surface' };

export interface ProjectionMesh {
  readonly name: ProjectionName;
  readonly entries: readonly Entry[];
  /** Absolute integer vertices, three per vertex. */
  readonly vertices: readonly number[];
  /** Indices into `vertices`, three per triangle. */
  readonly indices: readonly number[];
}

export interface TessellatedTile {
  readonly document: TileDocument;
  readonly records: readonly PlacedRecord[];
  readonly projections: readonly ProjectionMesh[];
}

/** The canonical bytes a record digest is taken over: `canonical_record` in Python. */
export function recordBytes(payload: RecordPayload): Uint8Array {
  return canonicalBytes({ fields: payload.fields, kind: payload.kind, version: payload.version });
}

/** Every record in document order, which is the order `tessellate` expects its digests in. */
export function documentRecords(document: TileDocument): readonly RecordPayload[] {
  return document.grammars.flatMap((grammar) => grammar.records);
}

function identityOf(payload: RecordPayload): string {
  const field = shapeOf(payload.kind).identity_field;
  if (field === undefined) return IDENTITY_NOT_STATED;
  return payload.fields[field] as string;
}

function extentOf(vertices: readonly number[]): { min: Triple; max: Triple } {
  const min = [vertices[0]!, vertices[1]!, vertices[2]!];
  const max = [vertices[0]!, vertices[1]!, vertices[2]!];
  for (let index = 0; index < vertices.length; index += 1) {
    const axis = index % 3;
    const value = vertices[index]!;
    if (value < min[axis]!) min[axis] = value;
    if (value > max[axis]!) max[axis] = value;
  }
  return { min: [min[0]!, min[1]!, min[2]!], max: [max[0]!, max[1]!, max[2]!] };
}

/**
 * Tessellate a document whose record digests have already been taken, in `documentRecords`
 * order. Digests are an argument because core cannot hash.
 */
export function tessellate(document: TileDocument, digests: readonly string[]): TessellatedTile {
  const inOrder = documentRecords(document);
  if (digests.length !== inOrder.length) {
    throw new RangeError(`${inOrder.length} records and ${digests.length} digests`);
  }
  let cursor = 0;
  const placed: PlacedRecord[] = [];
  document.grammars.forEach((grammar, grammarIndex) => {
    for (const payload of grammar.records) {
      placed.push({
        payload,
        sha256: digests[cursor]!,
        identity: identityOf(payload),
        grammar: grammarIndex,
      });
      cursor += 1;
    }
  });
  placed.sort((a, b) => {
    const byKind = compareCodeUnits(a.payload.kind, b.payload.kind);
    if (byKind !== 0) return byKind;
    return compareCodeUnits(a.sha256, b.sha256);
  });
  placed.forEach((record, index) => {
    if (index > 0) {
      if (record.sha256 === placed[index - 1]!.sha256) {
        throw new RangeError('two records share a digest, so the record order would tie');
      }
    }
  });

  const projections = MATERIALISED_PROJECTIONS.map((name): ProjectionMesh => {
    const vertices: number[] = [];
    const indices: number[] = [];
    const entries = placed.map((record, recordIndex): Entry => {
      const admitted = document.grammars[record.grammar]!.declared_semantics.admissible_uses;
      if (!admitted.includes(name)) return { record: recordIndex, state: 'not_admitted' };
      const rule = ruleFor(name, record.payload.kind);
      switch (rule.rule) {
        case 'not_a_surface':
          return { record: recordIndex, state: 'not_a_surface' };
        case 'needs':
          return { record: recordIndex, state: 'unavailable', needs: rule.needs };
        case 'expand': {
          const expansion = rule.expand(record.payload.fields);
          if (expansion.state === 'unavailable') {
            return { record: recordIndex, state: 'unavailable', needs: expansion.needs };
          }
          const firstVertex = vertices.length / 3;
          const firstTriangle = indices.length / 3;
          for (const value of expansion.vertices) vertices.push(value);
          for (const index of expansion.triangles) indices.push(firstVertex + index);
          return {
            record: recordIndex,
            state: 'drawn',
            material: { state: expansion.material },
            first_vertex: firstVertex,
            vertex_count: expansion.vertices.length / 3,
            first_triangle: firstTriangle,
            triangle_count: expansion.triangles.length / 3,
            extent_mm: extentOf(expansion.vertices),
          };
        }
      }
    });
    return { name, entries, vertices, indices };
  });
  return { document, records: placed, projections };
}

/**
 * The triangle digest's entries for one projection mesh, de-indexed. Shared by the bake and by
 * the container verifier, so the two can only disagree about their inputs, never their reading.
 */
export function digestEntries(
  records: readonly Pick<PlacedRecord, 'payload' | 'sha256' | 'identity'>[],
  mesh: Pick<ProjectionMesh, 'entries' | 'indices'> & { readonly vertices: ArrayLike<number> },
): DigestEntry[] {
  return mesh.entries.map((entry): DigestEntry => {
    const record = records[entry.record]!;
    const head = { kind: record.payload.kind, recordSha256: record.sha256, identity: record.identity };
    switch (entry.state) {
      case 'drawn': {
        const triangles = new Array<number>(entry.triangle_count * COORDINATES_PER_TRIANGLE);
        let out = 0;
        const end = (entry.first_triangle + entry.triangle_count) * 3;
        for (let corner = entry.first_triangle * 3; corner < end; corner += 1) {
          const vertex = mesh.indices[corner]!;
          triangles[out] = mesh.vertices[vertex * 3]!;
          triangles[out + 1] = mesh.vertices[vertex * 3 + 1]!;
          triangles[out + 2] = mesh.vertices[vertex * 3 + 2]!;
          out += 3;
        }
        const material = entry.material.state === 'record'
          ? records[entry.material.record]!.sha256
          : MATERIAL_NOT_CARRIED;
        return { ...head, state: 'drawn', material, triangles };
      }
      case 'unavailable':
        return { ...head, state: 'unavailable', needs: entry.needs };
      case 'not_admitted':
      case 'not_a_surface':
        return { ...head, state: entry.state };
    }
  });
}
