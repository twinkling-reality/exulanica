// The words of talking in the world (DESIGN's rulings T1 to T9 and N28, WORDS.md): who said a line and
// to whom, a line a character heard, a character's own lines in What Teo did, and the talking scene's
// plate and choices. A person is called as the tag and card call them (J20): `who` is
// character-words.mjs's called(). The lines are the society's own words, never written here.
// verify-talk-words.mjs holds these.

import { CHARACTER_WORDS, called, possessive } from './character-words.mjs';

const plain = value => typeof value === 'string' && value.trim() ? value.trim() : null;
const quote = line => `\u201c${plain(line) ?? ''}\u201d`;

/**
 * Who a line, a name over someone or the talking scene calls a person: `who` as the tag calls them (J20), unless it
 * calls them by their kind and `name` (their name in the society read) is known, so nobody is "the cook" while
 * their offer is still being read or gives no name of its own. A society name that is only their `body`'s label
 * (a placed creature's, numbered from the second: "Eight legged finned creature", "... 2") is no name, as the tag
 * holds it: they keep the tag's words ("the canopy strider").
 */
export const knownWho = (who, name, body = null) => who.named || !plain(name) || labelOnly(name, body) ? who : called({ name });

/** Whether a society name is a body's label alone, as written or numbered. */
function labelOnly(name, body) {
  const label = plain(body)?.toLowerCase(), said = plain(name).toLowerCase();
  if (!label || !said.startsWith(label)) return false;
  return said.length === label.length || /^ \d+$/u.test(said.slice(label.length));
}

/** A said line's pop: the line in quotes (T1). */
export const saidPop = line => quote(line);

/** A chosen action's pop, as the decision's own words with a capital (T1). */
export const chosePop = chose => {
  const words = plain(chose);
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : null;
};

/**
 * Over a line (N28, T8): who said it and to whom, "Ines, to Teo" or "The resident, to Teo"; "Ines" alone
 * over a line to everyone near and over a choice.
 */
export const speechLabel = (speaker, listener = null) => listener ? `${speaker.start}, to ${listener.within}` : speaker.start;

/** A line said to Teo, or to everyone near Teo, in What Teo did (T6): "Heard Ines: “Morning, Teo.”". */
export const heardRow = (speaker, line) => `Heard ${speaker.within}: ${quote(line)}`;

/** Teo's own line (T6): "Said to Ines: “…”", or "Said: “…”" to everyone near. */
export const saidRow = (listener, line) => listener ? `Said to ${listener.within}: ${quote(line)}` : `Said: ${quote(line)}`;

/**
 * One name label over people standing together (T10, WORDS.md "Names together", as building's): "Marco",
 * "Marco and Ines", "Marco, Ines and the resident", and from four "Marco and 3 more".
 */
export const togetherNames = names => names.length <= 1 ? names[0] ?? ''
  : names.length >= 4 ? `${names[0]} and ${names.length - 1} more`
    : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;

/** Talking while following a conversation (T9, frame r24): its two choices and the speaker's plate. */
export const SCENE_WORDS = Object.freeze({ stopFollowing: CHARACTER_WORDS.stopFollowing, everyone: 'to everyone nearby' });

/** The speaker's page, the scene's Enter (T9): "Ines's day", "The resident's day". */
export const dayWord = speaker => `${possessive(speaker.start)} day`;

/** Under the line now, after the speaker's name (T9): "to Teo", "to the resident", or "to everyone nearby". */
export const plateTo = listener => listener ? `to ${listener.within}` : SCENE_WORDS.everyone;

/** The letter on a speaker's orb until their portrait is made (R23's portraits): "I", "R" for the resident. */
export const orbLetter = speaker => speaker.title.charAt(0).toUpperCase();
