// The words of a character's personality (DESIGN's frame 11, WORDS.md): what the world's owner
// writes about a being they placed, which the server calls its character
// (exulanica.thing-character/v1) and shows its model as a description. On screen it is the
// Personality, because the workspace calls the being a character. A character is called by its name
// or kind, never "it". verify-personality-words.mjs holds the limits and codes to the server's own.
import { possessive } from './character-words.mjs';

export const PERSONALITY_WORDS = Object.freeze({
  label: 'Personality',
  name: 'Name',
  about: 'Personality',
  save: 'Save',
  cancel: 'Cancel',
  unsaved: 'This could not be saved. Try again.',
  record: 'Personality, as you wrote it',
  writtenByYou: 'Written by you',
  none: 'No personality yet.',
});

/** Under the fields, where the society reads personalities. */
export const readsEach = who => `${possessive(who.start)} model reads this each time it decides.`;

/** Where the world's people were added before personalities could be written. */
export const notRead = who => `This world's people were added before personalities could be written, so ${possessive(who.within)} model does not read this.`;

/** The note after a save the society reads. */
export const savedNote = who => `Saved. ${possessive(who.start)} model reads it from the next minute.`;

/** The most characters of each part (the character module's parameters, ability-modules.v1.json). */
export const PERSONALITY_LIMITS = Object.freeze({ name: 40, about: 300 });

/** Why a personality was not saved, by the server's code (THING_CHARACTER_CODES). */
export const PERSONALITY_REFUSALS = Object.freeze({
  character_out_of_bounds: 'Too long: a name has at most 40 characters, a personality at most 300.',
  character_carries_a_saved_name: 'It names a saved person or place, which is never sent to a model. Change those words.',
  character_for_beings_only: 'Only characters can have a personality.',
  character_changed: 'Someone changed it a moment ago. Look again and save once more.',
  no_change: 'Nothing changed.',
});

/** Characters as the line rule counts them: one per code point. */
export const length = text => [...(text || '')].length;

/** "12 of 40" for a field. */
export function counter(text, maximum) {
  return `${length(text)} of ${maximum}`;
}

/** A decision's first input section: the personality as written, name then words, or null. */
export function personalityRecordLines(character) {
  if (!character) return null;
  const parts = [character.name, character.about].filter(Boolean);
  return parts.length ? parts : null;
}

/** The words for a refused save by its code; any other code says it was not saved. */
export function personalityRefusalWords(code) {
  return Object.hasOwn(PERSONALITY_REFUSALS, code) ? PERSONALITY_REFUSALS[code] : PERSONALITY_WORDS.unsaved;
}

/** What a save sends: each part trimmed, an empty part left out, both empty a clear. */
export function personalityBody(name, about) {
  const held = { name: (name || '').trim() || null, about: (about || '').trim() || null };
  return held.name === null && held.about === null ? null : held;
}
