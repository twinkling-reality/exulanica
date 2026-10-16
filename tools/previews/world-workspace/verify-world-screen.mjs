// Checks world-screen.mjs in Node: the rail's buttons, the keys card's rows, the clock's line and when
// the first-minute hint leaves (R-WORLD-BUILD-SHEET). Run: node verify-world-screen.mjs
import assert from 'node:assert/strict';
import { SCREEN_TIMING, clockText, firstHintLeaves, keysCardRows, railButtonOf, railEntries } from './world-screen.mjs';

// The rail: Your worlds, a divider, Build and History only where they work here, Fly last; flying
// lights Fly and names it Land.
const ids = (list) => list.map((entry) => (entry === 'divider' ? '|' : entry.id));
assert.deepEqual(ids(railEntries({ build: true, history: true, flying: false })), ['worlds', '|', 'build', 'history', 'fly']);
assert.deepEqual(ids(railEntries({ build: false, history: true, flying: false })), ['worlds', '|', 'history', 'fly']);
const walking = railEntries({ build: true, history: true, flying: false }).at(-1);
const flying = railEntries({ build: true, history: true, flying: true }).at(-1);
assert.deepEqual([walking.word, walking.lit, flying.word, flying.lit], ['Fly', false, 'Land', true]);
assert.deepEqual(railEntries({ build: true, history: true, flying: false }).filter((one) => one !== 'divider').map((one) => one.key), ['Esc', 'B', 'H', 'F']);
assert.equal(railButtonOf('KeyH'), 'history');
assert.equal(railButtonOf('KeyW'), null);

// The keys card: every key of the world view that works here, no new key; Build, History and Play
// only where they do.
const words = (list) => list.map((row) => row.word);
assert.deepEqual(words(keysCardRows({ build: true, history: true, clock: true })), ['Move', 'Sprint', 'Look', 'Inspect', 'Fly', 'Build', 'History', 'Play', 'Follow', 'Your worlds']);
assert.deepEqual(words(keysCardRows({ build: false, history: true, clock: false })), ['Move', 'Sprint', 'Look', 'Inspect', 'Fly', 'History', 'Follow', 'Your worlds']);
assert.equal(keysCardRows({}).find((row) => row.word === 'Look').keys, 'mouse-click');

assert.equal(clockText('06:55', 1), '06:55 · Day 1');

// The first-minute hint stays until the person has both walked and looked, or for its minute.
const rule = SCREEN_TIMING.firstHint;
assert.equal(firstHintLeaves({ shownMs: 1_000, walkedM: rule.walkedM, turnedRad: 0 }), false, 'walked only');
assert.equal(firstHintLeaves({ shownMs: 1_000, walkedM: 0, turnedRad: rule.lookedRad }), false, 'looked only');
assert.equal(firstHintLeaves({ shownMs: 1_000, walkedM: rule.walkedM, turnedRad: rule.lookedRad }), true);
assert.equal(firstHintLeaves({ shownMs: rule.leaveAfterMs, walkedM: 0, turnedRad: 0 }), true, 'after its minute');
assert.equal(firstHintLeaves({ shownMs: rule.leaveAfterMs - 1, walkedM: 0, turnedRad: 0 }), false);
console.log('World screen checks passed: the rail, the keys card, the clock\'s line and the first-minute hint.');
