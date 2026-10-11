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

export type WorldMakingState = 'choosing' | 'drafting' | 'making' | 'ready' | 'refused';

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

export interface WorldMakingRefusal {
  readonly code: string;
  readonly detail: string;
  /** The check that refused, where one did: `detail` is then the check's own sentence. */
  readonly check: string | null;
}

export interface WorldMakingDraft {
  readonly draftId: string;
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
  readonly refusal: WorldMakingRefusal | null;
  /** Every code a draft answers with, and what each means. */
  readonly refusals: readonly { readonly code: string; readonly meaning: string }[];
}

/** What starting a draft would meet, read before a word is typed (`GET /worlds/drafts`). */
export interface WorldDraftOffer {
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
}

type Json = Readonly<Record<string, unknown>>;

const STATES: readonly WorldMakingState[] = ['choosing', 'drafting', 'making', 'ready', 'refused'];

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
  });
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
  return Object.freeze({
    draftId: text(held['draft_id'], 'draft id'),
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

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
  }

  /** What starting a draft would meet now, and what one may spend. */
  async offer(): Promise<WorldDraftOffer> {
    return parseWorldDraftOffer(await this.#transport.getJson<unknown>('/worlds/drafts'));
  }

  /** Start making a world from `description`; answers at once with the draft to follow. */
  async start(description: string): Promise<WorldMakingDraft> {
    return parseWorldMakingDraft(await this.#transport.postJson<unknown>('/worlds/drafts', { description }));
  }

  async read(draftId: string): Promise<WorldMakingDraft> {
    return parseWorldMakingDraft(await this.#transport.getJson<unknown>(`/worlds/drafts/${encodeURIComponent(draftId)}`));
  }
}
