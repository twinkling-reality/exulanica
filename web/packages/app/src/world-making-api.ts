/**
 * A world made from a person's words (`GET /worlds/drafts` for what a draft would take,
 * `POST /worlds/drafts`, then `GET /worlds/drafts/{draft_id}` at the interval each answer names;
 * docs/world-kinds-contract.md, "A world made from a sentence").
 *
 * The offer says, before a word is typed, whether a draft would be taken from this person now and
 * by which code if not, the most times one draft asks a model, how many of the hour's starts are
 * left, and the person's own draft still running.
 * The route answers at once and never waits on a model. A job chooses the tool that can make the
 * place, drafts with it and makes the world; the draft says which of those it is at, and ends
 * ready with the saved world, each part that was made and what the words asked for that was left
 * out, or refused by a code of the closed list every answer carries.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import { parseEntry, type SavedWorldEntry } from './world-entry-api.js';

export type WorldMakingState = 'queued' | 'choosing' | 'drafting' | 'making' | 'ready' | 'refused';

/** One part of the world that was made, in the document's own words. */
export interface MadePart {
  readonly key: string;
  readonly label: string;
  readonly form: string;
  /** What a style pack dresses, `family.leaf`. */
  readonly look: string;
  /** How many slots the world's drawing draws for it; null for a town's parts. */
  readonly drawn: number | null;
  /** The largest box among them, width, depth and height in millimetres; null where it has none. */
  readonly boxMm: readonly [number, number, number] | null;
}

/** The look the made world is drawn in because the words asked for it. */
export interface TakenLook {
  readonly packId: string;
  readonly title: string;
  /** The person's own words that chose it. */
  readonly words: readonly string[];
}

/** The named parts of a setting the made world stands in because the words asked for them. */
export interface TakenSetting {
  readonly parts: readonly { readonly axis: string; readonly key: string; readonly title: string }[];
  readonly words: readonly string[];
}

export interface WorldMakingRefusal {
  readonly code: string;
  readonly detail: string;
  /** The check that refused, where one did: `detail` is then the check's own sentence. */
  readonly check: string | null;
}

export interface WorldMakingDraft {
  readonly draftId: string;
  readonly requestId: string | null;
  readonly operation: WorldDraftOperation | null;
  readonly recovered: boolean;
  readonly state: WorldMakingState;
  /** The words, while the draft runs; a draft that ended keeps none. */
  readonly description: string;
  readonly elapsedSeconds: number;
  /** When to ask again while it runs; null once it ended. */
  readonly pollAfterSeconds: number | null;
  /** The tool that drafts and makes the world, and whether a model chose it. */
  readonly tool: { readonly key: string; readonly chosenBy: 'model' | 'unsure' } | null;
  readonly entry: SavedWorldEntry | null;
  readonly made: readonly MadePart[];
  /** What the words asked for that the made world does not say, each the person's own words. */
  readonly leftOut: readonly string[];
  /** What the job took from the words for how the world is drawn and where it stands; null where
   * the words asked for none, and on a server that takes none. */
  readonly look: TakenLook | null;
  readonly setting: TakenSetting | null;
  readonly refusal: WorldMakingRefusal | null;
  /** Every code a draft answers with, and what each means. */
  readonly refusals: readonly { readonly code: string; readonly meaning: string }[];
}

/** Exact sealed server quote, forwarded without rounding or rebuilding its economic terms. */
export interface WorldDraftOperation {
  readonly maximumUsd: string;
  /**
   * The most one step of the draft may hold, one request to one model at its worst case: what an allowance must have
   * left for a draft to send anything. Null for a quote priced before steps were stated.
   */
  readonly stepUsdAtMost: string | null;
  readonly expiresAt: number;
  readonly document: Readonly<Record<string, unknown>>;
}

export interface WorldMakingStart {
  readonly idempotencyKey: string;
  readonly operation: WorldDraftOperation;
  readonly maximumUsd: string;
}

/** Page-session state only. Private words survive solely while exact POST recovery needs them. */
export interface WorldMakingMemory {
  pending: { readonly kind: 'sending'; readonly description: string; readonly submission: WorldMakingStart | null }
    | { readonly kind: 'following'; readonly draftId: string; readonly requestId: string | null } | null;
}
const memories = new WeakMap<object, WorldMakingMemory>();

/** What starting a draft would meet, read before a word is typed (`GET /worlds/drafts`). */
export interface WorldDraftOffer {
  readonly operation: WorldDraftOperation | null;
  readonly offered: boolean;
  /** Why not, where a start would be refused now; `detail` says it in a sentence. */
  readonly code: string | null;
  readonly detail: string | null;
  /** The most times one draft asks a model. */
  readonly callsAtMost: number;
  /** This person's starts in this workspace over the last hour. */
  readonly starts: { readonly anHour: number; readonly left: number; readonly retryAfterSeconds: number | null };
  /** The longest description a draft reads, in characters. */
  readonly descriptionCharacters: number;
  /** This person's own draft of a world still running here. */
  readonly runningDraftId: string | null;
  readonly refusals: readonly { readonly code: string; readonly meaning: string }[];
  /**
   * Where the workspace's own allowances have less left than the operation's most: what they have left, in USD, the
   * most a draft started now may spend. A draft holds each step as it is sent and stops where this runs out.
   */
  readonly leftUsd: string | null;
}

type Json = Readonly<Record<string, unknown>>;

const STATES: readonly WorldMakingState[] = ['queued', 'choosing', 'drafting', 'making', 'ready', 'refused'];

function fail(what: string): never {
  throw new TypeError(`The server returned an invalid ${what}.`);
}

function object(value: unknown, what: string): Json {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) fail(what);
  return value as Json;
}

function list(value: unknown, what: string): readonly unknown[] {
  if (!Array.isArray(value)) fail(what);
  return value as readonly unknown[];
}

function text(value: unknown, what: string): string {
  if (typeof value !== 'string') fail(what);
  return value as string;
}

function whole(value: unknown, what: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) fail(what);
  return value as number;
}

function codes(value: unknown): readonly { readonly code: string; readonly meaning: string }[] {
  return Object.freeze(list(value ?? [], 'refusal codes').map((one) => {
    const code = object(one, 'refusal code');
    return Object.freeze({ code: text(code['code'], 'refusal code'), meaning: text(code['meaning'], 'refusal meaning') });
  }));
}

function maybeText(value: unknown, what: string): string | null {
  return value === null || value === undefined ? null : text(value, what);
}

/** A USD figure as the server states one: a decimal string of at most eight places, more than zero unless `none`. */
function usd(value: unknown, what: string, none = false): string {
  const figure = text(value, what);
  if (!/^[0-9]{1,6}(\.[0-9]{1,8})?$/.test(figure) || (!none && Number(figure) <= 0)) fail(what);
  return figure;
}

/**
 * How an operation's ceiling was priced: each request at its role's request envelope of input and its answer limit, or,
 * for a quote priced before envelopes, at its model's whole context window. Both are ceilings no request can pass.
 */
const OPERATION_BASES: readonly unknown[] = ['request_envelope_ceiling', 'full_context_reservation_ceiling'];

function operation(value: unknown): WorldDraftOperation | null {
  if (value === null || value === undefined) return null;
  const held = object(value, 'world draft operation');
  const maximum = usd(held['maximum_usd'], 'world draft operation');
  const step = held['step_usd_at_most'] === undefined ? null : usd(held['step_usd_at_most'], 'world draft operation');
  const expires = Date.parse(text(held['expires_at'], 'operation expiry'));
  const readAt = Date.parse(text(held['read_at'], 'operation date'));
  if (held['profile'] !== 'exulanica.world-draft-operation/v1'
    || !OPERATION_BASES.includes(held['basis']) || held['estimate_is_expected_spend'] !== false
    || (step !== null && Number(step) > Number(maximum)) || !Number.isFinite(expires) || !Number.isFinite(readAt) || expires <= readAt || expires > readAt + 60_000
    || !/^[a-f0-9]{64}$/.test(text(held['document_sha256'], 'operation digest'))) fail('world draft operation');
  // Clone the complete quote; sending it later must not depend on a caller mutating the response.
  const freeze = (node: unknown): unknown => {
    if (node !== null && typeof node === 'object') {
      for (const child of Object.values(node)) freeze(child);
      Object.freeze(node);
    }
    return node;
  };
  return Object.freeze({ maximumUsd: maximum, stepUsdAtMost: step, expiresAt: expires,
    document: freeze(JSON.parse(JSON.stringify(held))) as Json });
}

export function parseWorldDraftOffer(raw: unknown): WorldDraftOffer {
  const held = object(raw, 'draft offer');
  if (typeof held['offered'] !== 'boolean') fail('draft offer');
  const code = maybeText(held['code'], 'draft offer code');
  // An offer that is not one names why not; one that is names nothing.
  if (held['offered'] === (code !== null)) fail('draft offer');
  const starts = object(held['starts'], 'draft starts');
  const retry = starts['retry_after_seconds'];
  const calls = whole(held['calls_at_most'], 'draft calls');
  const characters = whole(held['description_characters'], 'description length');
  if (calls < 1 || characters < 1) fail('draft offer');
  return Object.freeze({
    offered: held['offered'],
    operation: operation(held['operation']),
    code,
    detail: maybeText(held['detail'], 'draft offer detail'),
    callsAtMost: calls,
    starts: Object.freeze({
      anHour: whole(starts['an_hour'], 'draft starts'),
      left: whole(starts['left'], 'draft starts'),
      retryAfterSeconds: retry === null || retry === undefined ? null : whole(retry, 'draft starts'),
    }),
    descriptionCharacters: characters,
    runningDraftId: maybeText(held['running_draft_id'], 'running draft'),
    refusals: codes(held['refusals']),
    leftUsd: held['left_usd'] === null || held['left_usd'] === undefined ? null : usd(held['left_usd'], 'draft offer', true),
  });
}

function phrases(value: unknown, what: string): readonly string[] {
  return Object.freeze(list(value, what).map((one) => text(one, what)));
}

function takenLook(value: unknown): TakenLook | null {
  if (value === null || value === undefined) return null;
  const look = object(value, 'taken look');
  return Object.freeze({
    packId: text(look['pack_id'], 'taken look'), title: text(look['title'], 'taken look'),
    words: phrases(look['words'], 'taken look words'),
  });
}

function takenSetting(value: unknown): TakenSetting | null {
  if (value === null || value === undefined) return null;
  const setting = object(value, 'taken setting');
  const parts = list(setting['parts'], 'taken setting parts').map((one) => {
    const part = object(one, 'taken setting part');
    return Object.freeze({
      axis: text(part['axis'], 'taken setting part'), key: text(part['key'], 'taken setting part'),
      title: text(part['title'], 'taken setting part'),
    });
  });
  // A setting that was taken names at least one part.
  if (parts.length === 0) fail('taken setting parts');
  return Object.freeze({ parts: Object.freeze(parts), words: phrases(setting['words'], 'taken setting words') });
}

export function parseWorldMakingDraft(raw: unknown): WorldMakingDraft {
  const held = object(raw, 'draft of a world');
  const state = held['state'] as WorldMakingState;
  if (!STATES.includes(state)) fail('draft state');
  const tool = held['tool'] === null || held['tool'] === undefined ? null : object(held['tool'], 'draft tool');
  const chosenBy = tool?.['chosen_by'];
  if (tool !== null && chosenBy !== 'model' && chosenBy !== 'unsure') fail('draft tool');
  const refusal = held['refusal'] === null || held['refusal'] === undefined ? null : object(held['refusal'], 'draft refusal');
  const entry = held['entry'] === null || held['entry'] === undefined ? null : parseEntry(held['entry']);
  if (state === 'ready' && entry === null) fail('made world');
  if (state === 'refused' && refusal === null) fail('draft refusal');
  const poll = held['poll_after_seconds'];
  const recovered = held['recovered'] === undefined ? false : held['recovered'];
  if (typeof recovered !== 'boolean') fail('recovered draft');
  return Object.freeze({
    draftId: text(held['draft_id'], 'draft id'),
    requestId: maybeText(held['request_id'], 'request id'),
    operation: operation(held['operation']),
    recovered,
    state,
    description: text(held['description'], 'draft description'),
    elapsedSeconds: whole(held['elapsed_seconds'], 'draft elapsed seconds'),
    pollAfterSeconds: poll === null || poll === undefined ? null : whole(poll, 'draft poll interval'),
    tool: tool === null ? null : Object.freeze({ key: text(tool['key'], 'tool key'), chosenBy: chosenBy as 'model' | 'unsure' }),
    entry,
    made: Object.freeze(list(held['made'], 'made parts').map((one): MadePart => {
      const part = object(one, 'made part');
      const box = part['box_mm'];
      const drawn = part['drawn'];
      const read = box === null || box === undefined ? null : list(box, 'part box').map((side) => whole(side, 'part box'));
      if (read !== null && read.length !== 3) fail('part box');
      return Object.freeze({
        key: text(part['key'], 'part key'),
        label: text(part['label'], 'part label'),
        form: text(part['form'], 'part form'),
        look: text(part['look'], 'part look'),
        drawn: drawn === null || drawn === undefined ? null : whole(drawn, 'part slots'),
        boxMm: read === null ? null : (Object.freeze(read) as unknown as readonly [number, number, number]),
      });
    })),
    leftOut: Object.freeze(list(held['left_out'], 'left out phrases').map((one) => text(one, 'left out phrase'))),
    look: takenLook(held['look']),
    setting: takenSetting(held['setting']),
    refusal: refusal === null ? null : Object.freeze({
      code: text(refusal['code'], 'refusal code'),
      detail: text(refusal['detail'], 'refusal detail'),
      check: refusal['check'] === null || refusal['check'] === undefined ? null : text(refusal['check'], 'refusal check'),
    }),
    refusals: codes(held['refusals']),
  });
}

export class WorldMakingClient {
  readonly #transport: Transport;
  readonly memory: WorldMakingMemory;

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
    this.memory = memories.get(options) ?? { pending: null };
    memories.set(options, this.memory);
  }

  /** What starting a draft would meet now, and what one may spend. */
  async offer(): Promise<WorldDraftOffer> {
    return parseWorldDraftOffer(await this.#transport.getJson<unknown>('/worlds/drafts'));
  }

  /** Start making a world from `description`; answers at once with the draft to follow. */
  async start(description: string, submission?: WorldMakingStart): Promise<WorldMakingDraft> {
    const body = submission === undefined ? { description } : {
      description, idempotency_key: submission.idempotencyKey,
      operation: submission.operation.document, maximum_usd: submission.maximumUsd,
    };
    const answer = parseWorldMakingDraft(await this.#transport.postJson<unknown>('/worlds/drafts', body));
    if (submission !== undefined && answer.requestId !== submission.idempotencyKey) fail('world draft request identity');
    return answer;
  }

  async read(draftId: string): Promise<WorldMakingDraft> {
    return parseWorldMakingDraft(await this.#transport.getJson<unknown>(`/worlds/drafts/${encodeURIComponent(draftId)}`));
  }
}
