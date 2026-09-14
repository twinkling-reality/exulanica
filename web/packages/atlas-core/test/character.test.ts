import { describe, expect, it } from 'vitest';
import { entityId, evidenceRef } from '../src/ids.js';
import {
  ABSTRACT_CHARACTER_RIG, CHARACTER_PROFILE, DEFAULT_CHARACTER_APPEARANCE, DEFAULT_CHARACTER_BODY,
  characterSubjectKey, parseCharacterRepresentation, resolveCharacterRepresentation,
  validateCharacterReplacement,
  type CharacterRepresentation, type CharacterSourceRef, type CharacterSubject,
} from '../src/character.js';

function spec(subject: CharacterSubject = { kind: 'player', playerId: 'local-player' }): CharacterRepresentation {
  return {
    profile: CHARACTER_PROFILE, representationId: 'character:one', revision: 1, subject,
    body: DEFAULT_CHARACTER_BODY, appearance: DEFAULT_CHARACTER_APPEARANCE,
    rig: { profile: ABSTRACT_CHARACTER_RIG, motions: ['idle', 'walk', 'run', 'start', 'stop', 'turn'], traversal: null },
    lod: { level: 'near' },
  };
}
function source(purpose: CharacterSourceRef['purpose'] = 'texture'): CharacterSourceRef {
  return { assetId: 'authorized-asset', contentSha256: 'a'.repeat(64), purpose, origin: 'observed',
    producer: 'reviewed-source-adapter/v1', revision: 'source-revision-2', rigProfile: null,
    evidenceRefs: [evidenceRef('opaque-evidence-handle')] };
}
function sourced(): CharacterRepresentation {
  const base = spec();
  return { ...base, appearance: { kind: 'sourced', sources: [source()], fallback: DEFAULT_CHARACTER_APPEARANCE },
    body: { ...base.body, heightMm: 1950, provenance: { ...base.body.provenance,
      heightMm: { origin: 'observed', sourceRefs: [source('proportions')] } } } };
}
const scene: CharacterSubject = { kind: 'scene-person', sceneId: 'scene-1', captureId: 'capture-1',
  personRegionId: 'region-1', anchorId: null, islandId: null, occurrenceId: null,
  entityId: null, identityLink: 'unlinked' };

describe('shared character representation declaration', () => {
  it('supports player, simulation and unlinked scene subjects without merging their IDs', () => {
    const subjects: CharacterSubject[] = [
      { kind: 'player', playerId: 'same-id' },
      { kind: 'synthetic-inhabitant', societyId: 'society-1', branchId: 'branch-1', inhabitantId: 'same-id' },
      scene,
    ];
    expect(new Set(subjects.map(characterSubjectKey)).size).toBe(3);
    for (const subject of subjects) {
      const parsed = parseCharacterRepresentation(spec(subject));
      expect(parsed.subject).toEqual(subject);
      expect(parsed.body.heightMm).toBe(1820);
      expect(parsed.body.provenance.heightMm.origin).toBe('authored');
    }
    expect(characterSubjectKey(subjects[1]!)).not.toBe(characterSubjectKey({
      kind: 'synthetic-inhabitant', societyId: 'society-1', branchId: 'other', inhabitantId: 'same-id',
    }));
  });

  it('retains subject identity across LOD/appearance replacement but rejects rebinding', () => {
    const before = spec();
    const after: CharacterRepresentation = { ...before, revision: 2, lod: { level: 'far' },
      appearance: { ...DEFAULT_CHARACTER_APPEARANCE, palette: {
        ...DEFAULT_CHARACTER_APPEARANCE.palette, torso: '#304080',
      } } };
    expect(() => validateCharacterReplacement(before, after)).not.toThrow();
    expect(characterSubjectKey(after.subject)).toBe(characterSubjectKey(before.subject));
    expect(() => validateCharacterReplacement(before, { ...after, subject: { kind: 'player', playerId: 'other' } })).toThrow();
    expect(() => validateCharacterReplacement(before, { ...after, revision: 1 })).toThrow();
  });

  it('requires a confirmed external entity link and preserves anonymous scene observations', () => {
    expect(parseCharacterRepresentation(spec(scene)).subject).toEqual(scene);
    expect(() => parseCharacterRepresentation({ ...spec(scene), subject: { ...scene, entityId: entityId('entity-1') } })).toThrow();
    const confirmed = { ...scene, entityId: entityId('entity-1'), identityLink: 'confirmed' as const };
    expect(parseCharacterRepresentation(spec(confirmed)).subject).toEqual(confirmed);
    expect(() => parseCharacterRepresentation({ ...spec(scene), subject: { ...scene, inhabitantId: 'invented-merge' } })).toThrow();
  });

  it('does not label arbitrary dimensions as observed without proportion evidence', () => {
    const base = spec();
    expect(() => parseCharacterRepresentation({ ...base, body: { ...base.body,
      provenance: { ...base.body.provenance, heightMm: { origin: 'observed', sourceRefs: [] } },
    } })).toThrow();
    const observed = parseCharacterRepresentation(sourced());
    expect(observed.body.provenance.heightMm.origin).toBe('observed');
    expect(observed.body.provenance.hipWidthMm.origin).toBe('authored');
    expect(() => parseCharacterRepresentation({ ...sourced(), appearance: { kind: 'sourced',
      sources: [{ ...source(), evidenceRefs: [] }], fallback: DEFAULT_CHARACTER_APPEARANCE } })).toThrow();
  });

  it.each([
    { ...spec(), profile: 'unknown' },
    { ...spec(), revision: true },
    { ...spec(), displayName: 'inferred biography' },
    { ...spec(), body: { ...DEFAULT_CHARACTER_BODY, heightMm: Number.NaN } },
    { ...spec(), body: { ...DEFAULT_CHARACTER_BODY, legRatioMilli: 900 } },
    { ...spec(), rig: { profile: 'unknown-rig', motions: ['idle'], traversal: null } },
    { ...spec(), rig: { profile: ABSTRACT_CHARACTER_RIG, motions: ['rest'], traversal: null } },
    { ...spec(), appearance: { ...DEFAULT_CHARACTER_APPEARANCE, palette: { ...DEFAULT_CHARACTER_APPEARANCE.palette, head: 'url(https://example.com)' } } },
  ])('rejects unsupported, malformed or executable representation content', (value) => {
    expect(() => parseCharacterRepresentation(value)).toThrow(TypeError);
  });
});

describe('current permission and compatibility resolution', () => {
  it('defaults unavailable sourced rendering to deliberate abstract fallback', () => {
    const original = sourced();
    const resolved = resolveCharacterRepresentation(original, { presence: 'allowed' });
    expect(resolved.availability).toBe('abstract');
    expect(resolved.subject).toEqual(original.subject);
    expect(resolved.body).toEqual(DEFAULT_CHARACTER_BODY);
    expect(resolved.appearance).toEqual(DEFAULT_CHARACTER_APPEARANCE);
    expect(JSON.stringify(resolved)).not.toContain('authorized-asset');
    expect(original.body.heightMm).toBe(1950);
  });

  it('removes observed proportions even when only a texture source has become unavailable', () => {
    const original = sourced();
    const ready = resolveCharacterRepresentation(original, { presence: 'allowed',
      sourceAvailability: () => 'available', sourcedRenderingSupported: true });
    expect(ready.availability).toBe('sourced');
    expect(ready.body?.heightMm).toBe(1950);
    const revoked = resolveCharacterRepresentation(original, { presence: 'allowed',
      sourceAvailability: (ref) => ref.purpose === 'texture' ? 'withdrawn' : 'available',
      sourcedRenderingSupported: true });
    expect(revoked.availability).toBe('abstract');
    expect(revoked.body?.heightMm).toBe(1820);
    expect(revoked.representationId).toBe(ready.representationId);
    expect(revoked.subject).toEqual(ready.subject);
    expect(JSON.stringify(revoked)).not.toContain('authorized-asset');
  });

  it.each(['denied', 'unresolved'] as const)('hides presence rather than showing a blank person when %s', (presence) => {
    const resolved = resolveCharacterRepresentation(spec(scene), { presence });
    expect(resolved.availability).toBe('hidden');
    expect(resolved.appearance).toBeNull();
    expect(resolved.body).toBeNull();
    expect(resolved.subject).toEqual(scene);
  });

  it('requires a body asset to declare its rig rather than assuming compatibility', () => {
    expect(() => parseCharacterRepresentation({ ...spec(), appearance: { kind: 'sourced',
      sources: [source('body')], fallback: DEFAULT_CHARACTER_APPEARANCE } })).toThrow(TypeError);
  });

  it('fails closed on resolver failure and unsupported source rigs', () => {
    expect(resolveCharacterRepresentation(sourced(), { presence: 'allowed',
      sourceAvailability: () => { throw new Error('no current permission'); },
    }).availability).toBe('abstract');
    const value = sourced();
    const incompatible: CharacterRepresentation = { ...value, appearance: { kind: 'sourced',
      sources: [{ ...source('body'), rigProfile: 'different-rig/v1' }], fallback: DEFAULT_CHARACTER_APPEARANCE } };
    expect(resolveCharacterRepresentation(incompatible, { presence: 'allowed',
      sourceAvailability: () => 'available', sourcedRenderingSupported: true,
      supportedSourceRigProfiles: [ABSTRACT_CHARACTER_RIG],
    }).reason).toBe('source_rig_unsupported');
  });

  it('reports dimensions outside the traversal envelope without changing collision policy', () => {
    const value: CharacterRepresentation = { ...spec(), rig: { ...spec().rig,
      traversal: { radiusMm: 180, heightMm: 1700 } } };
    const resolved = resolveCharacterRepresentation(value, { presence: 'allowed' });
    expect(resolved.traversalCompatibility).toBe('exceeds-declared-envelope');
    expect(resolved.rig.traversal).toEqual({ radiusMm: 180, heightMm: 1700 });
    expect(resolved.body?.heightMm).toBe(1820);
    expect(resolveCharacterRepresentation(spec(), { presence: 'allowed' }).traversalCompatibility).toBe('unassessed');
  });
});


describe('pinned imported rig representation', () => {
  const rigProfile = 'quaternius-modular/men/81099af88b304deba9f53be5a68d9af82c3f58107828fec28393a39fe12554eb';
  const bodySource: CharacterSourceRef = { assetId: 'quaternius.modular.hoodie.v2',
    contentSha256: '7d026bd1bac1a4c2e9e4785af4a1c3ed13d0abae2c870798654f816ec8d78d2d',
    purpose: 'body', origin: 'authored', producer: 'quaternius-modular-prepare/2',
    revision: '2', rigProfile, evidenceRefs: [] };
  const imported = (): CharacterRepresentation => ({ ...spec(),
    appearance: { kind: 'sourced', sources: [bodySource], fallback: DEFAULT_CHARACTER_APPEARANCE },
    rig: { profile: rigProfile, source: bodySource, motions: ['idle', 'walk', 'run'], traversal: null } });
  it('retains the actual rig ID, pinned body bytes and provenance', () => {
    expect(parseCharacterRepresentation(imported()).rig.source).toEqual(bodySource);
    expect(resolveCharacterRepresentation(imported(), { presence: 'allowed', sourcedRenderingSupported: true,
      supportedSourceRigProfiles: [rigProfile], sourceAvailability: () => 'available' }).availability).toBe('sourced');
  });
  it('rejects missing or mismatched rig receipts and abstract relabeling', () => {
    const value = imported();
    for (const rig of [
      { ...value.rig, source: { ...bodySource, contentSha256: 'a'.repeat(64) } },
      { ...value.rig, source: { ...bodySource, producer: 'unrelated' } },
      { ...value.rig, profile: ABSTRACT_CHARACTER_RIG },
      { profile: rigProfile, motions: ['idle'], traversal: null },
    ]) expect(() => parseCharacterRepresentation({ ...value, rig })).toThrow();
  });
  it('withdrawal removes imported rendering and returns an actual abstract rig', () => {
    const resolved = resolveCharacterRepresentation(imported(), { presence: 'allowed', sourcedRenderingSupported: true,
      supportedSourceRigProfiles: [rigProfile], sourceAvailability: () => 'withdrawn' });
    expect(resolved.availability).toBe('abstract');
    expect(resolved.rig.profile).toBe(ABSTRACT_CHARACTER_RIG);
    expect(resolved.rig.source).toBeUndefined();
    expect(resolved.subject).toEqual(imported().subject);
    expect(resolveCharacterRepresentation(imported(), { presence: 'denied' }).availability).toBe('hidden');
  });
});
