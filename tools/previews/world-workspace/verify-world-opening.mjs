import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { BAKING_STAGE, OPENING_EVENT, OPENING_STAGES, STEP_EASE, bakeReach, bakeShare, easedShare, openingProgress, populationLine, readHandoff, speedBars } from './opening-steps.mjs';
import { OPENING_WORDS } from './world-words.mjs';
import { SEAMS, patchSource } from './seams.mjs';

// The line moves only on a real report, in the loader's order; a later report before an earlier one
// does not move it.
assert.deepEqual(openingProgress([]), { fraction: 0, words: 'Reading the world', done: false });
assert.deepEqual(openingProgress(['world-read']), { fraction: 1 / 3, words: 'Drawing the land', done: false });
assert.deepEqual(openingProgress(['land-drawn']), { fraction: 0, words: 'Reading the world', done: false });
assert.deepEqual(openingProgress(['world-read', 'land-drawn', 'people-in']), { fraction: 1, words: null, done: true });
assert.deepEqual(openingProgress(['world-read', 'nothing']), openingProgress(['world-read']));
// A town still baking opens with its bake (C3): the line moves within that stage by the share the
// entry's tiles give, and the loader's own stages follow it.
const baking = [BAKING_STAGE, ...OPENING_STAGES];
assert.deepEqual(openingProgress([], baking, 0.5), { fraction: 0.5 / 4, words: 'Making the land', done: false });
assert.deepEqual(openingProgress(['land-made'], baking), { fraction: 1 / 4, words: 'Reading the world', done: false });
assert.equal(openingProgress([], baking, 7).fraction, 1 / 4);
assert.equal(openingProgress([], baking, Number.NaN).fraction, 0);
// Only facts the entry serves move it: a baked tile counts whole, a baking tile the steps it states.
assert.equal(bakeShare([{ state: 'baking' }, { state: 'baking' }]), 0);
assert.equal(bakeShare([{ state: 'baked' }, { state: 'baking' }]), 0.5);
assert.equal(bakeShare([{ state: 'baking', stepsFinished: 1, steps: 4 }, { state: 'baking', stepsFinished: 3, steps: 4 }]), 0.5);
assert.equal(bakeShare([{ state: 'baking', stepsFinished: 9, steps: 4 }, { state: 'failed' }]), 0.5);
assert.equal(bakeShare([{ state: 'baking', stepsFinished: 2 }]), 0);
assert.equal(bakeShare([]), 0);
assert.equal(bakeShare(undefined), 0);
// Where the bake would stand once each baking tile's running step ends (C3c): one step on, never past all of them.
assert.equal(bakeReach([{ state: 'baking', stepsFinished: 2, steps: 4 }, { state: 'baking', stepsFinished: 2, steps: 4 }]), 0.75);
assert.equal(bakeReach([{ state: 'baked' }, { state: 'baking', stepsFinished: 0, steps: 4 }]), 0.625);
assert.equal(bakeReach([{ state: 'baking', stepsFinished: 4, steps: 4 }]), 1);
for (const tiles of [[{ state: 'baking' }], [{ state: 'baking', stepsFinished: 2 }], [], undefined]) assert.equal(bakeReach(tiles), bakeShare(tiles));
// Within a step the line eases toward its end: from where it began at once, half of STEP_EASE.most of the way in
// halfMs, slower as it nears, never as far as the end; nowhere where the end is not ahead.
assert.equal(easedShare(0.5, 0.75, 0), 0.5);
assert.ok(Math.abs(easedShare(0.5, 0.75, STEP_EASE.halfMs) - (0.5 + 0.25 * STEP_EASE.most / 2)) < 1e-12);
{
  const at = [1000, 4000, 15000, 60000, 3_600_000].map((ms) => easedShare(0.5, 0.75, ms));
  for (let i = 1; i < at.length; i++) assert.ok(at[i] > at[i - 1] && at[i] - at[i - 1] < 0.25);
  assert.ok(at.every((share) => share < 0.5 + 0.25 * STEP_EASE.most + 1e-12 && share < 0.75));
}
assert.equal(easedShare(0.75, 0.75, 5000), 0.75);
assert.equal(easedShare(0.75, 0.5, 5000), 0.75);

// Every stage the opening shows is reported by a seam of the served app, once, with the event the
// opening listens for: no stage is shown that the loader does not report.
const main = readFileSync(new URL('../../../web/packages/app/src/main.ts', import.meta.url), 'utf8');
const served = patchSource('web/packages/app/src/main.ts', main, '/here');
// The opening starts from the first script: bootstrap.ts loads it beside the app.
const boot = patchSource('web/packages/app/src/bootstrap.ts', readFileSync(new URL('../../../web/packages/app/src/bootstrap.ts', import.meta.url), 'utf8'), '/here');
assert.ok(boot.indexOf("world-opening.ts').then((opening) => opening.mountOpening()") >= 0 && boot.indexOf('world-opening.ts') < boot.indexOf("void import('./main.js')"));
for (const stage of [BAKING_STAGE, ...OPENING_STAGES]) {
  assert.equal(served.split(`detail: { report: '${stage.report}'`).length - 1, 1, stage.report);
}
// Every stage's report, and the bake's share, each dispatched in one place.
assert.equal(served.split(`new CustomEvent('${OPENING_EVENT}'`).length - 1, OPENING_STAGES.length + 2);
assert.equal(served.split('detail: { baking: bakeShare(entry.generatedGround?.tiles), reach: bakeReach(entry.generatedGround?.tiles) }').length - 1, 1);
assert.ok(SEAMS.some((one) => one.seam === 'land drawn'));
// The land is reported after the renderer mounts and before the people begin.
assert.ok(served.indexOf("report: 'land-drawn'") > served.indexOf('const renderer = await mountRenderer('));
assert.ok(served.indexOf("report: 'people-in'") > served.indexOf("report: 'land-drawn'"));

// Speed: one bar at the slowest, all seven at the fastest, by ratio between.
assert.equal(speedBars(2), 1);
assert.equal(speedBars(150), 7);
assert.equal(speedBars(12), 3);
assert.equal(speedBars(Math.sqrt(2 * 150)), 4);
assert.equal(speedBars(1), 1);
assert.equal(speedBars(1000), 7);
assert.equal(speedBars(NaN), 1);

// The banner's line, and none where nobody lives.
assert.equal(populationLine(24), '24 people live here');
assert.equal(populationLine(1), '1 person lives here');
for (const none of [0, null, undefined, -3, 1.5]) assert.equal(populationLine(none), null);

// The handoff from the front door names one world, carries only a picture's data, and anything
// else reads as none.
assert.deepEqual(readHandoff(JSON.stringify({ entryId: 'a', title: 'Bay', picture: 'data:image/jpeg;base64,AA' }), 'a'), { entryId: 'a', title: 'Bay', picture: 'data:image/jpeg;base64,AA', baking: false });
// A town still baking says so, so its opening names the bake from the first frame (C3b); only true counts.
assert.equal(readHandoff(JSON.stringify({ entryId: 'a', title: 'Bay', baking: true }), 'a').baking, true);
assert.equal(readHandoff(JSON.stringify({ entryId: 'a', title: 'Bay', baking: 'yes' }), 'a').baking, false);
assert.equal(readHandoff(JSON.stringify({ entryId: 'b', title: 'Bay' }), 'a'), null);
assert.equal(readHandoff(JSON.stringify({ entryId: 'a', title: 'Bay', picture: 'blob:http://x/1' }), 'a').picture, null);
assert.equal(readHandoff('not json', 'a'), null);
assert.equal(readHandoff(null, 'a'), null);

assert.deepEqual(OPENING_WORDS.tipKeys.map((one) => one.word), ['Fly', 'Up', 'Down']);
for (const file of ['opening-steps.mjs', 'world-opening.ts']) {
  assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /\u2014/u, file);
}

export default true;
