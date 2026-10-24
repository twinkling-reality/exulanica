import assert from 'node:assert/strict';
import { COMPARE_LAYOUTS, NARROW_BELOW, branchPlaces, branchWidth, compareLayout, momentXs, nameParts, saidParts, timeIndexes } from './compare-line.mjs';
import { LAYOUTS } from './history-rows.mjs';

const wide = compareLayout(1920), narrow = compareLayout(1440);
const NANO = 'Nemotron 3 Nano 30B', QWEN = 'Qwen3 235B Instruct';

// History's line (r12): x 120 to 1180 at y 560, the picked moment opened at 1260; at 1440 History's margin and line,
// 80 and 470, the opened moment at 940.
assert.deepEqual([wide.narrow, wide.margin, wide.lineY, wide.lineTo, wide.openLeft, wide.openWidth, wide.sumWidth], [false, 120, 560, 1180, 1260, 540, 1100]);
assert.deepEqual([narrow.narrow, narrow.margin, narrow.lineY, narrow.lineTo, narrow.openLeft, narrow.openWidth], [true, LAYOUTS.narrow.margin, LAYOUTS.narrow.lineY, 860, 940, 420]);
assert.equal(compareLayout(NARROW_BELOW).narrow, false);
// One moment opens in the left column under the head, at the answer's top; the rest of the layout is the same (H1).
for (const width of [1920, 1440]) {
  const one = compareLayout(width, true), many = compareLayout(width);
  assert.deepEqual([one.openLeft, one.openTop, one.openWidth], [many.margin, many.sumTop, many.openWidth], `one moment at the left: ${width}`);
  assert.deepEqual({ ...one, openLeft: 0 }, { ...many, openLeft: 0 });
}
assert.equal(compareLayout(NARROW_BELOW - 1).narrow, true);
assert.equal(COMPARE_LAYOUTS.wide.margin, LAYOUTS.wide.margin);
// At every width the opened moment ends a margin from the right edge, never cut by the window (1728 is a laptop's
// default; between 1700 and 1800 fixed places ran past it): the line ends before it, the answer in words too, and the
// head keeps within the margins.
for (const width of [2560, 1920, 1800, 1728, 1700, 1699, 1600, 1512, 1440, 1366, 1280]) {
  const layout = compareLayout(width);
  assert.equal(layout.openLeft + layout.openWidth, width - layout.margin, `opened moment ends a margin in: ${width}`);
  assert.equal(layout.lineTo, layout.openLeft - 80, `line ends 80 before it: ${width}`);
  assert.equal(layout.margin + layout.sumWidth, layout.openLeft - 40, `answer ends 40 before it: ${width}`);
  assert.ok(layout.margin + layout.headWidth <= width - layout.margin, `head within the margins: ${width}`);
}
assert.deepEqual([compareLayout(1728).openLeft, compareLayout(1728).lineTo], [1068, 988]);

// Twelve moments: the first 12 in from the line's start, the newest at its end, evenly apart.
const xs = momentXs(12, wide);
assert.equal(xs.length, 12);
assert.equal(xs[0], 132);
assert.equal(xs[11], 1180);
const gaps = xs.slice(1).map((x, index) => x - xs[index]);
assert.ok(Math.max(...gaps) - Math.min(...gaps) <= 0.2, 'evenly apart');
assert.deepEqual(momentXs(12, narrow).filter((_, index) => index === 0 || index === 11), [92, 860]);
assert.deepEqual(momentXs(1, wide), [132]);
assert.deepEqual(momentXs(0, wide), []);

// Times every third, counted back from the newest, and the oldest unless it sits beside one shown (the frame's
// 06:41, 06:43, 06:46, 06:49, 06:52).
assert.deepEqual(timeIndexes(xs), [0, 2, 5, 8, 11]);
assert.deepEqual(timeIndexes(momentXs(12, narrow)), [0, 2, 5, 8, 11]);
assert.deepEqual(timeIndexes(momentXs(11, wide)), [0, 1, 4, 7, 10]);
assert.deepEqual(timeIndexes(momentXs(2, wide)), [0, 1]);
assert.deepEqual(timeIndexes(momentXs(1, wide)), [0]);
assert.ok(!timeIndexes(momentXs(23, wide)).includes(0), 'the oldest beside a time shown keeps quiet');
const crowded = momentXs(60, narrow), shownTimes = timeIndexes(crowded);
assert.ok(shownTimes.slice(1).every((index, at) => crowded[index] - crowded[shownTimes[at]] >= 64), 'times never crowd');
assert.equal((shownTimes.at(-1) - shownTimes.at(-2)) % 3, 0, 'still every third, or a multiple of it');

// A model's name never breaks, so a long one widens its branch's words.
assert.equal(branchWidth('Qwen3 235B'), 120);
assert.equal(branchWidth(QWEN), Math.ceil(QWEN.length * 7.2));

// The frame's three different answers (06:43, 06:47, 06:51): the first two hang right on the first level, 642 their
// words' top; the last, too near the line's end to read rightwards, hangs left a level deeper, 762.
const frame = branchPlaces([2, 6, 10].map(index => ({ index, x: xs[index], width: 120 })), wide);
assert.deepEqual(frame.map(place => [place.index, place.level, place.side, place.top]), [[2, 0, 'right', 642], [6, 0, 'right', 642], [10, 1, 'left', 762]]);
assert.equal(frame[0].left, xs[2] + 26);
assert.equal(frame[2].left + 120, Math.round((xs[10] - 26) * 10) / 10);
assert.equal(frame[0].path, `M ${xs[2]} 567 L ${xs[2]} 640 Q ${xs[2]} 652 ${Math.round((xs[2] + 12) * 10) / 10} 652 L ${Math.round((xs[2] + 20) * 10) / 10} 652`);
// Two neighbours: the newer keeps the first level, the older hangs under it.
assert.deepEqual(branchPlaces([5, 6].map(index => ({ index, x: xs[index], width: 120 })), wide).map(place => [place.level, place.side]), [[1, 'right'], [0, 'right']]);
// The picked moment never moves a branch: places come from the moments alone (there is no focus to pass).
assert.equal(branchPlaces.length, 2);

// Every set of different answers among 12, at 1920, 1440, 1728 and 1280: words inside the line's span, never meeting
// other words on their level, never across another branch's line, the first level always reading rightwards, and no
// deeper than the layout allows; a branch without room is a short line alone.
for (const layout of [wide, narrow, compareLayout(1728), compareLayout(1280)]) {
  const at = momentXs(12, layout);
  let stubs = 0;
  for (let set = 1; set < 1 << 12; set += 1) {
    const branches = at.flatMap((x, index) => set & (1 << index) ? [{ index, x, width: index % 4 === 0 ? branchWidth(QWEN) : 120 }] : []);
    const places = branchPlaces(branches, layout);
    assert.deepEqual(places.map(place => place.index), branches.map(branch => branch.index));
    const hung = places.filter(place => place.level !== null);
    stubs += places.length - hung.length;
    for (const place of places.filter(one => one.level === null)) assert.equal(place.left, null);
    for (const place of hung) {
      const span = place.side === 'right' ? [place.x, place.left + place.width] : [place.left, place.x];
      assert.ok(span[0] >= layout.margin && span[1] <= layout.lineTo, `inside the line: ${set}`);
      assert.ok(place.level < layout.levels, `levels: ${set}`);
      if (place.level === 0) assert.equal(place.side, 'right', `first level reads rightwards: ${set}`);
      for (const other of hung) {
        if (other === place) continue;
        const otherSpan = other.side === 'right' ? [other.x, other.left + other.width] : [other.left, other.x];
        if (other.level === place.level) assert.ok(span[1] + 16 <= otherSpan[0] || otherSpan[1] + 16 <= span[0], `words apart: ${set}`);
        if (other.level > place.level) assert.ok(other.x < span[0] - 8 || other.x > span[1] + 8, `no words across a line: ${set}`);
      }
    }
  }
  assert.ok(stubs > 0, 'a crowded line keeps some branches short');
}
// Three apart at either size: every answer has its words.
assert.ok(branchPlaces([1, 4, 7, 10].map(index => ({ index, x: momentXs(12, narrow)[index], width: 120 })), narrow).every(place => place.level !== null));

// A sentence keeps each model's name whole; the longest name wins.
assert.deepEqual(nameParts('Qwen3 235B Instruct chose as Nemotron 3 Nano 30B did at 9 of 12 moments.', [NANO, QWEN]),
  [{ model: QWEN }, ' chose as ', { model: NANO }, ' did at 9 of 12 moments.']);
assert.deepEqual(nameParts('Asked again, Nemotron 3 Nano 30B, again chose', [NANO, `${NANO}, again`]), ['Asked again, ', { model: `${NANO}, again` }, ' chose']);
assert.deepEqual(nameParts('Nothing named.', [NANO]), ['Nothing named.']);
assert.deepEqual(nameParts('', [NANO]), []);

// An answer's words said stand apart from its plain lead.
assert.deepEqual(saidParts('Said to Ines: “Calm water today, Ines.”'), [{ words: 'Said to Ines: ', said: false }, { words: '“Calm water today, Ines.”', said: true }]);
assert.deepEqual(saidParts('Walk to the lower pools'), [{ words: 'Walk to the lower pools', said: false }]);
assert.deepEqual(saidParts('Said: “Morning.” then left'), [{ words: 'Said: ', said: false }, { words: '“Morning.”', said: true }, { words: ' then left', said: false }]);

console.log('Compare line checks passed: History\'s line, the times shown, where each branch hangs, and names kept whole.');
