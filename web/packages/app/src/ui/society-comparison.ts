/**
 * The same hour of a world, run by two deciders, side by side on one clock.
 *
 * It builds elements and holds no client: the mount hands it the server's comparison reads and the
 * runs it replayed, and routes each choice through a handler. Every number is the server's, shown
 * as written and never clipped, so a score below 0 (worse than waiting) or above 1 (better than
 * the routine) reads as it is. Whether two arms differ is the server's verdict, read by its code;
 * nothing here compares two numbers to decide it. A score says how the group's people fared, and
 * wherever one is shown, what its arm's model answered is shown beside it: the turns it answered,
 * those whose answer was refused and those left to the routine, since the routine decides every
 * turn a model leaves.
 */

import type {
  Answering,
  AnsweringMechanism,
  AnsweringSource,
  ArmRole,
  ComparisonArm,
  ComparisonListing,
  ComparisonResult,
  ComparisonSeed,
  GroupSourceKind,
  OtherPerson,
  Reliability,
  RunDecision,
  ReportedCounts,
  RunReplay,
  VerdictCode,
} from '../society-comparison-api.js';
import { REPORTED_ACTS } from '../society-comparison-api.js';
import { DECISION_WORDS, eventReasonWords, livingNeedLabel, optionalPhrase, outcomeWords } from '../society-inhabitant-words.js';
import { el, replace } from './dom.js';
import { createLivingWorldInspector } from './living-world-inspector.js';
import { buildComparisonPlan, classWords, minuteAt, minuteClass, type MinuteClass } from './society-comparison-plan.js';
import { buildComparisonStrips } from './society-comparison-strips.js';
import { progressWords, startWords } from './society-comparison-start.js';
import './society-comparison.css';

/**
 * The verdict in words, by the server's code: exactly `VERDICTS` in
 * `exulanica/world/society_comparison_claim.py`, held to it by society-comparison-words-parity.test.ts.
 */
export const VERDICT_WORDS: Readonly<Record<VerdictCode, string>> = {
  different: 'Different',
  no_measured_difference: 'No measured difference',
  not_judged: 'Not judged',
  incomplete: 'Incomplete',
};

/** Why a comparison is not judged, by `NOT_JUDGED_REASONS` in the same module. */
export const NOT_JUDGED_WORDS: Readonly<Record<string, string>> = {
  development_seeds: 'It ran on development seeds, which are looked at freely, so no difference is claimed from them.',
  scored_under_other_code: 'The code that scores it now is not the code it was registered under, so its registered claim is not read again here.',
  too_few_seeds_scored: 'Fewer than two of its seeds carry a score for every arm the claim reads, too few for an interval.',
};

/** Why a run failed, by `RUN_FAILURE_CODES` in `exulanica/api/society_comparison_runner.py`. */
export const FAILURE_WORDS: Readonly<Record<string, string>> = {
  anchor_failed: 'a run of the routine or of waiting on this seed did not complete, so this run could never be scored and asked nothing',
  comparison_bound_before_seed: 'what was left of the bound you set would not let this seed finish, so the comparison stopped before it and kept the seeds it had played',
  comparison_bound_spent: 'the bound you set for this comparison had too little left for its next ask, so it stopped there',
  comparison_cancelled: 'the comparison was stopped before this run finished',
  comparison_stopped: 'the server stopped running the comparison before this run was played',
  input_unavailable: 'this world\'s places were no longer available to run it on',
  interrupted: 'the process that ran it stopped part way, so its hour was not finished; a new comparison runs it again',
  model_no_longer_offered: 'the model is no longer offered for decisions',
  process_budget_spent: 'the model budget it ran under had too little left',
  process_share_spent: 'the model budget it ran under, less the part kept for other work, had too little left',
  provider_changed: 'the service that runs the model changed',
  provider_configuration_changed: 'the server asks the model otherwise than the comparison recorded',
  provider_credential_absent: 'the server that ran it had no key for the model\'s service',
  provider_not_admitted: 'the server that ran it may not reach the model\'s service',
  question_changed_by_rules: 'this world\'s rules would change the question each person is asked',
  request_refused: 'this world\'s rules would not let the question be sent',
  spending_not_granted: 'this workspace has no allowance to spend on that model\'s service',
  spending_revoked: 'the allowance it spent from was withdrawn',
  spending_expired: 'the allowance it spent from had run out of time',
  spending_limit_reached: 'the allowance would have gone over its limit',
  spending_suspended: 'spending on models is paused until the person who runs this installation resumes it',
  spending_unavailable: 'the allowance could not be checked, so nothing was sent',
  spending_scope_missing: 'the request did not say which workspace to spend for',
};

/**
 * Where a comparison's group came from, by `GROUP_SOURCES` in
 * `exulanica/world/society_comparison_result.py`, held to it by society-comparison-words-parity.test.ts.
 */
export const GROUP_SOURCE_WORDS: Readonly<Record<GroupSourceKind, string>> = {
  everyone: 'everybody in this world',
  named: 'the people the comparison named',
  owner_choice: 'the group you chose a model for',
};

/** A decimal the server wrote as a share, as a percentage: the same digits, the point moved. */
export function percentText(share: string): string {
  const negative = share.startsWith('-');
  const [whole, fraction = ''] = (negative ? share.slice(1) : share).split('.');
  const digits = `${whole}${fraction.padEnd(2, '0')}`;
  const point = whole!.length + 2;
  const integer = digits.slice(0, point).replace(/^0+(?=\d)/, '');
  const rest = digits.slice(point);
  return `${negative ? '−' : ''}${integer}${rest.length > 0 ? `.${rest}` : ''}%`;
}

/**
 * What an arm's model answered, in words, as it is said beside every score: its share of turns
 * answered, refused and left to the routine; or that no model decides for the group in the arm.
 */
export function reliabilityWords(arm: ComparisonArm, reliability: Reliability | null): string {
  if (arm.decider.kind !== 'model') {
    return arm.decider.kind === 'routine'
      ? 'No model is asked: the group follows its routine.'
      : 'No model is asked: the group waits.';
  }
  if (reliability === null) return 'No completed run to say what its model answered.';
  if (reliability.shares === null) return `${armName(arm)} was not asked for any turn.`;
  const { answered, refused, leftToRoutine } = reliability.shares;
  return `${armName(arm)} answered ${percentText(answered)} of ${reliability.turns} turns; `
    + `${percentText(refused)} were refused and ${percentText(leftToRoutine)} left to the routine.`;
}

/**
 * Why the turns a model did not decide were decided by the routine instead, by the reason each
 * receipt or minute recorded, most often first, in the words the inspector uses for them.
 */
export function reasonWords(reliability: Reliability | null): string {
  const reasons = Object.entries(reliability?.reasons ?? {}).filter(([, times]) => times > 0)
    .sort(([one, first], [two, second]) => second - first || one.localeCompare(two));
  if (reasons.length === 0) return '';
  return `Why the routine decided instead: ${reasons.map(([code, times]) =>
    `${DECISION_WORDS[code] ?? 'a reason this page cannot name yet'} (${times})`).join('; ')}.`;
}

/**
 * The same turns per choice point the routine's own run had for the group on the same seed, a
 * count no model's answers move; or, for a comparison that did not record it, that it did not.
 */
export function routineRateWords(arm: ComparisonArm, reliability: Reliability | null, scoreVersion: number): string {
  if (arm.decider.kind !== 'model' || reliability === null) return '–';
  if (reliability.perRoutineChoice === null) {
    return scoreVersion === 1
      ? 'Not recorded: this comparison predates counting the routine\'s choice points.'
      : 'No routine run of these seeds recorded its choice points.';
  }
  return `${reliability.perRoutineChoice.leftToRoutine} left to the routine per choice point `
    + `the routine had (${reliability.routineChoicePoints ?? 0})`;
}

/** Why a seed carries no score, by `BELOW_FLOOR` in `exulanica/world/society_score.py`. */
export const EXCLUDED_WORDS: Readonly<Record<string, string>> = {
  need_below_floor: 'the routine spared too little need on it for a score to mean anything',
};

const ROLE_WORDS: Readonly<Record<ArmRole, string>> = {
  candidate: 'A model deciding for them',
  control: 'The same model, run again',
  one: 'The score\'s 1',
  zero: 'The score\'s 0',
};

/** An arm as a sentence names it: a model by the name the server gives it, an anchor by its description. */
export const armName = (arm: ComparisonArm): string =>
  arm.decider.kind === 'model' ? arm.decider.name : arm.description;

/** A decimal as the server wrote it, with a true minus sign and never rounded to a bound. */
export const scoreText = (value: string | null): string =>
  value === null ? 'no score' : value.startsWith('-') ? `−${value.slice(1)}` : value;
const signed = (value: string): string => (value.startsWith('-') ? scoreText(value) : `+${value}`);
const seconds = (ms: number | null): string => (ms === null ? '–' : `${(ms / 1000).toFixed(1)} s`);

/**
 * What the primary pair's models answered, in the verdict's own sentence: each one's answered
 * share, and, by the server's word, whether the two differ by more than the same model's two runs.
 */
function answeredClause(result: ComparisonResult): string {
  if (result.primary === null) return '';
  const [first, second] = result.primary.map((key) => result.arms.find((arm) => arm.key === key));
  const share = (arm: ComparisonArm | undefined): string | null => {
    const shares = arm === undefined ? null : result.summaries[arm.key]?.reliability?.shares ?? null;
    return arm === undefined || arm.decider.kind !== 'model' || shares === null ? null : shares.answered;
  };
  const [one, two] = [share(first), share(second)];
  if (one === null || two === null) return '';
  const both = `${armName(first!)} answered ${percentText(one)} of its turns and ${armName(second!)} ${percentText(two)}`;
  switch (result.verdict.answeredSharesDiffer) {
    case true: return `; but ${both}, further apart than the same model's two runs, so the routine decided more of one's turns`;
    case false: return `; ${both}, no further apart than the same model's two runs`;
    default: return `; ${both}`;
  }
}

/** What each verdict says after its heading, filled from the server's numbers. */
export function verdictDetail(result: ComparisonResult): string {
  const name = (key: string): string => {
    const arm = result.arms.find((held) => held.key === key);
    return arm === undefined ? key : armName(arm);
  };
  const primary = result.primary === null ? undefined : result.differences.find(
    (d) => d.first === result.primary![0] && d.second === result.primary![1]);
  const range = primary === undefined ? ''
    : ` ${name(primary.second)} minus ${name(primary.first)}: ${signed(primary.mean)}, from ${scoreText(primary.low)} to ${scoreText(primary.high)}.`;
  const answered = answeredClause(result);
  switch (result.verdict.code) {
    case 'different':
      return `${name(result.verdict.higher!)}'s people fared better, by more than the same model varies when it runs the same hour twice (${scoreText(result.controlBound)})${answered}.${range}`;
    case 'no_measured_difference':
      return `On the registered seeds this comparison cannot tell how the people fared under the two apart: the difference is inside its interval, or no larger than the same model varies between two runs${answered}.${range}`;
    case 'not_judged':
      return `${NOT_JUDGED_WORDS[result.verdict.reason ?? ''] ?? 'No difference is claimed from it.'}${answered === '' ? '' : ` ${answered.slice(2, 3).toUpperCase()}${answered.slice(3)}.`}${range}`;
    case 'incomplete':
      return 'A run of this comparison has no result, so nothing is claimed from it.';
  }
}

/** Each mechanism a model is asked by, in words. */
export const MECHANISM_WORDS: Readonly<Record<AnsweringMechanism, string>> = {
  tool_call: 'a forced call',
  json_schema: 'a JSON schema',
};

/** Whose order a model is asked in, in words. */
export const ANSWERING_SOURCE_WORDS: Readonly<Record<AnsweringSource, string>> = {
  model: 'the order measured for this model',
  contract: 'the contract\'s order',
};

/** How a model was asked, in words; empty where nothing records it. */
export function answeringWords(answering: Answering | null): string {
  return answering === null ? ''
    : `Asked by ${MECHANISM_WORDS[answering.mechanism]}, ${ANSWERING_SOURCE_WORDS[answering.source]}.`;
}

/** Who decides for somebody outside the group in every arm, in words. */
function otherDeciderWords(other: OtherPerson): string {
  if (other.decider.kind !== 'model') return 'their own routine';
  const asked = other.answering === null ? '' : `, asked by ${MECHANISM_WORDS[other.answering.mechanism]}`;
  return `${other.decider.name}, the model you chose for them${asked}`;
}

/** Who a comparison compares: its group, and what decides for everybody else in every arm. */
export function groupWords(result: ComparisonResult): string {
  const people = result.group.people;
  const who = people === null || result.group.source.kind === 'everyone'
    ? 'everybody in this world'
    : `${people.map((person) => person.name).join(', ')} (${GROUP_SOURCE_WORDS[result.group.source.kind]})`;
  const others = result.others.map((other) => `${other.name}: ${otherDeciderWords(other)}`);
  return `Each arm decides for ${who}.${others.length === 0 ? ''
    : ` Everybody else keeps the same decider in every arm: ${others.join('; ')}.`}${
    result.othersAsked ? ` ${OTHERS_ASKED_WORDS}` : ''}`;
}

/**
 * What a model outside the group means for the score, said wherever the server says one decides
 * for somebody there: only a development comparison can have one.
 */
export const OTHERS_ASKED_WORDS = 'A model you chose for somebody outside the group is asked in every arm, the routine\'s and waiting\'s runs included, so here a model that answers nothing does not score exactly the routine\'s 1, and the routine\'s choice points move with that model\'s answers too. A judged comparison keeps everybody outside its group on their routine.';

/** The arms a comparison shows first: its registered pair, else its first two candidates. */
export function defaultSides(result: ComparisonResult): { readonly left: string; readonly right: string } {
  const candidates = result.arms.filter((arm) => arm.role === 'candidate');
  if (candidates.length >= 2) return { left: candidates[0]!.key, right: candidates[1]!.key };
  if (result.primary !== null) return { left: result.primary[0], right: result.primary[1] };
  return { left: result.arms[0]!.key, right: result.arms[1]!.key };
}

/**
 * Who decided a person's latest turn at or before `minute` in one run, in words: the arm's decider
 * for a person of the group, and for anybody else the decider they keep in every arm.
 */
export function decidedWords(run: RunReplay, arm: ComparisonArm, subjectId: string, minute: number): string {
  const person = run.people.find((held) => held.id === subjectId);
  const outside = person !== undefined && !person.inGroup;
  const decider = outside ? person.decider : arm.decider;
  const keeps = outside ? ' They are outside the group, so they keep it in every arm.' : '';
  if (decider.kind === 'routine') return `Their own routine decides everything they do in this run.${keeps}`;
  if (decider.kind === 'wait') return 'In this run they wait wherever they are; nothing decides for them.';
  const latest = [...run.decisions].reverse()
    .find((d: RunDecision) => d.subjectId === subjectId && d.tick <= minute);
  if (latest === undefined) return `${decider.name} has not been asked for them yet.${keeps}`;
  if (latest.disposition === 'applied') {
    return `${decider.name} chose at minute ${latest.tick}: ${latest.chose ?? 'one of the things they could do'}.${keeps}`;
  }
  const why = latest.status === 'accepted' ? latest.dispositionReason ?? latest.reason : latest.reason;
  return `Their routine chose at minute ${latest.tick}, because ${DECISION_WORDS[why] ?? `of a reason this page has no words for (${why})`}.${keeps}`;
}

/** One kind of minute and how many of the group spent any minute of the run in it. */
export interface GroupActivity {
  readonly minuteClass: MinuteClass;
  readonly words: string;
  readonly people: number;
}

/**
 * What the group did over one run, counted from its replay: for each kind of minute (walking,
 * waiting, or an activity the routine names), how many of the group spent at least one minute in
 * it, most first. A person counts once under each kind they did, so the counts add up to more than
 * the group. Only people of the group are counted; everybody else keeps one decider in every arm.
 */
export function groupActivity(run: RunReplay): { readonly group: number; readonly kinds: readonly GroupActivity[] } {
  const inGroup = new Set(run.people.filter((person) => person.inGroup).map((person) => person.id));
  // By the words a person reads: walking a path and an activity the routine also calls walking are
  // one row, counting each person once, under the kind of minute the first of them was.
  const did = new Map<string, { minuteClass: MinuteClass; people: Set<string> }>();
  for (const minute of run.minutes) {
    for (const person of minute.people) {
      if (!inGroup.has(person.id)) continue;
      const found = minuteClass(run, person);
      const words = classWords(run, found);
      const held = did.get(words) ?? { minuteClass: found, people: new Set<string>() };
      held.people.add(person.id);
      did.set(words, held);
    }
  }
  const kinds = [...did.entries()]
    .map(([words, held]) => ({ minuteClass: held.minuteClass, words, people: held.people.size }))
    .sort((a, b) => b.people - a.people || a.words.localeCompare(b.words));
  return { group: inGroup.size, kinds };
}

export interface ComparisonDay {
  readonly seedDigest: string;
  readonly left: string;
  readonly right: string;
}

export interface SocietyComparisonView {
  readonly root: HTMLElement;
  /** Where the controls that start a comparison go, above the list. */
  readonly startSlot: HTMLElement;
  /** List the version's comparisons, `selected` open. */
  showList(listings: readonly ComparisonListing[], selected: string | null): void;
  /** Show a comparison's numbers and verdict, and which day and sides are chosen. */
  showResult(result: ComparisonResult, day: ComparisonDay): void;
  /** Draw the chosen day's two runs on one clock; a side whose run did not complete says why. */
  showDay(left: RunReplay | null, right: RunReplay | null): void;
  /** Say a read failed or is under way, in words, in the part of the view it belongs to. */
  status(part: 'list' | 'result' | 'day', title: string, detail: string): void;
  dispose(): void;
}

function seedLabel(seed: ComparisonSeed, index: number): string {
  const name = seed.name ?? `Seed ${index + 1}`;
  return seed.excluded === null ? name : `${name} (no score: ${EXCLUDED_WORDS[seed.excluded] ?? seed.excluded})`;
}

/** When a comparison was defined, in the reader's own time and words. */
const when = (iso: string): string =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

function listingRow(listing: ComparisonListing, selected: boolean, onOpen: () => void): HTMLElement {
  const models = listing.arms.filter((arm) => arm.role === 'candidate');
  const button = el('button', {
    type: 'button',
    class: 'comparison-listing',
    'aria-pressed': String(selected),
    'data-comparison-id': listing.comparisonId,
  }, [
    el('ul', { class: 'comparison-listing-models' }, models.map((arm) => el('li', { text: armName(arm), title: arm.description }))),
    el('span', {
      text: `${listing.phase === 'held_out' ? 'Held-out seeds' : 'Development seeds'}, ${listing.seeds} ${listing.seeds === 1 ? 'seed' : 'seeds'}, ${listing.group.source.kind === 'everyone' ? 'everybody' : `a group of ${listing.group.size}`}, ${listing.runsCompleted} of ${listing.runsExpected} runs completed`,
    }),
    el('time', { datetime: listing.createdAt, text: when(listing.createdAt) }),
    ...((progress) => (progress === null ? [] : [el('span', { class: 'comparison-listing-progress', text: progress })]))(
      progressWords(listing),
    ),
  ]);
  button.addEventListener('click', onOpen);
  return button;
}

function armsTable(result: ComparisonResult): HTMLElement {
  const head = el('tr', {}, ['Arm', 'How the group fared', 'Interval', 'What its model answered',
    'Left to the routine, per choice point of the routine\'s own run', 'Cost for the hour', 'Answer time']
    .map((label) => el('th', { scope: 'col', text: label })));
  const rows = result.arms.map((arm) => {
    const summary = result.summaries[arm.key];
    const interval = summary?.interval ?? null;
    return el('tr', { 'data-arm': arm.key, 'data-role': arm.role }, [
      el('th', { scope: 'row' }, [
        el('span', { class: 'comparison-arm-name', text: armName(arm), title: arm.description }),
        el('span', { class: 'comparison-arm-role', text: ROLE_WORDS[arm.role] }),
        ...(arm.answering === null ? []
          : [el('span', { class: 'comparison-arm-answering', text: answeringWords(arm.answering) })]),
      ]),
      el('td', { class: 'comparison-number', text: scoreText(summary?.meanScore ?? null) }),
      el('td', {
        class: 'comparison-number',
        text: interval === null ? 'fewer than two seeds scored' : `${scoreText(interval.low)} to ${scoreText(interval.high)}`,
      }),
      el('td', { class: 'comparison-reliability' }, [
        el('span', { text: reliabilityWords(arm, summary?.reliability ?? null) }),
        el('span', { class: 'comparison-reasons', text: reasonWords(summary?.reliability ?? null) }),
      ]),
      el('td', { class: 'comparison-rate', text: routineRateWords(arm, summary?.reliability ?? null, result.scoreVersion) }),
      el('td', {
        class: 'comparison-number',
        text: summary?.costUsdPerHour === null || summary === undefined ? 'nothing asked'
          : `$${summary.costUsdPerHour}${summary.costKnown ? '' : ' at most'}`,
      }),
      el('td', {
        class: 'comparison-number',
        text: summary === undefined || summary.latencyMs.p50 === null ? '–'
          : `${seconds(summary.latencyMs.p50)} typical, ${seconds(summary.latencyMs.p95)} slowest twentieth`,
      }),
    ]);
  });
  return el('table', { class: 'comparison-arms' }, [
    el('caption', { text: 'Each arm over every seed: how the group fared (the mean score and the middle of its resampled means) and, beside it, what its model answered' }),
    el('thead', {}, [head]),
    el('tbody', {}, rows),
  ]);
}

function seedsTable(result: ComparisonResult): HTMLElement {
  const head = el('tr', {}, [el('th', { scope: 'col', text: 'Seed' }),
    ...result.arms.map((arm) => el('th', { scope: 'col', text: armName(arm) }))]);
  const rows = result.seeds.map((seed, index) => el('tr', { 'data-seed-digest': seed.seedDigest }, [
    el('th', { scope: 'row', text: seedLabel(seed, index) }),
    ...result.arms.map((arm) => {
      const run = seed.runs[arm.key];
      if (run === undefined || run.status !== 'completed') {
        const text = run === undefined || run.status === 'incomplete' ? 'not run'
          : `failed: ${FAILURE_WORDS[run.failure ?? ''] ?? run.failure ?? 'no reason recorded'}`;
        return el('td', { class: 'comparison-number', 'data-status': run?.status ?? 'incomplete', text });
      }
      return el('td', { class: 'comparison-number', 'data-status': run.status }, [
        el('span', { class: 'comparison-score', text: scoreText(run.score) }),
        el('span', { class: 'comparison-reliability', text: reliabilityWords(arm, run.reliability) }),
      ]);
    }),
  ]));
  return el('table', { class: 'comparison-seeds' }, [
    el('caption', { text: 'Each seed: the same start, the same people, the same hour' }),
    el('thead', {}, [head]),
    el('tbody', {}, rows),
  ]);
}

function differencesList(result: ComparisonResult): HTMLElement {
  const name = (key: string): string => {
    const arm = result.arms.find((held) => held.key === key);
    return arm === undefined ? key : armName(arm);
  };
  return el('ul', { class: 'comparison-differences' }, result.differences.map((difference) => el('li', {
    'data-rejected': String(difference.rejected),
  }, [
    `${name(difference.second)} minus ${name(difference.first)}: ${signed(difference.mean)}, from ${scoreText(difference.low)} to ${scoreText(difference.high)}`,
  ])));
}

/**
 * The acts a society of things records (a line said, a thing picked up, put down, given or taken),
 * each counted once per person of the group who did it, from the run's own events. They are kinds of
 * things people did, as the sixth score weighs them; each takes the palette's next colour after the
 * run's own activities, and its words are the catalog's outcome words.
 */
export function groupActs(run: RunReplay): readonly { readonly act: string; readonly words: string; readonly people: number; readonly minuteClass: MinuteClass }[] {
  const inGroup = new Set(run.people.filter((person) => person.inGroup).map((person) => person.id));
  return REPORTED_ACTS.flatMap((act, index) => {
    const people = new Set(run.events.filter((event) => event.kind === act && inGroup.has(event.subjectId)).map((event) => event.subjectId));
    const words = outcomeWords(act);
    return people.size === 0 || words === undefined ? [] : [{
      act, words, people: people.size, minuteClass: `activity-${run.activities.length + index}` as MinuteClass,
    }];
  });
}

/** What the group did in one run, as a list a person reads down: each kind, and how many did it. */
function didList(run: RunReplay): HTMLElement {
  const { group, kinds } = groupActivity(run);
  const capital = (words: string): string => `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
  return el('div', { class: 'comparison-side-did' }, [
    el('p', { class: 'comparison-side-did-head', text: `What the group of ${group} did` }),
    el('ul', {}, [
      ...kinds.map((kind) => el('li', { 'data-class': kind.minuteClass }, [
        el('span', { class: 'comparison-side-did-kind', text: capital(kind.words) }),
        el('span', { class: 'comparison-side-did-count', text: `${kind.people} of ${group}` }),
      ])),
      ...groupActs(run).map((kind) => el('li', { 'data-class': kind.minuteClass, 'data-act': kind.act }, [
        el('span', { class: 'comparison-side-did-kind', text: capital(kind.words) }),
        el('span', { class: 'comparison-side-did-count', text: `${kind.people} of ${group}` }),
      ])),
    ]),
  ]);
}

/** How lines are compared, said once under the reported section. */
export const NEAR_REPEAT_WORDS = 'A line counts as nearly the same as an earlier line when at least half of the different words the '
  + 'two lines use between them are in both: compared with every line the same person said earlier in the hour, and with '
  + 'the line they were answering, the last one said to them or to everyone near them that they heard before they spoke.';

/** One seed's reported counts for one side, in a quiet line; null where the run reports none. */
export function seedReportedWords(reported: ReportedCounts | null | undefined): string | null {
  if (reported == null) return null;
  const { said, nearRepeats } = reported.lines;
  const lines = said === 0 ? 'no lines said'
    : `${said} ${said === 1 ? 'line' : 'lines'} said, ${nearRepeats} nearly the same as an earlier line`;
  const gave = reported.acts.gave;
  const handed = gave === 0 ? 'nothing handed over' : `${gave} ${gave === 1 ? 'thing' : 'things'} handed over`;
  return `On this seed: ${lines}; ${handed}. Reported, not judged.`;
}

/** A hand move that did not happen, as a row reads it: the catalog's row words, else its event reason's words. */
function handMoveWords(reason: string): string {
  return optionalPhrase(`hand_move_${reason}`) ?? eventReasonWords(reason) ?? 'for a reason not recorded in words';
}

/**
 * What each model's people said and did with their hands, over the comparison's seeds: reported,
 * never weighed, in its own quieter section under the verdict. One column for each arm a model
 * decides, and the routine's from its own recorded counts: in a group where all of them are 0 it
 * says so in words ("The routine never speaks"), and where it has none recorded its column is left
 * out. A row whose count is 0 for every column is left out. Null for a comparison that reports none.
 */
export function reportedSection(result: ComparisonResult): HTMLElement | null {
  const asked = result.arms.filter((arm) => arm.role === 'candidate' || arm.role === 'control');
  const counts = asked.map((arm) => result.summaries[arm.key]?.reported ?? null);
  if (counts.every((held) => held === null)) return null;
  const one = result.arms.find((arm) => arm.role === 'one') ?? null;
  const routineCounts = one === null ? null : result.summaries[one.key]?.reported ?? null;
  const routine = routineCounts === null ? null : one;
  const zero = (held: ReportedCounts | null): ReportedCounts => held ?? {
    acts: { said: 0, picked_up: 0, put_down: 0, gave: 0, took: 0 }, lines: { said: 0, nearRepeats: 0 }, handsMissed: {},
  };
  const all = counts.map(zero);
  const everyColumn = routineCounts === null ? all : [...all, routineCounts];
  const reasons = [...new Set(everyColumn.flatMap((held) => Object.keys(held.handsMissed)))]
    .sort((a, b) => everyColumn.reduce((n, held) => n + (held.handsMissed[b] ?? 0), 0)
      - everyColumn.reduce((n, held) => n + (held.handsMissed[a] ?? 0), 0));
  type Row = { readonly words: string; readonly sub: boolean; readonly value: (held: ReportedCounts) => number };
  const lineRows: Row[] = [
    { words: 'Lines said', sub: false, value: (held) => held.lines.said },
    { words: 'nearly the same as an earlier line', sub: true, value: (held) => held.lines.nearRepeats },
  ];
  const handRows: Row[] = [
    { words: 'Things handed to someone', sub: false, value: (held) => held.acts.gave },
    { words: 'Things taken from someone', sub: false, value: (held) => held.acts.took },
    { words: 'Things picked up', sub: false, value: (held) => held.acts.picked_up },
    { words: 'Things put down', sub: false, value: (held) => held.acts.put_down },
    { words: 'Hand moves that did not happen', sub: false, value: (held) => Object.values(held.handsMissed).reduce((n, v) => n + v, 0) },
    ...reasons.map((reason) => ({ words: handMoveWords(reason), sub: true, value: (held: ReportedCounts) => held.handsMissed[reason] ?? 0 })),
  ];
  const shown = (rows: Row[]) => rows.filter((row) => everyColumn.some((held) => row.value(held) > 0));
  // The routine's words for a group are said only where its own record has 0 in every row of it.
  const groups = [
    { rows: shown(lineRows), never: 'The routine never speaks' },
    { rows: shown(handRows), never: 'The routine never uses its hands' },
  ].filter((group) => group.rows.length > 0)
    .map((group) => ({ ...group, routineSaysNever: routineCounts !== null && group.rows.every((row) => row.value(routineCounts) === 0) }));
  const seeds = result.seeds.length;
  return el('section', { class: 'comparison-reported' }, [
    el('h4', { class: 'comparison-reported-head', text: 'Words and hands: reported, not judged' }),
    el('p', {
      class: 'comparison-reported-why',
      text: `What each model's people said and did with their hands, over ${seeds === 1 ? 'the seed' : `all ${seeds} seeds`}. `
        + 'None of this decides who fared better. Lines are counted here, not read: open a person\'s hour below to read what they said.',
    }),
    el('details', { class: 'comparison-reported-rule' }, [
      el('summary', { text: 'How lines are compared' }),
      el('p', { text: NEAR_REPEAT_WORDS }),
    ]),
    el('table', { class: 'comparison-reported-table' }, [
      el('thead', {}, [el('tr', {}, [
        el('th', { scope: 'col' }, [el('span', { class: 'comparison-reported-hidden', text: 'What was counted' })]),
        ...asked.map((arm) => el('th', { scope: 'col', text: armName(arm) })),
        ...(routine === null ? [] : [el('th', { scope: 'col', text: armName(routine) })]),
      ])]),
      el('tbody', {}, groups.flatMap((group) => group.rows.map((row, index) => el('tr', { 'data-sub': String(row.sub) }, [
        el('th', { scope: 'row', text: row.words }),
        ...all.map((held) => el('td', { text: String(row.value(held)) })),
        ...(routineCounts === null ? []
          : group.routineSaysNever
            ? (index > 0 ? [] : [el('td', { class: 'comparison-reported-routine', rowspan: String(group.rows.length), text: group.never })])
            : [el('td', { text: String(row.value(routineCounts)) })]),
      ])))),
    ]),
  ]);
}

/** The Compare view. Every choice is a handler: the view reads nothing itself. */
export function buildSocietyComparisonView(handlers: {
  readonly onClose: () => void;
  readonly onRecordedResult?: () => void;
  readonly onComparison: (comparisonId: string) => void;
  readonly onDay: (day: ComparisonDay) => void;
}): SocietyComparisonView {
  const startSlot = el('div', { class: 'comparison-start-slot' });
  const list = el('nav', { class: 'comparison-list', 'aria-label': 'Comparisons of this world' });
  const summary = el('section', { class: 'comparison-summary', 'aria-live': 'polite' });
  const dayPart = el('section', { class: 'comparison-day' });
  const closer = el('button', { type: 'button', class: 'comparison-close' }, [
    'Back to the world', el('kbd', { class: 'x-shortcut', text: 'Esc' }),
  ]);
  closer.addEventListener('click', () => handlers.onClose());
  const receipt = el('button', {
    type: 'button', class: 'comparison-receipt', text: 'Open a result from a receipt',
  });
  receipt.addEventListener('click', () => handlers.onRecordedResult?.());
  const root = el('section', {
    class: 'society-comparison',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-labelledby': 'society-comparison-title',
  }, [
    el('header', { class: 'comparison-head' }, [
      closer,
      el('div', {}, [
        el('h2', { id: 'society-comparison-title', class: 'comparison-title', text: 'Compare models' }),
        el('p', {
          class: 'comparison-note',
          text: 'Give the same people the same starting hour, then see what each model chose.',
        }),
      ]),
    ]),
    el('div', { class: 'comparison-scroll' }, [
      startSlot, list,
      ...(handlers.onRecordedResult === undefined ? [] : [receipt]),
      summary, dayPart,
    ]),
  ]);
  root.hidden = true;
  let frame = 0;
  let disposed = false;
  let current: { result: ComparisonResult; day: ComparisonDay } | null = null;
  const stop = () => { if (frame !== 0) cancelAnimationFrame(frame); frame = 0; };
  const state = (part: HTMLElement, title: string, detail: string) => replace(part, [
    el('div', { class: 'comparison-state' }, [el('h3', { text: title }), el('p', { text: detail })]),
  ]);

  return {
    root,
    startSlot,
    status(part, title, detail) {
      if (part === 'day') stop();
      state(part === 'list' ? list : part === 'result' ? summary : dayPart, title, detail);
    },
    showList(listings, selected) {
      if (listings.length === 0) {
        state(list, 'No comparison of this world yet',
          'Start a comparison above to see what different models chose for the same people.');
        return;
      }
      replace(list, [
        el('h3', { text: 'Comparisons of this world' }),
        ...listings.map((listing) => listingRow(listing, listing.comparisonId === selected,
          () => handlers.onComparison(listing.comparisonId))),
      ]);
    },
    showResult(result, day) {
      current = { result, day };
      const choose = (key: 'left' | 'right') => {
        const select = el('select', { class: 'comparison-side-select', 'aria-label': key === 'left' ? 'Left side' : 'Right side' },
          result.arms.map((arm) => el('option', { value: arm.key, text: armName(arm), selected: arm.key === day[key] })));
        select.addEventListener('change', () => handlers.onDay({ ...day, [key]: select.value }));
        return select;
      };
      const seedSelect = el('select', { class: 'comparison-seed-select', 'aria-label': 'Seed' },
        result.seeds.map((seed, index) => el('option', {
          value: seed.seedDigest, text: seedLabel(seed, index), selected: seed.seedDigest === day.seedDigest,
        })));
      seedSelect.addEventListener('change', () => handlers.onDay({ ...day, seedDigest: seedSelect.value }));
      const named = result.group.people;
      const groupSize = named === null || result.group.source.kind === 'everyone' ? null : named.length;
      const eyebrow = [
        groupSize === null ? 'Everybody here' : `The same ${groupSize === 1 ? 'person' : `${groupSize} people`}`,
        'the same start',
        result.seeds.length === 1 ? 'one simulated hour' : `one simulated hour on each of ${result.seeds.length} seeds`,
      ].join(' · ');
      replace(summary, [
        el('section', { class: 'comparison-verdict', 'data-verdict': result.verdict.code }, [
          el('div', { class: 'comparison-eyebrow', text: eyebrow }),
          ...(result.start === null ? [] : [el('p', {
            class: 'comparison-progress',
            text: startWords(result.start, result.seeds.reduce((finished, seed) =>
              finished + Object.values(seed.runs).filter((run) => run.status !== 'incomplete').length, 0)),
          })]),
          el('h3', { text: VERDICT_WORDS[result.verdict.code] }),
          el('p', { class: 'comparison-verdict-detail', text: verdictDetail(result) }),
          el('details', { class: 'comparison-who' }, [
            el('summary', { text: 'Who it decides for' }),
            el('p', { class: 'comparison-group', text: groupWords(result) }),
          ]),
          ...(result.preregistration === null ? [] : [el('p', {
            class: 'comparison-registration',
            text: `Registered before it ran: ${result.preregistration.record}`,
          })]),
        ]),
        ...[reportedSection(result)].filter((section): section is HTMLElement => section !== null),
        el('div', { class: 'comparison-choose' }, [
          el('label', {}, [el('span', { text: 'Seed' }), seedSelect]),
          el('label', {}, [el('span', { text: 'Left' }), choose('left')]),
          el('label', {}, [el('span', { text: 'Right' }), choose('right')]),
        ]),
        el('details', { class: 'comparison-numbers' }, [
          el('summary', { text: 'Every number from this comparison' }),
          armsTable(result),
          ...(result.differences.length === 0 ? [] : [
            el('h3', { text: 'Registered differences' }), differencesList(result)]),
          seedsTable(result),
        ]),
      ]);
    },
    showDay(leftRun, rightRun) {
      stop();
      if (current === null) return;
      const { result, day } = current;
      const arms = new Map(result.arms.map((arm) => [arm.key, arm] as const));
      const seed = result.seeds.find((found) => found.seedDigest === day.seedDigest);
      const sides = [
        { arm: arms.get(day.left)!, run: leftRun, record: seed?.runs[day.left] },
        { arm: arms.get(day.right)!, run: rightRun, record: seed?.runs[day.right] },
      ] as const;
      if (leftRun === null || rightRun === null) {
        replace(dayPart, sides.map(({ arm, run, record }) => el('article', { class: 'comparison-side', 'data-arm': arm.key }, [
          el('h3', { class: 'comparison-side-name', text: armName(arm), title: arm.description }),
          el('p', {
            text: run !== null ? 'Recorded, and replayed.'
              : record?.status === 'failed'
                ? `This run failed: ${FAILURE_WORDS[record.failure ?? ''] ?? record.failure ?? 'no reason recorded'}.`
                : 'This run has no recorded hour to show.',
          }),
        ])));
        return;
      }
      const last = Math.min(leftRun.minutes.length, rightRun.minutes.length) - 1;
      let clock = 0;
      let playing = false;
      let speed = 1;
      let selected: { side: 0 | 1; id: string } | null = null;
      const inspector = createLivingWorldInspector();
      const inspectorSide = el('p', { class: 'comparison-inspector-side' });
      const pick = (side: 0 | 1, id: string) => { selected = { side, id }; render(); };
      const plans = sides.map(({ arm, run }, side) =>
        buildComparisonPlan(run!, `${armName(arm)}: the place from above`, (id) => pick(side as 0 | 1, id)));
      const strips = buildComparisonStrips(leftRun, rightRun, [armName(sides[0].arm), armName(sides[1].arm)],
        (side, id, minute) => { clock = minute; playing = false; pick(side, id); });
      const scrubber = el('input', {
        type: 'range', min: 0, max: last, step: 'any', value: 0,
        class: 'comparison-scrubber', 'aria-label': 'Simulated minute',
      });
      const minuteLabel = el('output', { class: 'comparison-minute' });
      const play = el('button', { type: 'button', class: 'comparison-play', text: 'Play' });
      const speeds = [1, 2, 4].map((factor) => {
        const button = el('button', {
          type: 'button', class: 'comparison-speed', text: `${factor}×`, 'aria-pressed': String(factor === speed),
        });
        button.addEventListener('click', () => {
          speed = factor;
          for (const other of speeds) other.setAttribute('aria-pressed', String(other === button));
        });
        return button;
      });
      const render = () => {
        if (disposed) return;
        plans.forEach((plan) => plan.draw(clock, selected?.id ?? null));
        strips.draw(clock, selected?.id ?? null);
        scrubber.value = String(clock);
        minuteLabel.textContent = `Minute ${Math.floor(clock)} of ${last}`;
        play.textContent = playing ? 'Pause' : 'Play';
        if (selected === null) {
          inspector.clear();
          inspectorSide.textContent = 'Choose a person on either side to see what they did and who decided.';
          return;
        }
        const { run, arm } = sides[selected.side];
        const { index } = minuteAt(run!, clock);
        const minute = run!.minutes[index]!;
        const person = minute.people.find((p) => p.id === selected!.id);
        if (person === undefined) { inspector.clear(); return; }
        const name = run!.people.find((p) => p.id === person.id)?.name ?? 'Someone';
        const doing = classWords(run!, minuteClass(run!, person));
        const livingNeeds = run!.needThresholds && person.needs
          ? Object.entries(person.needs).map(([key, value]) => {
            const threshold = run!.needThresholds?.[key];
            return `${livingNeedLabel(key)}: ${threshold === undefined ? 'recorded' : value >= threshold ? 'needs attention' : 'comfortable'}`;
          }).join(', ')
          : null;
        inspectorSide.textContent = `${selected.side === 0 ? 'Left' : 'Right'}: ${armName(arm)}, minute ${minute.tick}`;
        inspector.show({
          subject: person.id,
          title: name,
          description: 'A simulated person in this recorded run: invented for this world, and nothing they do is a memory.',
          activity: `${doing.slice(0, 1).toUpperCase()}${doing.slice(1)}. ${decidedWords(run!, arm, person.id, minute.tick)}`,
          details: [
            [livingNeeds === null ? 'Tiredness' : 'Needs', livingNeeds ?? `${person.needMilli} of 1000; they prefer to rest from ${run!.threshold}`],
            ['Doing', livingNeeds === null ? `${person.action} (${person.status}), ${person.reason.replaceAll('_', ' ')}` : doing],
            ['Heading for', person.goal === null ? 'nowhere yet'
              : run!.targets.find((t) => t.targetId === person.goal!.targetId)?.label ?? person.goal.kind],
            ['Run', livingNeeds === null ? `${run!.runId} (${arm.key})` : armName(arm)],
          ],
        });
      };
      let previous = 0;
      const tick = (now: number) => {
        if (disposed || !playing) { frame = 0; return; }
        const elapsed = previous === 0 ? 0 : (now - previous) / 1000;
        previous = now;
        // One simulated minute per second at 1x: an hour in a minute, slow enough to follow a walk.
        clock = Math.min(last, clock + elapsed * speed);
        if (clock >= last) playing = false;
        render();
        frame = playing ? requestAnimationFrame(tick) : 0;
      };
      play.addEventListener('click', () => {
        playing = !playing;
        if (playing && clock >= last) clock = 0;
        previous = 0;
        render();
        if (playing && frame === 0) frame = requestAnimationFrame(tick);
      });
      scrubber.addEventListener('input', () => { clock = Number(scrubber.value); playing = false; render(); });
      replace(dayPart, [
        el('div', { class: 'comparison-sides' }, sides.map(({ arm }, side) =>
          el('article', {
            class: 'comparison-side', 'data-arm': arm.key, 'data-side': side === 0 ? 'left' : 'right',
            'data-run-id': sides[side]!.run!.runId,
          }, [
            el('header', { class: 'comparison-side-head' }, [
              el('p', { class: 'comparison-side-role', text: ROLE_WORDS[arm.role] }),
              el('h3', { class: 'comparison-side-name', text: armName(arm), title: arm.description }),
              el('p', {
                class: 'comparison-side-score',
                text: `How the group fared on this seed: ${scoreText(seed?.runs[arm.key]?.score ?? null)}`,
              }),
              el('p', {
                class: 'comparison-reliability',
                text: reliabilityWords(arm, seed?.runs[arm.key]?.reliability ?? null),
              }),
            ]),
            didList(sides[side]!.run!),
            ...[seedReportedWords(seed?.runs[sides[side]!.arm.key]?.reported)].filter((line): line is string => line !== null)
              .map((line) => el('p', { class: 'comparison-side-reported', text: line })),
            el('details', { class: 'comparison-from-above' }, [
              el('summary', { text: 'See them from above' }),
              plans[side]!.root,
            ]),
          ]))),
        el('div', { class: 'comparison-clock' }, [play, ...speeds, scrubber, minuteLabel]),
        el('div', { class: 'comparison-detail' }, [
          strips.root,
          el('aside', { class: 'comparison-inspector' }, [inspectorSide, inspector.root]),
        ]),
      ]);
      render();
    },
    dispose() {
      disposed = true;
      stop();
      root.remove();
    },
  };
}
