/**
 * The lines a being of a society of things said and heard, for its card, from what the society
 * recorded: its own `said` events (the line, to whom, and whether a model, the outside program that
 * sent it or a person playing the being decided it) and the lines its state says it heard (`heard`).
 * Only a decider says a line, never a being's routine, so every line was said by a model, by an
 * outside program or by a person playing the being; the card marks each by the one rule the world's
 * line bubbles use (`lineMarkOf`, thing-marks.ts),
 * and said events are read by the drawing's own reader (`saidLine`, thing-lines.ts).
 *
 * A line is the society's text, held to the line rule and treated as untrusted: the card shows it
 * as plain text. Who said it and to whom are named as the drawn state names them now, or by their
 * kind's label where they have left.
 */

import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import type { SocietyEvent } from '../society-api.js';
import type { ModelRef } from '../society-models-api.js';
import type { LineDecider, MarkInput } from './thing-marks.js';
import { saidLine } from './thing-lines.js';
import type { KindReference } from './visitor-notices.js';

type Person = OwnedSocietyState['inhabitants'][number];

export interface BeingLine {
  readonly tick: number;
  readonly speakerId: string;
  /** The speaker's name now, or its kind's label where it has left. */
  readonly speakerName: string;
  readonly toId: string | null;
  /** Whom it was said to by name, or null for everyone near. */
  readonly to: string | null;
  readonly line: string;
  /** Who decided it, as its said event states; null where no event read says (a line heard earlier). */
  readonly decider: LineDecider | null;
  /** The model that wrote it, where the line's record names one. */
  readonly model: ModelRef | null;
  /** The speaker as markOf reads them now, or null once they have left. */
  readonly speaker: MarkInput | null;
}

export interface LineNames {
  /** A person's name as the inspector draws it, or null where the state no longer lists them. */
  person(id: string): string | null;
  /** A kind's label by its reference, or null where the library does not list it. */
  kindLabel(kind: KindReference): string | null;
  /** The speaker as markOf reads them now (who runs them, how they came), or null once they left. */
  speaker(id: string): MarkInput | null;
}

/** How many of each the card shows: enough to follow a conversation, few enough to read at once. */
export const LINES_SHOWN = 3;

const record = (value: unknown): Readonly<Record<string, unknown>> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

const capital = (words: string): string => words.charAt(0).toUpperCase() + words.slice(1);

function named(id: string, kind: KindReference | null, names: LineNames): string {
  const now = names.person(id);
  if (now !== null) return now;
  const label = kind === null ? null : names.kindLabel(kind);
  return label === null ? 'Someone who has left' : capital(label);
}

/** The model a heard line names, where it names one (an optional field, THINGS 3b). */
function modelOf(value: unknown): ModelRef | null {
  const { provider, model_id: modelId } = record(value);
  return typeof provider === 'string' && typeof modelId === 'string' ? { provider, modelId } : null;
}

/** The lines `id` said, newest first, from the events read (a bounded window of the latest). */
export function saidBy(id: string, events: readonly SocietyEvent[], names: LineNames): readonly BeingLine[] {
  return events
    .filter((event) => event.subject_id === id)
    .sort((a, b) => b.tick - a.tick || order(b) - order(a))
    .flatMap((event) => {
      const said = saidLine(event);
      if (said === null) return [];
      // The one it was said to by id, which the event states beside their kind and number.
      const to = record(record(event.document)['thing'])['to'];
      const toId = typeof to === 'string' ? to : null;
      return [{
        tick: said.tick,
        speakerId: id,
        speakerName: named(id, said.from?.kind ?? null, names),
        toId,
        to: toId === null ? null : named(toId, said.to?.kind ?? null, names),
        line: said.text,
        decider: said.decider,
        model: said.model,
        speaker: names.speaker(id),
      }];
    })
    .slice(0, LINES_SHOWN);
}

/**
 * The lines `person` heard, newest first, each decided as the speaker's own said event states where
 * the events read still hold it, and otherwise by nothing the page can read (`lineMarkOf` then
 * gives no mark).
 */
export function heardBy(person: Person, events: readonly SocietyEvent[], names: LineNames): readonly BeingLine[] {
  const heard = person.heard ?? [];
  return [...heard].reverse().slice(0, LINES_SHOWN).map((entry) => {
    const said = events.map(saidLine).find((line) => line !== null && line.speakerId === entry.from &&
      line.tick === entry.tick && line.text === entry.line) ?? null;
    return {
      tick: entry.tick,
      speakerId: entry.from,
      speakerName: named(entry.from, entry.from_kind, names),
      toId: entry.to,
      to: entry.to === null ? null : named(entry.to, null, names),
      line: entry.line,
      decider: said?.decider ?? null,
      // A heard line may name its model itself (THINGS 3b), as its said event does.
      model: said?.model ?? modelOf(record(entry)['model']),
      speaker: names.speaker(entry.from),
    };
  });
}

const order = (event: SocietyEvent): number => {
  const value = record(event.document)['order'];
  return typeof value === 'number' ? value : 0;
};
