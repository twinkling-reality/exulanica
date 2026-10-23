import assert from 'node:assert/strict';
import { NAMED_LEAST_PX, NAMES_MOST, OVER_HEAD, QUIET_KINDS, quietWords, STACK_GAP, TALK_HEARING, TALK_HOLD, createTalk, edgePlace, endedBy, exchangeOf, framingStep, holdMs, nameGroups, namedPeople, popLeft, popPlacement, sceneBy, shownWhile, stackPops, talkActs } from './talk-pops.mjs';

// T4: a pop holds 67 ms a character, at least 3.6 s and at most 9 s, and fades over 600 ms.
assert.deepEqual({ ...TALK_HOLD }, { perCharacterMs: 67, leastMs: 3600, mostMs: 9000, outMs: 600 });
assert.equal(holdMs('Morning.'), 3600);
assert.equal(holdMs('x'.repeat(53)), 3600);
assert.equal(holdMs('x'.repeat(100)), 6700);
assert.equal(holdMs('x'.repeat(135)), 9000);
assert.equal(holdMs('x'.repeat(400)), 9000);
assert.equal(STACK_GAP, 8);

// T1: every said line pops, whoever decided it; a choice pops only where a mind decided it and the
// world applied it, never a routine's, and a choice that said something pops once, as its line.
const events = [
  { subject_id: 'b', tick: 6, event_kind: 'said', document: { thing: { request_id: 'r2', line: 'Is there shade?', to: 'a', decider: 'person' } } },
  { subject_id: 'a', tick: 3, event_kind: 'said', document: { thing: { request_id: 'r1', line: 'Rest here.', to: null, decider: 'external' } } },
  { subject_id: 'a', tick: 3, event_kind: 'decision_applied', document: { request_id: 'r1', origin: 'external', disposition: 'applied', chose: 'say something to everyone near you' } },
  { subject_id: 'c', tick: 4, event_kind: 'decision_applied', document: { request_id: 'r3', origin: 'model', disposition: 'applied', chose: 'walk to the lower pools', model: { provider: 'p', model_id: 'm' } } },
  { subject_id: 'c', tick: 5, event_kind: 'decision_applied', document: { request_id: 'r4', origin: 'model', disposition: 'rejected', chose: 'wait here' } },
  { subject_id: 'd', tick: 5, event_kind: 'decision_applied', document: { request_id: 'r5', chose: 'rest', model: null } },
  { subject_id: 'e', tick: 5, event_kind: 'decision_applied', document: { request_id: 'r6', chose: 'rest', model: { provider: 'p', model_id: 'm' } } },
  { subject_id: 'f', tick: 5, event_kind: 'decision_applied', document: { request_id: 'r7', origin: 'routine', disposition: 'applied', chose: 'wander' } },
];
assert.deepEqual(talkActs(events), [
  { subjectId: 'a', words: '\u201cRest here.\u201d', said: true, to: null, by: { kind: 'external', model: null } },
  { subjectId: 'c', words: 'Walk to the lower pools', said: false, to: null },
  { subjectId: 'e', words: 'Rest', said: false, to: null },
  { subjectId: 'b', words: '\u201cIs there shade?\u201d', said: true, to: 'a', by: { kind: 'person', model: null } },
]);

// T14: a said line carries who chose it, and the scene's plate says it in History's who-line words (H19).
const modelLine = { subject_id: 'g', tick: 7, event_kind: 'said', document: { thing: { request_id: 'r8', line: 'Evening.', to: null, decider: 'model',
  model: { provider: 'nebius_token_factory', model_id: 'nvidia/nemotron-3-super-120b-a12b' } } } };
const [said] = talkActs([modelLine]);
assert.deepEqual(said.by, { kind: 'model', model: { provider: 'nebius_token_factory', model_id: 'nvidia/nemotron-3-super-120b-a12b' } });
const named = (model) => (model.model_id === 'nvidia/nemotron-3-super-120b-a12b' ? 'Nemotron 3 Super 120B' : null);
assert.equal(sceneBy(said.by, named), 'By Nemotron 3 Super 120B');
assert.equal(sceneBy(said.by), 'By nvidia/nemotron-3-super-120b-a12b', 'a model the page cannot name is said by its id');
assert.equal(sceneBy({ kind: 'person', model: null }), 'By a person playing');
assert.equal(sceneBy({ kind: 'external', model: null }), 'By an outside program');
assert.equal(sceneBy(null), null, 'a line no mind chose keeps no who line');
const [older] = talkActs([{ subject_id: 'h', tick: 8, event_kind: 'said', document: { thing: { request_id: 'r9', line: 'Hello.', to: null } } }]);
assert.equal(older.by, null, 'a line recorded before deciders were kept names nobody');

// T11: a choice that changes nothing to see (waiting a minute, carrying on) does not pop; the quiet words come
// from the decision-action catalogs' kinds, every version, a word with a placeholder left out.
assert.deepEqual([...QUIET_KINDS], ['wait', 'carry_on']);
const catalogs = [
  { entries: [{ kind: 'wait', words: 'wait here a minute' }, { kind: 'target', words: '{activity}, {metres} m away' }] },
  { entries: [{ kind: 'wait', words: 'Wait here a minute' }, { kind: 'carry_on', words: 'carry on with what you are doing' }, { kind: 'stand', words: 'stand a while' }] },
];
const quiet = quietWords(catalogs);
assert.deepEqual([...quiet].sort(), ['carry on with what you are doing', 'wait here a minute']);
const quietEvents = [
  { subject_id: 'a', tick: 1, event_kind: 'decision_applied', document: { request_id: 'q1', origin: 'model', disposition: 'applied', chose: 'carry on with what you are doing' } },
  { subject_id: 'b', tick: 1, event_kind: 'decision_applied', document: { request_id: 'q2', origin: 'model', disposition: 'applied', chose: 'wait here a minute' } },
  { subject_id: 'c', tick: 1, event_kind: 'decision_applied', document: { request_id: 'q3', origin: 'model', disposition: 'applied', chose: 'stand a while' } },
];
assert.deepEqual(talkActs(quietEvents, quiet).map(act => act.words), ['Stand a while']);
assert.equal(talkActs(quietEvents).length, 3, 'with no quiet words given, every mind\'s choice pops (T1)');

// T4: a reply keeps the line it answers up, dimmed, until the reply fades; a third line replaces its
// speaker's pop.
const talk = createTalk();
talk.add({ subjectId: 'knight', words: '\u201cMay I rest in your shade?\u201d', said: true, to: 'canopy' }, 0);
assert.deepEqual(talk.shown(100).map(pop => [pop.subjectId, pop.earlier]), [['knight', false]]);
talk.add({ subjectId: 'canopy', words: '\u201cRest beneath the canopy. The shore is quiet.\u201d', said: true, to: 'knight' }, 3000);
const answered = talk.shown(3100);
assert.deepEqual(answered.map(pop => [pop.subjectId, pop.earlier]), [['knight', true], ['canopy', false]]);
// The reply's hold is 46 characters (with its quotation marks) at 67 ms, under 3.6 s, so the line it
// answers stays until 3000 + 3600 (+ the fade).
assert.equal(talk.shown(3000 + 3600 - 1).length, 2, 'the earlier line stays while the reply shows');
assert.equal(talk.shown(3000 + 3600 + 1).find(pop => pop.subjectId === 'knight').leaving, true);
talk.add({ subjectId: 'knight', words: '\u201cThank you.\u201d', said: true, to: 'canopy' }, 4000);
assert.deepEqual(talk.shown(4100).map(pop => [pop.subjectId, pop.words, pop.earlier]), [
  ['canopy', '\u201cRest beneath the canopy. The shore is quiet.\u201d', true],
  ['knight', '\u201cThank you.\u201d', false],
]);
assert.deepEqual(talk.shown(4000 + 3600 + TALK_HOLD.outMs + 1).map(pop => pop.subjectId), [], 'both fade together');
// A pop gone is no reply's to keep.
talk.add({ subjectId: 'knight', words: '\u201cHello, all.\u201d', said: true, to: null }, 20000);
talk.add({ subjectId: 'canopy', words: 'Walk to the shore', said: false, to: null }, 20000);
talk.add({ subjectId: 'canopy', words: '\u201cHello.\u201d', said: true, to: 'nobody' }, 21000);
assert.equal(talk.shown(21100).find(pop => pop.subjectId === 'knight').earlier, false);
talk.clear();
assert.deepEqual(talk.shown(21100), []);
// A reply answers a line said to its speaker, or to everyone near, and never a chosen action (T4).
const third = createTalk();
third.add({ subjectId: 'ines', words: '\u201cMorning, Teo.\u201d', said: true, to: 'teo' }, 0);
third.add({ subjectId: 'bo', words: '\u201cHi.\u201d', said: true, to: 'ines' }, 500);
assert.deepEqual(third.shown(600).map(pop => [pop.subjectId, pop.earlier]), [['ines', false], ['bo', false]],
  'a line to Ines does not answer what Ines said to Teo');
third.add({ subjectId: 'teo', words: 'Walk to the shore', said: false, to: null }, 700);
third.add({ subjectId: 'ines', words: '\u201cWait for me.\u201d', said: true, to: 'teo' }, 800);
assert.equal(third.shown(900).find(pop => pop.subjectId === 'teo').earlier, false, 'a chosen action is never answered');
third.add({ subjectId: 'teo', words: '\u201cMe?\u201d', said: true, to: 'teo' }, 1000);
assert.equal(third.shown(1100).find(pop => pop.subjectId === 'ines').earlier, false, 'a line to oneself answers nothing');
const all = createTalk();
all.add({ subjectId: 'ines', words: '\u201cHello, all.\u201d', said: true, to: null }, 0);
all.add({ subjectId: 'teo', words: '\u201cHello, Ines.\u201d', said: true, to: 'ines' }, 500);
assert.equal(all.shown(600).find(pop => pop.subjectId === 'ines').earlier, true, 'a reply to a line to everyone near');
// T2: nothing pops while the world is paused, and a pause puts away what showed.
const paused = createTalk();
paused.add({ subjectId: 'ines', words: '\u201cHi.\u201d', said: true, to: null }, 0);
assert.equal(shownWhile(paused, 'playing', 100).length, 1);
assert.deepEqual(shownWhile(paused, 'paused', 200), []);
assert.deepEqual(shownWhile(paused, 'playing', 300), [], 'playing again brings nothing back');
// N28, T8: which lines are heard. On screen within hearing a line sits over its speaker; beyond it, its
// people are named instead, unless the person attends to the speaker, who is heard at any distance; off
// screen only an attended speaker's line shows, at the view's edge.
assert.deepEqual({ ...TALK_HEARING }, { metres: 20 });
assert.deepEqual({ ...OVER_HEAD }, { speech: 24, name: 16 });
assert.equal(popPlacement({ onScreen: true, metres: 6, attended: false }), 'over');
assert.equal(popPlacement({ onScreen: true, metres: 20, attended: false }), 'over', 'at the hearing distance');
assert.equal(popPlacement({ onScreen: true, metres: 20.5, attended: false }), 'far');
assert.equal(popPlacement({ onScreen: true, metres: 80, chosen: true, attended: true }), 'over', 'the chosen one: heard from afar');
assert.equal(popPlacement({ onScreen: true, metres: 80, attended: true }), 'far', 'a run\'s character on screen: named from afar');
assert.equal(popPlacement({ onScreen: true, metres: Infinity, attended: false }), 'far', 'no distance is not near');
assert.equal(popPlacement({ onScreen: false, metres: 3, attended: true }), 'edge');
assert.equal(popPlacement({ onScreen: false, metres: 3, attended: false }), 'none', 'off screen, not attended');
assert.equal(popPlacement({ onScreen: true, metres: 30, attended: false, hearing: { metres: 40 } }), 'over', 'hearing is data');
// T8: a line said off screen sits at the side nearest its speaker, its words the edge inset in, at the
// height it would take over them, kept in the safe area; a speaker behind the camera gets its middle.
const box = { width: 300, height: 60, viewWidth: 1920, inset: 32, top: 120, bottom: 920 };
assert.deepEqual(edgePlace({ ...box, right: true, overY: 400 }), { x: 1920 - 32 - 300, y: 400 });
assert.deepEqual(edgePlace({ ...box, right: false, overY: 400 }), { x: 32, y: 400 });
assert.deepEqual(edgePlace({ ...box, right: false, overY: 20 }), { x: 32, y: 120 }, 'never above the safe area');
assert.deepEqual(edgePlace({ ...box, right: false, overY: 2000 }), { x: 32, y: 920 - 60 }, 'never below it');
assert.deepEqual(edgePlace({ ...box, right: true, overY: null }), { x: 1588, y: 120 + (800 - 60) / 2 }, 'behind the camera');
// N28 section 5: who is named. The person chosen last first, then the nearest, at most three; never
// one with a line showing, the looked-at tag, or chosen now; one counted once, at its nearest.
assert.equal(NAMES_MOST, 3);
assert.equal(NAMED_LEAST_PX, 24);
const far = [
  { id: 'marco', metres: 40 }, { id: 'lia', metres: 25 }, { id: 'ana', metres: 60 }, { id: 'bo', metres: 30 },
  { id: 'lia', metres: 22 }, { id: 'teo', metres: 90, last: true }, { id: 'ines', metres: 21 }, { id: 'kai', metres: Infinity },
];
assert.deepEqual(namedPeople(far, new Set(['ines'])), ['teo', 'lia', 'bo']);
assert.deepEqual(namedPeople(far, new Set(['teo', 'ines'])), ['lia', 'bo', 'marco']);
assert.deepEqual(namedPeople(far, new Set(), 1), ['teo']);
assert.deepEqual(namedPeople([], new Set()), []);
// T10: names that would overlap become one label over them, left to right; a name apart stays alone, and a
// chain of overlaps is one label.
const label = (id, x, y = 400, width = 60) => ({ id, x, y, width, height: 20 });
assert.deepEqual(nameGroups([label('ines', 520), label('marco', 470), label('teo', 900)]), [['marco', 'ines'], ['teo']]);
assert.deepEqual(nameGroups([label('a', 100), label('b', 163), label('c', 226)]), [['a', 'b', 'c']], 'within the gap, chained');
assert.deepEqual(nameGroups([label('a', 100), label('b', 166)]), [['a'], ['b']], 'apart by more than the gap');
assert.deepEqual(nameGroups([label('a', 100, 400), label('b', 100, 430)]), [['a'], ['b']], 'one above the other, apart');
assert.deepEqual(nameGroups([]), []);

// T4: two pops that would overlap stack, the earlier above the newer, each over its own speaker.
const tops = stackPops([
  { serial: 1, x: 900, y: 300, width: 300, height: 60 },
  { serial: 2, x: 1000, y: 310, width: 300, height: 60 },
  { serial: 3, x: 100, y: 300, width: 200, height: 60 },
]);
assert.equal(tops.get(2), 310, 'the newer stays over its speaker');
assert.equal(tops.get(1), 310 - STACK_GAP - 60, 'the earlier rises above it');
assert.equal(tops.get(3), 300, 'one that meets nothing stays');
// A line beside someone else's name tag rises above the tag, as above an earlier line (live check, 16 Oct).
const tag = { x: 950, y: 430, width: 220, height: 80 };
const clear = stackPops([{ serial: 7, x: 500, y: 420, width: 480, height: 64 }, { serial: 8, x: 100, y: 420, width: 200, height: 64 }], STACK_GAP, [tag]);
assert.equal(clear.get(7), 430 - STACK_GAP - 64, 'it rises clear of the tag');
assert.equal(clear.get(8), 420, 'a line away from the tag stays');
assert.equal(stackPops([{ serial: 1, x: 0, y: 0, width: 10, height: 10 }]).get(1), 0, 'no fixed boxes by default');

// T5: the exchange a followed character is in.
const shown = [
  { subjectId: 'x', said: true, to: null },
  { subjectId: 'knight', said: true, to: 'canopy' },
  { subjectId: 'y', said: false, to: null },
];
const shownSerials = shown.map((pop, index) => ({ ...pop, serial: index + 1 }));
assert.deepEqual(exchangeOf(shownSerials, 'knight'), { other: 'canopy', serial: 2 });
assert.deepEqual(exchangeOf(shownSerials, 'canopy'), { other: 'knight', serial: 2 });
assert.equal(exchangeOf(shownSerials, 'x'), null, 'a line to everyone near is no exchange');
// T5: a framing starts on a seen person near enough and holds while near; the person's own movement
// ends it, and it stays ended until no exchange shows or a newer line comes (AUDIT B1).
const exchange = { other: 'canopy', serial: 2 };
assert.deepEqual(framingStep({ exchange, near: true, seen: true }), { frame: true, ended: null });
assert.deepEqual(framingStep({ exchange, near: true, seen: false }), { frame: false, ended: null }, 'not started unseen');
assert.deepEqual(framingStep({ exchange, near: true, seen: false, framed: true }), { frame: true, ended: null }, 'held while near');
assert.deepEqual(framingStep({ exchange, near: false, seen: true, framed: true }), { frame: false, ended: null }, 'let go when far');
const ended = endedBy(exchange);
assert.equal(ended, 2);
assert.deepEqual(framingStep({ exchange, ended, near: true, seen: true }), { frame: false, ended: 2 }, 'an ended exchange stays ended');
assert.deepEqual(framingStep({ exchange: { other: 'canopy', serial: 3 }, ended, near: true, seen: true }), { frame: true, ended: null }, 'a newer line frames again');
assert.deepEqual(framingStep({ exchange: null, ended, near: true, seen: true }), { frame: false, ended: null }, 'no exchange forgets the end');
assert.equal(endedBy(null), null);
// A line stays whole on screen (N28): centred over its speaker, but its words never nearer either edge
// than the edge inset.
assert.equal(popLeft(960, 240, 1920, 32), 840, 'centred over a speaker in the middle');
assert.equal(popLeft(1900, 240, 1920, 32), 1920 - 32 - 240, 'a speaker at the right edge keeps the line inside');
assert.equal(popLeft(10, 240, 1920, 32), 32, 'a speaker at the left edge keeps the line inside');
assert.equal(popLeft(500, 400, 450, 32), 32, 'a line wider than the room starts at the left inset');
console.log('Talk pops checks passed: what pops, holds, replies, the earlier line, stacking, hearing, names, lines off screen, the exchange followed and the edges.');
