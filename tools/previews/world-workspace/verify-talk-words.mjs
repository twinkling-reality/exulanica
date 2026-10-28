import assert from 'node:assert/strict';
import { called } from './character-words.mjs';
import { SCENE_WORDS, chosePop, dayWord, heardRow, knownWho, orbLetter, plateTo, saidPop, saidRow, speechLabel, togetherNames } from './talk-words.mjs';

const ines = called({ name: 'Ines' }), resident = called({ kind: 'resident' });

// Who (J20): the tag's words where they name the person; else their name in the society read; the kind only
// where no name is known.
assert.equal(knownWho(called({ kind: 'cook' }), 'Ines').start, 'Ines');
assert.equal(knownWho(called({ kind: 'cook' }), 'Ines').named, true);
assert.equal(knownWho(ines, 'Teo').start, 'Ines');
assert.equal(knownWho(resident, null).within, 'the resident');
assert.equal(knownWho(resident, '  ').within, 'the resident');
// A placed creature's society name is its body's label, numbered from the second: no name of its own, as its tag holds
// it, so it keeps the tag's words; a knight (no body), a name that only holds the label and a resident keep theirs.
const strider = called({ kind: 'canopy strider' }), body = 'eight legged finned creature';
assert.equal(knownWho(strider, 'Eight legged finned creature', body).within, 'the canopy strider');
assert.equal(knownWho(strider, 'Eight legged finned creature 2', body).within, 'the canopy strider');
assert.equal(knownWho(strider, 'Eight legged finned creature', null).start, 'Eight legged finned creature', 'before its offer is read, as before');
assert.equal(knownWho(strider, 'Eight legged finned creature Nell', body).start, 'Eight legged finned creature Nell');
assert.equal(knownWho(strider, 'Eight legged finned creatures', body).start, 'Eight legged finned creatures');
assert.equal(knownWho(called({ kind: 'knight' }), 'Knight', null).start, 'Knight');
assert.equal(knownWho(called({ kind: 'barista' }), 'Hugo Kerr', null).start, 'Hugo Kerr');

// A pop (T1): a line in quotes, an action with a capital.
assert.equal(saidPop(' Morning, Teo. '), '\u201cMorning, Teo.\u201d');
assert.equal(chosePop('walk to the lower pools'), 'Walk to the lower pools');
assert.equal(chosePop(' '), null);
// Over a line (N28, T8): who said it, then to whom, named as the card names them; the speaker alone over
// a line to everyone near and over a choice.
const teo = called({ name: 'Teo' });
assert.equal(speechLabel(ines, teo), 'Ines, to Teo');
assert.equal(speechLabel(resident, teo), 'The resident, to Teo');
assert.equal(speechLabel(ines, resident), 'Ines, to the resident');
assert.equal(speechLabel(ines), 'Ines');
assert.equal(speechLabel(resident, null), 'The resident');
// What Teo did (T6).
assert.equal(heardRow(ines, 'Morning, Teo.'), 'Heard Ines: \u201cMorning, Teo.\u201d');
assert.equal(heardRow(resident, 'Calm water.'), 'Heard the resident: \u201cCalm water.\u201d');
assert.equal(saidRow(ines, 'Calm water today, Ines.'), 'Said to Ines: \u201cCalm water today, Ines.\u201d');
assert.equal(saidRow(null, 'Calm water today.'), 'Said: \u201cCalm water today.\u201d');
// Talking while following (T9): the speaker's page, whom the line now was said to, the orb's letter.
assert.equal(SCENE_WORDS.stopFollowing, 'Stop Following');
assert.equal(dayWord(ines), 'Activity');
assert.equal(dayWord(resident), 'Activity');
assert.equal(plateTo(teo), 'to Teo');
assert.equal(plateTo(resident), 'to the resident');
assert.equal(plateTo(null), 'to everyone nearby');
assert.equal(orbLetter(ines), 'I');
assert.equal(orbLetter(resident), 'R');
// T10: one label over people standing together.
assert.equal(togetherNames(['Marco']), 'Marco');
assert.equal(togetherNames(['Marco', 'Ines']), 'Marco and Ines');
assert.equal(togetherNames(['Marco', 'Ines', 'the resident']), 'Marco, Ines and the resident');
assert.equal(togetherNames(['Marco', 'Ines', 'Teo', 'Lia']), 'Marco and 3 more');
assert.equal(togetherNames(['Marco', 'Ines', 'Teo', 'Lia', 'Bo']), 'Marco and 4 more');
assert.equal(togetherNames([]), '');
for (const words of [dayWord(ines), plateTo(null), speechLabel(ines, teo), speechLabel(resident), heardRow(ines, 'A'), saidRow(ines, 'A'), saidRow(null, 'A')]) {
  assert.doesNotMatch(words, /\u2014|_|\b(he|she|it)\b/i, words);
}
console.log('Talk words checks passed: the pops, who said a line to whom, and the heard and said rows.');
