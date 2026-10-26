// The model gallery (G2, DESIGN's BUILD-SHEETS-1024 "G2" and its WORDS.md rulings): M on a chosen person opens a light
// page over the world faded behind it, as the day page and the decision page are. At the left who it is for and what
// the role is, then the models in their groups, free first and by price, none set above another; at the right the one in focus
// opened: why it can decide for a person here, its maker's own words, the facts from its card, what a decision costs
// and what it has done in this world. Pure: what the page draws, from the models read, never a figure of its own.
import { CHARACTER_WORDS, amount, called, cardWords, checkingLine, notAbleFold, notAbleLine, possessive, reasonsOn, runnerOpen } from './character-words.mjs';
import { choosableModels, noneRunningHere, overRows } from './character-group.mjs';
import { PROVIDER_NAMES } from './create-words.mjs';

export const GALLERY_WORDS = Object.freeze({
  title: who => `Choose an AI model for ${who.within}`,
  role: 'Open models that can decide what a person does. Picking one spends nothing; only a run spends.',
  noModel: CHARACTER_WORDS.noModel,
  routineSub: who => `${possessive(who.start)} own daily routine`,
  routineLine: who => `No AI model decides for ${who.within}: they follow their own daily routine, and nothing is spent.`,
  choose: who => `Choose it for ${who.within}`,
  chooseRoutine: who => `Choose the routine for ${who.within}`,
  then: who => `Then run, and see what ${who.within} does with it.`,
  why: 'Why it can decide for a person here',
  strict: "It answers in the strict form this role asks for: exactly one of the person's offered choices.",
  roomy: 'It reads everything a person is told at a decision, with room to spare.',
  inWords: "In its maker's words",
  onCard: maker => `${maker}, on its model card`,
  fromCard: 'From its card',
  learnMore: 'Learn more on its model card ↗',
  move: 'Move',
  chooseAtOnce: 'Choose at once',
  back: CHARACTER_WORDS.back,
});

/** The largest share of a model's context a decision's largest request may take for "room to spare": half (G2 ruling). */
const ROOM = 2;

/**
 * A maker's mark in letters (DESIGN 12:05, by rule, no logos): the first letter and the next capital where the name has
 * one inside it ("DeepSeek" DS), the first two letters of a name in capitals ("NVIDIA" NV), else the first two as
 * written ("Qwen" Qw). A model with no maker takes its own name's.
 */
export function markOf(maker) {
  const name = String(maker ?? '').replace(/[^A-Za-z0-9]/gu, '');
  if (!name) return '?';
  const inner = name.slice(1).search(/[A-Z]/u);
  if (inner >= 0 && name !== name.toUpperCase()) return name[0] + name[inner + 1];
  return name[0] + (name.slice(1, 2) || '');
}

const capital = words => words.charAt(0).toUpperCase() + words.slice(1);

/** "120B" as a sentence says it: "120 billion"; "3.5B" "3.5 billion"; "800M" "800 million"; null for anything else. */
function sizeWords(size) {
  const found = /^(\d+(?:\.\d+)?)([BM])$/u.exec(String(size ?? '').replace(/\.0(?=[BM]$)/u, ''));
  return found ? `${found[1]} ${found[2] === 'B' ? 'billion' : 'million'}` : null;
}

/** How many times the contract asks at most, in a word: the read's most for a decision over its most for an attempt. */
function attemptsWord(model) {
  const times = Math.round(Number(model.decisionMostUsd) / Number(model.attemptMostUsd));
  return times === 1 ? 'once' : times === 2 ? 'twice' : `${times} times`;
}

/** What this world's decisions came to for `model`, from the read's by-model summaries; null where it has none. */
function hereOf(read, model) {
  return (read?.byModel ?? []).find(one => one.provider === model.provider && one.modelId === model.modelId) ?? null;
}

/** "decided 9 times here", or "decided at least 2,000 times here" where the read's window is full (DESIGN 12:05). */
function decidedHere(read, here, { sentence = false } = {}) {
  if (!here || !here.decisions) return sentence ? 'Not asked here yet' : null;
  const full = Number.isSafeInteger(read?.decisionsMaximum) && read.decisionsCounted >= read.decisionsMaximum;
  const count = `${full ? 'at least ' : ''}${here.decisions.toLocaleString('en-US')} ${here.decisions === 1 ? 'time' : 'times'}`;
  return sentence ? `Decided ${count}` : `decided ${count} here`;
}

/** "about $0.0002", or "less than $0.0001" where the middle is under the smallest figure amount() writes. */
function about(usd) {
  const words = amount(usd);
  return words.startsWith('less than') ? words : `about ${words}`;
}

/** A row's cost (G2 3): "Free" on this computer; "about $Y a decision" once it has decided here; else "at most $X". */
function rowCost(read, model) {
  if (model.local === true) return CHARACTER_WORDS.free;
  const middle = hereOf(read, model)?.costMedianUsd;
  if (middle) return `${about(middle)} a decision`;
  return model.decisionMostUsd ? `at most ${amount(model.decisionMostUsd)} a decision` : '';
}

/** Under a row's name: maker and size, the size at work for a mixture of experts, and what it decided here. */
function rowSub(read, model) {
  const card = model.card;
  const size = card?.parameters?.total?.replace(/\.0(?=B$)/u, '');
  const active = card?.parameters?.active?.replace(/\.0(?=B$)/u, '');
  const made = card ? [card.maker, size ? `${size}${active ? `, ${active} at work at a time` : ''}` : null].filter(Boolean).join(' · ') : null;
  return [made, decidedHere(read, hereOf(read, model))].filter(Boolean).join(' · ') || null;
}

/** The free group's label: this computer on a person's own install, this server on a guest's page (a guest's own
 * computer runs nothing here; DESIGN 26 October, as the guest's Integrations page says it). */
const hereLabel = fromServer => (fromServer ? 'On this server, free' : CHARACTER_WORDS.hereFree);

/** Where a model runs, as a group label and as the detail's "Runs on" says it. */
function runsOn(model, fromServer) {
  if (model.local === true) return { label: hereLabel(fromServer), on: fromServer ? 'This server' : 'This computer' };
  if (fromServer) return { label: "From this server's budget", on: "This server's budget" };
  const name = PROVIDER_NAMES[model.provider] ?? (model.providerDescription?.split(',')[0].trim() || model.provider);
  return { label: `With your ${name} key`, on: `${model.providerDescription?.split(',')[0].trim() || name}, with your key` };
}

/**
 * The page (G2 2 to 5): the head's words, the groups with their rows in the chooser's order (choosableModels: this
 * computer first, then by price), a guest's too-dear rows faint in their provider's group (U2, U3b), the runner's rows
 * being checked and the fold of those not able under this computer's (L1c), then No AI model with Routine. Each
 * choosable row has its number key; faint rows have none and never take the focus. `current` is the person's model
 * (null: their routine); `fromServer` a guest's page.
 */
export function galleryPage({ read, who = called({ name: null, kind: null }), doing = null, current = null, fromServer = false }) {
  const models = choosableModels(read);
  const sameAs = model => current !== null && model.provider === current.provider && model.modelId === (current.modelId ?? current.model_id);
  const groups = new Map();
  const group = label => {
    if (!groups.has(label)) groups.set(label, { label, rows: [], faint: [], fold: null, waiting: null });
    return groups.get(label);
  };
  const choosable = [];
  for (const model of models) {
    choosable.push(model);
    group(runsOn(model, fromServer).label).rows.push(Object.freeze({
      key: String(choosable.length), mark: markOf(model.card?.maker ?? model.name), name: model.name, sub: rowSub(read, model),
      cost: rowCost(read, model), current: sameAs(model), model,
    }));
  }
  const runner = read?.runnerModels ?? [];
  const checking = runner.filter(one => one.state === 'checking');
  const notAble = runner.filter(one => one.state === 'not_able');
  if (checking.length || notAble.length) {
    const here = group(hereLabel(fromServer));
    here.faint.push(...checking.map(one => Object.freeze({ mark: markOf(one.name), name: checkingLine(one), sub: null, line: null })));
    if (notAble.length) here.fold = Object.freeze({ line: notAbleFold(notAble.length), sub: reasonsOn(who), lines: Object.freeze(notAble.map(notAbleLine)) });
  }
  // This install lets a model on this computer in and none runs yet: the group stands with how to start one (A3 2).
  if (noneRunningHere(read)) group(hereLabel(fromServer)).waiting = CHARACTER_WORDS.noneRunning;
  const over = overRows(read, current);
  if (over.length) {
    // Each keeps its maker and size as the other rows say them (DESIGN 26 October).
    const named = row => (read?.models ?? []).find(model => model.name === row.word) ?? null;
    const label = runsOn(named(over[0]) ?? {}, fromServer).label;
    group(label).faint.push(...over.map(row => Object.freeze({ mark: markOf(named(row)?.card?.maker ?? row.word), name: row.word,
      sub: named(row) ? rowSub(read, named(row)) : row.sub, line: row.line, current: row.current })));
  }
  const routineKey = String(choosable.length + 1);
  const routine = Object.freeze({ key: routineKey, mark: 'R', name: CHARACTER_WORDS.routine, sub: GALLERY_WORDS.routineSub(who), cost: CHARACTER_WORDS.free, current: current === null, model: null });
  const free = hereLabel(fromServer);
  const ordered = [...groups.values()].sort((one, other) => Number(one.label !== free) - Number(other.label !== free));
  return Object.freeze({
    over: [who.title, doing].filter(Boolean).join(' · '),
    title: GALLERY_WORDS.title(who),
    role: GALLERY_WORDS.role,
    groups: Object.freeze([...ordered.map(one => Object.freeze({ ...one, rows: Object.freeze(one.rows), faint: Object.freeze(one.faint) })),
      Object.freeze({ label: GALLERY_WORDS.noModel, rows: Object.freeze([routine]), faint: Object.freeze([]), fold: null, waiting: null })]),
    // Every row a number or the arrows reach, in the page's order: the models, then Routine.
    rows: Object.freeze([...ordered.flatMap(one => one.rows), routine]),
    // The keys as the frame draws them: caps, then the word; the number keys from 1 to the last row's.
    keys: Object.freeze([{ caps: ['↑', '↓'], word: GALLERY_WORDS.move }, { caps: ['1', routineKey], through: true, word: GALLERY_WORDS.chooseAtOnce },
      { caps: ['Esc'], word: GALLERY_WORDS.back }].map(key => Object.freeze(key))),
  });
}

/** Where the focus starts (66dd88174): the person's own model, else the first with its maker's words, else the first. */
export function firstFocus(page) {
  const own = page.rows.findIndex(row => row.current && row.model);
  if (own >= 0) return own;
  const worded = page.rows.findIndex(row => row.model?.card);
  return worded >= 0 ? worded : 0;
}

/**
 * The model in focus opened (G2 4), each part only where its fact is held: its mark and name, its maker with the link to
 * its card at the pinned revision, why it can decide for a person here, its maker's words, the facts from its card, and
 * choosing it. Routine in focus says what the routine is. A runner's model says what its check found (L1c).
 */
export function galleryDetail({ read, row, who = called({ name: null, kind: null }), fromServer = false }) {
  const model = row?.model ?? null;
  if (!model) {
    return Object.freeze({ mark: 'R', name: CHARACTER_WORDS.routine, by: null, link: null, why: Object.freeze([]), words: null,
      line: GALLERY_WORDS.routineLine(who), facts: Object.freeze([]), act: GALLERY_WORDS.chooseRoutine(who), then: null });
  }
  const card = model.card ?? null;
  const why = [];
  // A model a person's own runner holds says first what its check on this computer found (L1c, DESIGN 26 October).
  const checked = model.runner ? runnerOpen(model) : null;
  if (checked?.said) why.push(checked.said);
  if (model.mechanism === 'tool_call' || model.mechanism === 'json_schema') why.push(GALLERY_WORDS.strict);
  const request = read?.requestTokensAtMost, context = model.contextWindowTokens;
  if (Number.isSafeInteger(request) && Number.isSafeInteger(context) && context >= ROOM * request) why.push(GALLERY_WORDS.roomy);
  const facts = [];
  const total = sizeWords(card?.parameters?.total), active = sizeWords(card?.parameters?.active);
  if (total) facts.push(['Size', `${total} parameters${active ? `, ${active} at work at a time` : ''}`]);
  if (Number.isSafeInteger(context)) facts.push(['Reads', `Text, up to ${context.toLocaleString('en-US')} tokens at once`]);
  // Without a card, the licence its runner states, quoted as stated (L1c): "from your runner · “<licence>”".
  const licence = card?.licence ?? checked?.from ?? null;
  if (licence) facts.push(['Licence', licence]);
  facts.push(['Runs on', runsOn(model, fromServer).on]);
  if (model.local !== true && model.decisionMostUsd && model.attemptMostUsd) {
    const here = hereOf(read, model);
    const most = `at most ${amount(model.decisionMostUsd)}, its largest request and longest answer, ${attemptsWord(model)}.`;
    const perMillion = model.price ? ` ${amount(model.price.input)} in and ${amount(model.price.output)} out per million tokens.` : '';
    facts.push(['A decision', here?.costMedianUsd
      ? `${capital(about(here.costMedianUsd))} a decision here (the middle of ${here.costsCounted}); ${most}${perMillion}`
      : `${capital(most)}${perMillion}`]);
  } else if (model.local === true) facts.push(['A decision', CHARACTER_WORDS.free]);
  facts.push(['In this world', decidedHere(read, hereOf(read, model), { sentence: true })]);
  return Object.freeze({
    mark: markOf(card?.maker ?? model.name), name: model.name,
    by: card ? `By ${card.maker}` : null, link: card?.source ?? null,
    why: Object.freeze(why),
    words: card ? Object.freeze({ said: cardWords(model).said, from: GALLERY_WORDS.onCard(card.maker) }) : null,
    line: null,
    facts: Object.freeze(facts.map(([key, value]) => Object.freeze({ key, value }))),
    act: GALLERY_WORDS.choose(who), then: GALLERY_WORDS.then(who),
  });
}

/** The focus moved by the arrows over the choosable rows only (faint rows are not among `page.rows`), clamped. */
export const moveFocus = (page, focus, step) => Math.max(0, Math.min(page.rows.length - 1, focus + step));

/** The row a number key chooses at once, or null for a key no row has. */
export const rowForKey = (page, key) => page.rows.find(row => row.key === key) ?? null;
