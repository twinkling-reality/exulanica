/**
 * The mark a being wears in the world, on its card and before every line it says: one decision,
 * made here only, so the card and the world can never disagree about who runs something.
 *
 * Anything a model runs wears the AI mark; a visitor a person runs from a game wears where it came
 * from instead; a being its own routine runs, and every object, wears nothing. A visitor the world
 * decides for (its arrival said so) is marked by who decides here: the AI mark naming the model asked,
 * with where it came from, or where it came from alone while its routine runs it.
 */

import type { NamedModelRef } from '../society-models-api.js';

/**
 * The drawn mark. `short` is the pill's words ("Qwen3"), `full` what a screen reader says and a
 * line's header names. The drawing layer declares the same shape for the pills it draws.
 */
export type ThingMark =
  | { readonly kind: 'ai'; readonly short: string; readonly full: string; readonly outside?: true; readonly from?: string }
  | { readonly kind: 'from'; readonly label: string; readonly full: string };

/** An outside program's entry as the door lists it for this workspace. */
export interface MarkBridge {
  readonly label: string;
  /** Whether what it brings in is run by an AI (an agent) rather than a person playing a game. */
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
}

/** The first word of a served model name: "Qwen3 235B Instruct" is "Qwen3" on a pill. */
function shortName(name: string): string {
  return name.trim().split(/\s+/u)[0] ?? name;
}

export function markOf(input: MarkInput): ThingMark | null {
  if (input.crossing != null && input.crossing.decided_by === 'world') {
    const origin = input.bridge?.label ?? 'outside';
    if (input.running === null) return { kind: 'from', label: `from ${origin}`, full: `From ${origin}, run by this world` };
    return { kind: 'ai', short: shortName(input.running.name), full: input.running.name, from: origin };
  }
  if (input.crossing != null) {
    const bridge = input.bridge ?? null;
    if (bridge === null) return { kind: 'from', label: 'from outside', full: 'Someone from outside this world' };
    if (!bridge.ai) return { kind: 'from', label: `from ${bridge.label}`, full: `A person playing ${bridge.label}` };
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
  if (mark.kind === 'ai' && mark.outside !== true) {
    return mark.from === undefined ? `run by an AI model, ${mark.full}` : `run by an AI model, ${mark.full}, from ${mark.from}`;
  }
  return mark.full;
}
