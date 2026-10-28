import assert from 'node:assert/strict';
import { called } from './character-words.mjs';
import { askNames, chosenCard, chosenDecision, didRows, doingLine, easePose, modelAnswered, modelChoosableFor, outsideDecider, outsideOf, ownPeople, unlistedOutside, pageFraming, pairFraming, promptPlace, ringRadii, subjectWho, tagWords, timeRange } from './character-view.mjs';

// Names: a being named only by its body is called by its kind; a thing by its own name or look.
const being = { scene: { type: 'being' }, label: 'Duck' };
assert.equal(subjectWho(being, { subject: { name: 'Teo', kind: { label: 'resident' } } }).title, 'Teo');
assert.equal(subjectWho(being, { subject: { name: 'duck', kind: { label: 'resident', body: { name: 'Duck' } } } }).title, 'Resident');
assert.equal(subjectWho(being, null).title, 'Character');
assert.equal(subjectWho({ scene: { type: 'object' }, label: 'Bench' }, null).title, 'Bench');
assert.equal(subjectWho({ scene: { type: 'object' }, label: 'Bench' }, { subject: { name: 'Lantern tower' } }).title, 'Lantern tower');

// A town's own people are named by the society at once; a placed or written character waits for its offer.
const society = { state: { inhabitants: [
  { id: 'p1', synthetic: true, display_name: 'Ada Reed' }, { id: 'p2', synthetic: true, display_name: '  ' },
  { id: 'heron', synthetic: false, display_name: 'Heron' }, { id: 'p3', display_name: 'Teo' },
] } };
assert.deepEqual([...ownPeople(society)], ['p1']);
assert.deepEqual([...ownPeople(null)], []);
assert.deepEqual([...ownPeople({ state: {} })], []);

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
assert.deepEqual({ ...tagWords({ who: teo, being: true, doing: 'Waiting', model: 'Nano', live: true }) }, { name: 'Teo', doing: 'Waiting', model: 'Nano', live: true, quiet: false });
// An outside AI agent's chip in the quiet fill (AG1d 1).
assert.equal(tagWords({ who: teo, being: true, model: 'An outside AI agent', quiet: true }).quiet, true);
assert.equal(tagWords({ who: teo, being: true, doing: 'Waiting', popping: true }).doing, null);
assert.equal(tagWords({ who: teo, being: true, live: true }).live, false);
assert.deepEqual({ ...tagWords({ who: called({ name: 'Bench', being: false }), being: false, doing: 'x', model: 'y' }) }, { name: 'Bench', doing: null, model: null, live: false, quiet: false });

// The ring keeps a readable size; [E] Inspect sits right of the head, or left near the edge.
assert.deepEqual(ringRadii({ x: 960, y: 760 }, { x: 1064, y: 760 }, { x: 960, y: 735 }), { rx: 104, ry: 25 });
assert.deepEqual(ringRadii({ x: 0, y: 0 }, { x: 2, y: 0 }, { x: 0, y: 1 }), { rx: 18, ry: 5 });
assert.equal(promptPlace({ x: 960, y: 452 }, { width: 120, height: 44 }, { width: 1920, height: 1080 }).x, 1012);
assert.equal(promptPlace({ x: 1850, y: 452 }, { width: 120, height: 44 }, { width: 1920, height: 1080 }).x, 1850 - 52 - 120);

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
  ['06:52', 'Said: \u201cCalm water today.\u201d', 'Nemotron 3 Nano 30B · 9 choices'],
  ['06:44', 'Follow Ines', 'Nemotron 3 Nano 30B · 9 choices'],
  ['06:00', 'Leaving home', 'Routine'],
]);
assert.equal(didRows({ events, subjectId: 't', wordGoal: () => null, modelName: () => null, limit: 1 }).length, 1);
// U3: a model asked whose choice was not taken, with no usable answer or one that came after the world moved on, is a
// row of what the routine did, marked so; an answered row and a routine row are not marked.
const ultra = { provider: 'p', model_id: 'ultra' };
const untaken = didRows({ events: [
  { subject_id: 't', tick: 9, event_kind: 'decision_applied', document: { request_id: 'u9', chose: 'go to the bakery', disposition: 'stale', reason: 'decision_context_changed', model: ultra, origin: 'model' } },
  { subject_id: 't', tick: 8, event_kind: 'decision_applied', document: { request_id: 'u8', chose: null, disposition: 'unavailable', reason: 'spending_limit_reached', model: ultra, origin: 'model' } },
  { subject_id: 't', tick: 7, event_kind: 'decision_applied', document: { request_id: 'u7', chose: 'wait here', disposition: 'applied', model: ultra, origin: 'model' } },
  { subject_id: 't', tick: 6, event_kind: 'decision_applied', document: { request_id: 'u6', chose: null, disposition: 'unavailable', reason: 'spending_limit_reached', model: null, origin: 'model' } },
], subjectId: 't', wordGoal: () => 'Walking to the quay', modelName: () => 'Nemotron 3 Ultra 550B' });
assert.deepEqual(untaken.map(row => [row.what, row.chose, row.unanswered, row.requestId]), [
  ['Walking to the quay', null, 'late', 'u9'],
  ['Walking to the quay', null, 'none', 'u8'],
  ['Wait here', 'wait here', null, 'u7'],
  ['Walking to the quay', null, null, 'u6'],
]);
// An outside AI agent at the door (AG1d): its door entry, named an agent where the door says an AI runs it, a game's
// program otherwise; a subject the page's rows lack is read for again.
const read = { outside: [{ subjectId: 'v1', ai: true, connected: true, declared: { name: 'Scout', maker: 'Harbour Lab', mind: null } }, { subjectId: 'v2', ai: false, connected: true, declared: null }] };
assert.deepEqual([outsideDecider(read, 'v1'), outsideDecider(read, 'v2'), outsideDecider(read, 't'), outsideDecider(null, 'v1')], ['agent', 'external', null, null]);
assert.equal(outsideOf(read, 'v1').declared.name, 'Scout');
// The page offers no model choice for a being an outside program decides for (AG1c): the server refuses it
// decided_from_outside, so the day page offers no M while an AI agent or a visitor's own program decides.
assert.deepEqual([modelChoosableFor(read, 'v1'), modelChoosableFor(read, 'v2'), modelChoosableFor(read, 't'), modelChoosableFor(null, 'v1')], [false, false, true, true]);
assert.equal(unlistedOutside(read, [{ scene: { id: 'v1' } }]), true, 'v2 has no row yet');
assert.equal(unlistedOutside(read, [{ scene: { id: 'v1' } }, { scene: { id: 'v2' } }]), false);
assert.equal(unlistedOutside({ outside: [] }, []), false);
// Its rows: its lines and choices by it; a turn it did not answer at all, or whose answer could not be used, the
// routine's, marked so; a game's program keeps "An outside program".
const theirs = (events, agent) => didRows({ events, subjectId: 'v1', wordGoal: () => 'Walking to the quay', modelName: () => null, agent });
const outsideEvents = [
  { subject_id: 'v1', tick: 9, event_kind: 'decision_applied', document: { request_id: 'o9', chose: null, disposition: 'unavailable', reason: 'no_answer_in_time', origin: 'external', model: null, goal: { kind: 'stand' } } },
  { subject_id: 'v1', tick: 8, event_kind: 'decision_applied', document: { request_id: 'o8', chose: null, disposition: 'rejected', reason: 'answer_not_offered', origin: 'external', model: null, goal: { kind: 'stand' } } },
  { subject_id: 'v1', tick: 7, event_kind: 'decision_applied', document: { request_id: 'o7', chose: 'wait here', disposition: 'applied', origin: 'external', model: null } },
  { subject_id: 'v1', tick: 6, event_kind: 'said', document: { thing: { request_id: 'o6', line: 'Evening.', decider: 'external' } } },
];
assert.deepEqual(theirs(outsideEvents, true).map(row => [row.decider, row.unanswered ?? null, row.sub]), [
  ['agent', 'silent', 'An outside AI agent'], ['agent', 'none', 'An outside AI agent'], ['agent', null, 'An outside AI agent'], ['agent', null, 'An outside AI agent'],
]);
assert.deepEqual(theirs(outsideEvents, false).map(row => [row.decider, row.unanswered ?? null]), [['external', null], ['external', null], ['external', null], ['external', null]]);
assert.deepEqual(theirs(outsideEvents, true).map(modelAnswered), [false, false, false, false], "Compare asks again only a model's");
// Compare asks again only a decision a model answered: a choice made too late was answered; no usable answer was not.
assert.deepEqual(untaken.map(modelAnswered), [true, false, true, false]);
// R5h: a goal the routine set that repeats Teo's goal just before it (a stand after a stand) is no row of its own; the
// earlier goal's row spans to it where no row lies between, and keeps its own time where Teo's lines do. A routine goal
// that changes what he does stays a row, in a line's minute too; a repeat of his model's stand hides behind its row.
const stand = { kind: 'stand', target_id: null, reason: 'stopping_a_while' };
const aim = (tick, goal, reason = 'stopping_a_while') => ({ subject_id: 't', tick, event_kind: 'goal_selected', document: { reason, goal } });
const nemo = { provider: 'p', model_id: 'super' };
const spoke = (tick) => [
  { subject_id: 't', tick, event_kind: 'decision_applied', document: { request_id: `s${tick}`, chose: 'say something', model: nemo } },
  { subject_id: 't', tick, event_kind: 'said', document: { thing: { request_id: `s${tick}`, line: 'Morning.', heard_by: [], model: nemo } } },
];
// As the events read serves them: newest minute first, and in a minute as recorded (the goal, the choice, the line).
const served = (minutes) => minutes.reverse().flat();
const stood = served([
  [aim(1, stand)], [aim(2, stand)], [aim(3, stand), ...spoke(3)], [aim(5, stand), ...spoke(5)],
  [aim(8, stand, 'chosen_by_their_model'), { subject_id: 't', tick: 8, event_kind: 'decision_applied', document: { request_id: 'c8', chose: 'stand here a while', model: nemo } }],
  [aim(10, stand)], [aim(12, { kind: 'rest', target_id: 'bench', reason: 'resting' }), ...spoke(12)],
]);
const goalWords = (document) => ({ stand: 'Went to stand a while', rest: 'Went to rest', eat: 'Went to eat' })[document.goal?.kind ?? document.goal?.activity] ?? null;
assert.deepEqual(didRows({ events: stood, subjectId: 't', startMinute: 360, wordGoal: goalWords, modelName: () => 'Nemotron 3 Super 120B', options: () => 8 })
  .map(row => [row.time, row.what, row.sub]), [
  ['06:12', 'Said: \u201cMorning.\u201d', 'Nemotron 3 Super 120B · 8 choices'],
  ['06:12', 'Went to rest', 'Routine'],
  ['06:08', 'Stand here a while', 'Nemotron 3 Super 120B · 8 choices'],
  ['06:05', 'Said: \u201cMorning.\u201d', 'Nemotron 3 Super 120B · 8 choices'],
  ['06:03', 'Said: \u201cMorning.\u201d', 'Nemotron 3 Super 120B · 8 choices'],
  ['06:01 to 06:03', 'Went to stand a while', 'Routine'],
]);
// P2: a routine row made in a run in which a model chose for Teo says it lies between that model's choices; outside a
// run, or in a run with no choice of his, it stays "Routine". A run's minutes are those after the one it opened at, to
// the one it closed at, or on while it plays; the model is Teo's nearest choice in that run, the one before the row first.
const between = "Routine, between Nemotron 3 Super 120B's choices";
const inRuns = (runs, events = stood, modelName = () => 'Nemotron 3 Super 120B') => didRows({ events, subjectId: 't', startMinute: 360, wordGoal: goalWords, modelName, options: () => 8, runs })
  .filter(row => !row.model).map(row => [row.time, row.sub]);
assert.deepEqual(inRuns([{ from: 2, to: 12 }]), [['06:12', between], ['06:01 to 06:03', 'Routine']]);
assert.deepEqual(inRuns([{ from: 10, to: null }]), [['06:12', between], ['06:01 to 06:03', 'Routine']], 'a run still playing');
assert.deepEqual(inRuns([{ from: 0, to: 2 }]), [['06:12', 'Routine'], ['06:01 to 06:03', 'Routine']], 'a run with no choice of his');
assert.deepEqual(inRuns([{ from: 0, to: 12 }]), [['06:12', between], ['06:01 to 06:03', between]], 'before his first choice in it');
assert.deepEqual(inRuns([]), [['06:12', 'Routine'], ['06:01 to 06:03', 'Routine']]);
const nanoModel = { provider: 'p', model_id: 'nano' };
const picked = (tick, model) => ({ subject_id: 't', tick, event_kind: 'decision_applied', document: { request_id: `p${tick}`, chose: 'wait here', model } });
const named = model => (model.model_id === 'nano' ? 'Nemotron 3 Nano 30B' : 'Nemotron 3 Super 120B');
assert.deepEqual(inRuns([{ from: 0, to: null }], served([[picked(1, nanoModel)], [aim(2, { kind: 'rest', target_id: 'bench', reason: 'resting' })], [picked(3, nemo)]]), named),
  [['06:02', "Routine, between Nemotron 3 Nano 30B's choices"]], 'the choice before it names the model');
// A routine row while an outside AI agent decides (AG1c, DESIGN 12:10) lies between its choices, as a model's does: after a
// turn it answered and before its next turn; before its first answered turn, or after its last, it stays "Routine".
const agentTurn = (tick, chose) => ({ subject_id: 'v1', tick, event_kind: 'decision_applied', document: chose
  ? { request_id: `a${tick}`, chose, disposition: 'applied', origin: 'external', model: null }
  : { request_id: `a${tick}`, chose: null, disposition: 'unavailable', reason: 'no_answer_in_time', origin: 'external', model: null, goal: { kind: 'stand' } } });
const routineAim = (tick, kind) => ({ subject_id: 'v1', tick, event_kind: 'goal_selected', document: { reason: 'stopping_a_while', goal: { kind } } });
const agentDay = didRows({ events: [routineAim(12, 'eat'), agentTurn(11, 'wait here'), routineAim(10, 'rest'), agentTurn(9, null), agentTurn(8, 'wait here'), routineAim(5, 'eat')],
  subjectId: 'v1', wordGoal: goalWords, modelName: () => null, agent: true });
assert.deepEqual(agentDay.map(row => [row.what, row.sub]), [
  ['Went to eat', 'Routine'], ['Wait here', 'An outside AI agent'], ['Went to rest', "Routine, between the outside AI agent's choices"],
  ['Went to stand a while', 'An outside AI agent'], ['Wait here', 'An outside AI agent'], ['Went to eat', 'Routine'],
]);
// A decision with no usable answer is no choice (U3b, DESIGN 15:58): a run of only those leaves the routine "Routine";
// a choice made too late is still the model's choice.
const unused = (tick, model, disposition = 'unavailable') => ({ subject_id: 't', tick, event_kind: 'decision_applied',
  document: { request_id: `u${tick}`, chose: disposition === 'stale' ? 'wait here' : null, disposition, model, goal: { kind: 'stand', target_id: null } } });
const rest = aim(2, { kind: 'rest', target_id: 'bench', reason: 'resting' });
assert.deepEqual(didRows({ events: served([[unused(1, nanoModel)]]), subjectId: 't', startMinute: 360, wordGoal: goalWords, modelName: named }).map(row => row.unanswered), ['none'], 'the test decision is a row');
assert.deepEqual(inRuns([{ from: 0, to: null }], served([[unused(1, nanoModel)], [rest], [unused(3, nanoModel)]]), named),
  [['06:02', 'Routine']], 'no usable answer is no choice');
assert.deepEqual(inRuns([{ from: 0, to: null }], served([[unused(1, nanoModel, 'stale')], [rest]]), named),
  [['06:02', "Routine, between Nemotron 3 Nano 30B's choices"]], 'a choice made too late is a choice');
// A living society's goal names its spot: the same activity at another spot is somewhere new, and another activity at
// the same spot is something new.
const eat = (tick, spot, activity = 'eat') => aim(tick, { activity, destination_id: 'home', spot_id: spot, node_id: null, reason: 'most_pressing_need' }, 'most_pressing_need');
assert.deepEqual(didRows({ events: served([[eat(1, 'a')], [eat(2, 'a')], [eat(4, 'b')], [eat(6, 'b', 'rest')]]), subjectId: 't', startMinute: 360, wordGoal: goalWords, modelName: () => null })
  .map(row => [row.time, row.what]), [['06:06', 'Went to rest'], ['06:04', 'Went to eat'], ['06:01 to 06:02', 'Went to eat']]);
// Every row carries its time (R5e): where the society keeps no clock, the minute in J35's form.
assert.deepEqual(didRows({ events, subjectId: 't', wordGoal: () => 'Leaving home', modelName: () => null }).map(row => row.time), ['Minute 52', 'Minute 44', 'Minute 0']);
// The same choice made several times in a row, each with no moment of its own, is one row (R5e item 3): its time
// the span, its who line the count, its decision the newest (which [Enter] opens). A choice with a moment, or one the
// moments read cannot place (foldable false), keeps its own row; another choice or row between ends the run.
const nano = { provider: 'p', model_id: 'nano' };
const choice = (tick, id, chose, did) => ({ subject_id: 't', tick, event_kind: 'decision_applied', did, document: { request_id: id, chose, model: nano } });
const waited = { kind: 'waited', target: null, with: null };
const bench = { kind: 'went', target: { target_id: 'authored:v:bench:1:sit', activity: 'rest' }, with: null };
const day = [
  ...[33, 32, 31, 30, 29].map((tick) => choice(tick, `w${tick}`, 'wait here a minute', waited)),
  choice(28, 'b28', 'rest at the bench (4 m away)', bench), choice(27, 'b27', 'rest at the bench (3 m away)', bench),
  choice(26, 'w26', 'wait here a minute', waited), choice(12, 's12', 'talk with Ines', { kind: 'talked', target: null, with: 'i' }),
];
const rowsOf = (foldable, more = {}) => didRows({ events: day, subjectId: 't', wordGoal: () => null, modelName: () => 'Nemotron 3 Nano 30B', options: () => 8, foldable, ...more });
assert.deepEqual(rowsOf((row) => row.requestId !== 's12').map(row => [row.time, row.sub, row.requestId, row.decisions ?? 1]), [
  ['Minute 29 to minute 33', 'Nemotron 3 Nano 30B · 5 decisions', 'w33', 5],
  ['Minute 27 to minute 28', 'Nemotron 3 Nano 30B · 2 decisions', 'b28', 2],
  ['Minute 26', 'Nemotron 3 Nano 30B · 8 choices', 'w26', 1],
  ['Minute 12', 'Nemotron 3 Nano 30B · 8 choices', 's12', 1],
]);
// The offered words differ (4 m, 3 m away) but what was done is the same, so the two rests fold; nothing folds where
// no row may, and the limit counts the folded rows.
assert.equal(rowsOf(() => false).length, 7);
// Each row keeps who decided, so the page words its who line itself ("By a person playing", R5e part 2 as built).
assert.deepEqual(didRows({ events: [choice(5, 'p5', 'wait here a minute', waited)].map((event) => ({ ...event, document: { ...event.document, model: null, origin: 'person' } })), subjectId: 't', wordGoal: () => null, modelName: () => null })
  .map((row) => [row.model, row.decider]), [[null, 'person']]);
assert.equal(rowsOf(() => true, { limit: 2 }).map(row => row.requestId).join(), 'w33,b28');
// A wait whose decision made a moment stops the run there.
assert.deepEqual(rowsOf((row) => row.requestId !== 'w31').map(row => row.decisions ?? 1).slice(0, 3), [2, 1, 2]);
// Where the read says no kind (none joined, or an option the moment rules do not map), the offered words decide:
// the waits fold, the rests 4 m and 3 m away do not.
const unjoined = didRows({ events: day.map(({ did, ...event }) => event), subjectId: 't', wordGoal: () => null, modelName: () => 'N', foldable: () => true });
assert.deepEqual(unjoined.map((row) => row.decisions ?? 1), [5, 1, 1, 1, 1]);
const unmapped = didRows({ events: day.map((event) => ({ ...event, did: { kind: null, target: null, with: null } })), subjectId: 't', wordGoal: () => null, modelName: () => 'N', foldable: () => true });
assert.deepEqual(unmapped.map((row) => row.decisions ?? 1), [5, 1, 1, 1, 1]);
assert.deepEqual([timeRange('06:10', '06:33'), timeRange('Minute 4', 'Minute 27'), timeRange('06:10', '06:10')], ['06:10 to 06:33', 'Minute 4 to minute 27', '06:10']);
// T6: a line said to Teo, or to everyone near while Teo heard it, is a heard row with no sub-line and
// no decision; a line overheard, said to someone else, or not heard at all, is none; Teo's own line
// names whom it was said to.
const names = { i: called({ name: 'Ines' }), r: called({ kind: 'resident' }) };
const talked = [
  { subject_id: 'i', tick: 60, event_kind: 'said', document: { thing: { request_id: 'q1', line: 'Morning, Teo.', to: 't', heard_by: ['t', 'r'] } } },
  { subject_id: 'r', tick: 59, event_kind: 'said', document: { thing: { request_id: 'q2', line: 'Calm water.', to: null, heard_by: ['t'] } } },
  { subject_id: 'r', tick: 58, event_kind: 'said', document: { thing: { request_id: 'q3', line: 'Hello, Ines.', to: 'i', heard_by: ['t', 'i'] } } },
  { subject_id: 'i', tick: 57, event_kind: 'said', document: { thing: { request_id: 'q4', line: 'Far off.', to: null, heard_by: ['r'] } } },
  { subject_id: 't', tick: 56, event_kind: 'said', document: { thing: { request_id: 'q5', line: 'Hello, Ines.', to: 'i', heard_by: ['i'] } } },
];
const heard = didRows({ events: talked, subjectId: 't', startMinute: 360, wordGoal: () => null, modelName: () => null, who: id => names[id] });
assert.deepEqual(heard.map(row => [row.time, row.what, row.sub, row.requestId, row.heard === true]), [
  ['07:00', 'Heard Ines: \u201cMorning, Teo.\u201d', '', null, true],
  ['06:59', 'Heard the resident: \u201cCalm water.\u201d', '', null, true],
  ['06:56', 'Said to Ines: \u201cHello, Ines.\u201d', 'Routine', 'q5', false],
]);

// The page's camera: 2.6 m from the character at eye height, the character at 30 % of the width.
const pose = pageFraming({ ground: { x: 0, y: 0, z: 0 }, eye: { x: 0, z: 5 }, fovDeg: 60, aspect: 16 / 9 });
assert.ok(Math.abs(Math.hypot(pose.x, pose.z) - 2.6) < 1e-9 && Math.abs(pose.y - 1.62) < 1e-9 && pose.pitch < 0);
const fx = -Math.sin(pose.yaw), fz = -Math.cos(pose.yaw), rx = Math.cos(pose.yaw), rz = -Math.sin(pose.yaw);
const share = 0.5 + ((-pose.x) * rx + (-pose.z) * rz) / ((-pose.x) * fx + (-pose.z) * fz) / (2 * Math.tan(Math.atan(Math.tan(Math.PI / 6) * 16 / 9)));
assert.ok(Math.abs(share - 0.30) < 1e-9, String(share));
assert.equal(easePose({ x: 0, y: 0, z: 0, yaw: 3.1, pitch: 0 }, { x: 2, y: 2, z: 2, yaw: -3.1, pitch: 1 }, 1).yaw, 3.1 + (Math.atan2(Math.sin(-6.2), Math.cos(-6.2))));
assert.equal(easePose({ x: 0, y: 0, z: 0, yaw: 0, pitch: 0 }, { x: 2, y: 2, z: 2, yaw: 0, pitch: 1 }, 0.5).x, 1);

// T5: following an exchange, the camera faces the middle of the two at its own height and pitch,
// far enough back that both heads sit within the safe share of the half width, never nearer than asked.
{
  const from = { x: 0, y: 1.7, z: 10, yaw: 0, pitch: -0.1 }, a = { x: -4, y: 1.7, z: 0 }, b = { x: 4, y: 1.7, z: 0 };
  const framed = pairFraming({ from, a, b, fovDeg: 60, aspect: 16 / 9, safe: 0.5 });
  assert.ok(Math.abs(framed.yaw) < 1e-9 && framed.y === 1.7 && framed.pitch === -0.1);
  const halfWidth = Math.atan(Math.tan(Math.PI / 6) * 16 / 9);
  const share = 4 / framed.z / Math.tan(halfWidth);
  assert.ok(Math.abs(share - 0.5) < 1e-9, `each head at half the half width: ${share}`);
  assert.equal(pairFraming({ from, a, b, fovDeg: 60, aspect: 16 / 9, safe: 0.5, least: 30 }).z, 30, 'never nearer than following stands');
  const side = pairFraming({ from: { x: 10, y: 1.7, z: 0, yaw: 0, pitch: 0 }, a: { x: 0, y: 1.7, z: -1 }, b: { x: 0, y: 1.7, z: 1 }, fovDeg: 60, aspect: 16 / 9, safe: 0.5, least: 10 });
  assert.ok(Math.abs(-Math.sin(side.yaw) - -1) < 1e-9 && side.x === 10, 'turned to face the middle of the two');
  // One 7 m beyond the other on the line of sight: the nearer stays `least` in front of the camera (AUDIT S1).
  const behind = pairFraming({ from: { x: 0, y: 1.7, z: 3, yaw: 0, pitch: 0 }, a: { x: 0, y: 1.7, z: 0 }, b: { x: 0, y: 1.7, z: -7 }, fovDeg: 60, aspect: 16 / 9, safe: 0.4, least: 3 });
  assert.ok(Math.abs(behind.z - 3) < 1e-9, `the nearer person stays 3 m in front: camera at z ${behind.z}`);
}
// T7: a character a person plays: the chip says so, and the card's line where the person chose it.
{
  const played = chosenCard({ who: teo, being: true, doing: 'Resting', decider: 'person', deciderChose: true });
  assert.equal(played.chip, 'A person playing');
  assert.deepEqual(played.lines, ['Resting', 'A person chose this.']);
  assert.equal(chosenCard({ who: teo, being: true, decider: 'external', deciderChose: false }).lines.at(-1), "Teo's routine.");
  assert.equal(chosenCard({ who: teo, being: true, decider: 'external' }).chip, 'An outside program');
  assert.ok(!chosenCard({ who: teo, being: true, decider: 'person', connected: true }).prompts.some(item => item.action === 'run'), 'no Run without a model');
  const rows = didRows({ events: [
    { subject_id: 't', tick: 3, event_kind: 'said', document: { thing: { request_id: 'p1', line: 'Hello.', to: null, decider: 'person' } } },
    { subject_id: 't', tick: 2, event_kind: 'decision_applied', document: { request_id: 'p2', chose: 'rest', origin: 'external' } },
  ], subjectId: 't', wordGoal: () => null, modelName: () => null });
  assert.deepEqual(rows.map(row => row.sub), ['A person playing', 'An outside program']);
}
// D2: an Ask answer's beings are drawn as the page names them inside a sentence, a made creature by its own name and
// the one asked about included; a society read for another version lends neither names nor places.
const pageNames = { duck: 'the round duck', ari: 'Ari Ash', teo: 'Teo' };
const societyRead = { versionId: 'v1', people: new Map([['duck', 'Winged two legged creature 2'], ['ari', 'Ari Ash']]), spots: new Map([['bench', 'Bench 2']]) };
const drawnBy = askNames({ known: societyRead, versionId: 'v1', subjectId: 'teo', nameOf: id => pageNames[id] });
assert.deepEqual([...drawnBy.people], [['duck', 'the round duck'], ['ari', 'Ari Ash'], ['teo', 'Teo']]);
assert.equal(drawnBy.spots.get('bench'), 'Bench 2');
const elsewhere = askNames({ known: societyRead, versionId: 'v2', subjectId: 'teo', nameOf: id => pageNames[id] });
assert.deepEqual([[...elsewhere.people], elsewhere.spots.size], [[['teo', 'Teo']], 0]);
assert.deepEqual([...askNames({ known: null, versionId: 'v1', subjectId: 'teo', nameOf: () => null }).people], []);
console.log('Character view checks passed: names, the doing line, which decision chose, the card, the tag, the ring, the prompt, the run question, the rows and the page camera.');
