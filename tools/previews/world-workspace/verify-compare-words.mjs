import assert from 'node:assert/strict';
import { COMPARE_WORDS, again, answerTag, askLine, asking, atMoment, cannotAskAgain, atMost, choseWords, compareMoments, laneMarks, nothingToAsk, resultOver, resultSub, resultTitle, sameCounts, spentAsking, spentOf, useFor, whatEachChose } from './compare-words.mjs';
import { called } from './character-words.mjs';
import { compareFirst, compareStep } from './compare-words.mjs';

const teo = called({ name: 'Teo' }), resident = called({ kind: 'resident' });
const NANO = 'Nemotron 3 Nano 30B', QWEN = 'Qwen3 235B Instruct';

// Frame 12a, as DESIGN wrote it (C1); the count and the bound are the server's offer.
assert.equal(askLine(teo, 12), "Ask Teo's last 12 decisions again");
assert.equal(askLine(resident, 3), "Ask the resident's last 3 decisions again");
assert.equal(askLine(teo, 1), "Ask Teo's last decision again");
assert.equal(askLine(teo, 1, true), 'Ask this decision again');
assert.equal(atMost('0.00740060'), 'At most $0.0074');
assert.equal(atMost('0.012'), 'At most $0.01');
assert.equal('askedOnce' in COMPARE_WORDS, false, 'no line restating that nothing happens');
// C2: while the asks run, the count and the spend so far.
assert.equal(asking(5, 24, 0.0008, '0.01'), 'Asking 5 of 24 · $0.0008 of $0.01');
assert.equal(nothingToAsk(teo), 'Teo has no decisions to ask again yet.');
assert.equal(nothingToAsk(resident), 'The resident has no decisions to ask again yet.');
assert.equal(cannotAskAgain(teo), "Teo's last decisions cannot be asked again here.");
assert.equal(cannotAskAgain(resident, true), 'This decision cannot be asked again here.');

// Frame 12b.
assert.equal(resultOver({ who: teo, count: 12, from: '06:41', to: '06:52', day: 1 }), 'Teo · 12 decisions, 06:41 to 06:52 · Day 1');
assert.equal(resultOver({ who: resident, count: 1, from: '06:41', to: '06:41', day: 1 }), 'Resident · 1 decision, 06:41 · Day 1');
assert.equal(resultOver({ who: teo, count: 5 }), 'Teo · 5 decisions');
assert.equal(resultTitle(teo, 12), "Teo's last 12 decisions, asked again");
assert.equal(resultTitle(teo, 1, true), "Teo's decision, asked again");
assert.equal(COMPARE_WORDS.sameMoments(teo), "The same moments, exactly as Teo's model was told them. Nothing in the world changed.");
assert.equal(spentAsking(0.003), 'Spent $0.003 asking again');
assert.equal(spentAsking('0.00300000'), 'Spent $0.003 asking again');
// r12: the small sentence carries what asking again spent.
assert.equal(resultSub(COMPARE_WORDS.sameMoments(teo), spentAsking(0.003)), "The same moments, exactly as Teo's model was told them. Nothing in the world changed. Spent $0.003 asking again.");
assert.equal(resultSub(COMPARE_WORDS.sameMoment(teo), ''), "The same moment, exactly as Teo's model was told it. Nothing in the world changed.");
assert.equal(resultSub('Asked.', 'Spent $0.003 asking again.'), 'Asked. Spent $0.003 asking again.');
assert.equal(atMoment('06:43', 2, 12), 'At 06:43 · 3 of 12');
assert.equal(atMoment(null, 0, 5), '1 of 5');
// One moment: its clock alone, or nothing (C3).
assert.equal(atMoment('06:43', 0, 1), 'At 06:43');
assert.equal(atMoment(null, 0, 1), '');
assert.equal(again(NANO), 'Nemotron 3 Nano 30B, again');
assert.equal(choseWords({ chose: 'say something to Ines', line: ' Calm water today, Ines. ', to: 'Ines' }), 'Said to Ines: “Calm water today, Ines.”');
assert.equal(choseWords({ chose: 'walk to the lower pools' }), 'Walk to the lower pools');
assert.equal(useFor(QWEN, teo), 'Use Qwen3 235B Instruct for Teo');

// The moments: only what the server could ask, each ask matched by the recorded option it chose.
const offered = [
  { requestId: 'a', baseTick: 41, chose: 'wait here a minute', line: null, askUsd: { chosen: '0.0007', again: '0.0004' } },
  { requestId: 'b', baseTick: 42, chose: 'say something to Ines', line: 'Calm water today, Ines.', askUsd: { chosen: '0.0007', again: '0.0004' } },
  { requestId: 'x', baseTick: 43, chose: 'rest', line: null, askUsd: null, refusal: 'decision_not_reproducible' },
  { requestId: 'c', baseTick: 44, chose: 'rest', line: null, askUsd: { chosen: '0.0007', again: null } },
];
const answers = new Map([
  ['a', { other: { chose: 'walk to the lower pools', line: null, costUsd: '0.00017' }, again: { chose: 'wait here a minute', line: null, costUsd: '0.0001' } }],
  ['b', { other: { chose: 'say something to Ines', line: 'Morning.', costUsd: '0.0002' }, again: { chose: 'say something to Ines', line: 'Morning, Ines.', costUsd: null } }],
  ['c', { other: { chose: 'rest', line: null, costUsd: '0.0001' } }],
]);
const moments = compareMoments(offered, answers);
assert.deepEqual(moments.map(moment => moment.requestId), ['a', 'b', 'c']);
assert.equal(answerTag({ recorded: true }), 'As recorded');
assert.equal(answerTag(moments[0].other), 'Another choice');
assert.equal(answerTag(moments[1].other), 'Same choice', 'the same option with other words is the same choice');
assert.equal(answerTag(moments[2].again), null, 'not asked: no tag');
assert.deepEqual(sameCounts(moments, 'other'), { asked: 3, same: 2 });
assert.deepEqual(sameCounts(moments, 'again'), { asked: 2, same: 2 });
assert.equal(Number(spentOf(moments).toFixed(5)), 0.00057);
assert.deepEqual(laneMarks(moments, 'recorded'), [{ said: false, differs: false, hollow: false }, { said: true, differs: false, hollow: false }, { said: false, differs: false, hollow: false }]);
assert.deepEqual(laneMarks(moments, 'other').map(mark => mark.differs), [true, false, false]);
assert.deepEqual(laneMarks(moments, 'again').map(mark => mark.hollow), [false, false, true]);

// What each chose: over the moments asked (C2), never which is better.
assert.deepEqual(whatEachChose({ recordedName: NANO, otherName: QWEN, other: { asked: 12, same: 9 }, again: { asked: 12, same: 10 }, count: 12 }), [
  'Qwen3 235B Instruct chose as Nemotron 3 Nano 30B did at 9 of 12 moments.',
  'Asked again, Nemotron 3 Nano 30B chose as before at 10 of 12: a small difference can be chance.',
]);
assert.deepEqual(whatEachChose({ recordedName: NANO, otherName: QWEN, other: { asked: 5, same: 4 }, again: { asked: 0, same: 0 }, count: 12 }), [
  'Qwen3 235B Instruct chose as Nemotron 3 Nano 30B did at 4 of 5 moments asked.',
]);
// All, none or some, never "0 of" or "1 of 1" (C3); one moment has no such lines.
const each = (other, rerun, count, againRefused = false) => whatEachChose({ recordedName: NANO, otherName: QWEN, other, again: rerun, count, againRefused });
assert.deepEqual(each({ asked: 12, same: 12 }, { asked: 12, same: 12 }, 12), [
  'Qwen3 235B Instruct chose as Nemotron 3 Nano 30B did at all 12 moments.',
  'Asked again, Nemotron 3 Nano 30B chose as before at all 12 moments.',
]);
assert.deepEqual(each({ asked: 12, same: 0 }, { asked: 12, same: 0 }, 12), [
  'Qwen3 235B Instruct chose differently from Nemotron 3 Nano 30B at all 12 moments.',
  'Asked again, Nemotron 3 Nano 30B chose differently at all 12 moments, so a difference here can be chance.',
]);
assert.deepEqual(each({ asked: 4, same: 4 }, { asked: 4, same: 3 }, 6), [
  'Qwen3 235B Instruct chose as Nemotron 3 Nano 30B did at all 4 moments asked.',
  'Asked again, Nemotron 3 Nano 30B chose as before at 3 of 4 moments asked: a small difference can be chance.',
]);
assert.deepEqual(each({ asked: 6, same: 2 }, { asked: 0, same: 0 }, 6, true), [
  'Qwen3 235B Instruct chose as Nemotron 3 Nano 30B did at 2 of 6 moments.',
  'Nemotron 3 Nano 30B could not be asked again here.',
]);
assert.deepEqual(each({ asked: 1, same: 0 }, { asked: 0, same: 0 }, 6), ['Qwen3 235B Instruct chose differently from Nemotron 3 Nano 30B at the one moment asked.']);
assert.deepEqual(each({ asked: 1, same: 1 }, { asked: 1, same: 1 }, 1), [], 'one moment: the tags say it');
for (const line of [each({ asked: 3, same: 0 }, { asked: 3, same: 3 }, 3), each({ asked: 2, same: 1 }, { asked: 1, same: 0 }, 2)].flat()) {
  assert.doesNotMatch(line, /\b0 of\b|\b1 of 1\b/, line);
}
for (const line of [...whatEachChose({ recordedName: NANO, otherName: QWEN, other: { asked: 12, same: 9 }, again: { asked: 12, same: 10 }, count: 12 }), ...Object.values(COMPARE_WORDS).filter(value => typeof value === 'string')]) {
  assert.doesNotMatch(line, /\b(better|worse|best|wins?)\b/i, line);
  assert.doesNotMatch(line, /\u2014|_/, line);
}
// A guest's model too dear to ask once stays in Compare's list, faint (`over`): the arrows pass over it, and Compare opens
// on the first a guest can afford, or the first where every one is faint (ROOT 11:29, with U2's threshold).
const listed = [{ name: 'a' }, { name: 'dear', over: 'Asking it once can cost up to $0.086, more than the $0.03 left for AI models here.' }, { name: 'c' }];
assert.equal(compareStep(listed, 0, 1), 2, 'down past the faint one');
assert.equal(compareStep(listed, 2, -1), 0, 'up past it too');
assert.equal(compareStep(listed, 2, 1), 2, 'nothing further: the focus stays');
assert.equal(compareStep([{ over: 'x' }, { name: 'b' }, { over: 'y' }], 1, 1), 1, 'only faint ones that way: it stays');
assert.equal(compareFirst(listed), 0);
assert.equal(compareFirst([{ over: 'x' }, { name: 'b' }]), 1);
assert.equal(compareFirst([{ over: 'x' }, { over: 'y' }]), 0, 'every one faint: the first');
assert.equal(compareFirst([]), 0);
console.log('Compare words checks passed: the frames’ lines, the moments asked, the counts, the band and r12’s small sentence.');
