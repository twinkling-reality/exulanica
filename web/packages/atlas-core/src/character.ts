/** Shared runtime appearance, never a person-identity or society-state authority. */
import type { AnchorId, EntityId, EvidenceRef, IslandId, OccurrenceId } from './ids.js';

export const CHARACTER_PROFILE = 'exulanica.character/v1' as const;
export const ABSTRACT_CHARACTER_RIG = 'abstract-human/v1' as const;

export type CharacterSubject =
  | { readonly kind: 'player'; readonly playerId: string }
  | { readonly kind: 'synthetic-inhabitant'; readonly societyId: string;
      readonly branchId: string; readonly inhabitantId: string }
  | { readonly kind: 'scene-person'; readonly sceneId: string; readonly captureId: string;
      readonly personRegionId: string; readonly anchorId: AnchorId | null;
      readonly islandId: IslandId | null; readonly occurrenceId: OccurrenceId | null;
      /** Only an externally confirmed entity link, never an appearance-derived match. */
      readonly entityId: EntityId | null; readonly identityLink: 'unlinked' | 'confirmed' };

export type CharacterOrigin = 'observed' | 'authored' | 'generated';
export type CharacterMotion = 'idle' | 'walk' | 'run' | 'start' | 'stop' | 'turn';

/** Opaque asset/evidence references, resolved and authorized outside atlas-core. No URLs or pixels. */
export interface CharacterSourceRef {
  readonly assetId: string;
  readonly contentSha256: string;
  readonly purpose: 'face' | 'body' | 'texture' | 'proportions';
  readonly origin: CharacterOrigin;
  readonly producer: string;
  readonly revision: string;
  readonly rigProfile: string | null;
  readonly evidenceRefs: readonly EvidenceRef[];
}

export type CharacterBodyTrait = 'heightMm' | 'shoulderWidthMm' | 'hipWidthMm'
  | 'headRatioMilli' | 'legRatioMilli' | 'armRatioMilli';
export interface CharacterTraitProvenance {
  readonly origin: CharacterOrigin;
  readonly sourceRefs: readonly CharacterSourceRef[];
}
const BODY_TRAITS: readonly CharacterBodyTrait[] = ['heightMm', 'shoulderWidthMm', 'hipWidthMm',
  'headRatioMilli', 'legRatioMilli', 'armRatioMilli'];

export interface CharacterBody {
  readonly heightMm: number;
  readonly shoulderWidthMm: number;
  readonly hipWidthMm: number;
  /** Ratios are thousandths of total standing height: crown-to-chin, hip-to-ground
   * including feet, and shoulder-to-fingertip respectively. Widths are neutral-pose spans. */
  readonly headRatioMilli: number;
  readonly legRatioMilli: number;
  readonly armRatioMilli: number;
  readonly provenance: Readonly<Record<CharacterBodyTrait, CharacterTraitProvenance>>;
}

export interface AbstractCharacterAppearance {
  readonly kind: 'abstract';
  readonly preset: 'soft-human/v1';
  readonly surface: 'blank' | 'color';
  readonly palette: { readonly head: string; readonly torso: string;
    readonly limbs: string; readonly accent: string };
  readonly origin: 'authored' | 'generated';
}

export type CharacterAppearance = AbstractCharacterAppearance | {
  readonly kind: 'sourced';
  readonly sources: readonly CharacterSourceRef[];
  readonly fallback: AbstractCharacterAppearance;
};

export interface CharacterRepresentation {
  readonly profile: typeof CHARACTER_PROFILE;
  /** Content/LOD representation identity. Never substituted for the bound subject's identity. */
  readonly representationId: string;
  readonly revision: number;
  readonly subject: CharacterSubject;
  readonly body: CharacterBody;
  readonly appearance: CharacterAppearance;
  readonly rig: {
    /** Native profiles retain the exact source rig ID; imported rigs require a pinned body receipt. */
    readonly profile: string;
    readonly source?: CharacterSourceRef;
    readonly motions: readonly CharacterMotion[];
    /** Supplied by traversal authority; visual height never changes collision policy. */
    readonly traversal: { readonly radiusMm: number; readonly heightMm: number } | null };
  readonly lod: { readonly level: 'near' | 'mid' | 'far' };
}

const authoredTrait: CharacterTraitProvenance = Object.freeze({ origin: 'authored', sourceRefs: Object.freeze([]) });
export const DEFAULT_CHARACTER_BODY: CharacterBody = Object.freeze({
  heightMm: 1820, shoulderWidthMm: 400, hipWidthMm: 270,
  headRatioMilli: 167, legRatioMilli: 484, armRatioMilli: 320,
  provenance: Object.freeze({ heightMm: authoredTrait, shoulderWidthMm: authoredTrait,
    hipWidthMm: authoredTrait, headRatioMilli: authoredTrait, legRatioMilli: authoredTrait,
    armRatioMilli: authoredTrait }),
});
export const DEFAULT_CHARACTER_APPEARANCE: AbstractCharacterAppearance = Object.freeze({
  kind: 'abstract', preset: 'soft-human/v1', surface: 'color', origin: 'authored',
  palette: Object.freeze({ head: '#d5e4f2', torso: '#193d79', limbs: '#193d79', accent: '#758fba' }),
});

type RecordValue = Record<string, unknown>;
function record(value: unknown, keys: readonly string[], label: string): RecordValue {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`Invalid ${label}`);
  }
  const result = value as RecordValue;
  const actual = Object.keys(result).sort();
  if (actual.length !== keys.length || actual.some((key, i) => key !== [...keys].sort()[i])) {
    throw new TypeError(`Unexpected ${label} fields`);
  }
  return result;
}
function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length < 1 || value.length > 1000 || /[\u0000-\u001f]/u.test(value)) {
    throw new TypeError(`Invalid ${label}`);
  }
  return value;
}
function nullableText(value: unknown, label: string): string | null {
  return value === null ? null : text(value, label);
}
function integer(value: unknown, min: number, max: number, label: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) {
    throw new TypeError(`Invalid ${label}`);
  }
  return value;
}
function choice<T extends string>(value: unknown, choices: readonly T[], label: string): T {
  if (typeof value !== 'string' || !choices.includes(value as T)) throw new TypeError(`Invalid ${label}`);
  return value as T;
}
function array(value: unknown, max: number, label: string): readonly unknown[] {
  if (!Array.isArray(value) || value.length > max) throw new TypeError(`Invalid ${label}`);
  return value as unknown[];
}
function origin(value: unknown): CharacterOrigin {
  return choice(value, ['observed', 'authored', 'generated'], 'character origin');
}

function parseSubject(value: unknown): CharacterSubject {
  if (typeof value !== 'object' || value === null) throw new TypeError('Invalid character subject');
  const kind = (value as RecordValue)['kind'];
  if (kind === 'player') {
    const r = record(value, ['kind', 'playerId'], 'player binding');
    return { kind, playerId: text(r['playerId'], 'player ID') };
  }
  if (kind === 'synthetic-inhabitant') {
    const r = record(value, ['kind', 'societyId', 'branchId', 'inhabitantId'], 'simulation binding');
    return { kind, societyId: text(r['societyId'], 'society ID'), branchId: text(r['branchId'], 'branch ID'),
      inhabitantId: text(r['inhabitantId'], 'inhabitant ID') };
  }
  if (kind !== 'scene-person') throw new TypeError('Unsupported character subject');
  const r = record(value, ['kind', 'sceneId', 'captureId', 'personRegionId', 'anchorId', 'islandId',
    'occurrenceId', 'entityId', 'identityLink'], 'scene-person binding');
  const entityId = nullableText(r['entityId'], 'entity ID') as EntityId | null;
  const identityLink = choice(r['identityLink'], ['unlinked', 'confirmed'], 'identity link');
  if ((entityId !== null) !== (identityLink === 'confirmed')) throw new TypeError('Unconfirmed entity binding');
  const anchorId = nullableText(r['anchorId'], 'anchor ID') as AnchorId | null;
  const islandId = nullableText(r['islandId'], 'island ID') as IslandId | null;
  const occurrenceId = nullableText(r['occurrenceId'], 'occurrence ID') as OccurrenceId | null;
  if (anchorId !== null && (islandId === null || occurrenceId === null)) {
    throw new TypeError('Anchor binding requires its existing island and occurrence');
  }
  return { kind, sceneId: text(r['sceneId'], 'scene ID'), captureId: text(r['captureId'], 'capture ID'),
    personRegionId: text(r['personRegionId'], 'person region ID'), anchorId, islandId,
    occurrenceId, entityId, identityLink };
}

function parseSource(value: unknown): CharacterSourceRef {
  const r = record(value, ['assetId', 'contentSha256', 'purpose', 'origin', 'producer', 'revision',
    'rigProfile', 'evidenceRefs'], 'character source');
  const digest = text(r['contentSha256'], 'asset digest');
  if (!/^[0-9a-f]{64}$/u.test(digest)) throw new TypeError('Invalid asset digest');
  const evidenceRefs = array(r['evidenceRefs'], 32, 'evidence refs')
    .map((ref) => text(ref, 'evidence ref') as EvidenceRef);
  if (new Set(evidenceRefs).size !== evidenceRefs.length) throw new TypeError('Duplicate evidence ref');
  const sourceOrigin = origin(r['origin']);
  if (sourceOrigin === 'observed' && evidenceRefs.length === 0) {
    throw new TypeError('Observed character source requires evidence references');
  }
  const purpose = choice(r['purpose'], ['face', 'body', 'texture', 'proportions'] as const, 'source purpose');
  if (purpose === 'body' && r['rigProfile'] === null) throw new TypeError('Sourced body requires an explicit rig');
  return { assetId: text(r['assetId'], 'asset ID'), contentSha256: digest,
    purpose,
    origin: sourceOrigin, producer: text(r['producer'], 'source producer'),
    revision: text(r['revision'], 'source revision'), rigProfile: nullableText(r['rigProfile'], 'source rig'),
    evidenceRefs };
}
function parseSources(value: unknown): readonly CharacterSourceRef[] {
  const sources = array(value, 8, 'character sources').map(parseSource);
  const keys = sources.map((s) => `${s.purpose}:${s.assetId}`);
  if (new Set(keys).size !== keys.length) throw new TypeError('Duplicate character source');
  return sources;
}
function parseBody(value: unknown): CharacterBody {
  const r = record(value, ['heightMm', 'shoulderWidthMm', 'hipWidthMm', 'headRatioMilli',
    'legRatioMilli', 'armRatioMilli', 'provenance'], 'character body');
  const provenance = record(r['provenance'], BODY_TRAITS, 'body provenance');
  const traits = {} as Record<CharacterBodyTrait, CharacterTraitProvenance>;
  for (const trait of BODY_TRAITS) {
    const value = record(provenance[trait], ['origin', 'sourceRefs'], 'trait provenance');
    const sourceRefs = parseSources(value['sourceRefs']);
    const traitOrigin = origin(value['origin']);
    if (sourceRefs.some((ref) => ref.purpose !== 'proportions')) throw new TypeError('Body requires proportion receipts');
    if (traitOrigin === 'observed' && (sourceRefs.length === 0 || sourceRefs.some((ref) => ref.origin !== 'observed'))) {
      throw new TypeError('Observed body requires observed proportion receipts');
    }
    traits[trait] = { origin: traitOrigin, sourceRefs };
  }
  const result = { heightMm: integer(r['heightMm'], 300, 3000, 'height'),
    shoulderWidthMm: integer(r['shoulderWidthMm'], 80, 1200, 'shoulder width'),
    hipWidthMm: integer(r['hipWidthMm'], 80, 1200, 'hip width'),
    headRatioMilli: integer(r['headRatioMilli'], 80, 220, 'head ratio'),
    legRatioMilli: integer(r['legRatioMilli'], 350, 650, 'leg ratio'),
    armRatioMilli: integer(r['armRatioMilli'], 300, 600, 'arm ratio'),
    provenance: traits };
  if (result.shoulderWidthMm > result.heightMm * 0.75 || result.hipWidthMm > result.heightMm * 0.75
      || result.headRatioMilli + result.legRatioMilli > 850) throw new TypeError('Incompatible body proportions');
  return result;
}
function parseAbstract(value: unknown): AbstractCharacterAppearance {
  const r = record(value, ['kind', 'preset', 'surface', 'palette', 'origin'], 'abstract appearance');
  const palette = record(r['palette'], ['head', 'torso', 'limbs', 'accent'], 'character palette');
  const color = (name: string): string => {
    const value = palette[name];
    if (typeof value !== 'string' || !/^#[0-9a-f]{6}$/u.test(value)) throw new TypeError('Invalid character color');
    return value;
  };
  return { kind: choice(r['kind'], ['abstract'], 'appearance kind'),
    preset: choice(r['preset'], ['soft-human/v1'], 'abstract preset'),
    surface: choice(r['surface'], ['blank', 'color'], 'abstract surface'),
    palette: { head: color('head'), torso: color('torso'), limbs: color('limbs'), accent: color('accent') },
    origin: choice(r['origin'], ['authored', 'generated'], 'abstract appearance origin') };
}
function parseAppearance(value: unknown): CharacterAppearance {
  if (typeof value !== 'object' || value === null) throw new TypeError('Invalid character appearance');
  if ((value as RecordValue)['kind'] === 'abstract') return parseAbstract(value);
  const r = record(value, ['kind', 'sources', 'fallback'], 'sourced appearance');
  choice(r['kind'], ['sourced'], 'appearance kind');
  const sources = parseSources(r['sources']);
  if (sources.length === 0 || sources.some((ref) => ref.purpose === 'proportions')) {
    throw new TypeError('Sourced appearance requires face, body or texture references');
  }
  return { kind: 'sourced', sources, fallback: parseAbstract(r['fallback']) };
}

/** Strict closed runtime boundary; this validates a declaration, never resolves identity or permission. */
export function parseCharacterRepresentation(value: unknown): CharacterRepresentation {
  const r = record(value, ['profile', 'representationId', 'revision', 'subject', 'body', 'appearance',
    'rig', 'lod'], 'character representation');
  const hasRigSource = typeof r['rig'] === 'object' && r['rig'] !== null && Object.hasOwn(r['rig'], 'source');
  const rig = record(r['rig'], hasRigSource ? ['profile', 'source', 'motions', 'traversal'] : ['profile', 'motions', 'traversal'], 'character rig');
  const rigProfile = text(rig['profile'], 'character rig profile');
  const rigSource = rig['source'] === undefined ? undefined : parseSource(rig['source']);
  const appearance = parseAppearance(r['appearance']);
  if (rigProfile === ABSTRACT_CHARACTER_RIG) {
    if (rigSource !== undefined) throw new TypeError('Abstract rig cannot carry an imported rig source');
  } else {
    if (rigSource === undefined || rigSource.purpose !== 'body' || rigSource.rigProfile !== rigProfile
        || appearance.kind !== 'sourced' || !appearance.sources.some(source =>
          source.purpose === 'body' && source.assetId === rigSource.assetId
          && source.contentSha256 === rigSource.contentSha256 && source.rigProfile === rigProfile
          && source.origin === rigSource.origin && source.producer === rigSource.producer
          && source.revision === rigSource.revision
          && JSON.stringify(source.evidenceRefs) === JSON.stringify(rigSource.evidenceRefs))) {
      throw new TypeError('Imported rig requires its matching pinned body source and provenance');
    }
  }
  const traversal = rig['traversal'] === null ? null : record(rig['traversal'], ['radiusMm', 'heightMm'], 'traversal envelope');
  const motions = array(rig['motions'], 6, 'rig motions')
    .map((m) => choice<CharacterMotion>(m, ['idle', 'walk', 'run', 'start', 'stop', 'turn'], 'motion'));
  if (!motions.includes('idle') || new Set(motions).size !== motions.length) throw new TypeError('Invalid rig motion set');
  const lod = record(r['lod'], ['level'], 'character LOD');
  return { profile: choice(r['profile'], [CHARACTER_PROFILE], 'character profile'),
    representationId: text(r['representationId'], 'representation ID'),
    revision: integer(r['revision'], 1, Number.MAX_SAFE_INTEGER, 'representation revision'),
    subject: parseSubject(r['subject']), body: parseBody(r['body']), appearance,
    rig: { profile: rigProfile, ...(rigSource === undefined ? {} : { source: rigSource }), motions,
      traversal: traversal === null ? null : { radiusMm: integer(traversal['radiusMm'], 1, 2000, 'traversal radius'),
        heightMm: integer(traversal['heightMm'], 1, 10000, 'traversal height') } },
    lod: { level: choice(lod['level'], ['near', 'mid', 'far'], 'character LOD') } };
}

/** Namespacing remains explicit, and even confirmed scene instances are never merged by this key. */
export function characterSubjectKey(subject: CharacterSubject): string {
  const s = parseSubject(subject);
  if (s.kind === 'player') return JSON.stringify([s.kind, s.playerId]);
  if (s.kind === 'synthetic-inhabitant') return JSON.stringify([s.kind, s.societyId, s.branchId, s.inhabitantId]);
  return JSON.stringify([s.kind, s.sceneId, s.captureId, s.personRegionId]);
}

/** Use before replacing a cached representation; LOD/palette changes cannot rebind its subject. */
export function validateCharacterReplacement(previous: CharacterRepresentation, next: CharacterRepresentation): void {
  const before = parseCharacterRepresentation(previous);
  const after = parseCharacterRepresentation(next);
  if (before.representationId !== after.representationId || after.revision <= before.revision
      || characterSubjectKey(before.subject) !== characterSubjectKey(after.subject)) {
    throw new TypeError('Character replacement must retain identity and advance its revision');
  }
}

export type CharacterSourceAvailability = 'available' | 'unavailable' | 'withdrawn' | 'unresolved';
export interface CharacterResolutionContext {
  /** Presence is distinct from likeness; denied or unresolved presence never draws a fallback person. */
  readonly presence: 'allowed' | 'denied' | 'unresolved';
  readonly sourceAvailability?: (source: CharacterSourceRef) => CharacterSourceAvailability;
  /** Default false. Asset descriptors do not establish that the renderer can load them. */
  readonly sourcedRenderingSupported?: boolean;
  readonly supportedSourceRigProfiles?: readonly string[];
}
export interface ResolvedCharacterRepresentation {
  readonly profile: typeof CHARACTER_PROFILE;
  readonly representationId: string;
  readonly revision: number;
  readonly subject: CharacterSubject;
  readonly availability: 'abstract' | 'sourced' | 'hidden';
  readonly traversalCompatibility: 'within-declared-envelope' | 'exceeds-declared-envelope' | 'unassessed';
  readonly reason: string | null;
  readonly body: CharacterBody | null;
  readonly appearance: CharacterAppearance | null;
  readonly rig: CharacterRepresentation['rig'];
  readonly lod: CharacterRepresentation['lod'];
}

/** Re-resolve when current permissions/bytes change; never retain revoked sourced pixels or dimensions. */
export function resolveCharacterRepresentation(
  representation: CharacterRepresentation, current: CharacterResolutionContext,
): ResolvedCharacterRepresentation {
  const spec = parseCharacterRepresentation(representation);
  const base = { profile: spec.profile, representationId: spec.representationId, revision: spec.revision,
    subject: spec.subject, rig: spec.rig, lod: spec.lod };
  if (current.presence !== 'allowed') {
    return { ...base, availability: 'hidden', traversalCompatibility: 'unassessed', reason: 'presence_unavailable', body: null, appearance: null };
  }
  const refs = [...BODY_TRAITS.flatMap((trait) => spec.body.provenance[trait].sourceRefs), ...(spec.appearance.kind === 'sourced' ? spec.appearance.sources : [])];
  let failure: string | null = null;
  for (const source of refs) {
    let status: CharacterSourceAvailability = 'unresolved';
    try { status = current.sourceAvailability?.(source) ?? 'unresolved'; } catch { /* Fail closed. */ }
    if (status !== 'available') { failure = 'source_unavailable'; break; }
    if (source.rigProfile !== null && !(current.supportedSourceRigProfiles ?? []).includes(source.rigProfile)) {
      failure = 'source_rig_unsupported'; break;
    }
  }
  if (spec.appearance.kind === 'sourced' && current.sourcedRenderingSupported !== true) {
    failure ??= 'sourced_rendering_unsupported';
  }
  const fit = (body: CharacterBody): ResolvedCharacterRepresentation['traversalCompatibility'] => {
    const envelope = spec.rig.traversal;
    if (envelope === null) return 'unassessed';
    return body.heightMm <= envelope.heightMm && Math.max(body.shoulderWidthMm, body.hipWidthMm) <= envelope.radiusMm * 2
      ? 'within-declared-envelope' : 'exceeds-declared-envelope';
  };
  if (failure !== null) {
    return { ...base, rig: { profile: ABSTRACT_CHARACTER_RIG, motions: spec.rig.motions, traversal: spec.rig.traversal },
      availability: 'abstract', traversalCompatibility: fit(DEFAULT_CHARACTER_BODY), reason: failure,
      // Full generic body prevents a revoked observed height/shape from surviving texture fallback.
      body: { ...DEFAULT_CHARACTER_BODY },
      appearance: spec.appearance.kind === 'sourced' ? spec.appearance.fallback : spec.appearance };
  }
  return { ...base, availability: spec.appearance.kind === 'sourced' ? 'sourced' : 'abstract',
    traversalCompatibility: fit(spec.body), reason: null, body: spec.body, appearance: spec.appearance };
}
