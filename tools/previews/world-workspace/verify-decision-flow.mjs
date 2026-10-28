import assert from 'node:assert/strict';
import { ABOVE_KEYS, CAP, FLOW_LAYOUTS, HEAD, NARROW_BELOW, PIPELINE_BAR, PIPELINE_STAGES, TOLD, WRAP, bend, choiceEnd, choiceLines, decisionPipeline, executionPipeline, flowLayout, flowSize, headBottom, pipelineLayout, rowMost, run, titleLines, toldHeight } from './decision-flow.mjs';

const { wide, narrow } = FLOW_LAYOUTS;

// The sheet's numbers at 1920 by 1080 (R-DAY-DECISION section 2): the head at 120, 84 with its 56px title; what was
// told at 120, 300, 470 wide; the ring r 22 at x 740 with its dot r 8; the column at x 852; up to 12 choices drawn 44
// apart; the card at x 1380, 300 by 170 with History's 52px portraits; History's keys, 100 in and 40 up.
assert.deepEqual([wide.width, wide.height, wide.margin, wide.headTop, wide.title], [1920, 1080, 120, 84, 56]);
assert.deepEqual([wide.told.left, wide.told.top, wide.told.width], [120, 300, 470]);
assert.deepEqual([wide.ring.x, wide.ring.r, wide.ring.core, wide.column, wide.gap, wide.shown], [740, 22, 8, 852, 44, 12]);
assert.deepEqual([wide.card.x, wide.card.width, wide.card.height, wide.card.orb], [1380, 300, 170, 52]);
assert.deepEqual([wide.keys.right, wide.keys.bottom], [100, 40]);
// At 1440 by 900, History's rules: margins 80, the title 48, the choices 38 apart, the ring at x 600, the card at x
// 1100 at 260 by 148 (History's 46px portraits), keys 64 in and 32 up; the ring, its dot and the column's count stay.
assert.deepEqual([narrow.width, narrow.height, narrow.margin, narrow.headTop, narrow.title], [1440, 900, 80, 84, 48]);
assert.deepEqual([narrow.ring.x, narrow.ring.r, narrow.ring.core, narrow.gap, narrow.shown], [600, 22, 8, 38, 12]);
assert.deepEqual([narrow.card.x, narrow.card.width, narrow.card.height, narrow.card.orb], [1100, 260, 148, 46]);
assert.deepEqual([narrow.keys.right, narrow.keys.bottom], [64, 32]);
assert.equal(narrow.told.left, narrow.margin);
// Each size keeps r10's shapes: the bracket 22 past the told column and 120 before the ring's centre, the column 112
// past it, and the card's words inside the right margin.
for (const layout of [wide, narrow]) {
  assert.equal(layout.told.left + layout.told.width + layout.bracket.gap + layout.bracket.depth, layout.ring.x - 120);
  assert.equal(layout.column - layout.ring.x, 112);
  assert.ok(layout.card.x + layout.card.text <= layout.width - layout.margin + 10, 'the card stays inside the margin');
  assert.ok(layout.ring.y + (layout.shown - 1) * layout.gap / 2 + 24 < layout.height - layout.keys.bottom - 21, 'twelve rows clear the keys');
}
// Narrower than 1700 the page takes its 1440 sizes.
assert.equal(NARROW_BELOW, 1700);
assert.equal(flowSize(1920), wide);
assert.equal(flowSize(1700), wide);
assert.equal(flowSize(1699), narrow);
assert.equal(flowSize(1440), narrow);

// The curve helper draws r10's shapes.
assert.equal(bend(762, 610, 852, 482, 38, 40), 'M 762 610 C 800 610, 812 482, 852 482');
assert.equal(run(1132, 438, 1380, 438), 'M 1132 438 L 1380 438');
assert.equal(bend(0, 0.25, 10, 5, 2, 2), 'M 0 0.3 C 2 0.3, 8 5, 10 5');

// r10's own decision: six told sections, nine choices, the first taken (frames/r10-decision.html). Its column, its
// curves, its bracket and its card land where the frame draws them; the ring sits at the column's middle (614).
const told = [
  ['“A retired fisherman who walks the quay every morning and talks to anyone who will listen.”'],
  ['The lower pools, 06:52, morning.'],
  ['Rest: not needed yet (417 of 1000).', 'A meal: needed soon (612 of 1000).'],
  ['Ines, 3 m away, standing, can hear Teo.'],
  ['Ines, 1 minute ago: “Morning.”'],
  ['Followed Ines at 06:44.'],
];
const height = toldHeight(told, wide.told.width);
assert.equal(height, TOLD.label + TOLD.labelGap + 6 * (TOLD.name + TOLD.nameGap) + 5 * TOLD.sectionGap + 8 * TOLD.line);
const flow = flowLayout(wide, { count: 9, taken: 0, toldHeight: height, takenEnd: choiceEnd(wide, 'Say something to Ines', true) });
assert.equal(flow.bracket.path, 'M 612 320 L 620 320 L 620 732 L 612 732');
assert.equal(flow.bracket.into, 'M 620 526 L 668 526 C 694 526, 694 614, 718 614');
assert.deepEqual(flow.ring, { x: 740, y: 614, r: 22, core: 8 });
assert.deepEqual(flow.caption, { x: 740, y: 650 });
assert.deepEqual(flow.over, { x: 868, y: 392 });
assert.deepEqual(flow.rows.map(row => row.y), [438, 482, 526, 570, 614, 658, 702, 746, 790]);
assert.deepEqual(flow.rows.map(row => row.index), [0, 1, 2, 3, 4, 5, 6, 7, 8]);
assert.deepEqual(flow.rows.map(row => row.taken), [true, false, false, false, false, false, false, false, false]);
assert.equal(flow.rows[1].path, 'M 762 614 C 800 614, 812 482, 852 482');
assert.equal(flow.rows[8].path, 'M 762 614 C 800 614, 812 790, 852 790');
assert.deepEqual(flow.rows[0].end, { x: 852, y: 438, r: 4 });
assert.deepEqual(flow.rows[1].end, { x: 852, y: 482, r: 3.5 });
assert.equal(flow.lit, flow.rows[0].path);
assert.deepEqual(flow.card, { x: 1380, top: 336, width: 300, height: 170, text: 330, orb: 52 });
// The taken row's line runs level from its Chosen tag (r10: 1132) to the card.
const onward = /^M (\d+) 438 L 1380 438$/.exec(flow.onward);
assert.ok(onward && Math.abs(Number(onward[1]) - 1132) <= 4, flow.onward);
assert.deepEqual([flow.offset, flow.above, flow.below], [0, 0, 0]);

// Twelve are drawn; more scroll a whole row at a time, the window first showing the taken one.
const twelve = flowLayout(wide, { count: 12, taken: 11 });
assert.deepEqual([twelve.rows[0].y, twelve.rows[11].y], [372, 856]);
assert.equal(twelve.over.y, 326);
assert.deepEqual([twelve.above, twelve.below], [0, 0]);
const fourteen = flowLayout(wide, { count: 14, taken: 1 });
assert.equal(fourteen.rows.length, 12);
assert.deepEqual([fourteen.rows[0].index, fourteen.rows[11].index, fourteen.above, fourteen.below], [0, 11, 0, 2]);
assert.deepEqual(fourteen.rows.map(row => row.y), Array.from({ length: 12 }, (_, at) => 372 + 44 * at));
assert.deepEqual(fourteen.down, { x: 868, y: 878 });
const scrolled = flowLayout(wide, { count: 14, taken: 1, offset: 2 });
assert.deepEqual([scrolled.rows[0].index, scrolled.rows[11].index, scrolled.above, scrolled.below], [2, 13, 2, 0]);
// The taken one scrolled out of view: its curve points up to the column's edge, no line on to the card, and the
// card stays where the taken row first put it.
assert.equal(scrolled.lit, 'M 762 614 C 800 614, 812 350, 852 350');
assert.equal(scrolled.onward, null);
assert.equal(scrolled.rows.some(row => row.taken), false);
assert.equal(scrolled.card.top, fourteen.card.top);
assert.equal(flowLayout(wide, { count: 14, taken: 1, offset: 9 }).offset, 2);
assert.equal(flowLayout(wide, { count: 14, taken: 1, offset: -3 }).offset, 0);
// A taken one past the twelfth opens with it as the last row drawn, and points down when scrolled back to the top.
const late = flowLayout(wide, { count: 14, taken: 13 });
assert.deepEqual([late.home, late.offset, late.rows.at(-1).index, late.rows.at(-1).taken], [2, 2, 13, true]);
assert.equal(flowLayout(wide, { count: 14, taken: 13, offset: 0 }).lit, 'M 762 614 C 800 614, 812 878, 852 878');

// The card keeps clear of the head and the keys; the line bends into it when it cannot meet the row level.
assert.equal(twelve.card.top, 640);
assert.equal(twelve.onward.startsWith(`M ${choiceEnd(wide, '', true)} 856 C `), true);
assert.ok(twelve.onward.endsWith(`, 1380 ${640 + wide.card.height - 16}`), twelve.onward);
// The card's picture and words end above the keys.
assert.equal(640 + wide.card.block, 1080 - wide.keys.bottom - CAP - ABOVE_KEYS);
assert.equal(flowLayout(wide, { count: 12, taken: 0 }).card.top, 270);

// Nothing told: no bracket. No choices: the decision's own line runs on to the card. None taken: nothing lit.
assert.equal(flowLayout(wide, { count: 3, taken: 0, toldHeight: 0 }).bracket, null);
assert.equal(flowLayout(wide, { count: 3, taken: 0 }).bracket, null);
const none = flowLayout(wide, { count: 0 });
assert.deepEqual([none.rows.length, none.lit], [0, null]);
assert.equal(none.onward, 'M 762 614 L 1380 614');
const untaken = flowLayout(wide, { count: 4, taken: -1 });
assert.deepEqual([untaken.lit, untaken.onward, untaken.rows.some(row => row.taken)], [null, null, false]);
// A long told column scrolls inside its place, and the bracket spans only what shows.
assert.equal(flowLayout(wide, { count: 2, taken: 0, toldHeight: 5000 }).bracket.path, 'M 612 320 L 620 320 L 620 1018 L 612 1018');

// At 1440: the column 38 apart around the ring at x 600, the bracket and curves moved with it, the card at x 1100.
const small = flowLayout(narrow, { count: 9, taken: 0, toldHeight: toldHeight(told, narrow.told.width), takenEnd: choiceEnd(narrow, 'Say something to Ines', true) });
assert.deepEqual(small.rows.map(row => row.y), [360, 398, 436, 474, 512, 550, 588, 626, 664]);
assert.equal(small.rows[1].path, 'M 622 512 C 660 512, 672 398, 712 398');
assert.match(small.bracket.path, /^M 472 280 L 480 280 L 480 \d+(\.\d)? L 472 \d+(\.\d)?$/);
assert.match(small.bracket.into, /^M 480 \S+ L 528 \S+ C 554 \S+, 554 512, 578 512$/);
assert.deepEqual([small.card.x, small.card.top, small.card.width, small.card.height], [1100, 271, 260, 148]);
assert.deepEqual(flowLayout(narrow, { count: 12, taken: 0 }).rows.map(row => row.y).filter((_, at) => at === 0 || at === 11), [303, 721]);
assert.equal(small.over.x, 728);
// A choice's words stop 48px short of the card, at both sizes.
assert.equal(rowMost(wide), 464);
assert.equal(rowMost(narrow), 324);
assert.equal(choiceEnd(narrow, 'x'.repeat(200), true), 1100 - 48);

// The head ends above what the model was told, its title cut at two lines (the CSS clamp): at 1920 two lines still end
// 24px clear of 300; at 1440 two lines push what was told down to keep that gap. Either way the head ends above the
// label of a full column of twelve.
assert.equal(HEAD.most, 2);
assert.deepEqual([titleLines(wide, ''), titleLines(wide, 'Teo spoke to Ines'), titleLines(wide, 'x'.repeat(60)), titleLines(wide, 'x'.repeat(400))], [0, 1, 2, 2]);
assert.equal(headBottom(wide, { lines: 9 }), headBottom(wide, { lines: 2 }));
assert.equal(headBottom(wide), 84 + 14 + 14 + 56 * 1.05 + 16 + 21);
assert.equal(headBottom(narrow, { over: false, lines: 1, by: false }), 84 + 14 + 48 * 1.05);
for (const layout of [wide, narrow]) {
  const tallest = headBottom(layout, { lines: 2 });
  const placed = flowLayout(layout, { count: 12, taken: 0, headBottom: tallest });
  assert.ok(placed.told.top >= tallest + HEAD.gap, `${layout.width}: what was told starts below the head`);
  assert.ok(placed.over.y > tallest, `${layout.width}: the choices' label is below the head`);
  assert.ok(layout.margin + layout.headWidth <= layout.card.x - 40, `${layout.width}: the head stays clear of the card`);
}
assert.equal(flowLayout(wide, { count: 9, taken: 0, headBottom: headBottom(wide, { lines: 2 }) }).told.top, 300);
const pushed = flowLayout(narrow, { count: 9, taken: 0, toldHeight: 300, headBottom: headBottom(narrow, { lines: 2 }) });
assert.equal(pushed.told.top, 274);
assert.equal(pushed.record.top, 274);
assert.ok(pushed.bracket.path.startsWith('M 472 294 L 480 294 '), pushed.bracket.path);
assert.equal(flowLayout(narrow, { count: 9, taken: 0, headBottom: null }).told.top, 260);

// The window's height places what was told and the stored record: at each size's own height as r10 draws them, and in
// a shorter window both stop above its foot and the keys. A window too short for twelve rows raises the ring.
assert.deepEqual(flowLayout(wide, { count: 9, taken: 0 }).told, { left: 120, top: 300, width: 470, most: 720 });
assert.deepEqual(flowLayout(wide, { count: 9, taken: 0 }).record, { left: 120, top: 300, width: 1680, height: 695 });
assert.deepEqual(flowLayout(narrow, { count: 9, taken: 0 }).told, { left: 80, top: 260, width: 370, most: 592 });
assert.deepEqual(flowLayout(narrow, { count: 9, taken: 0 }).record, { left: 80, top: 260, width: 1280, height: 563 });
const short = flowLayout(wide, { count: 12, taken: 11, height: 960, toldHeight: 5000 });
assert.equal(short.told.top + short.told.most, 960 - wide.told.foot);
assert.equal(short.record.top + short.record.height, 960 - wide.keys.bottom - CAP - ABOVE_KEYS);
assert.ok(short.bracket.path.endsWith(`L 612 ${960 - wide.told.foot - 2}`), short.bracket.path);
assert.equal(short.ring.y, 614);
assert.equal(short.card.top + wide.card.block, 960 - wide.keys.bottom - CAP - ABOVE_KEYS);
const shorter = flowLayout(wide, { count: 12, taken: 0, height: 900 });
assert.equal(shorter.ring.y, 900 - wide.keys.bottom - CAP - ABOVE_KEYS - 12 - 11 * 22);
assert.ok(shorter.rows.at(-1).y + 12 + ABOVE_KEYS <= 900 - wide.keys.bottom - CAP, 'the lowest row clears the keys');
assert.equal(flowLayout(wide, { count: 9, taken: 0, height: 900 }).ring.y, 614);
assert.equal(flowLayout(wide, { count: 9, taken: 0, height: 300 }).record.height, 120);


// D3: a choice too long for the column wraps to a second line, and the column lays its rows by their own heights; a
// window holds the rows that fit in the height of the size's most one-line rows, the ring keeps its place while the
// column scrolls, and the window first shown holds the taken one.
const long = 'Say something to Ines Brook (a villager), 4 m away';
assert.deepEqual([choiceLines(narrow, long, false), choiceLines(narrow, 'Wait here a minute', false), choiceLines(wide, long, false)], [2, 1, 1]);
const tops = layout => layout.rows.map(row => row.y);
const gaps = ys => ys.slice(1).map((y, at) => y - ys[at]);
assert.deepEqual(gaps(tops(flowLayout(narrow, { count: 3, lines: [1, 2, 1] }))), [narrow.gap + WRAP / 2, narrow.gap + WRAP / 2]);
assert.deepEqual(tops(flowLayout(narrow, { count: 9, lines: Array(9).fill(1) })), tops(flowLayout(narrow, { count: 9 })), 'one-line rows read as before');
const twoLines = Array(12).fill(2);
const tall = flowLayout(narrow, { count: 12, lines: twoLines });
assert.deepEqual([tall.rows.length, tall.below], [7, 5]);
assert.ok(gaps(tops(tall)).every(gap => gap === narrow.gap + WRAP));
const scrolledDown = flowLayout(narrow, { count: 12, lines: twoLines, offset: 5 });
assert.deepEqual([scrolledDown.ring.y, scrolledDown.offset, scrolledDown.below], [tall.ring.y, 5, 0]);
const keysLine = narrow.height - narrow.keys.bottom - CAP - ABOVE_KEYS;
for (const window of [tall, scrolledDown]) assert.ok(window.rows.at(-1).y + 12 + WRAP / 2 <= keysLine, 'the lowest two-line row clears the keys');
const takenLate = flowLayout(narrow, { count: 12, taken: 10, lines: twoLines });
assert.ok(takenLate.rows.some(row => row.taken) && takenLate.lit !== null, 'the taken one is in the window first shown');
assert.equal(takenLate.down.y, takenLate.rows.at(-1).y + narrow.gap / 2 + WRAP / 2);

// In a short window where the keys hold the ring up, windows of mixed rows stand at different heights; the ring keeps
// the place of the tallest, so scrolling never moves it.
const mixed = [...Array(10).fill(1), 2, 2, 2, 2];
const shortFirst = flowLayout(narrow, { count: 14, lines: mixed, height: 700 });
const shortLast = flowLayout(narrow, { count: 14, lines: mixed, height: 700, offset: 99 });
assert.deepEqual([shortLast.ring.y, shortLast.below], [shortFirst.ring.y, 0]);
assert.ok(shortLast.offset > 0 && shortLast.rows.length !== shortFirst.rows.length);

// Pillar 1 ([X] System): 5-stage live execution pipeline and proportional timing/status breakdown.
assert.equal(executionPipeline, decisionPipeline);
assert.deepEqual(PIPELINE_STAGES.map(stage => stage.label), [
  '1. World Snapshot',
  '2. Context',
  '3. Model Inference',
  '4. Engine Check',
  '5. Outcome',
]);

{
  const detail = {
    status: 'completed',
    request: {
      request_id: 'req-412',
      base_tick: 412,
      state_sha256: '8f2a9c1b44d0e5128f2a9c1b44d0e5128f2a9c1b44d0e5128f2a9c1b44d0e512',
      document_sha256: 'a'.repeat(64),
      provider_config: { provider: 'nebius_token_factory', model_id: 'nvidia/Nemotron-3-Nano-30B' },
      context: {
        tick: 412,
        character: { name: 'Teo', about: 'A retired fisherman.' },
        here: 'by the lower pools',
        clock: { day: 0, minute_of_day: 412 },
        needs: [{ label: 'rest', milli: 417, seen_to_at_milli: 500 }],
        surroundings: {
          beings: [{ who: 'Ines', metres: 3, doing: 'standing', hears_you: true }],
          things: [{ what: 'bench', metres: 4 }, { what: 'lantern', metres: 6 }],
          more_beings: 1,
          more_things: 0,
        },
        heard: [{ from: 'Ines', line: 'Morning.', minutes_ago: 1 }],
        remembers: { beings: [{ who: 'Ines', met_minutes_ago: 3, here: true }], places: [], handed: [] },
        options: [
          { label: 'say something to Ines', kind: 'say_to' },
          { label: 'walk to the bench', kind: 'go' },
          { label: 'wait a minute', kind: 'wait' },
        ],
      },
    },
    decision: {
      request_id: 'req-412',
      status: 'accepted',
      reason: 'validated_choice',
      proposal: { label: 'say something to Ines', line: 'Morning, Ines. The boats are out early.' },
      provider: {
        provider: 'nebius_token_factory',
        served_model_id: 'nvidia/Nemotron-3-Nano-30B',
        latency_ms: 912,
        prompt_tokens: 410,
        completion_tokens: 38,
        cost_usd: '0.00030000',
        cost_known: true,
      },
    },
  };

  const pipe = executionPipeline({ detail, model: 'Nemotron 3 Nano 30B', said: 'Teo: “Morning, Ines. The boats are out early.”' });
  assert.equal(pipe.verdict, 'Applied');
  assert.equal(pipe.totalLatencyMs, 912);
  assert.equal(pipe.stages.length, 5);
  assert.equal(pipe.stages.reduce((sum, stage) => sum + stage.percent, 0), 100);
  assert.ok(pipe.stages.every(stage => stage.percent >= 10 && stage.status === 'ok'));

  // Stage 1: World Snapshot
  assert.equal(pipe.stages[0].label, '1. World Snapshot');
  assert.equal(pipe.stages[0].summary, 'Tick 412 · #8f2a9c1b');
  assert.equal(pipe.stages[0].detail, '2 beings, 2 objects');
  assert.deepEqual(pipe.stages[0].metrics, { tick: 412, digest: '8f2a9c1b', beings: 2, objects: 2 });

  // Stage 2: Context
  assert.equal(pipe.stages[1].label, '2. Context');
  assert.equal(pipe.stages[1].summary, '6 sections · 3 choices');
  assert.equal(pipe.stages[1].detail, 'Personality · Location & Time · Status · Nearby · Heard · Remembers');

  // Stage 3: Model Inference
  assert.equal(pipe.stages[2].label, '3. Model Inference');
  assert.equal(pipe.stages[2].summary, 'Nemotron 3 Nano 30B · 912 ms (0.9 s)');
  assert.equal(pipe.stages[2].detail, 'nebius token factory · 448 tok (410 in / 38 out) · $0.0003');
  assert.equal(pipe.stages[2].metrics.tokens, 448);

  // Stage 4: Engine Check
  assert.equal(pipe.stages[3].label, '4. Engine Check');
  assert.equal(pipe.stages[3].summary, 'Applied');
  assert.equal(pipe.stages[3].detail, 'Option #1 verified');

  // Stage 5: Outcome
  assert.equal(pipe.stages[4].label, '5. Outcome');
  assert.equal(pipe.stages[4].summary, 'Teo: “Morning, Ines. The boats are out early.”');
  assert.equal(pipe.stages[4].detail, 'Spoken line committed · Tick 412');

  // Proportional layout at 1920 and 1440
  const wideBox = pipelineLayout(wide, wide.height, pipe.stages);
  assert.deepEqual([wideBox.left, wideBox.width, wideBox.height], [120, 1680, PIPELINE_BAR.height]);
  assert.equal(wideBox.segments.reduce((sum, seg) => sum + seg.width, 0), 1680);
  const narrowBox = pipelineLayout(narrow, narrow.height, pipe.stages);
  assert.deepEqual([narrowBox.left, narrowBox.width, narrowBox.height], [80, 1280, PIPELINE_BAR.height]);
  assert.equal(narrowBox.segments.reduce((sum, seg) => sum + seg.width, 0), 1280);

  // Refusal / Routine Fallback and Not Applied (late/stale) states
  const fallbackPipe = executionPipeline({
    detail: {
      ...detail,
      decision: { request_id: 'req-412', status: 'unavailable', reason: 'spending_limit_reached', proposal: null, provider: { latency_ms: 2100, cost_usd: '0.0121', cost_known: true } },
    },
    model: 'Nemotron 3 Nano 30B',
    title: 'Walked to the quay',
    unanswered: { asks: 1, latencyMs: 2100, costUsd: '0.0121', costKnown: true, reason: 'spending_limit_reached' },
    why: 'Its answer was not one of the actions, and asking it again would have gone over the money left.',
  });
  assert.equal(fallbackPipe.verdict, 'Routine Fallback');
  assert.equal(fallbackPipe.stages[2].status, 'fallback');
  assert.equal(fallbackPipe.stages[3].status, 'fallback');
  assert.equal(fallbackPipe.stages[3].summary, 'Spending limit reached · Routine Fallback');
  assert.equal(fallbackPipe.stages[4].summary, 'Walked to the quay');
  assert.equal(fallbackPipe.stages[4].detail, 'Routine fallback committed to world state');

  const latePipe = executionPipeline({
    detail,
    model: 'Nemotron 3 Nano 30B',
    title: 'Walked to the quay',
    late: true,
  });
  assert.equal(latePipe.verdict, 'Not Applied');
  assert.equal(latePipe.stages[3].status, 'warn');
  assert.equal(latePipe.stages[3].summary, 'Not Applied · Routine Fallback');
  assert.equal(latePipe.stages[4].detail, 'Routine fallback committed to world state');

  // Local model inference increases/decreases stage 3 share proportionally with latency
  const fastLocal = executionPipeline({
    request: { base_tick: 10, provider_config: { provider: 'local', local: true, model_id: 'Qwen3-4B-Local' }, context: { tick: 10, options: [{ label: 'wait' }] } },
    decision: { status: 'accepted', reason: 'validated_choice', proposal: { label: 'wait' }, provider: { local: true, latency_ms: 45, prompt_tokens: 120, completion_tokens: 12, cost_usd: '0', cost_known: true } },
  });
  assert.equal(fastLocal.stages[2].summary, 'Qwen3-4B-Local · 45 ms (<0.1 s)');
  assert.equal(fastLocal.stages[2].detail, 'Local · 132 tok (120 in / 12 out) · $0');
  assert.ok(pipe.stages[2].percent > fastLocal.stages[2].percent, 'slower remote inference takes a larger proportional bar share than 45ms local inference');
}

console.log('decision flow: ok');
