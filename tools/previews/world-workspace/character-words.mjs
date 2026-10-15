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
 * model's decision that set it ({ hhmm, options }), or null when the routine did.
 */
export function chosenLine(who, decision) {
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

/** Under one row of What Teo did: the model and its number of choices, or the routine. */
export function rowSub(decision) {
  if (!decision?.model) return CHARACTER_WORDS.routine;
  return Number.isSafeInteger(decision.options) && decision.options > 0 ? `${decision.model} · ${choices(decision.options)}` : decision.model;
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

/** The page's Model line: the price per million tokens, or no model. */
export function modelLine(model) {
  if (!model) return `${CHARACTER_WORDS.noModel} · ${CHARACTER_WORDS.free}`;
  const price = priceWords(model);
  return price && price.includes(' in · ') ? `${price} per million tokens` : price;
}

/** The page's Run section for a character with no model (DESIGN's J2). */
export const routineRun = who => `${who.start} follows a routine. Choose a model to run.`;

/** The page's Run section where no AI model can be asked here (spec 7, empty). */
export const notConnected = who => `No AI model is connected here, so ${who.within} follows a routine.`;

/** Routine's row in the model list. */
export const routineRow = () => `${CHARACTER_WORDS.noModel} · ${CHARACTER_WORDS.free}`;

/**
 * The models a person chooses from, as the list shows them: NVIDIA's open models first, cheapest
 * first; then the rest in the order the server serves them. Routine is the list's own last row.
 */
export function orderedModels(models) {
  const first = models.filter(model => model.modelId.startsWith('nvidia/'))
    .map((model, index) => ({ model, index, price: model.price ? Number(model.price.input) : Infinity }))
    .sort((a, b) => a.price - b.price || a.index - b.index).map(item => item.model);
  return [...first, ...models.filter(model => !model.modelId.startsWith('nvidia/'))];
}

/**
 * Why a model could not be chosen, in the place it happened (spec 8.7): `stale` when the character
 * or its offer changed between the read and the choice, else by the server's code.
 */
export function modelRefusalWords(code, who) {
  if (code === 'stale' || code === 'choice_key_reused') return `${who.start} changed a moment ago. Look again and choose once more.`;
  if (code === 'person_not_in_this_world') return goneNote(who);
  return `This model cannot decide for ${who.within} here.`;
}
