/**
 * The mark a being wears in the world, on its card and before every line it says: one decision,
 * made here only, so the card and the world can never disagree about who runs something.
 *
 * Anything a model runs wears the AI mark; a visitor a game's program decides for wears where it came
 * from instead, and is never said to be a person, which nothing it sends shows; a being its own routine
 * runs, and every object, wears nothing. A visitor the world
 * decides for (its arrival said so) is marked by who decides here: the AI mark naming the model asked,
 * with where it came from, or where it came from alone while its routine runs it. A being a person
 * plays (Play this one) wears the person mark while they play it, whatever its mind: "You" to the one
 * playing, "Played" to everyone else; its lines say a person played it, never who.
 */

import type { NamedModelRef } from '../society-models-api.js';

/**
 * The drawn mark. `short` is the pill's words ("Qwen3"), `full` what a screen reader says and a
 * line's header names. The drawing layer declares the same shape for the pills it draws.
 */
export type ThingMark =
  | { readonly kind: 'ai'; readonly short: string; readonly full: string; readonly outside?: true; readonly from?: string }
  | { readonly kind: 'from'; readonly label: string; readonly full: string }
  /** Played by a person: `label` the pill's word, `mine` whether the viewer is the one playing. */
  | { readonly kind: 'person'; readonly label: string; readonly full: string; readonly mine: boolean; readonly from?: string };

/** An outside program's entry as the door lists it for this workspace. */
export interface MarkBridge {
  readonly label: string;
  /** Whether what it brings in is run by an AI (an agent) rather than by a game's program. */
  readonly ai: boolean;
}

export interface MarkInput {
  /** The model asked for it now (`PersonMind.running`), or null when nothing asks a model. */
  readonly running: NamedModelRef | null;
  /** Set when it came in from outside this world: the bridge it came through. */
  readonly crossing?: { readonly bridge: string; readonly decided_by?: 'program' | 'world' } | null;
  /** The door's entry for that bridge, or null when the door does not list it here. */
  readonly bridge?: MarkBridge | null;
  /** What an outside agent says it is, in its own words. */
  readonly declared?: { readonly name: string } | null;
  /** Set while a person plays it (the models read's person choice): whether the viewer is that person. */
  readonly played?: { readonly byYou: boolean } | null;
}

/** What a mark naming no model says it is run by. */
const UNNAMED_MODEL = 'an AI model';

/** The first word of a served model name: "Qwen3 235B Instruct" is "Qwen3" on a pill. */
function shortName(name: string): string {
  return name.trim().split(/\s+/u)[0] ?? name;
}

/** Where a visitor the world decides for came from, by its bridge's label; undefined for anyone else. */
function worldVisitorOrigin(input: MarkInput): string | undefined {
  return input.crossing != null && input.crossing.decided_by === 'world' ? input.bridge?.label ?? 'outside' : undefined;
}

export function markOf(input: MarkInput): ThingMark | null {
  // While a person plays it, the person decides, not its mind, which rests until it is given back.
  if (input.played != null) {
    const mine = input.played.byYou;
    const from = worldVisitorOrigin(input);
    return {
      kind: 'person', mine, label: mine ? 'You' : 'Played', full: mine ? 'Played by you' : 'Played by another person',
      ...(from === undefined ? {} : { from }),
    };
  }
  if (input.crossing != null && input.crossing.decided_by === 'world') {
    const origin = input.bridge?.label ?? 'outside';
    if (input.running === null) return { kind: 'from', label: `from ${origin}`, full: `From ${origin}, run by this world` };
    return { kind: 'ai', short: shortName(input.running.name), full: input.running.name, from: origin };
  }
  if (input.crossing != null) {
    const bridge = input.bridge ?? null;
    if (bridge === null) return { kind: 'from', label: 'from outside', full: 'Someone from outside this world' };
    if (!bridge.ai) return { kind: 'from', label: `from ${bridge.label}`, full: `From ${bridge.label}, decided from outside` };
    const name = input.declared?.name ?? null;
    return {
      kind: 'ai',
      short: name ?? 'agent',
      full: name === null ? 'An outside AI agent' : `An outside AI agent, ${name}`,
      outside: true,
    };
  }
  if (input.running === null) return null;
  return { kind: 'ai', short: shortName(input.running.name), full: input.running.name };
}

/** What a screen reader says for a mark, on the card and over a being. */
export function markLabel(mark: ThingMark): string {
  if (mark.kind === 'person') return mark.from === undefined ? mark.full : `${mark.full}, from ${mark.from}`;
  if (mark.kind === 'ai' && mark.outside !== true) {
    // A mark naming no model says only that a model runs it.
    const said = mark.full === UNNAMED_MODEL ? 'run by an AI model' : `run by an AI model, ${mark.full}`;
    return mark.from === undefined ? said : `${said}, from ${mark.from}`;
  }
  return mark.full;
}

/** Who decided a line a being said: the world's own model, the program it came from, or a person playing it. */
export type LineDecider = 'model' | 'external' | 'person';

/** The plain AI mark of a model's line when the page does not know which model wrote it. */
export const AN_AI_MODEL: ThingMark = { kind: 'ai', short: 'AI', full: UNNAMED_MODEL };

const FROM_OUTSIDE: ThingMark = { kind: 'from', label: 'from outside', full: 'Someone from outside this world' };

/** A line a person said while playing a being: whose it was, no read says. */
const PERSON_LINE = { kind: 'person', label: 'Person', full: 'Played by a person', mine: false } as const;

export interface LineMarkInput {
  /** Who decided the line, as its said event states; null where no event says (a heard line alone). */
  readonly decider: LineDecider | null;
  /** The model that wrote it, where the line's record names one, by its served name. */
  readonly model?: NamedModelRef | null;
  /** The speaker as the world marks them now (`markOf`'s input), or null once they have left. */
  readonly speaker?: MarkInput | null;
}

/**
 * The mark a line opens with, in the world and on the card alike, from the line's own record: a
 * model's line is always an AI's, naming the model only where the line's record names it (the
 * speaker's model now may not be the one that wrote it), else a plain AI mark; it keeps where a
 * visitor the world runs came from. An outside program's line wears its speaker's mark (the game it
 * came from, or an outside agent's), from outside where the speaker is not known; a person's line
 * wears the person mark saying a person played it (never "You": no read names who it was), keeping
 * where a visitor the world decides for came from; a line no event decides wears none.
 */
export function lineMarkOf(input: LineMarkInput): ThingMark | null {
  if (input.decider === null) return null;
  if (input.decider === 'person') {
    const from = input.speaker == null ? undefined : worldVisitorOrigin(input.speaker);
    return from === undefined ? PERSON_LINE : { ...PERSON_LINE, from };
  }
  const speaker = input.speaker == null ? null : markOf(input.speaker);
  if (input.decider === 'external') return speaker ?? FROM_OUTSIDE;
  // A model's line keeps where a visitor the world decides for came from, played now or not.
  const from = (speaker?.kind === 'ai' && speaker.outside !== true) || speaker?.kind === 'person' ? speaker.from : undefined;
  const model = input.model ?? null;
  if (model === null) return from === undefined ? AN_AI_MODEL : { kind: 'ai', short: 'AI', full: UNNAMED_MODEL, from };
  return { kind: 'ai', short: shortName(model.name), full: model.name, ...(from === undefined ? {} : { from }) };
}
