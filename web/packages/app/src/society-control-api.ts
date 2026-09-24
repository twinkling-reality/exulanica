/**
 * Authenticated saved playback controls for one society.
 *
 * Speaks `/world/versions/{id}/society/control` (`exulanica/api/routes/society_control.py`).
 * Importing this client never starts a worker. `configure` writes mode and speed;
 * `step` advances one leased tick bound to the displayed snapshot. Every request names the open
 * world, as the society client's do.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import { parseSociety, type SocietySnapshot } from './society-api.js';
import { openWorldPath } from './world-scope.js';

export type SocietyPlaybackMode = 'paused' | 'playing';
/** The speeds the server accepts (`SPEEDS` in `exulanica/world/society_controls.py`). */
export const PLAYBACK_SPEEDS = [1, 2, 4] as const;
export type SocietyPlaybackSpeed = (typeof PLAYBACK_SPEEDS)[number];

/**
 * Whether this host plays the world on its own (`host_playback`). `running` means the host's
 * playback worker is alive and plays this workspace, whatever mode is saved; `intervalMs` is the
 * real time one simulated minute takes, the host's base interval divided by the speed; `reason` is
 * the server's own sentence for why it does not play, null while it does.
 */
export interface HostPlayback {
  readonly running: boolean;
  readonly intervalMs: number;
  readonly reason: string | null;
}

export interface SocietyPlaybackControl {
  readonly societyId: string;
  readonly versionId: string;
  readonly persisted: boolean;
  readonly revision: number;
  readonly mode: SocietyPlaybackMode;
  readonly speed: SocietyPlaybackSpeed;
  readonly tickIntervalMs: number;
  readonly currentTick: number;
  readonly stateSha256: string;
  readonly nextDueAt: string | null;
  readonly reason: string | null;
  readonly playEligible: boolean;
  readonly playIneligibleReason: string | null;
  /** Whether this host plays the world; null for a server that does not say. */
  readonly hostPlayback: HostPlayback | null;
}

const object = (value: unknown): Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid society playback response');
  }
  return value as Record<string, unknown>;
};
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0;
const integer = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;

const HOST_PLAYBACK_KEYS = ['interval_ms', 'reason', 'running'];

/** The host's statement, exactly: a reason when and only when it does not play. */
function parseHostPlayback(value: unknown): HostPlayback | null {
  if (value === undefined) return null;
  const held = object(value);
  if (Object.keys(held).sort().join() !== HOST_PLAYBACK_KEYS.join()
    || typeof held['running'] !== 'boolean' || !integer(held['interval_ms']) || held['interval_ms'] === 0
    || (held['running'] ? held['reason'] !== null : !text(held['reason']))) {
    throw new Error('Invalid society playback response');
  }
  return Object.freeze({
    running: held['running'], intervalMs: held['interval_ms'] as number, reason: held['reason'] as string | null,
  });
}

export function parseSocietyControl(value: unknown, versionId: string): SocietyPlaybackControl {
  const row = object(value);
  if (row['profile'] !== 'exulanica.society-control/v1' || row['branch_id'] !== versionId
    || !text(row['society_id']) || typeof row['persisted'] !== 'boolean'
    || !integer(row['revision']) || !['paused', 'playing'].includes(String(row['mode']))
    || !(PLAYBACK_SPEEDS as readonly unknown[]).includes(row['speed']) || !integer(row['tick_interval_ms'])
    || row['interval_semantics'] !== 'minimum_wait_after_batch_completion'
    || !integer(row['current_tick']) || !text(row['state_sha256'])
    || !/^[0-9a-f]{64}$/.test(row['state_sha256'] as string)
    || typeof row['play_eligible'] !== 'boolean'
    || !(row['next_due_at'] === null || text(row['next_due_at']))
    || !(row['reason'] === null || text(row['reason']))
    || !(row['play_ineligible_reason'] === null || text(row['play_ineligible_reason']))) {
    throw new Error('Invalid society playback response');
  }
  return Object.freeze({
    societyId: row['society_id'] as string, versionId,
    persisted: row['persisted'] as boolean, revision: row['revision'] as number,
    mode: row['mode'] as SocietyPlaybackMode, speed: row['speed'] as SocietyPlaybackSpeed,
    tickIntervalMs: row['tick_interval_ms'] as number, currentTick: row['current_tick'] as number,
    stateSha256: row['state_sha256'] as string, nextDueAt: row['next_due_at'] as string | null,
    reason: row['reason'] as string | null, playEligible: row['play_eligible'] as boolean,
    playIneligibleReason: row['play_ineligible_reason'] as string | null,
    hostPlayback: parseHostPlayback(row['host_playback']),
  });
}

export interface SocietyControlClientOptions extends TransportOptions {
  /** The open world the versions belong to; null where none is open, which sends nothing. */
  readonly worldId: string | null;
}

export class SocietyControlClient {
  readonly #transport: Transport;
  readonly #worldId: string | null;
  constructor(options: SocietyControlClientOptions) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
  }

  async read(versionId: string): Promise<SocietyPlaybackControl> {
    return this.#transport.getJson<unknown>(this.#path(versionId))
      .then(value => parseSocietyControl(value, versionId));
  }

  async configure(
    control: SocietyPlaybackControl, mode: SocietyPlaybackMode, speed: SocietyPlaybackSpeed,
  ): Promise<SocietyPlaybackControl> {
    return this.#transport.putJson<unknown>(this.#path(control.versionId), {
      base_revision: control.revision, mode, speed,
    }).then(value => parseSocietyControl(value, control.versionId));
  }

  async step(control: SocietyPlaybackControl, snapshot: SocietySnapshot): Promise<{
    readonly control: SocietyPlaybackControl; readonly society: SocietySnapshot;
  }> {
    if (snapshot.versionId !== control.versionId || snapshot.societyId !== control.societyId) {
      return Promise.reject(new Error('Society playback state does not match the displayed world'));
    }
    return this.#transport.postJson<unknown>(this.#path(control.versionId, '/steps'), {
      base_revision: control.revision, base_tick: snapshot.currentTick,
      base_state_sha256: snapshot.stateSha256,
    }).then(value => {
      const row = object(value);
      return Object.freeze({
        control: parseSocietyControl(row['control'], control.versionId),
        society: parseSociety(row['society']),
      });
    });
  }

  #path(versionId: string, suffix = ''): string {
    const path = `/world/versions/${encodeURIComponent(versionId)}/society/control${suffix}`;
    return openWorldPath(path, this.#worldId, 'society playback to read or change');
  }
}
