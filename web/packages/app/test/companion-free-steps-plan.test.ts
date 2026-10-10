// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { parseActionPlan, type ActionPlan } from '../src/companion-actions-api.js';
import { PLAN_ACTIONS, plannedEntry, plannedRequest, stepAnswer } from '../src/ui/actions/planned.js';
import { actionSpec, availability } from '../src/ui/actions/registry.js';
import { stepDetail } from '../src/ui/companion-plan.js';

/*
 * The plan steps that spend nothing: a placed thing moved or taken away, a being played and given
 * back, everyone sent away and brought back. Each is sent as the registry's own action to its own
 * route. The plans here are the planner's own documents as the route's view serves them, written
 * by the scripted planner (tests/test_companion_free_steps_plan.py's world).
 */

const repository = `${process.cwd()}/..`;
const plan = (name: string): ActionPlan => parseActionPlan(
  JSON.parse(readFileSync(`${repository}/web/packages/app/test/companion-plans/${name}.json`, 'utf8')));
const VERSION = '00000000-0000-0000-0000-000000000007';
const KNIGHT = '00000000-0000-0000-0000-000000000001';

function request(name: string) {
  const [step] = plan(name).steps;
  const built = plannedRequest(step!, []);
  if ('refused' in built) throw new Error(JSON.stringify(built.refused));
  return { step: step!, request: built.request };
}

describe('a placed thing moved or taken away, as a planned step', () => {
  it('goes to the things routes with the plan’s pose and base', () => {
    const moved = request('free-move-thing-plan');
    expect(moved.request.actionId).toBe('things.move');
    expect(moved.request.path).toBe(`/world/versions/${VERSION}/things/well/move`);
    expect(moved.request.body['pose']).toMatchObject({ x_mm: 2000, y_mm: 0, z_mm: -1000 });
    expect(stepDetail(moved.step)).toBe('Well');
    const removed = request('free-remove-thing-plan');
    expect(removed.request.actionId).toBe('things.remove');
    expect(removed.request.path).toBe(`/world/versions/${VERSION}/things/well/remove`);
    expect(Object.keys(removed.request.body).sort()).toEqual(['base_state_sha256', 'saved_entry']);
  });

  it('answers the outcome read with the edit its request made', () => {
    const body = { edit_seq: 9, state_sha256: 'c'.repeat(64), things: [] };
    for (const name of ['free-move-thing-plan', 'free-remove-thing-plan']) {
      expect(stepAnswer(request(name).step.operation, { status: 200, body }))
        .toEqual({ status: 200, code: null, edit_seq: 9, state_sha256: 'c'.repeat(64) });
    }
  });

  it('has words for every code the planner can block either step with', () => {
    for (const id of ['things.move', 'things.remove']) {
      for (const code of ['invalid_object_state', 'invalid_thing_placement', 'no_free_place_near']) {
        expect(actionSpec(id).refusals?.[code]?.happened, `${id} ${code}`).toBeTruthy();
      }
    }
  });
});

describe('a being played and given back, as a planned step', () => {
  it('goes to the play routes, names the being and is never marked as spending', () => {
    const played = request('free-play-plan');
    expect(played.request.actionId).toBe('beings.play');
    expect(played.request.path).toBe(`/world/versions/${VERSION}/society/play`);
    expect(played.request.body['subject_id']).toBe(KNIGHT);
    expect(stepDetail(played.step)).toBe('Traveller');
    expect(played.step.spends).toBe(false);
    const given = request('free-give-back-plan');
    expect(given.request.actionId).toBe('beings.give-back');
    expect(given.request.path).toBe(`/world/versions/${VERSION}/society/play/${KNIGHT}/give-back`);
    expect(Object.keys(given.request.body)).toEqual(['idempotency_key']);
    for (const id of ['beings.play', 'beings.give-back']) {
      // No version's capability read lists a society's play routes: the plan step says whether.
      expect(availability(actionSpec(id), null)).toMatchObject({ state: 'available', spends: false });
    }
    expect(stepAnswer(played.step.operation, { status: 201, body: { choice_seq: 3 } }))
      .toEqual({ status: 201, code: null, choice_seq: 3 });
  });

  it('has words for every code the planner can block either step with', () => {
    for (const code of ['engine_takes_no_play', 'being_played', 'decided_from_outside', 'decider_not_allowed',
      'not_played', 'no_change']) {
      expect(actionSpec('beings.play').refusals?.[code]?.happened, code).toBeTruthy();
    }
  });
});

describe('everyone sent away and brought back, as a planned step', () => {
  it('goes to the presence route with the minute the plan read', () => {
    const away = request('free-send-away-plan');
    expect(PLAN_ACTIONS['send_away']).toBe('people.send-away');
    expect(PLAN_ACTIONS['bring_back']).toBe('people.bring-back');
    expect(away.request.actionId).toBe('people.send-away');
    expect(away.request.path).toBe(`/world/versions/${VERSION}/society/presence`);
    expect(away.request.body).toMatchObject({ presence: 'away', base_tick: 12 });
    expect(actionSpec('people.bring-back').operation).toBe(away.step.operation);
    // The route answers with the society as it stands; the read needs only that it succeeded.
    expect(stepAnswer(away.step.operation, { status: 200, body: { current_tick: 13 } })).toEqual({ status: 200, code: null });
  });

  it('has words for every name the presence route refuses by', () => {
    const names = [...readFileSync(`${repository}/exulanica/world/society_presence.py`, 'utf8')
      .slice(0, 4000).matchAll(/^ {8}"([a-z_]+)",$/gm)].map((match) => match[1]!);
    expect(names.length).toBe(5);
    for (const name of names) expect(actionSpec('people.send-away').refusals?.[name]?.happened, name).toBeTruthy();
  });
});

describe('each new step', () => {
  it('is a registry entry offered only as a plan step', () => {
    for (const name of ['free-move-thing-plan', 'free-remove-thing-plan', 'free-play-plan', 'free-give-back-plan',
      'free-send-away-plan']) {
      const entry = plannedEntry(plan(name).steps[0]!);
      if (!('spec' in entry)) throw new Error(`${name}: ${JSON.stringify(entry.refused)}`);
      expect(entry.spec.placement, name).toEqual(['companion']);
      expect(entry.spec.label.trim(), name).not.toBe('');
    }
  });
});
