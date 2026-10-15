import assert from 'node:assert/strict';
import { routineLine, CHARACTER_WORDS, amount, called, chosenLine, goneNote, lastRunLine, modelLine, modelRefusalWords, money, nothingYet, orderedModels, outOfViewNote, pageSub, possessive, priceWords, readingRecord, routineRow, rowSub, whatDid } from './character-words.mjs';

// A character is called by its name, or by its kind, never "it", "he" or "she" (WORDS.md rule 10).
const teo = called({ name: 'Teo' }), resident = called({ name: '  ', kind: 'Resident' }), someone = called({ name: null }), bench = called({ name: null, being: false });
assert.deepEqual({ ...teo }, { title: 'Teo', start: 'Teo', within: 'Teo', named: true });
assert.deepEqual({ ...resident }, { title: 'Resident', start: 'The resident', within: 'the resident', named: false });
assert.equal(someone.title, 'Character');
assert.equal(bench.title, 'Thing');
assert.equal(possessive('Teo'), "Teo's");
assert.equal(possessive("the resident"), "the resident's");

// Frame 05's line: the model's choice with its time and count, or the routine.
assert.equal(chosenLine(teo, { hhmm: '07:09', options: 7 }), "Teo's model chose this at 07:09, from 7 choices.");
assert.equal(chosenLine(teo, { hhmm: '07:09', options: 1 }), "Teo's model chose this at 07:09, from 1 choice.");
assert.equal(chosenLine(teo, { hhmm: '07:09', options: null }), "Teo's model chose this at 07:09.");
assert.equal(chosenLine(teo, null), "Teo's routine.");
assert.equal(chosenLine(resident, null), "The resident's routine.");
assert.equal(readingRecord(teo), "Reading Teo's record…");
assert.equal(goneNote(teo), 'Teo is no longer in this world.');
assert.equal(outOfViewNote(resident), 'The resident went out of view, so following stopped.');

// Frames 06 and 07.
assert.equal(pageSub('resident', 'Terraces on the bay'), 'Resident · Terraces on the bay');
assert.equal(pageSub(null, 'Terraces on the bay'), 'Terraces on the bay');
assert.equal(whatDid(teo), 'What Teo did');
assert.equal(nothingYet(teo), 'Teo has not done anything yet.');
assert.equal(rowSub({ model: 'Nemotron 3 Nano 30B', options: 7 }), 'Nemotron 3 Nano 30B · 7 choices');
assert.equal(rowSub(null), 'Routine');
assert.equal(lastRunLine({ from: '06:00', to: '07:15', decisions: 12, spent: '0.00420000' }), 'Last run 06:00 to 07:15 · 12 decisions · spent $0.0042');
assert.equal(lastRunLine({ from: '06:00', to: '06:10', decisions: 1, spent: '0' }), 'Last run 06:00 to 06:10 · 1 decision · spent $0');

// Money (WORDS.md rule 5 and DESIGN's K8): "Free" only for a price; "$0" for nothing spent.
assert.equal(amount('0.05000000'), '$0.05');
assert.equal(amount('1'), '$1.00');
assert.equal(amount('0.00420000'), '$0.0042');
assert.equal(amount('0.00001800'), 'less than $0.0001');
assert.equal(amount('0'), '$0');
assert.equal(money('0'), 'Free');
assert.equal(priceWords({ price: { input: '0.06', output: '0.24' } }), '$0.06 in · $0.24 out');
assert.equal(priceWords({ price: { input: '0.3', output: '0.9' } }), '$0.30 in · $0.90 out');
assert.equal(priceWords({ price: { input: '0', output: '0.00' } }), 'Free');
assert.equal(priceWords({ price: null }), null);
// A model its provider serves from this computer (the read's on_this_computer), DESIGN's J11.
assert.equal(priceWords({ price: { input: '0', output: '0' }, local: true }), 'On this computer · Free');
assert.equal(modelLine({ price: { input: '0', output: '0' }, local: true }), 'On this computer · Free');
assert.equal(modelLine({ price: { input: '0.06', output: '0.24' } }), '$0.06 in · $0.24 out per million tokens');
assert.equal(modelLine(null), 'No AI model · Free');
assert.equal(routineRow(), 'No AI model · Free');

// The model list: NVIDIA's models first, cheapest first; the rest as served.
const model = (modelId, input) => ({ modelId, price: input === null ? null : { input, output: '1' } });
assert.deepEqual(orderedModels([model('Qwen/Qwen3-235B', '0.2'), model('nvidia/Ultra', '1.0'), model('deepseek/flash', '0.14'), model('nvidia/Nano', '0.06'), model('nvidia/Super', '0.3')]).map(one => one.modelId),
  ['nvidia/Nano', 'nvidia/Super', 'nvidia/Ultra', 'Qwen/Qwen3-235B', 'deepseek/flash']);
assert.equal(modelRefusalWords('stale', teo), 'Teo changed a moment ago. Look again and choose once more.');
assert.equal(modelRefusalWords('choice_key_reused', teo), 'Teo changed a moment ago. Look again and choose once more.');
assert.equal(modelRefusalWords('person_not_in_this_world', teo), 'Teo is no longer in this world.');
assert.equal(modelRefusalWords('decider_not_allowed', teo), 'This model cannot decide for Teo here.');

// Sentence case, no codes, no em dash, never "it", "entity", "session" or "provider" for a character.
const said = [...Object.values(CHARACTER_WORDS), chosenLine(teo, null), readingRecord(teo), goneNote(teo), nothingYet(teo), whatDid(teo)];
for (const words of said) {
  assert.doesNotMatch(words, /_|\u2014|entity|session|provider/i, words);
  assert.doesNotMatch(words, /\b(he|she)\b/i, words);
}
// A character with no model (J2, J22): the line asks for nothing the page cannot do.
assert.equal(routineLine(called({ name: 'Teo' }), { anyConnected: true, assignable: true }), 'Teo follows a routine. Choose a model to run.');
assert.equal(routineLine(called({ kind: 'resident' }), { anyConnected: false, assignable: true }), 'No AI model is connected here, so the resident follows a routine.');
assert.equal(routineLine(called({ kind: 'resident' }), { anyConnected: true, assignable: false }), 'The resident follows a routine.');
console.log('Character words checks passed: names and kinds, the chosen line, the page lines, money and the model list.');
