import assert from 'node:assert/strict';
import { DAY_LAYOUTS, NARROW_BELOW, dayCapacity, dayLayout, dayView, stepChoice } from './day-rows.mjs';

const { wide, narrow } = DAY_LAYOUTS;

// The 1920 page and the 1440 page, chosen by width as History chooses (narrower than 1700 is 1440's).
assert.equal(dayLayout(1920), wide);
assert.equal(dayLayout(NARROW_BELOW), wide);
assert.equal(dayLayout(NARROW_BELOW - 1), narrow);
assert.equal(dayLayout(1440), narrow);

// 1440's rules: margins 80, titles 60, pictures 0.86 of their size, keys 64 in and 32 up.
assert.equal(narrow.left, 80);
assert.equal(narrow.title, 60);
assert.equal(narrow.picture.width, Math.round(wide.picture.width * 0.86));
assert.equal(narrow.picture.height, Math.round(wide.picture.height * 0.86));
assert.equal(narrow.portrait, Math.round(wide.portrait * 0.86));
assert.deepEqual([narrow.keysRight, narrow.keysBottom], [64, 32]);
assert.deepEqual([wide.keysRight, wide.keysBottom], [100, 40]);

// r06 at 1920 by 1080: five cards 160 apart from 150, the dots 21 under each top, the path from the newest card's top
// to the oldest dot (frames/r06-day.html: "M 880 150 L 880 811"), the words 28 past a 208 picture.
const five = dayView({ count: 5, chosen: 2, layout: wide, width: 1920, height: 1080 });
assert.equal(five.capacity, 5);
assert.deepEqual(five.items.map((item) => item.top), [150, 310, 470, 630, 790]);
assert.deepEqual(five.items.map((item) => item.dot), [171, 331, 491, 651, 811]);
assert.deepEqual(five.path, { x: 880, from: 150, to: 811 });
assert.equal(five.wordsX, 1156);
assert.deepEqual([five.newer, five.older], [false, false]);
// Every card in view stands whole above the band kept for the keys.
for (const item of five.items) assert.ok(item.top + wide.picture.height <= 1080 - wide.foot);

// More than fit: the chosen card is kept in view; a choice inside the view moves nothing; the path runs past the
// cards out of view, up under "What Teo did" for newer ones and down to the band over the page's foot for older ones.
const oldest = dayView({ count: 7, chosen: 6, layout: wide, width: 1920, height: 1080 });
assert.equal(oldest.first, 2);
assert.deepEqual(oldest.items.map((item) => item.index), [2, 3, 4, 5, 6]);
assert.deepEqual([oldest.newer, oldest.older], [true, false]);
assert.deepEqual(oldest.path, { x: 880, from: wide.pathTop, to: 811 });
assert.ok(wide.pathTop > wide.top + 14, 'the path starts under the label');
assert.equal(dayView({ count: 7, chosen: 3, first: 2, layout: wide, width: 1920, height: 1080 }).first, 2);
const newest = dayView({ count: 7, chosen: 0, first: 2, layout: wide, width: 1920, height: 1080 });
assert.equal(newest.first, 0);
assert.deepEqual(newest.path, { x: 880, from: 150, to: 1080 - wide.foot });
// With nothing chosen the view stays where it was, never past the oldest card.
assert.equal(dayView({ count: 7, chosen: null, first: 9, layout: wide, width: 1920, height: 1080 }).first, 2);
assert.equal(dayView({ count: 3, chosen: null, first: 2, layout: wide, width: 1920, height: 1080 }).first, 0);

// 1440 by 900: four cards at 0.86 of the spacing, the words 28 past a 179 picture, the cards to the key row's edge.
const small = dayView({ count: 5, chosen: 0, layout: narrow, width: 1440, height: 900 });
assert.equal(small.capacity, 4);
assert.deepEqual(small.items.map((item) => item.top), [150, 288, 426, 564]);
assert.deepEqual(small.items.map((item) => item.dot), [168, 306, 444, 582]);
assert.deepEqual(small.path, { x: 640, from: 150, to: 900 - narrow.foot });
assert.equal(small.wordsX, 887);
assert.equal(small.itemWidth, 1440 - 64 - 680);
for (const item of small.items) assert.ok(item.top + narrow.picture.height <= 900 - narrow.foot);
// The who column ends before the day begins, with room between.
for (const layout of [wide, narrow]) assert.ok(layout.left + layout.whoWidth + 40 <= layout.labelX);

// No cards, no path; a page too short for one card still shows the chosen one.
assert.equal(dayView({ count: 0, layout: wide, width: 1920, height: 1080 }).path, null);
assert.equal(dayCapacity(wide, 300), 1);
assert.deepEqual(dayView({ count: 4, chosen: 3, layout: wide, width: 1920, height: 300 }).items.map((item) => item.index), [3]);

// The arrows step over a line heard (T6) and stop at either end.
const heard = new Set([1]);
const choosable = (index) => !heard.has(index);
assert.equal(stepChoice(4, 0, 1, choosable), 2);
assert.equal(stepChoice(4, 2, -1, choosable), 0);
assert.equal(stepChoice(4, 3, 1, choosable), 3);
assert.equal(stepChoice(4, 0, -1, choosable), 0);
assert.equal(stepChoice(4, null, 1, choosable), 0);

console.log("Day rows checks passed: r06's places at 1920 and 1440, the chosen card kept in view, the path's ends and the arrows over lines heard.");
