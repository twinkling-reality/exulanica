/**
 * The Companion's plan, on the sheet: each step as the action it is, the plan's spending said
 * before its one confirmation, and what became of each step once confirmed.
 *
 * A step is drawn from its registry entry (`ui/actions/planned.ts`): the same label and icon as
 * that action's rail button or panel control, and the same words for why it is not available.
 * Nothing important sits behind a disclosure: only the requests' route keys, the plan's digest and
 * any code go into the technical record.
 */

import type { ActionPlan, PlanClarification, PlanStep } from '../companion-actions-api.js';
import { el } from './dom.js';
import { plannedEntry } from './actions/planned.js';
import type { RefusalWords } from './actions/registry.js';
import { button, panel, stateChip, technicalRecord, type InterfaceState } from './system/components.js';
import { icon, type IconName } from './system/icon.js';
import { PLAN_CLARIFY_SLOT_WORDS, PLAN_CLARIFY_WORDS, PLAN_HANDS_WORDS, PLAN_WORDS, pieceEstimateWords } from './words/companion-plan.js';
import { filled, isObjectActivity, objectActivity } from '../society-activity-words.js';

/** A step's words before anything is sent: what it is and whether it can be sent now. */
export interface PlanStepView {
  readonly index: number;
  readonly label: string;
  readonly icon: IconName;
  /** The particular of this step in words (which object, which minute), or null. */
  readonly detail: string | null;
  /** Why it cannot be sent now, in the action's words, or null when it can. */
  readonly held: { readonly state: InterfaceState; readonly words: RefusalWords } | null;
}

export type StepProgress =
  /** `when` says what it waits for, under the row: the world's next minute. */
  | { readonly kind: 'waiting'; readonly when?: string }
  | { readonly kind: 'running' }
  | { readonly kind: 'done' }
  | { readonly kind: 'not-done'; readonly words: RefusalWords; readonly code: string | null }
  | { readonly kind: 'not-reached' };

export interface PlanSheetOptions {
  readonly onConfirm: () => void;
  readonly onCancel: () => void;
  /** A clarification answered with one of its candidates. */
  readonly onChoose: (clarification: PlanClarification, value: string) => void;
  /** Play the world again, through the registry's Play, after a chain left it paused. */
  readonly onPlay: () => void;
}

export interface PlanSheet {
  readonly root: HTMLElement;
  /** Show a plan to check: its steps, its spending and Confirm. */
  showPlan(plan: ActionPlan, steps: readonly PlanStepView[], utterance: string): void;
  /** Show a question the plan needs answered first, with its candidates. */
  showClarification(plan: ActionPlan, utterance: string, candidateLabel: (value: string, title: string) => string): void;
  /** Say why nothing can be planned, with Close: a clarification answered into a refusal. */
  say(words: RefusalWords): void;
  /** One step's progress after Confirm. */
  setStep(index: number, progress: StepProgress): void;
  /** The plan's end: how many steps happened, and Play when the world was left paused. */
  finish(done: number, all: number, offerPlay: boolean): void;
  close(): void;
}

const PROGRESS_LOOK: Readonly<Record<StepProgress['kind'], { state: InterfaceState; words: string }>> = {
  waiting: { state: 'queued', words: 'Waiting' },
  running: { state: 'running', words: 'Working' },
  done: { state: 'ready', words: PLAN_WORDS.didHappen },
  'not-done': { state: 'failed', words: PLAN_WORDS.notDone },
  'not-reached': { state: 'cancelled', words: PLAN_WORDS.notReached },
};

/**
 * A place's served title with its article: "the well", "the bakery at number 12"; a title that
 * already says one ("a place", the server's words for a place no one named) is kept as it is.
 */
export function thePlace(title: string): string {
  return /^(a|an|the) /iu.test(title) ? title : `the ${title}`;
}

/**
 * A thing step's particulars in words, from the labels the server's reads gave it: "Knight, beside
 * the well", "Knight, go to the well", "Traveller, rest at the bench". An activity's words are the
 * catalog's (`society-activity-words.ts`), never restated.
 */
export function thingDetail(step: PlanStep): string | null {
  const titles = step.titles;
  const capital = (words: string): string => words.charAt(0).toUpperCase() + words.slice(1);
  // New pieces: the things they are for, as the server's reads label them ("gate, sword, well").
  if (step.action.operation === 'request_pieces' && titles['kinds'] !== undefined) return capital(titles['kinds']);
  if (step.action.operation === 'place_thing' && titles['kind'] !== undefined) {
    const near = titles['near'];
    if (near === undefined) return capital(titles['kind']);
    const being = String(step.action['near'] ?? '').startsWith('being:');
    return `${capital(titles['kind'])}, beside ${being ? near : `the ${near}`}`;
  }
  // A being asked to use their hands: the thing by its kind's label, the other being by name.
  const hands = step.action.operation === 'direct_thing' ? PLAN_HANDS_WORDS[titles['act'] ?? ''] : undefined;
  if (hands !== undefined && titles['subject'] !== undefined && titles['thing'] !== undefined
    && (!hands.includes('{with}') || titles['with'] !== undefined)) {
    return hands.replace('{subject}', titles['subject']).replace('{thing}', titles['thing'])
      .replace('{with}', titles['with'] ?? '');
  }
  if (step.action.operation === 'direct_thing' && titles['subject'] !== undefined && titles['place'] !== undefined) {
    const place = thePlace(titles['place']);
    if (titles['act'] === 'go_to') return `${titles['subject']}, go to ${place}`;
    const activity = titles['affordance'];
    const words = activity !== undefined && isObjectActivity(activity)
      ? filled(objectActivity(activity).verbAtPlace, { place }) : `use ${place}`;
    return `${titles['subject']}, ${words}`;
  }
  return null;
}

/** A step's own particulars in words: the minute of a chain, a speed. Objects are the caller's. */
export function stepDetail(step: PlanStep): string | null {
  const thing = thingDetail(step);
  if (thing !== null) return thing;
  const action = step.action;
  if (action.operation === 'advance' && typeof action['minute'] === 'number' && typeof action['minutes'] === 'number') {
    return `Minute ${action['minute']} of ${action['minutes']}`;
  }
  if ((action.operation === 'set_speed' || action.operation === 'play') && typeof action['speed'] === 'number') {
    return `At ${action['speed']}× speed`;
  }
  return null;
}

export function buildPlanSheet(options: PlanSheetOptions): PlanSheet {
  const surface = panel({
    id: 'companion-plan', title: PLAN_WORDS.title, icon: 'companion', role: 'dialog',
    className: 'companion-plan', onClose: options.onCancel,
  });
  surface.root.hidden = true;
  const rows = new Map<number, { readonly row: HTMLElement; readonly status: HTMLElement }>();
  let current: ActionPlan | null = null;

  const footer = (...buttons: HTMLButtonElement[]): void => {
    surface.footer.replaceChildren(...buttons);
    surface.footer.hidden = buttons.length === 0;
  };
  const record = (plan: ActionPlan, codes: Readonly<Record<string, string | null>> = {}): HTMLElement => technicalRecord({
    plan: plan.planSha256,
    kind: plan.kind,
    ...Object.fromEntries(plan.steps.map((step) => [`step ${step.index}`, `${step.action.operation} ${step.operation}`])),
    ...(plan.spendsBy.length === 0 ? {} : { spends_by: plan.spendsBy.join(', ') }),
    ...codes,
  });

  return {
    root: surface.root,
    showPlan(plan, steps, utterance) {
      current = plan;
      rows.clear();
      surface.title.textContent = PLAN_WORDS.title;
      const list = el('ol', { class: 'companion-plan-steps' });
      for (const step of steps) {
        const status = el('span', { class: 'companion-plan-status' });
        const row = el('li', { class: 'companion-plan-step', 'data-step': String(step.index) }, [
          icon(step.icon),
          el('span', { class: 'companion-plan-step-words' }, [
            el('span', { class: 'companion-plan-step-label', text: step.label }),
            ...(step.detail === null ? [] : [el('span', { class: 'companion-plan-step-detail', text: step.detail })]),
            ...(step.held === null ? [] : [el('span', { class: 'companion-plan-step-held', text: `${step.held.words.happened} ${step.held.words.next}` })]),
          ]),
          status,
        ]);
        if (step.held !== null) status.replaceChildren(stateChip(step.held.state));
        rows.set(step.index, { row, status });
        list.append(row);
      }
      const confirm = button({ label: PLAN_WORDS.confirm, icon: 'confirm', variant: 'primary', onClick: options.onConfirm });
      confirm.dataset['action'] = 'plan.confirm';
      confirm.disabled = steps.some((step) => step.held !== null);
      const cancel = button({ label: PLAN_WORDS.cancel, onClick: options.onCancel });
      cancel.dataset['action'] = 'plan.cancel';
      surface.body.replaceChildren(
        el('p', { class: 'companion-plan-utterance', text: `“${utterance}”` }),
        el('p', { class: 'companion-plan-intro', text: PLAN_WORDS.intro }),
        list,
        el('p', { class: 'companion-plan-spends', 'data-spends': String(plan.spends) }, [
          icon('spends', 'sm'), plan.spends ? PLAN_WORDS.spends : PLAN_WORDS.spendsNot,
        ]),
        // What new pieces would take, in time and money, before the one Confirm (GEN's estimate).
        ...plan.steps.flatMap((step) => (step.estimate === null ? [] : [
          el('p', { class: 'companion-plan-estimate', 'data-step': String(step.index) }, [
            icon('spends', 'sm'), pieceEstimateWords(step.estimate),
          ]),
        ])),
        el('p', { class: 'companion-plan-summary', role: 'status', 'aria-live': 'polite' }),
        record(plan),
      );
      footer(confirm, cancel);
      surface.root.hidden = false;
      confirm.focus({ preventScroll: true });
    },
    showClarification(plan, utterance, candidateLabel) {
      current = plan;
      rows.clear();
      const clarification = plan.clarification!;
      surface.title.textContent = PLAN_WORDS.clarifyTitle;
      const choices = el('div', { class: 'companion-plan-choices', role: 'group' },
        clarification.candidates.map((candidate) => {
          const choice = button({
            label: candidateLabel(candidate.value, candidate.title),
            variant: candidate.selected ? 'primary' : 'secondary',
            onClick: () => options.onChoose(clarification, candidate.value),
          });
          choice.dataset['action'] = 'plan.choose';
          return choice;
        }));
      const cancel = button({ label: PLAN_WORDS.cancel, onClick: options.onCancel });
      cancel.dataset['action'] = 'plan.cancel';
      surface.body.replaceChildren(
        el('p', { class: 'companion-plan-utterance', text: `“${utterance}”` }),
        el('p', { class: 'companion-plan-intro', text: PLAN_CLARIFY_SLOT_WORDS[`${clarification.code}:${clarification.slot ?? ''}`]
          ?? PLAN_CLARIFY_WORDS[clarification.code] ?? PLAN_CLARIFY_WORDS['asset_ambiguous']! }),
        ...(clarification.candidates.length === 0 ? [] : [choices]),
        record(plan, { clarification: clarification.code }),
      );
      footer(cancel);
      surface.root.hidden = false;
    },
    say(words) {
      rows.clear();
      // What it says is the plan's answer, not a question, whatever was asked before it.
      surface.title.textContent = PLAN_WORDS.title;
      const close = button({ label: PLAN_WORDS.close, onClick: options.onCancel });
      close.dataset['action'] = 'plan.close';
      surface.body.replaceChildren(el('p', { class: 'companion-plan-intro', role: 'status', text: `${words.happened} ${words.next}` }));
      footer(close);
      surface.root.hidden = false;
    },
    setStep(index, progress) {
      const found = rows.get(index);
      if (found === undefined) return;
      const look = PROGRESS_LOOK[progress.kind];
      found.row.dataset['progress'] = progress.kind;
      found.status.replaceChildren(stateChip(look.state, look.words));
      found.row.querySelector('.companion-plan-step-held')?.remove();
      found.row.querySelector('.companion-plan-step-when')?.remove();
      if (progress.kind === 'waiting' && progress.when !== undefined) {
        found.row.querySelector('.companion-plan-step-words')?.append(
          el('span', { class: 'companion-plan-step-when', text: progress.when }),
        );
      }
      if (progress.kind === 'not-done') {
        found.row.querySelector('.companion-plan-step-words')?.append(
          el('span', { class: 'companion-plan-step-held', text: `${progress.words.happened} ${progress.words.next}` }),
        );
        if (progress.code !== null && current !== null) {
          surface.body.querySelector('.x-technical')?.replaceWith(record(current, { [`code at step ${index}`]: progress.code }));
        }
      }
    },
    finish(done, all, offerPlay) {
      const summary = surface.body.querySelector<HTMLElement>('.companion-plan-summary');
      const said = done === all ? PLAN_WORDS.done
        : done === 0 ? PLAN_WORDS.none
          : PLAN_WORDS.partly.replace('{done}', String(done)).replace('{all}', String(all));
      summary?.replaceChildren(
        ...(done > 0 && done < all ? [stateChip('partial')] : []),
        ` ${said}`,
        ...(offerPlay ? [` ${PLAN_WORDS.pausedOffer}`] : []),
      );
      const close = button({ label: PLAN_WORDS.close, onClick: options.onCancel });
      close.dataset['action'] = 'plan.close';
      if (offerPlay) {
        const play = button({ label: 'Play', icon: 'play', variant: 'primary', onClick: options.onPlay });
        play.dataset['action'] = 'clock.play';
        footer(play, close);
      } else {
        footer(close);
      }
    },
    close() {
      surface.root.hidden = true;
      current = null;
    },
  };
}

/** A step's words before anything is sent, from its registry entry; null where it is never sent. */
export function plannedStepView(
  step: PlanStep,
  label: (spec: { readonly label: string }) => string,
  held: (actionId: string) => PlanStepView['held'],
  particular: (step: PlanStep) => string | null,
): PlanStepView {
  const entry = plannedEntry(step);
  if ('refused' in entry) {
    return {
      index: step.index, label: PLAN_WORDS.unsentLabel, icon: 'warning', detail: null,
      held: { state: 'unavailable', words: { happened: PLAN_WORDS.notSentRoute, next: PLAN_WORDS.none } },
    };
  }
  return {
    index: step.index,
    label: label(entry.spec),
    icon: entry.spec.icon,
    detail: particular(step) ?? stepDetail(step),
    held: held(entry.spec.id),
  };
}
