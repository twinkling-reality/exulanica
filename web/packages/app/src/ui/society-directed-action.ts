/**
 * One browser control that issues an existing typed society directed-action and shows the record.
 *
 * Speaks SocietyClient.requestAction → POST /society/actions (`record_action`). Simulated
 * action requests stay labeled as simulation, never as personal evidence. v4 living societies
 * and missing selection surface an explicit unavailable state instead of inventing a memory.
 */

import { ApiError } from '@exulanica/graph-client';
import {
  type SocietyActionAffordance,
  type SocietyActionRecord,
  type SocietyClient,
  type SocietySnapshot,
} from '../society-api.js';
import { el } from './dom.js';

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
  // The browser society client materializes v2 purposeful state for directed actions. v3 is
  // accepted by the HTTP API but is not a held browser snapshot shape here; v4 living societies
  // refuse this control rather than inventing a different action kind.
  if (snapshot.state.profile !== 'exulanica-society/v2') {
    return {
      ok: false,
      reason: snapshot.state.profile === 'exulanica-society/v4'
        ? 'Directed actions require a v2 society. This world uses the living society profile.'
        : 'Directed actions require a v2 society.',
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
  const target = String(record.request.target['target_id'] ?? intent.target_id);
  const action = intent.kind === 'perform'
    ? `perform ${intent.affordance} at ${target}`
    : `go_to ${target}`;
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

export function describeSocietyActionFailure(error: unknown): string {
  if (error instanceof ApiError) {
    const prefix = `${error.code}: `;
    const detail = error.message.startsWith(prefix)
      ? error.message.slice(prefix.length)
      : error.message;
    if (error.status === 401 || error.status === 403) {
      return 'Directed action refused: sign in again to write this world.';
    }
    if (error.status === 424 || error.code === 'unavailable_society_input') {
      return `Directed action unavailable: ${detail}`;
    }
    if (error.status === 409 || error.code === 'invalid_society_action' || error.code === 'stale_society_state') {
      return `Directed action refused: ${detail}`;
    }
    return `Directed action unavailable (${error.code}): ${detail}`;
  }
  return error instanceof Error
    ? `Directed action unavailable. ${error.message}`
    : 'Directed action unavailable. The request failed.';
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
}): SocietyDirectedActionControl {
  const label = options.affordance === 'rest'
    ? 'Direct selected inhabitant to rest here'
    : 'Direct selected inhabitant to visit here';
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
    const gate = societyDirectedActionGate(options.getSnapshot(), options.getSubjectId());
    button.disabled = busy || !gate.ok;
    if (busy) return;
    if (outcome !== null && outcome.heldFor !== held()) outcome = null;
    if (!gate.ok) status.textContent = gate.reason;
    else {
      status.textContent = outcome?.text
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
      outcome = { heldFor, text: describeSocietyActionRecord(record) };
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
