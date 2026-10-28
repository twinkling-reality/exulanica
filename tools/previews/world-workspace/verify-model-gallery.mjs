import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { called } from './character-words.mjs';
import { firstFocus, galleryDetail, galleryPage, moveFocus, rowForKey } from './model-gallery.mjs';

// The model gallery (G2): the page's words, groups and rows, the detail of the model in focus, from the models read.
const sami = called({ name: 'Sami Sorrel', kind: 'resident' });
const card = (maker, total, active, says, licence) => ({ maker, parameters: total ? { total, active } : null, licence, says,
  source: `https://huggingface.co/maker/model/blob/${'0'.repeat(40)}/README.md`, readOn: '2026-10-23' });
const NEBIUS = 'Nebius Token Factory, which serves open models behind one OpenAI-compatible API.';
const nebius = (modelId, name, price, made, most) => ({ provider: 'nebius_token_factory', providerDescription: NEBIUS, modelId, name, price,
  mechanism: 'tool_call', card: made, contextWindowTokens: 262144, decisionMostUsd: most, attemptMostUsd: (Number(most) / 2).toFixed(8) });
const models = [
  nebius('qwen/235b', 'Qwen3 235B Instruct', { input: '0.20', output: '0.60' }, card('Qwen', '235B', '22B', 'Improvements in general capabilities.', 'Apache 2.0'), '0.00500000'),
  nebius('nvidia/super', 'Nemotron 3 Super 120B', { input: '0.30', output: '0.90' }, card('NVIDIA', '120B', '12B', 'Optimized for collaborative agents.', 'NVIDIA Nemotron Open Model License'), '0.00700000'),
  nebius('deepseek/flash', 'DeepSeek V4 Flash', { input: '0.14', output: '0.28' }, card('DeepSeek', null, null, 'A fast model.', 'MIT'), '0.00300000'),
  { provider: 'ollama', providerDescription: 'This computer, through Ollama.', modelId: 'qwen3:4b', name: 'Qwen3 4B Instruct', local: true, mechanism: 'json_schema',
    card: card('Qwen', '4.0B', null, 'Improvements in general capabilities.', 'Apache 2.0'), contextWindowTokens: 16384, decisionMostUsd: '0', attemptMostUsd: '0', price: { input: '0', output: '0' } },
];
const read = { takesModelChoices: true, models, requestTokensAtMost: 7200, decisionsCounted: 40, decisionsMaximum: 2000,
  byModel: [{ provider: 'nebius_token_factory', modelId: 'qwen/235b', decisions: 9, costMedianUsd: '0.00023340', costsCounted: 9 }] };

const page = galleryPage({ read, who: sami, doing: 'Resting at the bench', current: null });
assert.equal(page.over, 'Sami Sorrel · Resting at the bench');
assert.equal(page.title, 'Choose an AI model for Sami Sorrel');
// No line on what the models are or what picking costs, no maker's marks (ROOT's sweep of 27 October).
assert.equal('role' in page, false);
// This computer first, then the key's group by price, never ranked; Routine last under No AI model.
assert.deepEqual(page.groups.map(group => [group.label, group.rows.map(row => [row.key, row.name, row.sub, row.cost, row.current])]), [
  ['On this computer, free', [['1', 'Qwen3 4B Instruct', 'Qwen · 4B', 'Free', false]]],
  ['With your Nebius key', [
    ['2', 'DeepSeek V4 Flash', 'DeepSeek', 'at most $0.003 a decision', false],
    ['3', 'Qwen3 235B Instruct', 'Qwen · 235B, 22B at work at a time · decided 9 times here', 'about $0.0002 a decision', false],
    ['4', 'Nemotron 3 Super 120B', 'NVIDIA · 120B, 12B at work at a time', 'at most $0.007 a decision', false],
  ]],
  ['No AI model', [['5', 'Routine', null, 'Free', true]]],
]);
assert.equal(page.rows.some(row => 'mark' in row), false);
assert.deepEqual(page.keys.map(key => [key.caps.join(key.through ? ' to ' : ' '), key.word]), [['↑ ↓', 'Move'], ['1 to 5', 'Choose at once'], ['Esc', 'Back']]);
// A guest's page: the server's budget names the group (C4's own-key words are a person's own install's).
const served = galleryPage({ read, who: sami, fromServer: true });
assert.deepEqual(served.groups.map(group => group.label), ['On this server, free', "From this server's budget", 'No AI model'], 'a guest\'s own computer runs nothing here');
// Where a model runs is its group's label alone: the card says it no second time.
assert.equal(galleryDetail({ read, row: served.rows[0], who: sami }).facts.some(fact => fact.key === 'Runs on'), false);
// A full window says so: the count is at least what the read counted.
assert.match(galleryPage({ read: { ...read, decisionsCounted: 2000 }, who: sami }).groups[1].rows[1].sub, /decided at least 9 times here$/u);

// The focus starts on their own model, else the first with its maker's words; arrows stay on the choosable rows.
assert.equal(firstFocus(page), 0);
const theirs = galleryPage({ read, who: sami, current: { provider: 'nebius_token_factory', modelId: 'nvidia/super' } });
assert.equal(theirs.rows[firstFocus(theirs)].name, 'Nemotron 3 Super 120B');
assert.equal(theirs.rows.at(-1).current, false, 'Routine is not theirs while a model is');
assert.deepEqual([moveFocus(page, 0, -1), moveFocus(page, 4, 1), moveFocus(page, 2, 1)], [0, 4, 3]);
assert.equal(rowForKey(page, '3').name, 'Qwen3 235B Instruct');
assert.equal(rowForKey(page, '9'), null);

// The model in focus, each fact from the read; "about" with its sample once it has decided here, else "at most".
const asked = galleryDetail({ read, row: rowForKey(page, '3'), who: sami });
assert.deepEqual([asked.name, asked.by, asked.link], ['Qwen3 235B Instruct', 'By Qwen', models[0].card.source]);
assert.equal('mark' in asked, false);
// No reasons the role restates and no heading over them; the maker's words with no line on where they come from.
assert.deepEqual(asked.why, []);
assert.deepEqual(asked.words, { said: '“Improvements in general capabilities.”' });
assert.deepEqual(asked.facts.map(fact => [fact.key, fact.value]), [
  ['Size', '235 billion parameters, 22 billion at work at a time'],
  ['Reads', 'Text, up to 262,144 tokens at once'],
  ['Licence', 'Apache 2.0'],
  ['A decision', 'About $0.0002 a decision here (the middle of 9); at most $0.005, its largest request and longest answer, twice. $0.20 in and $0.60 out per million tokens.'],
  ['In this world', 'Decided 9 times'],
]);
assert.equal(asked.act, 'Choose it for Sami Sorrel');
assert.equal('then' in asked, false);
const never = galleryDetail({ read, row: rowForKey(page, '2'), who: sami });
assert.deepEqual(never.facts.map(fact => fact.key), ['Reads', 'Licence', 'A decision', 'In this world'], 'no size where its card states none');
assert.equal(never.facts.find(fact => fact.key === 'A decision').value, 'At most $0.003, its largest request and longest answer, twice. $0.14 in and $0.28 out per million tokens.');
assert.equal(never.facts.at(-1).value, 'Not asked here yet');
// A middle under the smallest figure says so, never "about less than".
const tiny = { ...read, byModel: [{ ...read.byModel[0], costMedianUsd: '0.00000400' }] };
assert.equal(galleryPage({ read: tiny, who: sami }).groups[1].rows[1].cost, 'less than $0.0001 a decision');
assert.match(galleryDetail({ read: tiny, row: rowForKey(page, '3'), who: sami }).facts.find(fact => fact.key === 'A decision').value, /^Less than \$0\.0001 a decision here \(the middle of 9\)/u);
// Routine in focus: its name and choosing it, nothing on what the routine is.
const routine = galleryDetail({ read, row: rowForKey(page, '5'), who: sami });
assert.deepEqual([routine.name, routine.act, routine.why], ['Routine', 'Choose the routine for Sami Sorrel', []]);
assert.equal('line' in routine, false);

// A guest's model too dear to ask once stands faint in its group with its line, no number, never focused (U2, U3b).
const guest = galleryPage({ read: { ...read, spendHereUsd: { nebius_token_factory: '0.00200000' } }, who: sami, fromServer: true,
  current: { provider: 'nebius_token_factory', modelId: 'nvidia/super' } });
assert.deepEqual(guest.groups[1].rows.map(row => row.name), ['DeepSeek V4 Flash']);
assert.deepEqual(guest.groups[1].faint.map(row => [row.name, row.line, row.current]), [
  ['Qwen3 235B Instruct', 'Asking it once can cost up to $0.0025, more than the $0.002 left for AI models here.', false],
  ['Nemotron 3 Super 120B', 'Asking it once can cost up to $0.0035, more than the $0.002 left for AI models here.', true],
]);
assert.deepEqual(guest.groups[1].faint.map(row => row.sub), ['Qwen · 235B, 22B at work at a time · decided 9 times here', 'NVIDIA · 120B, 12B at work at a time'],
  'a faint row keeps its maker and size as the others say them');
assert.equal(guest.rows.some(row => row.name === 'Qwen3 235B Instruct'), false, 'a faint row takes no focus');

// This computer's models a check found not able fold into one faint line (L1c); one being checked stands faint.
const runner = { ...read, runnerModels: [{ name: 'Llama 3.2 1B', state: 'not_able', reason: 'form' }, { name: 'Phi 4 Mini', state: 'checking' }] };
const here = galleryPage({ read: runner, who: sami }).groups[0];
assert.deepEqual(here.faint.map(row => row.name), ['Phi 4 Mini · Checking that it can decide for a person here…']);
assert.equal(here.fold.line, 'And 1 more on this computer that cannot decide for a person here.');
assert.equal('sub' in here.fold, false, 'no pointer to reasons drawn nowhere');

// A model a person's own runner holds (L1c): what its check found, and with no card its licence as its runner states it,
// no maker's words.
const held = { provider: 'ollama_local', providerDescription: 'This computer, through Ollama.', modelId: 'local/sha256-a', name: 'Qwen3 · 4.0B', local: true,
  mechanism: 'json_schema', card: null, contextWindowTokens: 40960, decisionMostUsd: '0', attemptMostUsd: '0', price: { input: '0', output: '0' },
  runner: { family: 'qwen3', size: '4.0B', servedAs: 'qwen3:4b', licence: 'Apache License 2.0', checkedMs: 2014 } };
const local = galleryPage({ read: { ...read, models: [held, ...models.slice(0, 1)] }, who: sami });
const checkedHere = galleryDetail({ read, row: local.rows[0], who: sami });
assert.deepEqual(checkedHere.why, ['Checked on this computer: it chose one of the offered choices in 2.0 s.']);
assert.equal(checkedHere.words, null, 'no card: no maker\'s words');
assert.equal(checkedHere.facts.find(fact => fact.key === 'Licence').value, 'from your runner \u00b7 \u201cApache License 2.0\u201d');
assert.equal(checkedHere.by, null);

// Where this install lets a model on this computer in and none runs, no group stands for it and nothing says how to
// start one (ROOT's sweep of 27 October).
const idle = galleryPage({ read: { ...read, models: [{ ...models[3], refusal: 'provider_not_running' }, ...models.slice(0, 3)] }, who: sami });
assert.deepEqual(idle.groups.map(group => group.label), ['With your Nebius key', 'No AI model']);

// Opened from the Integrations page with nobody to choose for: "Models", the same groups and rows, no number keys
// and nothing to choose.
const listed = galleryPage({ read, browse: true });
assert.equal(listed.title, 'Models');
assert.equal(listed.over, '');
assert.deepEqual(listed.groups.map(group => group.label), page.groups.map(group => group.label));
assert.deepEqual(listed.keys.map(key => key.word), ['Move', 'Back']);
assert.equal(listed.rows.some(row => row.current), false, 'nobody\'s choice is current in a list for nobody');
assert.equal(galleryDetail({ read, row: rowForKey(listed, '3'), browse: true }).act, null);
assert.equal(galleryDetail({ read, row: rowForKey(listed, '5'), browse: true }).act, null);

// No em dash, no score words: nothing ranks a model (Nebius 5(f)).
const source = readFileSync(new URL('./model-gallery.mjs', import.meta.url), 'utf8');
assert.equal(source.includes('\u2014'), false);
assert.doesNotMatch(source, /\b(best|better|worse|fastest|cheapest|smartest|ranked|score)\b/iu);

console.log('Model gallery checks passed: groups, rows, marks, costs, faint rows, focus and the detail of the model in focus.');
