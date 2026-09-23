/**
 * The account holder's own names, put back where the server left a placeholder.
 *
 * No name the account holder saved goes to a hosted model (`exulanica/epistemics/saved_names.py`):
 * the planner and the composer are sent `[person A]` or `[place A]` instead, so an answer names a
 * person or a place only that way, and the answer's `names` says which entity each placeholder
 * stands for. This module turns a placeholder back into the name, and nothing else does: every
 * surface that shows the Companion's words draws them through one `CompanionNames`.
 *
 * **The name comes from the library, never from the answer.** Which entity a placeholder stands
 * for is the server's statement, made by the redaction that wrote the placeholder. What that
 * entity is called is its `displayName` in the graph this browser already read with the account
 * holder's own credential (`GET /graph`), and only a person's own naming writes that column
 * (`display_name` in `exulanica/migrations/0001_spine.sql`). Nothing a model wrote is read as a
 * name: not the sentence around a placeholder, and not the letters inside one.
 *
 * **A placeholder that cannot be resolved is said in words, never shown as brackets.** Each reason
 * has its own words in the copy table, so "a place no longer in your library" and "a place you have
 * not named" stay two different statements.
 *
 * What it does not do: an answer kept in the Companion's memory stores its text and not its
 * `names`, so a placeholder in a remembered answer cannot be tied to an entity and reads as
 * `not_identified`. And a name is always the entity's current one, so a remembered sentence about
 * a sign reads whatever the place is called now.
 */

import { entityById, type EntityRecord, type GraphSnapshot } from '@exulanica/graph-client';
import { fill, say } from './ui/copy.js';

/**
 * A placeholder, as the server writes one.
 *
 * The source of `PLACEHOLDER` in `exulanica/epistemics/saved_names.py`, character for character.
 * `tests/test_companion_placeholder_parity.py` fails when the two differ, so a class the server
 * learns to write is a class this module recognises rather than one a person reads in brackets.
 */
export const PLACEHOLDER_SOURCE = '(\\[(?:person|voice|place|object|conversation|event) [A-Z]+\\])';

/** Why a placeholder is shown in words rather than as a name. */
export type Unresolved =
  /** The entity is in the library and has no name: never named, or its name was taken back. */
  | 'not_named'
  /** The entity was merged into another one. */
  | 'merged'
  /** The account holder deleted the entity. */
  | 'removed'
  /** The library this page holds does not have the entity, or the page holds no library. */
  | 'not_loaded'
  /** The text does not say which entity the placeholder stands for. */
  | 'not_identified';

export type SpokenPiece =
  | { readonly kind: 'text'; readonly text: string }
  | {
      readonly kind: 'name';
      readonly text: string;
      readonly placeholder: string;
      readonly entityId: string;
    }
  | {
      readonly kind: 'unresolved';
      readonly text: string;
      readonly placeholder: string;
      readonly entityId: string | null;
      readonly reason: Unresolved;
    };

export interface CompanionNames {
  /**
   * `text` in reading order, with each placeholder it carries resolved.
   *
   * `names` is the answer's own map from placeholder to entity id. Absent means the text says
   * nothing about which entity a placeholder stands for, so every one it carries is
   * `not_identified`.
   */
  restore(
    text: string,
    names: Readonly<Record<string, string>> | undefined,
  ): readonly SpokenPiece[];
}

/** The pieces as one string, for a surface that has no element to put a name in. */
export function spokenText(pieces: readonly SpokenPiece[]): string {
  return pieces.map((piece) => piece.text).join('');
}

/**
 * `[place A]` however the model cased it, and its class word.
 *
 * A composer that begins a sentence with a placeholder may raise its first letter, and the
 * brackets are what make the match unambiguous, so the class word and the letters are both read
 * without regard to case and looked up in the server's own spelling.
 */
function canonical(written: string): { readonly label: string; readonly entityClass: string } {
  const [classWord = '', letters = ''] = written.slice(1, -1).split(' ');
  const entityClass = classWord.toLowerCase();
  return { label: `[${entityClass} ${letters.toUpperCase()}]`, entityClass };
}

/** Where a placeholder began a sentence, the words said in its place begin with a capital. */
function sentenceCase(phrase: string, before: string): string {
  const starts = before.trim() === '' || /[.!?]["')\]]*\s+$/.test(before);
  return starts ? phrase.charAt(0).toUpperCase() + phrase.slice(1) : phrase;
}

/** The entity's name, or why there is none to show. */
function resolve(
  entityId: string | null,
  snapshot: GraphSnapshot | null,
  entities: ReadonlyMap<string, EntityRecord>,
): { readonly name: string } | { readonly reason: Unresolved } {
  if (entityId === null) return { reason: 'not_identified' };
  if (snapshot === null) return { reason: 'not_loaded' };
  if (snapshot.deletedEntityIds.includes(entityId)) return { reason: 'removed' };
  const entity = entities.get(entityId);
  if (entity === undefined) return { reason: 'not_loaded' };
  if (entity.mergedInto !== null) return { reason: 'merged' };
  const name = entity.displayName;
  return name === null || name.trim() === '' ? { reason: 'not_named' } : { name };
}

/**
 * The answer's own labels written without their brackets, `place A`, `Place A` or `PLACE A`.
 *
 * Measured on the live composer: asked which photographs were taken at a confirmed place, it wrote
 * "These photographs were taken at place A.", and asked what a sign in capitals says, "The sign
 * reads PLACE A." Only a label this answer's `names` assigned is looked for, its class word in any
 * case and its letters exactly as the server wrote them, with nothing word-like either side, so
 * "a place a friend chose" and "workplace A" stay the words they are. A remembered answer has no
 * `names`, and in its text only the bracketed form is recognised.
 */
function bareLabels(names: Readonly<Record<string, string>> | undefined): RegExp | null {
  const forms = Object.keys(names ?? {}).flatMap((label) => {
    const parts = /^\[([a-z]+) ([A-Z]+)\]$/.exec(label);
    if (parts === null) return [];
    const [, word = '', letters = ''] = parts;
    const anyCase = [...word].map((letter) => `[${letter}${letter.toUpperCase()}]`).join('');
    return [`${anyCase} ${letters}`];
  });
  return forms.length === 0 ? null : new RegExp(`(?<![\\w[])(?:${forms.join('|')})(?![\\w\\]])`, 'g');
}

interface Found {
  readonly start: number;
  readonly end: number;
  readonly label: string;
  readonly entityClass: string;
}

/** Every placeholder in `text`, bracketed or one of the answer's own labels bare, in order. */
function placeholdersIn(text: string, names: Readonly<Record<string, string>> | undefined): Found[] {
  const matches: Found[] = [];
  for (const match of text.matchAll(new RegExp(PLACEHOLDER_SOURCE, 'gi'))) {
    matches.push({ start: match.index, end: match.index + match[0].length, ...canonical(match[0]) });
  }
  const bare = bareLabels(names);
  for (const match of bare === null ? [] : text.matchAll(bare)) {
    matches.push({
      start: match.index,
      end: match.index + match[0].length,
      ...canonical(`[${match[0]}]`),
    });
  }
  matches.sort((a, b) => a.start - b.start);
  const kept: Found[] = [];
  for (const found of matches) {
    if (found.start >= (kept.at(-1)?.end ?? 0)) kept.push(found);
  }
  return kept;
}

/**
 * One resolver over whatever library the page holds at the moment it is asked.
 *
 * `library` is read on every call rather than once, because the composition root replaces the
 * snapshot after every committed write: a place confirmed a moment ago is in the next snapshot and
 * not in the one the Companion was mounted with.
 */
export function companionNames(library: () => GraphSnapshot | null): CompanionNames {
  return {
    restore(text, names) {
      const snapshot = library();
      const entities = snapshot === null ? new Map<string, EntityRecord>() : entityById(snapshot);
      const pieces: SpokenPiece[] = [];
      let at = 0;
      for (const { start, end, label, entityClass } of placeholdersIn(text, names)) {
        if (start > at) pieces.push({ kind: 'text', text: text.slice(at, start) });
        const entityId = names?.[label] ?? null;
        const resolved = resolve(entityId, snapshot, entities);
        if (entityId !== null && 'name' in resolved) {
          pieces.push({ kind: 'name', text: resolved.name, placeholder: label, entityId });
        } else {
          const reason = 'reason' in resolved ? resolved.reason : 'not_identified';
          const phrase = fill(`name.unresolved.${reason}`, {
            thing: say(`name.class.${entityClass}`),
          });
          pieces.push({
            kind: 'unresolved',
            text: sentenceCase(phrase, text.slice(0, start)),
            placeholder: label,
            entityId,
            reason,
          });
        }
        at = end;
      }
      if (at < text.length) pieces.push({ kind: 'text', text: text.slice(at) });
      return pieces;
    },
  };
}
