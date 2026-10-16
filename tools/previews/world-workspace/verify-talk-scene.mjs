import assert from 'node:assert/strict';
import { SPEAKING_ABOVE, TALK_SCENE, createScene, toldMoments } from './talk-scene.mjs';

// T9: the scene's figures.
assert.deepEqual({ ...TALK_SCENE }, { afterMs: 2000, lines: 2 });
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
scene.add(said('ines', 'teo', '“Early enough for the market?”'));
scene.add(said('teo', null, '“Everyone, the boats.”'));
const shown = scene.shown(200, exchange);
assert.deepEqual([shown.before.words, shown.now.words], ['“Early enough for the market?”', '“Everyone, the boats.”'], 'the newest two; a line Teo says to everyone near is his');
// It stays 2 s after the conversation stops showing, then goes, and its lines with it.
assert.equal(scene.shown(1000, null).showing, true);
assert.equal(scene.shown(1000 + TALK_SCENE.afterMs - 1, null).showing, true);
assert.deepEqual(scene.shown(1000 + TALK_SCENE.afterMs, null), { showing: false, now: null, before: null });
assert.equal(scene.shown(5000, exchange).showing, false, 'its lines went with it');
scene.add(said('ines', 'teo', '“Again?”'));
assert.equal(scene.shown(5100, exchange).before, null, 'a new scene starts with no line before');
// A line while quiet keeps it up; following someone else, or no one, starts again.
scene.add(said('teo', 'ines', '“Yes.”'));
assert.equal(scene.shown(5200, null).showing, true);
scene.follow('ines');
assert.equal(scene.shown(5300, exchange).showing, false, 'a new followed character, a new scene');
scene.follow(null);
assert.equal(scene.shown(5400, exchange).showing, false);
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
