/**
 * A Companion plan's steps, read as registry actions.
 *
 * Each step names a typed action (`place_object`, `advance` ...) from the planner's vocabulary
 * (`exulanica/selection/action_plan.py`). That word picks the registry entry, so a step and the
 * rail button or panel control for the same action share their words, icon, availability and
 * refusal words. The registry also picks the route: the request goes to the entry's own operation,
 * never to a route the plan names. The plan supplies only what fills that route: its path values,
 * its body and the pins inside it. A step whose typed action maps to no entry, or whose route key
 * differs from its entry's operation, is refused here and never sent.
 */

import type { FromEarlier, PlanStep } from '../../companion-actions-api.js';
import { actionSpec, type ActionSpec } from './registry.js';

/**
 * Every word of the planner's vocabulary, and the registry entry it is sent as. `null` is a word
 * deliberately not sent from a plan: an appearance change is reviewed in Design before it is
 * applied (atlas-world-customization-contract.md 7), and `other` is the planner saying it cannot
 * express the request, which it never prepares as a step.
 */
export const PLAN_ACTIONS: Readonly<Record<string, string | null>> = Object.freeze({
  place_object: 'objects.place',
  move_object: 'objects.move',
  remove_object: 'objects.remove',
  undo_last_edit: 'objects.undo',
  place_arrangement: 'arrangements.place',
  play: 'clock.play',
  pause: 'clock.pause',
  set_speed: 'clock.speed',
  advance: 'clock.advance',
  bring_people: 'people.bring-in',
  propose_appearance: null,
  apply_appearance: null,
  other: null,
});

/** The request one planned step sends, built from its registry entry. */
export interface PlannedRequest {
  readonly actionId: string;
  readonly stepIndex: number;
  readonly method: string;
  /** The entry's route with the plan's path values; the world scope is the page's to add. */
  readonly path: string;
  readonly body: Readonly<Record<string, unknown>>;
}

export type PlannedRefusal =
  /** The typed action is not in the vocabulary, or is one a plan never sends. */
  | { readonly kind: 'unmapped'; readonly action: string }
  /** The plan names another route than the registry entry's own. */
  | { readonly kind: 'route-mismatch'; readonly action: string; readonly planned: string; readonly registry: string }
  /** A path value or a body value the step needs is not there, or not in the earlier response. */
  | { readonly kind: 'missing-value'; readonly action: string; readonly field: string };

/** The registry entry a step is sent as, or why it is not sent. */
export function plannedEntry(step: PlanStep): { readonly spec: ActionSpec } | { readonly refused: PlannedRefusal } {
  const action = step.action.operation;
  const id = Object.hasOwn(PLAN_ACTIONS, action) ? PLAN_ACTIONS[action] : null;
  if (id === null || id === undefined) return { refused: { kind: 'unmapped', action } };
  const spec = actionSpec(id);
  if (spec.operation !== step.operation) {
    return { refused: { kind: 'route-mismatch', action, planned: step.operation, registry: spec.operation ?? '' } };
  }
  return { spec };
}

/** A value at a dotted path in an earlier step's response, or undefined. */
function earlierValue(earlier: readonly unknown[], from: FromEarlier): unknown {
  let value: unknown = earlier[from.step];
  for (const part of from.field.split('.')) {
    if (value === null || typeof value !== 'object') return undefined;
    value = (value as Record<string, unknown>)[part];
  }
  return value;
}

/**
 * The request a step sends: its entry's method and route, the route's path values from the plan
 * (or from an earlier response where the plan says so), and the plan's body with any value it
 * takes from an earlier response filled in. `earlier` holds the responses of the steps already
 * sent, by step index.
 */
export function plannedRequest(
  step: PlanStep,
  earlier: readonly unknown[],
): { readonly request: PlannedRequest } | { readonly refused: PlannedRefusal } {
  const entry = plannedEntry(step);
  if ('refused' in entry) return entry;
  const action = step.action.operation;
  const [method, template] = entry.spec.operation!.split(' ', 2) as [string, string];
  let path = template;
  for (const name of template.match(/\{([a-z_]+)\}/g)?.map((key) => key.slice(1, -1)) ?? []) {
    const from = step.bindFrom?.[name];
    const value = from === undefined ? step.bind[name] : earlierValue(earlier, from);
    if (typeof value !== 'string' || value.length === 0) return { refused: { kind: 'missing-value', action, field: name } };
    path = path.replace(`{${name}}`, encodeURIComponent(value));
  }
  const body: Record<string, unknown> = { ...(step.body ?? {}) };
  for (const [field, from] of Object.entries(step.bodyFrom ?? {})) {
    const value = earlierValue(earlier, from);
    if (value === undefined || value === null) return { refused: { kind: 'missing-value', action, field } };
    body[field] = value;
  }
  return { request: Object.freeze({ actionId: entry.spec.id, stepIndex: step.index, method, path, body: Object.freeze(body) }) };
}
