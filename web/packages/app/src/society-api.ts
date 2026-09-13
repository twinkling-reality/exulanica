import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';
import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';

export interface SocietySnapshot {
  readonly societyId: string;
  readonly versionId: string;
  readonly placeId: string;
  readonly populationSize: number;
  readonly currentTick: number;
  readonly stateSha256: string;
  readonly state: OwnedSocietyState;
}

const record = (value: unknown): Readonly<Record<string, unknown>> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid society response');
  }
  return value as Readonly<Record<string, unknown>>;
};

export function parseSociety(value: unknown): SocietySnapshot {
  const row = record(value);
  const state = record(row['state']);
  const inhabitants = state['inhabitants'];
  if (
    typeof row['society_id'] !== 'string' ||
    typeof row['version_id'] !== 'string' ||
    typeof row['place_id'] !== 'string' ||
    !Number.isSafeInteger(row['population_size']) ||
    !Number.isSafeInteger(row['current_tick']) ||
    typeof row['state_sha256'] !== 'string' ||
    !Array.isArray(inhabitants) ||
    inhabitants.length < 100
  ) throw new Error('Invalid society response');
  return Object.freeze({
    societyId: row['society_id'],
    versionId: row['version_id'],
    placeId: row['place_id'],
    populationSize: row['population_size'] as number,
    currentTick: row['current_tick'] as number,
    stateSha256: row['state_sha256'],
    state: state as unknown as OwnedSocietyState,
  });
}

export class SocietyClient {
  private readonly transport: Transport;

  constructor(options: TransportOptions) {
    this.transport = new Transport(options);
  }

  async connect(
    versionId: string,
    placeId: string,
    regionId: string,
  ): Promise<SocietySnapshot> {
    const path = `/world/versions/${encodeURIComponent(versionId)}/society`;
    try {
      return parseSociety(await this.transport.getJson<unknown>(path));
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      return parseSociety(await this.transport.postJson<unknown>(path, {
        place_id: placeId,
        region_id: regionId,
        seed: '7a'.repeat(32),
      }));
    }
  }

  advance(snapshot: SocietySnapshot): Promise<SocietySnapshot> {
    return this.transport.postJson<unknown>(
      `/world/versions/${encodeURIComponent(snapshot.versionId)}/society/steps`,
      {
        base_tick: snapshot.currentTick,
        base_state_sha256: snapshot.stateSha256,
      },
    ).then(parseSociety);
  }
}
