import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  DEFAULT_REPRESENTATION_INTENT,
  GENERATED_ANONYMOUS_RECORD_KINDS,
  GENERATED_IDENTITY_RECORD_KINDS,
  generatedRecordSubject,
  resolveRepresentation,
  type GeneratedRecordPayload,
  type GeneratedRecordRegistration,
  type GeneratedTileReference,
} from '../src/representation.js';

/** Real city.v1 record shapes, built and validated by the Python grammar. See the file's description. */
const fixture = JSON.parse(readFileSync(new URL('./generated-street-records.json', import.meta.url), 'utf8')) as {
  readonly grammar: string;
  readonly records: readonly GeneratedRecordPayload[];
};

const tile: GeneratedTileReference = {
  tileX: 3, tileY: -2, lod: 0,
  frameId: 'city.v1:tile:3:-2:render-metres',
  inputsDigest: 'b'.repeat(64),
};

/** Extents a tessellator would report, in integer millimetres. Invented for the fixture. */
const EXTENTS: Readonly<Record<string, GeneratedRecordRegistration['extentMm']>> = {
  'city.massing': { min: [0, 0, 0], max: [20_000, 26_400, 30_000] },
  'city.facade': { min: [0, 0, -300], max: [20_000, 26_400, 0] },
  'city.surface_material': null,
  'city.vitrine': { min: [8_000, 0, -600], max: [11_000, 3_600, 0] },
  'city.premises': { min: [0, 0, 0], max: [6_000, 4_800, 12_000] },
};

const register = (record: GeneratedRecordPayload, changes: Partial<GeneratedRecordRegistration> = {}) =>
  generatedRecordSubject(tile, {
    record, extentMm: EXTENTS[record.kind] ?? null, drawnSeparately: false, availability: 'available', ...changes,
  });

const byKind = (kind: string): GeneratedRecordPayload => fixture.records.find(record => record.kind === kind)!;

describe('generated street subject contract', () => {
  it('covers every record kind the fixture was built from, and only those', () => {
    expect(fixture.grammar).toBe('city.v1');
    const known = new Set<string>([...GENERATED_IDENTITY_RECORD_KINDS, ...GENERATED_ANONYMOUS_RECORD_KINDS]);
    for (const record of fixture.records) expect(known.has(record.kind)).toBe(true);
    for (const kind of GENERATED_IDENTITY_RECORD_KINDS) expect(byKind(kind)).toBeDefined();
  });

  it('gives each identity-bearing record one generated subject that carries the record verbatim', () => {
    const ids = new Set<string>();
    for (const kind of GENERATED_IDENTITY_RECORD_KINDS) {
      const record = byKind(kind);
      const { subject, reason } = register(record);
      expect(reason).toBeNull();
      expect(subject).toMatchObject({
        subjectKind: 'object', origin: 'generated', points: 'mesh-surface-samples', rendered: true,
        sceneId: null, frameId: tile.frameId, sourceRefs: [tile.inputsDigest], label: null,
        record: { kind, version: record.version, identity: record.fields['building_identity'] },
      });
      expect(subject!.subjectId.startsWith(`generated:${kind}:${record.fields['building_identity']}:`)).toBe(true);
      ids.add(subject!.subjectId);
    }
    expect(ids.size).toBe(GENERATED_IDENTITY_RECORD_KINDS.length);
    expect(register(byKind('city.vitrine')).subject!.record!.key).toBe('edge_ordinal.0/bay_ordinal.2');
    expect(register(byKind('city.massing')).subject!.record!.key).toBe('parcel_ordinal.3');
  });

  it('states the extent of the record in metres as a generated extent, or no bounds at all', () => {
    const facade = register(byKind('city.facade')).subject!;
    expect(facade.bounds).toEqual({
      frameId: tile.frameId, units: 'metres', origin: 'generated', basis: 'generated-extent',
      min: [0, 0, -0.3], max: [20, 26.4, 0],
    });
    const material = register(byKind('city.surface_material')).subject!;
    expect(material.bounds).toBeNull();
    const resolved = resolveRepresentation({ ...DEFAULT_REPRESENTATION_INTENT, boxes: true, ids: true }, material);
    expect(resolved).toMatchObject({ boxes: false, ids: false });
    expect(resolved.reasons.join(' ')).toContain('no box or tag');
  });

  it('gives records that state no identity no subject, and says so', () => {
    for (const kind of ['city.terrain', 'city.street_node', 'city.parcel', 'city.street_furniture']) {
      const result = register(byKind(kind));
      expect(result.subject).toBeNull();
      expect(result.reason).toBe(`${kind} states no identity, so it has no subject, box or tag.`);
    }
  });

  it('crossfades only a record drawn on its own, and follows availability', () => {
    expect(register(byKind('city.massing')).subject!.compatibleBlend).toBe(false);
    expect(register(byKind('city.massing'), { drawnSeparately: true }).subject!.compatibleBlend).toBe(true);
    const withdrawn = register(byKind('city.massing'), { availability: 'withdrawn' }).subject!;
    expect(withdrawn).toMatchObject({ availability: 'withdrawn', dataAvailable: false });
    expect(resolveRepresentation({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1, boxes: true }, withdrawn))
      .toMatchObject({ geometryVisible: false, boxes: false });
  });

  it('refuses records and tiles it cannot read exactly', () => {
    const massing = byKind('city.massing');
    expect(() => register({ ...massing, kind: 'city.tree' })).toThrow('Unknown generated record kind');
    expect(() => register({ ...massing, fields: { ...massing.fields, building_identity: 'BUILDING-1' } }))
      .toThrow('canonical lowercase UUID');
    const { parcel_ordinal: _dropped, ...rest } = massing.fields;
    expect(() => register({ ...massing, fields: rest })).toThrow('parcel_ordinal');
    expect(() => register(massing, { extentMm: { min: [0, 0, 0.5], max: [1, 1, 1] } })).toThrow('integer millimetres');
    expect(() => register(massing, { extentMm: { min: [2, 0, 0], max: [1, 1, 1] } })).toThrow('ordered box');
    expect(() => generatedRecordSubject({ ...tile, inputsDigest: 'not-a-digest' }, {
      record: massing, extentMm: null, drawnSeparately: false, availability: 'available',
    })).toThrow('inputs digest');
  });
});
