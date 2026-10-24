import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { GROUP_LAYOUT, MODEL_ROWS, SAID_READ, choosableModels, offersModels, openWhileOffered, deciderOf, freeHere, groupContent, groupHeld, groupPlace, keepLastSaid, lastSaid, modelGroup, modelPicker, noModelLine, noneRunningHere, questionGroup, readLastSaid } from './character-group.mjs';
import { GROUP_WORDS, called, decidesPrint, modelsDecide, noModelRunning, quoted, saidUnder, stopsAfter } from './character-words.mjs';
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
assert.deepEqual({ ...groupContent({ who: teo, reading: true, decider: 'model', model: 'M' }), rows: [] }, { name: 'Teo', doing: "Reading Teo's record…", said: null, note: null, rows: [], list: null, print: null, after: null, refused: false });

// The Run question (r08): the same group asking in place; J28's words for whose models decide.
const ari = called({ name: 'Ari' }), ines = called({ name: 'Ines' });
assert.equal(modelsDecide([teo]), "Teo's model decides. Everyone else carries on as before.");
assert.equal(modelsDecide([teo], { others: false }), "Teo's model decides.");
assert.equal(modelsDecide([teo, ari]), "Teo's and Ari's models decide. Everyone else carries on as before.");
assert.equal(modelsDecide([teo, ari, resident]), "Teo's, Ari's and the resident's models decide. Everyone else carries on as before.");
assert.equal(modelsDecide([teo, ari, resident, ines]), "Teo's model and 3 more decide. Everyone else carries on as before.");
assert.equal(modelsDecide([]), null);
assert.equal(stopsAfter(10), 'It stops after 10 minutes, or when you stop it.');
assert.equal(stopsAfter(1), 'It stops after 1 minute, or when you stop it.');
const limits = { wallSeconds: 600, usd: '0.05000000' };
const asked = questionGroup({ who: teo, askers: [teo], models: ['Nemotron 3 Nano 30B'], limits, anotherModel: true });
assert.equal(asked.name, 'Teo');
assert.equal(asked.doing, 'Run for 10 minutes');
assert.equal(asked.said, null);
assert.equal(asked.note, "Teo's model decides. Everyone else carries on as before.");
assert.deepEqual(keys(asked), ['Enter Run', 'M Choose another model']);
assert.deepEqual(asked.rows.map(row => row.action), ['run', 'model']);
assert.equal(asked.print, 'Nemotron 3 Nano 30B · at most $0.05');
assert.equal(asked.after, 'It stops after 10 minutes, or when you stop it.');
assert.equal(asked.refused, false);
assert.deepEqual(keys(questionGroup({ who: teo, models: ['M'], limits })), ['Enter Run'], 'no other model offered, or this page cannot choose: no M');
assert.equal(questionGroup({ who: teo, models: ['M'], limits, busy: true }).rows[0].disabled, true);
// A refusal takes the small print's place in its own sentence; Run stays (dimmed), its key still answers.
const refusedRun = questionGroup({ who: teo, models: ['M'], limits, refusal: 'stale_society_state' });
assert.equal(refusedRun.print, 'The world changed a moment ago. Press Run again.');
assert.equal(refusedRun.after, null);
assert.equal(refusedRun.refused, true);
assert.equal(refusedRun.rows[0].disabled, false);
assert.equal(questionGroup({ who: teo, models: ['M'], limits, refusal: 'unheard_of' }).print, 'The run did not start. Nothing was spent.');
assert.equal(questionGroup({ who: teo, askers: [], models: ['M'], limits }).note, "Teo's model decides. Everyone else carries on as before.", 'the chosen one at least');
assert.equal(questionGroup({ who: teo, models: ['M'], limits: { wallSeconds: 300, usd: '0.02000000' } }).doing, 'Run for 5 minutes');
// The models a run asks, as they are (DESIGN's aha 20): three people, three models, named by the chosen one's.
const three = questionGroup({ who: teo, askers: [teo, ari, resident], models: ['Nemotron 3 Nano 30B', 'Qwen3 235B Instruct', 'Nemotron 3 Super 120B'], limits });
assert.equal(three.print, 'Nemotron 3 Nano 30B and 2 other models · at most $0.05');
assert.equal(questionGroup({ who: teo, askers: [teo, ari], models: ['Nemotron 3 Nano 30B', 'Qwen3 235B Instruct'], limits }).print, 'Nemotron 3 Nano 30B and Qwen3 235B Instruct · at most $0.05');
assert.equal(questionGroup({ who: teo, askers: [teo, ari], models: ['Nemotron 3 Nano 30B', 'Nemotron 3 Nano 30B'], limits }).print, 'Nemotron 3 Nano 30B · at most $0.05', 'one model two people use is named once');

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
const listed = modelGroup({ who: teo, models: ordered, current: { provider: 'nebius', modelId: 'nvidia/nano' }, focus: 1 });
assert.equal(listed.name, 'Teo');
assert.equal(listed.doing, 'Choose an AI model');
assert.equal(listed.note, 'Open models, each from its maker. Picking one spends nothing. Only a run spends.');
assert.deepEqual(listed.rows, [], 'the list takes the rows\' place');
assert.equal(listed.list.waiting, null, 'a model runs on this computer: its group holds it');
assert.deepEqual(listed.list.rows.map(row => [row.key, row.word, row.sub, row.price, row.current, row.on, row.index, row.label]), [
  ['1', 'Qwen3 4B Instruct', 'Qwen · 4B', 'Free', false, false, 0, 'On this computer, free'],
  ['2', 'Nemotron 3 Nano 30B', 'NVIDIA · 30B', '$0.06 in · $0.24 out', true, true, 1, 'With your Nebius Token Factory key, per million tokens'],
  ['3', 'Qwen3 235B Instruct', 'Qwen · 235B', '$0.20 in · $0.60 out', false, false, 2, null],
  ['4', 'Routine', null, 'No AI model · Free', false, false, 3, null],
]);
assert.deepEqual(listed.list.rows.map(row => row.open), [null, {
  said: '\u201cA general purpose reasoning and chat model.\u201d', from: "from NVIDIA's model card · NVIDIA Nemotron Open Model License",
}, null, null], 'only the focused row opens, with its maker\'s words');
assert.equal(modelGroup({ who: teo, models: ordered, fromServer: true }).list.rows[1].label, "From this server's budget, per million tokens", 'a guest\'s page: the host pays');
const bare = modelGroup({ who: teo, models: [{ ...served[1], card: null }], focus: 0 }).list.rows[0];
assert.deepEqual([bare.sub, bare.open], [null, null], 'no card kept: no maker line and nothing opens');
assert.equal(modelGroup({ who: teo, models: [{ ...served[1], card: { ...served[1].card, maker: 'DeepSeek', parameters: null } }] }).list.rows[0].sub, 'DeepSeek', 'no size stated: the maker alone');
// This computer's group where none runs yet (A3 item 2): its label and one line, no key, never focused; left out where
// the install does not let one in, or once one runs.
assert.equal(noneRunningHere({ models: [{ ...served[2], refusal: 'provider_not_running' }, served[1]] }), true);
assert.equal(noneRunningHere({ models: [{ ...served[2], refusal: 'provider_not_admitted' }, served[1]] }), false);
assert.equal(noneRunningHere({ models: served }), false);
assert.equal(noneRunningHere(null), false);
const waiting = modelGroup({ who: teo, models: [served[1]], waiting: true });
assert.deepEqual(waiting.list.waiting, { label: 'On this computer, free', line: 'None is running yet. Start one with a local model runner, and it shows here, free.' });
assert.deepEqual(waiting.list.rows.map(row => [row.key, row.word, row.label]), [['1', 'Nemotron 3 Nano 30B', 'With your Nebius Token Factory key, per million tokens'], ['2', 'Routine', null]]);
assert.deepEqual(listed.list.keys.map(item => [item.keys.join(' '), item.word]), [['↑ ↓', 'Choose'], ['Enter', 'Use this model']]);
assert.equal(listed.print, null);
assert.equal(modelGroup({ who: teo, models: served, current: null, focus: 3 }).list.rows[3].current, true, 'no model: Routine is theirs');
assert.equal(modelGroup({ who: teo, models: [], current: null }).list.rows.length, 1, 'nothing served: Routine alone');
assert.equal(modelGroup({ who: teo, models: served, focus: 99 }).list.rows.at(-1).on, true, 'focus held to the list');
// F5: only a model this install can ask is offered. A server on this computer the install does not reach, or a hosted
// provider it holds no key for, is refused in the models read and left out of both choosers.
const refusedHere = [
  served[0],
  { ...served[1], refusal: 'provider_credential_absent' },
  { ...served[2], refusal: 'provider_not_admitted' },
];
assert.deepEqual(choosableModels({ models: refusedHere }).map(model => model.name), ['Qwen3 235B Instruct']);
assert.deepEqual(modelGroup({ who: teo, models: choosableModels({ models: refusedHere }) }).list.rows.map(row => [row.word, row.price]), [
  ['Qwen3 235B Instruct', '$0.20 in · $0.60 out'],
  ['Routine', 'No AI model · Free'],
]);
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
const open = { focus: 1 };
assert.equal(openWhileOffered(open, { models: refusedHere }), open, 'a model to choose: the chooser stays open');
assert.equal(openWhileOffered(open, { models: allRefused }), null, 'none left to choose: the chooser closes');
{
  let offered = served;
  const picker = modelPicker({ models: () => offered, currentOf: () => null, write: async () => 'verified', refusal: () => '' });
  const row = { key: 'teo' };
  picker.open(row);
  assert.equal(picker.of(row)?.focus, served.length, 'opens on Routine');
  offered = [];
  assert.equal(picker.of(row), null, 'every model refused while the card\'s list is open: it closes');
  offered = served;
  assert.equal(picker.of(row), null, 'closed stays closed');
}
const refusedChoice = modelGroup({ who: teo, models: served, refusal: 'This model cannot decide for Teo here.' });
assert.equal(refusedChoice.print, 'This model cannot decide for Teo here.');
assert.equal(refusedChoice.refused, true);
// Past nine, the window follows the focus and the number keys name its rows.
const many = Array.from({ length: 12 }, (_, index) => ({ provider: 'p', modelId: `m${index}`, name: `Model ${index + 1}`, price: { input: '0.1', output: '0.2' } }));
assert.equal(MODEL_ROWS, 9);
assert.deepEqual(modelGroup({ who: teo, models: many, focus: 0 }).list.rows.map(row => row.index), [0, 1, 2, 3, 4, 5, 6, 7, 8]);
const scrolled = modelGroup({ who: teo, models: many, focus: 11 });
assert.equal(scrolled.list.first, 3);
assert.deepEqual(scrolled.list.rows.map(row => [row.key, row.index]), [['1', 3], ['2', 4], ['3', 5], ['4', 6], ['5', 7], ['6', 8], ['7', 9], ['8', 10], ['9', 11]]);
assert.equal(modelGroup({ who: teo, models: many, focus: 12 }).list.rows.at(-1).word, 'Routine');

{
  // The model list's state and keys (r07): opens on their model, the arrows move, a number on the window or Enter writes,
  // Esc closes unchanged, movement keys pass, a key repeat is taken but does nothing.
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
  const row = { key: 'teo' }, writes = [], used = [];
  let current = { provider: 'nebius', modelId: 'nvidia/nano' }, keys = 0, answer = null;
  const picker = modelPicker({ models: () => ordered, currentOf: () => current, refusal: (error) => `refused ${error.code}`,
    write: (at, selected, key) => { writes.push([at.key, selected?.modelId ?? null, key]); return answer ?? Promise.resolve('verified'); },
    onUsed: (verified) => used.push(verified), newKey: () => `key-${++keys}` });
  const press = (code, extra = {}) => { let prevented = false; const fate = picker.key({ code, repeat: false, ...extra, preventDefault: () => { prevented = true; } }, 0, extra.onButton === true); return [fate, prevented]; };
  assert.equal(picker.key({ code: 'KeyM', preventDefault() {} }), false, 'no list: the key is not the list\'s');
  picker.open(row);
  assert.equal(picker.of(row).focus, 1, 'opens on their current model');
  assert.equal(picker.of({ key: 'other' }), null);
  assert.deepEqual(press('KeyW'), ['pass', false]);
  assert.deepEqual(press('Enter', { onButton: true }), ['pass', false], 'a focused button presses itself');
  assert.deepEqual(press('ArrowDown'), [true, true]);
  assert.equal(picker.of(row).focus, 2);
  press('ArrowDown'); press('ArrowDown'); press('ArrowDown');
  assert.equal(picker.of(row).focus, 3, 'held at Routine, the last row');
  press('ArrowUp', { repeat: true });
  assert.equal(picker.of(row).focus, 3, 'a repeat does nothing');
  press('Escape');
  assert.equal(picker.of(row), null, 'Esc closes it unchanged');
  assert.deepEqual(writes, []);
  // A number writes the model on that row of the window, with one key for the write; the list closes and the read is kept.
  picker.open(row);
  press('Digit3');
  await settle();
  assert.deepEqual(writes, [['teo', 'qwen/235b', 'key-2']]);
  assert.deepEqual(used, ['verified']);
  assert.equal(picker.of(row), null);
  // With nothing chosen it opens on Routine; Enter writes Routine (null); a refusal keeps the list with its words and a new key.
  current = null;
  picker.open(row);
  assert.equal(picker.of(row).focus, served.length);
  answer = Promise.reject({ code: 'stale' });
  press('Enter');
  await settle(); await settle();
  assert.deepEqual(writes.at(-1), ['teo', null, 'key-3']);
  assert.equal(picker.of(row).refusal, 'refused stale');
  assert.equal(picker.of(row).key, 'key-4');
  // While a write is on its way, Esc and the arrows wait; an index past Routine is no row.
  let finish;
  answer = new Promise((resolve) => { finish = resolve; });
  void picker.use(0);
  assert.equal(picker.of(row).busy, true);
  press('Escape'); press('ArrowDown');
  assert.equal(picker.of(row).focus, 0);
  finish('verified-2'); await settle(); await settle();
  assert.equal(picker.of(row), null);
  picker.open(row);
  const before = writes.length;
  await picker.use(served.length + 1);
  assert.equal(writes.length, before);
  picker.drop();
  assert.equal(picker.of(row), null, 'letting go of the character drops the list');
}

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

// A2 (DESIGN's "A2 amended"): where every model this install would offer is refused as not running on this computer,
// the card says, under its small print, how to have one, naming no runner.
const lone = called({ name: 'Ada' });
const local = { refusal: 'provider_not_running' }, hosted = { refusal: 'provider_credential_absent' };
const runOne = 'No AI model is running on this computer yet. Start one with a local model runner, and it can decide for Ada, free.';
assert.equal(noModelRunning(lone), runOne);
assert.equal(noModelLine({ takesModelChoices: true, models: [hosted, local] }, lone), runOne);
assert.equal(noModelLine({ takesModelChoices: true, models: [hosted, { refusal: null }] }, lone), null, 'a model to choose: [M] is offered instead');
assert.equal(noModelLine({ takesModelChoices: true, models: [hosted, { refusal: 'provider_not_admitted' }] }, lone), null, 'no model here by setting');
assert.equal(noModelLine({ takesModelChoices: true, models: [{ refusal: 'process_budget_spent' }, local] }, lone), null, 'a key whose models are spent: not this line');
assert.equal(noModelLine({ takesModelChoices: true, models: [hosted] }, lone), null, 'no model on this computer at all');
assert.equal(noModelLine({ takesModelChoices: false, models: [local] }, lone), null, 'people no model runs');
assert.equal(noModelLine(null, lone), null);
assert.equal(groupContent({ who: lone, noModel: runOne }).after, runOne);
assert.equal(groupContent({ who: lone, assignable: true, noModel: runOne }).after, null, 'never beside [M]');
assert.equal(groupContent({ who: lone }).after, null);
// A run whose every model is on this computer says it is free in place of its cap.
const free = questionGroup({ who: lone, models: ['Qwen3 4B Instruct'], limits: { wallSeconds: 600, usd: '0.05000000' }, free: true });
assert.equal(free.print, 'Qwen3 4B Instruct \u00b7 Free, on this computer');
assert.match(questionGroup({ who: lone, models: ['Qwen3 4B Instruct'], limits: { wallSeconds: 600, usd: '0.05000000' } }).print, /at most/);
const read = { models: [{ provider: 'ollama_local', modelId: 'm', local: true }, { provider: 'nebius', modelId: 'n', local: false }] };
assert.equal(freeHere(read, [{ provider: 'ollama_local', modelId: 'm' }]), true);
assert.equal(freeHere(read, [{ provider: 'ollama_local', modelId: 'm' }, { provider: 'nebius', modelId: 'n' }]), false, 'one hosted model costs');
assert.equal(freeHere(read, []), false);

export default true;
