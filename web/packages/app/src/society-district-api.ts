/**
 * Authenticated exact district presentation for the registered society frame.
 *
 * Speaks `GET /world/versions/{id}/society/district` (`exulanica/api/routes/society_district.py`).
 * The renderer base already on screen must agree with the authenticated artifact; this
 * client checks those bytes and does not re-serialize JSON as a pin.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import { districtCanonicalJson, parseDistrictInterpretation, parseOwnedDistrict,
  type DistrictInterpretation, type OwnedDistrict } from '@exulanica/atlas-core';

export interface SocietyDistrictScope {
  readonly worldId: string;
  readonly versionId: string;
  readonly sourceSnapshotId: string;
  readonly placeId: string;
  /** The base already installed in the renderer must agree with the authenticated artifact. */
  readonly renderedBase: OwnedDistrict;
}
export interface SocietyDistrictPlacement {
  readonly versionId: string;
  readonly regionId: string;
  /** Authored region-local millimetres + translation = district millimetres. */
  readonly translationMm: readonly [number, number, number];
  readonly boundsMm: readonly [number, number, number, number];
}
export interface SocietyDistrictView {
  readonly placement: SocietyDistrictPlacement;
  readonly base: OwnedDistrict;
  readonly interpretation: DistrictInterpretation;
  readonly baseArtifactSha256: string;
  readonly interpretationArtifactSha256: string;
  readonly currentDependencies: Readonly<Record<string, 'available'>>;
}
const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid society district response');
  return value as Record<string, unknown>;
};
const requireValue = (ok: unknown, reason: string): void => { if (!ok) throw new Error(`Society district: ${reason}`); };
const digest = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const identity = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 500;
export async function societyDistrictSha256(text: string): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), byte => byte.toString(16).padStart(2, '0')).join('');
}

/** Exact artifact bytes and existing semantic validation; no JSON reserialization as a byte pin. */
export async function parseSocietyDistrict(value: unknown, scope: SocietyDistrictScope): Promise<SocietyDistrictView> {
  // Freeze the response scope before asynchronous hashing so mutable callers cannot change it.
  const row = record(JSON.parse(JSON.stringify(value)));
  const registration = record(row['registration']);
  requireValue(row['profile'] === 'exulanica.society-district-view/v1', 'unsupported profile');
  requireValue(registration['world_id'] === scope.worldId && registration['version_id'] === scope.versionId &&
    registration['source_snapshot_id'] === scope.sourceSnapshotId && row['place_id'] === scope.placeId, 'world scope mismatch');
  const translation = registration['translation_mm'];
  requireValue(identity(registration['region_id']) && Array.isArray(translation) && translation.length === 3 &&
    translation.every(value => Number.isSafeInteger(value) && Math.abs(value) <= 1e9) &&
    registration['yaw_microradians'] === 0 && registration['scale_milli'] === 1000, 'unsupported frame registration');
  const baseJson = row['base_json'], interpretationJson = row['interpretation_json'];
  requireValue(typeof baseJson === 'string' && baseJson.length <= 8_000_000 &&
    typeof interpretationJson === 'string' && interpretationJson.length <= 16_000_000, 'missing or oversized artifact bytes');
  requireValue(digest(row['base_artifact_sha256']) && digest(row['interpretation_artifact_sha256']) &&
    digest(row['interpretation_document_sha256']), 'invalid artifact pin');
  const [baseHash, interpretationHash] = await Promise.all([
    societyDistrictSha256(baseJson as string), societyDistrictSha256(interpretationJson as string),
  ]);
  requireValue(baseHash === row['base_artifact_sha256'] && interpretationHash === row['interpretation_artifact_sha256'], 'artifact digest mismatch');
  const base = parseOwnedDistrict(JSON.parse(baseJson as string));
  requireValue(districtCanonicalJson(base) === districtCanonicalJson(scope.renderedBase), 'rendered district does not match authorized base');
  const interpretation = await parseDistrictInterpretation(JSON.parse(interpretationJson as string), base, {
    baseArtifactSha256: baseHash, sha256: societyDistrictSha256,
  });
  requireValue(interpretation.document_sha256 === row['interpretation_document_sha256'] &&
    registration['district_id'] === base.district_id && registration['frame_name'] === interpretation.frame.name, 'district frame or document mismatch');
  const current = record(row['current_dependencies']);
  const sources = interpretation.source_dependencies.map(source => source.sha256).sort();
  requireValue(Object.keys(current).sort().join(',') === sources.join(',') && sources.every(sha => current[sha] === 'available'), 'dependencies unavailable or mismatched');
  const placement: SocietyDistrictPlacement = Object.freeze({versionId:scope.versionId,regionId:registration['region_id'] as string,
    translationMm:Object.freeze([...(translation as number[])]) as unknown as readonly [number,number,number],
    boundsMm:Object.freeze(base.bounds_cm.map(value => value * 10)) as unknown as readonly [number,number,number,number]});
  return Object.freeze({placement,base,interpretation,baseArtifactSha256:baseHash,interpretationArtifactSha256:interpretationHash,
    currentDependencies:Object.freeze(current) as Readonly<Record<string,'available'>>});
}

export class SocietyDistrictClient {
  private readonly transport: Transport;
  constructor(options: TransportOptions) { this.transport = new Transport(options); }
  read(scope: SocietyDistrictScope): Promise<SocietyDistrictView> {
    return this.transport.getJson<unknown>(`/world/versions/${encodeURIComponent(scope.versionId)}/society/district`)
      .then(value => parseSocietyDistrict(value, scope));
  }
}
