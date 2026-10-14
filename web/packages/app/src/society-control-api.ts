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
import { decisionMeasures, type DecisionMeasures } from './society-models-api.js';
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
  /**
   * Why it does not play, by code (`host_playback_code`, the keys of `HOST_PLAYBACK_REFUSALS`), or
   * null while it plays or from a server that names none; the page says it in its own words.
   */
  readonly code: string | null;
}

/**
 * Why the people here who would ask an open model follow their own routines instead
 * (`model_minds_code`, the keys of `MODEL_MINDS_REASONS`), with the server's sentence. The world
 * keeps playing either way: it is not a playback refusal.
 */
export interface ModelMinds {
  readonly code: string;
  readonly reason: string;
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
  /** Why open models are not asked for the people here now, or null while they may be (or the server does not say). */
  readonly modelMinds?: ModelMinds | null;
  /**
   * The society's latest living session, open or the last to close, with what it has used; null
   * for a society that never had one. Absent from a server that predates sessions.
   */
  readonly livingSession?: LivingSessionNow | null;
}

/** What a living session may use before it closes. `usd` is a decimal string at the ledger's places. */
export interface LivingSessionLimits {
  readonly wallSeconds: number;
  readonly minutes: number;
  readonly decisions: number;
  readonly usd: string;
  readonly calls: number;
}

/** Attempts that may have cost what nobody knows yet, until an operator reconciles them. */
export interface Unresolved {
  readonly count: number;
  readonly usd: string;
}

/**
 * What a living session has used of each limit: wall seconds since it opened, minutes played,
 * model decisions asked, and what its bounds committed, with what among that is unresolved.
 */
export interface LivingSessionUsed extends LivingSessionLimits {
  readonly unresolved: Unresolved;
}

/** A living session as the control read states it. `closedReason` is a code; null while open. */
export interface LivingSessionNow {
  readonly sessionId: string;
  readonly state: 'open' | 'closed';
  readonly limits: LivingSessionLimits;
  readonly used: LivingSessionUsed;
  readonly startTick: number;
  readonly openedAt: string;
  readonly endsBy: string;
  readonly endTick: number | null;
  readonly closedAt: string | null;
  readonly closedReason: string | null;
  /** Why it closed, in the server's one wording (`SESSION_CLOSED_WORDS`); null while open. */
  readonly closedReasonWords: string | null;
}

/** One provider's spending bound of a session, as the ledger holds it. Amounts are decimal strings. */
export interface SessionBound {
  readonly provider: string;
  readonly boundId: string;
  readonly state: 'open' | 'closed';
  readonly ceilingUsd: string;
  readonly maxCalls: number;
  readonly validUntil: string;
  readonly committedUsd: string;
  readonly committedCalls: number;
  readonly inFlightUsd: string;
  readonly unresolved: Unresolved;
  readonly knownUsageUsd: string;
  readonly reconciledUsd: string;
}

/** One decision asked for a session's minutes; `consumedTick` is null until a minute takes it up. */
export interface SessionDecision {
  readonly requestId: string;
  readonly decisionSeq: number;
  readonly role: string;
  readonly subjectId: string;
  readonly decider: 'model' | 'person' | 'external';
  readonly baseTick: number;
  readonly consumedTick: number | null;
  /** How its ask ended: the receipt's status and reason, so a timeout shows without another read. */
  readonly status: string;
  readonly reason: string;
}

/** A living session and what it came to, from the decisions asked for its own minutes alone. */
export interface LivingSessionRead extends LivingSessionNow {
  readonly bounds: readonly SessionBound[];
  /** In decision order: its latest `decisionsRead.maximum` at most. */
  readonly decisions: readonly SessionDecision[];
  /** `total` is every decision of the session: the list is complete exactly when `counted` equals it. */
  readonly decisionsRead: { readonly counted: number; readonly maximum: number; readonly total: number };
  /** Over its model decisions among `decisions`, as the models read measures them. */
  readonly measures: DecisionMeasures;
  readonly byModel: readonly { readonly provider: string; readonly modelId: string; readonly measures: DecisionMeasures }[];
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

const invalid = (): never => { throw new Error('Invalid society playback response'); };
const count = (value: unknown): number => (integer(value) ? value : invalid());
const usd = (value: unknown): string =>
  (typeof value === 'string' && /^(0|[1-9][0-9]*)\.[0-9]{8}$/.test(value) ? value : invalid());
const word = (value: unknown): string => (text(value) ? value : invalid());
const either = <T>(value: unknown, read: (held: unknown) => T): T | null => (value === null ? null : read(value));
const state = (value: unknown): 'open' | 'closed' => (value === 'open' || value === 'closed' ? value : invalid());

function limits(value: unknown): LivingSessionLimits {
  const held = object(value);
  return {
    wallSeconds: count(held['wall_seconds']), minutes: count(held['minutes']),
    decisions: count(held['decisions']), usd: usd(held['usd']), calls: count(held['calls']),
  };
}

function unresolved(value: unknown): Unresolved {
  const held = object(value);
  return { count: count(held['count']), usd: usd(held['usd']) };
}

/** A session as the control read states it; its closing fields are null exactly while it is open. */
function livingSessionNow(value: unknown): LivingSessionNow {
  const held = object(value);
  const used = object(held['used']);
  const now: LivingSessionNow = {
    sessionId: word(held['session_id']), state: state(held['state']), limits: limits(held['limits']),
    used: { ...limits(used), unresolved: unresolved(used['unresolved']) },
    startTick: count(held['start_tick']), openedAt: word(held['opened_at']), endsBy: word(held['ends_by']),
    endTick: either(held['end_tick'], count), closedAt: either(held['closed_at'], word),
    closedReason: either(held['closed_reason'], word),
    closedReasonWords: either(held['closed_reason_words'], word),
  };
  const closing = [now.endTick, now.closedAt, now.closedReason, now.closedReasonWords];
  if (now.state === 'open' ? closing.some((one) => one !== null) : closing.some((one) => one === null)) invalid();
  return now;
}

function bound(value: unknown): SessionBound {
  const held = object(value);
  return {
    provider: word(held['provider']), boundId: word(held['bound_id']), state: state(held['state']),
    ceilingUsd: usd(held['ceiling_usd']), maxCalls: count(held['max_calls']), validUntil: word(held['valid_until']),
    committedUsd: usd(held['committed_usd']), committedCalls: count(held['committed_calls']),
    inFlightUsd: usd(held['in_flight_usd']), unresolved: unresolved(held['unresolved']),
    knownUsageUsd: usd(held['known_usage_usd']), reconciledUsd: usd(held['reconciled_usd']),
  };
}

const DECIDERS = ['model', 'person', 'external'] as const;
function sessionDecision(value: unknown): SessionDecision {
  const held = object(value);
  const decider = (DECIDERS as readonly unknown[]).includes(held['decider'])
    ? held['decider'] as SessionDecision['decider'] : invalid();
  return {
    requestId: word(held['request_id']), decisionSeq: count(held['decision_seq']), role: word(held['role']),
    subjectId: word(held['subject_id']), decider, baseTick: count(held['base_tick']),
    consumedTick: either(held['consumed_tick'], count),
    status: word(held['status']), reason: word(held['reason']),
  };
}

const list = (value: unknown): readonly unknown[] => (Array.isArray(value) ? value : invalid());

/**
 * `GET .../society/control/sessions/{id}`: the session (`exulanica.society-session/v1`) with what
 * it came to. Its opening and closing receipts give what the control read states of it.
 */
export function parseLivingSession(value: unknown, sessionId: string): LivingSessionRead {
  const row = object(value);
  if (row['profile'] !== 'exulanica.society-session/v1' || row['session_id'] !== sessionId) invalid();
  const opened = object(row['opened']);
  const closed = row['closed'] === null ? null : object(row['closed']);
  const now = livingSessionNow({
    session_id: row['session_id'], state: row['state'], limits: opened['limits'], used: row['used'],
    start_tick: opened['start_tick'], opened_at: opened['opened_at'], ends_by: opened['ends_by'],
    end_tick: closed === null ? null : closed['end_tick'], closed_at: closed === null ? null : closed['closed_at'],
    closed_reason: closed === null ? null : closed['reason'],
    closed_reason_words: closed === null ? null : closed['words'],
  });
  const read = object(row['decisions_read']);
  const decisions = list(row['decisions']).map(sessionDecision);
  if (decisions.some((one, index) => index > 0 && one.decisionSeq <= decisions[index - 1]!.decisionSeq)) invalid();
  return Object.freeze({
    ...now,
    bounds: list(row['bounds']).map(bound),
    decisions,
    decisionsRead: { counted: count(read['counted']), maximum: count(read['maximum']), total: count(read['total']) },
    measures: decisionMeasures(row['measures']),
    byModel: list(row['by_model']).map((entry) => {
      const held = object(entry);
      return { provider: word(held['provider']), modelId: word(held['model_id']), measures: decisionMeasures(held['measures']) };
    }),
  });
}

/** The host's statement, exactly: a reason when and only when it does not play. */
function parseHostPlayback(value: unknown, code: unknown): HostPlayback | null {
  if (value === undefined) return null;
  if (!(code === undefined || code === null || text(code))) throw new Error('Invalid society playback response');
  const held = object(value);
  if (Object.keys(held).sort().join() !== HOST_PLAYBACK_KEYS.join()
    || typeof held['running'] !== 'boolean' || !integer(held['interval_ms']) || held['interval_ms'] === 0
    || (held['running'] ? held['reason'] !== null : !text(held['reason']))) {
    throw new Error('Invalid society playback response');
  }
  return Object.freeze({
    running: held['running'], intervalMs: held['interval_ms'] as number, reason: held['reason'] as string | null,
    code: held['running'] ? null : (code as string | null | undefined) ?? null,
  });
}

/** Why open models are not asked now: a code with its sentence, both or neither; absent from an older server. */
function parseModelMinds(code: unknown, reason: unknown): ModelMinds | null {
  if ((code === undefined || code === null) && (reason === undefined || reason === null)) return null;
  if (!text(code) || !text(reason)) throw new Error('Invalid society playback response');
  return Object.freeze({ code, reason });
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
    hostPlayback: parseHostPlayback(row['host_playback'], row['host_playback_code']),
    modelMinds: parseModelMinds(row['model_minds_code'], row['model_minds_reason']),
    ...(row['session'] === undefined ? {} : { livingSession: either(row['session'], livingSessionNow) }),
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

  /** One living session of the society and what it came to; reading it asks no model. */
  async readSession(versionId: string, sessionId: string): Promise<LivingSessionRead> {
    return this.#transport.getJson<unknown>(this.#path(versionId, `/sessions/${encodeURIComponent(sessionId)}`))
      .then(value => parseLivingSession(value, sessionId));
  }

  #path(versionId: string, suffix = ''): string {
    const path = `/world/versions/${encodeURIComponent(versionId)}/society/control${suffix}`;
    return openWorldPath(path, this.#worldId, 'society playback to read or change');
  }
}
