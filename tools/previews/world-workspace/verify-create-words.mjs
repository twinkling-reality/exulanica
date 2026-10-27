import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import {
  NOTES_WORDS, aspectLabel, notesAskLine, notesFoot, sumUsd, webColumn, webNotesLabel, webTip,
  CREATE_WORDS, PROVIDER_NAMES, REFUSAL_BY_CODE, REFUSAL_WORDS, STEP_WORDS, budgetShort, cardSub, ceilingAmount, countWords, keyName, leftAmount, madeSpent, hostKeepsLine, priceLine,
  priceUp, priceUpTo, refusalSpent, refusalWords, setValue, spendLine, spentUpTo, startsLeftLine, stepTime, stoppedLine,
} from './create-words.mjs';

// Frame 20's words, as WORDS.md "Making a world" and N1 to N20 say them.
assert.equal(CREATE_WORDS.wordmark, 'exulanica');
assert.equal(CREATE_WORDS.title, 'Create a world');
assert.equal(CREATE_WORDS.describeIt, 'Describe it');
assert.equal(CREATE_WORDS.create, 'Create');
assert.equal(CREATE_WORDS.orStartFrom, 'Or start from');
assert.equal(CREATE_WORDS.noModelFree, 'No AI model · Free');
assert.equal(CREATE_WORDS.blank, 'Blank');
assert.equal(CREATE_WORDS.buildItYourself, 'Build it yourself · Free');
assert.equal(CREATE_WORDS.opensMyWorldAgain, 'Opens My world again · Free');
assert.equal(CREATE_WORDS.yourWorlds, 'Your worlds');
assert.equal(CREATE_WORDS.loading, 'Reading what you can make here…');
assert.equal(CREATE_WORDS.noModel, 'Making a world from your words needs an AI model, and none is connected here. You can still start from these:');
assert.equal(CREATE_WORDS.budgetSpent, 'The budget for AI models here is spent. You can still start from these:');
assert.equal(CREATE_WORDS.spendingPaused, 'Spending on AI models is paused here, so nothing can be made from your words now. You can still start from these:');
assert.equal(CREATE_WORDS.offline, 'Not connected to your world. Trying again.');
assert.equal(priceLine('0.20766720'), 'An open model makes it from your words: at most $0.21, and you see what it really spent.');
assert.equal(priceLine('0.00410000'), 'An open model makes it from your words: at most $0.01, and you see what it really spent.');
// What a newcomer can do with AI here, under the title, and who pays where the draft runs on the person's own key (C4).
assert.equal(CREATE_WORDS.peopleMoveIn, 'People move in, and you choose an open AI model to decide for any of them.');
assert.equal(priceLine('0.20766720', null, 'Nebius'), 'An open model makes it with your Nebius key: at most $0.21, and you see what it really spent.');
assert.equal(priceLine('0.20766720', '0.12', 'Nebius'), 'An open model makes it with your Nebius key: at most the $0.12 left for AI models here, and you see what it really spent.');
{
  const one = { providers: [{ provider: 'nebius_token_factory', ceiling_usd: '0.20766720' }] };
  assert.equal(PROVIDER_NAMES.nebius_token_factory, 'Nebius');
  assert.equal(keyName(true, one), 'Nebius');
  // A server's budget (a guest's), a provider the page cannot name, two providers or none: the line keeps its words.
  for (const [ownKey, document] of [[false, one], [undefined, one], [true, { providers: [{ provider: 'someone_else' }] }],
    [true, { providers: [...one.providers, { provider: 'ollama_local' }] }], [true, { providers: [] }], [true, null]]) {
    assert.equal(keyName(ownKey, document), null);
    assert.match(priceLine('0.20766720', null, keyName(ownKey, document)), /^An open model makes it from your words: /);
  }
}
// A1b: less than the whole left, the most is what is left (rounded down); the whole left or more, A1's line.
assert.equal(priceLine('0.20766720', '0.05'), 'An open model makes it from your words: at most the $0.05 left for AI models here, and you see what it really spent.');
assert.equal(priceLine('0.20766720', '0.0599'), priceLine('0.20766720', '0.05'));
assert.equal(priceLine('0.20766720', '0.20766720'), priceLine('0.20766720'));
assert.equal(priceLine('0.20766720', null), priceLine('0.20766720'));
assert.equal(hostKeepsLine('2026-12-15'), 'The worlds you make here and the words you type stay on this server until it is deleted after 15\u00a0December\u00a02026.');
// A5 is said on the guest gate now (ROOT, 27 October), from the app's own words: the same sentence, the day filled in.
{
  const app = readFileSync(new URL('../../../web/packages/app/src/ui/copy.ts', import.meta.url), 'utf8');
  const gate = /'gate\.hostKeepsUntil': '([^']*)'/u.exec(app)?.[1];
  assert.ok(gate, 'copy.ts says the host\'s day on the gate');
  assert.equal(gate.replace('{date}', '15\u00a0December\u00a02026'), hostKeepsLine('2026-12-15'));
}
assert.equal(hostKeepsLine('2027-01-03'), 'The worlds you make here and the words you type stay on this server until it is deleted after 3\u00a0January\u00a02027.');
for (const none of [undefined, null, '', '2026-13-01', '15/12/2026', '2026-12-15T00:00', 20261215]) assert.equal(hostKeepsLine(none), null, String(none));
assert.equal(countWords(86, 1000), '86 of 1000');
assert.equal(countWords(1000, 1000), '1000 of 1000');
assert.equal(countWords(0, 1000), null);
assert.equal(startsLeftLine(2), '2 more worlds can be started this hour.');
assert.equal(startsLeftLine(1), '1 more world can be started this hour.');
assert.equal(startsLeftLine(4), null);
assert.equal(startsLeftLine(0), null);
assert.equal(cardSub(null), 'No AI model · Free');
assert.equal(cardSub('0'), 'No AI model · Free');
assert.equal(cardSub('0.4'), 'At most $0.40');
// The placeholder is today's, read from the app's copy rather than retyped: a sentence that makes a world (WORLDLOOK,
// 2 of 2); the harbour sentence it replaced made none.
const copy = readFileSync(new URL('../../../web/packages/app/src/ui/copy.ts', import.meta.url), 'utf8');
assert.ok(copy.includes(`'worldSentence.placeholder': '${CREATE_WORDS.placeholder}'`), 'the placeholder is copy.ts\'s');
assert.equal(CREATE_WORDS.placeholder, 'A cozy little town by the sea at dusk');
assert.doesNotMatch(copy, /A harbour with fishing boats/u);

// The composer page's words (ROOT's mock of 27 October): the strip's kinds and arrows, the toggle and its details, the
// price in the composer's foot and what was spent under the making view's steps.
assert.equal(CREATE_WORDS.readyWorld, 'READY WORLD');
assert.equal(CREATE_WORDS.empty, 'EMPTY');
assert.deepEqual([CREATE_WORDS.previous, CREATE_WORDS.next], ['Previous', 'Next']);
assert.equal(NOTES_WORDS.toggle, 'Search the web');
assert.equal(priceUpTo('0.2577'), 'up to $0.26');
assert.equal(priceUpTo('0.20766720', '0.05'), 'up to $0.05');
assert.equal(priceUpTo('0.20766720', '0.0599'), 'up to $0.05');
assert.equal(priceUpTo('0.20766720', '0.20766720'), 'up to $0.21');
assert.equal(priceUpTo('0.20766720', null), 'up to $0.21');
assert.equal(priceUpTo('0.20766720', '0.00428'), 'up to $0.0042');
assert.equal(spentUpTo({ spentUsd: 0.0061 }, '0.2577'), 'Spent $0.0061 of up to $0.26');
assert.equal(spentUpTo({ spentUsd: 0.12, unknownUsd: 0.03 }, '1.43'), 'Spent $0.12 of up to $1.43, and up to $0.03 not known yet');
assert.equal(spentUpTo({ spentUsd: 0 }, '0.26'), 'Spent $0 of up to $0.26');
assert.equal(webTip(3, '0.0453'), 'Looks up what such a place looks like before it is made: up to 3 searches with Tavily, which keeps them. Adds at most $0.05.');
assert.equal(webTip(1, '0.01'), 'Looks up what such a place looks like before it is made: up to 1 search with Tavily, which keeps it. Adds at most $0.01.');
assert.equal(webNotesLabel(3), 'FROM THE WEB, 3 SEARCHES');
assert.equal(webNotesLabel(1), 'FROM THE WEB, 1 SEARCH');
for (const none of [0, null, undefined, 1.5]) assert.equal(webNotesLabel(none), 'FROM THE WEB', String(none));

// Frame 21's and 22's words.
assert.equal(CREATE_WORDS.creating, 'Creating your world');
assert.deepEqual({ ...STEP_WORDS }, { queued: 'Waiting to start', choosing: 'Worked out what to make', drafting: 'Planning the place', making: 'Building it', land: 'Drawing its land' });
assert.equal(CREATE_WORDS.leave, 'You can leave this page. It carries on, and it waits in Your worlds.');
assert.equal(CREATE_WORDS.beingMade, 'Being made…');
assert.equal(spendLine({ spentUsd: 0.12 }, '1.43'), 'Spent $0.12 of at most $1.43');
assert.equal(spendLine({ spentUsd: 0.12, unknownUsd: 0.03 }, '1.43'), 'Spent $0.12 of at most $1.43, and up to $0.03 not known yet');
assert.equal(CREATE_WORDS.madeFromYourWords, 'Made from your words');
assert.deepEqual([CREATE_WORDS.inIt, CREATE_WORDS.set, CREATE_WORDS.notInItYet, CREATE_WORDS.spent], ['In it', 'Set', 'Not in it yet', 'Spent']);
assert.equal(madeSpent({ spentUsd: 0.31 }, '1.4227'), '$0.31 of at most $1.43');

// Money (rule 5): a limit rounded up to the cent; under a cent four places; "less than $0.0001"; "$0".
assert.equal(ceilingAmount('1.43'), '$1.43');
assert.equal(ceilingAmount('1.4300001'), '$1.44');
// N31, A1b: what one step could cost against what is left, each served figure in the money format (the step up, the left down).
assert.equal(budgetShort('0.0344064', '0.01'),
  'Making a world from your words can cost up to $0.04 a step, more than the $0.01 left for AI models here. You can still start from these:');
assert.equal(budgetShort('0.0344064', '0.019'), budgetShort('0.0344064', '0.01'));
// Under a cent left: P1's four places rounded down, never "$0" while something is left.
assert.equal(leftAmount('0.00428'), '$0.0042');
assert.equal(leftAmount('0.0099999'), '$0.0099');
assert.equal(leftAmount('0.01'), '$0.01');
assert.equal(leftAmount('0.00004'), 'less than $0.0001');
assert.equal(leftAmount('0.00009'), 'less than $0.0001');
assert.equal(leftAmount('0'), '$0');
assert.equal(budgetShort('0.0344064', '0.00428'),
  'Making a world from your words can cost up to $0.04 a step, more than the $0.0042 left for AI models here. You can still start from these:');
// Below a ten-thousandth the sentence turns rather than say "more than the less than".
assert.equal(budgetShort('0.0344064', '0.00004'),
  'Making a world from your words can cost up to $0.04 a step, and less than $0.0001 is left for AI models here. You can still start from these:');
// A1b: a draft stopped part way, from its refusal's served figures: the step it could not hold, what was left, what it spent.
const bound = { reason: 'spending_limit_reached', scope: 'workspace', detail: 'usd', limit: '0.03440640', committed: '0.02583680', requested: '0.03440640' };
assert.equal(stoppedLine(bound, { spentUsd: 0.0058368 }),
  'Making stopped part way: its next step could cost up to $0.04, more than the $0.0085 left for AI models here. No world was made, and it spent $0.0058.');
assert.equal(stoppedLine({ ...bound, committed: '0.0244064' }, { spentUsd: 0.0058368 }),
  'Making stopped part way: its next step could cost up to $0.04, more than the $0.01 left for AI models here. No world was made, and it spent $0.0058.');
assert.equal(stoppedLine({ ...bound, committed: '0.03440639' }, { spentUsd: 0.03, unknownUsd: 0.004 }),
  'Making stopped part way: its next step could cost up to $0.04, and less than $0.0001 is left for AI models here. No world was made, and it spent $0.03, and up to $0.004 not known yet.');
// Any other refusal, or one that states no figures, says "The budget for AI models here is spent." and what was spent.
assert.equal(stoppedLine({ reason: 'not_granted', retry: 'never' }, { spentUsd: 0.01 }), null);
assert.equal(stoppedLine({ reason: 'spending_limit_reached', retry: 'never' }, { spentUsd: 0.01 }), null);
assert.equal(stoppedLine(null, { spentUsd: 0.01 }), null);
// N32: a higher price is said with its new figure; the same or a lower one is never said at all.
assert.equal(priceUp(ceilingAmount('1.6')), 'The price went up before it started. It can now spend at most $1.60.');
assert.equal(madeSpent({ spentUsd: 0.0042 }, '1.43'), '$0.0042 of at most $1.43');
assert.equal(madeSpent({ spentUsd: 0.00001 }, '1.43'), 'less than $0.0001 of at most $1.43');
assert.equal(madeSpent({ spentUsd: 0 }, '1.43'), '$0 of at most $1.43');

// Times (N11).
assert.equal(stepTime(1), '1 s');
assert.equal(stepTime(12), '12 s');
assert.equal(stepTime(59), '59 s');
assert.equal(stepTime(64), '1 min 4 s');
assert.equal(stepTime(120), '2 min');
assert.equal(stepTime(Number.NaN), '');

// Refusals (build sheet section 3, N8, N9, N15): each code to its sentence, an unknown code to the last.
const sentences = {
  world_not_a_place: 'These words don’t describe a place, so no world could be made from them. Try a place and what is in it.',
  world_draft_model_failed: 'The AI model didn’t answer, so nothing was made. Try again in a minute.',
  kind_draft_model_failed: 'The AI model didn’t answer, so nothing was made. Try again in a minute.',
  world_limit_reached: 'You have as many worlds as one person can keep. Remove one in Your worlds to make another.',
  world_draft_price_expired: 'The price changed before it started. Here is the new most it can spend.',
  world_draft_operation_changed: 'The price changed before it started. Here is the new most it can spend.',
  world_draft_bound_too_small: 'The price changed before it started. Here is the new most it can spend.',
  world_draft_failed: 'Something went wrong while making it, so nothing was made. Try again.',
  kind_draft_failed: 'Something went wrong while making it, so nothing was made. Try again.',
  kind_work_unavailable: 'Something went wrong while making it, so nothing was made. Try again.',
  kind_draft_limit: 'You’ve started as many worlds as you can this hour. Try again later.',
  kind_draft_busy: 'A world is being made already. It waits in Your worlds when it’s done.',
  kind_draft_capacity: 'This computer is busy making other worlds. Try again in a few minutes.',
  budget_exceeded: 'The budget for AI models here is spent.',
  spending_suspended: 'Spending on AI models is paused here, so nothing was made.',
  world_draft_unanswered: 'The AI model took too long, so nothing was made. Try again.',
  world_draft_interrupted: 'Making stopped part way, so nothing was kept. Try again.',
  // A kind's draft the model could not make from the words, as a world's (REHEARSAL run 3, beat 1's village).
  kind_not_drafted: 'No world could be made from these words. Try again, or say it another way.',
  // A kind's draft whose reply ran on until the call's token ceiling cut it (DESIGN 11:35 on 26 October).
  kind_draft_ran_on: 'The AI model’s answer ran on too long to use, so nothing was made. Try again, or say it another way.',
};
for (const [code, sentence] of Object.entries(sentences)) assert.equal(refusalWords(code), sentence, code);
for (const unknown of ['no_such_code', null, undefined, 42]) {
  assert.equal(refusalWords(unknown), REFUSAL_WORDS.failed, String(unknown));
}
for (const key of Object.values(REFUSAL_BY_CODE)) assert.ok(Object.hasOwn(REFUSAL_WORDS, key), key);
assert.equal(refusalSpent({ spentUsd: 0.02 }), 'Spent $0.02 before it stopped.');
assert.equal(refusalSpent({ spentUsd: 0 }), null);

// The Set value (TERRAIN's WORDING.md without its "Set", N13): the five cases.
const coast = 'on a coast, with a beach below and a terraced hill behind';
// N26: each starts with a capital; a setting is its titles, then the land, then the words.
assert.equal(setValue({ title: 'on gentle hills, with mountains far off', chosen_by: 'default', words: [], fell_back: false }), 'On gentle hills, with mountains far off');
assert.equal(setValue({ title: 'in a valley between two long ridges', chosen_by: 'words', words: ['valley'], fell_back: false }), 'In a valley between two long ridges, for your words “valley”');
assert.equal(setValue({ title: coast, chosen_by: 'setting', words: [], fell_back: false }, { parts: [{ axis: 'ground', key: 'sea', title: 'By the sea' }], words: ['by the sea'] }),
  `By the sea, ${coast}, for your words “by the sea”`);
assert.equal(setValue({ title: coast, chosen_by: 'setting', words: [], fell_back: false }, { parts: [{ title: 'Night' }, { title: 'By the sea' }], words: ['at night', 'by the sea'] }),
  `Night, by the sea, ${coast}, for your words “at night”, “by the sea”`);
assert.equal(setValue({ title: coast, chosen_by: 'words', words: ['coast'], fell_back: true }), `On level ground, since this place did not fit the land ${coast}`);
// N25's sentences and codes.
assert.equal(CREATE_WORDS.notOffered, 'Making a world from your words isn’t offered here. You can still start from these:');
assert.equal(refusalWords('world_draft_price_unavailable'), 'The price can’t be read right now. Trying again.');
assert.equal(refusalWords('tile_budget_reached'), 'You’ve reached today’s limit for new worlds. Try again tomorrow.');
assert.equal(refusalWords('world_not_drafted'), 'No world could be made from these words. Try again, or say it another way.');
assert.equal(setValue(null), null);

// Never on screen: a code, "US$", "provider", "session", an em dash; no line ends in the old "Design" line.
const said = [
  ...Object.values(CREATE_WORDS), ...Object.values(STEP_WORDS), ...Object.values(REFUSAL_WORDS),
  priceLine('1.43'), priceLine('1.43', '0.05'), priceUp('$1.60'), budgetShort('0.0344', '0.01'), spendLine({ spentUsd: 0.12, unknownUsd: 0.03 }, '1.43'), startsLeftLine(2),
  refusalSpent({ spentUsd: 0.02 }), stoppedLine(bound, { spentUsd: 0.0058368 }),
  priceUpTo('1.43', '0.05'), spentUpTo({ spentUsd: 0.12, unknownUsd: 0.03 }, '1.43'), webTip(3, '0.05'), webNotesLabel(3),
  setValue({ title: coast, chosen_by: 'setting', words: [], fell_back: false }, { parts: [{ title: 'By the sea' }], words: ['by the sea'] }),
];
for (const line of said) {
  assert.doesNotMatch(line, /\u2014|US\$|provider|session|[a-z]+_[a-z_]+|Design\./u, line);
}
for (const file of ['create-words.mjs', 'create-steps.mjs', 'world-ui-create.ts', 'world-ui-create.css', 'create-world.ts', 'create-world.css', 'verify-create-steps.mjs']) {
  assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /\u2014/u, file);
}

// The light plane's stylesheet: its inks once (N9, N16), more contrast's faint, every size through
// --u, and text under 16 px never below 12 px (a key cap's glyph 9 px, L5).
const css = readFileSync(new URL('world-ui-create.css', import.meta.url), 'utf8');
for (const token of ['--l-ink: #121715', '--l-muted: #344750', '--l-faint: #5b6b72', '--refused-ink-light: #8f2f25', '--l-faint: #3d4a50']) {
  assert.equal(css.split(token).length - 1, 1, token);
}
for (const query of ['prefers-reduced-motion: reduce', 'prefers-reduced-transparency: reduce', 'prefers-contrast: more']) assert.ok(css.includes(query), query);
for (const [, size] of css.matchAll(/(?:font:\s*\d+\s+|font-size:\s*)calc\((\d+(?:\.\d+)?) \* var\(--u\)\)/gu)) {
  assert.ok(Number(size) >= 16, `a ${size} px text scales below 12 px; wrap it in max(12px, ...)`);
}
assert.match(css, /\.wu-qcmd-key \{[^}]*font: 400 max\(9px, calc\(10 \* var\(--u\)\)\)/u);
assert.doesNotMatch(css, /font:\s*\d+\s+\d+(?:\.\d+)?px/u, 'a fixed font size');

// The composer page's stylesheet (create-world.css): the mock's inks, column edge and curve once, in the mock's own
// pixels rather than --u; motion only at 160 ms and 500 ms; less motion, less transparency and forced colours honoured.
const page = readFileSync(new URL('create-world.css', import.meta.url), 'utf8');
for (const token of ['--c-ink-2: rgb(255 255 255 / 72%)', '--c-ink-3: rgb(255 255 255 / 48%)', '--c-col: clamp(48px, 24.5vw, 470px)', '--c-ease: cubic-bezier(.25, .46, .45, .94)']) {
  assert.equal(page.split(token).length - 1, 1, token);
}
for (const query of ['prefers-reduced-motion: reduce', 'prefers-reduced-transparency: reduce', 'forced-colors: active']) assert.ok(page.includes(query), query);
assert.match(page, /\.wu-strip-card \{[^}]*transition: width 500ms var\(--c-ease\)/u);
assert.match(page, /\.wu-strip-card\[aria-current="true"\] \{ width: 200px; \}/u);
assert.doesNotMatch(page, /var\(--u\)/u, 'the mock\'s pixels, never the --u scale');
for (const [, ms] of page.matchAll(/(\d+)ms/gu)) assert.ok(['160', '500'].includes(ms), `a ${ms} ms motion`);
assert.doesNotMatch(page, /\btitle=|text-transform/u);
// L5 on the composer page too: no words, chips, counts or lines under 12 px (the mock's 10.5 px mono labels among
// them, ROOT 27 October); only a key cap's glyph may be smaller, down to 9 px.
for (const [, selector, body] of page.matchAll(/([^{}]+)\{([^{}]*)\}/gu)) {
  for (const [, size] of body.matchAll(/(?:font:\s*\d+\s+|font-size:\s*)(\d+(?:\.\d+)?)px/gu)) {
    const floor = /wu-composer-key|wu-qcmd-key/u.test(selector) ? 9 : 12;
    assert.ok(Number(size) >= floor, `${selector.trim()}: ${size} px is under the ${floor} px floor (L5)`);
  }
}

// With WORDS_MD naming DESIGN's word list (kept outside the repository), each phrase here is in it.
const words = process.env.WORDS_MD;
if (words && existsSync(words)) {
  const text = readFileSync(words, 'utf8').replace(/\s+/gu, ' ');
  for (const line of [CREATE_WORDS.title, CREATE_WORDS.describeIt, CREATE_WORDS.orStartFrom, CREATE_WORDS.buildItYourself, CREATE_WORDS.loading,
    CREATE_WORDS.noModel, CREATE_WORDS.budgetSpent, CREATE_WORDS.leave, CREATE_WORDS.madeFromYourWords, CREATE_WORDS.notInItYet,
    STEP_WORDS.queued, STEP_WORDS.choosing, STEP_WORDS.drafting, STEP_WORDS.making, STEP_WORDS.land,
    REFUSAL_WORDS.hourlyLimit.replace('’', "'"), REFUSAL_WORDS.capacity, REFUSAL_WORDS.tooSlow, REFUSAL_WORDS.interrupted, REFUSAL_WORDS.failed,
    spendLine({ spentUsd: 0.12 }, '0.21'), '2 more worlds can be started this hour.', 'Spent $0.02 before it stopped.',
    priceLine('0.2077', '0.05'), budgetShort('0.0344', '0.01'), stoppedLine({ ...bound, committed: '0.0244064' }, { spentUsd: 0.0058368 })]) {
    assert.ok(text.includes(line) || text.includes(line.replaceAll('’', "'")), `WORDS.md says: ${line}`);
  }
}

export default true;

// Web notes in Create, DESIGN's words of 11:55 on 25 October (WORDS.md "Web notes in Create, the words").
assert.equal(NOTES_WORDS.ask, 'Read the web first for what such a place looks like');
assert.equal(notesAskLine(3, '0.0153'), 'Up to 3 web searches go to Tavily, made from your words with the names and details this install holds as yours left out, and Tavily keeps them. Adds at most $0.02.');
assert.deepEqual(NOTES_WORDS.steps, { plan: 'Choosing what to look up', search: 'Searching the web', read: 'Writing notes from what it found' });
assert.equal(notesFoot(3), 'A model wrote these from 3 web searches. They help plan the place and are never facts about it.');
assert.equal(NOTES_WORDS.notMade, 'The web notes could not be made, so it is made from your words alone.');
assert.equal(NOTES_WORDS.nothingFound, 'The searches found nothing to use, so it is made from your words alone.');
assert.equal(NOTES_WORDS.notReached, 'This kind of place is made from your words alone, so the notes were not used.');
assert.equal(CREATE_WORDS.fromTheWeb, 'From the web');
assert.equal(webColumn(7, 3), '7 notes from 3 searches');
assert.equal(webColumn(1, 1), '1 note from 1 search');
// Each note's aspect by the aspect catalog's label, never a key the page names.
assert.equal(aspectLabel('landscape_and_plants'), 'Landscape and plants');
assert.equal(sumUsd('0.20766720', '0.0153'), '0.22296720');
