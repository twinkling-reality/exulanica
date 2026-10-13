import { Transport, type TransportOptions } from '@exulanica/graph-client';
import type { PlacedThingSupportReference } from '@exulanica/atlas-react/things';
import { openWorldPath } from './world-scope.js';

export interface ThingSupportAvailability {
  readonly versionId: string;
  readonly thingId: string;
  readonly stateSha256: string;
  readonly support: PlacedThingSupportReference | null;
  readonly availability: 'available' | 'unavailable' | 'unbound' | 'removed';
}
const row = (value: unknown): Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new TypeError('Invalid thing support document.');
  return value as Record<string, unknown>;
};
const text = (value: unknown): string => {
  if (typeof value !== 'string' || !value.length || value.length > 200) throw new TypeError('Invalid thing support identity.');
  return value;
};
const sha = (value: unknown): string => {
  if (typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value)) throw new TypeError('Invalid thing support digest.');
  return value;
};
export function parseThingSupport(value: unknown, versionId: string, thingId: string): ThingSupportAvailability {
  const body = row(value);
  if (body['profile'] !== 'exulanica.support-placement-availability/v1' || body['version_id'] !== versionId
      || body['thing_id'] !== thingId) throw new TypeError('Thing support belongs to another request.');
  const availability = body['availability'];
  if (availability !== 'available' && availability !== 'unavailable' && availability !== 'unbound' && availability !== 'removed') {
    throw new TypeError('Unknown thing support availability.');
  }
  let support: PlacedThingSupportReference | null = null;
  if (body['support'] !== null) {
    const ref = row(body['support']);
    if (Object.keys(ref).sort().join(',') !== 'network_sha256,profile,receipt_sha256,region_id,source_snapshot_id,surface_id,world_id'
        || ref['profile'] !== 'exulanica.support-reference/v1') throw new TypeError('Invalid thing support reference.');
    support = Object.freeze({ profile: 'exulanica.support-reference/v1', worldId: text(ref['world_id']),
      sourceSnapshotId: text(ref['source_snapshot_id']), receiptSha256: sha(ref['receipt_sha256']),
      networkSha256: sha(ref['network_sha256']), regionId: text(ref['region_id']), surfaceId: text(ref['surface_id']) });
  }
  if ((availability === 'unbound') !== (support === null)) throw new TypeError('Inconsistent thing support availability.');
  return Object.freeze({versionId, thingId, stateSha256: sha(body['state_sha256']), support, availability});
}

/** A fresh authorized read, never a substitute for the saved placement transform. */
export class ThingSupportClient {
  constructor(private readonly options: TransportOptions & { readonly worldId: string | null }) {}
  async read(versionId: string, thingId: string, signal: AbortSignal): Promise<ThingSupportAvailability> {
    const path = openWorldPath(`/world/versions/${encodeURIComponent(versionId)}/things/${encodeURIComponent(thingId)}/support`,
      this.options.worldId, 'a saved thing support');
    return parseThingSupport(await new Transport({...this.options, signal}).getJson<unknown>(path), versionId, thingId);
  }
}
