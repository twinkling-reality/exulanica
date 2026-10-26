// The words of a character's moments in the world: looking at a character, choosing one, its page
// and choosing its model (DESIGN's frames 04 to 07 and WORDS.md). The page draws them; what a run
// says is run-words.mjs, a personality personality-words.mjs. verify-character-words.mjs holds them.

export const CHARACTER_WORDS = Object.freeze({
  inspect: 'Inspect',
  details: 'Details',
  run: 'Run',
  stop: 'Stop',
  follow: 'Follow',
  stopFollowing: 'Stop following',
  back: 'Back',
  model: 'Model',
  personality: 'Personality',
  writtenByYou: 'Written by you',
  noPersonality: 'No personality yet.',
  routine: 'Routine',
  /** Who decides where a model does not (T7): the chip on the card and tag, and a row's sub-line. */
  personPlaying: 'A person playing',
  outsideProgram: 'An outside program',
  /** An outside AI agent at the door (AG1d, DESIGN 18:07): where a model's name stands, it is named as what it is. */
  outsideAgent: 'An outside AI agent',
  /** Where an outside AI agent decides: what it costs this world (its model is its maker's to pay for). */
  costsNothing: 'It costs this world nothing.',
  /** The card's line where a person or an outside program chose what the character does (T7). */
  personChose: 'A person chose this.',
  programChose: 'An outside program chose this.',
  agentChose: 'An outside AI agent chose this.',
  noModel: 'No AI model',
  free: 'Free',
  current: 'Current',
  chooseModel: 'Choose an AI model',
  /** Above the chooser's rows (A3): what the models are, and that picking one spends nothing. */
  chooserIntro: 'Open models, each from its maker. Picking one spends nothing. Only a run spends.',
  /** The chooser's groups by where a model runs (A3), free first; the key group is keyGroup's. */
  hereFree: 'On this computer, free',
  serverBudget: "From this server's budget, per million tokens",
  /** The group of models on this computer where none runs yet (A3 item 2, amended 17:22). */
  noneRunning: 'None is running yet. Start one with a local model runner, and it shows here, free.',
  /** A model a person's own runner holds, while a check on this computer runs (L1): its faint row, after its name. */
  checking: 'Checking that it can decide for a person here…',
  /** The faint label over the runner's models a check found not able, after the group's choosable rows (L1). */
  notAbleHere: 'Also on this computer, not able to decide for a person here',
  perMillion: 'Per million tokens',
  choose: 'Choose',
  useThisModel: 'Use this model',
  onThisComputer: 'On this computer',
  /** The Run question's cost where every model it asks runs on this computer (A2, DESIGN). */
  freeHere: 'Free, on this computer',
  readingModels: 'Reading the models…',
  inspectDecision: 'Inspect decision',
  ask: 'Ask',
  askReading: 'Reading the world\u2019s records\u2026',
  noAnswer: 'The world has no answer recorded for this question.',
  askFailed: 'The world\u2019s records could not be read. Try again.',
  /** What a being is called with neither a name nor a kind; a thing likewise. */
  someone: 'character',
  something: 'thing',
});

const capitalised = words => words ? words.charAt(0).toUpperCase() + words.slice(1) : '';
const plain = value => typeof value === 'string' && value.trim() ? value.trim() : null;

/**
 * What a character or thing is called (WORDS.md rule 10): by its name where it has one, or by its
 * kind ("the resident"), never by "it", "he" or "she". `title` heads a tag, card or page; `start`
 * opens a sentence; `within` sits inside one.
 */
export function called({ name, kind, being = true }) {
  const named = plain(name);
  if (named) return Object.freeze({ title: named, start: named, within: named, named: true });
  const sort = (plain(kind) || (being ? CHARACTER_WORDS.someone : CHARACTER_WORDS.something)).toLowerCase();
  return Object.freeze({ title: capitalised(sort), start: `The ${sort}`, within: `the ${sort}`, named: false });
}

/** "Teo's", "the resident's". */
export const possessive = words => words + (words.endsWith("'s") ? '' : "'s");

/** The day page's Q key, naming the person as the card's keys do (DESIGN 03:57): "Ask Teo", "Ask the resident". */
export const askWho = who => `${CHARACTER_WORDS.ask} ${who.within}`;

const choices = count => `${count} ${count === 1 ? 'choice' : 'choices'}`;

/**
 * The chosen card's second line: what chose the character's current action. `decision` is the
 * model's decision that set it ({ hhmm, options }), or null when the routine did; `decider`,
 * `person` or `external`, where a person playing or an outside program chose it (T7).
 */
export function chosenLine(who, decision, decider = null) {
  if (decider === 'person') return CHARACTER_WORDS.personChose;
  if (decider === 'external') return CHARACTER_WORDS.programChose;
  if (decider === 'agent') return CHARACTER_WORDS.agentChose;
  if (!decision) return `${possessive(who.start)} routine.`;
  const options = Number.isSafeInteger(decision.options) && decision.options > 0 ? `, from ${choices(decision.options)}` : '';
  return `${possessive(who.start)} model chose this at ${decision.hhmm}${options}.`;
}

/** While a character's record is read for its card or page. */
export const readingRecord = who => `Reading ${possessive(who.within)} record…`;

/** A note when the chosen character has left the world. */
export const goneNote = who => `${who.start} is no longer in this world.`;

/** A note when following ends because the character went out of view. */
export const outOfViewNote = who => `${who.start} went out of view, so following stopped.`;

/** A page's sub-line: the character's kind and the world's name. */
export const pageSub = (kind, world) => [plain(kind) ? capitalised(plain(kind)) : null, plain(world)].filter(Boolean).join(' · ');

/** The page's list of a character's actions, titled with its name. */
export const whatDid = who => `What ${who.within} did`;

/** The list when nothing is recorded yet. */
export const nothingYet = who => `${who.start} has not done anything yet.`;

/**
 * Under one row of What Teo did: the model and its number of choices, a person playing or an outside
 * program where one decided (`decider`, T7), or the routine.
 */
export function rowSub(decision) {
  const decided = deciderWords(decision?.decider);
  if (decided) return decided;
  if (!decision?.model) return CHARACTER_WORDS.routine;
  return Number.isSafeInteger(decision.options) && decision.options > 0 ? `${decision.model} · ${choices(decision.options)}` : decision.model;
}

/** A routine row the society made while the character's model decided (P2): "Routine, between Nemotron 3 Super
 * 120B's choices". */
export const routineBetween = model => `${CHARACTER_WORDS.routine}, between ${possessive(model)} choices`;

/** The outside AI agent as a routine row between its choices names it (AG1c): "Routine, between the outside AI agent's choices". */
export const OUTSIDE_AGENT = 'the outside AI agent';

/** Who decides where a model does not (T7, AG1d): "A person playing", "An outside program", "An outside AI agent", or
 * null. */
export const deciderWords = decider => decider === 'person' ? CHARACTER_WORDS.personPlaying : decider === 'external' ? CHARACTER_WORDS.outsideProgram
  : decider === 'agent' ? CHARACTER_WORDS.outsideAgent : null;

/**
 * An outside AI agent's own words about itself (AG1d 2), as parts: ours (`declared` false, the faint ink) around its
 * declared name, maker and mind (`declared` true), each only where it declared one: "In its own words: Scout, made by
 * Harbour Lab, thinking with Nemotron 3 Nano 30B.", "In its own words: Scout."; null with no name. Shown as sent.
 */
export function declaredParts(declared) {
  if (!plain(declared?.name)) return null;
  const parts = [{ words: 'In its own words: ', declared: false }, { words: declared.name, declared: true }];
  if (plain(declared.maker)) parts.push({ words: ', made by ', declared: false }, { words: declared.maker, declared: true });
  if (plain(declared.mind)) parts.push({ words: ', thinking with ', declared: false }, { words: declared.mind, declared: true });
  parts.push({ words: '.', declared: false });
  return Object.freeze(parts.map(part => Object.freeze(part)));
}

/**
 * US dollars spent or allowed, as a person reads them (WORDS.md rule 5): whole cents to two places,
 * under a cent to four, nothing as "$0", and a cost too small for four places as less than the
 * smallest.
 */
export function amount(usd) {
  const value = Number(usd);
  if (!Number.isFinite(value) || value < 0) return '';
  if (value === 0) return '$0';
  if (value < 0.00005) return 'less than $0.0001';
  if (value >= 0.01) return '$' + value.toFixed(2);
  return '$' + value.toFixed(4).replace(/0+$/u, '');
}

/** A price: like amount(), but a price of nothing is "Free" (WORDS.md: "Free" only for a price). */
export const money = usd => Number(usd) === 0 ? CHARACTER_WORDS.free : amount(usd);

/** "Last run 06:00 to 07:15 · 12 decisions · spent $0.0042". */
export function lastRunLine({ from, to, decisions, spent }) {
  return [`Last run ${from} to ${to}`, `${decisions} ${decisions === 1 ? 'decision' : 'decisions'}`, `spent ${amount(spent)}`].join(' · ');
}

/** Whether a served model runs on this computer: its provider serves from the local host. */
export const onThisComputer = model => model?.local === true;

/** A model row's price: "$0.06 in · $0.24 out", "On this computer · Free", or "Free". */
export function priceWords(model) {
  if (onThisComputer(model)) return `${CHARACTER_WORDS.onThisComputer} · ${CHARACTER_WORDS.free}`;
  const price = model?.price;
  if (!price) return null;
  const input = Number(price.input), output = Number(price.output);
  if (input === 0 && output === 0) return CHARACTER_WORDS.free;
  return `${amount(input)} in · ${amount(output)} out`;
}

/** A model's price in the chooser's row (A3): "Free" on this computer, where its group says where, else priceWords'. */
export const rowPrice = model => onThisComputer(model) ? CHARACTER_WORDS.free : priceWords(model) ?? '';

/** A provider's name: its description up to the first comma, as a model's name is its description's. */
export const providerName = model => (typeof model?.providerDescription === 'string' ? model.providerDescription.split(',')[0].trim() : '') || model?.provider || '';

/** The chooser's group of models a key pays for (A3): "With your Nebius Token Factory key, per million tokens". */
export const keyGroup = provider => `With your ${provider} key, per million tokens`;

/**
 * Under a model's name in the chooser (A3): its maker and size, "NVIDIA · 120B", the size written as a name writes it
 * ("Qwen · 4B" where the card states 4.0B); its maker alone where its card states no size; null without a card.
 */
export function makerLine(model) {
  const card = model?.card;
  if (!card) return null;
  return card.parameters ? `${card.maker} · ${card.parameters.total.replace(/\.0(?=B$)/u, '')}` : card.maker;
}

/**
 * The focused row's words (A3 item 4): its maker's own words in quotes (`said`), then on a line of its own in the
 * faint ink where they come from and the model's licence (`from`: "from NVIDIA's model card · OpenMDW 1.1"); null
 * where no card is kept. Never our own claim.
 */
export function cardWords(model) {
  const card = model?.card;
  if (!card) return null;
  return Object.freeze({ said: `\u201c${card.says}\u201d`, from: `from ${possessive(card.maker)} model card · ${card.licence}` });
}

/** The world's model list folds a runner's models a check found not able into one line (L1, DESIGN 11:58). */
export const notAbleFold = count => `And ${count} more on this computer that cannot decide for a person here.`;

/** Under the fold: where each one's reason is told. */
export const reasonsOn = who => `Their reasons are on ${possessive(who.within)} day page.`;

/** A runner's model being checked (L1): "Llama · 1.2B · Checking that it can decide for a person here…". */
export const checkingLine = model => `${model.name} · ${CHARACTER_WORDS.checking}`;

/** A dollar figure to the cent's tenth and hundredth where it has them ("$0.086", "$0.03"), so a decision's most and
 * what is left never read alike in one line (U2). */
export const finer = usd => `$${Number(usd).toFixed(4).replace(/\.?0+$/u, '')}`;

/** A guest's faint row (U2, DESIGN 12:20): asking it once can cost more than they have left for AI models here; where
 * what is left rounds to nothing, without its figure (DESIGN 15:58). */
export const overLine = (most, left) => finer(left) === '$0'
  ? `Asking it once can cost up to ${finer(most)}, more than is left for AI models here.`
  : `Asking it once can cost up to ${finer(most)}, more than the ${finer(left)} left for AI models here.`;

/** Why a runner's model is not able to decide for a person here (L1), in one line from its check. */
export function notAbleLine(model) {
  if (model?.reason === 'context') return `It reads at most ${Number(model.contextTokens).toLocaleString('en-US')} tokens at once, less than a person is told here.`;
  if (model?.reason === 'form') return 'It did not answer with one of the offered choices when checked.';
  if (model?.reason === 'slow') return `It took longer than the ${Math.round(Number(model.deadlineMs) / 1000)} seconds a person has to decide.`;
  if (model?.reason === 'text') return 'It does not read text.';
  return 'It could not be checked here.';
}

/** Under a runner's model whose name another row shares (L1 rule 5): "Your runner calls it qwen3:4b-instruct". */
export const runnerCalls = model => `Your runner calls it ${model.servedAs.replace(/:latest$/u, '')}`;

/** The most of a runner's licence line its open row quotes (L1). */
const LICENCE_SHOWN = 80;

/**
 * A runner's model's open words in the chooser (L1, DESIGN 11:22): no maker's card is kept for it, so first what its
 * check on this computer found, in the row's ink ("Checked on this computer: it chose one of the offered choices in
 * 2.1 s.", its slowest case), then, in the faint ink, the licence its runner states, quoted as stated and cut to 80
 * characters; with no licence stated the check's line opens alone. Null where neither is known.
 */
export function runnerOpen(model) {
  const runner = model?.runner;
  const checked = Number.isFinite(runner?.checkedMs)
    ? `Checked on this computer: it chose one of the offered choices in ${(runner.checkedMs / 1000).toFixed(1)} s.` : null;
  const licence = plain(runner?.licence);
  const quoted = licence && (licence.length > LICENCE_SHOWN ? `${licence.slice(0, LICENCE_SHOWN - 1)}\u2026` : licence);
  const from = quoted ? `from your runner · \u201c${quoted}\u201d` : null;
  return checked || from ? Object.freeze({ said: checked ?? '', from }) : null;
}

/** The page's Model line: the price per million tokens, or no model. */
export function modelLine(model) {
  if (!model) return `${CHARACTER_WORDS.noModel} · ${CHARACTER_WORDS.free}`;
  const price = priceWords(model);
  return price && price.includes(' in · ') ? `${price} per million tokens` : price;
}

/** The page's Run section for a character with no model (DESIGN's J2). */
export const routineRun = who => `${who.start} follows a routine. Choose an AI model to run.`;

/** The same where this person cannot choose a model here (no [M] Model): no instruction it cannot follow. */
export const followsRoutine = who => `${who.start} follows a routine.`;

/** The host's money for models is spent (its codes, as the models read and a run's refusal name them). */
export const BUDGET_SPENT = Object.freeze(['process_budget_spent', 'process_share_spent']);

/** The Run section where the host's budget for models is spent (J22). */
export const budgetSpent = who => `The budget for AI models here is spent, so ${who.within} follows a routine.`;

/** The Run section where spending on AI models is held closed until an operator acts, not spent (N34). */
export const spendingPaused = who => `Spending on AI models is paused here, so ${who.within} follows a routine.`;

/** The Run section where the character's chosen model is refused here and others are not (J22). */
export const modelCannot = (who, assignable) =>
  `This model cannot decide for ${who.within} here, so ${who.within} follows a routine.${assignable ? ' Choose another model to run.' : ''}`;

/**
 * Why a character's model does not run here, as the page's Run section says it (DESIGN's J2 and
 * J22), or null where it can run. From the models read: the host's own refusal, each offered model's
 * refusal, and the chosen model's (`chosen` false with none chosen). The host's budget spent wins;
 * then spending held closed (N34); then nothing that can be asked because the models on this computer do not run (A2); then
 * nothing that can be asked at all; then a chosen model refused while others can be asked; then
 * no model chosen, with how to run only where [M] is drawn (`assignable`).
 */
export function runSectionLine(who, { hostRefusal = null, offered = [], chosen = false, chosenRefusal = null, assignable = false }) {
  const refusals = offered.map(model => model.refusal ?? null);
  if (BUDGET_SPENT.includes(hostRefusal) || BUDGET_SPENT.includes(chosenRefusal)
    || (refusals.length > 0 && refusals.every(code => BUDGET_SPENT.includes(code)))) return budgetSpent(who);
  if (hostRefusal === 'spending_suspended') return spendingPaused(who);
  const wouldOffer = refusals.filter(code => code !== 'provider_credential_absent');
  if (!hostRefusal && wouldOffer.length > 0 && wouldOffer.every(code => code === 'provider_not_running')) return notRunningHere(who);
  if (hostRefusal || !refusals.some(code => code === null)) return notConnected(who);
  if (chosen && chosenRefusal) return modelCannot(who, assignable);
  if (!chosen) return assignable ? routineRun(who) : followsRoutine(who);
  return null;
}

/** The page's Run section where no AI model can be asked here (spec 7, empty). */
export const notConnected = who => `No AI model is connected here, so ${who.within} follows a routine.`;

/**
 * Where no model can be offered because none is running on this computer (A2, DESIGN's "A2 amended"): how to have one,
 * plainly, naming no runner.
 */
export const noModelRunning = who => `No AI model is running on this computer yet. Start one with a local model runner, and it can decide for ${who.within}, free.`;

/** The page's Run section in that case (A2, DESIGN's words): why the routine decides, then how to have a model. */
export const notRunningHere = who => `No AI model is running on this computer yet, so ${who.within} follows a routine. Start one with a local model runner, and it can decide for ${who.within}, free.`;

/** Routine's row in the model list. */
export const routineRow = () => `${CHARACTER_WORDS.noModel} · ${CHARACTER_WORDS.free}`;

/**
 * Why a model could not be chosen, in the place it happened (spec 8.7): `stale` when the character
 * or its offer changed between the read and the choice, else by the server's code.
 */
export function modelRefusalWords(code, who) {
  if (code === 'stale' || code === 'choice_key_reused') return `${who.start} changed a moment ago. Look again and choose once more.`;
  if (code === 'person_not_in_this_world') return goneNote(who);
  return `This model cannot decide for ${who.within} here.`;
}

/**
 * A chosen character's group beside them (DESIGN's J30, the r05 picture): its choices, each only where it
 * works, as the key rows say them. `who` is called()'s.
 */
export const GROUP_WORDS = Object.freeze({
  decide: who => `Let ${possessive(who.within)} model decide`,
  stop: who => `Stop ${possessive(who.within)} model`,
  choose: who => `Choose ${possessive(who.within)} AI model`,
  follow: who => `Follow ${who.within}`,
  stopFollowing: () => CHARACTER_WORDS.stopFollowing,
});

/**
 * The group's small print: who decides for the character now (J30). `decider` is 'external' (an outside
 * program, T7), 'person', 'model' or 'routine'; `model` the model's served name; `left` the time left of a run its model is in
 * ("1:52"), or null when no run is on.
 */
export function decidesPrint(who, { decider, model = null, left = null }) {
  if (decider === 'external') return `${who.start} comes from an outside program`;
  if (decider === 'agent') return `${CHARACTER_WORDS.outsideAgent} decides for ${who.within}.`;
  if (decider === 'person') return `A person is playing ${who.within}`;
  if (decider === 'model' && plain(model)) return left ? `${possessive(who.start)} model is deciding · ${left} left` : `${plain(model)} decides for ${who.within}`;
  return `${who.start} follows a routine`;
}

/** A line as it was said, in curly quotes. */
export const quoted = line => `“${line}”`;

/**
 * Under the last line said: to whom and when ("To Marco, 07:10"). `to` is called()'s for the one it was said
 * to, or null for everyone near, which shows the time alone; `hhmm` is null where the society keeps no
 * clock (J25), and then a line to everyone near shows nothing under it.
 */
export function saidUnder({ to = null, hhmm = null }) {
  if (to) return hhmm ? `To ${to.within}, ${hhmm}` : `To ${to.within}`;
  return hhmm ?? null;
}

/**
 * Whose models a run asks (J28), the chosen character first, then the others in the order served: "Teo's model
 * decides.", "Teo's and Ari's models decide.", "Teo's, Ari's and the resident's models decide.", "Teo's model and
 * 3 more decide.", then "Everyone else carries on as before." unless nobody else lives in the world (`others`
 * false). `whos` are called()'s for each character the run will ask; null when there is none.
 */
export function modelsDecide(whos, { others = true } = {}) {
  const [first, ...rest] = whos ?? [];
  if (!first) return null;
  const owners = rest.length === 0 ? `${possessive(first.start)} model decides.`
    : rest.length === 1 ? `${possessive(first.start)} and ${possessive(rest[0].within)} models decide.`
      : rest.length === 2 ? `${possessive(first.start)}, ${possessive(rest[0].within)} and ${possessive(rest[1].within)} models decide.`
        : `${possessive(first.start)} model and ${rest.length} more decide.`;
  return others ? `${owners} Everyone else carries on as before.` : owners;
}

/**
 * The models a run asks (r08, DESIGN's aha 20), the chosen character's first, each named once: one by its name, two
 * joined with "and", more than two the first "and 2 other models"; null when none has a name.
 */
export function modelsNamed(names) {
  const named = [...new Set((names ?? []).map(name => (typeof name === 'string' ? name.trim() : '')).filter(Boolean))];
  if (named.length <= 2) return named.join(' and ') || null;
  return `${named[0]} and ${named.length - 1} other models`;
}

/**
 * Under the Run question's model and cap (r08): when the run stops, naming no control, its minutes said as real
 * time so they are never read as the world's (DESIGN 03:57).
 */
export const stopsAfter = minutes => `It stops after ${minutes} ${minutes === 1 ? 'minute' : 'minutes'} of real time, or when you stop it.`;

/** The Run question's way to another model (r08), where another is offered and this page may choose. */
export const ANOTHER_MODEL = 'Choose another model';
