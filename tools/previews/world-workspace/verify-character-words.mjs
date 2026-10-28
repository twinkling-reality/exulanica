import assert from 'node:assert/strict';
import { checkingLine, notAbleFold, notAbleLine, overLine, runnerCalls, runnerOpen } from './character-words.mjs';
import { declaredParts, deciderWords, decidesPrint, runSectionLine, CHARACTER_WORDS, amount, askWho, called, chosenLine, goneNote, lastRunLine, modelLine, modelRefusalWords, modelsNamed, money, nothingYet, outOfViewNote, recordFailed, pageSub, possessive, priceWords, readingRecord, routineBetween, routineRow, rowSub, whatDid, rowPrice, providerName, keyGroup, makerLine, cardWords } from './character-words.mjs';

// A character is called by its name, or by its kind, never "it", "he" or "she" (WORDS.md rule 10).
const teo = called({ name: 'Teo' }), resident = called({ name: '  ', kind: 'Resident' }), someone = called({ name: null }), bench = called({ name: null, being: false });
assert.deepEqual({ ...teo }, { title: 'Teo', start: 'Teo', within: 'Teo', named: true });
assert.deepEqual({ ...resident }, { title: 'Resident', start: 'The resident', within: 'the resident', named: false });
assert.equal(someone.title, 'Character');
assert.equal(bench.title, 'Thing');
assert.equal(possessive('Teo'), "Teo's");
assert.equal(possessive("the resident"), "the resident's");

// Frame 05's line: the model's choice with its time and count, or the routine.
assert.equal(chosenLine(teo, { hhmm: '07:09', options: 7 }), "Teo's model chose this at 07:09, from 7 choices.");
assert.equal(chosenLine(teo, { hhmm: '07:09', options: 1 }), "Teo's model chose this at 07:09, from 1 choice.");
assert.equal(chosenLine(teo, { hhmm: '07:09', options: null }), "Teo's model chose this at 07:09.");
assert.equal(chosenLine(teo, null), "Teo's routine.");
assert.equal(chosenLine(resident, null), "The resident's routine.");
assert.equal(readingRecord(teo), "Reading Teo's record…");
// The day page's Q key names the person as the card's keys do, by name or by kind.
assert.equal(askWho(teo), 'Ask Teo');
assert.equal(askWho(called({ name: null, kind: 'resident' })), 'Ask the resident');
assert.equal(goneNote(teo), 'Teo is no longer in this world.');
assert.equal(outOfViewNote(resident), 'The resident went out of view, so following stopped.');

// Frames 06 and 07.
assert.equal(pageSub('resident', 'Terraces on the bay'), 'Resident · Terraces on the bay');
assert.equal(pageSub(null, 'Terraces on the bay'), 'Terraces on the bay');
assert.equal(whatDid(teo), 'Activity');
assert.equal(nothingYet(teo), 'Teo has not done anything yet.');
// A read that failed says so, never that nothing was done (ROOT's sweep of 27 October).
assert.equal(recordFailed(teo), "Teo's record could not be read. Try again.");
assert.equal(recordFailed(called({ kind: 'resident' })), "The resident's record could not be read. Try again.");
assert.equal(rowSub({ model: 'Nemotron 3 Nano 30B', options: 7 }), 'Nemotron 3 Nano 30B · 7 choices');
assert.equal(rowSub(null), 'Routine');
assert.equal(routineBetween('Nemotron 3 Super 120B'), "Routine, between Nemotron 3 Super 120B's choices");
assert.equal(lastRunLine({ from: '06:00', to: '07:15', decisions: 12, spent: '0.00420000' }), 'Last run 06:00 to 07:15 · 12 decisions · spent $0.0042');
assert.equal(lastRunLine({ from: '06:00', to: '06:10', decisions: 1, spent: '0' }), 'Last run 06:00 to 06:10 · 1 decision · spent $0');

// Money (WORDS.md rule 5 and DESIGN's K8): "Free" only for a price; "$0" for nothing spent.
assert.equal(amount('0.05000000'), '$0.05');
assert.equal(amount('1'), '$1.00');
assert.equal(amount('0.00420000'), '$0.0042');
assert.equal(amount('0.00001800'), 'less than $0.0001');
assert.equal(amount('0'), '$0');
assert.equal(money('0'), 'Free');
assert.equal(priceWords({ price: { input: '0.06', output: '0.24' } }), '$0.06 in · $0.24 out');
assert.equal(priceWords({ price: { input: '0.3', output: '0.9' } }), '$0.30 in · $0.90 out');
assert.equal(priceWords({ price: { input: '0', output: '0.00' } }), 'Free');
assert.equal(priceWords({ price: null }), null);
// A model its provider serves from this computer (the read's on_this_computer), DESIGN's J11.
assert.equal(priceWords({ price: { input: '0', output: '0' }, local: true }), 'On this computer · Free');
// The chooser as a gallery that teaches (A3): a row's price ("Free" where its group says this computer), the key group
// by the provider's own name, a model's maker and size, and its maker's own words with their source and the licence.
assert.equal(rowPrice({ price: { input: '0', output: '0' }, local: true }), 'Free');
assert.equal(rowPrice({ price: { input: '0.3', output: '0.9' } }), '$0.30 in · $0.90 out');
assert.equal(rowPrice({ price: null }), '');
assert.equal(providerName({ provider: 'nebius_token_factory', providerDescription: 'Nebius Token Factory, which serves open models.' }), 'Nebius Token Factory');
assert.equal(providerName({ provider: 'nebius_token_factory' }), 'nebius_token_factory', 'no description: the provider\'s key');
assert.equal(keyGroup('Nebius Token Factory'), 'With your Nebius Token Factory key, per million tokens');
assert.equal(CHARACTER_WORDS.hereFree, 'Local Models (Free)');
assert.equal(CHARACTER_WORDS.serverBudget, "From this server's budget, per million tokens");
const nemotron = { maker: 'NVIDIA', parameters: { total: '120B', active: '12B' }, licence: 'NVIDIA Nemotron Open Model License', says: 'This model is optimized for collaborative agents and high-volume workloads.' };
assert.equal(makerLine({ card: nemotron }), 'NVIDIA · 120B');
assert.equal(makerLine({ card: { ...nemotron, maker: 'DeepSeek', parameters: null } }), 'DeepSeek');
assert.equal(makerLine({ card: { ...nemotron, maker: 'Qwen', parameters: { total: '4.0B', active: null } } }), 'Qwen · 4B', 'the size as a name writes it');
assert.equal(makerLine({ card: { ...nemotron, parameters: { total: '3.5B', active: null } } }), 'NVIDIA · 3.5B');
assert.equal(makerLine({ card: null }), null);
assert.deepEqual(cardWords({ card: nemotron }), { said: '\u201cThis model is optimized for collaborative agents and high-volume workloads.\u201d', from: "from NVIDIA's model card · NVIDIA Nemotron Open Model License" });
assert.equal(cardWords({}), null);
// Never a word that sets one model against another (A3 item 5) in the product's own words of the gallery.
for (const words of [CHARACTER_WORDS.hereFree, CHARACTER_WORDS.serverBudget, keyGroup('Nebius Token Factory')]) {
  assert.doesNotMatch(words, /\b(best|better|fastest|faster|top|rank|score|cheapest|smartest)\b/iu, words);
}
assert.equal(modelLine({ price: { input: '0', output: '0' }, local: true }), 'On this computer · Free');
assert.equal(modelLine({ price: { input: '0.06', output: '0.24' } }), '$0.06 in · $0.24 out per million tokens');
assert.equal(modelLine(null), 'No AI model · Free');
assert.equal(routineRow(), 'No AI model · Free');

assert.equal(modelRefusalWords('stale', teo), 'Teo changed a moment ago. Look again and choose once more.');
assert.equal(modelRefusalWords('choice_key_reused', teo), 'Teo changed a moment ago. Look again and choose once more.');
assert.equal(modelRefusalWords('person_not_in_this_world', teo), 'Teo is no longer in this world.');
assert.equal(modelRefusalWords('decider_not_allowed', teo), 'This model cannot decide for Teo here.');

// Sentence case, no codes, no em dash, never "it", "entity", "session" or "provider" for a character.
const said = [...Object.values(CHARACTER_WORDS), chosenLine(teo, null), readingRecord(teo), goneNote(teo), nothingYet(teo), whatDid(teo)];
for (const words of said) {
  assert.doesNotMatch(words, /_|\u2014|entity|session|provider/i, words);
  assert.doesNotMatch(words, /\b(he|she)\b/i, words);
}
// Why a character's model does not run (J2, J22): the cause the models read states, asking for
// nothing the page cannot do.
const open = [{ refusal: null }, { refusal: 'model_no_longer_offered' }];
// No model chosen: who decides, and no how-to (ROOT's sweep of 27 October).
assert.equal(runSectionLine(teo, { offered: open }), 'Teo follows a routine.');
assert.equal(runSectionLine(resident, { offered: open }), 'The resident follows a routine.');
assert.equal(runSectionLine(teo, { offered: open, chosen: true }), null, 'a chosen model that may be asked runs');
for (const unasked of [{ hostRefusal: 'provider_credential_absent', offered: open }, { hostRefusal: 'models_not_run_here', offered: open },
  { offered: [{ refusal: 'provider_not_admitted' }], chosen: true, chosenRefusal: 'provider_not_admitted' }, { offered: [] }]) {
  assert.equal(runSectionLine(resident, { ...unasked }), 'No AI model is connected here, so the resident follows a routine.');
}
for (const spent of [{ hostRefusal: 'process_budget_spent', offered: open }, { offered: open, chosen: true, chosenRefusal: 'process_share_spent' },
  { offered: [{ refusal: 'process_budget_spent' }, { refusal: 'process_share_spent' }] }]) {
  assert.equal(runSectionLine(teo, { ...spent }), 'The budget for AI models here is spent, so Teo follows a routine.');
}
// A2: the only models offered run on this computer and none runs now: say so.
assert.equal(runSectionLine(teo, { offered: [{ refusal: 'provider_credential_absent' }, { refusal: 'provider_not_running' }] }),
  'No AI model is running on this computer yet, so Teo follows a routine.');
assert.equal(runSectionLine(teo, { hostRefusal: 'models_not_run_here', offered: [{ refusal: 'provider_not_running' }] }),
  'No AI model is connected here, so Teo follows a routine.', 'a host that asks no model says so first');
assert.equal(runSectionLine(teo, { offered: [{ refusal: 'process_budget_spent' }, { refusal: 'provider_not_running' }] }),
  'No AI model is connected here, so Teo follows a routine.', 'a key whose models are spent: never the line about this computer');
// N34: spending held closed until an operator acts is paused, not spent and not a missing model.
assert.equal(runSectionLine(teo, { hostRefusal: 'spending_suspended', offered: open }),
  'Spending on AI models is paused here, so Teo follows a routine.');
assert.equal(runSectionLine(teo, { hostRefusal: 'spending_suspended', offered: open, chosen: true, chosenRefusal: 'process_share_spent' }),
  'The budget for AI models here is spent, so Teo follows a routine.', 'a spent budget wins');
assert.equal(runSectionLine(teo, { offered: open, chosen: true, chosenRefusal: 'provider_changed' }),
  'This model cannot decide for Teo here, so Teo follows a routine.');
assert.equal(runSectionLine(resident, { offered: open, chosen: true, chosenRefusal: 'model_no_longer_offered' }),
  'This model cannot decide for the resident here, so the resident follows a routine.');
// T7: where a person playing or an outside program decides, the chip, the row and the card say so.
assert.equal(deciderWords('person'), 'A person playing');
assert.equal(deciderWords('external'), 'An outside program');
assert.equal(deciderWords('model'), null);
assert.equal(chosenLine(teo, null, 'person'), 'A person chose this.');
assert.equal(chosenLine(teo, null, 'external'), 'An outside program chose this.');
assert.equal(chosenLine(teo, null), "Teo's routine.");
assert.equal(rowSub({ decider: 'person' }), 'A person playing');
assert.equal(rowSub({ decider: 'external' }), 'An outside program');
assert.equal(rowSub({ decider: 'model' }), 'Routine', 'a model with no name read is no decider word');
// The models a run asks (DESIGN's aha 20): one by its name, two joined with "and", more the first and how many others.
assert.equal(modelsNamed(['Nemotron 3 Nano 30B']), 'Nemotron 3 Nano 30B');
assert.equal(modelsNamed(['Nemotron 3 Nano 30B', 'Qwen3 235B Instruct']), 'Nemotron 3 Nano 30B and Qwen3 235B Instruct');
assert.equal(modelsNamed(['Nemotron 3 Nano 30B', 'Qwen3 235B Instruct', 'Nemotron 3 Super 120B']), 'Nemotron 3 Nano 30B and 2 other models');
assert.equal(modelsNamed(['A', 'B', 'A', ' B ', null, '']), 'A and B', 'each model once, however many people it decides for');
assert.equal(modelsNamed([]), null);
// A person's runner's models (L1, DESIGN's words): being checked, not able and why from the check's own numbers, the
// name a runner calls one where another row reads the same, and the licence the runner states, quoted.
const qwen = { name: 'Qwen3 · 4.0B', servedAs: 'qwen3:4b-instruct:latest', contextTokens: 4096, deadlineMs: 20000 };
assert.equal(checkingLine(qwen), 'Qwen3 · 4.0B · Checking that it can decide for a person here…');
assert.equal(CHARACTER_WORDS.notAbleHere, 'Also on this computer, not able to decide for a person here');
assert.equal(notAbleLine({ ...qwen, reason: 'context' }), 'It reads at most 4,096 tokens at once, less than a person is told here.');
assert.equal(notAbleLine({ ...qwen, reason: 'form' }), 'It did not answer with one of the offered choices when checked.');
assert.equal(notAbleLine({ ...qwen, reason: 'slow' }), 'It took longer than the 20 seconds a person has to decide.');
assert.equal(notAbleLine({ ...qwen, reason: 'text' }), 'It does not read text.');
assert.equal(notAbleLine({ ...qwen, reason: 'error' }), 'It could not be checked here.');
assert.equal(runnerCalls(qwen), 'Your runner calls it qwen3:4b-instruct');
// Its open row (DESIGN 11:22): what its check found, its slowest case in tenths of a second, then the licence the
// runner states, quoted and cut to 80 characters; with no licence the check's line opens alone.
assert.deepEqual(runnerOpen({ runner: { licence: 'AN INVENTED LICENSE', checkedMs: 2104 } }), {
  said: 'Checked on this computer: it chose one of the offered choices in 2.1 s.', from: 'from your runner · \u201cAN INVENTED LICENSE\u201d',
});
assert.deepEqual(runnerOpen({ runner: { licence: null, checkedMs: 238 } }), { said: 'Checked on this computer: it chose one of the offered choices in 0.2 s.', from: null });
const longLicence = runnerOpen({ runner: { licence: 'L'.repeat(120), checkedMs: 238 } }).from;
assert.equal(longLicence, `from your runner · \u201c${'L'.repeat(79)}\u2026\u201d`, 'at most 80 characters of the licence');
assert.equal(runnerOpen({ runner: { licence: null, checkedMs: null } }), null, 'nothing known: nothing opens');
// The world's list folds the not-able rows (DESIGN 11:58).
assert.equal(notAbleFold(4), 'And 4 more on this computer that cannot decide for a person here.');
// A guest's faint row (U2, DESIGN 12:20): one attempt's most and what is left, each to the figure that tells them apart.
assert.equal(overLine('0.04300000', '0.03000000'), 'Asking it once can cost up to $0.043, more than the $0.03 left for AI models here.');
assert.equal(overLine('0.01290000', '0.01250000'), 'Asking it once can cost up to $0.0129, more than the $0.0125 left for AI models here.');
// What is left that rounds to nothing is not shown as $0 (U3b, DESIGN 15:58).
assert.equal(overLine('0.00270000', '0.00000200'), 'Asking it once can cost up to $0.0027, more than is left for AI models here.');
assert.equal(overLine('0.00270000', '0'), 'Asking it once can cost up to $0.0027, more than is left for AI models here.');
// An outside AI agent (AG1d): named as what it is where a model's name stands; its print and chosen line; its own
// words only where declared; what it costs this world.
assert.equal(deciderWords('agent'), 'An outside AI agent');
assert.equal(deciderWords('external'), 'An outside program', "a game's program keeps its words");
assert.equal(decidesPrint(called({ name: null, kind: 'visitor' }), { decider: 'agent' }), 'An outside AI agent decides for the visitor.');
assert.equal(chosenLine(called({ name: 'Teo' }), null, 'agent'), 'An outside AI agent chose this.');
assert.equal(rowSub({ decider: 'agent' }), 'An outside AI agent');
assert.equal(CHARACTER_WORDS.costsNothing, 'It costs this world nothing.');
assert.equal(declaredParts({ name: 'Scout', maker: 'Harbour Lab', mind: null }).map(part => part.words).join(''), 'In its own words: Scout, made by Harbour Lab.');
assert.equal(declaredParts({ name: '  ', maker: 'Harbour Lab', mind: 'x' }), null, 'no name, no line');
console.log('Character words checks passed: names and kinds, the chosen line, the page lines, money and the model list.');
