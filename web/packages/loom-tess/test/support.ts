import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { canonicalBytes, canonicalJson } from '../src/core/canonical-json.js';
import type { CanonicalValue } from '../src/core/canonical-json.js';

export const PACKAGE_ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));
export const REPOSITORY_ROOT = resolve(PACKAGE_ROOT, '..', '..', '..');
export const FIXTURE_PATH = join(PACKAGE_ROOT, 'test', 'fixtures', 'tile-conformance.json');

export const fixtureBytes = (): Uint8Array => new Uint8Array(readFileSync(FIXTURE_PATH));

/** The fixture as a mutable object, for tests that break one thing in it. */
export const fixtureObject = (): any => JSON.parse(readFileSync(FIXTURE_PATH, 'utf8'));

/** Back to canonical bytes, which is the only form the reader accepts. */
export const documentBytes = (document: unknown): Uint8Array => canonicalBytes(document as CanonicalValue);

/** Every record of `kind` the first grammar entry lists, owned and halo, as the objects in the lists. */
export const recordsOf = (document: any, kind: string): any[] =>
  [...document.grammars[0].owned, ...document.grammars[0].halo].filter((record: any) => record.kind === kind);

/** Sort one membership list the way the document requires: kind, then version, then identity. */
export function sortList(records: any[]): void {
  records.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind < b.kind ? -1 : 1;
    if (a.version !== b.version) return a.version - b.version;
    return a.fields.identity < b.fields.identity ? -1 : 1;
  });
}

export const scratch = (label: string): string => mkdtempSync(join(tmpdir(), `loom-tess-${label}-`));

function uuidBytes(text: string): Buffer {
  return Buffer.from(text.replace(/-/g, ''), 'hex');
}

/** RFC 4122 version 5, as Python's `uuid.uuid5`. */
export function uuid5(namespace: string, name: string): string {
  const hash = createHash('sha1').update(uuidBytes(namespace)).update(Buffer.from(name, 'utf8')).digest();
  hash[6] = (hash[6]! & 0x0f) | 0x50;
  hash[8] = (hash[8]! & 0x3f) | 0x80;
  const hex = hash.subarray(0, 16).toString('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

const NAMESPACE_URL = '6ba7b811-9dad-11d1-80b4-00c04fd430c8';

/** `exulanica.grammar.subjects.subject_identity`. */
export function subjectIdentity(root: string, subjectKind: string, owner: string, ordinal: number): string {
  const namespace = uuid5(NAMESPACE_URL, 'https://exulanica.invalid/grammar/subject');
  return uuid5(namespace, canonicalJson(['exulanica.grammar.subject/v1', 'city', root, subjectKind, owner, ordinal]));
}

/** The terrain role's code, `exulanica.grammar.grammars.city.common.SURFACE_ROLE_CODES["terrain"]`. */
const TERRAIN_ROLE_CODE = 20;

/**
 * The fixture with a material record dressing its terrain. TEST ONLY: the city grammar admits no
 * terrain material in version 2 and its material catalog lists no set for the role, so the
 * grammar's own validator refuses this document. Core does not read catalogs, so it reads it, and
 * the render path has a drawn range to hold and to break.
 */
export function dressedTerrainObject(): any {
  const document = fixtureObject();
  const grammar = document.grammars[0];
  const terrain = recordsOf(document, 'city.terrain')[0];
  grammar.owned.push({
    kind: 'city.surface_material',
    version: 2,
    fields: {
      base_weathering_millionths: 0,
      course_module_mm: 0,
      identity: subjectIdentity(grammar.subject_identity, 'surface_material', terrain.fields.identity, TERRAIN_ROLE_CODE),
      material: 'carriageway_asphalt',
      mortar_module_mm: 0,
      repeat_size_millionths: 1_000_000,
      reveal_darkening_millionths: 0,
      role: 'terrain',
      // Zero on every role but glazing, which the grammar's soil_band_role rule holds.
      soil_band_bottom_mm: 0,
      soil_band_edge_mm: 0,
      soiling_gradient_millionths: 0,
      surface_identity: terrain.fields.identity,
      surface_kind: 'city.terrain',
      texture_set_id: 'cc0.carriageway-asphalt',
      uv_offset_u_mm: 0,
      uv_offset_v_mm: 0,
      uv_rotation_urad: 0,
    },
  });
  sortList(grammar.owned);
  return document;
}

/** Plan boxes of every record whose stated extent covers the ground: all but terrain and districts. */
export function coveringBoxes(document: any): { min_x: number; min_y: number; max_x: number; max_y: number }[] {
  const grammar = document.grammars[0];
  return [...grammar.owned, ...grammar.halo]
    .filter((record: any) => record.fields.extent !== undefined)
    .filter((record: any) => record.kind !== 'city.terrain' && record.kind !== 'city.district')
    .map((record: any) => ({
      min_x: record.fields.extent.min_x_mm,
      min_y: record.fields.extent.min_y_mm,
      max_x: record.fields.extent.max_x_mm,
      max_y: record.fields.extent.max_y_mm,
    }));
}
