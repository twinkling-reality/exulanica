import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { byDay, historyRows, timelineMarks } from './history-rows.mjs';
import { HISTORY_WORDS, chosenLabel, cost, dayHeading, money, onGitHub, runFacts, subLine } from './history-words.mjs';

// Money as the workspace writes it (rule 5, P1): cents, four places under a cent, never $0.0000.
assert.equal(money('0.05000000'), '$0.05');
assert.equal(money('0.0042'), '$0.0042');
assert.equal(money('0.000018'), 'less than $0.0001');
assert.equal(money('0'), '$0');
assert.equal(cost('0'), '');
assert.equal(cost(null), '');

// Days and the chosen label in the reader's own time (H3): Today, Yesterday, "13 Oct".
const now = new Date(2026, 9, 15, 10, 20).getTime();
const today = new Date(2026, 9, 15, 9, 44).getTime();
const yesterday = new Date(2026, 9, 14, 21, 5).getTime();
const before = new Date(2026, 9, 13, 8, 0).getTime();
assert.deepEqual([dayHeading(today, now), dayHeading(yesterday, now), dayHeading(before, now)], ['Today', 'Yesterday', '13 Oct']);
assert.deepEqual([chosenLabel(today, now), chosenLabel(yesterday, now), chosenLabel(before, now)], ['09:44 today', '21:05 yesterday', '08:00, 13 Oct']);

// A run's facts: world time only where the clock is read; the limit as "at most".
assert.equal(runFacts({ from: '06:00', to: '07:15', decisions: 12, spent: '0.0042', limit: '0.05' }), 'World time 06:00 to 07:15 · 12 decisions · spent $0.0042 of at most $0.05');
assert.equal(runFacts({ decisions: 1, spent: '0' }), '1 decision · spent $0');

// Where the world is kept: frame 23's sub-line and its other states (H4), the repository without its owner.
const github = { reached: true, visibility: 'PRIVATE', not_sent: 0, pull_request: { number: 3, title: "Teo's first run" }, paused: null, sent_through_at: '2026-10-15T08:00:00Z' };
const project = { link: { repository: 'learner/terraces-on-the-bay', publish: 'automatic' }, last_checkpoint_at: '2026-10-15T08:30:00Z', github };
assert.equal(subLine('Terraces on the bay', project), 'Terraces on the bay · kept in your GitHub project terraces-on-the-bay, private · up to date');
assert.equal(subLine('Terraces on the bay', { ...project, github: { ...github, not_sent: 1 } }), 'Terraces on the bay · kept in your GitHub project terraces-on-the-bay, private · 1 change not sent yet');
assert.equal(subLine('Terraces on the bay', { ...project, github: { ...github, not_sent: 3 } }).endsWith('3 changes not sent yet'), true);
assert.equal(subLine('Terraces on the bay', { ...project, github: { ...github, paused: { at: '2026-10-15T08:00:00Z', reason: 'the repository is no longer private' } } }).endsWith('sending to GitHub is paused'), true);
assert.equal(subLine('Terraces on the bay', null), 'Terraces on the bay · not linked to GitHub');
assert.equal(subLine('Terraces on the bay', undefined), 'Terraces on the bay', 'unread is not unlinked');

// On GitHub, by when the change was kept and sent: never the newest pull request on every row.
const sent = Date.parse('2026-10-15T07:59:00Z'), unsent = Date.parse('2026-10-15T08:10:00Z'), unkept = Date.parse('2026-10-15T08:40:00Z');
assert.equal(onGitHub(project, sent), 'Pull request 3, “Teo\'s first run”, waiting for you to merge');
assert.equal(onGitHub({ ...project, github: { ...github, pull_request: null } }, sent), 'Sent to GitHub');
assert.equal(onGitHub(project, unsent), 'Not sent to GitHub yet');
// Not kept yet (H5): said by the project's own settle period, as its follower states it.
assert.equal(onGitHub(project, unkept), 'Not kept in the project yet: it is kept once the changes stop.');
assert.equal(onGitHub({ ...project, settle_seconds: 120 }, unkept), 'Not kept in the project yet: it is kept once nothing has changed for 2 minutes.');
assert.equal(onGitHub({ ...project, settle_seconds: 60 }, unkept), 'Not kept in the project yet: it is kept once nothing has changed for 1 minute.');
assert.equal(onGitHub({ ...project, settle_seconds: 90 }, unkept), 'Not kept in the project yet: it is kept once nothing has changed for 90 seconds.');
assert.equal(onGitHub({ ...project, github: { ...github, reached: false } }, sent), 'GitHub could not be reached. Your changes are kept here and sent when it answers.');
assert.equal(onGitHub(null, sent), null);

// The rows, from the reads alone, newest first; build mode's sentence for an edit.
const names = { subject: (id) => ({ teo: 'Teo', ines: 'Ines' })[id] ?? 'the resident', placed: (id) => ({ 'teo:1': 'Teo' })[id] ?? 'the resident' };
const wordsOf = (edit) => ({ move_thing: 'Moved the bench', remove_thing: 'Removed the fan palm' })[edit.kind] ?? 'Changed the world';
const iso = (hour, minute) => new Date(2026, 9, 15, hour, minute).toISOString();
const reads = {
  edits: [
    { edit_id: 'e1', kind: 'move_thing', thing_id: 'bench:1', recorded_at: iso(10, 15) },
    { edit_id: 'e2', kind: 'remove_thing', thing_id: 'palm:1', recorded_at: iso(10, 16) },
  ],
  runs: [{ session_id: 's1', opened_at: iso(9, 44), minutes: 10, decisions: 12, done: 11, spent: '0.0042', limit: '0.05', subjects: ['teo'], models: ['Nemotron 3 Nano 30B'], ended: 'The run played all its minutes.', from: '06:00', to: '07:15' }],
  models: [
    { choice_seq: 2, recorded_at: iso(9, 41), subjects: ['teo'], decider: { kind: 'model' }, model: { name: 'Nemotron 3 Nano 30B' }, ended: false },
    { choice_seq: 3, recorded_at: iso(9, 50), subjects: ['ines'], decider: { kind: 'person' }, model: null, ended: false },
  ],
  characters: [{ placed_id: 'teo:1', revision: 1, states_name: true, states_about: true, written_at: iso(9, 40) }],
  comparisons: [{ comparison_id: 'c1', created_at: iso(10, 2), subject: 'Teo', models: ['Nemotron 3 Nano 30B', 'Qwen3 235B Instruct'], spent: '0.0031' }],
  creation: { at: iso(9, 12), readyWorld: null, spent: '0.31' },
};
const rows = historyRows(reads, names, wordsOf);
assert.deepEqual(rows.map((row) => [row.words, row.cost]), [
  ['Removed the fan palm', ''],
  ['Moved the bench', ''],
  ['Compared two models for Teo', '$0.0031'],
  ["Ran 10 minutes with Teo's model", '$0.0042'],
  ["Changed Teo's model to Nemotron 3 Nano 30B", ''],
  ["Wrote Teo's personality", ''],
  ['Created from your words', '$0.31'],
]);
const run = rows.find((row) => row.kind === 'run');
assert.equal(run.facts, 'World time 06:00 to 07:15 · 12 decisions · spent $0.0042 of at most $0.05');
assert.equal(run.happened, '12 decisions, 11 done.');
assert.equal(run.ended, 'The run played all its minutes.');
// A person playing a character is not a change of model; no row says "it".
assert.equal(rows.some((row) => /\bit\b/.test(row.words)), false);
// Personalities written, changed, cleared, by revision.
const later = historyRows({ characters: [
  { placed_id: 'teo:1', revision: 1, states_name: true, states_about: true, written_at: iso(9, 0) },
  { placed_id: 'teo:1', revision: 2, states_name: true, states_about: false, written_at: iso(9, 5) },
  { placed_id: 'teo:1', revision: 3, states_name: false, states_about: false, written_at: iso(9, 9) },
] }, names, wordsOf);
assert.deepEqual(later.map((row) => row.words), ["Cleared Teo's personality", "Changed Teo's personality", "Wrote Teo's personality"]);

// Under their days, and the timeline's marks around the chosen one, oldest first, Now drawn after.
assert.deepEqual(byDay(rows, (time) => dayHeading(time, now)).map((day) => [day.heading, day.rows.length]), [['Today', 7]]);
const marks = timelineMarks(rows, run.id, 7);
assert.deepEqual(marks.map((mark) => mark.words), ['Created from your words', "Wrote Teo's personality", "Changed Teo's model", 'Ran 10 minutes', 'Compared two models', 'Moved the bench', 'Removed the fan palm']);
assert.equal(marks.find((mark) => mark.chosen).words, 'Ran 10 minutes');
assert.deepEqual(marks.find((mark) => mark.words === 'Compared two models').branches, ['Nemotron 3 Nano 30B', 'Qwen3 235B Instruct']);
assert.deepEqual(timelineMarks(rows, rows[rows.length - 1].id, 3).map((mark) => mark.words), ['Created from your words', "Wrote Teo's personality", "Changed Teo's model"]);
assert.deepEqual(historyRows({}, names, wordsOf), []);

// The words are WORDS.md's: sentence case where they open a line, no banned word, no em dash.
for (const line of Object.values(HISTORY_WORDS)) assert.doesNotMatch(line, /\b(entity|session|provider|payload|context)\b/iu, line);
for (const row of rows) assert.match(row.words, /^[A-Z]/u, row.words);
for (const file of ['history-words.mjs', 'history-rows.mjs', 'history.ts', 'world-ui-history.ts', 'world-ui-history.css']) {
  assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /\u2014/u, file);
}

console.log('History checks passed: money and days, where the world is kept, rows from the reads newest first, personalities by revision, the timeline around the chosen change.');
