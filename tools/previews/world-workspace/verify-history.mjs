import assert from 'node:assert/strict';
import { changeParts, changeWords } from './build-words.mjs';
import { LAYOUTS, earlierBreak, historyPath, pathLayout, pathView, rowsWindow, runBrackets, targetObject } from './history-rows.mjs';
import {
  HEAD_WORDS, PATH_WORDS, branchWords, didWords, byParts, creationWhen, dayHeading, headLine, momentWords, money, partsText,
  personWhen, runSpanWords, youChangeWords, youModelParts, youPersonalityWords,
} from './history-words.mjs';

// Money as the workspace writes it (rule 5, P1): cents, four places under a cent, never $0.0000.
assert.equal(money('0.05000000'), '$0.05');
assert.equal(money('0.0042'), '$0.0042');
assert.equal(money('0.000018'), 'less than $0.0001');
assert.equal(money('0'), '$0');

// The person's own time (H4): today the clock alone on a change, the creation always with its day.
const now = new Date(2026, 9, 16, 9, 0).getTime();
const at = (day, hour, minute) => new Date(2026, 9, day, hour, minute).getTime();
assert.deepEqual([dayHeading(at(16, 8, 30), now), dayHeading(at(15, 21, 40), now), dayHeading(at(13, 8, 0), now)], ['Today', 'Yesterday', '13 Oct']);
assert.deepEqual([personWhen(at(16, 8, 30), now), personWhen(at(15, 21, 40), now)], ['08:30', 'Yesterday · 21:40']);
assert.deepEqual([creationWhen(at(16, 9, 12), now), creationWhen(at(15, 21, 40), now)], ['Today · 09:12', 'Yesterday · 21:40']);

// The head's GitHub line (sheet section 2), refusals marked for the refusal ink.
const github = { reached: true, visibility: 'PRIVATE', not_sent: 0, paused: null };
const linked = (state) => ({ link: { repository: 'learner/terraces-on-the-bay', publish: 'automatic' }, github: { ...github, ...state } });
assert.deepEqual(headLine(linked({})), { words: 'Kept on GitHub in terraces-on-the-bay, private · up to date', refused: false });
assert.equal(headLine(linked({ not_sent: 3 })).words, 'Kept on GitHub in terraces-on-the-bay, private · 3 changes not sent yet');
assert.equal(headLine(linked({ not_sent: 1 })).words, 'Kept on GitHub in terraces-on-the-bay, private · 1 change not sent yet');
assert.deepEqual(headLine(linked({ paused: { reason: 'the repository is no longer private' } })), { words: 'Kept on GitHub in terraces-on-the-bay · sending is paused: the repository is no longer private', refused: true });
assert.equal(headLine(linked({ reached: false })).words, HEAD_WORDS.unreachable);
assert.equal(headLine({ link: null }).words, 'Kept in a project on this computer, not on GitHub');
assert.equal(headLine(null).words, 'Not kept in a project');
assert.equal(headLine(null, { refused: null }).words, 'Starting a project…');
assert.deepEqual(headLine(null, { refused: { code: 'world_unreadable' } }), { words: 'Not kept: the world could not be read. Try again.', refused: true });
assert.equal(headLine(undefined).words, '');
// After Create in H12's question, until the follower links the project; a linked project says where it is.
assert.deepEqual(headLine({ link: null }, null, true), { words: 'Putting it on GitHub…', refused: false });
assert.equal(headLine(linked({}), null, true).words, 'Kept on GitHub in terraces-on-the-bay, private · up to date');

// The path (r23) from the moments read as JOURNEY's R1 serves it (society_moments.read_moments) and the other reads.
const things = { 'bench:1': 'bench', 'market:1': 'market', 'lantern:1': 'lantern', 'pond:part': null };
const subjects = { teo: 'Teo', ines: 'Ines', marco: 'Marco', ari: 'Ari' };
const names = {
  subject: (id) => subjects[id] ?? 'the resident',
  placed: (id) => ({ 'teo:1': 'Teo' })[id] ?? 'the resident',
  thing: (id) => things[id] ?? null,
  place: (place) => things[place.thing_id] ?? null,
  target: (target) => things[targetObject(target.target_id)] ?? null,
};
// A society's target: a placed thing's use (its object id may hold ':'), or a destination with no name.
const VID = '3c4d5e6f-0000-4000-8000-000000000002';
const use = (object, affordance = 'visit') => ({ target_id: `authored:${VID}:${object}:${affordance}`, activity: null });
assert.deepEqual([targetObject(use('market:1').target_id), targetObject(use('bench:1', 'sit').target_id), targetObject('destination:harbour-steps'),
  targetObject('authored:not-a-version:market:1:visit'), targetObject(null)], ['market:1', 'bench:1', null, null, null]);
const parts = { pond: 'pond', 'tea-house': 'tea house' };
const partsOf = (edit, edits) => changeParts(edit, edits, (id) => things[id] ?? null, (id) => parts[id] ?? null);
const clock = (tick) => (Number.isInteger(tick) ? { hhmm: `${String(Math.floor(tick / 60) % 24).padStart(2, '0')}:${String(tick % 60).padStart(2, '0')}`, day: Math.floor(tick / 1440) + 1 } : null);
const iso = (day, hour, minute) => new Date(at(day, hour, minute)).toISOString();
const model = (name) => ({ kind: 'model', model: { provider: 'nebius', model_id: name, name } });
const said = (tick, by, to, line, decider) => ({ tick, by, to: [to], line, decider });
const answer = (ask, minute, name, same, extra = {}) => ({ ask_id: ask, asked_at: iso(16, 9, minute), model: { provider: 'nebius', model_id: name, name }, same_choice: same, kind: 'carried_on', target: null, with: null, said: null, scene: null, picture: null, ...extra });
const stand = {
  creation: { at: iso(15, 21, 40), readyWorld: null, sentence: 'Glass terraces with pools above the sea, and a grand hotel at the top', picture: { sha256: 'p0', width: 1280, height: 720 } },
  edits: [{ edit_id: 'e1', kind: 'add_thing', thing_id: 'bench:1', recorded_at: iso(16, 8, 30) }],
  runs: [{ session_id: 's1', start_tick: 360, end_tick: 435, spent: '0.0042', closed: { end_tick: 435, reason: 'session_minutes', words: 'The run played all its minutes.' } }],
  nowTick: 435,
  moments: [
    { moment_id: 'm1', tick: 412, at: iso(16, 8, 52), session_id: 's1', kind: 'met', subjects: ['teo', 'ines'], place: { placed_id: 'placed-bench', thing_id: 'bench:1' }, target: null, with: null,
      said: [said(412, 'teo', 'ines', 'Morning, Ines. The boats are out early.', model('Nemotron 3 Nano 30B'))], decider: model('Nemotron 3 Nano 30B'), scene: {}, picture: { sha256: 'p1', width: 1280, height: 720 },
      branches: [answer('a0', 1, 'Llama 4', false, { kind: 'waited' }), answer('a1', 2, 'Qwen3 235B', false, { kind: 'went', target: use('market:1') })] },
    { moment_id: 'm2', tick: 415, at: iso(16, 8, 55), session_id: 's1', kind: 'went', subjects: ['ines', 'teo'], place: null, target: use('market:1'), with: null,
      said: [said(415, 'ines', 'teo', 'Early enough for the market?', model('Nemotron 3 Super 120B'))], decider: model('Nemotron 3 Super 120B'), scene: {}, picture: null, branches: [] },
    { moment_id: 'm3', tick: 429, at: iso(16, 9, 9), session_id: 's1', kind: 'spoke', subjects: ['marco', 'teo'], place: null, target: null, with: null,
      said: [said(429, 'marco', 'teo', 'Did they bring in anything good?', { kind: 'person', model: null }), said(430, 'teo', 'marco', 'Sardines, mostly.', model('Nemotron 3 Nano 30B')), said(431, 'marco', 'teo', 'Any for the hotel?', { kind: 'person', model: null })],
      decider: { kind: 'person', model: null }, scene: {}, picture: null, branches: [answer('a2', 10, 'Qwen3 235B', true, { kind: 'spoke' })] },
  ],
};
const path = historyPath(stand, names, partsOf, clock, now);
const text = (words) => (typeof words === 'string' ? words : words === null ? null : partsText(words));
assert.deepEqual(path.items.map((item) => [item.kind, item.when, text(item.words)]), [
  ['creation', 'Yesterday · 21:40', 'Made from your words'],
  ['change', '08:30', 'You placed the bench'],
  ['moment', '06:52 · Day 1', 'Teo met Ines at the bench'],
  ['moment', '06:55 · Day 1', 'Ines and Teo went to the market'],
  ['moment', '07:09 · Day 1', 'Marco asked Teo'],
]);
const [creation, single, met, went, asked] = path.items;
// A single change's words are the whole of it: it keeps no list and opens nothing (H15).
assert.equal('changes' in single, false);
assert.equal(creation.quote, 'Glass terraces with pools above the sea, and a grand hotel at the top');
assert.deepEqual([met.shown, met.more, text(met.by), met.subjects], [['Teo: “Morning, Ines. The boats are out early.”'], null, 'By Nemotron 3 Nano 30B', ['teo', 'ines']]);
// A model's name is a part the page keeps on one line.
assert.deepEqual(met.by, ['By ', { model: 'Nemotron 3 Nano 30B' }]);
// An exchange: the first two lines on the card, the rest counted; every line, with its own decider, opened.
assert.deepEqual([asked.shown, asked.more], [['Marco: “Did they bring in anything good?”', 'Teo: “Sardines, mostly.”'], '1 more line']);
assert.deepEqual(asked.lines.map((line) => [line.subject, line.quote, text(line.by)]), [
  ['marco', '“Did they bring in anything good?”', 'By a person playing'],
  ['teo', '“Sardines, mostly.”', 'By Nemotron 3 Nano 30B'],
  ['marco', '“Any for the hotel?”', 'By a person playing'],
]);
assert.deepEqual([text(went.by), text(asked.by)], ['By Nemotron 3 Super 120B', 'By a person playing']);
// Only an answer that differs is a branch, the newest drawn; a same answer is one small line on the card.
assert.deepEqual([text(met.branch.head), met.branch.outcome, met.same], ['Asked again with Qwen3 235B', 'Teo would have gone to the market', null]);
assert.deepEqual([asked.branch, text(asked.same)], [null, 'Qwen3 235B chose the same']);
// The opened moment holds every answer, oldest first.
assert.deepEqual(met.answers.map(text), ['Llama 4: Teo would have waited a minute', 'Qwen3 235B: Teo would have gone to the market']);
assert.deepEqual(asked.answers.map(text), ['Qwen3 235B chose the same']);
assert.deepEqual(path.spans.map((span) => [span.first, span.last, span.words, span.small, span.ended]), [
  ['moment:m1', 'moment:m3', "Teo's and Ines's models were deciding · 06:00 to 07:15 · spent $0.0042", "Teo's and Ines's models were deciding · 06:00 to 07:15", null],
]);
assert.equal(path.now.when, '07:15 · Day 1');
// A run that did not end at its own time says why, in the opened moment only (H3).
const stopped = historyPath({ ...stand, runs: [{ ...stand.runs[0], closed: { end_tick: 435, reason: 'stopped_by_person', words: 'The run was stopped.' } }] }, names, partsOf, clock, now);
assert.equal(stopped.spans[0].ended, 'The run was stopped.');

// On a going two people made together, each answer is said of the one whose decision it answers ("by"); an answer
// that takes a thing names it from its target.
const together = historyPath({ moments: [{ ...stand.moments[1], branches: [
  answer('b1', 3, 'Qwen3 235B', false, { by: 'teo', kind: 'went', target: use('bench:1', 'sit') }),
  answer('b2', 4, 'Llama 4', false, { by: 'ines', kind: 'picked_up', target: use('lantern:1', 'take') }),
] }] }, names, partsOf, clock, now);
assert.deepEqual(together.items[0].answers.map(text), ['Qwen3 235B: Teo would have gone to the bench', 'Llama 4: Ines would have picked up the lantern']);
assert.equal(together.items[0].branch.outcome, 'Ines would have picked up the lantern');

// Where items sit (r23's own: creation 120, the change 510, moments 600, 1020, 1440, Now 1800), and what a view
// draws: only whole items, the first at the margin, Now at its place while the newest end is in view.
const wide = LAYOUTS.wide, narrow = LAYOUTS.narrow;
const placed = pathLayout(path.items, wide);
assert.deepEqual([...placed.x.values()], [120, 510, 600, 1020, 1440]);
assert.equal(placed.nowAt, 1800);
const opening = pathView(path.items, placed, wide, 1920, 'moment:m3');
assert.deepEqual([opening.offset, opening.drawn.size, opening.now, opening.from, opening.to], [0, 5, 1800, 120, 1800]);
// 1440: r23's items do not fit; the view opens slid by whole items, the creation out of view, the change's words
// at the margin (x 80), the line running on to the window's left edge; Now's ring 120px from the right.
const small = pathLayout(path.items, narrow);
const opened = pathView(path.items, small, narrow, 1440, 'moment:m3');
assert.equal(small.extent.get(path.items[1].id)[0] + opened.offset, 80);
assert.deepEqual([opened.offset, [...opened.drawn], opened.now, opened.from], [-276, path.items.slice(1).map((item) => item.id), 1320, 0]);
// A change's words stay 16px clear of the picture before them (1440: the creation's).
assert.equal(small.extent.get(path.items[1].id)[0] - (small.x.get('creation') + narrow.card), 16);
// The choice reaching the first moment slides back to the start where that card stays whole: the creation shows,
// the newest moment is out of view, the line runs on to the right edge and Now is not drawn.
const first = pathView(path.items, small, narrow, 1440, 'moment:m1', opened.offset);
assert.deepEqual([first.offset, first.drawn.has('creation'), first.drawn.has('moment:m3'), first.now, first.to], [0, true, false, null, 1440]);
// A choice already whole moves nothing; the newest chosen again slides back to the newest end by whole items.
assert.equal(pathView(path.items, small, narrow, 1440, 'moment:m2', first.offset).offset, 0);
assert.equal(pathView(path.items, small, narrow, 1440, 'moment:m3', first.offset).offset, -276);

// A long story at 1920: the smallest slide by whole items, the first item drawn exactly at the margin.
const long = historyPath({
  creation: { at: iso(16, 6, 0), readyWorld: 'Terraces on the bay', picture: null },
  moments: Array.from({ length: 6 }, (_, index) => ({
    moment_id: `l${index}`, tick: 400 + index, at: iso(16, 7, index), session_id: null, kind: 'left', subjects: ['ari'],
    place: null, target: null, with: null, said: [], decider: { kind: 'routine', model: null }, scene: {}, picture: null, branches: [],
  })),
}, names, partsOf, clock, now);
const longPlaced = pathLayout(long.items, wide);
const newest = pathView(long.items, longPlaced, wide, 1920, 'moment:l5');
assert.deepEqual([newest.offset, newest.now, [...newest.drawn]], [-1260, 1800, ['moment:l2', 'moment:l3', 'moment:l4', 'moment:l5']]);
const back = pathView(long.items, longPlaced, wide, 1920, 'moment:l1', newest.offset);
assert.deepEqual([back.offset, back.now, back.to, back.from], [-840, null, 1920, 0]);
assert.equal(longPlaced.x.get('moment:l1') + back.offset, 120);
assert.equal(pathView(long.items, longPlaced, wide, 1920, 'moment:l5', back.offset).offset, -1260);
assert.equal(pathView(long.items, longPlaced, wide, 1920, 'moment:l0', back.offset).offset, 0);
// A routine's moment has no who line.
assert.equal(long.items[1].by, null);

// Moments not read yet (H17): the line breaks midway between the oldest moment held and what is drawn before it (a
// change's dot; a card's picture end); with nothing drawn before it, the line runs to the window's edge; nothing
// where the read has no more, or where the oldest moment is out of view.
assert.equal(earlierBreak(path.items, placed, opening, wide, true), (510 + 600) / 2);
assert.equal(earlierBreak(path.items, placed, opening, wide, false), null);
const longBack = pathView(long.items, longPlaced, wide, 1920, 'moment:l0', newest.offset);
assert.equal(earlierBreak(long.items, longPlaced, longBack, wide, true), Math.round((120 + wide.card + longPlaced.x.get('moment:l0')) / 2));
assert.equal(earlierBreak(long.items, longPlaced, newest, wide, true), null);
const alone = historyPath({ moments: [{ moment_id: 'a1', tick: 400, at: iso(16, 7, 0), session_id: null, kind: 'left', subjects: ['ari'],
  place: null, target: null, with: null, said: [], decider: { kind: 'routine', model: null }, scene: {}, picture: null, branches: [] }] }, names, partsOf, clock, now);
const alonePlaced = pathLayout(alone.items, wide);
assert.equal(earlierBreak(alone.items, alonePlaced, pathView(alone.items, alonePlaced, wide, 1920, 'moment:a1'), wide, true), 'edge');

// A run's bracket partly in view (H16): a line over the part in view, cut at the window's edge with no leg there; its
// words above its left end where that end is in view, else at the margin, and left out there where they would meet
// another run's words (16px clear). Two runs over six model-made moments, 420 apart from 540.
const twoRuns = historyPath({
  creation: { at: iso(16, 6, 0), readyWorld: 'Terraces on the bay', picture: null },
  runs: [{ session_id: 'ra', start_tick: 400, end_tick: 404, spent: '0.0010', closed: { reason: 'session_minutes', words: '' } },
    { session_id: 'rb', start_tick: 404, end_tick: 406, spent: '0.0020', closed: { reason: 'session_minutes', words: '' } }],
  moments: Array.from({ length: 6 }, (_, index) => ({
    moment_id: `r${index}`, tick: 400 + index, at: iso(16, 7, index), session_id: index < 4 ? 'ra' : 'rb', kind: 'left', subjects: ['teo'],
    place: null, target: null, with: null, said: [], decider: model('Qwen3 235B'), scene: {}, picture: null, branches: [],
  })),
}, names, partsOf, clock, now);
const runsPlaced = pathLayout(twoRuns.items, wide);
const bracketsOf = (view, widthOf = () => 500) => runBrackets(twoRuns.spans, twoRuns.items, runsPlaced, view, wide, 1920, widthOf);
// The newest end: r0 and r1 out of view to the left. The first run is cut at the window's left edge (1260 in the
// track's places), its words at the margin (120 on the page); the second is whole, its words over its first dot.
const runsNewest = pathView(twoRuns.items, runsPlaced, wide, 1920, 'moment:r5');
assert.equal(runsNewest.offset, -1260);
assert.deepEqual(bracketsOf(runsNewest), [
  { id: 'run:ra', from: 1260, to: 2100, legs: [false, true], words: 1380 },
  { id: 'run:rb', from: 2220, to: 2940, legs: [true, true], words: 2220 },
]);
assert.equal(bracketsOf(runsNewest)[0].words + runsNewest.offset, wide.margin);
// Words at the margin that would come within 16px of the next run's words are left out; the other run's stay.
assert.deepEqual(bracketsOf(runsNewest, (id) => (id === 'run:ra' ? 825 : 500)).map((one) => one.words), [null, 2220]);
assert.deepEqual(bracketsOf(runsNewest, (id) => (id === 'run:ra' ? 824 : 500)).map((one) => one.words), [1380, 2220]);
// Back at the start: the first run is cut at the window's right edge, its left leg and words at its first dot; the
// second run has no moment in view and draws nothing.
const runsStart = pathView(twoRuns.items, runsPlaced, wide, 1920, 'moment:r0', runsNewest.offset);
assert.deepEqual(bracketsOf(runsStart), [{ id: 'run:ra', from: 540, to: 1920, legs: [true, false], words: 540 }]);

// Nothing yet: the creation alone, and Now still at its place on the right.
const empty = historyPath({ creation: { at: iso(16, 9, 12), readyWorld: 'Terraces on the bay', picture: null } }, names, partsOf, clock, now);
assert.deepEqual(empty.items.map((item) => [item.words, item.quote]), [['Started from Terraces on the bay', null]]);
const emptyView = pathView(empty.items, pathLayout(empty.items, wide), wide, 1920, null);
assert.deepEqual([emptyView.offset, emptyView.now, emptyView.from, emptyView.to], [0, 1800, 120, 1800]);

// Several changes between two moments are one dot; the world's day changing is a mark; a run still on.
const busy = historyPath({
  edits: [
    { edit_id: 'e1', kind: 'move_thing', thing_id: 'bench:1', recorded_at: iso(16, 8, 30) },
    { edit_id: 'e2', kind: 'move_thing', thing_id: 'lantern:1', recorded_at: iso(16, 8, 41) },
  ],
  models: [{ choice_seq: 1, recorded_at: iso(16, 8, 35), subjects: ['teo'], decider: { kind: 'model' }, model: { name: 'Qwen3 235B' }, ended: false }],
  runs: [{ session_id: 's2', start_tick: 1430, end_tick: null, spent: '0.0011', ends_by: new Date(now + 112_000).toISOString(), closed: null }],
  moments: [
    { moment_id: 'n1', tick: 1430, at: iso(16, 8, 50), session_id: 's2', kind: 'picked_up', subjects: ['ari'], place: null, target: null, with: { thing: 'lantern:1' }, said: [], decider: model('Qwen3 235B'), picture: null, branches: [] },
    { moment_id: 'n2', tick: 1445, at: iso(16, 8, 52), session_id: 's2', kind: 'left', subjects: ['marco'], place: null, target: null, with: null, said: [], decider: { kind: 'routine', model: null }, picture: null, branches: [] },
  ],
  nowTick: 1446,
}, names, partsOf, clock, now);
assert.deepEqual(busy.items.map((item) => [item.kind, item.when ?? null, text(item.words)]), [
  ['change', '08:30 to 08:41', 'You made 3 changes'],
  ['moment', '23:50 · Day 1', 'Ari picked up the lantern'],
  ['day', null, 'Day 2'],
  ['moment', '00:05 · Day 2', 'Marco left'],
]);
assert.equal(busy.items[3].by, null);
// A grouped dot keeps every change it stands for, oldest first, each its own time and You sentence, for the list it
// opens (H15); its count is the list's length.
assert.deepEqual(busy.items[0].changes.map((row) => [row.when, text(row.words)]), [
  ['08:30', 'You moved the bench'],
  ['08:35', "You changed Teo's model to Qwen3 235B"],
  ['08:41', 'You moved the lantern'],
]);

// The opened list's window (H15): a list that fits never moves and offers no arrows; a longer one moves a row at a
// time, held where its last row ends at the foot, never past it and never before its first row.
const rowsOf = (count, tall = 50, gap = 20) => Array.from({ length: count }, (_, index) => [index * (tall + gap), index * (tall + gap) + tall]);
// Its height ends on a whole row (DESIGN, "H15 as built"): 300 has room for four rows of 50 with 20 between (260), never
// a fifth row's time alone.
assert.deepEqual(rowsWindow(rowsOf(3), 600, 0), { first: 0, scroll: 0, height: 190, earlier: false, later: false });
assert.deepEqual(rowsWindow(rowsOf(3), 600, 2), { first: 0, scroll: 0, height: 190, earlier: false, later: false });
assert.deepEqual(rowsWindow(rowsOf(10), 300, 0), { first: 0, scroll: 0, height: 260, earlier: false, later: true });
assert.deepEqual(rowsWindow(rowsOf(10), 300, 1), { first: 1, scroll: 70, height: 260, earlier: true, later: true });
// Rows 6 to 9 end at 680 from row 6's top 420: the last row stands at the foot from row 6, so row 6 is the furthest.
assert.deepEqual(rowsWindow(rowsOf(10), 300, 9), { first: 6, scroll: 420, height: 260, earlier: true, later: false });
assert.deepEqual(rowsWindow(rowsOf(10), 300, -3), { first: 0, scroll: 0, height: 260, earlier: false, later: true });
assert.deepEqual(rowsWindow(rowsOf(10, 50, 20), 329, 0).height, 260);
assert.deepEqual(rowsWindow(rowsOf(10, 50, 20), 330, 0).height, 330);
// Not yet laid out (no height): nothing moves, no height is set and no arrows are offered.
assert.deepEqual(rowsWindow(rowsOf(10), 0, 4), { first: 0, scroll: 0, height: null, earlier: false, later: false });
assert.deepEqual(busy.spans.map((span) => span.words), ["Ari's model is deciding · 23:50 to now · 1:52 left"]);

// Every moment kind's title (JOURNEY's catalog, the sheet's section 9): no pronoun for a character, never a topic.
const title = (kind, extra = {}) => momentWords({ kind, place: null, to: null, thing: null, firstLine: null, ...extra }, 'Teo', ['Ines']);
assert.deepEqual([
  title('met', { place: 'bench' }), title('met'), title('talked'), title('spoke'), title('spoke', { place: 'bench' }), title('spoke', { firstLine: 'Is it raining?' }),
  title('spoke_to_all', { place: 'bench' }), title('went', { to: 'market' }), momentWords({ kind: 'went', to: 'market' }, 'Ines', []),
  title('went', { to: 'bench', activity: 'rest' }), title('went', { activity: 'rest' }), title('went'),
  title('followed'), title('stopped_following'), title('picked_up', { thing: 'lantern' }), title('put_down', { thing: 'lantern' }),
  title('gave', { thing: 'lantern' }), title('took', { thing: 'lantern' }), title('left'),
], [
  'Teo met Ines at the bench', 'Teo met Ines', 'Teo talked with Ines', 'Teo spoke to Ines', 'Teo spoke to Ines at the bench', 'Teo asked Ines',
  'Teo spoke up at the bench', 'Teo and Ines went to the market', 'Ines went to the market',
  'Teo and Ines went to rest at the bench', 'Teo and Ines went to rest', 'Teo and Ines went on',
  'Teo followed Ines', 'Teo stopped following Ines', 'Teo picked up the lantern', 'Teo put down the lantern',
  'Teo gave Ines the lantern', 'Teo took the lantern from Ines', 'Teo left',
]);
// What another model would have done, with no full stop (the catalog's forms).
const would = (kind, extra = {}) => branchWords({ kind, to: null, thing: null, withName: null, line: null, ...extra }, 'Teo');
assert.deepEqual([
  would('went', { to: 'market' }), would('went', { to: 'bench', activity: 'rest' }), would('went'), would('stood'),
  would('spoke', { line: '…', withName: 'Ines' }), would('spoke', { withName: 'Ines' }), would('spoke_to_all'), would('talked', { withName: 'Ines' }),
  would('followed', { withName: 'Ines' }), would('stopped_following', { withName: 'Ines' }), would('picked_up', { thing: 'lantern' }),
  would('put_down', { thing: 'lantern' }), would('gave', { withName: 'Ines', thing: 'lantern' }), would('took', { withName: 'Ines', thing: 'lantern' }),
  would('left'), would('waited'), would('carried_on'),
], [
  'Teo would have gone to the market', 'Teo would have rested at the bench', 'Teo would have gone on', 'Teo would have stood a while',
  'Teo would have said “…” to Ines', 'Teo would have spoken to Ines', 'Teo would have spoken up', 'Teo would have talked with Ines',
  'Teo would have followed Ines', 'Teo would have stopped following Ines', 'Teo would have picked up the lantern',
  'Teo would have put down the lantern', 'Teo would have given Ines the lantern', 'Teo would have taken the lantern from Ines',
  'Teo would have left', 'Teo would have waited a minute', 'Teo would have carried on as before',
]);
assert.ok([would('went'), would('left'), would('talked', { withName: 'Ines' })].every((words) => !words.endsWith('.')));
assert.deepEqual([byParts({ kind: 'external' }), byParts({ kind: 'routine' }), byParts(null)], [[PATH_WORDS.outsideProgram], null, null]);
// What a person did at a choice of their day (R5e), in the past with no full stop; null for a kind with no words.
const did = (kind, extra = {}) => didWords({ kind, ...extra });
assert.deepEqual([
  did('went', { to: 'market' }), did('went', { to: 'bench', activity: 'rest' }), did('went'), did('went_to_spot'), did('stood'), did('waited'),
  did('talked', { withName: 'Ines' }), did('talked'), did('spoke', { withName: 'Ines' }), did('spoke_to_all'),
  did('followed', { withName: 'Ines' }), did('stopped_following', { withName: 'Ines' }), did('picked_up', { thing: 'lantern' }),
  did('put_down', { thing: 'lantern' }), did('gave', { withName: 'Ines', thing: 'lantern' }), did('took', { withName: 'Ines', thing: 'lantern' }),
  did('left'), did('carried_on'),
], [
  'Went to the market', 'Went to rest at the bench', 'Moved on', 'Went to the chosen spot', 'Stood a while', 'Waited',
  'Talked with Ines', 'Talked with someone', 'Spoke to Ines', 'Spoke up',
  'Followed Ines', 'Stopped following Ines', 'Picked up the lantern',
  'Put down the lantern', 'Gave Ines the lantern', 'Took the lantern from Ines',
  'Went away', 'Carried on as before',
]);
assert.deepEqual([did(null), did('point'), didWords()], [null, null, null]);

// The person's own changes, History's "You" form of each of build mode's sentence kinds (never a cut string).
const you = (edit, edits = [edit]) => youChangeWords(partsOf(edit, edits));
assert.deepEqual([
  you({ edit_id: 'a', kind: 'add_thing', thing_id: 'bench:1' }),
  you({ edit_id: 'b', kind: 'move_thing', thing_id: 'bench:1' }),
  you({ edit_id: 'c', kind: 'remove_thing', thing_id: 'bench:1' }),
  you({ edit_id: 'd', kind: 'suppress_element', element_id: 'part:pond' }),
  you({ edit_id: 'e', kind: 'transform_element', element_id: 'part:tea-house', storeys: { before: 2, after: 4 } }),
  you({ edit_id: 'f', kind: 'undo', undone_edit_id: 'b' }, [{ edit_id: 'b', kind: 'move_thing', thing_id: 'bench:1' }, { edit_id: 'f', kind: 'undo', undone_edit_id: 'b' }]),
  you({ edit_id: 'g', kind: 'undo', undone_edit_id: 'd' }, [{ edit_id: 'd', kind: 'suppress_element', element_id: 'part:pond' }, { edit_id: 'g', kind: 'undo', undone_edit_id: 'd' }]),
  you({ edit_id: 'h', kind: 'undo', undone_edit_id: 'g' }, [{ edit_id: 'd', kind: 'suppress_element', element_id: 'part:pond' }, { edit_id: 'g', kind: 'undo', undone_edit_id: 'd' }, { edit_id: 'h', kind: 'undo', undone_edit_id: 'g' }]),
], [
  'You placed the bench', 'You moved the bench', 'You took out the bench', 'You took out the pond', 'You raised the tea house to 4 storeys',
  'You put the bench back where it was', 'You brought back the pond', 'You took out the pond again',
]);
// A thing turned where it stood (ruling W12.7), as the version read states it on the move: turned, back, again.
const turnLog = [{ edit_id: 't', kind: 'move_thing', thing_id: 'bench:1', turned_in_place: true }, { edit_id: 'tu', kind: 'undo', undone_edit_id: 't' }, { edit_id: 'tr', kind: 'undo', undone_edit_id: 'tu' }];
assert.deepEqual(turnLog.map(edit => you(edit, turnLog)), ['You turned the bench', 'You turned the bench back', 'You turned the bench again']);
// changeParts reads every edit as changeWords does: an edit build mode words is never a change History cannot word.
const fixtures = [
  { edit_id: 'a', kind: 'add_thing', thing_id: 'bench:1' }, { edit_id: 'b', kind: 'move_thing', thing_id: 'bench:1' },
  { edit_id: 'c', kind: 'remove_thing', thing_id: 'bench:1' }, { edit_id: 'd', kind: 'suppress_element', element_id: 'part:pond' },
  { edit_id: 'e', kind: 'transform_element', element_id: 'part:tea-house', storeys: { before: null, after: 3 } },
  { edit_id: 'f', kind: 'transform_element', element_id: 'part:tea-house' }, { edit_id: 'g', kind: 'add_object' },
  { edit_id: 'h', kind: 'retint_object' }, { edit_id: 'i', kind: 'undo', undone_edit_id: 'e' }, { edit_id: 'j', kind: 'undo', undone_edit_id: 'c' },
  { edit_id: 'k', kind: 'undo', undone_edit_id: 'a' }, { edit_id: 'l', kind: 'undo', undone_edit_id: 'j' }, { edit_id: 'm', kind: 'undo', undone_edit_id: 'missing' },
  { edit_id: 'n', kind: 'move_thing', thing_id: 'bench:1', turned_in_place: true }, { edit_id: 'o', kind: 'undo', undone_edit_id: 'n' },
];
for (const edit of fixtures) {
  const said = changeWords(edit, fixtures, (id) => things[id] ?? null, (id) => parts[id] ?? null);
  const form = partsOf(edit, fixtures).form;
  assert.equal(form === 'changed_world', said === 'Changed the world', edit.edit_id);
  assert.equal(form === 'undid', said === 'Undid the last change', edit.edit_id);
  assert.equal(form === 'again', said.endsWith(' again'), edit.edit_id);
}
assert.deepEqual([youPersonalityWords('Teo', 'wrote'), youPersonalityWords('Teo', 'changed'), youPersonalityWords('Teo', 'cleared')], ["You wrote Teo's personality", "You changed Teo's personality", "You cleared Teo's personality"]);
assert.deepEqual([partsText(youModelParts("Teo's model", 'Qwen3 235B')), partsText(youModelParts("Teo's model", null))], ["You changed Teo's model to Qwen3 235B", "You changed Teo's model to routine"]);
// Run brackets: one character, three or more, and a world without a clock.
assert.equal(runSpanWords({ names: ['Teo'], from: '06:00', to: '07:15', spent: '0.0042' }), "Teo's model was deciding · 06:00 to 07:15 · spent $0.0042");
assert.equal(runSpanWords({ names: ['Teo', 'Ines', 'Marco'], from: '06:00', to: '07:15', spent: '0' }), "3 characters' models were deciding · 06:00 to 07:15");
assert.equal(runSpanWords({ names: ['Teo', 'Ines'], from: null, to: null, worldMinutes: 75, spent: '0.0042' }), "Teo's and Ines's models were deciding · 75 minutes of world time · spent $0.0042");

console.log('History checks passed: money and days, the GitHub line, the path from the moments read in r23\'s words and places, whole-item views, Now at its place, exchanges, same answers and branches, the "You" forms, a grouped dot\'s changes and their window, runs on and ended, a run\'s bracket partly in view.');
