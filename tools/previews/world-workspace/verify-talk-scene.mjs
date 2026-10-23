import assert from 'node:assert/strict';
import { SPEAKING_ABOVE, TALK_SCENE, createScene, toldMoments } from './talk-scene.mjs';

// T9: the scene's figures.
assert.deepEqual({ ...TALK_SCENE }, { afterMs: 2000, lines: 2, holdMs: 2000, perCharMs: 70, replyLeastMs: 6000, replyBeyondMinuteMs: 1000 });
assert.equal(SPEAKING_ABOVE, 18);
const exchange = { other: 'ines', serial: 1 };
const said = (subjectId, to, words) => ({ subjectId, to, words, said: true });

// Nothing followed: no scene, whatever is said.
const idle = createScene();
idle.add(said('teo', 'ines', '“Morning.”'));
assert.deepEqual(idle.shown(0, exchange), { showing: false, now: null, before: null });

// Following Teo: the lines said by Teo or to Teo, the newest two; a line between others, a choice and
// a line to everyone near by someone else are not the scene's.
const scene = createScene();
scene.follow('teo');
assert.equal(scene.shown(0, null).showing, false, 'no line yet');
scene.add(said('teo', 'ines', '“Morning, Ines.”'));
scene.add(said('marco', 'lia', '“Not ours.”'));
scene.add({ subjectId: 'teo', to: null, words: 'Walk to the pier', said: false });
scene.add(said('lia', null, '“Hello, all.”'));
assert.deepEqual(scene.shown(100, exchange), { showing: true, now: { speaker: 'teo', to: 'ines', words: '“Morning, Ines.”' }, before: null });
// T14: who chose a line rides with it for the plate; a line whose act names nobody keeps no such field.
const byModel = { kind: 'model', model: { provider: 'p', model_id: 'm' } };
const chosen = createScene();
chosen.follow('teo');
chosen.add({ subjectId: 'teo', words: '“Evening.”', said: true, to: null, by: byModel });
assert.deepEqual(chosen.shown(100, exchange).now.by, byModel);
scene.add(said('ines', 'teo', '“Early enough for the market?”'));
scene.add(said('teo', null, '“Everyone, the boats.”'));
const shown = scene.shown(200, exchange);
assert.deepEqual([shown.before.words, shown.now.words], ['“Early enough for the market?”', '“Everyone, the boats.”'], 'the newest two; a line Teo says to everyone near is his');
// F7: after the conversation stops showing, it stays until its newest line, said to everyone near and
// so waiting for nobody, has been up 2 s plus 70 ms a character (from 200, when it arrived), then goes,
// and its lines with it.
const boats = 200 + TALK_SCENE.holdMs + TALK_SCENE.perCharMs * '“Everyone, the boats.”'.length;
assert.equal(scene.shown(1000, null).showing, true);
assert.equal(scene.shown(boats - 1, null).showing, true, 'held to be read past the 2 s after the exchange');
assert.deepEqual(scene.shown(boats, null), { showing: false, now: null, before: null });
assert.equal(scene.shown(9000, exchange).showing, false, 'its lines went with it');
scene.add(said('ines', 'teo', '“Again?”'));
assert.equal(scene.shown(9100, exchange).before, null, 'a new scene starts with no line before');
// A line while quiet keeps it up; following someone else, or no one, starts again.
scene.add(said('teo', 'ines', '“Yes.”'));
assert.equal(scene.shown(9200, null).showing, true);
scene.follow('ines');
assert.equal(scene.shown(9300, exchange).showing, false, 'a new followed character, a new scene');
scene.follow(null);
assert.equal(scene.shown(9400, exchange).showing, false);

// F7: a short line said to everyone holds 2 s plus its characters; a line said to someone waits for their
// answer, and the answer, kept, joins the scene.
const quiet = createScene();
quiet.follow('teo');
quiet.add(said('teo', null, '“Hi.”'));
assert.equal(quiet.shown(0, null).showing, true);
assert.equal(quiet.shown(TALK_SCENE.holdMs + TALK_SCENE.perCharMs * 5 - 1, null).showing, true);
assert.equal(quiet.shown(TALK_SCENE.holdMs + TALK_SCENE.perCharMs * 5, null).showing, false, 'a five-character line to everyone holds 2.35 s');
const question = '“Have you seen the lighthouse light up yet?”';
const waiting = createScene();
waiting.follow('ada');
waiting.add(said('ada', 'zeno', question));
assert.equal(waiting.shown(1000, null).showing, true);
const read = 1000 + TALK_SCENE.holdMs + TALK_SCENE.perCharMs * question.length;
assert.equal(waiting.shown(read + TALK_SCENE.replyLeastMs - 1, null).showing, true, 'it waits for Zeno');
waiting.add(said('zeno', 'ada', '“Not yet.”'));
const answered = waiting.shown(read + TALK_SCENE.replyLeastMs + 100, null);
assert.deepEqual([answered.showing, answered.before.words, answered.now.words], [true, question, '“Not yet.”'], 'the answer joins the scene');
const unanswered = createScene();
unanswered.follow('ada');
unanswered.add(said('ada', 'zeno', question));
unanswered.shown(1000, null);
assert.equal(unanswered.shown(read + TALK_SCENE.replyLeastMs, null).showing, false, 'no answer: it goes after the wait');
// The wait is a minute of the world's clock at the pace read, and 1 s more: minutes 8 s apart wait 9 s.
const paced = createScene();
for (const [at, minute] of [[0, 10], [500, 10], [1000, 11], [9000, 12]]) paced.shown(at, null, minute);
paced.follow('ada');
paced.add(said('ada', 'zeno', question));
paced.shown(9000, null, 12);
const readPaced = 9000 + TALK_SCENE.holdMs + TALK_SCENE.perCharMs * question.length;
assert.equal(paced.shown(readPaced + 8000 + TALK_SCENE.replyBeyondMinuteMs - 1, null, 12).showing, true, 'it waits a whole minute and a second');
assert.equal(paced.shown(readPaced + 8000 + TALK_SCENE.replyBeyondMinuteMs, null, 12).showing, false);
// A quick world still waits the least; a minute skipped (a jump) measures nothing.
const quick = createScene();
for (const [at, minute] of [[0, 1], [100, 2], [300, 3], [30000, 7]]) quick.shown(at, null, minute);
quick.follow('ada');
quick.add(said('ada', 'zeno', question));
quick.shown(30000, null, 7);
const readQuick = 30000 + TALK_SCENE.holdMs + TALK_SCENE.perCharMs * question.length;
assert.equal(quick.shown(readQuick + TALK_SCENE.replyLeastMs - 1, null, 7).showing, true);
assert.equal(quick.shown(readQuick + TALK_SCENE.replyLeastMs, null, 7).showing, false, 'the 29.7 s jump is no minute');
// An answer after the scene has gone opens it again while the one it was said to is still followed.
unanswered.add(said('zeno', 'ada', '“Not yet.”'));
const reopened = unanswered.shown(read + TALK_SCENE.replyLeastMs + 500, null);
assert.deepEqual([reopened.showing, reopened.now.words], [true, '“Not yet.”']);
// Following starts from the lines still showing by or to the followed one, oldest first.
const seeded = createScene();
seeded.follow('teo', [said('teo', 'ines', '“One.”'), said('bo', 'lia', '“No.”'), said('ines', 'teo', '“Two.”')]);
const first = seeded.shown(0, exchange);
assert.deepEqual([first.before.words, first.now.words], ['“One.”', '“Two.”']);
seeded.follow('teo', [said('teo', 'ines', '“Ignored.”')]);
assert.equal(seeded.shown(10, exchange).now.words, '“Two.”', 'following the same one again keeps its scene');

// T9's top line: the conversation's newest moment and the first going on from it, from R1's moments.
const m = (kind, tick, subjects) => ({ kind, tick, subjects });
const moments = [
  m('met', 1, ['ines', 'teo']), m('went', 2, ['bo']), m('spoke', 3, ['teo', 'ines']), m('spoke', 4, ['teo', 'lia']),
  m('went', 5, ['lia']), m('went', 6, ['ines', 'teo']), m('went', 7, ['teo']),
];
assert.deepEqual(toldMoments(moments, 'teo', 'ines').map(one => one.tick), [3, 6], 'the newest between them, then their going on');
assert.deepEqual(toldMoments(moments, 'teo', 'lia').map(one => one.tick), [4, 5], 'with another, the other one going on');
assert.deepEqual(toldMoments(moments, 'teo').map(one => one.tick), [4, 6], 'with no other known, the followed one\'s newest');
assert.deepEqual(toldMoments(moments.slice(0, 2), 'ines', 'teo').map(one => one.tick), [1], 'a meeting with nothing after it');
assert.deepEqual(toldMoments([m('went', 1, ['teo'])], 'teo', 'ines'), [], 'no conversation, no top line');
assert.deepEqual(toldMoments(null, 'teo'), []);
assert.deepEqual(toldMoments([m('spoke_to_all', 9, ['teo'])], 'teo', 'ines').map(one => one.tick), [9], 'a line to all names the followed one alone');
console.log('Talk scene checks passed: when the scene shows, its two lines, following again, and its top line.');
