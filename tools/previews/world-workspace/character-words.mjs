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
  /** The card's line where a person or an outside program chose what the character does (T7). */
  personChose: 'A person chose this.',
  programChose: 'An outside program chose this.',
  noModel: 'No AI model',
  free: 'Free',
  current: 'Current',
  chooseModel: 'Choose a model',
  pickingSpendsNothing: 'Picking one spends nothing. Only a run spends.',
  perMillion: 'Per million tokens',
  choose: 'Choose',
  useThisModel: 'Use this model',
  onThisComputer: 'On this computer',
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

const choices = count => `${count} ${count === 1 ? 'choice' : 'choices'}`;

/**
 * The chosen card's second line: what chose the character's current action. `decision` is the
 * model's decision that set it ({ hhmm, options }), or null when the routine did; `decider`,
 * `person` or `external`, where a person playing or an outside program chose it (T7).
 */
export function chosenLine(who, decision, decider = null) {
  if (decider === 'person') return CHARACTER_WORDS.personChose;
  if (decider === 'external') return CHARACTER_WORDS.programChose;
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

/** Who decides where a model does not (T7): "A person playing", "An outside program", or null. */
export const deciderWords = decider => decider === 'person' ? CHARACTER_WORDS.personPlaying : decider === 'external' ? CHARACTER_WORDS.outsideProgram : null;

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

/** The page's Model line: the price per million tokens, or no model. */
export function modelLine(model) {
  if (!model) return `${CHARACTER_WORDS.noModel} · ${CHARACTER_WORDS.free}`;
  const price = priceWords(model);
  return price && price.includes(' in · ') ? `${price} per million tokens` : price;
}

/** The page's Run section for a character with no model (DESIGN's J2). */
export const routineRun = who => `${who.start} follows a routine. Choose a model to run.`;

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
 * then spending held closed (N34); then nothing that can be asked at all; then a chosen model refused while others can be asked; then
 * no model chosen, with how to run only where [M] is drawn (`assignable`).
 */
export function runSectionLine(who, { hostRefusal = null, offered = [], chosen = false, chosenRefusal = null, assignable = false }) {
  const refusals = offered.map(model => model.refusal ?? null);
  if (BUDGET_SPENT.includes(hostRefusal) || BUDGET_SPENT.includes(chosenRefusal)
    || (refusals.length > 0 && refusals.every(code => BUDGET_SPENT.includes(code)))) return budgetSpent(who);
  if (hostRefusal === 'spending_suspended') return spendingPaused(who);
  if (hostRefusal || !refusals.some(code => code === null)) return notConnected(who);
  if (chosen && chosenRefusal) return modelCannot(who, assignable);
  if (!chosen) return assignable ? routineRun(who) : followsRoutine(who);
  return null;
}

/** The page's Run section where no AI model can be asked here (spec 7, empty). */
export const notConnected = who => `No AI model is connected here, so ${who.within} follows a routine.`;

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
  choose: who => `Choose ${possessive(who.within)} model`,
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

/** Under the Run question's model and cap (r08): when the run stops, naming no control. */
export const stopsAfter = minutes => `It stops after ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}, or when you stop it.`;

/** The Run question's way to another model (r08), where another is offered and this page may choose. */
export const ANOTHER_MODEL = 'Choose another model';
