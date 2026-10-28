import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DEFAULT_RUN, MODEL_MINDS_REFUSALS, NOT_CONNECTED, RUN_REFUSALS, RUN_WORDS, atMost, defaultRunLimits, endedNote, OWN_ENDS, runFor, runSpent, runStopWords, runLength, runRefusalWords, runningLine, spentWords, stripWords, timeLeft, decidingWords, pillRunLine } from './run-words.mjs';
import { called } from './character-words.mjs';

const python = path => readFileSync(new URL('../../../' + path, import.meta.url), 'utf8');

// Every code a run can be refused with has its words, and every worded code is one the server can
// send: the session refusals the repository raises, the route's own statuses, and a stale read.
const raised = new Set([
  ...python('exulanica/world/society_control_repository.py').matchAll(/SessionRefused\(\s*"([a-z_]+)"/g),
  ...python('exulanica/world/society_sessions.py').matchAll(/SessionRefused\(\s*"([a-z_]+)"/g),
].map(match => match[1]));
for (const code of python('exulanica/api/routes/society_control.py').matchAll(/^\s+"([a-z_]+)": 4\d\d,$/gm)) raised.add(code[1]);
assert.match(python('exulanica/api/app.py'), /_problem\(409, "stale_society_state"/);
raised.add('stale_society_state');
assert.deepEqual([...raised].sort(), Object.keys(RUN_REFUSALS).sort());
// A start refused while open models are not asked names the control read's code (U3): each worded code is one the
// control read can state, and the allowance used up reads as the budget spent, never "Nothing was spent".
const minds = python('exulanica/api/routes/society_control.py').match(/model_minds_code: Literal\[([^\]]+)\]/)[1].match(/"([a-z_]+)"/g).map(code => code.slice(1, -1));
for (const code of Object.keys(MODEL_MINDS_REFUSALS)) assert.ok(minds.includes(code), code);
assert.equal(runRefusalWords('spending_cap_reached'), 'The run did not start: the budget for AI models here is spent.');
// A playing world opens a run as it plays: no refusal asks the person to pause first.
assert.ok(!raised.has('society_not_paused'));
assert.equal(runRefusalWords('stale_society_state'), 'The world changed a moment ago. Press Run again.');
assert.equal(runRefusalWords('provider_credential_absent'), 'No AI model is connected here.');
assert.match(python('exulanica/world/decision_roles.py'), /"provider_credential_absent"/);
assert.equal(runRefusalWords('provider_not_running', 'Qwen3 4B Instruct'), 'Qwen3 4B Instruct is not running on this computer now. Start it, then try again.');
assert.equal(runRefusalWords('provider_not_running'), 'The model is not running on this computer now. Start it, then try again.');
// Two or more models named are not running, and are started (ROOT's sweep of 27 October).
assert.equal(runRefusalWords('provider_not_running', 'Qwen3 4B Instruct and Granite 4.1 8B', true), 'Qwen3 4B Instruct and Granite 4.1 8B are not running on this computer now. Start them, then try again.');
assert.match(python('exulanica/models/client.py'), /PROVIDER_NOT_RUNNING: Final = "provider_not_running"/);
// The host's money for models spent (J22); a run's own cap stays its spending limit.
for (const code of ['process_budget_spent', 'process_share_spent']) {
  assert.equal(runRefusalWords(code), 'The budget for AI models here is spent.');
  assert.match(python('exulanica/world/decision_roles.py'), new RegExp(`"${code}"`));
}
for (const code of ['toString', 'http_500', null]) assert.equal(runRefusalWords(code), 'The run did not start. Nothing was spent.');

// One noun: a run, never a session; never a code, an id or an em dash.
const who = called({ name: 'Teo' });
const limits = defaultRunLimits(60_000, 1);
const sentences = [...Object.values(RUN_WORDS), ...Object.values(RUN_REFUSALS), ...Object.values(MODEL_MINDS_REFUSALS), ...Object.values(NOT_CONNECTED), runFor(limits), runLength(limits)];
for (const words of sentences) {
  assert.doesNotMatch(words, /session|entity|provider/i, words);
  assert.doesNotMatch(words, /_|\u2014|\b(he|she)\b/i, words);
}
// The server's sentences for why a run ended name the run, one full sentence each.
const closed = python('exulanica/world/society_sessions.py');
const table = closed.slice(closed.indexOf('SESSION_CLOSED_WORDS'), closed.indexOf('def closed_words'));
const ended = [...table.matchAll(/:\s*\(?\s*"([^"]+)"/g)].map(match => match[1]);
assert.equal(ended.length, 10);
for (const sentence of ended) { assert.doesNotMatch(sentence, /session|someone|playback/i, sentence); assert.match(sentence, /\brun\b/, sentence); assert.match(sentence, /\.$/, sentence); }
assert.match(closed, /^UNWORDED_CLOSE: Final = "The run ended\."$/m);

// The default run: ten minutes of real time and at most five cents, whatever the world's clock.
assert.deepEqual(defaultRunLimits(60_000, 1), { wallSeconds: 600, minutes: 10, decisions: 20, usd: '0.05000000', calls: 40 });
assert.deepEqual(defaultRunLimits(8_000, 1), { wallSeconds: 600, minutes: 75, decisions: 150, usd: '0.05000000', calls: 300 });
assert.deepEqual(defaultRunLimits(60_000, 3), { wallSeconds: 600, minutes: 10, decisions: 60, usd: '0.05000000', calls: 120 });
assert.equal(defaultRunLimits(10, 4000).minutes, 1440);
assert.equal(defaultRunLimits(10, 4000).decisions, 10_000);
assert.equal(DEFAULT_RUN.usd, '0.05000000');

// The frames' words (08, 09).
assert.equal(runFor(limits), 'Run · 10 Minutes');
assert.equal(atMost(limits, true), 'At most $0.05');
assert.equal(runLength(limits), '10 minutes · at most $0.05');
// A run whose every model is on this computer says no money figure: free (A2).
assert.equal(runLength(limits, true), '10 minutes · Free');
const now = Date.parse('2026-10-14T17:20:00Z');
const open = { endsBy: '2026-10-14T17:29:13Z', limits: { usd: '0.05000000' }, used: { decisions: 4, usd: '0.00110000', unresolved: { count: 0, usd: '0.00000000' } } };
assert.equal(timeLeft(open.endsBy, now), '9:13');
assert.equal(timeLeft(open.endsBy, now + 600_000), '0:00');
assert.deepEqual({ ...stripWords(open, now) }, { running: 'Running', timeLeft: '9:13', left: 'left', spent: '$0.0011', of: 'of $0.05', stop: 'Stop' });
assert.equal(runningLine(open, now), '9:13 left · $0.0011 of $0.05');
assert.equal(runningLine(open, now, true), '9:13 left');
// Before the page has read the run's models, no money figure is said either.
assert.equal(runningLine(open, now, null), '9:13 left');
// The pill's run line (r09): who decides by J28's names, then the time left and the spending.
const teo = called({ name: 'Teo' }), ines = called({ name: 'Ines' }), someone = called({ name: null, kind: 'Resident' });
assert.equal(pillRunLine(open, now, [teo]), "Teo's model is deciding · 9:13 left · $0.0011 of $0.05");
assert.equal(pillRunLine(open, now, [teo], true), "Teo's model is deciding · 9:13 left");
assert.equal(pillRunLine(open, now, [], null), 'Running · 9:13 left');
// What the people's cards add up to (D9, DESIGN's fold-in): the pill says the same receipts at the cards' precision,
// "at least" as the cards do; with nothing known yet, what the run's bounds hold.
const cards = [{ subjectId: 'teo', decisions: 2, knownCostUsd: '0.00030000', costsUnknown: 0 }, { subjectId: 'ari', decisions: 3, knownCostUsd: '0.00050000', costsUnknown: 0 }];
assert.deepEqual(runSpent(cards), { usd: '0.00080000', unknown: false });
assert.equal(pillRunLine(open, now, [teo], false, runSpent(cards)), "Teo's model is deciding · 9:13 left · $0.0008 of $0.05");
assert.equal(runningLine(open, now, false, runSpent([{ ...cards[0], costsUnknown: 1 }])), '9:13 left · at least $0.0003 of $0.05');
assert.equal(runningLine(open, now, true, runSpent(cards)), '9:13 left', 'a free run says no money');
assert.equal(runSpent(null), null);
assert.equal(runningLine(open, now, false, runSpent(cards, true)), '9:13 left · at least $0.0008 of $0.05', 'a partial read says at least');
assert.equal(runSpent([{ ...cards[0], knownCostUsd: '0.00000000', costsUnknown: 1 }]), null, 'nothing known yet: the run figure stands');
assert.equal(runningLine(open, now, false, null), '9:13 left · $0.0011 of $0.05');
assert.equal(decidingWords([teo, ines]), "Teo's and Ines's models are deciding");
assert.equal(decidingWords([teo, ines, someone]), "Teo's, Ines's and the resident's models are deciding");
assert.equal(decidingWords([someone]), "The resident's model is deciding");
assert.equal(decidingWords([teo, ines, someone, teo]), '4 models are deciding');
assert.equal(decidingWords([]), 'Running');
assert.equal(spentWords({ used: { usd: '0.00120000', unresolved: { count: 1, usd: '0.00060000' } } }), '$0.0012, and up to $0.0006 not known yet');
assert.equal(endedNote({ closedReasonWords: 'The run played all its minutes.', used: { usd: '0.00420000', unresolved: { count: 0, usd: '0' } } }), 'The run played all its minutes. Spent $0.0042.');
assert.equal(endedNote({ closedReasonWords: 'The run was stopped.', used: { usd: '0', unresolved: { count: 0, usd: '0' } } }), 'The run was stopped. Spent $0.');

// Why a run stopped, on the day page: the server's sentence, except for its own time or the person's own Stop or pause.
const closedWords = Object.fromEntries([...python('exulanica/world/society_sessions.py')
  .split('SESSION_CLOSED_WORDS: Final[Mapping[str, str]] = {')[1].split('\n}')[0]
  .matchAll(/"([a-z_]+)": "([^"]+)"/g)].map(match => [match[1], match[2]]));
// DESIGN: its time (the wall clock or its minutes) and the person's own Stop or pause.
assert.deepEqual([...OWN_ENDS].sort(), ['paused_by_person', 'session_deadline', 'session_minutes', 'stopped_by_person']);
assert.ok(OWN_ENDS.every(reason => reason in closedWords), 'every own end is a reason the server can close with');
for (const [reason, words] of Object.entries(closedWords)) {
  const run = { state: 'closed', closedReason: reason, closedReasonWords: words };
  assert.equal(runStopWords(run), OWN_ENDS.includes(reason) ? null : words, reason);
}
assert.equal(runStopWords({ state: 'closed', closedReason: 'session_liability_unknown', closedReasonWords: closedWords.session_liability_unknown }),
  "The run stopped because a decision's cost is not known yet.");
assert.equal(runStopWords({ state: 'open', closedReason: null, closedReasonWords: null }), null);
assert.equal(runStopWords(null), null);

console.log('Run words checks passed: every refusal worded, one noun, the default run and the frames\' words.');
