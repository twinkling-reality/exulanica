/** A mountable, read-only presentation of one exact society experiment attempt. */

import type { TransportOptions } from '@exulanica/graph-client';
import {
  SocietyExperimentClient,
  SocietyExperimentContractError,
  type ArmMetrics,
  type ExperimentAttempt,
  type ExperimentDefinition,
  type ExperimentRatio,
  type RawRatio,
  type SocietyExperimentBinding,
  type SocietyExperimentReadPort,
  type ValidExperimentResult,
} from '../society-experiment-api.js';
import { el, replace } from '../ui/dom.js';

export interface SocietyExperimentComparisonOptions {
  readonly parent?: HTMLElement;
  readonly credentials?: TransportOptions;
  readonly client?: SocietyExperimentReadPort;
}

export type SocietyExperimentViewStatus =
  | 'idle'
  | 'loading'
  | 'available'
  | 'unavailable'
  | 'incomplete'
  | 'failed'
  | 'invalid';

export interface MountedSocietyExperimentComparison {
  readonly root: HTMLElement;
  readonly status: SocietyExperimentViewStatus;
  readonly binding: SocietyExperimentBinding | null;
  load(binding: SocietyExperimentBinding): Promise<void>;
  dispose(): void;
}

const STYLE = `
.society-experiment-comparison {
  color: var(--ink, #202a2f); background: var(--atlas-plane, #f5f8f7f2);
  border: 1px solid var(--edge, #c5cfd2); border-radius: var(--radius-panel, 4px);
  box-shadow: var(--app-shadow, 0 8px 32px #24203312); overflow: auto;
  font: 400 .875rem/1.5 var(--ui-font-body, system-ui, sans-serif);
}
.society-experiment-comparison * { box-sizing: border-box; }
.experiment-view-body { display: grid; gap: 1rem; padding: clamp(1rem, 3vw, 1.5rem); }
.experiment-view-head { display: grid; gap: .35rem; }
.experiment-view-kicker { margin: 0; color: var(--ink-faint, #66747a); font-size: .68rem; font-weight: 650; letter-spacing: .14em; text-transform: uppercase; }
.experiment-view-title { margin: 0; font: 500 clamp(1.25rem, 3vw, 1.75rem)/1.15 var(--ui-font-display, system-ui, sans-serif); letter-spacing: -.018em; }
.experiment-view-note, .experiment-state p { margin: 0; color: var(--ink-soft, #4e5d64); max-width: 72ch; }
.experiment-state { display: grid; gap: .5rem; padding: 1rem; border: 1px solid var(--edge, #c5cfd2); background: color-mix(in srgb, var(--raised, #fff) 74%, transparent); }
.experiment-state h3 { margin: 0; font: 600 1rem/1.3 var(--ui-font-display, system-ui, sans-serif); }
.experiment-status-code { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .78rem; overflow-wrap: anywhere; }
.experiment-binding { border-top: 1px solid var(--edge, #c5cfd2); padding-top: .75rem; }
.experiment-binding summary { color: var(--ink-soft, #4e5d64); cursor: pointer; font-weight: 600; }
.experiment-binding summary:focus-visible { outline: 2px solid var(--focus, #294955); outline-offset: 3px; }
.experiment-binding dl { display: grid; grid-template-columns: minmax(8rem, auto) 1fr; gap: .35rem 1rem; margin: .75rem 0 0; }
.experiment-binding dt { color: var(--ink-faint, #66747a); }
.experiment-binding dd { margin: 0; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .72rem; overflow-wrap: anywhere; }
.experiment-ledger { overflow-x: auto; border: 1px solid var(--edge, #c5cfd2); background: color-mix(in srgb, var(--raised, #fff) 74%, transparent); }
.experiment-ledger table { width: 100%; min-width: 42rem; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.experiment-ledger caption { padding: .8rem .9rem; color: var(--ink-soft, #4e5d64); text-align: left; font-size: .75rem; }
.experiment-ledger th, .experiment-ledger td { padding: .62rem .8rem; border-top: 1px solid var(--edge, #c5cfd2); text-align: left; vertical-align: top; }
.experiment-ledger thead th { border-top: 0; color: var(--ink-faint, #66747a); font-size: .7rem; letter-spacing: .08em; text-transform: uppercase; }
.experiment-ledger tbody th { width: 29%; font-weight: 550; }
.experiment-ledger td { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .78rem; }
.experiment-ledger .experiment-delta { border-left: 2px solid var(--accent, #40545d); }
.experiment-unavailable { color: var(--ink-faint, #66747a); font-family: var(--ui-font-body, system-ui, sans-serif); font-style: italic; }
.experiment-limitations { display: grid; gap: .45rem; margin: 0; padding-left: 1.15rem; color: var(--ink-soft, #4e5d64); }
.experiment-limitations strong { color: var(--ink, #202a2f); font-weight: 600; }
.experiment-loading-line { height: 2px; background: linear-gradient(90deg, transparent, var(--accent, #40545d), transparent); background-size: 200% 100%; animation: experiment-read 1.4s linear infinite; }
@keyframes experiment-read { to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .experiment-loading-line { animation: none; background: var(--accent, #40545d); } }
@media (max-width: 38rem) {
  .experiment-view-body { padding: 1rem; }
  .experiment-binding dl { grid-template-columns: 1fr; gap: .1rem; }
  .experiment-binding dd + dt { margin-top: .45rem; }
}
`;

const code = (value: string): HTMLElement => el('span', { class: 'experiment-status-code', text: value });

function ratioText(value: ExperimentRatio): Node {
  if ('availability' in value) {
    return el('span', { class: 'experiment-unavailable', text: `Unavailable${value.reason ? `: ${value.reason}` : ''}` });
  }
  if (value.denominator === null) {
    return el('span', { class: 'experiment-unavailable', text: `Unavailable: ${value.numerator} / denominator absent` });
  }
  if (value.denominator === 0) {
    return el('span', { class: 'experiment-unavailable', text: `Unavailable: ${value.numerator} / 0` });
  }
  return document.createTextNode(`${value.numerator} / ${value.denominator}`);
}

function scalar(value: number): RawRatio {
  return Object.freeze({ numerator: value, denominator: 1 });
}

interface MetricRow {
  readonly label: string;
  readonly baseline: ExperimentRatio;
  readonly treatment: ExperimentRatio;
  readonly delta: ExperimentRatio | null;
}

function metricRows(result: ValidExperimentResult): readonly MetricRow[] {
  return [
    { label: 'High-fatigue person-minutes', baseline: result.baseline.highFatiguePersonMinutes,
      treatment: result.treatment.highFatiguePersonMinutes, delta: result.comparison.highFatigueFraction },
    { label: 'High-fatigue relative change', baseline: { availability: 'not_present', reason: 'comparison only' },
      treatment: { availability: 'not_present', reason: 'comparison only' }, delta: result.comparison.highFatigueRelativeChange },
    { label: 'Completed rest activities / person-minute', baseline: result.baseline.completedRestActivities,
      treatment: result.treatment.completedRestActivities, delta: result.comparison.completedRestRate },
    { label: 'All-rest occupancy', baseline: result.baseline.allRestOccupancy,
      treatment: result.treatment.allRestOccupancy, delta: result.comparison.allRestOccupancyFraction },
    { label: 'Focus-rest occupancy', baseline: result.baseline.focusRestOccupancy,
      treatment: result.treatment.focusRestOccupancy, delta: null },
    { label: 'Travel mm / inhabitant', baseline: result.baseline.travelMmPerInhabitant,
      treatment: result.treatment.travelMmPerInhabitant, delta: result.comparison.travelMmPerInhabitant },
    { label: 'Fatigue median, milli-units', baseline: scalar(result.baseline.fatigueMilli.medianNearestRank),
      treatment: scalar(result.treatment.fatigueMilli.medianNearestRank), delta: result.comparison.fatigueMedianMilli },
    { label: 'Fatigue p95, milli-units', baseline: scalar(result.baseline.fatigueMilli.p95NearestRank),
      treatment: scalar(result.treatment.fatigueMilli.p95NearestRank), delta: result.comparison.fatigueP95Milli },
  ];
}

function ledger(result: ValidExperimentResult): HTMLElement {
  const body = el('tbody');
  for (const metric of metricRows(result)) {
    body.append(el('tr', {}, [el('th', { scope: 'row', text: metric.label }),
      el('td', {}, [ratioText(metric.baseline)]), el('td', {}, [ratioText(metric.treatment)]),
      el('td', { class: 'experiment-delta' }, [metric.delta === null
        ? el('span', { class: 'experiment-unavailable', text: 'Unavailable: no compact delta' })
        : ratioText(metric.delta)])]));
  }
  const table = el('table', {}, [
    el('caption', { text: 'Exact integers as recorded. Delta is treatment minus baseline.' }),
    el('thead', {}, [el('tr', {}, [el('th', { scope: 'col', text: 'Measure' }),
      el('th', { scope: 'col', text: 'Baseline' }), el('th', { scope: 'col', text: 'Treatment' }),
      el('th', { scope: 'col', class: 'experiment-delta', text: 'Treatment − baseline' })])]), body,
  ]);
  return el('div', { class: 'experiment-ledger' }, [table]);
}

function safetyLedger(baseline: ArmMetrics, treatment: ArmMetrics): HTMLElement {
  const rows: readonly [string, number, number][] = [
    ['Stationary collisions', baseline.safety.stationaryCollisions, treatment.safety.stationaryCollisions],
    ['Over-capacity destination ticks', baseline.safety.overCapacityDestinationTicks, treatment.safety.overCapacityDestinationTicks],
    ['Transition refusals', baseline.safety.transitionRefusals, treatment.safety.transitionRefusals],
    ['Minimum distinct positions', baseline.safety.minimumDistinctPositions, treatment.safety.minimumDistinctPositions],
  ];
  return el('div', { class: 'experiment-ledger' }, [el('table', {}, [
    el('caption', { text: 'Safety observations. The compact result does not publish safety deltas.' }),
    el('thead', {}, [el('tr', {}, [el('th', { scope: 'col', text: 'Observation' }),
      el('th', { scope: 'col', text: 'Baseline' }), el('th', { scope: 'col', text: 'Treatment' }),
      el('th', { scope: 'col', class: 'experiment-delta', text: 'Delta' })])]),
    el('tbody', {}, rows.map(([label, left, right]) => el('tr', {}, [el('th', { scope: 'row', text: label }),
      el('td', { text: left }), el('td', { text: right }),
      el('td', { class: 'experiment-delta' }, [el('span', { class: 'experiment-unavailable', text: 'Not published' })])]))),
  ])]);
}

function bindings(
  definition: ExperimentDefinition,
  attempt: { readonly attemptId: string; readonly seedSha256?: string; readonly checkpointSha256?: string | null },
): HTMLElement {
  const values: [string, string][] = [
    ['World', definition.worldId], ['Authored version', definition.versionId],
    ['Experiment', definition.experimentId], ['Attempt', attempt.attemptId],
    ['Definition SHA-256', definition.definitionSha256],
    ['Baseline input', `${definition.baselineInputSeq} · ${definition.baselineInputSha256}`],
    ['Treatment input', `${definition.treatmentInputSeq} · ${definition.treatmentInputSha256}`],
  ];
  if (attempt.seedSha256 !== undefined) values.splice(5, 0, ['Seed SHA-256', attempt.seedSha256]);
  if (attempt.checkpointSha256 !== undefined && attempt.checkpointSha256 !== null) {
    values.push(['Checkpoint SHA-256', attempt.checkpointSha256]);
  }
  return el('details', { class: 'experiment-binding' }, [el('summary', { text: 'Exact record bindings' }),
    el('dl', {}, values.flatMap(([label, value]) => [el('dt', { text: label }), el('dd', { text: value })]))]);
}

function heading(definition?: ExperimentDefinition): HTMLElement {
  const intervention = definition?.intervention.kind === 'add_rest_amenity'
    ? `One rest amenity added at ${definition.intervention.targetId}`
    : definition?.intervention.kind === 'noop' ? 'No-op control' : 'Bound attempt comparison';
  return el('header', { class: 'experiment-view-head' }, [
    el('p', { class: 'experiment-view-kicker', text: 'Controlled society experiment' }),
    el('h2', { class: 'experiment-view-title', text: intervention }),
    el('p', { class: 'experiment-view-note', text: 'A compact read of one exact development attempt. No simulation is run from this view.' }),
  ]);
}

function statusPanel(title: string, detail: string, extra: readonly Node[] = []): HTMLElement {
  return el('section', { class: 'experiment-state' }, [el('h3', { text: title }), el('p', { text: detail }), ...extra]);
}

function validView(definition: ExperimentDefinition, attempt: Extract<ExperimentAttempt, { status: 'completed' }>, result: ValidExperimentResult): Node[] {
  const unsupported = result.unsupportedMetrics.length === 0 ? [] : [
    el('ul', { class: 'experiment-limitations' }, result.unsupportedMetrics.map(metric =>
      el('li', {}, [el('strong', { text: `${metric.metric}: ` }), metric.reason]))),
  ];
  return [heading(definition), statusPanel('Server-recorded pair validation',
    'The server recorded this pair as valid, and this reader verified its canonical result digest and bindings. This is not an independent arithmetic proof, scientific significance, or a prediction of real people. Compact results do not contain enough evidence to replay the simulation.'),
  ledger(result), safetyLedger(result.baseline, result.treatment), ...unsupported,
  bindings(definition, attempt)];
}

function availableView(definition: ExperimentDefinition, attempt: ExperimentAttempt): { status: SocietyExperimentViewStatus; nodes: Node[] } {
  if (attempt.status === 'incomplete') return { status: 'incomplete', nodes: [heading(definition),
    statusPanel('Attempt is incomplete', 'The reservation exists, but no immutable terminal outcome has been recorded. Nothing is interpreted as an effect.'),
    bindings(definition, attempt)] };
  if (attempt.status === 'failed') return { status: 'failed', nodes: [heading(definition),
    statusPanel('Attempt failed', attempt.failure.detail, [code(attempt.failure.code), code(attempt.failureSha256)]),
    bindings(definition, attempt)] };
  if (attempt.result.status === 'invalid_pair') return { status: 'invalid', nodes: [heading(definition),
    statusPanel('Comparison is invalid', 'The result refused this baseline/treatment pair. No arm metrics or effect are shown.',
      attempt.result.reasons.flatMap(reason => [code(reason.code), el('p', { text: reason.detail })])),
    bindings(definition, attempt)] };
  return { status: 'available', nodes: validView(definition, attempt, attempt.result) };
}

/**
 * Mount a comparison surface. `load` replaces the exact binding and cancels the previous read;
 * a late response is ignored even when an injected test/client does not honor AbortSignal.
 */
export function mountSocietyExperimentComparison(
  options: SocietyExperimentComparisonOptions,
): MountedSocietyExperimentComparison {
  if (!options.client && !options.credentials) throw new Error('Experiment comparison needs authenticated transport');
  const client = options.client ?? new SocietyExperimentClient(options.credentials!);
  const root = el('section', { class: 'society-experiment-comparison', 'aria-live': 'polite', 'data-status': 'idle' });
  const style = el('style'); style.textContent = STYLE;
  const body = el('div', { class: 'experiment-view-body' }, [heading(),
    statusPanel('No attempt loaded', 'Provide an authored version, experiment and attempt identity to read an existing result.')]);
  root.append(style, body); options.parent?.append(root);
  let status: SocietyExperimentViewStatus = 'idle';
  let binding: SocietyExperimentBinding | null = null;
  let request: AbortController | null = null;
  let generation = 0;
  let disposed = false;
  const show = (next: SocietyExperimentViewStatus, nodes: readonly Node[]): void => {
    if (disposed) return;
    status = next; root.dataset['status'] = next; replace(body, nodes);
  };
  const api: MountedSocietyExperimentComparison = {
    root,
    get status() { return status; },
    get binding() { return binding; },
    async load(next) {
      if (disposed) throw new Error('Society experiment comparison is disposed');
      request?.abort(); const controller = new AbortController(); request = controller; const mine = ++generation;
      binding = Object.freeze({ ...next });
      show('loading', [heading(), el('div', { class: 'experiment-loading-line', 'aria-hidden': 'true' }),
        statusPanel('Reading bound attempt', 'Checking the immutable definition and nested attempt.')]);
      try {
        const read = await client.read(binding, controller.signal);
        if (disposed || mine !== generation || controller.signal.aborted) return;
        if (read.status === 'unavailable') {
          show('unavailable', [heading(read.definition ?? undefined),
            statusPanel('Experiment unavailable', read.problem.detail, [code(read.problem.code)]),
            ...(read.definition === null ? [] : [bindings(read.definition, { attemptId: read.binding.attemptId })])]);
          return;
        }
        const rendered = availableView(read.definition, read.attempt);
        show(rendered.status, rendered.nodes);
      } catch (error) {
        if (disposed || mine !== generation || controller.signal.aborted || (error instanceof DOMException && error.name === 'AbortError')) return;
        const detail = error instanceof SocietyExperimentContractError
          ? `The response could not be verified. ${error.message}`
          : error instanceof Error ? error.message : 'The request failed.';
        show('unavailable', [heading(), statusPanel('Experiment unavailable', detail)]);
      }
    },
    dispose() {
      if (disposed) return;
      disposed = true; generation += 1; request?.abort(); request = null; binding = null;
      status = 'idle'; root.dataset['status'] = 'idle'; root.remove();
    },
  };
  return api;
}
