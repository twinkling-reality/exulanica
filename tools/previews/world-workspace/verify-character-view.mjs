import assert from 'node:assert/strict';
import { called } from './character-words.mjs';
import { chosenCard, chosenDecision, didRows, doingLine, easePose, pageFraming, promptPlace, ringRadii, runQuestion, subjectWho, tagWords } from './character-view.mjs';
import { defaultRunLimits } from './run-words.mjs';

// Names: a being named only by its body is called by its kind; a thing by its own name or look.
const being = { scene: { type: 'being' }, label: 'Duck' };
assert.equal(subjectWho(being, { subject: { name: 'Teo', kind: { label: 'resident' } } }).title, 'Teo');
assert.equal(subjectWho(being, { subject: { name: 'duck', kind: { label: 'resident', body: { name: 'Duck' } } } }).title, 'Resident');
assert.equal(subjectWho(being, null).title, 'Character');
assert.equal(subjectWho({ scene: { type: 'object' }, label: 'Bench' }, null).title, 'Bench');
assert.equal(subjectWho({ scene: { type: 'object' }, label: 'Bench' }, { subject: { name: 'Lantern tower' } }).title, 'Lantern tower');

// The doing line is the catalog's sentence, without its full stop and with a capital.
assert.equal(doingLine('Resting at the bench.'), 'Resting at the bench');
assert.equal(doingLine('eating at home'), 'Eating at home');
assert.equal(doingLine('  '), null);

// The model set the current action only where the society says so, and only for an applied decision.
const latest = { disposition: 'applied', consumedTick: 69, requestId: 'r1', name: 'Nemotron 3 Nano 30B' };
const chose = { goal: { reason: 'chosen_by_their_model' } };
assert.deepEqual({ ...chosenDecision({ person: chose, latest, startMinute: 360, options: 7 }) }, { hhmm: '07:09', options: 7, requestId: 'r1', model: 'Nemotron 3 Nano 30B' });
assert.equal(chosenDecision({ person: { goal: { reason: 'routine_next' } }, latest, startMinute: 360 }), null);
assert.equal(chosenDecision({ person: chose, latest: { ...latest, disposition: 'rejected' }, startMinute: 360 }), null);
assert.equal(chosenDecision({ person: chose, latest: null, startMinute: 360 }), null);
assert.equal(chosenDecision({ person: chose, latest, startMinute: null }).hhmm, null);
assert.equal(chosenDecision({ person: { goal: null }, latest, living: true, startMinute: 0 }).hhmm, '01:09');

// The chosen card (frame 05; DESIGN's J1 and J2).
const teo = called({ name: 'Teo' });
const card = chosenCard({ who: teo, being: true, doing: 'Waiting by the bench', decision: { hhmm: '07:09', options: 7 }, model: 'Nemotron 3 Nano 30B' });
assert.equal(card.title, 'Teo');
assert.deepEqual(card.lines, ['Waiting by the bench', "Teo's model chose this at 07:09, from 7 choices."]);
assert.equal(card.chip, 'Nemotron 3 Nano 30B');
assert.deepEqual(card.prompts.map(item => `${item.keys.join('+')} ${item.word}`), ['Enter Details', 'R Run', 'V Follow']);
assert.deepEqual(chosenCard({ who: teo, being: true, model: 'Nano', running: true }).prompts.map(item => item.word), ['Details', 'Stop', 'Follow']);
assert.deepEqual(chosenCard({ who: teo, being: true, model: 'Nano', connected: false }).prompts.map(item => item.word), ['Details', 'Follow']);
assert.deepEqual(chosenCard({ who: teo, being: true, following: true }).prompts.map(item => item.word), ['Details', 'Stop following']);
assert.deepEqual([...chosenCard({ who: teo, being: true }).lines], ["Teo's routine."]);
assert.deepEqual([...chosenCard({ who: teo, being: true, reading: true }).lines], ["Reading Teo's record…"]);
const thing = chosenCard({ who: called({ name: 'Bench', being: false }), being: false, thingLine: 'Placed in this world' });
assert.deepEqual([thing.title, [...thing.lines], thing.chip, thing.prompts.length], ['Bench', ['Placed in this world'], null, 0]);
for (const made of [card, thing]) assert.ok(made.prompts.length <= 4, 'a card holds at most four prompts');

// The name tag: a thing shows its name only; a pop hides the doing line; the dot only with a model.
assert.deepEqual({ ...tagWords({ who: teo, being: true, doing: 'Waiting', model: 'Nano', live: true }) }, { name: 'Teo', doing: 'Waiting', model: 'Nano', live: true });
assert.equal(tagWords({ who: teo, being: true, doing: 'Waiting', popping: true }).doing, null);
assert.equal(tagWords({ who: teo, being: true, live: true }).live, false);
assert.deepEqual({ ...tagWords({ who: called({ name: 'Bench', being: false }), being: false, doing: 'x', model: 'y' }) }, { name: 'Bench', doing: null, model: null, live: false });

// The ring keeps a readable size; [E] Inspect sits right of the head, or left near the edge.
assert.deepEqual(ringRadii({ x: 960, y: 760 }, { x: 1064, y: 760 }, { x: 960, y: 735 }), { rx: 104, ry: 25 });
assert.deepEqual(ringRadii({ x: 0, y: 0 }, { x: 2, y: 0 }, { x: 0, y: 1 }), { rx: 18, ry: 5 });
assert.equal(promptPlace({ x: 960, y: 452 }, { width: 120, height: 44 }, { width: 1920, height: 1080 }).x, 1012);
assert.equal(promptPlace({ x: 1850, y: 452 }, { width: 120, height: 44 }, { width: 1920, height: 1080 }).x, 1850 - 52 - 120);
// The question before a run (frame 08), and its refusal with [P] Pause when the world plays.
const asked = runQuestion({ who: teo, model: 'Nemotron 3 Nano 30B', limits: defaultRunLimits(60_000, 1) });
assert.deepEqual([asked.label, asked.title, asked.lines[0], asked.big, asked.small, asked.orbWord], ['Teo', 'Run for 10 minutes', "Teo's model decides. Everyone else keeps their routine.", 'At most $0.05', 'It stops by itself, or when you press Stop.', 'Run']);
assert.deepEqual(asked.answers.map(item => `${item.keys[0]} ${item.word}`), ['Enter Run', 'Esc Back']);
const playing = runQuestion({ who: teo, model: 'Nano', limits: defaultRunLimits(60_000, 1), refusal: 'society_not_paused' });
assert.equal(playing.refusal, 'The world is playing. Pause it first, then run.');
assert.deepEqual(playing.answers.map(item => item.word), ['Run', 'Pause', 'Back']);

// What Teo did: newest first; a line said is one row; a goal a model chose is the choice's row.
const events = [
  { subject_id: 't', tick: 52, event_kind: 'said', document: { thing: { request_id: 'r2', line: 'Calm water today.', model: { provider: 'p', model_id: 'nano' } } } },
  { subject_id: 't', tick: 52, event_kind: 'decision_applied', document: { request_id: 'r2', chose: 'say it', model: { provider: 'p', model_id: 'nano' } } },
  { subject_id: 'x', tick: 50, event_kind: 'goal_selected', document: { reason: 'routine' } },
  { subject_id: 't', tick: 44, event_kind: 'goal_selected', document: { reason: 'chosen_by_their_model' } },
  { subject_id: 't', tick: 44, event_kind: 'decision_applied', document: { request_id: 'r1', chose: 'follow Ines', model: { provider: 'p', model_id: 'nano' } } },
  { subject_id: 't', tick: 0, event_kind: 'goal_selected', document: { reason: 'starting_at_home' } },
];
const did = didRows({ events, subjectId: 't', startMinute: 360, wordGoal: () => 'Leaving home', modelName: model => model.model_id === 'nano' ? 'Nemotron 3 Nano 30B' : null, options: id => ({ r1: 9, r2: 9 })[id] });
assert.deepEqual(did.map(row => [row.time, row.what, row.sub]), [
  ['06:52', 'Said \u201cCalm water today.\u201d', 'Nemotron 3 Nano 30B · 9 choices'],
  ['06:44', 'Follow Ines', 'Nemotron 3 Nano 30B · 9 choices'],
  ['06:00', 'Leaving home', 'Routine'],
]);
assert.equal(didRows({ events, subjectId: 't', wordGoal: () => null, modelName: () => null, limit: 1 }).length, 1);

// The page's camera: 2.6 m from the character at eye height, the character at 30 % of the width.
const pose = pageFraming({ ground: { x: 0, y: 0, z: 0 }, eye: { x: 0, z: 5 }, fovDeg: 60, aspect: 16 / 9 });
assert.ok(Math.abs(Math.hypot(pose.x, pose.z) - 2.6) < 1e-9 && Math.abs(pose.y - 1.62) < 1e-9 && pose.pitch < 0);
const fx = -Math.sin(pose.yaw), fz = -Math.cos(pose.yaw), rx = Math.cos(pose.yaw), rz = -Math.sin(pose.yaw);
const share = 0.5 + ((-pose.x) * rx + (-pose.z) * rz) / ((-pose.x) * fx + (-pose.z) * fz) / (2 * Math.tan(Math.atan(Math.tan(Math.PI / 6) * 16 / 9)));
assert.ok(Math.abs(share - 0.30) < 1e-9, String(share));
assert.equal(easePose({ x: 0, y: 0, z: 0, yaw: 3.1, pitch: 0 }, { x: 2, y: 2, z: 2, yaw: -3.1, pitch: 1 }, 1).yaw, 3.1 + (Math.atan2(Math.sin(-6.2), Math.cos(-6.2))));
assert.equal(easePose({ x: 0, y: 0, z: 0, yaw: 0, pitch: 0 }, { x: 2, y: 2, z: 2, yaw: 0, pitch: 1 }, 0.5).x, 1);

console.log('Character view checks passed: names, the doing line, which decision chose, the card, the tag, the ring, the prompt, the run question, the rows and the page camera.');
