import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { GROUP_LAYOUT, SAID_READ, choosableModels, offersModels, deciderOf, freeHere, groupContent, groupHeld, groupPlace, keepLastSaid, lastSaid, overRows, questionGroup, readLastSaid } from './character-group.mjs';
import { CHARACTER_WORDS, GROUP_WORDS, called, decidesPrint, modelsDecide, quoted, runSpentWords, saidUnder } from './character-words.mjs';
import { dayWord } from './talk-words.mjs';

// A chosen character's group (DESIGN's J30, the r05 picture): what it says and where it stands.
const teo = called({ name: 'Teo' }), marco = called({ name: 'Marco' }), resident = called({ name: null, kind: 'Resident' });

// The words, as J30 has them, for a named person and for one called by their kind.
assert.equal(dayWord(teo), "Teo's day", 'the talking scene\'s own word (talk-words.mjs), one word for both');
assert.equal(GROUP_WORDS.decide(teo), "Let Teo's model decide");
assert.equal(GROUP_WORDS.stop(teo), "Stop Teo's model");
assert.equal(GROUP_WORDS.choose(teo), "Choose Teo's AI model");
assert.equal(GROUP_WORDS.follow(teo), 'Follow Teo');
assert.equal(dayWord(resident), "The resident's day");
assert.equal(GROUP_WORDS.follow(resident), 'Follow the resident');
assert.equal(decidesPrint(teo, { decider: 'model', model: 'Nemotron 3 Nano 30B' }), 'Nemotron 3 Nano 30B decides for Teo');
assert.equal(decidesPrint(teo, { decider: 'model', model: 'Nemotron 3 Nano 30B', left: '1:52' }), "Teo's model is deciding · 1:52 left");
// What their model has spent in the run (D9): from its known receipts, "at least" while a cost is not known, nothing before.
assert.equal(decidesPrint(teo, { decider: 'model', model: 'Nemotron 3 Nano 30B', left: '1:52', spent: '$0.0003 spent' }), "Teo's model is deciding · 1:52 left · $0.0003 spent");
assert.equal(runSpentWords({ knownCostUsd: '0.00030000', costsUnknown: 0 }), '$0.0003 spent');
assert.equal(runSpentWords({ knownCostUsd: '0.00030000', costsUnknown: 1 }), 'at least $0.0003 spent');
assert.equal(runSpentWords({ knownCostUsd: '0.00002000', costsUnknown: 0 }), 'less than $0.0001 spent');
assert.equal(runSpentWords({ knownCostUsd: '0.00000000', costsUnknown: 1 }), null, 'no estimate before a cost is known');
assert.equal(runSpentWords(null), null);
assert.equal(runSpentWords({ knownCostUsd: '0.00030000', costsUnknown: 0 }, true), 'at least $0.0003 spent', 'a read that did not reach every receipt never reads low unsaid');
assert.equal(decidesPrint(teo, { decider: 'routine' }), 'Teo follows a routine');
assert.equal(decidesPrint(resident, { decider: 'routine' }), 'The resident follows a routine');
assert.equal(decidesPrint(teo, { decider: 'person' }), 'A person is playing Teo');
assert.equal(decidesPrint(teo, { decider: 'external' }), 'Teo comes from an outside program');
assert.equal(decidesPrint(teo, { decider: 'model', model: '  ' }), 'Teo follows a routine', 'a model with no name is no model to name');
assert.equal(quoted('Sardines, mostly.'), '“Sardines, mostly.”');
assert.equal(saidUnder({ to: marco, hhmm: '07:10' }), 'To Marco, 07:10');
assert.equal(saidUnder({ to: resident, hhmm: '07:10' }), 'To the resident, 07:10');
assert.equal(saidUnder({ to: marco, hhmm: null }), 'To Marco', 'no clock: no time (J25)');
assert.equal(saidUnder({ to: null, hhmm: '07:10' }), '07:10', 'to everyone near: the time alone');
assert.equal(saidUnder({ to: null, hhmm: null }), null);

// The last line said: the character's newest said event with a line, newest first as the read serves them.
const said = (subject, line, { to = null, tick = 10 } = {}) => ({ event_kind: 'said', subject_id: subject, tick, document: { thing: { line, to } } });
const events = [
  { event_kind: 'decision_applied', subject_id: 'teo', tick: 12, document: {} },
  said('marco', 'Morning.', { tick: 11 }),
  said('teo', '   ', { tick: 11 }),
  said('teo', 'Sardines, mostly. Come down early tomorrow.', { to: 'marco', tick: 10 }),
  said('teo', 'An older line.', { tick: 4 }),
];
assert.deepEqual({ ...lastSaid(events, 'teo') }, { line: 'Sardines, mostly. Come down early tomorrow.', to: 'marco', tick: 10 });
assert.deepEqual({ ...lastSaid([said('teo', 'To all.', { to: '' })], 'teo') }, { line: 'To all.', to: null, tick: 10 });
assert.equal(lastSaid(events, 'ines'), null);
assert.equal(lastSaid(undefined, 'teo'), null);
assert.equal(lastSaid([{ ...said('teo', 'No minute.'), tick: undefined }], 'teo').tick, null);
{
  // Reading back: page by page until found, at most SAID_READ.pages pages, never past the last page.
  const asked = [];
  const pages = [{ events: [said('marco', 'One.')], next: 'a' }, { events: [said('teo', 'Found.')], next: 'b' }, { events: [], next: null }];
  const readPage = async (before) => { asked.push(before); return pages[asked.length - 1]; };
  assert.equal((await readLastSaid(readPage, 'teo')).line, 'Found.');
  assert.deepEqual(asked, [null, 'a']);
  const none = [];
  assert.equal(await readLastSaid(async (before) => { none.push(before); return { events: [], next: 'more' }; }, 'teo'), null);
  assert.equal(none.length, SAID_READ.pages);
  const ends = [];
  assert.equal(await readLastSaid(async (before) => { ends.push(before); return { events: [], next: null }; }, 'teo'), null);
  assert.equal(ends.length, 1);
}

{
  // Keeping the chosen character's last line: read once chosen, again every SAID_READ.every ms, never two at once;
  // a read for someone no longer chosen is dropped.
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
  const asked = [], answers = [];
  let changes = 0;
  const kept = keepLastSaid({ readPage: (before) => new Promise((resolve) => { asked.push(before); answers.push(resolve); }), onRead: () => { changes++; } });
  assert.equal(kept.of('teo', 0), null);
  assert.equal(kept.of('teo', 10), null);
  assert.equal(kept.of('teo', SAID_READ.every + 10), null);
  assert.equal(asked.length, 1, 'one read at a time, however long it takes');
  answers[0]({ events: [said('teo', 'Found.')], next: null }); await settle();
  assert.equal(kept.of('teo', 20).line, 'Found.');
  assert.equal(changes, 1);
  kept.of('teo', SAID_READ.every - 1);
  assert.equal(asked.length, 1, 'not read again before its time');
  kept.of('teo', SAID_READ.every);
  assert.equal(asked.length, 2);
  answers[1]({ events: [said('teo', 'Found.')], next: null }); await settle();
  assert.equal(changes, 1, 'the same line read again changes nothing');
  // Choosing someone else forgets the line at once and reads theirs; a late answer for Teo is dropped.
  kept.of('teo', 2 * SAID_READ.every);
  assert.equal(kept.of('marco', 2 * SAID_READ.every + 1), null);
  answers[2]({ events: [said('teo', 'Late.')], next: null }); await settle();
  assert.equal(kept.of('marco', 2 * SAID_READ.every + 2), null);
  assert.equal(asked.length, 4);
  answers[3]({ events: [said('marco', 'Morning.')], next: null }); await settle();
  assert.equal(kept.of('marco', 2 * SAID_READ.every + 3).line, 'Morning.');
  // A failed read keeps what is known and tries again in time.
  const failing = keepLastSaid({ readPage: async () => { throw new Error('offline'); } });
  assert.equal(failing.of('teo', 0), null); await settle();
  assert.equal(failing.of('teo', 1), null);
  assert.equal(kept.of(null, 3 * SAID_READ.every), null, 'nobody chosen: nothing read');
}

// Who decides: an outside program, a person playing, their model, or their routine.
assert.equal(deciderOf({ decider: 'external', model: 'M' }), 'external');
assert.equal(deciderOf({ decider: 'person', model: 'M' }), 'person');
assert.equal(deciderOf({ decider: null, model: 'Nemotron 3 Nano 30B' }), 'model');
assert.equal(deciderOf({ decider: null, model: '  ' }), 'routine');
assert.equal(deciderOf({}), 'routine');

// What the group says, top to bottom (J30's picture): Teo, waiting, his last line to Marco at 07:10, three choices, his model.
const keys = content => content.rows.map(row => `${row.key} ${row.word}`);
const picture = groupContent({ who: teo, doing: 'Waiting by the bench', said: lastSaid(events, 'teo'), toWho: marco, startMinute: 420,
  decider: 'model', model: 'Nemotron 3 Nano 30B', connected: true });
assert.equal(picture.name, 'Teo');
assert.equal(picture.doing, 'Waiting by the bench');
assert.deepEqual({ ...picture.said }, { line: '“Sardines, mostly. Come down early tomorrow.”', under: 'To Marco, 07:10' });
assert.deepEqual(keys(picture), ["Enter Teo's day", "R Let Teo's model decide", 'V Follow Teo']);
assert.deepEqual(picture.rows.map(row => row.action), ['details', 'run', 'follow']);
assert.deepEqual(picture.rows.map(row => row.shortcut), ['Enter', 'R', 'V']);
assert.equal(picture.print, 'Nemotron 3 Nano 30B decides for Teo');
// Each row only where it works (K6).
const running = groupContent({ who: teo, decider: 'model', model: 'Nemotron 3 Nano 30B', running: true, left: '1:52' });
assert.deepEqual(keys(running), ["Enter Teo's day", "R Stop Teo's model", 'V Follow Teo']);
assert.equal(running.print, "Teo's model is deciding · 1:52 left");
assert.equal(groupContent({ who: teo, decider: 'model', model: 'N', running: true, left: '1:52', spent: '$0.0003 spent' }).print, "Teo's model is deciding · 1:52 left · $0.0003 spent");
assert.equal(groupContent({ who: teo, decider: 'model', model: 'N', spent: '$0.0003 spent' }).print, 'N decides for Teo', 'no run, no spending');
assert.deepEqual(keys(groupContent({ who: teo, decider: 'model', model: 'M', connected: false })), ["Enter Teo's day", 'V Follow Teo'], 'a model that cannot be asked here: no R');
assert.deepEqual(keys(groupContent({ who: teo, decider: 'routine', assignable: true })), ["Enter Teo's day", "M Choose Teo's AI model", 'V Follow Teo']);
assert.deepEqual(keys(groupContent({ who: teo, decider: 'routine', assignable: false })), ["Enter Teo's day", 'V Follow Teo'], 'no M where this page cannot choose');
assert.deepEqual(keys(groupContent({ who: teo, decider: 'person', model: 'M' })), ["Enter Teo's day", 'V Follow Teo']);
assert.deepEqual(keys(groupContent({ who: teo, decider: 'external', assignable: true })), ["Enter Teo's day", 'V Follow Teo']);
assert.deepEqual(keys(groupContent({ who: teo, following: true })), ["Enter Teo's day", 'V Stop following']);
assert.equal(groupContent({ who: teo, decider: 'routine', running: true, left: '1:52' }).print, 'Teo follows a routine', 'a run on without their model: their routine still decides');
assert.deepEqual(keys(groupContent({ who: teo, decider: 'routine', running: true, left: '1:52' })), ["Enter Teo's day", 'V Follow Teo'], 'no Stop for someone the run does not ask');
// Nothing said yet: both lines are left out; no clock: no time; to everyone near: the time alone.
assert.equal(groupContent({ who: teo }).said, null);
assert.equal(groupContent({ who: teo, said: lastSaid(events, 'teo'), toWho: marco, startMinute: null }).said.under, 'To Marco');
assert.equal(groupContent({ who: teo, said: { line: 'Hello.', to: null, tick: 10 }, startMinute: 420 }).said.under, '07:10');
assert.equal(groupContent({ who: teo, said: { line: 'Hello.', to: null, tick: 10 }, startMinute: null }).said.under, null);
assert.equal(groupContent({ who: resident, doing: '  ' }).doing, null);
assert.equal(groupContent({ who: resident }).name, 'Resident');
// While their record is read: the name and that it is reading, no keys and no small print yet.
assert.deepEqual({ ...groupContent({ who: teo, reading: true, decider: 'model', model: 'M' }), rows: [] }, { name: 'Teo', doing: "Reading Teo's record…", said: null, note: null, rows: [], print: null, refused: false, declared: null });

// An outside AI agent decides (AG1d 2): its day and Follow only, no Model and no Run; the print; its own words as
// parts, each only where declared, exactly as sent; a game's program keeps its words and has none.
const visitor = called({ name: null, kind: 'visitor' });
const declared = { name: 'Scout', maker: 'Harbour Lab', mind: 'Nemotron 3 Nano 30B' };
const agentGroup = groupContent({ who: visitor, decider: 'agent', declared, assignable: true, connected: true });
assert.deepEqual(agentGroup.rows.map(row => `${row.key} ${row.word}`), ["Enter The visitor's day", 'V Follow the visitor']);
assert.equal(agentGroup.print, 'An outside AI agent decides for the visitor.');
assert.equal(agentGroup.declared.map(part => part.words).join(''), 'In its own words: Scout, made by Harbour Lab, thinking with Nemotron 3 Nano 30B.');
assert.deepEqual(agentGroup.declared.filter(part => part.declared).map(part => part.words), ['Scout', 'Harbour Lab', 'Nemotron 3 Nano 30B']);
assert.equal(groupContent({ who: visitor, decider: 'agent', declared: { name: 'Scout', maker: '', mind: null } }).declared.map(part => part.words).join(''), 'In its own words: Scout.');
assert.equal(groupContent({ who: visitor, decider: 'agent', declared: null }).declared, null);
assert.equal(groupContent({ who: visitor, decider: 'agent', declared: { name: ' <b>x</b> ', maker: 'm', mind: null } }).declared[1].words, ' <b>x</b> ', 'as sent, never reworded');
assert.equal(groupContent({ who: visitor, decider: 'external', declared }).declared, null);
assert.equal(deciderOf({ decider: 'agent', model: 'M' }), 'agent');

// A read-only copy draws no run key: neither Let decide nor Stop, which do nothing there (ROOT's sweep of 27 October).
assert.deepEqual(groupContent({ who: teo, decider: 'model', model: 'M', connected: true, canRun: false }).rows.map(row => row.action), ['details', 'follow']);
assert.deepEqual(groupContent({ who: teo, decider: 'model', model: 'M', connected: true, running: true, canRun: false }).rows.map(row => row.action), ['details', 'follow']);
assert.deepEqual(groupContent({ who: teo, decider: 'model', model: 'M', connected: true }).rows.map(row => row.action), ['details', 'run', 'follow']);

// The Run question (r08): the same group asking in place; J28's counts, each person with their own model (F9).
const ari = called({ name: 'Ari' }), ines = called({ name: 'Ines' });
const [nano, qwen, sup] = ['Nemotron 3 Nano 30B', 'Qwen3 235B Instruct', 'Nemotron 3 Super 120B'];
// A model's name stays whole on one line in the note (DESIGN's fold-in): its spaces are no-break spaces.
const whole = text => text.replace(/Nemotron 3 Nano 30B|Qwen3 235B Instruct|Nemotron 3 Super 120B|\bM\b(?= decides)/gu, name => name.replaceAll(' ', '\u00a0'));
// Whose models decide, and nothing about everyone else (ROOT's sweep of 27 October).
assert.equal(modelsDecide([teo], { models: [nano] }), whole("Teo's Nemotron 3 Nano 30B decides."));
assert.equal(modelsDecide([teo, ari], { models: [nano, qwen] }), whole("Teo's Nemotron 3 Nano 30B and Ari's Qwen3 235B Instruct decide."));
assert.equal(modelsDecide([teo, ari, resident], { models: [nano, qwen, sup] }),
  whole("Teo's Nemotron 3 Nano 30B, Ari's Qwen3 235B Instruct and the resident's Nemotron 3 Super 120B decide."));
assert.ok(!/Nemotron 3/u.test(modelsDecide([teo], { models: [sup] })), 'no break inside a model name');
assert.equal(modelsDecide([teo, ari, resident, ines], { models: [nano, qwen, sup, nano] }), whole("Teo's Nemotron 3 Nano 30B and 3 more people's models decide."));
assert.equal(modelsDecide([teo, ari], { models: [nano] }), whole("Teo's Nemotron 3 Nano 30B and Ari's model decide."), 'a model not read yet');
assert.equal(modelsDecide([]), null);
const limits = { wallSeconds: 600, usd: '0.05000000' };
const asked = questionGroup({ who: teo, askers: [teo], models: ['Nemotron 3 Nano 30B'], limits, anotherModel: true });
assert.equal(asked.name, 'Teo');
assert.equal(asked.doing, 'Run for 10 minutes');
assert.equal(asked.said, null);
assert.equal(asked.note, whole("Teo's Nemotron 3 Nano 30B decides."));
assert.deepEqual(keys(asked), ['Enter Run', 'M Choose another model']);
assert.deepEqual(asked.rows.map(row => row.action), ['run', 'model']);
assert.equal(asked.print, 'At most $0.05');
assert.equal('after' in asked, false, 'no line on when it stops under the cap');
assert.equal(asked.refused, false);
assert.deepEqual(keys(questionGroup({ who: teo, models: ['M'], limits })), ['Enter Run'], 'no other model offered, or this page cannot choose: no M');
assert.equal(questionGroup({ who: teo, models: ['M'], limits, busy: true }).rows[0].disabled, true);
// A refusal takes the small print's place in its own sentence; Run stays (dimmed), its key still answers.
const refusedRun = questionGroup({ who: teo, models: ['M'], limits, refusal: 'stale_society_state' });
assert.equal(refusedRun.print, 'The world changed a moment ago. Press Run again.');
assert.equal(refusedRun.refused, true);
assert.equal(refusedRun.rows[0].disabled, false);
// Models on this computer not running: one model is, two or more are (ROOT's sweep of 27 October).
assert.equal(questionGroup({ who: teo, askers: [teo], models: ['Qwen3 4B Instruct'], limits, refusal: 'provider_not_running' }).print,
  'Qwen3 4B Instruct is not running on this computer now. Start it, then try again.');
assert.equal(questionGroup({ who: teo, askers: [teo, ari], models: ['Qwen3 4B Instruct', 'Granite 4.1 8B'], limits, refusal: 'provider_not_running' }).print,
  'Qwen3 4B Instruct and Granite 4.1 8B are not running on this computer now. Start them, then try again.');
assert.equal(questionGroup({ who: teo, askers: [teo, ari], models: ['Qwen3 4B Instruct', ' Qwen3 4B Instruct '], limits, refusal: 'provider_not_running' }).print,
  'Qwen3 4B Instruct is not running on this computer now. Start it, then try again.', 'one model for two people is one model');
assert.equal(questionGroup({ who: teo, models: ['M'], limits, refusal: 'unheard_of' }).print, 'The run did not start. Nothing was spent.');
assert.equal(questionGroup({ who: teo, askers: [], models: ['M'], limits }).note, whole("Teo's M decides."), 'the chosen one at least');
assert.equal(questionGroup({ who: teo, models: ['M'], limits: { wallSeconds: 300, usd: '0.02000000' } }).doing, 'Run for 5 minutes');
// Whose model is whose (F9): the note pairs each person with theirs, and the small print is the cap alone.
const three = questionGroup({ who: teo, askers: [teo, ari, resident], models: [nano, qwen, sup], limits });
assert.equal(three.note, whole("Teo's Nemotron 3 Nano 30B, Ari's Qwen3 235B Instruct and the resident's Nemotron 3 Super 120B decide."));
assert.equal(three.print, 'At most $0.05');
assert.equal(questionGroup({ who: teo, askers: [teo, ari], models: [nano, nano], limits }).note, whole("Teo's Nemotron 3 Nano 30B and Ari's Nemotron 3 Nano 30B decide."));

// Choose a model (r07; a gallery that teaches, A3): what this computer runs first, then the key group by price, Routine
// last; each group under its label, a model's maker and size under its name, Current on theirs, the chosen row marked
// and opened with its maker's own words, where they come from and the licence.
const card = (maker, total, says, licence) => ({ maker, parameters: total ? { total, active: null } : null, licence, says,
  source: `https://huggingface.co/maker/model/blob/${'0'.repeat(40)}/README.md`, readOn: '2026-10-23' });
const NEBIUS = 'Nebius Token Factory, which serves open models behind one OpenAI-compatible API.';
const served = [
  { provider: 'nebius', providerDescription: NEBIUS, modelId: 'qwen/235b', name: 'Qwen3 235B Instruct', price: { input: '0.20', output: '0.60' }, card: card('Qwen', '235B', 'Improvements in general capabilities.', 'Apache 2.0') },
  { provider: 'nebius', providerDescription: NEBIUS, modelId: 'nvidia/nano', name: 'Nemotron 3 Nano 30B', price: { input: '0.06', output: '0.24' }, card: card('NVIDIA', '30B', 'A general purpose reasoning and chat model.', 'NVIDIA Nemotron Open Model License') },
  { provider: 'local', providerDescription: 'This computer, through Ollama: an open model.', modelId: 'qwen/4b', name: 'Qwen3 4B Instruct', local: true, card: card('Qwen', '4.0B', 'Improvements in general capabilities.', 'Apache 2.0') },
];
const ordered = choosableModels({ models: served });
assert.deepEqual(ordered.map(model => model.name), ['Qwen3 4B Instruct', 'Nemotron 3 Nano 30B', 'Qwen3 235B Instruct'], 'this computer first, then the lowest price');
// F5: only a model this install can ask is offered. A server on this computer the install does not reach, or a hosted
// provider it holds no key for, is refused in the models read and left out of both choosers.
const refusedHere = [
  served[0],
  { ...served[1], refusal: 'provider_credential_absent' },
  { ...served[2], refusal: 'provider_not_admitted' },
];
assert.deepEqual(choosableModels({ models: refusedHere }).map(model => model.name), ['Qwen3 235B Instruct']);
assert.deepEqual(new Set(choosableModels({ models: served })), new Set(served), 'nothing refused: every served model is offered');
assert.deepEqual(choosableModels(null), [], 'no models read yet: nothing offered');
// Every model refused (DESIGN, "F5 A"): nothing to choose, so neither the card nor the page offers [M] for a person on
// their routine, and a chooser left open closes; the Run line says why by its code.
const allRefused = refusedHere.map(model => ({ ...model, refusal: model.refusal ?? 'provider_credential_absent' }));
assert.equal(choosableModels({ models: allRefused }).length, 0);
assert.equal(offersModels({ takesModelChoices: true, models: allRefused }), false, 'every model refused: no [M]');
assert.equal(offersModels({ takesModelChoices: true, models: refusedHere }), true);
assert.equal(offersModels({ takesModelChoices: false, models: served }), false, 'choices not taken: no [M]');
const nothingToChoose = groupContent({ who: teo, doing: null, decider: 'routine', assignable: offersModels({ takesModelChoices: true, models: allRefused }) });
assert.equal(nothingToChoose.rows.some(row => row.action === 'model'), false);
assert.equal(groupContent({ who: teo, doing: null, decider: 'routine', assignable: offersModels({ takesModelChoices: true, models: refusedHere }) }).rows.some(row => row.action === 'model'), true);
// Where it stands: its words 100 px past the person's right edge, its middle level with their head; the leader
// from the head to an elbow 56 px before the words at the name line's middle, ending 36 px before them.
const viewport = { width: 1920, height: 1080 }, size = { width: 420, height: 336 };
const head = { x: 992, y: 466 }, bounds = { left: 905, right: 996 };
const right = groupPlace({ head, bounds, size, viewport });
assert.equal(right.side, 'right');
assert.equal(right.x, 1096);
assert.equal(right.y, 466 - 168);
assert.deepEqual({ ...right.leader.from }, { x: 992, y: 466 });
assert.deepEqual({ ...right.leader.elbow }, { x: 1040, y: 298 + 24 });
assert.deepEqual({ ...right.leader.to }, { x: 1060, y: 298 + 24 });
// Near the right edge it flips to the left; the leader mirrors.
const nearEdge = groupPlace({ head: { x: 1700, y: 500 }, bounds: { left: 1660, right: 1740 }, size, viewport });
assert.equal(nearEdge.side, 'left');
assert.equal(nearEdge.x, 1660 - 100 - 420);
assert.equal(nearEdge.leader.elbow.x, nearEdge.x + 420 + 56);
assert.equal(nearEdge.leader.to.x, nearEdge.x + 420 + 36);
// A side to prefer (the talking scene's) is taken where it fits there, else the usual rule.
assert.equal(groupPlace({ head, bounds, size, viewport, prefer: 'left' }).side, 'left');
assert.equal(groupPlace({ head, bounds, size, viewport, prefer: 'left' }).x, 905 - 100 - 420);
assert.equal(groupPlace({ head: { x: 200, y: 500 }, bounds: { left: 160, right: 240 }, size, viewport, prefer: 'left' }).side, 'right', 'no room on the left: the right');
assert.equal(groupPlace({ head: { x: 1700, y: 500 }, bounds: { left: 1660, right: 1740 }, size, viewport, prefer: 'right' }).side, 'left', 'no room on the right: the left');
// A card taller than the room between the bands (a short window, DESIGN's short-window review): it comes up until its
// whole height shows 24 px above the bottom, its leader following to its name line.
const short = { width: 1744, height: 567 }, tall = { width: 420, height: 452 };
const upped = groupPlace({ head: { x: 992, y: 300 }, bounds, size: tall, viewport: short });
assert.equal(upped.y, 567 - 24 - 452, 'its whole height shows 24 px above the bottom');
assert.equal(upped.leader.elbow.y, upped.y + 24);
// Held while its person is out of view, in a window made smaller since: fitted to the window as it is now.
const heldShort = groupHeld({ last: { x: 1500, y: 410 }, edge: { x: 0, y: 283 }, size: tall, viewport: short });
assert.deepEqual([heldShort.x, heldShort.y], [1744 - 32 - 420, 567 - 24 - 452], 'held whole inside the smaller window');
assert.equal(heldShort.leader.to.y, heldShort.y + 24);
// P7: its person walked out of view with the list open. It stays where it stood; the leader runs from the edge they
// left by to the side of the group facing it, at the name line, as groupPlace draws one.
const offLeft = groupHeld({ last: right, edge: { x: 0, y: 540 }, size });
assert.deepEqual([offLeft.x, offLeft.y, offLeft.side], [right.x, right.y, 'right'], 'left by the left edge: held where it stood');
assert.deepEqual({ ...offLeft.leader.from }, { x: 0, y: 540 });
assert.deepEqual({ ...offLeft.leader.elbow }, { ...right.leader.elbow }, 'the leader ends where it ended');
assert.deepEqual({ ...offLeft.leader.to }, { ...right.leader.to });
const offRight = groupHeld({ last: right, edge: { x: 1920, y: 300 }, size });
assert.deepEqual([offRight.x, offRight.side], [right.x, 'left'], 'left by the right edge: the leader comes to its right side');
assert.equal(offRight.leader.elbow.x, right.x + 420 + 56);
assert.equal(offRight.leader.to.x, right.x + 420 + 36);
// It keeps inside the screen and clear of the bands where the world screen's pills and keys sit.
assert.equal(groupPlace({ head: { x: 400, y: 20 }, bounds: { left: 360, right: 440 }, size, viewport }).y, GROUP_LAYOUT.top);
assert.equal(groupPlace({ head: { x: 400, y: 1070 }, bounds: { left: 360, right: 440 }, size, viewport }).y, 1080 - GROUP_LAYOUT.bottom - 336);
assert.equal(groupPlace({ head: { x: 400, y: 0 }, bounds: { left: 360, right: 440 }, size, viewport: { width: 1440, height: 900 }, scale: 0.78 }).y, GROUP_LAYOUT.top * 0.78);
// With room on neither side it stays right, held inside the screen.
const crowded = groupPlace({ head: { x: 960, y: 540 }, bounds: { left: 400, right: 1500 }, size, viewport });
assert.equal(crowded.side, 'right');
assert.equal(crowded.x, 1920 - 32 - 420);
// At 1440 by 900 (scale 0.78) the gaps scale: the words 78 px from the person.
const small = groupPlace({ head: { x: 680, y: 400 }, bounds: { left: 600, right: 690 }, size, viewport: { width: 1440, height: 900 }, scale: 0.78 });
assert.equal(small.side, 'right');
assert.equal(small.x, 690 + 78);
assert.ok(Math.abs(small.leader.to.x - (small.x - 36 * 0.78)) < 1e-9);

// The words are WORDS.md's: no em dash in the files.
for (const file of ['character-group.mjs', 'character-group.ts', 'character-group.css', 'character-words.mjs']) {
  assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /\u2014/u, file);
}

// A2: where no model runs on this computer the card says who decides and no how-to (ROOT's sweep of 27 October).
const lone = called({ name: 'Ada' });
assert.equal(groupContent({ who: lone }).print, 'Ada follows a routine');
assert.equal('after' in groupContent({ who: lone }), false);
// A run whose every model is on this computer says it is free in place of its cap.
const free = questionGroup({ who: lone, models: ['Qwen3 4B Instruct'], limits: { wallSeconds: 600, usd: '0.05000000' }, free: true });
assert.equal(free.print, 'Free, on this computer');
assert.equal(questionGroup({ who: lone, models: ['Qwen3 4B Instruct'], limits: { wallSeconds: 600, usd: '0.05000000' } }).print, 'At most $0.05');
const read = { models: [{ provider: 'ollama_local', modelId: 'm', local: true }, { provider: 'nebius', modelId: 'n', local: false }] };
assert.equal(freeHere(read, [{ provider: 'ollama_local', modelId: 'm' }]), true);
assert.equal(freeHere(read, [{ provider: 'ollama_local', modelId: 'm' }, { provider: 'nebius', modelId: 'n' }]), false, 'one hosted model costs');
assert.equal(freeHere(read, []), false);

{
  // A guest's chooser (U2, DESIGN 11:29 and 12:20, ROOT 12:20): a model asking which once can cost more than they have
  // left for AI models here stands faint with why, never numbered or chosen; on a person's own install every model stays.
  const most = { 'qwen/235b': '0.04300000', 'nvidia/nano': '0.00270000', 'qwen/4b': '0' };
  const dear = served.map(model => ({ ...model, attemptMostUsd: most[model.modelId] }));
  const guest = { takesModelChoices: true, models: dear, spendHereUsd: { nebius: '0.03000000' } };
  assert.deepEqual(choosableModels(guest).map(model => model.name), ['Qwen3 4B Instruct', 'Nemotron 3 Nano 30B']);
  assert.deepEqual(overRows(guest), [{ word: 'Qwen3 235B Instruct', sub: 'Qwen · 235B',
    line: 'Asking it once can cost up to $0.043, more than the $0.03 left for AI models here.', current: false }]);
  // The person's own model keeps "Current" while it stands faint (U3b, DESIGN 15:58).
  const qwen = dear.find(model => model.modelId === 'qwen/235b');
  assert.deepEqual(overRows(guest, { provider: qwen.provider, modelId: qwen.modelId }).map(row => row.current), [true]);
  assert.deepEqual(overRows(guest, { provider: 'nebius', modelId: 'nvidia/nano' }).map(row => row.current), [false]);
  const owner = { takesModelChoices: true, models: dear };
  assert.equal(choosableModels(owner).length, 3, "a person's own install: every model stays choosable");
  assert.deepEqual(overRows(owner), []);
  const noneHere = { ...guest, spendHereUsd: { nebius: '0.00100000' }, models: dear.filter(model => !model.local) };
  assert.deepEqual(choosableModels(noneHere), []);
  assert.equal(offersModels(noneHere), true, '[M] still shows, so the list can say why');
}

export default true;
