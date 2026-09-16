import { describe, expect, it } from 'vitest';
import {
  DEFAULT_REPRESENTATION_INTENT,
  artifactByteWindow,
  districtRepresentationSubjects,
  representationBinaryVisualization,
  representationIntent,
  representationSampleIndices,
  resolveRepresentation,
  type RepresentationSubject,
} from '../src/representation.js';
import type { OwnedDistrict } from '../src/owned-district.js';

const subject = (changes: Partial<RepresentationSubject> = {}): RepresentationSubject => ({
  subjectId: 'artifact:one', subjectKind: 'scene', sceneId: 'scene:one',
  frameId: 'scene:one', origin: 'inferred', sourceRefs: ['sha:one'],
  availability: 'available', rendered: true, points: 'retained-points',
  compatibleBlend: true,
  bounds: { frameId: 'scene:one', units: 'scene-units', origin: 'inferred', basis: 'source-bounds',
    min: [0, 0, 0], max: [1, 2, 3] },
  label: 'wall', dataAvailable: true, unavailableReason: null, ...changes,
});

describe('representation capability resolution', () => {
  it('blends only a compatible retained representation and keeps overlays separate', () => {
    const resolved = resolveRepresentation({
      ...DEFAULT_REPRESENTATION_INTENT, pointMix: 0.25, boxes: true,
      labels: true, ids: true, data: true, binary: 'visualization',
    }, subject());
    expect(resolved).toMatchObject({ renderedWeight: 0.75, pointWeight: 0.25,
      boxes: true, labels: true, ids: true, data: true, binary: true,
      geometryVisible: true, pointLabel: 'Retained points' });
  });

  it('reports endpoint-only and absent forms instead of inventing a blend', () => {
    const intent = { ...DEFAULT_REPRESENTATION_INTENT, pointMix: 0.5 };
    expect(resolveRepresentation(intent, subject({ compatibleBlend: false }))).toMatchObject({
      renderedWeight: 1, pointWeight: 0,
    });
    expect(resolveRepresentation(intent, subject({ points: null, compatibleBlend: false,
      unavailableReason: 'No retained point buffer.' })).reasons).toContain('No retained point buffer.');
  });

  it('lets withdrawal and parent visibility defeat every geometry request', () => {
    for (const item of [
      resolveRepresentation({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1 },
        subject({ availability: 'withdrawn', unavailableReason: 'Rights withdrawn.' })),
      resolveRepresentation({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 1 }, subject(), false),
    ]) expect(item).toMatchObject({ renderedWeight: 0, pointWeight: 0, geometryVisible: false });
    expect(resolveRepresentation({ ...DEFAULT_REPRESENTATION_INTENT, data: true }, subject(), false))
      .toMatchObject({ geometryVisible: false, data: true });
  });

  it('rejects malformed intents, frames, bounds and capability combinations', () => {
    expect(() => representationIntent({ ...DEFAULT_REPRESENTATION_INTENT, pointMix: 2 })).toThrow();
    expect(() => resolveRepresentation(DEFAULT_REPRESENTATION_INTENT,
      subject({ compatibleBlend: true, points: null }))).toThrow();
    expect(() => resolveRepresentation(DEFAULT_REPRESENTATION_INTENT,
      subject({ bounds: { frameId: '', units: 'scene-units', origin: 'inferred', basis: 'source-bounds',
        min: [2, 0, 0], max: [1, 1, 1] } }))).toThrow();
  });
});

describe('bounded data and source-address helpers', () => {
  it('samples deterministic existing addresses including a stable last interval', () => {
    expect([...representationSampleIndices(10, 4)]).toEqual([0, 2, 5, 7]);
    expect([...representationSampleIndices(2, 4)]).toEqual([0, 1]);
    expect([...representationSampleIndices(0, 4)]).toEqual([]);
    expect(() => representationSampleIndices(10, 65_537)).toThrow();
  });

  it('formats only the supplied bounded artifact byte window', () => {
    expect(artifactByteWindow(new Uint8Array([0, 1, 254, 255]), 1, 2)).toEqual({
      offset: 1, totalBytes: 4, hex: '01 fe', binary: '00000001 11111110',
    });
    expect(() => artifactByteWindow(new Uint8Array(300), 0, 257)).toThrow();
  });

  it('labels deterministic decorative bits as generated rather than raw data', () => {
    const first = representationBinaryVisualization('building:1', 32);
    expect(first).toEqual(representationBinaryVisualization('building:1', 32));
    expect(first.label).toBe('Generated binary visualization, not artifact bytes');
    expect(first.bits).toMatch(/^[01]{32}$/u);
  });
});

describe('district semantic subjects', () => {
  it('uses actual per-building records and their declared district frame', () => {
    const district = {
      district_id: 'flatiron', frame: { name: 'flatiron-local-mm' },
      source_records: [{ sha256: 'a'.repeat(64), operation_rights: { display: true } }],
      buildings: [{ id: 'doitt_id:1', name: 'Library', bbox_cm: [100, 200, 500, 800],
        height_cm: 1200 }],
    } as unknown as OwnedDistrict;
    expect(districtRepresentationSubjects(district)[0]).toMatchObject({
      subjectId: 'doitt_id:1', subjectKind: 'object',
      frameId: 'flatiron-local-mm:render-metres',
      origin: 'external', sourceRefs: ['a'.repeat(64)], label: 'Library',
      compatibleBlend: false, points: null,
      bounds: { units: 'metres', min: [1, 0, 2], max: [5, 12, 8], basis: 'source-bounds' },
    });
  });
});
