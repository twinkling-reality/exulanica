/**
 * The lines the beings of a society of things say, drawn over them as they are said: one bubble per
 * line, opening with the line's own mark, from the minute's `said` events (`document.thing`: the
 * line, who it was said to, both by kind and number as the minute began, and who decided it).
 *
 * Only lines said after the page first read the society are drawn, so nothing from before the visit
 * is replayed. A line's words are set as text only: models, outside programs and people write them. A
 * model's line always wears the AI mark, naming the model only where the line's own event names it;
 * an outside program's line wears its speaker's mark (the game it came from, or an outside agent's);
 * a line a person said while playing a being wears the person mark and says it was played by a person.
 * Every word but the line comes from the library's kind labels and the marks, never from a kind's,
 * a game's or a model's name in code.
 */

import type { ThingLine } from '@exulanica/atlas-react/things';
import type { SocietyEvent } from '../society-api.js';
import type { ModelRef, NamedModelRef } from '../society-models-api.js';
import { lineMarkOf, markLabel, type LineDecider, type MarkInput } from './thing-marks.js';
import type { KindReference } from './visitor-notices.js';

/** A `said` event as the drawing reads it. */
export interface SaidLine {
  readonly eventId: string;
  readonly tick: number;
  readonly speakerId: string;
  readonly text: string;
  readonly decider: LineDecider;
  /** The model that wrote it, where the event names one. */
  readonly model: ModelRef | null;
  readonly from: { readonly kind: KindReference; readonly number: number } | null;
  /** The one it was said to, or null for everyone near. */
  readonly to: { readonly kind: KindReference; readonly number: number } | null;
}

const record = (value: unknown): Readonly<Record<string, unknown>> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

function kindOf(value: unknown): KindReference | null {
  const { kind, version, sha256 } = record(value);
  return typeof kind === 'string' && typeof version === 'number' && typeof sha256 === 'string' ? { kind, version, sha256 } : null;
}

function numbered(kind: unknown, number: unknown): { readonly kind: KindReference; readonly number: number } | null {
  const reference = kindOf(kind);
  return reference !== null && typeof number === 'number' && Number.isInteger(number) && number >= 1 ? { kind: reference, number } : null;
}

function modelOf(value: unknown): ModelRef | null {
  const { provider, model_id: modelId } = record(value);
  return typeof provider === 'string' && typeof modelId === 'string' ? { provider, modelId } : null;
}

/** A `said` event's line, or null for any other event or one whose line or decider is not stated. */
export function saidLine(event: SocietyEvent): SaidLine | null {
  if (event.event_kind !== 'said') return null;
  const thing = record(event.document['thing']);
  const text = thing['line'];
  const decider = thing['decider'];
  if (typeof text !== 'string' || text.trim() === '') return null;
  if (decider !== 'model' && decider !== 'external' && decider !== 'person') return null;
  return {
    eventId: event.event_id,
    tick: event.tick,
    speakerId: event.subject_id,
    text,
    decider,
    model: modelOf(thing['model']),
    from: numbered(thing['from_kind'], thing['from_number']),
    to: thing['to'] === null || thing['to'] === undefined ? null : numbered(thing['to_kind'], thing['to_number']),
  };
}

export interface LineWords {
  /** A kind's label by its reference ("knight"), or null where the library does not list it. */
  kindLabel(kind: KindReference): string | null;
  /** How many beings of that kind the drawn state holds, so a number is said only where it tells them apart. */
  countOf(kind: KindReference): number;
  /** A model's served name, or null where the page has not read it. */
  modelName?(model: ModelRef): NamedModelRef | null;
}

function named(who: { readonly kind: KindReference; readonly number: number } | null, words: LineWords): string {
  if (who === null) return 'someone';
  const label = words.kindLabel(who.kind) ?? 'someone';
  return words.countOf(who.kind) > 1 ? `${label} ${who.number}` : label;
}

/** The bubble for a line: its words, its mark (`lineMarkOf`), and who said it to whom in words. */
export function thingLine(line: SaidLine, speaker: MarkInput | null, words: LineWords): ThingLine {
  const model = line.model === null ? null : words.modelName?.(line.model) ?? null;
  const mark = lineMarkOf({ decider: line.decider, model, speaker })!;
  const said = line.to === null ? named(line.from, words) : `${named(line.from, words)} to ${named(line.to, words)}`;
  const header = line.decider === 'person' ? `${said} · played by a person` : model === null ? said : `${said} · ${model.name}`;
  return { subjectId: line.speakerId, text: line.text, mark, header, spoken: markLabel(mark) };
}

/** The lines said since the page first read a society, each once, oldest first. */
export class LineWatch {
  #societyId: string | null = null;
  #seen = new Set<string>();

  take(societyId: string, events: readonly SocietyEvent[]): readonly SaidLine[] {
    const first = this.#societyId !== societyId;
    this.#societyId = societyId;
    const fresh = first ? [] : events.filter((event) => !this.#seen.has(event.event_id));
    // The window read is bounded; an event that has left it never comes back, so only it is kept.
    this.#seen = new Set(events.map((event) => event.event_id));
    return fresh
      .map(saidLine)
      .filter((line): line is SaidLine => line !== null)
      .sort((a, b) => a.tick - b.tick || (a.eventId < b.eventId ? -1 : a.eventId > b.eventId ? 1 : 0));
  }

  /** Forget the society, as when the world is closed. */
  reset(): void {
    this.#societyId = null;
    this.#seen.clear();
  }
}
