/**
 * One browser control that issues an existing typed society directed-action and shows the record.
 *
 * Speaks SocietyClient.requestAction → POST /society/actions (`record_action`). Simulated
 * action requests stay labeled as simulation, never as personal evidence. v4 living societies
 * and missing selection surface an explicit unavailable state instead of inventing a memory.
 */

import { objectActivity } from '../society-activity-words.js';
import { ApiError } from '@exulanica/graph-client';
import { problemSentence } from './words/problems.js';
import {
  type SocietyActionAffordance,
  type SocietyActionRecord,
  type SocietyClient,
  type SocietySnapshot,
} from '../society-api.js';
import { el } from './dom.js';
import { societyEngine } from '../society-engines.js';

export type SocietyDirectedActionGate =
  | { readonly ok: true }
  | { readonly ok: false; readonly reason: string };

/** Whether the held society can accept a typed directed action for this inhabitant. */
export function societyDirectedActionGate(
  snapshot: SocietySnapshot | null,
  subjectId: string | null,
): SocietyDirectedActionGate {
  if (snapshot === null) {
    return { ok: false, reason: 'Connect a persisted society before requesting a directed action.' };
  }
  // Which engines take directed actions is the engine table's to say. The living society, and
  // any engine the table does not give them, refuses this control rather than inventing an
  // action kind it does not have.
  const engine = societyEngine(snapshot.state.profile);
  if (!engine.directedActions) {
    return {
      ok: false,
      reason: engine.stateFamily === 'living'
        ? 'Directed actions need a society that takes them. This world uses the living society profile.'
        : 'Directed actions need a society that takes them.',
    };
  }
  if (!subjectId) {
    return { ok: false, reason: 'Select a synthetic inhabitant before directing them to this place.' };
  }
  if (!snapshot.state.inhabitants.some((person) => person.id === subjectId)) {
    return { ok: false, reason: 'The selected inhabitant is not in the current society state.' };
  }
  return { ok: true };
}

/** Plain-language summary of a recorded action envelope. Never claims personal evidence. */
export function describeSocietyActionRecord(record: SocietyActionRecord): string {
  const intent = record.request.intent;
  const action = intent.kind === 'hands'
    ? `${intent.ability} ${intent.thing_id}${intent.with_id === null ? '' : ` with ${intent.with_id}`}`
    : intent.kind === 'perform'
      ? `perform ${intent.affordance} at ${String(record.request.target?.['target_id'] ?? intent.target_id)}`
      : `go_to ${String(record.request.target?.['target_id'] ?? intent.target_id)}`;
  if (record.status === 'pending') {
    return `Simulation action request recorded (${record.status}): ${action}. `
      + `Request ${record.request.requestId}. Digest ${record.request.documentSha256}. `
      + 'This is a synthetic society record, not personal evidence. Advance the society to consume it.';
  }
  const disposition = record.consumption?.disposition ?? 'unknown';
  return `Simulation action request ${record.status} (${disposition}): ${action}. `
    + `Request ${record.request.requestId}. Digest ${record.request.documentSha256}. `
    + 'This is a synthetic society record, not personal evidence.';
}

/**
 * Words for each name the server refuses a directed request by, or finds it stale by: exactly
 * `ACTION_REFUSALS` in exulanica/world/society_actions.py, held to it by
 * code-words-parity.test.ts.
 */
export const REFUSAL_WORDS: Readonly<Record<string, string>> = {
  action_context_changed: 'The world changed since you asked. Look again, then ask again.',
  canonical_target_changed: 'That place changed since you chose it. Choose it again.',
  decided_from_outside: 'This visitor came from another program, which decides what it does; it cannot be sent anywhere from here.',
  destination_full: 'Every place there is taken. Ask again when someone leaves.',
  inhabitant_action_in_progress: 'They are in the middle of something and cannot be asked yet.',
  inhabitant_already_there: 'They are already there, using it now.',
  target_unreachable: 'They cannot reach that place from where they are.',
  unknown_inhabitant: 'That inhabitant is not in this world any more.',
  act_not_offered: 'They cannot do that: it is out of their reach, or their hands or the thing do not allow it.',
  thing_gone: 'That is not here any more.',
  out_of_reach: 'They could not get close enough to do it.',
  belongs_to_visitor: 'That belongs to a visitor. Only they can give it away.',
};

export function describeSocietyActionFailure(error: unknown): string {
  if (error instanceof ApiError) {
    const prefix = `${error.code}: `;
    const detail = error.message.startsWith(prefix)
      ? error.message.slice(prefix.length)
      : error.message;
    if (error.status === 401 || error.status === 403) {
      return 'Nothing was asked: this session may not change this world. Sign in again.';
    }
    if (error.status === 424 || error.code === 'unavailable_society_input') {
      return 'Nothing was asked: the people of this world cannot be read right now. Try again in a moment.';
    }
    if (error.status === 409 || error.code === 'invalid_society_action' || error.code === 'stale_society_state') {
      // The refusal's own name is in the detail; a name with no words gets the general sentence.
      return REFUSAL_WORDS[detail] ?? 'Nothing was asked: the world changed. Look again, then ask again.';
    }
    if (error.code === 'engine_takes_no_directed_actions') {
      return 'People in this kind of world choose for themselves; they cannot be asked to go somewhere.';
    }
  }
  return problemSentence(error, {}, {
    happened: 'Nothing was asked.',
    next: 'Try again in a moment.',
  });
}

export interface SocietyDirectedActionControl {
  readonly root: HTMLElement;
  readonly button: HTMLButtonElement;
  readonly status: HTMLParagraphElement;
  /**
   * Re-gate against the current society and selected inhabitant. Call it whenever either may
   * have changed. A returned record or refusal stays shown while the same society and
   * inhabitant are held, and is dropped when either changes.
   */
  reflect(): void;
  issue(): Promise<SocietyActionRecord | null>;
}

type ActionPort = Pick<SocietyClient, 'requestAction'>;

/**
 * Mount the existing destination affordance as a directed-action control for one canonical target.
 * The button issues `perform` with the declared visit/rest affordance.
 */
export function buildSocietyDirectedAction(options: {
  readonly client: ActionPort;
  readonly getSnapshot: () => SocietySnapshot | null;
  readonly getSubjectId: () => string | null;
  readonly targetId: string;
  readonly affordance: SocietyActionAffordance;
  readonly onRecord?: (record: SocietyActionRecord) => void;
  /** The button's words, when the place has a name a person knows it by. */
  readonly label?: string;
  /** How a returned record is said. The full simulation record when omitted. */
  readonly describeRecord?: (record: SocietyActionRecord) => string;
  /** What the status says while the control is available and nothing has been asked yet. */
  readonly idleText?: string;
  /**
   * Why the world's capability descriptor refuses directed actions now, in words, or null when it
   * does not. Read on every reflect; a refusal disables the control and is said in its status.
   */
  readonly serverGate?: () => string | null;
}): SocietyDirectedActionControl {
  const label = options.label ?? objectActivity(options.affordance).directDefault;
  const describe = options.describeRecord ?? describeSocietyActionRecord;
  const button = el('button', { type: 'button', text: label }) as HTMLButtonElement;
  const status = el('p', {
    role: 'status',
    'aria-live': 'polite',
    class: 'society-directed-action-status',
    text: 'Simulation directed actions stay separate from personal evidence.',
  });
  const root = el('div', { class: 'society-directed-action' }, [button, status]);
  let busy = false;
  // The last result, and the society and inhabitant it was for.
  let outcome: { readonly heldFor: string; readonly text: string } | null = null;
  const held = (): string =>
    `${options.getSnapshot()?.societyId ?? ''}:${options.getSubjectId() ?? ''}`;

  const reflect = (): void => {
    const local = societyDirectedActionGate(options.getSnapshot(), options.getSubjectId());
    const refused = options.serverGate?.() ?? null;
    const gate = refused !== null ? { ok: false as const, reason: refused } : local;
    button.disabled = busy || !gate.ok;
    if (busy) return;
    if (outcome !== null && outcome.heldFor !== held()) outcome = null;
    if (!gate.ok) status.textContent = gate.reason;
    else {
      status.textContent = outcome?.text
        ?? options.idleText
        ?? 'Issues one typed perform request to the society action API. '
          + 'The returned record is a synthetic simulation event, not personal evidence.';
    }
  };

  const issue = async (): Promise<SocietyActionRecord | null> => {
    const snapshot = options.getSnapshot();
    const subjectId = options.getSubjectId();
    const gate = societyDirectedActionGate(snapshot, subjectId);
    if (!gate.ok || snapshot === null || subjectId === null) {
      status.textContent = gate.ok ? 'Directed action unavailable.' : gate.reason;
      reflect();
      return null;
    }
    const heldFor = held();
    busy = true;
    reflect();
    status.textContent = 'Recording simulation directed action…';
    try {
      const record = await options.client.requestAction(snapshot, subjectId, {
        kind: 'perform',
        targetId: options.targetId,
        affordance: options.affordance,
      });
      outcome = { heldFor, text: describe(record) };
      options.onRecord?.(record);
      return record;
    } catch (error) {
      outcome = { heldFor, text: describeSocietyActionFailure(error) };
      return null;
    } finally {
      busy = false;
      reflect();
    }
  };

  button.addEventListener('click', () => { void issue(); });
  reflect();
  return { root, button, status, reflect, issue };
}
