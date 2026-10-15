import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DECISION_WORDS, askedAt, choiceRows, choicesLabel, decisionTitle, needLine, overLabel, resultLines, toldLabel, toldSections } from './decision-words.mjs';
import { called } from './character-words.mjs';

const repository = path => readFileSync(new URL('../../../' + path, import.meta.url), 'utf8');
const teo = called({ name: 'Teo' }), resident = called({ kind: 'resident' });

// Frame 10's labels, called by name or kind, never "it".
assert.equal(toldLabel(teo), "What Teo's model was told");
assert.equal(toldLabel(resident), "What the resident's model was told");
assert.equal(choicesLabel(teo, 9), "Teo's choices (9)");
assert.equal(choicesLabel(resident, 3), "The resident's choices (3)");
assert.equal(overLabel({ at: askedAt(52, 360), who: teo, said: true, to: 'Ines' }), '06:52 · Day 1 · Teo said to Ines');
assert.equal(overLabel({ at: askedAt(1500, 360), who: teo }), '07:00 · Day 2');
assert.equal(overLabel({ at: askedAt(4, null), who: resident, said: true }), 'The resident said');
assert.equal(overLabel({ at: null, who: teo }), '');
assert.equal(decisionTitle({ line: ' Morning, Ines. ', chose: 'say something' }), '“Morning, Ines.”');
assert.equal(decisionTitle({ chose: 'wait here a minute' }), 'Wait here a minute');

// What came of it is the choice account's verdict: Done with its time, else the verdict's words.
const record = { latencyMs: 912, costUsd: '0.00030000', costKnown: true };
assert.deepEqual(resultLines({ verdict: { kind: 'applied', words: 'Applied in minute 53.' }, doneAt: '06:53', ...record }),
  { done: 'Done at 06:53 · answered in 0.9 s · cost $0.0003', verdict: null });
assert.equal(resultLines({ verdict: { kind: 'applied' }, ...record }).done, 'Done · answered in 0.9 s · cost $0.0003');
assert.deepEqual(resultLines({ verdict: { kind: 'pending', words: 'Accepted; no minute has acted on it yet.' }, latencyMs: 1300, costUsd: '0.0014006', costKnown: false }),
  { done: 'Answered in 1.3 s · cost at most $0.0014', verdict: 'Accepted; no minute has acted on it yet.' });
assert.deepEqual(resultLines({ verdict: { kind: 'awaiting_answer', words: 'No answer is recorded yet.' } }), { done: null, verdict: 'No answer is recorded yet.' });
assert.equal(resultLines({ verdict: { kind: 'applied' }, costUsd: '0' }).done, 'Done · cost $0');
// A time under a tenth of a second (DESIGN's W5).
assert.equal(resultLines({ verdict: { kind: 'applied' }, doneAt: '06:53', latencyMs: 13 }).done, 'Done at 06:53 · answered in under 0.1 s');
assert.equal(resultLines({ verdict: { kind: 'applied' }, latencyMs: 100 }).done, 'Done · answered in 0.1 s');

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
  { label: 'Remembers', lines: ['Ines, met 3 minutes ago.', 'Ari, met 1 minute ago, no longer here.', 'The lower pools, this minute.', 'The bench, 2 minutes ago.', 'And 2 more in the Full record.'] , apart: false },
]);
assert.deepEqual(toldSections({}, teo), []);

// Plain words: no em dash, no code, no "it" for a character (the personality is "it": as you wrote it;
// a spot's own words, in brackets, are the server's and name a place).
const said = [...Object.values(DECISION_WORDS), ...toldSections(garden, teo).flatMap(section => [section.label, ...section.lines])];
for (const words of said) {
  assert.doesNotMatch(words, /\u2014|_/, words);
  assert.doesNotMatch(words.replace('as you wrote it', '').replace(/\([^)]*\)/gu, ''), /\b(it|he|she)\b/i, words);
}
console.log('decision words: ok');
