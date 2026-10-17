import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PERSONALITY_LIMITS, PERSONALITY_REFUSALS, PERSONALITY_WORDS, counter, length, notRead, personalityBody, personalityRecordLines, personalityRefusalWords, readsEach, savedNote, writtenWords } from './personality-words.mjs';
import { called } from './character-words.mjs';

const repository = path => readFileSync(new URL('../../../' + path, import.meta.url), 'utf8');

// The limits are the character module's own parameters.
const modules = JSON.parse(repository('exulanica/abilities/ability-modules.v1.json'));
const entries = Array.isArray(modules) ? modules : modules.modules ?? Object.values(modules).find(Array.isArray);
const character = entries.find(entry => entry.module === 'exulanica-ability/character/v1');
const parameter = name => character.parameters.find(item => item.name === name).value;
assert.equal(PERSONALITY_LIMITS.name, parameter('name_characters_maximum'));
assert.equal(PERSONALITY_LIMITS.about, parameter('about_characters_maximum'));
assert.match(PERSONALITY_REFUSALS.character_out_of_bounds, new RegExp(`at most ${PERSONALITY_LIMITS.name} characters, a personality at most ${PERSONALITY_LIMITS.about}`));

// Every code the server refuses a write with has its words, and no other.
const source = repository('exulanica/world/thing_characters.py');
const opening = source.indexOf('THING_CHARACTER_CODES: Final = (');
assert.ok(opening > 0);
const codes = [...source.slice(opening, source.indexOf(')', opening)).matchAll(/"([a-z_]+)"/g)].map(match => match[1]);
assert.deepEqual(codes.sort(), Object.keys(PERSONALITY_REFUSALS).sort());
assert.equal(personalityRefusalWords('no_change'), 'Nothing changed.');
assert.equal(personalityRefusalWords('valueOf'), 'This could not be saved. Try again.');

// The note's word on screen is Personality, never the being's own word; no code, no em dash.
for (const words of [...Object.values(PERSONALITY_WORDS), ...Object.values(PERSONALITY_REFUSALS)]) {
  assert.doesNotMatch(words, /\bcharacter\b(?!s can)/, words);
  assert.doesNotMatch(words, /_|\u2014/, words);
}

// Counting, the sentences that name the character (never "it"), and the record's lines.
assert.equal(length('Puddle'), 6);
assert.equal(length('Düsseldorf'), 10);
assert.equal(counter('Puddle', 40), '6 of 40');
const teo = called({ name: 'Teo' }), resident = called({ name: null, kind: 'resident' });
assert.equal(readsEach(teo), "Teo's model reads this each time it decides.");
assert.equal(notRead(resident), "This world's people were added before personalities could be written, so the resident's model does not read this.");
assert.equal(savedNote(teo), "Saved. Teo's model reads it from the next minute.");

// Teo's day (r06) and its fields (r11): the personality as written in curly quotes, the line where none is written,
// and the counts over the fields ("3 of 40", "89 of 300").
assert.equal(writtenWords(' A retired fisherman who walks the quay. '), '\u201cA retired fisherman who walks the quay.\u201d');
assert.equal(PERSONALITY_WORDS.noneWritten, 'No personality written yet.');
assert.equal(counter('Teo', PERSONALITY_LIMITS.name), '3 of 40');
assert.equal(counter('A retired fisherman who walks the quay every morning and talks to anyone who will listen.', PERSONALITY_LIMITS.about), '89 of 300');
assert.deepEqual(personalityRecordLines({ name: 'Puddle', about: 'A worried yellow duck.' }), ['Puddle', 'A worried yellow duck.']);
assert.equal(personalityRecordLines({ name: null, about: null }), null);
assert.equal(personalityRecordLines(null), null);

// What a save sends: trimmed parts, empty ones left out, both empty a clear.
assert.deepEqual(personalityBody(' Puddle ', ''), { name: 'Puddle', about: null });
assert.equal(personalityBody(' ', ''), null);

console.log('Personality words checks passed: the module\'s limits, every refusal code, the sentences that name the character, the record\'s lines and Teo\'s day\'s.');
