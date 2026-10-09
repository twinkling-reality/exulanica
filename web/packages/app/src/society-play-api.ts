/**
 * A person plays one being of a society of things (THINGS 3p): start, read the minute's turn,
 * answer it, give the being back. Routes under `/world/versions/{version}/society/play`, each with
 * the open world's scope.
 *
 * The server keeps the account out of every answer: a read says only whether the reader is the one
 * playing (`played_by_you`). A turn offers the being's options for the next minute by their words
 * (`label`), each naming what it acts on where it acts on something (a place or thing, `targetId`;
 * another being, `beingId`) and whether it takes a line. One answer per minute counts, the latest.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import { openWorldPath } from './world-scope.js';

/** One thing the played being may do at the next minute, in the words the server gives it. */
export interface PlayOption {
  readonly label: string;
  /** `target`, `talk`, `stand`, `wait`, `carry_on`, `say_to`, `say_all`, `leave`, `pick_up`, `put_down`, `give`, `take`. */
  readonly kind: string;
  /** The place or society thing it acts on, or null. */
  readonly targetId: string | null;
  /** The other being it involves (talked to, given to, taken from), or null. */
  readonly beingId: string | null;
  readonly takesLine: boolean;
}

export interface PlayTurn {
  readonly subjectId: string;
  /** The minute the options were read at; an answer names it. */
  readonly baseTick: number;
  readonly options: readonly PlayOption[];
  readonly lineCharactersMaximum: number;
  readonly played: boolean;
  readonly playedByYou: boolean;
  /** Minutes with no answer before the host gives the being back, and how many are left. */
  readonly quietMinutes: number;
  readonly quietLeft: number;
  /** When the next minute is due, and how long one lasts; null while the world is paused. */
  readonly nextDueAt: string | null;
  readonly minuteMs: number | null;
}

export interface PlayAnswered {
  readonly baseTick: number;
  readonly answerSeq: number;
}

type Json = Readonly<Record<string, unknown>>;
const invalid = (): never => { throw new TypeError('The server returned an invalid play answer.'); };
const object = (value: unknown): Json =>
  (value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Json : invalid());
const text = (value: unknown): string => (typeof value === 'string' && value.length > 0 ? value : invalid());
const count = (value: unknown): number => (typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : invalid());
const flag = (value: unknown): boolean => (typeof value === 'boolean' ? value : invalid());
const maybe = <T>(value: unknown, read: (present: unknown) => T): T | null =>
  (value === null || value === undefined ? null : read(value));

export function parsePlayTurn(raw: unknown): PlayTurn {
  const held = object(raw);
  const options = held['options'];
  if (!Array.isArray(options)) invalid();
  return Object.freeze({
    subjectId: text(held['subject_id']),
    baseTick: count(held['base_tick']),
    options: Object.freeze((options as unknown[]).map((entry): PlayOption => {
      const option = object(entry);
      return Object.freeze({
        label: text(option['label']),
        kind: text(option['kind']),
        targetId: maybe(option['target_id'], text),
        beingId: maybe(option['being_id'], text),
        takesLine: flag(option['takes_line']),
      });
    })),
    lineCharactersMaximum: count(held['line_characters_maximum']),
    played: flag(held['played']),
    playedByYou: flag(held['played_by_you']),
    quietMinutes: count(held['quiet_minutes']),
    quietLeft: count(held['quiet_left']),
    nextDueAt: maybe(held['next_due_at'], text),
    minuteMs: maybe(held['minute_ms'], count),
  });
}

export class SocietyPlayClient {
  readonly #transport: Transport;
  readonly #worldId: string | null;

  constructor(options: TransportOptions & { readonly worldId: string | null }) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
  }

  /** Start playing `subjectId`; refused by name where it cannot be played (another person plays it). */
  async start(versionId: string, subjectId: string, idempotencyKey: string = crypto.randomUUID()): Promise<void> {
    await this.#transport.postJson<unknown>(this.#path(versionId, ''), { idempotency_key: idempotencyKey, subject_id: subjectId });
  }

  async giveBack(versionId: string, subjectId: string, idempotencyKey: string = crypto.randomUUID()): Promise<void> {
    await this.#transport.postJson<unknown>(this.#path(versionId, `/${encodeURIComponent(subjectId)}/give-back`), { idempotency_key: idempotencyKey });
  }

  async turn(versionId: string, subjectId: string): Promise<PlayTurn> {
    return parsePlayTurn(await this.#transport.getJson<unknown>(this.#path(versionId, `/${encodeURIComponent(subjectId)}/turn`)));
  }

  async answer(versionId: string, subjectId: string, baseTick: number, label: string, line: string | null): Promise<PlayAnswered> {
    const held = object(await this.#transport.postJson<unknown>(this.#path(versionId, `/${encodeURIComponent(subjectId)}/answer`), {
      base_tick: baseTick, label, ...(line === null ? {} : { line }),
    }));
    return { baseTick: count(held['base_tick']), answerSeq: count(held['answer_seq']) };
  }

  #path(versionId: string, rest: string): string {
    const path = `/world/versions/${encodeURIComponent(versionId)}/society/play${rest}`;
    return openWorldPath(path, this.#worldId, 'a person playing one of this world\'s beings');
  }
}
