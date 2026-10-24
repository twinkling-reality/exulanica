import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { BAKING_STAGE, OPENING_EVENT, OPENING_STAGES, bakeShare, openingProgress, populationLine, readHandoff, speedBars } from './opening-steps.mjs';
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
assert.equal(bakeShare([{ state: 'baking', stepsDone: 1, steps: 4 }, { state: 'baking', stepsDone: 3, steps: 4 }]), 0.5);
assert.equal(bakeShare([{ state: 'baking', stepsDone: 9, steps: 4 }, { state: 'failed' }]), 0.5);
assert.equal(bakeShare([{ state: 'baking', stepsDone: 2 }]), 0);
assert.equal(bakeShare([]), 0);
assert.equal(bakeShare(undefined), 0);

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
assert.equal(served.split('detail: { baking: bakeShare(').length - 1, 1);
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
assert.deepEqual(readHandoff(JSON.stringify({ entryId: 'a', title: 'Bay', picture: 'data:image/jpeg;base64,AA' }), 'a'), { entryId: 'a', title: 'Bay', picture: 'data:image/jpeg;base64,AA' });
assert.equal(readHandoff(JSON.stringify({ entryId: 'b', title: 'Bay' }), 'a'), null);
assert.equal(readHandoff(JSON.stringify({ entryId: 'a', title: 'Bay', picture: 'blob:http://x/1' }), 'a').picture, null);
assert.equal(readHandoff('not json', 'a'), null);
assert.equal(readHandoff(null, 'a'), null);

assert.deepEqual(OPENING_WORDS.tipKeys.map((one) => one.word), ['Fly', 'Up', 'Down']);
for (const file of ['opening-steps.mjs', 'world-opening.ts']) {
  assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /\u2014/u, file);
}

export default true;
