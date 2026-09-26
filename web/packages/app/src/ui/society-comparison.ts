/**
 * The same hour of a world, run by two deciders, side by side on one clock.
 *
 * It builds elements and holds no client: the mount hands it the server's comparison reads and the
 * runs it replayed, and routes each choice through a handler. Every number is the server's, shown
 * as written and never clipped, so a score below 0 (worse than waiting) or above 1 (better than
 * the routine) reads as it is. Whether two arms differ is the server's verdict, read by its code;
 * nothing here compares two numbers to decide it.
 */

import type {
  ArmRole,
  ComparisonArm,
  ComparisonListing,
  ComparisonResult,
  ComparisonSeed,
  RunDecision,
  RunReplay,
  VerdictCode,
} from '../society-comparison-api.js';
import { DECISION_WORDS } from '../society-inhabitant-words.js';
import { el, replace } from './dom.js';
import { createLivingWorldInspector } from './living-world-inspector.js';
import { buildComparisonPlan, classWords, minuteAt, minuteClass } from './society-comparison-plan.js';
import { buildComparisonStrips } from './society-comparison-strips.js';
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
};

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
  switch (result.verdict.code) {
    case 'different':
      return `${name(result.verdict.higher!)}'s people fared better, by more than the same model varies when it runs the same hour twice (${scoreText(result.controlBound)}).${range}`;
    case 'no_measured_difference':
      return `On the registered seeds this comparison cannot tell the two apart: the difference is inside its interval, or no larger than the same model varies between two runs.${range}`;
    case 'not_judged':
      return `${NOT_JUDGED_WORDS[result.verdict.reason ?? ''] ?? 'No difference is claimed from it.'}${range}`;
    case 'incomplete':
      return 'A run of this comparison has no result, so nothing is claimed from it.';
  }
}

/** The arms a comparison shows first: its registered pair, else its first two candidates. */
export function defaultSides(result: ComparisonResult): { readonly left: string; readonly right: string } {
  const candidates = result.arms.filter((arm) => arm.role === 'candidate');
  if (candidates.length >= 2) return { left: candidates[0]!.key, right: candidates[1]!.key };
  if (result.primary !== null) return { left: result.primary[0], right: result.primary[1] };
  return { left: result.arms[0]!.key, right: result.arms[1]!.key };
}

/** Who decided a person's latest turn at or before `minute` in one run, in words. */
export function decidedWords(run: RunReplay, arm: ComparisonArm, subjectId: string, minute: number): string {
  if (arm.decider.kind === 'routine') return 'Their own routine decides everything they do in this run.';
  if (arm.decider.kind === 'wait') return 'In this run they wait wherever they are; nothing decides for them.';
  const latest = [...run.decisions].reverse()
    .find((d: RunDecision) => d.subjectId === subjectId && d.tick <= minute);
  if (latest === undefined) return `${armName(arm)} has not been asked for them yet.`;
  if (latest.disposition === 'applied') {
    return `${armName(arm)} chose at minute ${latest.tick}: ${latest.chose ?? 'one of the things they could do'}.`;
  }
  const why = latest.status === 'accepted' ? latest.dispositionReason ?? latest.reason : latest.reason;
  return `Their routine chose at minute ${latest.tick}, because ${DECISION_WORDS[why] ?? `of a reason this page has no words for (${why})`}.`;
}

export interface ComparisonDay {
  readonly seedDigest: string;
  readonly left: string;
  readonly right: string;
}

export interface SocietyComparisonView {
  readonly root: HTMLElement;
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
      text: `${listing.phase === 'held_out' ? 'Held-out seeds' : 'Development seeds'}, ${listing.seeds} ${listing.seeds === 1 ? 'seed' : 'seeds'}, ${listing.runsCompleted} of ${listing.runsExpected} runs completed`,
    }),
    el('time', { datetime: listing.createdAt, text: when(listing.createdAt) }),
  ]);
  button.addEventListener('click', onOpen);
  return button;
}

function armsTable(result: ComparisonResult): HTMLElement {
  const head = el('tr', {}, ['Arm', 'Score', 'Interval', 'Share of turns the model did not decide', 'Cost for the hour', 'Answer time']
    .map((label) => el('th', { scope: 'col', text: label })));
  const rows = result.arms.map((arm) => {
    const summary = result.summaries[arm.key];
    const interval = summary?.interval ?? null;
    return el('tr', { 'data-arm': arm.key, 'data-role': arm.role }, [
      el('th', { scope: 'row' }, [
        el('span', { class: 'comparison-arm-name', text: armName(arm), title: arm.description }),
        el('span', { class: 'comparison-arm-role', text: ROLE_WORDS[arm.role] }),
      ]),
      el('td', { class: 'comparison-number', text: scoreText(summary?.meanScore ?? null) }),
      el('td', {
        class: 'comparison-number',
        text: interval === null ? 'fewer than two seeds scored' : `${scoreText(interval.low)} to ${scoreText(interval.high)}`,
      }),
      el('td', { class: 'comparison-number', text: summary?.notAppliedShare ?? 'none asked' }),
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
    el('caption', { text: 'Each arm over every seed: the mean score and the middle of its resampled means' }),
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
      const text = run === undefined || run.status === 'incomplete' ? 'not run'
        : run.status === 'failed' ? `failed: ${FAILURE_WORDS[run.failure ?? ''] ?? run.failure ?? 'no reason recorded'}`
          : scoreText(run.score);
      return el('td', { class: 'comparison-number', 'data-status': run?.status ?? 'incomplete', text });
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

/** The Compare view. Every choice is a handler: the view reads nothing itself. */
export function buildSocietyComparisonView(handlers: {
  readonly onClose: () => void;
  readonly onComparison: (comparisonId: string) => void;
  readonly onDay: (day: ComparisonDay) => void;
}): SocietyComparisonView {
  const list = el('nav', { class: 'comparison-list', 'aria-label': 'Comparisons of this world' });
  const summary = el('section', { class: 'comparison-summary', 'aria-live': 'polite' });
  const dayPart = el('section', { class: 'comparison-day' });
  const closer = el('button', { type: 'button', class: 'comparison-close', text: '← Return' });
  closer.addEventListener('click', () => handlers.onClose());
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
          text: 'The same hour of this world, decided by different open models, replayed from what each run recorded. Nothing here asks a model.',
        }),
      ]),
    ]),
    el('div', { class: 'comparison-scroll' }, [list, summary, dayPart]),
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
    status(part, title, detail) {
      if (part === 'day') stop();
      state(part === 'list' ? list : part === 'result' ? summary : dayPart, title, detail);
    },
    showList(listings, selected) {
      if (listings.length === 0) {
        state(list, 'No comparison of this world yet',
          'A comparison is run by the local compare command; this view reads what it recorded.');
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
      replace(summary, [
        el('section', { class: 'comparison-verdict', 'data-verdict': result.verdict.code }, [
          el('h3', { text: VERDICT_WORDS[result.verdict.code] }),
          el('p', { text: verdictDetail(result) }),
          ...(result.preregistration === null ? [] : [el('p', {
            class: 'comparison-registration',
            text: `Registered before it ran: ${result.preregistration.record}`,
          })]),
        ]),
        armsTable(result),
        ...(result.differences.length === 0 ? [] : [
          el('h3', { text: 'Registered differences' }), differencesList(result)]),
        seedsTable(result),
        el('div', { class: 'comparison-choose' }, [
          el('label', {}, [el('span', { text: 'Seed' }), seedSelect]),
          el('label', {}, [el('span', { text: 'Left' }), choose('left')]),
          el('label', {}, [el('span', { text: 'Right' }), choose('right')]),
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
        inspectorSide.textContent = `${selected.side === 0 ? 'Left' : 'Right'}: ${armName(arm)}, minute ${minute.tick}`;
        inspector.show({
          subject: person.id,
          title: name,
          description: 'A simulated person in this recorded run: invented for this world, and nothing they do is a memory.',
          activity: `${doing.slice(0, 1).toUpperCase()}${doing.slice(1)}. ${decidedWords(run!, arm, person.id, minute.tick)}`,
          details: [
            ['Tiredness', `${person.needMilli} of 1000; they prefer to rest from ${run!.threshold}`],
            ['Doing', `${person.action} (${person.status}), ${person.reason.replaceAll('_', ' ')}`],
            ['Heading for', person.goal === null ? 'nowhere yet'
              : run!.targets.find((t) => t.targetId === person.goal!.targetId)?.label ?? person.goal.kind],
            ['Run', `${run!.runId} (${arm.key})`],
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
                text: `Score on this seed: ${scoreText(seed?.runs[arm.key]?.score ?? null)}`,
              }),
            ]),
            plans[side]!.root,
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
