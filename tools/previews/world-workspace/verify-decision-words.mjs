import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  DECISION_FLOW_WORDS, DECISION_NOTE_WORDS, DECISION_WORDS, answeredIn, askedAt, choiceRows, choicesLabel, choicesOver, choseOneOf, costWords, decidedByParts, decisionNotes, decisionTitle,
  needLine, overLabel, resultLines, toldLabel, toldSections,
} from './decision-words.mjs';
import { called } from './character-words.mjs';

const repository = path => readFileSync(new URL('../../../' + path, import.meta.url), 'utf8');
const teo = called({ name: 'Teo' }), resident = called({ kind: 'resident' });

// Frame 10's labels, called by name or kind, never "it".
assert.equal(toldLabel(teo), "What Teo's model was told");
assert.equal(toldLabel(resident), "What the resident's model was told");
// Each decider names itself (WORDS.md R5b, R5c): a person playing them was shown, a model or an outside program was told.
assert.equal(toldLabel(teo, 'person'), 'What the person playing Teo was shown');
assert.equal(toldLabel(resident, 'person'), 'What the person playing the resident was shown');
assert.equal(toldLabel(teo, 'external'), "What Teo's outside program was told");
assert.equal(toldLabel(resident, 'external'), "What the resident's outside program was told");
assert.equal(toldLabel(teo, 'model'), "What Teo's model was told");
assert.equal(toldLabel(resident, 'model'), "What the resident's model was told");
assert.equal(choicesLabel(teo, 9), "Teo's choices (9)");
assert.equal(choicesLabel(resident, 3), "The resident's choices (3)");
assert.equal(overLabel({ at: askedAt(52, 360), who: teo, said: true, to: 'Ines' }), '06:52 · Day 1 · Teo said to Ines');
assert.equal(overLabel({ at: askedAt(1500, 360), who: teo }), '07:00 · Day 2');
assert.equal(overLabel({ at: askedAt(4, null), who: resident, said: true }), 'The resident said');
assert.equal(overLabel({ at: null, who: teo }), '');
assert.equal(decisionTitle({ line: ' Morning, Ines. ', chose: 'say something' }), '“Morning, Ines.”');
assert.equal(decisionTitle({ chose: 'wait here a minute' }), 'Wait here a minute');

// What came of it: a done decision says only its answer's time and cost (the head names its minute), any other
// verdict its own words.
const record = { latencyMs: 912, costUsd: '0.00030000', costKnown: true };
assert.deepEqual(resultLines({ verdict: { kind: 'applied', words: 'Applied in minute 53.' }, ...record }),
  { done: 'Answered in 0.9 s · cost $0.0003', verdict: null });
assert.deepEqual(resultLines({ verdict: { kind: 'applied' } }), { done: null, verdict: null });
assert.deepEqual(resultLines({ verdict: { kind: 'pending', words: 'Accepted; no minute has acted on it yet.' }, latencyMs: 1300, costUsd: '0.0014006', costKnown: false }),
  { done: 'Answered in 1.3 s · cost at most $0.0014', verdict: 'Accepted; no minute has acted on it yet.' });
assert.deepEqual(resultLines({ verdict: { kind: 'awaiting_answer', words: 'No answer is recorded yet.' } }), { done: null, verdict: 'No answer is recorded yet.' });
assert.equal(resultLines({ verdict: { kind: 'applied' }, costUsd: '0' }).done, 'Cost $0');
// A time under a tenth of a second (DESIGN's W5).
assert.equal(resultLines({ verdict: { kind: 'applied' }, latencyMs: 13 }).done, 'Answered in under 0.1 s');
assert.equal(resultLines({ verdict: { kind: 'applied' }, latencyMs: 100 }).done, 'Answered in 0.1 s');

// The record page's words (r10): the column's label, the ring's count, the card's label and the head's small print,
// who decided first (T7's words where no model did), then the answer's time and cost as resultLines says them.
assert.equal(choicesOver(teo), "Teo's choices");
// A newcomer's notes (A7): a model's decision names the model's parts; a person playing's, What happened's alone; Compare's
// only where C shows; an unnamed being inside the sentence.
const noted = decisionNotes({ who: teo, decider: 'model', canCompare: true });
assert.equal(noted.by, 'The open model that chose for Teo, how long it took to answer, and what this one choice cost.');
assert.equal(noted.told, "The prompt Teo's model was given: everything it was told about that moment, and nothing more. Full record shows it as it was sent.");
assert.equal(noted.choices, 'The actions the world allowed Teo there. The model picked one, and the world checked it before it happened.');
assert.equal(noted.happened, 'What the choice did in the world, at that minute.');
assert.equal(noted.compare, 'Compare asks another open model the same moment, to see what it would choose.');
assert.equal(decisionNotes({ who: teo, decider: 'model' }).compare, null);
assert.deepEqual({ ...decisionNotes({ who: teo, decider: 'person', canCompare: true }) }, { by: null, told: null,
  choices: 'The actions the world allowed Teo there. A person playing picked one, and the world checked it before it happened.',
  happened: 'What the choice did in the world, at that minute.', compare: null });
assert.equal(decisionNotes({ who: teo, decider: 'external' }).by, null);
assert.equal(decisionNotes({ who: teo, decider: 'external' }).choices,
  'The actions the world allowed Teo there. An outside program picked one, and the world checked it before it happened.');
assert.equal(decisionNotes({ who: teo }).choices, null);
assert.match(decisionNotes({ who: resident, decider: 'model' }).told, /^The prompt the resident's model was given/);
assert.deepEqual({ ...DECISION_NOTE_WORDS }, { hide: 'Hide notes', show: 'Notes' });
assert.equal(choicesOver(resident), "The resident's choices");
assert.equal(choseOneOf(9), 'chose 1 of 9');
assert.equal(DECISION_FLOW_WORDS.whatHappened, 'What happened');
assert.equal(DECISION_WORDS.chosen, 'Chosen');
assert.equal(toldLabel(teo), "What Teo's model was told");
assert.deepEqual([answeredIn(912), answeredIn(13), answeredIn(100), answeredIn(null)], ['answered in 0.9 s', 'answered in under 0.1 s', 'answered in 0.1 s', null]);
assert.deepEqual([costWords('0.00030000'), costWords('0.0014006', false), costWords('0'), costWords(null), costWords('nonsense')], ['cost $0.0003', 'cost at most $0.0014', 'cost $0', null, null]);
const partsText = parts => parts.map(part => typeof part === 'string' ? part : part.model).join('');
assert.deepEqual(decidedByParts({ model: 'Nemotron 3 Nano 30B', ...record }), ['Decided by ', { model: 'Nemotron 3 Nano 30B' }, ' · answered in 0.9 s · cost $0.0003']);
assert.deepEqual(decidedByParts({ decider: 'model', model: ' Nemotron 3 Nano 30B ' }), ['Decided by ', { model: 'Nemotron 3 Nano 30B' }]);
assert.deepEqual(decidedByParts({ decider: 'person' }), ['Decided by a person playing']);
assert.equal(partsText(decidedByParts({ decider: 'external', latencyMs: 1300 })), 'Decided by an outside program · answered in 1.3 s');
assert.equal(partsText(decidedByParts({ decider: 'person', model: 'Nemotron 3 Nano 30B' })), 'Decided by a person playing');
assert.deepEqual(decidedByParts({ latencyMs: 1300, costUsd: '0.0014006', costKnown: false }), ['Answered in 1.3 s · cost at most $0.0014']);
assert.deepEqual(decidedByParts({}), []);
assert.deepEqual(decidedByParts(), []);

// A need, words first (ruling J14): needed now only above the level people see to it at.
assert.equal(needLine('rest', 417, 500), 'Rest: not needed yet (417 of 1000).');
assert.equal(needLine('rest', 500, 500), 'Rest: not needed yet (500 of 1000).');
assert.equal(needLine('a meal', 712, 700), 'A meal: needed now (712 of 1000).');
assert.equal(needLine('rest', 502, null), 'Rest: not needed yet (502 of 1000).');
assert.equal(needLine('', 10, 5), null);
// Every living need has a label to say, from the catalog the society reads.
const needs = JSON.parse(repository('assets/catalogs/society/society-need.v1.json')).entries;
for (const need of needs) assert.match(needLine(need.label, need.urgency_threshold_milli + 1, need.urgency_threshold_milli), /^[A-Z][^:]*: needed now \(\d+ of 1000\)\.$/);

// A town's context: its clock is the minute being chosen for (day counted from 0).
const town = {
  here: 'on the glass terraces', role: 'resident', tick: 53, clock: { day: 0, minute_of_day: 414 },
  doing: { kind: 'idle', reason: 'waiting_a_minute', status: 'active' },
  needs: [{ label: 'rest', milli: 417, seen_to_at_milli: 500 }, { label: 'a meal', milli: 712, seen_to_at_milli: 700 }],
  options: [{ kind: 'target', label: 'walking, 62 m away' }, { kind: 'wait', label: 'wait here a minute' }, { kind: 'target', label: 'at home, 35 m away' }],
};
assert.deepEqual(toldSections(town, resident), [
  { label: 'Where and when', lines: ['On the glass terraces · 06:54 · Day 1'] , apart: false },
  { label: 'How the resident is', lines: ['Rest: not needed yet (417 of 1000).', 'A meal: needed now (712 of 1000).'] , apart: true },
]);
// A society of things' model told the world's clock (clock_told) is shown it as told; before that it was told a minute.
assert.deepEqual(toldSections({ here: 'on the quay', tick: 27, world_clock: { minute_of_day: 1108, day: 0 } }, resident)[0].lines, ['On the quay · 18:28 · Day 1']);
assert.deepEqual(toldSections({ here: 'on the quay', tick: 27 }, resident)[0].lines, ['On the quay · Minute 27']);
// A town's premises told by name (places_named, P3): the page shows where the model stood and what it remembered as
// told, at a premises' door, inside one, and a premises remembered by what the being did there.
const town7 = (at) => ({ tick: 638, world_clock: { minute_of_day: 1118, day: 0 },
  surroundings: { at, beings: [], things: [], more_beings: 0, more_things: 0 },
  remembers: { beings: [], places: [{ words: 'visited the restaurant at number 7', last_minutes_ago: 10 }], handed: [] } });
assert.deepEqual(toldSections(town7({ words: 'at the restaurant at number 7', good_for: 'others can visit it' }), teo).map(section => section.lines),
  [['At the restaurant at number 7 (others can visit it) · 18:38 · Day 1'], ['Visited the restaurant at number 7, 10 minutes ago.']]);
assert.deepEqual(toldSections(town7({ words: 'in the restaurant at number 7' }), teo)[0].lines, ['In the restaurant at number 7 · 18:38 · Day 1']);
assert.deepEqual(choiceRows(town, 'wait here a minute'), [
  { number: 1, words: 'Walking, 62 m away', chosen: false },
  { number: 2, words: 'Wait here a minute', chosen: true },
  { number: 3, words: 'At home, 35 m away', chosen: false },
]);

// A garden's context: told the minute, one tiredness, what it holds, who is near, what was heard
// and what is remembered, in the frame's order, the personality first.
const garden = {
  tick: 4, character: { name: 'Teo', about: 'A slow, kind resident who likes the pools.' },
  need_milli: 802, rest_at_need_milli: 750, holding: ['acorn'],
  surroundings: {
    at: { words: 'by the lower pools', good_for: 'others can rest at it' },
    beings: [{ who: 'Ines', metres: 3, doing: 'standing', holding: [], hears_you: true, from_elsewhere: false },
      { who: 'a duck', metres: 0, doing: 'resting', holding: ['leaf'], hears_you: false, from_elsewhere: true }],
    things: [{ what: 'bench', metres: 4, good_for: ['sitting'] }], more_beings: 2, more_things: 1,
  },
  heard: [{ from: 'Ines', line: 'Morning.', minutes_ago: 1, to_you: true }],
  remembers: { beings: [{ who: 'Ines', met_minutes_ago: 3, here: true }, { who: 'Ari', met_minutes_ago: 1, here: false }],
    places: [{ words: 'the lower pools', last_minutes_ago: 0 }, { words: 'the bench', last_minutes_ago: 2 }, { words: 'the gate', last_minutes_ago: 9 }],
    handed: [{ way: 'gave', who: 'Ines', thing: 'acorn', minutes_ago: 2 }] },
  options: [{ label: 'say something' }, { label: 'rest, 4 m away' }],
};
assert.deepEqual(toldSections(garden, teo), [
  { label: 'Personality, as you wrote it', lines: ['Teo', 'A slow, kind resident who likes the pools.'] , apart: false },
  { label: 'Where and when', lines: ['By the lower pools (others can rest at it) · Minute 4'] , apart: false },
  { label: 'How Teo is', lines: ['Rest: needed now (802 of 1000).', 'Holding the acorn.'] , apart: true },
  { label: 'Near Teo', lines: ['Ines, 3 m away, standing, can hear Teo.', 'A duck, beside Teo, resting, holding the leaf, from another world.', 'The bench, 4 m away.', 'And 3 more farther away.'] , apart: false },
  { label: 'Heard', lines: ['Ines, 1 minute ago: “Morning.”'] , apart: false },
  { label: 'Remembers', lines: ['Ines, met 3 minutes ago.', 'Ari, met 1 minute ago, no longer here.', 'The lower pools, this minute.', 'The bench, 2 minutes ago.'] , apart: false, more: 'And 2 more in the Full record.' },
]);
assert.deepEqual(toldSections({}, teo), []);
// D4: Heard shows the newest three lines in the order they were told, the rest in the Full record; three or fewer, all.
const heardOf = count => ({ heard: Array.from({ length: count }, (_, at) => ({ from: `Ines ${at + 1}`, line: `Line ${at + 1}.`, minutes_ago: count - at, to_you: false })) });
assert.deepEqual(toldSections(heardOf(5), teo).find(section => section.label === 'Heard').lines,
  ['Ines 3, 3 minutes ago: “Line 3.”', 'Ines 4, 2 minutes ago: “Line 4.”', 'Ines 5, 1 minute ago: “Line 5.”']);
assert.deepEqual(['And 2 earlier lines in the Full record.', 'And 1 earlier line in the Full record.', undefined],
  [5, 4, 3].map(count => toldSections(heardOf(count), teo).find(section => section.label === 'Heard').more));

// Plain words: no em dash, no code, no "it" for a character (the personality is "it": as you wrote it;
// a spot's own words, in brackets, are the server's and name a place).
const said = [...Object.values(DECISION_WORDS), ...Object.values(DECISION_FLOW_WORDS), choicesOver(teo), choicesOver(resident), choseOneOf(9),
  ...toldSections(garden, teo).flatMap(section => [section.label, ...section.lines])];
for (const words of said) {
  assert.doesNotMatch(words, /\u2014|_/, words);
  assert.doesNotMatch(words.replace('as you wrote it', '').replace(/\([^)]*\)/gu, ''), /\b(it|he|she)\b/i, words);
}
console.log('decision words: ok');
